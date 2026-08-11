"""Per-visit roll-ups: units, minutes, shoe pairs and the estimate (PRD 3.5, 3.9)."""

from core.constants import (
    HORSE_HANDLING_MINUTES,
    SEDATION_EXTRA_MINUTES,
    SEDATION_HANDLING_MULTIPLIER_BP,
    SEDATION_LABOR_SURCHARGE_BP,
    SERVICE_TYPE_TO_MINUTES,
    SERVICE_TYPE_TO_PRICE_FIELD,
    SERVICE_TYPE_TO_UNITS,
)
from core.store import db, order_key
from core.timeutil import parse_iso_date

from .money import apply_bp, pairs_for_shoe_count
from .rates import select_rate_card

ACTIVE_LINE_STATUSES = ("PLANNED", "PERFORMED")


def lines_of(appointment, statuses=ACTIVE_LINE_STATUSES):
    rows = [
        line
        for line in db.service_lines.values()
        if line["appointment_id"] == appointment["id"]
        and (statuses is None or line["status"] in statuses)
    ]
    rows.sort(key=order_key)
    return rows


def service_units(appointment, lines=None):
    rows = lines_of(appointment) if lines is None else lines
    return sum(SERVICE_TYPE_TO_UNITS[line["service_type"]] for line in rows)


def service_minutes(appointment, horse, lines=None):
    """Per-limb chair time plus handling; the SEDATED variant adds 18 minutes."""
    rows = lines_of(appointment) if lines is None else lines
    limb_minutes = sum(SERVICE_TYPE_TO_MINUTES[line["service_type"]] for line in rows)
    if horse["requires_sedation"]:
        handling = apply_bp(HORSE_HANDLING_MINUTES, SEDATION_HANDLING_MULTIPLIER_BP)
        return limb_minutes + handling + SEDATION_EXTRA_MINUTES
    return limb_minutes + HORSE_HANDLING_MINUTES


def shoe_pairs_required(appointment, lines=None):
    """{sku_id: pairs} over PLANNED/PERFORMED lines that consume a shoe."""
    rows = lines_of(appointment) if lines is None else lines
    counts = {}
    order = []
    for line in rows:
        sku_id = line.get("sku_id")
        if not sku_id:
            continue
        if line["service_type"] not in ("NEW_SHOES", "CORRECTIVE", "GLUE_ON"):
            continue
        if sku_id not in counts:
            counts[sku_id] = 0
            order.append(sku_id)
        counts[sku_id] += 1
    return {sku_id: pairs_for_shoe_count(counts[sku_id]) for sku_id in order}


def line_labor_cents(appointment, horse, card, service_type):
    """Rate-card base plus the per-line sedation surcharge, rounded on its own.

    On a WARRANTY_REVISIT the labour of EVERY line is forced to 0 while the
    visit's product lines are still charged in full.
    """
    if appointment["visit_kind"] == "WARRANTY_REVISIT":
        return 0
    base = card[SERVICE_TYPE_TO_PRICE_FIELD[service_type]]
    if horse["requires_sedation"]:
        return base + apply_bp(base, SEDATION_LABOR_SURCHARGE_BP)
    return base


def recompute_appointment_rollups(appointment, horse=None):
    horse = horse or db.get("horses", appointment["horse_id"])
    rows = lines_of(appointment)
    appointment["service_units"] = service_units(appointment, rows)
    appointment["service_minutes"] = service_minutes(appointment, horse, rows)
    return appointment


def recompute_estimate(appointment, horse=None):
    """The ESTIMATE variant: PLANNED lines priced off the scheduled date's card.

    No trip-fee share, no discounts, no tax and no fees.
    """
    horse = horse or db.get("horses", appointment["horse_id"])
    card = select_rate_card(appointment["scheduled_date"], required=False)
    if card is None:
        appointment["estimated_total_cents"] = 0
        return appointment
    planned = [line for line in lines_of(appointment) if line["status"] == "PLANNED"]
    total = 0
    for line in planned:
        total += line_labor_cents(appointment, horse, card, line["service_type"])
    for sku_id, pairs in shoe_pairs_required(appointment, planned).items():
        sku = db.get("shoe_skus", sku_id)
        if sku:
            total += pairs * sku["price_cents_per_pair"]
    total += card["pad_price_cents"] * sum(1 for line in planned if line["with_pad"])
    appointment["estimated_total_cents"] = total
    return appointment


def prescription_is_live(prescription, on_date_iso):
    """Both date bounds are inclusive (PRD 3.6)."""
    if prescription is None or prescription["status"] != "ACTIVE":
        return False
    on_date = parse_iso_date(on_date_iso)
    issued = parse_iso_date(prescription["issued_on"])
    expires = parse_iso_date(prescription["expires_on"])
    if on_date is None or issued is None or expires is None:
        return False
    return issued <= on_date <= expires


def prescription_covers(prescription, limb):
    return prescription is not None and limb in prescription["limb_scope"]
