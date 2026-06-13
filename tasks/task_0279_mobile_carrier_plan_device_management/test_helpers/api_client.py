"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Accounts ────────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def mark_delinquent(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/mark-delinquent", payload, headers)

    # ─── Plans ───────────────────────────────────────────────────────────
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/retire", headers=headers)

    # ─── Devices ─────────────────────────────────────────────────────────
    def create_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    # ─── Lines ───────────────────────────────────────────────────────────
    def create_line(self, payload, headers):
        return self._request("POST", "/lines", payload, headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/lines", headers=headers, params=params)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/lines/{line_id}", headers=headers)

    def activate_line(self, line_id, headers):
        return self._request("POST", f"/lines/{line_id}/activate", headers=headers)

    def suspend_line(self, line_id, payload, headers):
        return self._request("POST", f"/lines/{line_id}/suspend", payload, headers)

    def reconnect_line(self, line_id, headers):
        return self._request("POST", f"/lines/{line_id}/reconnect", headers=headers)

    def cancel_line(self, line_id, headers):
        return self._request("POST", f"/lines/{line_id}/cancel", headers=headers)

    def get_usage_summary(self, line_id, headers):
        return self._request("GET", f"/lines/{line_id}/usage-summary", headers=headers)

    # ─── SIM assignments ─────────────────────────────────────────────────
    def create_sim_assignment(self, payload, headers):
        return self._request("POST", "/sim-assignments", payload, headers)

    def get_sim_assignment(self, sim_id, headers):
        return self._request("GET", f"/sim-assignments/{sim_id}", headers=headers)

    def list_sim_assignments(self, headers, params=None):
        return self._request("GET", "/sim-assignments", headers=headers, params=params)

    # ─── Installment plans (EIP) ─────────────────────────────────────────
    def create_installment_plan(self, payload, headers):
        return self._request("POST", "/installment-plans", payload, headers)

    def get_installment_plan(self, eip_id, headers):
        return self._request("GET", f"/installment-plans/{eip_id}", headers=headers)

    def list_installment_plans(self, headers, params=None):
        return self._request("GET", "/installment-plans", headers=headers, params=params)

    # ─── Upgrades ────────────────────────────────────────────────────────
    def create_upgrade(self, payload, headers):
        return self._request("POST", "/upgrades", payload, headers)

    def get_upgrade(self, upgrade_id, headers):
        return self._request("GET", f"/upgrades/{upgrade_id}", headers=headers)

    def list_upgrades(self, headers, params=None):
        return self._request("GET", "/upgrades", headers=headers, params=params)

    # ─── Port requests ───────────────────────────────────────────────────
    def create_port_request(self, payload, headers):
        return self._request("POST", "/port-requests", payload, headers)

    def get_port_request(self, pr_id, headers):
        return self._request("GET", f"/port-requests/{pr_id}", headers=headers)

    def list_port_requests(self, headers, params=None):
        return self._request("GET", "/port-requests", headers=headers, params=params)

    def validate_port_request(self, pr_id, payload, headers):
        return self._request("POST", f"/port-requests/{pr_id}/validate", payload, headers)

    def complete_port_request(self, pr_id, headers):
        return self._request("POST", f"/port-requests/{pr_id}/complete", headers=headers)

    def reject_port_request(self, pr_id, payload, headers):
        return self._request("POST", f"/port-requests/{pr_id}/reject", payload, headers)

    def revert_port_request(self, pr_id, headers):
        return self._request("POST", f"/port-requests/{pr_id}/revert", headers=headers)

    # ─── Add-ons ─────────────────────────────────────────────────────────
    def create_addon(self, payload, headers):
        return self._request("POST", "/addons", payload, headers)

    def get_addon(self, addon_id, headers):
        return self._request("GET", f"/addons/{addon_id}", headers=headers)

    def list_addons(self, headers, params=None):
        return self._request("GET", "/addons", headers=headers, params=params)

    def activate_addon(self, addon_id, headers):
        return self._request("POST", f"/addons/{addon_id}/activate", headers=headers)

    def cancel_addon(self, addon_id, headers):
        return self._request("POST", f"/addons/{addon_id}/cancel", headers=headers)

    # ─── Usage records ───────────────────────────────────────────────────
    def create_usage_record(self, payload, headers):
        return self._request("POST", "/usage-records", payload, headers)

    def get_usage_record(self, usage_id, headers):
        return self._request("GET", f"/usage-records/{usage_id}", headers=headers)

    def list_usage_records(self, headers, params=None):
        return self._request("GET", "/usage-records", headers=headers, params=params)

    # ─── Billing cycles ──────────────────────────────────────────────────
    def create_billing_cycle(self, payload, headers):
        return self._request("POST", "/billing-cycles", payload, headers)

    def get_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/billing-cycles/{cycle_id}", headers=headers)

    def list_billing_cycles(self, headers, params=None):
        return self._request("GET", "/billing-cycles", headers=headers, params=params)

    def close_billing_cycle(self, cycle_id, headers):
        return self._request("POST", f"/billing-cycles/{cycle_id}/close", headers=headers)

    # ─── Charges (ledger) ────────────────────────────────────────────────
    def get_charge(self, charge_id, headers):
        return self._request("GET", f"/charges/{charge_id}", headers=headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", "/charges", headers=headers, params=params)

    # ─── Test-driving clock ──────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
