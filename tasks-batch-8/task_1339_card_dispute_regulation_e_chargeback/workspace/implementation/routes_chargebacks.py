"""Routes: chargebacks, representments, review, escalation, withdrawal,
and provisional-credit reverse/reinstate."""

from datetime import timedelta
from flask import Blueprint

import db
import errors
import middleware
from clock import end_of_day, parse_iso, iso_z
from helpers import (
    FRAUD_REASON_CODES,
    MERCHANT_RESPONSE_DAYS,
    NONFRAUD_REASON_CODES,
    OPEN_CREDIT_STATUSES,
    REASON_CODES,
    add_notification,
    get_body,
    maybe_restore_account,
    network_filing_deadline,
    open_credit_for_case,
    outstanding_loss,
    paginate,
    parse_pagination,
    record_loss_entry,
    reversal_notice_cooled,
    serialize_chargeback,
    serialize_credit,
    serialize_representment,
    settle_transaction,
    sorted_by_creation,
    stage_fee,
    stamp_new,
    touch,
    validate_body,
    FILING_FEE_CENTS,
)
from response import success_list, success_object
from routes_disputes import _finalize_credit, _final_liability
from state import CLOCK

bp = Blueprint("chargebacks", __name__)

ESCALATION_STAGES = {"PRE_COMPLIANCE", "ARBITRATION"}
ESCALATION_OUTCOMES = {"WON", "LOST", "WITHDRAWN"}
REVIEW_DECISIONS = {"ACCEPT", "REJECT"}


# ---------------------------------------------------------------------------
# Chargeback filing
# ---------------------------------------------------------------------------


@bp.route("/chargebacks", methods=["POST"])
def create_chargeback():
    middleware.authenticate()
    middleware.require_roles("ChargebackAnalyst")
    body = get_body()
    fields = validate_body(
        body,
        [
            ("dispute_case_id", "string", True, None),
            ("reason_code", "string", True, sorted(REASON_CODES)),
            ("amount_cents", "int", False, None),
        ],
    )
    case = db.dispute_cases.get(fields["dispute_case_id"])
    if case is None:
        raise errors.not_found("DisputeCase not found")
    # State tier: case must be CLASSIFIED
    if case["status"] != "CLASSIFIED":
        raise errors.invalid_state("Chargeback filing requires the case to be CLASSIFIED")

    txn = db.card_transactions[case["card_transaction_id"]]
    network = txn["network"]
    now = CLOCK.now()

    # Temporal tier: network filing deadline (posted_at + 120d VISA / 90d MC, eod inclusive)
    deadline = network_filing_deadline(txn)
    if now > deadline:
        raise errors.network_deadline_passed()

    # Business tier: response window occupancy [filed_at, response_window_end_at)
    # PRD §3.6: a cancelled chargeback's response window continues to occupy
    # the timeline until it expires, so occupancy is purely interval-based
    # (status does not free the window early).
    for other in db.chargebacks.values():
        if other["card_transaction_id"] != txn["id"]:
            continue
        filed_at = parse_iso(other["filed_at"])
        window_end = parse_iso(other["response_window_end_at"])
        if filed_at <= now < window_end:
            raise errors.network_window_active()

    # Business tier: reason-code compatibility with network + fraud classification
    allowed = FRAUD_REASON_CODES[network] if case["is_fraud_claim"] else NONFRAUD_REASON_CODES[network]
    if fields["reason_code"] not in allowed:
        raise errors.reason_code_mismatch()

    amount = fields["amount_cents"]
    if amount is None:
        amount = case["claim_amount_cents"]

    cb = stamp_new(CLOCK)
    cb.update(
        {
            "dispute_case_id": case["id"],
            "card_transaction_id": txn["id"],
            "reason_code": fields["reason_code"],
            "amount_cents": amount,
            "network": network,
            "filed_at": CLOCK.now_iso(),
            "network_filing_deadline_at": iso_z(deadline),
            "response_window_end_at": iso_z(
                end_of_day(now + timedelta(days=MERCHANT_RESPONSE_DAYS))
            ),
            "fees_total_cents": FILING_FEE_CENTS,
            "stage_entered": "NONE",
            "outcome": None,
            "status": "FILED",
        }
    )
    db.chargebacks[cb["id"]] = cb

    case["status"] = "CHARGEBACK_FILED"
    touch(case, CLOCK)
    txn["status"] = "CHARGED_BACK"
    touch(txn, CLOCK)
    return success_object(serialize_chargeback(cb), 201)


@bp.route("/chargebacks/<cb_id>", methods=["GET"])
def get_chargeback(cb_id):
    middleware.authenticate()
    middleware.require_roles(
        "BankAdmin", "IntakeAgent", "DisputeInvestigator", "ChargebackAnalyst", "FinanceOfficer"
    )
    cb = db.chargebacks.get(cb_id)
    if cb is None:
        raise errors.not_found("Chargeback not found")
    return success_object(serialize_chargeback(cb), 200)


@bp.route("/chargebacks", methods=["GET"])
def list_chargebacks():
    middleware.authenticate()
    middleware.require_roles(
        "BankAdmin", "IntakeAgent", "DisputeInvestigator", "ChargebackAnalyst", "FinanceOfficer"
    )
    limit, offset = parse_pagination()
    txn_filter = _arg("card_transaction_id")
    status_filter = _arg("status")
    items = list(db.chargebacks.values())
    if txn_filter is not None:
        items = [c for c in items if c["card_transaction_id"] == txn_filter]
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_chargeback(c) for c in page], limit, offset, total)


def _arg(name):
    from flask import request

    value = request.args.get(name)
    return value if value not in (None, "") else None


# ---------------------------------------------------------------------------
# Representments
# ---------------------------------------------------------------------------


@bp.route("/chargebacks/<cb_id>/representments", methods=["POST"])
def create_representment(cb_id):
    middleware.authenticate()
    middleware.require_roles("ChargebackAnalyst")
    body = get_body()
    fields = validate_body(
        body,
        [
            ("merchant_ref", "string", True, None),
            ("evidence_documents", "evidence", True, None),
        ],
    )
    cb = db.chargebacks.get(cb_id)
    if cb is None:
        raise errors.not_found("Chargeback not found")
    if cb["status"] != "FILED":
        raise errors.invalid_state("Representment registration requires the chargeback to be FILED")
    if len(fields["evidence_documents"]) == 0:
        raise errors.evidence_required()

    rep = stamp_new(CLOCK)
    rep.update(
        {
            "chargeback_id": cb["id"],
            "merchant_ref": fields["merchant_ref"],
            "evidence_documents": fields["evidence_documents"],
            "received_at": CLOCK.now_iso(),
            "status": "PENDING_REVIEW",
        }
    )
    db.representments[rep["id"]] = rep

    cb["status"] = "REPRESENTED"
    touch(cb, CLOCK)
    case = db.dispute_cases[cb["dispute_case_id"]]
    case["status"] = "REPRESENTMENT_REVIEW"
    touch(case, CLOCK)
    txn = db.card_transactions[cb["card_transaction_id"]]
    txn["status"] = "RE_PRESENTED"
    touch(txn, CLOCK)
    return success_object(serialize_representment(rep), 201)


@bp.route("/chargebacks/<cb_id>/representments", methods=["GET"])
def list_representments(cb_id):
    middleware.authenticate()
    middleware.require_roles(
        "BankAdmin", "IntakeAgent", "DisputeInvestigator", "ChargebackAnalyst", "FinanceOfficer"
    )
    cb = db.chargebacks.get(cb_id)
    if cb is None:
        raise errors.not_found("Chargeback not found")
    limit, offset = parse_pagination()
    items = [r for r in db.representments.values() if r["chargeback_id"] == cb_id]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_representment(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Review representment (ACCEPT concedes; REJECT issues second presentment)
# ---------------------------------------------------------------------------


def _close_lost_cascade(cb, case):
    """Shared LOST/WITHDRAWN-style cascade: loss entry + case fork on open credit."""
    finalized_principal = _finalized_principal_borne(cb, case)
    loss_amount = cb["fees_total_cents"] + finalized_principal
    if loss_amount > 0:
        record_loss_entry(case["id"], "LOSS_RECOGNIZED", loss_amount, "AUTO", CLOCK)
    credit = open_credit_for_case(case["id"])
    if credit is not None:
        case["status"] = "REVERSAL_PENDING"
        touch(case, CLOCK)
        add_notification(
            case["id"],
            "REVERSAL_NOTICE",
            "Your provisional credit will be reversed following the chargeback outcome.",
            CLOCK,
        )
    else:
        case["status"] = "RESOLVED_MERCHANT_FAVOR"
        touch(case, CLOCK)
        add_notification(
            case["id"],
            "RESOLUTION_LETTER",
            "Your dispute has been resolved in the merchant's favor.",
            CLOCK,
        )
        settle_transaction(case, CLOCK)
        maybe_restore_account(db.card_accounts[case["card_account_id"]], CLOCK)


def _finalized_principal_borne(cb, case):
    """Finalized credit principal the issuer bears (0 when credit not FINALIZED)."""
    for credit in db.provisional_credits.values():
        if credit["dispute_case_id"] != case["id"]:
            continue
        if credit["status"] == "FINALIZED":
            return credit["final_amount_cents"]
    return 0


@bp.route("/chargebacks/<cb_id>/review-representment", methods=["POST"])
def review_representment(cb_id):
    middleware.authenticate()
    middleware.require_roles("ChargebackAnalyst")
    body = get_body()
    fields = validate_body(body, [("decision", "string", True, sorted(REVIEW_DECISIONS))])
    cb = db.chargebacks.get(cb_id)
    if cb is None:
        raise errors.not_found("Chargeback not found")
    if cb["status"] != "REPRESENTED":
        raise errors.invalid_state(
            "Representment review requires the chargeback to be REPRESENTED"
        )
    pending = None
    for rep in db.representments.values():
        if rep["chargeback_id"] == cb_id and rep["status"] == "PENDING_REVIEW":
            pending = rep
            break
    if pending is None:
        raise errors.invalid_state("No Representment in PENDING_REVIEW exists")

    case = db.dispute_cases[cb["dispute_case_id"]]
    txn = db.card_transactions[cb["card_transaction_id"]]

    if fields["decision"] == "REJECT":
        pending["status"] = "REJECTED"
        touch(pending, CLOCK)
        cb["status"] = "SECOND_PRESENTED"
        touch(cb, CLOCK)
        txn["status"] = "CHARGED_BACK"
        touch(txn, CLOCK)
        case["status"] = "CHARGEBACK_FILED"
        touch(case, CLOCK)
    else:  # ACCEPT — issuer concedes; chargeback CLOSED_LOST
        pending["status"] = "ACCEPTED"
        touch(pending, CLOCK)
        cb["status"] = "CLOSED_LOST"
        cb["outcome"] = "LOST"
        touch(cb, CLOCK)
        _close_lost_cascade(cb, case)
    return success_object(serialize_chargeback(cb), 200)


# ---------------------------------------------------------------------------
# Escalation (from SECOND_PRESENTED)
# ---------------------------------------------------------------------------


@bp.route("/chargebacks/<cb_id>/escalate", methods=["POST"])
def escalate_chargeback(cb_id):
    middleware.authenticate()
    middleware.require_roles("ChargebackAnalyst")
    body = get_body()
    fields = validate_body(
        body,
        [
            ("stage", "string", True, sorted(ESCALATION_STAGES)),
            ("outcome", "string", True, sorted(ESCALATION_OUTCOMES)),
        ],
    )
    cb = db.chargebacks.get(cb_id)
    if cb is None:
        raise errors.not_found("Chargeback not found")
    if cb["status"] != "SECOND_PRESENTED":
        raise errors.invalid_state("Escalation requires the chargeback to be SECOND_PRESENTED")

    # Accrue the entered stage fee (per-stage round-half-up, then sum)
    fee = stage_fee(fields["stage"], cb["amount_cents"])
    cb["fees_total_cents"] += fee
    cb["stage_entered"] = fields["stage"]

    case = db.dispute_cases[cb["dispute_case_id"]]

    if fields["outcome"] == "WON":
        cb["status"] = "CLOSED_WON"
        cb["outcome"] = "WON"
        touch(cb, CLOCK)
        # Final credit F = claim - final liability; finalize any open credit
        final_liability = _final_liability(case)
        final_credit = case["claim_amount_cents"] - final_liability
        case["final_liability_cents"] = final_liability
        case["cardholder_keeps_cents"] = final_credit
        _finalize_credit(case, final_credit)
        loss_amount = final_credit + cb["fees_total_cents"]
        if loss_amount > 0:
            record_loss_entry(case["id"], "LOSS_RECOGNIZED", loss_amount, "AUTO", CLOCK)
        record_loss_entry(case["id"], "RECOVERY_RECEIVED", cb["amount_cents"], "AUTO", CLOCK)
        add_notification(
            case["id"],
            "RESOLUTION_LETTER",
            "Your dispute has been resolved in your favor following chargeback escalation.",
            CLOCK,
        )
        case["status"] = "RESOLVED_CARDHOLDER_FAVOR"
        touch(case, CLOCK)
        settle_transaction(case, CLOCK)
        maybe_restore_account(db.card_accounts[case["card_account_id"]], CLOCK)
    elif fields["outcome"] == "LOST":
        cb["status"] = "CLOSED_LOST"
        cb["outcome"] = "LOST"
        touch(cb, CLOCK)
        _close_lost_cascade(cb, case)
    else:  # WITHDRAWN — withdrawal at arbitration concedes the case
        cb["status"] = "WITHDRAWN"
        cb["outcome"] = "WITHDRAWN"
        touch(cb, CLOCK)
        _close_lost_cascade(cb, case)
    return success_object(serialize_chargeback(cb), 200)


# ---------------------------------------------------------------------------
# Chargeback withdrawal (FILED -> CANCELLED; refile path)
# ---------------------------------------------------------------------------


@bp.route("/chargebacks/<cb_id>/withdraw", methods=["POST"])
def withdraw_chargeback(cb_id):
    middleware.authenticate()
    middleware.require_roles("ChargebackAnalyst")
    body = get_body()
    validate_body(body, [])
    cb = db.chargebacks.get(cb_id)
    if cb is None:
        raise errors.not_found("Chargeback not found")
    if cb["status"] != "FILED":
        raise errors.invalid_state("Chargeback withdrawal requires the chargeback to be FILED")
    cb["status"] = "CANCELLED"
    touch(cb, CLOCK)
    case = db.dispute_cases[cb["dispute_case_id"]]
    case["status"] = "CLASSIFIED"
    touch(case, CLOCK)
    txn = db.card_transactions[cb["card_transaction_id"]]
    txn["status"] = "DISPUTED"
    touch(txn, CLOCK)
    return success_object(serialize_chargeback(cb), 200)


# ---------------------------------------------------------------------------
# Provisional credit reverse / reinstate
# ---------------------------------------------------------------------------


@bp.route("/provisional-credits/<credit_id>/reverse", methods=["POST"])
def reverse_credit(credit_id):
    middleware.authenticate()
    middleware.require_roles("FinanceOfficer")
    body = get_body()
    validate_body(body, [])
    credit = db.provisional_credits.get(credit_id)
    if credit is None:
        raise errors.not_found("ProvisionalCredit not found")
    if credit["status"] not in OPEN_CREDIT_STATUSES:
        raise errors.invalid_state("Reverse requires the credit to be GRANTED or REINSTATED")
    case = db.dispute_cases[credit["dispute_case_id"]]
    if case["status"] != "REVERSAL_PENDING":
        raise errors.invalid_state("Reverse requires the case to be REVERSAL_PENDING")
    # Temporal tier: REVERSAL_NOTICE 3-business-day cooling
    if not reversal_notice_cooled(case["id"], CLOCK):
        raise errors.reversal_notice_pending()

    account = db.card_accounts[case["card_account_id"]]
    account["balance_cents"] -= credit["amount_cents"]
    touch(account, CLOCK)
    credit["status"] = "REVERSED"
    credit["reversed_at"] = CLOCK.now_iso()
    touch(credit, CLOCK)

    # Cascade: case REVERSAL_PENDING -> RESOLVED_MERCHANT_FAVOR
    case["status"] = "RESOLVED_MERCHANT_FAVOR"
    touch(case, CLOCK)
    add_notification(
        case["id"],
        "RESOLUTION_LETTER",
        "Your provisional credit has been reversed; the dispute is resolved in the merchant's favor.",
        CLOCK,
    )
    settle_transaction(case, CLOCK)
    maybe_restore_account(account, CLOCK)
    return success_object(serialize_credit(credit), 200)


@bp.route("/provisional-credits/<credit_id>/reinstate", methods=["POST"])
def reinstate_credit(credit_id):
    middleware.authenticate()
    middleware.require_roles("FinanceOfficer")
    body = get_body()
    validate_body(body, [])
    credit = db.provisional_credits.get(credit_id)
    if credit is None:
        raise errors.not_found("ProvisionalCredit not found")
    if credit["status"] != "REVERSED":
        raise errors.invalid_state("Reinstate requires the credit to be REVERSED")
    case = db.dispute_cases[credit["dispute_case_id"]]
    if case["status"] != "RESOLVED_MERCHANT_FAVOR":
        raise errors.invalid_state("Reinstate requires the case to be RESOLVED_MERCHANT_FAVOR")

    account = db.card_accounts[case["card_account_id"]]
    account["balance_cents"] += credit["amount_cents"]
    touch(account, CLOCK)
    credit["status"] = "REINSTATED"
    touch(credit, CLOCK)

    # Cascade: case flips to RESOLVED_CARDHOLDER_FAVOR with a loss auto-entry
    record_loss_entry(case["id"], "LOSS_RECOGNIZED", credit["amount_cents"], "AUTO", CLOCK)
    add_notification(
        case["id"],
        "RESOLUTION_LETTER",
        "Your provisional credit has been reinstated; the dispute is resolved in your favor.",
        CLOCK,
    )
    case["status"] = "RESOLVED_CARDHOLDER_FAVOR"
    touch(case, CLOCK)
    return success_object(serialize_credit(credit), 200)
