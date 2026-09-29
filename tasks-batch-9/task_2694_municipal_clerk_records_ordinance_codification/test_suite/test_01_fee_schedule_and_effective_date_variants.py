"""Two calculations that each exist in two variants: the records-request fee
schedule, and the basis an instrument's effective date is drawn from.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import CITY_CLERK

# The same two responsive-record lines, priced under each variant in turn.
IDENTICAL_LINES = [
    f.fee_line(page_count=30, staff_minutes=20, delivery_medium="PAPER"),
    f.fee_line(page_count=30, staff_minutes=25, delivery_medium="ELECTRONIC"),
]


def test_actual_cost_prices_each_line_on_its_own_quantities():
    """Thirty paper pages then thirty electronic pages, with 20 and 25 staff
    minutes, assess 2125 cents under ACTUAL_COST.

    PRD 3.8: "Under `ACTUAL_COST` each line is priced on its own quantities. A
    free allowance of 20 pages is carried into the first line and consumed line
    by line in the order the lines were supplied: a line's billable pages are
    its `page_count` less whatever allowance remains, floored at zero, and the
    remaining allowance is then reduced by that line's full `page_count`,
    floored at zero."

    Design: Difficulty/dual_variant_calc/records_fee_actual_cost_versus_flat_schedule_diverge_on_identical_lines
    """
    fx.set_clock("2026-08-03T09:00:00Z")
    request = fx.create_records_request(
        requester_name="Ada Vance",
        requester_email="ada@example.org",
        subject_description="Council minutes 2024",
        commercial_purpose=False,
    )

    response = api_client.assess_fee(
        request["id"],
        f.assess_fee_payload(IDENTICAL_LINES, "ACTUAL_COST"),
        CITY_CLERK,
    )
    assessed = validate_success(response, 200)

    a.assert_fields(assessed, fee_schedule_variant="ACTUAL_COST")
    a.assert_cents(assessed, "total_assessed_cents", 2125)
    a.assert_cents(assessed, "fee_balance_cents", 2125)


def test_flat_schedule_pools_the_same_lines_before_pricing_them():
    """The identical two lines assess only 1875 cents under FLAT_SCHEDULE.

    PRD 3.8: "Under `FLAT_SCHEDULE` the quantities are pooled before anything is
    priced. The `page_count` of every line is summed first, the 20-page
    allowance is deducted once from that total with the result floored at zero,
    and the remaining pages are charged at the flat rate of 25 cents per page —
    with **no electronic discount at all**, whatever any line's
    `delivery_medium` says."

    Design: Difficulty/dual_variant_calc/records_fee_actual_cost_versus_flat_schedule_diverge_on_identical_lines
    """
    fx.set_clock("2026-08-03T09:00:00Z")
    request = fx.create_records_request(
        requester_name="Ada Vance",
        requester_email="ada@example.org",
        subject_description="Council minutes 2025",
        commercial_purpose=False,
    )

    response = api_client.assess_fee(
        request["id"],
        f.assess_fee_payload(IDENTICAL_LINES, "FLAT_SCHEDULE"),
        CITY_CLERK,
    )
    assessed = validate_success(response, 200)

    a.assert_fields(assessed, fee_schedule_variant="FLAT_SCHEDULE")
    a.assert_cents(assessed, "total_assessed_cents", 1875)
    a.assert_cents(assessed, "fee_balance_cents", 1875)


def test_the_two_variants_diverge_by_250_cents_on_identical_lines():
    """Assessing both variants in one database pins the divergence at 250 cents
    and leaves the disclosure axis untouched on both requests.

    PRD 3.8: "The chosen variant is recorded on the request, because the two
    schedules produce **different totals from identical lines**: they differ not
    in their rates alone but in *where* the free allowances and the rounding
    land."

    Design: Difficulty/dual_variant_calc/records_fee_actual_cost_versus_flat_schedule_diverge_on_identical_lines
    """
    fx.set_clock("2026-08-03T09:00:00Z")
    actual = fx.create_records_request(
        requester_name="Ada Vance",
        requester_email="ada@example.org",
        subject_description="Council minutes 2024",
        commercial_purpose=False,
    )
    flat = fx.create_records_request(
        requester_name="Ada Vance",
        requester_email="ada@example.org",
        subject_description="Council minutes 2025",
        commercial_purpose=False,
    )

    priced_actual = validate_success(
        api_client.assess_fee(
            actual["id"], f.assess_fee_payload(IDENTICAL_LINES, "ACTUAL_COST"), CITY_CLERK
        )
    )
    priced_flat = validate_success(
        api_client.assess_fee(
            flat["id"], f.assess_fee_payload(IDENTICAL_LINES, "FLAT_SCHEDULE"), CITY_CLERK
        )
    )

    assert (
        priced_actual["total_assessed_cents"] - priced_flat["total_assessed_cents"] == 250
    )
    a.assert_axes(priced_actual, fulfillment_status="RECEIVED", fee_status="ASSESSED")
    a.assert_axes(priced_flat, fulfillment_status="RECEIVED", fee_status="ASSESSED")


def test_a_resolution_takes_its_effective_date_from_the_adoption_date_itself():
    """The resolution adopted on 2026-10-06 is EFFECTIVE that same day, numbered
    RES-2026-001, with no publication of any kind.

    PRD 3.5: "Under `ADOPTION_IMMEDIATE` the `effective_date` is simply the
    `adoption_date`, with no lag and no weekend adjustment of any kind; a
    resolution therefore becomes `EFFECTIVE` in the same cascade that adopts it,
    and an emergency ordinance takes effect the day it was made official."

    Design: Difficulty/dual_variant_calc/effective_date_adoption_immediate_versus_publication_plus_30
    """
    scenario = fx.ordinance_and_resolution_adopted_together()

    resolution = scenario["resolution"]
    a.assert_fields(
        resolution,
        effective_date_basis="ADOPTION_IMMEDIATE",
        effective_date="2026-10-06",
        status="EFFECTIVE",
        assigned_number="RES-2026-001",
    )
    a.assert_nulls(resolution, "publication_completed_on")


def test_a_general_ordinance_takes_publication_plus_thirty_rolled_off_the_weekend():
    """Publication completed on 2026-10-16 puts the general ordinance's effective
    date at 2026-11-16, so the instrument stays PUBLISHED rather than becoming
    effective in the certifying request.

    PRD 3.5: "The other two bases start from a common intermediate: take
    `publication_completed_on`, add 30 days, and then roll the result forward off
    the weekend — if that date falls on a Saturday add 2 days, if it falls on a
    Sunday add 1 day, and otherwise leave it alone."

    Design: Difficulty/dual_variant_calc/effective_date_adoption_immediate_versus_publication_plus_30
    """
    scenario = fx.ordinance_and_resolution_adopted_together()
    fx.ordered_notice(
        scenario["ordinance_notice"]["id"],
        ["2026-10-09", "2026-10-16"],
        column_inches=12.50,
        affidavit_required=True,
    )
    fx.set_clock("2026-10-16T09:00:00Z")

    fx.certify_notice(scenario["ordinance_notice"]["id"], "2026-10-16")

    ordinance = fx.read_instrument(scenario["ordinance"]["id"])
    a.assert_fields(
        ordinance,
        effective_date_basis="PUBLICATION_PLUS_30",
        effective_date="2026-11-16",
        status="PUBLISHED",
        assigned_number="ORD-2026-001",
    )


def test_one_shared_adoption_date_still_yields_two_different_effective_dates():
    """Both instruments carry adoption_date 2026-10-06, yet only the ordinance
    mirrors a publication date and only the resolution is already effective.

    PRD 2.10: "An instrument mirrors `publication_completed_on` from its
    publication notice."

    Design: Difficulty/dual_variant_calc/effective_date_adoption_immediate_versus_publication_plus_30
    """
    scenario = fx.ordinance_and_resolution_adopted_together()
    fx.ordered_notice(
        scenario["ordinance_notice"]["id"],
        ["2026-10-09", "2026-10-16"],
        column_inches=12.50,
        affidavit_required=True,
    )
    fx.set_clock("2026-10-16T09:00:00Z")
    fx.certify_notice(scenario["ordinance_notice"]["id"], "2026-10-16")

    ordinance = fx.read_instrument(scenario["ordinance"]["id"])
    resolution = fx.read_instrument(scenario["resolution"]["id"])

    assert ordinance["adoption_date"] == "2026-10-06"
    assert resolution["adoption_date"] == "2026-10-06"
    assert ordinance["publication_completed_on"] == "2026-10-16"
    a.assert_nulls(resolution, "publication_completed_on")
    assert ordinance["effective_date"] != resolution["effective_date"]
