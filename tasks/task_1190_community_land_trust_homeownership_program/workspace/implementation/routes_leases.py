"""GroundLease, LeaseFee, DefaultNotice, and RefinanceRequest endpoints."""
from flask import Blueprint, g, jsonify

import db
import engine
from auth import require, require_household_owner
from errors import (
    ApiError, ERR_ARREARS_NOT_CLEARED, ERR_CERT_STALE, ERR_CURE_EVIDENCE_MISSING,
    ERR_CURE_WINDOW_EXPIRED, ERR_EDUCATION_INCOMPLETE, ERR_HOUSEHOLD_INELIGIBLE,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_MULTI_LEASE_PROHIBITED,
    ERR_REFERENCE_NOT_FOUND, ERR_REFINANCE_LIMIT_EXCEEDED, ERR_SO_DUTY_VIOLATION,
    ERR_STALE_VERSION, ERR_UNDERPAYMENT, ERR_UNIT_BLOCKED, ERR_UNIT_OCCUPIED,
)
from scope import (
    get_fee_or_404, get_lease_or_404, get_notice_or_404, get_program_or_404,
    get_refi_or_404, get_unit_or_404,
)
from util import (
    add_months, body, bump, new_entity, ok_object, opt_int, opt_str, paginated,
    query_int, query_str, req_dt, req_enum, req_int, req_str, ser_fee,
    ser_lease, ser_notice, ser_refi,
)

bp = Blueprint("leases", __name__)

LEASE_READ = ["PlatformAdmin", "ProgramAdmin", "ComplianceOfficer", "LeaseManager", "Household"]


def _check_lease_ownership(lease):
    require_household_owner(lease["household_id"])


# ---------------------------------------------------------------------------
# GroundLeases
# ---------------------------------------------------------------------------

@bp.post("/programs/<pid>/units/<uid>/leases")
@require(["LeaseManager"])
def create_lease(pid, uid):
    program = get_program_or_404(pid)
    get_unit_or_404(pid, uid)
    if program["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Program is not ACTIVE; new ground leases cannot be created")
    data = body()
    household_id = req_str(data, "household_id")
    start_date = req_dt(data, "start_date")
    purchase_price = req_int(data, "purchase_price_cents")

    household = db.store.households.get(household_id)
    if household is None or household["program_id"] != pid:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422,
                       "household_id does not resolve in this program scope")

    l = new_entity()
    l.update({
        "unit_id": uid,
        "household_id": household_id,
        "start_date": start_date,
        "end_date": add_months(start_date, program["ground_lease_term_years"] * 12),
        "monthly_fee_cents": None,
        "subsidy_locked_cents": None,
        "purchase_price_cents": purchase_price,
        "status": "DRAFT",
        "fee_arrears_cents": 0,
        "last_fee_charged_at": None,
        "resale_count": 0,
        "_pending_subsidy_cents": None,
        "_purchase_appraisal_cents": None,
    })
    db.store.leases[l["id"]] = l
    return jsonify(ok_object(ser_lease(l))), 201


@bp.get("/programs/<pid>/units/<uid>/leases")
@require(LEASE_READ)
def list_leases(pid, uid):
    get_unit_or_404(pid, uid)
    items = [l for l in db.store.leases.values() if l["unit_id"] == uid]
    if g.user_role == "Household":
        items = [l for l in items if l["household_id"] == g.user_id]
    status = query_str("status")
    if status:
        items = [l for l in items if l["status"] == status]
    return jsonify(paginated(items, ser_lease)), 200


@bp.get("/programs/<pid>/units/<uid>/leases/<lid>")
@require(LEASE_READ)
def get_lease(pid, uid, lid):
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    _check_lease_ownership(lease)
    return jsonify(ok_object(ser_lease(lease))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/activate")
@require(["LeaseManager"])
def activate_lease(pid, uid, lid):
    program = get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    if lease["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT lease can be activated")

    data = body()
    expected_unit_version = req_int(data, "expected_unit_version")

    household = db.store.households.get(lease["household_id"])
    now = db.get_now()

    # Business checks in scaffold priority order (9, 10, 12, 14, 17, 19).
    if household is None or household["eligibility_status"] != "ELIGIBLE":
        raise ApiError(ERR_HOUSEHOLD_INELIGIBLE, 409,
                       "Household must be ELIGIBLE to activate a lease")
    if unit["occupancy_status"] not in ("VACANT", "UNDER_CONTRACT"):
        raise ApiError(ERR_UNIT_BLOCKED, 409,
                       "Unit occupancy_status does not permit lease activation")
    if (household["education_completed_at"] is None
            or not engine.required_courses_satisfied(pid, household["id"], now)):
        raise ApiError(ERR_EDUCATION_INCOMPLETE, 409,
                       "Required education completions are missing or expired")
    cert = engine.latest_approved_cert(household["id"])
    if not engine.cert_is_fresh(cert, now):
        raise ApiError(ERR_CERT_STALE, 409,
                       "Latest approved certification is older than 24 months")
    for other in db.store.leases.values():
        if other["id"] == lease["id"] or other["household_id"] != household["id"]:
            continue
        other_unit = db.store.units.get(other["unit_id"])
        if other_unit and other_unit["program_id"] == pid and other["status"] == "ACTIVE":
            raise ApiError(ERR_MULTI_LEASE_PROHIBITED, 409,
                           "Household already holds an ACTIVE lease in this program")
    for other in db.store.leases.values():
        if (other["unit_id"] == uid and other["id"] != lease["id"]
                and other["status"] == "ACTIVE"):
            raise ApiError(ERR_UNIT_OCCUPIED, 409,
                           "Unit already has an ACTIVE ground lease")

    # OCC (priority 20).
    if expected_unit_version != unit["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_unit_version does not match the unit's current version")

    # Side effects (atomic bundle).
    pending_subsidy = lease.pop("_pending_subsidy_cents", None)
    lease["subsidy_locked_cents"] = (
        pending_subsidy if pending_subsidy is not None else unit["original_subsidy_cents"])
    lease["_purchase_appraisal_cents"] = unit["appraisal_value_cents"]
    lease["monthly_fee_cents"] = engine.compute_monthly_fee(program, household["ami_pct"])
    lease["status"] = "ACTIVE"
    bump(lease)

    unit["occupancy_status"] = "OCCUPIED"
    unit["current_lease_id"] = lease["id"]
    last_passed = unit["last_inspection_passed_at"]
    base = last_passed if last_passed is not None else lease["start_date"]
    unit["next_inspection_due_at"] = add_months(base, program["inspection_cycle_months"])
    bump(unit)

    household["active_lease_id"] = lease["id"]
    bump(household)

    engine.create_lease_fee(lease, now, now.year, now.month)

    # A matched waitlist entry fulfilled by this successor activation.
    for entry in db.store.waitlist.values():
        if (entry["household_id"] == household["id"] and entry["status"] == "MATCHED"
                and entry["matched_unit_id"] == uid):
            entry["status"] = "FULFILLED"
            bump(entry)
            if household["waitlist_entry_id"] == entry["id"]:
                household["waitlist_entry_id"] = None

    return jsonify(ok_object(ser_lease(lease))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/terminate")
@require(["LeaseManager"])
def terminate_lease(pid, uid, lid):
    get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    if lease["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE lease can be terminated")
    data = body()
    expected_lease_version = req_int(data, "expected_lease_version")

    open_notices = [n for n in db.store.notices.values()
                    if n["lease_id"] == lease["id"] and n["status"] == "OPEN"]
    if open_notices:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Lease has OPEN default notices and cannot be terminated")

    if expected_lease_version != lease["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_lease_version does not match the lease's current version")

    lease["status"] = "TERMINATED"
    bump(lease)
    unit["occupancy_status"] = "VACANT"
    unit["current_lease_id"] = None
    bump(unit)
    household = db.store.households.get(lease["household_id"])
    if household and household["active_lease_id"] == lease["id"]:
        household["active_lease_id"] = None
        bump(household)
    return jsonify(ok_object(ser_lease(lease))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/foreclose")
@require(["LeaseManager"])
def foreclose_lease(pid, uid, lid):
    get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    if lease["status"] not in ("IN_DEFAULT", "CURE_PERIOD"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an IN_DEFAULT or CURE_PERIOD lease can be foreclosed")
    data = body()
    expected_lease_version = req_int(data, "expected_lease_version")

    now = db.get_now()
    foreclosable = any(
        n for n in db.store.notices.values()
        if n["lease_id"] == lease["id"]
        and (n["status"] == "ESCALATED"
             or (n["status"] == "OPEN" and n["cure_deadline_at"] < now))
    )
    if not foreclosable:
        raise ApiError(ERR_CURE_WINDOW_EXPIRED, 409,
                       "No default notice past its cure deadline exists for this lease")

    if expected_lease_version != lease["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_lease_version does not match the lease's current version")

    lease["status"] = "FORECLOSED"
    bump(lease)
    unit["occupancy_status"] = "FORECLOSED"
    unit["current_lease_id"] = None
    bump(unit)
    household = db.store.households.get(lease["household_id"])
    if household:
        if household["active_lease_id"] == lease["id"]:
            household["active_lease_id"] = None
        household["eligibility_status"] = "SUSPENDED"
        household["_eligibility_lost_at"] = now
        bump(household)
    for notice in db.store.notices.values():
        if notice["lease_id"] == lease["id"] and notice["status"] == "OPEN":
            notice["status"] = "ESCALATED"
            bump(notice)
    for fee in db.store.fees.values():
        if fee["lease_id"] == lease["id"] and fee["status"] in ("PENDING", "LATE"):
            fee["status"] = "DEFAULTED"
    return jsonify(ok_object(ser_lease(lease))), 200


# ---------------------------------------------------------------------------
# LeaseFees
# ---------------------------------------------------------------------------

@bp.get("/programs/<pid>/units/<uid>/leases/<lid>/fees")
@require(LEASE_READ)
def list_fees(pid, uid, lid):
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    _check_lease_ownership(lease)
    items = [f for f in db.store.fees.values() if f["lease_id"] == lid]
    status = query_str("status")
    if status:
        items = [f for f in items if f["status"] == status]
    year = query_int("period_year")
    if year is not None:
        items = [f for f in items if f["period_year"] == year]
    month = query_int("period_month")
    if month is not None:
        items = [f for f in items if f["period_month"] == month]
    return jsonify(paginated(items, ser_fee)), 200


@bp.get("/programs/<pid>/units/<uid>/leases/<lid>/fees/<fid>")
@require(LEASE_READ)
def get_fee(pid, uid, lid, fid):
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    fee = get_fee_or_404(pid, uid, lid, fid)
    _check_lease_ownership(lease)
    return jsonify(ok_object(ser_fee(fee))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/fees/<fid>/pay")
@require(["Household"])
def pay_fee(pid, uid, lid, fid):
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    fee = get_fee_or_404(pid, uid, lid, fid)
    _check_lease_ownership(lease)
    if fee["status"] not in ("PENDING", "LATE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PENDING or LATE fee can be paid")
    data = body()
    payment = req_int(data, "payment_amount_cents")
    if payment < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "payment_amount_cents must be >= 0")
    if fee["paid_amount_cents"] + payment < fee["amount_cents"]:
        raise ApiError(ERR_UNDERPAYMENT, 402,
                       "Payment does not cover the fee amount")

    now = db.get_now()
    fee["paid_amount_cents"] += payment
    fee["status"] = "PAID"
    fee["paid_at"] = now
    lease["fee_arrears_cents"] = max(0, lease["fee_arrears_cents"] - fee["amount_cents"])
    bump(lease)
    return jsonify(ok_object(ser_fee(fee))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/fees/<fid>/waive")
@require(["LeaseManager"])
def waive_fee(pid, uid, lid, fid):
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    fee = get_fee_or_404(pid, uid, lid, fid)
    if fee["status"] not in ("PENDING", "LATE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PENDING or LATE fee can be waived")
    fee["status"] = "WAIVED"
    unpaid = fee["amount_cents"] - fee["paid_amount_cents"]
    lease["fee_arrears_cents"] = max(0, lease["fee_arrears_cents"] - unpaid)
    bump(lease)
    return jsonify(ok_object(ser_fee(fee))), 200


# ---------------------------------------------------------------------------
# DefaultNotices
# ---------------------------------------------------------------------------

@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/default-notices")
@require(["LeaseManager"])
def create_notice(pid, uid, lid):
    program = get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    if lease["status"] not in ("ACTIVE", "IN_DEFAULT", "CURE_PERIOD"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Default notices can only be issued against a live lease")
    data = body()
    kind = req_enum(data, "notice_kind", engine.NOTICE_KINDS)
    amount_due = req_int(data, "amount_due_cents")
    if amount_due < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "amount_due_cents must be >= 0")
    evidence = opt_str(data, "cure_evidence", "")

    notice = engine.issue_default_notice(
        program, unit, lease, kind, amount_due, g.user_id, db.get_now(),
        cure_evidence=evidence)
    return jsonify(ok_object(ser_notice(notice))), 201


@bp.get("/programs/<pid>/units/<uid>/leases/<lid>/default-notices")
@require(LEASE_READ)
def list_notices(pid, uid, lid):
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    _check_lease_ownership(lease)
    items = [n for n in db.store.notices.values() if n["lease_id"] == lid]
    status = query_str("status")
    if status:
        items = [n for n in items if n["status"] == status]
    kind = query_str("notice_kind")
    if kind:
        items = [n for n in items if n["notice_kind"] == kind]
    return jsonify(paginated(items, ser_notice)), 200


@bp.get("/programs/<pid>/units/<uid>/leases/<lid>/default-notices/<nid>")
@require(LEASE_READ)
def get_notice(pid, uid, lid, nid):
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    notice = get_notice_or_404(pid, uid, lid, nid)
    _check_lease_ownership(lease)
    return jsonify(ok_object(ser_notice(notice))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/default-notices/<nid>/cure")
@require(["LeaseManager"])
def cure_notice(pid, uid, lid, nid):
    get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    notice = get_notice_or_404(pid, uid, lid, nid)
    if notice["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN notice can be cured")

    data = body()
    evidence = data.get("cure_evidence")
    now = db.get_now()

    # Priority 7: MAINTENANCE cure evidence / passed follow-up inspection.
    if notice["notice_kind"] == "MAINTENANCE":
        passed_followup = any(
            i for i in db.store.inspections.values()
            if i["unit_id"] == uid and i["result"] == "PASSED"
            and i["completed_at"] is not None
            and i["completed_at"] > notice["issued_at"]
        )
        if not evidence or not isinstance(evidence, str) or not passed_followup:
            raise ApiError(ERR_CURE_EVIDENCE_MISSING, 422,
                           "MAINTENANCE cure requires cure_evidence and a PASSED "
                           "follow-up inspection after the notice was issued")
    elif not evidence or not isinstance(evidence, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "cure_evidence must be a non-empty string")

    # Priority 8: FEE_ARREARS requires arrears fully cleared.
    if notice["notice_kind"] == "FEE_ARREARS" and lease["fee_arrears_cents"] != 0:
        raise ApiError(ERR_ARREARS_NOT_CLEARED, 402,
                       "fee_arrears_cents must be 0 to cure a FEE_ARREARS notice")

    # Priority 13: cure window.
    if now > notice["cure_deadline_at"]:
        raise ApiError(ERR_CURE_WINDOW_EXPIRED, 409,
                       "The cure deadline for this notice has passed")

    notice["status"] = "CURED"
    notice["cured_at"] = now
    notice["cure_evidence"] = evidence
    bump(notice)
    engine.close_out_lease_if_no_open_notices(lease, now)
    return jsonify(ok_object(ser_notice(notice))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/default-notices/<nid>/escalate")
@require(["LeaseManager"])
def escalate_notice(pid, uid, lid, nid):
    get_program_or_404(pid)
    get_unit_or_404(pid, uid)
    get_lease_or_404(pid, uid, lid)
    notice = get_notice_or_404(pid, uid, lid, nid)
    if notice["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN notice can be escalated")
    notice["status"] = "ESCALATED"
    bump(notice)
    return jsonify(ok_object(ser_notice(notice))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/default-notices/<nid>/dismiss")
@require(["LeaseManager"])
def dismiss_notice(pid, uid, lid, nid):
    get_program_or_404(pid)
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    notice = get_notice_or_404(pid, uid, lid, nid)
    if notice["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN notice can be dismissed")
    notice["status"] = "DISMISSED"
    bump(notice)
    engine.close_out_lease_if_no_open_notices(lease, db.get_now())
    return jsonify(ok_object(ser_notice(notice))), 200


# ---------------------------------------------------------------------------
# RefinanceRequests
# ---------------------------------------------------------------------------

@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/refinance-requests")
@require(["Household"])
def create_refi(pid, uid, lid):
    program = get_program_or_404(pid)
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    _check_lease_ownership(lease)
    if lease["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Refinance requests require an ACTIVE lease")
    data = body()
    lender_name = req_str(data, "lender_name")
    loan = req_int(data, "requested_loan_cents")
    cash_out = opt_int(data, "requested_cash_out_cents", 0)
    appraised = req_int(data, "appraised_value_cents")
    if appraised == 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "appraised_value_cents must not be 0")

    household = db.store.households.get(lease["household_id"])
    if household is None or household["eligibility_status"] != "ELIGIBLE":
        raise ApiError(ERR_HOUSEHOLD_INELIGIBLE, 409,
                       "Household must be ELIGIBLE to submit a refinance request")

    ltv, max_loan = engine.compute_refi(program, loan, appraised)
    r = new_entity()
    r.update({
        "lease_id": lid,
        "lender_name": lender_name,
        "requested_loan_cents": loan,
        "requested_cash_out_cents": cash_out,
        "appraised_value_cents": appraised,
        "computed_ltv": ltv,
        "program_max_loan_cents": max_loan,
        "status": "SUBMITTED",
        "rejection_reason": "",
        "submitted_by": g.user_id,
        "reviewed_by": "",
    })
    db.store.refis[r["id"]] = r
    return jsonify(ok_object(ser_refi(r))), 201


@bp.get("/programs/<pid>/units/<uid>/leases/<lid>/refinance-requests")
@require(LEASE_READ)
def list_refis(pid, uid, lid):
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    _check_lease_ownership(lease)
    items = [r for r in db.store.refis.values() if r["lease_id"] == lid]
    status = query_str("status")
    if status:
        items = [r for r in items if r["status"] == status]
    return jsonify(paginated(items, ser_refi)), 200


@bp.get("/programs/<pid>/units/<uid>/leases/<lid>/refinance-requests/<rid>")
@require(LEASE_READ)
def get_refi(pid, uid, lid, rid):
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    refi = get_refi_or_404(pid, uid, lid, rid)
    _check_lease_ownership(lease)
    return jsonify(ok_object(ser_refi(refi))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/refinance-requests/<rid>/submit-to-lender")
@require(["Household"])
def submit_refi_to_lender(pid, uid, lid, rid):
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    refi = get_refi_or_404(pid, uid, lid, rid)
    _check_lease_ownership(lease)
    if refi["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SUBMITTED request can move to LENDER_REVIEW")
    refi["status"] = "LENDER_REVIEW"
    bump(refi)
    return jsonify(ok_object(ser_refi(refi))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/refinance-requests/<rid>/approve")
@require(["LeaseManager"])
def approve_refi(pid, uid, lid, rid):
    program = get_program_or_404(pid)
    unit = get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    refi = get_refi_or_404(pid, uid, lid, rid)
    if refi["status"] != "LENDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a LENDER_REVIEW request can be approved")
    if g.user_id == refi["submitted_by"]:
        raise ApiError(ERR_SO_DUTY_VIOLATION, 409,
                       "Reviewer must differ from the request submitter")
    if (refi["computed_ltv"] > program["max_refi_ltv_pct"]
            or refi["requested_cash_out_cents"] > program["max_equity_withdrawal_cents"]):
        raise ApiError(ERR_REFINANCE_LIMIT_EXCEEDED, 422,
                       "Refinance exceeds the program LTV or cash-out limits")
    if lease["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Lease must be ACTIVE to approve a refinance")
    open_notices = [n for n in db.store.notices.values()
                    if n["lease_id"] == lid and n["status"] == "OPEN"]
    if open_notices:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Lease has OPEN default notices; refinance cannot be approved")

    refi["status"] = "APPROVED"
    refi["reviewed_by"] = g.user_id
    bump(refi)
    unit["appraisal_value_cents"] = refi["appraised_value_cents"]
    bump(unit)
    return jsonify(ok_object(ser_refi(refi))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/refinance-requests/<rid>/reject")
@require(["LeaseManager"])
def reject_refi(pid, uid, lid, rid):
    get_program_or_404(pid)
    get_unit_or_404(pid, uid)
    get_lease_or_404(pid, uid, lid)
    refi = get_refi_or_404(pid, uid, lid, rid)
    if refi["status"] != "LENDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a LENDER_REVIEW request can be rejected")
    if g.user_id == refi["submitted_by"]:
        raise ApiError(ERR_SO_DUTY_VIOLATION, 409,
                       "Reviewer must differ from the request submitter")
    data = body()
    reason = req_str(data, "rejection_reason")
    refi["status"] = "REJECTED"
    refi["rejection_reason"] = reason
    refi["reviewed_by"] = g.user_id
    bump(refi)
    return jsonify(ok_object(ser_refi(refi))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/refinance-requests/<rid>/withdraw")
@require(["Household"])
def withdraw_refi(pid, uid, lid, rid):
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    refi = get_refi_or_404(pid, uid, lid, rid)
    _check_lease_ownership(lease)
    if refi["status"] not in ("SUBMITTED", "LENDER_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SUBMITTED or LENDER_REVIEW request can be withdrawn")
    refi["status"] = "WITHDRAWN"
    bump(refi)
    return jsonify(ok_object(ser_refi(refi))), 200


@bp.post("/programs/<pid>/units/<uid>/leases/<lid>/refinance-requests/<rid>/record")
@require(["LeaseManager"])
def record_refi(pid, uid, lid, rid):
    get_program_or_404(pid)
    get_unit_or_404(pid, uid)
    lease = get_lease_or_404(pid, uid, lid)
    refi = get_refi_or_404(pid, uid, lid, rid)
    if refi["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an APPROVED request can be recorded")
    data = body()
    expected_lease_version = req_int(data, "expected_lease_version")
    if expected_lease_version != lease["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_lease_version does not match the lease's current version")
    refi["status"] = "RECORDED"
    bump(refi)
    bump(lease)
    return jsonify(ok_object(ser_refi(refi))), 200
