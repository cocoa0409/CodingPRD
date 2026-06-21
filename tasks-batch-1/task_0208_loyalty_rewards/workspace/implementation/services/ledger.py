"""Ledger backbone: tier evaluation, derived balances, lot minting, FIFO burns,
and member recomputation (SCAFFOLD §1.3 calculations; PRD §2.5, §3.3-§3.9).

All point quantities are integers. The logical clock (db.current_clock) drives
expiry-relative reasoning.
"""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from db import db
from errors import err, ERR_LOT_EXPIRED
from .helpers import parse_iso, fmt_iso, add_months

GOLD_RANK = 2  # SCAFFOLD §1.3 redemption_cost constant


# ---------------------------------------------------------------------------
# Floor helper — full real-valued product then floor once (PRD §2.7 earn side)
# ---------------------------------------------------------------------------
def floor_product(*factors):
    prod = Decimal(1)
    for f in factors:
        prod *= Decimal(str(f))
    return int(prod.to_integral_value(rounding=ROUND_DOWN))


# ---------------------------------------------------------------------------
# Redemption cost (SCAFFOLD §1.3 redemption_cost / redemption_line_rounding;
# PRD §2.7, §3.7). round_half_up PER LINE, then integer sum.
# ---------------------------------------------------------------------------
def line_cost(quantity, point_cost, applicable_discount_pct):
    raw = Decimal(str(quantity)) * Decimal(str(point_cost)) * (
        Decimal(1) - Decimal(str(applicable_discount_pct)))
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def applicable_discount(program_id, tier_code, reward):
    """Reward.tier_discount_pct when member tier rank >= GOLD_RANK, else 0.0."""
    if tier_rank(program_id, tier_code) >= GOLD_RANK:
        return reward["tier_discount_pct"]
    return 0.0


# ---------------------------------------------------------------------------
# Tier evaluation (SCAFFOLD §1.3 tier_evaluation; PRD §3.4)
# ---------------------------------------------------------------------------
def program_tiers(program_id):
    return [t for t in db.tiers.values() if t["program_id"] == program_id]


def qualifying_points_window(member):
    """Sum qualifying_points of the member's EARN_PURCHASE ledger rows whose
    created_at is at or after (clock.now - program.qualifying_window_months)."""
    program = db.programs.get(member["program_id"])
    if program is None:
        return 0
    window_start = add_months(db.current_clock, -program["qualifying_window_months"])
    total = 0
    for tx in db.transactions.values():
        if tx["member_id"] != member["id"]:
            continue
        if tx["type"] != "EARN_PURCHASE":
            continue
        if parse_iso(tx["created_at"]) >= window_start:
            total += tx["qualifying_points"]
    return total


def resolve_tier_code(member):
    """The code of the highest-rank tier whose qualify_threshold <= window total
    (inclusive). Defaults to STANDARD when no tier qualifies."""
    qpw = qualifying_points_window(member)
    tiers = program_tiers(member["program_id"])
    best = None
    for t in tiers:
        if t["qualify_threshold"] <= qpw:
            if best is None or t["rank"] > best["rank"]:
                best = t
    if best is not None:
        return best["code"]
    return "STANDARD"


def tier_for_code(program_id, code):
    for t in program_tiers(program_id):
        if t["code"] == code:
            return t
    return None


def tier_rank(program_id, code):
    t = tier_for_code(program_id, code)
    return t["rank"] if t is not None else 0


# ---------------------------------------------------------------------------
# Derived balances (SCAFFOLD §1.3 member_balance; PRD §2.5)
# ---------------------------------------------------------------------------
def member_lots(member_id):
    return [l for l in db.lots.values() if l["member_id"] == member_id]


def available_points(member_id):
    return sum(l["remaining_points"] for l in member_lots(member_id)
               if l["status"] == "ACTIVE")


def projected_points(member_id):
    now = db.current_clock
    total = 0
    for l in member_lots(member_id):
        if l["status"] != "ACTIVE":
            continue
        if parse_iso(l["expires_at"]) <= now:
            continue  # past-expiry unswept lots excluded from projected
        total += l["remaining_points"]
    return total


def lifetime_earned_points(member_id):
    earn_types = {"EARN_PURCHASE", "EARN_BONUS", "BIRTHDAY", "REFERRAL",
                  "TRANSFER_IN_REVERSAL"}
    total = 0
    for tx in db.transactions.values():
        if tx["member_id"] != member_id:
            continue
        if tx["type"] in earn_types:
            total += tx["points_delta"]
    return total


def recompute_member(member):
    """Re-derive all computed fields + current_tier_code (PRD §2.5).
    Does NOT bump the member's version (callers decide when version advances)."""
    member["available_points"] = available_points(member["id"])
    member["projected_points"] = projected_points(member["id"])
    member["qualifying_points_window"] = qualifying_points_window(member)
    member["lifetime_earned_points"] = lifetime_earned_points(member["id"])
    member["current_tier_code"] = resolve_tier_code(member)
    return member


# ---------------------------------------------------------------------------
# Lot minting + ledger row append
# ---------------------------------------------------------------------------
def mint_lot(member, source_type, points, source_id=None,
             tx_type=None, qualifying_points=0,
             ref_redemption_id=None, ref_transfer_id=None):
    """Create a new ACTIVE PointsLot and append the matching PointsTransaction.

    expires_at = lot.created_at + program.lot_expiration_months.
    Returns (lot, transaction).
    """
    program = db.programs[member["program_id"]]
    lot = {
        "member_id": member["id"],
        "source_type": source_type,
        "source_id": source_id,
        "original_points": points,
        "remaining_points": points,
        "status": "ACTIVE",
    }
    db.stamp_create(lot, common_fields=True)
    expires = add_months(parse_iso(lot["created_at"]), program["lot_expiration_months"])
    lot["expires_at"] = fmt_iso(expires)
    db.lots[lot["id"]] = lot

    tx = append_tx(
        member, lot_id=lot["id"],
        tx_type=tx_type or source_type,
        points_delta=points,
        qualifying_points=qualifying_points,
        ref_redemption_id=ref_redemption_id,
        ref_transfer_id=ref_transfer_id,
    )
    return lot, tx


def append_tx(member, lot_id, tx_type, points_delta, qualifying_points=0,
              ref_redemption_id=None, ref_transfer_id=None):
    tx = {
        "member_id": member["id"],
        "lot_id": lot_id,
        "type": tx_type,
        "points_delta": points_delta,
        "qualifying_points": qualifying_points,
        "ref_redemption_id": ref_redemption_id,
        "ref_transfer_id": ref_transfer_id,
    }
    db.stamp_create(tx, common_fields=False)
    db.transactions[tx["id"]] = tx
    return tx


# ---------------------------------------------------------------------------
# FIFO burn (PRD §3.7 confirm, §3.8 transfer)
# ---------------------------------------------------------------------------
def burnable_lots(member_id):
    """ACTIVE lots with remaining_points > 0 whose expires_at is strictly after
    the clock (past-expiry unswept lots are not burnable — PRD §3.7), ordered
    FIFO: created_at ASC, tie-break lot id ASC for identical timestamps."""
    now = db.current_clock
    lots = [l for l in member_lots(member_id)
            if l["status"] == "ACTIVE" and l["remaining_points"] > 0]
    lots = [l for l in lots if parse_iso(l["expires_at"]) > now]
    return sorted(lots, key=lambda l: (l["created_at"], l["id"]))


def fifo_burn(member, amount, tx_type, ref_redemption_id=None,
              ref_transfer_id=None):
    """Burn `amount` points FIFO. Appends one negative PointsTransaction per
    consumed lot; moves a lot to EXHAUSTED when it reaches 0. Caller must have
    already verified available_points >= amount via the right balance variant.

    Raises ERR_LOT_EXPIRED only if the burnable (non-expired) supply is
    insufficient even though some past-expiry lots hold the difference.
    """
    remaining = amount
    candidates = burnable_lots(member["id"])
    for lot in candidates:
        if remaining <= 0:
            break
        take = min(lot["remaining_points"], remaining)
        lot["remaining_points"] -= take
        if lot["remaining_points"] == 0:
            lot["status"] = "EXHAUSTED"
        db.touch(lot)
        append_tx(member, lot_id=lot["id"], tx_type=tx_type,
                  points_delta=-take, qualifying_points=0,
                  ref_redemption_id=ref_redemption_id,
                  ref_transfer_id=ref_transfer_id)
        remaining -= take
    if remaining > 0:
        # Burnable (non-expired) lots could not cover the amount even though the
        # caller's gate passed against available_points (which counts expired
        # unswept lots). This is the internal past-expiry guard.
        raise err(ERR_LOT_EXPIRED,
                  "Burn would have to draw from a past-expiry unswept lot")
