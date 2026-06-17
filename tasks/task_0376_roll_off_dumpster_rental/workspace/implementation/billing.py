"""The pickup billing cascade (PRD sections 3.9, 3.10)."""
from db import db
import calculations as calc


def _date_diff_days(start_iso, end_iso):
    """Inclusive span end - start + 1, computed from ISO YYYY-MM-DD dates."""
    from datetime import date
    sy, sm, sd = (int(x) for x in start_iso.split("-"))
    ey, em, ed = (int(x) for x in end_iso.split("-"))
    start = date(sy, sm, sd)
    end = date(ey, em, ed)
    return (end - start).days + 1


def find_pickup_ticket(order_id, stop_id):
    """The WeighTicket referencing this PICKUP/SWAP stop (most recent wins
    if more than one was recorded; tests record exactly one per stop)."""
    matches = [t for t in db.weigh_tickets.values()
               if t["service_stop_id"] == stop_id]
    if not matches:
        return None
    matches.sort(key=lambda t: (t["created_at"], t["id"]))
    return matches[-1]


def _approved_permit_fee(order_id):
    for p in db.street_permits.values():
        if p["order_id"] == order_id and p["status"] == "APPROVED":
            return p["permit_fee_cents"]
    return 0


def run_pickup_billing(order, pickup_stop, ticket, ctype):
    """Run the two-stage billing cascade on a PICKUP completion.

    Stage 1 (estimate): base + overage_day + tonnage(estimate) + permit.
    Stage 2 (final): base + overage_day + tonnage(final) + permit + contamination.
    Then issue an Invoice. The order's billing_status advances
    UNBILLED -> ESTIMATED -> FINALIZED within this one call.
    """
    base_cents = ctype["base_rate_cents"]
    rental_days = order["rental_days"]
    overage_day_cents = calc.overage_day_charge(rental_days, ctype)
    permit_cents = _approved_permit_fee(order["id"])

    # ---- Stage one: estimate (uses PICKUP stop estimated_weight_lbs) ----
    est_weight = pickup_stop["estimated_weight_lbs"]
    tonnage_cents_est = calc.tonnage_overage_charge(est_weight, ctype)
    order["billing_status"] = "ESTIMATED"
    order["estimated_total_cents"] = calc.estimated_charge(
        base_cents, overage_day_cents, tonnage_cents_est, permit_cents)
    db.touch(order)

    # ---- Stage two: final (uses WeighTicket.net_weight_lbs + contamination) ----
    net_weight = ticket["net_weight_lbs"]
    tonnage_cents_final = calc.tonnage_overage_charge(net_weight, ctype)
    # tonnage computed before contamination (HAZMAT reuses overage pounds).
    contamination_cents = calc.contamination_fee(ticket, net_weight, ctype)
    order["billing_status"] = "FINALIZED"
    order["final_total_cents"] = calc.final_charge(
        base_cents, overage_day_cents, tonnage_cents_final,
        permit_cents, contamination_cents)
    db.touch(order)

    # ---- Issue the invoice ----
    total = (base_cents + overage_day_cents + tonnage_cents_final
             + permit_cents + contamination_cents)
    db.insert_with_common(db.invoices, {
        "order_id": order["id"],
        "account_id": order["account_id"],
        "base_cents": base_cents,
        "overage_day_cents": overage_day_cents,
        "tonnage_cents": tonnage_cents_final,
        "permit_cents": permit_cents,
        "contamination_cents": contamination_cents,
        "total_cents": total,
        "status": "ISSUED",
    })

    # ---- Ledger sync: account outstanding recomputed (computed on read) ----
    account = db.contractor_accounts.get(order["account_id"])
    if account is not None:
        db.touch(account)
