"""Finding endpoints (PRD 3.6): severity pinned to the ACTIVE config at
creation, issue/escalate transitions, overdue count re-evaluated on read."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_ENGAGEMENT_INVALID_STATE,
    ERR_FINDING_INVALID_STATE,
    ERR_FINDING_SELF_ISSUE,
    ERR_NEGOTIATION_ROUNDS_NOT_EXHAUSTED,
    ERR_NO_ACTIVE_RATING_CONFIG,
    ERR_REPORT_ALREADY_ISSUED,
    ERR_WORKPAPER_NOT_SIGNED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_str
from services.calculations import compute_severity
from services.cascades import recompute_finding_overdue, recompute_open_finding_count
from services.core import new_record, public, touch
from validate import (
    body_ref,
    check_score_range,
    check_unknown_fields,
    get_body,
    opt_nullable_str,
    req_int,
    req_str,
    require_path,
)

bp = Blueprint("findings", __name__)

CREATE_FIELDS = {"engagement_id", "title", "likelihood", "impact", "workpaper_id"}


def _active_config():
    for cfg in db["rating_criteria_configs"].values():
        if cfg["status"] == "ACTIVE":
            return cfg
    return None


def _refresh_overdue(finding):
    """open_overdue_action_count is re-evaluated against the logical clock on
    every read (PRD 3.7) — without a version bump, since a read is no mutation."""
    recompute_finding_overdue(finding)


@bp.post("/audit/findings")
def create_finding():
    caller = authorized(["FieldAuditor"])
    body = get_body()
    # Stage 4: body FK existence in declared input order
    body_ref(body, "engagement_id", "engagements")
    body_ref(body, "workpaper_id", "workpapers")  # optional ref
    # Stage 5: shape, then score ranges
    check_unknown_fields(body, CREATE_FIELDS)
    engagement_id = req_str(body, "engagement_id")
    title = req_str(body, "title")
    likelihood = req_int(body, "likelihood")
    impact = req_int(body, "impact")
    workpaper_id = opt_nullable_str(body, "workpaper_id")
    check_score_range(likelihood, "likelihood")
    check_score_range(impact, "impact")
    eng = db["engagements"][engagement_id]
    # Stage 7: findings are raised against an engagement in flight
    if eng["status"] not in ("FIELDWORK", "REPORTING"):
        raise_error(ERR_ENGAGEMENT_INVALID_STATE,
                    f"findings require FIELDWORK or REPORTING, not {eng['status']}")
    # Referential gate: linked workpaper must belong to the engagement and be
    # SIGNED_OFF (PRD 3.6 payload rule)
    if workpaper_id is not None:
        wp = db["workpapers"][workpaper_id]
        if wp["engagement_id"] != engagement_id or wp["status"] != "SIGNED_OFF":
            raise_error(ERR_WORKPAPER_NOT_SIGNED,
                        "linked workpaper must belong to the engagement and be SIGNED_OFF")
    # Referential gate: an ACTIVE rating config must exist to pin severity
    config = _active_config()
    if config is None:
        raise_error(ERR_NO_ACTIVE_RATING_CONFIG, "no ACTIVE rating criteria config")
    # Business gate: the finding roster freezes once a report is issued
    for rep in db["audit_reports"].values():
        if rep["engagement_id"] == engagement_id and rep["status"] in ("ISSUED", "DISTRIBUTED"):
            raise_error(ERR_REPORT_ALREADY_ISSUED,
                        "the engagement's report is already issued")
    composite = likelihood * impact
    rec = new_record("findings", {
        "engagement_id": engagement_id,
        "workpaper_id": workpaper_id,
        "rating_criteria_config_id": config["id"],  # version pinning (PRD 2.6)
        "title": title,
        "likelihood": likelihood,
        "impact": impact,
        "composite_score": composite,
        "severity": compute_severity(composite, config),
        "status": "DRAFT",
        "negotiation_rounds": 0,
        "created_by_user_id": caller.user_id,
        "open_overdue_action_count": 0,
        "finalized_at": None,
    })
    recompute_open_finding_count(eng)
    touch(eng)
    return success_object(public(rec), status=201)


@bp.get("/audit/findings")
def list_findings():
    filters = {
        "engagement_id": query_str("engagement_id"),
        "workpaper_id": query_str("workpaper_id"),
        "rating_criteria_config_id": query_str("rating_criteria_config_id"),
        "status": query_str("status"),
        "severity": query_str("severity"),
    }
    return list_response("findings", filters, pre=_refresh_overdue)


@bp.get("/audit/findings/<rid>")
def get_finding(rid):
    return get_one("findings", rid, pre=_refresh_overdue)


@bp.post("/audit/findings/<rid>/issue")
def issue_finding(rid):
    caller = authorized(["AuditManager"])
    finding = require_path("findings", rid)
    # Stage 7: must be DRAFT
    if finding["status"] != "DRAFT":
        raise_error(ERR_FINDING_INVALID_STATE, "finding is not DRAFT")
    # Stage 8: segregation of duties — issuer differs from creator; evaluated
    # before any referential gate (PRD 2.7 stage 8 note)
    if caller.user_id == finding["created_by_user_id"]:
        raise_error(ERR_FINDING_SELF_ISSUE, "creator cannot issue own finding")
    # Stage 11: a linked workpaper must still be SIGNED_OFF
    if finding["workpaper_id"] is not None:
        wp = db["workpapers"].get(finding["workpaper_id"])
        if wp is None or wp["status"] != "SIGNED_OFF":
            raise_error(ERR_WORKPAPER_NOT_SIGNED,
                        "linked workpaper is no longer SIGNED_OFF")
    finding["status"] = "PENDING_RESPONSE"
    touch(finding)
    return success_object(public(finding))


@bp.post("/audit/findings/<rid>/escalate")
def escalate_finding(rid):
    authorized(["ChiefAuditExecutive"])
    finding = require_path("findings", rid)
    # Stage 7: must be REBUTTED
    if finding["status"] != "REBUTTED":
        raise_error(ERR_FINDING_INVALID_STATE, "finding is not REBUTTED")
    # Stage 11: negotiation rounds exhausted — exactly 3 suffices
    if finding["negotiation_rounds"] < 3:
        raise_error(ERR_NEGOTIATION_ROUNDS_NOT_EXHAUSTED,
                    "escalation requires negotiation_rounds >= 3")
    finding["status"] = "ESCALATED"
    touch(finding)
    return success_object(public(finding))
