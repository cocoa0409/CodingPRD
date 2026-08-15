"""CorrespondenceItem endpoints (PRD 3.3): capture, review, segregated escalation."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CORRESPONDENCE_INVALID_STATE,
    ERR_SOD_ESCALATION_RESOLVER,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch
from util import add_days_dt, clock_ts, fmt_datetime, CLOCK
from validate import (
    get_body, opt_str, req_enum, req_int, req_str, require_path_resource, require_ref,
)

bp = Blueprint("correspondence", __name__)

CHANNELS = ("EMAIL", "SMS", "SOCIAL_MEDIA", "PAPER_LETTER")
CHANNEL_WEIGHT = {"EMAIL": 5, "PAPER_LETTER": 10, "SMS": 20, "SOCIAL_MEDIA": 25}
REVIEW_DECISIONS = ("APPROVE", "FLAG", "ESCALATE")
RESOLVE_DECISIONS = ("APPROVE", "FLAG")

CAP = 100
FLAG_FLOOR = 70
ESCALATION_APPROVE_CEILING = 30
HEIGHTENED_BONUS = 30
REVIEW_WINDOW_DAYS = 30


@bp.post("/correspondence-items")
def create_correspondence():
    authorized(["ComplianceAnalyst"])
    body = get_body()
    # Priority 3: FK existence
    rep = require_ref("representatives", body.get("rep_id"), "rep_id")
    # Priority 8: schema
    channel = req_enum(body, "channel", CHANNELS)
    subject = req_str(body, "subject")
    body_excerpt = opt_str(body, "body_excerpt", default="")
    lexicon_hits = req_int(body, "lexicon_hits", non_negative=True)
    if rep is None:
        raise_error(ERR_VALIDATION, "missing or invalid field: rep_id")

    # Provisional variant: pure formula over lexicon_hits + channel + rep tier
    tier_bonus = HEIGHTENED_BONUS if rep["supervision_tier"] == "HEIGHTENED" else 0
    provisional = min(CAP, 10 * lexicon_hits + CHANNEL_WEIGHT[channel] + tier_bonus)
    captured = CLOCK.now()
    rec = new_record("correspondence_items", {
        "rep_id": rep["id"],
        "channel": channel,
        "subject": subject,
        "body_excerpt": body_excerpt,
        "lexicon_hits": lexicon_hits,
        "captured_at": fmt_datetime(captured),
        "review_deadline": fmt_datetime(add_days_dt(captured, REVIEW_WINDOW_DAYS)),
        "provisional_risk_score": provisional,
        "final_risk_score": None,
        "reviewed_by": None,
        "escalated_by": None,
        "resolved_by": None,
        "status": "PENDING_REVIEW",
    })
    return success_object(public(rec), status=201)


@bp.get("/correspondence-items")
def list_correspondence():
    return list_response("correspondence_items", filters={
        "rep_id": request.args.get("rep_id"),
        "status": request.args.get("status"),
    })


@bp.get("/correspondence-items/<rid>")
def get_correspondence(rid):
    return get_one("correspondence_items", rid)


@bp.post("/correspondence-items/<rid>/review")
def review_correspondence(rid):
    caller = authorized(["CompliancePrincipal"])
    item = require_path_resource("correspondence_items", rid)
    if item["status"] not in ("PENDING_REVIEW", "OVERDUE"):
        raise_error(ERR_CORRESPONDENCE_INVALID_STATE,
                    "review is allowed only from PENDING_REVIEW or OVERDUE")
    body = get_body()
    decision = req_enum(body, "decision", REVIEW_DECISIONS)
    opt_str(body, "note")

    prov = item["provisional_risk_score"]
    if decision == "APPROVE":
        item["status"] = "APPROVED"
        item["reviewed_by"] = caller.user_id
        item["final_risk_score"] = prov
    elif decision == "FLAG":
        item["status"] = "FLAGGED"
        item["reviewed_by"] = caller.user_id
        item["final_risk_score"] = max(prov, FLAG_FLOOR)
        _bump_flag_count(item)
    else:  # ESCALATE — final score stays unwritten
        item["status"] = "ESCALATED"
        item["escalated_by"] = caller.user_id
    touch(item)
    return success_object(public(item))


@bp.post("/correspondence-items/<rid>/resolve-escalation")
def resolve_escalation(rid):
    caller = authorized(["CompliancePrincipal"])
    item = require_path_resource("correspondence_items", rid)
    if item["status"] != "ESCALATED":
        raise_error(ERR_CORRESPONDENCE_INVALID_STATE,
                    "resolve-escalation is allowed only from ESCALATED")
    # Segregation of duties (PRD 2.6): resolver must differ from escalated_by
    if caller.user_id == item["escalated_by"]:
        raise_error(ERR_SOD_ESCALATION_RESOLVER,
                    "the escalating principal cannot resolve their own escalation")
    body = get_body()
    decision = req_enum(body, "decision", RESOLVE_DECISIONS)
    opt_str(body, "note")

    prov = item["provisional_risk_score"]
    item["resolved_by"] = caller.user_id
    if decision == "APPROVE":
        item["status"] = "APPROVED"
        item["final_risk_score"] = min(prov, ESCALATION_APPROVE_CEILING)
    else:  # FLAG
        item["status"] = "FLAGGED"
        item["final_risk_score"] = max(prov, FLAG_FLOOR)
        _bump_flag_count(item)
    touch(item)
    return success_object(public(item))


def _bump_flag_count(item):
    rep = db["representatives"].get(item["rep_id"])
    if rep is not None:
        rep["compliance_flag_count"] += 1
        touch(rep)
