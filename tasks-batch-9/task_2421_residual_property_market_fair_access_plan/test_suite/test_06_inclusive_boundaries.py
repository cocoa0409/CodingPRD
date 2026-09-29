"""Thresholds probed one unit either side of the edge that decides the outcome.

Three different metrics are pinned here: a calendar lookback window measured in
whole days, a four-decimal rate ratio, and a whole-cent fiscal amount. In each
case the value exactly on the edge is admissible and the value one unit past it
is not.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_client import FairPlanApiClient
from test_helpers.api_errors import (
    ERR_LOSSES_WITHIN_RESERVES,
    ERR_RATE_BELOW_VOLUNTARY_FLOOR,
)
from test_helpers.assertions import (
    assert_cents,
    assert_field_equals,
    assert_field_null,
    assert_instant_equals,
    assert_ratio,
    find_one,
)
from test_helpers.constants import (
    APP_STATUS_ELIGIBILITY_HELD,
    APP_STATUS_SUBMITTED,
    BASIS_MARKET_SHARE,
    CLOCK_BASE,
    EVENT_STATUS_ALLOCATED,
    EVENT_STATUS_DRAFT,
    FILING_STATUS_FILED,
    HOLD_REASON_INSUFFICIENT_DECLINATIONS,
)
from test_helpers.fixtures import (
    ApplicationChain,
    Foundations,
    add_declination,
    allocate_event,
    create_draft_application,
    create_event,
    create_member_insurers,
    create_zone,
    file_rate,
    pin_clock,
    read_allocations,
    read_event,
    read_filing,
    read_zone,
    submit,
)
from test_helpers.test_users import admin_headers, rate_analyst_headers

WINDOW_START_DATE = "2026-07-03"
ONE_DAY_BEFORE_WINDOW = "2026-07-02"
QUOTED_ANNUAL_PREMIUM_CENTS = 546_750
AT_FLOOR_RATE = 880
BELOW_FLOOR_RATE = 879
SURVEYED_RATE = 800


def _application_declined_on(
    foundations: Foundations, label: str, last_declination_date: str
) -> ApplicationChain:
    """A draft application with three carrier declinations, the last one dated."""
    chain = create_draft_application(
        foundations.client,
        foundations,
        applicant_overrides={
            "full_name": f"Owner {label}",
            "email": f"owner{label}@example.com",
        },
        property_overrides={"address_line": f"{label} Shore Rd"},
    )
    member_ids = foundations.member_ids
    add_declination(
        chain, member_ids[0], declined_on=WINDOW_START_DATE, evidence_reference="DEC-1"
    )
    add_declination(
        chain, member_ids[1], declined_on=WINDOW_START_DATE, evidence_reference="DEC-2"
    )
    add_declination(
        chain,
        member_ids[2],
        declined_on=last_declination_date,
        evidence_reference="DEC-3",
    )
    return chain


def _zone_with_a_filing_at_the_floor(client: FairPlanApiClient) -> tuple:
    """A bare territory carrying exactly one filing whose differential is 0.1000."""
    pin_clock(client)
    zone = create_zone(client)
    filing = file_rate(
        client,
        zone["id"],
        filed_rate_per_1000_cents=AT_FLOOR_RATE,
        voluntary_market_avg_rate_per_1000_cents=SURVEYED_RATE,
    )
    return zone, filing


def _two_events_astride_the_reserve_balance(client: FairPlanApiClient) -> tuple:
    """One loss exactly equal to reserves, one loss a single cent above them."""
    pin_clock(client)
    members = create_member_insurers(client)
    zone = create_zone(client)
    at_reserves = create_event(
        client, zone["id"], 50_000_000, 50_000_000, BASIS_MARKET_SHARE
    )
    one_cent_over = create_event(
        client, zone["id"], 50_000_001, 50_000_000, BASIS_MARKET_SHARE
    )
    return members, at_reserves, one_cent_over


# ---------------------------------------------------------------------------
# The sixty-day declination window, inclusive at its opening day
# ---------------------------------------------------------------------------


def test_declination_dated_exactly_sixty_days_back_still_counts(
    roomy_foundations: Foundations,
) -> None:
    """Three declinations on the window's opening day carry the submission.

    PRD: "The window opens sixty days before that anchor date and closes on the anchor date itself, and **both** bounds are inclusive."

    PRD: "A declination qualifies when it belongs to this application, when its `verified` flag is true, and when the calendar date in its `declined_on` falls inside that inclusive sixty-day window."

    Design: Difficulty/boundary_precision_check/declination_lookback_window_start_is_inclusive_at_sixty_days
    """
    chain = _application_declined_on(roomy_foundations, "1", WINDOW_START_DATE)

    application = submit(chain)

    assert_field_equals(application, "declination_count", 3)
    assert_field_equals(application, "status", APP_STATUS_SUBMITTED)
    assert_field_null(application, "eligibility_hold_reason")
    assert_instant_equals(application["submitted_at"], CLOCK_BASE, "submitted_at")
    assert_cents(
        application["quoted_annual_premium_cents"],
        QUOTED_ANNUAL_PREMIUM_CENTS,
        "quoted_annual_premium_cents",
    )


def test_declination_dated_one_day_earlier_holds_the_application(
    roomy_foundations: Foundations,
) -> None:
    """Sliding one declination a single day out of the window drops the count to two.

    PRD: "The routing then forks on the count alone, and **no error is raised on either branch**."

    PRD: "A count below three routes `DRAFT → ELIGIBILITY_HELD` and writes `eligibility_hold_reason` to the literal string `INSUFFICIENT_DECLINATIONS`."

    Design: Difficulty/boundary_precision_check/declination_lookback_window_start_is_inclusive_at_sixty_days
    """
    chain = _application_declined_on(roomy_foundations, "2", ONE_DAY_BEFORE_WINDOW)

    application = submit(chain)

    assert_field_equals(application, "declination_count", 2)
    assert_field_equals(application, "status", APP_STATUS_ELIGIBILITY_HELD)
    assert_field_equals(
        application,
        "eligibility_hold_reason",
        HOLD_REASON_INSUFFICIENT_DECLINATIONS,
    )


# ---------------------------------------------------------------------------
# The four-decimal rate differential floor, admissible at exactly 0.1000
# ---------------------------------------------------------------------------


def test_filing_exactly_one_tenth_above_the_survey_is_admissible(
    client: FairPlanApiClient,
) -> None:
    """880 over 800 rounds to exactly 0.1000, which the floor accepts.

    PRD: "At filing time the server computes `differential_pct`: the filed rate minus the surveyed voluntary average, divided by that same surveyed voluntary average, rounded half up to four decimal places."

    PRD: "A differential of exactly 0.1000 is admissible; anything below it is rejected with `ERR_RATE_BELOW_VOLUNTARY_FLOOR`."

    Design: Difficulty/boundary_precision_check/filing_differential_floor_is_admissible_at_exactly_ten_percent
    """
    _zone, filing = _zone_with_a_filing_at_the_floor(client)

    stored = read_filing(client, filing["id"])
    assert_ratio(stored["differential_pct"], "0.1000", "differential_pct")
    assert_field_equals(stored, "status", FILING_STATUS_FILED)
    assert_field_equals(stored, "filed_by_user_id", "ra-1")


def test_filing_one_cent_below_the_floor_is_rejected(
    client: FairPlanApiClient,
) -> None:
    """879 over 800 rounds to 0.0988, below the inclusive floor, so nothing is filed.

    PRD: "Because the plan is a market of last resort and may not undercut private carriers, this differential must be **at least** 0.1000 — that is, the filed rate must be at least one tenth above the surveyed average."

    PRD: "Threshold comparisons against them are made on the rounded four-decimal value, and every such threshold in this specification is inclusive unless the text says otherwise."

    Design: Difficulty/boundary_precision_check/filing_differential_floor_is_admissible_at_exactly_ten_percent
    """
    zone, _filing = _zone_with_a_filing_at_the_floor(client)
    zone_version = read_zone(client, zone["id"])["version"]

    response = client.create_rate_filing(
        f.rate_filing_payload(
            cat_zone_id=zone["id"],
            expected_zone_version=zone_version,
            filed_rate_per_1000_cents=BELOW_FLOOR_RATE,
            voluntary_market_avg_rate_per_1000_cents=SURVEYED_RATE,
        ),
        rate_analyst_headers(),
    )

    validate_error(response, ERR_RATE_BELOW_VOLUNTARY_FLOOR)
    _filings, meta = validate_paginated(
        client.list_cat_zone_rate_filings(zone["id"], admin_headers(), {"limit": 100})
    )
    assert_field_equals(meta, "total_count", 1)


# ---------------------------------------------------------------------------
# The assessable amount, which must clear zero by at least one cent
# ---------------------------------------------------------------------------


def test_loss_exactly_equal_to_reserves_blocks_the_allocation_run(
    client: FairPlanApiClient,
) -> None:
    """A zero shortfall is not assessable, and the event stays in DRAFT.

    PRD: "Two fiscal gates follow: `assessable_amount_cents` must be **strictly greater than zero**, so a loss exactly equal to the reserve balance yields zero and blocks the run with `ERR_LOSSES_WITHIN_RESERVES`; and the eligible member set must be non-empty with a total basis weight greater than zero, or `ERR_NO_ASSESSABLE_MEMBERS`."

    PRD: "The server immediately writes `assessable_amount_cents` as the trigger loss minus the reserve balance, with a negative result replaced by zero."

    Design: Difficulty/boundary_precision_check/assessable_amount_must_exceed_zero_by_at_least_one_cent
    """
    _members, at_reserves, _over = _two_events_astride_the_reserve_balance(client)
    assert_cents(
        at_reserves["assessable_amount_cents"], 0, "assessable_amount_cents"
    )

    response = client.run_allocation(
        at_reserves["id"],
        f.allocation_run_payload(at_reserves["version"]),
        admin_headers(),
    )

    validate_error(response, ERR_LOSSES_WITHIN_RESERVES)
    unchanged = read_event(client, at_reserves["id"])
    assert_field_equals(unchanged, "status", EVENT_STATUS_DRAFT)
    assert_field_equals(unchanged, "allocation_run_count", 0)
    assert not read_allocations(client, at_reserves["id"]), (
        "a blocked run must create no allocations"
    )


def test_loss_one_cent_above_reserves_allocates_that_single_cent(
    client: FairPlanApiClient,
) -> None:
    """Every rounded share is zero, so the whole cent lands on the greatest weight.

    PRD: "The reconciliation figure, `remainder_cents`, is `assessable_amount_cents` minus the sum of the per-member rounded shares, and it may be negative."

    PRD: "It is absorbed entirely by one member: the eligible member with the greatest weight, with a tie on equal weight broken in favour of the earliest `created_at` among those members."

    Design: Difficulty/boundary_precision_check/assessable_amount_must_exceed_zero_by_at_least_one_cent
    """
    members, _at_reserves, one_cent_over = _two_events_astride_the_reserve_balance(
        client
    )
    assert_cents(
        one_cent_over["assessable_amount_cents"], 1, "assessable_amount_cents"
    )

    allocated = allocate_event(client, one_cent_over)

    assert_field_equals(allocated, "status", EVENT_STATUS_ALLOCATED)
    assert_cents(allocated["allocated_total_cents"], 1, "allocated_total_cents")
    assert_cents(allocated["remainder_cents"], 1, "remainder_cents")

    allocations = read_allocations(client, one_cent_over["id"])
    assert_cents(
        find_one(allocations, "member_insurer_id", members[2]["id"])[
            "gross_share_cents"
        ],
        1,
        "gross_share_cents",
    )
    for index in (0, 1):
        assert_cents(
            find_one(allocations, "member_insurer_id", members[index]["id"])[
                "gross_share_cents"
            ],
            0,
            "gross_share_cents",
        )
