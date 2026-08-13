"""API client: one method per endpoint defined in the PRD.

Query parameters (filters, limit, offset) are passed via `params` so they land
in the URL query string rather than the JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/plant/_clock/set_current_utc", payload, headers)

    # --- plants ---
    def create_plant(self, payload, headers):
        return self._request("POST", "/plant/plants", payload, headers)

    def get_plant(self, plant_id, headers):
        return self._request("GET", f"/plant/plants/{plant_id}", headers=headers)

    def update_plant(self, plant_id, payload, headers):
        return self._request("PATCH", f"/plant/plants/{plant_id}", payload, headers)

    # --- milk intakes ---
    def create_milk_intake(self, plant_id, payload, headers):
        return self._request("POST", f"/plant/plants/{plant_id}/milk-intakes", payload, headers)

    def get_milk_intake(self, milk_intake_id, headers):
        return self._request("GET", f"/plant/milk-intakes/{milk_intake_id}", headers=headers)

    def list_milk_intakes(self, headers, params=None):
        return self._request("GET", "/plant/milk-intakes", headers=headers, params=params)

    def accept_milk_intake(self, milk_intake_id, headers):
        return self._request("POST", f"/plant/milk-intakes/{milk_intake_id}/accept", {}, headers)

    def reject_milk_intake(self, milk_intake_id, headers):
        return self._request("POST", f"/plant/milk-intakes/{milk_intake_id}/reject", {}, headers)

    # --- vats ---
    def create_vat(self, plant_id, payload, headers):
        return self._request("POST", f"/plant/plants/{plant_id}/vats", payload, headers)

    def get_vat(self, vat_id, headers):
        return self._request("GET", f"/plant/vats/{vat_id}", headers=headers)

    def list_vats(self, headers, params=None):
        return self._request("GET", "/plant/vats", headers=headers, params=params)

    def cip_vat(self, vat_id, headers):
        return self._request("POST", f"/plant/vats/{vat_id}/cip", {}, headers)

    def decommission_vat(self, vat_id, headers):
        return self._request("POST", f"/plant/vats/{vat_id}/decommission", {}, headers)

    # --- additive lots ---
    def create_additive_lot(self, plant_id, payload, headers):
        return self._request("POST", f"/plant/plants/{plant_id}/additive-lots", payload, headers)

    def get_additive_lot(self, additive_lot_id, headers):
        return self._request("GET", f"/plant/additive-lots/{additive_lot_id}", headers=headers)

    def list_additive_lots(self, headers, params=None):
        return self._request("GET", "/plant/additive-lots", headers=headers, params=params)

    def release_additive_lot(self, additive_lot_id, headers):
        return self._request("POST", f"/plant/additive-lots/{additive_lot_id}/release", {}, headers)

    def recall_additive_lot(self, additive_lot_id, headers):
        return self._request("POST", f"/plant/additive-lots/{additive_lot_id}/recall", {}, headers)

    # --- make sheets ---
    def create_make_sheet(self, payload, headers):
        return self._request("POST", "/plant/make-sheets", payload, headers)

    def get_make_sheet(self, make_sheet_id, headers):
        return self._request("GET", f"/plant/make-sheets/{make_sheet_id}", headers=headers)

    def list_make_sheets(self, headers, params=None):
        return self._request("GET", "/plant/make-sheets", headers=headers, params=params)

    def start_make_sheet(self, make_sheet_id, headers):
        return self._request("POST", f"/plant/make-sheets/{make_sheet_id}/start", {}, headers)

    def sign_off_step(self, make_sheet_id, step_no, headers):
        return self._request(
            "POST", f"/plant/make-sheets/{make_sheet_id}/steps/{step_no}/sign-off", {}, headers
        )

    def complete_make_sheet(self, make_sheet_id, payload, headers):
        return self._request("POST", f"/plant/make-sheets/{make_sheet_id}/complete", payload, headers)

    def cancel_make_sheet(self, make_sheet_id, headers):
        return self._request("POST", f"/plant/make-sheets/{make_sheet_id}/cancel", {}, headers)

    # --- cheese batches ---
    def get_cheese_batch(self, cheese_batch_id, headers):
        return self._request("GET", f"/plant/cheese-batches/{cheese_batch_id}", headers=headers)

    def list_cheese_batches(self, headers, params=None):
        return self._request("GET", "/plant/cheese-batches", headers=headers, params=params)

    def release_cheese_batch(self, cheese_batch_id, headers):
        return self._request("POST", f"/plant/cheese-batches/{cheese_batch_id}/release", {}, headers)

    def allocation_preview(self, cheese_batch_id, headers):
        return self._request(
            "GET", f"/plant/cheese-batches/{cheese_batch_id}/allocation-preview", headers=headers
        )

    # --- whey streams ---
    def get_whey_stream(self, whey_stream_id, headers):
        return self._request("GET", f"/plant/whey-streams/{whey_stream_id}", headers=headers)

    def list_whey_streams(self, headers, params=None):
        return self._request("GET", "/plant/whey-streams", headers=headers, params=params)

    def update_whey_stream(self, whey_stream_id, payload, headers):
        return self._request("PUT", f"/plant/whey-streams/{whey_stream_id}", payload, headers)

    # --- aging rooms ---
    def create_aging_room(self, plant_id, payload, headers):
        return self._request("POST", f"/plant/plants/{plant_id}/aging-rooms", payload, headers)

    def get_aging_room(self, aging_room_id, headers):
        return self._request("GET", f"/plant/aging-rooms/{aging_room_id}", headers=headers)

    def list_aging_rooms(self, headers, params=None):
        return self._request("GET", "/plant/aging-rooms", headers=headers, params=params)

    def update_aging_room(self, aging_room_id, payload, headers):
        return self._request("PATCH", f"/plant/aging-rooms/{aging_room_id}", payload, headers)

    def decommission_aging_room(self, aging_room_id, headers):
        return self._request("POST", f"/plant/aging-rooms/{aging_room_id}/decommission", {}, headers)

    # --- aging units ---
    def create_aging_unit(self, payload, headers):
        return self._request("POST", "/plant/aging-units", payload, headers)

    def get_aging_unit(self, aging_unit_id, headers):
        return self._request("GET", f"/plant/aging-units/{aging_unit_id}", headers=headers)

    def list_aging_units(self, headers, params=None):
        return self._request("GET", "/plant/aging-units", headers=headers, params=params)

    def turn_aging_unit(self, aging_unit_id, headers):
        return self._request("POST", f"/plant/aging-units/{aging_unit_id}/turn", {}, headers)

    def move_aging_unit(self, aging_unit_id, payload, headers):
        return self._request("POST", f"/plant/aging-units/{aging_unit_id}/move", payload, headers)

    def remove_aging_unit(self, aging_unit_id, headers):
        return self._request("POST", f"/plant/aging-units/{aging_unit_id}/remove", {}, headers)

    # --- grading events ---
    def create_grading_event(self, payload, headers):
        return self._request("POST", "/plant/grading-events", payload, headers)

    def get_grading_event(self, grading_event_id, headers):
        return self._request("GET", f"/plant/grading-events/{grading_event_id}", headers=headers)

    def list_grading_events(self, headers, params=None):
        return self._request("GET", "/plant/grading-events", headers=headers, params=params)

    # --- allocation orders ---
    def create_allocation_order(self, payload, headers):
        return self._request("POST", "/plant/allocation-orders", payload, headers)

    def get_allocation_order(self, allocation_order_id, headers):
        return self._request("GET", f"/plant/allocation-orders/{allocation_order_id}", headers=headers)

    def list_allocation_orders(self, headers, params=None):
        return self._request("GET", "/plant/allocation-orders", headers=headers, params=params)

    def cancel_allocation_order(self, allocation_order_id, headers):
        return self._request(
            "POST", f"/plant/allocation-orders/{allocation_order_id}/cancel", {}, headers
        )

    # --- cut-wrap runs ---
    def create_cut_wrap_run(self, payload, headers):
        return self._request("POST", "/plant/cut-wrap-runs", payload, headers)

    def get_cut_wrap_run(self, cut_wrap_run_id, headers):
        return self._request("GET", f"/plant/cut-wrap-runs/{cut_wrap_run_id}", headers=headers)

    def list_cut_wrap_runs(self, headers, params=None):
        return self._request("GET", "/plant/cut-wrap-runs", headers=headers, params=params)

    def reconcile_cut_wrap_run(self, cut_wrap_run_id, headers):
        return self._request(
            "POST", f"/plant/cut-wrap-runs/{cut_wrap_run_id}/reconcile", {}, headers
        )

    def void_cut_wrap_run(self, cut_wrap_run_id, headers):
        return self._request("POST", f"/plant/cut-wrap-runs/{cut_wrap_run_id}/void", {}, headers)

    # --- export certificates ---
    def create_export_certificate(self, payload, headers):
        return self._request("POST", "/plant/export-certificates", payload, headers)

    def get_export_certificate(self, export_certificate_id, headers):
        return self._request(
            "GET", f"/plant/export-certificates/{export_certificate_id}", headers=headers
        )

    def list_export_certificates(self, headers, params=None):
        return self._request("GET", "/plant/export-certificates", headers=headers, params=params)

    def issue_export_certificate(self, export_certificate_id, headers):
        return self._request(
            "POST", f"/plant/export-certificates/{export_certificate_id}/issue", {}, headers
        )

    def deny_export_certificate(self, export_certificate_id, headers):
        return self._request(
            "POST", f"/plant/export-certificates/{export_certificate_id}/deny", {}, headers
        )

    def revoke_export_certificate(self, export_certificate_id, headers):
        return self._request(
            "POST", f"/plant/export-certificates/{export_certificate_id}/revoke", {}, headers
        )


api_client = ApiClient()
