"""RosterSource endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import DB
from errors import ApiError, not_found, invalid_state, invalid_request
from errors import ERR_PRECEDENCE_RANK_CONFLICT, ERR_SOURCE_HAS_INFLIGHT_FILE
from middleware import require_roles, json_body
from response import success_object, paginate
from services.common import (
    new_common, touch, require_string, require_int, require_enum,
)

bp = Blueprint("roster_sources", __name__)

FORMATS = {"CSV", "XLSX", "JSON", "FHIR", "FIXED_WIDTH"}
INFLIGHT_FILE_STATES = {"RECEIVED", "PARSED", "NORMALIZED", "VALIDATED"}


def _rank_conflict(precedence_rank, exclude_id=None):
    for s in DB.roster_sources.values():
        if s["id"] == exclude_id:
            continue
        if s["status"] != "RETIRED" and s["precedence_rank"] == precedence_rank:
            return True
    return False


def _public(src):
    return {k: v for k, v in src.items() if not k.startswith("_")}


@bp.route("/pdm/roster-sources", methods=["POST"])
def create_source():
    require_roles("DataSteward")
    body = json_body()
    source_code = require_string(body, "source_code")
    display_name = require_string(body, "display_name")
    fmt = require_enum(body, "format", FORMATS)
    precedence_rank = require_int(body, "precedence_rank")
    freshness_sla_days = require_int(body, "freshness_sla_days", minimum=1)
    default_campaign = body.get("default_attestation_campaign_id")
    if default_campaign is not None and not isinstance(default_campaign, str):
        raise invalid_request("default_attestation_campaign_id must be a string")
    if _rank_conflict(precedence_rank):
        raise ApiError(ERR_PRECEDENCE_RANK_CONFLICT, 409,
                       "precedence_rank duplicates another non-RETIRED source")
    rec = {
        **new_common(),
        "source_code": source_code,
        "display_name": display_name,
        "format": fmt,
        "precedence_rank": precedence_rank,
        "freshness_sla_days": freshness_sla_days,
        "status": "ACTIVE",
        "default_attestation_campaign_id": default_campaign,
    }
    DB.roster_sources[rec["id"]] = rec
    return success_object(_public(rec), status=201)


@bp.route("/pdm/roster-sources", methods=["GET"])
def list_sources():
    require_roles("DataSteward", "IntakeOperator", "DistributionOperator", "ProviderContact")
    items = list(DB.roster_sources.values())
    status = request.args.get("status")
    fmt = request.args.get("format")
    dac = request.args.get("default_attestation_campaign_id")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if fmt is not None:
        items = [s for s in items if s["format"] == fmt]
    if dac is not None:
        items = [s for s in items if s.get("default_attestation_campaign_id") == dac]
    return paginate([_public(s) for s in items], request.args)


@bp.route("/pdm/roster-sources/<sid>", methods=["GET"])
def get_source(sid):
    require_roles("DataSteward", "IntakeOperator", "DistributionOperator")
    src = DB.roster_sources.get(sid)
    if src is None:
        raise not_found()
    return success_object(_public(src))


@bp.route("/pdm/roster-sources/<sid>", methods=["PATCH"])
def patch_source(sid):
    require_roles("DataSteward")
    src = DB.roster_sources.get(sid)
    if src is None:
        raise not_found()
    body = json_body()
    allowed = {"precedence_rank", "freshness_sla_days", "display_name",
               "default_attestation_campaign_id"}
    for k in body:
        if k not in allowed:
            raise invalid_request(f"Field {k} is not mutable")
    if "precedence_rank" in body:
        v = body["precedence_rank"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise invalid_request("precedence_rank must be an integer")
        if _rank_conflict(v, exclude_id=sid):
            raise ApiError(ERR_PRECEDENCE_RANK_CONFLICT, 409,
                           "precedence_rank duplicates another non-RETIRED source")
        src["precedence_rank"] = v
    if "freshness_sla_days" in body:
        v = body["freshness_sla_days"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise invalid_request("freshness_sla_days must be an integer >= 1")
        src["freshness_sla_days"] = v
    if "display_name" in body:
        v = body["display_name"]
        if not isinstance(v, str) or not v:
            raise invalid_request("display_name must be a non-empty string")
        src["display_name"] = v
    if "default_attestation_campaign_id" in body:
        v = body["default_attestation_campaign_id"]
        if v is not None and not isinstance(v, str):
            raise invalid_request("default_attestation_campaign_id must be a string")
        src["default_attestation_campaign_id"] = v
    touch(src)
    return success_object(_public(src))


def _has_inflight_files(sid):
    return any(
        f["roster_source_id"] == sid and f["status"] in INFLIGHT_FILE_STATES
        for f in DB.roster_files.values()
    )


@bp.route("/pdm/roster-sources/<sid>/suspend", methods=["POST"])
def suspend_source(sid):
    require_roles("DataSteward")
    src = DB.roster_sources.get(sid)
    if src is None:
        raise not_found()
    if src["status"] != "ACTIVE":
        raise invalid_state()
    if _has_inflight_files(sid):
        raise ApiError(ERR_SOURCE_HAS_INFLIGHT_FILE, 409,
                       "Suspend blocked by inflight files")
    src["status"] = "SUSPENDED"
    touch(src)
    return success_object(_public(src))


@bp.route("/pdm/roster-sources/<sid>/resume", methods=["POST"])
def resume_source(sid):
    require_roles("DataSteward")
    src = DB.roster_sources.get(sid)
    if src is None:
        raise not_found()
    if src["status"] != "SUSPENDED":
        raise invalid_state()
    src["status"] = "ACTIVE"
    touch(src)
    return success_object(_public(src))


@bp.route("/pdm/roster-sources/<sid>/retire", methods=["POST"])
def retire_source(sid):
    require_roles("DataSteward")
    src = DB.roster_sources.get(sid)
    if src is None:
        raise not_found()
    if src["status"] != "ACTIVE":
        raise invalid_state()
    if _has_inflight_files(sid):
        raise ApiError(ERR_SOURCE_HAS_INFLIGHT_FILE, 409,
                       "Retire blocked by inflight files")
    src["status"] = "RETIRED"
    touch(src)
    return success_object(_public(src))
