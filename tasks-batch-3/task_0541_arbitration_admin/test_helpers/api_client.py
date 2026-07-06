"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/cases", headers=headers, params=params)

    def transition_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/transition", payload, headers)

    def appoint_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/appoint", payload, headers)

    # ---- Party ----
    def create_party(self, payload, headers):
        return self._request("POST", "/parties", payload, headers)

    def list_case_parties(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/parties", headers=headers)

    # ---- Neutral ----
    def create_neutral(self, payload, headers):
        return self._request("POST", "/neutrals", payload, headers)

    def get_neutral(self, neutral_id, headers):
        return self._request("GET", f"/neutrals/{neutral_id}", headers=headers)

    def list_neutrals(self, headers, params=None):
        return self._request("GET", "/neutrals", headers=headers, params=params)

    def transition_neutral(self, neutral_id, payload, headers):
        return self._request("POST", f"/neutrals/{neutral_id}/transition", payload, headers)

    # ---- Candidate ----
    def add_candidate(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/candidates", payload, headers)

    def list_case_candidates(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/candidates", headers=headers)

    def list_neutral_candidates(self, neutral_id, headers):
        return self._request("GET", f"/neutrals/{neutral_id}/candidates", headers=headers)

    def disclose_candidate(self, candidate_id, payload, headers):
        return self._request("POST", f"/candidates/{candidate_id}/disclose", payload, headers)

    def transition_candidate(self, candidate_id, payload, headers):
        return self._request("POST", f"/candidates/{candidate_id}/transition", payload, headers)

    # ---- Ranking ----
    def create_ranking(self, payload, headers):
        return self._request("POST", "/rankings", payload, headers)

    def get_ranking(self, ranking_id, headers):
        return self._request("GET", f"/rankings/{ranking_id}", headers=headers)

    def list_rankings(self, headers, params=None):
        return self._request("GET", "/rankings", headers=headers, params=params)

    def withdraw_ranking(self, ranking_id, headers):
        return self._request("POST", f"/rankings/{ranking_id}/withdraw", headers=headers)

    # ---- Hearing ----
    def create_hearing(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/hearings", payload, headers)

    def list_case_hearings(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/hearings", headers=headers)

    def transition_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"/hearings/{hearing_id}/transition", payload, headers)

    # ---- Exchange ----
    def create_exchange(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/exchanges", payload, headers)

    def list_case_exchanges(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/exchanges", headers=headers)

    def submit_exchange(self, exchange_id, headers):
        return self._request("POST", f"/exchanges/{exchange_id}/submit", headers=headers)

    # ---- Deposit ----
    def create_deposit(self, payload, headers):
        return self._request("POST", "/deposits", payload, headers)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/deposits", headers=headers, params=params)

    def pay_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/pay", headers=headers)

    def refund_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/refund", headers=headers)

    # ---- FeeCharge ----
    def create_fee_charge(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/fee-charges", payload, headers)

    def get_fee_charge(self, fee_charge_id, headers):
        return self._request("GET", f"/fee-charges/{fee_charge_id}", headers=headers)

    def list_fee_charges(self, headers, params=None):
        return self._request("GET", "/fee-charges", headers=headers, params=params)

    def reverse_fee_charge(self, fee_charge_id, headers):
        return self._request("POST", f"/fee-charges/{fee_charge_id}/reverse", headers=headers)

    # ---- Award ----
    def create_award(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/awards", payload, headers)

    def list_case_awards(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/awards", headers=headers)

    def transition_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/transition", payload, headers)

    # ---- Appeal ----
    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def transition_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/transition", payload, headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
