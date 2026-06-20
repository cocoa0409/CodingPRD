"""Card issuance and lifecycle (PRD §3.2)."""
from flask import Blueprint

import errors
from db import db, stamp_create, touch, LOCK
from middleware import get_user_context, require_role, get_json_body
from response import success, success_list
from services.common import (
    get_or_404, require_fields, validate_enum, paginate, serialize,
    recompute_held, q as _q, filter_items as _filter,
)

bp = Blueprint("cards", __name__)


@bp.route("/cards", methods=["POST"])
def create_card():
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    body = get_json_body()
    require_fields(body, ["company_id", "employee_id", "spend_policy_id",
                          "form_factor", "card_limit_cents"])
    validate_enum(body, "form_factor", {"VIRTUAL", "PHYSICAL"})
    with LOCK:
        # company resolved before child references that also appear in the body.
        get_or_404(db.companies, body["company_id"])
        get_or_404(db.employees, body["employee_id"])
        get_or_404(db.spend_policies, body["spend_policy_id"])
        status = "ACTIVE" if body["form_factor"] == "VIRTUAL" else "REQUESTED"
        card = {
            "company_id": body["company_id"],
            "employee_id": body["employee_id"],
            "spend_policy_id": body["spend_policy_id"],
            "form_factor": body["form_factor"],
            "card_limit_cents": body["card_limit_cents"],
            "held_cents": 0,
            "status": status,
        }
        stamp_create(card)
        db.cards[card["id"]] = card
        return success(serialize(card), 201)


@bp.route("/cards/<card_id>", methods=["GET"])
def get_card(card_id):
    get_user_context()
    with LOCK:
        card = get_or_404(db.cards, card_id)
        recompute_held(card)
        return success(serialize(card), 200)


@bp.route("/cards", methods=["GET"])
def list_cards():
    get_user_context()
    with LOCK:
        items = list(db.cards.values())
        items = _filter(items, {
            "company_id": _q("company_id"),
            "employee_id": _q("employee_id"),
            "spend_policy_id": _q("spend_policy_id"),
            "status": _q("status"),
        })
        for c in items:
            recompute_held(c)
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


def _company_active(card):
    company = db.companies.get(card["company_id"])
    return company is not None and company["status"] == "ACTIVE", company


@bp.route("/cards/<card_id>/activate", methods=["POST"])
def activate_card(card_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        card = get_or_404(db.cards, card_id)
        # Generic state check first (§2.10): activate is defined only REQUESTED->ACTIVE.
        if card["status"] != "REQUESTED":
            raise errors.err(errors.ERR_INVALID_STATE, "Card cannot be activated from its current state.")
        active, _ = _company_active(card)
        if not active:
            raise errors.err(errors.ERR_COMPANY_SUSPENDED, "Company is suspended.")
        card["status"] = "ACTIVE"
        touch(card)
        return success(serialize(card), 200)


@bp.route("/cards/<card_id>/freeze", methods=["POST"])
def freeze_card(card_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        card = get_or_404(db.cards, card_id)
        if card["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE card can be frozen.")
        card["status"] = "FROZEN"
        touch(card)
        return success(serialize(card), 200)


@bp.route("/cards/<card_id>/unfreeze", methods=["POST"])
def unfreeze_card(card_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        card = get_or_404(db.cards, card_id)
        if card["status"] != "FROZEN":
            raise errors.err(errors.ERR_INVALID_STATE, "Only a FROZEN card can be unfrozen.")
        active, _ = _company_active(card)
        if not active:
            raise errors.err(errors.ERR_COMPANY_SUSPENDED, "Company is suspended.")
        card["status"] = "ACTIVE"
        touch(card)
        return success(serialize(card), 200)


@bp.route("/cards/<card_id>/terminate", methods=["POST"])
def terminate_card(card_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        card = get_or_404(db.cards, card_id)
        if card["status"] not in ("ACTIVE", "FROZEN"):
            raise errors.err(errors.ERR_INVALID_STATE, "Card cannot be terminated from its current state.")
        # No transaction with auth_status == PENDING.
        for tx in db.transactions.values():
            if tx["card_id"] == card["id"] and tx["auth_status"] == "PENDING":
                raise errors.err(errors.ERR_CARD_HAS_OPEN_AUTH,
                                 "Card has an open (PENDING) authorization.")
        card["status"] = "TERMINATED"
        touch(card)
        return success(serialize(card), 200)
