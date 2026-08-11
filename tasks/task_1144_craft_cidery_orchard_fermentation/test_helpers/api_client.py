"""API client: one method per endpoint defined in the PRD (all under /cidery)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/cidery/_clock/set_current_utc", payload, headers)

    # --- AppleVariety ---
    def create_variety(self, payload, headers):
        return self._request("POST", "/cidery/varieties", payload, headers)

    def get_variety(self, variety_id, headers):
        return self._request("GET", f"/cidery/varieties/{variety_id}", headers=headers)

    def list_varieties(self, headers, params=None):
        return self._request("GET", "/cidery/varieties", headers=headers, params=params)

    # --- YeastProgram ---
    def create_yeast_program(self, payload, headers):
        return self._request("POST", "/cidery/yeast-programs", payload, headers)

    def get_yeast_program(self, program_id, headers):
        return self._request("GET", f"/cidery/yeast-programs/{program_id}", headers=headers)

    def list_yeast_programs(self, headers, params=None):
        return self._request("GET", "/cidery/yeast-programs", headers=headers, params=params)

    # --- OrchardContract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/cidery/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/cidery/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/cidery/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/cidery/contracts/{contract_id}/activate", payload, headers)

    def settle_contract(self, contract_id, headers):
        return self._request("POST", f"/cidery/contracts/{contract_id}/settle", {}, headers)

    def void_contract(self, contract_id, headers):
        return self._request("POST", f"/cidery/contracts/{contract_id}/void", {}, headers)

    # --- HarvestLot ---
    def create_harvest_lot(self, contract_id, payload, headers):
        return self._request("POST", f"/cidery/contracts/{contract_id}/harvest-lots", payload, headers)

    def get_harvest_lot(self, lot_id, headers):
        return self._request("GET", f"/cidery/harvest-lots/{lot_id}", headers=headers)

    def list_contract_harvest_lots(self, contract_id, headers, params=None):
        return self._request("GET", f"/cidery/contracts/{contract_id}/harvest-lots",
                             headers=headers, params=params)

    def list_harvest_lots(self, headers, params=None):
        return self._request("GET", "/cidery/harvest-lots", headers=headers, params=params)

    def spoil_harvest_lot(self, lot_id, headers):
        return self._request("POST", f"/cidery/harvest-lots/{lot_id}/spoil", {}, headers)

    # --- PressBatch / BlendLine ---
    def create_press_batch(self, payload, headers):
        return self._request("POST", "/cidery/press-batches", payload, headers)

    def get_press_batch(self, batch_id, headers):
        return self._request("GET", f"/cidery/press-batches/{batch_id}", headers=headers)

    def list_press_batches(self, headers, params=None):
        return self._request("GET", "/cidery/press-batches", headers=headers, params=params)

    def list_batch_blend_lines(self, batch_id, headers):
        return self._request("GET", f"/cidery/press-batches/{batch_id}/blend-lines", headers=headers)

    def add_blend_line(self, batch_id, payload, headers):
        return self._request("POST", f"/cidery/press-batches/{batch_id}/blend-lines", payload, headers)

    def list_blend_lines(self, headers, params=None):
        return self._request("GET", "/cidery/blend-lines", headers=headers, params=params)

    def get_blend_line(self, line_id, headers):
        return self._request("GET", f"/cidery/blend-lines/{line_id}", headers=headers)

    def start_press_batch(self, batch_id, headers):
        return self._request("POST", f"/cidery/press-batches/{batch_id}/start", {}, headers)

    def pause_press_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/cidery/press-batches/{batch_id}/pause", payload, headers)

    def complete_press_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/cidery/press-batches/{batch_id}/complete", payload, headers)

    def cancel_press_batch(self, batch_id, headers):
        return self._request("POST", f"/cidery/press-batches/{batch_id}/cancel", {}, headers)

    # --- Tank ---
    def create_tank(self, payload, headers):
        return self._request("POST", "/cidery/tanks", payload, headers)

    def get_tank(self, tank_id, headers):
        return self._request("GET", f"/cidery/tanks/{tank_id}", headers=headers)

    def list_tanks(self, headers, params=None):
        return self._request("GET", "/cidery/tanks", headers=headers, params=params)

    def reserve_tank(self, tank_id, headers):
        return self._request("POST", f"/cidery/tanks/{tank_id}/reserve", {}, headers)

    def release_tank(self, tank_id, headers):
        return self._request("POST", f"/cidery/tanks/{tank_id}/release", {}, headers)

    # --- FermentationBatch ---
    def create_fermentation_batch(self, payload, headers):
        return self._request("POST", "/cidery/fermentation-batches", payload, headers)

    def get_fermentation_batch(self, batch_id, headers):
        return self._request("GET", f"/cidery/fermentation-batches/{batch_id}", headers=headers)

    def list_fermentation_batches(self, headers, params=None):
        return self._request("GET", "/cidery/fermentation-batches", headers=headers, params=params)

    def record_reading(self, batch_id, payload, headers):
        return self._request("POST", f"/cidery/fermentation-batches/{batch_id}/readings", payload, headers)

    def age_batch(self, batch_id, headers):
        return self._request("POST", f"/cidery/fermentation-batches/{batch_id}/age", {}, headers)

    def ready_batch(self, batch_id, headers):
        return self._request("POST", f"/cidery/fermentation-batches/{batch_id}/ready", {}, headers)

    def dump_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/cidery/fermentation-batches/{batch_id}/dump", payload, headers)

    def back_blend_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/cidery/fermentation-batches/{batch_id}/back-blend", payload, headers)

    # --- CiderProduct ---
    def create_product(self, payload, headers):
        return self._request("POST", "/cidery/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/cidery/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/cidery/products", headers=headers, params=params)

    def activate_product(self, product_id, headers):
        return self._request("POST", f"/cidery/products/{product_id}/activate", {}, headers)

    def retire_product(self, product_id, headers):
        return self._request("POST", f"/cidery/products/{product_id}/retire", {}, headers)

    # --- LabelApproval ---
    def create_label_approval(self, product_id, payload, headers):
        return self._request("POST", f"/cidery/products/{product_id}/label-approvals", payload, headers)

    def get_label_approval(self, approval_id, headers):
        return self._request("GET", f"/cidery/label-approvals/{approval_id}", headers=headers)

    def list_product_label_approvals(self, product_id, headers, params=None):
        return self._request("GET", f"/cidery/products/{product_id}/label-approvals",
                             headers=headers, params=params)

    def list_label_approvals(self, headers, params=None):
        return self._request("GET", "/cidery/label-approvals", headers=headers, params=params)

    def approve_label(self, approval_id, headers):
        return self._request("POST", f"/cidery/label-approvals/{approval_id}/approve", {}, headers)

    def reject_label(self, approval_id, headers):
        return self._request("POST", f"/cidery/label-approvals/{approval_id}/reject", {}, headers)

    def resubmit_label(self, approval_id, payload, headers):
        return self._request("POST", f"/cidery/label-approvals/{approval_id}/resubmit", payload, headers)

    # --- LicensePermit ---
    def create_license(self, payload, headers):
        return self._request("POST", "/cidery/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/cidery/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/cidery/licenses", headers=headers, params=params)

    def suspend_license(self, license_id, headers):
        return self._request("POST", f"/cidery/licenses/{license_id}/suspend", {}, headers)

    def reinstate_license(self, license_id, headers):
        return self._request("POST", f"/cidery/licenses/{license_id}/reinstate", {}, headers)

    # --- PackagingRun ---
    def create_packaging_run(self, payload, headers):
        return self._request("POST", "/cidery/packaging-runs", payload, headers)

    def get_packaging_run(self, run_id, headers):
        return self._request("GET", f"/cidery/packaging-runs/{run_id}", headers=headers)

    def list_packaging_runs(self, headers, params=None):
        return self._request("GET", "/cidery/packaging-runs", headers=headers, params=params)

    def complete_packaging_run(self, run_id, payload, headers):
        return self._request("POST", f"/cidery/packaging-runs/{run_id}/complete", payload, headers)

    def cancel_packaging_run(self, run_id, headers):
        return self._request("POST", f"/cidery/packaging-runs/{run_id}/cancel", {}, headers)

    # --- SalesOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/cidery/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/cidery/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/cidery/orders", headers=headers, params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/cidery/orders/{order_id}/confirm", {}, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/cidery/orders/{order_id}/ship", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/cidery/orders/{order_id}/deliver", {}, headers)

    def return_order(self, order_id, headers):
        return self._request("POST", f"/cidery/orders/{order_id}/return", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/cidery/orders/{order_id}/cancel", {}, headers)

    # --- ExciseReport ---
    def create_excise_report(self, payload, headers):
        return self._request("POST", "/cidery/excise-reports", payload, headers)

    def get_excise_report(self, report_id, headers):
        return self._request("GET", f"/cidery/excise-reports/{report_id}", headers=headers)

    def list_excise_reports(self, headers, params=None):
        return self._request("GET", "/cidery/excise-reports", headers=headers, params=params)

    def file_excise_report(self, report_id, headers):
        return self._request("POST", f"/cidery/excise-reports/{report_id}/file", {}, headers)

    def amend_excise_report(self, report_id, payload, headers):
        return self._request("POST", f"/cidery/excise-reports/{report_id}/amend", payload, headers)

    # --- ComplianceEvent (read-only audit) ---
    def list_compliance_events(self, headers, params=None):
        return self._request("GET", "/cidery/compliance-events", headers=headers, params=params)

    def get_compliance_event(self, event_id, headers):
        return self._request("GET", f"/cidery/compliance-events/{event_id}", headers=headers)


api_client = ApiClient()
