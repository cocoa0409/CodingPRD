"""Catalogue resources: Patient, Clinician, TestPanel.

PRD §3.1 fixes the input fields and constraints for each catalog
resource; PRD §2.4 fixes the common system-managed fields; PRD §2.10
fixes optimistic concurrency control.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    analyte_spec,
    assert_clinician,
    assert_patient,
    assert_test_panel,
    assert_version_incremented_by_one,
    create_catalog_bundle,
    create_clinician_payload,
    create_patient_payload,
    create_test_panel_payload,
    make_lab_director_headers,
    make_ordering_provider_headers,
    patch_clinician_payload,
    random_mrn,
    random_panel_code,
    validate_error,
    validate_success,
)


# ===========================================================================
# Patient — PRD §3.1
# ===========================================================================
class TestPatientCatalog:

    def test_create_patient_returns_201_and_persisted_record(self, api):
        """PRD §3.1: "A `Patient` is created by either an
        `OrderingProvider` or a `LabDirector`."

        Claim: POST /patients returns 201 with a persisted Patient
        whose mrn equals the supplied value.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        mrn = random_mrn()
        payload = create_patient_payload(mrn=mrn)
        res = api.create_patient(payload, op_headers)
        patient = validate_success(res, 201)
        assert_patient(patient)
        assert patient["mrn"] == mrn

    def test_create_patient_default_notification_consent(self, api):
        """PRD §3.1: "The optional `notification_consent` defaults to
        `SMS_AND_VOICE` and may be set to `VOICE_ONLY` or `NONE`."

        Claim: omitting notification_consent yields a persisted record
        whose notification_consent is SMS_AND_VOICE.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        payload = create_patient_payload()
        assert "notification_consent" not in payload
        patient = validate_success(
            api.create_patient(payload, op_headers), 201,
        )
        assert patient.get("notification_consent") == "SMS_AND_VOICE"

    @pytest.mark.parametrize("bad_mrn", [
        "AB1234567",
        "ABC12345678",
        "ab12345678",
        "12345678AB",
        "AB-1234-5678",
    ])
    def test_invalid_mrn_format_rejected(self, api, bad_mrn):
        """PRD §2.13: "Generic malformed-input failures — invalid
        E.164 phone strings, ill-formed ISO 8601 timestamps, missing
        required body fields, regex failures on `mrn` (which must
        match the format of two uppercase letters followed by eight
        digits) or `npi` (ten digits) or `code` (3 to 20 uppercase
        letters, digits, or underscores) — are reported with
        `ERR_VALIDATION`."

        Claim: malformed mrn -> ERR_VALIDATION.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        payload = create_patient_payload(mrn=bad_mrn)
        res = api.create_patient(payload, op_headers)
        validate_error(res, "ERR_VALIDATION")

    def test_duplicate_mrn_rejected(self, api):
        """PRD §3.1: "Each patient is identified externally by `mrn`,
        the medical record number, which must be unique across
        patients and conform to the format of two uppercase letters
        followed by eight digits."

        Claim: creating a second Patient with the same mrn fails.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        op_headers = make_ordering_provider_headers(
            bundle["ordering_provider"]["id"],
        )
        mrn = random_mrn()
        first = api.create_patient(
            create_patient_payload(mrn=mrn), op_headers,
        )
        validate_success(first, 201)
        second = api.create_patient(
            create_patient_payload(mrn=mrn), op_headers,
        )
        assert second.status_code >= 400


# ===========================================================================
# Clinician — PRD §3.1
# ===========================================================================
class TestClinicianCatalog:

    def test_create_clinician_returns_201_default_active(self, api):
        """PRD §3.1: "A new clinician is active by default; a
        `LabDirector` may later toggle the `active` flag or update
        `phone_e164` on an existing clinician, optionally supplying
        `version` for OCC."

        Claim: POST /clinicians returns 201 with active == true.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        director_headers = make_lab_director_headers(
            bundle["director"]["id"],
        )
        res = api.create_clinician(
            create_clinician_payload(role_kind="LAB_TECH"),
            director_headers,
        )
        clin = validate_success(res, 201)
        assert_clinician(clin)
        assert clin["active"] is True

    @pytest.mark.parametrize("bad_npi", [
        "123456789",
        "12345678901",
        "12345abcd0",
        "",
    ])
    def test_invalid_npi_rejected(self, api, bad_npi):
        """PRD §2.13: "Generic malformed-input failures — invalid
        E.164 phone strings, ill-formed ISO 8601 timestamps, missing
        required body fields, regex failures on `mrn` (which must
        match the format of two uppercase letters followed by eight
        digits) or `npi` (ten digits) or `code` (3 to 20 uppercase
        letters, digits, or underscores) — are reported with
        `ERR_VALIDATION`."

        Claim: malformed npi -> ERR_VALIDATION.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        director_headers = make_lab_director_headers(
            bundle["director"]["id"],
        )
        payload = create_clinician_payload(
            role_kind="LAB_TECH", npi=bad_npi,
        )
        res = api.create_clinician(payload, director_headers)
        validate_error(res, "ERR_VALIDATION")

    def test_patch_clinician_active_flag_increments_version(self, api):
        """PRD §3.1: "a `LabDirector` may later toggle the `active`
        flag or update `phone_e164` on an existing clinician,
        optionally supplying `version` for OCC."

        PRD §2.10: "On every persisted mutation — including state
        transitions, cascaded child or parent updates, and
        recomputations — the server bumps `updated_at` and increments
        `version` by exactly 1 on each mutated row."

        Claim: PATCH active=false succeeds and version increments by
        exactly 1.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        director_headers = make_lab_director_headers(
            bundle["director"]["id"],
        )
        before = bundle["lab_tech"]
        res = api.patch_clinician(
            before["id"], patch_clinician_payload(active=False),
            director_headers,
        )
        after = validate_success(res, 200)
        assert after["active"] is False
        assert_version_incremented_by_one(
            after["version"], before["version"],
        )

    def test_patch_clinician_stale_version_rejected(self, api):
        """PRD §2.10: "When the client supplies `version`, the server
        compares it to the current `version` of the targeted resource;
        a mismatch is rejected with `ERR_VERSION_CONFLICT`."

        Claim: PATCH with a stale version after the row has been
        mutated returns ERR_VERSION_CONFLICT.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        director_headers = make_lab_director_headers(
            bundle["director"]["id"],
        )
        clin = bundle["lab_tech"]
        stale_version = clin["version"]
        api.patch_clinician(
            clin["id"], patch_clinician_payload(active=False),
            director_headers,
        )
        res = api.patch_clinician(
            clin["id"],
            patch_clinician_payload(active=True, version=stale_version),
            director_headers,
        )
        validate_error(res, "ERR_VERSION_CONFLICT")


# ===========================================================================
# TestPanel — PRD §3.1
# ===========================================================================
class TestPanelCatalog:

    def test_create_test_panel_returns_201(self, api):
        """PRD §3.1: "A `TestPanel` is defined exclusively by a
        `LabDirector` with `code` (a LOINC-style identifier 3 to 20
        characters drawn from uppercase letters, digits, and
        underscores; unique across panels), `name`, `clia_complexity`
        (`WAIVED`, `MODERATE`, or `HIGH`), `specimen_type` (`BLOOD`,
        `URINE`, `CSF`, or `SWAB`), `stability_minutes` (a positive
        integer giving the maximum minutes the specimen may spend in
        transit before being rejected at lab receipt), and `analytes`."

        Claim: POST /test-panels returns 201 with the persisted panel.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        director_headers = make_lab_director_headers(
            bundle["director"]["id"],
        )
        payload = create_test_panel_payload(
            code=random_panel_code(),
            clia_complexity="HIGH",
            specimen_type="URINE",
            stability_minutes=60,
            analytes=[
                analyte_spec(
                    analyte_code="GLU", unit="mg/dL",
                    critical_low=40, critical_high=300,
                ),
            ],
        )
        res = api.create_test_panel(payload, director_headers)
        panel = validate_success(res, 201)
        assert_test_panel(panel)
        assert panel["clia_complexity"] == "HIGH"
        assert panel["specimen_type"] == "URINE"
        assert panel["stability_minutes"] == 60

    def test_one_sided_critical_bound_accepted(self, api):
        """PRD §3.1: "Bounds may individually be null to express a
        one-sided critical range; when both bounds are present,
        `critical_low` must be less than `critical_high`."

        Claim: a panel with critical_high only (critical_low null) is
        accepted.
        """
        bundle = create_catalog_bundle(panel_complexity="MODERATE")
        director_headers = make_lab_director_headers(
            bundle["director"]["id"],
        )
        payload = create_test_panel_payload(
            analytes=[
                analyte_spec(
                    analyte_code="A1", unit="mg/dL",
                    critical_low=None, critical_high=300,
                ),
            ],
        )
        res = api.create_test_panel(payload, director_headers)
        panel = validate_success(res, 201)
        assert panel["analytes"][0]["critical_low"] is None
        assert panel["analytes"][0]["critical_high"] == 300
