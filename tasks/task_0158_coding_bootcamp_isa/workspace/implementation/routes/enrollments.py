"""Enrollment, deposit + ISA opening, graduation/dismissal/withdrawal (PRD §3.3-3.5)."""
from flask import Blueprint, request

import errors
from db import db, stamp_create, touch, clock_iso
from middleware import require_role
from response import success
from services import serialize
from services.common import (
    get_json_body, parse_pagination, sort_by_created, paginate, lookup,
    require_fields, as_int, as_enum, as_number,
)
from services.derive import seats_committed, enrollment_attendance, recompute_isa_ledger

bp = Blueprint("enrollments", __name__)

FINANCING = {"ISA", "UPFRONT"}
REFUND_REASONS = {"COOLING_OFF", "WITHDRAWAL", "DISMISSAL_APPEAL"}


@bp.post("/enrollments")
def create_enrollment():
    require_role("AdmissionsOfficer")
    body = get_json_body()
    require_fields(body, ["applicant_id", "financing_choice", "deposit_amount_cents"])
    applicant_id = body["applicant_id"]
    if not isinstance(applicant_id, str):
        raise errors.invalid_request("applicant_id must be a string")
    applicant = lookup(db.applicants, applicant_id)  # existence first (PRD §2.6)

    financing = as_enum(body, "financing_choice", FINANCING)
    deposit_amount = as_int(body, "deposit_amount_cents", min_value=0)

    # ISA terms validated when financing is ISA
    isa_terms = None
    if financing == "ISA":
        require_fields(body, ["isa_income_share_pct", "isa_cap_cents",
                              "isa_term_months", "isa_income_threshold_cents"])
        share = as_number(body, "isa_income_share_pct", gt=0, le=0.5)
        cap = as_int(body, "isa_cap_cents", min_value=0)
        term = as_int(body, "isa_term_months", min_value=1)
        threshold = as_int(body, "isa_income_threshold_cents", min_value=0)
        isa_terms = (share, cap, term, threshold)

    # state: applicant must be ADMITTED
    if applicant["status"] != "ADMITTED":
        raise errors.invalid_state(f"Applicant is {applicant['status']}, expected ADMITTED")

    cohort = db.cohorts.get(applicant["cohort_id"])
    committed = seats_committed(cohort["id"]) if cohort else 0
    if cohort is None or cohort["capacity"] - committed < 1:
        raise errors.ApiError(errors.ERR_COHORT_FULL, 409, "Cohort has no available seat")

    # apply: applicant ADMITTED -> ENROLLED
    applicant["status"] = "ENROLLED"
    touch(applicant)

    e = {
        "applicant_id": applicant_id,
        "cohort_id": cohort["id"],
        "financing_choice": financing,
        "status": "ENROLLED",
        "enrolled_at": clock_iso(),
    }
    stamp_create(e)
    db.enrollments[e["id"]] = e

    # Deposit(HELD)
    dep = {
        "enrollment_id": e["id"],
        "amount_cents": deposit_amount,
        "status": "HELD",
        "refunded_amount_cents": 0,
    }
    stamp_create(dep)
    db.deposits[dep["id"]] = dep

    # ISAContract(PENDING) when financing=ISA
    if isa_terms is not None:
        share, cap, term, threshold = isa_terms
        contract = {
            "enrollment_id": e["id"],
            "income_share_pct": share,
            "cap_cents": cap,
            "term_months": term,
            "income_threshold_cents": threshold,
            "status": "PENDING",
            "_base_cap_cents": cap,
            "_amount_paid_cents": 0,
            "_payments_made_count": 0,
            "_remaining_cap_cents": cap,
        }
        stamp_create(contract)
        db.isa_contracts[contract["id"]] = contract

    return success(serialize.enrollment_view(e), status=201)


@bp.get("/enrollments/<eid>")
def get_enrollment(eid):
    require_role("AdmissionsOfficer", "ServicingOfficer", "ComplianceOfficer", "Student")
    e = lookup(db.enrollments, eid)
    return success(serialize.enrollment_view(e))


@bp.get("/enrollments")
def list_enrollments():
    require_role("AdmissionsOfficer", "ServicingOfficer", "ComplianceOfficer")
    limit, offset = parse_pagination()
    applicant_id = request.args.get("applicant_id")
    cohort_id = request.args.get("cohort_id")
    status = request.args.get("status")
    rows = list(db.enrollments.values())
    if applicant_id is not None:
        rows = [e for e in rows if e["applicant_id"] == applicant_id]
    if cohort_id is not None:
        rows = [e for e in rows if e["cohort_id"] == cohort_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.enrollment_view(e) for e in window], pagination=pg)


def _linked_isa(enrollment_id):
    return next((c for c in db.isa_contracts.values()
                 if c["enrollment_id"] == enrollment_id), None)


def _linked_deposit(enrollment_id):
    return next((d for d in db.deposits.values()
                 if d["enrollment_id"] == enrollment_id), None)


@bp.post("/enrollments/<eid>/graduate")
def graduate_enrollment(eid):
    require_role("AdmissionsOfficer")
    e = lookup(db.enrollments, eid)
    if e["status"] != "ACTIVE":
        raise errors.invalid_state(f"Enrollment is {e['status']}, expected ACTIVE")
    _, progress = enrollment_attendance(eid)
    if progress < 100:
        raise errors.ApiError(errors.ERR_PROGRESS_INCOMPLETE, 409,
                              "progress_pct must be >= 100 to graduate")
    e["status"] = "GRADUATED"
    touch(e)
    contract = _linked_isa(eid)
    if contract is not None and contract["status"] == "PENDING":
        contract["status"] = "ACTIVE"
        recompute_isa_ledger(contract)
        touch(contract)
    return success(serialize.enrollment_view(e))


@bp.post("/enrollments/<eid>/dismiss")
def dismiss_enrollment(eid):
    require_role("AdmissionsOfficer")
    e = lookup(db.enrollments, eid)
    if e["status"] != "ACTIVE":
        raise errors.invalid_state(f"Enrollment is {e['status']}, expected ACTIVE")
    attendance_pct, _ = enrollment_attendance(eid)
    if not (attendance_pct < 50):
        raise errors.ApiError(errors.ERR_DISMISSAL_NOT_JUSTIFIED, 409,
                              "attendance_pct must be < 50 to dismiss")
    e["status"] = "DISMISSED"
    touch(e)
    # void PENDING ISA; forfeit deposit
    contract = _linked_isa(eid)
    if contract is not None and contract["status"] == "PENDING":
        contract["status"] = "VOIDED"
        touch(contract)
    dep = _linked_deposit(eid)
    if dep is not None and dep["status"] == "HELD":
        dep["status"] = "FORFEITED"
        touch(dep)
    return success(serialize.enrollment_view(e))


@bp.post("/enrollments/<eid>/withdraw")
def withdraw_enrollment(eid):
    require_role("AdmissionsOfficer", "Student")
    e = lookup(db.enrollments, eid)
    if e["status"] not in ("ENROLLED", "ACTIVE"):
        raise errors.invalid_state(f"Enrollment is {e['status']}, cannot withdraw")
    body = get_json_body()
    from_state = e["status"]
    refund_reason = body.get("refund_reason")
    if refund_reason is not None and refund_reason not in REFUND_REASONS:
        raise errors.invalid_request("refund_reason invalid")

    e["status"] = "WITHDRAWN"
    touch(e)
    # void PENDING ISA
    contract = _linked_isa(eid)
    if contract is not None and contract["status"] == "PENDING":
        contract["status"] = "VOIDED"
        touch(contract)
    # open a RefundRequest(PENDING)
    if refund_reason is None:
        # withdrawal from ENROLLED -> COOLING_OFF or WITHDRAWAL; ACTIVE -> WITHDRAWAL
        refund_reason = "COOLING_OFF" if from_state == "ENROLLED" else "WITHDRAWAL"
    rr = {
        "enrollment_id": eid,
        "reason": refund_reason,
        "requested_at": clock_iso(),
        "gross_refund_cents": None,
        "net_refund_cents": None,
        "status": "PENDING",
    }
    stamp_create(rr)
    db.refund_requests[rr["id"]] = rr
    return success(serialize.enrollment_view(e))


@bp.get("/enrollments/<eid>/attendance")
def list_attendance(eid):
    require_role("AdmissionsOfficer", "ServicingOfficer")
    limit, offset = parse_pagination()
    lookup(db.enrollments, eid)
    rows = [r for r in db.attendance_records.values() if r["enrollment_id"] == eid]
    rows = sort_by_created(rows)
    window, pg = paginate(rows, limit, offset)
    return success([serialize.attendance_view(a) for a in window], pagination=pg)
