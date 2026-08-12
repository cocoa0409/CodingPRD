"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- formulations ---
    def create_formulation(self, payload, headers):
        return self._request("POST", "/api/formulations", payload, headers)

    def list_formulations(self, headers, params=None):
        return self._request("GET", "/api/formulations", headers=headers, params=params)

    def get_formulation(self, formulation_id, headers):
        return self._request("GET", f"/api/formulations/{formulation_id}", headers=headers)

    def activate_formulation(self, formulation_id, headers):
        return self._request("POST", f"/api/formulations/{formulation_id}/activate", {}, headers)

    def withdraw_formulation(self, formulation_id, headers):
        return self._request("POST", f"/api/formulations/{formulation_id}/withdraw", {}, headers)

    # --- mixing vessels ---
    def create_vessel(self, payload, headers):
        return self._request("POST", "/api/mixing-vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/api/mixing-vessels/{vessel_id}", headers=headers)

    # --- dry rooms ---
    def create_dry_room(self, payload, headers):
        return self._request("POST", "/api/dry-rooms", payload, headers)

    def get_dry_room(self, dry_room_id, headers):
        return self._request("GET", f"/api/dry-rooms/{dry_room_id}", headers=headers)

    # --- production batches ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/api/batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/api/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/api/batches/{batch_id}", headers=headers)

    def complete_mix(self, batch_id, headers):
        return self._request("POST", f"/api/batches/{batch_id}/complete-mix", {}, headers)

    def void_batch(self, batch_id, headers, payload=None):
        return self._request("POST", f"/api/batches/{batch_id}/void", payload or {}, headers)

    # --- packaging runs ---
    def create_packaging_run(self, payload, headers):
        return self._request("POST", "/api/packaging-runs", payload, headers)

    def list_packaging_runs(self, headers, params=None):
        return self._request("GET", "/api/packaging-runs", headers=headers, params=params)

    def get_packaging_run(self, run_id, headers):
        return self._request("GET", f"/api/packaging-runs/{run_id}", headers=headers)

    def complete_run(self, run_id, headers):
        return self._request("POST", f"/api/packaging-runs/{run_id}/complete", {}, headers)

    def create_exposure_event(self, run_id, payload, headers):
        return self._request("POST", f"/api/packaging-runs/{run_id}/exposure-events", payload, headers)

    def list_exposure_events(self, headers, params=None):
        return self._request("GET", "/api/exposure-events", headers=headers, params=params)

    def get_exposure_event(self, event_id, headers):
        return self._request("GET", f"/api/exposure-events/{event_id}", headers=headers)

    def hold_release(self, run_id, payload, headers):
        return self._request("POST", f"/api/packaging-runs/{run_id}/hold-release", payload, headers)

    # --- production lots ---
    def list_production_lots(self, headers, params=None):
        return self._request("GET", "/api/production-lots", headers=headers, params=params)

    def get_production_lot(self, lot_id, headers):
        return self._request("GET", f"/api/production-lots/{lot_id}", headers=headers)

    def create_cure_test(self, lot_id, payload, headers):
        return self._request("POST", f"/api/production-lots/{lot_id}/cure-tests", payload, headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/api/production-lots/{lot_id}/release", {}, headers)

    def reject_lot(self, lot_id, headers, payload=None):
        return self._request("POST", f"/api/production-lots/{lot_id}/reject", payload or {}, headers)

    def request_retest(self, lot_id, headers):
        return self._request("POST", f"/api/production-lots/{lot_id}/request-retest", {}, headers)

    # --- cure tests ---
    def list_cure_tests(self, headers, params=None):
        return self._request("GET", "/api/cure-tests", headers=headers, params=params)

    def get_cure_test(self, test_id, headers):
        return self._request("GET", f"/api/cure-tests/{test_id}", headers=headers)

    def accept_cure_test(self, test_id, headers):
        return self._request("POST", f"/api/cure-tests/{test_id}/accept", {}, headers)

    def void_cure_test(self, test_id, headers, payload=None):
        return self._request("POST", f"/api/cure-tests/{test_id}/void", payload or {}, headers)

    # --- formulation requests ---
    def create_formulation_request(self, payload, headers):
        return self._request("POST", "/api/formulation-requests", payload, headers)

    def list_formulation_requests(self, headers, params=None):
        return self._request("GET", "/api/formulation-requests", headers=headers, params=params)

    def get_formulation_request(self, request_id, headers):
        return self._request("GET", f"/api/formulation-requests/{request_id}", headers=headers)

    def start_review(self, request_id, headers):
        return self._request("POST", f"/api/formulation-requests/{request_id}/start-review", {}, headers)

    def request_info(self, request_id, payload, headers):
        return self._request("POST", f"/api/formulation-requests/{request_id}/request-info", payload, headers)

    def respond(self, request_id, payload, headers):
        return self._request("POST", f"/api/formulation-requests/{request_id}/respond", payload, headers)

    def decide(self, request_id, payload, headers):
        return self._request("POST", f"/api/formulation-requests/{request_id}/decide", payload, headers)

    def start_development(self, request_id, headers):
        return self._request("POST", f"/api/formulation-requests/{request_id}/start-development", {}, headers)

    def convert(self, request_id, payload, headers):
        return self._request("POST", f"/api/formulation-requests/{request_id}/convert", payload, headers)

    # --- distributors ---
    def create_distributor(self, payload, headers):
        return self._request("POST", "/api/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/api/distributors/{distributor_id}", headers=headers)

    # --- consignment agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/api/consignment-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/api/consignment-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/consignment-agreements/{agreement_id}", headers=headers)

    def patch_agreement(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/api/consignment-agreements/{agreement_id}", payload, headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/consignment-agreements/{agreement_id}/activate", {}, headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/consignment-agreements/{agreement_id}/suspend", {}, headers)

    def resume_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/consignment-agreements/{agreement_id}/resume", {}, headers)

    def close_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/consignment-agreements/{agreement_id}/close", {}, headers)

    # --- consignment stock ---
    def list_consignment_stock(self, headers, params=None):
        return self._request("GET", "/api/consignment-stock", headers=headers, params=params)

    def get_consignment_stock(self, stock_id, headers):
        return self._request("GET", f"/api/consignment-stock/{stock_id}", headers=headers)

    def return_stock(self, stock_id, payload, headers):
        return self._request("POST", f"/api/consignment-stock/{stock_id}/return", payload, headers)

    # --- consumption reports ---
    def create_consumption_report(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/api/consignment-agreements/{agreement_id}/consumption-reports", payload, headers
        )

    def list_consumption_reports(self, headers, params=None):
        return self._request("GET", "/api/consumption-reports", headers=headers, params=params)

    def get_consumption_report(self, report_id, headers):
        return self._request("GET", f"/api/consumption-reports/{report_id}", headers=headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/api/consumption-reports/{report_id}/submit", {}, headers)

    def settle_report(self, report_id, headers):
        return self._request("POST", f"/api/consumption-reports/{report_id}/settle", {}, headers)

    def dispute_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/consumption-reports/{report_id}/dispute", payload, headers)

    def revise_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/consumption-reports/{report_id}/revise", payload, headers)

    # --- shipments ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/api/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/api/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/api/shipments/{shipment_id}", headers=headers)

    def add_shipment_line(self, shipment_id, payload, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/lines", payload, headers)

    def remove_shipment_line(self, shipment_id, lot_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/lines/{lot_id}/remove", {}, headers)

    def plan_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/plan", {}, headers)

    def confirm_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/confirm", {}, headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/dispatch", {}, headers)

    def cancel_shipment(self, shipment_id, headers, payload=None):
        return self._request("POST", f"/api/shipments/{shipment_id}/cancel", payload or {}, headers)

    def replan_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/replan", {}, headers)


api_client = ApiClient()
