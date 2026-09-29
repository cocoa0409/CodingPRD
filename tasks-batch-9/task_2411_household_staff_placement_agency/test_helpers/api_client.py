"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -------------------------------------------------------
    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers=None):
        return self._request("GET", "/_clock", headers=headers)

    # --- Households ----------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def confidentiality_agreement(self, client_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/confidentiality-agreement", payload, headers
        )

    def create_ledger_adjustment(self, client_id, payload, headers):
        return self._request(
            "POST", f"/clients/{client_id}/ledger-adjustments", payload, headers
        )

    def list_ledger_entries(self, client_id, headers, params=None):
        return self._request(
            "GET", f"/clients/{client_id}/ledger-entries", headers=headers, params=params
        )

    # --- Fee schedules -------------------------------------------------------
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{fee_schedule_id}", headers=headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    def retire_fee_schedule(self, fee_schedule_id, payload=None, headers=None):
        return self._request(
            "POST", f"/fee-schedules/{fee_schedule_id}/retire", payload, headers
        )

    # --- Role requisitions ---------------------------------------------------
    def create_requisition(self, payload, headers):
        return self._request("POST", "/role-requisitions", payload, headers)

    def get_requisition(self, requisition_id, headers):
        return self._request(
            "GET", f"/role-requisitions/{requisition_id}", headers=headers
        )

    def list_requisitions(self, headers, params=None):
        return self._request("GET", "/role-requisitions", headers=headers, params=params)

    def scope_requisition(self, requisition_id, payload, headers):
        return self._request(
            "POST", f"/role-requisitions/{requisition_id}/scope", payload, headers
        )

    def finalize_scope(self, requisition_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/role-requisitions/{requisition_id}/finalize-scope",
            payload,
            headers,
        )

    def withdraw_requisition(self, requisition_id, payload=None, headers=None):
        return self._request(
            "POST", f"/role-requisitions/{requisition_id}/withdraw", payload, headers
        )

    def create_trial_engagement(self, requisition_id, payload, headers):
        return self._request(
            "POST",
            f"/role-requisitions/{requisition_id}/trial-engagements",
            payload,
            headers,
        )

    def create_accommodation_term(self, requisition_id, payload, headers):
        return self._request(
            "POST",
            f"/role-requisitions/{requisition_id}/accommodation-terms",
            payload,
            headers,
        )

    # --- Candidates ----------------------------------------------------------
    def create_candidate(self, payload, headers):
        return self._request("POST", "/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/candidates/{candidate_id}", headers=headers)

    def list_candidates(self, headers, params=None):
        return self._request("GET", "/candidates", headers=headers, params=params)

    def create_reference_check(self, candidate_id, payload, headers):
        return self._request(
            "POST", f"/candidates/{candidate_id}/reference-checks", payload, headers
        )

    def list_candidate_reference_checks(self, candidate_id, headers, params=None):
        return self._request(
            "GET",
            f"/candidates/{candidate_id}/reference-checks",
            headers=headers,
            params=params,
        )

    def create_background_verification(self, candidate_id, payload, headers):
        return self._request(
            "POST",
            f"/candidates/{candidate_id}/background-verifications",
            payload,
            headers,
        )

    def list_candidate_background_verifications(
        self, candidate_id, headers, params=None
    ):
        return self._request(
            "GET",
            f"/candidates/{candidate_id}/background-verifications",
            headers=headers,
            params=params,
        )

    def release_availability(self, candidate_id, payload=None, headers=None):
        return self._request(
            "POST", f"/candidates/{candidate_id}/release-availability", payload, headers
        )

    # --- Reference checks ----------------------------------------------------
    def get_reference_check(self, reference_id, headers):
        return self._request("GET", f"/reference-checks/{reference_id}", headers=headers)

    def list_reference_checks(self, headers, params=None):
        return self._request("GET", "/reference-checks", headers=headers, params=params)

    def verify_reference_check(self, reference_id, payload, headers):
        return self._request(
            "POST", f"/reference-checks/{reference_id}/verify", payload, headers
        )

    # --- Background verifications -------------------------------------------
    def get_background_verification(self, verification_id, headers):
        return self._request(
            "GET", f"/background-verifications/{verification_id}", headers=headers
        )

    def record_background_result(self, verification_id, payload, headers):
        return self._request(
            "POST",
            f"/background-verifications/{verification_id}/record-result",
            payload,
            headers,
        )

    def adjudicate_background_verification(self, verification_id, payload, headers):
        return self._request(
            "POST",
            f"/background-verifications/{verification_id}/adjudicate",
            payload,
            headers,
        )

    # --- Trial engagements ---------------------------------------------------
    def get_trial_engagement(self, trial_id, headers):
        return self._request("GET", f"/trial-engagements/{trial_id}", headers=headers)

    def list_trial_engagements(self, headers, params=None):
        return self._request(
            "GET", "/trial-engagements", headers=headers, params=params
        )

    def start_trial(self, trial_id, payload=None, headers=None):
        return self._request(
            "POST", f"/trial-engagements/{trial_id}/start", payload, headers
        )

    def record_trial_outcome(self, trial_id, payload, headers):
        return self._request(
            "POST", f"/trial-engagements/{trial_id}/record-outcome", payload, headers
        )

    def cancel_trial(self, trial_id, payload, headers):
        return self._request(
            "POST", f"/trial-engagements/{trial_id}/cancel", payload, headers
        )

    # --- Accommodation terms -------------------------------------------------
    def get_accommodation_term(self, term_id, headers):
        return self._request("GET", f"/accommodation-terms/{term_id}", headers=headers)

    def list_accommodation_terms(self, headers, params=None):
        return self._request(
            "GET", "/accommodation-terms", headers=headers, params=params
        )

    def respond_accommodation_term(self, term_id, payload, headers):
        return self._request(
            "POST", f"/accommodation-terms/{term_id}/respond", payload, headers
        )

    # --- Placements ----------------------------------------------------------
    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def confirm_placement_start(self, placement_id, payload=None, headers=None):
        return self._request(
            "POST", f"/placements/{placement_id}/confirm-start", payload, headers
        )

    def terminate_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/terminate", payload, headers
        )

    def list_fee_milestones(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"/placements/{placement_id}/fee-milestones",
            headers=headers,
            params=params,
        )

    def create_replacement_claim(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/replacement-claims", payload, headers
        )

    def list_placement_replacement_claims(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"/placements/{placement_id}/replacement-claims",
            headers=headers,
            params=params,
        )

    def create_payroll_handoff(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/placements/{placement_id}/payroll-handoffs", payload, headers
        )

    def list_placement_payroll_handoffs(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"/placements/{placement_id}/payroll-handoffs",
            headers=headers,
            params=params,
        )

    # --- Fee milestones ------------------------------------------------------
    def get_fee_milestone(self, milestone_id, headers):
        return self._request("GET", f"/fee-milestones/{milestone_id}", headers=headers)

    def invoice_fee_milestone(self, milestone_id, payload=None, headers=None):
        return self._request(
            "POST", f"/fee-milestones/{milestone_id}/invoice", payload, headers
        )

    def record_milestone_payment(self, milestone_id, payload, headers):
        return self._request(
            "POST", f"/fee-milestones/{milestone_id}/record-payment", payload, headers
        )

    def reverse_fee_milestone(self, milestone_id, payload=None, headers=None):
        return self._request(
            "POST", f"/fee-milestones/{milestone_id}/reverse", payload, headers
        )

    # --- Replacement claims --------------------------------------------------
    def get_replacement_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/replacement-claims/{claim_id}", headers=headers
        )

    def review_replacement_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/replacement-claims/{claim_id}/review", payload, headers
        )

    def provide_claim_info(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/replacement-claims/{claim_id}/provide-info", payload, headers
        )

    # --- Payroll handoffs ----------------------------------------------------
    def get_payroll_handoff(self, handoff_id, headers):
        return self._request("GET", f"/payroll-handoffs/{handoff_id}", headers=headers)

    def update_payroll_handoff_ein(self, handoff_id, payload, headers):
        return self._request(
            "POST", f"/payroll-handoffs/{handoff_id}/update-ein", payload, headers
        )

    def attest_payroll_handoff(self, handoff_id, payload, headers):
        return self._request(
            "POST", f"/payroll-handoffs/{handoff_id}/attest", payload, headers
        )

    # --- Non-solicitation enforcement ---------------------------------------
    def create_non_solicitation_case(self, payload, headers):
        return self._request("POST", "/non-solicitation-cases", payload, headers)

    def get_non_solicitation_case(self, case_id, headers):
        return self._request(
            "GET", f"/non-solicitation-cases/{case_id}", headers=headers
        )

    def list_non_solicitation_cases(self, headers, params=None):
        return self._request(
            "GET", "/non-solicitation-cases", headers=headers, params=params
        )

    def investigate_non_solicitation_case(self, case_id, payload=None, headers=None):
        return self._request(
            "POST", f"/non-solicitation-cases/{case_id}/investigate", payload, headers
        )

    def resolve_non_solicitation_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/non-solicitation-cases/{case_id}/resolve", payload, headers
        )

    def settle_non_solicitation_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/non-solicitation-cases/{case_id}/settle", payload, headers
        )


api_client = ApiClient()
