"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- host sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def patch_site(self, site_id, payload, headers):
        return self._request("PATCH", f"/sites/{site_id}", payload, headers)

    # --- pricing policies ---
    def create_pricing_policy(self, payload, headers):
        return self._request("POST", "/pricing-policies", payload, headers)

    def get_pricing_policy(self, policy_id, headers):
        return self._request("GET", f"/pricing-policies/{policy_id}", headers=headers)

    def list_pricing_policies(self, headers, params=None):
        return self._request("GET", "/pricing-policies", headers=headers, params=params)

    # --- drivers ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    def patch_driver(self, driver_id, payload, headers):
        return self._request("PATCH", f"/drivers/{driver_id}", payload, headers)

    # --- technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def patch_technician(self, technician_id, payload, headers):
        return self._request("PATCH", f"/technicians/{technician_id}", payload, headers)

    # --- cylinders ---
    def create_cylinder(self, payload, headers):
        return self._request("POST", "/cylinders", payload, headers)

    def get_cylinder(self, cylinder_id, headers):
        return self._request("GET", f"/cylinders/{cylinder_id}", headers=headers)

    def list_cylinders(self, headers, params=None):
        return self._request("GET", "/cylinders", headers=headers, params=params)

    def quarantine_cylinder(self, cylinder_id, payload, headers):
        return self._request("POST", f"/cylinders/{cylinder_id}/quarantine", payload, headers)

    def release_quarantine(self, cylinder_id, headers):
        return self._request("POST", f"/cylinders/{cylinder_id}/release-quarantine", {}, headers)

    # --- exchange orders ---
    def create_exchange_order(self, payload, headers):
        return self._request("POST", "/exchange-orders", payload, headers)

    def get_exchange_order(self, order_id, headers):
        return self._request("GET", f"/exchange-orders/{order_id}", headers=headers)

    def list_exchange_orders(self, headers, params=None):
        return self._request("GET", "/exchange-orders", headers=headers, params=params)

    def complete_exchange_order(self, order_id, payload, headers):
        return self._request("POST", f"/exchange-orders/{order_id}/complete", payload, headers)

    def void_exchange_order(self, order_id, headers):
        return self._request("POST", f"/exchange-orders/{order_id}/void", {}, headers)

    def refund_exchange_order(self, order_id, headers):
        return self._request("POST", f"/exchange-orders/{order_id}/refund", {}, headers)

    # --- refill tickets ---
    def create_refill_ticket(self, payload, headers):
        return self._request("POST", "/refill-tickets", payload, headers)

    def get_refill_ticket(self, ticket_id, headers):
        return self._request("GET", f"/refill-tickets/{ticket_id}", headers=headers)

    def list_refill_tickets(self, headers, params=None):
        return self._request("GET", "/refill-tickets", headers=headers, params=params)

    def weigh_refill_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/refill-tickets/{ticket_id}/weigh", payload, headers)

    def reweigh_refill_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/refill-tickets/{ticket_id}/reweigh", payload, headers)

    def fill_refill_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/refill-tickets/{ticket_id}/fill", payload, headers)

    def close_refill_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/refill-tickets/{ticket_id}/close", payload, headers)

    def void_refill_ticket(self, ticket_id, headers):
        return self._request("POST", f"/refill-tickets/{ticket_id}/void", {}, headers)

    # --- certification records ---
    def create_certification_record(self, payload, headers):
        return self._request("POST", "/certification-records", payload, headers)

    def get_certification_record(self, record_id, headers):
        return self._request("GET", f"/certification-records/{record_id}", headers=headers)

    def list_certification_records(self, headers, params=None):
        return self._request("GET", "/certification-records", headers=headers, params=params)

    def confirm_certification_record(self, record_id, payload, headers):
        return self._request("POST", f"/certification-records/{record_id}/confirm", payload, headers)

    def reject_certification_record(self, record_id, payload, headers):
        return self._request("POST", f"/certification-records/{record_id}/reject", payload, headers)

    # --- leak reports ---
    def create_leak_report(self, payload, headers):
        return self._request("POST", "/leak-reports", payload, headers)

    def get_leak_report(self, report_id, headers):
        return self._request("GET", f"/leak-reports/{report_id}", headers=headers)

    def list_leak_reports(self, headers, params=None):
        return self._request("GET", "/leak-reports", headers=headers, params=params)

    def confirm_leak_report(self, report_id, headers):
        return self._request("POST", f"/leak-reports/{report_id}/confirm", {}, headers)

    def resolve_leak_report(self, report_id, payload, headers):
        return self._request("POST", f"/leak-reports/{report_id}/resolve", payload, headers)

    def false_alarm_leak_report(self, report_id, payload, headers):
        return self._request("POST", f"/leak-reports/{report_id}/false-alarm", payload, headers)

    # --- restock runs ---
    def create_restock_run(self, payload, headers):
        return self._request("POST", "/restock-runs", payload, headers)

    def get_restock_run(self, run_id, headers):
        return self._request("GET", f"/restock-runs/{run_id}", headers=headers)

    def list_restock_runs(self, headers, params=None):
        return self._request("GET", "/restock-runs", headers=headers, params=params)

    def dispatch_restock_run(self, run_id, headers):
        return self._request("POST", f"/restock-runs/{run_id}/dispatch", {}, headers)

    def arrive_restock_run(self, run_id, headers):
        return self._request("POST", f"/restock-runs/{run_id}/arrive", {}, headers)

    def complete_restock_run(self, run_id, payload, headers):
        return self._request("POST", f"/restock-runs/{run_id}/complete", payload, headers)

    def verify_restock_run(self, run_id, headers):
        return self._request("POST", f"/restock-runs/{run_id}/verify", {}, headers)

    def cancel_restock_run(self, run_id, headers):
        return self._request("POST", f"/restock-runs/{run_id}/cancel", {}, headers)

    # --- commission statements ---
    def create_commission_statement(self, payload, headers):
        return self._request("POST", "/commission-statements", payload, headers)

    def get_commission_statement(self, statement_id, headers):
        return self._request("GET", f"/commission-statements/{statement_id}", headers=headers)

    def list_commission_statements(self, headers, params=None):
        return self._request("GET", "/commission-statements", headers=headers, params=params)

    def finalize_commission_statement(self, statement_id, headers):
        return self._request("POST", f"/commission-statements/{statement_id}/finalize", {}, headers)

    def dispute_commission_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/commission-statements/{statement_id}/dispute", payload, headers)

    def pay_commission_statement(self, statement_id, headers):
        return self._request("POST", f"/commission-statements/{statement_id}/pay", {}, headers)

    # --- reconciliation sessions ---
    def create_reconciliation_session(self, payload, headers):
        return self._request("POST", "/reconciliation-sessions", payload, headers)

    def get_reconciliation_session(self, session_id, headers):
        return self._request("GET", f"/reconciliation-sessions/{session_id}", headers=headers)

    def list_reconciliation_sessions(self, headers, params=None):
        return self._request("GET", "/reconciliation-sessions", headers=headers, params=params)

    def count_reconciliation_session(self, session_id, payload, headers):
        return self._request("POST", f"/reconciliation-sessions/{session_id}/count", payload, headers)

    def recount_reconciliation_session(self, session_id, headers):
        return self._request("POST", f"/reconciliation-sessions/{session_id}/recount", {}, headers)

    def escalate_reconciliation_session(self, session_id, payload, headers):
        return self._request("POST", f"/reconciliation-sessions/{session_id}/escalate", payload, headers)

    def resolve_reconciliation_session(self, session_id, payload, headers):
        return self._request("POST", f"/reconciliation-sessions/{session_id}/resolve", payload, headers)


api_client = ApiClient()
