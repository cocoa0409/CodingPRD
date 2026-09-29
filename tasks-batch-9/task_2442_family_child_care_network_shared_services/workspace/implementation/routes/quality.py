"""PRD 3.7 coaching visits, quality scoring and compliance escalation."""
from flask import Blueprint

import auth
import clock
import db
import response
import services
import validators as v
from errors import ApiError

bp = Blueprint("quality", __name__)

FOCUS_AREAS = ("ENVIRONMENT", "CURRICULUM", "BUSINESS_PRACTICE", "HEALTH_SAFETY")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
COACHING_WINDOW_DAYS = 29
COACHING_WINDOW_MAX_VISITS = 2
DEFAULT_CRITICAL_STANDARD_CODE = "QS-CRITICAL"
DEFAULT_CAP_DUE_DAYS = 30
CAP_REJECTION_LIMIT = 2


def _visit(actor, visit_id):
    row = services.find_or_404(db.visits, visit_id, "ERR_VISIT_NOT_FOUND", "coaching visit")
    auth.scope_provider(actor, row["provider_id"])
    return row


def _review(actor, review_id):
    row = services.find_or_404(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND", "compliance review")
    auth.scope_provider(actor, row["provider_id"])
    return row


def _open_review(provider, actor, origin, standard_codes, severity, cap_due_on):
    row = db.make_row(
        provider_id=provider["id"],
        origin=origin,
        standard_codes=standard_codes,
        severity=severity,
        cap_due_on=cap_due_on,
        opened_by_user_id=actor.user_id,
        cap_narrative=None,
        cap_submitted_at=None,
        cap_rejection_count=0,
        closed_by_user_id=None,
        status="OPEN",
    )
    services.register_new(row)
    db.reviews[row["id"]] = row
    services.recompute_open_finding_count(provider)
    return row


# --- coaching visits -------------------------------------------------------

@bp.post("/fccn/coaching-visits")
def schedule_visit():
    actor = auth.require_auth(("QualityCoach",))
    body = v.get_body()
    provider_id = v.req_str(body, "provider_id")
    provider = services.provider_or_404(provider_id)
    scheduled_on = v.req_instant(body, "scheduled_on")
    focus_area = v.req_enum(body, "focus_area", FOCUS_AREAS)
    v.reject_unversioned(body)

    requested_date = clock.date_of(scheduled_on)
    if requested_date < clock.today():
        raise ApiError(
            "ERR_VISIT_DATE_IN_PAST",
            "A coaching visit may not be scheduled before the logical clock date.",
        )
    low = clock.plus_days(requested_date, -COACHING_WINDOW_DAYS)
    high = clock.plus_days(requested_date, COACHING_WINDOW_DAYS)
    nearby = [
        x for x in services.provider_children(db.visits, provider["id"])
        if x["status"] in ("SCHEDULED", "COMPLETED")
        and low <= clock.date_of(x["scheduled_on"]) <= high
    ]
    if len(nearby) >= COACHING_WINDOW_MAX_VISITS:
        raise ApiError(
            "ERR_COACHING_WINDOW_SATURATED",
            "The provider already has two visits inside the fifty-nine-day window.",
        )

    row = db.make_row(
        provider_id=provider["id"],
        scheduled_on=scheduled_on,
        focus_area=focus_area,
        coach_user_id=actor.user_id,
        conducted_by_user_id=None,
        visit_conducted_on=None,
        observation_score=None,
        findings=[],
        critical_finding=False,
        status="SCHEDULED",
    )
    services.register_new(row)
    db.visits[row["id"]] = row
    return response.created(row)


@bp.post("/fccn/coaching-visits/<visit_id>/conduct")
def conduct_visit(visit_id):
    actor = auth.require_auth(("QualityCoach",))
    visit = services.find_or_404(db.visits, visit_id, "ERR_VISIT_NOT_FOUND", "coaching visit")
    provider = db.providers[visit["provider_id"]]
    body = v.get_body()
    v.reject_unversioned(body)
    visit_conducted_on = v.req_instant(body, "visit_conducted_on")
    observation_score = v.req_number(body, "observation_score", 0, 100)
    findings = v.req_str_array(body, "findings", non_empty=False)
    critical_finding = v.req_bool(body, "critical_finding")
    critical_standard_codes = v.opt_array(body, "critical_standard_codes")
    if critical_standard_codes is not None:
        critical_standard_codes = v.req_str_array(body, "critical_standard_codes")
    cap_due_on = v.opt_instant(body, "cap_due_on")

    conducted_date = clock.date_of(visit_conducted_on)
    if conducted_date < clock.date_of(visit["scheduled_on"]) or conducted_date > clock.today():
        v.bad(
            "'visit_conducted_on' must fall on or after scheduled_on and on or before the clock date."
        )

    if visit["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_VISIT_STATE", "Only a SCHEDULED visit may be conducted.")
    if actor.user_id == visit["coach_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "A visit may not be conducted by the operator who scheduled it.",
        )

    visit["visit_conducted_on"] = visit_conducted_on
    visit["observation_score"] = observation_score
    visit["findings"] = findings
    visit["critical_finding"] = critical_finding
    visit["conducted_by_user_id"] = actor.user_id
    visit["status"] = "COMPLETED"
    services.touch(visit)

    if critical_finding:
        _open_review(
            provider,
            actor,
            "COACHING_CRITICAL_FINDING",
            critical_standard_codes or [DEFAULT_CRITICAL_STANDARD_CODE],
            "CRITICAL",
            cap_due_on
            or clock.format_date(clock.plus_days(clock.today(), DEFAULT_CAP_DUE_DAYS)),
        )
    services.rescore_quality(provider, "COACHING_WEIGHTED")
    return response.ok(visit)


@bp.get("/fccn/coaching-visits/<visit_id>")
def read_visit(visit_id):
    actor = auth.require_auth(("NetworkAdmin", "QualityCoach", "Provider"))
    return response.ok(_visit(actor, visit_id))


# --- compliance reviews ----------------------------------------------------

@bp.post("/fccn/compliance-reviews")
def open_review():
    actor = auth.require_auth(("QualityCoach",))
    body = v.get_body()
    provider_id = v.req_str(body, "provider_id")
    provider = services.provider_or_404(provider_id)
    standard_codes = v.req_str_array(body, "standard_codes")
    severity = v.req_enum(body, "severity", SEVERITIES)
    cap_due_on = v.req_instant(body, "cap_due_on")
    v.reject_unversioned(body)

    row = _open_review(provider, actor, "SCHEDULED_AUDIT", standard_codes, severity, cap_due_on)
    return response.created(row)


@bp.post("/fccn/compliance-reviews/<review_id>/submit-cap")
def submit_cap(review_id):
    actor = auth.require_auth(("Provider",))
    review = _review(actor, review_id)
    body = v.get_body()
    v.reject_unversioned(body)
    cap_narrative = v.req_str(body, "cap_narrative")

    if review["status"] not in ("OPEN", "CAP_REJECTED"):
        raise ApiError(
            "ERR_INVALID_REVIEW_STATE",
            "A corrective action plan may only be filed against an OPEN or CAP_REJECTED review.",
        )
    if clock.today() > clock.date_of(review["cap_due_on"]):
        raise ApiError(
            "ERR_CAP_DEADLINE_PASSED", "The corrective action plan deadline has passed."
        )

    review["cap_narrative"] = cap_narrative
    review["cap_submitted_at"] = clock.now_raw()
    review["status"] = "CAP_SUBMITTED"
    services.touch(review)
    services.recompute_open_finding_count(db.providers[review["provider_id"]])
    return response.ok(review)


@bp.post("/fccn/compliance-reviews/<review_id>/reject-cap")
def reject_cap(review_id):
    auth.require_auth(("QualityCoach",))
    review = services.find_or_404(
        db.reviews, review_id, "ERR_REVIEW_NOT_FOUND", "compliance review"
    )
    if review["status"] != "CAP_SUBMITTED":
        raise ApiError(
            "ERR_INVALID_REVIEW_STATE", "Only a CAP_SUBMITTED review may have its plan rejected."
        )
    review["status"] = "CAP_REJECTED"
    review["cap_rejection_count"] += 1
    services.touch(review)
    services.recompute_open_finding_count(db.providers[review["provider_id"]])
    return response.ok(review)


@bp.post("/fccn/compliance-reviews/<review_id>/close")
def close_review(review_id):
    actor = auth.require_auth(("QualityCoach",))
    review = services.find_or_404(
        db.reviews, review_id, "ERR_REVIEW_NOT_FOUND", "compliance review"
    )
    provider = db.providers[review["provider_id"]]

    if review["status"] != "CAP_SUBMITTED":
        raise ApiError("ERR_INVALID_REVIEW_STATE", "Only a CAP_SUBMITTED review may be closed.")
    if actor.user_id == review["opened_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "A review may not be closed by the operator who opened it.",
        )

    review["closed_by_user_id"] = actor.user_id
    review["status"] = "CLOSED_COMPLIANT"
    services.touch(review)
    services.recompute_open_finding_count(provider)
    services.rescore_quality(provider, "COMPLIANCE_ANCHORED")
    return response.ok(review)


@bp.post("/fccn/compliance-reviews/<review_id>/escalate")
def escalate_review(review_id):
    auth.require_auth(("NetworkAdmin",))
    review = services.find_or_404(
        db.reviews, review_id, "ERR_REVIEW_NOT_FOUND", "compliance review"
    )
    provider = db.providers[review["provider_id"]]

    if review["status"] != "CAP_REJECTED":
        raise ApiError("ERR_INVALID_REVIEW_STATE", "Only a CAP_REJECTED review may be escalated.")
    if provider["membership_status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_PROVIDER_STATE", "Only an ACTIVE provider may be placed on probation."
        )
    if review["cap_rejection_count"] < CAP_REJECTION_LIMIT:
        raise ApiError(
            "ERR_CAP_REJECTION_LIMIT_NOT_REACHED",
            "Escalation requires at least %d corrective action plan rejections."
            % CAP_REJECTION_LIMIT,
        )

    review["status"] = "ESCALATED_TO_LICENSING"
    services.touch(review)
    services.recompute_open_finding_count(provider)
    services.escalation_cascade(provider)
    return response.ok(review)


@bp.get("/fccn/compliance-reviews/<review_id>")
def read_review(review_id):
    actor = auth.require_auth(("NetworkAdmin", "QualityCoach", "Provider"))
    return response.ok(_review(actor, review_id))
