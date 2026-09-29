"""Appeals: filing, reviewer assignment and the three decisions (PRD 3.9)."""
from flask import Blueprint, request

from db import (appeals_of_claim, assignments_of_claim, db, invoice_of_claim,
                new_row, order_rows)
from errors import ApiError
from middleware import (ROLE_ASSESSOR, ROLE_COORDINATOR, ROLE_REGISTRAR,
                        ROLE_REVIEWER, ROLE_STUDENT, authenticate,
                        enforce_assessor_scope, enforce_panel_member,
                        find_or_404, scoped_claim)
from response import created, ok, ok_list, read_pagination
from serializers import appeal_out
from services import invoice as invoice_service
from services.capacity import (cap_block_cascade, program_of_student,
                               remaining_reserved_inclusive, take_reservation)
from services.selection import (assignment_window, create_assignment,
                                create_replacement, eligible_pool,
                                resolve_named)
from util import (MAX_APPEALS_PER_CLAIM, TERMINAL_ASSESSMENT_STATES, as_enum,
                  as_id, as_int, as_str, dtv, json_body, present, put_dt,
                  require, touch)

bp = Blueprint("appeals", __name__)

READ_ROLES = [ROLE_COORDINATOR, ROLE_REGISTRAR, ROLE_REVIEWER, ROLE_ASSESSOR,
              ROLE_STUDENT]
OPEN_APPEAL_STATUSES = ("FILED", "UNDER_REVIEW")
DECISIONS = ["UPHELD", "OVERTURNED", "REMANDED"]


def _prior_scorers(claim_id):
    """Every assessor who scored this claim, snapshotted at filing time."""
    rows = order_rows([a for a in assignments_of_claim(claim_id)
                       if a["status"] == "SCORING_COMPLETE"],
                      [(lambda r: r["created_at"], False)])
    ids = []
    for row in rows:
        if row["assessor_id"] not in ids:
            ids.append(row["assessor_id"])
    return ids


# ---------------------------------------------------------------- filing
@bp.post("/appeals")
def file_appeal():
    ctx = authenticate([ROLE_STUDENT])
    body = json_body()
    # rung 7 then rung 3, then rung 8
    claim_id = as_id(require(body, "claim_id"), "claim_id")
    claim = scoped_claim(ctx, claim_id)
    grounds = as_str(require(body, "grounds"), "grounds", 1)
    # rung 14
    if claim["assessment_status"] in TERMINAL_ASSESSMENT_STATES:
        raise ApiError("ERR_CLAIM_ALREADY_TERMINAL")
    # rung 15a
    if claim["assessment_status"] != "DENIED":
        raise ApiError("ERR_CLAIM_NOT_DENIED")
    # rung 28: strictly earlier than the deadline
    deadline = dtv(claim, "appeal_deadline_at")
    if deadline is None or db.clock >= deadline:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")
    # rung 33
    if claim["appeal_count"] >= MAX_APPEALS_PER_CLAIM:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED")
    for existing in appeals_of_claim(claim["id"]):
        if existing["status"] in OPEN_APPEAL_STATUSES:
            raise ApiError("ERR_APPEAL_LIMIT_REACHED")

    appeal = new_row("Appeal")
    appeal["claim_id"] = claim["id"]
    appeal["grounds"] = grounds
    appeal["status"] = "FILED"
    appeal["reviewer_assessor_id"] = None
    put_dt(appeal, "filed_at", db.clock)
    put_dt(appeal, "assigned_at", None)
    put_dt(appeal, "decided_at", None)
    appeal["decision_note"] = None
    appeal["prior_scorer_assessor_ids"] = _prior_scorers(claim["id"])
    db.appeals[appeal["id"]] = appeal

    claim["appeal_count"] += 1
    claim["assessment_status"] = "APPEAL_PENDING"
    touch(claim)
    student = db.students.get(claim["student_id"])
    invoice_service.recompute(claim, student)
    return created(appeal_out(appeal))


@bp.get("/appeals/<appeal_id>")
def read_appeal(appeal_id):
    authenticate(READ_ROLES)
    appeal = find_or_404("appeals", appeal_id, "ERR_APPEAL_NOT_FOUND")
    return ok(appeal_out(appeal))


@bp.get("/appeals")
def list_appeals():
    authenticate(READ_ROLES)
    limit, offset = read_pagination()
    rows = list(db.appeals.values())
    for name in ("claim_id", "reviewer_assessor_id", "status"):
        wanted = request.args.get(name)
        if wanted is not None and wanted != "":
            rows = [r for r in rows if r.get(name) == wanted]
    rows = order_rows(rows, [(lambda r: r["filed_at"], False)])
    return ok_list(rows, appeal_out, limit, offset)


# ---------------------------------------------------------------- reviewer assignment
@bp.post("/appeals/<appeal_id>/assign-reviewer")
def assign_reviewer(appeal_id):
    authenticate([ROLE_COORDINATOR])
    appeal = find_or_404("appeals", appeal_id, "ERR_APPEAL_NOT_FOUND")
    body = json_body()
    named = None
    if present(body, "reviewer_assessor_id"):
        named_id = as_id(body["reviewer_assessor_id"], "reviewer_assessor_id")
        named = db.assessors.get(named_id)
        if named is None:
            raise ApiError("ERR_ASSESSOR_NOT_FOUND")
    # rung 18
    if appeal["status"] != "FILED":
        raise ApiError("ERR_APPEAL_NOT_FILED")

    claim = db.claims.get(appeal["claim_id"])
    course = db.courses.get(claim["course_id"]) if claim else None
    if claim is None or course is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    window = assignment_window(claim, db.clock)
    if named is not None:
        # rungs 20, 31b and 32 in their catalogued order
        resolve_named(named, course, claim, (window[0], window[1]),
                      for_reviewer=True, appeal=appeal)
        reviewer = named
    else:
        pool = eligible_pool(course, claim, (window[0], window[1]),
                             for_reviewer=True, appeal=appeal)
        if not pool:
            raise ApiError("ERR_NO_ELIGIBLE_ASSESSOR")
        reviewer = pool[0]
    # rung 43: the filing fee must be settled before review may begin
    invoice = invoice_of_claim(claim["id"])
    if invoice is None or invoice["balance_due_cents"] != 0:
        raise ApiError("ERR_APPEAL_FEE_UNPAID")

    appeal["reviewer_assessor_id"] = reviewer["id"]
    put_dt(appeal, "assigned_at", db.clock)
    appeal["status"] = "UNDER_REVIEW"
    touch(appeal)
    return ok(appeal_out(appeal))


# ---------------------------------------------------------------- decision
def _articulation_live(claim):
    """Award-integrity recheck: rungs 21 and 22."""
    if claim["source_type"] == "PORTFOLIO":
        return None, None
    rule = db.rules.get(claim["articulation_rule_id"]) if claim.get("articulation_rule_id") else None
    recommendation = db.recommendations.get(rule["recommendation_id"]) if rule else None
    if rule is None or rule["status"] != "APPROVED":
        raise ApiError("ERR_ARTICULATION_NOT_APPROVED")
    if recommendation is None or recommendation["status"] != "PUBLISHED":
        raise ApiError("ERR_ARTICULATION_NOT_APPROVED")
    if rule["pinned_recommendation_version"] != recommendation["terms_version"]:
        raise ApiError("ERR_ARTICULATION_STALE_PIN")
    return rule, recommendation


@bp.post("/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    ctx = authenticate([ROLE_REVIEWER])
    # rung 5 precedes the existence check
    enforce_panel_member(ctx)
    appeal = find_or_404("appeals", appeal_id, "ERR_APPEAL_NOT_FOUND")
    if appeal["reviewer_assessor_id"] is not None:
        enforce_assessor_scope(ctx, appeal["reviewer_assessor_id"])
    body = json_body()
    decision = as_enum(require(body, "decision"), "decision", DECISIONS)
    note = None
    if present(body, "decision_note"):
        note = as_str(body["decision_note"], "decision_note", 1)
    awarded = None
    if decision == "OVERTURNED":
        awarded = as_int(require(body, "credits_awarded"), "credits_awarded", 1)
    elif present(body, "credits_awarded"):
        raise ApiError("ERR_INVALID_REQUEST", "credits_awarded is not allowed for this decision")
    # rung 18
    if appeal["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPEAL_NOT_UNDER_REVIEW")
    # rung 20
    if ctx.user_id in (appeal.get("prior_scorer_assessor_ids") or []):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    claim = db.claims.get(appeal["claim_id"])
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    student = db.students.get(claim["student_id"])
    course = db.courses.get(claim["course_id"])
    program = program_of_student(student) if student else None
    invoice = invoice_of_claim(claim["id"])

    if decision == "UPHELD":
        appeal["status"] = "UPHELD"
        claim["assessment_status"] = "DENIED_FINAL"
        if claim["fee_status"] == "PAID":
            claim["fee_status"] = "RETAINED"
            if invoice is not None:
                invoice["fee_status"] = "RETAINED"
                touch(invoice)
    elif decision == "OVERTURNED":
        # rung 25 then rungs 21 and 22
        if program is None or program["status"] != "ACTIVE":
            raise ApiError("ERR_PROGRAM_INACTIVE")
        _articulation_live(claim)
        appeal["status"] = "OVERTURNED"
        remaining = remaining_reserved_inclusive(program, student, claim)
        if remaining >= claim["credits_requested"]:
            claim["assessment_status"] = "AWARDED"
            claim["assessor_recommendation"] = "PASS"
            claim["credits_awarded"] = awarded
            student["pla_credits_awarded"] += awarded
            if course is not None and course["level"] == "UPPER":
                student["pla_upper_division_committed"] += awarded
            touch(student)
            if invoice is not None:
                invoice_service.settle(claim, invoice, student, 0)
            touch(claim)
            cap_block_cascade(student, claim["id"])
        else:
            claim["assessment_status"] = "CAP_BLOCKED"
            claim["hold_reason"] = "PLA_CAP"
            if invoice is not None:
                invoice_service.settle(claim, invoice, student, 0)
            touch(claim)
    else:
        appeal["status"] = "REMANDED"
        remaining = remaining_reserved_inclusive(program, student, claim) if program else -1
        if program is not None and remaining >= claim["credits_requested"]:
            claim["assessment_status"] = "UNDER_ASSESSMENT"
            claim["assessor_recommendation"] = None
            claim["verified_coverage_bp"] = None
            claim["denial_reason"] = None
            put_dt(claim, "appeal_deadline_at", None)
            take_reservation(student, claim, course)
            touch(claim)
            create_replacement(claim)
        else:
            claim["assessment_status"] = "CAP_BLOCKED"
            claim["hold_reason"] = "PLA_CAP"
            touch(claim)
        invoice_service.recompute(claim, student, extra_refund=invoice_service.APPEAL_FILING_FEE_CENTS)

    put_dt(appeal, "decided_at", db.clock)
    appeal["decision_note"] = note
    touch(appeal)
    return ok(appeal_out(appeal))
