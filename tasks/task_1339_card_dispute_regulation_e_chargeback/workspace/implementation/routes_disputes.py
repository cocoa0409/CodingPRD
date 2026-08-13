"""Routes: dispute cases, classify/reclassify, provisional credit grant,
resolve, withdraw, plus case-scoped collections (chargebacks, credits,
notifications, loss-recoveries)."""

from datetime import timedelta
from flask import Blueprint, g

import db
import errors
import middleware
from clock import end_of_day, parse_iso, iso_z
from helpers import (
    ERROR_TYPES,
    LOSS_TYPES,
    NON_TERMINAL_CASE_STATUSES,
    NOTIFICATION_TYPES,
    OPEN_CREDIT_STATUSES,
    RESOLVED_CASE_STATUSES,
    account_is_new,
    add_notification,
    any_credit_ever_for_case,
    case_non_terminal_for_transaction,
    get_body,
    holdback_for,
    investigation_window,
    maybe_restore_account,
    new_id,
    open_credit_for_case,
    outstanding_loss,
    paginate,
    parse_pagination,
    provisional_due_at,
    record_loss_entry,
    serialize_case,
    serialize_chargeback,
    serialize_credit,
    serialize_loss_entry,
    serialize_notification,
    settle_transaction,
    sorted_by_creation,
    stamp_new,
    touch,
    validate_body,
)
from middleware import require_cardholder_owns
from response import success_list, success_object
from state import CLOCK

bp = Blueprint("disputes", __name__)


# ---------------------------------------------------------------------------
# Internal business operations shared across routes
# ---------------------------------------------------------------------------


def _apply_classification(case, is_fraud, verified_delay):
    """Classify / reclassify side effects (no state transition, no version bump)."""
    txn = db.card_transactions[case["card_transaction_id"]]
    account = db.card_accounts[case["card_account_id"]]
    is_new = account_is_new(account, txn)

    case["is_fraud_claim"] = is_fraud
    case["verified_report_delay_days"] = verified_delay
    case["provisional_holdback_cents"] = holdback_for(
        is_fraud, case["claimed_report_delay_days"], case["claim_amount_cents"]
    )
    window = investigation_window(is_fraud, txn["transaction_type"], is_new)
    case["investigation_window_days"] = window
    received = parse_iso(case["received_at"])
    case["investigation_deadline_at"] = iso_z(end_of_day(received + timedelta(days=window)))

    # Fraud restriction cascade (PRD §2.9)
    if is_fraud:
        if account["status"] != "RESTRICTED":
            account["status"] = "RESTRICTED"
            touch(account, CLOCK)
    else:
        maybe_restore_account(account, CLOCK)


def _final_liability(case):
    return holdback_for(
        case["is_fraud_claim"], case["verified_report_delay_days"], case["claim_amount_cents"]
    )


def _finalize_credit(case, final_amount):
    """Finalize an open credit with true-up, or create one directly FINALIZED.

    Returns the ProvisionalCredit record.
    """
    account = db.card_accounts[case["card_account_id"]]
    credit = open_credit_for_case(case["id"])
    if credit is not None:
        delta = final_amount - credit["amount_cents"]
        account["balance_cents"] += delta
        touch(account, CLOCK)
        credit["final_amount_cents"] = final_amount
        credit["status"] = "FINALIZED"
        touch(credit, CLOCK)
        return credit
    # No credit ever granted: create directly in FINALIZED and credit balance.
    credit = stamp_new(CLOCK)
    credit.update(
        {
            "dispute_case_id": case["id"],
            "amount_cents": final_amount,
            "final_amount_cents": final_amount,
            "granted_at": CLOCK.now_iso(),
            "granted_late": False,
            "reversed_at": None,
            "status": "FINALIZED",
        }
    )
    db.provisional_credits[credit["id"]] = credit
    account["balance_cents"] += final_amount
    touch(account, CLOCK)
    return credit


def _auto_reverse_open_credit(case):
    """Auto-reversal on cardholder withdrawal (no notice cooling applies)."""
    credit = open_credit_for_case(case["id"])
    if credit is None:
        return None
    account = db.card_accounts[case["card_account_id"]]
    account["balance_cents"] -= credit["amount_cents"]
    touch(account, CLOCK)
    credit["status"] = "REVERSED"
    credit["reversed_at"] = CLOCK.now_iso()
    touch(credit, CLOCK)
    return credit


def _resolve_error_confirmed(case):
    """CLASSIFIED -> RESOLVED_CARDHOLDER_FAVOR."""
    final_liability = _final_liability(case)
    final_credit = case["claim_amount_cents"] - final_liability
    case["final_liability_cents"] = final_liability
    case["cardholder_keeps_cents"] = final_credit
    _finalize_credit(case, final_credit)
    if final_credit > 0:
        record_loss_entry(case["id"], "LOSS_RECOGNIZED", final_credit, "AUTO", CLOCK)
    add_notification(
        case["id"],
        "RESOLUTION_LETTER",
        "Your dispute has been resolved in your favor.",
        CLOCK,
    )
    case["status"] = "RESOLVED_CARDHOLDER_FAVOR"
    touch(case, CLOCK)
    settle_transaction(case, CLOCK)
    maybe_restore_account(db.card_accounts[case["card_account_id"]], CLOCK)


def _resolve_no_error(case):
    """CLASSIFIED -> REVERSAL_PENDING (open credit) or RESOLVED_MERCHANT_FAVOR."""
    credit = open_credit_for_case(case["id"])
    if credit is not None:
        case["status"] = "REVERSAL_PENDING"
        touch(case, CLOCK)
        add_notification(
            case["id"],
            "REVERSAL_NOTICE",
            "Your provisional credit will be reversed; the investigation found no error.",
            CLOCK,
        )
    else:
        case["status"] = "RESOLVED_MERCHANT_FAVOR"
        touch(case, CLOCK)
        add_notification(
            case["id"],
            "RESOLUTION_LETTER",
            "Your dispute has been resolved; the investigation found no error.",
            CLOCK,
        )
        settle_transaction(case, CLOCK)
        maybe_restore_account(db.card_accounts[case["card_account_id"]], CLOCK)


# ---------------------------------------------------------------------------
# Dispute intake and reads
# ---------------------------------------------------------------------------


@bp.route("/disputes", methods=["POST"])
def create_dispute():
    middleware.authenticate()
    middleware.require_roles("Cardholder", "IntakeAgent")
    body = get_body()
    fields = validate_body(
        body,
        [
            ("card_transaction_id", "string", True, None),
            ("error_type", "string", True, sorted(ERROR_TYPES)),
            ("claim_amount_cents", "int", True, None),
            ("claimed_report_delay_days", "int_nonneg", True, None),
        ],
    )
    txn = db.card_transactions.get(fields["card_transaction_id"])
    if txn is None:
        raise errors.not_found("CardTransaction not found")
    account = db.card_accounts[txn["card_account_id"]]
    # Cardholder ownership (tier 5)
    if g.role == "Cardholder" and g.user_id != txn["card_account_id"]:
        raise errors.forbidden("Cardholder may only dispute transactions on their own account")
    # State tier (6): duplicate-active-dispute takes precedence over generic state
    if case_non_terminal_for_transaction(txn["id"]) is not None:
        raise errors.duplicate_active_dispute()
    if txn["status"] != "POSTED":
        raise errors.invalid_state("Transaction is not in a disputable state")
    # Fiscal tier (11)
    if fields["claim_amount_cents"] > txn["amount_cents"]:
        raise errors.claim_exceeds_transaction()

    # Provisional fraud treatment keyed off error_type until classification
    provisional_fraud = fields["error_type"] == "UNAUTHORIZED"
    holdback = holdback_for(
        provisional_fraud, fields["claimed_report_delay_days"], fields["claim_amount_cents"]
    )
    is_new = account_is_new(account, txn)
    due_at = provisional_due_at(CLOCK.now(), is_new)

    case = stamp_new(CLOCK)
    case.update(
        {
            "card_transaction_id": txn["id"],
            "card_account_id": txn["card_account_id"],
            "intake_agent_id": g.user_id if g.role == "IntakeAgent" else None,
            "error_type": fields["error_type"],
            "claim_amount_cents": fields["claim_amount_cents"],
            "claimed_report_delay_days": fields["claimed_report_delay_days"],
            "received_at": CLOCK.now_iso(),
            "is_fraud_claim": None,
            "verified_report_delay_days": None,
            "provisional_holdback_cents": holdback,
            "provisional_credit_due_at": iso_z(due_at),
            "investigation_window_days": None,
            "investigation_deadline_at": None,
            "final_liability_cents": None,
            "cardholder_keeps_cents": 0,
            "outstanding_loss_cents": 0,
            "status": "RECEIVED",
        }
    )
    db.dispute_cases[case["id"]] = case
    txn["status"] = "DISPUTED"
    touch(txn, CLOCK)
    return success_object(serialize_case(case), 201)


@bp.route("/disputes/<case_id>", methods=["GET"])
def get_dispute(case_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    case = db.dispute_cases.get(case_id)
    if case is None:
        raise errors.not_found("DisputeCase not found")
    require_cardholder_owns(case["card_account_id"])
    return success_object(serialize_case(case), 200)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    account_filter = request_arg("card_account_id")
    txn_filter = request_arg("card_transaction_id")
    status_filter = request_arg("status")
    cases = list(db.dispute_cases.values())
    if g.role == "Cardholder":
        cases = [c for c in cases if c["card_account_id"] == g.user_id]
    if account_filter is not None:
        # Cardholder filtering on someone else's account is an ownership failure
        if g.role == "Cardholder" and account_filter != g.user_id:
            raise errors.forbidden("Cardholder may only list their own disputes")
        cases = [c for c in cases if c["card_account_id"] == account_filter]
    if txn_filter is not None:
        cases = [c for c in cases if c["card_transaction_id"] == txn_filter]
    if status_filter is not None:
        cases = [c for c in cases if c["status"] == status_filter]
    cases = sorted_by_creation(cases)
    page, total = paginate(cases, limit, offset)
    return success_list([serialize_case(c) for c in page], limit, offset, total)


def request_arg(name):
    from flask import request

    value = request.args.get(name)
    return value if value not in (None, "") else None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@bp.route("/disputes/<case_id>/classify", methods=["POST"])
def classify_dispute(case_id):
    middleware.authenticate()
    middleware.require_roles("DisputeInvestigator")
    body = get_body()
    fields = validate_body(
        body,
        [
            ("is_fraud_claim", "bool", True, None),
            ("verified_report_delay_days", "int_nonneg", True, None),
        ],
    )
    case = db.dispute_cases.get(case_id)
    if case is None:
        raise errors.not_found("DisputeCase not found")
    if case["status"] != "RECEIVED":
        raise errors.invalid_state("Classify requires the case to be in RECEIVED")
    _apply_classification(case, fields["is_fraud_claim"], fields["verified_report_delay_days"])
    case["status"] = "CLASSIFIED"
    touch(case, CLOCK)
    return success_object(serialize_case(case), 200)


@bp.route("/disputes/<case_id>/reclassify", methods=["POST"])
def reclassify_dispute(case_id):
    middleware.authenticate()
    middleware.require_roles("DisputeInvestigator")
    body = get_body()
    fields = validate_body(
        body,
        [
            ("is_fraud_claim", "bool", True, None),
            ("verified_report_delay_days", "int_nonneg", True, None),
            ("expected_dispute_version", "int", True, None),
        ],
    )
    case = db.dispute_cases.get(case_id)
    if case is None:
        raise errors.not_found("DisputeCase not found")
    if case["status"] != "CLASSIFIED":
        raise errors.invalid_state("Reclassify requires the case to be in CLASSIFIED")
    # OCC (tier 7)
    if fields["expected_dispute_version"] != case["version"]:
        raise errors.stale_version()
    _apply_classification(case, fields["is_fraud_claim"], fields["verified_report_delay_days"])
    touch(case, CLOCK)  # CLASSIFIED -> CLASSIFIED self-loop, version +1
    return success_object(serialize_case(case), 200)


# ---------------------------------------------------------------------------
# Provisional credit grant
# ---------------------------------------------------------------------------


@bp.route("/disputes/<case_id>/grant-provisional-credit", methods=["POST"])
def grant_provisional_credit(case_id):
    middleware.authenticate()
    middleware.require_roles("IntakeAgent")
    body = get_body()
    validate_body(body, [])  # no fields accepted
    case = db.dispute_cases.get(case_id)
    if case is None:
        raise errors.not_found("DisputeCase not found")
    if case["status"] != "CLASSIFIED":
        raise errors.invalid_state("Provisional credit grant requires the case to be CLASSIFIED")
    if open_credit_for_case(case["id"]) is not None:
        raise errors.invalid_state("A ProvisionalCredit in GRANTED or REINSTATED already exists")

    amount = max(0, case["claim_amount_cents"] - case["provisional_holdback_cents"])
    granted_late = CLOCK.now() > parse_iso(case["provisional_credit_due_at"])

    credit = stamp_new(CLOCK)
    credit.update(
        {
            "dispute_case_id": case["id"],
            "amount_cents": amount,
            "final_amount_cents": None,
            "granted_at": CLOCK.now_iso(),
            "granted_late": granted_late,
            "reversed_at": None,
            "status": "GRANTED",
        }
    )
    db.provisional_credits[credit["id"]] = credit

    account = db.card_accounts[case["card_account_id"]]
    account["balance_cents"] += amount
    touch(account, CLOCK)

    add_notification(
        case["id"],
        "PROVISIONAL_CREDIT_ADVICE",
        f"A provisional credit of {amount} cents has been granted.",
        CLOCK,
    )
    return success_object(serialize_credit(credit), 201)


# ---------------------------------------------------------------------------
# Resolve / withdraw
# ---------------------------------------------------------------------------


@bp.route("/disputes/<case_id>/resolve", methods=["POST"])
def resolve_dispute(case_id):
    middleware.authenticate()
    middleware.require_roles("DisputeInvestigator")
    body = get_body()
    fields = validate_body(
        body,
        [("outcome", "string", True, ["ERROR_CONFIRMED", "NO_ERROR"])],
    )
    case = db.dispute_cases.get(case_id)
    if case is None:
        raise errors.not_found("DisputeCase not found")
    if case["status"] != "CLASSIFIED":
        raise errors.invalid_state("Resolve requires the case to be CLASSIFIED")
    # SoD (tier 8) — sits above the temporal gates
    if case["intake_agent_id"] is not None and g.user_id == case["intake_agent_id"]:
        raise errors.sod_violation()
    # Provisional-credit compliance (tier 9)
    now = CLOCK.now()
    if now > parse_iso(case["provisional_credit_due_at"]) and not any_credit_ever_for_case(
        case["id"]
    ):
        raise errors.provisional_credit_required()
    # Investigation window (tier 9) applies to NO_ERROR only
    if fields["outcome"] == "NO_ERROR" and now > parse_iso(case["investigation_deadline_at"]):
        raise errors.investigation_window_expired()

    if fields["outcome"] == "ERROR_CONFIRMED":
        _resolve_error_confirmed(case)
    else:
        _resolve_no_error(case)
    return success_object(serialize_case(case), 200)


@bp.route("/disputes/<case_id>/withdraw", methods=["POST"])
def withdraw_dispute(case_id):
    middleware.authenticate()
    middleware.require_roles("Cardholder", "IntakeAgent")
    body = get_body()
    validate_body(body, [])
    case = db.dispute_cases.get(case_id)
    if case is None:
        raise errors.not_found("DisputeCase not found")
    if g.role == "Cardholder" and g.user_id != case["card_account_id"]:
        raise errors.forbidden("Cardholder may only withdraw their own cases")
    if case["status"] not in ("RECEIVED", "CLASSIFIED"):
        raise errors.invalid_state("Withdraw requires the case to be RECEIVED or CLASSIFIED")

    if case["status"] == "CLASSIFIED":
        # Cardholder-initiated withdrawal waives the 3-business-day notice
        _auto_reverse_open_credit(case)
    case["status"] = "WITHDRAWN"
    touch(case, CLOCK)
    settle_transaction(case, CLOCK)
    maybe_restore_account(db.card_accounts[case["card_account_id"]], CLOCK)
    return success_object(serialize_case(case), 200)


# ---------------------------------------------------------------------------
# Case-scoped collections
# ---------------------------------------------------------------------------


@bp.route("/disputes/<case_id>/chargebacks", methods=["GET"])
def list_case_chargebacks(case_id):
    middleware.authenticate()
    middleware.require_roles(
        "BankAdmin", "IntakeAgent", "DisputeInvestigator", "ChargebackAnalyst", "FinanceOfficer"
    )
    case = db.dispute_cases.get(case_id)
    if case is None:
        raise errors.not_found("DisputeCase not found")
    limit, offset = parse_pagination()
    items = [cb for cb in db.chargebacks.values() if cb["dispute_case_id"] == case_id]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_chargeback(c) for c in page], limit, offset, total)


@bp.route("/disputes/<case_id>/provisional-credits", methods=["GET"])
def list_case_credits(case_id):
    middleware.authenticate()
    middleware.require_roles(
        "BankAdmin", "IntakeAgent", "DisputeInvestigator", "ChargebackAnalyst", "FinanceOfficer"
    )
    case = db.dispute_cases.get(case_id)
    if case is None:
        raise errors.not_found("DisputeCase not found")
    limit, offset = parse_pagination()
    items = [c for c in db.provisional_credits.values() if c["dispute_case_id"] == case_id]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_credit(c) for c in page], limit, offset, total)


@bp.route("/disputes/<case_id>/notifications", methods=["GET"])
def list_case_notifications(case_id):
    middleware.authenticate()
    middleware.require_roles(
        "BankAdmin", "IntakeAgent", "DisputeInvestigator", "ChargebackAnalyst", "FinanceOfficer"
    )
    case = db.dispute_cases.get(case_id)
    if case is None:
        raise errors.not_found("DisputeCase not found")
    type_filter = request_arg("type")
    if type_filter is not None and type_filter not in NOTIFICATION_TYPES:
        raise errors.invalid_request(f"Unknown notification type filter: {type_filter}")
    limit, offset = parse_pagination()
    items = [n for n in db.notifications.values() if n["dispute_case_id"] == case_id]
    if type_filter is not None:
        items = [n for n in items if n["type"] == type_filter]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_notification(n) for n in page], limit, offset, total)


@bp.route("/disputes/<case_id>/loss-recoveries", methods=["POST"])
def create_loss_recovery(case_id):
    middleware.authenticate()
    middleware.require_roles("FinanceOfficer")
    body = get_body()
    fields = validate_body(
        body,
        [
            ("type", "string", True, sorted(LOSS_TYPES)),
            ("amount_cents", "int", True, None),
            ("memo", "string", False, None),
        ],
    )
    case = db.dispute_cases.get(case_id)
    if case is None:
        raise errors.not_found("DisputeCase not found")
    # Manual LOSS_RECOGNIZED requires a RESOLVED_* case status (state tier)
    if fields["type"] == "LOSS_RECOGNIZED" and case["status"] not in RESOLVED_CASE_STATUSES:
        raise errors.invalid_state(
            "Manual LOSS_RECOGNIZED requires the case to be in a RESOLVED_* status"
        )
    # Fiscal tier: manual RECOVERY_RECEIVED bounded by outstanding loss
    if fields["type"] == "RECOVERY_RECEIVED":
        if fields["amount_cents"] > outstanding_loss(case["id"]):
            raise errors.loss_exceeds_outstanding()
    entry = record_loss_entry(
        case["id"], fields["type"], fields["amount_cents"], "MANUAL", CLOCK,
        memo=fields["memo"],
    )
    return success_object(serialize_loss_entry(entry), 201)


@bp.route("/disputes/<case_id>/loss-recoveries", methods=["GET"])
def list_loss_recoveries(case_id):
    middleware.authenticate()
    middleware.require_roles(
        "BankAdmin", "IntakeAgent", "DisputeInvestigator", "ChargebackAnalyst", "FinanceOfficer"
    )
    case = db.dispute_cases.get(case_id)
    if case is None:
        raise errors.not_found("DisputeCase not found")
    type_filter = request_arg("type")
    if type_filter is not None and type_filter not in LOSS_TYPES:
        raise errors.invalid_request(f"Unknown loss entry type filter: {type_filter}")
    limit, offset = parse_pagination()
    items = [e for e in db.loss_recoveries.values() if e["dispute_case_id"] == case_id]
    if type_filter is not None:
        items = [e for e in items if e["type"] == type_filter]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_loss_entry(e) for e in page], limit, offset, total)
