"""AttributeConflict endpoints (PRD §3.5)."""

from flask import Blueprint, request

from db import DB, CLOCK
from errors import ApiError, not_found, invalid_state, invalid_request
from errors import (
    ERR_SOD_ADJUDICATOR, ERR_MERGE_VALUE_REQUIRED,
    ERR_PRECEDENCE_TIE_NOT_ESCALATABLE,
)
from middleware import require_roles, json_body
from response import success_object, paginate
from services.common import new_common, touch, require_enum
from services.quality import run_quality_scoring

bp = Blueprint("attribute_conflicts", __name__)

RESOLUTIONS = {"KEEP_INCUMBENT", "ACCEPT_CHALLENGER", "MERGE_VALUES"}


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _get_conflict(cid):
    c = DB.attribute_conflicts.get(cid)
    if c is None:
        raise not_found()
    return c


@bp.route("/pdm/attribute-conflicts", methods=["GET"])
def list_conflicts():
    require_roles("DataSteward")
    items = list(DB.attribute_conflicts.values())
    for param, field in (
        ("provider_id", "provider_id"),
        ("status", "status"),
        ("incumbent_attribute_id", "incumbent_attribute_id"),
        ("challenger_attribute_id", "challenger_attribute_id"),
        ("incumbent_source_id", "incumbent_source_id"),
        ("challenger_source_id", "challenger_source_id"),
    ):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(field) == v]
    return paginate([_public(c) for c in items], request.args)


@bp.route("/pdm/attribute-conflicts/<cid>", methods=["GET"])
def get_conflict(cid):
    require_roles("DataSteward")
    return success_object(_public(_get_conflict(cid)))


@bp.route("/pdm/attribute-conflicts/<cid>/resolve", methods=["POST"])
def resolve_conflict(cid):
    _role, user_id = require_roles("DataSteward")
    c = _get_conflict(cid)
    if c["status"] not in ("OPEN", "ESCALATED"):
        raise invalid_state()
    # SoD: adjudicator must not be the operator who committed the challenger file.
    challenger_committer = c.get("_challenger_committer_user_id")
    if challenger_committer is not None and user_id == challenger_committer:
        raise ApiError(ERR_SOD_ADJUDICATOR, 403,
                       "Conflict resolution attempted by the operator who "
                       "committed the challenger file")
    body = json_body()
    resolution = require_enum(body, "resolution", RESOLUTIONS)
    reason = body.get("resolution_reason")
    resolved_value = body.get("resolved_value")
    if resolution != "PENDING" and (reason is None or not isinstance(reason, str) or not reason):
        raise invalid_request("resolution_reason is required when resolution is not PENDING")
    if resolution == "MERGE_VALUES" and (resolved_value is None or resolved_value == ""):
        raise ApiError(ERR_MERGE_VALUE_REQUIRED, 422,
                       "resolution=MERGE_VALUES without resolved_value")

    pid = c["provider_id"]
    incumbent = DB.provider_attributes.get(c["incumbent_attribute_id"])
    challenger = DB.provider_attributes.get(c["challenger_attribute_id"])

    if resolution == "KEEP_INCUMBENT":
        if challenger is not None:
            challenger["status"] = "VOIDED"
            touch(challenger)
    elif resolution == "ACCEPT_CHALLENGER":
        if incumbent is not None:
            incumbent["status"] = "SUPERSEDED"
            touch(incumbent)
        if challenger is not None:
            challenger["status"] = "ACTIVE"
            challenger["supersedes_attribute_id"] = c["incumbent_attribute_id"]
            touch(challenger)
    elif resolution == "MERGE_VALUES":
        today = CLOCK.today()
        for a in (incumbent, challenger):
            if a is not None:
                a["status"] = "SUPERSEDED"
                touch(a)
        base = challenger if challenger is not None else incumbent
        merged = {
            **new_common(),
            "provider_id": pid,
            "attribute_group": c["attribute_group"],
            "attribute_key": c["attribute_key"],
            "attribute_value": resolved_value,
            "effective_date": today,
            "term_date": None,
            "roster_source_id": base.get("roster_source_id") if base else None,
            "roster_row_id": None,
            "supersedes_attribute_id": c["challenger_attribute_id"],
            "status": "ACTIVE",
        }
        DB.provider_attributes[merged["id"]] = merged

    c["resolution"] = resolution
    c["resolution_reason"] = reason
    c["resolved_value"] = resolved_value
    c["status"] = "RESOLVED"
    touch(c)
    run_quality_scoring(pid)
    return success_object(_public(c))


@bp.route("/pdm/attribute-conflicts/<cid>/escalate", methods=["POST"])
def escalate_conflict(cid):
    require_roles("DataSteward")
    c = _get_conflict(cid)
    if c["status"] != "OPEN":
        raise invalid_state()
    inc_src = DB.roster_sources.get(c["incumbent_source_id"])
    cha_src = DB.roster_sources.get(c["challenger_source_id"])
    if (inc_src is not None and cha_src is not None
            and inc_src["precedence_rank"] == cha_src["precedence_rank"]):
        raise ApiError(ERR_PRECEDENCE_TIE_NOT_ESCALATABLE, 409,
                       "Escalation of an equal-rank conflict is not permitted")
    c["status"] = "ESCALATED"
    touch(c)
    return success_object(_public(c))
