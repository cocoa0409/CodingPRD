"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Intended Parents
    # ------------------------------------------------------------------
    def create_intended_parent(self, payload, headers):
        return self._request("POST", "/intended-parents", payload, headers)

    def get_intended_parent(self, ip_id, headers):
        return self._request("GET", f"/intended-parents/{ip_id}", headers=headers)

    def list_intended_parents(self, headers, params=None):
        return self._request("GET", "/intended-parents", headers=headers, params=params)

    def submit_intended_parent(self, ip_id, headers):
        return self._request("POST", f"/intended-parents/{ip_id}/submit", headers=headers)

    def return_intended_parent_to_draft(self, ip_id, headers):
        return self._request("POST", f"/intended-parents/{ip_id}/return-to-draft", headers=headers)

    def start_screening_intended_parent(self, ip_id, headers):
        return self._request("POST", f"/intended-parents/{ip_id}/start-screening", headers=headers)

    def set_psych_intended_parent(self, ip_id, payload, headers):
        return self._request("POST", f"/intended-parents/{ip_id}/set-psych", payload, headers)

    def clear_intended_parent(self, ip_id, headers):
        return self._request("POST", f"/intended-parents/{ip_id}/clear", headers=headers)

    def reject_intended_parent(self, ip_id, headers):
        return self._request("POST", f"/intended-parents/{ip_id}/reject", headers=headers)

    # ------------------------------------------------------------------
    # Gestational Carriers
    # ------------------------------------------------------------------
    def create_carrier(self, payload, headers):
        return self._request("POST", "/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/carriers/{carrier_id}", headers=headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/carriers", headers=headers, params=params)

    def submit_carrier(self, carrier_id, headers):
        return self._request("POST", f"/carriers/{carrier_id}/submit", headers=headers)

    def start_screening_carrier(self, carrier_id, headers):
        return self._request("POST", f"/carriers/{carrier_id}/start-screening", headers=headers)

    def set_psych_carrier(self, carrier_id, payload, headers):
        return self._request("POST", f"/carriers/{carrier_id}/set-psych", payload, headers)

    def clear_carrier(self, carrier_id, headers):
        return self._request("POST", f"/carriers/{carrier_id}/clear", headers=headers)

    def reject_carrier(self, carrier_id, headers):
        return self._request("POST", f"/carriers/{carrier_id}/reject", headers=headers)

    def list_carrier_insurance_reviews(self, carrier_id, headers, params=None):
        return self._request("GET", f"/carriers/{carrier_id}/insurance-reviews", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Egg Donors
    # ------------------------------------------------------------------
    def create_egg_donor(self, payload, headers):
        return self._request("POST", "/egg-donors", payload, headers)

    def get_egg_donor(self, donor_id, headers):
        return self._request("GET", f"/egg-donors/{donor_id}", headers=headers)

    def list_egg_donors(self, headers, params=None):
        return self._request("GET", "/egg-donors", headers=headers, params=params)

    def submit_egg_donor(self, donor_id, headers):
        return self._request("POST", f"/egg-donors/{donor_id}/submit", headers=headers)

    def start_screening_egg_donor(self, donor_id, headers):
        return self._request("POST", f"/egg-donors/{donor_id}/start-screening", headers=headers)

    def clear_egg_donor(self, donor_id, headers):
        return self._request("POST", f"/egg-donors/{donor_id}/clear", headers=headers)

    def reject_egg_donor(self, donor_id, headers):
        return self._request("POST", f"/egg-donors/{donor_id}/reject", headers=headers)

    # ------------------------------------------------------------------
    # Insurance Reviews
    # ------------------------------------------------------------------
    def create_insurance_review(self, payload, headers):
        return self._request("POST", "/insurance-reviews", payload, headers)

    def get_insurance_review(self, review_id, headers):
        return self._request("GET", f"/insurance-reviews/{review_id}", headers=headers)

    def approve_insurance_review(self, review_id, headers):
        return self._request("POST", f"/insurance-reviews/{review_id}/approve", headers=headers)

    def identify_gap_insurance_review(self, review_id, headers):
        return self._request("POST", f"/insurance-reviews/{review_id}/identify-gap", headers=headers)

    def reject_insurance_review(self, review_id, headers):
        return self._request("POST", f"/insurance-reviews/{review_id}/reject", headers=headers)

    # ------------------------------------------------------------------
    # Matches
    # ------------------------------------------------------------------
    def create_match(self, payload, headers):
        return self._request("POST", "/matches", payload, headers)

    def get_match(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/matches", headers=headers, params=params)

    def get_match_comp_breakdown(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}/comp-breakdown", headers=headers)

    def counter_match(self, match_id, payload, headers):
        return self._request("POST", f"/matches/{match_id}/counter", payload, headers)

    def re_propose_match(self, match_id, payload, headers):
        return self._request("POST", f"/matches/{match_id}/re-propose", payload, headers)

    def accept_match(self, match_id, payload, headers):
        return self._request("POST", f"/matches/{match_id}/accept", payload, headers)

    def psych_clear_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/psych-clear", headers=headers)

    def void_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/void", headers=headers)

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def ip_sign_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/ip-sign", headers=headers)

    def carrier_sign_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/carrier-sign", headers=headers)

    def void_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/void", headers=headers)

    # ------------------------------------------------------------------
    # Journeys
    # ------------------------------------------------------------------
    def create_journey(self, payload, headers):
        return self._request("POST", "/journeys", payload, headers)

    def get_journey(self, journey_id, headers):
        return self._request("GET", f"/journeys/{journey_id}", headers=headers)

    def list_journeys(self, headers, params=None):
        return self._request("GET", "/journeys", headers=headers, params=params)

    def hold_journey(self, journey_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/hold", headers=headers)

    def resume_journey(self, journey_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/resume", headers=headers)

    def complete_journey(self, journey_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/complete", headers=headers)

    def terminate_journey(self, journey_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/terminate", headers=headers)

    def file_parentage(self, journey_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/parentage/file", headers=headers)

    def decide_parentage(self, journey_id, payload, headers):
        return self._request("POST", f"/journeys/{journey_id}/parentage/decide", payload, headers)

    # ------------------------------------------------------------------
    # Milestones (under Journey)
    # ------------------------------------------------------------------
    def create_milestone(self, journey_id, payload, headers):
        return self._request("POST", f"/journeys/{journey_id}/milestones", payload, headers)

    def list_milestones(self, journey_id, headers, params=None):
        return self._request("GET", f"/journeys/{journey_id}/milestones", headers=headers, params=params)

    def achieve_milestone(self, journey_id, milestone_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/milestones/{milestone_id}/achieve", headers=headers)

    def fail_milestone(self, journey_id, milestone_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/milestones/{milestone_id}/fail", headers=headers)

    # ------------------------------------------------------------------
    # Compensation Schedule (under Journey)
    # ------------------------------------------------------------------
    def create_comp_schedule(self, journey_id, payload, headers):
        return self._request("POST", f"/journeys/{journey_id}/comp-schedule", payload, headers)

    def list_comp_schedule(self, journey_id, headers, params=None):
        return self._request("GET", f"/journeys/{journey_id}/comp-schedule", headers=headers, params=params)

    def get_comp_schedule(self, schedule_id, headers):
        return self._request("GET", f"/comp-schedule/{schedule_id}", headers=headers)

    # ------------------------------------------------------------------
    # Escrow Accounts
    # ------------------------------------------------------------------
    def get_escrow_account(self, escrow_id, headers):
        return self._request("GET", f"/escrow-accounts/{escrow_id}", headers=headers)

    def list_escrow_accounts(self, headers, params=None):
        return self._request("GET", "/escrow-accounts", headers=headers, params=params)

    def get_escrow_summary(self, escrow_id, headers):
        return self._request("GET", f"/escrow-accounts/{escrow_id}/summary", headers=headers)

    def deposit_escrow(self, escrow_id, payload, headers):
        return self._request("POST", f"/escrow-accounts/{escrow_id}/deposit", payload, headers)

    def freeze_escrow(self, escrow_id, headers):
        return self._request("POST", f"/escrow-accounts/{escrow_id}/freeze", headers=headers)

    def unfreeze_escrow(self, escrow_id, headers):
        return self._request("POST", f"/escrow-accounts/{escrow_id}/unfreeze", headers=headers)

    def close_escrow(self, escrow_id, headers):
        return self._request("POST", f"/escrow-accounts/{escrow_id}/close", headers=headers)

    # ------------------------------------------------------------------
    # Disbursements (under Journey)
    # ------------------------------------------------------------------
    def create_disbursement(self, journey_id, payload, headers):
        return self._request("POST", f"/journeys/{journey_id}/disbursements", payload, headers)

    def list_disbursements_for_journey(self, journey_id, headers, params=None):
        return self._request("GET", f"/journeys/{journey_id}/disbursements", headers=headers, params=params)

    def approve_disbursement(self, journey_id, disbursement_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/disbursements/{disbursement_id}/approve", headers=headers)

    def release_disbursement(self, journey_id, disbursement_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/disbursements/{disbursement_id}/release", headers=headers)

    def reject_disbursement(self, journey_id, disbursement_id, headers):
        return self._request("POST", f"/journeys/{journey_id}/disbursements/{disbursement_id}/reject", headers=headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/disbursements", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Clock (test-driving)
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
