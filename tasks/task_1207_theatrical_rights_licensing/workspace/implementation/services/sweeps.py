"""System-driven sweeps fired when the logical clock advances (PRD §2.5)."""
import db
from services import calculations


def run_sweeps():
    """Fire OVERDUE rental transitions and agreement COMPLETED transitions."""
    now = db.clock_now()

    # Rental overdue sweep: non-terminal rentals with due_date < now and status in
    # {SHIPPED, RECEIVED, RETURN_IN_TRANSIT} -> OVERDUE, recompute PROJECTED late fee.
    for r in db.rentals.values():
        if r["status"] in ("SHIPPED", "RECEIVED", "RETURN_IN_TRANSIT") and r["due_date"] < now:
            title = db.titles.get(db.agreements[r["agreement_id"]]["title_id"])
            r["status"] = "OVERDUE"
            r["accrued_late_fee_cents"] = calculations.overdue_fine_cents(r, title, now)
            r["updated_at"] = now
            r["version"] += 1

    # Agreement completion sweep.
    for g in db.agreements.values():
        if g["license_status"] != "ACTIVE":
            continue
        if now <= g["window_end"]:
            continue
        perfs = [p for p in db.performances.values() if p["agreement_id"] == g["id"]]
        if not perfs:
            continue
        all_terminal = all(p["status"] in ("HELD", "CANCELLED") for p in perfs)
        if not all_terminal:
            continue
        held = [p for p in perfs if p["status"] == "HELD"]
        if not all(p["gross_reported"] for p in held):
            continue
        # All HELD performances reported, all terminal, last performance_at < now (implied by window check)
        title = db.titles[g["title_id"]]
        g["royalty_mode"] = "SETTLED"
        settled = calculations.settled_aggregate_royalty(title, g, held)
        g["settled_royalty_total_cents"] = settled
        total_paid = sum(p["amount_cents"] for p in db.payments.values() if p["agreement_id"] == g["id"])
        balance = settled - total_paid
        g["royalty_balance_cents"] = balance
        if balance < 0:
            g["payment_status"] = "REFUNDED"
        g["license_status"] = "COMPLETED"
        g["updated_at"] = now
        g["version"] += 1
