"""API client: one method per endpoint defined in the PRD.

GET methods pass filters/pagination via `params`; POST methods send a JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    # ---- Election ----
    def create_election(self, payload, headers):
        return self._request("POST", "/elections", payload, headers)

    def get_election(self, election_id, headers):
        return self._request("GET", f"/elections/{election_id}", headers=headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", "/elections", headers=headers, params=params)

    def transition_election(self, election_id, payload, headers):
        return self._request("POST", f"/elections/{election_id}/transition", payload, headers)

    # ---- Precinct ----
    def create_precinct(self, payload, headers):
        return self._request("POST", "/precincts", payload, headers)

    def get_precinct(self, precinct_id, headers):
        return self._request("GET", f"/precincts/{precinct_id}", headers=headers)

    def list_precincts(self, headers, params=None):
        return self._request("GET", "/precincts", headers=headers, params=params)

    def tally_precinct(self, precinct_id, payload, headers):
        return self._request("POST", f"/precincts/{precinct_id}/tally", payload, headers)

    # ---- VoterRegistration ----
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def approve_registration(self, registration_id, headers, payload=None):
        return self._request("POST", f"/registrations/{registration_id}/approve", payload or {}, headers)

    def transition_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/registrations/{registration_id}/transition", payload, headers)

    # ---- AbsenteeBallot ----
    def create_absentee_ballot(self, payload, headers):
        return self._request("POST", "/absentee-ballots", payload, headers)

    def get_absentee_ballot(self, ballot_id, headers):
        return self._request("GET", f"/absentee-ballots/{ballot_id}", headers=headers)

    def list_absentee_ballots(self, headers, params=None):
        return self._request("GET", "/absentee-ballots", headers=headers, params=params)

    def transition_absentee_ballot(self, ballot_id, payload, headers):
        return self._request("POST", f"/absentee-ballots/{ballot_id}/transition", payload, headers)

    def flag_cure(self, ballot_id, payload, headers):
        return self._request("POST", f"/absentee-ballots/{ballot_id}/flag-cure", payload, headers)

    # ---- CureCase ----
    def get_cure_case(self, cure_case_id, headers):
        return self._request("GET", f"/cure-cases/{cure_case_id}", headers=headers)

    def list_cure_cases(self, headers, params=None):
        return self._request("GET", "/cure-cases", headers=headers, params=params)

    def transition_cure_case(self, cure_case_id, payload, headers):
        return self._request("POST", f"/cure-cases/{cure_case_id}/transition", payload, headers)

    # ---- VotingMachine ----
    def create_voting_machine(self, payload, headers):
        return self._request("POST", "/voting-machines", payload, headers)

    def get_voting_machine(self, machine_id, headers):
        return self._request("GET", f"/voting-machines/{machine_id}", headers=headers)

    def list_voting_machines(self, headers, params=None):
        return self._request("GET", "/voting-machines", headers=headers, params=params)

    def transition_voting_machine(self, machine_id, payload, headers):
        return self._request("POST", f"/voting-machines/{machine_id}/transition", payload, headers)

    # ---- MachineFailure ----
    def create_machine_failure(self, payload, headers):
        return self._request("POST", "/machine-failures", payload, headers)

    def get_machine_failure(self, failure_id, headers):
        return self._request("GET", f"/machine-failures/{failure_id}", headers=headers)

    def list_machine_failures(self, headers, params=None):
        return self._request("GET", "/machine-failures", headers=headers, params=params)

    # ---- EarlyVoteCheckIn ----
    def create_early_vote_checkin(self, payload, headers):
        return self._request("POST", "/early-vote-checkins", payload, headers)

    def get_early_vote_checkin(self, checkin_id, headers):
        return self._request("GET", f"/early-vote-checkins/{checkin_id}", headers=headers)

    def list_early_vote_checkins(self, headers, params=None):
        return self._request("GET", "/early-vote-checkins", headers=headers, params=params)

    # ---- RecountCase ----
    def create_recount_case(self, payload, headers):
        return self._request("POST", "/recount-cases", payload, headers)

    def get_recount_case(self, recount_id, headers):
        return self._request("GET", f"/recount-cases/{recount_id}", headers=headers)

    def list_recount_cases(self, headers, params=None):
        return self._request("GET", "/recount-cases", headers=headers, params=params)

    def submit_recount_pass(self, recount_id, payload, headers):
        return self._request("POST", f"/recount-cases/{recount_id}/submit-pass", payload, headers)

    def transition_recount_case(self, recount_id, payload, headers):
        return self._request("POST", f"/recount-cases/{recount_id}/transition", payload, headers)


api_client = ApiClient()
