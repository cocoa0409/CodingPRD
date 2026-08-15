"""Calculation rules: permit_fee, credit_bundle_subtotal, sale_total_with_service_fee,
daily_settlement, inspector_assignment. All money is integer cents via Decimal with
ROUND_HALF_UP exactly where the rules prescribe."""
from decimal import Decimal, ROUND_HALF_UP

from db import store

# --- permit_fee constants ---------------------------------------------------
BASE_FEE_CENTS = 25000
REINSPECTION_SURCHARGE_CENTS = 7500
MAX_FEE_CENTS = 200000
CLASS_RATE_CENTS = {"KIDDIE": 5000, "FAMILY": 9000, "THRILL": 14000, "EXTREME": 20000}

# --- service fee constants --------------------------------------------------
SERVICE_FEE_PCT = Decimal("0.06")
SERVICE_FEE_MIN_CENTS = 50

# --- settlement constants ---------------------------------------------------
RECONCILIATION_FLAG_THRESHOLD_CENTS = 1000

# --- inspector assignment constants -----------------------------------------
TRAVEL_BUFFER_HOURS = 2

# --- wind constants ---------------------------------------------------------
FAIR_WIND_CLOSURE_MPH = 45
FAIR_WIND_RESUME_MPH = 39
RIDE_RESUME_HYSTERESIS_MPH = 3

# --- incident constants -----------------------------------------------------
MINOR_INCIDENT_DAILY_THRESHOLD = 3


def _round_cent(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def qualifying_rides(fair_id):
    """Rides of the fair with setup_status == SETUP_VERIFIED (any license posture)."""
    return [
        r
        for r in store["rides"].values()
        if r["fair_id"] == fair_id and r["setup_status"] == "SETUP_VERIFIED"
    ]


def fair_wide_failure_count(fair_id):
    return len(
        [
            a
            for a in store["appointments"].values()
            if a["fair_id"] == fair_id
            and a["scope"] == "FAIR_WIDE"
            and a["status"] == "COMPLETED_FAIL"
        ]
    )


def permit_fee(fair_id, failures):
    """Returns (fee_cents, billable_ride_count). Cap applied LAST, after surcharges."""
    rides = qualifying_rides(fair_id)
    subtotal = BASE_FEE_CENTS + sum(CLASS_RATE_CENTS[r["ride_class"]] for r in rides)
    fee = subtotal + REINSPECTION_SURCHARGE_CENTS * failures
    return min(fee, MAX_FEE_CENTS), len(rides)


def credit_bundle_subtotal(base_price_cents, quantity):
    """Marginal tiers; discounted per-unit prices rounded half-up BEFORE multiplying."""
    tier1_count = min(quantity, 9)
    tier2_count = min(max(quantity - 9, 0), 15)
    tier3_count = max(quantity - 24, 0)
    tier1_unit = base_price_cents
    tier2_unit = _round_cent(Decimal(base_price_cents) * Decimal("0.90"))
    tier3_unit = _round_cent(Decimal(base_price_cents) * Decimal("0.80"))
    return (
        tier1_count * tier1_unit
        + tier2_count * tier2_unit
        + tier3_count * tier3_unit
    )


def sale_pricing(kind, base_price_cents, quantity):
    """Returns (subtotal_cents, service_fee_cents, total_charged_cents).

    The fee is computed on the PRE-FEE subtotal (evaluation order is pinned).
    """
    if kind == "CREDIT_BUNDLE":
        subtotal = credit_bundle_subtotal(base_price_cents, quantity)
    elif kind == "RIDE_TICKET":
        subtotal = base_price_cents * quantity
    else:  # WRISTBAND: flat price, quantity pinned to 1
        subtotal = base_price_cents
    fee = max(SERVICE_FEE_MIN_CENTS, _round_cent(Decimal(subtotal) * SERVICE_FEE_PCT))
    return subtotal, fee, subtotal + fee


def projected_settlement(day_id):
    """forward_looking variant at close-gates. VOIDED sales stay visible in gross/voided."""
    sales = [s for s in store["sales"].values() if s["operating_day_id"] == day_id]
    gross = sum(s["total_charged_cents"] for s in sales)
    voided = sum(s["total_charged_cents"] for s in sales if s["status"] == "VOIDED")
    return gross, voided, gross - voided


def recognized_settlement(day_id):
    """chronological variant at reconcile; per-sale pro-rata round_half_up before summing."""
    sales = [s for s in store["sales"].values() if s["operating_day_id"] == day_id]
    sales.sort(key=lambda s: (s["created_at"], s["_seq"]))
    recognized = 0
    for sale in sales:
        if sale["status"] == "VOIDED":
            continue
        if sale["is_unlimited"]:
            recognized += sale["total_charged_cents"]
        else:
            prorata = _round_cent(
                Decimal(sale["subtotal_cents"])
                * Decimal(sale["credits_redeemed"])
                / Decimal(sale["credits_granted"])
            )
            recognized += sale["service_fee_cents"] + prorata
    return recognized


def assign_inspector(scheduled_date, start_hour, duration_hours):
    """Weighted-scoring inspector selector. Returns the chosen Inspector or None.

    Eligible: active; same-date appointments in {SCHEDULED, COMPLETED_PASS,
    COMPLETED_FAIL} below max_daily_inspections; and none of those appointments
    violates the two-hour travel buffer. Ranked by (same-date count ASC,
    inspector created_at ASC). CANCELLED frees the slot.
    """
    new_end = start_hour + duration_hours
    best = None
    best_key = None
    for inspector in store["inspectors"].values():
        if not inspector["active"]:
            continue
        same_day = [
            a
            for a in store["appointments"].values()
            if a["inspector_id"] == inspector["id"]
            and a["scheduled_date"] == scheduled_date
            and a["status"] in ("SCHEDULED", "COMPLETED_PASS", "COMPLETED_FAIL")
        ]
        if len(same_day) >= inspector["max_daily_inspections"]:
            continue
        conflict = False
        for existing in same_day:
            if not (
                new_end + TRAVEL_BUFFER_HOURS <= existing["start_hour"]
                or existing["end_hour"] + TRAVEL_BUFFER_HOURS <= start_hour
            ):
                conflict = True
                break
        if conflict:
            continue
        key = (len(same_day), inspector["created_at"], inspector["_seq"])
        if best_key is None or key < best_key:
            best_key = key
            best = inspector
    return best
