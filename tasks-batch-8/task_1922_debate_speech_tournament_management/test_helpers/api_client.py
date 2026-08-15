"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Tournaments
    # ------------------------------------------------------------------
    def create_tournament(self, payload, headers):
        return self._request("POST", "/tournaments", payload, headers)

    def list_tournaments(self, headers, params=None):
        return self._request("GET", "/tournaments", headers=headers, params=params)

    def get_tournament(self, tournament_id, headers):
        return self._request("GET", f"/tournaments/{tournament_id}", headers=headers)

    def open_registration(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/open-registration",
                             {}, headers)

    def lock_registration(self, tournament_id, expected_tournament_version, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/lock-registration",
                             {"expected_tournament_version": expected_tournament_version},
                             headers)

    def start_prelims(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/start-prelims",
                             {}, headers)

    def start_elims(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/start-elims",
                             {}, headers)

    def complete_tournament(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/complete",
                             {}, headers)

    def publish_results(self, tournament_id, headers):
        return self._request("POST", f"/tournaments/{tournament_id}/publish-results",
                             {}, headers)

    def certify_qualifications(self, tournament_id, headers):
        return self._request("POST",
                             f"/tournaments/{tournament_id}/certify-qualifications",
                             {}, headers)

    # ------------------------------------------------------------------
    # Schools
    # ------------------------------------------------------------------
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", "/schools", headers=headers, params=params)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def confirm_school(self, school_id, headers):
        return self._request("POST", f"/schools/{school_id}/confirm", {}, headers)

    def unconfirm_school(self, school_id, headers):
        return self._request("POST", f"/schools/{school_id}/unconfirm", {}, headers)

    # ------------------------------------------------------------------
    # Event divisions
    # ------------------------------------------------------------------
    def create_division(self, payload, headers):
        return self._request("POST", "/divisions", payload, headers)

    def list_divisions(self, headers, params=None):
        return self._request("GET", "/divisions", headers=headers, params=params)

    def get_division(self, division_id, headers):
        return self._request("GET", f"/divisions/{division_id}", headers=headers)

    def determine_breaks(self, division_id, headers):
        return self._request("POST", f"/divisions/{division_id}/determine-breaks",
                             {}, headers)

    def get_standings(self, division_id, headers, params=None):
        return self._request("GET", f"/divisions/{division_id}/standings",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Entries
    # ------------------------------------------------------------------
    def create_entry(self, payload, headers):
        return self._request("POST", "/entries", payload, headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/entries", headers=headers, params=params)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/entries/{entry_id}", headers=headers)

    def confirm_entry(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/confirm", {}, headers)

    def withdraw_entry(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Judges and judge conflicts
    # ------------------------------------------------------------------
    def create_judge(self, payload, headers):
        return self._request("POST", "/judges", payload, headers)

    def list_judges(self, headers, params=None):
        return self._request("GET", "/judges", headers=headers, params=params)

    def get_judge(self, judge_id, headers):
        return self._request("GET", f"/judges/{judge_id}", headers=headers)

    def commit_judge(self, judge_id, commitment_rounds, headers):
        return self._request("POST", f"/judges/{judge_id}/commit",
                             {"commitment_rounds": commitment_rounds}, headers)

    def withdraw_judge(self, judge_id, headers):
        return self._request("POST", f"/judges/{judge_id}/withdraw", {}, headers)

    def create_judge_conflict(self, payload, headers):
        return self._request("POST", "/judge-conflicts", payload, headers)

    def list_judge_conflicts(self, headers, params=None):
        return self._request("GET", "/judge-conflicts", headers=headers, params=params)

    def get_judge_conflict(self, conflict_id, headers):
        return self._request("GET", f"/judge-conflicts/{conflict_id}", headers=headers)

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    # ------------------------------------------------------------------
    # Rounds
    # ------------------------------------------------------------------
    def create_round(self, payload, headers):
        return self._request("POST", "/rounds", payload, headers)

    def list_rounds(self, headers, params=None):
        return self._request("GET", "/rounds", headers=headers, params=params)

    def get_round(self, round_id, headers):
        return self._request("GET", f"/rounds/{round_id}", headers=headers)

    def generate_pairings(self, round_id, expected_round_version, headers):
        return self._request("POST", f"/rounds/{round_id}/generate-pairings",
                             {"expected_round_version": expected_round_version},
                             headers)

    def open_ballots(self, round_id, headers):
        return self._request("POST", f"/rounds/{round_id}/open-ballots", {}, headers)

    def tabulate_round(self, round_id, headers):
        return self._request("POST", f"/rounds/{round_id}/tabulate", {}, headers)

    # ------------------------------------------------------------------
    # Pairings and pairing entries
    # ------------------------------------------------------------------
    def list_pairings(self, headers, params=None):
        return self._request("GET", "/pairings", headers=headers, params=params)

    def get_pairing(self, pairing_id, headers):
        return self._request("GET", f"/pairings/{pairing_id}", headers=headers)

    def assign_room(self, pairing_id, room_id, headers):
        return self._request("POST", f"/pairings/{pairing_id}/assign-room",
                             {"room_id": room_id}, headers)

    def assign_judge(self, pairing_id, judge_id, headers):
        return self._request("POST", f"/pairings/{pairing_id}/assign-judge",
                             {"judge_id": judge_id}, headers)

    def unassign_judge(self, pairing_id, headers):
        return self._request("POST", f"/pairings/{pairing_id}/unassign-judge",
                             {}, headers)

    def list_pairing_entries(self, headers, params=None):
        return self._request("GET", "/pairing-entries", headers=headers, params=params)

    def get_pairing_entry(self, pairing_entry_id, headers):
        return self._request("GET", f"/pairing-entries/{pairing_entry_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Ballots
    # ------------------------------------------------------------------
    def create_ballot(self, payload, headers):
        return self._request("POST", "/ballots", payload, headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", "/ballots", headers=headers, params=params)

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"/ballots/{ballot_id}", headers=headers)

    def submit_ballot(self, ballot_id, headers):
        return self._request("POST", f"/ballots/{ballot_id}/submit", {}, headers)

    def recall_ballot(self, ballot_id, headers):
        return self._request("POST", f"/ballots/{ballot_id}/recall", {}, headers)

    def verify_ballot(self, ballot_id, headers):
        return self._request("POST", f"/ballots/{ballot_id}/verify", {}, headers)

    def void_ballot(self, ballot_id, headers):
        return self._request("POST", f"/ballots/{ballot_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Hired-judge contracts
    # ------------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/hired-judge-contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/hired-judge-contracts",
                             headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/hired-judge-contracts/{contract_id}",
                             headers=headers)

    def fill_contract(self, contract_id, judge_name, headers):
        return self._request("POST", f"/hired-judge-contracts/{contract_id}/fill",
                             {"judge_name": judge_name}, headers)

    def accept_contract(self, contract_id, headers):
        return self._request("POST", f"/hired-judge-contracts/{contract_id}/accept",
                             {}, headers)

    def dispute_contract(self, contract_id, headers):
        return self._request("POST", f"/hired-judge-contracts/{contract_id}/dispute",
                             {}, headers)

    def resolve_dispute(self, contract_id, headers):
        return self._request("POST",
                             f"/hired-judge-contracts/{contract_id}/resolve-dispute",
                             {}, headers)

    def pay_contract(self, contract_id, headers):
        return self._request("POST", f"/hired-judge-contracts/{contract_id}/pay",
                             {}, headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/hired-judge-contracts/{contract_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Logistics orders
    # ------------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/logistics-orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/logistics-orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/logistics-orders/{order_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/logistics-orders/{order_id}/submit",
                             {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/logistics-orders/{order_id}/fulfill",
                             {}, headers)


api_client = ApiClient()
