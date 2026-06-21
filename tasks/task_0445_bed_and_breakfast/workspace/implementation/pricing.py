"""Booking money-ladder recomputation (PRD §3.2, §3.3).

Recomputes nights, room_charge, package_charge, taxable_base, lodging_tax, total,
deposit_due, and the running deposit_paid / net_inn_revenue figures from current
inventory & rate config. Called at booking create and at confirm time (PRD §3.2:
"Each of these money fields is recomputed at confirm time").
"""
import calculations as calc
from db import db


def rate_periods_for_inn(inn_id):
    return [rp for rp in db.rate_periods.values() if rp["inn_id"] == inn_id]


def recompute_booking_money(booking):
    inn = db.inns[booking["inn_id"]]
    room = db.rooms[booking["room_id"]]
    package = db.packages.get(booking["package_id"]) if booking.get("package_id") else None
    rate_periods = rate_periods_for_inn(booking["inn_id"])

    nights = calc.date_diff_days(booking["checkout_date"], booking["checkin_date"])
    per_night = calc.per_night_charges(
        room, booking["checkin_date"], booking["checkout_date"], rate_periods
    )
    room_charge = sum(per_night)
    first_night_cents = per_night[0] if per_night else 0

    package_charge = calc.compute_package_charge(package, nights)
    taxable_base = calc.compute_taxable_base(room, room_charge, package, package_charge)
    lodging_tax = calc.compute_lodging_tax(taxable_base, inn["lodging_tax_rate_bps"])
    total = room_charge + package_charge + lodging_tax
    deposit_due = calc.compute_deposit_due(booking["channel"], total, first_night_cents)

    booking["nights"] = nights
    booking["room_charge_cents"] = room_charge
    booking["package_charge_cents"] = package_charge
    booking["taxable_base_cents"] = taxable_base
    booking["lodging_tax_cents"] = lodging_tax
    booking["total_cents"] = total
    booking["deposit_due_cents"] = deposit_due
    booking["_first_night_cents"] = first_night_cents
    recompute_payment_fields(booking)


def recompute_payment_fields(booking):
    """deposit_paid_cents = sum(DEPOSIT + REDEMPTION) - sum(|REFUND|) over the
    booking's ledger. REFUND amounts are stored negative, so a plain signed sum of
    DEPOSIT + REDEMPTION + REFUND yields money-in net of refunds. FORFEIT is 0.
    (PRD §3.3.)
    net_inn_revenue = total - OTA commission - lodging_tax (commission only on OTA).
    """
    paid = 0
    for le in db.ledger_entries.values():
        if le["booking_id"] != booking["id"]:
            continue
        kind = le["source_kind"]
        if kind in ("DEPOSIT", "REDEMPTION", "REFUND"):
            paid += le["amount_cents"]
    booking["deposit_paid_cents"] = paid

    total = booking["total_cents"]
    commission = 0
    if booking["channel"] == "OTA":
        commission = calc.round_half_up_bps(total, booking.get("ota_commission_bps", 0))
    booking["net_inn_revenue_cents"] = total - commission - booking["lodging_tax_cents"]
