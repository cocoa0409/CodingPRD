"""Card endpoints: issue, read, recharge, bind/unbind, suspend/reactivate, transfer."""
from flask import Blueprint, g

import db
from clock import iso, now, parse_iso
from errors import err
from middleware import require_auth
from response import success
from services.validation import (
    get_body, require_str, require_int, require_enum, optional_int,
    require_field, require_bool, require_reason,
)
from services.projection import card_view
from services.cards import is_card_valid_now, expire_card_if_due
from services.payment import create_payment
from services.revenue import compute_card_balances
from services.audit import write_audit


bp = Blueprint("cards", __name__)


CARD_TYPES = {"MONTHLY", "STORED_VALUE"}


@bp.route("/cards", methods=["POST"])
@require_auth(roles={"Operator"})
def create_card():
    body = get_body()
    card_type = require_enum(body, "card_type", CARD_TYPES)
    holder_ref = require_str(body, "holder_ref", min_len=1, max_len=128)
    require_field(body, "valid_from")
    require_field(body, "valid_until")
    try:
        vfrom = parse_iso(body["valid_from"])
        vuntil = parse_iso(body["valid_until"])
    except ValueError as e:
        raise err("ERR_BAD_REQUEST", str(e))
    if not (vuntil >= vfrom):
        raise err("ERR_BAD_REQUEST", "valid_until must be >= valid_from")
    monthly_fee = optional_int(body, "monthly_fee_cents", default=0, ge=0)
    auto_pay = require_bool(body, "auto_pay_enabled", default=False)

    card = {
        "card_type": card_type,
        "status": "ACTIVE",
        "holder_ref": holder_ref,
        # balance_cents/finalized_balance_cents are recomputed in projections
        "balance_cents": 0,
        "monthly_fee_cents": monthly_fee if card_type == "MONTHLY" else 0,
        "valid_from": body["valid_from"],
        "valid_until": body["valid_until"],
        "bound_vehicle_ids": [],
        "auto_pay_enabled": auto_pay,
    }
    db.stamp_create(card)
    db.cards[card["id"]] = card
    return success(card_view(card), status=201)


@bp.route("/cards/<card_id>", methods=["GET"])
@require_auth(roles={"Operator", "Driver", "ParkingPartner", "Auditor"})
def get_card(card_id):
    card = db.cards.get(card_id)
    if card is None:
        raise err("ERR_NOT_FOUND", "Card not found")
    return success(card_view(card))


def _settle_unpaid_sessions_for_card(card: dict):
    """When auto_pay_enabled and a recharge happens, sweep unpaid EXITED sessions
    pinned to this card or whose vehicle is bound to this card and pay them.

    Per PRD §3.3, recharge cascades a settlement sweep.
    """
    if not card.get("auto_pay_enabled"):
        return
    if card.get("status") != "ACTIVE":
        return
    bound_vehicle_ids = set(card.get("bound_vehicle_ids", []))
    # Iterate sessions in stable order
    sessions_sorted = sorted(db.sessions_tbl.values(), key=lambda s: s.get("_seq", 0))
    for s in sessions_sorted:
        if s.get("occupancy_status") != "EXITED":
            continue
        if s.get("payment_status") != "UNPAID":
            continue
        # Either explicitly pinned to this card, or vehicle bound to this card
        pinned = s.get("card_id") == card["id"]
        bound = s.get("vehicle_id") in bound_vehicle_ids
        if not (pinned or bound):
            continue
        fee = int(s.get("final_fee_cents") or 0)
        if fee <= 0:
            # Already at zero — mark paid trivially? PRD says zero-fee sessions
            # for exempt/monthly-covered remain UNPAID until explicit pay.
            # Skip auto-paying zero-fee sessions to avoid creating $0 payments.
            continue
        # Recompute provisional balance and skip if insufficient
        prov, _ = compute_card_balances(card["id"])
        if prov < fee:
            continue
        # Pin card_id to session if not yet
        if not s.get("card_id"):
            s["card_id"] = card["id"]
        create_payment(
            kind="SESSION_FEE",
            subject_id=s["id"],
            amount_cents=fee,
            card_id=card["id"],
        )
        s["payment_status"] = "PAID"
        db.stamp_update(s)
        # Revenue entry
        from services.revenue import create_revenue_entry
        # zone resolved via space
        space = db.spaces.get(s.get("space_id")) if s.get("space_id") else None
        zone_id = space.get("zone_id") if space else None
        bk = s.get("billing_kind")
        billing_type = "MONTHLY" if bk == "MONTHLY_COVERED" else "HOURLY"
        create_revenue_entry(
            lot_id=s["lot_id"],
            zone_id=zone_id,
            billing_type=billing_type,
            source_kind="SESSION",
            source_id=s["id"],
            gross_amount_cents=fee,
        )


@bp.route("/cards/<card_id>/recharge", methods=["POST"])
@require_auth(roles={"Operator", "Driver"})
def recharge_card(card_id):
    card = db.cards.get(card_id)
    if card is None:
        raise err("ERR_NOT_FOUND", "Card not found")
    body = get_body()
    # Optimistic concurrency: PRD §2.5 — recharge mutations on a Card may
    # supply the card's version via body or If-Match; mismatch yields
    # ERR_VERSION_CONFLICT before any business validation.
    from services.validation import check_version
    check_version(body, card.get("version", 1))
    if card.get("status") == "EXPIRED" or not is_card_valid_now(card):
        raise err("ERR_CARD_EXPIRED", "Card is expired or outside validity window")
    amount = require_int(body, "amount_cents", ge=1)
    external_ref = body.get("external_ref")

    create_payment(
        kind="CARD_RECHARGE",
        subject_id=card_id,
        amount_cents=amount,
        card_id=card_id,
        external_ref=external_ref,
    )
    # Bump card version & updated_at — recharge mutates effective balance
    db.stamp_update(card)
    # Cascade: auto-pay sweep
    _settle_unpaid_sessions_for_card(card)
    return success(card_view(card))


@bp.route("/cards/<card_id>/bind", methods=["POST"])
@require_auth(roles={"Operator"})
def bind_card(card_id):
    card = db.cards.get(card_id)
    if card is None:
        raise err("ERR_NOT_FOUND", "Card not found")
    body = get_body()
    vehicle_id = require_str(body, "vehicle_id")
    veh = db.vehicles.get(vehicle_id)
    if veh is None:
        raise err("ERR_NOT_FOUND", "Vehicle not found")

    # priority 6: state — can't bind on EXPIRED
    if card.get("status") == "EXPIRED":
        raise err("ERR_CARD_EXPIRED", "Card has expired")
    # priority 7: vehicle exemption — N/A here
    # priority 8: binding_eligible
    if not veh.get("binding_eligible", True):
        raise err("ERR_VEHICLE_HAS_OPEN_VIOLATIONS",
                  "Vehicle has open violations and cannot be bound")
    # priority 11: card binding cardinality
    bound = list(card.get("bound_vehicle_ids", []))
    if vehicle_id in bound:
        # Idempotent — already bound. Return the card unchanged to avoid duplicates.
        return success(card_view(card))
    if card.get("card_type") == "STORED_VALUE":
        if len(bound) >= 1:
            raise err("ERR_CARD_BINDING_LIMIT", "STORED_VALUE card admits at most 1 vehicle")
    elif card.get("card_type") == "MONTHLY":
        if len(bound) >= 4:
            raise err("ERR_CARD_BINDING_LIMIT", "MONTHLY card admits at most 4 vehicles")
        # Cross-card invariant: a Vehicle may be bound to at most one MONTHLY card
        for c in db.cards.values():
            if c["id"] == card_id:
                continue
            if c.get("card_type") != "MONTHLY":
                continue
            if vehicle_id in c.get("bound_vehicle_ids", []):
                raise err("ERR_VEHICLE_ALREADY_BOUND",
                          "Vehicle already bound to a MONTHLY card")
    # priority 12: card validity
    if not is_card_valid_now(card):
        raise err("ERR_CARD_EXPIRED", "Card is outside validity window")

    bound.append(vehicle_id)
    card["bound_vehicle_ids"] = bound
    db.stamp_update(card)
    return success(card_view(card))


@bp.route("/cards/<card_id>/unbind", methods=["POST"])
@require_auth(roles={"Operator"})
def unbind_card(card_id):
    card = db.cards.get(card_id)
    if card is None:
        raise err("ERR_NOT_FOUND", "Card not found")
    body = get_body()
    vehicle_id = require_str(body, "vehicle_id")
    if not db.vehicles.get(vehicle_id):
        raise err("ERR_NOT_FOUND", "Vehicle not found")
    bound = list(card.get("bound_vehicle_ids", []))
    if vehicle_id not in bound:
        raise err("ERR_VEHICLE_NOT_BOUND", "Vehicle not bound to this card")
    bound.remove(vehicle_id)
    card["bound_vehicle_ids"] = bound
    db.stamp_update(card)
    return success(card_view(card))


@bp.route("/cards/<card_id>/suspend", methods=["POST"])
@require_auth(roles={"Operator"})
def suspend_card(card_id):
    card = db.cards.get(card_id)
    if card is None:
        raise err("ERR_NOT_FOUND", "Card not found")
    if card.get("status") != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  f"Cannot suspend a card in status {card.get('status')}")
    card["status"] = "SUSPENDED"
    db.stamp_update(card)
    return success(card_view(card))


@bp.route("/cards/<card_id>/reactivate", methods=["POST"])
@require_auth(roles={"Operator"})
def reactivate_card(card_id):
    card = db.cards.get(card_id)
    if card is None:
        raise err("ERR_NOT_FOUND", "Card not found")
    if card.get("status") != "SUSPENDED":
        raise err("ERR_INVALID_STATE",
                  f"Cannot reactivate a card in status {card.get('status')}")
    # PRD: allowed only while now() < valid_until
    try:
        vuntil = parse_iso(card["valid_until"])
    except Exception:
        raise err("ERR_CARD_EXPIRED", "Card validity window invalid")
    if now() > vuntil:
        raise err("ERR_CARD_EXPIRED", "Card validity window has passed")
    card["status"] = "ACTIVE"
    db.stamp_update(card)
    return success(card_view(card))


@bp.route("/cards/<card_id>/transfer", methods=["POST"])
@require_auth(roles={"Operator"})
def transfer_card(card_id):
    src = db.cards.get(card_id)
    if src is None:
        raise err("ERR_NOT_FOUND", "Source card not found")
    body = get_body()
    target_id = require_str(body, "target_card_id")
    reason = require_reason(body)
    tgt = db.cards.get(target_id)
    if tgt is None:
        raise err("ERR_NOT_FOUND", "Target card not found")
    if src["id"] == tgt["id"]:
        raise err("ERR_INVALID_CARD_TRANSFER", "Source and target cards must differ")
    # both ACTIVE, same holder, same type
    if src.get("status") != "ACTIVE" or tgt.get("status") != "ACTIVE":
        raise err("ERR_INVALID_CARD_TRANSFER", "Both cards must be ACTIVE")
    if src.get("holder_ref") != tgt.get("holder_ref"):
        raise err("ERR_INVALID_CARD_TRANSFER", "holder_ref mismatch")
    if src.get("card_type") != tgt.get("card_type"):
        raise err("ERR_INVALID_CARD_TRANSFER", "card_type mismatch")

    # Capacity check on target's bindings (existing + incoming, dedup)
    incoming = [v for v in src.get("bound_vehicle_ids", [])
                if v not in tgt.get("bound_vehicle_ids", [])]
    new_bound = list(tgt.get("bound_vehicle_ids", [])) + incoming
    if src.get("card_type") == "STORED_VALUE":
        if len(new_bound) > 1:
            raise err("ERR_CARD_BINDING_LIMIT",
                      "STORED_VALUE target cannot accept more than 1 vehicle")
    elif src.get("card_type") == "MONTHLY":
        if len(new_bound) > 4:
            raise err("ERR_CARD_BINDING_LIMIT",
                      "MONTHLY target cannot accept more than 4 vehicles")

    # Snapshot pre/post for audit
    before = {
        "src_balance_cents": src.get("balance_cents"),
        "tgt_balance_cents": tgt.get("balance_cents"),
        "src_bound_vehicle_ids": list(src.get("bound_vehicle_ids", [])),
        "tgt_bound_vehicle_ids": list(tgt.get("bound_vehicle_ids", [])),
    }

    # Move balance: emit two REFUND-ish payments? No — PRD says target +=, source := 0.
    # Implement as two CARD_RECHARGE/CARD_DEBIT? PRD's payment kinds don't include
    # explicit transfer — so we mutate stored balance fields directly.
    # The provisional balance is computed from payments, so we instead append
    # mirrored Payment rows to keep the chronological ledger consistent.
    src_prov, _ = compute_card_balances(src["id"])
    if src_prov > 0:
        # Debit source: emit a SESSION_FEE-like outflow? PRD only catalogs five kinds.
        # For correctness vs. balance-replay invariant, append:
        #   - one synthetic CARD_RECHARGE on target with amount = src_prov
        #   - one synthetic outflow on source — represented as REFUND with amount = src_prov
        #     and subject_id = src.id (a refund is an inflow per balance algo, but
        #     here we want outflow). To safely keep the chronological replay simple,
        #     we instead use direct field manipulation and skip ledger mutation.
        # PRD does not require new Payment rows for transfers, so we just mutate
        # the stored numerical balance fields the projection ignores. Since the
        # projection recomputes from payments, we need ledger entries.
        # Use a simple two-row trick: create a CARD_RECHARGE on target and a
        # SESSION_FEE-like debit on source (but SESSION_FEE requires session subject).
        # The cleanest path: a pair of REFUND rows where source carries a NEGATIVE amount
        # is forbidden (amount_cents must be positive).
        # Final approach: append a REFUND with amount = src_prov on source (this
        # ADDS to source per algo — wrong direction). So we instead emit:
        #   - on target: a CARD_RECHARGE that increases target's provisional balance
        #   - on source: a SESSION_FEE-type with subject = a synthetic id?
        # Given the algorithm rules, the cleanest practical approach is to
        # mutate via two synthetic CARD_RECHARGE rows: target gets +src_prov, and
        # source gets a balancing REFUND that we negate? Algorithm forbids this.
        #
        # We choose: create a CARD_RECHARGE on target (+src_prov) and a NEGATIVE
        # offset by appending an additional CARD_RECHARGE on source with amount
        # = -src_prov. But amounts are positive integers.
        #
        # Pragmatic resolution: emit a CARD_RECHARGE on target for +src_prov, and
        # append a REFUND on source whose subject is a placeholder. REFUND adds to
        # balance per algo — wrong sign. So we use the LEDGER inversion trick:
        # emit a SESSION_FEE row whose subject_id = src.id with amount = src_prov.
        # SESSION_FEE subtracts amount from card balance. This drains source.
        from services.payment import create_payment as _cp
        _cp(kind="SESSION_FEE", subject_id=src["id"], amount_cents=src_prov, card_id=src["id"])
        _cp(kind="CARD_RECHARGE", subject_id=tgt["id"], amount_cents=src_prov, card_id=tgt["id"])

    # Move bindings
    tgt["bound_vehicle_ids"] = new_bound
    src["bound_vehicle_ids"] = []

    # Bump versions & timestamps
    db.stamp_update(src)
    db.stamp_update(tgt)

    after = {
        "src_balance_cents": compute_card_balances(src["id"])[0],
        "tgt_balance_cents": compute_card_balances(tgt["id"])[0],
        "src_bound_vehicle_ids": list(src.get("bound_vehicle_ids", [])),
        "tgt_bound_vehicle_ids": list(tgt.get("bound_vehicle_ids", [])),
    }

    write_audit(
        action="CARD_TRANSFER",
        subject_kind="Card",
        subject_id=src["id"],
        before=before,
        after=after,
        reason=reason,
    )
    return success(card_view(src))
