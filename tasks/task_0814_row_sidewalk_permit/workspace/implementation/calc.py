from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# --- occupancy fee -----------------------------------------------------------
ZONE_BASE_CENTS = {"RESIDENTIAL": 5000, "COMMERCIAL": 10000, "ARTERIAL": 20000}
ZONE_DAILY_CENTS = {"RESIDENTIAL": 500, "COMMERCIAL": 1500, "ARTERIAL": 3000}
ZONE_CAP_CENTS = {"RESIDENTIAL": 200000, "COMMERCIAL": 500000, "ARTERIAL": 1000000}
AREA_FACTOR = {"SIDEWALK": Decimal("1.0"), "LANE": Decimal("2.0"), "FULL_ROAD": Decimal("3.5")}

# --- total permit charge -----------------------------------------------------
TCP_REVIEW_FEE_CENTS = 7500
INSPECTION_FEE_CENTS = 4000
SURCHARGE_PCT = Decimal("0.0725")

# --- bond --------------------------------------------------------------------
BOND_FLOOR_CENTS = 50000
BOND_MULTIPLIER = 2

# --- penalties ---------------------------------------------------------------
PENALTY_BASE_CENTS = 15000
ESCALATION_PCT = Decimal("0.5")
PENALTY_MAX_CENTS = 100000
PENALTY_REVOKE_THRESHOLD_CENTS = 37500

# --- moratorium --------------------------------------------------------------
MORATORIUM_YEARS = {"RESIDENTIAL": 2, "COMMERCIAL": 3, "ARTERIAL": 5}

# --- sidewalk buffer ---------------------------------------------------------
SIDEWALK_BUFFER_DAYS = 3

ZONE_CLASSES = set(ZONE_BASE_CENTS.keys())


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_date(s):
    return date.fromisoformat(s)


def duration_days(start, end):
    return (parse_date(end) - parse_date(start)).days


def parse_iso_datetime(s):
    s2 = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def occupancy_fee(zone_class, obstruction_type, start_date, end_date):
    base = ZONE_BASE_CENTS[zone_class]
    daily = ZONE_DAILY_CENTS[zone_class]
    area = AREA_FACTOR[obstruction_type]
    days = duration_days(start_date, end_date)
    product = round_half_up(Decimal(daily) * area * Decimal(days))
    raw = base + product
    return min(raw, ZONE_CAP_CENTS[zone_class])


def surcharge_and_total(estimated_fee_cents):
    components = [estimated_fee_cents, TCP_REVIEW_FEE_CENTS, INSPECTION_FEE_CENTS]
    # PINNED ORDER: surcharge is rounded per component then summed.
    surcharge = sum(round_half_up(Decimal(c) * SURCHARGE_PCT) for c in components)
    total = sum(components) + surcharge
    return surcharge, total


def bond_required(estimated_occupancy_fee_cents):
    return max(BOND_FLOOR_CENTS, estimated_occupancy_fee_cents * BOND_MULTIPLIER)


def penalty_for(prior_count):
    escalated = Decimal(PENALTY_BASE_CENTS) * (Decimal(1) + ESCALATION_PCT * Decimal(prior_count))
    return min(PENALTY_MAX_CENTS, round_half_up(escalated))


def bond_refund(posted_cents, deficiency_total, cumulative_penalty_cents):
    refund = max(0, posted_cents - deficiency_total - cumulative_penalty_cents)
    forfeit = posted_cents - refund
    return refund, forfeit


def _add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:  # Feb 29 -> Feb 28
        return d.replace(year=d.year + n, day=28)


def moratorium_end_date(last_repaved_date, zone_class):
    d = parse_date(last_repaved_date)
    return _add_years(d, MORATORIUM_YEARS[zone_class]).isoformat()
