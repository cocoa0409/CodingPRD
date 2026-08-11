"""Provisional quote pricing: travel fee, per-line rounding, discount/surcharge
order, guest tiers, deposit rounding, handwash/staffing derivations (PRD §3.4).

Covers Difficulty queue rule combinatorial_formula and the corner calculations
section, all of which exercise the pinned eight-step pricing evaluation.
"""
from test_helpers import (
    validate_success, get_success_data,
    fixtures as fx,
)
from test_helpers.test_users import make_customer_headers


# =====================================================================
# Difficulty/combinatorial_formula/travel_fee_multi_input_nonlinear
# =====================================================================
def _setup_seven_chicken_booking():
    """ZONE_B 60mi PAVEMENT venue with seven PROPOSED chickens (3000c each)."""
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(
        customer["id"], name="Lot 7", address="7 Asphalt Way",
        surface_type="PAVEMENT", travel_zone="ZONE_B", distance_miles=60,
        max_guest_capacity=200, requires_handwash_stations=False,
    )
    chickens = [
        fx.create_certified_animal(f"Chk{i}", "CHICKEN", "SMALL", 2, 3000)
        for i in range(1, 8)
    ]
    booking = fx.create_booking(
        customer["id"], venue["id"],
        start_time="2026-06-10T10:00:00Z", end_time="2026-06-10T12:00:00Z",
        guest_count=20, child_guest_count=0, planned_handwash_stations=0,
    )
    for chicken in chickens:
        fx.attach_animal(booking["id"], chicken["id"])
    return booking


def test_travel_fee_combines_zone_overage_trailers_and_pavement(api):
    """PRD §3.4: "`ZONE_B` is 9000 cents with 50 miles included" and "each overage
    mile costs 85 cents" and "Trailer count is the in-scope animal count divided
    by 6, rounded up, with a minimum of one trailer, and each trailer adds 3000
    cents" and "when the venue's `surface_type` is `PAVEMENT`, the raw fee is
    multiplied by 1.25 and rounded half up — the only rounding point in this
    calculation — and on any other surface the raw fee stands as-is."

    Design: Difficulty/combinatorial_formula/travel_fee_multi_input_nonlinear
    """
    booking = _setup_seven_chicken_booking()
    data = validate_success(api.quote_booking(booking["id"], fx.COORD))

    # raw = 9000 + (60-50)*85 + ceil(7/6)*3000 = 15850; x1.25 = 19812.5 -> 19813
    assert data["travel_fee_cents"] == 19813, data["travel_fee_cents"]
    # 7 x 3000, weekday (2026-06-10 is a Wednesday): no weekend multiplier
    assert data["animal_subtotal_cents"] == 21000, data["animal_subtotal_cents"]


def test_travel_fee_feeds_surcharge_and_total(api):
    """PRD §3.4: "`surcharge_cents` is 3 percent of the subtotal minus the discount,
    rounded half up — computed second, from the discounted amount."
    PRD §3.4: "`quoted_total_cents` is the subtotal minus the discount plus the
    surcharge plus the travel fee plus the guest surcharge."

    Design: Difficulty/combinatorial_formula/travel_fee_multi_input_nonlinear
    """
    booking = _setup_seven_chicken_booking()
    data = validate_success(api.quote_booking(booking["id"], fx.COORD))

    assert data["surcharge_cents"] == 630, data["surcharge_cents"]  # 0.03 * 21000
    assert data["guest_surcharge_cents"] == 0, data["guest_surcharge_cents"]  # 20 guests
    assert data["quoted_total_cents"] == 41443, data["quoted_total_cents"]


# =====================================================================
# Difficulty/combinatorial_formula/invoice_per_line_rounding_order
# =====================================================================
def _setup_three_rabbit_saturday_booking():
    """Three rabbits at 3343c each, PROPOSED on a Saturday booking."""
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(customer["id"], distance_miles=5)
    rabbits = [
        fx.create_certified_animal(f"Bun{i}", "RABBIT", "SMALL", 2, 3343)
        for i in range(1, 4)
    ]
    booking = fx.create_booking(
        customer["id"], venue["id"],
        start_time="2026-06-06T10:00:00Z", end_time="2026-06-06T12:00:00Z",
        guest_count=10, child_guest_count=0, planned_handwash_stations=1,
    )
    for rabbit in rabbits:
        fx.attach_animal(booking["id"], rabbit["id"])
    return booking


def test_animal_lines_round_per_line_then_sum(api):
    """PRD §3.4: "For example, three animals at 3343 cents each on a weekend
    produce three lines of 3844 cents each (3343 times 1.15 is 3844.45, which
    rounds half up to 3844) for a subtotal of 11532, whereas summing first would
    give 10029 times 1.15, which rounds to 11533 — a different, forbidden answer."

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order
    """
    booking = _setup_three_rabbit_saturday_booking()
    data = validate_success(api.quote_booking(booking["id"], fx.COORD))

    # 2026-06-06 is a Saturday: per-line round_half_up(3343 * 1.15) = 3844
    assert data["animal_subtotal_cents"] == 11532, data["animal_subtotal_cents"]
    assert data["animal_subtotal_cents"] != 11533  # forbidden sum-then-round answer


def test_per_line_rounding_feeds_surcharge_and_total(api):
    """PRD §3.4: "`surcharge_cents` is 3 percent of the subtotal minus the discount,
    rounded half up — computed second, from the discounted amount."
    PRD §3.4: "`quoted_total_cents` is the subtotal minus the discount plus the
    surcharge plus the travel fee plus the guest surcharge."

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order
    """
    booking = _setup_three_rabbit_saturday_booking()
    data = validate_success(api.quote_booking(booking["id"], fx.COORD))

    assert data["surcharge_cents"] == 346, data["surcharge_cents"]  # 0.03 * 11532
    assert data["travel_fee_cents"] == 8000, data["travel_fee_cents"]  # A/5mi/1 trailer
    assert data["guest_surcharge_cents"] == 0, data["guest_surcharge_cents"]
    assert data["quoted_total_cents"] == 19878, data["quoted_total_cents"]


# =====================================================================
# Difficulty/combinatorial_formula/discount_surcharge_evaluation_order
# =====================================================================
def _setup_school_program_booking():
    """SCHOOL_PROGRAM booking with an APPROVED PONY_RIDE add-on (45min) and two
    PROPOSED animals on a ZONE_C 90mi GRASS venue."""
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer(customer_type="SCHOOL")
    venue = fx.create_venue(
        customer["id"], name="School Field", address="9 Scholar Rd",
        travel_zone="ZONE_C", distance_miles=90, max_guest_capacity=200,
    )
    sheep = fx.create_certified_animal("Shelly", "SHEEP", "MEDIUM", 2, 9000)
    goat = fx.create_certified_animal("Gogo", "GOAT", "SMALL", 3, 8000)
    booking = fx.create_booking(
        customer["id"], venue["id"],
        start_time="2026-06-10T09:00:00Z", end_time="2026-06-10T11:00:00Z",
        guest_count=60, child_guest_count=40, booking_type="SCHOOL_PROGRAM",
        planned_handwash_stations=3,
    )
    addon = fx.create_addon(
        booking["id"], customer["id"], "PONY_RIDE", 45, booking["version"],
    )
    fx.decide_addon(booking["id"], addon["id"], "APPROVED")
    fx.attach_animal(booking["id"], sheep["id"])
    fx.attach_animal(booking["id"], goat["id"])
    return booking


def test_discount_computed_first_on_raw_subtotal(api):
    """PRD §3.4: "For `SCHOOL_PROGRAM` and `LIBRARY_PROGRAM` bookings,
    `discount_cents` is 15 percent of the subtotal, rounded half up; for
    `PRIVATE_PARTY` it is 0. The discount is computed first, from the raw subtotal."
    PRD §3.4: "A `PONY_RIDE` costs a flat 12000 cents when `duration_minutes` is
    at most 60; beyond that it costs 12000 plus 200 cents for each minute past 60."

    Design: Difficulty/combinatorial_formula/discount_surcharge_evaluation_order
    """
    booking = _setup_school_program_booking()
    data = validate_success(api.quote_booking(booking["id"], fx.COORD))

    assert data["addon_subtotal_cents"] == 12000, data["addon_subtotal_cents"]
    # subtotal = 17000 animals (weekday) + 12000 addon = 29000
    assert data["discount_cents"] == 4350, data["discount_cents"]  # 0.15 * 29000


def test_surcharge_computed_second_on_discounted_subtotal(api):
    """PRD §3.4: "On a subtotal of 29000 the pinned order yields a discount of
    4350 and a surcharge of 740; the reversed order would yield 870 and 4481 and
    a different final total."
    PRD §3.4: "`quoted_total_cents` is the subtotal minus the discount plus the
    surcharge plus the travel fee plus the guest surcharge."

    Design: Difficulty/combinatorial_formula/discount_surcharge_evaluation_order
    """
    booking = _setup_school_program_booking()
    data = validate_success(api.quote_booking(booking["id"], fx.COORD))

    assert data["surcharge_cents"] == 740, data["surcharge_cents"]  # 0.03 * 24650
    assert data["travel_fee_cents"] == 17000, data["travel_fee_cents"]  # C/90mi/1 trailer
    assert data["guest_surcharge_cents"] == 3500, data["guest_surcharge_cents"]  # 60 guests
    # 29000 - 4350 + 740 + 17000 + 3500 — the pinned order, not the reversed one
    assert data["quoted_total_cents"] == 45890, data["quoted_total_cents"]


# =====================================================================
# Corner/calculations/guest_surcharge_tier_boundary_50_vs_51
# =====================================================================
def test_guest_tier_boundary_50_stays_in_1500_tier(api):
    """PRD §3.4: "`guest_surcharge_cents` tiers on the in-scope guest count: 20
    guests or fewer pay nothing; 21 through 50 pay 1500 cents; 51 through 100 pay
    3500 cents; more than 100 pay 6000 cents. Tier boundaries are inclusive at the
    lower edge — 21 guests belongs to the 1500-cent tier."

    Design: Corner/calculations/guest_surcharge_tier_boundary_50_vs_51
    """
    ctx = fx.setup_draft_booking(
        guest_count=50, planned_handwash_stations=3,
        start_time="2026-06-17T14:00:00Z", end_time="2026-06-17T16:00:00Z",
    )
    goat = fx.create_certified_animal("Gogo", "GOAT", "SMALL", 3, 8000)
    fx.attach_animal(ctx["booking"]["id"], goat["id"])
    data = validate_success(api.quote_booking(ctx["booking"]["id"], fx.COORD))

    # 50 guests: upper edge of the 21..50 tier
    assert data["guest_surcharge_cents"] == 1500, data["guest_surcharge_cents"]
    # 8000 + 240 surcharge + 8000 travel + 1500
    assert data["quoted_total_cents"] == 17740, data["quoted_total_cents"]


def test_guest_tier_boundary_51_enters_3500_tier(api):
    """PRD §3.4: "`guest_surcharge_cents` tiers on the in-scope guest count: 20
    guests or fewer pay nothing; 21 through 50 pay 1500 cents; 51 through 100 pay
    3500 cents; more than 100 pay 6000 cents. Tier boundaries are inclusive at the
    lower edge — 21 guests belongs to the 1500-cent tier."

    Design: Corner/calculations/guest_surcharge_tier_boundary_50_vs_51
    """
    ctx = fx.setup_draft_booking(
        guest_count=51, planned_handwash_stations=3,
        start_time="2026-06-18T14:00:00Z", end_time="2026-06-18T16:00:00Z",
    )
    goat = fx.create_certified_animal("Gogo", "GOAT", "SMALL", 3, 8000)
    fx.attach_animal(ctx["booking"]["id"], goat["id"])
    data = validate_success(api.quote_booking(ctx["booking"]["id"], fx.COORD))

    # 51 guests: lower edge of the 51..100 tier
    assert data["guest_surcharge_cents"] == 3500, data["guest_surcharge_cents"]
    # 8000 + 240 surcharge + 8000 travel + 3500
    assert data["quoted_total_cents"] == 19740, data["quoted_total_cents"]


# =====================================================================
# Corner/calculations/deposit_rounds_half_up
# =====================================================================
def test_deposit_half_cent_rounds_up(api):
    """PRD §3.4: "`deposit_amount_cents` is 30 percent of `quoted_total_cents`,
    rounded half up — a quoted total of 34375 cents yields a deposit of 10313
    cents, because half-cent cases round up."

    Design: Corner/calculations/deposit_rounds_half_up
    """
    fx.set_clock(fx.DEFAULT_CLOCK)
    customer = fx.create_customer()
    venue = fx.create_venue(customer["id"])
    goat = fx.create_certified_animal("Gogo", "GOAT", "SMALL", 3, 8000)
    sheep = fx.create_certified_animal("Shelly", "SHEEP", "MEDIUM", 2, 9000)
    rabbit = fx.create_certified_animal("Bun", "RABBIT", "SMALL", 3, 4000)
    booking = fx.create_booking(
        customer["id"], venue["id"],
        start_time="2026-06-06T14:00:00Z", end_time="2026-06-06T16:00:00Z",
        guest_count=30, child_guest_count=0, planned_handwash_stations=2,
    )
    for animal in (goat, sheep, rabbit):
        fx.attach_animal(booking["id"], animal["id"])
    data = validate_success(api.quote_booking(booking["id"], fx.COORD))

    # Saturday lines 9200 + 10350 + 4600 = 24150; +725 surcharge +8000 travel +1500
    assert data["quoted_total_cents"] == 34375, data["quoted_total_cents"]
    # 0.30 * 34375 = 10312.5 -> rounds up, never toward zero on the half
    assert data["deposit_amount_cents"] == 10313, data["deposit_amount_cents"]


# =====================================================================
# Corner/calculations/reptile_addon_adds_dedicated_handwash_station
# =====================================================================
def test_reptile_show_adds_one_required_handwash_station(api):
    """PRD §3.4: "`required_handwash_stations` is zero when the venue's
    `requires_handwash_stations` flag is false, and otherwise the guest count
    divided by 20 rounded up — exactly divisible counts need exactly that many
    stations, so 40 guests require 2 stations and 41 require 3 — plus one
    additional station whenever any in-scope add-on is a `REPTILE_SHOW`."
    PRD §3.4: "A `REPTILE_SHOW` costs a flat 15000 cents when `duration_minutes`
    is at most 45; beyond that it costs 15000 plus 250 cents for each minute
    past 45."

    Design: Corner/calculations/reptile_addon_adds_dedicated_handwash_station
    """
    ctx = fx.setup_draft_booking(
        guest_count=40, child_guest_count=0, planned_handwash_stations=3,
    )
    addon = fx.create_addon(
        ctx["booking"]["id"], ctx["customer"]["id"], "REPTILE_SHOW", 30,
        ctx["booking"]["version"],
    )
    rex = fx.create_handler("Rex", ["REPTILE_CERTIFIED"])
    fx.assign_handler(ctx["booking"]["id"], rex["id"], "LEAD")
    fx.decide_addon(ctx["booking"]["id"], addon["id"], "APPROVED")

    data = validate_success(api.quote_booking(ctx["booking"]["id"], fx.COORD))

    # ceil(40/20) = 2 base + 1 reptile station
    assert data["required_handwash_stations"] == 3, data["required_handwash_stations"]
    # REPTILE_SHOW 30min <= 45min flat rate
    assert data["addon_subtotal_cents"] == 15000, data["addon_subtotal_cents"]


# =====================================================================
# Corner/cross_cutting_layers/quote_reconcile_after_addon_approval
# =====================================================================
def test_requote_reconciles_after_addon_approval(api):
    """PRD §3.4: "Quoting is allowed from `DRAFT` (moving the booking to `QUOTED`)
    and from `QUOTED` itself (a re-quote with identical recomputation), and it
    stamps every computed quote field on the booking"
    PRD §3.4: "Approval moves the request to `APPROVED` and clears the booking's
    `quote_fresh`."

    Design: Corner/cross_cutting_layers/quote_reconcile_after_addon_approval
    """
    ctx = fx.setup_quoted_goat_booking()
    booking_id = ctx["booking"]["id"]
    assert ctx["quote"]["quoted_total_cents"] == 16240, ctx["quote"]["quoted_total_cents"]

    addon = fx.create_addon(
        booking_id, ctx["customer"]["id"], "PONY_RIDE", 30,
        ctx["quote"]["version"],
    )
    fx.decide_addon(booking_id, addon["id"], "APPROVED")

    data = validate_success(api.quote_booking(booking_id, fx.COORD))

    # animal 8000 + addon 12000 = 20000 subtotal; surcharge 600; travel 8000;
    # guest tier 0 (20 guests) -> 28600
    assert data["quoted_total_cents"] == 28600, data["quoted_total_cents"]
    assert data["quote_fresh"] is True


# =====================================================================
# Corner/entities/booking_create_computed_field_input_ignored
# =====================================================================
def test_booking_create_ignores_client_supplied_quote_fields(api):
    """PRD §3.4: "it stamps every computed quote field on the booking:
    `animal_subtotal_cents`, `addon_subtotal_cents`, `discount_cents`,
    `surcharge_cents`, `travel_fee_cents`, `guest_surcharge_cents`,
    `quoted_total_cents`, `deposit_amount_cents`, `required_handwash_stations`,
    `required_staff_count`, and `compliance_screening_score`."

    Design: Corner/entities/booking_create_computed_field_input_ignored
    """
    ctx = fx.setup_draft_booking(guest_count=10)
    payload = {
        "venue_id": ctx["venue"]["id"],
        "start_time": "2026-06-17T14:00:00Z",
        "end_time": "2026-06-17T16:00:00Z",
        "guest_count": 10,
        "child_guest_count": 0,
        "booking_type": "PRIVATE_PARTY",
        "planned_handwash_stations": 1,
        "quoted_total_cents": 999999,  # computed field: must not be honored
    }
    created = validate_success(
        api.create_booking(payload, make_customer_headers(ctx["customer"]["id"])),
        expected_status=201,
    )
    assert created["status"] == "DRAFT", created["status"]
    assert created.get("quoted_total_cents") != 999999, created

    # The quote stamps the computed value, proving the client input never persisted:
    # no animals -> subtotal 0, travel = 5000 base + 1 minimum trailer 3000 = 8000.
    quoted = validate_success(api.quote_booking(created["id"], fx.COORD))
    assert quoted["quoted_total_cents"] == 8000, quoted["quoted_total_cents"]
