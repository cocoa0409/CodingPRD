"""Leak adjustments, payment arrangements and board appeals."""

from flask import Blueprint, g

import calc
import domain
from core import (
    ADJUSTMENT_STATUSES,
    APPEAL_FILING_DAYS,
    APPEAL_STATUSES,
    ARRANGEMENT_STATUSES,
    DECISIONS,
    HEARING_DOCKET_CAPACITY,
    HEARING_MIN_NOTICE_DAYS,
    LEAK_TYPES,
    MAX_ARRANGEMENT_REINSTATEMENTS,
    MAX_INSTALLMENTS,
    MISSED_PAYMENTS_TO_DEFAULT,
    REMAND_MAX,
    VARIANTS,
    Body,
    add_days,
    as_date,
    as_dt,
    base_record,
    clock_date,
    clock_now,
    created_response,
    date_str,
    endpoint,
    err,
    get_or_404,
    insert,
    is_customer,
    list_result,
    maybe,
    now_iso,
    object_response,
    parse_date,
    q_date,
    q_enum,
    q_str,
    register_new,
    require_own_account,
    rows,
    serialize,
    touch,
)

bp = Blueprint("routes_d", __name__)


# ---------------------------------------------------------------------------
# LeakAdjustment helpers
# ---------------------------------------------------------------------------
def _blank_adjustment():
    rec = base_record()
    rec.update(
        {
            "investigation_id": None,
            "bill_id": None,
            "leak_type": None,
            "variant_applied": None,
            "excess_gallons": 0,
            "water_credit_cents": 0,
            "sewer_relief_gallons": 0,
            "sewer_credit_cents": 0,
            "gross_credit_cents": 0,
            "cap_cents": 0,
            "capped_credit_cents": 0,
            "cap_applied": False,
            "admin_fee_charged_cents": 0,
            "net_credit_cents": 0,
            "status": "DRAFT",
            "created_by_user_id": None,
            "approved_by_user_id": None,
            "posted_at": None,
            "supersedes_adjustment_id": None,
            "board_ordered": False,
            "return_reason": None,
            "denial_reason": None,
            "reversal_reason": None,
        }
    )
    return rec


def _apply_credit(adjustment, bill):
    period = domain.period_of_bill(bill)
    schedule = domain.schedule_of_bill(bill)
    computed = calc.leak_adjustment_credit(
        bill,
        schedule,
        period["season"],
        adjustment["leak_type"],
        bill["seasonal_baseline_gallons"],
        board_ordered=bool(adjustment["board_ordered"]),
    )
    adjustment.update(computed)


def _adjustment_account(adjustment):
    bill = maybe("bills", adjustment["bill_id"])
    return maybe("service_accounts", bill["account_id"]) if bill else None


@bp.route("/leak-adjustments", methods=["POST"])
@endpoint("CustomerServiceRep")
def create_leak_adjustment():
    body = Body()
    investigation_id = body.string("investigation_id")
    bill_id = body.string("bill_id")
    leak_type = body.enum("leak_type", LEAK_TYPES)
    expected_investigation_version = body.integer("expected_investigation_version")

    investigation = get_or_404("investigations", investigation_id)
    bill = get_or_404("bills", bill_id)

    if expected_investigation_version != investigation["version"]:
        err(
            "ERR_STALE_INVESTIGATION_VERSION",
            "expected_investigation_version does not match the investigation's version",
        )
    if investigation["status"] != "DETERMINED":
        err("ERR_INVALID_STATE_TRANSITION", "the investigation is not DETERMINED")

    meter_error = investigation["leak_determination"] == "METER_ERROR"
    proofs = domain.verified_proofs(investigation["id"])
    if not meter_error:
        if not proofs:
            err("ERR_REPAIR_PROOF_REQUIRED", "a VERIFIED repair proof is required")
        if leak_type not in set(p["leak_type"] for p in proofs):
            err(
                "ERR_LEAK_TYPE_MISMATCH",
                "leak_type does not match any VERIFIED repair proof",
            )
    if bill_id != investigation["bill_id"]:
        err("ERR_ADJUSTMENT_BILL_MISMATCH", "bill_id does not match the investigation's bill")

    rec = _blank_adjustment()
    rec["investigation_id"] = investigation["id"]
    rec["bill_id"] = bill["id"]
    rec["leak_type"] = leak_type
    rec["created_by_user_id"] = g.user_id
    _apply_credit(rec, bill)
    insert("leak_adjustments", register_new(rec))

    investigation["status"] = "ADJUSTMENT_PENDING"
    domain.sync_investigation_hold(investigation)
    touch(investigation)
    return created_response(serialize(rec))


@bp.route("/leak-adjustments", methods=["GET"])
@endpoint("CustomerServiceRep", "BillingSupervisor", "SystemAdmin", "Customer", "UtilityBoardClerk")
def list_leak_adjustments():
    investigation_id = q_str("investigation_id")
    bill_id = q_str("bill_id")
    supersedes_adjustment_id = q_str("supersedes_adjustment_id")
    status = q_enum("status", ADJUSTMENT_STATUSES)
    variant_applied = q_enum("variant_applied", VARIANTS)
    if investigation_id is not None:
        inv = maybe("investigations", investigation_id)
        if inv is not None:
            require_own_account(inv["account_id"])
    if bill_id is not None:
        bill = maybe("bills", bill_id)
        if bill is not None:
            require_own_account(bill["account_id"])

    result = []
    for rec in rows("leak_adjustments"):
        if investigation_id is not None and rec["investigation_id"] != investigation_id:
            continue
        if bill_id is not None and rec["bill_id"] != bill_id:
            continue
        if (
            supersedes_adjustment_id is not None
            and rec.get("supersedes_adjustment_id") != supersedes_adjustment_id
        ):
            continue
        if status is not None and rec["status"] != status:
            continue
        if variant_applied is not None and rec["variant_applied"] != variant_applied:
            continue
        result.append(rec)
    if is_customer():
        owned = set(b["id"] for b in rows("bills") if b["account_id"] == g.user_id)
        result = [r for r in result if r["bill_id"] in owned]
    return list_result(result)


@bp.route("/leak-adjustments/<rid>", methods=["GET"])
@endpoint("CustomerServiceRep", "BillingSupervisor", "SystemAdmin", "Customer", "UtilityBoardClerk")
def get_leak_adjustment(rid):
    rec = get_or_404("leak_adjustments", rid)
    bill = maybe("bills", rec["bill_id"])
    if bill is not None:
        require_own_account(bill["account_id"])
    return object_response(serialize(rec))


@bp.route("/leak-adjustments/<rid>/submit", methods=["POST"])
@endpoint("CustomerServiceRep")
def submit_leak_adjustment(rid):
    rec = get_or_404("leak_adjustments", rid)
    investigation = maybe("investigations", rec["investigation_id"])
    if rec["status"] != "DRAFT":
        err("ERR_INVALID_STATE_TRANSITION", "only a DRAFT adjustment may be submitted")
    if investigation is None or investigation["status"] != "ADJUSTMENT_PENDING":
        err("ERR_INVALID_STATE_TRANSITION", "the investigation is not ADJUSTMENT_PENDING")
    if investigation["leak_determination"] != "METER_ERROR":
        proofs = domain.verified_proofs(investigation["id"])
        if rec["leak_type"] not in set(p["leak_type"] for p in proofs):
            err(
                "ERR_INVALID_STATE_TRANSITION",
                "a VERIFIED repair proof of the same leak_type is required",
            )
    bill = maybe("bills", rec["bill_id"])
    _apply_credit(rec, bill)
    rec["status"] = "PENDING_APPROVAL"
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/leak-adjustments/<rid>/return", methods=["POST"])
@endpoint("BillingSupervisor")
def return_leak_adjustment(rid):
    body = Body()
    return_reason = body.string("return_reason")
    rec = get_or_404("leak_adjustments", rid)
    if rec["status"] != "PENDING_APPROVAL":
        err("ERR_INVALID_STATE_TRANSITION", "only a PENDING_APPROVAL adjustment may be returned")
    rec["status"] = "DRAFT"
    rec["return_reason"] = return_reason
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/leak-adjustments/<rid>/approve", methods=["POST"])
@endpoint("BillingSupervisor")
def approve_leak_adjustment(rid):
    rec = get_or_404("leak_adjustments", rid)
    investigation = maybe("investigations", rec["investigation_id"])
    bill = maybe("bills", rec["bill_id"])
    period = domain.period_of_bill(bill) if bill else None

    if rec["status"] != "PENDING_APPROVAL":
        err("ERR_INVALID_STATE_TRANSITION", "only a PENDING_APPROVAL adjustment may be approved")
    if investigation is not None and g.user_id == investigation["determination_by_user_id"]:
        err(
            "ERR_SEGREGATION_OF_DUTIES",
            "the approver must differ from the user who recorded the determination",
        )
    if period is not None and period["status"] == "LOCKED":
        err("ERR_BILLING_PERIOD_LOCKED", "the billing period is LOCKED")
    if domain.rolling_window_conflict(rec, bill["account_id"], as_date(period["end_date"])):
        err(
            "ERR_LEAK_ADJUSTMENT_CAP_EXCEEDED",
            "another adjustment already sits inside the rolling twelve-month window",
        )

    account = maybe("service_accounts", bill["account_id"])
    # CASCADE LINK 1 -- ledger inserts first
    domain.add_ledger_entry(
        account,
        "CREDIT",
        "LEAK_ADJUSTMENT_CREDIT",
        -int(rec["capped_credit_cents"]),
        bill_id=bill["id"],
        source_id=rec["id"],
    )
    if int(rec["admin_fee_charged_cents"] or 0) > 0:
        domain.add_ledger_entry(
            account,
            "CHARGE",
            "LEAK_ADJUSTMENT_ADMIN_FEE",
            int(rec["admin_fee_charged_cents"]),
            bill_id=bill["id"],
            source_id=rec["id"],
        )

    rec["status"] = "POSTED"
    rec["approved_by_user_id"] = g.user_id
    rec["posted_at"] = now_iso()
    touch(rec)

    if bill["billing_status"] == "UNDER_INVESTIGATION":
        bill["billing_status"] = "ADJUSTED"
    domain.recompute_adjusted_total(bill)
    touch(bill)

    if investigation is not None and investigation["status"] == "ADJUSTMENT_PENDING":
        investigation["status"] = "RESOLVED"
        domain.sync_investigation_hold(investigation)
        touch(investigation)

    domain.refresh_account(account)
    return object_response(serialize(rec))


@bp.route("/leak-adjustments/<rid>/deny", methods=["POST"])
@endpoint("BillingSupervisor")
def deny_leak_adjustment(rid):
    body = Body()
    denial_reason = body.string("denial_reason")
    rec = get_or_404("leak_adjustments", rid)
    investigation = maybe("investigations", rec["investigation_id"])
    bill = maybe("bills", rec["bill_id"])
    period = domain.period_of_bill(bill) if bill else None

    if rec["status"] != "PENDING_APPROVAL":
        err("ERR_INVALID_STATE_TRANSITION", "only a PENDING_APPROVAL adjustment may be denied")
    if investigation is not None and g.user_id == investigation["determination_by_user_id"]:
        err(
            "ERR_SEGREGATION_OF_DUTIES",
            "the denier must differ from the user who recorded the determination",
        )
    if period is not None and period["status"] == "LOCKED":
        err("ERR_BILLING_PERIOD_LOCKED", "the billing period is LOCKED")

    rec["status"] = "DENIED"
    rec["denial_reason"] = denial_reason
    touch(rec)
    if investigation is not None and investigation["status"] == "ADJUSTMENT_PENDING":
        investigation["status"] = "DETERMINED"
        domain.sync_investigation_hold(investigation)
        touch(investigation)
    return object_response(serialize(rec))


@bp.route("/leak-adjustments/<rid>/reverse", methods=["POST"])
@endpoint("BillingSupervisor")
def reverse_leak_adjustment(rid):
    body = Body()
    reversal_reason = body.string("reversal_reason")
    rec = get_or_404("leak_adjustments", rid)
    investigation = maybe("investigations", rec["investigation_id"])
    bill = maybe("bills", rec["bill_id"])
    period = domain.period_of_bill(bill) if bill else None

    if rec["status"] != "POSTED":
        err("ERR_INVALID_STATE_TRANSITION", "only a POSTED adjustment may be reversed")
    if investigation is not None and g.user_id == investigation["determination_by_user_id"]:
        err(
            "ERR_SEGREGATION_OF_DUTIES",
            "the reverser must differ from the user who recorded the determination",
        )
    if period is not None and period["status"] == "LOCKED":
        err("ERR_BILLING_PERIOD_LOCKED", "the billing period is LOCKED")

    account = maybe("service_accounts", bill["account_id"])
    domain.add_ledger_entry(
        account,
        "REVERSAL",
        "LEAK_ADJUSTMENT_REVERSAL",
        int(rec["capped_credit_cents"]) - int(rec["admin_fee_charged_cents"] or 0),
        bill_id=bill["id"],
        source_id=rec["id"],
    )

    rec["status"] = "REVERSED"
    rec["reversal_reason"] = reversal_reason
    touch(rec)

    if bill["billing_status"] == "ADJUSTED":
        bill["billing_status"] = "ISSUED"
    domain.recompute_adjusted_total(bill)
    touch(bill)

    if investigation is not None and investigation["status"] == "RESOLVED":
        investigation["status"] = "DETERMINED"
        domain.sync_investigation_hold(investigation)
        touch(investigation)

    domain.refresh_account(account)
    return object_response(serialize(rec))


# ---------------------------------------------------------------------------
# PaymentArrangement
# ---------------------------------------------------------------------------
@bp.route("/payment-arrangements", methods=["POST"])
@endpoint("CustomerServiceRep", "Customer")
def create_payment_arrangement():
    body = Body()
    account_id = body.string("account_id")
    bill_id = body.string("bill_id")
    total_amount_cents = body.integer("total_amount_cents", minimum=1)
    down_payment_cents = body.integer("down_payment_cents", minimum=0)
    installment_count = body.integer("installment_count", minimum=1)
    expected_account_version = body.integer("expected_account_version")
    investigation_id = body.string("investigation_id", required=False)

    account = get_or_404("service_accounts", account_id)
    bill = get_or_404("bills", bill_id)
    investigation = None
    if investigation_id is not None:
        investigation = get_or_404("investigations", investigation_id)

    require_own_account(account["id"])

    if expected_account_version != account["version"]:
        err(
            "ERR_STALE_ACCOUNT_VERSION",
            "expected_account_version does not match the account's version",
        )
    if installment_count > MAX_INSTALLMENTS:
        err(
            "ERR_INSTALLMENT_LIMIT_EXCEEDED",
            "installment_count may not exceed %d" % MAX_INSTALLMENTS,
        )
    if bill["account_id"] != account_id:
        err("ERR_ARRANGEMENT_ACCOUNT_MISMATCH", "the bill belongs to another account")
    if investigation is not None and investigation["account_id"] != account_id:
        err(
            "ERR_ARRANGEMENT_ACCOUNT_MISMATCH",
            "the investigation belongs to another account",
        )

    minimum_down = calc.minimum_down_payment(total_amount_cents)
    if down_payment_cents < minimum_down or down_payment_cents > total_amount_cents:
        err(
            "ERR_DOWN_PAYMENT_TOO_LOW",
            "down_payment_cents must be between %d and %d"
            % (minimum_down, total_amount_cents),
        )
    if total_amount_cents != int(bill["adjusted_total_cents"] or 0):
        err(
            "ERR_ARRANGEMENT_AMOUNT_MISMATCH",
            "total_amount_cents must equal the bill's adjusted_total_cents",
        )

    installment_cents, final_installment_cents = calc.arrangement_schedule(
        total_amount_cents, down_payment_cents, installment_count
    )

    rec = base_record()
    rec.update(
        {
            "account_id": account["id"],
            "bill_id": bill["id"],
            "investigation_id": investigation["id"] if investigation else None,
            "total_amount_cents": total_amount_cents,
            "down_payment_cents": down_payment_cents,
            "installment_count": installment_count,
            "installment_cents": installment_cents,
            "final_installment_cents": final_installment_cents,
            "paid_installment_count": 0,
            "missed_payment_count": 0,
            "reinstatement_count": 0,
            "status": "PROPOSED",
        }
    )
    insert("payment_arrangements", register_new(rec))

    for other in domain.arrangements_of_account(account["id"]):
        if other["id"] == rec["id"]:
            continue
        if other["status"] in ("PROPOSED", "ACTIVE"):
            other["status"] = "CANCELLED"
            touch(other)

    touch(account)
    domain.refresh_account(account)
    return created_response(serialize(rec))


@bp.route("/payment-arrangements", methods=["GET"])
@endpoint("CustomerServiceRep", "Customer", "BillingSupervisor", "SystemAdmin")
def list_payment_arrangements():
    account_id = q_str("account_id")
    bill_id = q_str("bill_id")
    investigation_id = q_str("investigation_id")
    status = q_enum("status", ARRANGEMENT_STATUSES)
    if account_id is not None:
        require_own_account(account_id)
    if bill_id is not None:
        bill = maybe("bills", bill_id)
        if bill is not None:
            require_own_account(bill["account_id"])
    if investigation_id is not None:
        inv = maybe("investigations", investigation_id)
        if inv is not None:
            require_own_account(inv["account_id"])

    result = []
    for rec in rows("payment_arrangements"):
        if account_id is not None and rec["account_id"] != account_id:
            continue
        if bill_id is not None and rec["bill_id"] != bill_id:
            continue
        if investigation_id is not None and rec.get("investigation_id") != investigation_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        result.append(rec)
    if is_customer():
        result = [r for r in result if r["account_id"] == g.user_id]
    return list_result(result)


@bp.route("/payment-arrangements/<rid>", methods=["GET"])
@endpoint("CustomerServiceRep", "Customer", "BillingSupervisor", "SystemAdmin")
def get_payment_arrangement(rid):
    rec = get_or_404("payment_arrangements", rid)
    require_own_account(rec["account_id"])
    return object_response(serialize(rec))


@bp.route("/payment-arrangements/<rid>/activate", methods=["POST"])
@endpoint("Customer", "CustomerServiceRep")
def activate_payment_arrangement(rid):
    rec = get_or_404("payment_arrangements", rid)
    require_own_account(rec["account_id"])
    account = maybe("service_accounts", rec["account_id"])

    if rec["status"] != "PROPOSED":
        err("ERR_INVALID_STATE_TRANSITION", "only a PROPOSED arrangement may be activated")
    if account["service_status"] == "SHUTOFF_EXECUTED" and int(rec["down_payment_cents"]) <= 0:
        err(
            "ERR_INVALID_STATE_TRANSITION",
            "a down payment is required to activate on a shut-off account",
        )

    rec["status"] = "ACTIVE"
    touch(rec)
    domain.add_ledger_entry(
        account,
        "PAYMENT",
        "ARRANGEMENT_DOWN_PAYMENT",
        -int(rec["down_payment_cents"]),
        bill_id=rec["bill_id"],
        source_id=rec["id"],
    )
    domain.refresh_account(account)
    return object_response(serialize(rec))


@bp.route("/payment-arrangements/<rid>/record-payment", methods=["POST"])
@endpoint("Customer", "CustomerServiceRep")
def record_arrangement_payment(rid):
    body = Body()
    amount_cents = body.integer("amount_cents")
    on_time = body.boolean("on_time")
    rec = get_or_404("payment_arrangements", rid)
    require_own_account(rec["account_id"])

    if rec["status"] != "ACTIVE":
        err("ERR_INVALID_STATE_TRANSITION", "only an ACTIVE arrangement may take a payment")
    if amount_cents <= 0:
        err("ERR_PAYMENT_AMOUNT_INVALID", "amount_cents must be greater than zero")

    account = maybe("service_accounts", rec["account_id"])
    domain.add_ledger_entry(
        account,
        "PAYMENT",
        "ARRANGEMENT_INSTALLMENT",
        -amount_cents,
        bill_id=rec["bill_id"],
        source_id=rec["id"],
    )
    rec["paid_installment_count"] = rec["paid_installment_count"] + 1
    if on_time is False:
        rec["missed_payment_count"] = rec["missed_payment_count"] + 1
    if rec["paid_installment_count"] >= rec["installment_count"]:
        rec["status"] = "COMPLETED"
    elif rec["missed_payment_count"] >= MISSED_PAYMENTS_TO_DEFAULT:
        rec["status"] = "DEFAULTED"
    touch(rec)
    domain.refresh_account(account)
    return object_response(serialize(rec))


@bp.route("/payment-arrangements/<rid>/reinstate", methods=["POST"])
@endpoint("BillingSupervisor")
def reinstate_payment_arrangement(rid):
    rec = get_or_404("payment_arrangements", rid)
    if rec["status"] != "DEFAULTED":
        err("ERR_INVALID_STATE_TRANSITION", "only a DEFAULTED arrangement may be reinstated")
    if rec["reinstatement_count"] >= MAX_ARRANGEMENT_REINSTATEMENTS:
        err("ERR_REINSTATEMENT_LIMIT", "the reinstatement limit has been reached")
    rec["status"] = "ACTIVE"
    rec["reinstatement_count"] = rec["reinstatement_count"] + 1
    rec["missed_payment_count"] = 0
    touch(rec)
    account = maybe("service_accounts", rec["account_id"])
    if account is not None:
        domain.refresh_account(account)
    return object_response(serialize(rec))


# ---------------------------------------------------------------------------
# BoardAppeal
# ---------------------------------------------------------------------------
@bp.route("/board-appeals", methods=["POST"])
@endpoint("Customer", "CustomerServiceRep")
def create_board_appeal():
    body = Body()
    investigation_id = body.string("investigation_id")
    grounds = body.string("grounds")

    investigation = get_or_404("investigations", investigation_id)
    require_own_account(investigation["account_id"])

    if investigation["status"] not in ("DETERMINED", "RESOLVED", "CLOSED_NO_ADJUSTMENT"):
        err(
            "ERR_INVALID_STATE_TRANSITION",
            "the investigation cannot be appealed from this state",
        )
    if investigation["status"] == "CLOSED_NO_ADJUSTMENT":
        reference = as_dt(investigation.get("_closed_at"))
    else:
        reference = as_dt(investigation["determined_at"])
    if reference is None:
        err("ERR_INVALID_STATE_TRANSITION", "the investigation has no determination instant")
    if clock_date() > add_days(reference.date(), APPEAL_FILING_DAYS):
        err("ERR_APPEAL_UNTIMELY", "the appeal filing window has closed")

    rec = base_record()
    rec.update(
        {
            "investigation_id": investigation["id"],
            "grounds": grounds,
            "filed_by_user_id": g.user_id,
            "filing_date": now_iso(),
            "hearing_date": None,
            "hearing_officer_user_id": None,
            "status": "FILED",
            "decision": None,
            "decision_note": None,
        }
    )
    insert("board_appeals", register_new(rec))

    investigation["status"] = "APPEALED"
    domain.sync_investigation_hold(investigation)
    touch(investigation)
    account = maybe("service_accounts", investigation["account_id"])
    if account is not None:
        domain.refresh_account(account)
    return created_response(serialize(rec))


@bp.route("/board-appeals", methods=["GET"])
@endpoint("Customer", "CustomerServiceRep", "UtilityBoardClerk", "BillingSupervisor", "SystemAdmin")
def list_board_appeals():
    investigation_id = q_str("investigation_id")
    status = q_enum("status", APPEAL_STATUSES)
    hearing_date = q_date("hearing_date")
    if investigation_id is not None:
        inv = maybe("investigations", investigation_id)
        if inv is not None:
            require_own_account(inv["account_id"])

    result = []
    for rec in rows("board_appeals"):
        if investigation_id is not None and rec["investigation_id"] != investigation_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        if hearing_date is not None and rec.get("hearing_date") != hearing_date:
            continue
        result.append(rec)
    if is_customer():
        owned = set(
            i["id"] for i in rows("investigations") if i["account_id"] == g.user_id
        )
        result = [r for r in result if r["investigation_id"] in owned]
    return list_result(result)


@bp.route("/board-appeals/<rid>", methods=["GET"])
@endpoint("Customer", "CustomerServiceRep", "UtilityBoardClerk", "BillingSupervisor", "SystemAdmin")
def get_board_appeal(rid):
    rec = get_or_404("board_appeals", rid)
    inv = maybe("investigations", rec["investigation_id"])
    if inv is not None:
        require_own_account(inv["account_id"])
    return object_response(serialize(rec))


@bp.route("/board-appeals/<rid>/schedule", methods=["POST"])
@endpoint("UtilityBoardClerk")
def schedule_board_appeal(rid):
    body = Body()
    hearing_date = body.date("hearing_date")
    rec = get_or_404("board_appeals", rid)

    if rec["status"] != "FILED":
        err("ERR_INVALID_STATE_TRANSITION", "only a FILED appeal may be scheduled")
    filed = as_dt(rec["filing_date"])
    if parse_date(hearing_date) < add_days(filed.date(), HEARING_MIN_NOTICE_DAYS):
        err(
            "ERR_HEARING_NOTICE_TOO_SHORT",
            "at least %d days of notice are required" % HEARING_MIN_NOTICE_DAYS,
        )
    booked = [
        a
        for a in rows("board_appeals")
        if a["id"] != rec["id"]
        and a["status"] == "SCHEDULED"
        and a.get("hearing_date") == hearing_date
    ]
    if len(booked) >= HEARING_DOCKET_CAPACITY:
        err("ERR_HEARING_DOCKET_FULL", "the docket for that date is full")

    rec["status"] = "SCHEDULED"
    rec["hearing_date"] = hearing_date
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/board-appeals/<rid>/record-decision", methods=["POST"])
@endpoint("UtilityBoardClerk")
def record_board_decision(rid):
    body = Body()
    decision = body.enum("decision", DECISIONS)
    decision_note = body.string("decision_note")
    rec = get_or_404("board_appeals", rid)
    investigation = maybe("investigations", rec["investigation_id"])

    if rec["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE_TRANSITION", "only a SCHEDULED appeal may record a decision")
    proofs = domain.verified_proofs(rec["investigation_id"])
    if decision == "REVERSE" and not proofs:
        err(
            "ERR_INVALID_STATE_TRANSITION",
            "a VERIFIED repair proof is required to reverse",
        )
    if investigation is not None and g.user_id == investigation["determination_by_user_id"]:
        err(
            "ERR_HEARING_OFFICER_CONFLICT",
            "the hearing officer may not be the determining user",
        )
    if g.user_id == rec["filed_by_user_id"]:
        err("ERR_HEARING_OFFICER_CONFLICT", "the hearing officer may not be the filer")
    if clock_date() < as_date(rec["hearing_date"]):
        err("ERR_HEARING_NOT_YET_HELD", "the hearing date has not arrived")
    if decision == "REMAND" and investigation["remand_count"] >= REMAND_MAX:
        err("ERR_REMAND_LIMIT_EXCEEDED", "the remand limit has been reached")

    rec["hearing_officer_user_id"] = g.user_id
    rec["decision"] = decision
    rec["decision_note"] = decision_note
    bill = maybe("bills", investigation["bill_id"]) if investigation else None
    account = maybe("service_accounts", investigation["account_id"]) if investigation else None

    if decision == "UPHOLD":
        rec["status"] = "UPHELD"
        touch(rec)
        investigation["status"] = "RESOLVED"
        domain.sync_investigation_hold(investigation)
        touch(investigation)
        if bill is not None and bill["billing_status"] == "UNDER_INVESTIGATION":
            bill["billing_status"] = "UPHELD_AS_BILLED"
            domain.recompute_adjusted_total(bill)
            touch(bill)
    elif decision == "REVERSE":
        rec["status"] = "REVERSED"
        touch(rec)
        superseded = [
            a
            for a in rows("leak_adjustments")
            if a["investigation_id"] == investigation["id"]
            and a["status"] in ("DENIED", "REVERSED")
        ]
        superseded.sort(key=lambda a: (a["created_at"], a["version"], a["_seq"]))
        adjustment = _blank_adjustment()
        adjustment["investigation_id"] = investigation["id"]
        adjustment["bill_id"] = investigation["bill_id"]
        adjustment["leak_type"] = proofs[-1]["leak_type"]
        adjustment["board_ordered"] = True
        adjustment["supersedes_adjustment_id"] = superseded[-1]["id"] if superseded else None
        adjustment["status"] = "PENDING_APPROVAL"
        adjustment["created_by_user_id"] = g.user_id
        _apply_credit(adjustment, bill)
        insert("leak_adjustments", register_new(adjustment))
        investigation["status"] = "ADJUSTMENT_PENDING"
        domain.sync_investigation_hold(investigation)
        touch(investigation)
    else:
        rec["status"] = "REMANDED"
        touch(rec)
        investigation["status"] = "EVIDENCE_REQUESTED"
        investigation["remand_count"] = investigation["remand_count"] + 1
        investigation["evidence_round_count"] = investigation["evidence_round_count"] + 1
        domain.sync_investigation_hold(investigation)
        touch(investigation)
        if bill is not None and bill["billing_status"] == "UPHELD_AS_BILLED":
            bill["billing_status"] = "UNDER_INVESTIGATION"
            domain.recompute_adjusted_total(bill)
            touch(bill)

    if account is not None:
        domain.refresh_account(account)
    return object_response(serialize(rec))
