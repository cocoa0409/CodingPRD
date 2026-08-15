"""RosterRow endpoints (PRD §3.2, §3.3)."""

from flask import Blueprint, request

from db import DB
from errors import ApiError, not_found, invalid_state, invalid_request
from errors import ERR_PROVIDER_NOT_LINKABLE
from middleware import require_roles, json_body
from response import success_object, paginate
from services.common import new_common, touch, require_string

bp = Blueprint("roster_rows", __name__)

REJECT_REASONS = {
    "MALFORMED_NPI", "MALFORMED_TIN", "MISSING_LOCATION",
    "DUPLICATE_IN_FILE", "SOURCE_RETIRED",
}


def _public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _get_row(rid):
    row = DB.roster_rows.get(rid)
    if row is None:
        raise not_found()
    return row


@bp.route("/pdm/roster-rows/<rid>", methods=["GET"])
def get_row(rid):
    require_roles("DataSteward", "IntakeOperator")
    return success_object(_public(_get_row(rid)))


@bp.route("/pdm/roster-rows", methods=["GET"])
def list_rows():
    require_roles("DataSteward", "IntakeOperator")
    items = list(DB.roster_rows.values())
    rf = request.args.get("roster_file_id")
    rp = request.args.get("resolved_provider_id")
    status = request.args.get("status")
    if rf is not None:
        items = [r for r in items if r["roster_file_id"] == rf]
    if rp is not None:
        items = [r for r in items if r.get("resolved_provider_id") == rp]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate([_public(r) for r in items], request.args)


def _create_manual_alias(row, provider_id):
    alias = {
        **new_common(),
        "provider_id": provider_id,
        "alias_npi": row.get("npi", ""),
        "alias_tin": row.get("tin", ""),
        "alias_location_key": row.get("location_key", ""),
        "match_confidence": 100,
        "link_kind": "MANUAL",
        "status": "ACTIVE",
    }
    DB.provider_aliases[alias["id"]] = alias


@bp.route("/pdm/roster-rows/<rid>/link", methods=["POST"])
def link_row(rid):
    require_roles("DataSteward")
    row = _get_row(rid)
    if row["status"] not in ("PENDING", "CONFLICT"):
        raise invalid_state()
    body = json_body()
    provider_id = require_string(body, "provider_id")
    provider = DB.providers.get(provider_id)
    if provider is None:
        raise not_found("provider_id does not exist")
    if provider["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_PROVIDER_NOT_LINKABLE, 409,
                       "Target provider not ACTIVE for link")
    row["status"] = "MATCHED"
    row["resolved_provider_id"] = provider_id
    row["_winning_link_kind"] = "MANUAL"
    row["_winning_match_score"] = 100
    touch(row)
    _create_manual_alias(row, provider_id)
    return success_object(_public(row))


@bp.route("/pdm/roster-rows/<rid>/spawn-new", methods=["POST"])
def spawn_new(rid):
    require_roles("DataSteward")
    row = _get_row(rid)
    if row["status"] != "CONFLICT":
        raise invalid_state()
    row["status"] = "NEW_PROVIDER"
    touch(row)
    return success_object(_public(row))


@bp.route("/pdm/roster-rows/<rid>/reject", methods=["POST"])
def reject_row(rid):
    require_roles("IntakeOperator")
    row = _get_row(rid)
    if row["status"] != "PENDING":
        raise invalid_state()
    body = json_body()
    reason = require_string(body, "reject_reason")
    if reason not in REJECT_REASONS:
        raise invalid_request("reject_reason must be one of "
                              "MALFORMED_NPI, MALFORMED_TIN, MISSING_LOCATION, "
                              "DUPLICATE_IN_FILE, SOURCE_RETIRED")
    row["status"] = "REJECTED"
    row["reject_reason"] = reason
    touch(row)
    f = DB.roster_files.get(row["roster_file_id"])
    if f is not None:
        f["rejected_row_count"] = sum(
            1 for r in DB.roster_rows.values()
            if r["roster_file_id"] == f["id"] and r["status"] == "REJECTED"
        )
        touch(f)
    return success_object(_public(row))
