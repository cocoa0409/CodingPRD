"""Purchase transaction routes."""

from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.calculations import fraud_velocity_should_flag
from util import (
    get_json_body, require_nonempty_str, parse_pagination, paginate, new_id,
    get_card_or_parent_404,
)


bp = Blueprint("purchase_transactions", __name__)


def _tx_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "ebt_card_id": t["ebt_card_id"],
        "household_id": t["household_id"],
        "merchant_id": t["merchant_id"],
        "total_cents": t.get("total_cents", 0),
        "line_items": t.get("line_items", []),
        "ineligible_line_codes": t.get("ineligible_line_codes", []),
        "status": t["status"],
        "settled_at": t.get("settled_at"),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def _category_eligibility_map():
    return {c["code"]: c["eligible"] for c in db.eligible_categories.values()}


@bp.route("/snap/purchase-transactions", methods=["POST"])
@require_roles("Merchant")
def create_transaction(**_):
    body = get_json_body()
    ebt_card_id = require_nonempty_str(body, "ebt_card_id")
    merchant_id = require_nonempty_str(body, "merchant_id")

    card = get_card_or_parent_404(ebt_card_id)

    line_items = body.get("line_items", None)
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise_api("ERR_INVALID_LINE_ITEMS", "line_items must be a non-empty array")

    # Validate each line item structure & resolve category
    cat_map = _category_eligibility_map()
    normalised_items = []
    ineligible_codes = []
    total = 0

    # First pass: structural validation
    for idx, item in enumerate(line_items):
        if not isinstance(item, dict):
            raise_api("ERR_INVALID_LINE_ITEMS", f"line_items[{idx}] must be an object")
        code = item.get("category_code")
        amt = item.get("amount_cents")
        qty = item.get("quantity")
        if not isinstance(code, str) or not code:
            raise_api("ERR_INVALID_LINE_ITEMS", f"line_items[{idx}].category_code missing")
        if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
            raise_api("ERR_INVALID_LINE_ITEMS", f"line_items[{idx}].amount_cents must be > 0")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise_api("ERR_INVALID_LINE_ITEMS", f"line_items[{idx}].quantity must be >= 1")
        if code not in cat_map:
            raise_api("ERR_INVALID_LINE_ITEMS",
                      f"line_items[{idx}].category_code {code} unknown")
        normalised_items.append({
            "category_code": code,
            "amount_cents": amt,
            "quantity": qty,
        })

    for item in normalised_items:
        if cat_map[item["category_code"]]:
            total += item["amount_cents"]
        else:
            ineligible_codes.append(item["category_code"])

    if total == 0:
        raise_api("ERR_ALL_ITEMS_INELIGIBLE",
                  "All line items resolve to ineligible categories")

    hh_id = card["household_id"]
    hh = db.households.get(hh_id)

    # Out-of-state check: scaffold/PRD says merchant_id implies a location.
    # The PRD does not specify how to derive merchant location from merchant_id.
    # Judgement call: treat merchant_id starting with "<STATE>_" (e.g. "TX_...") as the
    # state hint; if the merchant_id contains a two-letter state code prefix followed by "_",
    # use that. Otherwise assume merchant is in-state (no out-of-state condition triggered).
    # Then: if household already has any FraudFlag of OUT_OF_STATE that is OPEN/UNDER_REVIEW/SUBSTANTIATED,
    # second occurrence (when current is also out-of-state) is blocked.
    out_of_state = False
    if hh is not None and len(merchant_id) >= 3 and merchant_id[2] == "_":
        prefix = merchant_id[:2]
        if prefix.isalpha() and prefix.isupper():
            out_of_state = (prefix != hh["state_code"])

    if out_of_state:
        prior_flag_exists = any(
            f["household_id"] == hh_id
            and f["trigger_rule"] == "OUT_OF_STATE"
            and f["status"] in ("OPEN", "UNDER_REVIEW", "SUBSTANTIATED")
            for f in db.fraud_flags.values()
        )
        if prior_flag_exists:
            raise_api("ERR_OUT_OF_STATE_BLOCKED",
                      "Out-of-state purchase blocked: prior OUT_OF_STATE flag exists")

    now = db.current_utc_iso()
    t = {
        "id": new_id(),
        "ebt_card_id": ebt_card_id,
        "household_id": hh_id,
        "merchant_id": merchant_id,
        "total_cents": total,
        "line_items": normalised_items,
        "ineligible_line_codes": ineligible_codes,
        "status": "AUTHORIZED",
        "settled_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.purchase_transactions[t["id"]] = t

    # If out-of-state and no prior flag, this attempt RAISES the first OUT_OF_STATE flag.
    if out_of_state:
        flag_now = db.current_utc_iso()
        flag = {
            "id": new_id(),
            "household_id": hh_id,
            "trigger_rule": "OUT_OF_STATE",
            "status": "OPEN",
            "investigator_id": None,
            "resolution_note": None,
            "created_at": flag_now,
            "updated_at": flag_now,
            "version": 1,
        }
        db.fraud_flags[flag["id"]] = flag

    return success(_tx_view(t), 201)


@bp.route("/snap/purchase-transactions/<tx_id>", methods=["GET"])
@require_roles("Merchant", "Caseworker", "FraudInvestigator")
def get_transaction(tx_id, **_):
    t = db.purchase_transactions.get(tx_id)
    if t is None:
        raise_api("ERR_NOT_FOUND", "PurchaseTransaction not found")
    return success(_tx_view(t))


@bp.route("/snap/purchase-transactions", methods=["GET"])
@require_roles("Merchant", "Caseworker", "FraudInvestigator")
def list_transactions(**_):
    limit, offset = parse_pagination()
    ebt_filter = request.args.get("ebt_card_id")
    hh_filter = request.args.get("household_id")
    status_filter = request.args.get("status")

    rows = list(db.purchase_transactions.values())
    if ebt_filter is not None:
        rows = [r for r in rows if r["ebt_card_id"] == ebt_filter]
    if hh_filter is not None:
        rows = [r for r in rows if r["household_id"] == hh_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]

    page, total = paginate(rows, limit, offset)
    return list_success([_tx_view(r) for r in page], limit, offset, total)


@bp.route("/snap/purchase-transactions/<tx_id>/settle", methods=["POST"])
@require_roles("Merchant")
def settle_transaction(tx_id, **_):
    t = db.purchase_transactions.get(tx_id)
    if t is None:
        raise_api("ERR_NOT_FOUND", "PurchaseTransaction not found")
    if t["status"] != "AUTHORIZED":
        raise_api("ERR_INVALID_STATE", "PurchaseTransaction must be AUTHORIZED to settle")
    card = db.ebt_cards.get(t["ebt_card_id"])
    if card is None or card["status"] != "ACTIVE":
        raise_api("ERR_CARD_NOT_ACTIVE", "EBT card must be ACTIVE for settlement")

    # Mandatory order: write settled_at/status FIRST, then evaluate aggregate.
    now = db.current_utc_iso()
    t["status"] = "SETTLED"
    t["settled_at"] = now
    t["updated_at"] = now
    t["version"] = int(t.get("version", 1)) + 1

    # Velocity recomputation includes the just-settled row.
    if fraud_velocity_should_flag(t["household_id"]):
        flag_now = db.current_utc_iso()
        flag = {
            "id": new_id(),
            "household_id": t["household_id"],
            "trigger_rule": "VELOCITY_SPIKE",
            "status": "OPEN",
            "investigator_id": None,
            "resolution_note": None,
            "created_at": flag_now,
            "updated_at": flag_now,
            "version": 1,
        }
        db.fraud_flags[flag["id"]] = flag

    return success(_tx_view(t))


@bp.route("/snap/purchase-transactions/<tx_id>/reverse", methods=["POST"])
@require_roles("Merchant")
def reverse_transaction(tx_id, **_):
    t = db.purchase_transactions.get(tx_id)
    if t is None:
        raise_api("ERR_NOT_FOUND", "PurchaseTransaction not found")
    if t["status"] != "AUTHORIZED":
        raise_api("ERR_INVALID_STATE", "PurchaseTransaction must be AUTHORIZED to reverse")

    t["status"] = "REVERSED"
    t["updated_at"] = db.current_utc_iso()
    t["version"] = int(t.get("version", 1)) + 1
    return success(_tx_view(t))
