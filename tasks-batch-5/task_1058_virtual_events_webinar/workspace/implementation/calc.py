"""Calculations: pricing, lead scoring, settlements, availability, analytics.

All monetary quantities are integer cents. Rounding is half up, away from zero,
and happens exactly where the PRD says it happens.
"""

from decimal import Decimal, ROUND_HALF_UP

import db
from db import S, dt_of, parse_dt

# ---- registration_amount_due
VIP_SURCHARGE_CENTS = 5000
EARLY_BIRD_DISCOUNT_PCT = Decimal("0.20")
GROUP_DISCOUNT_PCT = Decimal("0.10")
GROUP_MIN_SIZE = 5
MAX_TOTAL_DISCOUNT_PCT = Decimal("0.25")
PROCESSING_FEE_PCT = Decimal("0.03")
PROCESSING_FEE_MIN_CENTS = 100
PROCESSING_FEE_MAX_CENTS = 2500

# ---- lead_score
BOOTH_VISIT_WEIGHT = Decimal("3")
DOC_DOWNLOAD_WEIGHT = Decimal("5")
SESSION_MINUTE_WEIGHT = Decimal("0.5")
MEETING_ACCEPTED_WEIGHT = Decimal("12")
LEAD_SCORE_CAP = 100
HOT_LEAD_THRESHOLD = 60

# ---- sponsor_settlement_lines
PACKAGE_PRICE_CENTS = {
    "BRONZE": Decimal("250000"),
    "SILVER": Decimal("500000"),
    "GOLD": Decimal("900000"),
}
LEAD_OVERAGE_UNIT_CENTS = Decimal("137.5")
BOOTH_STREAM_UNIT_CENTS = Decimal("4.25")
SPONSOR_TAX_PCT = Decimal("0.0825")

# ---- event_settlement_total
STREAMING_RATE_CENTS_PER_MINUTE = 4
PLATFORM_FEE_PCT = Decimal("0.08")
VOLUME_TIER_1_CENTS = 100000
VOLUME_TIER_1_DISCOUNT_PCT = Decimal("0.10")
VOLUME_TIER_2_CENTS = 250000
VOLUME_TIER_2_DISCOUNT_PCT = Decimal("0.15")
PLATFORM_FEE_MIN_CENTS = 500

# ---- global
SPEAKER_TRANSITION_BUFFER_MINUTES = 10
MATCH_EXPIRY_LEAD_MINUTES = 60
ATTENDANCE_MIN_MINUTES = 15


def round_half_up(value, places=0):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value))


# ------------------------------------------------------ registration pricing


def registration_amount_due(ticket_type, event, pricing_clock, effective_group_size):
    """Seven-step tiered pricing, PRD 3.4. Rounds exactly twice."""
    # STEP 1 - list price with tier surcharge
    list_price = Decimal(int(ticket_type.get("price_cents", 0)))
    if ticket_type.get("tier") == "VIP":
        list_price = list_price + Decimal(VIP_SURCHARGE_CENTS)

    # STEP 2 - early-bird component (strict <)
    early_ends = parse_dt(event.get("early_bird_ends_at"))
    if pricing_clock is not None and early_ends is not None and pricing_clock < early_ends:
        early_pct = EARLY_BIRD_DISCOUNT_PCT
    else:
        early_pct = Decimal("0")

    # STEP 3 - group component (>=)
    if effective_group_size is not None and effective_group_size >= GROUP_MIN_SIZE:
        group_pct = GROUP_DISCOUNT_PCT
    else:
        group_pct = Decimal("0")

    # STEP 4 - stacked discount, capped
    discount_pct = min(early_pct + group_pct, MAX_TOTAL_DISCOUNT_PCT)

    # STEP 5 - discounted price, rounded once
    discounted_cents = rhu_int(list_price * (Decimal(1) - discount_pct))

    # STEP 6 - processing fee, rounded once, then clamped
    fee_cents = rhu_int(Decimal(discounted_cents) * PROCESSING_FEE_PCT)
    fee_cents = min(max(fee_cents, PROCESSING_FEE_MIN_CENTS), PROCESSING_FEE_MAX_CENTS)

    # STEP 7 - never rounded again
    return discounted_cents + fee_cents


def price_provisional(registration, ticket_type, event):
    """pricing_clock = current logical clock; group size = the claimed value."""
    return registration_amount_due(
        ticket_type, event, S.now(), registration.get("group_size") or 1
    )


def observed_group_size(registration):
    """The OBSERVED count of PAID registrations of the event sharing the group_code."""
    code = registration.get("group_code")
    if code is None:
        return 1
    count = 0
    for r in S.registrations.values():
        if (
            r.get("event_id") == registration.get("event_id")
            and r.get("group_code") == code
            and r.get("payment_status") == "PAID"
        ):
            count += 1
    return count


def price_final(registration, ticket_type, event):
    """pricing_clock = the registration's own created_at; observed group size."""
    return registration_amount_due(
        ticket_type, event, dt_of(registration, "created_at"),
        observed_group_size(registration),
    )


# ------------------------------------------------------- ticket availability


def recompute_availability(ticket_type):
    available_seats = int(ticket_type.get("quota", 0)) - int(ticket_type.get("sold_count", 0))
    ticket_type["availability_status"] = "SOLD_OUT" if available_seats <= 0 else "AVAILABLE"
    return ticket_type["availability_status"]


# -------------------------------------------------------------- lead scoring


def score_lead(lead, variant):
    raw = (
        Decimal(int(lead.get("booth_visits", 0))) * BOOTH_VISIT_WEIGHT
        + Decimal(int(lead.get("doc_downloads", 0))) * DOC_DOWNLOAD_WEIGHT
    )
    if variant == "ENGAGEMENT_WEIGHTED":
        reg = S.registrations.get(lead.get("registration_id"))
        watched = 0
        meetings = 0
        if reg is not None and reg.get("attendance_status") != "WITHDRAWN":
            watched = int(reg.get("watched_minutes", 0))
            meetings = int(reg.get("accepted_meeting_count", 0))
        raw = raw + Decimal(watched) * SESSION_MINUTE_WEIGHT
        raw = raw + Decimal(meetings) * MEETING_ACCEPTED_WEIGHT
    score = min(rhu_int(raw), LEAD_SCORE_CAP)
    lead["score"] = score
    lead["score_variant"] = variant
    lead["is_hot"] = score >= HOT_LEAD_THRESHOLD
    return score


# ------------------------------------------------------- sponsor settlement


def sponsor_settlement_lines(sponsor):
    booth = None
    for b in db.sort_rows(list(S.booths.values())):
        if b.get("sponsor_id") == sponsor["id"]:
            booth = b
            break

    if booth is None:
        overage_units = 0
        stream_units = 0
    else:
        overage_units = max(
            0, int(booth.get("captured_lead_count", 0)) - int(booth.get("lead_quota", 0))
        )
        stream_units = int(booth.get("stream_minutes_total", 0))

    package_rate = PACKAGE_PRICE_CENTS[sponsor.get("package_tier")]

    raw_lines = [
        ("PACKAGE", 1, package_rate),
        ("LEAD_OVERAGE", overage_units, LEAD_OVERAGE_UNIT_CENTS),
        ("BOOTH_STREAM", stream_units, BOOTH_STREAM_UNIT_CENTS),
    ]

    line_items = []
    subtotal = 0
    for label, units, unit_cents in raw_lines:
        line_total = rhu_int(Decimal(units) * unit_cents)
        subtotal += line_total
        line_items.append({
            "label": label,
            "units": units,
            "unit_cents": _num(unit_cents),
            "line_total_cents": line_total,
        })

    tax_cents = rhu_int(Decimal(subtotal) * SPONSOR_TAX_PCT)
    return {
        "line_items": line_items,
        "subtotal_cents": subtotal,
        "tax_cents": tax_cents,
        "platform_fee_cents": 0,
        "total_cents": subtotal + tax_cents,
        "organizer_payout_cents": 0,
    }


def _num(dec):
    """Render a unit rate as an int when whole, otherwise as a float."""
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


# --------------------------------------------------------- event settlement


def event_settlement_total(event):
    """Seven steps, strictly in order. The volume discount is keyed on subtotal."""
    paid = [
        r for r in db.sort_rows(list(S.registrations.values()))
        if r.get("event_id") == event["id"] and r.get("payment_status") == "PAID"
    ]

    # STEP 1 - re-derive every PAID registration with the final variant
    for r in paid:
        ticket_type = S.ticket_types.get(r.get("ticket_type_id"))
        if ticket_type is None:
            continue
        r["final_amount_due_cents"] = price_final(r, ticket_type, event)
        db.touch(r)

    # STEP 2
    gross_ticket_cents = sum(int(r.get("final_amount_due_cents") or 0) for r in paid)

    # STEP 3
    adjustment = sum(
        int(r.get("final_amount_due_cents") or 0) - int(r.get("amount_paid_cents") or 0)
        for r in paid
    )

    # STEP 4
    streaming_cents = int(event.get("streamed_minutes_total", 0)) * STREAMING_RATE_CENTS_PER_MINUTE
    subtotal_cents = gross_ticket_cents + streaming_cents

    # STEP 5 - inclusive thresholds
    if subtotal_cents >= VOLUME_TIER_2_CENTS:
        discount_pct = VOLUME_TIER_2_DISCOUNT_PCT
    elif subtotal_cents >= VOLUME_TIER_1_CENTS:
        discount_pct = VOLUME_TIER_1_DISCOUNT_PCT
    else:
        discount_pct = Decimal("0")

    # STEP 6 - the only two roundings
    raw_fee_cents = rhu_int(Decimal(subtotal_cents) * PLATFORM_FEE_PCT)
    platform_fee_cents = max(
        rhu_int(Decimal(raw_fee_cents) * (Decimal(1) - discount_pct)),
        PLATFORM_FEE_MIN_CENTS,
    )

    # STEP 7
    total_cents = platform_fee_cents + streaming_cents
    organizer_payout_cents = gross_ticket_cents - total_cents

    line_items = [
        {
            "label": "PLATFORM_FEE",
            "units": 1,
            "unit_cents": platform_fee_cents,
            "line_total_cents": platform_fee_cents,
        },
        {
            "label": "STREAMING",
            "units": int(event.get("streamed_minutes_total", 0)),
            "unit_cents": STREAMING_RATE_CENTS_PER_MINUTE,
            "line_total_cents": streaming_cents,
        },
    ]

    event["settlement_adjustment_cents"] = adjustment

    return {
        "line_items": line_items,
        "subtotal_cents": subtotal_cents,
        "tax_cents": 0,
        "platform_fee_cents": platform_fee_cents,
        "total_cents": total_cents,
        "organizer_payout_cents": organizer_payout_cents,
    }


# ------------------------------------------------------------- analytics


def event_analytics_snapshot(event):
    now = S.now()
    population = []
    for r in S.registrations.values():
        if r.get("event_id") != event["id"]:
            continue
        if r.get("attendance_status") not in ("CHECKED_IN", "ATTENDED"):
            continue
        created = dt_of(r, "created_at")
        if created is not None and created > now:
            continue
        population.append(r)

    unique_attendees = len(population)
    total_watch_minutes = sum(int(r.get("watched_minutes", 0)) for r in population)
    if unique_attendees > 0:
        avg = round_half_up(Decimal(total_watch_minutes) / Decimal(unique_attendees), 2)
    else:
        avg = Decimal("0.00")

    on_demand_views = sum(
        int(rec.get("view_count", 0))
        for rec in S.recordings.values()
        if rec.get("event_id") == event["id"] and rec.get("state") == "PUBLISHED"
    )

    return {
        "unique_attendees": unique_attendees,
        "total_watch_minutes": total_watch_minutes,
        "avg_watch_minutes": float(avg),
        "on_demand_views": on_demand_views,
        "registered_count": int(event.get("registered_count", 0)),
        "gross_collected_cents": int(event.get("gross_collected_cents", 0)),
    }
