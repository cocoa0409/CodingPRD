"""Prize calculation per §3.6."""
from decimal import Decimal, ROUND_HALF_UP, getcontext

import db
from clock import iso, parse_iso
from datetime import timedelta


getcontext().prec = 50


# Tier percent fractions (numerator, denominator)
TIER_PCT = {
    1: Decimal("50"),
    2: Decimal("25"),
    3: Decimal("10"),
    4: Decimal("10"),
    5: Decimal("1.25"),
    6: Decimal("1.25"),
    7: Decimal("1.25"),
    8: Decimal("1.25"),
}


def _round_half_up(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def gross_for_rank(prize_pool_cents: int, rank: int) -> int:
    if rank not in TIER_PCT:
        return 0
    pct = TIER_PCT[rank]
    cents = (Decimal(prize_pool_cents) * pct) / Decimal(100)
    return _round_half_up(cents)


def tax_for_gross(gross_cents: int, tax_pct: Decimal) -> int:
    raw = (Decimal(gross_cents) * tax_pct) / Decimal(100)
    return _round_half_up(raw)


def participant_has_active_sanction(event_id: str, pid: str) -> bool:
    """True if a SanctionRecord (status ISSUED or FINAL) exists for this participant in this event."""
    sample_ids = {s["id"] for s in db.doping_samples.values()
                  if s["event_id"] == event_id and s["participant_id"] == pid}
    for sr in db.sanction_records.values():
        if sr["sample_id"] in sample_ids and sr["status"] in ("ISSUED", "FINAL"):
            return True
    return False


def compute_initial_prize_payments(event: dict) -> None:
    """Initial calculation at COMPLETED. Creates PrizePayment rows."""
    event_id = event["id"]
    prize_pool = event.get("prize_pool_cents", 0) or 0
    tax_pct = Decimal(str(event.get("tax_withholding_pct", 0)))
    starts_at = parse_iso(event["starts_at"])
    pay_at = iso(starts_at + timedelta(seconds=604800))

    # Compute per-rank gross with residual reallocation to rank 1
    gross_by_rank = {}
    for rank in range(1, 9):
        gross_by_rank[rank] = gross_for_rank(prize_pool, rank)
    total_allocated = sum(gross_by_rank.values())
    # Compute total expected (sum of pcts) — but tier 5..8 sum 5%, 3+4 sum 20, 2 is 25, 1 is 50 = 100%
    # Residual = prize_pool - total_allocated. Add to rank 1.
    residual = prize_pool - total_allocated
    # Only add residual if it fits — per spec: "any residual cent left over from rounding"
    # The residual could be positive or zero (rounding can leave cents).
    if residual != 0:
        gross_by_rank[1] = gross_by_rank[1] + residual

    # Find each participant's rank
    # Build a list of (participant, rank) for participants with final_rank set
    by_rank = {}
    for p in db.participants.values():
        if p["event_id"] != event_id:
            continue
        rank = p.get("final_rank")
        if rank is None:
            continue
        by_rank.setdefault(rank, []).append(p)

    for rank in range(1, 9):
        for p in by_rank.get(rank, []):
            gross = gross_by_rank[rank]
            tax = tax_for_gross(gross, tax_pct)
            disqualified = (p["status"] == "DISQUALIFIED" or
                            participant_has_active_sanction(event_id, p["id"]))
            forfeit = gross if disqualified else 0
            net = gross - tax - forfeit
            if net < 0:
                net = 0
            status = "FORFEITED" if disqualified else "SCHEDULED"
            row = {
                "event_id": event_id,
                "participant_id": p["id"],
                "gross_amount_cents": gross,
                "tax_withheld_cents": tax,
                "forfeit_amount_cents": forfeit,
                "net_amount_cents": net,
                "scheduled_pay_at": pay_at,
                "status": status,
            }
            db.stamp_create(row, common_fields=True)
            db.prize_payments[row["id"]] = row
            # Mirror onto participant
            p["gross_prize_cents"] = gross
            p["net_prize_cents"] = net
            db.stamp_update(p)
            # Emit SyncEvent preview only for SCHEDULED rows
            if status == "SCHEDULED":
                from services.sync import emit
                emit(target_system="PAYMENT", kind="PRIZE_PAID",
                     payload={"prize_payment_id": row["id"], "preview": True,
                              "participant_id": p["id"], "net_amount_cents": net})

    # Participants with rank > 8 receive no PrizePayment but mirror 0
    for p in db.participants.values():
        if p["event_id"] != event_id:
            continue
        if p.get("final_rank") is None or p["final_rank"] > 8:
            if p.get("gross_prize_cents", 0) != 0 or p.get("net_prize_cents", 0) != 0:
                p["gross_prize_cents"] = 0
                p["net_prize_cents"] = 0
                db.stamp_update(p)
    # Recompute event aggregate
    recompute_event_prize_total(event_id)


def recompute_event_prize_total(event_id: str) -> None:
    total = 0
    for pp in db.prize_payments.values():
        if pp["event_id"] != event_id:
            continue
        if pp["status"] in ("SCHEDULED", "PAID"):
            total += pp.get("net_amount_cents", 0)
    ev = db.events.get(event_id)
    if ev and ev.get("prize_paid_total_cents") != total:
        ev["prize_paid_total_cents"] = total
        db.stamp_update(ev)


def recompute_for_sanction(participant_id: str, event_id: str, *, sanction_active: bool) -> None:
    """post_sanction_recompute variant: gross + tax preserved; flip forfeit and net."""
    tax_pct = Decimal(str(db.events[event_id].get("tax_withholding_pct", 0)))
    for pp in list(db.prize_payments.values()):
        if pp["event_id"] != event_id or pp["participant_id"] != participant_id:
            continue
        if sanction_active:
            if pp["status"] == "SCHEDULED":
                pp["forfeit_amount_cents"] = pp["gross_amount_cents"]
                pp["net_amount_cents"] = 0
                pp["status"] = "FORFEITED"
                db.stamp_update(pp)
                # Mirror
                p = db.participants.get(participant_id)
                if p:
                    p["net_prize_cents"] = 0
                    db.stamp_update(p)
        else:
            if pp["status"] == "FORFEITED":
                pp["forfeit_amount_cents"] = 0
                gross = pp["gross_amount_cents"]
                tax = pp["tax_withheld_cents"]  # preserved, NOT recomputed
                net = gross - tax
                if net < 0:
                    net = 0
                pp["net_amount_cents"] = net
                pp["status"] = "SCHEDULED"
                db.stamp_update(pp)
                p = db.participants.get(participant_id)
                if p:
                    p["net_prize_cents"] = net
                    db.stamp_update(p)
    recompute_event_prize_total(event_id)
