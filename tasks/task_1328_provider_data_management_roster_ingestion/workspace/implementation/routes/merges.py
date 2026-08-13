"""ProviderMergeRecord endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import DB, CLOCK, iso_ts
from errors import ApiError, not_found, invalid_state, invalid_request
from errors import ERR_STALE_VERSION, ERR_PROVIDER_NOT_LINKABLE, ERR_MERGE_SELF
from middleware import require_roles, json_body
from response import success_object, paginate
from services.common import new_ledger, touch, require_string
from services.quality import run_quality_scoring

bp = Blueprint("merges", __name__)


def _get_provider(pid):
    p = DB.providers.get(pid)
    if p is None:
        raise not_found()
    return p


@bp.route("/pdm/provider-merges", methods=["POST"])
def create_merge():
    _role, user_id = require_roles("DataSteward")
    body = json_body()
    survivor_id = require_string(body, "survivor_provider_id")
    merged_id = require_string(body, "merged_provider_id")
    rationale = require_string(body, "rationale")
    expected = body.get("expected_provider_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("expected_provider_version is required")

    survivor = _get_provider(survivor_id)
    merged = _get_provider(merged_id)
    # Guard order per PRD §3.6: survivor ACTIVE (state), stale version,
    # merged ACTIVE (linkable), distinct parties.
    if survivor["lifecycle_status"] != "ACTIVE":
        raise invalid_state("Survivor provider not ACTIVE")
    if expected != merged["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_provider_version does not match the merged "
                       "provider's current version")
    if merged["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_PROVIDER_NOT_LINKABLE, 409,
                       "Merged provider not ACTIVE")
    if survivor_id == merged_id:
        raise ApiError(ERR_MERGE_SELF, 422,
                       "survivor_provider_id equals merged_provider_id")

    record = {
        **new_ledger(),
        "survivor_provider_id": survivor_id,
        "merged_provider_id": merged_id,
        "decided_by_user_id": user_id,
        "decided_at": iso_ts(CLOCK.now()),
        "rationale": rationale,
    }
    DB.provider_merge_records[record["id"]] = record

    # Rewire attributes to the survivor.
    for a in DB.provider_attributes.values():
        if a["provider_id"] == merged_id:
            a["provider_id"] = survivor_id
            touch(a)
    # Aliases re-point to the survivor.
    for a in DB.provider_aliases.values():
        if a["provider_id"] == merged_id:
            a["provider_id"] = survivor_id
            touch(a)
    # Open conflicts transfer to the survivor.
    for c in DB.attribute_conflicts.values():
        if c["provider_id"] == merged_id and c["status"] in ("OPEN", "ESCALATED"):
            c["provider_id"] = survivor_id
            touch(c)
    # Attestation requests in DRAFT/SENT withdraw.
    for r in DB.attestation_requests.values():
        if r["provider_id"] == merged_id and r["status"] in ("DRAFT", "SENT"):
            r["status"] = "WITHDRAWN"
            touch(r)

    merged["lifecycle_status"] = "MERGED"
    merged["merged_into_provider_id"] = survivor_id
    touch(merged)

    run_quality_scoring(survivor_id)
    return success_object(record, status=201)


@bp.route("/pdm/provider-merges", methods=["GET"])
def list_merges():
    require_roles("DataSteward")
    items = list(DB.provider_merge_records.values())
    sid = request.args.get("survivor_provider_id")
    mid = request.args.get("merged_provider_id")
    if sid is not None:
        items = [m for m in items if m["survivor_provider_id"] == sid]
    if mid is not None:
        items = [m for m in items if m["merged_provider_id"] == mid]
    return paginate(items, request.args)


@bp.route("/pdm/provider-merges/<mid>", methods=["GET"])
def get_merge(mid):
    require_roles("DataSteward")
    rec = DB.provider_merge_records.get(mid)
    if rec is None:
        raise not_found()
    return success_object(rec)
