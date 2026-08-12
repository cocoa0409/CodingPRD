"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # CostCenter
    # ------------------------------------------------------------------
    def create_cost_center(self, payload, headers):
        return self._request("POST", "/cost-centers", payload, headers)

    def get_cost_center(self, cost_center_id, headers):
        return self._request("GET", f"/cost-centers/{cost_center_id}", headers=headers)

    # ------------------------------------------------------------------
    # JobRole
    # ------------------------------------------------------------------
    def create_job_role(self, payload, headers):
        return self._request("POST", "/job-roles", payload, headers)

    def get_job_role(self, job_role_id, headers):
        return self._request("GET", f"/job-roles/{job_role_id}", headers=headers)

    # ------------------------------------------------------------------
    # Item
    # ------------------------------------------------------------------
    def create_item(self, payload, headers):
        return self._request("POST", "/items", payload, headers)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/items/{item_id}", headers=headers)

    def discontinue_item(self, item_id, headers):
        return self._request("POST", f"/items/{item_id}/discontinue", {}, headers)

    # ------------------------------------------------------------------
    # ContractPrice
    # ------------------------------------------------------------------
    def create_contract_price(self, payload, headers):
        return self._request("POST", "/contract-prices", payload, headers)

    def list_contract_prices(self, headers, params=None):
        return self._request("GET", "/contract-prices", headers=headers, params=params)

    def get_contract_price(self, price_id, headers):
        return self._request("GET", f"/contract-prices/{price_id}", headers=headers)

    # ------------------------------------------------------------------
    # IssuancePolicy
    # ------------------------------------------------------------------
    def create_issuance_policy(self, payload, headers):
        return self._request("POST", "/issuance-policies", payload, headers)

    def list_issuance_policies(self, headers, params=None):
        return self._request("GET", "/issuance-policies", headers=headers, params=params)

    def get_issuance_policy(self, policy_id, headers):
        return self._request("GET", f"/issuance-policies/{policy_id}", headers=headers)

    # ------------------------------------------------------------------
    # Employee
    # ------------------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def update_employee(self, employee_id, payload, headers):
        return self._request("PUT", f"/employees/{employee_id}", payload, headers)

    def record_fit_test(self, employee_id, payload, headers):
        return self._request("POST", f"/employees/{employee_id}/fit-tests", payload, headers)

    # ------------------------------------------------------------------
    # VendingMachine
    # ------------------------------------------------------------------
    def create_machine(self, payload, headers):
        return self._request("POST", "/machines", payload, headers)

    def list_machines(self, headers, params=None):
        return self._request("GET", "/machines", headers=headers, params=params)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/machines/{machine_id}", headers=headers)

    def update_machine(self, machine_id, payload, headers):
        return self._request("PUT", f"/machines/{machine_id}", payload, headers)

    # ------------------------------------------------------------------
    # MachineSlot
    # ------------------------------------------------------------------
    def create_slot(self, machine_id, payload, headers):
        return self._request("POST", f"/machines/{machine_id}/slots", payload, headers)

    def list_machine_slots(self, machine_id, headers, params=None):
        return self._request("GET", f"/machines/{machine_id}/slots", headers=headers, params=params)

    def list_slots(self, headers, params=None):
        return self._request("GET", "/slots", headers=headers, params=params)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/slots/{slot_id}", headers=headers)

    def update_slot(self, slot_id, payload, headers):
        return self._request("PUT", f"/slots/{slot_id}", payload, headers)

    # ------------------------------------------------------------------
    # SerializedUnit
    # ------------------------------------------------------------------
    def create_serialized_unit(self, payload, headers):
        return self._request("POST", "/serialized-units", payload, headers)

    def list_serialized_units(self, headers, params=None):
        return self._request("GET", "/serialized-units", headers=headers, params=params)

    def get_serialized_unit(self, unit_id, headers):
        return self._request("GET", f"/serialized-units/{unit_id}", headers=headers)

    def inspect_serialized_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/serialized-units/{unit_id}/inspect", payload, headers)

    # ------------------------------------------------------------------
    # ManagerOverride
    # ------------------------------------------------------------------
    def create_manager_override(self, payload, headers):
        return self._request("POST", "/manager-overrides", payload, headers)

    def list_manager_overrides(self, headers, params=None):
        return self._request("GET", "/manager-overrides", headers=headers, params=params)

    def get_manager_override(self, override_id, headers):
        return self._request("GET", f"/manager-overrides/{override_id}", headers=headers)

    def revoke_manager_override(self, override_id, headers):
        return self._request("POST", f"/manager-overrides/{override_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # IssuanceTransaction
    # ------------------------------------------------------------------
    def create_issuance(self, payload, headers):
        return self._request("POST", "/issuances", payload, headers)

    def list_issuances(self, headers, params=None):
        return self._request("GET", "/issuances", headers=headers, params=params)

    def get_issuance(self, issuance_id, headers):
        return self._request("GET", f"/issuances/{issuance_id}", headers=headers)

    def reverse_issuance(self, issuance_id, headers):
        return self._request("POST", f"/issuances/{issuance_id}/reverse", {}, headers)

    # ------------------------------------------------------------------
    # RestockOrder
    # ------------------------------------------------------------------
    def create_restock_order(self, payload, headers):
        return self._request("POST", "/restock-orders", payload, headers)

    def list_restock_orders(self, headers, params=None):
        return self._request("GET", "/restock-orders", headers=headers, params=params)

    def get_restock_order(self, order_id, headers):
        return self._request("GET", f"/restock-orders/{order_id}", headers=headers)

    def pick_restock_order(self, order_id, headers):
        return self._request("POST", f"/restock-orders/{order_id}/pick", {}, headers)

    def load_restock_order(self, order_id, headers):
        return self._request("POST", f"/restock-orders/{order_id}/load", {}, headers)

    def cancel_restock_order(self, order_id, headers):
        return self._request("POST", f"/restock-orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # ServiceTicket
    # ------------------------------------------------------------------
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/service-tickets", payload, headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def start_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/start", {}, headers)

    def resolve_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/resolve", {}, headers)

    # ------------------------------------------------------------------
    # ChargebackBatch
    # ------------------------------------------------------------------
    def create_chargeback_batch(self, payload, headers):
        return self._request("POST", "/chargeback-batches", payload, headers)

    def list_chargeback_batches(self, headers, params=None):
        return self._request("GET", "/chargeback-batches", headers=headers, params=params)

    def get_chargeback_batch(self, batch_id, headers):
        return self._request("GET", f"/chargeback-batches/{batch_id}", headers=headers)

    def close_chargeback_batch(self, batch_id, headers):
        return self._request("POST", f"/chargeback-batches/{batch_id}/close", {}, headers)

    def dispute_chargeback_batch(self, batch_id, headers):
        return self._request("POST", f"/chargeback-batches/{batch_id}/dispute", {}, headers)

    def settle_chargeback_batch(self, batch_id, headers):
        return self._request("POST", f"/chargeback-batches/{batch_id}/settle", {}, headers)

    # ------------------------------------------------------------------
    # ComplianceAudit
    # ------------------------------------------------------------------
    def create_compliance_audit(self, payload, headers):
        return self._request("POST", "/compliance-audits", payload, headers)

    def get_compliance_audit(self, audit_id, headers):
        return self._request("GET", f"/compliance-audits/{audit_id}", headers=headers)

    def begin_audit_fieldwork(self, audit_id, headers):
        return self._request("POST", f"/compliance-audits/{audit_id}/begin-fieldwork", {}, headers)

    def file_audit_findings(self, audit_id, headers):
        return self._request("POST", f"/compliance-audits/{audit_id}/file-findings", {}, headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"/compliance-audits/{audit_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    def get_consumption_report(self, headers, params=None):
        return self._request("GET", "/reports/consumption", headers=headers, params=params)


api_client = ApiClient()
# Under per-test-server isolation the runner kills and re-spawns the server on
# the same port before every test. This client instance is session-scoped, so a
# pooled HTTP keep-alive connection to the previous (now-killed) server process
# would otherwise be reused by the next test and surface as a spurious
# "RemoteDisconnected: Remote end closed connection without response" whenever
# the dead-connection reset races the reused request under load. Sending
# "Connection: close" makes every request open a fresh connection to whichever
# server process is currently bound, eliminating the stale-connection reuse race.
api_client.session.headers["Connection"] = "close"
