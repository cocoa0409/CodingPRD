"""DeaccessionProposal routes (PRD §3.8) — board governance, SoD, cooling-off,
SALE proceeds, and the depth-3 finalize cascade."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES, ERR_ITEMS_IN_TREATMENT,
    ERR_COOLING_OFF_NOT_ELAPSED, ERR_HAMMER_PRICE_MISSING,
)
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from services.deaccession import finalize_cascade
from util import (
    get_json_body, as_str, as_enum, as_str_list, check_no_duplicates,
    paginate, public_view,
)

bp = Blueprint("proposals", __name__)

DISPOSAL_METHODS = {"SALE", "TRANSFER", "DESTRUCTION", "RETURN_TO_DONOR"}
COOLING_OFF_DAYS = 30


def serialize_proposal(p: dict) -> dict:
    return public_view(p)


def _get_proposal(pid: str) -> dict:
    p = db.proposals.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, f"DeaccessionProposal not found: {pid}")
    return p


def _items_in_treatment_check(prop: dict):
    for iid in prop["item_ids"]:
        item = db.items.get(iid)
        if item is not None and item["status"] == "IN_TREATMENT":
            raise_err(ERR_ITEMS_IN_TREATMENT, f"Item {iid} is IN_TREATMENT")


@bp.route("/deaccession-proposals", methods=["POST"])
@require_roles("Registrar")
def create_proposal(_user_id: str, _role: str):
    body = get_json_body()
    item_ids = as_str_list(body, "item_ids", required=True)
    if len(item_ids) == 0:
        raise_err(ERR_INVALID_REQUEST, "item_ids must contain at least one entry")
    check_no_duplicates(item_ids)
    justification = as_str(body, "justification", required=True)
    disposal_method = as_enum(body, "disposal_method", DISPOSAL_METHODS, required=True)

    for iid in item_ids:
        item = db.items.get(iid)
        if item is None:
            raise_err(ERR_NOT_FOUND, f"Item not found: {iid}")
    for iid in item_ids:
        if db.items[iid]["status"] == "DEACCESSIONED":
            raise_err(ERR_INVALID_STATE, f"Item {iid} is already DEACCESSIONED")

    prop = {
        **db.make_common_fields(),
        "item_ids": list(item_ids),
        "justification": justification,
        "disposal_method": disposal_method,
        "proposed_by_user_id": _user_id,
        "approved_by_user_id": None,
        "approved_at": None,
        "finalize_not_before": None,
        "hammer_prices": None,
        "proceeds_cents": None,
        "status": "DRAFT",
        "_finalize_not_before_dt": None,
    }
    db.proposals[prop["id"]] = prop
    return success_object(serialize_proposal(prop), 201)


@bp.route("/deaccession-proposals", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_proposals(_user_id: str, _role: str):
    status = request.args.get("status")
    rows = list(db.proposals.values())
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    page, limit, offset, total = paginate(rows)
    return success_list([serialize_proposal(p) for p in page], limit, offset, total)


@bp.route("/deaccession-proposals/<pid>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_proposal(pid: str, _user_id: str, _role: str):
    return success_object(serialize_proposal(_get_proposal(pid)))


@bp.route("/deaccession-proposals/<pid>/submit", methods=["POST"])
@require_roles("Registrar")
def submit(pid: str, _user_id: str, _role: str):
    p = _get_proposal(pid)
    if p["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT proposal may be submitted")
    p["status"] = "SUBMITTED"
    db.touch(p)
    return success_object(serialize_proposal(p))


@bp.route("/deaccession-proposals/<pid>/send-to-board", methods=["POST"])
@require_roles("Registrar")
def send_to_board(pid: str, _user_id: str, _role: str):
    p = _get_proposal(pid)
    if p["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED proposal may be sent to the board")
    p["status"] = "BOARD_REVIEW"
    db.touch(p)
    return success_object(serialize_proposal(p))


@bp.route("/deaccession-proposals/<pid>/approve", methods=["POST"])
@require_roles("BoardOfficer")
def approve(pid: str, _user_id: str, _role: str):
    p = _get_proposal(pid)
    if p["status"] != "BOARD_REVIEW":
        raise_err(ERR_INVALID_STATE, "Only a BOARD_REVIEW proposal may be approved")
    # segregation of duties (priority 8)
    if p["proposed_by_user_id"] == _user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The approver must differ from the proposer")
    # no proposed item in treatment (priority 10)
    _items_in_treatment_check(p)

    p["approved_by_user_id"] = _user_id
    p["approved_at"] = db.now_iso()
    fnb_dt = db.get_now() + timedelta(days=COOLING_OFF_DAYS)
    p["_finalize_not_before_dt"] = fnb_dt
    p["finalize_not_before"] = db.format_ts(fnb_dt)
    p["status"] = "APPROVED"
    db.touch(p)
    return success_object(serialize_proposal(p))


@bp.route("/deaccession-proposals/<pid>/reject", methods=["POST"])
@require_roles("BoardOfficer")
def reject(pid: str, _user_id: str, _role: str):
    p = _get_proposal(pid)
    # no segregation-of-duties check on rejection (pinned asymmetry)
    if p["status"] != "BOARD_REVIEW":
        raise_err(ERR_INVALID_STATE, "Only a BOARD_REVIEW proposal may be rejected")
    p["status"] = "REJECTED"
    db.touch(p)
    return success_object(serialize_proposal(p))


@bp.route("/deaccession-proposals/<pid>/withdraw", methods=["POST"])
@require_roles("Registrar")
def withdraw(pid: str, _user_id: str, _role: str):
    p = _get_proposal(pid)
    if p["status"] not in ("DRAFT", "SUBMITTED"):
        raise_err(ERR_INVALID_STATE, "Only a DRAFT or SUBMITTED proposal may be withdrawn")
    p["status"] = "WITHDRAWN"
    db.touch(p)
    return success_object(serialize_proposal(p))


@bp.route("/deaccession-proposals/<pid>/finalize", methods=["POST"])
@require_roles("Registrar")
def finalize(pid: str, _user_id: str, _role: str):
    body = get_json_body()
    hammer_prices = body.get("hammer_prices")
    if hammer_prices is not None:
        if not isinstance(hammer_prices, list):
            raise_err(ERR_INVALID_REQUEST, "Field 'hammer_prices' must be an array")
        normalized = []
        for entry in hammer_prices:
            if not isinstance(entry, dict) or not isinstance(entry.get("item_id"), str):
                raise_err(ERR_INVALID_REQUEST, "hammer_prices entries must carry an item_id string")
            price = entry.get("price_cents")
            if isinstance(price, bool) or not isinstance(price, (int, Decimal)):
                raise_err(ERR_INVALID_REQUEST, "hammer_prices entries must carry a non-negative integer price_cents")
            if isinstance(price, Decimal):
                if price != price.to_integral_value():
                    raise_err(ERR_INVALID_REQUEST, "hammer_prices price_cents must be an integer")
                price = int(price)
            if price < 0:
                raise_err(ERR_INVALID_REQUEST, "hammer_prices price_cents must be non-negative")
            normalized.append({"item_id": entry["item_id"], "price_cents": price})
        hammer_prices = normalized

    p = _get_proposal(pid)

    # priority 5/9: state gate — APPROVED surfaces as cooling-off-not-elapsed
    if p["status"] == "APPROVED":
        raise_err(ERR_COOLING_OFF_NOT_ELAPSED, "The 30-day cooling-off period has not elapsed")
    if p["status"] != "COOLED_OFF":
        raise_err(ERR_INVALID_STATE, "Only a COOLED_OFF proposal may be finalized")

    # priority 10: no proposed item in treatment
    _items_in_treatment_check(p)

    # priority 12: SALE requires exactly one hammer price per proposed item
    if p["disposal_method"] == "SALE":
        if hammer_prices is None:
            raise_err(ERR_HAMMER_PRICE_MISSING, "SALE finalization requires hammer_prices")
        seen = [e["item_id"] for e in hammer_prices]
        if len(set(seen)) != len(seen) or set(seen) != set(p["item_ids"]):
            raise_err(ERR_HAMMER_PRICE_MISSING, "hammer_prices must cover every proposed item exactly once")
        p["hammer_prices"] = [
            {"item_id": e["item_id"], "price_cents": e["price_cents"]} for e in hammer_prices
        ]

    finalize_cascade(p)
    return success_object(serialize_proposal(p))
