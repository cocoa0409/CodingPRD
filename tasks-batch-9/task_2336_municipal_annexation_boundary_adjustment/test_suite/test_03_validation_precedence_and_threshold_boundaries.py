"""Precedence between competing statutory objections, and the exact edges of the
annexation thresholds.

Two families of behaviour are exercised here. The first asks which objection a
municipal action reports when several are true at once — a vacated hearing that
also lost its notice, an ordinance blocked both by an open objection window and
by an intolerable fiscal deficit, a written protest that is both late and aimed
at another case's parcel. Each pairing is checked twice: once with both faults
live, to see which one the service reports, and once with only the lower-ranked
fault live, to prove that check is genuinely reached rather than missing.

The second family pins the comparison edges themselves: an objection weight
landing exactly on the statutory threshold, a contiguity ratio landing exactly
on the statutory minimum, and a base service cost landing exactly on the
administrative-overhead tier ceiling — each paired with the neighbouring value
one unit away on the failing side.
"""
from datetime import datetime
from decimal import Decimal

from test_helpers import (
    assertions,
    constants,
    factories,
    fixtures,
    get_success_data,
    make_property_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_FISCAL_DEFICIT_EXCEEDS_TOLERANCE,
    ERR_HEARING_NOT_SCHEDULED,
    ERR_NOTICE_NOT_PUBLISHED,
    ERR_PARCEL_CASE_MISMATCH,
    ERR_PROTEST_FILING_OUT_OF_WINDOW,
    ERR_PROTEST_PERIOD_OPEN,
    ERR_TERRITORY_NOT_CONTIGUOUS,
)

# A second council-chamber booking a day after the canonical one, so the
# trailing changeover buffer of the first booking cannot reach it.
SECOND_HEARING_START_AT = "2026-09-16T10:00:00Z"
SECOND_HEARING_END_AT = "2026-09-16T12:00:00Z"

# The instant the cooling-off period between hearing and ordinance elapses for
# the canonical timeline: the hearing is held at 2026-09-15T10:00:00Z and the
# statute's default cooling-off period is ten days.
CLOCK_AT_COOLING_OFF_ELAPSED = "2026-09-25T10:00:00Z"


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating both the trailing Z and the
    three fractional digits the envelope carries."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _expected_gross_revenue_cents(ctx, projected_population):
    """Property tax on the territory plus per-capita state-shared revenue; the
    canonical territory carries no utility accounts, so utility revenue is 0."""
    property_tax = assertions.expected_property_tax_cents(
        ctx["case"]["territory_assessed_value_cents"],
        ctx["municipality"]["general_fund_millage_rate"],
    )
    shared = projected_population * ctx["statute"]["per_capita_shared_revenue_cents"]
    return property_tax + shared


def _expected_deficit_ratio_pct(ctx, projected_population):
    """The whole AVERAGE_COST cost ladder, so the test can state the deficit the
    council is being asked to tolerate."""
    base = assertions.expected_average_cost_base_cents(
        ctx["municipality"]["citywide_annual_service_cost_cents"],
        projected_population,
        ctx["municipality"]["citywide_population"],
    )
    tier = assertions.expected_overhead_tier_pct(base)
    overhead = assertions.cents(Decimal(base) * Decimal(str(tier)))
    gross = _expected_gross_revenue_cents(ctx, projected_population)
    net = gross - (base + overhead)
    return assertions.expected_deficit_ratio_pct(net, gross)


# ==========================================================================
# Holding a hearing: the hearing-state objection outranks the notice objection
# ==========================================================================
def test_holding_a_vacated_hearing_reports_the_hearing_state_error_not_the_missing_notice(api):
    """PRD §3.6: "Four conditions apply, and their order is the order of §2.10:
    the hearing must still be `SCHEDULED` (`ERR_HEARING_NOT_SCHEDULED`), no
    sibling hearing of the same case may already be `HELD`
    (`ERR_HEARING_ALREADY_HELD`), the hearing must have a `notice_published_at`
    that is not null (`ERR_NOTICE_NOT_PUBLISHED`), the logical clock must have
    reached `notice_published_at` advanced by the statute's `notice_min_days`
    days (`ERR_NOTICE_WINDOW_NOT_SATISFIED`), and the clock must have reached
    the hearing's own `scheduled_start_at` (`ERR_HEARING_NOT_STARTED`)."

    Design: Difficulty/priority_pair_validation_conflict/hold_vacated_hearing_state_error_precedes_notice_safety_error
    """
    # Two parcels of unequal value, so withdrawing the larger owner's signature
    # alone drops the petition under the 50.00% signature threshold.
    ctx = fixtures.setup_sufficient_petition(
        api,
        petition_type="OWNER_MAJORITY",
        parcel_values_cents=[60000000, 40000000],
    )
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    vacated_hearing_id = ctx["hearing"]["id"]

    # The withdrawal drops the petition below its threshold, so the supersession
    # cascade vacates the noticed hearing and clears its notice_published_at.
    validate_success(
        api.withdraw_consent(
            fixtures.owner_headers(ctx, 0), ctx["consents"][0]["id"]
        )
    )

    # Cure the petition and notice a fresh hearing, so the case is back in an
    # admissible origin state for holding a hearing while the first hearing
    # stays vacated with no notice of its own.
    fixtures.sign_consent(api, ctx, parcel_index=0)
    validate_success(api.certify_sufficiency(fixtures.clerk(ctx), ctx["petition"]["id"]))
    second_hearing = get_success_data(
        api.create_public_hearing(
            fixtures.clerk(ctx),
            factories.public_hearing_payload(
                ctx["case"]["id"],
                ctx["municipality"]["id"],
                scheduled_start_at=SECOND_HEARING_START_AT,
                scheduled_end_at=SECOND_HEARING_END_AT,
            ),
        ),
        201,
    )
    validate_success(
        api.publish_notice(fixtures.clerk(ctx), second_hearing["id"], "NEWSPAPER"), 201
    )

    # The clock sits on the vacated hearing's own start, so neither temporal
    # rule can pre-empt the pair under test.
    fixtures.set_clock(api, constants.CLOCK_AT_HEARING)

    vacated = fixtures.read_hearing(api, ctx["municipality"]["id"], vacated_hearing_id)
    assert vacated["hearing_status"] == "VACATED"
    assert vacated["notice_published_at"] is None, (
        "the vacated hearing must also violate the notice rule for the pairing to bite"
    )

    validate_error(
        api.hold_hearing(fixtures.clerk(ctx), vacated_hearing_id),
        ERR_HEARING_NOT_SCHEDULED,
    )

    unchanged = fixtures.read_hearing(api, ctx["municipality"]["id"], vacated_hearing_id)
    assert unchanged["hearing_status"] == "VACATED"
    assert unchanged["held_at"] is None
    assert unchanged["notice_published_at"] is None
    case = fixtures.refresh_case(api, ctx)
    assert case["status"] == "HEARING_NOTICED"
    assert case["hearing_held_at"] is None


def test_holding_a_scheduled_hearing_without_notice_reports_the_missing_notice_error(api):
    """PRD §3.6: "Four conditions apply, and their order is the order of §2.10:
    the hearing must still be `SCHEDULED` (`ERR_HEARING_NOT_SCHEDULED`), no
    sibling hearing of the same case may already be `HELD`
    (`ERR_HEARING_ALREADY_HELD`), the hearing must have a `notice_published_at`
    that is not null (`ERR_NOTICE_NOT_PUBLISHED`), the logical clock must have
    reached `notice_published_at` advanced by the statute's `notice_min_days`
    days (`ERR_NOTICE_WINDOW_NOT_SATISFIED`), and the clock must have reached
    the hearing's own `scheduled_start_at` (`ERR_HEARING_NOT_STARTED`)."

    Design: Difficulty/priority_pair_validation_conflict/hold_vacated_hearing_state_error_precedes_notice_safety_error
    """
    ctx = fixtures.setup_certified_case(api)
    fixtures.setup_adopted_plan(api, ctx)
    # The first hearing's notice is what carries the case into HEARING_NOTICED;
    # the second hearing is scheduled but never noticed.
    fixtures.setup_hearing_noticed(api, ctx)
    unnoticed = get_success_data(
        api.create_public_hearing(
            fixtures.clerk(ctx),
            factories.public_hearing_payload(
                ctx["case"]["id"],
                ctx["municipality"]["id"],
                scheduled_start_at=SECOND_HEARING_START_AT,
                scheduled_end_at=SECOND_HEARING_END_AT,
            ),
        ),
        201,
    )
    fixtures.set_clock(api, SECOND_HEARING_START_AT)

    assert unnoticed["hearing_status"] == "SCHEDULED", (
        "the hearing-state rule must be satisfied so the notice rule is the one reached"
    )
    assert unnoticed["notice_published_at"] is None

    validate_error(
        api.hold_hearing(fixtures.clerk(ctx), unnoticed["id"]),
        ERR_NOTICE_NOT_PUBLISHED,
    )

    unchanged = fixtures.read_hearing(api, ctx["municipality"]["id"], unnoticed["id"])
    assert unchanged["hearing_status"] == "SCHEDULED"
    assert unchanged["held_at"] is None
    case = fixtures.refresh_case(api, ctx)
    assert case["status"] == "HEARING_NOTICED"
    assert case["hearing_held_at"] is None


# ==========================================================================
# Adopting the ordinance: the open objection window outranks the deficit
# ==========================================================================
def test_adopting_the_ordinance_with_the_protest_window_open_reports_the_open_window(api):
    """PRD §3.7: "The case must be in `HEARING_HELD` with `protest_outcome`
    equal to `FAILED`; a case whose `HELD` hearing still has `protest_outcome`
    `OPEN` is refused with `ERR_PROTEST_PERIOD_OPEN`, and a case in any other
    status with `ERR_CASE_STATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/adopt_ordinance_protest_safety_error_precedes_fiscal_deficit_error
    """
    ctx = fixtures.setup_certified_case(api)
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)

    # A projected population of 240 residents makes the average-cost service
    # bill far outrun the territory's revenue, so the deficit rule is violated
    # on the very same call as the still-open objection window.
    projected_population = 240
    fixtures.setup_finalized_analysis(
        api, ctx, projected_population=projected_population
    )
    expected_deficit = _expected_deficit_ratio_pct(ctx, projected_population)
    assertions.assert_numeric_equals(
        ctx["analysis"]["deficit_ratio_pct"], expected_deficit, "deficit_ratio_pct"
    )
    assert ctx["analysis"]["status"] == "FINALIZED"
    assert Decimal(str(ctx["analysis"]["deficit_ratio_pct"])) > Decimal(
        str(ctx["municipality"]["fiscal_deficit_tolerance_pct"])
    ), "the fiscal fault must be live for the pairing to bite"

    # Past the cooling-off period but well inside the thirty-day objection
    # window, so the only two live objections are the pair under test.
    fixtures.set_clock(api, CLOCK_AT_COOLING_OFF_ELAPSED)
    hearing = fixtures.read_hearing(api, ctx["municipality"]["id"], ctx["hearing"]["id"])
    assert hearing["protest_outcome"] == "OPEN"
    assert _instant(hearing["protest_closes_at"]) == _instant(
        assertions.add_days(hearing["held_at"], constants.DEFAULT_PROTEST_WINDOW_DAYS)
    )

    validate_error(
        api.adopt_ordinance(fixtures.clerk(ctx), ctx["case"]["id"]),
        ERR_PROTEST_PERIOD_OPEN,
    )

    case = fixtures.refresh_case(api, ctx)
    assert case["status"] == "HEARING_HELD"
    assert case["protest_outcome"] == "NOT_EVALUATED"
    assert case["ordinance_adopted_at"] is None


def test_adopting_the_ordinance_after_a_failed_protest_reports_the_fiscal_deficit(api):
    """PRD §3.7: "The case must have an `ADOPTED` plan of services
    (`ERR_PLAN_NOT_ADOPTED`) and a `FINALIZED` fiscal impact analysis
    (`ERR_FISCAL_ANALYSIS_NOT_FINALIZED`), that analysis's `deficit_ratio_pct`
    must be no greater than the municipality's `fiscal_deficit_tolerance_pct` —
    equality is tolerated, anything above it is refused with
    `ERR_FISCAL_DEFICIT_EXCEEDS_TOLERANCE` — and the case's `method` must still
    appear in the statute's `authorized_methods`
    (`ERR_METHOD_NOT_AUTHORIZED_BY_STATUTE`)."

    Design: Difficulty/priority_pair_validation_conflict/adopt_ordinance_protest_safety_error_precedes_fiscal_deficit_error
    """
    ctx = fixtures.setup_certified_case(api)
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)
    # Nobody objects, so the tabulation clears the objection window and leaves
    # the deficit as the only surviving objection.
    fixtures.close_protest_period(api, ctx)

    projected_population = 240
    fixtures.setup_finalized_analysis(
        api, ctx, projected_population=projected_population
    )
    expected_deficit = _expected_deficit_ratio_pct(ctx, projected_population)
    assertions.assert_numeric_equals(
        ctx["analysis"]["deficit_ratio_pct"], expected_deficit, "deficit_ratio_pct"
    )
    assert Decimal(str(ctx["analysis"]["deficit_ratio_pct"])) > Decimal(
        str(ctx["municipality"]["fiscal_deficit_tolerance_pct"])
    )

    hearing = fixtures.read_hearing(api, ctx["municipality"]["id"], ctx["hearing"]["id"])
    assert hearing["protest_outcome"] == "FAILED", (
        "the objection window must be settled so the fiscal rule is the one reached"
    )

    validate_error(
        api.adopt_ordinance(fixtures.clerk(ctx), ctx["case"]["id"]),
        ERR_FISCAL_DEFICIT_EXCEEDS_TOLERANCE,
    )

    case = fixtures.refresh_case(api, ctx)
    assert case["status"] == "HEARING_HELD"
    assert case["protest_outcome"] == "FAILED"
    assert case["ordinance_adopted_at"] is None


# ==========================================================================
# Filing a protest: the late-filing objection outranks the parcel mismatch
# ==========================================================================
def _setup_hearing_and_foreign_parcel(api):
    """A held hearing on one case, plus a second DRAFT case in the same city
    holding a parcel that belongs to no part of the heard territory."""
    ctx = fixtures.setup_certified_case(api)
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)

    municipality_id = ctx["municipality"]["id"]
    other_case = fixtures.create_case(api, municipality_id)
    other_owner = fixtures.create_owner(api)
    other_parcel = fixtures.add_parcel(
        api, municipality_id, other_case["id"], other_owner["id"]
    )
    return ctx, other_case, other_owner, other_parcel


def test_late_protest_filing_on_a_foreign_parcel_reports_the_out_of_window_error(api):
    """PRD §3.6: "The protest period must be open, or
    `ERR_PROTEST_PERIOD_CLOSED`, and the logical clock — which becomes the
    filing's `filed_at` — must lie inside the closed interval from
    `protest_opens_at` through `protest_closes_at` inclusive, or
    `ERR_PROTEST_FILING_OUT_OF_WINDOW`."

    Design: Difficulty/priority_pair_validation_conflict/protest_filing_temporal_error_precedes_parcel_referential_error
    """
    ctx, other_case, other_owner, other_parcel = _setup_hearing_and_foreign_parcel(api)

    # Past the close instant, but the clerk has not yet tabulated, so the
    # objection period is still in the state the filing needs and the lateness
    # rule is the one that can fire.
    current_utc = fixtures.set_clock(api, constants.CLOCK_AFTER_PROTEST_WINDOW)
    hearing = fixtures.read_hearing(api, ctx["municipality"]["id"], ctx["hearing"]["id"])
    assert hearing["protest_outcome"] == "OPEN"
    assert _instant(current_utc) > _instant(hearing["protest_closes_at"])
    assert other_parcel["annexation_case_id"] == other_case["id"], (
        "the parcel must belong to another case for the pairing to bite"
    )

    validate_error(
        api.create_protest_filing(
            make_property_owner_headers(other_owner["id"]),
            factories.protest_filing_payload(
                hearing["id"], other_parcel["id"], other_owner["id"], 100.00
            ),
        ),
        ERR_PROTEST_FILING_OUT_OF_WINDOW,
    )

    filings, meta = validate_paginated(
        api.list_protest_filings(
            fixtures.clerk(ctx), public_hearing_id=hearing["id"]
        )
    )
    assert meta["total_count"] == 0
    assert filings == []
    unchanged_hearing = fixtures.read_hearing(
        api, ctx["municipality"]["id"], hearing["id"]
    )
    assert unchanged_hearing["protest_outcome"] == "OPEN"
    assertions.assert_numeric_equals(
        unchanged_hearing["protest_pct"], Decimal("0.00"), "protest_pct"
    )
    assert (
        fixtures.read_parcel(api, ctx["municipality"]["id"], other_parcel["id"])[
            "parcel_status"
        ]
        == "PROPOSED"
    )


def test_in_window_protest_filing_on_a_foreign_parcel_reports_the_parcel_case_mismatch(api):
    """PRD §3.6: "The referenced parcel must belong to the same case as the
    referenced hearing, or `ERR_PARCEL_CASE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/protest_filing_temporal_error_precedes_parcel_referential_error
    """
    ctx, other_case, other_owner, other_parcel = _setup_hearing_and_foreign_parcel(api)

    # Squarely inside the objection window, so the lateness rule is satisfied
    # and the referential rule is the one reached.
    current_utc = fixtures.set_clock(api, constants.CLOCK_DURING_PROTEST_WINDOW)
    hearing = fixtures.read_hearing(api, ctx["municipality"]["id"], ctx["hearing"]["id"])
    assert (
        _instant(hearing["protest_opens_at"])
        <= _instant(current_utc)
        <= _instant(hearing["protest_closes_at"])
    )
    assert other_parcel["annexation_case_id"] == other_case["id"]

    validate_error(
        api.create_protest_filing(
            make_property_owner_headers(other_owner["id"]),
            factories.protest_filing_payload(
                hearing["id"], other_parcel["id"], other_owner["id"], 100.00
            ),
        ),
        ERR_PARCEL_CASE_MISMATCH,
    )

    filings, meta = validate_paginated(
        api.list_protest_filings(
            fixtures.clerk(ctx), public_hearing_id=hearing["id"]
        )
    )
    assert meta["total_count"] == 0
    assert filings == []
    assert (
        fixtures.read_hearing(api, ctx["municipality"]["id"], hearing["id"])[
            "protest_outcome"
        ]
        == "OPEN"
    )


# ==========================================================================
# The objection threshold: an inclusive comparison at the exact edge
# ==========================================================================
# Four parcels whose assessed values sum to 100,000,000 cents, chosen so that a
# whole 10,000,000-cent parcel plus half of a 20,000,000-cent parcel lands the
# objection weight exactly on the 20.00% statutory threshold.
_GRADED_PARCEL_VALUES_CENTS = [40000000, 30000000, 20000000, 10000000]


def _setup_held_hearing_with_graded_parcels(api):
    ctx = fixtures.setup_certified_case(
        api, parcel_values_cents=list(_GRADED_PARCEL_VALUES_CENTS)
    )
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.setup_hearing_noticed(api, ctx)
    fixtures.setup_hearing_held(api, ctx)
    fixtures.set_clock(api, constants.CLOCK_DURING_PROTEST_WINDOW)
    return ctx


def test_protest_weight_exactly_at_the_statutory_threshold_sustains_the_protest(api):
    """PRD §3.6: "When `protest_pct` is at or above the statute's
    `protest_threshold_pct`, the hearing's `protest_outcome` moves `OPEN →
    SUSTAINED`, the hearing's `protest_pct` is stamped, the case mirrors both —
    `protest_pct` copied and `protest_outcome` set to `SUSTAINED` — and the
    case's `status` advances `HEARING_HELD → PROTEST_SUSTAINED`."

    Design: Difficulty/boundary_precision_check/protest_pct_exactly_at_threshold_sustains_annexation
    """
    ctx = _setup_held_hearing_with_graded_parcels(api)

    # 10,000,000 in full plus half of 20,000,000 is 20,000,000 of a
    # 100,000,000-cent territory: exactly the threshold, not a hundredth over.
    whole_share = fixtures.file_protest(
        api, ctx, parcel_index=3, ownership_share_pct=100.00
    )
    half_share = fixtures.file_protest(
        api, ctx, parcel_index=2, ownership_share_pct=50.00
    )
    assert whole_share["protest_value_cents"] == assertions.expected_share_value_cents(
        _GRADED_PARCEL_VALUES_CENTS[3], 100.00
    )
    assert half_share["protest_value_cents"] == assertions.expected_share_value_cents(
        _GRADED_PARCEL_VALUES_CENTS[2], 50.00
    )

    fixtures.close_protest_period(api, ctx)

    expected_pct = assertions.expected_weight_pct(
        whole_share["protest_value_cents"] + half_share["protest_value_cents"],
        ctx["case"]["territory_assessed_value_cents"],
    )
    assertions.assert_numeric_equals(
        expected_pct, ctx["statute"]["protest_threshold_pct"], "protest_pct at threshold"
    )
    hearing = ctx["hearing"]
    assertions.assert_numeric_equals(
        hearing["protest_pct"], expected_pct, "hearing protest_pct"
    )
    assert hearing["protest_outcome"] == "SUSTAINED"
    case = fixtures.refresh_case(api, ctx)
    assertions.assert_numeric_equals(
        case["protest_pct"], expected_pct, "case protest_pct"
    )
    assert case["protest_outcome"] == "SUSTAINED"
    assert case["status"] == "PROTEST_SUSTAINED"


def test_protest_weight_one_hundredth_below_the_threshold_leaves_the_case_adoptable(api):
    """PRD §3.6: "When `protest_pct` is strictly below the threshold, the
    hearing's `protest_outcome` moves `OPEN → FAILED`, the hearing's
    `protest_pct` is stamped, the case mirrors both with `protest_outcome` set
    to `FAILED`, and the case's `status` stays exactly where it was at
    `HEARING_HELD` — a self-loop that leaves the case adoptable."

    Design: Difficulty/boundary_precision_check/protest_pct_exactly_at_threshold_sustains_annexation
    """
    ctx = _setup_held_hearing_with_graded_parcels(api)

    # 49.95% of the 20,000,000-cent parcel is 9,990,000, so the aggregate is
    # 19,990,000 — one hundredth of a percentage point under the threshold.
    whole_share = fixtures.file_protest(
        api, ctx, parcel_index=3, ownership_share_pct=100.00
    )
    short_share = fixtures.file_protest(
        api, ctx, parcel_index=2, ownership_share_pct=49.95
    )
    assert short_share["protest_value_cents"] == assertions.expected_share_value_cents(
        _GRADED_PARCEL_VALUES_CENTS[2], 49.95
    )

    fixtures.close_protest_period(api, ctx)

    expected_pct = assertions.expected_weight_pct(
        whole_share["protest_value_cents"] + short_share["protest_value_cents"],
        ctx["case"]["territory_assessed_value_cents"],
    )
    assert expected_pct < Decimal(str(ctx["statute"]["protest_threshold_pct"]))
    hearing = ctx["hearing"]
    assertions.assert_numeric_equals(
        hearing["protest_pct"], expected_pct, "hearing protest_pct"
    )
    assert hearing["protest_outcome"] == "FAILED"
    case = fixtures.refresh_case(api, ctx)
    assertions.assert_numeric_equals(
        case["protest_pct"], expected_pct, "case protest_pct"
    )
    assert case["protest_outcome"] == "FAILED"
    assert case["status"] == "HEARING_HELD"


# ==========================================================================
# Contiguity: the four-decimal rounding edge of the statutory minimum
# ==========================================================================
# 10,000 feet of shared boundary against an 80,000-foot corporate perimeter
# rounds to exactly the statutory minimum; 9,990 feet rounds to 0.1249.
_CONTIGUITY_MIN_RATIO = 0.125
_SHARED_FEET_AT_MINIMUM = 10000
_SHARED_FEET_BELOW_MINIMUM = 9990


def test_contiguity_ratio_exactly_at_the_statutory_minimum_certifies_the_territory(api):
    """PRD §3.2: "If it is below the statute's `contiguity_min_ratio` the
    certification is refused with `ERR_TERRITORY_NOT_CONTIGUOUS`; a ratio
    exactly equal to the minimum passes."

    Design: Difficulty/boundary_precision_check/contiguity_ratio_exactly_at_statutory_minimum_certifies
    """
    ctx = fixtures.setup_draft_case(
        api,
        statute={"contiguity_min_ratio": _CONTIGUITY_MIN_RATIO},
        case={"shared_boundary_feet": _SHARED_FEET_AT_MINIMUM},
    )
    expected_ratio = assertions.expected_contiguity_ratio(
        _SHARED_FEET_AT_MINIMUM, ctx["municipality"]["corporate_boundary_perimeter_feet"]
    )
    assert expected_ratio == Decimal(str(ctx["statute"]["contiguity_min_ratio"])), (
        "the ratio must land on the minimum, not above it, for the edge to be tested"
    )

    case = get_success_data(
        api.certify_territory(fixtures.planner(ctx), ctx["case"]["id"])
    )

    assertions.assert_numeric_equals(
        case["contiguity_ratio"], expected_ratio, "contiguity_ratio", places=4
    )
    # The contiguity ramp saturates at twice the minimum, so a ratio sitting on
    # the minimum earns half the base credit; the fully developed lot set adds
    # the flat urban bonus and draws no density penalty.
    expected_index = assertions.expected_qualification_index(
        expected_ratio,
        ctx["statute"]["contiguity_min_ratio"],
        True,
        assertions.expected_density(
            ctx["case"]["dwelling_units"], case["territory_acreage"]
        ),
        ctx["statute"]["urban_density_min_units_per_acre"],
        assertions.expected_developed_lot_ratio(
            ctx["case"]["developed_lot_count"], ctx["case"]["total_lot_count"]
        ),
        ctx["statute"]["subdivision_test_min_developed_ratio"],
        ctx["case"]["max_service_distance_miles"],
    )
    assertions.assert_numeric_equals(
        case["qualification_index"], expected_index, "qualification_index"
    )
    assert case["urban_development_qualified"] is True
    assert case["status"] == "TERRITORY_CERTIFIED"


def test_contiguity_ratio_one_ten_thousandth_below_the_minimum_refuses_certification(api):
    """PRD §3.2: "If it is below the statute's `contiguity_min_ratio` the
    certification is refused with `ERR_TERRITORY_NOT_CONTIGUOUS`; a ratio
    exactly equal to the minimum passes."

    Design: Difficulty/boundary_precision_check/contiguity_ratio_exactly_at_statutory_minimum_certifies
    """
    ctx = fixtures.setup_draft_case(
        api,
        statute={"contiguity_min_ratio": _CONTIGUITY_MIN_RATIO},
        case={"shared_boundary_feet": _SHARED_FEET_BELOW_MINIMUM},
    )
    # 9,990 / 80,000 is 0.124875, which rounds half up to 0.1249 at four
    # decimals — a single ten-thousandth under the minimum.
    expected_ratio = assertions.expected_contiguity_ratio(
        _SHARED_FEET_BELOW_MINIMUM,
        ctx["municipality"]["corporate_boundary_perimeter_feet"],
    )
    assert expected_ratio < Decimal(str(ctx["statute"]["contiguity_min_ratio"]))

    validate_error(
        api.certify_territory(fixtures.planner(ctx), ctx["case"]["id"]),
        ERR_TERRITORY_NOT_CONTIGUOUS,
    )

    case = fixtures.refresh_case(api, ctx)
    assert case["status"] == "DRAFT"
    for parcel in ctx["parcels"]:
        assert (
            fixtures.read_parcel(api, ctx["municipality"]["id"], parcel["id"])[
                "parcel_status"
            ]
            == "PROPOSED"
        )


# ==========================================================================
# Administrative overhead: the strict tier ceiling on the base service cost
# ==========================================================================
# Under AVERAGE_COST the citywide cost of 800,000,000 cents over a citywide
# population of 40,000 is 20,000 cents per projected resident, so 250 residents
# land the base cost on exactly the first tier ceiling and 249 land just under.
_POPULATION_AT_TIER_CEILING = 250
_POPULATION_BELOW_TIER_CEILING = 249


def _assert_overhead_ladder(api, ctx, projected_population, expected_tier_pct):
    analysis = fixtures.author_analysis(
        api,
        ctx,
        analysis_method="AVERAGE_COST",
        projected_population=projected_population,
    )
    expected_base = assertions.expected_average_cost_base_cents(
        ctx["municipality"]["citywide_annual_service_cost_cents"],
        projected_population,
        ctx["municipality"]["citywide_population"],
    )
    assert analysis["base_service_cost_cents"] == expected_base
    assertions.assert_numeric_equals(
        analysis["overhead_tier_pct"], expected_tier_pct, "overhead_tier_pct", places=4
    )

    expected_overhead = assertions.cents(
        Decimal(expected_base) * Decimal(str(expected_tier_pct))
    )
    assert analysis["administrative_overhead_cents"] == expected_overhead
    assert (
        analysis["projected_annual_service_cost_cents"]
        == expected_base + expected_overhead
    )

    expected_gross = _expected_gross_revenue_cents(ctx, projected_population)
    assert analysis["gross_annual_revenue_cents"] == expected_gross
    expected_net = expected_gross - (expected_base + expected_overhead)
    assert analysis["net_annual_impact_cents"] == expected_net
    assertions.assert_numeric_equals(
        analysis["deficit_ratio_pct"],
        assertions.expected_deficit_ratio_pct(expected_net, expected_gross),
        "deficit_ratio_pct",
    )
    assert analysis["status"] == "DRAFT"
    return analysis


def test_base_cost_exactly_at_the_tier_ceiling_takes_the_nine_percent_rate(api):
    """PRD §3.4: "When the base cost is below five million cents the rate is
    0.12; otherwise, when it is below twenty-five million cents the rate is
    0.09; otherwise the rate is 0.06."

    Design: Difficulty/boundary_precision_check/overhead_tier_boundary_at_exactly_five_million_base_cost
    """
    ctx = fixtures.setup_draft_case(api)

    analysis = _assert_overhead_ladder(
        api, ctx, _POPULATION_AT_TIER_CEILING, constants.OVERHEAD_TIER_2_PCT
    )

    # The comparison against the ceiling is strict, so a base cost sitting
    # exactly on it falls into the cheaper second tier rather than the first.
    assert analysis["base_service_cost_cents"] == constants.OVERHEAD_TIER_1_CEILING_CENTS


def test_base_cost_one_resident_below_the_tier_ceiling_takes_the_twelve_percent_rate(api):
    """PRD §3.4: "When the base cost is below five million cents the rate is
    0.12; otherwise, when it is below twenty-five million cents the rate is
    0.09; otherwise the rate is 0.06."

    Design: Difficulty/boundary_precision_check/overhead_tier_boundary_at_exactly_five_million_base_cost
    """
    ctx = fixtures.setup_draft_case(api)

    analysis = _assert_overhead_ladder(
        api, ctx, _POPULATION_BELOW_TIER_CEILING, constants.OVERHEAD_TIER_1_PCT
    )

    # One projected resident fewer puts the base cost strictly under the
    # ceiling, so the cheaper territory carries the larger overhead rate.
    assert analysis["base_service_cost_cents"] < constants.OVERHEAD_TIER_1_CEILING_CENTS
