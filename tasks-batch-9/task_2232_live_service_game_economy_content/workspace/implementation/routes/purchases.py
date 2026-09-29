"""The purchase path: creation at the personalized quote and settlement (PRD 3.6)."""
from flask import Blueprint, request

import config
import db
import resolve
import validators as v
from db import ordered, serialize
from errors import fail
from middleware import authenticate, require_owner
from response import list_response, object_response, touch
from services import calc, cascades, ledger

bp = Blueprint("purchases", __name__)

READ_ROLES = (
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_COMPLIANCE_OFFICER,
    config.ROLE_ECONOMY_DESIGNER,
    config.ROLE_PLAYER,
)
LIST_ROLES = (
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_COMPLIANCE_OFFICER,
    config.ROLE_ECONOMY_DESIGNER,
)


def _required_currencies(offer):
    """Distinct granted_currency_code values in ascending line-sku order."""
    seen = []
    for line in sorted(offer["line_items"], key=lambda l: l["sku"]):
        if line["granted_currency_code"] not in seen:
            seen.append(line["granted_currency_code"])
    return seen


def _accounts_by_currency(player):
    mapping = {}
    for account in ordered([a for a in db.db.accounts.values() if a["player_id"] == player["id"]]):
        mapping.setdefault(account["currency_code"], account)
    return mapping


@bp.post("/purchases")
def create_purchase():
    user_id, role = authenticate(config.ROLE_PLAYER)
    payload = v.body()
    player = resolve.body_fk(payload, "player_id", db.db.players, "ERR_PLAYER_NOT_FOUND")
    offer = resolve.body_fk(payload, "offer_id", db.db.offers, "ERR_OFFER_NOT_FOUND")
    v.req_string(payload, "player_id")
    v.req_string(payload, "offer_id")
    expected_offer_version = v.req_int(payload, "expected_offer_version", minimum=1)

    require_owner(role, user_id, player["id"])

    if offer["version"] != expected_offer_version:
        fail("ERR_STALE_OFFER_VERSION", "The pinned offer version is stale.")
    if offer["availability_status"] != "LIVE":
        fail("ERR_OFFER_NOT_PURCHASABLE", "The offer is not LIVE on the storefront.")
    if db.now() > offer["window_end"]:
        fail("ERR_OFFER_WINDOW_CLOSED", "The merchandising window has closed.")
    if player["is_minor"] and not player["guardian_verified"]:
        fail("ERR_GUARDIAN_VERIFICATION_REQUIRED", "A guardian has not verified this account.")
    if player["is_minor"] and not offer["minor_purchasable"]:
        fail("ERR_MINOR_OFFER_FORBIDDEN", "The offer is not available to minor accounts.")
    if offer["disclosure_state"] == "REQUIRED_MISSING":
        fail("ERR_DISCLOSURE_NOT_PUBLISHED", "A randomized offer needs a published probability table.")

    accounts = _accounts_by_currency(player)
    for currency in _required_currencies(offer):
        if currency not in accounts:
            fail("ERR_CURRENCY_ACCOUNT_MISSING", "The buyer holds no %s account." % currency)

    if player["spend_state"] == "LOCKED":
        fail("ERR_SPEND_LOCKED", "The player's spending is locked.")
    if player["spend_state"] == "COOLDOWN" and offer["offer_type"] == "LOOT_BOX":
        fail("ERR_SPEND_COOLDOWN_RESTRICTED", "A player in cooldown may not buy randomized offers.")

    quote = calc.personalized_quote(offer, player)
    quoted = quote["quote_minor"]
    if player["is_minor"]:
        projected = player["spend_30d_minor"] + player["pending_spend_minor"] + quoted
        if projected > config.MINOR_MONTHLY_CAP_MINOR:
            fail("ERR_MINOR_SPEND_CAP_EXCEEDED", "The minor monthly spend ceiling would be exceeded.")

    purchase = db.insert(
        db.db.purchases,
        {
            "player_id": player["id"],
            "offer_id": offer["id"],
            "quoted_price_minor": quoted,
            "applied_personalization_bp": quote["applied_personalization_bp"],
            "price_paid_minor": 0,
            "granted_total_minor": 0,
            "granted_consumed_minor": 0,
            "is_minor_purchase": player["is_minor"],
            "status": "PENDING",
            "settled_at": None,
            "deny_reason": None,
        },
    )

    offer["pending_purchase_count"] += 1
    touch(offer)
    season = db.db.seasons.get(offer["season_id"])
    if season is not None:
        season["pending_revenue_minor"] += quoted
        touch(season)
    player["pending_spend_minor"] += quoted
    touch(player)
    return object_response(serialize(purchase), 201)


@bp.get("/purchases/<purchase_id>")
def read_purchase(purchase_id):
    user_id, role = authenticate(*READ_ROLES)
    purchase = resolve.purchase(purchase_id)
    require_owner(role, user_id, purchase["player_id"])
    return object_response(serialize(purchase))


@bp.get("/purchases")
def list_purchases():
    authenticate(*LIST_ROLES)
    player_id = request.args.get("player_id")
    offer_id = request.args.get("offer_id")
    status = v.query_enum("status", config.PURCHASE_STATUSES)
    limit, offset = v.pagination()
    rows = list(db.db.purchases.values())
    if player_id is not None:
        rows = [p for p in rows if p["player_id"] == player_id]
    if offer_id is not None:
        rows = [p for p in rows if p["offer_id"] == offer_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    records = [serialize(p) for p in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/purchases/<purchase_id>/settlement")
def settle_purchase(purchase_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    purchase = resolve.purchase(purchase_id)
    payload = v.body()
    outcome = v.req_enum(payload, "outcome", ("SETTLED", "DENIED"))
    deny_reason = v.opt_string(payload, "deny_reason")

    if purchase["status"] != "PENDING":
        fail("ERR_PURCHASE_INVALID_STATE", "Only a PENDING purchase can be settled or denied.")

    offer = db.db.offers.get(purchase["offer_id"])
    player = db.db.players.get(purchase["player_id"])

    if outcome == "DENIED":
        cascades.deny_purchase(purchase, deny_reason)
        return object_response(serialize(purchase))

    if offer is None or offer["availability_status"] != "LIVE":
        fail("ERR_OFFER_NOT_PURCHASABLE", "The offer is no longer LIVE on the storefront.")

    accounts = _accounts_by_currency(player)
    required = _required_currencies(offer)
    for currency in required:
        account = accounts.get(currency)
        if account is not None and account["status"] == "FROZEN":
            fail("ERR_CURRENCY_ACCOUNT_FROZEN", "The buyer's %s account is frozen." % currency)
    for currency in required:
        if currency not in accounts:
            fail("ERR_CURRENCY_ACCOUNT_MISSING", "The buyer holds no %s account." % currency)
    if player["spend_state"] == "LOCKED":
        fail("ERR_SPEND_LOCKED", "The player's spending is locked.")

    quoted = purchase["quoted_price_minor"]
    purchase["status"] = "SETTLED"
    purchase["price_paid_minor"] = quoted
    purchase["settled_at"] = db.now()

    granted_total = 0
    for line in sorted(offer["line_items"], key=lambda l: l["sku"]):
        account = accounts[line["granted_currency_code"]]
        ledger.append_entry(
            account,
            "FAUCET",
            line["granted_amount_minor"],
            "PURCHASE_GRANT",
            offer["season_id"],
            purchase_id=purchase["id"],
        )
        granted_total += line["granted_amount_minor"]
    purchase["granted_total_minor"] = granted_total
    touch(purchase)

    offer["units_sold"] += 1
    offer["pending_purchase_count"] = max(0, offer["pending_purchase_count"] - 1)
    touch(offer)

    season = db.db.seasons.get(offer["season_id"])
    if season is not None:
        season["pending_revenue_minor"] = max(0, season["pending_revenue_minor"] - quoted)
        season["settled_revenue_minor"] += purchase["price_paid_minor"]
        calc.refresh_lifetime_ratio(season)
        touch(season)

    player["pending_spend_minor"] = max(0, player["pending_spend_minor"] - quoted)
    player["lifetime_spend_minor"] += purchase["price_paid_minor"]
    calc.refresh_realized_pacing(player)
    cascades.reevaluate_spend_state(player, "SETTLEMENT")
    return object_response(serialize(purchase))
