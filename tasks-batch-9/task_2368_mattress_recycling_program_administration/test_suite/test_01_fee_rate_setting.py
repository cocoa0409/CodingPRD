"""Fee-rate recommendation, the reserve-coverage interlock and rate intervals."""

import pytest

from test_helpers import (
    TEST_USERS,
    create_active_rate,
    create_fee_rate_schedule_payload,
    create_program,
    propose_rate,
    read_fee_adequacy,
    read_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN_2 = TEST_USERS["admin_2_headers"]


def texas_program(api):
    """A Texas forecast whose base rate lands exactly on the upper edge of the
    middle surcharge tier."""
    return create_program(
        api,
        state_code="TX",
        program_name="Texas Mattress Recycling Program",
        forecast_annual_cost_cents=78_000_000,
        forecast_annual_units=50_000,
        forecast_other_revenue_cents=0,
        reserve_target_months=3,
        reserve_opening_cents=15_500_000,
    )


def nevada_program(api):
    """A Nevada forecast whose reserve coverage quotient is a shade under three
    months and therefore rounds to exactly 3.00."""
    return create_program(
        api,
        state_code="NV",
        program_name="Nevada Mattress Recycling Program",
        forecast_annual_cost_cents=60_000_000,
        forecast_annual_units=60_000,
        forecast_other_revenue_cents=3_000_000,
        reserve_target_months=3,
        reserve_opening_cents=14_999_999,
    )


def test_surcharge_tier_is_selected_from_the_base_rate_before_the_surcharge(api):
    """PRD §3.1: "Fifth, an administrative surcharge percentage is selected from
    that base rate: six percent when the base rate is 800 cents or less, four
    percent when the base rate is from 801 through 1600 cents, and two percent
    when the base rate is 1601 cents or more. The tier is chosen from the base
    rate and only from the base rate; it is never re-selected after the surcharge
    has been applied."

    Design: Difficulty/combinatorial_formula/fee_recommendation_surcharge_tier_keyed_on_pre_surcharge_base
    """
    program = texas_program(api)

    adequacy = validate_success(api.get_fee_adequacy(program["id"], ADMIN))

    assert adequacy["reserve_target_cents"] == 19_500_000
    assert adequacy["reserve_gap_cents"] == 4_000_000
    assert adequacy["base_rate_cents"] == 1600
    assert adequacy["admin_surcharge_pct"] == pytest.approx(0.04)
    assert adequacy["recommended_rate_cents"] == 1664, (
        "a base rate of exactly 1600 cents sits in the four percent tier; "
        "re-selecting the tier from the surcharged figure would yield 1632"
    )
    assert adequacy["recommended_rate_cents"] != 1632
    assert adequacy["band_low_cents"] == 1331
    assert adequacy["band_high_cents"] == 1997
    assert adequacy["reserve_coverage_months"] == pytest.approx(2.38)
    assert program["recommended_rate_cents"] == 1664


def test_raising_the_unit_forecast_moves_the_base_rate_into_the_two_percent_tier(api):
    """PRD §3.1: "Fifth, an administrative surcharge percentage is selected from
    that base rate: six percent when the base rate is 800 cents or less, four
    percent when the base rate is from 801 through 1600 cents, and two percent
    when the base rate is 1601 cents or more."

    Design: Difficulty/combinatorial_formula/fee_recommendation_surcharge_tier_keyed_on_pre_surcharge_base
    """
    program = texas_program(api)

    revised = validate_success(
        api.update_cost_forecast(
            program["id"], {"forecast_annual_units": 40_000}, ADMIN
        )
    )

    assert revised["recommended_rate_cents"] == 2040
    adequacy = read_fee_adequacy(api, program["id"])
    assert adequacy["base_rate_cents"] == 2000
    assert adequacy["admin_surcharge_pct"] == pytest.approx(0.02)
    assert adequacy["recommended_rate_cents"] == 2040


def test_reserve_coverage_a_shade_under_three_months_rounds_to_three(api):
    """PRD §2.6: "Both are produced by rounding half up to two decimal places, and
    in both cases it is the **rounded** value that a threshold gate compares — not
    the unrounded quotient. A coverage figure whose exact quotient is a shade
    under three months but which rounds to `3.00` is treated as `3.00` by the
    rate-increase gate."

    Design: Difficulty/boundary_precision_check/reserve_coverage_rounds_to_three_months_blocks_rate_increase
    """
    program = nevada_program(api)

    assert program["reserve_coverage_months"] == pytest.approx(3.00)
    adequacy = read_fee_adequacy(api, program["id"])
    assert adequacy["reserve_coverage_months"] == pytest.approx(3.00)
    assert adequacy["reserve_balance_cents"] == 14_999_999
    assert adequacy["recommended_rate_cents"] == 989
    assert adequacy["band_low_cents"] == 791
    assert adequacy["band_high_cents"] == 1187


def test_rate_increase_is_refused_at_exactly_three_months_of_coverage(api):
    """PRD §3.2: "A program sitting at exactly `3.00` months of coverage is
    already well enough funded that a rate increase is refused with
    `ERR_RESERVE_ABOVE_INCREASE_CEILING`; the comparison is strict, not inclusive,
    and it compares the two-decimal rounded coverage figure."

    Design: Difficulty/boundary_precision_check/reserve_coverage_rounds_to_three_months_blocks_rate_increase
    """
    program = nevada_program(api)
    create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1000,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    successor = propose_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-09-01T00:00:00Z",
    )

    response = api.approve_fee_rate_schedule(successor["id"], ADMIN_2)

    validate_error(response, "ERR_RESERVE_ABOVE_INCREASE_CEILING", 422)
    stored = validate_success(api.get_fee_rate_schedule(successor["id"], ADMIN))
    assert stored["status"] == "PROPOSED"
    assert stored["approved_by_user_id"] is None


def test_rate_proposal_one_instant_before_the_predecessor_end_overlaps(api):
    """PRD §3.2: "Treating an absent `effective_to` on either side as infinitely
    far in the future, two intervals overlap when the proposal's start is strictly
    earlier than the existing schedule's end and the existing schedule's start is
    strictly earlier than the proposal's end."

    Design: Difficulty/resource_temporal_overlap/fee_rate_interval_abuts_predecessor_end_but_rejects_one_instant_earlier
    """
    program = create_program(api)
    predecessor = create_active_rate(
        api,
        program["id"],
        unit_class="FOUNDATION",
        fee_cents_per_unit=900,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
    )

    response = api.create_fee_rate_schedule(
        create_fee_rate_schedule_payload(
            program["id"],
            read_program(api, program["id"])["version"],
            unit_class="FOUNDATION",
            fee_cents_per_unit=950,
            effective_from="2026-12-31T23:59:59Z",
        ),
        ADMIN,
    )

    validate_error(response, "ERR_RATE_PERIOD_OVERLAP", 409)
    still_active = validate_success(api.get_fee_rate_schedule(predecessor["id"], ADMIN))
    assert still_active["status"] == "ACTIVE"
    assert still_active["effective_to"] == "2027-01-01T00:00:00Z"


def test_rate_proposal_abutting_the_predecessor_end_is_accepted(api):
    """PRD §3.2: "The practical consequence is that a successor is proposed by
    abutting its predecessor: a proposal whose `effective_from` equals the
    predecessor's exclusive `effective_to` is accepted, while one instant earlier
    is not."

    Design: Difficulty/resource_temporal_overlap/fee_rate_interval_abuts_predecessor_end_but_rejects_one_instant_earlier
    """
    program = create_program(api)
    predecessor = create_active_rate(
        api,
        program["id"],
        unit_class="FOUNDATION",
        fee_cents_per_unit=900,
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
    )

    response = api.create_fee_rate_schedule(
        create_fee_rate_schedule_payload(
            program["id"],
            read_program(api, program["id"])["version"],
            unit_class="FOUNDATION",
            fee_cents_per_unit=950,
            effective_from="2027-01-01T00:00:00Z",
        ),
        ADMIN,
    )

    successor = validate_success(response, 201)
    assert successor["status"] == "PROPOSED"
    assert successor["effective_from"] == "2027-01-01T00:00:00Z"
    assert successor["effective_to"] is None
    assert successor["recommended_rate_cents_at_proposal"] == 1075
    assert validate_success(api.get_fee_rate_schedule(predecessor["id"], ADMIN))[
        "status"
    ] == "ACTIVE"
    schedules, meta = validate_paginated(
        api.list_fee_rate_schedules(
            ADMIN,
            params={"state_program_id": program["id"], "unit_class": "FOUNDATION"},
        )
    )
    assert meta["total_count"] == 2
    assert len(schedules) == 2
