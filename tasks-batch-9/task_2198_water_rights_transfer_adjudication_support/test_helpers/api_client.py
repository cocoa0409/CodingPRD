"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Claimants (PRD §3.1)
    # ------------------------------------------------------------------
    def create_claimant(self, payload, headers):
        return self._request("POST", "/claimants", payload, headers)

    def get_claimant(self, claimant_id, headers):
        return self._request("GET", f"/claimants/{claimant_id}", headers=headers)

    def set_claimant_standing(self, claimant_id, standing_status, headers):
        return self._request(
            "PATCH",
            f"/claimants/{claimant_id}/standing",
            {"standing_status": standing_status},
            headers,
        )

    # ------------------------------------------------------------------
    # Water rights (PRD §3.1, §3.2)
    # ------------------------------------------------------------------
    def create_water_right(self, payload, headers):
        return self._request("POST", "/water-rights", payload, headers)

    def list_water_rights(self, headers, params=None):
        return self._request("GET", "/water-rights", payload=params, headers=headers)

    def get_water_right(self, right_id, headers):
        return self._request("GET", f"/water-rights/{right_id}", headers=headers)

    def activate_water_right(self, right_id, headers):
        return self._request(
            "POST", f"/water-rights/{right_id}/activate", {}, headers
        )

    def reinstate_water_right(self, right_id, reinstatement_note, headers):
        return self._request(
            "POST",
            f"/water-rights/{right_id}/reinstate",
            {"reinstatement_note": reinstatement_note},
            headers,
        )

    def declare_forfeiture(self, right_id, finding_note, headers):
        return self._request(
            "POST",
            f"/water-rights/{right_id}/declare-forfeiture",
            {"finding_note": finding_note},
            headers,
        )

    def get_forfeiture_assessment(self, right_id, headers):
        return self._request(
            "GET", f"/water-rights/{right_id}/forfeiture-assessment", headers=headers
        )

    # ------------------------------------------------------------------
    # Beneficial-use records (PRD §3.1)
    # ------------------------------------------------------------------
    def create_beneficial_use_record(self, right_id, payload, headers):
        return self._request(
            "POST", f"/water-rights/{right_id}/beneficial-use-records", payload, headers
        )

    def list_beneficial_use_records(self, right_id, headers, params=None):
        return self._request(
            "GET",
            f"/water-rights/{right_id}/beneficial-use-records",
            payload=params,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Points of diversion (PRD §3.1)
    # ------------------------------------------------------------------
    def create_point_of_diversion(self, right_id, payload, headers):
        return self._request(
            "POST", f"/water-rights/{right_id}/points-of-diversion", payload, headers
        )

    def list_points_of_diversion(self, right_id, headers, params=None):
        return self._request(
            "GET",
            f"/water-rights/{right_id}/points-of-diversion",
            payload=params,
            headers=headers,
        )

    def get_point_of_diversion(self, pod_id, headers):
        return self._request("GET", f"/points-of-diversion/{pod_id}", headers=headers)

    # ------------------------------------------------------------------
    # Consumptive-use studies (PRD §3.3)
    # ------------------------------------------------------------------
    def create_hcu_study(self, right_id, payload, headers):
        return self._request(
            "POST", f"/water-rights/{right_id}/hcu-studies", payload, headers
        )

    def list_hcu_studies(self, right_id, headers, params=None):
        return self._request(
            "GET",
            f"/water-rights/{right_id}/hcu-studies",
            payload=params,
            headers=headers,
        )

    def get_hcu_study(self, study_id, headers):
        return self._request("GET", f"/hcu-studies/{study_id}", headers=headers)

    def certify_hcu_study(self, study_id, expected_water_right_version, headers):
        return self._request(
            "POST",
            f"/hcu-studies/{study_id}/certify",
            {"expected_water_right_version": expected_water_right_version},
            headers,
        )

    # ------------------------------------------------------------------
    # Transfer applications (PRD §3.4)
    # ------------------------------------------------------------------
    def create_transfer_application(self, payload, headers):
        return self._request("POST", "/transfer-applications", payload, headers)

    def list_transfer_applications(self, headers, params=None):
        return self._request(
            "GET", "/transfer-applications", payload=params, headers=headers
        )

    def get_transfer_application(self, application_id, headers):
        return self._request(
            "GET", f"/transfer-applications/{application_id}", headers=headers
        )

    def submit_transfer_application(
        self, application_id, expected_water_right_version, headers
    ):
        return self._request(
            "POST",
            f"/transfer-applications/{application_id}/submit",
            {"expected_water_right_version": expected_water_right_version},
            headers,
        )

    def publish_transfer_application(self, application_id, headers):
        return self._request(
            "POST", f"/transfer-applications/{application_id}/publish", {}, headers
        )

    def close_protest_period(self, application_id, headers):
        return self._request(
            "POST",
            f"/transfer-applications/{application_id}/close-protest-period",
            {},
            headers,
        )

    def request_revision(self, application_id, revision_note, headers):
        return self._request(
            "POST",
            f"/transfer-applications/{application_id}/request-revision",
            {"revision_note": revision_note},
            headers,
        )

    def resubmit_transfer_application(
        self, application_id, requested_af, expected_water_right_version, headers
    ):
        return self._request(
            "POST",
            f"/transfer-applications/{application_id}/resubmit",
            {
                "requested_af": requested_af,
                "expected_water_right_version": expected_water_right_version,
            },
            headers,
        )

    def decide_transfer_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/transfer-applications/{application_id}/decide", payload, headers
        )

    def withdraw_transfer_application(self, application_id, withdrawal_reason, headers):
        return self._request(
            "POST",
            f"/transfer-applications/{application_id}/withdraw",
            {"withdrawal_reason": withdrawal_reason},
            headers,
        )

    # ------------------------------------------------------------------
    # Injury analyses (PRD §3.5)
    # ------------------------------------------------------------------
    def create_injury_analysis(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/transfer-applications/{application_id}/injury-analyses",
            payload,
            headers,
        )

    def list_injury_analyses(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/transfer-applications/{application_id}/injury-analyses",
            payload=params,
            headers=headers,
        )

    def get_injury_analysis(self, analysis_id, headers):
        return self._request("GET", f"/injury-analyses/{analysis_id}", headers=headers)

    # ------------------------------------------------------------------
    # Protests (PRD §3.6)
    # ------------------------------------------------------------------
    def create_protest(self, payload, headers):
        return self._request("POST", "/protests", payload, headers)

    def list_protests(self, headers, params=None):
        return self._request("GET", "/protests", payload=params, headers=headers)

    def get_protest(self, protest_id, headers):
        return self._request("GET", f"/protests/{protest_id}", headers=headers)

    def route_protest(self, protest_id, track, headers):
        return self._request(
            "POST", f"/protests/{protest_id}/route", {"track": track}, headers
        )

    def resolve_protest(self, protest_id, payload, headers):
        return self._request(
            "POST", f"/protests/{protest_id}/resolve", payload, headers
        )

    def withdraw_protest(self, protest_id, withdrawal_reason, headers):
        return self._request(
            "POST",
            f"/protests/{protest_id}/withdraw",
            {"withdrawal_reason": withdrawal_reason},
            headers,
        )

    # ------------------------------------------------------------------
    # Approval conditions (PRD §3.8)
    # ------------------------------------------------------------------
    def list_approval_conditions(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/transfer-applications/{application_id}/approval-conditions",
            payload=params,
            headers=headers,
        )

    def get_approval_condition(self, condition_id, headers):
        return self._request(
            "GET", f"/approval-conditions/{condition_id}", headers=headers
        )

    def pay_approval_condition(self, condition_id, headers):
        return self._request(
            "POST", f"/approval-conditions/{condition_id}/pay", {}, headers
        )

    def satisfy_approval_condition(self, condition_id, compliance_evidence, headers):
        return self._request(
            "POST",
            f"/approval-conditions/{condition_id}/satisfy",
            {"compliance_evidence": compliance_evidence},
            headers,
        )

    def violate_approval_condition(self, condition_id, violation_note, headers):
        return self._request(
            "POST",
            f"/approval-conditions/{condition_id}/violate",
            {"violation_note": violation_note},
            headers,
        )

    # ------------------------------------------------------------------
    # Water bank accounts (PRD §3.9)
    # ------------------------------------------------------------------
    def create_water_bank_account(self, payload, headers):
        return self._request("POST", "/water-bank-accounts", payload, headers)

    def list_water_bank_accounts(self, headers, params=None):
        return self._request(
            "GET", "/water-bank-accounts", payload=params, headers=headers
        )

    def get_water_bank_account(self, account_id, headers):
        return self._request(
            "GET", f"/water-bank-accounts/{account_id}", headers=headers
        )

    def create_deposit(self, account_id, payload, headers):
        return self._request(
            "POST", f"/water-bank-accounts/{account_id}/deposits", payload, headers
        )

    # ------------------------------------------------------------------
    # Lease assignments (PRD §3.9)
    # ------------------------------------------------------------------
    def create_lease_assignment(self, payload, headers):
        return self._request("POST", "/lease-assignments", payload, headers)

    def list_lease_assignments(self, headers, params=None):
        return self._request(
            "GET", "/lease-assignments", payload=params, headers=headers
        )

    def get_lease_assignment(self, lease_id, headers):
        return self._request("GET", f"/lease-assignments/{lease_id}", headers=headers)

    def activate_lease_assignment(self, lease_id, headers):
        return self._request(
            "POST", f"/lease-assignments/{lease_id}/activate", {}, headers
        )

    def resume_lease_assignment(self, lease_id, headers):
        return self._request(
            "POST", f"/lease-assignments/{lease_id}/resume", {}, headers
        )

    def complete_lease_assignment(self, lease_id, headers):
        return self._request(
            "POST", f"/lease-assignments/{lease_id}/complete", {}, headers
        )

    def cancel_lease_assignment(self, lease_id, cancellation_reason, headers):
        return self._request(
            "POST",
            f"/lease-assignments/{lease_id}/cancel",
            {"cancellation_reason": cancellation_reason},
            headers,
        )

    # ------------------------------------------------------------------
    # Decree dockets and adjudication claims (PRD §3.10)
    # ------------------------------------------------------------------
    def create_decree_docket(self, payload, headers):
        return self._request("POST", "/decree-dockets", payload, headers)

    def get_decree_docket(self, docket_id, headers):
        return self._request("GET", f"/decree-dockets/{docket_id}", headers=headers)

    def advance_docket_phase(self, docket_id, target_phase, headers):
        return self._request(
            "POST",
            f"/decree-dockets/{docket_id}/advance-phase",
            {"target_phase": target_phase},
            headers,
        )

    def create_adjudication_claim(self, payload, headers):
        return self._request("POST", "/adjudication-claims", payload, headers)

    def list_adjudication_claims(self, headers, params=None):
        return self._request(
            "GET", "/adjudication-claims", payload=params, headers=headers
        )

    def get_adjudication_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/adjudication-claims/{claim_id}", headers=headers
        )

    def examine_adjudication_claim(
        self, claim_id, examiner_recommended_af, examination_note, headers
    ):
        return self._request(
            "POST",
            f"/adjudication-claims/{claim_id}/examine",
            {
                "examiner_recommended_af": examiner_recommended_af,
                "examination_note": examination_note,
            },
            headers,
        )

    def verify_adjudication_claim(
        self, claim_id, verification_outcome, field_note, headers
    ):
        return self._request(
            "POST",
            f"/adjudication-claims/{claim_id}/verify",
            {"verification_outcome": verification_outcome, "field_note": field_note},
            headers,
        )

    def object_to_adjudication_claim(
        self, claim_id, objection_basis, objection_note, headers
    ):
        return self._request(
            "POST",
            f"/adjudication-claims/{claim_id}/object",
            {"objection_basis": objection_basis, "objection_note": objection_note},
            headers,
        )

    def decree_adjudication_claim(self, claim_id, decree_note, headers):
        return self._request(
            "POST",
            f"/adjudication-claims/{claim_id}/decree",
            {"decree_note": decree_note},
            headers,
        )

    # ------------------------------------------------------------------
    # Raw escape hatches for negative request-shape tests
    # ------------------------------------------------------------------
    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)

    def raw_get(self, path, headers, params=None):
        return self._request("GET", path, payload=params, headers=headers)

    def raw_patch(self, path, payload, headers):
        return self._request("PATCH", path, payload, headers)


api_client = ApiClient()
