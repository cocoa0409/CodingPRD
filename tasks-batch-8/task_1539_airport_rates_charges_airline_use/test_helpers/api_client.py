"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/airport/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # FiscalYear
    # ------------------------------------------------------------------
    def create_fiscal_year(self, payload, headers):
        return self._request("POST", "/airport/fiscal_years", payload, headers)

    def list_fiscal_years(self, headers, params=None):
        return self._request("GET", "/airport/fiscal_years", headers=headers,
                             params=params)

    def get_fiscal_year(self, fy_id, headers):
        return self._request("GET", f"/airport/fiscal_years/{fy_id}",
                             headers=headers)

    def open_fiscal_year(self, fy_id, headers):
        return self._request("POST", f"/airport/fiscal_years/{fy_id}/open",
                             {}, headers)

    # ------------------------------------------------------------------
    # Airline
    # ------------------------------------------------------------------
    def create_airline(self, payload, headers):
        return self._request("POST", "/airport/airlines", payload, headers)

    def list_airlines(self, headers, params=None):
        return self._request("GET", "/airport/airlines", headers=headers,
                             params=params)

    def get_airline(self, airline_id, headers):
        return self._request("GET", f"/airport/airlines/{airline_id}",
                             headers=headers)

    def list_airline_agreements(self, airline_id, headers, params=None):
        return self._request("GET", f"/airport/airlines/{airline_id}/agreements",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # AirlineAgreement
    # ------------------------------------------------------------------
    def create_airline_agreement(self, payload, headers):
        return self._request("POST", "/airport/airline_agreements", payload,
                             headers)

    def get_airline_agreement(self, agreement_id, headers):
        return self._request("GET", f"/airport/airline_agreements/{agreement_id}",
                             headers=headers)

    def countersign_agreement(self, agreement_id, headers):
        return self._request("POST",
                             f"/airport/airline_agreements/{agreement_id}/countersign",
                             {}, headers)

    def decline_renewal_agreement(self, agreement_id, headers):
        return self._request("POST",
                             f"/airport/airline_agreements/{agreement_id}/decline-renewal",
                             {}, headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST",
                             f"/airport/airline_agreements/{agreement_id}/suspend",
                             {}, headers)

    def reinstate_agreement(self, agreement_id, headers):
        return self._request("POST",
                             f"/airport/airline_agreements/{agreement_id}/reinstate",
                             {}, headers)

    def list_agreement_successors(self, agreement_id, headers, params=None):
        return self._request("GET",
                             f"/airport/airline_agreements/{agreement_id}/successors",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # RatesSetting
    # ------------------------------------------------------------------
    def create_rates_setting(self, fy_id, payload, headers):
        return self._request("POST",
                             f"/airport/fiscal_years/{fy_id}/rates_settings",
                             payload, headers)

    def get_rates_setting(self, rs_id, headers):
        return self._request("GET", f"/airport/rates_settings/{rs_id}",
                             headers=headers)

    def list_rates_settings(self, fy_id, headers, params=None):
        return self._request("GET",
                             f"/airport/fiscal_years/{fy_id}/rates_settings",
                             headers=headers, params=params)

    def publish_rates_setting(self, rs_id, headers):
        return self._request("POST", f"/airport/rates_settings/{rs_id}/publish",
                             {}, headers)

    def adopt_rates_setting(self, rs_id, headers):
        return self._request("POST", f"/airport/rates_settings/{rs_id}/adopt",
                             {}, headers)

    # ------------------------------------------------------------------
    # ConsultationComment
    # ------------------------------------------------------------------
    def create_comment(self, rs_id, payload, headers):
        return self._request("POST", f"/airport/rates_settings/{rs_id}/comments",
                             payload, headers)

    def list_comments(self, rs_id, headers, params=None):
        return self._request("GET", f"/airport/rates_settings/{rs_id}/comments",
                             headers=headers, params=params)

    def get_comment(self, comment_id, headers):
        return self._request("GET",
                             f"/airport/consultation_comments/{comment_id}",
                             headers=headers)

    def list_airline_comments(self, airline_id, headers, params=None):
        return self._request("GET", f"/airport/airlines/{airline_id}/comments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # ActivityRecord
    # ------------------------------------------------------------------
    def create_activity_record(self, fy_id, payload, headers):
        return self._request("POST",
                             f"/airport/fiscal_years/{fy_id}/activity_records",
                             payload, headers)

    def list_activity_records(self, fy_id, headers, params=None):
        return self._request("GET",
                             f"/airport/fiscal_years/{fy_id}/activity_records",
                             headers=headers, params=params)

    def get_activity_record(self, record_id, headers):
        return self._request("GET", f"/airport/activity_records/{record_id}",
                             headers=headers)

    def list_airline_activity_records(self, airline_id, headers, params=None):
        return self._request("GET",
                             f"/airport/airlines/{airline_id}/activity_records",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # CapitalProject + MIIVote
    # ------------------------------------------------------------------
    def create_capital_project(self, fy_id, payload, headers):
        return self._request("POST",
                             f"/airport/fiscal_years/{fy_id}/capital_projects",
                             payload, headers)

    def get_capital_project(self, project_id, headers):
        return self._request("GET", f"/airport/capital_projects/{project_id}",
                             headers=headers)

    def list_capital_projects(self, fy_id, headers, params=None):
        return self._request("GET",
                             f"/airport/fiscal_years/{fy_id}/capital_projects",
                             headers=headers, params=params)

    def open_voting(self, project_id, headers):
        return self._request("POST",
                             f"/airport/capital_projects/{project_id}/open-voting",
                             {}, headers)

    def close_voting(self, project_id, headers):
        return self._request("POST",
                             f"/airport/capital_projects/{project_id}/close-voting",
                             {}, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST",
                             f"/airport/capital_projects/{project_id}/cancel",
                             {}, headers)

    def cast_mii_vote(self, project_id, payload, headers):
        return self._request("POST",
                             f"/airport/capital_projects/{project_id}/mii_votes",
                             payload, headers)

    def list_mii_votes(self, project_id, headers, params=None):
        return self._request("GET",
                             f"/airport/capital_projects/{project_id}/mii_votes",
                             headers=headers, params=params)

    def get_mii_vote(self, vote_id, headers):
        return self._request("GET", f"/airport/mii_votes/{vote_id}",
                             headers=headers)

    def list_airline_mii_votes(self, airline_id, headers, params=None):
        return self._request("GET", f"/airport/airlines/{airline_id}/mii_votes",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # AnnualSettlement + AirlineSettlementLine
    # ------------------------------------------------------------------
    def compute_settlement(self, fy_id, headers):
        return self._request("POST",
                             f"/airport/fiscal_years/{fy_id}/settlement/compute",
                             {}, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/airport/settlements/{settlement_id}",
                             headers=headers)

    def get_fiscal_year_settlement(self, fy_id, headers):
        return self._request("GET", f"/airport/fiscal_years/{fy_id}/settlement",
                             headers=headers)

    def publish_review(self, settlement_id, headers):
        return self._request("POST",
                             f"/airport/settlements/{settlement_id}/publish-review",
                             {}, headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST",
                             f"/airport/settlements/{settlement_id}/dispute",
                             payload, headers)

    def resolve_settlement(self, settlement_id, payload, headers):
        return self._request("POST",
                             f"/airport/settlements/{settlement_id}/resolve",
                             payload, headers)

    def recompute_settlement(self, settlement_id, payload, headers):
        return self._request("POST",
                             f"/airport/settlements/{settlement_id}/recompute",
                             payload, headers)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST",
                             f"/airport/settlements/{settlement_id}/finalize",
                             {}, headers)

    def list_settlement_lines(self, settlement_id, headers, params=None):
        return self._request("GET", f"/airport/settlements/{settlement_id}/lines",
                             headers=headers, params=params)

    def get_settlement_line(self, line_id, headers):
        return self._request("GET", f"/airport/settlement_lines/{line_id}",
                             headers=headers)

    def record_payment(self, line_id, payload, headers):
        return self._request("POST",
                             f"/airport/settlement_lines/{line_id}/record-payment",
                             payload, headers)

    def write_off_line(self, line_id, headers):
        return self._request("POST",
                             f"/airport/settlement_lines/{line_id}/write-off",
                             {}, headers)

    def list_airline_settlement_lines(self, airline_id, headers, params=None):
        return self._request("GET",
                             f"/airport/airlines/{airline_id}/settlement_lines",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # PFCApplication
    # ------------------------------------------------------------------
    def create_pfc_application(self, fy_id, payload, headers):
        return self._request("POST",
                             f"/airport/fiscal_years/{fy_id}/pfc_applications",
                             payload, headers)

    def list_pfc_applications(self, fy_id, headers, params=None):
        return self._request("GET",
                             f"/airport/fiscal_years/{fy_id}/pfc_applications",
                             headers=headers, params=params)

    def get_pfc_application(self, pfc_id, headers):
        return self._request("GET", f"/airport/pfc_applications/{pfc_id}",
                             headers=headers)

    def list_airline_pfc_applications(self, airline_id, headers, params=None):
        return self._request("GET",
                             f"/airport/airlines/{airline_id}/pfc_applications",
                             headers=headers, params=params)

    def decide_pfc_application(self, pfc_id, payload, headers):
        return self._request("POST",
                             f"/airport/pfc_applications/{pfc_id}/decide",
                             payload, headers)

    # ------------------------------------------------------------------
    # Reverse-reachability GETs
    # ------------------------------------------------------------------
    def list_fiscal_year_agreements(self, fy_id, headers, params=None):
        return self._request("GET",
                             f"/airport/fiscal_years/{fy_id}/agreements",
                             headers=headers, params=params)


api_client = ApiClient()
