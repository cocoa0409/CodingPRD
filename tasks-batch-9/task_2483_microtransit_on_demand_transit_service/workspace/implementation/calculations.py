"""Pinned domain arithmetic (SCAFFOLD Section 1.3, PRD Sections 2.6-2.7)."""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

# --- corridor_travel_geometry ---------------------------------------------
TRAVEL_MINUTES_PER_INDEX = 3

# --- pool_match_selection -------------------------------------------------
SURGE_PENALTY = 15
WAV_TIGHT_PENALTY = 8
SEAT_SLACK_CAP = 12
SEAT_SLACK_WEIGHT = 2
MAX_MATCH_ATTEMPTS = 2

# --- trip_fare ------------------------------------------------------------
BAND_EDGE_SHORT_MINUTES = 10
BAND_EDGE_MEDIUM_MINUTES = 20
BAND_SURCHARGE_CENTS = {"SHORT": 0, "MEDIUM": 75, "LONG": 150}
CATEGORY_MULTIPLIER = {
    "FULL": Decimal("1.00"),
    "REDUCED": Decimal("0.50"),
    "PARATRANSIT": Decimal("0.00"),
}

# --- fleet_sizing ---------------------------------------------------------
TRIPS_PER_BLOCK_HOUR = 4
SURGE_THRESHOLD_PEAK_FACTOR = Decimal("1.50")
MAX_SURGE_BLOCKS = 6

# --- subsidy_per_trip -----------------------------------------------------
OPERATING_COST_CENTS_PER_REVENUE_HOUR = 8250
ADMIN_OVERHEAD_PCT = Decimal("0.12")

# --- service_performance_metrics -----------------------------------------
WAV_EQUIVALENCE_MAX_RATIO = Decimal("1.25")

# --- temporal -------------------------------------------------------------
DRIVER_REST_BUFFER_MINUTES = 30
DECLINE_SUSPENSION_THRESHOLD = 3
CURB_BUCKET_MINUTES = 15


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to a whole unit (used for every money figure)."""
    return int(round_half_up(value, 0))


def rhu_float(value, places):
    return float(round_half_up(value, places))


def ceil_div(numerator, denominator):
    return int((dec(numerator) / dec(denominator)).quantize(
        Decimal(1), rounding=ROUND_CEILING))


def ceil_value(value):
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_CEILING))


# --------------------------------------------------------------------------
# corridor geometry
# --------------------------------------------------------------------------

def baseline_direct_minutes(origin_index, destination_index):
    return TRAVEL_MINUTES_PER_INDEX * abs(destination_index - origin_index)


def prospective_span(block, origin_index, destination_index):
    if block.get("committed_index_min") is None:
        span_min = min(origin_index, destination_index)
        span_max = max(origin_index, destination_index)
    else:
        span_min = min(block["committed_index_min"], origin_index, destination_index)
        span_max = max(block["committed_index_max"], origin_index, destination_index)
    return span_min, span_max


def projected_detour_minutes(block, origin_index, destination_index):
    baseline = baseline_direct_minutes(origin_index, destination_index)
    span_min, span_max = prospective_span(block, origin_index, destination_index)
    return TRAVEL_MINUTES_PER_INDEX * (span_max - span_min) - baseline


def detour_allowance_minutes(zone, baseline):
    pct_allowance = ceil_value(dec(baseline) * dec(zone["detour_tolerance_pct"]))
    return max(zone["detour_tolerance_floor_minutes"], pct_allowance)


# --------------------------------------------------------------------------
# minute / hour derivations
# --------------------------------------------------------------------------

def minutes_between(later, earlier):
    seconds = (later - earlier).total_seconds()
    return rhu_int(dec(seconds) / dec(60))


def hours_between_2dp(later, earlier):
    seconds = (later - earlier).total_seconds()
    return rhu_float(dec(seconds) / dec(3600), 2)


def epoch_minute_bucket(instant):
    epoch_minutes = int(instant.timestamp()) // 60
    return epoch_minutes // CURB_BUCKET_MINUTES


# --------------------------------------------------------------------------
# match score
# --------------------------------------------------------------------------

def match_score(trip, block, vehicle, detour):
    remaining_seats = (vehicle["seat_capacity"] - block["seats_committed"]
                       - trip["party_size"])
    wav_headroom = vehicle["wav_positions"] - block["wav_positions_committed"]
    score = min(100, detour * 4)
    score += 0 if block["block_type"] == "BASE" else SURGE_PENALTY
    if trip["wav_required"]:
        score += 0 if wav_headroom >= 2 else WAV_TIGHT_PENALTY
    score += min(SEAT_SLACK_CAP, remaining_seats) * SEAT_SLACK_WEIGHT
    return score


# --------------------------------------------------------------------------
# trip_fare (eight pinned steps, two variants)
# --------------------------------------------------------------------------

def distance_band(minutes):
    if minutes <= BAND_EDGE_SHORT_MINUTES:
        return "SHORT"
    if minutes <= BAND_EDGE_MEDIUM_MINUTES:
        return "MEDIUM"
    return "LONG"


def trip_fare(zone, rider, connection, variant_minutes, variant_pickup_dt,
              daily_paid_cents, weekly_paid_cents):
    # step 1 -- distance band
    band = distance_band(variant_minutes or 0)

    # step 2 -- guaranteed-transfer waiver (decided before any money)
    surcharge_waived = False
    if connection is not None and variant_pickup_dt is not None:
        import clock as _clock
        departure = _clock.parse_dt(connection["scheduled_departure_utc"])
        delta_seconds = abs((variant_pickup_dt - departure).total_seconds())
        surcharge_waived = (
            delta_seconds <= connection["guaranteed_transfer_buffer_minutes"] * 60)

    # step 3 -- gross fare
    gross_cents = zone["base_fare_cents"] + (
        0 if surcharge_waived else BAND_SURCHARGE_CENTS[band])

    # step 4 -- category multiplier; the single rounding of the whole rule
    category_cents = rhu_int(
        dec(gross_cents) * CATEGORY_MULTIPLIER[rider["fare_category"]])

    # step 5 -- transfer credit, bounded by the post-multiplier fare
    if surcharge_waived:
        transfer_credit_cents = min(connection["transfer_credit_cents"], category_cents)
    else:
        transfer_credit_cents = 0

    # step 6 -- net fare before capping
    net_before_cap_cents = category_cents - transfer_credit_cents

    # step 7 -- fare capping
    daily_headroom_cents = max(0, zone["fare_cap_cents_daily"] - daily_paid_cents)
    weekly_headroom_cents = max(0, zone["fare_cap_cents_weekly"] - weekly_paid_cents)
    charge_cents = min(net_before_cap_cents, daily_headroom_cents, weekly_headroom_cents)

    # step 8 -- attribution and rebate
    if charge_cents == net_before_cap_cents:
        applied_cap = "NONE"
    elif daily_headroom_cents <= weekly_headroom_cents:
        applied_cap = "DAILY"
    else:
        applied_cap = "WEEKLY"
    cap_rebate_cents = net_before_cap_cents - charge_cents

    return {
        "band": band,
        "surcharge_waived": surcharge_waived,
        "gross_cents": gross_cents,
        "category_cents": category_cents,
        "transfer_credit_cents": transfer_credit_cents,
        "net_before_cap_cents": net_before_cap_cents,
        "charge_cents": charge_cents,
        "applied_cap": applied_cap,
        "cap_rebate_cents": cap_rebate_cents,
    }


# --------------------------------------------------------------------------
# fleet_sizing
# --------------------------------------------------------------------------

def fleet_sizing(window_start_dt, window_end_dt, forecast_trips, peak_factor):
    window_seconds = dec((window_end_dt - window_start_dt).total_seconds())
    window_hours = window_seconds / dec(3600)
    block_trip_capacity = dec(TRIPS_PER_BLOCK_HOUR) * window_hours

    required_base_blocks = ceil_div(forecast_trips, block_trip_capacity)

    peak_trips = ceil_value(dec(forecast_trips) * dec(peak_factor))
    surge_trips = peak_trips - forecast_trips
    if dec(peak_factor) <= SURGE_THRESHOLD_PEAK_FACTOR:
        required_surge_blocks = 0
    else:
        required_surge_blocks = min(
            MAX_SURGE_BLOCKS, ceil_div(surge_trips, block_trip_capacity))
    return required_base_blocks, required_surge_blocks


# --------------------------------------------------------------------------
# subsidy_per_trip
# --------------------------------------------------------------------------

def block_operating_cost_cents(revenue_hours):
    return rhu_int(dec(revenue_hours)
                   * dec(OPERATING_COST_CENTS_PER_REVENUE_HOUR)
                   * (Decimal(1) + ADMIN_OVERHEAD_PCT))


def subsidy_per_trip_cents(total_operating_cost_cents, total_fare_revenue_cents,
                           total_trips):
    if total_trips == 0:
        return 0
    return rhu_int(dec(total_operating_cost_cents - total_fare_revenue_cents)
                   / dec(total_trips))


# --------------------------------------------------------------------------
# half-open interval helpers
# --------------------------------------------------------------------------

def overlaps_half_open(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end
