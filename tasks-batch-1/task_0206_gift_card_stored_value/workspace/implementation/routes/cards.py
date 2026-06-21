"""GiftCard issuance and lifecycle/risk transitions (PRD §3.2, §3.3, §3.7, §3.8)."""

from flask import Blueprint, request

from db import db
from core import (
    get_body, stamp_new, touch, paginate, now_iso,
    check_str, check_int, check_enum,
    settled_balance, post_ledger, round_half_up,
)
from errors import err
from middleware import get_identity, require_role
from response import success
from lookups import get_card, state_rule_for
import serialize
from domain import (
    apply_balance_lifecycle,
    active_campaign_for_program,
    whole_months_between,
    waiver_covers,
)

bp = Blueprint("cards", __name__)


def _owner_ok(card, uid, role):
    """A Customer may act only on a card they own (PRD §2.1)."""
    if role == "Customer" and card["owner_customer_id"] != uid:
        raise err("ERR_FORBIDDEN", "Not the owner of this card.")


# ---------------------------------------------------------------- issuance
@bp.post("/v1/cards")
def issue_card():
    _uid, role = get_identity()
    require_role(role, {"StoreAssociate", "ProgramAdmin"})
    body = get_body()
    program_id = check_str(body, "program_id")
    form_factor = check_enum(body, "form_factor", {"DIGITAL", "PHYSICAL"})
    state_code = check_str(body, "state_code")
    owner_customer_id = check_str(body, "owner_customer_id", required=False)

    if program_id not in db.programs:
        raise err("ERR_REFERENCE_NOT_FOUND", "program_id does not exist.")
    if owner_customer_id is not None and owner_customer_id not in db.customers:
        raise err("ERR_REFERENCE_NOT_FOUND", "owner_customer_id does not exist.")

    c = {
        "program_id": program_id,
        "owner_customer_id": owner_customer_id,
        "form_factor": form_factor,
        "state_code": state_code,
        "lifecycle_status": "INACTIVE",
        "risk_status": "CLEAR",
        "replaced_by_card_id": None,
        "activated_at": None,
    }
    stamp_new(c)
    db.cards[c["id"]] = c
    return success(serialize.card(c), status=201)


@bp.get("/v1/cards/<card_id>")
def read_card(card_id):
    uid, role = get_identity()
    require_role(role, {"StoreAssociate", "ProgramAdmin", "FraudAnalyst", "Customer"})
    c = get_card(card_id)
    _owner_ok(c, uid, role)
    return success(serialize.card(c))


@bp.get("/v1/cards")
def list_cards():
    _uid, role = get_identity()
    require_role(role, {"StoreAssociate", "ProgramAdmin", "FraudAnalyst"})
    items = list(db.cards.values())
    for key in ("program_id", "owner_customer_id", "lifecycle_status", "replaced_by_card_id"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    page, pg = paginate(items)
    return success([serialize.card(c) for c in page], pagination=pg)


# ---------------------------------------------------------------- activate
@bp.post("/v1/cards/<card_id>/activate")
def activate_card(card_id):
    _uid, role = get_identity()
    require_role(role, {"StoreAssociate"})
    c = get_card(card_id)
    body = get_body()
    initial_load = check_int(body, "initial_load_cents")
    program = db.programs[c["program_id"]]

    # State (priority 8): must be INACTIVE.
    if c["lifecycle_status"] != "INACTIVE":
        raise err("ERR_INVALID_STATE", "Card is not INACTIVE.")
    # Fiscal floor/cap (priority 13).
    if initial_load < program["reload_min_cents"]:
        raise err("ERR_RELOAD_BELOW_MIN", "Initial load below reload_min_cents.")
    if settled_balance(c["id"]) + initial_load > program["reload_max_balance_cents"]:
        raise err("ERR_BALANCE_CAP_EXCEEDED", "Initial load exceeds balance cap.")

    entry = post_ledger(c, "LOAD", initial_load)
    c["lifecycle_status"] = "ACTIVE"
    c["activated_at"] = entry["created_at"]
    touch(c)
    return success(serialize.card(c))


# ---------------------------------------------------------------- reload
@bp.post("/v1/cards/<card_id>/reload")
def reload_card(card_id):
    uid, role = get_identity()
    require_role(role, {"StoreAssociate", "Customer"})
    c = get_card(card_id)
    _owner_ok(c, uid, role)
    body = get_body()
    amount = check_int(body, "amount_cents")
    program = db.programs[c["program_id"]]

    # State (priority 8): must be ACTIVE or EXHAUSTED.
    if c["lifecycle_status"] not in ("ACTIVE", "EXHAUSTED"):
        raise err("ERR_INVALID_STATE", "Card is not ACTIVE or EXHAUSTED.")
    # Risk gate (priority 9).
    if c["risk_status"] == "FROZEN_RISK":
        raise err("ERR_CARD_RISK_FROZEN", "Card is frozen.")
    # Fiscal floor/cap (priority 13).
    if amount < program["reload_min_cents"]:
        raise err("ERR_RELOAD_BELOW_MIN", "Reload below reload_min_cents.")
    if settled_balance(c["id"]) + amount > program["reload_max_balance_cents"]:
        raise err("ERR_BALANCE_CAP_EXCEEDED", "Reload exceeds balance cap.")

    post_ledger(c, "RELOAD", amount)
    # Promo bonus if an ACTIVE campaign covers the reload instant (PRD §3.3).
    campaign = active_campaign_for_program(c["program_id"], db.clock.now())
    if campaign is not None:
        bonus = round_half_up(amount * campaign["bonus_pct"])
        if bonus > 0:
            post_ledger(c, "BONUS", bonus)
    apply_balance_lifecycle(c)
    touch(c)
    return success(serialize.card(c))


# ---------------------------------------------------------------- assess-dormancy
@bp.post("/v1/cards/<card_id>/assess-dormancy")
def assess_dormancy(card_id):
    _uid, role = get_identity()
    require_role(role, {"ProgramAdmin"})
    c = get_card(card_id)
    now = db.clock.now()
    program = db.programs[c["program_id"]]
    rule = state_rule_for(c["program_id"], c["state_code"])

    # State (priority 8): only ACTIVE/EXHAUSTED cards can be assessed.
    if c["lifecycle_status"] not in ("ACTIVE", "EXHAUSTED"):
        raise err("ERR_INVALID_STATE", "Card is not ACTIVE or EXHAUSTED.")

    threshold = rule["dormancy_threshold_months"] if rule is not None else 12
    last_iso = serialize.card(c)["last_activity_at"]
    months = whole_months_between(last_iso, now) if last_iso else 0
    dormant = months >= threshold
    covered = waiver_covers(c["id"], now)

    # Dormancy due check (priority 12).
    if not dormant or covered:
        raise err("ERR_DORMANCY_NOT_DUE", "Card has not reached the dormancy threshold or a waiver covers now.")

    fee_allowed = rule is not None and rule["dormancy_fee_allowed"]
    expiration_allowed = rule is not None and rule["expiration_allowed"]

    # Validate all gates before any side effect (atomicity, §2.11). The dormancy
    # fee (gated only on dormancy_fee_allowed) is independent of expiration; the
    # card is expired only where expiration_allowed. If the card is dormant but
    # the jurisdiction bars expiration AND no dormancy fee applies, the only
    # remaining action (expire) is rejected with ERR_EXPIRATION_NOT_ALLOWED.
    if not expiration_allowed and not fee_allowed:
        raise err("ERR_EXPIRATION_NOT_ALLOWED", "Expiration not allowed for this jurisdiction.")

    # Side effects (all stores mutated together after validation).
    if fee_allowed:
        fee = min(200, settled_balance(c["id"]))
        if fee > 0:
            post_ledger(c, "DORMANCY_FEE", -fee)
            apply_balance_lifecycle(c)

    if expiration_allowed:
        residual = settled_balance(c["id"])
        if rule["breakage_policy"] == "RECOGNIZE":
            if residual > 0:
                post_ledger(c, "BREAKAGE", -residual)
        elif rule["breakage_policy"] == "ESCHEAT":
            if residual > 0:
                escheated = round_half_up(residual * rule["escheat_rate"])
                if escheated > 0:
                    post_ledger(c, "ESCHEAT", -escheated)
        c["lifecycle_status"] = "EXPIRED"
        touch(c)

    return success(serialize.card(c))


# ---------------------------------------------------------------- risk: flag
@bp.post("/v1/cards/<card_id>/flag")
def flag_card(card_id):
    _uid, role = get_identity()
    require_role(role, {"FraudAnalyst"})
    c = get_card(card_id)
    # CLEAR->FLAGGED, permitted only when lifecycle is ACTIVE/EXHAUSTED.
    if c["lifecycle_status"] not in ("ACTIVE", "EXHAUSTED"):
        raise err("ERR_INVALID_STATE", "Card lifecycle is not ACTIVE/EXHAUSTED.")
    if c["risk_status"] != "CLEAR":
        raise err("ERR_INVALID_STATE", "Card risk_status is not CLEAR.")
    c["risk_status"] = "FLAGGED"
    touch(c)
    return success(serialize.card(c))


# ---------------------------------------------------------------- risk: freeze
@bp.post("/v1/cards/<card_id>/freeze")
def freeze_card(card_id):
    _uid, role = get_identity()
    require_role(role, {"FraudAnalyst"})
    c = get_card(card_id)
    if c["risk_status"] != "FLAGGED":
        raise err("ERR_INVALID_STATE", "Card risk_status is not FLAGGED.")
    c["risk_status"] = "FROZEN_RISK"
    touch(c)
    # Cascade: every ACTIVE hold -> RELEASED (PRD §3.7).
    for h in db.holds.values():
        if h["card_id"] == c["id"] and h["status"] == "ACTIVE":
            h["status"] = "RELEASED"
            touch(h)
    return success(serialize.card(c))


# ---------------------------------------------------------------- risk: clear
@bp.post("/v1/cards/<card_id>/clear-risk")
def clear_risk(card_id):
    _uid, role = get_identity()
    require_role(role, {"FraudAnalyst"})
    c = get_card(card_id)
    if c["risk_status"] not in ("FLAGGED", "FROZEN_RISK"):
        raise err("ERR_INVALID_STATE", "Card risk_status is not FLAGGED/FROZEN_RISK.")
    c["risk_status"] = "CLEAR"
    touch(c)
    return success(serialize.card(c))
