"""DebitCard, CardControl, Transaction, and SpendAlert endpoints (PRD §3.5, §3.6)."""
from flask import Blueprint, request

import db
import domain
import serialize
import validate
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import object_response, list_response

bp = Blueprint("cards", __name__)


# ----------------------------- DebitCard -----------------------------------
@bp.route("/child-accounts/<cid>/debit-cards", methods=["GET"])
def list_cards(cid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)
    items = [c for c in db.debit_cards.values() if c["child_account_id"] == cid]
    for c in items:
        domain.recompute_card(c)
    return list_response([serialize.debit_card(c) for c in items], request.args)


@bp.route("/debit-cards/<cardid>", methods=["GET"])
def read_card(cardid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    card = domain.get_card(cardid)
    child = domain.get_child(card["child_account_id"])
    domain.check_child_owner(identity, child)
    domain.recompute_card(card)
    return object_response(serialize.debit_card(card))


def _check_occ(card, body):
    """OCC (priority 7): expected_debit_card_version must equal current version.
    Checked before the generic state transition check."""
    expected = body.get("expected_debit_card_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_debit_card_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_debit_card_version must be an integer")
    if expected != card["version"]:
        raise err("ERR_STALE_CARD_VERSION", "Card version is stale")


@bp.route("/debit-cards/<cardid>/lock", methods=["POST"])
def lock_card(cardid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child"})
    card = domain.get_card(cardid)
    child = domain.get_child(card["child_account_id"])
    domain.check_child_owner(identity, child)
    body = get_json_body()
    _check_occ(card, body)
    if card["lock_state"] != "UNLOCKED":
        raise err("ERR_INVALID_STATE", "Card is not UNLOCKED")
    card["lock_state"] = "LOCKED"
    db.touch(card)  # bumps version by 1
    domain.recompute_card(card)
    return object_response(serialize.debit_card(card))


@bp.route("/debit-cards/<cardid>/unlock", methods=["POST"])
def unlock_card(cardid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    card = domain.get_card(cardid)
    child = domain.get_child(card["child_account_id"])
    domain.check_child_owner(identity, child)
    body = get_json_body()
    _check_occ(card, body)
    if card["lock_state"] != "LOCKED":
        raise err("ERR_INVALID_STATE", "Card is not LOCKED")
    card["lock_state"] = "UNLOCKED"
    db.touch(card)
    domain.recompute_card(card)
    return object_response(serialize.debit_card(card))


# ----------------------------- CardControl ---------------------------------
@bp.route("/debit-cards/<cardid>/controls", methods=["POST"])
def create_control(cardid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    card = domain.get_card(cardid)
    child = domain.get_child(card["child_account_id"])
    domain.check_child_owner(identity, child)
    body = get_json_body()

    control_kind = validate.require_enum(body, "control_kind", {"STORE", "CATEGORY"})
    match_value = validate.require_str(body, "match_value")
    rule = validate.require_enum(body, "rule", {"BLOCK", "LIMIT"})
    per_period = validate.optional_int(body, "per_period_cap_cents", 0)
    if rule == "LIMIT":
        # per_period_cap_cents is required and must be > 0 to be meaningful.
        if "per_period_cap_cents" not in body or body["per_period_cap_cents"] is None:
            raise err("ERR_INVALID_REQUEST", "per_period_cap_cents required when rule=LIMIT")
        validate.bound_min(per_period, 0, "per_period_cap_cents")
    else:
        per_period = 0

    # OCC before state (priority 7 before 8).
    _check_occ(card, body)

    rec = db.base_fields()
    rec.update({
        "debit_card_id": cardid,
        "control_kind": control_kind,
        "match_value": match_value,
        "rule": rule,
        "per_period_cap_cents": per_period,
        "is_active": True,
    })
    db.card_controls[rec["id"]] = rec
    db.touch(card)  # control-create bumps card version
    return object_response(serialize.card_control(rec), status=201)


@bp.route("/debit-cards/<cardid>/controls", methods=["GET"])
def list_controls(cardid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    card = domain.get_card(cardid)
    child = domain.get_child(card["child_account_id"])
    domain.check_child_owner(identity, child)
    items = [c for c in db.card_controls.values() if c["debit_card_id"] == cardid]
    is_active = request.args.get("is_active")
    if is_active is not None:
        want = is_active.lower() in ("true", "1", "yes")
        items = [c for c in items if c["is_active"] == want]
    return list_response([serialize.card_control(c) for c in items], request.args)


@bp.route("/card-controls/<ctlid>", methods=["DELETE"])
def delete_control(ctlid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    ctl = domain.get_control(ctlid)
    card = domain.get_card(ctl["debit_card_id"])
    child = domain.get_child(card["child_account_id"])
    domain.check_child_owner(identity, child)
    ctl["is_active"] = False
    db.touch(ctl)
    return object_response(serialize.card_control(ctl))


# ----------------------------- Transaction ---------------------------------
def _matching_active_controls(cardid, merchant_id, category):
    """Return active controls that match this txn's dimension."""
    out = []
    for c in db.card_controls.values():
        if c["debit_card_id"] != cardid or not c["is_active"]:
            continue
        if c["control_kind"] == "STORE" and c["match_value"] == merchant_id:
            out.append(c)
        elif c["control_kind"] == "CATEGORY" and c["match_value"] == category:
            out.append(c)
    return out


def _matched_cumulative(cardid, control, merchant_id_field, category_field):
    """Sum amount_cents over PENDING+SETTLED txns on this card matching the
    control's dimension."""
    total = 0
    for t in db.transactions.values():
        if t["debit_card_id"] != cardid:
            continue
        if t["status"] not in ("PENDING", "SETTLED"):
            continue
        if control["control_kind"] == "STORE":
            if t["merchant_id"] == control["match_value"]:
                total += t["amount_cents"]
        else:  # CATEGORY
            if t["category"] == control["match_value"]:
                total += t["amount_cents"]
    return total


@bp.route("/debit-cards/<cardid>/authorizations", methods=["POST"])
def authorize(cardid):
    identity = authenticate()
    require_role(identity, {"Child", "PlatformAdmin"})
    card = domain.get_card(cardid)
    child = domain.get_child(card["child_account_id"])
    domain.check_child_owner(identity, child)
    body = get_json_body()

    merchant_id = validate.require_str(body, "merchant_id")
    category = validate.require_str(body, "category")
    amount = validate.require_int(body, "amount_cents")
    record_decline = validate.optional_bool(body, "record_decline", False)
    validate.bound_positive(amount, "amount_cents")

    domain.recompute_card(card)

    def fail(error_id, message):
        if record_decline:
            tx = db.base_fields()
            tx.update({
                "debit_card_id": cardid,
                "child_account_id": card["child_account_id"],
                "merchant_id": merchant_id,
                "category": category,
                "amount_cents": amount,
                "settled_amount_cents": 0,
                "status": "DECLINED",
            })
            db.transactions[tx["id"]] = tx
        raise err(error_id, message)

    # Gauntlet in PRD §3.5 order: lock, family suspended, block control,
    # limit control, available funds.
    if card["lock_state"] == "LOCKED":
        fail("ERR_CARD_LOCKED", "Card is locked")

    fam = db.families[child["family_id"]]
    if fam["status"] == "SUSPENDED":
        fail("ERR_FAMILY_SUSPENDED", "Family is suspended")

    matching = _matching_active_controls(cardid, merchant_id, category)
    for c in matching:
        if c["rule"] == "BLOCK":
            fail("ERR_CONTROL_BLOCKED", "A block control matches this authorization")
    for c in matching:
        if c["rule"] == "LIMIT":
            matched = _matched_cumulative(cardid, c, merchant_id, category)
            if matched + amount > c["per_period_cap_cents"]:
                fail("ERR_CONTROL_LIMIT_EXCEEDED", "Limit control cap exceeded")

    if card["available_cents"] < amount:
        fail("ERR_INSUFFICIENT_CARD_FUNDS", "Card available funds insufficient")

    # Passed: create PENDING txn, place hold, emit alerts.
    tx = db.base_fields()
    tx.update({
        "debit_card_id": cardid,
        "child_account_id": card["child_account_id"],
        "merchant_id": merchant_id,
        "category": category,
        "amount_cents": amount,
        "settled_amount_cents": 0,
        "status": "PENDING",
    })
    db.transactions[tx["id"]] = tx

    domain.recompute_card(card)  # held_cents += amount, available recomputed
    db.touch(card)  # authorization bumps version by 1

    # SpendAlerts (PRD §3.6).
    large_threshold = fam.get("large_spend_threshold_cents")
    low_threshold = fam.get("low_balance_threshold_cents")
    if large_threshold is not None and amount >= large_threshold:
        _emit_alert(tx, card["child_account_id"], "LARGE_SPEND", amount)
    if low_threshold is not None and card["available_cents"] < low_threshold:
        _emit_alert(tx, card["child_account_id"], "LOW_BALANCE", amount)

    return object_response(serialize.transaction(tx), status=201)


def _emit_alert(tx, child_id, kind, amount):
    rec = db.base_fields(common=False)
    rec.update({
        "transaction_id": tx["id"],
        "child_account_id": child_id,
        "alert_kind": kind,
        "amount_cents": amount,
    })
    db.spend_alerts[rec["id"]] = rec


@bp.route("/debit-cards/<cardid>/transactions", methods=["GET"])
def list_transactions(cardid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    card = domain.get_card(cardid)
    child = domain.get_child(card["child_account_id"])
    domain.check_child_owner(identity, child)
    items = [t for t in db.transactions.values() if t["debit_card_id"] == cardid]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return list_response([serialize.transaction(t) for t in items], request.args)


@bp.route("/transactions/<txid>", methods=["GET"])
def read_transaction(txid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    tx = domain.get_transaction(txid)
    card = domain.get_card(tx["debit_card_id"])
    child = domain.get_child(card["child_account_id"])
    domain.check_child_owner(identity, child)
    return object_response(serialize.transaction(tx))


@bp.route("/transactions/<txid>/settle", methods=["POST"])
def settle_transaction(txid):
    identity = authenticate()
    require_role(identity, {"PlatformAdmin"})
    tx = domain.get_transaction(txid)
    card = domain.get_card(tx["debit_card_id"])
    body = get_json_body()
    settled = validate.require_int(body, "settled_amount_cents")

    if tx["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Transaction is not PENDING")
    if not (0 < settled <= tx["amount_cents"]):
        raise err("ERR_INVALID_SETTLE_AMOUNT", "settled_amount_cents out of range")

    # CASCADE: release hold, debit SPEND jar by settled, recompute card.
    tx["settled_amount_cents"] = settled
    tx["status"] = "SETTLED"
    db.touch(tx)

    spend = domain.jar_of_type(card["child_account_id"], "SPEND")
    domain.debit_jar(spend, settled)  # bumps jar + card recompute
    domain.recompute_card(card)
    db.touch(card)  # settle bumps card version
    return object_response(serialize.transaction(tx))


@bp.route("/transactions/<txid>/reverse", methods=["POST"])
def reverse_transaction(txid):
    identity = authenticate()
    require_role(identity, {"PlatformAdmin"})
    tx = domain.get_transaction(txid)
    card = domain.get_card(tx["debit_card_id"])

    if tx["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Transaction is not PENDING")

    # Release hold, no jar debit; SPEND jar unchanged.
    tx["status"] = "REVERSED"
    db.touch(tx)
    domain.recompute_card(card)  # hold drops as txn no longer PENDING
    db.touch(card)  # reverse bumps card version
    return object_response(serialize.transaction(tx))


@bp.route("/transactions/<txid>/alerts", methods=["GET"])
def list_alerts(txid):
    identity = authenticate()
    require_role(identity, {"Parent", "PlatformAdmin"})
    tx = domain.get_transaction(txid)
    card = domain.get_card(tx["debit_card_id"])
    child = domain.get_child(card["child_account_id"])
    domain.check_family_owner_for_child(identity, child)
    items = [a for a in db.spend_alerts.values() if a["transaction_id"] == txid]
    return list_response([serialize.spend_alert(a) for a in items], request.args)
