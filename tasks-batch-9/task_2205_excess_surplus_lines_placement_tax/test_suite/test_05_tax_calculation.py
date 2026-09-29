"""Calculating premium tax: the two allocation variants, the normative rounding
order, the stamping-fee cap and the rates pinned onto every row.
"""

import pytest

from test_helpers import (
    ERR_ALLOCATION_STATE_PROGRAM_MISSING,
    STATE_REGULATOR_AZ,
    STATE_REGULATOR_GA,
    TAX_FILER_NINA,
    assert_allocation_row,
    assert_filing_line,
    assert_parts_sum_to,
    assert_policy_dimensions,
    assert_state_codes_ascending,
    by_state,
    exposure,
    state_program_payload,
    validate_success,
    validate_error,
)


def test_california_stamping_fee_is_capped_at_the_program_cap(ca_home_world):
    """The uncapped figure is computed and then the cap wins.

    PRD 3.7: "Otherwise an uncapped figure is computed as the row's
    `allocated_premium_cents` multiplied by its `stamping_fee_rate_applied`,
    rounded half up to whole cents; when the state's `stamping_fee_cap_cents` is
    null the uncapped figure stands, and when a cap is configured the row takes
    the smaller of the uncapped figure and the cap."

    Design: Corner/calculations/california_stamping_fee_is_capped_at_the_program_cap
    """
    world = ca_home_world
    assert world.program("CA")["stamping_fee_cap_cents"] == 50000

    world.issue_policy(
        policy_number="SL-2026-0400",
        original_gross_premium_cents=30_000_000,
        policy_fee_cents=0,
        broker_fee_cents=0,
    )
    policy = world.calculate_tax()

    assert policy["taxable_premium_cents"] == 30_000_000
    assert policy["total_tax_cents"] == 900_000
    # 30,000,000 x 0.0018 would be 54,000; the cap holds it at 50,000.
    assert policy["total_stamping_fee_cents"] == 50000

    rows = world.allocations()
    assert len(rows) == 1
    assert_allocation_row(
        rows[0],
        state_code="CA",
        allocated_premium_cents=30_000_000,
        tax_cents=900_000,
        stamping_fee_cents=50000,
    )


def test_money_rounding_is_round_half_up_at_an_exact_half_cent(configured_world):
    """An exact half cent rounds away from zero, not to even.

    PRD 2.6: "Where a rule requires rounding a non-integer intermediate to cents,
    the method is always **round half up**: round the exact rational value to the
    nearest integer, with ties resolved away from zero."

    Design: Corner/calculations/money_rounding_is_round_half_up_at_an_exact_half_cent
    """
    world = configured_world
    world.add_license(state_code="AZ", license_number="SL-AZ-3003")
    world.create_program(
        state_program_payload(
            state_code="AZ",
            premium_tax_rate=0.05,
            stamping_fee_rate=0.0025,
            stamping_fee_cap_cents=None,
            stamping_office_required=True,
            allocation_method="HOME_STATE_SINGLE",
            diligent_search_min_declinations=0,
            export_list_exempts_search=False,
            filing_frequency="MONTHLY",
            filing_deadline_days=30,
            return_premium_tax_refundable=True,
            return_premium_stamping_refundable=True,
            min_carrier_capital_surplus_cents=0,
            required_notice_codes=[],
        )
    )
    world.create_carrier(naic_number="12345")
    world.review_carrier("APPROVE")
    world.white_list("AZ", regulator=STATE_REGULATOR_AZ)

    placement = world.create_placement(
        insured_name="Sonoran Metalworks LLC",
        principal_place_of_business_state="AZ",
        state_exposures=[exposure("AZ", 100_000_000)],
    )
    world.begin_search(placement)
    world.complete_search(placement)
    world.issue_policy(
        policy_number="SL-2026-0500",
        original_gross_premium_cents=130_010,
        policy_fee_cents=0,
        broker_fee_cents=0,
    )
    policy = world.calculate_tax()

    assert policy["taxable_premium_cents"] == 130_010
    # 130,010 x 0.05 is exactly 6,500.5 cents.
    assert policy["total_tax_cents"] == 6501
    # 130,010 x 0.0025 is 325.025 cents.
    assert policy["total_stamping_fee_cents"] == 325

    rows = world.allocations()
    assert len(rows) == 1
    assert_allocation_row(
        rows[0],
        state_code="AZ",
        allocation_pct=1.0,
        allocated_premium_cents=130_010,
        tax_cents=6501,
        stamping_fee_cents=325,
    )


def test_patching_a_state_program_rate_leaves_already_pinned_allocation_rows_alone(
    calculated_world,
):
    """Configuration drift never reaches backwards into a calculated policy.

    PRD 2.7: "Such an amendment changes only the fields actually supplied,
    increments the program's `version`, and — critically — **has no retroactive
    effect on any allocation row already created.**"

    Design: Corner/endpoints/patching_a_state_program_rate_leaves_already_pinned_allocation_rows_alone
    """
    world = calculated_world
    before = world.get_policy()
    assert before["total_tax_cents"] == 38779

    amended = world.patch_program("TX", {"premium_tax_rate": 0.06})
    assert amended["premium_tax_rate"] == pytest.approx(0.06)

    texas_row = by_state(world.allocations())["TX"]
    assert texas_row["premium_tax_rate_applied"] == pytest.approx(0.0485)
    assert texas_row["tax_cents"] == 16571

    after = world.get_policy()
    assert after["total_tax_cents"] == 38779
    assert after["version"] == before["version"]


def test_the_allocation_read_endpoint_returns_the_stored_derived_rows(policy_world):
    """Rows appear only once the calculation has run, and expose their rates.

    PRD 3.7: "A policy's allocation rows may be listed and narrowed by
    `state_code`; each row exposes the `policy_id` it belongs to alongside the
    rates pinned at calculation time."

    Design: Corner/endpoints/the_allocation_read_endpoint_returns_the_stored_derived_rows
    """
    world = policy_world
    assert world.allocations() == []

    policy = world.calculate_tax()
    rows = world.allocations()
    assert [row["state_code"] for row in rows] == ["CA", "NV", "TX"]
    assert_state_codes_ascending(rows)
    assert all(row["policy_id"] == policy["id"] for row in rows)
    assert all(row["allocation_basis"] == "ALLOCATED_MULTI" for row in rows)

    nevada = world.allocations(params={"state_code": "NV"})
    assert len(nevada) == 1
    assert nevada[0]["state_code"] == "NV"
    assert nevada[0]["premium_tax_rate_applied"] == pytest.approx(0.035)
    assert nevada[0]["stamping_fee_rate_applied"] == pytest.approx(0.004)


def test_an_allocation_state_with_no_registered_program_is_refused(white_listed_world):
    """Every allocated state needs a program, not just the home state.

    PRD 3.7: "Two preconditions apply: the policy's `status` must be `ISSUED`,
    and a state program must exist for the policy's `home_state` and for every
    state the selected variant allocates premium to, else
    `ERR_ALLOCATION_STATE_PROGRAM_MISSING`."

    Design: Corner/errors/an_allocation_state_with_no_registered_program_is_refused
    """
    world = white_listed_world
    placement = world.searched_placement(
        insured_name="Red River Terminals LLC",
        state_exposures=[exposure("TX", 300_000_000), exposure("OK", 100_000_000)],
    )
    assert placement["home_state"] == "TX"
    policy = world.issue_policy(policy_number="SL-2026-0800")

    validate_error(
        world.api.calculate_tax(policy["id"], TAX_FILER_NINA),
        ERR_ALLOCATION_STATE_PROGRAM_MISSING,
        422,
    )

    after = world.get_policy()
    assert_policy_dimensions(after, tax_status="UNCALCULATED")
    assert after["total_tax_cents"] == 0
    assert world.allocations() == []


def test_one_request_returns_every_row_it_touched_already_updated(policy_world):
    """The calculation's own response body is already the settled truth.

    PRD 2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/consistency_model/one_request_returns_every_row_it_touched_already_updated
    """
    world = policy_world
    returned = validate_success(
        world.api.calculate_tax(world.policy["id"], TAX_FILER_NINA), 200
    )
    assert_policy_dimensions(returned, tax_status="CALCULATED")
    assert returned["taxable_premium_cents"] == 1_025_000
    assert returned["total_tax_cents"] == 38779
    assert returned["total_stamping_fee_cents"] == 1127

    fetched = world.get_policy()
    assert fetched["tax_status"] == returned["tax_status"]
    assert fetched["total_tax_cents"] == returned["total_tax_cents"]
    assert fetched["total_stamping_fee_cents"] == returned["total_stamping_fee_cents"]
    assert fetched["version"] == returned["version"]

    rows = world.allocations()
    assert [row["state_code"] for row in rows] == ["CA", "NV", "TX"]

    lines = world.filing_lines(policy_id=returned["id"])
    assert len(lines) == 3
    # PRD 3.7: a line's `period_key` is "formatted according to that state's
    # `filing_frequency` -- `YYYY-MM` for `MONTHLY` and `YYYY-Qn` for
    # `QUARTERLY`". Texas and Nevada file monthly; California files quarterly.
    expected_period_key = {"TX": "2026-08", "NV": "2026-08", "CA": "2026-Q3"}
    state_of_program = {
        world.program_id(code): code for code in expected_period_key
    }
    for line in lines:
        state_code = state_of_program[line["state_program_id"]]
        assert_filing_line(
            line,
            line_type="NEW_BUSINESS",
            status="OPEN",
            period_key=expected_period_key[state_code],
        )


def test_allocated_multi_taxes_each_state_at_its_own_rate(calculated_world):
    """Three states, three different rates, three separately rounded figures.

    PRD 3.7: "Each row is taxed at its **own** state's `premium_tax_rate` and
    subject to its **own** state's `stamping_fee_rate` and
    `stamping_fee_cap_cents`."

    Design: Difficulty/dual_variant_calc/premium_tax_allocated_multi_versus_home_state_single_diverge
    """
    world = calculated_world
    policy = world.get_policy()
    assert policy["allocation_method_applied"] == "ALLOCATED_MULTI"
    assert policy["taxable_premium_cents"] == 1_025_000
    assert policy["total_tax_cents"] == 38779
    assert policy["total_stamping_fee_cents"] == 1127

    rows = by_state(world.allocations())
    assert_allocation_row(
        rows["CA"],
        allocated_premium_cents=341_667,
        allocation_pct=0.3333,
        premium_tax_rate_applied=0.03,
        tax_cents=10250,
        stamping_fee_cents=615,
    )
    assert_allocation_row(
        rows["NV"],
        allocated_premium_cents=341_667,
        premium_tax_rate_applied=0.035,
        tax_cents=11958,
        stamping_fee_cents=0,
    )
    assert_allocation_row(
        rows["TX"],
        allocated_premium_cents=341_666,
        premium_tax_rate_applied=0.0485,
        tax_cents=16571,
        stamping_fee_cents=512,
    )

    lines = world.filing_lines(policy_id=policy["id"])
    assert len(lines) == 3
    assert [line["line_type"] for line in lines] == ["NEW_BUSINESS"] * 3
    assert all(line["status"] == "OPEN" for line in lines)


def test_home_state_single_taxes_the_whole_premium_in_one_state(ca_home_world):
    """The same money under the other variant produces a different total.

    PRD 3.7: "Under `HOME_STATE_SINGLE`, exactly one allocation row is created,
    for the policy's `home_state`, with `allocation_pct` of 1.0000 and
    `allocated_premium_cents` equal to the entire taxable premium — regardless of
    how many states hold exposure on the underlying risk."

    Design: Difficulty/dual_variant_calc/premium_tax_allocated_multi_versus_home_state_single_diverge
    """
    world = ca_home_world
    placement = world.get_placement()
    assert placement["home_state"] == "CA"
    assert placement["total_insured_value_cents"] == 900_000_000

    world.issue_policy(policy_number="SL-2026-0002")
    policy = world.calculate_tax()
    assert policy["allocation_method_applied"] == "HOME_STATE_SINGLE"
    assert policy["taxable_premium_cents"] == 1_025_000
    # The whole base at California's 3%, not spread over three rates.
    assert policy["total_tax_cents"] == 30750
    assert policy["total_stamping_fee_cents"] == 1845
    assert policy["total_tax_cents"] != 38779

    rows = world.allocations()
    assert len(rows) == 1
    assert_allocation_row(
        rows[0],
        state_code="CA",
        allocation_pct=1.0,
        allocated_premium_cents=1_025_000,
        tax_cents=30750,
        stamping_fee_cents=1845,
    )

    lines = world.filing_lines(policy_id=policy["id"])
    assert len(lines) == 1
    assert_filing_line(lines[0], line_type="NEW_BUSINESS", tax_cents=30750)


def _georgia_world(world):
    """A Georgia-homed risk split with Florida, both states taxed at 4.5%."""
    world.add_license(state_code="GA", license_number="SL-GA-3003")
    for state_code in ("GA", "FL"):
        world.create_program(
            state_program_payload(
                state_code=state_code,
                premium_tax_rate=0.045,
                stamping_fee_rate=0.0,
                stamping_fee_cap_cents=None,
                stamping_office_required=False,
                allocation_method="ALLOCATED_MULTI",
                diligent_search_min_declinations=0,
                export_list_exempts_search=False,
                filing_frequency="MONTHLY",
                filing_deadline_days=30,
                return_premium_tax_refundable=True,
                return_premium_stamping_refundable=True,
                min_carrier_capital_surplus_cents=0,
                required_notice_codes=[],
            )
        )
    world.create_carrier(naic_number="12345")
    world.review_carrier("APPROVE")
    world.white_list("GA", regulator=STATE_REGULATOR_GA)

    placement = world.create_placement(
        insured_name="Peachtree Cold Storage LLC",
        principal_place_of_business_state="GA",
        state_exposures=[exposure("GA", 100_000_000), exposure("FL", 300_000_000)],
    )
    world.begin_search(placement)
    world.complete_search(placement)
    world.issue_policy(
        policy_number="SL-2026-0100",
        original_gross_premium_cents=400_000,
        policy_fee_cents=400,
        broker_fee_cents=0,
    )
    return world.calculate_tax()


def test_premium_tax_is_rounded_per_allocation_row_and_only_then_summed(
    configured_world,
):
    """Two rows each rounding a half cent upward outrun a single rounding.

    PRD 2.6: "Wherever an amount is apportioned across states and then taxed, the
    per-state amount is rounded to whole cents first, the per-state tax is then
    computed from that rounded amount and itself rounded to whole cents, and only
    then are the per-state figures summed into a total."

    Design: Difficulty/combinatorial_formula/premium_tax_rounding_is_per_allocation_row_then_summed
    """
    world = configured_world
    policy = _georgia_world(world)

    assert policy["taxable_premium_cents"] == 400_400
    rows = by_state(world.allocations())
    assert_allocation_row(
        rows["FL"], allocated_premium_cents=300_300, allocation_pct=0.75, tax_cents=13514
    )
    assert_allocation_row(
        rows["GA"], allocated_premium_cents=100_100, allocation_pct=0.25, tax_cents=4505
    )
    assert policy["total_tax_cents"] == 18019
    # A single rounding of 400,400 x 0.045 would have produced 18,018.
    assert policy["total_tax_cents"] != 18018
    assert_parts_sum_to(world.allocations(), "allocated_premium_cents", 400_400)


def test_the_per_row_rounding_carries_through_to_the_ledger_and_the_fees(
    configured_world,
):
    """The policy totals and the filing lines agree on the per-row figures.

    PRD 3.7: "The policy's `total_tax_cents` and `total_stamping_fee_cents` are
    the sums of `tax_cents` and `stamping_fee_cents` across the rows — rounded
    per row first, summed second, per §2.6."

    Design: Difficulty/combinatorial_formula/premium_tax_rounding_is_per_allocation_row_then_summed
    """
    world = configured_world
    policy = _georgia_world(world)

    assert policy["total_stamping_fee_cents"] == 0
    assert_policy_dimensions(policy, tax_status="CALCULATED", stamping_status="NOT_REQUIRED")
    assert world.get_placement()["declination_count"] == 0

    lines = world.filing_lines(policy_id=policy["id"])
    assert [line["state_program_id"] for line in lines] == [
        world.program_id("FL"),
        world.program_id("GA"),
    ]
    by_program = {line["state_program_id"]: line for line in lines}
    assert_filing_line(
        by_program[world.program_id("FL")],
        line_type="NEW_BUSINESS",
        taxable_premium_cents=300_300,
        tax_cents=13514,
        stamping_fee_cents=0,
    )
    assert_filing_line(
        by_program[world.program_id("GA")],
        line_type="NEW_BUSINESS",
        taxable_premium_cents=100_100,
        tax_cents=4505,
        stamping_fee_cents=0,
    )
    assert sum(line["tax_cents"] for line in lines) == policy["total_tax_cents"]
