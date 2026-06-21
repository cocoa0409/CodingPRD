"""Calculation rules (PRD §3.7 destruction charge, §3.8 storage invoice,
§3.9 retrieval charge, §3.5 net weight)."""
from decimal import Decimal

from db import db
from common import round_half_up_cents, round_kg


def destruction_charge(order, rate_card):
    """Compute order_charge_cents (PRD §3.7). billed_weight_kg already set on the order.

    Pinned component order: weight_charge, then trip_fee, then console_fee, then sum.
    """
    billed_weight_kg = order["billed_weight_kg"]
    cadence = order["cadence"]
    service_mode = order["service_mode"]

    if cadence == "SCHEDULED":
        per_kg_rate = rate_card["scheduled_purge_rate_cents_per_kg"]
    else:  # ONE_TIME
        per_kg_rate = rate_card["onetime_purge_rate_cents_per_kg"]

    weight_charge_cents = round_half_up_cents(
        Decimal(str(billed_weight_kg)) * Decimal(per_kg_rate)
    )

    trip_fee_cents = rate_card["onsite_trip_fee_cents"] if service_mode == "ON_SITE" else 0

    console_count = 0
    for cid in order.get("container_ids") or []:
        c = db.containers.get(cid)
        if c is not None and c["container_type"] == "CONSOLE":
            console_count += 1
    console_fee_cents = rate_card["console_swap_fee_cents"] * console_count

    return weight_charge_cents + trip_fee_cents + console_fee_cents


def estimated_billed_weight(order):
    """Sum of capacity_kg across the order's named containers (PRD §3.3 estimated)."""
    total = Decimal("0")
    for cid in order.get("container_ids") or []:
        c = db.containers.get(cid)
        if c is not None:
            total += Decimal(str(c["capacity_kg"]))
    # capacity_kg is integer kg; keep as a plain number.
    return float(total)


def net_weight(order, gross_weight_kg):
    """tare_total = sum tare_weight_kg over the order's container_ids; net = max(gross-tare,0).

    3 decimal places, round-half-up, floored at 0 (PRD §3.5 / §2.7).
    Returns (tare_total_kg, net_weight_kg).
    """
    tare_total = Decimal("0")
    for cid in order.get("container_ids") or []:
        c = db.containers.get(cid)
        if c is not None:
            tare_total += Decimal(str(c["tare_weight_kg"]))
    net = Decimal(str(gross_weight_kg)) - tare_total
    if net < 0:
        net = Decimal("0")
    return round_kg(tare_total), round_kg(net)


def retrieval_charge(priority, rate_card):
    """PRD §3.9: STANDARD = base; RUSH = round_half_up(base * bps / 10000)."""
    base = rate_card["retrieval_fee_cents"]
    if priority == "RUSH":
        bps = rate_card["rush_retrieval_multiplier_bps"]
        return round_half_up_cents(Decimal(base) * Decimal(bps) / Decimal(10000))
    return base
