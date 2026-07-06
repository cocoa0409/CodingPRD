"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/copyright/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Work ----
    def create_work(self, payload, headers):
        return self._request("POST", "/copyright/works", payload, headers)

    def get_work(self, work_id, headers):
        return self._request("GET", f"/copyright/works/{work_id}", headers=headers)

    def list_works(self, headers, params=None):
        return self._request("GET", "/copyright/works", headers=headers, params=params)

    # ---- Application ----
    def create_application(self, payload, headers):
        return self._request("POST", "/copyright/applications", payload, headers)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/copyright/applications/{app_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/copyright/applications", headers=headers, params=params)

    def submit_application(self, app_id, headers):
        return self._request("POST", f"/copyright/applications/{app_id}/submit", {}, headers)

    def pay_fee(self, app_id, payload, headers):
        return self._request("POST", f"/copyright/applications/{app_id}/pay-fee", payload, headers)

    def begin_examination(self, app_id, headers):
        return self._request("POST", f"/copyright/applications/{app_id}/begin-examination", {}, headers)

    def issue_correspondence(self, app_id, payload, headers):
        return self._request("POST", f"/copyright/applications/{app_id}/issue-correspondence", payload, headers)

    def respond_correspondence(self, app_id, payload, headers):
        return self._request("POST", f"/copyright/applications/{app_id}/respond-correspondence", payload, headers)

    def register_application(self, app_id, headers):
        return self._request("POST", f"/copyright/applications/{app_id}/register", {}, headers)

    def refuse_application(self, app_id, headers, payload=None):
        return self._request("POST", f"/copyright/applications/{app_id}/refuse", payload or {}, headers)

    def withdraw_application(self, app_id, headers):
        return self._request("POST", f"/copyright/applications/{app_id}/withdraw", {}, headers)

    # ---- Deposit ----
    def create_deposit(self, payload, headers):
        return self._request("POST", "/copyright/deposits", payload, headers)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/copyright/deposits/{deposit_id}", headers=headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/copyright/deposits", headers=headers, params=params)

    def accept_deposit(self, deposit_id, headers):
        return self._request("POST", f"/copyright/deposits/{deposit_id}/accept", {}, headers)

    def reject_deposit(self, deposit_id, headers):
        return self._request("POST", f"/copyright/deposits/{deposit_id}/reject", {}, headers)

    # ---- Certificate ----
    def get_certificate(self, cert_id, headers):
        return self._request("GET", f"/copyright/certificates/{cert_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/copyright/certificates", headers=headers, params=params)

    def renew_certificate(self, cert_id, headers):
        return self._request("POST", f"/copyright/certificates/{cert_id}/renew", {}, headers)

    # ---- Recordation ----
    def create_recordation(self, payload, headers):
        return self._request("POST", "/copyright/recordations", payload, headers)

    def get_recordation(self, rec_id, headers):
        return self._request("GET", f"/copyright/recordations/{rec_id}", headers=headers)

    def list_recordations(self, headers, params=None):
        return self._request("GET", "/copyright/recordations", headers=headers, params=params)

    # ---- License ----
    def create_license(self, payload, headers):
        return self._request("POST", "/copyright/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/copyright/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/copyright/licenses", headers=headers, params=params)

    # ---- RoyaltyStatement ----
    def create_royalty_statement(self, payload, headers):
        return self._request("POST", "/copyright/royalty-statements", payload, headers)

    def get_royalty_statement(self, rs_id, headers):
        return self._request("GET", f"/copyright/royalty-statements/{rs_id}", headers=headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request("GET", "/copyright/royalty-statements", headers=headers, params=params)

    def post_royalty_statement(self, rs_id, headers):
        return self._request("POST", f"/copyright/royalty-statements/{rs_id}/post", {}, headers)

    def distribute_royalty_statement(self, rs_id, headers):
        return self._request("POST", f"/copyright/royalty-statements/{rs_id}/distribute", {}, headers)

    def reverse_royalty_statement(self, rs_id, headers):
        return self._request("POST", f"/copyright/royalty-statements/{rs_id}/reverse", {}, headers)

    # ---- DmcaTakedown ----
    def create_dmca_takedown(self, payload, headers):
        return self._request("POST", "/copyright/dmca-takedowns", payload, headers)

    def get_dmca_takedown(self, td_id, headers):
        return self._request("GET", f"/copyright/dmca-takedowns/{td_id}", headers=headers)

    def list_dmca_takedowns(self, headers, params=None):
        return self._request("GET", "/copyright/dmca-takedowns", headers=headers, params=params)

    def process_dmca_takedown(self, td_id, headers):
        return self._request("POST", f"/copyright/dmca-takedowns/{td_id}/process", {}, headers)

    def restore_dmca_takedown(self, td_id, headers):
        return self._request("POST", f"/copyright/dmca-takedowns/{td_id}/restore", {}, headers)

    def withdraw_dmca_takedown(self, td_id, headers):
        return self._request("POST", f"/copyright/dmca-takedowns/{td_id}/withdraw", {}, headers)

    # ---- CounterNotice ----
    def create_counter_notice(self, payload, headers):
        return self._request("POST", "/copyright/counter-notices", payload, headers)

    def get_counter_notice(self, cn_id, headers):
        return self._request("GET", f"/copyright/counter-notices/{cn_id}", headers=headers)

    def list_counter_notices(self, headers, params=None):
        return self._request("GET", "/copyright/counter-notices", headers=headers, params=params)

    # ---- Termination ----
    def create_termination(self, payload, headers):
        return self._request("POST", "/copyright/terminations", payload, headers)

    def get_termination(self, term_id, headers):
        return self._request("GET", f"/copyright/terminations/{term_id}", headers=headers)

    def list_terminations(self, headers, params=None):
        return self._request("GET", "/copyright/terminations", headers=headers, params=params)

    def effectuate_termination(self, term_id, headers):
        return self._request("POST", f"/copyright/terminations/{term_id}/effectuate", {}, headers)


api_client = ApiClient()
