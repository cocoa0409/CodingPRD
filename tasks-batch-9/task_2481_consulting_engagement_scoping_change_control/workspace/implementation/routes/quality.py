"""Quality checkpoints, risk escalations and the satisfaction assessment (PRD 3.9)."""

from flask import Blueprint, g

from calc import satisfaction_csat
from db import clock_date, clock_stamp, db, new_row, rows, touch
from errors import fail
from middleware import (
    READ_ROLES,
    ROLE_CLIENT,
    ROLE_LEADERSHIP,
    ROLE_MANAGER,
    ROLE_REVIEWER,
    client_scope,
    require_roles,
)
from response import ok
from routes.common import fetch, filtered, fk, paged
from serializers import quality_review_out, risk_escalation_out, satisfaction_out
from services.cascade import (
    UNRESOLVED,
    create_escalation,
    hold_delivery,
    reconcile_on_raise,
    reconcile_on_resolve,
    release_delivery,
    unresolved_severe_count,
)
from validators import (
    filter_arg,
    get_bool,
    get_date,
    get_enum,
    get_id,
    get_int,
    get_str,
    json_body,
    parse_date,
)

bp = Blueprint("quality", __name__)

CHECKPOINT_TYPES = ("SCOPE_GATE", "MIDPOINT", "PRE_DELIVERY")
SEVERITIES = ("NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL")
OUTCOMES = ("PASSED", "CONDITIONAL", "FAILED")
SEVERITY_FOR_OUTCOME = {
    "PASSED": ("NONE",),
    "CONDITIONAL": ("LOW", "MEDIUM"),
    "FAILED": ("HIGH", "CRITICAL"),
}
MIN_WINDOW_GAP_DAYS = 3
RESPONSES = ("ACKNOWLEDGE", "HOLD_DELIVERY", "RESOLVE")
LEGAL_RESPONSES = {
    "ACKNOWLEDGE": ("OPEN",),
    "HOLD_DELIVERY": ("OPEN", "ACKNOWLEDGED"),
    "RESOLVE": ("OPEN", "ACKNOWLEDGED", "DELIVERY_HELD"),
}
READ_ESCALATION_ROLES = tuple(r for r in READ_ROLES if r != ROLE_CLIENT)
READY_REVIEW_STATES = ("PASSED", "CONDITIONAL")


def engagement_reviews(engagement_id):
    return [r for r in rows("quality_reviews") if r["engagement_id"] == engagement_id]


def engagement_escalations(engagement_id):
    return [e for e in rows("risk_escalations") if e["engagement_id"] == engagement_id]


def window_gap_days(new_start, new_end, other_start, other_end):
    """None when the two closed windows overlap, otherwise the gap in days."""
    if new_start > other_end:
        return (new_start - other_end).days
    if other_start > new_end:
        return (other_start - new_end).days
    return None


# ------------------------------------------------------------------ scheduling


@bp.post("/quality-reviews")
def create_quality_review():
    require_roles(ROLE_MANAGER, ROLE_LEADERSHIP)
    body = json_body()
    engagement_id = get_id(body, "engagement_id")
    reviewer_id = get_id(body, "reviewer_consultant_id")
    checkpoint_type = get_enum(body, "checkpoint_type", CHECKPOINT_TYPES)
    window_start = get_date(body, "window_start_date")
    window_end = get_date(body, "window_end_date")

    if window_end < window_start:
        fail("ERR_INVALID_DATE_RANGE", "window_end_date must fall on or after window_start_date.")

    engagement = fk("engagements", engagement_id)
    reviewer = fk("consultants", reviewer_id)

    if reviewer_id in (
        engagement["lead_partner_consultant_id"],
        engagement["engagement_manager_consultant_id"],
    ):
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "Nobody may assure an engagement they lead or manage.",
        )
    if engagement["delivery_state"] == "CLOSED":
        fail("ERR_ENGAGEMENT_STATE_INVALID", "The engagement is CLOSED.")
    if not reviewer["quality_reviewer_certified"]:
        fail("ERR_REVIEWER_NOT_CERTIFIED", "The nominated reviewer is not certified.")

    for other in engagement_reviews(engagement_id):
        if other["status"] != "SCHEDULED":
            continue
        gap = window_gap_days(
            window_start,
            window_end,
            parse_date(other["window_start_date"]),
            parse_date(other["window_end_date"]),
        )
        if gap is None or gap < MIN_WINDOW_GAP_DAYS:
            fail(
                "ERR_REVIEW_WINDOW_CONFLICT",
                "The window must keep a gap of at least 3 days from every other checkpoint.",
            )

    row = new_row(
        {
            "engagement_id": engagement_id,
            "reviewer_consultant_id": reviewer_id,
            "checkpoint_type": checkpoint_type,
            "window_start_date": window_start.isoformat(),
            "window_end_date": window_end.isoformat(),
            "status": "SCHEDULED",
            "findings_severity": "NONE",
            "note": None,
        }
    )
    db.quality_reviews[row["id"]] = row
    return ok(quality_review_out(row), 201)


@bp.get("/quality-reviews/<review_id>")
def read_quality_review(review_id):
    require_roles(*READ_ROLES)
    row = fetch("quality_reviews", review_id)
    engagement = db.engagements.get(row["engagement_id"])
    if engagement is not None:
        client_scope(engagement["client_id"])
    return ok(quality_review_out(row))


@bp.get("/quality-reviews")
def list_quality_reviews():
    require_roles(*READ_ROLES)
    engagement_id = filter_arg("engagement_id")
    reviewer_id = filter_arg("reviewer_consultant_id")
    checkpoint_type = filter_arg("checkpoint_type")
    status = filter_arg("status")
    own_client = g.user_id if g.role == ROLE_CLIENT else None

    def keep(row):
        if engagement_id is not None and row["engagement_id"] != engagement_id:
            return False
        if reviewer_id is not None and row["reviewer_consultant_id"] != reviewer_id:
            return False
        if checkpoint_type is not None and row["checkpoint_type"] != checkpoint_type:
            return False
        if status is not None and row["status"] != status:
            return False
        if own_client is not None:
            engagement = db.engagements.get(row["engagement_id"])
            if engagement is None or engagement["client_id"] != own_client:
                return False
        return True

    return paged(filtered("quality_reviews", keep), quality_review_out)


# ------------------------------------------------------------------ outcome


@bp.post("/quality-reviews/<review_id>/record-outcome")
def record_outcome(review_id):
    require_roles(ROLE_REVIEWER)
    row = fetch("quality_reviews", review_id)
    if g.user_id != row["reviewer_consultant_id"]:
        fail(
            "ERR_NOT_ASSIGNED_TO_ENGAGEMENT",
            "Only the nominated reviewer may record this outcome.",
        )

    body = json_body()
    outcome = get_enum(body, "outcome", OUTCOMES)
    severity = get_enum(body, "findings_severity", SEVERITIES)
    note = get_str(body, "note", required=False, min_len=0, max_len=None)

    if row["status"] != "SCHEDULED":
        fail("ERR_QUALITY_REVIEW_STATE_INVALID", "The checkpoint has already been recorded.")
    if severity not in SEVERITY_FOR_OUTCOME[outcome]:
        fail(
            "ERR_FINDINGS_SEVERITY_INCONSISTENT",
            "findings_severity %s is inconsistent with outcome %s." % (severity, outcome),
        )
    today = clock_date()
    if today < parse_date(row["window_start_date"]) or today > parse_date(row["window_end_date"]):
        fail("ERR_REVIEW_WINDOW_NOT_OPEN", "The current clock date is outside the review window.")

    row["status"] = outcome
    row["findings_severity"] = severity
    row["note"] = note
    touch(row)

    if outcome == "FAILED":
        engagement = db.engagements.get(row["engagement_id"])
        if engagement is not None:
            escalation_status = "DELIVERY_HELD" if severity == "CRITICAL" else "OPEN"
            create_escalation(
                engagement,
                source="QUALITY",
                severity=severity,
                opened_reason="quality checkpoint %s failed" % row["checkpoint_type"],
                source_quality_review_id=row["id"],
                status=escalation_status,
            )
            if escalation_status == "DELIVERY_HELD" and engagement["delivery_state"] == "ACTIVE":
                hold_delivery(engagement)
            reconcile_on_raise(engagement, severity)
            touch(engagement)
    return ok(quality_review_out(row))


# ------------------------------------------------------------------ escalations


@bp.get("/risk-escalations/<escalation_id>")
def read_escalation(escalation_id):
    require_roles(*READ_ESCALATION_ROLES)
    return ok(risk_escalation_out(fetch("risk_escalations", escalation_id)))


@bp.get("/risk-escalations")
def list_escalations():
    require_roles(*READ_ESCALATION_ROLES)
    engagement_id = filter_arg("engagement_id")
    review_id = filter_arg("source_quality_review_id")
    source = filter_arg("source")
    severity = filter_arg("severity")
    status = filter_arg("status")

    def keep(row):
        if engagement_id is not None and row["engagement_id"] != engagement_id:
            return False
        if review_id is not None and row["source_quality_review_id"] != review_id:
            return False
        if source is not None and row["source"] != source:
            return False
        if severity is not None and row["severity"] != severity:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paged(filtered("risk_escalations", keep), risk_escalation_out)


@bp.post("/risk-escalations/<escalation_id>/leadership-response")
def leadership_response(escalation_id):
    require_roles(ROLE_LEADERSHIP)
    row = fetch("risk_escalations", escalation_id)
    body = json_body()
    response = get_enum(body, "response", RESPONSES)

    if row["status"] not in LEGAL_RESPONSES[response]:
        fail(
            "ERR_RISK_ESCALATION_STATE_INVALID",
            "%s is not reachable from %s." % (response, row["status"]),
        )

    engagement = db.engagements.get(row["engagement_id"])

    if response == "ACKNOWLEDGE":
        row["status"] = "ACKNOWLEDGED"
        row["leadership_response"] = response
        touch(row)
        return ok(risk_escalation_out(row))

    if response == "HOLD_DELIVERY":
        if engagement is None or engagement["delivery_state"] != "ACTIVE":
            fail("ERR_ENGAGEMENT_STATE_INVALID", "The engagement's delivery is not ACTIVE.")
        row["status"] = "DELIVERY_HELD"
        row["leadership_response"] = response
        touch(row)
        hold_delivery(engagement)
        return ok(risk_escalation_out(row))

    # RESOLVE
    if row["source"] == "QUALITY":
        origin = db.quality_reviews.get(row["source_quality_review_id"])
        cleared = False
        if origin is not None:
            for review in engagement_reviews(row["engagement_id"]):
                if (
                    review["checkpoint_type"] == origin["checkpoint_type"]
                    and review["_seq"] > origin["_seq"]
                    and review["status"] in READY_REVIEW_STATES
                ):
                    cleared = True
                    break
        if not cleared:
            fail(
                "ERR_QUALITY_GATE_PENDING",
                "A later checkpoint of the same type must have passed before resolution.",
            )

    was_held = row["status"] == "DELIVERY_HELD"
    count_before = unresolved_severe_count(row["engagement_id"])
    row["status"] = "RESOLVED"
    row["leadership_response"] = response
    row["resolved_at"] = clock_stamp()
    touch(row)

    if engagement is not None:
        if was_held and engagement["delivery_state"] == "ON_HOLD":
            others = [
                e
                for e in engagement_escalations(engagement["id"])
                if e["id"] != row["id"] and e["status"] == "DELIVERY_HELD"
            ]
            if not others:
                release_delivery(engagement)
        reconcile_on_resolve(engagement, count_before)
    return ok(risk_escalation_out(row))


# ------------------------------------------------------------------ satisfaction


@bp.post("/satisfaction-assessments")
def create_assessment():
    require_roles(ROLE_CLIENT)
    body = json_body()
    engagement_id = get_id(body, "engagement_id")
    delivery_score = get_int(body, "delivery_score", minimum=1, maximum=10)
    value_score = get_int(body, "value_score", minimum=1, maximum=10)
    communication_score = get_int(body, "communication_score", minimum=1, maximum=10)
    would_refer = get_bool(body, "would_refer")
    comments = get_str(body, "comments", required=False, min_len=0, max_len=None)

    engagement = fk("engagements", engagement_id)
    client_scope(engagement["client_id"])

    if engagement["delivery_state"] != "CLOSED":
        fail(
            "ERR_ENGAGEMENT_STATE_INVALID",
            "A satisfaction assessment may only be filed on a CLOSED engagement.",
        )
    for existing in rows("satisfaction_assessments"):
        if existing["engagement_id"] == engagement_id:
            fail(
                "ERR_ENGAGEMENT_STATE_INVALID",
                "The engagement already carries a satisfaction assessment.",
            )

    row = new_row(
        {
            "engagement_id": engagement_id,
            "delivery_score": delivery_score,
            "value_score": value_score,
            "communication_score": communication_score,
            "would_refer": would_refer,
            "comments": comments,
            "csat_score": satisfaction_csat(
                delivery_score, value_score, communication_score, would_refer
            ),
        },
        common=False,
    )
    db.satisfaction_assessments[row["id"]] = row
    return ok(satisfaction_out(row), 201)


@bp.get("/satisfaction-assessments/<assessment_id>")
def read_assessment(assessment_id):
    require_roles(*READ_ROLES)
    row = fetch("satisfaction_assessments", assessment_id)
    engagement = db.engagements.get(row["engagement_id"])
    if engagement is not None:
        client_scope(engagement["client_id"])
    return ok(satisfaction_out(row))


@bp.get("/satisfaction-assessments")
def list_assessments():
    require_roles(*READ_ROLES)
    engagement_id = filter_arg("engagement_id")
    own_client = g.user_id if g.role == ROLE_CLIENT else None

    def keep(row):
        if engagement_id is not None and row["engagement_id"] != engagement_id:
            return False
        if own_client is not None:
            engagement = db.engagements.get(row["engagement_id"])
            if engagement is None or engagement["client_id"] != own_client:
                return False
        return True

    return paged(filtered("satisfaction_assessments", keep), satisfaction_out)
