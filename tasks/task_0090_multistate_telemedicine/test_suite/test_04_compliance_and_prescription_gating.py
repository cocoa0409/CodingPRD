"""Validation-precedence conflicts, DEA recency boundary, and the empty-license-pool block.

Depth coverage for two explicitly-ordered precedence pairs (state-before-DEA on
prescription authoring; modality-before-license on run-compliance), the DEA recency
day boundary (exactly 180 passes), and the empty candidate-pool compliance block.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    make_physician_headers,
    make_patient_headers,
    board_headers,
    officer_headers,
    set_clock,
    create_physician,
    issue_license,
    create_patient,
    request_visit,
    setup_requested_visit,
)


class TestValidationPrecedencePairs:
    """PRD-stated check ordering wins when two validations both fail."""

    def test_state_check_beats_dea_recency_on_prescription(self, api):
        """PRD §3.7: "Thus a malformed body surfaces before any state objection, a state
        objection before the DEA recency objection, and the recency objection before the
        authority objection, with the stale-version rejection evaluated last."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_dea_safety_on_prescription
        """
        # Schedule-II rx (would fail DEA recency: no prior exam) on a still-REQUESTED visit
        # (state check fails). State check is ordered first -> ERR_INVALID_STATE.
        physician, license_, patient, visit = setup_requested_visit(
            controlled=True, dea_number="BV1234567", state_code="CA",
        )
        phys_headers = make_physician_headers(physician["id"])
        res = api.create_prescription(
            visit["id"], {"drug_name": "Adderall", "dea_schedule": "II", "days_supply": 30}, phys_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_state_check_beats_dea_recency_schedule_iv_audio_on_requested_visit(self, api):
        """PRD §3.7: "Thus a malformed body surfaces before any state objection, a state
        objection before the DEA recency objection, and the recency objection before the
        authority objection, with the stale-version rejection evaluated last."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_dea_safety_on_prescription
        """
        # Schedule-IV rx on an AUDIO_ONLY, still-REQUESTED visit, no prior exam: DEA recency
        # would fail (no recency, not video), but the state check is ordered first -> ERR_INVALID_STATE.
        physician, license_, patient, visit = setup_requested_visit(
            controlled=True, dea_number="BV1234567", state_code="CA",
            visit_overrides={"modality": "AUDIO_ONLY"},
        )
        phys_headers = make_physician_headers(physician["id"])
        res = api.create_prescription(
            visit["id"], {"drug_name": "Tramadol", "dea_schedule": "IV", "days_supply": 30}, phys_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_modality_check_beats_license_referential_on_run_compliance(self, api):
        """PRD §3.3: "First, the modality rule: an `AUDIO_ONLY` visit cannot be
        compliance-cleared on this platform — audio-only is not a permitted modality for
        an initial cleared visit. When the visit's `modality` is `AUDIO_ONLY`, the outcome
        is `BLOCKED` with a `reason_code` of `AUDIO_ONLY_NOT_PERMITTED`, and the request is
        rejected with `ERR_MODALITY_NOT_PERMITTED`."

        Design: Difficulty/priority_pair_validation_conflict/modality_safety_beats_license_referential_on_run_compliance
        """
        # AUDIO_ONLY visit in TX where the physician (licensed only in CA) has no TX license.
        # Both modality and licensure fail; modality is the FIRST block reason -> ERR_MODALITY_NOT_PERMITTED.
        set_clock("2026-04-01T09:00:00.000Z")
        physician = create_physician(home_state_code="CA")
        issue_license(physician["id"], state_code="CA", issuance_type="FULL")
        patient = create_patient(residence_state_code="TX")
        visit = request_visit(physician["id"], patient["id"],
                              modality="AUDIO_ONLY", determined_state_code="TX")
        phys_headers = make_physician_headers(physician["id"])
        res = api.run_compliance(visit["id"], phys_headers)
        validate_error(res, "ERR_MODALITY_NOT_PERMITTED")

    def test_modality_block_records_audio_only_reason_when_license_exists(self, api):
        """PRD §3.3: "First, the modality rule: an `AUDIO_ONLY` visit cannot be
        compliance-cleared on this platform — audio-only is not a permitted modality for
        an initial cleared visit. When the visit's `modality` is `AUDIO_ONLY`, the outcome
        is `BLOCKED` with a `reason_code` of `AUDIO_ONLY_NOT_PERMITTED`, and the request is
        rejected with `ERR_MODALITY_NOT_PERMITTED`."

        Design: Difficulty/priority_pair_validation_conflict/modality_safety_beats_license_referential_on_run_compliance
        """
        # AUDIO_ONLY visit in CA where the physician IS licensed: licensure passes, but the
        # modality block still fires first and records AUDIO_ONLY_NOT_PERMITTED.
        physician, license_, patient, visit = setup_requested_visit(
            state_code="CA", visit_overrides={"modality": "AUDIO_ONLY"},
        )
        phys_headers = make_physician_headers(physician["id"])
        res = api.run_compliance(visit["id"], phys_headers)
        validate_error(res, "ERR_MODALITY_NOT_PERMITTED")
        data, _ = validate_paginated(api.list_visit_compliance_checks(visit["id"], officer_headers()))
        assert data[0]["outcome"] == "BLOCKED", f"expected BLOCKED, got {data[0]['outcome']}"
        assert data[0]["reason_code"] == "AUDIO_ONLY_NOT_PERMITTED", (
            f"expected AUDIO_ONLY_NOT_PERMITTED, got {data[0]['reason_code']}"
        )


class TestDeaRecencyBoundary:
    """Schedule-II recency window: exactly 180 days satisfies (<=)."""

    def _setup_prior_completed_then_advance(self, api, advance_clock, new_scheduled_at):
        """Physician dea+controlled CA (license eff 2025-06-01); a prior VIDEO visit COMPLETED
        at clock 2026-01-01; then clock advanced; a new VIDEO visit cleared. Returns (physician, new_visit)."""
        set_clock("2026-01-01T00:00:00.000Z")
        physician = create_physician(dea_number="BV1234567", home_state_code="CA")
        issue_license(physician["id"], state_code="CA", issuance_type="FULL",
                      controlled_substance_authority=True,
                      effective_date="2025-06-01T00:00:00.000Z", expiration_date="2027-01-01T00:00:00.000Z")
        patient = create_patient(residence_state_code="CA")
        phys_headers = make_physician_headers(physician["id"])
        prior = request_visit(physician["id"], patient["id"], modality="VIDEO",
                              determined_state_code="CA", scheduled_at="2026-01-01T10:00:00.000Z")
        validate_success(api.run_compliance(prior["id"], phys_headers), 200)
        validate_success(api.approve_visit(prior["id"], phys_headers), 200)
        validate_success(api.complete_visit(prior["id"], phys_headers), 200)
        set_clock(advance_clock)
        new_visit = request_visit(physician["id"], patient["id"], modality="VIDEO",
                                  determined_state_code="CA", scheduled_at=new_scheduled_at)
        validate_success(api.run_compliance(new_visit["id"], phys_headers), 200)
        return physician, new_visit

    def test_schedule_ii_at_exactly_180_days_passes(self, api):
        """PRD §3.7: "The recency condition is satisfied when such a prior visit exists and
        the whole-day difference between the logical clock's `current_utc` and that visit's
        completion time is at most 180 days — the boundary day, a difference of exactly 180
        days, still satisfies the window."
        PRD §3.7: "for a schedule `II` drug, both the recency condition must hold *and* the
        current visit's `modality` must be `VIDEO` (the strictest case)".

        Design: Difficulty/boundary_precision_check/dea_recency_window_exact_180_days_passes
        """
        # Completion clock 2026-01-01; advanced to 2026-06-30 == prior + 180 days exactly.
        physician, new_visit = self._setup_prior_completed_then_advance(
            api, "2026-06-30T00:00:00.000Z", "2026-06-30T10:00:00.000Z")
        phys_headers = make_physician_headers(physician["id"])
        res = api.create_prescription(
            new_visit["id"], {"drug_name": "Adderall", "dea_schedule": "II", "days_supply": 30,
                              "expected_visit_prescription_version": 0}, phys_headers,
        )
        rx = validate_success(res, 201)
        assert rx["status"] == "ACTIVE", f"expected ACTIVE, got {rx['status']}"

    def test_schedule_ii_at_exactly_180_days_persists_active_prescription(self, api):
        """PRD §3.7: "The recency condition is satisfied when such a prior visit exists and
        the whole-day difference between the logical clock's `current_utc` and that visit's
        completion time is at most 180 days — the boundary day, a difference of exactly 180
        days, still satisfies the window."
        PRD §3.7: "A newly authored prescription has `status` `ACTIVE` and records its
        visit through `visit_id`."

        Design: Difficulty/boundary_precision_check/dea_recency_window_exact_180_days_passes
        """
        physician, new_visit = self._setup_prior_completed_then_advance(
            api, "2026-06-30T00:00:00.000Z", "2026-06-30T10:00:00.000Z")
        phys_headers = make_physician_headers(physician["id"])
        rx = validate_success(api.create_prescription(
            new_visit["id"], {"drug_name": "Adderall", "dea_schedule": "II", "days_supply": 30,
                              "expected_visit_prescription_version": 0}, phys_headers,
        ), 201)
        data, meta = validate_paginated(api.list_visit_prescriptions(new_visit["id"], phys_headers))
        assert meta["total_count"] == 1, f"expected one prescription on the visit, got {meta['total_count']}"
        assert data[0]["id"] == rx["id"], "listed prescription should be the one just authored"
        assert data[0]["dea_schedule"] == "II", f"expected schedule II, got {data[0]['dea_schedule']}"
        assert data[0]["status"] == "ACTIVE", f"expected ACTIVE, got {data[0]['status']}"


class TestEmptyLicensePoolBlock:
    """run-compliance blocks with NO_LICENSE_IN_STATE when no candidate license exists."""

    def _setup_no_license_state_visit(self, api):
        set_clock("2026-04-01T09:00:00.000Z")
        physician = create_physician(home_state_code="CA")
        issue_license(physician["id"], state_code="CA", issuance_type="FULL")
        patient = create_patient(residence_state_code="NV")
        visit = request_visit(physician["id"], patient["id"], determined_state_code="NV")
        return physician, visit

    def test_empty_pool_returns_no_license_in_state(self, api):
        """PRD §3.3: "Second, the licensure rule: when no candidate license qualifies, the
        outcome is `BLOCKED` with a null `matched_license_id`, and the request is rejected
        with `ERR_NO_LICENSE_IN_STATE`."

        Design: Difficulty/boundary_precision_check/empty_license_pool_blocks_run_compliance
        """
        physician, visit = self._setup_no_license_state_visit(api)
        phys_headers = make_physician_headers(physician["id"])
        res = api.run_compliance(visit["id"], phys_headers)
        validate_error(res, "ERR_NO_LICENSE_IN_STATE")
        visit_after = validate_success(api.get_visit(visit["id"], phys_headers), 200)
        assert visit_after["status"] == "REQUESTED", (
            f"no transition should occur, got {visit_after['status']}"
        )

    def test_empty_pool_records_blocked_check_with_no_license_reason(self, api):
        """PRD §3.3: "the licensure rule: when no candidate license qualifies, the outcome
        is `BLOCKED` with a null `matched_license_id`".
        PRD §3.3: "`NO_LICENSE_IN_STATE` when there is no matching physician-and-state
        license at all".

        Design: Difficulty/boundary_precision_check/empty_license_pool_blocks_run_compliance
        """
        physician, visit = self._setup_no_license_state_visit(api)
        phys_headers = make_physician_headers(physician["id"])
        api.run_compliance(visit["id"], phys_headers)
        data, _ = validate_paginated(api.list_visit_compliance_checks(visit["id"], officer_headers()))
        assert len(data) == 1, f"expected one ComplianceCheck, got {len(data)}"
        assert data[0]["outcome"] == "BLOCKED", f"expected BLOCKED, got {data[0]['outcome']}"
        assert data[0]["reason_code"] == "NO_LICENSE_IN_STATE", (
            f"expected NO_LICENSE_IN_STATE, got {data[0]['reason_code']}"
        )
