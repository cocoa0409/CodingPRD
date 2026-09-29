"""Rental arithmetic: the day-tier projection, its mandated rounding order, and the
vendor fee whose percentage is read off the figure it is about to be added to."""
from test_helpers import (
    create_order,
    create_patient,
    create_surface,
    create_unit,
    get_success_data,
    read_unit_version,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_director_headers, make_materials_headers


DIRECTOR = make_director_headers()
MATERIALS = make_materials_headers()

UNKNOWN_SURFACE_ID = "11111111-1111-4111-8111-111111111111"


def _ward_patient_and_surface(api, mrn, asset_tag, daily_rate_cents, **unit_overrides):
    """A funded ward, one admitted patient on it and one available rental asset."""
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        **unit_overrides,
    )
    patient = create_patient(unit, api=api, mrn=mrn, admitted_at="2026-07-31T00:00:00Z")
    surface = create_surface(
        api,
        asset_tag=asset_tag,
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=daily_rate_cents,
        vendor_name="AirBeds Inc",
    )
    return unit, patient, surface


def test_the_projection_rounds_each_day_before_it_adds_them_up(api):
    """A half-cent tier-2 rate makes per-day-then-sum and sum-then-round diverge.

    PRD §3.8: "Each billable day is numbered from 1, and the rate for a day is the
    asset's `daily_rate_cents` at full price for days 1 through 7, at 90 percent of
    it for days 8 through 21, and at 75 percent of it for every day from 22
    onward."
    PRD §3.8: "Each day's charge is rounded half up to whole cents
    **individually**, and the rounded per-day figures are then added together.
    Summing unrounded rates and rounding the total once is forbidden and gives a
    different answer: 14 days at a `daily_rate_cents` of 12345 comes to 164192
    cents when each day is rounded before summing, versus 164189 if the total were
    rounded once."
    PRD §3.8: "The order starts with `fulfillment_status` `REQUESTED` and
    `billing_status` `UNBILLED`, and no money moves at creation — creation is a
    costing exercise, not a ledger event."

    Design: Difficulty/combinatorial_formula/rental_projection_per_day_rounding_then_sum
    """
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    patient = create_patient(
        unit, api=api, mrn="MRN-R1", admitted_at="2026-07-30T00:00:00Z"
    )
    surface = create_surface(
        api,
        asset_tag="BED-001",
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=12345,
        vendor_name="AirBeds Inc",
    )

    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-15T00:00:00Z",
        authorized_days=14,
    )
    assert order["billable_days"] == 14, "336 interval hours divided by 24"
    assert order["projected_cost_cents"] == 164192, (
        "7 days at 12345 is 86415, plus 7 days at round_half_up(11110.5) = 11111, "
        "which is 77777"
    )
    assert order["projected_cost_cents"] != 164189, (
        "164189 is the forbidden sum-then-round answer"
    )
    assert order["vendor_service_fee_cents"] == 8210, (
        "164192 sits in the 5 percent band; round_half_up(8209.6) = 8210"
    )
    assert order["authorized_cost_cents"] == 172402, "164192 plus 8210 by integer addition"
    assert order["fulfillment_status"] == "REQUESTED"
    assert order["billing_status"] == "UNBILLED"

    after_unit = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert after_unit["rental_encumbered_cents"] == 0, "creation is not a ledger event"
    assert after_unit["rental_available_cents"] == 500000


def test_only_the_discounted_days_need_rounding_and_they_are_rounded_singly(api):
    """A tier-1-only rental and a tier-2-crossing rental at the very same rate.

    PRD §3.8: "Second, `projected_cost_cents`, using a tiered per-day rate."
    PRD §3.8: "Each day's charge is rounded half up to whole cents
    **individually**, and the rounded per-day figures are then added together."
    PRD §3.8: "The fee percentage is keyed on the **pre-fee**
    `projected_cost_cents`, never on the post-fee total: the percentage is 8 percent
    when `projected_cost_cents` is below 50000 cents, 5 percent when it is at least
    50000 and below 200000, and 3 percent when it is 200000 or more."

    Design: Difficulty/combinatorial_formula/rental_projection_per_day_rounding_then_sum
    """
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    patient = create_patient(
        unit, api=api, mrn="MRN-R1", admitted_at="2026-07-30T00:00:00Z"
    )
    short_surface = create_surface(
        api,
        asset_tag="BED-001",
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=12345,
        vendor_name="AirBeds Inc",
    )
    long_surface = create_surface(
        api,
        asset_tag="BED-003",
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=12345,
        vendor_name="AirBeds Inc",
    )

    inside_tier_one = create_order(
        unit,
        patient,
        short_surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-08T00:00:00Z",
        authorized_days=7,
    )
    assert inside_tier_one["billable_days"] == 7
    assert inside_tier_one["projected_cost_cents"] == 86415, (
        "seven full-price days at 12345 need no rounding at all"
    )
    assert inside_tier_one["vendor_service_fee_cents"] == 4321, (
        "86415 sits in the 5 percent band; round_half_up(4320.75) = 4321"
    )
    assert inside_tier_one["authorized_cost_cents"] == 90736

    across_the_boundary = create_order(
        unit,
        patient,
        long_surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-22T00:00:00Z",
        authorized_days=21,
    )
    assert across_the_boundary["billable_days"] == 21, "504 interval hours divided by 24"
    assert across_the_boundary["projected_cost_cents"] == 241969, (
        "86415 for days 1 to 7, plus 14 days at round_half_up(11110.5) = 11111, "
        "which is 155554"
    )
    assert across_the_boundary["projected_cost_cents"] != 241962, (
        "241962 is what summing the unrounded 11110.5 rates and rounding once gives"
    )
    assert across_the_boundary["vendor_service_fee_cents"] == 7259, (
        "241969 is at or above 200000, so 3 percent; round_half_up(7259.07) = 7259"
    )
    assert across_the_boundary["authorized_cost_cents"] == 249228
    assert (
        get_success_data(api.get_unit(unit["id"], DIRECTOR))["rental_available_cents"]
        == 500000
    ), "two costed orders and still nothing encumbered"


def test_the_fee_percentage_is_read_off_the_figure_before_the_fee(api):
    """199000 is one thousand cents short of the top tier and must stay there.

    PRD §3.8: "Third, `vendor_service_fee_cents`, which looks circular but is not."
    PRD §3.8: "Worked through: a `projected_cost_cents` of 199000 falls in the
    middle tier at 5 percent, giving a fee of 9950 and an `authorized_cost_cents`
    of 208950. Had the tier been keyed on the 208950 total it would have fallen in
    the 3 percent tier, giving 5970 and 204970 — that reading is wrong."
    PRD §3.8: "`authorized_cost_cents` is then exactly `projected_cost_cents` plus
    `vendor_service_fee_cents`, by integer addition."

    Design: Difficulty/combinatorial_formula/vendor_fee_tier_keyed_on_prefee_projected_cost
    """
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    patient = create_patient(
        unit, api=api, mrn="MRN-R2", admitted_at="2026-07-30T00:00:00Z"
    )
    surface = create_surface(
        api,
        asset_tag="BED-002",
        surface_class="BARIATRIC_BED",
        daily_rate_cents=39800,
        vendor_name="AirBeds Inc",
    )

    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-06T00:00:00Z",
        authorized_days=5,
    )
    assert order["billable_days"] == 5
    assert order["projected_cost_cents"] == 199000, "five full-price days at 39800"
    assert order["vendor_service_fee_cents"] == 9950, (
        "the pre-fee 199000 is below 200000, so the middle band's 5 percent applies"
    )
    assert order["authorized_cost_cents"] == 208950
    assert order["vendor_service_fee_cents"] != 5970, (
        "5970 is 3 percent of the post-fee total, which is the forbidden reading"
    )
    assert order["authorized_cost_cents"] != 204970


def test_the_lower_fee_boundary_is_read_pre_fee_in_the_other_direction(api):
    """At 49000 the post-fee total crosses 50000, and the tier must not follow it.

    PRD §3.8: "The fee percentage is keyed on the **pre-fee**
    `projected_cost_cents`, never on the post-fee total: the percentage is 8 percent
    when `projected_cost_cents` is below 50000 cents, 5 percent when it is at least
    50000 and below 200000, and 3 percent when it is 200000 or more."
    PRD §3.8: "The fee is that percentage of `projected_cost_cents`, rounded half
    up to whole cents."

    Design: Difficulty/combinatorial_formula/vendor_fee_tier_keyed_on_prefee_projected_cost
    """
    unit, patient, surface = _ward_patient_and_surface(
        api,
        mrn="MRN-R3",
        asset_tag="BED-004",
        daily_rate_cents=7000,
        rental_budget_cap_cents=300000,
    )

    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-08T00:00:00Z",
        authorized_days=7,
    )
    assert order["billable_days"] == 7
    assert order["projected_cost_cents"] == 49000, "seven full-price days at 7000"
    assert order["vendor_service_fee_cents"] == 3920, (
        "the pre-fee 49000 is below 50000, so the bottom band's 8 percent applies"
    )
    assert order["authorized_cost_cents"] == 52920
    assert order["vendor_service_fee_cents"] != 2646, (
        "2646 is 5 percent of the post-fee 52920, which the total crossing 50000 "
        "would have invited"
    )
    assert order["authorized_cost_cents"] != 51646
    assert (
        get_success_data(api.get_unit(unit["id"], DIRECTOR))["rental_encumbered_cents"] == 0
    )


def test_a_twenty_five_day_rental_puts_all_three_day_factors_in_play(api):
    """Each factor applies to its own day range and to no other.

    PRD §3.8: "Each billable day is numbered from 1, and the rate for a day is the
    asset's `daily_rate_cents` at full price for days 1 through 7, at 90 percent of
    it for days 8 through 21, and at 75 percent of it for every day from 22
    onward."
    PRD §3.8: "Approval moves `fulfillment_status` `REQUESTED → APPROVED` and, in
    the same breath, `billing_status` `UNBILLED → ENCUMBERED`. The unit's
    `rental_encumbered_cents` rises by the order's `authorized_cost_cents`,
    `rental_available_cents` is recomputed and the unit is versioned."

    Design: Corner/calculations/rental_projection_straddles_all_three_day_tiers
    """
    unit, patient, surface = _ward_patient_and_surface(
        api,
        mrn="MRN-L1",
        asset_tag="BED-100",
        daily_rate_cents=10000,
        rental_budget_cap_cents=500000,
    )
    unit_version = read_unit_version(unit["id"], api=api)

    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-26T00:00:00Z",
        authorized_days=25,
    )
    assert order["billable_days"] == 25, "600 interval hours divided by 24"
    assert order["projected_cost_cents"] == 226000, (
        "7 days at 10000 is 70000, 14 days at 9000 is 126000, 4 days at 7500 is 30000"
    )
    assert order["projected_cost_cents"] != 250000, "250000 would be a flat full-price rate"
    assert order["projected_cost_cents"] != 187500, (
        "187500 would apply the 75 percent factor to all 25 days"
    )
    assert order["vendor_service_fee_cents"] == 6780, (
        "226000 is at or above 200000, so 3 percent"
    )
    assert order["authorized_cost_cents"] == 232780

    approved = validate_success(
        api.approve_support_surface_order(
            order["id"], {"expected_unit_version": unit_version}, MATERIALS
        )
    )
    assert approved["fulfillment_status"] == "APPROVED"
    assert approved["billing_status"] == "ENCUMBERED"
    charged = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert charged["rental_encumbered_cents"] == 232780
    assert charged["rental_available_cents"] == 267220, "500000 cap less 232780"


def test_the_cheapest_of_three_rentals_carries_the_largest_vendor_fee(api):
    """A step function with a strictly-below comparison at the 50000 floor.

    PRD §3.8: "The fee percentage is keyed on the **pre-fee**
    `projected_cost_cents`, never on the post-fee total: the percentage is 8 percent
    when `projected_cost_cents` is below 50000 cents, 5 percent when it is at least
    50000 and below 200000, and 3 percent when it is 200000 or more."
    PRD §3.8: "The fee is that percentage of `projected_cost_cents`, rounded half
    up to whole cents."

    Design: Corner/calculations/vendor_fee_tier_boundary_at_fifty_thousand_exact
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=300000,
    )
    patient = create_patient(
        unit, api=api, mrn="MRN-L2", admitted_at="2026-07-31T00:00:00Z"
    )
    surfaces = [
        create_surface(
            api,
            asset_tag=asset_tag,
            surface_class="FOAM_OVERLAY",
            daily_rate_cents=daily_rate_cents,
            vendor_name="AirBeds Inc",
        )
        for asset_tag, daily_rate_cents in (
            ("BED-101", 7000),
            ("BED-102", 10000),
            ("BED-103", 10001),
        )
    ]

    below = create_order(
        unit,
        patient,
        surfaces[0],
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-08T00:00:00Z",
        authorized_days=7,
    )
    assert below["billable_days"] == 7
    assert below["projected_cost_cents"] == 49000
    assert below["vendor_service_fee_cents"] == 3920, "8 percent, because 49000 is below 50000"
    assert below["authorized_cost_cents"] == 52920

    exactly_on = create_order(
        unit,
        patient,
        surfaces[1],
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-06T00:00:00Z",
        authorized_days=5,
    )
    assert exactly_on["billable_days"] == 5
    assert exactly_on["projected_cost_cents"] == 50000
    assert exactly_on["vendor_service_fee_cents"] == 2500, (
        "5 percent, because the middle band is entered at 50000 and not above it"
    )
    assert exactly_on["authorized_cost_cents"] == 52500

    just_above = create_order(
        unit,
        patient,
        surfaces[2],
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-06T00:00:00Z",
        authorized_days=5,
    )
    assert just_above["projected_cost_cents"] == 50005, "five full-price days at 10001"
    assert just_above["vendor_service_fee_cents"] == 2500, (
        "round_half_up(2500.25) is 2500, so the whole-cent rounding is not a ceiling"
    )
    assert just_above["authorized_cost_cents"] == 52505

    assert below["vendor_service_fee_cents"] > exactly_on["vendor_service_fee_cents"], (
        "the cheaper rental carries the larger fee, which only a step function allows"
    )
    assert below["projected_cost_cents"] < exactly_on["projected_cost_cents"]
    assert (
        just_above["vendor_service_fee_cents"] == exactly_on["vendor_service_fee_cents"]
    ), "two different pre-fee costs, one fee, because the fee is rounded to whole cents"


def test_one_extra_hour_of_occupancy_costs_a_whole_billable_day(api):
    """A 49-hour interval is three billable days, and the authorization must match.

    PRD §3.8: "First, `billable_days`: the whole hours between `rental_start` and
    `rental_end` divided by 24, with any partial day rounded **up**, so a 25-hour
    rental is 2 billable days."
    PRD §2.10 rung 70: "The order's computed `billable_days` does not exceed its
    `authorized_days` — `ERR_RENTAL_DAYS_EXCEED_AUTHORIZATION` (422), on
    `POST /support-surface-orders/{order_id}/approve`."

    Design: Corner/calculations/rental_projection_ceils_partial_final_day
    """
    unit, patient, surface = _ward_patient_and_surface(
        api,
        mrn="MRN-L3",
        asset_tag="BED-104",
        daily_rate_cents=10000,
        rental_budget_cap_cents=100000,
    )
    unit_version = read_unit_version(unit["id"], api=api)

    order = create_order(
        unit,
        patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-03T01:00:00Z",
        authorized_days=3,
    )
    assert order["billable_days"] == 3, (
        "49 hours rounds up to 3; neither floor nor nearest would give 3"
    )
    assert order["projected_cost_cents"] == 30000, "three full-price days at 10000"
    assert order["vendor_service_fee_cents"] == 2400, "8 percent of a pre-fee 30000"
    assert order["authorized_cost_cents"] == 32400
    assert order["projected_cost_cents"] != 20000, (
        "20000 is what a floor-based day count would have charged"
    )

    approved = validate_success(
        api.approve_support_surface_order(
            order["id"], {"expected_unit_version": unit_version}, MATERIALS
        )
    )
    assert approved["fulfillment_status"] == "APPROVED", (
        "3 billable days does not exceed 3 authorized days, so the gate passes at "
        "its exact boundary"
    )
    charged = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert charged["rental_encumbered_cents"] == 32400
    assert charged["rental_available_cents"] == 67600, "100000 cap less 32400"


def test_reading_an_unknown_asset_id_gives_the_asset_specific_not_found(api):
    """A well-formed but unknown UUID earns the per-type 404, not a generic one.

    PRD §2.5: "Each identifier has its own dedicated not-found code, all at HTTP
    404: `ERR_UNIT_NOT_FOUND` for a `unit_id` path segment,
    `ERR_PATIENT_NOT_FOUND` for `patient_id`, `ERR_NURSE_NOT_FOUND` for
    `nurse_id`, `ERR_CONSULT_NOT_FOUND` for `consult_id`,
    `ERR_ASSESSMENT_NOT_FOUND` for `assessment_id`, `ERR_CASE_NOT_FOUND` for
    `case_id`, `ERR_SURVEY_ROUND_NOT_FOUND` for `round_id`,
    `ERR_OBSERVATION_NOT_FOUND` for `observation_id`, `ERR_SURFACE_NOT_FOUND` for
    `surface_id`, `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_PRODUCT_NOT_FOUND`
    for `product_id`, `ERR_PROTOCOL_NOT_FOUND` for `protocol_id` and
    `ERR_PLAN_NOT_FOUND` for `plan_id`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/entities/get_unknown_support_surface_id_returns_surface_not_found
    """
    response = api.get_support_surface(UNKNOWN_SURFACE_ID, MATERIALS)
    validate_error(response, "ERR_SURFACE_NOT_FOUND", expected_status=404)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"], "the envelope carries a non-empty explanation"

    _rows, meta = validate_paginated(api.list_support_surfaces(MATERIALS))
    assert meta["total_count"] == 0, "the failed read created nothing"
