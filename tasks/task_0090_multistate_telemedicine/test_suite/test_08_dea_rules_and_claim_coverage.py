"""DEA recency/modality outcomes, controlled-authority gate, and out-of-coverage claim denial.

Breadth coverage for the calculations corner section: the failing side of the DEA recency
boundary (181 days, schedule II), the schedule III-V video arm, the NONE exemption, the
controlled-authority gate, and claim denial when the payer does not cover the determined state.
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
    setup_cleared_visit,
)


class TestDeaRecencyOutcomes:

    def test_schedule_ii_at_181_days_fails(self, api):
        """PRD §3.7: "The recency condition is satisfied when such a prior visit exists and
        the whole-day difference between the logical clock's `current_utc` and that visit's
        completion time is at most 180 days — the boundary day, a difference of exactly 180
        days, still satisfies the window."
        PRD §3.7: "A controlled-substance authoring that fails the applicable
        recency-and-modality requirement is rejected with `ERR_DEA_EXAM_REQUIRED`."

        Design: Corner/calculations/dea_recency_181_days_schedule_II_fails
        """
        # Prior COMPLETED at clock 2026-01-01; clock advanced to 2026-07-01 == 181 days (> 180).
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
        set_clock("2026-07-01T00:00:00.000Z")
        new_visit = request_visit(physician["id"], patient["id"], modality="VIDEO",
                                  determined_state_code="CA", scheduled_at="2026-07-01T10:00:00.000Z")
        validate_success(api.run_compliance(new_visit["id"], phys_headers), 200)
        res = api.create_prescription(
            new_visit["id"], {"drug_name": "Adderall", "dea_schedule": "II", "days_supply": 30}, phys_headers,
        )
        validate_error(res, "ERR_DEA_EXAM_REQUIRED")

    def test_schedule_iv_on_video_visit_no_prior_exam_passes(self, api):
        """PRD §3.7: "for a schedule `III`, `IV`, or `V` drug, it suffices that *either* the
        recency condition holds or the current modality is `VIDEO`."

        Design: Corner/calculations/schedule_iv_on_video_visit_no_prior_exam_passes
        """
        # VIDEO visit, no prior exam; schedule IV passes via the video arm.
        _, _, _, cleared = setup_cleared_visit(controlled=True, dea_number="BV1234567", state_code="CA")
        phys_headers = make_physician_headers(cleared["physician_id"])
        res = api.create_prescription(
            cleared["id"], {"drug_name": "Tramadol", "dea_schedule": "IV", "days_supply": 14,
                            "expected_visit_prescription_version": 0}, phys_headers,
        )
        rx = validate_success(res, 201)
        assert rx["status"] == "ACTIVE", f"expected ACTIVE, got {rx['status']}"

    def test_non_controlled_prescription_skips_dea_rules(self, api):
        """PRD §3.7: "A non-controlled prescription (`NONE`) is exempt from this rule."
        PRD §3.7: "Controlled substances (`dea_schedule` other than `NONE`) carry three
        further gates. The first is authority: the prescribing physician must carry a
        `dea_number` that is not null, *and* the visit's governing license — the
        `StateLicense` named by the clearing `ComplianceCheck`'s `matched_license_id` —
        must have `controlled_substance_authority` set to true."

        Design: Corner/calculations/non_controlled_prescription_skips_dea_rules
        """
        # Physician has NO dea_number and a license WITHOUT controlled authority; a NONE rx still succeeds.
        _, _, _, cleared = setup_cleared_visit(controlled=False, dea_number=None, state_code="CA")
        phys_headers = make_physician_headers(cleared["physician_id"])
        res = api.create_prescription(
            cleared["id"], {"drug_name": "Amoxicillin", "dea_schedule": "NONE", "days_supply": 10}, phys_headers,
        )
        rx = validate_success(res, 201)
        assert rx["status"] == "ACTIVE", f"expected ACTIVE, got {rx['status']}"


class TestControlledAuthorityGate:

    def test_controlled_without_authority_returns_no_controlled_authority(self, api):
        """PRD §3.7: "A controlled-substance authoring that lacks either the federal DEA
        number or the state controlled-substance authority is rejected with
        `ERR_NO_CONTROLLED_AUTHORITY`."

        Design: Corner/calculations/controlled_without_authority_returns_no_controlled_authority
        """
        # Physician has a dea_number but the governing CA license has controlled authority false (default).
        _, _, _, cleared = setup_cleared_visit(controlled=False, dea_number="BV1234567", state_code="CA")
        phys_headers = make_physician_headers(cleared["physician_id"])
        res = api.create_prescription(
            cleared["id"], {"drug_name": "Tramadol", "dea_schedule": "IV", "days_supply": 14}, phys_headers,
        )
        validate_error(res, "ERR_NO_CONTROLLED_AUTHORITY")


class TestClaimCoverageDenial:

    def test_claim_denied_when_payer_does_not_cover_determined_state(self, api):
        """PRD §3.6: "If the payer's `covered_state_codes` does *not* contain the determined
        state, the claim is denied: it transitions from `SUBMITTED` to `DENIED`, and both
        `allowed_cents` and `plan_paid_cents` are set to zero."

        Design: Corner/calculations/claim_denied_when_payer_does_not_cover_determined_state
        """
        # Physician licensed in CA and TX; payer covers only CA; visit determined_state TX.
        # Routing depends only on the patient being insured (-> INSURANCE), so a TX claim is created,
        # then adjudicate denies it because TX is out of the payer's coverage map.
        set_clock("2026-04-01T09:00:00.000Z")
        physician = create_physician(imlc_eligible=True, home_state_code="CA")
        issue_license(physician["id"], state_code="CA", issuance_type="FULL")
        issue_license(physician["id"], state_code="TX", issuance_type="COMPACT_EXPEDITED")
        payer = validate_success(api.create_payer({
            "name": "Parity", "telehealth_parity": True, "copay_cents": 2500,
            "covered_state_codes": ["CA"], "allowed_amount_cents": 8000,
        }, officer_headers()), 201)
        patient = create_patient(email="a@x.com", residence_state_code="TX", insurance_payer_id=payer["id"])
        visit = request_visit(physician["id"], patient["id"], modality="VIDEO", determined_state_code="TX")
        phys_headers = make_physician_headers(physician["id"])
        validate_success(api.run_compliance(visit["id"], phys_headers), 200)
        validate_success(api.approve_visit(visit["id"], phys_headers), 200)
        claims, _ = validate_paginated(api.list_visit_claims(visit["id"], officer_headers()))
        claim_id = claims[0]["id"]
        denied = validate_success(api.adjudicate_claim(claim_id, officer_headers()), 200)
        assert denied["status"] == "DENIED", f"expected DENIED, got {denied['status']}"
        assert denied["allowed_cents"] == 0, f"denied allowed_cents should be 0, got {denied['allowed_cents']}"
        assert denied["plan_paid_cents"] == 0, f"denied plan_paid_cents should be 0, got {denied['plan_paid_cents']}"
