"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Fields ---
    def create_field(self, payload, headers):
        return self._request("POST", "/api/fields", payload, headers)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/api/fields/{field_id}", headers=headers)

    # --- Kilns ---
    def create_kiln(self, payload, headers):
        return self._request("POST", "/api/kilns", payload, headers)

    def get_kiln(self, kiln_id, headers):
        return self._request("GET", f"/api/kilns/{kiln_id}", headers=headers)

    # --- Planting plans ---
    def create_planting_plan(self, payload, headers):
        return self._request("POST", "/api/planting-plans", payload, headers)

    def get_planting_plan(self, plan_id, headers):
        return self._request("GET", f"/api/planting-plans/{plan_id}", headers=headers)

    def list_planting_plans(self, headers, params=None):
        return self._request("GET", "/api/planting-plans", headers=headers, params=params)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"/api/planting-plans/{plan_id}/approve", {}, headers)

    def revise_plan(self, plan_id, headers):
        return self._request("POST", f"/api/planting-plans/{plan_id}/revise", {}, headers)

    def open_harvest(self, plan_id, headers):
        return self._request("POST", f"/api/planting-plans/{plan_id}/open-harvest", {}, headers)

    def complete_plan(self, plan_id, headers):
        return self._request("POST", f"/api/planting-plans/{plan_id}/complete", {}, headers)

    def cancel_plan(self, plan_id, headers):
        return self._request("POST", f"/api/planting-plans/{plan_id}/cancel", {}, headers)

    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/api/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/activate", {}, headers)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/suspend", {}, headers)

    def reinstate_contract(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/reinstate", {}, headers)

    def amend_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/amendments", payload, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/terminate", {}, headers)

    # --- Harvest lots ---
    def create_harvest_lot(self, payload, headers):
        return self._request("POST", "/api/harvest-lots", payload, headers)

    def get_harvest_lot(self, lot_id, headers):
        return self._request("GET", f"/api/harvest-lots/{lot_id}", headers=headers)

    def list_harvest_lots(self, headers, params=None):
        return self._request("GET", "/api/harvest-lots", headers=headers, params=params)

    def load_kiln(self, lot_id, payload, headers):
        return self._request("POST", f"/api/harvest-lots/{lot_id}/load-kiln", payload, headers)

    def finish_drying(self, lot_id, payload, headers):
        return self._request("POST", f"/api/harvest-lots/{lot_id}/finish-drying", payload, headers)

    def redry(self, lot_id, payload, headers):
        return self._request("POST", f"/api/harvest-lots/{lot_id}/redry", payload, headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/api/harvest-lots/{lot_id}/release", {}, headers)

    # --- Lab tests ---
    def create_lab_test(self, payload, headers):
        return self._request("POST", "/api/lab-tests", payload, headers)

    def get_lab_test(self, test_id, headers):
        return self._request("GET", f"/api/lab-tests/{test_id}", headers=headers)

    def list_lab_tests(self, headers, params=None):
        return self._request("GET", "/api/lab-tests", headers=headers, params=params)

    # --- Pellet lots ---
    def create_pellet_lot(self, payload, headers):
        return self._request("POST", "/api/pellet-lots", payload, headers)

    def get_pellet_lot(self, lot_id, headers):
        return self._request("GET", f"/api/pellet-lots/{lot_id}", headers=headers)

    def list_pellet_lots(self, headers, params=None):
        return self._request("GET", "/api/pellet-lots", headers=headers, params=params)

    # --- Allocation runs & allocations ---
    def create_allocation_run(self, payload, headers):
        return self._request("POST", "/api/allocation-runs", payload, headers)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/api/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/api/allocations", headers=headers, params=params)

    def confirm_allocation(self, allocation_id, headers):
        return self._request("POST", f"/api/allocations/{allocation_id}/confirm", {}, headers)

    def cancel_allocation(self, allocation_id, headers):
        return self._request("POST", f"/api/allocations/{allocation_id}/cancel", {}, headers)

    def deliver_allocation(self, allocation_id, headers):
        return self._request("POST", f"/api/allocations/{allocation_id}/deliver", {}, headers)

    def settle_allocation(self, allocation_id, headers):
        return self._request("POST", f"/api/allocations/{allocation_id}/settle", {}, headers)

    # --- Spot sales ---
    def create_spot_sale(self, payload, headers):
        return self._request("POST", "/api/spot-sales", payload, headers)

    def get_spot_sale(self, sale_id, headers):
        return self._request("GET", f"/api/spot-sales/{sale_id}", headers=headers)

    def list_spot_sales(self, headers, params=None):
        return self._request("GET", "/api/spot-sales", headers=headers, params=params)

    def confirm_spot_sale(self, sale_id, headers):
        return self._request("POST", f"/api/spot-sales/{sale_id}/confirm", {}, headers)

    def cancel_spot_sale(self, sale_id, headers):
        return self._request("POST", f"/api/spot-sales/{sale_id}/cancel", {}, headers)

    # --- Brewery samples ---
    def create_sample(self, payload, headers):
        return self._request("POST", "/api/samples", payload, headers)

    def get_sample(self, sample_id, headers):
        return self._request("GET", f"/api/samples/{sample_id}", headers=headers)

    def list_samples(self, headers, params=None):
        return self._request("GET", "/api/samples", headers=headers, params=params)

    def decide_sample(self, sample_id, payload, headers):
        return self._request("POST", f"/api/samples/{sample_id}/decide", payload, headers)

    # --- Insurance claims ---
    def create_insurance_claim(self, payload, headers):
        return self._request("POST", "/api/insurance-claims", payload, headers)

    def get_insurance_claim(self, claim_id, headers):
        return self._request("GET", f"/api/insurance-claims/{claim_id}", headers=headers)

    def list_insurance_claims(self, headers, params=None):
        return self._request("GET", "/api/insurance-claims", headers=headers, params=params)

    def begin_review_claim(self, claim_id, headers):
        return self._request("POST", f"/api/insurance-claims/{claim_id}/begin-review", {}, headers)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/insurance-claims/{claim_id}/decide", payload, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/api/insurance-claims/{claim_id}/pay", {}, headers)

    # --- Ops & clock ---
    def crop_year_rollover(self, headers):
        return self._request("POST", "/api/ops/crop-year-rollover", {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
# The harness restarts the API server before every test (per-test-server
# isolation), which kills every keep-alive connection the previous server
# instance held. Sending `Connection: close` makes urllib3 open a fresh TCP
# connection per request instead of pooling one that can go stale mid-test
# when several suite rounds run concurrently on the same host.
api_client.session.headers["Connection"] = "close"
