"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Agencies
    # ------------------------------------------------------------------
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    # ------------------------------------------------------------------
    # Agents (agency-scoped)
    # ------------------------------------------------------------------
    def create_agent(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/agents", payload, headers)

    def list_agents(self, agency_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/agents",
                             headers=headers, params=params)

    def get_agent(self, agency_id, agent_id, headers):
        return self._request("GET", f"/agencies/{agency_id}/agents/{agent_id}",
                             headers=headers)

    def certify_agent(self, agency_id, agent_id, headers):
        return self._request("POST",
                             f"/agencies/{agency_id}/agents/{agent_id}/certify",
                             {}, headers)

    def suspend_agent(self, agency_id, agent_id, headers):
        return self._request("POST",
                             f"/agencies/{agency_id}/agents/{agent_id}/suspend",
                             {}, headers)

    def reinstate_agent(self, agency_id, agent_id, headers):
        return self._request("POST",
                             f"/agencies/{agency_id}/agents/{agent_id}/reinstate",
                             {}, headers)

    def revoke_agent(self, agency_id, agent_id, headers):
        return self._request("POST",
                             f"/agencies/{agency_id}/agents/{agent_id}/revoke",
                             {}, headers)

    # ------------------------------------------------------------------
    # Clients (agency-scoped)
    # ------------------------------------------------------------------
    def create_client(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/clients", payload, headers)

    def list_clients(self, agency_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/clients",
                             headers=headers, params=params)

    def get_client(self, agency_id, client_id, headers):
        return self._request("GET", f"/agencies/{agency_id}/clients/{client_id}",
                             headers=headers)

    def initiate_transition(self, agency_id, client_id, target_agent_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/initiate_transition",
            {"target_agent_id": target_agent_id}, headers)

    def complete_transition(self, agency_id, client_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/complete_transition",
            {}, headers)

    def release_client(self, agency_id, client_id, headers):
        return self._request(
            "POST", f"/agencies/{agency_id}/clients/{client_id}/release",
            {}, headers)

    # ------------------------------------------------------------------
    # Teams
    # ------------------------------------------------------------------
    def create_team(self, payload, headers):
        return self._request("POST", "/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}", headers=headers)

    # ------------------------------------------------------------------
    # Cap seasons
    # ------------------------------------------------------------------
    def create_cap_season(self, team_id, payload, headers):
        return self._request("POST", f"/teams/{team_id}/cap_seasons", payload, headers)

    def list_cap_seasons(self, team_id, headers, params=None):
        return self._request("GET", f"/teams/{team_id}/cap_seasons",
                             headers=headers, params=params)

    def get_cap_season(self, team_id, cap_season_id, headers):
        return self._request("GET", f"/teams/{team_id}/cap_seasons/{cap_season_id}",
                             headers=headers)

    def lock_cap_season(self, team_id, cap_season_id, headers):
        return self._request("POST",
                             f"/teams/{team_id}/cap_seasons/{cap_season_id}/lock",
                             {}, headers)

    def unlock_cap_season(self, team_id, cap_season_id, headers):
        return self._request("POST",
                             f"/teams/{team_id}/cap_seasons/{cap_season_id}/unlock",
                             {}, headers)

    def close_cap_season(self, team_id, cap_season_id, headers):
        return self._request("POST",
                             f"/teams/{team_id}/cap_seasons/{cap_season_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------
    def create_contract(self, agency_id, client_id, payload, headers):
        return self._request(
            "POST", f"/agencies/{agency_id}/clients/{client_id}/contracts",
            payload, headers)

    def list_contracts(self, agency_id, client_id, headers, params=None):
        return self._request(
            "GET", f"/agencies/{agency_id}/clients/{client_id}/contracts",
            headers=headers, params=params)

    def get_contract(self, agency_id, client_id, contract_id, headers):
        return self._request(
            "GET",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}",
            headers=headers)

    def sign_contract(self, agency_id, client_id, contract_id,
                      expected_contract_version, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}/sign",
            {"expected_contract_version": expected_contract_version}, headers)

    def void_contract(self, agency_id, client_id, contract_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}/void",
            {}, headers)

    # ------------------------------------------------------------------
    # Proposals
    # ------------------------------------------------------------------
    def create_proposal(self, agency_id, client_id, contract_id, payload, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}/proposals",
            payload, headers)

    def list_proposals(self, agency_id, client_id, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}/proposals",
            headers=headers, params=params)

    def get_proposal(self, agency_id, client_id, contract_id, proposal_id, headers):
        return self._request(
            "GET",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/proposals/{proposal_id}",
            headers=headers)

    def submit_proposal(self, agency_id, client_id, contract_id, proposal_id,
                        expected_cap_season_version, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/proposals/{proposal_id}/submit",
            {"expected_cap_season_version": expected_cap_season_version}, headers)

    def counter_proposal(self, agency_id, client_id, contract_id, proposal_id,
                         counter_aav_cents, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/proposals/{proposal_id}/counter",
            {"counter_aav_cents": counter_aav_cents}, headers)

    def resubmit_proposal(self, agency_id, client_id, contract_id, proposal_id,
                          proposed_aav_cents, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/proposals/{proposal_id}/resubmit",
            {"proposed_aav_cents": proposed_aav_cents}, headers)

    def accept_proposal(self, agency_id, client_id, contract_id, proposal_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/proposals/{proposal_id}/accept",
            {}, headers)

    def reject_proposal(self, agency_id, client_id, contract_id, proposal_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/proposals/{proposal_id}/reject",
            {}, headers)

    def withdraw_proposal(self, agency_id, client_id, contract_id, proposal_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/proposals/{proposal_id}/withdraw",
            {}, headers)

    # ------------------------------------------------------------------
    # Endorsement deals
    # ------------------------------------------------------------------
    def create_endorsement(self, agency_id, client_id, payload, headers):
        return self._request(
            "POST", f"/agencies/{agency_id}/clients/{client_id}/endorsements",
            payload, headers)

    def list_endorsements(self, agency_id, client_id, headers, params=None):
        return self._request(
            "GET", f"/agencies/{agency_id}/clients/{client_id}/endorsements",
            headers=headers, params=params)

    def get_endorsement(self, agency_id, client_id, deal_id, headers):
        return self._request(
            "GET",
            f"/agencies/{agency_id}/clients/{client_id}/endorsements/{deal_id}",
            headers=headers)

    def approve_endorsement(self, agency_id, client_id, deal_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/endorsements/{deal_id}/approve",
            {}, headers)

    def terminate_endorsement(self, agency_id, client_id, deal_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/endorsements/{deal_id}/terminate",
            {}, headers)

    # ------------------------------------------------------------------
    # Tender options
    # ------------------------------------------------------------------
    def create_tender_option(self, agency_id, client_id, contract_id, payload, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/tender_options",
            payload, headers)

    def list_tender_options(self, agency_id, client_id, contract_id, headers,
                            params=None):
        return self._request(
            "GET",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/tender_options",
            headers=headers, params=params)

    def get_tender_option(self, agency_id, client_id, contract_id, tender_id, headers):
        return self._request(
            "GET",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/tender_options/{tender_id}",
            headers=headers)

    def exercise_tender_option(self, agency_id, client_id, contract_id, tender_id,
                               headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/tender_options/{tender_id}/exercise",
            {}, headers)

    # ------------------------------------------------------------------
    # Grievances
    # ------------------------------------------------------------------
    def create_grievance(self, agency_id, client_id, contract_id, payload, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/grievances",
            payload, headers)

    def list_grievances(self, agency_id, client_id, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/grievances",
            headers=headers, params=params)

    def get_grievance(self, agency_id, client_id, contract_id, grievance_id, headers):
        return self._request(
            "GET",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/grievances/{grievance_id}",
            headers=headers)

    def start_review_grievance(self, agency_id, client_id, contract_id,
                               grievance_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/grievances/{grievance_id}/start_review",
            {}, headers)

    def return_for_cure_grievance(self, agency_id, client_id, contract_id,
                                  grievance_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/grievances/{grievance_id}/return_for_cure",
            {}, headers)

    def escalate_grievance(self, agency_id, client_id, contract_id,
                           grievance_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/grievances/{grievance_id}/escalate",
            {}, headers)

    def resolve_grievance(self, agency_id, client_id, contract_id, grievance_id,
                          resolution_outcome, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/grievances/{grievance_id}/resolve",
            {"resolution_outcome": resolution_outcome}, headers)

    def withdraw_grievance(self, agency_id, client_id, contract_id, grievance_id,
                           headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/clients/{client_id}/contracts/{contract_id}"
            f"/grievances/{grievance_id}/withdraw",
            {}, headers)

    # ------------------------------------------------------------------
    # Fee ledger (agency-scoped)
    # ------------------------------------------------------------------
    def list_fee_ledger_entries(self, agency_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/fee_ledger_entries",
                             headers=headers, params=params)

    def get_fee_ledger_entry(self, agency_id, entry_id, headers):
        return self._request(
            "GET", f"/agencies/{agency_id}/fee_ledger_entries/{entry_id}",
            headers=headers)

    def mark_fee_paid(self, agency_id, entry_id, headers):
        return self._request(
            "POST",
            f"/agencies/{agency_id}/fee_ledger_entries/{entry_id}/mark_paid",
            {}, headers)

    # ------------------------------------------------------------------
    # Flat cross-agency read views (LeagueOfficer oversight)
    # ------------------------------------------------------------------
    def flat_list_agents(self, headers, params=None):
        return self._request("GET", "/agents", headers=headers, params=params)

    def flat_get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def flat_list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def flat_get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def flat_list_cap_seasons(self, headers, params=None):
        return self._request("GET", "/cap_seasons", headers=headers, params=params)

    def flat_get_cap_season(self, cap_season_id, headers):
        return self._request("GET", f"/cap_seasons/{cap_season_id}", headers=headers)

    def flat_list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def flat_get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def flat_list_proposals(self, headers, params=None):
        return self._request("GET", "/proposals", headers=headers, params=params)

    def flat_get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/proposals/{proposal_id}", headers=headers)

    def flat_list_endorsements(self, headers, params=None):
        return self._request("GET", "/endorsements", headers=headers, params=params)

    def flat_get_endorsement(self, deal_id, headers):
        return self._request("GET", f"/endorsements/{deal_id}", headers=headers)

    def flat_list_tender_options(self, headers, params=None):
        return self._request("GET", "/tender_options", headers=headers, params=params)

    def flat_get_tender_option(self, tender_id, headers):
        return self._request("GET", f"/tender_options/{tender_id}", headers=headers)

    def flat_list_grievances(self, headers, params=None):
        return self._request("GET", "/grievances", headers=headers, params=params)

    def flat_get_grievance(self, grievance_id, headers):
        return self._request("GET", f"/grievances/{grievance_id}", headers=headers)

    def flat_list_fee_ledger_entries(self, headers, params=None):
        return self._request("GET", "/fee_ledger_entries", headers=headers,
                             params=params)

    def flat_get_fee_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/fee_ledger_entries/{entry_id}", headers=headers)


api_client = ApiClient()
