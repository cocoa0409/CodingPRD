"""API client: one method per endpoint defined in the PRD §4 endpoint table."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The runner's per-test-server isolation SIGKILLs and restarts the
        # server before every test, on the same port. A keep-alive connection
        # pool intermittently reuses a connection whose server end is dead
        # (ConnectionResetError / RemoteDisconnected / IncompleteRead).
        # Sending Connection: close makes every request open a fresh TCP
        # connection, eliminating the stale-pooled-connection race.
        self.session.headers.update({"Connection": "close"})

    # --- logical clock ---
    def set_clock(self, to_iso8601: str, headers: dict):
        return self._request(
            "POST", "/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601}, headers=headers,
        )

    # --- Branch ---
    def create_branch(self, payload: dict, headers: dict):
        return self._request("POST", "/branches", payload, headers)

    def list_branches(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/branches", headers=headers, params=params)

    def get_branch(self, branch_id: str, headers: dict):
        return self._request("GET", f"/branches/{branch_id}", headers=headers)

    def deactivate_branch(self, branch_id: str, headers: dict):
        return self._request("POST", f"/branches/{branch_id}/deactivate", headers=headers)

    def reactivate_branch(self, branch_id: str, headers: dict):
        return self._request("POST", f"/branches/{branch_id}/reactivate", headers=headers)

    # --- Customer ---
    def create_customer(self, payload: dict, headers: dict):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id: str, headers: dict):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def patch_customer(self, customer_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"/customers/{customer_id}", payload, headers)

    def suspend_customer(self, customer_id: str, headers: dict):
        return self._request("POST", f"/customers/{customer_id}/suspend", headers=headers)

    def reactivate_customer(self, customer_id: str, headers: dict):
        return self._request("POST", f"/customers/{customer_id}/reactivate", headers=headers)

    def close_customer(self, customer_id: str, headers: dict):
        return self._request("POST", f"/customers/{customer_id}/close", headers=headers)

    # --- CashTransaction ---
    def create_cash_transaction(self, payload: dict, headers: dict):
        return self._request("POST", "/cash-transactions", payload, headers)

    def list_cash_transactions(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/cash-transactions", headers=headers, params=params)

    def get_cash_transaction(self, txn_id: str, headers: dict):
        return self._request("GET", f"/cash-transactions/{txn_id}", headers=headers)

    def void_cash_transaction(self, txn_id: str, payload: Optional[dict], headers: dict):
        return self._request("POST", f"/cash-transactions/{txn_id}/void", payload, headers)

    # --- MonetaryInstrumentSale ---
    def create_instrument_sale(self, payload: dict, headers: dict):
        return self._request("POST", "/monetary-instrument-sales", payload, headers)

    def list_instrument_sales(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/monetary-instrument-sales", headers=headers, params=params)

    def get_instrument_sale(self, sale_id: str, headers: dict):
        return self._request("GET", f"/monetary-instrument-sales/{sale_id}", headers=headers)

    def void_instrument_sale(self, sale_id: str, payload: Optional[dict], headers: dict):
        return self._request("POST", f"/monetary-instrument-sales/{sale_id}/void", payload, headers)

    # --- DailyCashAggregation ---
    def list_daily_aggregations(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/daily-aggregations", headers=headers, params=params)

    def get_daily_aggregation(self, agg_id: str, headers: dict):
        return self._request("GET", f"/daily-aggregations/{agg_id}", headers=headers)

    # --- CTR ---
    def list_ctrs(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/ctrs", headers=headers, params=params)

    def get_ctr(self, ctr_id: str, headers: dict):
        return self._request("GET", f"/ctrs/{ctr_id}", headers=headers)

    def validate_ctr(self, ctr_id: str, headers: dict):
        return self._request("POST", f"/ctrs/{ctr_id}/validate", headers=headers)

    def return_ctr_to_draft(self, ctr_id: str, headers: dict):
        return self._request("POST", f"/ctrs/{ctr_id}/return-to-draft", headers=headers)

    def file_ctr(self, ctr_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/ctrs/{ctr_id}/file", payload, headers)

    def amend_ctr(self, ctr_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/ctrs/{ctr_id}/amendments", payload, headers)

    def acknowledge_ctr(self, ctr_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/ctrs/{ctr_id}/acknowledge", payload, headers)

    # --- ExemptionDesignation ---
    def create_exemption_designation(self, customer_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/customers/{customer_id}/exemption-designations", payload, headers,
        )

    def list_exemption_designations(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/exemption-designations", headers=headers, params=params)

    def get_exemption_designation(self, designation_id: str, headers: dict):
        return self._request("GET", f"/exemption-designations/{designation_id}", headers=headers)

    def approve_exemption(self, designation_id: str, headers: dict):
        return self._request("POST", f"/exemption-designations/{designation_id}/approve", headers=headers)

    def deny_exemption(self, designation_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/exemption-designations/{designation_id}/deny", payload, headers)

    def complete_review_exemption(self, designation_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/exemption-designations/{designation_id}/complete-review", payload, headers,
        )

    def revoke_exemption(self, designation_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/exemption-designations/{designation_id}/revoke", payload, headers)

    # --- StructuringAlert ---
    def create_structuring_alert(self, payload: dict, headers: dict):
        return self._request("POST", "/structuring-alerts", payload, headers)

    def list_structuring_alerts(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/structuring-alerts", headers=headers, params=params)

    def get_structuring_alert(self, alert_id: str, headers: dict):
        return self._request("GET", f"/structuring-alerts/{alert_id}", headers=headers)

    def begin_review_alert(self, alert_id: str, headers: dict):
        return self._request("POST", f"/structuring-alerts/{alert_id}/begin-review", headers=headers)

    def dismiss_alert(self, alert_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/structuring-alerts/{alert_id}/dismiss", payload, headers)

    def refer_alert(self, alert_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/structuring-alerts/{alert_id}/refer", payload, headers)

    def reopen_alert(self, alert_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/structuring-alerts/{alert_id}/reopen", payload, headers)

    # --- ExaminationCase / ExaminationFinding ---
    def create_examination_case(self, payload: dict, headers: dict):
        return self._request("POST", "/examination-cases", payload, headers)

    def list_examination_cases(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/examination-cases", headers=headers, params=params)

    def get_examination_case(self, case_id: str, headers: dict):
        return self._request("GET", f"/examination-cases/{case_id}", headers=headers)

    def begin_fieldwork(self, case_id: str, headers: dict):
        return self._request("POST", f"/examination-cases/{case_id}/begin-fieldwork", headers=headers)

    def issue_findings(self, case_id: str, headers: dict):
        return self._request("POST", f"/examination-cases/{case_id}/issue-findings", headers=headers)

    def reopen_fieldwork(self, case_id: str, headers: dict):
        return self._request("POST", f"/examination-cases/{case_id}/reopen-fieldwork", headers=headers)

    def close_examination_case(self, case_id: str, headers: dict):
        return self._request("POST", f"/examination-cases/{case_id}/close", headers=headers)

    def create_finding(self, case_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/examination-cases/{case_id}/findings", payload, headers)

    def list_examination_findings(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/examination-findings", headers=headers, params=params)

    def get_examination_finding(self, finding_id: str, headers: dict):
        return self._request("GET", f"/examination-findings/{finding_id}", headers=headers)

    def remediate_finding(self, finding_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/examination-findings/{finding_id}/remediate", payload, headers)

    def verify_finding(self, finding_id: str, headers: dict):
        return self._request("POST", f"/examination-findings/{finding_id}/verify", headers=headers)

    def reject_remediation(self, finding_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/examination-findings/{finding_id}/reject-remediation", payload, headers,
        )

    # --- Audit trail ---
    def list_audit_events(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/audit-events", headers=headers, params=params)

    def verify_audit_chain(self, headers: dict):
        return self._request("GET", "/audit-events/verify-chain", headers=headers)


api_client = ApiClient()
