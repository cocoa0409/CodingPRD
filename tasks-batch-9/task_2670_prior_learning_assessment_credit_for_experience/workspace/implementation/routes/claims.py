"""PLA claims: creation, submission, revision, withdrawal, award, denial, posting."""
from flask import Blueprint, request

from db import (assignments_of_claim, claims_of_student, db, invoice_of_claim,
                new_row, next_claim_number, order_rows, portfolio_of_claim)
from errors import ApiError
from middleware import (ROLE_ASSESSOR, ROLE_COORDINATOR, ROLE_REGISTRAR,
                        ROLE_REVIEWER, ROLE_STUDENT, authenticate,
                        enforce_student_scope, find_or_404, scoped_claim)
from response import created, ok, ok_list, read_pagination
from serializers import claim_out
from services import invoice as invoice_service
from services.capacity import (cap_block_cascade, program_of_student,
                               release_reservation, remaining_posted_only,
                               remaining_reserved_inclusive, take_reservation,
                               unblock_waterfall, upper_division_remaining)
from services.coverage import crosswalk_provisional_coverage
from services.sla import revoke_open_assignments
from util import (APPEAL_WINDOW_HOURS, DUPLICATE_BLOCKING_STATES,
                  MAX_REVISION_ROUNDS, RESERVING_STATES, SOURCE_TYPES,
                  TERMINAL_ASSESSMENT_STATES, add_hours, as_dt, as_id, as_int,
                  as_str, dtv, json_body, present, put_dt, require, touch)

bp = Blueprint("claims", __name__)

READ_ROLES = [ROLE_COORDINATOR, ROLE_REGISTRAR, ROLE_ASSESSOR, ROLE_REVIEWER, ROLE_STUDENT]
WRITE_ROLES = [ROLE_STUDENT, ROLE_COORDINATOR]

CREDENTIAL_WINDOW_SOURCES = ("CREDIT_BY_EXAM", "INDUSTRY_CREDENTIAL")


# ---------------------------------------------------------------- shared guards
def _not_terminal(claim):
    """Ladder rung 14."""
    if claim["assessment_status"] in TERMINAL_ASSESSMENT_STATES:
        raise ApiError("ERR_CLAIM_ALREADY_TERMINAL")


def _rule_of(claim):
    if claim.get("articulation_rule_id") is None:
        return None
    return db.rules.get(claim["articulation_rule_id"])


def _recommendation_of(rule):
    if rule is None:
        return None
    return db.recommendations.get(rule["recommendation_id"])


def _inside_window(moment, start, end):
    """Half-open: includes effective_from, excludes effective_to."""
    if moment is None:
        return False
    if start is not None and moment < start:
        return False
    if end is not None and moment >= end:
        return False
    return True


def _check_articulation_live(claim):
    """Ladder rungs 21 and 22."""
    if claim["source_type"] == "PORTFOLIO":
        return None, None
    rule = _rule_of(claim)
    recommendation = _recommendation_of(rule)
    if rule is None or rule["status"] != "APPROVED":
        raise ApiError("ERR_ARTICULATION_NOT_APPROVED")
    if recommendation is None or recommendation["status"] != "PUBLISHED":
        raise ApiError("ERR_ARTICULATION_NOT_APPROVED")
    if rule["pinned_recommendation_version"] != recommendation["terms_version"]:
        raise ApiError("ERR_ARTICULATION_STALE_PIN")
    return rule, recommendation


def _check_enrolment(student, program):
    """Ladder rung 25."""
    if student["enrollment_status"] != "MATRICULATED":
        raise ApiError("ERR_STUDENT_NOT_MATRICULATED")
    if program is None or program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_INACTIVE")


def _fee_gate(claim, allowed):
    if claim["fee_status"] not in allowed:
        raise ApiError("ERR_ASSESSMENT_FEE_UNPAID")


# ---------------------------------------------------------------- creation
@bp.post("/pla-claims")
def create_claim():
    ctx = authenticate(WRITE_ROLES)
    body = json_body()

    # rung 3: S2.1 "a claim's `student_id` ... must equal `X-User-ID`"
    if isinstance(body, dict) and isinstance(body.get("student_id"), str):
        enforce_student_scope(ctx, body["student_id"])

    # rung 7: body references in the endpoint's declared field order
    student = None
    if present(body, "student_id") and isinstance(body["student_id"], str):
        student = db.students.get(body["student_id"])
        if student is None:
            raise ApiError("ERR_STUDENT_NOT_FOUND")
    course = None
    if present(body, "course_id") and isinstance(body["course_id"], str):
        course = db.courses.get(body["course_id"])
        if course is None:
            raise ApiError("ERR_COURSE_NOT_FOUND")
    rule = None
    if present(body, "articulation_rule_id") and isinstance(body["articulation_rule_id"], str):
        rule = db.rules.get(body["articulation_rule_id"])
        if rule is None:
            raise ApiError("ERR_ARTICULATION_RULE_NOT_FOUND")
    superseded = None
    if present(body, "supersedes_claim_id") and isinstance(body["supersedes_claim_id"], str):
        superseded = db.claims.get(body["supersedes_claim_id"])
        if superseded is None:
            raise ApiError("ERR_CLAIM_NOT_FOUND")

    # rung 8: request shape
    as_id(require(body, "student_id"), "student_id")
    as_id(require(body, "course_id"), "course_id")
    source_type = as_enum_source(require(body, "source_type"))
    credits_requested = as_int(require(body, "credits_requested"), "credits_requested")
    rush_requested = False
    if present(body, "rush_requested"):
        if not isinstance(body["rush_requested"], bool):
            raise ApiError("ERR_INVALID_REQUEST", "rush_requested must be a boolean")
        rush_requested = body["rush_requested"]
    attempt_raw = None
    attempt_dt = None
    if source_type == "PORTFOLIO":
        if present(body, "attempt_date"):
            attempt_raw, attempt_dt = as_dt(body["attempt_date"], "attempt_date")
    else:
        attempt_raw, attempt_dt = as_dt(require(body, "attempt_date"), "attempt_date")
    if present(body, "articulation_rule_id"):
        as_id(body["articulation_rule_id"], "articulation_rule_id")
    if present(body, "supersedes_claim_id"):
        as_id(body["supersedes_claim_id"], "supersedes_claim_id")

    # rung 9a
    if credits_requested < 1 or credits_requested > course["credits"]:
        raise ApiError("ERR_INVALID_CREDIT_REQUEST")
    # rung 9b
    if source_type == "PORTFOLIO":
        if rule is not None or present(body, "articulation_rule_id"):
            raise ApiError("ERR_ARTICULATION_RULE_FORBIDDEN")
    elif rule is None:
        raise ApiError("ERR_ARTICULATION_RULE_REQUIRED")
    if superseded is not None:
        if (superseded["student_id"] != student["id"]
                or superseded["course_id"] != course["id"]
                or superseded["assessment_status"] not in ("DENIED_FINAL", "WITHDRAWN")):
            raise ApiError("ERR_SUPERSEDED_CLAIM_NOT_TERMINAL")

    program = program_of_student(student)
    # rung 24
    if program is None or source_type not in (program.get("allowed_source_types") or []):
        raise ApiError("ERR_SOURCE_NOT_ALLOWED_BY_PROGRAM")
    if not course["pla_eligible"]:
        raise ApiError("ERR_COURSE_NOT_PLA_ELIGIBLE")
    # rung 25
    _check_enrolment(student, program)
    # rung 27
    if source_type in CREDENTIAL_WINDOW_SOURCES and rule is not None:
        if not _inside_window(attempt_dt, dtv(rule, "effective_from"), dtv(rule, "effective_to")):
            raise ApiError("ERR_ATTEMPT_DATE_OUTSIDE_WINDOW")
    # rung 30a
    if superseded is None:
        for sibling in claims_of_student(student["id"]):
            if sibling["course_id"] != course["id"]:
                continue
            if sibling["assessment_status"] in TERMINAL_ASSESSMENT_STATES and sibling["assessment_status"] != "AWARDED":
                continue
            raise ApiError("ERR_DUPLICATE_CLAIM")

    claim = new_row("PlaClaim")
    claim["claim_number"] = next_claim_number(student["id"])
    claim["student_id"] = student["id"]
    claim["course_id"] = course["id"]
    claim["articulation_rule_id"] = rule["id"] if rule is not None else None
    claim["supersedes_claim_id"] = superseded["id"] if superseded is not None else None
    claim["source_type"] = source_type
    claim["credits_requested"] = credits_requested
    claim["credits_awarded"] = None
    put_dt(claim, "attempt_date", attempt_dt, attempt_raw)
    claim["rush_requested"] = rush_requested
    claim["priority_tier"] = "EXPEDITED" if rush_requested else "STANDARD"
    claim["assessment_status"] = "DRAFT"
    claim["fee_status"] = "UNBILLED"
    claim["credit_status"] = "NOT_POSTED"
    claim["provisional_coverage_bp"] = None
    claim["verified_coverage_bp"] = None
    claim["assessor_recommendation"] = None
    claim["revision_round"] = 0
    claim["sla_breach_count"] = 0
    claim["appeal_count"] = 0
    claim["hold_reason"] = None
    claim["denial_reason"] = None
    put_dt(claim, "appeal_deadline_at", None)
    put_dt(claim, "submitted_at", None)
    claim["posted_term"] = None
    claim["posted_credits"] = None
    db.claims[claim["id"]] = claim
    return created(claim_out(claim))


def as_enum_source(value):
    if not isinstance(value, str) or value not in SOURCE_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "source_type must be one of %s" % ", ".join(SOURCE_TYPES))
    return value


# ---------------------------------------------------------------- reads
@bp.get("/pla-claims/<claim_id>")
def read_claim(claim_id):
    ctx = authenticate(READ_ROLES)
    claim = scoped_claim(ctx, claim_id)
    return ok(claim_out(claim))


CLAIM_FILTERS = ["student_id", "course_id", "articulation_rule_id", "supersedes_claim_id",
                 "assessment_status", "fee_status", "credit_status"]


@bp.get("/pla-claims")
def list_claims():
    authenticate(READ_ROLES)
    limit, offset = read_pagination()
    rows = list(db.claims.values())
    for name in CLAIM_FILTERS:
        wanted = request.args.get(name)
        if wanted is not None and wanted != "":
            rows = [r for r in rows if r.get(name) == wanted]
    rows = order_rows(rows, [(lambda r: r["created_at"], False),
                             (lambda r: r["claim_number"], False)])
    return ok_list(rows, claim_out, limit, offset)


# ---------------------------------------------------------------- submission
@bp.post("/pla-claims/<claim_id>/submit")
def submit_claim(claim_id):
    ctx = authenticate(WRITE_ROLES)
    claim = scoped_claim(ctx, claim_id)
    _not_terminal(claim)
    if claim["assessment_status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_CLAIM_NOT_DRAFT")
    first_submission = claim["assessment_status"] == "DRAFT"
    student = db.students.get(claim["student_id"])
    course = db.courses.get(claim["course_id"])
    program = program_of_student(student)

    if claim["hold_reason"] is not None:
        raise ApiError("ERR_ARTICULATION_NOT_APPROVED")
    rule, recommendation = _check_articulation_live(claim)
    if claim["credits_requested"] < 1 or claim["credits_requested"] > course["credits"]:
        raise ApiError("ERR_INVALID_CREDIT_REQUEST")
    if rule is not None and claim["credits_requested"] > rule["awarded_credits"]:
        raise ApiError("ERR_INVALID_CREDIT_REQUEST")
    # rung 24
    if program is None or claim["source_type"] not in (program.get("allowed_source_types") or []):
        raise ApiError("ERR_SOURCE_NOT_ALLOWED_BY_PROGRAM")
    if not course["pla_eligible"]:
        raise ApiError("ERR_COURSE_NOT_PLA_ELIGIBLE")
    # rung 25
    _check_enrolment(student, program)
    # rung 27: the rule window and the recommendation window both bind at submission
    if claim["source_type"] in CREDENTIAL_WINDOW_SOURCES and rule is not None:
        attempt = dtv(claim, "attempt_date")
        if not _inside_window(attempt, dtv(rule, "effective_from"), dtv(rule, "effective_to")):
            raise ApiError("ERR_ATTEMPT_DATE_OUTSIDE_WINDOW")
        if not _inside_window(attempt, dtv(recommendation, "effective_from"),
                              dtv(recommendation, "effective_to")):
            raise ApiError("ERR_ATTEMPT_DATE_OUTSIDE_WINDOW")
    # rung 30a: the duplicate sweep ignores this claim itself
    for sibling in claims_of_student(student["id"]):
        if sibling["id"] == claim["id"] or sibling["course_id"] != claim["course_id"]:
            continue
        if sibling["assessment_status"] in DUPLICATE_BLOCKING_STATES:
            raise ApiError("ERR_DUPLICATE_CLAIM")
    # rung 34
    portfolio = portfolio_of_claim(claim["id"])
    if claim["source_type"] == "PORTFOLIO":
        # Rung 16 is scoped away from claim submission, so the artifact floor
        # answers first for a portfolio that is both empty and not SUBMITTED.
        if portfolio is None or portfolio["artifact_count"] < 1:
            raise ApiError("ERR_PORTFOLIO_NO_ARTIFACTS")
        if portfolio["status"] != "SUBMITTED":
            raise ApiError("ERR_PORTFOLIO_NOT_SUBMITTABLE")

    # the two capacity gates park the claim instead of rejecting the request
    held_reservation = claim["assessment_status"] in RESERVING_STATES
    wanted = claim["credits_requested"]
    remaining = remaining_reserved_inclusive(program, student, claim)
    upper_remaining = upper_division_remaining(program, student, claim, course)
    if wanted > remaining:
        return _park(claim, student, course, "PLA_CAP", held_reservation)
    if course["level"] == "UPPER" and wanted > upper_remaining:
        return _park(claim, student, course, "UPPER_DIVISION_CAP", held_reservation)

    claim["assessment_status"] = "SUBMITTED"
    put_dt(claim, "submitted_at", db.clock)
    claim["priority_tier"] = "EXPEDITED" if claim["rush_requested"] else "STANDARD"
    if not held_reservation:
        take_reservation(student, claim, course)
    if claim["source_type"] != "PORTFOLIO" and rule is not None:
        claim["provisional_coverage_bp"] = crosswalk_provisional_coverage(rule, course)
    if first_submission and invoice_of_claim(claim["id"]) is None:
        invoice_service.create_invoice(claim)
    else:
        invoice_service.recompute(claim, student)
    touch(claim)
    return ok(claim_out(claim))


def _park(claim, student, course, hold_reason, held_reservation):
    """Capacity gate outcome: CAP_BLOCKED, no reservation, fee dimension untouched."""
    if held_reservation:
        release_reservation(student, claim, course)
    claim["assessment_status"] = "CAP_BLOCKED"
    claim["hold_reason"] = hold_reason
    touch(claim)
    return ok(claim_out(claim))


# ---------------------------------------------------------------- withdrawal
WITHDRAWABLE = ("DRAFT", "SUBMITTED", "UNDER_ASSESSMENT", "REVISION_REQUESTED", "CAP_BLOCKED")
RETENTION_BP = {
    "DRAFT": 0,
    "SUBMITTED": 0,
    "REVISION_REQUESTED": 0,
    "CAP_BLOCKED": 0,
    "UNDER_ASSESSMENT": 5000,
}


@bp.post("/pla-claims/<claim_id>/withdraw")
def withdraw_claim(claim_id):
    ctx = authenticate(WRITE_ROLES)
    claim = scoped_claim(ctx, claim_id)
    body = json_body()
    as_str(require(body, "withdraw_reason"), "withdraw_reason", 1)
    _not_terminal(claim)
    leaving = claim["assessment_status"]
    if leaving not in WITHDRAWABLE:
        raise ApiError("ERR_CLAIM_NOT_DRAFT")

    student = db.students.get(claim["student_id"])
    course = db.courses.get(claim["course_id"])
    released = leaving in RESERVING_STATES
    if released:
        release_reservation(student, claim, course)
    if leaving == "UNDER_ASSESSMENT":
        revoke_open_assignments(claim, "CLAIM_WITHDRAWN")

    portfolio = portfolio_of_claim(claim["id"])
    if portfolio is not None and portfolio["status"] in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED"):
        portfolio["status"] = "VOIDED"
        touch(portfolio)

    invoice = invoice_of_claim(claim["id"])
    if invoice is not None:
        invoice_service.settle(claim, invoice, student, RETENTION_BP[leaving])
    else:
        invoice_service.recompute_student_fee_net(student)

    claim["assessment_status"] = "WITHDRAWN"
    touch(claim)
    if released:
        unblock_waterfall(student)
    return ok(claim_out(claim))


# ---------------------------------------------------------------- revision
@bp.post("/pla-claims/<claim_id>/request-revision")
def request_revision(claim_id):
    authenticate([ROLE_COORDINATOR])
    claim = find_or_404("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    body = json_body()
    as_str(require(body, "revision_note"), "revision_note", 1)
    _not_terminal(claim)
    if claim["assessment_status"] != "UNDER_ASSESSMENT":
        raise ApiError("ERR_CLAIM_NOT_UNDER_ASSESSMENT")
    if claim["revision_round"] >= MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")

    claim["revision_round"] += 1
    claim["assessment_status"] = "REVISION_REQUESTED"
    revoke_open_assignments(claim, "REVISION_REQUESTED")
    portfolio = portfolio_of_claim(claim["id"])
    if portfolio is not None and portfolio["status"] in ("SUBMITTED", "LOCKED"):
        portfolio["status"] = "REVISION_REQUESTED"
        portfolio["revision_round"] += 1
        touch(portfolio)
    touch(claim)
    return ok(claim_out(claim))


# ---------------------------------------------------------------- award
@bp.post("/pla-claims/<claim_id>/award")
def award_claim(claim_id):
    authenticate([ROLE_COORDINATOR])
    claim = find_or_404("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    body = json_body()
    expected = as_int(require(body, "expected_student_version"), "expected_student_version", 0)
    awarded = None
    if present(body, "credits_awarded"):
        awarded = as_int(body["credits_awarded"], "credits_awarded", 0)

    student = db.students.get(claim["student_id"])
    course = db.courses.get(claim["course_id"])
    program = program_of_student(student)
    # rung 12: the concurrency gate precedes every state precondition
    if student is None or student["version"] != expected:
        raise ApiError("ERR_STALE_STUDENT_VERSION")
    # rung 15a
    if claim["assessment_status"] != "SCORED" or claim["assessor_recommendation"] != "PASS":
        raise ApiError("ERR_CLAIM_NOT_SCORED")
    # rungs 21 and 22
    rule, recommendation = _check_articulation_live(claim)
    # rung 25
    _check_enrolment(student, program)

    if awarded is None:
        awarded = claim["credits_requested"]
    # rung 37
    if awarded < 1 or awarded > claim["credits_requested"]:
        raise ApiError("ERR_AWARD_EXCEEDS_RECOMMENDATION")
    if rule is not None and awarded > rule["awarded_credits"]:
        raise ApiError("ERR_AWARD_EXCEEDS_RECOMMENDATION")
    if (recommendation is not None and course["level"] == "UPPER"
            and recommendation["recommended_level"] != "UPPER"):
        raise ApiError("ERR_LEVEL_MISMATCH")
    # rung 38
    if course["level"] == "UPPER" and awarded > upper_division_remaining(program, student, claim, course):
        raise ApiError("ERR_UPPER_DIVISION_CAP_EXCEEDED")
    # rung 39
    if awarded > remaining_reserved_inclusive(program, student, claim):
        raise ApiError("ERR_PLA_CAP_EXCEEDED")
    # rung 42
    _fee_gate(claim, ("PAID", "WAIVED"))

    requested = claim["credits_requested"]
    claim["assessment_status"] = "AWARDED"
    claim["credits_awarded"] = awarded
    student["pla_credits_reserved"] -= requested
    student["pla_credits_awarded"] += awarded
    if course["level"] == "UPPER":
        student["pla_upper_division_committed"] += awarded - requested
    touch(student)
    touch(claim)
    cap_block_cascade(student, claim["id"])
    return ok(claim_out(claim))


# ---------------------------------------------------------------- denial
@bp.post("/pla-claims/<claim_id>/deny")
def deny_claim(claim_id):
    authenticate([ROLE_COORDINATOR])
    claim = find_or_404("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    body = json_body()
    denial_reason = as_str(require(body, "denial_reason"), "denial_reason", 1)
    _not_terminal(claim)
    if claim["assessment_status"] != "SCORED":
        raise ApiError("ERR_CLAIM_NOT_SCORED")

    student = db.students.get(claim["student_id"])
    course = db.courses.get(claim["course_id"])
    claim["assessment_status"] = "DENIED"
    claim["denial_reason"] = denial_reason
    put_dt(claim, "appeal_deadline_at", add_hours(db.clock, APPEAL_WINDOW_HOURS))
    release_reservation(student, claim, course)
    touch(claim)
    unblock_waterfall(student)
    return ok(claim_out(claim))


# ---------------------------------------------------------------- transcript
@bp.post("/pla-claims/<claim_id>/transcript-posting")
def post_transcript(claim_id):
    authenticate([ROLE_REGISTRAR])
    claim = find_or_404("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    body = json_body()
    posted_term = as_str(require(body, "posted_term"), "posted_term", 1, 32)
    # rung 15a
    if claim["assessment_status"] != "AWARDED":
        raise ApiError("ERR_CLAIM_NOT_AWARDED")
    # rung 15c
    if claim["credit_status"] not in ("NOT_POSTED", "REVERSED"):
        raise ApiError("ERR_CREDIT_ALREADY_POSTED")

    student = db.students.get(claim["student_id"])
    course = db.courses.get(claim["course_id"])
    program = program_of_student(student)
    reposting = claim["credit_status"] == "REVERSED"
    amount = claim["credits_awarded"] or 0

    # rungs 21 and 22
    _check_articulation_live(claim)
    # rung 25
    _check_enrolment(student, program)
    # rung 26
    headroom = program["total_credits_required"] - program["residency_min_credits"]
    if student["transfer_credits_accepted"] + student["pla_credits_posted"] + amount > headroom:
        raise ApiError("ERR_RESIDENCY_REQUIREMENT_VIOLATION")
    # rung 38: the claim's own committed contribution is excluded before the test
    if course["level"] == "UPPER":
        committed = student["pla_upper_division_committed"] - (0 if reposting else amount)
        if amount > program["pla_upper_division_max_credits"] - committed:
            raise ApiError("ERR_UPPER_DIVISION_CAP_EXCEEDED")
    # rung 39: the posted-only variant is the cap gate here
    if amount > remaining_posted_only(program, student):
        raise ApiError("ERR_PLA_CAP_EXCEEDED")
    # the fiscal gate sits at the bottom of the ladder
    _fee_gate(claim, ("PAID", "WAIVED", "REFUNDED", "RETAINED"))

    claim["credit_status"] = "POSTED"
    claim["posted_term"] = posted_term
    claim["posted_credits"] = amount
    student["pla_credits_awarded"] -= amount
    student["pla_credits_posted"] += amount
    if reposting and course["level"] == "UPPER":
        student["pla_upper_division_committed"] += amount
    touch(student)
    touch(claim)
    return ok(claim_out(claim))


@bp.post("/pla-claims/<claim_id>/transcript-posting/reversal")
def reverse_transcript(claim_id):
    authenticate([ROLE_REGISTRAR])
    claim = find_or_404("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    body = json_body()
    as_str(require(body, "reversal_reason"), "reversal_reason", 1)
    # rung 15c
    if claim["credit_status"] != "POSTED":
        raise ApiError("ERR_CREDIT_NOT_POSTED")

    student = db.students.get(claim["student_id"])
    course = db.courses.get(claim["course_id"])
    amount = claim["posted_credits"] or 0
    claim["credit_status"] = "REVERSED"
    claim["posted_credits"] = 0
    student["pla_credits_posted"] -= amount
    student["pla_credits_awarded"] += amount
    if course["level"] == "UPPER":
        student["pla_upper_division_committed"] -= amount
    touch(student)
    touch(claim)
    unblock_waterfall(student)
    return ok(claim_out(claim))
