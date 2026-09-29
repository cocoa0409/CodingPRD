"""Dual-variant arithmetic: the two dockage routes and the two protein bases."""

from test_helpers import (
    ApiErrorId,
    CORN_NO_1_FACTORS_MOISTURE_12_8,
    SIX_CORN_DRAFTS,
    SIX_CORN_DRAFTS_DOCKAGE_LBS,
    SIX_CORN_DRAFTS_DOCKAGE_PCT,
    SIX_CORN_DRAFTS_NET_BUSHELS,
    SIX_CORN_DRAFTS_NET_LBS,
    SIX_CORN_DRAFTS_PROVISIONAL_NET_LBS,
    SIX_CORN_DRAFTS_ROUNDING_VARIANCE_LBS,
    api_client,
    assert_weighing_record,
    read_analysis,
    read_request,
    record_analysis,
    record_grading,
    setup_office,
    setup_sampled_request,
    setup_weighed_request,
    validate_error,
    validate_success,
)
from test_helpers import INSPECTOR


def _weighing_office():
    return setup_office("DESIGNATED", area_overrides={"fee_multiplier_bp": 11500})


def _protein_office():
    return setup_office("DESIGNATED")


def test_weighing_record_carries_both_dockage_routes_and_their_variance():
    """The official variant works draft by draft: for each draft, subtract its
    `tare_lbs` from its `gross_lbs` to get that draft's gross-net, multiply that
    gross-net by `dockage_pct` and divide by 100, and round the product half up
    to a whole pound to obtain the draft's dockage deduction; the draft's net is
    its gross-net less its deduction.

    The provisional variant works on the aggregate: sum every draft's gross-net,
    multiply that single total by `dockage_pct`, divide by 100, round half up to
    a whole pound, and subtract to get `provisional_net_lbs`, which is what the
    applicant's advance advice quotes.

    Six corn drafts with gross-nets of 33700, 33900, 34100, 34300, 34500 and
    34700 pounds at a `dockage_pct` of 1.5 give per-draft deductions of 506,
    509, 512, 515, 518 and 521 for a `dockage_lbs` of 3081 and a `net_lbs` of
    202119, while the aggregate route deducts 3078 from 205200 for a
    `provisional_net_lbs` of 202122; `rounding_variance_lbs` is 3 and
    `net_bushels` is 3609.27.

    Design: Difficulty/dual_variant_calc/weighing_per_draft_vs_aggregate_dockage_rounding_variance
    """
    office = _weighing_office()
    staged = setup_weighed_request(
        office,
        drafts=SIX_CORN_DRAFTS,
        dockage_pct=SIX_CORN_DRAFTS_DOCKAGE_PCT,
        declared_quantity_bushels=3500,
    )
    record = staged["weighing"]

    assert_weighing_record(record)
    assert record["dockage_lbs"] == SIX_CORN_DRAFTS_DOCKAGE_LBS
    assert record["net_lbs"] == SIX_CORN_DRAFTS_NET_LBS
    assert record["provisional_net_lbs"] == SIX_CORN_DRAFTS_PROVISIONAL_NET_LBS
    assert record["rounding_variance_lbs"] == SIX_CORN_DRAFTS_ROUNDING_VARIANCE_LBS
    assert record["net_bushels"] == SIX_CORN_DRAFTS_NET_BUSHELS
    assert record["status"] == "WEIGHED"


def test_weighing_advances_only_the_weighing_dimension_and_prices_the_net_bushels():
    """`net_bushels` is `net_lbs` divided by the commodity's pounds per bushel —
    56 for `CORN` and 60 for `SOYBEANS` — rounded half up to 2 decimals.

    Creating the record advances the request `PENDING → WEIGHED` and sets
    `certified_quantity_bushels` to `net_bushels`.

    `grading_status` starts at `OPEN` and runs `OPEN → SAMPLED → GRADED →
    GRADE_CERTIFIED`, with `GRADE_CERTIFIED → UNDER_APPEAL` and back again when
    rights are exercised.

    Design: Difficulty/dual_variant_calc/weighing_per_draft_vs_aggregate_dockage_rounding_variance
    """
    office = _weighing_office()
    staged = setup_weighed_request(
        office,
        drafts=SIX_CORN_DRAFTS,
        dockage_pct=SIX_CORN_DRAFTS_DOCKAGE_PCT,
        declared_quantity_bushels=3500,
    )

    request = read_request(staged["request"]["id"])
    assert request["weighing_status"] == "WEIGHED"
    assert request["grading_status"] == "OPEN"
    assert request["certified_quantity_bushels"] == SIX_CORN_DRAFTS_NET_BUSHELS


def test_analysis_before_any_determination_uses_the_instrument_moisture_basis():
    """Which moisture the conversion uses depends on what the office already
    knows: when no `FINAL` grading determination exists for the request at the
    moment the analysis is created, `basis_source` is `INSTRUMENT_MOISTURE` and
    `moisture_source_pct` is the `instrument_moisture_pct`; when a `FINAL`
    determination does exist, `basis_source` is `OFFICIAL_MOISTURE` and
    `moisture_source_pct` is that determination's rounded `moisture_pct` from
    `rounded_factors`.

    In both cases `protein_reported_pct` is the as-is protein multiplied by the
    difference between 100 and 13.0, divided by the difference between 100 and
    `moisture_source_pct`, rounded half up to 2 decimals, and
    `basis_adjustment_pct` is `protein_reported_pct` less `protein_pct_as_is`,
    likewise rounded half up to 2 decimals.

    Design: Difficulty/dual_variant_calc/protein_basis_instrument_moisture_vs_official_moisture
    """
    office = _protein_office()
    staged = setup_sampled_request(
        office, requested_services=("GRADING", "PROTEIN"), portions_count=2
    )

    analysis = record_analysis(
        staged["request"]["id"],
        staged["sample"]["id"],
        office["instrument"]["id"],
        office["inspector"]["id"],
        protein_pct_as_is=34.60,
        instrument_moisture_pct=11.20,
    )

    assert analysis["basis_source"] == "INSTRUMENT_MOISTURE"
    assert analysis["moisture_source_pct"] == 11.20
    assert analysis["protein_reported_pct"] == 33.90
    assert analysis["basis_adjustment_pct"] == -0.70
    assert analysis["status"] == "ACCEPTED"


def test_recompute_restates_the_analysis_onto_the_official_rounded_moisture():
    """Restatement sets `basis_source` to `OFFICIAL_MOISTURE`, adopts the
    official rounded moisture as `moisture_source_pct`, recomputes
    `protein_reported_pct` and `basis_adjustment_pct` by the same arithmetic,
    and sets `status` to `RECOMPUTED`.

    Which moisture the conversion uses depends on what the office already
    knows: when no `FINAL` grading determination exists for the request at the
    moment the analysis is created, `basis_source` is `INSTRUMENT_MOISTURE` and
    `moisture_source_pct` is the `instrument_moisture_pct`; when a `FINAL`
    determination does exist, `basis_source` is `OFFICIAL_MOISTURE` and
    `moisture_source_pct` is that determination's rounded `moisture_pct` from
    `rounded_factors`.

    Design: Difficulty/dual_variant_calc/protein_basis_instrument_moisture_vs_official_moisture
    """
    office = _protein_office()
    staged = setup_sampled_request(
        office, requested_services=("GRADING", "PROTEIN"), portions_count=2
    )
    analysis = record_analysis(
        staged["request"]["id"],
        staged["sample"]["id"],
        office["instrument"]["id"],
        office["inspector"]["id"],
        protein_pct_as_is=34.60,
        instrument_moisture_pct=11.20,
    )
    grading = record_grading(
        staged["request"]["id"],
        staged["sample"]["id"],
        office["inspector"]["id"],
        factors=CORN_NO_1_FACTORS_MOISTURE_12_8,
    )
    assert grading["assigned_grade"] == "US_NO_1"
    assert grading["limiting_factor"] == "NONE"

    response = api_client.recompute_protein_analysis(analysis["id"], INSPECTOR)
    restated = validate_success(response, 200)

    assert restated["basis_source"] == "OFFICIAL_MOISTURE"
    assert restated["moisture_source_pct"] == 12.8
    assert restated["protein_reported_pct"] == 34.52
    assert restated["basis_adjustment_pct"] == -0.08
    assert restated["status"] == "RECOMPUTED"
    assert restated["protein_pct_as_is"] == 34.60


def test_a_restated_analysis_cannot_be_restated_a_second_time():
    """Restatement is permitted only when a `FINAL` grading determination now
    exists on the request, the analysis's `status` is still `ACCEPTED`, and its
    `basis_source` is still `INSTRUMENT_MOISTURE`; any other combination is
    refused with `ERR_ANALYSIS_RECOMPUTE_NOT_APPLICABLE`.

    Design: Difficulty/dual_variant_calc/protein_basis_instrument_moisture_vs_official_moisture
    """
    office = _protein_office()
    staged = setup_sampled_request(
        office, requested_services=("GRADING", "PROTEIN"), portions_count=2
    )
    analysis = record_analysis(
        staged["request"]["id"],
        staged["sample"]["id"],
        office["instrument"]["id"],
        office["inspector"]["id"],
        protein_pct_as_is=34.60,
        instrument_moisture_pct=11.20,
    )
    record_grading(
        staged["request"]["id"],
        staged["sample"]["id"],
        office["inspector"]["id"],
        factors=CORN_NO_1_FACTORS_MOISTURE_12_8,
    )
    validate_success(
        api_client.recompute_protein_analysis(analysis["id"], INSPECTOR), 200
    )

    response = api_client.recompute_protein_analysis(analysis["id"], INSPECTOR)
    validate_error(response, ApiErrorId.ERR_ANALYSIS_RECOMPUTE_NOT_APPLICABLE.value, 422)

    unchanged = read_analysis(analysis["id"])
    assert unchanged["status"] == "RECOMPUTED"
    assert unchanged["protein_reported_pct"] == 34.52
