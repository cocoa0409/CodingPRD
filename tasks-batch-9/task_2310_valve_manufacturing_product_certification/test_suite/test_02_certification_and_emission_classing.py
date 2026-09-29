"""Certification, fugitive-emission classing and the certification rejection order.

Fugitive-emission behaviour is scored twice by two different rules that deliberately
disagree, and certification itself sits at the meeting point of several bands of the
rejection ladder — the state band, the duty band and the license-posture band.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    CertStatus,
    CompliancePosture,
    EmissionLeakClass,
    ErrorId,
    LicenseStatus,
    ModelStatus,
    assert_emission_classes,
    assert_unit_dimensions,
    factories,
    fixtures,
    make_quality_manager_headers,
)

WITNESS = "u-77"


# ─── Fugitive-emission service: two rules over one record set ───


def _fugitive_emission_line(api):
    """A soft-seated class-300 ball design claiming fugitive-emission service, with a
    prototype unit type-tested twice: 40 ppm held 300 s and then 140 ppm held 100 s."""
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-02",
        foundry_name="Beta Castings",
        country_code="IN",
        heat_number="H-2001",
        mtr_document_ref="MTR-2001",
        model_code="BV-300-FE",
        seat_type="SOFT",
        base_break_torque_nm=420.0,
        required_special_services=["FUGITIVE_EMISSION"],
        release_design=False,
        license_code="MON-02",
        scope_valve_types=["BALL"],
    )
    fixtures.submit_model_for_review(api, line["model"]["id"])
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-FE-1",
        special_services=["FUGITIVE_EMISSION"],
    )
    fixtures.advance_to_assembled(api, unit["id"])
    fixtures.record_test(
        api,
        unit["id"],
        "SHELL",
        test_bench_code="BENCH-1",
        started_at="2026-08-01T08:00:00Z",
        ended_at="2026-08-01T09:00:00Z",
        test_pressure_bar=80.0,
        hold_seconds=60,
    )
    fixtures.record_test(
        api,
        unit["id"],
        "SEAT",
        test_bench_code="BENCH-1",
        started_at="2026-08-01T09:00:00Z",
        ended_at="2026-08-01T10:00:00Z",
        test_pressure_bar=60.0,
        hold_seconds=60,
    )
    fixtures.record_test(
        api,
        unit["id"],
        "FUGITIVE_EMISSION",
        test_bench_code="BENCH-2",
        started_at="2026-08-01T08:00:00Z",
        ended_at="2026-08-01T09:00:00Z",
        test_pressure_bar=0.0,
        hold_seconds=300,
        leak_rate_ppm=40.0,
    )
    fixtures.record_test(
        api,
        unit["id"],
        "FUGITIVE_EMISSION",
        test_bench_code="BENCH-2",
        started_at="2026-08-01T09:00:00Z",
        ended_at="2026-08-01T10:00:00Z",
        test_pressure_bar=0.0,
        hold_seconds=100,
        leak_rate_ppm=140.0,
    )
    return {"line": line, "unit": unit}


def test_01_the_peak_reading_rule_bands_the_largest_leak_rate_as_it_is_written(api):
    """The provisional class comes from the peak of the two readings and is available
    before certification, while the time-weighted answer is not yet computed.

    PRD §3.4: "rule takes the largest `leak_rate_ppm` in the input set and is
    recomputed on every fugitive-emission record written, landing in
    `provisional_emission_leak_class`." The peak of 140 falls in the band where "above
    100 and at or below 500 is class `B`".

    Design: Difficulty/dual_variant_calc/fugitive_emission_peak_variant_vs_time_weighted_variant
    """
    scenario = _fugitive_emission_line(api)

    unit = fixtures.read_unit(api, scenario["unit"]["id"])

    assert_emission_classes(unit, provisional=EmissionLeakClass.B, final=None)
    assert_unit_dimensions(unit, cert_status=CertStatus.TESTS_PASSED)


def test_02_the_time_weighted_rule_freezes_a_different_class_at_certification(api):
    """Certification computes the time-weighted figure once and freezes it, and the
    weighted 65.00 bands one class better than the peak.

    PRD §3.4: "rule multiplies each record's `leak_rate_ppm` by its own `hold_seconds`,
    sums those products, divides by the sum of the `hold_seconds`, and rounds the
    quotient half up to 2 decimal places before banding; it is evaluated exactly once,
    at certification, and frozen into `final_emission_leak_class`." PRD §3.7: "A
    successful certification writes `certified_by_user_id` from `X-User-ID` and
    `certified_at` from the current logical-clock instant, freezes
    `final_emission_leak_class` from the time-weighted rule of §3.4".

    Design: Difficulty/dual_variant_calc/fugitive_emission_peak_variant_vs_time_weighted_variant
    """
    scenario = _fugitive_emission_line(api)
    fixtures.model_action(api, scenario["line"]["model"]["id"], "RELEASE")

    unit = fixtures.certify_unit(api, scenario["unit"]["id"])

    assert_emission_classes(unit, provisional=EmissionLeakClass.B, final=EmissionLeakClass.A)
    assert_unit_dimensions(unit, cert_status=CertStatus.CERTIFIED)
    assert unit["certified_by_user_id"] == "qm-1"
    # A fresh system's logical clock reads 2026-08-01T00:00:00Z (PRD §2.5).
    assert unit["certified_at"] is not None
    assert unit["certified_at"].startswith("2026-08-01T00:00:00"), (
        f"certified_at should be the logical-clock instant, got {unit['certified_at']!r}"
    )


def test_03_the_two_rules_disagree_and_both_answers_are_retained(api):
    """A short high reading diluted by a long low one splits the two rules, and the
    design earns the service it was type-tested for.

    PRD §3.4: "The two can disagree, and usually do when a short high reading is diluted
    by a long low one: a 40 ppm reading held 300 seconds alongside a 140 ppm reading held
    100 seconds gives a provisional class of `B` from the peak of 140 and a final class of
    `A` from the weighted 65.00."

    Design: Difficulty/dual_variant_calc/fugitive_emission_peak_variant_vs_time_weighted_variant
    """
    scenario = _fugitive_emission_line(api)
    fixtures.model_action(api, scenario["line"]["model"]["id"], "RELEASE")
    fixtures.certify_unit(api, scenario["unit"]["id"])

    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    model = fixtures.read_model(api, scenario["line"]["model"]["id"])

    assert unit["provisional_emission_leak_class"] != unit["final_emission_leak_class"], (
        "The peak rule and the time-weighted rule must be retained separately"
    )
    assert unit["provisional_emission_leak_class"] == EmissionLeakClass.B
    assert unit["final_emission_leak_class"] == EmissionLeakClass.A
    assert model["qualified_special_services"] == ["FUGITIVE_EMISSION"]
    assert model["status"] == ModelStatus.RELEASED


# ─── The certification rejection order: state before duty ───


def _witness_certifies_line(api):
    """A released class-300 ball design whose unit was tested entirely by u-77 —
    shell passing, seat failing — leaving the unit at TESTS_FAILED."""
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-08",
        foundry_name="Theta Castings",
        country_code="IN",
        heat_number="H-8001",
        mtr_document_ref="MTR-8001",
        model_code="BV-300-SOD",
        license_code="MON-09",
        scope_valve_types=["BALL"],
    )
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-SOD-1",
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id=WITNESS)
    fixtures.record_test(
        api,
        unit["id"],
        "SHELL",
        test_bench_code="BENCH-4",
        started_at="2026-08-01T08:00:00Z",
        ended_at="2026-08-01T09:00:00Z",
        test_pressure_bar=80.0,
        hold_seconds=60,
        technician_user_id=WITNESS,
    )
    fixtures.record_test(
        api,
        unit["id"],
        "SEAT",
        test_bench_code="BENCH-4",
        started_at="2026-08-01T09:00:00Z",
        ended_at="2026-08-01T10:00:00Z",
        test_pressure_bar=60.0,
        hold_seconds=60,
        result="FAIL",
        technician_user_id=WITNESS,
    )
    return {"line": line, "unit": unit}


def _certify_as(api, unit_id, user_id):
    return api.valve_unit_cert_action(
        unit_id, factories.cert_action_payload("CERTIFY"), make_quality_manager_headers(user_id)
    )


def test_04_the_state_error_outranks_the_duty_conflict_on_certification(api):
    """Both the state check and the duty check are violated by one certification, and
    the state error is the one reported.

    PRD §2.10: "A `QualityManager` who also recorded one of a unit's tests, certifying a
    unit whose seat test failed, must see the state error `ERR_UNIT_NOT_TEST_PASSED`
    (HTTP 409) from band 11 and not the duty error `ERR_SOD_TEST_WITNESS_CONFLICT` (HTTP
    403) from band 14."

    Design: Difficulty/priority_pair_validation_conflict/certify_state_error_outranks_duty_conflict
    """
    scenario = _witness_certifies_line(api)

    response = _certify_as(api, scenario["unit"]["id"], WITNESS)

    error_id = validate_error(response, ErrorId.UNIT_NOT_TEST_PASSED, 409)["error_id"]
    assert error_id != ErrorId.SOD_TEST_WITNESS_CONFLICT

    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert_unit_dimensions(unit, cert_status=CertStatus.TESTS_FAILED)
    assert unit["certified_by_user_id"] is None


def test_05_the_duty_conflict_surfaces_only_once_the_state_check_is_satisfied(api):
    """Re-running the failed seat test with a pass clears the state objection, and the
    same caller now meets the duty objection the state error had masked.

    PRD §3.4: "Writing a further record for the same test type moves the unit back from
    `TESTS_FAILED` to `TESTS_IN_PROGRESS`, so a seat test that failed and was re-run with
    a pass leaves the unit at `TESTS_PASSED` — the later record decides." PRD §3.7: "The
    certifying `X-User-ID` must differ from the `performed_by_user_id` of every test
    record on the unit, otherwise `ERR_SOD_TEST_WITNESS_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/certify_state_error_outranks_duty_conflict
    """
    scenario = _witness_certifies_line(api)
    fixtures.record_test(
        api,
        scenario["unit"]["id"],
        "SEAT",
        test_bench_code="BENCH-4",
        started_at="2026-08-01T10:00:00Z",
        ended_at="2026-08-01T11:00:00Z",
        test_pressure_bar=60.0,
        hold_seconds=60,
        technician_user_id=WITNESS,
    )
    retested = fixtures.read_unit(api, scenario["unit"]["id"])
    assert_unit_dimensions(retested, cert_status=CertStatus.TESTS_PASSED)

    response = _certify_as(api, scenario["unit"]["id"], WITNESS)

    validate_error(response, ErrorId.SOD_TEST_WITNESS_CONFLICT, 403)
    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert_unit_dimensions(unit, cert_status=CertStatus.TESTS_PASSED)
    assert unit["certified_at"] is None


# ─── Certification blocked by another entity's posture ───


def _frozen_license_line(api):
    """A unit of its own accord ready to certify, governed by a license that has since
    been suspended."""
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-12",
        foundry_name="Mu Castings",
        country_code="IN",
        heat_number="H-1201",
        mtr_document_ref="MTR-1201",
        model_code="BV-300-FRZ",
        license_code="MON-13",
        scope_valve_types=["BALL"],
        lead_auditor_user_id="aud-4",
    )
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-FRZ-1",
    )
    fixtures.advance_to_assembled(api, unit["id"], technician_user_id="tech-4")
    fixtures.record_test(
        api,
        unit["id"],
        "SHELL",
        test_bench_code="BENCH-6",
        started_at="2026-08-01T08:00:00Z",
        ended_at="2026-08-01T09:00:00Z",
        test_pressure_bar=80.0,
        hold_seconds=60,
        technician_user_id="tech-4",
    )
    fixtures.record_test(
        api,
        unit["id"],
        "SEAT",
        test_bench_code="BENCH-6",
        started_at="2026-08-01T09:00:00Z",
        ended_at="2026-08-01T10:00:00Z",
        test_pressure_bar=60.0,
        hold_seconds=60,
        technician_user_id="tech-4",
    )
    fixtures.license_action(api, line["license"]["id"], "SUSPEND", "aud-4")
    return {"line": line, "unit": unit}


def test_06_suspension_freezes_the_posture_without_touching_an_uncertified_unit(api):
    """Suspension freezes the license and decertifies only its certified units, so a
    unit still at TESTS_PASSED keeps its own dimensions.

    PRD §3.6: "the effect cascades in three links: the posture becomes `FROZEN`; every
    unit with this `monogram_license_id` and `cert_status` `CERTIFIED` moves to
    `DECERTIFIED` with `decertification_reason` `LICENSE_SUSPENDED`".

    Design: Difficulty/cross_entity_state_dependency/unit_certification_blocked_by_frozen_license_posture
    """
    scenario = _frozen_license_line(api)

    license_row = fixtures.read_license(api, scenario["line"]["license"]["id"])
    unit = fixtures.read_unit(api, scenario["unit"]["id"])

    assert license_row["license_status"] == LicenseStatus.SUSPENDED
    assert license_row["compliance_posture"] == CompliancePosture.FROZEN
    assert_unit_dimensions(unit, cert_status=CertStatus.TESTS_PASSED)
    assert unit["decertification_reason"] is None


def test_07_certification_is_refused_on_the_governing_license_s_frozen_posture(api):
    """The unit's own dimensions permit certification; the refusal comes from a
    different entity.

    PRD §3.7: "The governing license's `compliance_posture` must be `COMPLIANT` or
    `CONDITIONAL`; a `FROZEN` posture is `ERR_LICENSE_POSTURE_BLOCKED`, and so is a
    `CONDITIONAL` posture when the unit's `special_services` list is not empty."

    Design: Difficulty/cross_entity_state_dependency/unit_certification_blocked_by_frozen_license_posture
    """
    scenario = _frozen_license_line(api)

    response = _certify_as(api, scenario["unit"]["id"], "qm-3")

    validate_error(response, ErrorId.LICENSE_POSTURE_BLOCKED, 409)
    unit = fixtures.read_unit(api, scenario["unit"]["id"])
    assert_unit_dimensions(unit, cert_status=CertStatus.TESTS_PASSED)
    assert unit["certified_at"] is None
    assert unit["certified_by_user_id"] is None
