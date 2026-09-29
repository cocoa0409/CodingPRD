"""Values sitting exactly on a threshold, and the smallest step past it."""

from test_helpers import (
    SURVEYOR,
    add_finding,
    issue_survey,
    open_survey,
    read_device,
    read_inspection,
    read_lot,
    read_pt_enrollment,
    read_readiness,
    read_site,
    record_qc_run,
    setup_covered_site,
    setup_pt_graded_events,
    setup_site_with_unverified_lot,
)

# ─── qc_control_value_exactly_at_upper_bound_then_one_tenth_over ─────


def _instrument_awaiting_its_first_control_run():
    """A received lot with an 80.0-120.0 level-one band, nothing run against it yet."""
    return setup_site_with_unverified_lot(
        certificate_overrides={"certificate_number": "45D2243015"},
        site_overrides={
            "name": "Boundary POCT",
            "department_code": "DEPT-240",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Alma Ruiz"},
        device_overrides={"serial_number": "SN-0801"},
        lot_overrides={"lot_number": "LOT-G1"},
    )


def _run(env, measured_value):
    return record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_1", measured_value,
    )


def test_a_control_value_exactly_on_the_upper_bound_passes():
    """120.0 against a band of 80.0-120.0 is a PASS and locks nothing.

    PRD 3.4: "The `result` is `PASS` when the `measured_value` is greater than or
    equal to `expected_min` and also less than or equal to `expected_max`; both
    bounds are inclusive, so a value sitting exactly on either bound passes."

    Design: Difficulty/boundary_precision_check/qc_control_value_exactly_at_upper_bound_passes_then_one_tenth_over_fails
    """
    env = _instrument_awaiting_its_first_control_run()

    run = _run(env, 120.0)

    assert run["result"] == "PASS"
    assert run["expected_min"] == 80.0
    assert run["expected_max"] == 120.0
    assert run["locked_device"] is False
    assert read_device(env["device"]["id"])["status"] == "ACTIVE"


def test_one_tenth_above_the_same_bound_fails_and_locks_the_instrument():
    """120.1 is the smallest step outside the band and it fails.

    PRD 3.4: "Otherwise the `result` is `FAIL`." and "their `locked_device` flag is
    true only when this particular run is the one that drove its instrument from
    `ACTIVE` to `QC_LOCKED`."

    Design: Difficulty/boundary_precision_check/qc_control_value_exactly_at_upper_bound_passes_then_one_tenth_over_fails
    """
    env = _instrument_awaiting_its_first_control_run()

    _run(env, 120.0)
    failing = _run(env, 120.1)

    assert failing["result"] == "FAIL"
    assert failing["locked_device"] is True
    device = read_device(env["device"]["id"])
    assert device["status"] == "QC_LOCKED"
    assert device["qc_lock_reason"] == "QC_FAILURE"


def test_a_single_level_pass_never_completes_the_two_level_pair():
    """One accepted level-one run leaves the two-level stamp and the lot untouched.

    PRD 3.4: "`last_two_level_qc_pass_on` in turn is the latest date on which the
    instrument recorded a passing control run at **both** `LEVEL_1` and `LEVEL_2` —
    one level alone never advances the horizon."

    Design: Difficulty/boundary_precision_check/qc_control_value_exactly_at_upper_bound_passes_then_one_tenth_over_fails
    """
    env = _instrument_awaiting_its_first_control_run()

    _run(env, 120.0)
    _run(env, 120.1)

    assert read_device(env["device"]["id"])["last_two_level_qc_pass_on"] is None
    assert read_lot(env["lot"]["id"])["verification_status"] == "UNVERIFIED"
    assert read_site(env["site"]["id"])["held_result_count"] == 0


# ─── pt_score_exactly_eighty_passes_and_seventy_nine_ninety_nine ─────


def _two_graded_shipments_across_the_threshold():
    """One shipment scored exactly 80.00 and one at 79.99."""
    _certificate, site, _coverage = setup_covered_site(
        certificate_overrides={"certificate_number": "45D2243016"},
        site_overrides={
            "name": "PT Boundary POCT",
            "department_code": "DEPT-250",
            "complexity_scope": "WAIVED",
        },
    )
    enrollment, events = setup_pt_graded_events(
        site["id"], [80.00, 79.99],
        enrollment_overrides={"analyte": "GLUCOSE", "program_year": 2026},
        due_dates=["2026-08-10", "2026-08-20"],
    )
    return site, enrollment, events


def test_a_score_of_exactly_eighty_is_a_pass():
    """80.00 sits on the inclusive threshold and takes the passed branch.

    PRD 3.7: "The `outcome` is `PASS` when `score_pct` is greater than or equal to
    80.00 — the threshold is inclusive, so exactly 80.00 passes — and `FAIL`
    otherwise."

    Design: Difficulty/boundary_precision_check/pt_score_exactly_eighty_passes_and_seventy_nine_ninety_nine_fails
    """
    _site, _enrollment, events = _two_graded_shipments_across_the_threshold()

    assert events[0]["outcome"] == "PASS"
    assert events[0]["status"] == "PASSED"


def test_one_hundredth_below_the_threshold_fails_and_opens_an_investigation():
    """79.99 is the smallest step below 80.00 and it fails.

    PRD 3.7: "**Investigation open.** When the outcome is `FAIL` and
    `fail_count_last_three` is below 2, the event moves `PENDING →
    INVESTIGATION_OPEN` with `outcome` of `FAIL` and `graded_on` recorded."

    Design: Difficulty/boundary_precision_check/pt_score_exactly_eighty_passes_and_seventy_nine_ninety_nine_fails
    """
    _site, enrollment, events = _two_graded_shipments_across_the_threshold()

    assert events[1]["outcome"] == "FAIL"
    assert events[1]["status"] == "INVESTIGATION_OPEN"
    read_back = read_pt_enrollment(enrollment["id"])
    assert read_back["status"] == "ENROLLED"
    assert read_back["fail_count_last_three"] == 1
    assert read_back["graded_event_count"] == 2


def test_the_single_boundary_failure_costs_exactly_three_readiness_points():
    """A WAIVED site pays 3 points for its one unsuccessful shipment.

    PRD 3.9: "**Proficiency penalty.** The per-failure unit depends on the site's
    declared `complexity_scope`: 6 points per unsuccessful proficiency event when the
    scope is `MODERATE`, and 3 points when it is `WAIVED`."

    Design: Difficulty/boundary_precision_check/pt_score_exactly_eighty_passes_and_seventy_nine_ninety_nine_fails
    """
    site, _enrollment, _events = _two_graded_shipments_across_the_threshold()

    readiness = read_readiness(site["id"], SURVEYOR)

    assert readiness["pt_unsuccessful_count"] == 1
    assert readiness["pt_penalty"] == 3.00
    assert readiness["score"] == 97.00
    assert read_site(site["id"])["pt_unsuccessful_count"] == 1


# ─── oversight_posture_walks_inclusive_weight_thresholds ─────────────


def _three_surveys_totalling_sixteen_points():
    """Survey A issued at 3.00, with B (3.00) and C (10.00) still in progress."""
    _certificate, site, _coverage = setup_covered_site(
        certificate_overrides={"certificate_number": "45D2243017"},
        site_overrides={
            "name": "Threshold POCT",
            "department_code": "DEPT-260",
            "complexity_scope": "WAIVED",
        },
    )
    inspection_a = open_survey(
        site["id"], SURVEYOR,
        inspection_type="INTERNAL_READINESS", scheduled_date="2026-08-01",
    )
    add_finding(
        inspection_a["id"], SURVEYOR,
        category="PERSONNEL_COMPETENCY", severity="STANDARD_LEVEL",
        description="Semiannual competency observations missing for two operators",
        correction_due_date="2026-10-31",
    )
    inspection_a = issue_survey(inspection_a["id"], SURVEYOR, issued_on="2026-08-01")

    inspection_b = open_survey(
        site["id"], SURVEYOR,
        inspection_type="INTERNAL_READINESS", scheduled_date="2026-08-01",
    )
    add_finding(
        inspection_b["id"], SURVEYOR,
        category="QUALITY_CONTROL", severity="STANDARD_LEVEL",
        description="Two-level control not run on every day of patient testing",
        correction_due_date="2026-10-31",
    )

    inspection_c = open_survey(
        site["id"], SURVEYOR,
        inspection_type="BIENNIAL_SURVEY", scheduled_date="2026-08-01",
    )
    add_finding(
        inspection_c["id"], SURVEYOR,
        category="PROFICIENCY_TESTING", severity="CONDITION_LEVEL",
        description="No enrolment for a regulated analyte in testing",
        correction_due_date="2026-10-31",
    )
    add_finding(
        inspection_c["id"], SURVEYOR,
        category="REAGENT_STORAGE", severity="ADVISORY",
        description="Fridge log gaps on weekends",
        correction_due_date="2026-10-31",
    )
    add_finding(
        inspection_c["id"], SURVEYOR,
        category="CERTIFICATE_SCOPE", severity="ADVISORY",
        description="Certificate copy not posted in the testing area",
        correction_due_date="2026-10-31",
    )
    return site, inspection_a, inspection_b, inspection_c


def test_a_weight_of_three_stays_below_the_restriction_threshold():
    """3.00 is under 6.0, so the site is still OPEN.

    PRD 2.10: "Otherwise the posture is `OPEN`."

    Design: Difficulty/boundary_precision_check/oversight_posture_walks_inclusive_weight_thresholds_six_and_sixteen
    """
    site, inspection_a, _b, _c = _three_surveys_totalling_sixteen_points()

    read_back = read_site(site["id"])

    assert read_inspection(inspection_a["id"])["status"] == "DEFICIENCIES_ISSUED"
    assert read_inspection(inspection_a["id"])["issued_weight_total"] == 3.00
    assert read_back["open_deficiency_weight"] == 3.00
    assert read_back["oversight_posture"] == "OPEN"


def test_a_weight_of_exactly_six_restricts_the_site():
    """The restriction threshold is inclusive, so 6.00 exactly restricts.

    PRD 2.10: "Otherwise, if its `open_deficiency_weight` is at least 6.0, **or** its
    `held_result_count` is at least 3, **or** twice its `locked_out_operator_count` is
    strictly greater than its `total_operator_count`, the posture is `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/oversight_posture_walks_inclusive_weight_thresholds_six_and_sixteen
    """
    site, _a, inspection_b, _c = _three_surveys_totalling_sixteen_points()

    issue_survey(inspection_b["id"], SURVEYOR, issued_on="2026-08-01")

    read_back = read_site(site["id"])
    assert read_back["open_deficiency_weight"] == 6.00
    assert read_back["oversight_posture"] == "RESTRICTED"


def test_a_weight_of_exactly_sixteen_suspends_the_site():
    """The suspension threshold is inclusive too, so 16.00 exactly suspends.

    PRD 2.10: "If the site has no in-window active coverage, **or** its
    `open_deficiency_weight` is at least 16.0, the posture is `SUSPENDED`."

    Design: Difficulty/boundary_precision_check/oversight_posture_walks_inclusive_weight_thresholds_six_and_sixteen
    """
    site, _a, inspection_b, inspection_c = _three_surveys_totalling_sixteen_points()

    issue_survey(inspection_b["id"], SURVEYOR, issued_on="2026-08-01")
    issue_survey(inspection_c["id"], SURVEYOR, issued_on="2026-08-01")

    read_back = read_site(site["id"])
    assert read_back["open_deficiency_weight"] == 16.00
    assert read_back["oversight_posture"] == "SUSPENDED"
    assert read_back["manual_entry_blocked"] is True
    assert read_back["inspection_readiness_score"] == 60.00
    assert read_inspection(inspection_c["id"])["issued_weight_total"] == 10.00
