"""Readiness and index outcomes that only a multi-term formula can produce."""

from test_helpers import (
    ADMIN,
    SURVEYOR,
    SURVEYOR_BETA,
    add_finding,
    capture_result,
    create_coverage,
    create_device,
    create_operator,
    create_reagent_lot,
    create_site,
    create_storage_unit,
    create_trained_operator,
    issue_survey,
    open_survey,
    read_certificate,
    read_device,
    read_pt_enrollment,
    read_readiness,
    read_site,
    set_clock,
    setup_covered_site,
    setup_pt_graded_events,
    setup_site_with_verified_lot,
    verify_lot,
)

# ─── readiness_four_penalty_terms_with_two_caps_binding ─────────────


def _moderate_site_with_all_four_penalties():
    """A MODERATE site carrying weight 8.00, a 1-of-2 competency gap, index 50.00
    and four unsuccessful proficiency events."""
    env = setup_site_with_verified_lot(
        certificate_overrides={
            "certificate_number": "45D2243003",
            "certificate_type": "CERTIFICATE_OF_COMPLIANCE",
            "permitted_complexity": "MODERATE",
        },
        site_overrides={
            "name": "Emergency POCT",
            "department_code": "DEPT-120",
            "complexity_scope": "MODERATE",
        },
        operator_overrides={"full_name": "Alma Ruiz"},
        device_overrides={"serial_number": "SN-0101"},
        lot_overrides={"lot_number": "LOT-B1"},
    )
    site_id = env["site"]["id"]
    # op_b is never trained, so it stays LOCKED_OUT: 1 of 2 operators.
    env["untrained"] = create_operator(
        site_id, full_name="Ben Osei", role_title="MEDICAL_ASSISTANT",
        hire_date="2026-03-01",
    )
    capture_result(env, patient_mrn="MRN-2001", measured_value=96.0)
    set_clock("2026-08-03T09:00:00Z")
    capture_result(env, patient_mrn="MRN-2002", measured_value=104.0)

    inspection = open_survey(
        site_id, SURVEYOR,
        inspection_type="BIENNIAL_SURVEY", scheduled_date="2026-08-03",
    )
    env["finding"] = add_finding(
        inspection["id"], SURVEYOR,
        category="QUALITY_CONTROL", severity="CONDITION_LEVEL",
        description="No two-level QC on days of patient testing",
        correction_due_date="2026-10-31",
    )
    issue_survey(inspection["id"], SURVEYOR, issued_on="2026-08-03")

    env["enrollment_glucose"], _ = setup_pt_graded_events(
        site_id, [60.00, 60.00], enrollment_overrides={"analyte": "GLUCOSE"},
    )
    env["enrollment_hba1c"], _ = setup_pt_graded_events(
        site_id, [60.00, 60.00], enrollment_overrides={"analyte": "HBA1C"},
    )
    return env


def test_four_simultaneous_penalties_with_two_caps_binding_score_twenty_nine_fifty():
    """All four terms fire at once and the score is 100.00 minus their sum.

    PRD 3.9: "Subtract all four penalties from 100.0, round the remainder half up
    to 2 decimals, and take the greater of that and 0.0 — the score never goes
    negative."

    Design: Difficulty/combinatorial_formula/readiness_four_penalty_terms_with_two_caps_binding_under_moderate_scope
    """
    env = _moderate_site_with_all_four_penalties()

    readiness = read_readiness(env["site"]["id"], SURVEYOR_BETA)

    assert readiness["basis"] == "AS_OF_ACTUAL"
    assert readiness["deficiency_penalty"] == 20.00
    assert readiness["competency_penalty"] == 12.50
    assert readiness["qc_penalty"] == 20.00
    assert readiness["pt_penalty"] == 18.00
    assert readiness["site_qc_compliance_index"] == 50.00
    assert readiness["pt_unsuccessful_count"] == 4
    assert readiness["score"] == 29.50


def test_moderate_scope_binds_the_proficiency_cap_at_eighteen_points():
    """Four failures at the MODERATE unit of 6 would be 24 points, so the cap binds.

    PRD 3.9: "**Proficiency penalty.** The per-failure unit depends on the site's
    declared `complexity_scope`: 6 points per unsuccessful proficiency event when
    the scope is `MODERATE`, and 3 points when it is `WAIVED`. Multiply the
    unsuccessful-event count by that unit and take the lesser of the product and
    the cap of 18.0."

    Design: Difficulty/combinatorial_formula/readiness_four_penalty_terms_with_two_caps_binding_under_moderate_scope
    """
    env = _moderate_site_with_all_four_penalties()

    readiness = read_readiness(env["site"]["id"], SURVEYOR_BETA)

    assert readiness["pt_unsuccessful_count"] == 4
    assert readiness["pt_penalty"] == 18.00
    assert read_pt_enrollment(env["enrollment_glucose"]["id"])["status"] == (
        "UNSUCCESSFUL_PARTICIPATION"
    )
    assert read_pt_enrollment(env["enrollment_hba1c"]["id"])["status"] == (
        "UNSUCCESSFUL_PARTICIPATION"
    )


def test_the_multi_term_score_is_persisted_and_the_weight_restricts_the_site():
    """The stored score matches the read and weight 8.00 alone restricts the site.

    PRD 2.10: "Otherwise, if its `open_deficiency_weight` is at least 6.0, **or**
    its `held_result_count` is at least 3, **or** twice its
    `locked_out_operator_count` is strictly greater than its
    `total_operator_count`, the posture is `RESTRICTED`."

    Design: Difficulty/combinatorial_formula/readiness_four_penalty_terms_with_two_caps_binding_under_moderate_scope
    """
    env = _moderate_site_with_all_four_penalties()

    read_readiness(env["site"]["id"], SURVEYOR_BETA)
    site = read_site(env["site"]["id"])
    device = read_device(env["device"]["id"])

    assert site["inspection_readiness_score"] == 29.50
    assert site["open_deficiency_weight"] == 8.00
    assert site["oversight_posture"] == "RESTRICTED"
    assert device["status"] == "QC_LOCKED"
    assert device["qc_lock_reason"] == "PT_UNSUCCESSFUL"


# ─── site_index_two_stage_rounding_order_pinned_at_forty_one_fifty ──


def _two_devices_at_thirty_three_and_fifty():
    """Instrument A used on three days, instrument B on two, both covered once."""
    _certificate, site, _coverage = setup_covered_site(
        certificate_overrides={"certificate_number": "45D2243004"},
        site_overrides={
            "name": "Family Medicine POCT",
            "department_code": "DEPT-130",
            "complexity_scope": "WAIVED",
        },
    )
    operator = create_trained_operator(site["id"], full_name="Cora Vance")
    storage_unit = create_storage_unit(site["id"])
    device_a = create_device(
        site["id"], serial_number="SN-0201",
        device_model="GlucoMeter-X", analyte="GLUCOSE",
    )
    device_b = create_device(
        site["id"], serial_number="SN-0202",
        device_model="A1cAnalyzer-Y", analyte="HBA1C",
    )
    lot_a = create_reagent_lot(
        site["id"], storage_unit["id"], device_model="GlucoMeter-X",
        lot_number="LOT-C1",
    )
    lot_b = create_reagent_lot(
        site["id"], storage_unit["id"], device_model="A1cAnalyzer-Y",
        lot_number="LOT-C2",
        control_min_level_1=5.0, control_max_level_1=7.0,
        control_min_level_2=9.0, control_max_level_2=11.0,
    )
    lot_a, _, _ = verify_lot(lot_a["id"], device_a["id"], operator["id"])
    lot_b, _, _ = verify_lot(
        lot_b["id"], device_b["id"], operator["id"],
        level_1_value=6.0, level_2_value=10.0,
    )

    env_a = {"device": device_a, "lot": lot_a, "operator": operator}
    env_b = {"device": device_b, "lot": lot_b, "operator": operator}

    capture_result(env_a, patient_mrn="MRN-3001", measured_value=98.0)
    capture_result(
        env_b, patient_mrn="MRN-3002", analyte="HBA1C", measured_value=6.4
    )
    set_clock("2026-08-02T09:00:00Z")
    capture_result(env_a, patient_mrn="MRN-3003", measured_value=105.0)
    set_clock("2026-08-03T09:00:00Z")
    capture_result(env_a, patient_mrn="MRN-3004", measured_value=92.0)
    capture_result(
        env_b, patient_mrn="MRN-3005", analyte="HBA1C", measured_value=7.1
    )
    return site, device_a, device_b


def test_site_index_rounds_each_instrument_to_a_whole_percent_before_averaging():
    """Rates of 33.33 and 50.00 aggregate to exactly 41.50, never 41.67.

    PRD 3.4: "**step one**, round each eligible instrument's
    `qc_compliance_rate_day_of_use` half up to a whole percent with no decimal
    places; **step two**, add those whole-percent values, divide by the number of
    eligible instruments, and round the quotient half up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/site_index_two_stage_rounding_order_pinned_at_forty_one_fifty
    """
    site, device_a, device_b = _two_devices_at_thirty_three_and_fifty()

    read_a = read_device(device_a["id"])
    read_b = read_device(device_b["id"])
    read_back = read_site(site["id"])

    assert read_a["qc_compliance_rate_day_of_use"] == 33.33
    assert read_a["use_day_count"] == 3
    assert read_b["qc_compliance_rate_day_of_use"] == 50.00
    assert read_b["use_day_count"] == 2
    assert read_back["site_qc_compliance_index"] == 41.50
    assert read_back["site_qc_compliance_index"] != 41.67


def test_the_pinned_index_feeds_a_capped_quality_control_penalty():
    """An index of 41.50 yields an uncapped 23.40, clipped to the 20.0 cap.

    PRD 3.9: "**Quality-control penalty.** Subtract the site's
    `site_qc_compliance_index` from 100.0, multiply the difference by 0.40, round
    half up to 2 decimals, and take the lesser of that and the cap of 20.0."

    Design: Difficulty/combinatorial_formula/site_index_two_stage_rounding_order_pinned_at_forty_one_fifty
    """
    site, _device_a, _device_b = _two_devices_at_thirty_three_and_fifty()

    readiness = read_readiness(site["id"], ADMIN)

    assert readiness["site_qc_compliance_index"] == 41.50
    assert readiness["qc_penalty"] == 20.00
    assert readiness["score"] == 80.00


def test_both_instruments_share_the_same_calendar_rate():
    """The calendar variant is identical for both instruments at 33.33.

    PRD 3.4: "The window starts on the later of the instrument's creation date and
    the date 30 days before the current logical date, and ends on the current
    logical date, both endpoints included."

    Design: Difficulty/combinatorial_formula/site_index_two_stage_rounding_order_pinned_at_forty_one_fifty
    """
    _site, device_a, device_b = _two_devices_at_thirty_three_and_fifty()

    assert read_device(device_a["id"])["qc_compliance_rate_calendar"] == 33.33
    assert read_device(device_b["id"])["qc_compliance_rate_calendar"] == 33.33


# ─── pt_penalty_unit_branch_waived_three_versus_moderate_six ────────


def _two_sites_with_two_failures_each():
    """One MODERATE certificate covering a WAIVED site and a MODERATE site."""
    certificate, site_waived, _coverage = setup_covered_site(
        certificate_overrides={
            "certificate_number": "45D2243005",
            "certificate_type": "CERTIFICATE_OF_COMPLIANCE",
            "permitted_complexity": "MODERATE",
        },
        site_overrides={
            "name": "Waived Clinic",
            "department_code": "DEPT-140",
            "complexity_scope": "WAIVED",
        },
    )
    site_moderate = create_site(
        name="Moderate Clinic", department_code="DEPT-141",
        complexity_scope="MODERATE",
    )
    create_coverage(site_moderate["id"], certificate["id"])
    enrollment_w, _ = setup_pt_graded_events(site_waived["id"], [60.00, 60.00])
    enrollment_m, _ = setup_pt_graded_events(site_moderate["id"], [60.00, 60.00])
    return certificate, site_waived, site_moderate, enrollment_w, enrollment_m


def test_waived_scope_charges_three_points_per_unsuccessful_event():
    """Two failures on a WAIVED site cost 6.00 and score 94.00.

    PRD 3.9: "**Proficiency penalty.** The per-failure unit depends on the site's
    declared `complexity_scope`: 6 points per unsuccessful proficiency event when
    the scope is `MODERATE`, and 3 points when it is `WAIVED`."

    Design: Difficulty/combinatorial_formula/pt_penalty_unit_branch_waived_three_versus_moderate_six
    """
    _cert, site_waived, _site_m, _enr_w, _enr_m = _two_sites_with_two_failures_each()

    readiness = read_readiness(site_waived["id"], ADMIN)

    assert readiness["pt_unsuccessful_count"] == 2
    assert readiness["pt_penalty"] == 6.00
    assert readiness["score"] == 94.00


def test_moderate_scope_charges_six_points_for_the_identical_input():
    """The same two failures on a MODERATE site cost 12.00 and score 88.00.

    PRD 3.9: "Multiply the unsuccessful-event count by that unit and take the
    lesser of the product and the cap of 18.0."

    Design: Difficulty/combinatorial_formula/pt_penalty_unit_branch_waived_three_versus_moderate_six
    """
    _cert, site_waived, site_moderate, _enr_w, _enr_m = (
        _two_sites_with_two_failures_each()
    )

    waived = read_readiness(site_waived["id"], ADMIN)
    moderate = read_readiness(site_moderate["id"], ADMIN)

    assert moderate["pt_unsuccessful_count"] == 2
    assert moderate["pt_penalty"] == 12.00
    assert moderate["score"] == 88.00
    assert waived["score"] - moderate["score"] == 6.00


def test_both_enrolments_reach_unsuccessful_participation_with_two_of_three_failures():
    """The second failure of the last three trips the severe branch on both sites.

    PRD 3.7: "**Unsuccessful participation.** When the outcome is `FAIL` and
    `fail_count_last_three` is at least 2, the event moves `PENDING →
    UNSUCCESSFUL_LOCKED` with `outcome` of `FAIL` and `graded_on` recorded. The
    enrolment moves `ENROLLED → UNSUCCESSFUL_PARTICIPATION`."

    Design: Difficulty/combinatorial_formula/pt_penalty_unit_branch_waived_three_versus_moderate_six
    """
    certificate, _site_w, _site_m, enrollment_w, enrollment_m = (
        _two_sites_with_two_failures_each()
    )

    read_w = read_pt_enrollment(enrollment_w["id"])
    read_m = read_pt_enrollment(enrollment_m["id"])

    assert read_w["status"] == "UNSUCCESSFUL_PARTICIPATION"
    assert read_w["fail_count_last_three"] == 2
    assert read_m["status"] == "UNSUCCESSFUL_PARTICIPATION"
    assert read_m["fail_count_last_three"] == 2
    assert read_certificate(certificate["id"])["covered_site_count"] == 2
