"""Genotyping pipeline: qc_score computation, outcome gate, the sample fork,
and the PASS cascade into kit-consume and report creation.

Covers queue A (combinatorial_formula, transitive_cascade, boundary_precision_check)
and queue B (calculations) instances tied to genotyping runs.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_received_sample,
)
from test_helpers.factories import create_genotyping_run_payload, pass_run_payload

LAB = TEST_USERS["lab_technician_headers"]


# =========================================================================
# qc_score combinatorial formula (queue A: combinatorial_formula)
# =========================================================================

def test_qc_score_three_input_blend_yields_99_10(api):
    """PRD §3.3: "The raw score is then 100 multiplied by the sum of three
    weighted contributions — the call rate weighted by 0.6, one minus the
    contamination weighted by 0.3, and the heterozygosity-consistency term
    weighted by 0.1."
    PRD §3.3: "Equivalently: a `call_rate` of at least 0.85 together with a
    `qc_score` of at least 60.00 yields `PASS`"

    Design: Difficulty/combinatorial_formula/qc_score_three_input_nonlinear_mode_a
    """
    base = setup_received_sample(product_tier="BREED")
    resp = api.create_genotyping_run(
        base["sample"]["id"],
        pass_run_payload(call_rate=0.99, het_rate=0.35, contamination=0.01),
        LAB,
    )
    run = validate_success(resp, expected_status=201)
    assert run["qc_score"] == 99.10, f"expected qc_score 99.10, got {run['qc_score']}"
    assert run["outcome"] == "PASS", f"expected outcome PASS, got {run['outcome']}"


def test_qc_score_pass_advances_sample_to_pass(api):
    """PRD §3.3: "On a `PASS` outcome the sample advances from `GENOTYPING` to
    `PASS`; this success path also transitions the owning kit from `RECEIVED`
    to `CONSUMED`, creates a `PRELIMINARY` report for the sample, and increments
    the sample's `version`"

    Design: Difficulty/combinatorial_formula/qc_score_three_input_nonlinear_mode_a
    """
    base = setup_received_sample(product_tier="BREED")
    api.create_genotyping_run(
        base["sample"]["id"],
        pass_run_payload(call_rate=0.99, het_rate=0.35, contamination=0.01),
        LAB,
    )
    sample = validate_success(api.get_sample(base["sample"]["id"], LAB))
    assert sample["status"] == "PASS", f"expected sample PASS, got {sample['status']}"


# =========================================================================
# breed composition rounding + reallocation (queue A: combinatorial_formula)
# =========================================================================

def test_breed_composition_three_equal_segments_sums_to_100(api):
    """PRD §3.4: "a remainder is computed as 100.00 minus the sum of the rounded
    percentages, rounded half-up to two decimals, and that entire remainder is
    added to the single segment with the largest `match_cm` (ties broken in
    favour of the earliest array index)."
    PRD §3.4: "The resulting `breed_composition` is the list of `breed`-and-`pct`
    pairs in the original request order, and it sums to exactly 100.00."

    Design: Difficulty/combinatorial_formula/breed_composition_round_then_reallocate_mode_b
    """
    base = setup_received_sample(product_tier="BREED")
    segments = [
        {"breed": "LABRADOR", "match_cm": 1000},
        {"breed": "POODLE", "match_cm": 1000},
        {"breed": "BEAGLE", "match_cm": 1000},
    ]
    api.create_genotyping_run(
        base["sample"]["id"], pass_run_payload(breed_segments=segments), LAB
    )
    reports = validate_success(
        api.list_reports(LAB, params={"sample_id": base["sample"]["id"]})
    )
    comp = reports[0]["breed_composition"]
    assert comp == [
        {"breed": "LABRADOR", "pct": 33.34},
        {"breed": "POODLE", "pct": 33.33},
        {"breed": "BEAGLE", "pct": 33.33},
    ], f"unexpected breed_composition: {comp}"


def test_breed_composition_pct_total_is_exactly_100(api):
    """PRD §3.4: "The resulting `breed_composition` is the list of `breed`-and-`pct`
    pairs in the original request order, and it sums to exactly 100.00."

    Design: Difficulty/combinatorial_formula/breed_composition_round_then_reallocate_mode_b
    """
    base = setup_received_sample(product_tier="BREED")
    segments = [
        {"breed": "LABRADOR", "match_cm": 1000},
        {"breed": "POODLE", "match_cm": 1000},
        {"breed": "BEAGLE", "match_cm": 1000},
    ]
    api.create_genotyping_run(
        base["sample"]["id"], pass_run_payload(breed_segments=segments), LAB
    )
    reports = validate_success(
        api.list_reports(LAB, params={"sample_id": base["sample"]["id"]})
    )
    total = round(sum(seg["pct"] for seg in reports[0]["breed_composition"]), 2)
    assert total == 100.00, f"breed_composition pct sum must be 100.00, got {total}"


# =========================================================================
# transitive cascade: PASS -> sample PASS -> kit CONSUMED -> report (queue A)
# =========================================================================

def test_pass_run_consumes_kit_via_sample_pass(api):
    """PRD §3.3: "this success path also transitions the owning kit from
    `RECEIVED` to `CONSUMED`, creates a `PRELIMINARY` report for the sample"

    Design: Difficulty/transitive_cascade/genotyping_pass_cascades_sample_then_kit_depth3
    """
    base = setup_received_sample(product_tier="BREED")
    api.create_genotyping_run(base["sample"]["id"], pass_run_payload(), LAB)

    sample = validate_success(api.get_sample(base["sample"]["id"], LAB))
    assert sample["status"] == "PASS", f"link 1: expected sample PASS, got {sample['status']}"

    kit = validate_success(api.get_kit(base["kit"]["id"], LAB))
    assert kit["status"] == "CONSUMED", f"link 2: expected kit CONSUMED, got {kit['status']}"


def test_pass_run_creates_one_preliminary_report(api):
    """PRD §3.4: "A **Report** is born the moment a sample passes genotyping.
    It is created in `PRELIMINARY`"

    Design: Difficulty/transitive_cascade/genotyping_pass_cascades_sample_then_kit_depth3
    """
    base = setup_received_sample(product_tier="BREED")
    api.create_genotyping_run(base["sample"]["id"], pass_run_payload(), LAB)
    reports = validate_success(
        api.list_reports(LAB, params={"sample_id": base["sample"]["id"]})
    )
    assert len(reports) == 1, f"expected exactly 1 report, got {len(reports)}"
    assert reports[0]["status"] == "PRELIMINARY", \
        f"expected PRELIMINARY, got {reports[0]['status']}"


# =========================================================================
# boundary: call-rate gate >= 0.85 (queue A: boundary_precision_check)
# =========================================================================

def test_call_rate_below_gate_forces_failed(api):
    """PRD §3.3: "if `call_rate` is below the call-rate gate of 0.85 the outcome
    is `FAILED` and no further test is applied"
    PRD §3.3: "a `call_rate` below 0.85 yields `FAILED` regardless of score."

    Design: Difficulty/boundary_precision_check/call_rate_gate_ge_085_boundary_on_genotyping_run
    """
    base = setup_received_sample(product_tier="BREED")
    resp = api.create_genotyping_run(
        base["sample"]["id"],
        create_genotyping_run_payload(call_rate=0.84, het_rate=0.35, contamination=0.01),
        LAB,
    )
    run = validate_success(resp, expected_status=201)
    assert run["outcome"] == "FAILED", \
        f"call_rate 0.84 < 0.85 must FAIL regardless of score, got {run['outcome']}"


def test_call_rate_below_gate_sets_sample_failed(api):
    """PRD §3.3: "On a `FAILED` outcome the sample moves from `GENOTYPING` to
    `FAILED`, copies the score, and increments its `version`, likewise eligible
    for a re-test."

    Design: Difficulty/boundary_precision_check/call_rate_gate_ge_085_boundary_on_genotyping_run
    """
    base = setup_received_sample(product_tier="BREED")
    api.create_genotyping_run(
        base["sample"]["id"],
        create_genotyping_run_payload(call_rate=0.84, het_rate=0.35, contamination=0.01),
        LAB,
    )
    sample = validate_success(api.get_sample(base["sample"]["id"], LAB))
    assert sample["status"] == "FAILED", f"expected sample FAILED, got {sample['status']}"


# =========================================================================
# Corner: calculations
# =========================================================================

def test_empty_breed_segments_yields_empty_composition(api):
    """PRD §3.4: "An empty `breed_segments` array yields an empty composition."

    Design: Corner/calculations/empty_breed_segments_yields_empty_composition
    """
    base = setup_received_sample(product_tier="BREED")
    api.create_genotyping_run(
        base["sample"]["id"],
        create_genotyping_run_payload(call_rate=0.99, het_rate=0.35, contamination=0.01),
        LAB,
    )
    reports = validate_success(
        api.list_reports(LAB, params={"sample_id": base["sample"]["id"]})
    )
    assert reports[0]["breed_composition"] == [], \
        f"expected empty composition, got {reports[0]['breed_composition']}"


def test_qns_outcome_leaves_qns_and_creates_no_report(api):
    """PRD §3.3: "otherwise, if the `qc_score` is below the QNS floor of 60.00
    the outcome is `QNS`"
    PRD §3.3: "On a `QNS` outcome — quantity not sufficient — the sample moves
    from `GENOTYPING` to `QNS`, copies the score, and increments its `version`,
    producing no report but leaving the sample eligible for a re-test."

    Design: Corner/calculations/qns_outcome_no_report_created
    """
    base = setup_received_sample(product_tier="BREED")
    resp = api.create_genotyping_run(
        base["sample"]["id"],
        create_genotyping_run_payload(call_rate=0.85, het_rate=0.0, contamination=0.9),
        LAB,
    )
    run = validate_success(resp, expected_status=201)
    assert run["qc_score"] == 54.00, f"expected qc 54.00, got {run['qc_score']}"
    assert run["outcome"] == "QNS", f"expected outcome QNS, got {run['outcome']}"

    sample = validate_success(api.get_sample(base["sample"]["id"], LAB))
    assert sample["status"] == "QNS", f"expected sample QNS, got {sample['status']}"

    reports = validate_success(
        api.list_reports(LAB, params={"sample_id": base["sample"]["id"]})
    )
    assert len(reports) == 0, f"QNS must create no report, got {len(reports)}"


def test_genotyping_run_out_of_range_call_rate_rejected(api):
    """PRD §3.3: "Each of the three metrics must lie between 0 and 1 inclusive;
    a value outside that range is rejected with `ERR_INVALID_RANGE`."

    Design: Corner/calculations/genotyping_range_out_of_bounds_returns_invalid_range
    """
    base = setup_received_sample(product_tier="BREED")
    resp = api.create_genotyping_run(
        base["sample"]["id"],
        create_genotyping_run_payload(call_rate=1.5, het_rate=0.35, contamination=0.01),
        LAB,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_RANGE.value)
