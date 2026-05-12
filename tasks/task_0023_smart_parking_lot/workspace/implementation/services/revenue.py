"""Revenue split, RevenueEntry creation, and stored-value balance helpers."""
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import now, iso
from services.billing import settlement_day_key


BPS_DENOMINATOR = Decimal("10000")


def round_half_up_to_int(d: Decimal) -> int:
    """Round HALF_UP to nearest integer (sign-preserving HALF_UP for negatives)."""
    # Decimal's quantize with ROUND_HALF_UP rounds away from zero on .5 for negatives;
    # PRD precision uses HALF_UP semantics consistently — we use HALF_UP from decimal.
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_revenue_split(gross_cents: int, partner_share_bps: int):
    """Per-entry partner / house split. Per scaffold revenue_split.

    partner_share = round_half_up(gross * bps / 10000), then clamped to [0, +inf).
    house = gross - partner.
    """
    if partner_share_bps == 0 or gross_cents == 0:
        return 0, gross_cents
    raw = Decimal(gross_cents) * Decimal(partner_share_bps) / BPS_DENOMINATOR
    partner = round_half_up_to_int(raw)
    if partner < 0:
        partner = 0
    house = gross_cents - partner
    return partner, house


def create_revenue_entry(*, lot_id: str, zone_id, billing_type: str,
                         source_kind: str, source_id: str,
                         gross_amount_cents: int, notes: str = None) -> dict:
    """Append a RevenueEntry with computed partner/house split."""
    lot = db.parking_lots.get(lot_id)
    bps = int(lot.get("partner_share_bps", 0)) if lot else 0
    partner, house = compute_revenue_split(gross_amount_cents, bps)
    entry = {
        "lot_id": lot_id,
        "zone_id": zone_id,
        "billing_type": billing_type,
        "source_kind": source_kind,
        "source_id": source_id,
        "gross_amount_cents": gross_amount_cents,
        "partner_share_cents": partner,
        "house_share_cents": house,
        "settlement_period": settlement_day_key(lot, now()) if lot else None,
        "notes": notes,
    }
    db.stamp_create(entry, common_fields=False)
    db.revenue_entries[entry["id"]] = entry
    return entry


def _payment_subject_terminal(p: dict) -> bool:
    """Return True iff this payment's subject lifecycle is in a terminal state.

    Used by the finalized_balance variant of stored-value balance.
    Terminal:
      - Session.occupancy_status == EXITED
      - Violation.status in {PAID, TOWED_AWAY}
      - Reservation.status in {MATCHED, EXPIRED_NO_SHOW, CANCELLED}
    For CARD_RECHARGE / REFUND we treat as terminal so they are always counted.
    """
    kind = p.get("kind")
    sid = p.get("subject_id")
    if kind == "CARD_RECHARGE":
        return True
    if kind == "REFUND":
        return True
    if kind == "SESSION_FEE":
        s = db.sessions_tbl.get(sid)
        if s is None:
            return True  # Pretend terminal if missing
        return s.get("occupancy_status") == "EXITED"
    if kind == "FINE_PAYMENT":
        v = db.violations.get(sid)
        if v is None:
            return True
        return v.get("status") in ("PAID", "TOWED_AWAY")
    if kind == "NO_SHOW_PENALTY":
        r = db.reservations.get(sid)
        if r is None:
            return True
        return r.get("status") in ("MATCHED", "EXPIRED_NO_SHOW", "CANCELLED")
    return True


def compute_card_balances(card_id: str):
    """Return (provisional_balance_cents, finalized_balance_cents) for a card.

    Walks Payment rows ordered by processed_at asc, tie-break by Payment.id asc.
    """
    rows = [p for p in db.payments.values() if p.get("card_id") == card_id]
    rows.sort(key=lambda p: (p.get("processed_at", ""), p.get("id", "")))
    prov = 0
    fin = 0
    for p in rows:
        amt = int(p.get("amount_cents", 0))
        kind = p.get("kind")
        delta = 0
        if kind == "CARD_RECHARGE":
            delta = amt
        elif kind == "SESSION_FEE":
            delta = -amt
        elif kind == "FINE_PAYMENT":
            delta = -amt
        elif kind == "NO_SHOW_PENALTY":
            delta = -amt
        elif kind == "REFUND":
            delta = amt
        prov += delta
        if _payment_subject_terminal(p):
            fin += delta
    return prov, fin
