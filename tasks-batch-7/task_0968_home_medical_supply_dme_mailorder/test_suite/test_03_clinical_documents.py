"""Clinical documentation: prescriptions, fit profiles (OCC), and the
prior-authorization denial/appeal cycle and window-overlap semantics."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    prescription_payload,
    create_payer_plan,
    create_patient,
    create_active_patient,
    verify_patient,
    create_prescription,
    create_fit_profile,
    create_prior_authorization,
    decide_prior_authorization,
    appeal_prior_authorization,
    INTAKE,
    PA_SPEC,
)


class TestPrescriptionCreation:
    def test_prescription_missing_required_field_returns_400(self, api):
        """PRD §3.3: "Creation takes `patient_id`, the `hcpcs_code` being
        authorized, the `prescriber_npi`, an optional `diagnosis_codes` array of
        ICD-10 codes, a `monthly_quantity` of authorized units per month".
        PRD §5: `ERR_INVALID_REQUEST` — 400 Bad Request.

        Design: Corner/entities/prescription_missing_required_field_returns_400
        """
        plan = create_payer_plan()
        patient = create_active_patient(plan["id"])

        payload = prescription_payload(patient["id"])
        payload.pop("hcpcs_code")
        resp = api.create_prescription(payload, INTAKE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_medicare_rx_without_diagnosis_rejected(self, api):
        """PRD §3.3: "when the patient's plan is `MEDICARE_DMEPOS`, at least one
        diagnosis code is required; creating the prescription without any is
        rejected with `ERR_DIAGNOSIS_REQUIRED` (HTTP 422)."

        Design: Corner/validations/medicare_rx_without_diagnosis_rejected
        """
        mcr = create_payer_plan(plan_type="MEDICARE_DMEPOS", coinsurance_pct=0.20, cycle_months=3)
        cash = create_payer_plan(plan_type="CASH_HSA", coinsurance_pct=1.00, cycle_months=1)
        pt_mcr = create_active_patient(mcr["id"])
        pt_cash = create_active_patient(cash["id"])

        payload = prescription_payload(pt_mcr["id"])
        payload.pop("diagnosis_codes")
        resp = api.create_prescription(payload, INTAKE)
        validate_error(resp, ApiErrorId.ERR_DIAGNOSIS_REQUIRED)

        payload_cash = prescription_payload(pt_cash["id"])
        payload_cash.pop("diagnosis_codes")
        rx = validate_success(api.create_prescription(payload_cash, INTAKE), expected_status=201)
        assert rx["status"] == "ACTIVE"


class TestPrescriptionWindowOverlap:
    def _patient_with_rx(self, api):
        plan = create_payer_plan()
        patient = create_active_patient(plan["id"])
        rx = create_prescription(
            patient["id"], hcpcs_code="A4419",
            effective_date="2026-05-01", expiration_date="2026-08-01",
        )
        return patient, rx

    def test_rx_adjacent_half_open_window_allowed(self, api):
        """PRD §3.3: "Adjacency is allowed: a new prescription whose
        `effective_date` equals the existing prescription's `expiration_date`
        does not overlap."

        Design: Difficulty/resource_temporal_overlap/prescription_half_open_window_overlap
        """
        patient, _rx = self._patient_with_rx(api)
        rx2 = validate_success(
            api.create_prescription(
                prescription_payload(
                    patient["id"], hcpcs_code="A4419",
                    effective_date="2026-08-01", expiration_date="2026-11-01",
                ),
                INTAKE,
            ),
            expected_status=201,
        )
        assert rx2["status"] == "ACTIVE"

    def test_rx_overlapping_half_open_window_rejected(self, api):
        """PRD §3.3: "no two `ACTIVE` prescriptions for the same patient and the
        same `hcpcs_code` may have overlapping half-open windows; an overlap is
        rejected with `ERR_PRESCRIPTION_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/prescription_half_open_window_overlap
        """
        patient, _rx = self._patient_with_rx(api)
        resp = api.create_prescription(
            prescription_payload(
                patient["id"], hcpcs_code="A4419",
                effective_date="2026-07-15", expiration_date="2026-10-01",
            ),
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_WINDOW_OVERLAP)


class TestPriorAuthWindowOverlap:
    def _patient_with_pa(self, api):
        plan = create_payer_plan()
        patient = create_active_patient(plan["id"])
        pa = create_prior_authorization(
            patient["id"], hcpcs_code="A6250",
            valid_from="2026-05-01", valid_to="2026-05-31",
        )
        return patient, pa

    def test_pa_adjacent_closed_window_rejected(self, api):
        """PRD §3.3: "because the window is closed, adjacency counts as overlap
        — a new `valid_from` equal to an existing `valid_to` collides."

        Design: Difficulty/resource_temporal_overlap/prior_auth_closed_window_overlap
        """
        patient, _pa = self._patient_with_pa(api)
        resp = api.create_prior_authorization(
            {
                "patient_id": patient["id"], "hcpcs_code": "A6250", "approved_units": 45,
                "valid_from": "2026-05-31", "valid_to": "2026-08-31",
            },
            PA_SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_WINDOW_OVERLAP)

    def test_pa_one_day_after_closed_window_allowed(self, api):
        """PRD §3.3: "Creation rejects any overlap with another authorization
        for the same patient and code that is still in `SUBMITTED`, `APPEALED`,
        or `APPROVED` status, with `ERR_AUTH_WINDOW_OVERLAP` (HTTP 409)" — a
        window starting the day after the existing `valid_to` does not overlap.

        Design: Difficulty/resource_temporal_overlap/prior_auth_closed_window_overlap
        """
        patient, _pa = self._patient_with_pa(api)
        pa2 = validate_success(
            api.create_prior_authorization(
                {
                    "patient_id": patient["id"], "hcpcs_code": "A6250", "approved_units": 45,
                    "valid_from": "2026-06-01", "valid_to": "2026-08-31",
                },
                PA_SPEC,
            ),
            expected_status=201,
        )
        assert pa2["status"] == "SUBMITTED"


class TestPriorAuthAppealCycle:
    def _patient_with_submitted_pa(self, api):
        plan = create_payer_plan()
        patient = create_active_patient(plan["id"])
        pa = create_prior_authorization(patient["id"], hcpcs_code="A6250")
        return patient, pa

    def test_pa_two_denial_appeal_loops_reach_approved(self, api):
        """PRD §3.3: "The payer's decision, recorded by a `PriorAuthSpecialist`
        with an `outcome` of `APPROVED` or `DENIED` plus an optional `note`,
        moves an authorization from `SUBMITTED` or `APPEALED` to `APPROVED` or
        `DENIED` respectively". PRD §3.3: "A `DENIED` authorization may be
        appealed, moving it to `APPEALED`".

        Design: Difficulty/non_linear_state_machine/prior_auth_denial_appeal_cycle
        """
        _patient, pa = self._patient_with_submitted_pa(api)
        pa_id = pa["id"]

        denied1 = decide_prior_authorization(pa_id, "DENIED")
        assert denied1["status"] == "DENIED"
        appealed1 = appeal_prior_authorization(pa_id)
        assert appealed1["status"] == "APPEALED"
        denied2 = decide_prior_authorization(pa_id, "DENIED")
        assert denied2["status"] == "DENIED"
        appealed2 = appeal_prior_authorization(pa_id)
        assert appealed2["status"] == "APPEALED"
        approved = decide_prior_authorization(pa_id, "APPROVED")
        assert approved["status"] == "APPROVED"

    def test_pa_appeal_count_and_version_track_the_cycle(self, api):
        """PRD §3.3: "A `DENIED` authorization may be appealed, moving it to
        `APPEALED` and incrementing its `appeal_count` by one (the count starts
        at 0)." PRD §2.4: "`version` (integer): a system-managed integer that
        increments by one with every modification to the resource".

        Design: Difficulty/non_linear_state_machine/prior_auth_denial_appeal_cycle
        """
        _patient, pa = self._patient_with_submitted_pa(api)
        pa_id = pa["id"]
        base_version = pa["version"]

        decide_prior_authorization(pa_id, "DENIED")
        first_appeal = appeal_prior_authorization(pa_id)
        assert first_appeal["appeal_count"] == 1
        decide_prior_authorization(pa_id, "DENIED")
        second_appeal = appeal_prior_authorization(pa_id)
        assert second_appeal["appeal_count"] == 2

        final = decide_prior_authorization(pa_id, "APPROVED")
        # create + DENIED + APPEALED + DENIED + APPEALED + APPROVED = 5 mutations
        assert final["version"] == base_version + 5, (
            f"five transitions must each increment version by one: "
            f"base {base_version} -> {final['version']}"
        )


class TestFitProfileOcc:
    def test_occ_fit_profile_stale_patient_version_rejected(self, api):
        """PRD §2.8: "If the patient's current `version` does not match —
        because another write has advanced it since the client's last read —
        the create is rejected with `ERR_STALE_VERSION` (HTTP 412)." PRD §3.3:
        "If a `CURRENT` profile already exists for the same patient and
        category, creating the new profile supersedes it: the prior profile
        flips to the terminal `SUPERSEDED` state, the new profile is `CURRENT`".

        Design: Corner/complexity_layers/occ_fit_profile_stale_patient_version_rejected
        """
        plan = create_payer_plan()
        patient = create_patient(plan["id"])
        verified = verify_patient(patient["id"], eligible=True)
        observed_version = verified["version"]

        fp1 = create_fit_profile(patient["id"], observed_version, category="OSTOMY", size_code="45MM")
        assert fp1["status"] == "CURRENT"

        # The first create bumped Patient.version, so the stale view is refused.
        resp = api.create_fit_profile(
            {
                "patient_id": patient["id"], "category": "OSTOMY", "size_code": "57MM",
                "measured_on": "2026-05-01", "expected_patient_version": observed_version,
            },
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.get_patient(patient["id"], INTAKE), expected_status=200)
        fp2 = create_fit_profile(patient["id"], fresh["version"], category="OSTOMY", size_code="57MM")
        assert fp2["status"] == "CURRENT"

        fp1_after = validate_success(api.get_fit_profile(fp1["id"], INTAKE), expected_status=200)
        assert fp1_after["status"] == "SUPERSEDED"

        profiles = validate_success(
            api.list_patient_fit_profiles(patient["id"], INTAKE,
                                          params={"category": "OSTOMY", "status": "CURRENT"}),
            expected_status=200,
        )
        current = [p for p in profiles if p["status"] == "CURRENT"]
        assert len(current) == 1 and current[0]["id"] == fp2["id"]
