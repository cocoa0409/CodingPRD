"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- TerminationCase ---
    def create_termination_case(self, payload, headers):
        return self._request("POST", "/termination-cases", payload, headers)

    def get_termination_case(self, case_id, headers):
        return self._request("GET", f"/termination-cases/{case_id}", headers=headers)

    def effectuate_termination(self, case_id, headers):
        return self._request(
            "POST", f"/termination-cases/{case_id}/effectuate-termination", {}, headers
        )

    def begin_distributions(self, case_id, headers):
        return self._request(
            "POST", f"/termination-cases/{case_id}/begin-distributions", {}, headers
        )

    def advance_to_reconciliation(self, case_id, headers):
        return self._request(
            "POST", f"/termination-cases/{case_id}/advance-to-reconciliation", {}, headers
        )

    def reopen_distributions(self, case_id, headers):
        return self._request(
            "POST", f"/termination-cases/{case_id}/reopen-distributions", {}, headers
        )

    def close_case(self, case_id, headers):
        return self._request("POST", f"/termination-cases/{case_id}/close", {}, headers)

    # --- Participant ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def flag_contact(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/contact-flags", payload, headers
        )

    def clear_contact_flag(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/clear-contact-flag", payload, headers
        )

    def declare_missing(self, participant_id, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/declare-missing", {}, headers
        )

    def locate_participant(self, participant_id, payload, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/locate", payload, headers
        )

    def apply_default_treatment(self, participant_id, headers):
        return self._request(
            "POST", f"/participants/{participant_id}/apply-default-treatment", {}, headers
        )

    # --- MissingSearchCase / SearchAttempt ---
    def get_search_case(self, search_case_id, headers):
        return self._request("GET", f"/search-cases/{search_case_id}", headers=headers)

    def list_search_cases(self, headers, params=None):
        return self._request("GET", "/search-cases", headers=headers, params=params)

    def record_attempt(self, search_case_id, payload, headers):
        return self._request(
            "POST", f"/search-cases/{search_case_id}/attempts", payload, headers
        )

    def list_attempts(self, search_case_id, headers, params=None):
        return self._request(
            "GET", f"/search-cases/{search_case_id}/attempts", headers=headers, params=params
        )

    def escalate_search_case(self, search_case_id, headers):
        return self._request(
            "POST", f"/search-cases/{search_case_id}/escalate", {}, headers
        )

    # --- ParticipantNotice ---
    def create_notice(self, payload, headers):
        return self._request("POST", "/notices", payload, headers)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/notices/{notice_id}", headers=headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/notices", headers=headers, params=params)

    # --- BlackoutPeriod ---
    def create_blackout_period(self, payload, headers):
        return self._request("POST", "/blackout-periods", payload, headers)

    def list_blackout_periods(self, case_id, headers, params=None):
        return self._request(
            "GET",
            f"/termination-cases/{case_id}/blackout-periods",
            headers=headers,
            params=params,
        )

    def activate_blackout(self, blackout_id, headers):
        return self._request(
            "POST", f"/blackout-periods/{blackout_id}/activate", {}, headers
        )

    def complete_blackout(self, blackout_id, headers):
        return self._request(
            "POST", f"/blackout-periods/{blackout_id}/complete", {}, headers
        )

    # --- DistributionElection ---
    def create_election(self, payload, headers):
        return self._request("POST", "/distribution-elections", payload, headers)

    def get_election(self, election_id, headers):
        return self._request(
            "GET", f"/distribution-elections/{election_id}", headers=headers
        )

    def list_elections(self, headers, params=None):
        return self._request(
            "GET", "/distribution-elections", headers=headers, params=params
        )

    def accept_election(self, election_id, headers):
        return self._request(
            "POST", f"/distribution-elections/{election_id}/accept", {}, headers
        )

    def reject_election(self, election_id, payload, headers):
        return self._request(
            "POST", f"/distribution-elections/{election_id}/reject", payload, headers
        )

    # --- Payout ---
    def list_participant_payouts(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/participants/{participant_id}/payouts", headers=headers, params=params
        )

    def list_election_payouts(self, election_id, headers):
        return self._request(
            "GET", f"/distribution-elections/{election_id}/payouts", headers=headers
        )

    def mark_payout_cleared(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/mark-cleared", {}, headers)

    def void_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/void", {}, headers)

    # --- PBGCTransfer ---
    def create_pbgc_transfer(self, payload, headers):
        return self._request("POST", "/pbgc-transfers", payload, headers)

    def list_participant_pbgc_transfers(self, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"/participants/{participant_id}/pbgc-transfers",
            headers=headers,
            params=params,
        )

    def confirm_pbgc_transfer(self, transfer_id, headers):
        return self._request(
            "POST", f"/pbgc-transfers/{transfer_id}/confirm", {}, headers
        )

    def record_pbgc_rejection(self, transfer_id, payload, headers):
        return self._request(
            "POST", f"/pbgc-transfers/{transfer_id}/record-rejection", payload, headers
        )

    # --- Forfeiture ---
    def create_forfeiture(self, payload, headers):
        return self._request("POST", "/forfeitures", payload, headers)

    def list_participant_forfeitures(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"/participants/{participant_id}/forfeitures", headers=headers, params=params
        )

    # --- DeterminationLetterRequest ---
    def create_dlr(self, payload, headers):
        return self._request("POST", "/determination-letter-requests", payload, headers)

    def list_dlrs(self, case_id, headers, params=None):
        return self._request(
            "GET",
            f"/termination-cases/{case_id}/determination-letter-requests",
            headers=headers,
            params=params,
        )

    def file_dlr(self, dlr_id, headers):
        return self._request(
            "POST", f"/determination-letter-requests/{dlr_id}/file", {}, headers
        )

    def record_determination(self, dlr_id, payload, headers):
        return self._request(
            "POST",
            f"/determination-letter-requests/{dlr_id}/record-determination",
            payload,
            headers,
        )

    def withdraw_dlr(self, dlr_id, headers):
        return self._request(
            "POST", f"/determination-letter-requests/{dlr_id}/withdraw", {}, headers
        )

    # --- FiduciaryLogEntry ---
    def create_fiduciary_log_entry(self, payload, headers):
        return self._request("POST", "/fiduciary-log-entries", payload, headers)

    def list_fiduciary_log_entries(self, case_id, headers, params=None):
        return self._request(
            "GET",
            f"/termination-cases/{case_id}/fiduciary-log-entries",
            headers=headers,
            params=params,
        )

    # --- ExpenseAllocation ---
    def create_expense_allocation(self, payload, headers):
        return self._request("POST", "/expense-allocations", payload, headers)

    def list_expense_allocations(self, case_id, headers, params=None):
        return self._request(
            "GET",
            f"/termination-cases/{case_id}/expense-allocations",
            headers=headers,
            params=params,
        )


api_client = ApiClient()
