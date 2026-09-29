"""Pinned rounding order, threshold edges and the constants each formula reads."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_area,
    assert_decimals,
    assert_four_decimals,
    assert_index,
    assert_money,
    assert_pay_factor,
    assert_scenario_totals,
    assert_segment_condition,
    find_by,
)
from test_helpers.constants import (
    AREA_ELM,
    AREA_GRAND,
    AREA_MAPLE,
    AREA_OAK,
    BAND_FAILED,
    CRACK_SEAL,
    FUNDING_STANDARD,
    GRAND_CANDIDATE_COST,
    MAPLE_CANDIDATE_COST,
    MILL_AND_OVERLAY,
    OBS_CS75,
    OBS_CS75_DEDUCT,
    OBS_CS75_INDEX,
    OBS_MILL,
    OBS_MILL_DEDUCT,
    OBS_MILL_INDEX,
    OBS_RECON_INDEX,
    OAK_CANDIDATE_COST,
    PCI_MAPLE_MODEL,
    RECONSTRUCTION,
    SEG_CEDAR,
    SEG_ELM,
    SEG_MAPLE,
    SEG_OAK,
    SOURCE_MODEL_PROJECTED,
    SOURCE_SURVEY_MEASURED,
)
from test_helpers.test_users import ENGINEER, OFFICER

# ----------------------------------------------------------------------
# Coverage: the same physical distress imaged over half the block
# ----------------------------------------------------------------------
OBS_MILL_HALF_COVERAGE = dict(OBS_MILL, sample_coverage_pct=50.0)
HALF_COVERAGE_DEDUCT = 61.80
HALF_COVERAGE_INDEX = 38.2
MAPLE_CEDAR_HALF_NETWORK_INDEX = 53.7

# ----------------------------------------------------------------------
# A block that has failed on every distress at once
# ----------------------------------------------------------------------
OBS_TOTAL_FAILURE = {
    "alligator_cracking_sqft": 30000.0,
    "longitudinal_cracking_lf": 1000.0,
    "rutting_depth_in": 3.0,
    "patching_sqft": 30000.0,
    "iri_in_per_mi": 300.0,
    "sample_coverage_pct": 100.0,
}
TOTAL_FAILURE_DEDUCT = 201.40
TOTAL_FAILURE_INDEX = 0.0
FAILED_RECON_COST = 38444629
FAILED_RECON_GAIN = 100.0
FAILED_RECON_BCR = 26011.4098

# ----------------------------------------------------------------------
# The two-slope decay curve sampled either side of the eight-year knee
# ----------------------------------------------------------------------
TREATED_AGE_5 = "2021-08-01T00:00:00Z"
TREATED_AGE_8 = "2018-08-01T00:00:00Z"
TREATED_AGE_10 = "2016-08-01T00:00:00Z"
PCI_AGE_5 = 85.0
PCI_AGE_8 = 80.8
PCI_AGE_10 = 76.0
LOCAL_DECAY = 1.4
LOCAL_KNEE_DECAY = 1.0

# ----------------------------------------------------------------------
# Area weighting across a small local street and a wide arterial
# ----------------------------------------------------------------------
MAPLE_GRAND_NETWORK_INDEX = 37.8
UNWEIGHTED_MEAN_INDEX = 49.55

# ----------------------------------------------------------------------
# The no-treatment ceiling, straddled by one tenth of a point
# ----------------------------------------------------------------------
OBS_CEILING = {
    "alligator_cracking_sqft": 0.0,
    "longitudinal_cracking_lf": 0.0,
    "rutting_depth_in": 0.5,
    "patching_sqft": 0.0,
    "iri_in_per_mi": 95.0,
    "sample_coverage_pct": 100.0,
}
OBS_BELOW_CEILING = dict(OBS_CEILING, iri_in_per_mi=96.25)
CEILING_DEDUCT = 10.00
CEILING_INDEX = 90.0
BELOW_CEILING_DEDUCT = 10.10
BELOW_CEILING_INDEX = 89.9
BELOW_CEILING_CANDIDATE_COST = 1486665
CEILING_NETWORK_INDEX = 90.0

# ----------------------------------------------------------------------
# Benefit-cost arithmetic on a crack-seal candidate with 25 points of headroom
# ----------------------------------------------------------------------
CRACK_SEAL_LIFE_YEARS = 5
CRACK_SEAL_GAIN_CAP = 8.0
OAK_CRACK_SEAL_BCR = 10195.7076
OAK_UNCAPPED_BCR = 31861.5862

# ----------------------------------------------------------------------
# A pay factor whose three components are all inside tolerance
# ----------------------------------------------------------------------
IN_TOLERANCE_DENSITY_PCT = 94.0
IN_TOLERANCE_IRI = 120.0
IN_TOLERANCE_THICKNESS_IN = 1.8
IN_TOLERANCE_PAY_FACTOR = 0.9126
PAY_FACTOR_CAP = 1.02

# ----------------------------------------------------------------------
# The service-level deadline and the instant either side of it
# ----------------------------------------------------------------------
SLA_DUE_HIGH = "2026-08-04T00:00:00"
SLA_DUE_MEDIUM = "2026-08-08T00:00:00"
CLOCK_ON_THE_DEADLINE = "2026-08-04T00:00:00Z"
CLOCK_ONE_SECOND_LATE = "2026-08-04T00:00:01Z"

# ----------------------------------------------------------------------
# Two strategies over one candidate pool
# ----------------------------------------------------------------------
MAPLE_MILL_BCR = 14381.0110
GRAND_RECON_BCR = 11809.3631
STRATEGY_BENEFIT_COST = "BENEFIT_COST"


# ----------------------------------------------------------------------
# Segment geometry
# ----------------------------------------------------------------------


def test_area_rounds_half_up_at_the_third_decimal_in_both_directions(api):
    """One foot of extra length flips the third decimal from discarded to carried.

    PRD: "Creation computes the segment's `area_sy`: the length in feet multiplied by
    the width in feet, divided by the nine square feet that make up one square yard,
    rounded to two decimal places."

    PRD: "Every rounding operation in this specification is round-half-up."

    1000.00 x 30.00 / 9 is 3333.3333... and publishes 3333.33, while 1001.00 x 30.00 /
    9 is 3336.6666... and publishes 3336.67.

    Design: Corner/calculations/segment_area_sy_rounds_half_up_at_the_third_decimal
    """
    fixtures.set_clock(api)

    maple = fixtures.create_segment(api, SEG_MAPLE)
    elm = fixtures.create_segment(api, SEG_ELM)

    assert_area(maple["area_sy"], AREA_MAPLE)
    assert_area(elm["area_sy"], AREA_ELM)
    assert_area(fixtures.read_segment(api, maple["id"])["area_sy"], AREA_MAPLE)
    assert_area(fixtures.read_segment(api, elm["id"])["area_sy"], AREA_ELM)
    assert_index(maple["condition_index"], PCI_MAPLE_MODEL)
    assert_index(elm["condition_index"], PCI_MAPLE_MODEL)


# ----------------------------------------------------------------------
# Distress arithmetic: the coverage factor and the clamp
# ----------------------------------------------------------------------


def _same_distress_at_full_and_half_coverage(api):
    """Two identical blocks, identical readings, one imaged over half its length."""
    plan = [(SEG_MAPLE, OBS_MILL), (SEG_CEDAR, OBS_MILL_HALF_COVERAGE)]
    return fixtures.survey_with_candidates(api, plan)


def test_halving_the_imaged_coverage_doubles_the_published_deduct(api):
    """The coverage factor divides into the coverage, so 50 per cent scales by 2.0000.

    PRD: "A coverage factor scales the raw deduct up for partial imaging: it is 100
    divided by `sample_coverage_pct`, rounded to four decimal places. The stored
    `deduct_total` is the raw deduct multiplied by that coverage factor, rounded to two
    decimal places."

    PRD: "Rounding the weighted sum before the coverage scale-up produces a different
    number and is wrong."

    Design: Corner/calculations/measured_index_coverage_factor_doubles_the_deduct_at_fifty_percent_coverage
    """
    ctx = _same_distress_at_full_and_half_coverage(api)
    full = ctx["observations"]["Maple St"]
    half = ctx["observations"]["Cedar St"]

    assert_decimals(full["deduct_total"], 2, "deduct_total")
    assert full["deduct_total"] == OBS_MILL_DEDUCT
    assert_index(full["measured_condition_index"], OBS_MILL_INDEX)
    assert_decimals(half["deduct_total"], 2, "deduct_total")
    assert half["deduct_total"] == HALF_COVERAGE_DEDUCT
    assert_index(half["measured_condition_index"], HALF_COVERAGE_INDEX)
    assert_area(
        fixtures.read_segment(api, fixtures.segment_for(ctx, "Cedar St")["id"])["area_sy"],
        AREA_MAPLE,
    )


def test_the_coverage_penalty_pushes_the_same_readings_two_treatment_tiers_down(api):
    """Identical field data, but 38.2 falls under the overlay floor and 69.1 does not.

    PRD: "Treatment follows from the snapshot: an index of at least 70.0 selects
    `CRACK_SEAL`, an index below 70.0 but at least 40.0 selects `MILL_AND_OVERLAY`, and
    an index below 40.0 selects `RECONSTRUCTION`."

    PRD: "Candidates are generated worst-first: ordered by the segment's
    `condition_index` ascending, with ties broken by the segment's `created_at`
    ascending."

    PRD: "Sealing stamps `sealed_at` with the logical clock and computes
    `network_condition_index` as the area-weighted mean measured index over the
    accepted observations: for each accepted observation, multiply its segment's
    `area_sy` by the observation's `measured_condition_index`; sum those products;
    divide by the sum of the same segments' `area_sy`; round to one decimal place."

    Design: Corner/calculations/measured_index_coverage_factor_doubles_the_deduct_at_fifty_percent_coverage
    """
    ctx = _same_distress_at_full_and_half_coverage(api)

    worst = ctx["candidate_list"][0]
    cedar = fixtures.candidate_for(ctx, "Cedar St")
    maple = fixtures.candidate_for(ctx, "Maple St")

    assert worst["id"] == cedar["id"]
    assert cedar["treatment_type"] == RECONSTRUCTION
    assert_index(cedar["selection_condition_index"], HALF_COVERAGE_INDEX)
    assert maple["treatment_type"] == MILL_AND_OVERLAY
    assert_index(maple["selection_condition_index"], OBS_MILL_INDEX)
    assert_index(
        ctx["survey"]["network_condition_index"], MAPLE_CEDAR_HALF_NETWORK_INDEX
    )


def _a_block_that_failed_on_every_distress(api):
    """One segment whose raw deduct alone exceeds a hundred points."""
    return fixtures.survey_with_candidates(api, [(SEG_MAPLE, OBS_TOTAL_FAILURE)])


def test_the_index_floors_at_zero_while_the_deduct_publishes_its_true_total(api):
    """The clamp is on the index alone: 201.40 of deduct is reported in full.

    PRD: "Finally `measured_condition_index` is 100 less the `deduct_total`, clamped
    into the range 0.0 through 100.0 and rounded to one decimal place."

    PRD: "Whatever wrote it, `condition_index` is immediately banded into
    `condition_band`: `GOOD` when the index is at least 70.0, `FAIR` when it is at
    least 50.0 but below 70.0, `POOR` when it is at least 25.0 but below 50.0, and
    `FAILED` when it is below 25.0."

    Design: Corner/calculations/measured_index_clamps_at_zero_when_the_deduct_exceeds_one_hundred
    """
    ctx = _a_block_that_failed_on_every_distress(api)
    observation = ctx["observations"]["Maple St"]

    assert observation["deduct_total"] == TOTAL_FAILURE_DEDUCT
    assert_index(observation["measured_condition_index"], TOTAL_FAILURE_INDEX)
    assert_index(ctx["survey"]["network_condition_index"], TOTAL_FAILURE_INDEX)
    assert_segment_condition(
        fixtures.read_segment(api, fixtures.segment_for(ctx, "Maple St")["id"]),
        TOTAL_FAILURE_INDEX,
        SOURCE_SURVEY_MEASURED,
        BAND_FAILED,
    )


def test_a_failed_snapshot_prices_the_reconstruction_with_the_full_penalty(api):
    """The clamped 0.0 is a live number: it bands FAILED and bills the 1.12 uplift.

    PRD: "The condition penalty recognises that badly broken pavement needs more repair
    before the new surface goes down: it is 1.12 when the snapshot index bands as
    `FAILED`, 1.05 when it bands as `POOR`, and 1.00 otherwise, using the same band
    thresholds as §2.7 applied to `selection_condition_index`."

    PRD: "The candidate's `estimated_cost_cents` is then the segment's `area_sy`
    multiplied by the base rate, then by the width factor, then by the condition
    penalty, all at full precision, with that single product rounded once to whole
    cents — and only *after* that rounding is a mobilisation charge added: 250,000 cents
    ($2,500) for crack seal, and 850,000 cents ($8,500) for either mill-and-overlay or
    reconstruction."

    3333.33 square yards at 9,500 cents, with the 1.0600 width factor and the 1.12
    penalty, rounds to 37,594,629 cents before the 850,000-cent mobilisation.

    Design: Corner/calculations/measured_index_clamps_at_zero_when_the_deduct_exceeds_one_hundred
    """
    ctx = _a_block_that_failed_on_every_distress(api)
    candidate = fixtures.candidate_for(ctx, "Maple St")

    assert candidate["treatment_type"] == RECONSTRUCTION
    assert_index(candidate["selection_condition_index"], TOTAL_FAILURE_INDEX)
    assert_index(candidate["treatment_pci_gain"], FAILED_RECON_GAIN)
    assert_money(candidate["estimated_cost_cents"], FAILED_RECON_COST)
    assert_four_decimals(candidate["benefit_cost_ratio"], FAILED_RECON_BCR)


# ----------------------------------------------------------------------
# The deterioration model
# ----------------------------------------------------------------------


def test_the_knee_coefficient_charges_only_the_years_past_the_eighth(api):
    """Three identical blocks of different ages trace the piecewise curve exactly.

    PRD: "Age in whole years is the number of whole days from the anchor date to the
    evaluation instant, divided by 365, with any fraction discarded."

    PRD: "An `ARTERIAL` segment loses 2.2 points per year with a further 1.6 after the
    knee; a `COLLECTOR` loses 1.8 with a further 1.3; a `LOCAL` loses 1.4 with a
    further 1.0. The knee falls at 8 years of age."

    PRD: "The projected index is therefore the `baseline_condition_index`, reduced by
    the pre-knee rate multiplied by the age in years, and reduced again by the knee
    rate multiplied by the number of years of age beyond 8 (which is zero for any
    segment younger than the knee), then clamped into the range 0.0 through 100.0 and
    rounded to one decimal place."

    The losses come out 7.0, 11.2 and 16.0: three years from age five to age eight cost
    4.2 points while two years from eight to ten cost 4.8.

    Design: Corner/calculations/model_projected_index_applies_the_knee_coefficient_only_past_eight_years
    """
    fixtures.set_clock(api)

    young = fixtures.create_segment(api, SEG_MAPLE, last_treatment_date=TREATED_AGE_5)
    at_knee = fixtures.create_segment(api, SEG_CEDAR, last_treatment_date=TREATED_AGE_8)
    older = fixtures.create_segment(
        api, SEG_MAPLE, street_name="Oak St", last_treatment_date=TREATED_AGE_10
    )

    for segment, index in ((young, PCI_AGE_5), (at_knee, PCI_AGE_8), (older, PCI_AGE_10)):
        assert_segment_condition(segment, index, SOURCE_MODEL_PROJECTED)
        assert segment["decay_coefficient"] == LOCAL_DECAY
        assert segment["decay_knee_coefficient"] == LOCAL_KNEE_DECAY


# ----------------------------------------------------------------------
# Aggregation over the network
# ----------------------------------------------------------------------


def test_the_network_index_weights_by_pavement_area_not_by_segment_count(api):
    """A wide broken arterial dominates a small local street four square yards to one.

    PRD: "Sealing stamps `sealed_at` with the logical clock and computes
    `network_condition_index` as the area-weighted mean measured index over the
    accepted observations: for each accepted observation, multiply its segment's
    `area_sy` by the observation's `measured_condition_index`; sum those products;
    divide by the sum of the same segments' `area_sy`; round to one decimal place."

    An unweighted mean of 69.1 and 30.0 would publish 49.55 and flatter the network by
    close to twelve points.

    Design: Corner/calculations/network_condition_index_is_area_weighted_not_a_segment_average
    """
    ctx = fixtures.sealed_survey(api, fixtures.MAPLE_AND_GRAND)
    sealed = ctx["survey"]

    assert_index(ctx["observations"]["Maple St"]["measured_condition_index"], OBS_MILL_INDEX)
    assert_index(ctx["observations"]["Grand Blvd"]["measured_condition_index"], OBS_RECON_INDEX)
    assert_area(fixtures.read_segment(api, fixtures.segment_for(ctx, "Maple St")["id"])["area_sy"], AREA_MAPLE)
    assert_area(fixtures.read_segment(api, fixtures.segment_for(ctx, "Grand Blvd")["id"])["area_sy"], AREA_GRAND)
    assert_index(sealed["network_condition_index"], MAPLE_GRAND_NETWORK_INDEX)
    assert sealed["network_condition_index"] != UNWEIGHTED_MEAN_INDEX
    assert sealed["accepted_observation_count"] == 2
    for street in ("Maple St", "Grand Blvd"):
        segment = fixtures.read_segment(api, fixtures.segment_for(ctx, street)["id"])
        assert segment["condition_index_source"] == SOURCE_SURVEY_MEASURED


# ----------------------------------------------------------------------
# Treatment selection at the healthy end of the scale
# ----------------------------------------------------------------------


def test_a_block_at_exactly_the_ceiling_produces_no_candidate_at_all(api):
    """90.0 is outside the pool entirely while 89.9 buys a 1,486,665-cent crack seal.

    PRD: "The eligible pool is the set of segments that have an `ACCEPTED` observation
    on this survey and whose `condition_index` is below the no-treatment ceiling of
    90.0. Segments whose only observation was flagged or rejected are not in the pool,
    and a segment at exactly 90.0 yields no candidate at all."

    PRD: "Crack seal runs 350 cents per square yard on a `LOCAL` street, 420 on a
    `COLLECTOR` and 500 on an `ARTERIAL`."

    Design: Corner/calculations/treatment_selection_at_the_no_treatment_ceiling_yields_no_candidate_at_all
    """
    plan = [(SEG_MAPLE, OBS_CEILING), (SEG_CEDAR, OBS_BELOW_CEILING)]
    ctx = fixtures.survey_with_candidates(api, plan)
    at_ceiling = ctx["observations"]["Maple St"]
    below = ctx["observations"]["Cedar St"]

    assert at_ceiling["deduct_total"] == CEILING_DEDUCT
    assert_index(at_ceiling["measured_condition_index"], CEILING_INDEX)
    assert below["deduct_total"] == BELOW_CEILING_DEDUCT
    assert_index(below["measured_condition_index"], BELOW_CEILING_INDEX)
    assert_index(ctx["survey"]["network_condition_index"], CEILING_NETWORK_INDEX)

    rows, meta = validate_paginated(
        api.list_candidates(ENGINEER, {"survey_id": ctx["survey"]["id"], "limit": 100})
    )
    only = ctx["candidate_list"][0]
    assert len(ctx["candidate_list"]) == 1
    assert meta["total_count"] == 1
    assert only["segment_id"] == fixtures.segment_for(ctx, "Cedar St")["id"]
    assert rows[0]["id"] == only["id"]
    assert only["treatment_type"] == CRACK_SEAL
    assert_index(only["selection_condition_index"], BELOW_CEILING_INDEX)
    assert_money(only["estimated_cost_cents"], BELOW_CEILING_CANDIDATE_COST)


# ----------------------------------------------------------------------
# Benefit-cost arithmetic
# ----------------------------------------------------------------------


def test_the_benefit_ratio_reads_the_capped_gain_not_the_headroom_to_one_hundred(api):
    """Twenty-five points of headroom, but crack seal is only ever worth eight.

    PRD: "Its `treatment_pci_gain` is the smaller of the treatment's gain cap — 8.0
    points for crack seal, 45.0 for mill-and-overlay, 100.0 for reconstruction — and
    the headroom actually available, which is 100 less the `selection_condition_index`,
    rounded to one decimal place."

    PRD: "The benefit quantity is that gain multiplied by the expected service life in
    years and again by the segment's `area_sy`, rounded to two decimal places. The cost
    is restated in thousands of dollars by dividing `estimated_cost_cents` by 100,000,
    with mobilisation included. The stored `benefit_cost_ratio` is the benefit quantity
    divided by that cost in thousands, rounded to four decimal places."

    8.0 points over 5 years across 11725.00 square yards is 469,000.00 benefit units
    against 45.99975 thousand dollars; the uncapped 25.0 would have published a figure
    three times larger.

    Design: Corner/calculations/benefit_cost_ratio_uses_the_capped_gain_not_the_raw_gap_to_one_hundred
    """
    ctx = fixtures.survey_with_candidates(api, [(SEG_OAK, OBS_CS75)])
    observation = ctx["observations"]["Oak St"]
    candidate = fixtures.candidate_for(ctx, "Oak St")

    assert observation["deduct_total"] == OBS_CS75_DEDUCT
    assert_index(observation["measured_condition_index"], OBS_CS75_INDEX)
    assert_area(fixtures.read_segment(api, fixtures.segment_for(ctx, "Oak St")["id"])["area_sy"], AREA_OAK)
    assert candidate["treatment_type"] == CRACK_SEAL
    assert_index(candidate["selection_condition_index"], OBS_CS75_INDEX)
    assert candidate["expected_service_life_years"] == CRACK_SEAL_LIFE_YEARS
    assert_index(candidate["treatment_pci_gain"], CRACK_SEAL_GAIN_CAP)
    assert_money(candidate["estimated_cost_cents"], OAK_CANDIDATE_COST)
    assert_four_decimals(candidate["benefit_cost_ratio"], OAK_CRACK_SEAL_BCR)
    assert candidate["benefit_cost_ratio"] != OAK_UNCAPPED_BCR


# ----------------------------------------------------------------------
# Pay factors
# ----------------------------------------------------------------------


def _a_core_inside_every_tolerance(api):
    """One test whose density, smoothness and thickness all sit in a non-zero band."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.in_construction_project(api, ctx, fixtures.MAPLE_LINE)
    submitted = fixtures.submit_test(
        api,
        ctx["lines"]["Maple St"]["id"],
        core_density_pct=IN_TOLERANCE_DENSITY_PCT,
        iri_in_per_mi=IN_TOLERANCE_IRI,
        thickness_in=IN_TOLERANCE_THICKNESS_IN,
    )
    return ctx, submitted


def test_three_in_tolerance_components_still_multiply_below_the_pass_floor(api):
    """No component scored zero, yet the product lands under 0.95 and the outcome fails.

    PRD: "The density factor is 1.00 when `core_density_pct` is at least 96.0, 0.98
    when it is at least 94.0, 0.95 when it is at least 92.0, and 0.00 below that. The
    smoothness factor is 1.02 when `iri_in_per_mi` is at most 60.0, 1.00 when it is at
    most 95.0, 0.97 when it is at most 120.0, and 0.00 above that. The thickness factor
    is 1.00 when `thickness_in` is at least the line's `design_thickness_in`, 0.96 when
    it is at least the design thickness less the 0.25-inch tolerance, and 0.00 below
    that."

    PRD: "Otherwise `computed_pay_factor` is the product of the three factors, capped
    at 1.02, rounded to four decimal places — the cap applies after multiplication, so
    a test with bonus smoothness, full density and full thickness yields exactly 1.0200
    — and `computed_outcome` is `PASS` when the pay factor is at least 0.95 and `FAIL`
    otherwise."

    0.98 times 0.97 times 0.96 is 0.912576, which publishes 0.9126 — nowhere near the
    1.02 cap, so the cap cannot be what produced it.

    Design: Corner/calculations/pay_factor_multiplies_three_live_components_and_still_lands_below_the_pass_floor
    """
    _ctx, submitted = _a_core_inside_every_tolerance(api)

    assert_pay_factor(submitted, IN_TOLERANCE_PAY_FACTOR, "FAIL")
    assert submitted["computed_pay_factor"] < PAY_FACTOR_CAP
    assert submitted["test_round"] == 1
    assert submitted["test_status"] == "SUBMITTED"


def test_submitting_a_failing_core_publishes_nothing_to_the_line_yet(api):
    """Submission computes the factor and counts the test; only a decision publishes it.

    PRD: "Every test starts with `test_status` `SUBMITTED`, `decided_by_user_id` null
    and `decision_note` null, and each submission increments the line's `test_count`."

    PRD: "A line's `pay_factor` always reflects the decided test with the highest
    `test_round` on that line, whether that test passed or failed, and is null until
    some test on the line has been decided."

    PRD: "The first test submitted anywhere on a project moves the project's
    `quality_status` from `NOT_STARTED` to `TESTING`, leaving `delivery_status`
    untouched — the two dimensions advance independently — and if the project's quality
    had bounced to `REMEDIATION_REQUIRED`, it returns to `TESTING` once
    `open_remediation_count` reaches zero again."

    Design: Corner/calculations/pay_factor_multiplies_three_live_components_and_still_lands_below_the_pass_floor
    """
    ctx, submitted = _a_core_inside_every_tolerance(api)

    line = fixtures.read_line(api, ctx["lines"]["Maple St"]["id"])
    project = fixtures.read_project(api, ctx["project"]["id"])
    assert submitted["decided_by_user_id"] is None
    assert submitted["decision_note"] is None
    assert line["work_state"] == "IN_PROGRESS"
    assert line["pay_factor"] is None
    assert line["test_count"] == 1
    assert project["quality_status"] == "TESTING"
    assert project["delivery_status"] == "IN_CONSTRUCTION"


# ----------------------------------------------------------------------
# The service-level deadline
# ----------------------------------------------------------------------


def _an_open_high_severity_complaint(api):
    """A HIGH pothole filed at 2026-08-01 and deliberately left in NEW."""
    fixtures.set_clock(api)
    segment = fixtures.create_segment(api)
    request = fixtures.file_service_request(
        api, segment["id"], location_note="deep pothole outside 214 Maple St"
    )
    assert request["request_status"] == "NEW"
    assert request["sla_due_at"].startswith(SLA_DUE_HIGH)
    return segment, request


def test_the_clock_landing_exactly_on_the_deadline_is_not_a_breach(api):
    """One second later the same untouched row flips, with no write in between.

    PRD: "The `sla_breached` flag compares a reference instant against that deadline —
    the reference is `closed_at` once the request has reached a closed state, and the
    logical clock while it is still open — and is true only when the reference is
    *strictly* later than `sla_due_at`; landing exactly on the deadline is not a
    breach."

    PRD: "The flag is re-evaluated on every read and again at closure."

    Design: Corner/calculations/service_request_sla_equality_is_not_a_breach_but_one_second_later_is
    """
    _segment, request = _an_open_high_severity_complaint(api)

    fixtures.set_clock(api, CLOCK_ON_THE_DEADLINE)
    on_time = validate_success(api.get_service_request(request["id"], ENGINEER))
    fixtures.set_clock(api, CLOCK_ONE_SECOND_LATE)
    late = validate_success(api.get_service_request(request["id"], ENGINEER))

    assert on_time["sla_breached"] is False
    assert late["sla_breached"] is True
    assert on_time["sla_due_at"] == late["sla_due_at"]
    assert on_time["request_status"] == "NEW"
    assert late["request_status"] == "NEW"
    assert on_time["closed_at"] is None
    assert late["closed_at"] is None


def test_the_deadline_comes_from_the_severity_table_and_not_a_global_default(api):
    """A MEDIUM complaint filed at the same instant gets 168 hours, not 72.

    PRD: "`sla_due_at` is the request's `created_at` plus the response allowance for its
    severity: 72 hours for `HIGH`, 168 hours for `MEDIUM`, and 720 hours for `LOW`."

    Design: Corner/calculations/service_request_sla_equality_is_not_a_breach_but_one_second_later_is
    """
    segment, high = _an_open_high_severity_complaint(api)

    medium = fixtures.file_service_request(
        api,
        segment["id"],
        reported_severity="MEDIUM",
        location_note="ponding at the 1300 block crosswalk",
    )

    assert high["sla_due_at"].startswith(SLA_DUE_HIGH)
    assert medium["sla_due_at"].startswith(SLA_DUE_MEDIUM)
    assert medium["sla_breached"] is False


# ----------------------------------------------------------------------
# The budget waterfall under two strategies
# ----------------------------------------------------------------------


def _one_pool_two_strategies(api):
    """A worst-first run and a benefit-cost run over the same two candidates."""
    ctx = fixtures.survey_with_candidates(api, fixtures.MAPLE_AND_GRAND)
    worst_first = fixtures.create_scenario(
        api, ctx["survey"]["id"], scenario_name="Worst first", funding_cents=FUNDING_STANDARD
    )
    benefit_cost = fixtures.create_scenario(
        api,
        ctx["survey"]["id"],
        scenario_name="Benefit cost",
        funding_cents=FUNDING_STANDARD,
        strategy=STRATEGY_BENEFIT_COST,
    )
    ran_worst_first = fixtures.run_scenario(api, worst_first["id"])
    ran_benefit_cost = fixtures.run_scenario(api, benefit_cost["id"])
    return ctx, ran_worst_first, ran_benefit_cost


def _allocations(api, scenario_id):
    rows, _meta = validate_paginated(
        api.list_allocations(OFFICER, {"scenario_id": scenario_id, "limit": 100})
    )
    return rows


def test_benefit_cost_reranks_the_same_pool_without_moving_a_single_cent(api):
    """Mirror-image ranks, identical money: only the order of the queue changed.

    PRD: "Under `WORST_FIRST`, candidates sort by `selection_condition_index`
    ascending, ties broken by segment `area_sy` descending, then by candidate
    `created_at` ascending. Under `BENEFIT_COST`, candidates sort by
    `benefit_cost_ratio` descending, ties broken by `estimated_cost_cents` ascending,
    then `created_at` ascending."

    PRD: "Critically, **the scan does not stop at the first candidate that does not
    fit**: a later, cheaper candidate that still fits within the remaining balance is
    funded."

    PRD: "A `rank` of 1 goes to the first pool member and increments for *every* pool
    member, funded or not."

    Design: Corner/calculations/waterfall_benefit_cost_strategy_reranks_the_identical_candidate_pool
    """
    ctx, worst_first, benefit_cost = _one_pool_two_strategies(api)
    mill = fixtures.candidate_for(ctx, "Maple St")
    recon = fixtures.candidate_for(ctx, "Grand Blvd")
    assert_four_decimals(mill["benefit_cost_ratio"], MAPLE_MILL_BCR)
    assert_four_decimals(recon["benefit_cost_ratio"], GRAND_RECON_BCR)

    worst_rows = _allocations(api, worst_first["id"])
    benefit_rows = _allocations(api, benefit_cost["id"])

    worst_mill = find_by(worst_rows, "candidate_id", mill["id"])
    benefit_mill = find_by(benefit_rows, "candidate_id", mill["id"])
    benefit_recon = find_by(benefit_rows, "candidate_id", recon["id"])
    assert worst_mill["rank"] == 2
    assert worst_mill["allocation_status"] == "FUNDED"
    assert benefit_mill["rank"] == 1
    assert benefit_mill["allocation_status"] == "FUNDED"
    assert_money(benefit_mill["allocated_cents"], MAPLE_CANDIDATE_COST)
    assert benefit_recon["rank"] == 2
    assert benefit_recon["allocation_status"] == "DEFERRED"
    assert_money(benefit_recon["allocated_cents"], 0)
    assert_scenario_totals(
        worst_first, 2, MAPLE_CANDIDATE_COST, GRAND_CANDIDATE_COST
    )
    assert_scenario_totals(
        benefit_cost, 2, MAPLE_CANDIDATE_COST, GRAND_CANDIDATE_COST
    )
    assert worst_first["scenario_status"] == "COMPUTED"
    assert benefit_cost["scenario_status"] == "COMPUTED"


# ----------------------------------------------------------------------
# Two cut-permit constants biting on the same small trench
# ----------------------------------------------------------------------
SMALL_CUT_SQFT = 50.0
LARGE_CUT_SQFT = 200.0
MIN_FEE_CENTS = 45000
LARGE_CUT_FEE_CENTS = 170000
BOTTOM_MULTIPLIER = 1.0
NO_MORATORIUM_DAYS = 0
ROUTINE_WINDOW = ("2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z")
EMERGENCY_WINDOW = ("2026-08-07T00:00:00Z", "2026-08-08T00:00:00Z")
LARGE_WINDOW = ("2026-08-09T00:00:00Z", "2026-08-10T00:00:00Z")


def test_the_minimum_fee_floor_and_the_clamped_relief_land_on_the_same_amount(api):
    """A fifty square foot trench pays the floor whether or not it is an emergency.

    PRD: "First, `moratorium_remaining_days` is zero when the segment's
    `moratorium_until` is null; otherwise it is the whole seconds from the logical clock
    to `moratorium_until` divided by the 86,400 seconds in a day with the fraction
    discarded, floored at zero."

    PRD: "Second, a tier multiplier follows from that remaining count: 3.0 when at
    least 1,096 days remain, 2.0 when at least 366 remain, 1.5 when at least 1 remains,
    and 1.0 when none remains."

    PRD: "Third, an emergency application gets relief of half a point off the tier
    multiplier, floored at 1.0, and the result is stored as `fee_multiplier`; a
    non-emergency application stores the tier multiplier unchanged."

    PRD: "Fourth, the base fee is the trench area multiplied by 850 cents per square
    foot, rounded to whole cents, but never less than the 45,000-cent ($450) minimum."

    PRD: "`degradation_fee_cents` is that base fee multiplied by `fee_multiplier`,
    rounded to whole cents."

    PRD: "When the segment's `moratorium_until` is null, or has already passed the
    logical clock, or when the application is flagged as an emergency, the permit opens
    at `permit_status` `PENDING`."

    A two hundred square foot trench under identical conditions clears the floor, so the
    matching fees on the small cuts are the floor at work and not a flat tariff.

    Design: Corner/calculations/cut_permit_fee_uses_the_minimum_base_and_floors_the_emergency_relief_at_one
    """
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_ONLY)
    ctx = fixtures.coordinating_project(api, ctx)
    segment_id = fixtures.segment_for(ctx, "Maple St")["id"]
    assert fixtures.read_segment(api, segment_id)["moratorium_until"] is None

    routine = fixtures.apply_cut_permit(
        api,
        segment_id,
        applicant_utility="WATER",
        requested_start=ROUTINE_WINDOW[0],
        requested_end=ROUTINE_WINDOW[1],
        cut_area_sqft=SMALL_CUT_SQFT,
        emergency=False,
    )
    assert routine["moratorium_remaining_days"] == NO_MORATORIUM_DAYS
    assert_decimals(routine["fee_multiplier"], 1, "fee_multiplier")
    assert routine["fee_multiplier"] == BOTTOM_MULTIPLIER
    assert_money(routine["degradation_fee_cents"], MIN_FEE_CENTS)
    assert routine["permit_status"] == "PENDING"

    emergency = fixtures.apply_cut_permit(
        api,
        segment_id,
        applicant_utility="SEWER",
        requested_start=EMERGENCY_WINDOW[0],
        requested_end=EMERGENCY_WINDOW[1],
        cut_area_sqft=SMALL_CUT_SQFT,
        emergency=True,
    )
    assert emergency["moratorium_remaining_days"] == NO_MORATORIUM_DAYS
    assert_decimals(emergency["fee_multiplier"], 1, "fee_multiplier")
    assert emergency["fee_multiplier"] == BOTTOM_MULTIPLIER
    assert_money(emergency["degradation_fee_cents"], MIN_FEE_CENTS)
    assert emergency["permit_status"] == "PENDING"

    large = fixtures.apply_cut_permit(
        api,
        segment_id,
        applicant_utility="FRANCHISE_GAS",
        requested_start=LARGE_WINDOW[0],
        requested_end=LARGE_WINDOW[1],
        cut_area_sqft=LARGE_CUT_SQFT,
        emergency=False,
    )
    assert large["fee_multiplier"] == BOTTOM_MULTIPLIER
    assert_money(large["degradation_fee_cents"], LARGE_CUT_FEE_CENTS)
