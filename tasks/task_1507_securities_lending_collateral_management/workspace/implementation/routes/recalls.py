"""Recall endpoints."""

from flask import Blueprint, request
from datetime import datetime
import db
import errors
from middleware import get_auth, require_roles, check_entity_scope
from response import success_object, success_list
from services import calculations as calc
from services.state_machines import (
    _touch, _post_ledger, _settle_loan, _complete_recall, _find_open_recall,
)
from routes.helpers import (
    get_json_body, require_fields, validate_positive_int, validate_enum,
    validate_date_string, get_or_404, paginate, serialize_common,
)

bp = Blueprint("recalls", __name__)

ALL_ROLES = ["DeskAdmin", "DeskTrader", "BorrowerRep", "OwnerRep", "RiskOfficer", "OpsSettler"]
RECALL_REASONS = ["SALE", "CORPORATE_ACTION", "VOTE", "PORTFOLIO_REBALANCE"]


@bp.route("/api/loans/<loan_id>/recalls", methods=["POST"])
def create_recall(loan_id):
    user_id, role = get_auth()
    require_roles(role, ["OwnerRep"])
    loan = get_or_404(db.loans, loan_id, "Loan")
    check_entity_scope(role, user_id, owner_id=loan["owner_id"])

    if loan["status"] != "BOOKED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not BOOKED")

    body = get_json_body()
    require_fields(body, ["quantity", "reason", "deadline_date"])
    validate_positive_int(body["quantity"], "quantity")
    validate_enum(body["reason"], RECALL_REASONS, "reason")
    validate_date_string(body["deadline_date"], "deadline_date")

    # Full recall only
    if body["quantity"] != loan["outstanding_quantity"]:
        raise errors.make_error(errors.ERR_VALIDATION, "Recall quantity must equal outstanding_quantity (full recall only)")

    # One non-terminal recall per loan
    existing = _find_open_recall(loan_id)
    if existing:
        raise errors.make_error(errors.ERR_RECALL_ALREADY_OPEN, "Loan already has a non-terminal recall")

    # Deadline strictly after today
    today = db.current_date_str()
    if body["deadline_date"] <= today:
        raise errors.make_error(errors.ERR_RECALL_WINDOW_INVALID, "Deadline must be strictly after current date")

    recall = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "loan_id": loan_id,
        "owner_id": loan["owner_id"],
        "quantity": body["quantity"],
        "reason": body["reason"],
        "issue_date": today,
        "deadline_date": body["deadline_date"],
        "delivered_quantity": 0,
        "extended_once": False,
        "fail_price_cents": None,
        "fail_fee_cents": 0,
        "status": "ISSUED",
    }
    db.recalls[recall["id"]] = recall

    # Loan -> RECALLED
    loan["status"] = "RECALLED"
    _touch(loan)
    calc.recompute_loan_derived(loan)

    return success_object(serialize_common(recall), 201)


@bp.route("/api/recalls/<recall_id>", methods=["GET"])
def get_recall(recall_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    recall = get_or_404(db.recalls, recall_id, "Recall")
    return success_object(serialize_common(recall))


@bp.route("/api/recalls", methods=["GET"])
def list_recalls():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    filters = {
        "loan_id": request.args.get("loan_id"),
        "owner_id": request.args.get("owner_id"),
        "status": request.args.get("status"),
    }
    # Entity-backed scoping
    if role == "OwnerRep":
        if filters["owner_id"] and filters["owner_id"] != user_id:
            raise errors.make_error(errors.ERR_FORBIDDEN, "OwnerRep must pass own id as owner_id filter")
        filters["owner_id"] = user_id

    items = list(db.recalls.values())
    for key in ("loan_id", "owner_id", "status"):
        if filters[key]:
            items = [r for r in items if r.get(key) == filters[key]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(r) for r in page], limit, offset, total)


@bp.route("/api/recalls/<recall_id>/extend", methods=["POST"])
def extend_recall(recall_id):
    user_id, role = get_auth()
    require_roles(role, ["OwnerRep"])
    recall = get_or_404(db.recalls, recall_id, "Recall")
    check_entity_scope(role, user_id, owner_id=recall["owner_id"])

    if recall["status"] != "ISSUED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Recall is not ISSUED")
    if recall["extended_once"]:
        raise errors.make_error(errors.ERR_RECALL_ALREADY_EXTENDED, "Recall was already extended")

    body = get_json_body()
    require_fields(body, ["new_deadline_date"])
    validate_date_string(body["new_deadline_date"], "new_deadline_date")

    if body["new_deadline_date"] <= recall["deadline_date"]:
        raise errors.make_error(errors.ERR_RECALL_WINDOW_INVALID, "Extension must push deadline later")

    recall["deadline_date"] = body["new_deadline_date"]
    recall["extended_once"] = True
    recall["status"] = "EXTENDED"
    _touch(recall)
    return success_object(serialize_common(recall))


@bp.route("/api/recalls/<recall_id>/cancel", methods=["POST"])
def cancel_recall(recall_id):
    user_id, role = get_auth()
    require_roles(role, ["OwnerRep"])
    recall = get_or_404(db.recalls, recall_id, "Recall")
    check_entity_scope(role, user_id, owner_id=recall["owner_id"])

    if recall["status"] not in ("ISSUED", "EXTENDED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Recall is not ISSUED or EXTENDED")
    if recall["delivered_quantity"] > 0:
        raise errors.make_error(errors.ERR_RECALL_PARTIALLY_DELIVERED, "Recall has deliveries")

    recall["status"] = "CANCELLED"
    _touch(recall)

    # Loan back to BOOKED
    loan = db.loans[recall["loan_id"]]
    if loan["status"] == "RECALLED":
        loan["status"] = "BOOKED"
        _touch(loan)
        calc.recompute_loan_derived(loan)

    return success_object(serialize_common(recall))


@bp.route("/api/recalls/<recall_id>/buy-in", methods=["POST"])
def buy_in_recall(recall_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskTrader"])
    recall = get_or_404(db.recalls, recall_id, "Recall")

    if recall["status"] != "FAILED":
        raise errors.make_error(errors.ERR_BUY_IN_NOT_ALLOWED, "Buy-in requires FAILED recall")

    body = get_json_body()
    require_fields(body, ["buy_in_price_cents"])
    validate_positive_int(body["buy_in_price_cents"], "buy_in_price_cents")

    loan = db.loans[recall["loan_id"]]
    undelivered = recall["quantity"] - recall["delivered_quantity"]
    buy_in_date = db.clock.now().date()
    deadline = datetime.strptime(recall["deadline_date"], "%Y-%m-%d").date()

    # Finalize fail fee for undelivered remainder
    fee_days = max(0, (buy_in_date - deadline).days)
    fail_fee = calc.compute_fail_fee_for_tranche(undelivered, recall["fail_price_cents"], fee_days)
    recall["fail_fee_cents"] += fail_fee

    # Post FAIL_FEE entry if > 0
    if recall["fail_fee_cents"] > 0:
        _post_ledger(
            loan_id=loan["id"],
            owner_id=loan["owner_id"],
            entry_type="FAIL_FEE",
            amount_cents=-recall["fail_fee_cents"],
            accrual_date=db.current_date_str(),
            note="buy_in_fail_fee",
        )

    # Post BUY_IN_CHARGE
    buy_in_charge = calc.compute_buy_in_charge(undelivered, body["buy_in_price_cents"])
    _post_ledger(
        loan_id=loan["id"],
        owner_id=loan["owner_id"],
        entry_type="BUY_IN_CHARGE",
        amount_cents=-buy_in_charge,
        accrual_date=db.current_date_str(),
        note="buy_in_charge",
    )

    recall["status"] = "BOUGHT_IN"
    recall["_bought_in_date"] = db.current_date_str()
    _touch(recall)

    # Loan -> SETTLED with settlement cascade. The buy-in is the mutation,
    # so bump the loan version here exactly once.
    loan["outstanding_quantity"] = 0
    _touch(loan)
    _settle_loan(loan)

    return success_object(serialize_common(recall))
