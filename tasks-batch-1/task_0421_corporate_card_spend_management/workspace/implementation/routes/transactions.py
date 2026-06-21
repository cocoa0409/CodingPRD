"""Transaction capture & lifecycle, receipts, approval-requests, review (PRD §3.3-§3.5)."""
from flask import Blueprint

import errors
from db import db, stamp_create, stamp_create_no_version, touch, LOCK
from middleware import get_user_context, require_role, get_json_body
from response import success, success_list
from services.common import (
    get_or_404, require_fields, require_positive_int, as_int_field, paginate, serialize,
    recompute_held, recompute_available_credit, open_statement_for, reward_account_for,
    RECEIPT_REQUIRED_THRESHOLD_CENTS, RECEIPT_TOLERANCE_CENTS,
    q as _q, filter_items as _filter,
)
from services.calculations import compute_transaction_reward

bp = Blueprint("transactions", __name__)


def _company_of(tx):
    return db.companies.get(tx["company_id"])


def _policy_of_card(card):
    return db.spend_policies.get(card["spend_policy_id"])


# ----------------------------------------------------- Capture (authorization)
@bp.route("/cards/<card_id>/transactions", methods=["POST"])
def capture_transaction(card_id):
    _, role = get_user_context()
    require_role(role, {"CardholderEmployee", "FinanceAdmin"})
    body = get_json_body()
    with LOCK:
        card = get_or_404(db.cards, card_id)  # existence (§2.10 step 3)
        require_fields(body, ["merchant_name", "mcc_code", "amount_cents"])  # body shape (step 4)
        amount = require_positive_int(body, "amount_cents")  # positivity (step 5)
        gl_id = body.get("gl_account_id")
        if gl_id is not None:
            get_or_404(db.gl_accounts, gl_id)

        company = _company_of(card)
        policy = _policy_of_card(card)
        mcc = str(body["mcc_code"])

        # Capture gate precedence (§2.9):
        # 1. merchant-category block
        if policy is not None and mcc in [str(m) for m in (policy.get("blocked_mcc_codes") or [])]:
            raise errors.err(errors.ERR_MCC_BLOCKED, "Merchant category is blocked.")
        # 2. card must be ACTIVE
        if card["status"] != "ACTIVE":
            raise errors.err(errors.ERR_CARD_NOT_ACTIVE, "Card is not ACTIVE.")
        # 3. per-transaction policy ceiling
        if policy is not None and amount > policy["per_transaction_limit_cents"]:
            raise errors.err(errors.ERR_PER_TXN_LIMIT_EXCEEDED, "Exceeds per-transaction limit.")
        # 4. card remaining headroom
        recompute_held(card)
        if amount > (card["card_limit_cents"] - card["held_cents"]):
            raise errors.err(errors.ERR_CARD_LIMIT_EXCEEDED, "Exceeds card headroom.")
        # 5. company credit pool
        recompute_available_credit(company)
        if amount > company["available_credit_cents"]:
            raise errors.err(errors.ERR_INSUFFICIENT_CREDIT, "Exceeds available credit.")

        review = "NEEDS_RECEIPT" if amount > RECEIPT_REQUIRED_THRESHOLD_CENTS else "UNREVIEWED"
        tx = {
            "card_id": card_id,
            "company_id": card["company_id"],
            "statement_id": None,
            "merchant_name": body["merchant_name"],
            "mcc_code": mcc,
            "amount_cents": amount,
            "settled_amount_cents": None,
            "gl_account_id": gl_id,
            "reward_points_cents": 0,
            "auth_status": "PENDING",
            "review_status": review,
        }
        stamp_create(tx)
        db.transactions[tx["id"]] = tx

        # Place the hold: recompute derived parents.
        recompute_held(card)
        touch(card)
        recompute_available_credit(company)
        touch(company)
        return success(serialize(tx), 201)


@bp.route("/transactions/<tx_id>", methods=["GET"])
def get_transaction(tx_id):
    get_user_context()
    with LOCK:
        return success(serialize(get_or_404(db.transactions, tx_id)), 200)


@bp.route("/transactions", methods=["GET"])
def list_transactions():
    get_user_context()
    with LOCK:
        items = list(db.transactions.values())
        items = _filter(items, {
            "card_id": _q("card_id"),
            "company_id": _q("company_id"),
            "statement_id": _q("statement_id"),
            "gl_account_id": _q("gl_account_id"),
            "auth_status": _q("auth_status"),
            "review_status": _q("review_status"),
        })
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


# ----------------------------------------------------- GL coding (PATCH)
@bp.route("/transactions/<tx_id>", methods=["PATCH"])
def code_transaction(tx_id):
    _, role = get_user_context()
    require_role(role, {"CardholderEmployee", "FinanceAdmin"})
    body = get_json_body()
    with LOCK:
        tx = get_or_404(db.transactions, tx_id)
        require_fields(body, ["gl_account_id"])
        gl = get_or_404(db.gl_accounts, body["gl_account_id"])
        if gl["status"] != "ACTIVE":
            raise errors.err(errors.ERR_GL_CODE_REQUIRED, "GL account is not ACTIVE.")
        tx["gl_account_id"] = gl["id"]
        touch(tx)
        return success(serialize(tx), 200)


# ----------------------------------------------------- Auth lifecycle
@bp.route("/transactions/<tx_id>/clear", methods=["POST"])
def clear_transaction(tx_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        tx = get_or_404(db.transactions, tx_id)
        if tx["auth_status"] != "PENDING":
            raise errors.err(errors.ERR_INVALID_STATE, "Transaction is not PENDING.")
        tx["auth_status"] = "CLEARED"
        touch(tx)
        # Hold remains counted; recompute parents (no net change but per §2.7 keep consistent).
        return success(serialize(tx), 200)


@bp.route("/transactions/<tx_id>/settle", methods=["POST"])
def settle_transaction(tx_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    body = get_json_body()
    with LOCK:
        tx = get_or_404(db.transactions, tx_id)
        # Generic state check before endpoint-specific gates (§2.10).
        if tx["auth_status"] != "CLEARED":
            raise errors.err(errors.ERR_INVALID_STATE, "Transaction is not CLEARED.")
        settled = as_int_field(body, "settled_amount_cents")
        if settled <= 0 or settled > tx["amount_cents"]:
            raise errors.err(errors.ERR_INVALID_AMOUNT,
                             "settled_amount_cents must be > 0 and <= amount_cents.")
        company = _company_of(tx)
        if company["status"] != "ACTIVE":
            raise errors.err(errors.ERR_COMPANY_SUSPENDED, "Company is suspended.")

        card = db.cards.get(tx["card_id"])
        policy = _policy_of_card(card) if card else None
        open_stmt = open_statement_for(tx["company_id"])

        tx["settled_amount_cents"] = settled
        tx["statement_id"] = open_stmt["id"] if open_stmt else None
        tx["auth_status"] = "SETTLED"
        # reward accrual (net variant) computed on settled amount.
        reward = compute_transaction_reward(tx, policy, company)
        tx["reward_points_cents"] = reward
        touch(tx)

        # CASCADE: card.held drops (hold released); company available recomputed.
        if card:
            recompute_held(card)
            touch(card)
        recompute_available_credit(company)
        touch(company)

        # CASCADE: reward account accrues.
        ra = reward_account_for(tx["company_id"])
        if ra and reward:
            ra["accrued_points_cents"] += reward
            ra["balance_points_cents"] = ra["accrued_points_cents"] - ra["redeemed_points_cents"]
            touch(ra)
        return success(serialize(tx), 200)


@bp.route("/transactions/<tx_id>/reverse", methods=["POST"])
def reverse_transaction(tx_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        tx = get_or_404(db.transactions, tx_id)
        if tx["auth_status"] not in ("PENDING", "CLEARED"):
            raise errors.err(errors.ERR_INVALID_STATE, "Transaction cannot be reversed from its state.")
        # Net any accrued reward back out (defensive; settled tx are terminal so unreachable).
        prior_reward = tx.get("reward_points_cents", 0)
        tx["auth_status"] = "REVERSED"
        touch(tx)
        card = db.cards.get(tx["card_id"])
        company = _company_of(tx)
        if card:
            recompute_held(card)
            touch(card)
        recompute_available_credit(company)
        touch(company)
        if prior_reward:
            ra = reward_account_for(tx["company_id"])
            if ra:
                ra["accrued_points_cents"] -= prior_reward
                ra["balance_points_cents"] = ra["accrued_points_cents"] - ra["redeemed_points_cents"]
                touch(ra)
        return success(serialize(tx), 200)


# ----------------------------------------------------- Receipts
@bp.route("/transactions/<tx_id>/receipts", methods=["POST"])
def upload_receipt(tx_id):
    _, role = get_user_context()
    require_role(role, {"CardholderEmployee", "FinanceAdmin"})
    body = get_json_body()
    with LOCK:
        tx = get_or_404(db.transactions, tx_id)
        require_fields(body, ["amount_cents", "merchant_name"])
        amount = require_positive_int(body, "amount_cents")
        match = abs(amount - tx["amount_cents"]) <= RECEIPT_TOLERANCE_CENTS
        receipt = {
            "company_id": tx["company_id"],
            "transaction_id": tx["id"],
            "amount_cents": amount,
            "merchant_name": body["merchant_name"],
            "match_result": "MATCH" if match else "MISMATCH",
        }
        stamp_create_no_version(receipt)
        db.receipts[receipt["id"]] = receipt
        # CASCADE: on MATCH, advance review toward MATCHED from NEEDS_RECEIPT/UNREVIEWED.
        if match and tx["review_status"] in ("NEEDS_RECEIPT", "UNREVIEWED"):
            tx["review_status"] = "MATCHED"
            touch(tx)
        return success(serialize(receipt), 201)


@bp.route("/transactions/<tx_id>/receipts", methods=["GET"])
def list_tx_receipts(tx_id):
    get_user_context()
    with LOCK:
        get_or_404(db.transactions, tx_id)
        items = [r for r in db.receipts.values() if r["transaction_id"] == tx_id]
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


@bp.route("/receipts/<receipt_id>", methods=["GET"])
def get_receipt(receipt_id):
    get_user_context()
    with LOCK:
        return success(serialize(get_or_404(db.receipts, receipt_id)), 200)


@bp.route("/receipts", methods=["GET"])
def list_receipts():
    get_user_context()
    with LOCK:
        items = list(db.receipts.values())
        items = _filter(items, {
            "company_id": _q("company_id"),
            "transaction_id": _q("transaction_id"),
        })
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


# ----------------------------------------------------- Review dimension
def _cardholder_of_tx(tx):
    card = db.cards.get(tx["card_id"])
    return card["employee_id"] if card else None


@bp.route("/transactions/<tx_id>/approve-review", methods=["POST"])
def approve_review(tx_id):
    user_id, role = get_user_context()
    require_role(role, {"Approver"})
    get_json_body()
    with LOCK:
        tx = get_or_404(db.transactions, tx_id)
        # 1. review must be MATCHED (else ERR_RECEIPT_REQUIRED for NEEDS_RECEIPT/UNREVIEWED)
        if tx["review_status"] != "MATCHED":
            if tx["review_status"] in ("NEEDS_RECEIPT", "UNREVIEWED"):
                raise errors.err(errors.ERR_RECEIPT_REQUIRED, "A matched receipt is required.")
            raise errors.err(errors.ERR_INVALID_STATE, "Review cannot be approved from its state.")
        # 2. gl_account_id set and references ACTIVE GlAccount
        gl_id = tx.get("gl_account_id")
        gl = db.gl_accounts.get(gl_id) if gl_id else None
        if gl is None or gl["status"] != "ACTIVE":
            raise errors.err(errors.ERR_GL_CODE_REQUIRED, "An active GL code is required.")
        # 3. high-value -> requires an APPROVED ApprovalRequest
        card = db.cards.get(tx["card_id"])
        policy = _policy_of_card(card) if card else None
        if policy is not None and tx["amount_cents"] > policy["approval_threshold_cents"]:
            has_approved = any(
                ar["transaction_id"] == tx["id"] and ar["status"] == "APPROVED"
                for ar in db.approval_requests.values()
            )
            if not has_approved:
                raise errors.err(errors.ERR_APPROVAL_REQUIRED, "An approved approval request is required.")
        # 4. segregation of duties
        if user_id == _cardholder_of_tx(tx):
            raise errors.err(errors.ERR_SELF_APPROVAL, "Cannot approve your own spend.")
        tx["review_status"] = "APPROVED"
        touch(tx)
        return success(serialize(tx), 200)


@bp.route("/transactions/<tx_id>/flag", methods=["POST"])
def flag_transaction(tx_id):
    user_id, role = get_user_context()
    require_role(role, {"Approver"})
    get_json_body()
    with LOCK:
        tx = get_or_404(db.transactions, tx_id)
        if tx["review_status"] not in ("MATCHED", "NEEDS_RECEIPT"):
            raise errors.err(errors.ERR_INVALID_STATE, "Transaction cannot be flagged from its state.")
        if user_id == _cardholder_of_tx(tx):
            raise errors.err(errors.ERR_SELF_APPROVAL, "Cannot flag your own spend.")
        tx["review_status"] = "FLAGGED"
        touch(tx)
        return success(serialize(tx), 200)


# ----------------------------------------------------- ApprovalRequest
@bp.route("/transactions/<tx_id>/approval-requests", methods=["POST"])
def open_approval_request(tx_id):
    _, role = get_user_context()
    require_role(role, {"CardholderEmployee", "FinanceAdmin"})
    get_json_body()
    with LOCK:
        tx = get_or_404(db.transactions, tx_id)
        card = db.cards.get(tx["card_id"])
        policy = _policy_of_card(card) if card else None
        threshold = policy["approval_threshold_cents"] if policy else None
        if threshold is not None and tx["amount_cents"] <= threshold:
            raise errors.err(errors.ERR_APPROVAL_NOT_NEEDED,
                             "Approval is not needed for this transaction.")
        ar = {
            "transaction_id": tx["id"],
            "company_id": tx["company_id"],
            "requester_employee_id": card["employee_id"] if card else None,
            "approver_employee_id": None,
            "decision_note": None,
            "revision_count": 0,
            "status": "PENDING",
        }
        stamp_create(ar)
        db.approval_requests[ar["id"]] = ar
        return success(serialize(ar), 201)


@bp.route("/approval-requests/<ar_id>", methods=["GET"])
def get_approval_request(ar_id):
    get_user_context()
    with LOCK:
        return success(serialize(get_or_404(db.approval_requests, ar_id)), 200)


@bp.route("/approval-requests", methods=["GET"])
def list_approval_requests():
    get_user_context()
    with LOCK:
        items = list(db.approval_requests.values())
        items = _filter(items, {
            "transaction_id": _q("transaction_id"),
            "company_id": _q("company_id"),
            "requester_employee_id": _q("requester_employee_id"),
            "approver_employee_id": _q("approver_employee_id"),
            "status": _q("status"),
        })
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


@bp.route("/approval-requests/<ar_id>/approve", methods=["POST"])
def approve_approval_request(ar_id):
    user_id, role = get_user_context()
    require_role(role, {"Approver"})
    body = get_json_body()
    with LOCK:
        ar = get_or_404(db.approval_requests, ar_id)
        if ar["status"] != "PENDING":
            raise errors.err(errors.ERR_INVALID_STATE, "Approval request is not PENDING.")
        if user_id == ar["requester_employee_id"]:
            raise errors.err(errors.ERR_SELF_APPROVAL, "Cannot approve your own request.")
        tx = db.transactions.get(ar["transaction_id"])
        if tx is not None and tx["auth_status"] == "REVERSED":
            raise errors.err(errors.ERR_INVALID_STATE, "Underlying transaction has been reversed.")
        ar["status"] = "APPROVED"
        ar["approver_employee_id"] = user_id
        if body.get("decision_note") is not None:
            ar["decision_note"] = body["decision_note"]
        touch(ar)
        return success(serialize(ar), 200)


@bp.route("/approval-requests/<ar_id>/reject", methods=["POST"])
def reject_approval_request(ar_id):
    user_id, role = get_user_context()
    require_role(role, {"Approver"})
    body = get_json_body()
    with LOCK:
        ar = get_or_404(db.approval_requests, ar_id)
        if ar["status"] != "PENDING":
            raise errors.err(errors.ERR_INVALID_STATE, "Approval request is not PENDING.")
        if user_id == ar["requester_employee_id"]:
            raise errors.err(errors.ERR_SELF_APPROVAL, "Cannot reject your own request.")
        ar["status"] = "REJECTED"
        ar["approver_employee_id"] = user_id
        if body.get("decision_note") is not None:
            ar["decision_note"] = body["decision_note"]
        touch(ar)
        return success(serialize(ar), 200)


@bp.route("/approval-requests/<ar_id>/resubmit", methods=["POST"])
def resubmit_approval_request(ar_id):
    user_id, role = get_user_context()
    require_role(role, {"CardholderEmployee"})
    get_json_body()
    with LOCK:
        ar = get_or_404(db.approval_requests, ar_id)
        if ar["status"] != "REJECTED":
            raise errors.err(errors.ERR_INVALID_STATE, "Approval request is not REJECTED.")
        if user_id != ar["requester_employee_id"]:
            raise errors.err(errors.ERR_FORBIDDEN_FOR_ROLE, "Only the requester may resubmit.")
        ar["status"] = "PENDING"
        ar["revision_count"] += 1
        ar["approver_employee_id"] = None
        touch(ar)
        return success(serialize(ar), 200)
