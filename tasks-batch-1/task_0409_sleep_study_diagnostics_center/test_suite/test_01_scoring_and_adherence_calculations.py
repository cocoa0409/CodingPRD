"""AHI scoring, severity banding, CPAP adherence, resupply cycle, and Epworth
improvement calculations.

Covers difficulty queue (A) calculation/boundary instances and corner queue (B)
calculation instances.
"""

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    create_in_progress_study,
    create_fulfilled_dme,
    create_interpreted_study,
    create_scheduled_follow_up,
    score_study_payload,
    create_compliance_record_payload,
    create_dme_order_payload,
    create_follow_up_payload,
    TEST_USERS,
)

TECH = TEST_USERS["sleep_technologist_headers"]
DME = TEST_USERS["dme_coordinator_headers"]
COORD = TEST_USERS["scheduling_coordinator_headers"]


# ─── AHI: divide-then-round (dual variant) ────────────────────────────────

def test_ahi_uses_divide_then_round_order(api):
    """PRD 3.6: "first the recording hours are obtained by dividing
    total_recording_minutes by 60 as an exact division with no intermediate
    rounding, and then the index is obtained by dividing respiratory_event_count
    by those recording hours and rounding the quotient to 1 decimal place using
    round-half-up."
    PRD 3.6: "The divide-then-round order is mandatory; rounding the recording
    hours before dividing would yield a different index."

    250 min / 50 events: 50 / (250/60) = 12.0 exact (divide-then-round). A
    round-then-divide reading (50/4) would give 12.5.

    Design: Difficulty/dual_variant_calc/ahi_divide_then_round_vs_round_then_divide
    """
    _, _, study, _ = create_in_progress_study(modality="HSAT")
    res = api.score_study(
        study["id"],
        score_study_payload(250, 50, study["version"]),
        TECH,
    )
    scored = validate_success(res, 200)
    assert scored["ahi"] == 12.0, f"Expected ahi 12.0, got {scored['ahi']}"
    assert scored["severity"] == "MILD"
    assert scored["status"] == "SCORED"


def test_ahi_divide_then_round_severity_band(api):
    """PRD 3.6: "first the recording hours are obtained by dividing
    total_recording_minutes by 60 as an exact division with no intermediate
    rounding, and then the index is obtained by dividing respiratory_event_count
    by those recording hours and rounding the quotient to 1 decimal place using
    round-half-up."
    PRD 3.6: "An index of at least 5 but below 15 is MILD, so an index of exactly
    5.0 is MILD."

    250 min / 50 events resolves to 12.0 (divide-then-round) which bands MILD.

    Design: Difficulty/dual_variant_calc/ahi_divide_then_round_vs_round_then_divide
    """
    _, _, study, _ = create_in_progress_study(modality="HSAT")
    res = api.score_study(
        study["id"],
        score_study_payload(250, 50, study["version"]),
        TECH,
    )
    scored = validate_success(res, 200)
    assert scored["ahi"] == 12.0
    assert scored["severity"] == "MILD", f"Expected MILD, got {scored['severity']}"


# ─── AHI severity boundary at exactly 5.0 (boundary precision) ─────────────

def test_ahi_severity_boundary_exactly_five_is_mild(api):
    """PRD 3.6: "An index of at least 5 but below 15 is MILD, so an index of
    exactly 5.0 is MILD."

    480 min, 40 events -> 40 / 8.0 = 5.0 -> MILD (inclusive lower edge).

    Design: Difficulty/boundary_precision_check/ahi_severity_boundary_exactly_five
    """
    _, _, study, _ = create_in_progress_study(modality="HSAT")
    res = api.score_study(
        study["id"],
        score_study_payload(480, 40, study["version"]),
        TECH,
    )
    scored = validate_success(res, 200)
    assert scored["ahi"] == 5.0, f"Expected ahi 5.0, got {scored['ahi']}"
    assert scored["severity"] == "MILD", f"Expected MILD at boundary, got {scored['severity']}"


def test_ahi_just_below_five_is_none_not_mild(api):
    """PRD 3.6: "An index below 5 is NONE."
    PRD 3.6: "An index of at least 5 but below 15 is MILD, so an index of exactly
    5.0 is MILD."

    480 min, 39 events -> 39 / 8.0 = 4.875 -> rounds to 4.9 -> NONE. The X-1 side
    of the >= 5 boundary: a `>` reading would also give NONE, but a faulty `<= 5`
    MILD reading would wrongly flip this to MILD.

    Design: Difficulty/boundary_precision_check/ahi_severity_boundary_exactly_five
    """
    _, _, study, _ = create_in_progress_study(modality="HSAT")
    res = api.score_study(
        study["id"],
        score_study_payload(480, 39, study["version"]),
        TECH,
    )
    scored = validate_success(res, 200)
    assert scored["ahi"] == 4.9, f"Expected ahi 4.9, got {scored['ahi']}"
    assert scored["severity"] == "NONE", f"Expected NONE just below boundary, got {scored['severity']}"


def test_ahi_below_five_is_none_band(api):
    """PRD 3.6: "An index below 5 is NONE."
    PRD 3.6: "An index of at least 5 but below 15 is MILD, so an index of exactly
    5.0 is MILD."

    480 min, 32 events -> 4.0 -> NONE (just below the 5.0 MILD edge).

    Design: Corner/calculations/ahi_none_band_below_five
    """
    _, _, study, _ = create_in_progress_study(modality="HSAT")
    res = api.score_study(
        study["id"],
        score_study_payload(480, 32, study["version"]),
        TECH,
    )
    scored = validate_success(res, 200)
    assert scored["ahi"] == 4.0, f"Expected ahi 4.0, got {scored['ahi']}"
    assert scored["severity"] == "NONE", f"Expected NONE, got {scored['severity']}"


def test_ahi_severe_boundary_exactly_thirty(api):
    """PRD 3.6: "An index of 30 or above is SEVERE, so an index of exactly 30.0
    is SEVERE."

    480 min, 240 events -> 30.0 -> SEVERE (inclusive lower edge).

    Design: Corner/calculations/ahi_severe_boundary_exactly_thirty
    """
    _, _, study, _ = create_in_progress_study(modality="HSAT")
    res = api.score_study(
        study["id"],
        score_study_payload(480, 240, study["version"]),
        TECH,
    )
    scored = validate_success(res, 200)
    assert scored["ahi"] == 30.0, f"Expected ahi 30.0, got {scored['ahi']}"
    assert scored["severity"] == "SEVERE", f"Expected SEVERE at boundary, got {scored['severity']}"


# ─── CPAP adherence: window-length gate first (dual variant) ───────────────

def test_adherence_window_gate_short_circuits_to_false(api):
    """PRD 3.10: "This window-length gate is evaluated first: if the window spans
    fewer than 30 days, the record is non-adherent and the usage clauses are not
    evaluated at all."

    20-day window with 25 strong nights -> adherent false on the gate alone, even
    though the usage clauses would otherwise pass.

    Design: Difficulty/dual_variant_calc/adherence_window_gate_first_vs_evaluate_all
    """
    _, _, dme = create_fulfilled_dme()
    res = api.create_compliance_record(
        create_compliance_record_payload(
            dme["id"],
            "2026-08-01T00:00:00Z", "2026-08-21T00:00:00Z",
            nights_used_4h_plus=25, total_usage_minutes=7500,
        ),
        DME,
    )
    record = validate_success(res, 201)
    assert record["adherent"] is False, "20-day window must be non-adherent on the window gate"


def test_adherence_short_window_ignores_usage_clauses(api):
    """PRD 3.10: "This window-length gate is evaluated first: if the window spans
    fewer than 30 days, the record is non-adherent and the usage clauses are not
    evaluated at all."

    A second short-window upload with strong usage (29-day window, 28 strong
    nights) is still non-adherent: the gate fires before any usage clause.

    Design: Difficulty/dual_variant_calc/adherence_window_gate_first_vs_evaluate_all
    """
    _, _, dme = create_fulfilled_dme()
    res = api.create_compliance_record(
        create_compliance_record_payload(
            dme["id"],
            "2026-08-01T00:00:00Z", "2026-08-30T00:00:00Z",
            nights_used_4h_plus=28, total_usage_minutes=12000,
        ),
        DME,
    )
    record = validate_success(res, 201)
    assert record["adherent"] is False, "29-day window must be non-adherent on the window gate"


# ─── CPAP adherence: three-input compound AND (combinatorial) ──────────────

def test_adherence_fails_on_average_usage_clause(api):
    """PRD 3.10: "And the average usage on the qualifying nights, computed as
    total_usage_minutes divided by nights_used_4h_plus (taken as zero when there
    are no qualifying nights), must be at least 240 minutes."

    30-day window, 22 nights, 5060 total minutes -> avg = 230 < 240 -> non-adherent
    even though the nights and proportion clauses pass.

    Design: Difficulty/combinatorial_formula/adherence_three_input_nonlinear_compound_and
    """
    _, _, dme = create_fulfilled_dme()
    res = api.create_compliance_record(
        create_compliance_record_payload(
            dme["id"],
            "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z",
            nights_used_4h_plus=22, total_usage_minutes=5060,
        ),
        DME,
    )
    record = validate_success(res, 201)
    assert record["adherent"] is False, "avg 230 < 240 must fail adherence"


def test_adherence_all_three_usage_clauses_must_hold(api):
    """PRD 3.10: "When the window is at least 30 days long, three conditions must
    all hold for the record to be adherent."
    PRD 3.10: "And the average usage on the qualifying nights, computed as
    total_usage_minutes divided by nights_used_4h_plus (taken as zero when there
    are no qualifying nights), must be at least 240 minutes."

    30-day window, 22 nights (proportion 0.733 >= 0.70, count >= 21), but avg 230
    < 240 -> the compound AND fails on the average clause.

    Design: Difficulty/combinatorial_formula/adherence_three_input_nonlinear_compound_and
    """
    _, _, dme = create_fulfilled_dme()
    res = api.create_compliance_record(
        create_compliance_record_payload(
            dme["id"],
            "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z",
            nights_used_4h_plus=22, total_usage_minutes=5060,
        ),
        DME,
    )
    record = validate_success(res, 201)
    assert record["adherent"] is False


# ─── CPAP adherence: pct/avg boundary exactly 0.70 / 240 (boundary) ────────

def test_adherence_pct_boundary_exactly_seventy_percent_is_adherent(api):
    """PRD 3.10: "Those qualifying nights, taken as a proportion of the window
    days, must be at least 0.70 — that is, the qualifying-night count divided by
    the window-day count must be at least seventy percent."
    PRD 3.10: "And the average usage on the qualifying nights, computed as
    total_usage_minutes divided by nights_used_4h_plus (taken as zero when there
    are no qualifying nights), must be at least 240 minutes."

    30-day window, 21 nights (21/30 = 0.70 exact), 5040 min (avg 240 exact) ->
    all three >= boundaries hit dead-on -> adherent true.

    Design: Difficulty/boundary_precision_check/adherence_pct_boundary_exactly_seventy_percent
    """
    _, _, dme = create_fulfilled_dme()
    res = api.create_compliance_record(
        create_compliance_record_payload(
            dme["id"],
            "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z",
            nights_used_4h_plus=21, total_usage_minutes=5040,
        ),
        DME,
    )
    record = validate_success(res, 201)
    assert record["adherent"] is True, "0.70 pct and 240 avg at boundary must be adherent"


def test_adherence_min_nights_boundary_twenty_one(api):
    """PRD 3.10: "There must be at least 21 nights with four or more hours of use."
    PRD 3.10: "Those qualifying nights, taken as a proportion of the window days,
    must be at least 0.70 — that is, the qualifying-night count divided by the
    window-day count must be at least seventy percent."

    30-day window, exactly 21 nights, avg exactly 240 -> the minimum-nights edge
    is inclusive -> adherent true.

    Design: Difficulty/boundary_precision_check/adherence_pct_boundary_exactly_seventy_percent
    """
    _, _, dme = create_fulfilled_dme()
    res = api.create_compliance_record(
        create_compliance_record_payload(
            dme["id"],
            "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z",
            nights_used_4h_plus=21, total_usage_minutes=5040,
        ),
        DME,
    )
    record = validate_success(res, 201)
    assert record["adherent"] is True


# ─── Resupply cycle number (combinatorial / pinned order) ──────────────────

def _build_fulfilled_resupply(api, study_id, predecessor_id, predecessor_version,
                              pressure=11.0):
    """Create a resupply against predecessor, then submit+fulfill it. Returns dme."""
    res = api.create_dme_order(
        create_dme_order_payload(
            study_id,
            prescribed_pressure_cmh2o=pressure,
            supersedes_dme_order_id=predecessor_id,
            expected_supersedes_version=predecessor_version,
        ),
        DME,
    )
    dme = get_success_data(res)
    api.submit_dme_order(dme["id"], DME)
    fulfilled = get_success_data(api.fulfill_dme_order(dme["id"], DME))
    return fulfilled


def test_resupply_cycle_number_increments_along_lineage(api):
    """PRD 3.9: "An order with no predecessor — an initial order — has a cycle
    number of 1."
    PRD 3.9: "A resupply's cycle number is its predecessor's resupply_cycle_number
    plus 1."

    Initial order cycle 1, first resupply cycle 2, second resupply cycle 3.

    Design: Difficulty/combinatorial_formula/resupply_cycle_circular_dependency_pinned_order
    """
    study, _, dme1 = create_fulfilled_dme()
    assert dme1["resupply_cycle_number"] == 1
    dme2 = _build_fulfilled_resupply(api, study["id"], dme1["id"], dme1["version"])
    assert dme2["resupply_cycle_number"] == 2
    res = api.create_dme_order(
        create_dme_order_payload(
            study["id"],
            prescribed_pressure_cmh2o=11.0,
            supersedes_dme_order_id=dme2["id"],
            expected_supersedes_version=dme2["version"],
        ),
        DME,
    )
    dme3 = validate_success(res, 201)
    assert dme3["resupply_cycle_number"] == 3, (
        f"Expected cycle 3, got {dme3['resupply_cycle_number']}"
    )
    assert dme3["supersedes_dme_order_id"] == dme2["id"]


def test_resupply_chain_links_to_named_predecessor(api):
    """PRD 3.9: "A resupply names the order it replaces through
    supersedes_dme_order_id and carries the optimistic-concurrency field
    expected_supersedes_version."
    PRD 3.9: "A resupply's cycle number is its predecessor's resupply_cycle_number
    plus 1."

    The third order in the chain records both cycle 3 and the predecessor id.

    Design: Difficulty/combinatorial_formula/resupply_cycle_circular_dependency_pinned_order
    """
    study, _, dme1 = create_fulfilled_dme()
    dme2 = _build_fulfilled_resupply(api, study["id"], dme1["id"], dme1["version"])
    res = api.create_dme_order(
        create_dme_order_payload(
            study["id"],
            prescribed_pressure_cmh2o=11.0,
            supersedes_dme_order_id=dme2["id"],
            expected_supersedes_version=dme2["version"],
        ),
        DME,
    )
    dme3 = validate_success(res, 201)
    assert dme3["supersedes_dme_order_id"] == dme2["id"]
    assert dme3["resupply_cycle_number"] == 3


# ─── Computed snapshot on the DRAFT scoring report (corner) ────────────────

def test_scoring_report_snapshots_ahi_and_severity(api):
    """PRD 3.6: "snapshots the just-computed index and severity into its
    ahi_snapshot and severity_snapshot fields."

    480 min, 120 events -> ahi 15.0 -> MODERATE; the DRAFT report copies both.

    Design: Corner/entities/computed_severity_snapshot_on_scoring_report
    """
    _, _, study, _ = create_in_progress_study(modality="HSAT")
    score_res = api.score_study(
        study["id"],
        score_study_payload(480, 120, study["version"]),
        TECH,
    )
    validate_success(score_res, 200)
    reports = get_success_data(
        api.list_scoring_reports_for_study(study["id"], TEST_USERS["physician_headers"])
    )
    report = reports[0]
    assert report["ahi_snapshot"] == 15.0, f"Expected 15.0, got {report['ahi_snapshot']}"
    assert report["severity_snapshot"] == "MODERATE"


# ─── Epworth improvement (corner) ─────────────────────────────────────────

def test_epworth_improvement_negative_when_symptoms_worsen(api):
    """PRD 3.11: "The improvement is the patient's baseline_epworth_score minus
    the post_treatment_epworth_score, so a positive result indicates the patient's
    daytime sleepiness improved; the value may be negative if symptoms worsened."

    baseline 10, post-treatment 12 -> improvement -2.

    Design: Corner/calculations/epworth_improvement_negative_when_worse
    """
    _, _, follow_up = create_scheduled_follow_up(baseline_epworth_score=10)
    res = api.complete_follow_up(follow_up["id"], {"post_treatment_epworth_score": 12}, COORD)
    completed = validate_success(res, 200)
    assert completed["epworth_improvement"] == -2, (
        f"Expected -2, got {completed['epworth_improvement']}"
    )
