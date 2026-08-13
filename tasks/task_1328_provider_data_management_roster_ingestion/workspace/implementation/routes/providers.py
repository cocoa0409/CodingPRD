"""Provider endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import DB, CLOCK
from errors import ApiError, not_found, invalid_state, invalid_request
from errors import (
    ERR_QUALITY_FLOOR_NOT_MET, ERR_OPEN_ATTESTATION_EXISTS,
)
from middleware import require_roles, json_body
from response import success_object, paginate
from services.common import new_common, touch, require_string, parse_iso_date
from services.quality import run_quality_scoring

bp = Blueprint("providers", __name__)


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _get_provider(pid):
    p = DB.providers.get(pid)
    if p is None:
        raise not_found()
    return p


@bp.route("/pdm/providers", methods=["POST"])
def create_provider():
    require_roles("DataSteward")
    body = json_body()
    npi = require_string(body, "npi")
    tin = require_string(body, "tin")
    location_key = require_string(body, "location_key")
    # npi unique across all non-MERGED providers; the triple is unique.
    for p in DB.providers.values():
        if p["lifecycle_status"] != "MERGED" and p["npi"] == npi:
            raise invalid_request("npi must be unique across non-MERGED providers")
        if (p["npi"] == npi and p["tin"] == tin
                and p["location_key"] == location_key):
            raise invalid_request("The (npi, tin, location_key) triple must be unique")
    rec = {
        **new_common(),
        "npi": npi,
        "tin": tin,
        "location_key": location_key,
        "lifecycle_status": "ACTIVE",
        "merged_into_provider_id": None,
        "current_quality_score": 0,
        "staleness_flag": False,
        "last_roster_file_id": None,
    }
    DB.providers[rec["id"]] = rec
    run_quality_scoring(rec["id"])
    return success_object(_public(rec), status=201)


@bp.route("/pdm/providers", methods=["GET"])
def list_providers():
    require_roles("DataSteward", "IntakeOperator", "DistributionOperator", "ProviderContact")
    items = list(DB.providers.values())
    ls = request.args.get("lifecycle_status")
    npi = request.args.get("npi")
    tin = request.args.get("tin")
    staleness = request.args.get("staleness_flag")
    min_qs = request.args.get("min_quality_score")
    merged_into = request.args.get("merged_into_provider_id")
    last_file = request.args.get("last_roster_file_id")
    if ls is not None:
        items = [p for p in items if p["lifecycle_status"] == ls]
    if npi is not None:
        items = [p for p in items if p["npi"] == npi]
    if tin is not None:
        items = [p for p in items if p["tin"] == tin]
    if staleness is not None:
        want = staleness.lower() == "true"
        items = [p for p in items if bool(p.get("staleness_flag")) == want]
    if min_qs is not None:
        try:
            threshold = int(min_qs)
        except ValueError:
            raise invalid_request("min_quality_score must be an integer")
        items = [p for p in items if p.get("current_quality_score", 0) >= threshold]
    if merged_into is not None:
        items = [p for p in items if p.get("merged_into_provider_id") == merged_into]
    if last_file is not None:
        items = [p for p in items if p.get("last_roster_file_id") == last_file]
    return paginate([_public(p) for p in items], request.args)


@bp.route("/pdm/providers/<pid>", methods=["GET"])
def get_provider(pid):
    require_roles("DataSteward", "IntakeOperator", "DistributionOperator", "ProviderContact")
    return success_object(_public(_get_provider(pid)))


@bp.route("/pdm/providers/<pid>/suspend", methods=["POST"])
def suspend_provider(pid):
    require_roles("DataSteward")
    p = _get_provider(pid)
    if p["lifecycle_status"] != "ACTIVE":
        raise invalid_state()
    p["lifecycle_status"] = "SUSPENDED"
    touch(p)
    for r in DB.attestation_requests.values():
        if r["provider_id"] == pid and r["status"] == "SENT":
            r["status"] = "WITHDRAWN"
            touch(r)
    return success_object(_public(p))


@bp.route("/pdm/providers/<pid>/reinstate", methods=["POST"])
def reinstate_provider(pid):
    require_roles("DataSteward")
    p = _get_provider(pid)
    if p["lifecycle_status"] != "SUSPENDED":
        raise invalid_state()
    floors = [
        t["required_quality_floor"]
        for t in DB.distribution_targets.values() if t["status"] == "ACTIVE"
    ]
    if floors:
        min_floor = min(floors)
        if p.get("current_quality_score", 0) < min_floor:
            raise ApiError(ERR_QUALITY_FLOOR_NOT_MET, 409,
                           "Reinstate blocked: quality score below the minimum "
                           "ACTIVE target floor")
    p["lifecycle_status"] = "ACTIVE"
    touch(p)
    return success_object(_public(p))


@bp.route("/pdm/providers/<pid>/terminate", methods=["POST"])
def terminate_provider(pid):
    require_roles("DataSteward")
    p = _get_provider(pid)
    if p["lifecycle_status"] != "ACTIVE":
        raise invalid_state()
    if any(
        r["provider_id"] == pid and r["status"] == "SENT"
        for r in DB.attestation_requests.values()
    ):
        raise ApiError(ERR_OPEN_ATTESTATION_EXISTS, 409,
                       "Terminate blocked by a SENT attestation request")
    today = CLOCK.today()
    for a in DB.provider_attributes.values():
        if a["provider_id"] == pid and a.get("term_date") is None \
                and a["status"] in ("ACTIVE", "PENDING", "RETRO_PENDING"):
            a["term_date"] = today
            touch(a)
    for c in DB.attribute_conflicts.values():
        if c["provider_id"] == pid and c["status"] == "OPEN":
            c["status"] = "RESOLVED"
            c["resolution"] = "KEEP_INCUMBENT"
            c["resolution_reason"] = "provider terminated"
            touch(c)
    p["lifecycle_status"] = "TERMINATED"
    touch(p)
    return success_object(_public(p))


@bp.route("/pdm/providers/<pid>/distribution-items", methods=["GET"])
def provider_distribution_items(pid):
    require_roles("DataSteward", "DistributionOperator")
    _get_provider(pid)
    items = [i for i in DB.distribution_items.values() if i["provider_id"] == pid]
    ck = request.args.get("change_kind")
    if ck is not None:
        items = [i for i in items if i["change_kind"] == ck]
    return paginate(items, request.args)


@bp.route("/pdm/providers/<pid>/attestation-requests", methods=["GET"])
def provider_attestation_requests(pid):
    require_roles("DataSteward", "ProviderContact")
    _get_provider(pid)
    items = [r for r in DB.attestation_requests.values() if r["provider_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    for r in items:
        r.pop("_registrant_user_id", None)
    return paginate([_public(r) for r in items], request.args)


@bp.route("/pdm/providers/<pid>/merge-records", methods=["GET"])
def provider_merge_records(pid):
    require_roles("DataSteward")
    _get_provider(pid)
    items = [
        m for m in DB.provider_merge_records.values()
        if m["survivor_provider_id"] == pid or m["merged_provider_id"] == pid
    ]
    return paginate(items, request.args)
