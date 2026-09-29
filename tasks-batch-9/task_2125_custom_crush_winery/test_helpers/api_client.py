"""API client: one method per endpoint published in PRD section 4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── logical clock ────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── clients ──────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def client_status(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/status", payload, headers)

    # ── contracts ────────────────────────────────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def contract_transition(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/transitions", payload, headers
        )

    def get_storage_accrual(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/storage-accrual",
            headers=headers, params=params,
        )

    def post_storage_accrual(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/storage-accruals", payload, headers
        )

    # ── vessels ──────────────────────────────────────────────────────
    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/vessels", headers=headers, params=params)

    def vessel_condition(self, vessel_id, payload, headers):
        return self._request(
            "POST", f"/vessels/{vessel_id}/condition", payload, headers
        )

    # ── vessel allocations ───────────────────────────────────────────
    def create_vessel_allocation(self, payload, headers):
        return self._request("POST", "/vessel-allocations", payload, headers)

    def get_vessel_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/vessel-allocations/{allocation_id}", headers=headers
        )

    def list_vessel_allocations(self, headers, params=None):
        return self._request(
            "GET", "/vessel-allocations", headers=headers, params=params
        )

    def commit_vessel_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"/vessel-allocations/{allocation_id}/commit", payload, headers
        )

    def vessel_allocation_transition(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"/vessel-allocations/{allocation_id}/transitions", payload, headers
        )

    # ── harvest intakes ──────────────────────────────────────────────
    def create_harvest_intake(self, payload, headers):
        return self._request("POST", "/harvest-intakes", payload, headers)

    def get_harvest_intake(self, intake_id, headers):
        return self._request("GET", f"/harvest-intakes/{intake_id}", headers=headers)

    def list_harvest_intakes(self, headers, params=None):
        return self._request("GET", "/harvest-intakes", headers=headers, params=params)

    def harvest_intake_transition(self, intake_id, payload, headers):
        return self._request(
            "POST", f"/harvest-intakes/{intake_id}/transitions", payload, headers
        )

    # ── lots ─────────────────────────────────────────────────────────
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def lot_transition(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/transitions", payload, headers)

    def get_lot_traceability(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}/traceability", headers=headers)

    # ── blend trials ─────────────────────────────────────────────────
    def create_blend_trial(self, payload, headers):
        return self._request("POST", "/blend-trials", payload, headers)

    def get_blend_trial(self, trial_id, headers):
        return self._request("GET", f"/blend-trials/{trial_id}", headers=headers)

    def list_blend_trials(self, headers, params=None):
        return self._request("GET", "/blend-trials", headers=headers, params=params)

    def revise_blend_trial(self, trial_id, payload, headers):
        return self._request(
            "POST", f"/blend-trials/{trial_id}/revise", payload, headers
        )

    def blend_trial_transition(self, trial_id, payload, headers):
        return self._request(
            "POST", f"/blend-trials/{trial_id}/transitions", payload, headers
        )

    def execute_blend_trial(self, trial_id, payload, headers):
        return self._request(
            "POST", f"/blend-trials/{trial_id}/execute", payload, headers
        )

    # ── work orders ──────────────────────────────────────────────────
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def work_order_transition(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/transitions", payload, headers
        )

    def bill_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/work-orders/{work_order_id}/bill", payload, headers
        )

    # ── bottling lines ───────────────────────────────────────────────
    def create_bottling_line(self, payload, headers):
        return self._request("POST", "/bottling-lines", payload, headers)

    def get_bottling_line(self, line_id, headers):
        return self._request("GET", f"/bottling-lines/{line_id}", headers=headers)

    def list_bottling_lines(self, headers, params=None):
        return self._request("GET", "/bottling-lines", headers=headers, params=params)

    def bottling_line_status(self, line_id, payload, headers):
        return self._request(
            "POST", f"/bottling-lines/{line_id}/status", payload, headers
        )

    # ── bottling runs ────────────────────────────────────────────────
    def create_bottling_run(self, payload, headers):
        return self._request("POST", "/bottling-runs", payload, headers)

    def get_bottling_run(self, run_id, headers):
        return self._request("GET", f"/bottling-runs/{run_id}", headers=headers)

    def list_bottling_runs(self, headers, params=None):
        return self._request("GET", "/bottling-runs", headers=headers, params=params)

    def bottling_run_transition(self, run_id, payload, headers):
        return self._request(
            "POST", f"/bottling-runs/{run_id}/transitions", payload, headers
        )

    # ── dry goods ────────────────────────────────────────────────────
    def create_dry_goods_item(self, payload, headers):
        return self._request("POST", "/dry-goods-items", payload, headers)

    def get_dry_goods_item(self, item_id, headers):
        return self._request("GET", f"/dry-goods-items/{item_id}", headers=headers)

    def list_dry_goods_items(self, headers, params=None):
        return self._request("GET", "/dry-goods-items", headers=headers, params=params)

    def receive_dry_goods(self, item_id, payload, headers):
        return self._request(
            "POST", f"/dry-goods-items/{item_id}/receipts", payload, headers
        )

    # ── TTB reports ──────────────────────────────────────────────────
    def create_ttb_report(self, payload, headers):
        return self._request("POST", "/ttb-reports", payload, headers)

    def get_ttb_report(self, report_id, headers):
        return self._request("GET", f"/ttb-reports/{report_id}", headers=headers)

    def list_ttb_reports(self, headers, params=None):
        return self._request("GET", "/ttb-reports", headers=headers, params=params)

    def ttb_report_transition(self, report_id, payload, headers):
        return self._request(
            "POST", f"/ttb-reports/{report_id}/transitions", payload, headers
        )

    # ── release orders ───────────────────────────────────────────────
    def create_release_order(self, payload, headers):
        return self._request("POST", "/release-orders", payload, headers)

    def get_release_order(self, order_id, headers):
        return self._request("GET", f"/release-orders/{order_id}", headers=headers)

    def list_release_orders(self, headers, params=None):
        return self._request("GET", "/release-orders", headers=headers, params=params)

    def release_order_transition(self, order_id, payload, headers):
        return self._request(
            "POST", f"/release-orders/{order_id}/transitions", payload, headers
        )


api_client = ApiClient()
