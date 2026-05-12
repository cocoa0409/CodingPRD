"""Bill endpoints (create, issue, mark-settled, void)."""

import db
import errors
import helpers
import response
import serializers
from flask import Blueprint
from middleware import auth_required
from services import calculations


bp = Blueprint("bills", __name__)


VALID_BILLING_MODES = {"HOURLY", "FIXED", "CONTINGENT"}


def _ensure_not_archived(case):
    if case["status"] == "ARCHIVED":
        errors.raise_error(errors.ERR_CASE_ARCHIVED, "Case is archived.")


@bp.route("/cases/<cid>/bills", methods=["POST"])
@auth_required("PartnerLawyer")
def create_bill(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    _ensure_not_archived(case)

    body = helpers.get_json_body()
    billing_mode = helpers.require_enum(body, "billing_mode", VALID_BILLING_MODES)

    fixed_fee_cents = body.get("fixed_fee_cents")
    contingent_rate_bps = body.get("contingent_rate_bps")
    recovered_amount_cents = body.get("recovered_amount_cents", 0) or 0
    expense_reimbursement_cents = body.get("expense_reimbursement_cents", 0) or 0
    cost_recovery_cents = body.get("cost_recovery_cents", 0) or 0

    for f, v in [
        ("recovered_amount_cents", recovered_amount_cents),
        ("expense_reimbursement_cents", expense_reimbursement_cents),
        ("cost_recovery_cents", cost_recovery_cents),
    ]:
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            errors.raise_error(errors.ERR_VALIDATION_FAILED, f"{f} must be a non-negative integer.")

    if case["status"] != "AWAITING_SETTLEMENT":
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Bills can only be created when Case is in AWAITING_SETTLEMENT.",
        )

    if billing_mode == "FIXED":
        if fixed_fee_cents is None or isinstance(fixed_fee_cents, bool) or not isinstance(fixed_fee_cents, int) or fixed_fee_cents <= 0:
            errors.raise_error(
                errors.ERR_BILLING_MODE_INVALID,
                "FIXED billing requires fixed_fee_cents > 0.",
            )
    elif billing_mode == "CONTINGENT":
        if contingent_rate_bps is None or isinstance(contingent_rate_bps, bool) or not isinstance(contingent_rate_bps, int):
            errors.raise_error(
                errors.ERR_BILLING_MODE_INVALID,
                "CONTINGENT billing requires contingent_rate_bps in [1, 5000].",
            )
        if not (1 <= contingent_rate_bps <= 5000):
            errors.raise_error(
                errors.ERR_BILLING_MODE_INVALID,
                "contingent_rate_bps must be in [1, 5000].",
            )

    bid = db.new_id()
    common = helpers.common_create()
    bill = {
        "id": bid,
        "case_id": cid,
        "billing_mode": billing_mode,
        "fixed_fee_cents": int(fixed_fee_cents) if fixed_fee_cents is not None else None,
        "contingent_rate_bps": int(contingent_rate_bps) if contingent_rate_bps is not None else None,
        "recovered_amount_cents": int(recovered_amount_cents),
        "court_fee_cents": None,
        "attorney_fee_cents": None,
        "expense_reimbursement_cents": int(expense_reimbursement_cents),
        "cost_recovery_cents": int(cost_recovery_cents),
        "total_due_cents": None,
        "status": "DRAFT",
        **common,
    }
    db.bills[bid] = bill
    return response.created(serializers.bill_dict(bill))


@bp.route("/bills/<bid>/issue", methods=["POST"])
@auth_required("PartnerLawyer")
def issue_bill(bid):
    bill = db.bills.get(bid)
    if bill is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Bill {bid} not found.")
    case = db.cases.get(bill["case_id"])
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Parent case not found.")
    _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(bill, body.get("version"))

    if bill["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only DRAFT bills can be issued.")
    if case["status"] != "AWAITING_SETTLEMENT":
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Case must be AWAITING_SETTLEMENT to issue.",
        )

    # All TimeEntry rows must NOT be in LOGGED.
    for te in db.time_entries.values():
        if te["case_id"] != case["id"]:
            continue
        if te["status"] == "LOGGED":
            errors.raise_error(
                errors.ERR_INVALID_STATE,
                "All TimeEntry rows must be ADJUSTED, WRITTEN_OFF, or BILLED before issue.",
            )

    court_fee = calculations.compute_court_fee(case["case_type"], case["claim_amount_cents"])
    attorney_fee = calculations.compute_attorney_fee(bill, case)
    total = calculations.compute_total_due(
        court_fee,
        attorney_fee,
        bill.get("expense_reimbursement_cents", 0),
        bill.get("cost_recovery_cents", 0),
    )

    bill["court_fee_cents"] = int(court_fee)
    bill["attorney_fee_cents"] = int(attorney_fee)
    bill["total_due_cents"] = int(total)
    bill["status"] = "ISSUED"
    helpers.bump(bill)

    # Cascade: ADJUSTED -> BILLED for every time entry on this case.
    for te in db.time_entries.values():
        if te["case_id"] != case["id"]:
            continue
        if te["status"] == "ADJUSTED":
            te["status"] = "BILLED"
            helpers.bump(te)

    return response.ok(serializers.bill_dict(bill))


@bp.route("/bills/<bid>/mark-settled", methods=["POST"])
@auth_required("PartnerLawyer")
def mark_settled(bid):
    bill = db.bills.get(bid)
    if bill is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Bill {bid} not found.")
    case = db.cases.get(bill["case_id"])
    if case is not None:
        _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(bill, body.get("version"))

    if bill["status"] != "ISSUED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only ISSUED bills can be marked settled.")

    if not (bill.get("recovered_amount_cents", 0) > 0 or bill.get("cost_recovery_cents", 0) > 0):
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Settlement requires recovered_amount_cents > 0 OR cost_recovery_cents > 0.",
        )

    bill["status"] = "SETTLED"
    helpers.bump(bill)
    return response.ok(serializers.bill_dict(bill))


@bp.route("/bills/<bid>/void", methods=["POST"])
@auth_required("PartnerLawyer")
def void_bill(bid):
    bill = db.bills.get(bid)
    if bill is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Bill {bid} not found.")
    case = db.cases.get(bill["case_id"])
    if case is not None:
        _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(bill, body.get("version"))

    if bill["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only DRAFT bills can be voided.")

    # Revert all BILLED time entries on the case back to ADJUSTED.
    for te in db.time_entries.values():
        if te["case_id"] != bill["case_id"]:
            continue
        if te["status"] == "BILLED":
            te["status"] = "ADJUSTED"
            helpers.bump(te)

    bill["status"] = "VOIDED"
    helpers.bump(bill)
    return response.ok(serializers.bill_dict(bill))
