"""Scoring and reporting: weighted math, variants, suppression, benchmarks, sampling."""
import pytest

from test_helpers import (
    ApiErrorId,
    configure_cycle,
    get_cycle,
    get_direct_snapshot,
    get_success_data,
    make_active_bank,
    make_cycle,
    make_employee,
    make_unit,
    pin_items,
    api_client,
    set_clock,
    setup_cycle_with_field_results,
    open_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.factories import create_benchmark_set_payload

HR_ADMIN = TEST_USERS["hr_admin_headers"]
PEOPLE_ANALYST = TEST_USERS["people_analyst_headers"]

DUAL_ITEM_SPECS = [
    {"item_code": "D-01", "dimension": "PURPOSE", "weight": 1.5},
    {"item_code": "D-02", "dimension": "GROWTH", "weight": 1.0},
    {"item_code": "D-03", "dimension": "PURPOSE", "weight": 2.0},
]
DUAL_ANSWERS = [[5, 4, 3]] * 5

ROUNDING_ITEM_SPECS = [
    {"item_code": "RD-01", "dimension": "PURPOSE", "weight": 0.3},
    {"item_code": "RD-02", "dimension": "GROWTH", "weight": 0.7},
    {"item_code": "RD-03", "dimension": "BELONGING", "weight": 1.1},
]
ROUNDING_ANSWERS = [[5, 5, 5], [1, 1, 1], [4, 2, 5]]


def test_census_scoring_applies_stored_pinned_weights(api):
    """PRD §3.5: "For a `PULSE` cycle every pinned weight is treated as 1.0
    regardless of the stored value, so identical answers yield a different
    overall score under pulse scoring than under census scoring, where the
    stored per-item weights apply."
    PRD §3.5: "A dimension's score is the sum of those 4-decimal products over
    all answers belonging to items of that dimension, divided by the sum of the
    pinned weights of that dimension's items — the weight denominator counted
    once per submitted respondent — rounded half-up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/engagement_score_census_vs_pulse_identical_answers
    """
    sc = setup_cycle_with_field_results(
        bank_name="CensusVar", item_specs=DUAL_ITEM_SPECS,
        unit_name="CensusVarU", manager_user_id="mgr-cv",
        min_n_threshold=5, num_employees=5, cycle_kind="CENSUS",
        target_state="SCORING", submitters=5, submit_scores=DUAL_ANSWERS,
    )
    snap = get_direct_snapshot(sc["cycle"]["id"], sc["unit"]["id"])
    assert snap["submitted_n"] == 5
    assert snap["overall_score"] == pytest.approx(72.22, abs=0.005), (
        "census variant: 325.0000 weighted / 4.5 per respondent -> 72.22"
    )
    assert snap["dimension_scores"]["PURPOSE"] == pytest.approx(71.43, abs=0.005)
    assert snap["dimension_scores"]["GROWTH"] == pytest.approx(75.00, abs=0.005)


def test_pulse_scoring_treats_all_pinned_weights_as_one(api):
    """PRD §3.5: "For a `PULSE` cycle every pinned weight is treated as 1.0
    regardless of the stored value, so identical answers yield a different
    overall score under pulse scoring than under census scoring, where the
    stored per-item weights apply."

    Design: Difficulty/dual_variant_calc/engagement_score_census_vs_pulse_identical_answers
    """
    sc = setup_cycle_with_field_results(
        bank_name="PulseVar", item_specs=DUAL_ITEM_SPECS,
        unit_name="PulseVarU", manager_user_id="mgr-pv",
        min_n_threshold=5, num_employees=5, cycle_kind="PULSE", sampling_ratio=1.0,
        cycle_label="Pulse", target_state="SCORING",
        submitters=5, submit_scores=DUAL_ANSWERS,
    )
    snap = get_direct_snapshot(sc["cycle"]["id"], sc["unit"]["id"])
    assert snap["submitted_n"] == 5
    assert snap["overall_score"] == pytest.approx(75.00, abs=0.005), (
        "pulse variant: weights flattened to 1.0 -> identical answers score 75.00, "
        "not the census-weighted 72.22"
    )
    assert snap["dimension_scores"]["PURPOSE"] == pytest.approx(75.00, abs=0.005)
    assert snap["dimension_scores"]["GROWTH"] == pytest.approx(75.00, abs=0.005)


def test_dimension_scores_built_from_4dp_products(api):
    """PRD §3.5: "For each answer of each submitted invitation in scope, the
    raw `score` from 1 to 5 is first rescaled onto a 0-to-100 scale by
    subtracting 1 and multiplying by 25; the rescaled value is then multiplied
    by the pinned weight of the answered item, and that per-answer product is
    rounded half-up to 4 decimal places. A dimension's score is the sum of
    those 4-decimal products over all answers belonging to items of that
    dimension, divided by the sum of the pinned weights of that dimension's
    items — the weight denominator counted once per submitted respondent —
    rounded half-up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/engagement_score_nested_rounding_order
    """
    sc = setup_cycle_with_field_results(
        bank_name="RoundDim", item_specs=ROUNDING_ITEM_SPECS,
        unit_name="RoundDimU", manager_user_id="mgr-rd",
        min_n_threshold=3, num_employees=3, cycle_kind="CENSUS",
        target_state="SCORING", submitters=3, submit_scores=ROUNDING_ANSWERS,
    )
    snap = get_direct_snapshot(sc["cycle"]["id"], sc["unit"]["id"])
    dims = snap["dimension_scores"]
    assert dims["PURPOSE"] == pytest.approx(58.33, abs=0.005), "52.5 / 0.9 rounded half-up at 2dp"
    assert dims["GROWTH"] == pytest.approx(41.67, abs=0.005), "87.5 / 2.1"
    assert dims["BELONGING"] == pytest.approx(66.67, abs=0.005), "220.0 / 3.3"


def test_overall_computed_from_unrounded_products_not_dimension_means(api):
    """PRD §3.5: "The overall score is the sum of the 4-decimal products over
    all answers, divided by the total pinned weight of all items counted once
    per submitted respondent, likewise rounded half-up to 2 decimal places —
    and it is computed from the unrounded 4-decimal products, never from the
    already-rounded dimension means."

    Design: Difficulty/combinatorial_formula/engagement_score_nested_rounding_order
    """
    sc = setup_cycle_with_field_results(
        bank_name="RoundAll", item_specs=ROUNDING_ITEM_SPECS,
        unit_name="RoundAllU", manager_user_id="mgr-ra",
        min_n_threshold=3, num_employees=3, cycle_kind="CENSUS",
        target_state="SCORING", submitters=3, submit_scores=ROUNDING_ANSWERS,
    )
    snap = get_direct_snapshot(sc["cycle"]["id"], sc["unit"]["id"])
    assert snap["overall_score"] == pytest.approx(57.14, abs=0.005), (
        "360.0 / 6.3 from unrounded 4dp products"
    )
    naive_mean = round((58.33 + 41.67 + 66.67) / 3, 2)
    assert naive_mean == 55.56
    assert not (snap["overall_score"] == pytest.approx(naive_mean, abs=0.005)), (
        "the forbidden evaluation order (mean of rounded 2dp dimension means) "
        "must not leak into overall_score"
    )


def test_submitted_n_exactly_at_min_n_threshold_is_visible(api):
    """PRD §2.6: "A count exactly at a threshold is visible — suppression
    begins one response below it."
    PRD §3.5: "`numeric_suppressed` is true exactly when `submitted_n` is
    strictly less than the effective minimum, counting only `SUBMITTED`
    invitations; a suppressed snapshot exposes an empty `dimension_scores` map
    and a null `overall_score`."

    Design: Difficulty/boundary_precision_check/minimum_n_exactly_at_threshold_visible
    """
    sc = setup_cycle_with_field_results(
        bank_name="BoundAt", unit_name="BoundAtU", manager_user_id="mgr-ba",
        min_n_threshold=5, num_employees=5, cycle_kind="CENSUS",
        target_state="SCORING", submitters=5, submit_scores=[[4, 4, 4]] * 5,
    )
    snap = get_direct_snapshot(sc["cycle"]["id"], sc["unit"]["id"])
    assert snap["submitted_n"] == 5
    assert snap["numeric_suppressed"] is False, "n == min_n is visible (strict < comparison)"
    assert snap["overall_score"] == pytest.approx(75.00, abs=0.005)
    assert snap["dimension_scores"], "visible snapshot exposes its dimension map"


def test_submitted_n_one_below_min_n_threshold_is_suppressed(api):
    """PRD §3.5: "`numeric_suppressed` is true exactly when `submitted_n` is
    strictly less than the effective minimum, counting only `SUBMITTED`
    invitations; a suppressed snapshot exposes an empty `dimension_scores` map
    and a null `overall_score`."
    PRD §2.6: "A count exactly at a threshold is visible — suppression begins
    one response below it."

    Design: Difficulty/boundary_precision_check/minimum_n_exactly_at_threshold_visible
    """
    sc = setup_cycle_with_field_results(
        bank_name="BoundBelow", unit_name="BoundBelowU", manager_user_id="mgr-bb",
        min_n_threshold=5, num_employees=5, cycle_kind="CENSUS",
        target_state="SCORING", submitters=4, submit_scores=[[4, 4, 4]] * 4,
    )
    snap = get_direct_snapshot(sc["cycle"]["id"], sc["unit"]["id"])
    assert snap["submitted_n"] == 4
    assert snap["numeric_suppressed"] is True, "n == min_n - 1 is suppressed"
    assert snap["overall_score"] is None
    assert snap["dimension_scores"] == {}


def test_benchmark_percentile_counts_half_ties(api):
    """PRD §3.6: "When scoring runs with an `ACTIVE` benchmark set linked, each
    snapshot's `benchmark_percentile` is the snapshot's standing against that
    distribution: count the reference scores strictly below the snapshot's
    `overall_score`, add half the count of reference scores exactly equal to
    it, divide by the total number of reference scores, multiply by 100, and
    round half-up to 2 decimal places."

    Design: Corner/calculations/benchmark_percentile_with_ties
    """
    bench = get_success_data(
        api.create_benchmark_set(
            create_benchmark_set_payload(
                name="Tech 2026",
                dimension_scores=[55, 60, 62, 65, 68, 70, 72, 75, 78, 80],
            ),
            PEOPLE_ANALYST,
        )
    )
    assert bench["status"] == "ACTIVE"
    sc = setup_cycle_with_field_results(
        bank_name="PctBank", item_specs=DUAL_ITEM_SPECS,
        unit_name="PctUnit", manager_user_id="mgr-pc",
        min_n_threshold=3, num_employees=3, cycle_kind="CENSUS",
        target_state="SCORING", submitters=3, submit_scores=[[5, 4, 3]] * 3,
    )
    snap = get_direct_snapshot(sc["cycle"]["id"], sc["unit"]["id"])
    assert snap["overall_score"] == pytest.approx(72.22, abs=0.005)
    assert snap["benchmark_percentile"] == pytest.approx(70.00, abs=0.005), (
        "7 reference scores strictly below 72.22, 0 ties: (7 + 0)/10 * 100 = 70.00"
    )


def test_pulse_sampling_floor_and_eligibility_gates(api):
    """PRD §3.3: "For a `PULSE` cycle the sweep multiplies the eligible
    headcount by `sampling_ratio`, rounds the product down to a whole number,
    and invites exactly that many employees, chosen in order of earliest
    `hired_at` first with ties broken by earliest `created_at`."
    PRD §3.3: "The eligible population is every employee with
    `employment_status` `ACTIVE` whose `hired_at` falls on or before the date
    thirty days before the cycle's `opens_at` — a tenure gate that excludes
    brand-new hires."
    PRD §3.2: "Only employees in `ACTIVE` status are ever invited to a survey;
    those on `LEAVE` and those `TERMINATED` are excluded from every eligibility
    sweep."

    Design: Corner/calculations/pulse_sampling_floor_truncates
    """
    bank, items = make_active_bank("Samp Bank")
    unit = make_unit("SampUnit", "mgr-sm")
    employees = [
        make_employee(unit["id"], f"SM{i:02d}", hired_at=f"2026-01-{i:02d}T00:00:00Z")
        for i in range(1, 11)
    ]
    get_success_data(
        api.terminate_employee(employees[9]["id"], {"exited_at": "2026-06-01T00:00:00Z"}, HR_ADMIN)
    )
    make_employee(unit["id"], "SM11", hired_at="2026-08-20T00:00:00Z")

    set_clock("2026-09-01T00:00:00Z")
    cycle = make_cycle(
        bank["id"], label="Samp Pulse", cycle_kind="PULSE",
        opens_at="2026-09-01T00:00:00Z", closes_at="2026-09-10T00:00:00Z",
        sampling_ratio=0.50,
    )
    pin_items(cycle["id"], items)
    configure_cycle(cycle["id"])
    open_cycle(cycle["id"])

    cycle_after = get_cycle(cycle["id"])
    assert cycle_after["invited_count"] == 4, (
        "floor(9 eligible * 0.50) = 4: TERMINATED and tenure-gated hires excluded"
    )
    invites, meta = validate_paginated(
        api.list_survey_invites(PEOPLE_ANALYST, params={"cycle_id": cycle["id"], "limit": 100})
    )
    assert meta["total_count"] == 4
    invited_employee_ids = {inv["employee_id"] for inv in invites}
    expected_ids = {e["id"] for e in employees[:4]}
    assert invited_employee_ids == expected_ids, (
        "the earliest four by hired_at (2026-01-01..04) are invited"
    )
    for inv in invites:
        assert inv["status"] == "INVITED"
        assert inv["unit_id_at_invite"] == unit["id"]


def test_verbatim_suppression_decouples_from_numeric_suppression(api):
    """PRD §3.5: "`verbatim_suppressed` is true exactly when `submitted_n` is
    strictly less than the effective verbatim threshold, and verbatim comments
    are served only when `verbatim_suppressed` is false."
    PRD §3.5: "`numeric_suppressed` is true exactly when `submitted_n` is
    strictly less than the effective minimum, counting only `SUBMITTED`
    invitations; a suppressed snapshot exposes an empty `dimension_scores` map
    and a null `overall_score`."
    PRD §2.6: "Violations of these boundaries — reaching for a snapshot outside
    the manager's subtree, requesting suppressed scores, or attempting
    response-level access — are rejected with `ERR_CONFIDENTIALITY` (HTTP 403)."

    Design: Corner/calculations/verbatim_suppression_independent_of_numeric
    """
    sc = setup_cycle_with_field_results(
        bank_name="VerbBank",
        item_specs=[
            {"item_code": "VB-1", "dimension": "PURPOSE", "weight": 1.0, "has_free_text": True},
            {"item_code": "VB-2", "dimension": "PURPOSE", "weight": 1.0},
            {"item_code": "VB-3", "dimension": "PURPOSE", "weight": 1.0},
        ],
        unit_name="VerbUnit", manager_user_id="mgr-vb",
        min_n_threshold=3, verbatim_n_threshold=10, num_employees=5,
        target_state="REPORTED", submitters=5,
        submit_scores=[[4, 4, 4]] * 5,
        submit_comments=[["great mission", None, None], ["love it", None, None], None, None, None],
    )
    snap = get_direct_snapshot(sc["cycle"]["id"], sc["unit"]["id"])
    assert snap["submitted_n"] == 5
    assert snap["numeric_suppressed"] is False, "5 >= min_n 3: numeric scores visible"
    assert snap["overall_score"] == pytest.approx(75.00, abs=0.005)
    assert snap["verbatim_suppressed"] is True, "5 < verbatim_n 10: verbatims withheld"

    resp = api.get_snapshot_verbatims(snap["id"], PEOPLE_ANALYST)
    validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY)
