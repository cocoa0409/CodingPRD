"""Two variants of one formula returning two different numbers from one dataset."""

from test_helpers import (
    COORDINATOR,
    SURVEYOR,
    SURVEYOR_BETA,
    add_finding,
    api_client,
    capture_result,
    correction_submission_payload,
    get_success_data,
    issue_survey,
    open_survey,
    read_deficiency,
    read_device,
    read_readiness,
    read_result,
    read_site,
    set_clock,
    setup_covered_site,
    setup_site_with_verified_lot,
)


# ─── readiness_basis_variant_divergence_on_submitted_correction ─────


def _site_with_submitted_correction():
    """Covered site whose only finding sits in CORRECTION_SUBMITTED, due 2026-09-30."""
    _certificate, site, _coverage = setup_covered_site(
        certificate_overrides={"certificate_number": "45D2243001"},
        site_overrides={
            "name": "Cardiology POCT",
            "department_code": "DEPT-100",
            "complexity_scope": "WAIVED",
        },
    )
    inspection = open_survey(
        site["id"], SURVEYOR,
        inspection_type="INTERNAL_READINESS", scheduled_date="2026-08-01",
    )
    finding = add_finding(
        inspection["id"], SURVEYOR,
        category="QUALITY_CONTROL", severity="STANDARD_LEVEL",
        description="QC log gaps on the glucose meter",
        correction_due_date="2026-09-30",
    )
    issue_survey(inspection["id"], SURVEYOR, issued_on="2026-08-01")
    get_success_data(
        api_client.submit_correction(
            finding["id"], correction_submission_payload(
                correction_narrative="Retraining completed and QC log template deployed",
                evidence_ref="EV-QC-001",
            ),
            COORDINATOR,
        )
    )
    return site, finding


def test_as_of_actual_basis_counts_a_submitted_plan_of_correction():
    """The default readiness basis still charges for a citation whose plan is filed.

    PRD 3.9: "**As-of-actual** is the default and the basis for the value persisted
    in `inspection_readiness_score`. Its open deficiency weight is the sum of
    `weight` over the site's findings whose `status` is `OPEN`,
    `CORRECTION_SUBMITTED` or `CORRECTION_REJECTED`." and "**Deficiency penalty.**
    Multiply the open deficiency weight by 2.5, round the product half up to 2
    decimals, and take the lesser of that and the cap of 50.0."

    Design: Difficulty/dual_variant_calc/readiness_basis_variant_divergence_on_submitted_correction
    """
    site, finding = _site_with_submitted_correction()

    actual = read_readiness(site["id"], SURVEYOR_BETA, basis="AS_OF_ACTUAL")

    assert actual["basis"] == "AS_OF_ACTUAL"
    assert actual["open_deficiency_weight"] == 3.00
    assert actual["deficiency_penalty"] == 7.50
    assert actual["score"] == 92.50
    assert read_deficiency(finding["id"])["status"] == "CORRECTION_SUBMITTED"


def test_pre_survey_projected_basis_excludes_a_plan_due_in_the_future():
    """The projected basis drops the same finding and returns a strictly higher score.

    PRD 3.9: "Its open deficiency weight excludes every finding whose `status` is
    `CORRECTION_SUBMITTED` and whose `correction_due_date` is on or after the
    current logical date — such a plan is assumed to be accepted on time — while
    findings in every other status count exactly as they do under as-of-actual."

    Design: Difficulty/dual_variant_calc/readiness_basis_variant_divergence_on_submitted_correction
    """
    site, finding = _site_with_submitted_correction()

    actual = read_readiness(site["id"], SURVEYOR_BETA, basis="AS_OF_ACTUAL")
    projected = read_readiness(site["id"], SURVEYOR_BETA, basis="PRE_SURVEY_PROJECTED")

    assert projected["basis"] == "PRE_SURVEY_PROJECTED"
    assert projected["deficiency_penalty"] == 0.00
    assert projected["score"] == 100.00
    assert projected["score"] - actual["score"] == 7.50
    assert read_deficiency(finding["id"])["weight"] == 3.00


def test_projected_read_never_persists_its_advisory_score():
    """After a projected read the stored score is still the as-of-actual figure.

    PRD 3.9: "Regardless of which basis was requested, the read persists the
    as-of-actual score into the site's `inspection_readiness_score` — the projected
    figure is advisory and is never stored."

    Design: Difficulty/dual_variant_calc/readiness_basis_variant_divergence_on_submitted_correction
    """
    site, _finding = _site_with_submitted_correction()

    read_readiness(site["id"], SURVEYOR_BETA, basis="PRE_SURVEY_PROJECTED")

    stored = read_site(site["id"])
    assert stored["inspection_readiness_score"] == 92.50
    assert stored["oversight_posture"] == "OPEN"


# ─── device_qc_rate_calendar_basis_vs_day_of_use_basis_divergence ───


def _device_used_on_two_of_three_days():
    """One instrument QC-covered on 2026-08-01 and used on 2026-08-01 and 2026-08-03."""
    env = setup_site_with_verified_lot(
        certificate_overrides={"certificate_number": "45D2243002"},
        site_overrides={
            "name": "Endocrine POCT",
            "department_code": "DEPT-110",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Dana Reed"},
        device_overrides={"serial_number": "SN-0001"},
        lot_overrides={"lot_number": "LOT-A1"},
    )
    env["result_day_1"] = capture_result(
        env, patient_mrn="MRN-1001", measured_value=95.0
    )
    set_clock("2026-08-03T09:00:00Z")
    env["result_day_3"] = capture_result(
        env, patient_mrn="MRN-1002", measured_value=101.0
    )
    return env


def test_calendar_variant_divides_the_covered_day_by_every_day_in_the_window():
    """One covered day out of three calendar days reads 33.33.

    PRD 3.4: "`qc_compliance_rate_calendar` uses the **calendar-day** denominator:
    every day in the window, whether or not the instrument was used. This is the
    regulator-facing figure."

    Design: Difficulty/dual_variant_calc/device_qc_rate_calendar_basis_vs_day_of_use_basis_divergence
    """
    env = _device_used_on_two_of_three_days()

    device = read_device(env["device"]["id"], COORDINATOR)

    assert device["qc_compliance_rate_calendar"] == 33.33
    assert device["last_two_level_qc_pass_on"] == "2026-08-01"
    assert device["qc_next_due_at"] == "2026-08-31"


def test_day_of_use_variant_divides_the_same_covered_day_by_the_usage_days():
    """The same stored data reads 50.00 once idle days leave the denominator.

    PRD 3.4: "`qc_compliance_rate_day_of_use` uses the **day-of-use** denominator:
    the number of distinct days inside the window on which at least one patient
    result was created on that instrument."

    Design: Difficulty/dual_variant_calc/device_qc_rate_calendar_basis_vs_day_of_use_basis_divergence
    """
    env = _device_used_on_two_of_three_days()

    device = read_device(env["device"]["id"], COORDINATOR)

    assert device["qc_compliance_rate_day_of_use"] == 50.00
    assert device["use_day_count"] == 2
    assert (
        device["qc_compliance_rate_day_of_use"]
        - device["qc_compliance_rate_calendar"]
    ) == 16.67


def test_site_index_aggregates_the_day_of_use_variant_only():
    """The site index follows the day-of-use figure, not the calendar figure.

    PRD 3.4: "This is the figure that feeds the site index, and `use_day_count` is
    that same count of distinct usage days."

    Design: Difficulty/dual_variant_calc/device_qc_rate_calendar_basis_vs_day_of_use_basis_divergence
    """
    env = _device_used_on_two_of_three_days()

    site = read_site(env["site"]["id"])

    assert site["site_qc_compliance_index"] == 50.00
    assert read_result(env["result_day_1"]["id"])["posting_status"] == "PENDING_REVIEW"
    assert read_result(env["result_day_3"]["id"])["posting_status"] == "PENDING_REVIEW"
