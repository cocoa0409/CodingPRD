"""Incentive programs, the capacity pool, the waitlist and performance scoring
(PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint

import calc
import listing
import resolve
import validate as v
from auth import ALL_ROLES, authenticate, require_scope
from envelope import array_response, object_response, paginate
from errors import (
    ERR_COMMITMENT_BELOW_MINIMUM,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_ENROLLMENT_CLOSED,
    ERR_INCENTIVE_CAPACITY_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_MCC_NOT_ELIGIBLE_FOR_PROGRAM,
    ERR_MERCHANT_MISREPRESENTED,
    ERR_MERCHANT_NOT_VERIFIED,
    ERR_MERCHANT_UNDER_CATEGORY_REVIEW,
    ERR_STALE_VERSION,
    fail,
)
from store import new_row, serialize, serialize_many, sorted_rows, store, touch
from timeutil import dec2
from validate import FOUR_DIGITS

bp = Blueprint("incentive", __name__)


# ---------------------------------------------------------------------------
# Incentive programs
# ---------------------------------------------------------------------------

@bp.post("/incentive-programs")
def create_program():
    authenticate(["NetworkAdmin"])
    data = v.body()
    total = v.req_int(data, "total_capacity_cents", 1)
    minimum = v.req_int(data, "min_commitment_cents", 1)
    reopen = v.req_int(data, "reopen_threshold_cents", 0)
    threshold = v.req_number(data, "performance_threshold_pct", 0, 1000, 2)
    fields = {
        "program_name": v.req_str(data, "program_name", 1, 120),
        "eligible_mcc_codes": v.req_code_list(
            data, "eligible_mcc_codes", None, required=True,
            pattern=FOUR_DIGITS, non_empty=True,
        ),
        "total_capacity_cents": total,
        "min_commitment_cents": minimum,
        "reopen_threshold_cents": reopen,
        "performance_threshold_pct": dec2(threshold),
        "uncommitted_capacity_cents": total,
        "enrolled_count": 0,
        "enrollment_state": "OPEN",
    }
    if minimum > total:
        v.bad("'min_commitment_cents' may not exceed 'total_capacity_cents'.")
    if reopen < minimum:
        v.bad("'reopen_threshold_cents' must be at least 'min_commitment_cents'.")
    row = new_row(fields)
    store.incentive_programs[row["id"]] = row
    return object_response(serialize("IncentiveProgram", row), 201)


@bp.get("/incentive-programs/<row_id>")
def get_program(row_id):
    authenticate(ALL_ROLES)
    row = resolve.incentive_program(row_id)
    return object_response(serialize("IncentiveProgram", row))


@bp.get("/incentive-programs")
def list_programs():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.incentive_programs.values()))
    rows = listing.string_filter(rows, "enrollment_state", "enrollment_state")
    page, meta = paginate(rows)
    return array_response(serialize_many("IncentiveProgram", page), meta)


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------

@bp.post("/incentive-enrollments")
def create_enrollment():
    caller = authenticate(["AcquirerOps"])
    data = v.body()

    program_id = v.raw_id(data, "incentive_program_id")
    if program_id is not None:
        resolve.incentive_program(program_id)
    merchant_id = v.raw_id(data, "merchant_id")
    if merchant_id is not None:
        resolve.merchant(merchant_id)

    fields = {
        "incentive_program_id": v.req_str(data, "incentive_program_id"),
        "merchant_id": v.req_str(data, "merchant_id"),
        "committed_volume_cents": v.req_int(data, "committed_volume_cents", 1),
        "waitlist_requested": v.opt_bool(data, "waitlist_requested", False),
    }
    expected = v.req_int(data, "expected_incentive_program_version")

    program = store.incentive_programs[fields["incentive_program_id"]]
    merchant = store.merchants[fields["merchant_id"]]
    require_scope(caller, merchant["acquirer_id"])

    committed = fields["committed_volume_cents"]
    waitlist_requested = fields["waitlist_requested"]

    # Priority 9.
    if program["enrollment_state"] == "CLOSED_FULL" and not waitlist_requested:
        fail(ERR_ENROLLMENT_CLOSED)
    # Priority 12.
    if expected != int(program["version"]):
        fail(ERR_STALE_VERSION)
    # Priorities 13, 14 and 15.
    if merchant["mcc_status"] == "MISREPRESENTED":
        fail(ERR_MERCHANT_MISREPRESENTED)
    if merchant["mcc_status"] == "UNDER_REVIEW":
        fail(ERR_MERCHANT_UNDER_CATEGORY_REVIEW)
    if merchant["mcc_status"] != "VERIFIED":
        fail(ERR_MERCHANT_NOT_VERIFIED)
    # Priority 27.
    if merchant["assigned_mcc"] not in (program.get("eligible_mcc_codes") or []):
        fail(ERR_MCC_NOT_ELIGIBLE_FOR_PROGRAM)
    # Priority 31.
    for existing in calc.enrollments_of_merchant(merchant["id"]):
        if (existing["incentive_program_id"] == program["id"]
                and existing["status"] in calc.BLOCKING_ENROLLMENT_STATUSES):
            fail(ERR_DUPLICATE_ENROLLMENT)
    # Priority 32.
    if committed < int(program["min_commitment_cents"]):
        fail(ERR_COMMITMENT_BELOW_MINIMUM)

    fits = committed <= int(program["uncommitted_capacity_cents"])
    to_waitlist = waitlist_requested and (
        program["enrollment_state"] == "CLOSED_FULL" or not fits
    )
    # Priority 33 is skipped entirely for a waitlist admission.
    if not to_waitlist and not fits:
        fail(ERR_INCENTIVE_CAPACITY_EXCEEDED)

    fields.update({
        "status": "WAITLISTED" if to_waitlist else "ENROLLED",
        "enrolled_at": None if to_waitlist else store.now_ms(),
        "last_evaluated_basis": None,
        "achieved_volume_cents": 0,
        "performance_score_pct": Decimal("0.00"),
        "gross_assessed_volume_cents": 0,
        "tier_code": None,
        "incentive_credit_cents": 0,
        "net_assessed_volume_cents": 0,
        "probation_count": 0,
        "withdrawal_reason": None,
    })
    row = new_row(fields)
    store.enrollments[row["id"]] = row
    if to_waitlist:
        # A waitlisted row takes no capacity debit but still moves the program.
        calc.recompute_capacity(program)
        touch(program)
    else:
        calc.after_capacity_debit(program)
    return object_response(serialize("IncentiveEnrollment", row), 201)


@bp.post("/incentive-enrollments/<row_id>/evaluate-performance")
def evaluate_performance(row_id):
    authenticate(["NetworkAdmin"])
    row = resolve.enrollment(row_id)
    data = v.body()
    basis = v.req_enum(data, "basis", ("TRAILING", "PROJECTED"))
    if row["status"] not in ("ENROLLED", "PROBATION"):
        fail(ERR_INVALID_STATE, "Only an ENROLLED or PROBATION enrollment may be scored.")

    program = store.incentive_programs.get(row["incentive_program_id"])
    achieved = calc.achieved_volume(row, basis)
    score = calc.performance_score(achieved, int(row["committed_volume_cents"]))
    gross = calc.gross_assessed_volume(row)
    tier, credit, net = calc.tier_and_credit(gross)

    row["last_evaluated_basis"] = basis
    row["achieved_volume_cents"] = achieved
    row["performance_score_pct"] = score
    row["gross_assessed_volume_cents"] = gross
    row["tier_code"] = tier
    row["incentive_credit_cents"] = credit
    row["net_assessed_volume_cents"] = net

    threshold = program["performance_threshold_pct"] if program else Decimal("0.00")
    passing = score >= threshold
    released = False
    if row["status"] == "ENROLLED" and not passing:
        row["status"] = "PROBATION"
        row["probation_count"] = int(row["probation_count"]) + 1
    elif row["status"] == "PROBATION" and passing:
        row["status"] = "ENROLLED"
    elif row["status"] == "PROBATION" and not passing:
        row["status"] = "TERMINATED_SHORTFALL"
        released = True
    touch(row)
    if released and program is not None:
        calc.after_capacity_release(program)
    return object_response(serialize("IncentiveEnrollment", row))


@bp.post("/incentive-enrollments/<row_id>/withdraw")
def withdraw_enrollment(row_id):
    caller = authenticate(["AcquirerOps", "NetworkAdmin"])
    row = resolve.enrollment(row_id)
    data = v.body()
    reason = v.req_str(data, "withdrawal_reason", 1, 1000)
    merchant = store.merchants.get(row["merchant_id"])
    require_scope(caller, merchant["acquirer_id"] if merchant else None)
    if row["status"] not in ("ENROLLED", "PROBATION", "WAITLISTED"):
        fail(ERR_INVALID_STATE, "This enrollment can no longer be withdrawn.")
    held_capacity = row["status"] in calc.COMMITTED_STATUSES
    row["status"] = "WITHDRAWN"
    row["withdrawal_reason"] = reason
    touch(row)
    program = store.incentive_programs.get(row["incentive_program_id"])
    if program is not None:
        if held_capacity:
            calc.after_capacity_release(program)
        else:
            # A waitlisted row never debited the pool; the invariant still holds.
            calc.recompute_capacity(program)
            touch(program)
    return object_response(serialize("IncentiveEnrollment", row))


@bp.get("/incentive-enrollments/<row_id>")
def get_enrollment(row_id):
    caller = authenticate(ALL_ROLES)
    row = resolve.enrollment(row_id)
    merchant = store.merchants.get(row["merchant_id"])
    require_scope(caller, merchant["acquirer_id"] if merchant else None)
    return object_response(serialize("IncentiveEnrollment", row))


@bp.get("/incentive-enrollments")
def list_enrollments():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.enrollments.values()))
    rows = listing.apply_string_filters(rows, [
        ("incentive_program_id", "incentive_program_id"),
        ("merchant_id", "merchant_id"),
        ("status", "status"),
    ])
    page, meta = paginate(rows)
    return array_response(serialize_many("IncentiveEnrollment", page), meta)
