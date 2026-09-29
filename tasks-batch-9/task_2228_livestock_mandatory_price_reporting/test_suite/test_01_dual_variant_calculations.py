"""Two published averages and two measurement bases over identical data.

The same accepted transaction lines publish one price under HEAD_WEIGHTED and a
different price under WEIGHT_WEIGHTED, and the same plant history measures one
head count under FIVE_YEAR_AVERAGE and another under PRIOR_YEAR_ACTUAL.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_determination,
    assert_price_statistics,
    assert_registration_number_format,
    assert_report_dimensions,
    assert_window_ledger,
)
from test_helpers.types import (
    AggregationState,
    BasisVariant,
    DeterminationOutcome,
    DisclosureState,
    PublicationState,
    PurchaseTypeFilter,
    RegistrationStatus,
    WeightingVariant,
)


def test_01_head_weighted_average_weights_each_priced_line_by_head_count(api):
    """A HEAD_WEIGHTED aggregate weights every priced line by its head count.

    Four priced lines carrying 950 head accumulate 271,325 dollar-head at full
    precision, and the single division rounds once to 285.61 per hundredweight.
    The packer-owned line is a volume only and never touches the price.

    PRD §3.6: "under `HEAD_WEIGHTED` the weight is the line's `head_count`, so a
    lot of light carcasses pulls the average down exactly as hard as an equal
    count of heavy ones".

    Design: Difficulty/dual_variant_calc/head_vs_weight_weighted_market_average
    """
    scene = fx.three_reporter_cattle_window(api)

    report = fx.computed_report(
        api,
        scene["window"]["id"],
        weighting_variant=WeightingVariant.HEAD_WEIGHTED.value,
    )

    assert report["weighting_variant"] == WeightingVariant.HEAD_WEIGHTED.value
    assert report["purchase_type_filter"] == PurchaseTypeFilter.ALL_PRICED.value
    assert report["weighted_average_price_per_cwt"] == 285.61, (
        "271325 dollar-head over 950 priced head is 285.6052..., which rounds "
        f"half up to 285.61, not {report['weighted_average_price_per_cwt']}"
    )
    assert_report_dimensions(
        report,
        AggregationState.COMPUTED.value,
        DisclosureState.UNREVIEWED.value,
        PublicationState.UNPUBLISHED.value,
    )


def test_02_weight_weighted_average_diverges_from_the_head_weighted_one(api):
    """The carcass-weight variant publishes a different cent value.

    The same five lines weighted by head times carcass weight accumulate
    2,386,715 over 8,350 hundredweight and round to 285.83, twenty-two cents
    away from the head-weighted figure on byte-identical input rows.

    PRD §3.6: "under `WEIGHT_WEIGHTED` the weight is the line's `head_count`
    multiplied by its `avg_carcass_weight_cwt`, left unrounded, so heavier
    carcasses dominate".

    Design: Difficulty/dual_variant_calc/head_vs_weight_weighted_market_average
    """
    scene = fx.three_reporter_cattle_window(api)

    head_report = fx.computed_report(
        api,
        scene["window"]["id"],
        weighting_variant=WeightingVariant.HEAD_WEIGHTED.value,
    )
    weight_report = fx.computed_report(
        api,
        scene["window"]["id"],
        weighting_variant=WeightingVariant.WEIGHT_WEIGHTED.value,
    )

    assert weight_report["weighted_average_price_per_cwt"] == 285.83, (
        "2386715 over 8350 weighted hundredweight is 285.8341..., which rounds "
        f"half up to 285.83, not {weight_report['weighted_average_price_per_cwt']}"
    )
    assert head_report["weighted_average_price_per_cwt"] == 285.61
    assert (
        head_report["weighted_average_price_per_cwt"]
        != weight_report["weighted_average_price_per_cwt"]
    ), "the two weighting variants must not publish the same average"


def test_03_volume_range_and_concentration_are_identical_under_both_variants(api):
    """Only the price moves between variants: volume and concentration do not.

    Head totals count every purchase type, the price range is taken from the
    priced items as reported, and reporter concentration is measured on the
    volume metric -- so all of those read the same on both reports.

    PRD §3.6: "`total_head` is the sum of `head_count` across all of them,
    `PACKER_OWNED` lines included, and `total_pounds` is null."

    Design: Difficulty/dual_variant_calc/head_vs_weight_weighted_market_average
    """
    scene = fx.three_reporter_cattle_window(api)
    window_id = scene["window"]["id"]

    head_report = fx.computed_report(
        api, window_id, weighting_variant=WeightingVariant.HEAD_WEIGHTED.value
    )
    weight_report = fx.computed_report(
        api, window_id, weighting_variant=WeightingVariant.WEIGHT_WEIGHTED.value
    )

    for report in (head_report, weight_report):
        assert report["total_head"] == 1250, report
        assert report["total_pounds"] is None, report
        assert_price_statistics(
            report, report["weighted_average_price_per_cwt"], 279.75, 292.25
        )
        assert report["reporter_count"] == 3, report
        assert report["max_reporter_share_pct"] == 40.00, report
        assert report["source_submission_count"] == 3, report

    window = fx.read_window(api, window_id)
    assert_window_ledger(window, total_head_reported=1250, accepted_submission_count=3)


def test_04_five_year_average_basis_measures_below_the_cattle_floor(api):
    """Pooled-then-floored measurement exempts a firm the prior year would not.

    A history of 100,000 / 110,000 / 120,000 / 130,000 / 150,000 head pools to
    610,000, divides once by five to 122,000, and lands below the 125,000-head
    cattle floor -- so the firm is EXEMPT and cannot be activated at all.

    PRD §3.2: "the platform pools every participating plant's head count for
    every one of the five lookback years into a single total, divides that one
    pooled total by five, and discards any fractional remainder".

    Design: Difficulty/dual_variant_calc/five_year_average_vs_prior_year_threshold
    """
    entity = fx.create_entity(api, legal_name="Bravo Beef")
    fx.create_plant(
        api,
        entity["id"],
        plant_code="EST-202",
        annual_head_history=dict(k.HISTORY_BELOW_CATTLE_FLOOR),
    )
    registration = fx.draft_registration(api, entity["id"])

    determined = get_success_data(
        api.determine_registration(registration["id"], u.PROGRAM_ADMIN)
    )

    assert determined["basis_variant"] == BasisVariant.FIVE_YEAR_AVERAGE.value
    assert_determination(
        determined,
        measured_head=122000,
        threshold_head=125000,
        outcome=DeterminationOutcome.EXEMPT.value,
    )
    assert determined["registration_number"] is None, determined
    assert determined["status"] == RegistrationStatus.DETERMINED.value

    refused = api.activate_registration(registration["id"], u.PROGRAM_ADMIN)
    validate_error(refused, ApiErrorId.ERR_ENTITY_EXEMPT.value, 409)

    still_determined = fx.read_registration(api, registration["id"])
    assert still_determined["status"] == RegistrationStatus.DETERMINED.value
    assert still_determined["effective_from"] is None, still_determined


def test_05_prior_year_redetermination_flips_the_outcome_to_mandatory(api):
    """The appealed basis switch turns the same plant data into an obligation.

    Redetermining on the prior-year basis measures the 2025 actual of 150,000
    head against the unchanged 125,000-head threshold, so the outcome flips to
    MANDATORY and the activation that was refused as exempt now succeeds.

    PRD §3.2: "Under `PRIOR_YEAR_ACTUAL`, `measured_head` is simply the sum,
    across participating plants, of the head count recorded for the year
    immediately before `determination_year`."

    Design: Difficulty/dual_variant_calc/five_year_average_vs_prior_year_threshold
    """
    entity = fx.create_entity(api, legal_name="Bravo Beef")
    fx.create_plant(
        api,
        entity["id"],
        plant_code="EST-202",
        annual_head_history=dict(k.HISTORY_BELOW_CATTLE_FLOOR),
    )
    registration = fx.draft_registration(api, entity["id"])
    averaged = get_success_data(
        api.determine_registration(registration["id"], u.PROGRAM_ADMIN)
    )
    assert averaged["determination_outcome"] == DeterminationOutcome.EXEMPT.value

    get_success_data(
        api.appeal_registration(
            registration["id"], f.appeal_payload(), u.reporter_agent(entity["id"])
        )
    )
    redetermined = get_success_data(
        api.redetermine_registration(
            registration["id"],
            f.redetermine_payload(BasisVariant.PRIOR_YEAR_ACTUAL.value),
            u.PROGRAM_ADMIN,
        )
    )

    assert redetermined["basis_variant"] == BasisVariant.PRIOR_YEAR_ACTUAL.value
    assert_determination(
        redetermined,
        measured_head=150000,
        threshold_head=125000,
        outcome=DeterminationOutcome.MANDATORY.value,
    )
    assert redetermined["status"] == RegistrationStatus.DETERMINED.value
    assert redetermined["appeal_count"] == 1, redetermined

    activated = validate_success(
        api.activate_registration(registration["id"], u.PROGRAM_ADMIN)
    )
    assert activated["status"] == RegistrationStatus.ACTIVE.value
    assert_registration_number_format(activated["registration_number"], 2026, 1)
