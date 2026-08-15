"""DistributionTarget and DistributionBatch endpoints (PRD §3.9)."""

import hashlib

from flask import Blueprint, request

from db import DB, CLOCK
from errors import ApiError, not_found, invalid_state, invalid_request
from errors import ERR_BATCH_INFLIGHT, ERR_TARGET_DISABLED
from middleware import require_roles, json_body, optional_json_body
from response import success_object, paginate
from services.common import (
    new_common, new_ledger, touch, require_string, require_int, require_enum,
)
from services.quality import directory_strict_score

bp = Blueprint("distribution", __name__)

TARGET_CODES = {"CLAIMS", "DIRECTORY", "NETWORK"}
CHANGE_RANK = {"ADD": 0, "UPDATE": 1, "TERM": 2, "QUALITY_DROP_EXCLUDED": 3}


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _get_target(tid):
    t = DB.distribution_targets.get(tid)
    if t is None:
        raise not_found()
    return t


def _get_batch(bid):
    b = DB.distribution_batches.get(bid)
    if b is None:
        raise not_found()
    return b


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

@bp.route("/pdm/distribution-targets", methods=["POST"])
def create_target():
    require_roles("DistributionOperator")
    body = json_body()
    target_code = require_enum(body, "target_code", TARGET_CODES)
    endpoint_uri = require_string(body, "endpoint_uri")
    floor = require_int(body, "required_quality_floor", minimum=0, maximum=100)
    rec = {
        **new_common(),
        "target_code": target_code,
        "endpoint_uri": endpoint_uri,
        "required_quality_floor": floor,
        "status": "ACTIVE",
    }
    DB.distribution_targets[rec["id"]] = rec
    return success_object(_public(rec), status=201)


@bp.route("/pdm/distribution-targets", methods=["GET"])
def list_targets():
    require_roles("DataSteward", "DistributionOperator")
    items = list(DB.distribution_targets.values())
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return paginate([_public(t) for t in items], request.args)


@bp.route("/pdm/distribution-targets/<tid>/disable", methods=["POST"])
def disable_target(tid):
    require_roles("DistributionOperator")
    t = _get_target(tid)
    if t["status"] != "ACTIVE":
        raise invalid_state()
    t["status"] = "DISABLED"
    touch(t)
    return success_object(_public(t))


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

@bp.route("/pdm/distribution-batches", methods=["POST"])
def create_batch():
    require_roles("DistributionOperator")
    body = json_body()
    target_id = require_string(body, "distribution_target_id")
    _get_target(target_id)
    retry_of = body.get("retry_of_batch_id")
    if retry_of is not None:
        if not isinstance(retry_of, str):
            raise invalid_request("retry_of_batch_id must be a string")
        old = DB.distribution_batches.get(retry_of)
        if old is None:
            raise not_found("retry_of_batch_id does not exist")
        if old["status"] == "FAILED":
            old["status"] = "SUPERSEDED"
            touch(old)
    rec = {
        **new_common(),
        "distribution_target_id": target_id,
        "snapshot_cutoff_at": CLOCK.now_iso(),
        "provider_count": 0,
        "status": "BUILDING",
        "failure_reason": None,
        "retry_of_batch_id": retry_of,
    }
    DB.distribution_batches[rec["id"]] = rec
    return success_object(_public(rec), status=201)


@bp.route("/pdm/distribution-batches", methods=["GET"])
def list_batches():
    require_roles("DataSteward", "DistributionOperator")
    items = list(DB.distribution_batches.values())
    tid = request.args.get("distribution_target_id")
    status = request.args.get("status")
    retry = request.args.get("retry_of_batch_id")
    if tid is not None:
        items = [b for b in items if b["distribution_target_id"] == tid]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if retry is not None:
        items = [b for b in items if b.get("retry_of_batch_id") == retry]
    return paginate([_public(b) for b in items], request.args)


@bp.route("/pdm/distribution-batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_roles("DataSteward", "DistributionOperator")
    return success_object(_public(_get_batch(bid)))


@bp.route("/pdm/distribution-batches/<bid>/items", methods=["GET"])
def list_batch_items(bid):
    require_roles("DataSteward", "DistributionOperator")
    _get_batch(bid)
    items = [i for i in DB.distribution_items.values()
             if i["distribution_batch_id"] == bid]
    ck = request.args.get("change_kind")
    if ck is not None:
        items = [i for i in items if i["change_kind"] == ck]
    return paginate(items, request.args)


def _payload_hash(provider):
    base = "|".join([
        provider["npi"], provider["tin"], provider["location_key"],
        str(provider.get("current_quality_score", 0)),
    ])
    return hashlib.sha256(base.encode()).hexdigest()


def _latest_acked_baseline(target_id):
    acked = [
        b for b in DB.distribution_batches.values()
        if b["distribution_target_id"] == target_id and b["status"] == "ACKED"
    ]
    if not acked:
        return None
    acked.sort(key=lambda b: (b["created_at"], b["id"]))
    return acked[-1]


@bp.route("/pdm/distribution-batches/<bid>/publish", methods=["POST"])
def publish_batch(bid):
    require_roles("DistributionOperator")
    b = _get_batch(bid)
    if b["status"] != "BUILDING":
        raise invalid_state()
    target_id = b["distribution_target_id"]
    # Guards in order: inflight batch first, then target ACTIVE.
    for other in DB.distribution_batches.values():
        if other["id"] != bid and other["distribution_target_id"] == target_id \
                and other["status"] in ("BUILDING", "PUBLISHED"):
            raise ApiError(ERR_BATCH_INFLIGHT, 409,
                           "Another batch for the same target is BUILDING or PUBLISHED")
    target = _get_target(target_id)
    if target["status"] != "ACTIVE":
        raise ApiError(ERR_TARGET_DISABLED, 409, "DistributionTarget is DISABLED")

    floor = target["required_quality_floor"]
    is_directory = target["target_code"] == "DIRECTORY"

    baseline = _latest_acked_baseline(target_id)
    baseline_items = {}
    if baseline is not None:
        for it in DB.distribution_items.values():
            if it["distribution_batch_id"] == baseline["id"] \
                    and it["change_kind"] != "QUALITY_DROP_EXCLUDED":
                baseline_items[it["provider_id"]] = it

    def eligible_score(p):
        if is_directory:
            return directory_strict_score(p["id"])
        return p.get("current_quality_score", 0)

    # Classify each provider.
    new_items = []
    for p in DB.providers.values():
        base_item = baseline_items.get(p["id"])
        eligible_now = (
            p["lifecycle_status"] == "ACTIVE" and eligible_score(p) >= floor
        )
        if base_item is None:
            if eligible_now:
                change = "ADD"
            else:
                continue
        else:
            if p["lifecycle_status"] in ("TERMINATED", "MERGED"):
                change = "TERM"
            elif eligible_now and _payload_hash(p) != base_item["payload_hash"]:
                change = "UPDATE"
            elif not eligible_now and p["lifecycle_status"] == "ACTIVE":
                change = "QUALITY_DROP_EXCLUDED"
            else:
                continue
        new_items.append((change, p))

    # Ordering: change_kind rank, then npi ASC, then provider created_at ASC.
    new_items.sort(key=lambda t: (
        CHANGE_RANK[t[0]], t[1]["npi"], t[1]["created_at"]
    ))
    for change, p in new_items:
        item = {
            **new_ledger(),
            "distribution_batch_id": bid,
            "provider_id": p["id"],
            "change_kind": change,
            "payload_hash": _payload_hash(p),
        }
        DB.distribution_items[item["id"]] = item
    b["provider_count"] = len(new_items)
    b["status"] = "PUBLISHED"
    touch(b)
    return success_object(_public(b))


@bp.route("/pdm/distribution-batches/<bid>/ack", methods=["POST"])
def ack_batch(bid):
    require_roles("DistributionOperator")
    b = _get_batch(bid)
    if b["status"] != "PUBLISHED":
        raise invalid_state()
    b["status"] = "ACKED"
    touch(b)
    return success_object(_public(b))


@bp.route("/pdm/distribution-batches/<bid>/fail", methods=["POST"])
def fail_batch(bid):
    require_roles("DistributionOperator")
    b = _get_batch(bid)
    if b["status"] != "PUBLISHED":
        raise invalid_state()
    body = json_body()
    reason = body.get("failure_reason")
    if not isinstance(reason, str) or not reason:
        raise invalid_request("failure_reason is required")
    b["failure_reason"] = reason
    b["status"] = "FAILED"
    touch(b)
    return success_object(_public(b))


@bp.route("/pdm/distribution-batches/<bid>/discard", methods=["POST"])
def discard_batch(bid):
    require_roles("DistributionOperator")
    b = _get_batch(bid)
    if b["status"] != "BUILDING":
        raise invalid_state()
    b["status"] = "SUPERSEDED"
    touch(b)
    return success_object(_public(b))
