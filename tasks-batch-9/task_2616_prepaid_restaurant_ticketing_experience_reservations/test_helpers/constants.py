"""
Domain constants and pure arithmetic helpers for the Prepaid Restaurant
Ticketing API.

Every literal in this module is transcribed from the PRD:

* the day-of-week and demand-tier basis-point matrices and the clamp bounds
  of the five-step per-cover pricing derivation,
* the two forfeiture ladders and the rebooking-fee bands of the settlement
  procedure,
* the waitlist priority-score weights,
* the dietary severity prep minutes,
* the documented defaults of every optional creation field.

The helper functions implement the PRD's rounding discipline: "Applying a
basis-point figure to a cent amount means multiplying the amount by the
basis-point figure, dividing by 10000, and rounding the result half up to a
whole cent".
"""

# ─── Roles ────────────────────────────────────────────────────────────────

ROLE_GUEST = "Guest"
ROLE_RESTAURANT_MANAGER = "RestaurantManager"
ROLE_KITCHEN_LEAD = "KitchenLead"
ROLE_GUEST_SERVICES = "GuestServices"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    ROLE_GUEST,
    ROLE_RESTAURANT_MANAGER,
    ROLE_KITCHEN_LEAD,
    ROLE_GUEST_SERVICES,
    ROLE_PLATFORM_ADMIN,
]

# ─── Logical clock ────────────────────────────────────────────────────────

# "Before any request sets it, the logical clock reads exactly
#  2026-08-01T00:00:00Z".
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ─── Pricing: step one factors ────────────────────────────────────────────

DOW_BP = {
    "MON": 9500,
    "TUE": 9500,
    "WED": 9500,
    "THU": 10000,
    "FRI": 11500,
    "SAT": 12500,
    "SUN": 11000,
}

TIER_BP = {
    "LOW": 9000,
    "STANDARD": 10000,
    "HIGH": 12000,
    "PEAK": 14500,
}

# ─── Pricing: step two clamp (floor first, cap second) ────────────────────

PRICE_FLOOR_BP = 8500
PRICE_CAP_BP = 18000

# ─── Pricing: step four scarcity ladder ───────────────────────────────────

SCARCITY_HIGH_THRESHOLD_BP = 8000
SCARCITY_HIGH_STEP_BP = 1500
SCARCITY_MID_THRESHOLD_BP = 5000
SCARCITY_MID_STEP_BP = 800

# ─── Settlement: forfeiture ladders ───────────────────────────────────────

# Each ladder is "a list of rows tried top to bottom, and the first row whose
# minimum-hours threshold is met by an at-or-above comparison wins".
FORFEITURE_LADDERS = {
    "STANDARD": [(72, 0), (24, 5000), (0, 10000)],
    "STRICT": [(168, 0), (72, 5000), (24, 8000), (0, 10000)],
}

# ─── Settlement: rebooking-fee bands, keyed on the raw forfeiture ─────────

REBOOK_FEE_BANDS = [(0, 0), (9999, 500), (39999, 1500), (None, 3000)]

# ─── Waitlist priority score weights ──────────────────────────────────────

PRIORITY_BASE_SCORE = 1000
PRIORITY_PARTY_WEIGHT = 50
PRIORITY_LOYALTY_WEIGHT = 25
PRIORITY_LOYALTY_CAP = 8
PRIORITY_STRIKE_PENALTY = 300
PRIORITY_SCRUTINY_PENALTY = 200
PRIORITY_ROUND_PENALTY = 100

# ─── Dietary severity prep minutes ────────────────────────────────────────

SEVERITY_PREP_MINUTES = {"INFO": 0, "ALLERGY": 6, "ANAPHYLAXIS": 15}

# ─── Enumerations ─────────────────────────────────────────────────────────

PREPAYMENT_MODES = ["DEPOSIT", "FULL"]
FORFEITURE_SCHEDULE_CODES = ["STANDARD", "STRICT"]
FORFEITURE_BASES = ["DEPOSIT_BASIS", "FULL_TICKET_BASIS"]
MEAL_PERIODS = ["LUNCH", "DINNER"]
DEMAND_TIERS = ["LOW", "STANDARD", "HIGH", "PEAK"]
WAITLIST_POLICIES = ["FAIR_QUEUE", "YIELD_WEIGHTED"]
DAYS_OF_WEEK = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

SERVICE_STATUSES = ["DRAFT", "PUBLISHED", "CLOSED", "CANCELLED"]
TICKET_CLASS_STATUSES = ["OPEN", "PAUSED", "SOLD_OUT", "RELEASED", "CLOSED"]
FULFILLMENT_STATUSES = [
    "PENDING",
    "CONFIRMED",
    "SEATED",
    "COMPLETED",
    "CANCELLED",
    "NO_SHOW",
    "TRANSFERRED_OUT",
    "EXPIRED",
]
PAYMENT_STATUSES = [
    "UNPAID",
    "DEPOSIT_PAID",
    "FULLY_PAID",
    "PARTIALLY_REFUNDED",
    "REFUNDED",
    "FORFEITED",
    "TRANSFERRED",
]
WAITLIST_STATUSES = ["WAITING", "OFFERED", "CLAIMED", "EXPIRED", "WITHDRAWN"]
ACK_STATUSES = ["PENDING", "ACKED", "PREP_REJECTED"]
REFUND_EXCEPTION_STATUSES = ["REQUESTED", "APPROVED", "DENIED"]
GOODWILL_STATUSES = ["ISSUED", "PARTIALLY_REDEEMED", "EXHAUSTED", "REVOKED"]

RESTRICTION_CODES = [
    "GLUTEN",
    "DAIRY",
    "SHELLFISH",
    "NUT",
    "SOY",
    "VEGAN",
    "PESCATARIAN",
    "OTHER",
]
SEVERITIES = ["INFO", "ALLERGY", "ANAPHYLAXIS"]
REJECT_REASON_CODES = [
    "CROSS_CONTAMINATION_RISK",
    "INGREDIENT_UNAVAILABLE",
    "DETAIL_INSUFFICIENT",
]
REFUND_REASON_CODES = [
    "MEDICAL",
    "TRAVEL_DISRUPTION",
    "KITCHEN_ERROR",
    "WEATHER",
    "OTHER",
]
DECISION_NOTE_CODES = [
    "POLICY_EXCEPTION",
    "PARTIAL_GOODWILL",
    "EVIDENCE_INSUFFICIENT",
    "OUT_OF_POLICY",
]

LEDGER_KINDS = [
    "DEPOSIT_CHARGE",
    "BALANCE_CHARGE",
    "GOODWILL_REDEMPTION",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "REFUND",
    "FORFEITURE",
    "FORFEITURE_REVERSAL",
]
POSITIVE_LEDGER_KINDS = [
    "DEPOSIT_CHARGE",
    "BALANCE_CHARGE",
    "GOODWILL_REDEMPTION",
    "TRANSFER_IN",
    "FORFEITURE_REVERSAL",
]
NEGATIVE_LEDGER_KINDS = ["TRANSFER_OUT", "REFUND", "FORFEITURE"]
MEMO_CODES = [
    "GUEST_PREPAY",
    "GUEST_BALANCE",
    "CREDIT_APPLIED",
    "TRANSFER_MOVE",
    "GUEST_CANCEL",
    "NO_SHOW",
    "SERVICE_CANCEL",
    "HOLD_LAPSE",
    "REFUND_EXCEPTION",
]

CANCEL_SETTLEMENT_BASES = [
    "DEPOSIT_BASIS",
    "FULL_TICKET_BASIS",
    "RESTAURANT_INITIATED",
    "NO_SHOW_FULL",
]

# ─── Documented defaults ──────────────────────────────────────────────────

RESTAURANT_DEFAULTS = {
    "service_charge_bp": 725,
    "hold_ttl_minutes": 20,
    "offer_ttl_minutes": 15,
    "max_offer_rounds": 2,
    "max_name_changes": 1,
    "name_change_cutoff_minutes": 240,
    "transfer_cutoff_minutes": 1440,
    "max_transfers_per_guest": 2,
    "no_show_grace_minutes": 30,
    "goodwill_credit_cap_cents": 20000,
    "prep_lead_minutes": 45,
    "refund_scrutiny_threshold_cents": 30000,
}

GUEST_DEFAULTS = {
    "is_broker_flagged": False,
    "no_show_strikes": 0,
    "completed_reservations_count": 0,
    "transfers_initiated_count": 0,
    "lifetime_refunded_cents": 0,
    "refund_scrutiny_flag": False,
}

TABLE_DEFAULTS = {"turn_buffer_minutes": 15}

PACKAGE_DEFAULTS = {
    "deposit_bp": 3000,
    "forfeiture_schedule_code": "STANDARD",
    "forfeiture_basis": "DEPOSIT_BASIS",
    "release_discount_bp": 1500,
    "kitchen_prep_minutes_per_cover": 10,
}

ADDON_DEFAULTS = {
    "prep_minutes_per_unit": 0,
    "max_qty_per_cover": 1,
    "order_cutoff_minutes": 1440,
    "requires_kitchen_ack": False,
}

SERVICE_DEFAULTS = {
    "demand_tier": "STANDARD",
    "unsold_release_bp": 5000,
    "release_lead_minutes": 180,
    "waitlist_policy": "FAIR_QUEUE",
    "kitchen_prep_capacity_minutes": 600,
}

SERVICE_ROLLUP_FIELDS = [
    "release_run_count",
    "seats_released_total",
    "last_release_released_count",
    "last_release_promoted_count",
    "covers_confirmed",
    "gross_charged_cents",
    "refunded_cents",
    "forfeited_cents",
    "net_settled_cents",
]

# ─── Pagination ───────────────────────────────────────────────────────────

DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MAX_LIMIT = 100
MIN_LIMIT = 1


# ─── Pure arithmetic helpers ──────────────────────────────────────────────


def apply_bp(amount_cents: int, bp: int) -> int:
    """Apply a basis-point figure to a cent amount, rounding half up.

    "multiplying the amount by the basis-point figure, dividing by 10000, and
    rounding the result half up to a whole cent: a remainder of exactly one
    half cent rounds away from zero, upward".
    """
    product = amount_cents * bp
    if product >= 0:
        return (product + 5000) // 10000
    return -((-product + 5000) // 10000)


def round_half_up_bp(bp_product: int) -> int:
    """Round a basis-point intermediate half up to a whole basis point."""
    return (bp_product + 5000) // 10000


def combined_factor_bp(day_of_week: str, demand_tier: str) -> int:
    """Step one: the day-of-week factor multiplied by the demand-tier factor."""
    return round_half_up_bp(DOW_BP[day_of_week] * TIER_BP[demand_tier])


def clamp_factor_bp(factor_bp: int) -> int:
    """Step two: floor first, cap second."""
    if factor_bp < PRICE_FLOOR_BP:
        factor_bp = PRICE_FLOOR_BP
    if factor_bp > PRICE_CAP_BP:
        factor_bp = PRICE_CAP_BP
    return factor_bp


def scarcity_step_bp(sell_through: int) -> int:
    """Step four's scarcity step, keyed on the class's own sell-through."""
    if sell_through >= SCARCITY_HIGH_THRESHOLD_BP:
        return SCARCITY_HIGH_STEP_BP
    if sell_through >= SCARCITY_MID_THRESHOLD_BP:
        return SCARCITY_MID_STEP_BP
    return 0


def sell_through_bp(seats_sold: int, seats_held: int, seats_allocated: int) -> int:
    """"the floor of ten thousand times the sum of seats_sold and seats_held
    divided by seats_allocated"."""
    return (10000 * (seats_sold + seats_held)) // seats_allocated


def list_price_per_cover(
    base_price_cents: int,
    day_of_week: str,
    demand_tier: str,
    sell_through: int = 0,
) -> int:
    """Steps one through four with ordinary availability as the drawing pool."""
    factor = clamp_factor_bp(combined_factor_bp(day_of_week, demand_tier))
    price = apply_bp(base_price_cents, factor)
    return apply_bp(price, 10000 + scarcity_step_bp(sell_through))


def release_price_per_cover(list_price_cents: int, release_discount_bp: int) -> int:
    """Step five: the discount comes off the scarcity-adjusted figure."""
    return apply_bp(list_price_cents, 10000 - release_discount_bp)


def charge_breakdown(
    price_locked_per_cover_cents: int,
    party_size: int,
    service_charge_bp: int,
    add_on_lines=(),
) -> dict:
    """The charge breakdown with the service charge rounded once per line.

    ``add_on_lines`` is an iterable of ``(unit_price_cents_locked, qty)`` pairs
    in the pinned accumulation order.
    """
    ticket_subtotal = price_locked_per_cover_cents * party_size
    service_charge = apply_bp(ticket_subtotal, service_charge_bp)
    add_on_total = 0
    for unit_price, qty in add_on_lines:
        line_subtotal = unit_price * qty
        add_on_total += line_subtotal
        service_charge += apply_bp(line_subtotal, service_charge_bp)
    grand_total = ticket_subtotal + add_on_total + service_charge
    return {
        "ticket_subtotal_cents": ticket_subtotal,
        "add_on_total_cents": add_on_total,
        "service_charge_cents": service_charge,
        "grand_total_cents": grand_total,
    }


def deposit_due(grand_total_cents: int, prepayment_mode: str, deposit_bp: int) -> int:
    """The amount the guest must put down before the hold can be confirmed."""
    if prepayment_mode == "FULL":
        return grand_total_cents
    return apply_bp(grand_total_cents, deposit_bp)


def forfeiture_band_bp(schedule_code: str, hours_to_service: float) -> int:
    """Step four: the first row whose threshold is met at-or-above wins."""
    for threshold_hours, band_bp in FORFEITURE_LADDERS[schedule_code]:
        if hours_to_service >= threshold_hours:
            return band_bp
    return 10000


def rebook_fee_cents(raw_forfeiture_cents: int) -> int:
    """Step six: the fee band is read off the raw forfeiture of step five."""
    for ceiling, fee in REBOOK_FEE_BANDS:
        if ceiling is None or raw_forfeiture_cents <= ceiling:
            return fee
    return 3000


def settle_cancellation(
    amount_paid_cents: int,
    deposit_due_cents: int,
    grand_total_cents: int,
    schedule_code: str,
    basis_code: str,
    hours_to_service: float,
) -> dict:
    """The full settlement procedure for a guest cancellation."""
    band = forfeiture_band_bp(schedule_code, hours_to_service)
    basis = (
        deposit_due_cents if basis_code == "DEPOSIT_BASIS" else grand_total_cents
    )
    raw = apply_bp(basis, band)
    fee = rebook_fee_cents(raw)
    retained = min(amount_paid_cents, raw + fee)
    return {
        "band_bp": band,
        "raw_forfeiture_cents": raw,
        "rebook_fee_cents": fee,
        "forfeited_cents": retained,
        "refunded_cents": amount_paid_cents - retained,
    }


def priority_score(
    party_size: int,
    completed_reservations_count: int = 0,
    no_show_strikes: int = 0,
    priority_penalty_applied: bool = False,
    offer_round: int = 0,
) -> int:
    """The waitlist ranking key, floored at 0."""
    score = PRIORITY_BASE_SCORE
    score += PRIORITY_PARTY_WEIGHT * party_size
    score += PRIORITY_LOYALTY_WEIGHT * min(
        completed_reservations_count, PRIORITY_LOYALTY_CAP
    )
    score -= PRIORITY_STRIKE_PENALTY * no_show_strikes
    if priority_penalty_applied:
        score -= PRIORITY_SCRUTINY_PENALTY
    score -= PRIORITY_ROUND_PENALTY * offer_round
    return max(0, score)


def prep_minutes_total(
    party_size: int,
    kitchen_prep_minutes_per_cover: int,
    severities=(),
    add_on_lines=(),
) -> int:
    """Baseline covers plus every note's severity minutes plus add-on minutes."""
    total = party_size * kitchen_prep_minutes_per_cover
    for severity in severities:
        total += SEVERITY_PREP_MINUTES[severity]
    for prep_minutes_per_unit, qty in add_on_lines:
        total += prep_minutes_per_unit * qty
    return total


def release_seat_count(seats_available: int, unsold_release_bp: int) -> int:
    """"the floor of that class's seats_available multiplied by the service's
    unsold_release_bp, divided by 10000 — a partial seat is never released"."""
    return (seats_available * unsold_release_bp) // 10000
