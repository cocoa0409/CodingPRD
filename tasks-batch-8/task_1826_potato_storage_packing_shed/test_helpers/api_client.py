"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/potato-shed/_clock/set_current_utc", payload, headers)

    # --- growers ---
    def create_grower(self, payload, headers):
        return self._request("POST", "/potato-shed/growers", payload, headers)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/potato-shed/growers/{grower_id}", headers=headers)

    # --- sheds / bins ---
    def create_shed(self, payload, headers):
        return self._request("POST", "/potato-shed/sheds", payload, headers)

    def get_shed(self, shed_id, headers):
        return self._request("GET", f"/potato-shed/sheds/{shed_id}", headers=headers)

    def create_bin(self, shed_id, payload, headers):
        return self._request("POST", f"/potato-shed/sheds/{shed_id}/bins", payload, headers)

    def list_bins(self, shed_id, headers, params=None):
        return self._request("GET", f"/potato-shed/sheds/{shed_id}/bins", headers=headers, params=params)

    # --- field lots ---
    def create_field_lot(self, grower_id, payload, headers):
        return self._request("POST", f"/potato-shed/growers/{grower_id}/field-lots", payload, headers)

    def get_field_lot(self, lot_id, headers):
        return self._request("GET", f"/potato-shed/field-lots/{lot_id}", headers=headers)

    def list_field_lots(self, headers, params=None):
        return self._request("GET", "/potato-shed/field-lots", headers=headers, params=params)

    def assign_bin(self, lot_id, payload, headers):
        return self._request("POST", f"/potato-shed/field-lots/{lot_id}/bin-assignment", payload, headers)

    def create_assessment(self, lot_id, payload, headers):
        return self._request("POST", f"/potato-shed/field-lots/{lot_id}/assessments", payload, headers)

    def list_assessments(self, lot_id, headers, params=None):
        return self._request("GET", f"/potato-shed/field-lots/{lot_id}/assessments", headers=headers, params=params)

    def apply_sprout_inhibitor(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/potato-shed/field-lots/{lot_id}/sprout-inhibitor-applications", payload, headers
        )

    def quality_transition(self, lot_id, payload, headers):
        return self._request("POST", f"/potato-shed/field-lots/{lot_id}/quality-transition", payload, headers)

    def close_lot(self, lot_id, headers):
        return self._request("POST", f"/potato-shed/field-lots/{lot_id}/close", {}, headers)

    def list_lot_draws(self, lot_id, headers, params=None):
        return self._request("GET", f"/potato-shed/field-lots/{lot_id}/lot-draws", headers=headers, params=params)

    # --- contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/potato-shed/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/potato-shed/contracts/{contract_id}", headers=headers)

    # --- pack orders ---
    def create_pack_order(self, payload, headers):
        return self._request("POST", "/potato-shed/pack-orders", payload, headers)

    def get_pack_order(self, order_id, headers):
        return self._request("GET", f"/potato-shed/pack-orders/{order_id}", headers=headers)

    def list_pack_orders(self, headers, params=None):
        return self._request("GET", "/potato-shed/pack-orders", headers=headers, params=params)

    def allocate_order(self, order_id, headers):
        return self._request("POST", f"/potato-shed/pack-orders/{order_id}/allocate", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/potato-shed/pack-orders/{order_id}/cancel", {}, headers)

    # --- pack runs ---
    def create_pack_run(self, order_id, payload, headers):
        return self._request("POST", f"/potato-shed/pack-orders/{order_id}/pack-runs", payload, headers)

    def list_pack_runs(self, order_id, headers, params=None):
        return self._request("GET", f"/potato-shed/pack-orders/{order_id}/pack-runs", headers=headers, params=params)

    def get_pack_run(self, run_id, headers):
        return self._request("GET", f"/potato-shed/pack-runs/{run_id}", headers=headers)

    def close_pack_run(self, run_id, payload, headers):
        return self._request("POST", f"/potato-shed/pack-runs/{run_id}/close", payload, headers)

    def list_run_draws(self, run_id, headers, params=None):
        return self._request("GET", f"/potato-shed/pack-runs/{run_id}/lot-draws", headers=headers, params=params)

    # --- food safety ---
    def record_wash_check(self, shed_id, payload, headers):
        return self._request("POST", f"/potato-shed/sheds/{shed_id}/wash-water-checks", payload, headers)

    def list_wash_checks(self, shed_id, headers, params=None):
        return self._request("GET", f"/potato-shed/sheds/{shed_id}/wash-water-checks", headers=headers, params=params)

    def create_audit(self, shed_id, payload, headers):
        return self._request("POST", f"/potato-shed/sheds/{shed_id}/audits", payload, headers)

    def close_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/potato-shed/audits/{audit_id}/close", payload, headers)

    def list_audits(self, shed_id, headers, params=None):
        return self._request("GET", f"/potato-shed/sheds/{shed_id}/audits", headers=headers, params=params)

    # --- settlements ---
    def create_settlement(self, grower_id, payload, headers):
        return self._request("POST", f"/potato-shed/growers/{grower_id}/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/potato-shed/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, grower_id, headers, params=None):
        return self._request("GET", f"/potato-shed/growers/{grower_id}/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/potato-shed/settlements/{settlement_id}/finalize", {}, headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/potato-shed/settlements/{settlement_id}/dispute", payload, headers)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/potato-shed/settlements/{settlement_id}/pay", {}, headers)


api_client = ApiClient()
