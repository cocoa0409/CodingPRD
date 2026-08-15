"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # The harness restarts the server before every test (per-test-server
        # isolation). HTTP keep-alive connection reuse across those restarts
        # leaves stale pooled sockets that surface as RemoteDisconnected /
        # IncompleteRead flakes. Force Connection: close so every request is a
        # fresh TCP connection to the currently live server process.
        hdrs = dict(headers or {})
        hdrs["Connection"] = "close"
        return super()._request(method, path, payload, hdrs, params)


    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/millwork/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/millwork/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/millwork/projects/{project_id}", headers=headers)

    def set_project_status(self, project_id, payload, headers):
        return self._request("PUT", f"/millwork/projects/{project_id}/status", payload, headers)

    # ------------------------------------------------------------------
    # Hardware templates
    # ------------------------------------------------------------------
    def create_hardware_template(self, payload, headers):
        return self._request("POST", "/millwork/hardware-templates", payload, headers)

    def list_hardware_templates(self, headers, params=None):
        return self._request("GET", "/millwork/hardware-templates", headers=headers, params=params)

    def get_hardware_template(self, template_id, headers):
        return self._request("GET", f"/millwork/hardware-templates/{template_id}", headers=headers)

    # ------------------------------------------------------------------
    # Moulder machines
    # ------------------------------------------------------------------
    def create_moulder_machine(self, payload, headers):
        return self._request("POST", "/millwork/moulder-machines", payload, headers)

    def list_moulder_machines(self, headers, params=None):
        return self._request("GET", "/millwork/moulder-machines", headers=headers, params=params)

    def get_moulder_machine(self, machine_id, headers):
        return self._request("GET", f"/millwork/moulder-machines/{machine_id}", headers=headers)

    # ------------------------------------------------------------------
    # Spray booths
    # ------------------------------------------------------------------
    def create_spray_booth(self, payload, headers):
        return self._request("POST", "/millwork/spray-booths", payload, headers)

    def list_spray_booths(self, headers, params=None):
        return self._request("GET", "/millwork/spray-booths", headers=headers, params=params)

    def get_spray_booth(self, booth_id, headers):
        return self._request("GET", f"/millwork/spray-booths/{booth_id}", headers=headers)

    # ------------------------------------------------------------------
    # Fire label rolls
    # ------------------------------------------------------------------
    def create_fire_label_roll(self, payload, headers):
        return self._request("POST", "/millwork/fire-label-rolls", payload, headers)

    def list_fire_label_rolls(self, headers, params=None):
        return self._request("GET", "/millwork/fire-label-rolls", headers=headers, params=params)

    def get_fire_label_roll(self, roll_id, headers):
        return self._request("GET", f"/millwork/fire-label-rolls/{roll_id}", headers=headers)

    def set_fire_label_roll_status(self, roll_id, payload, headers):
        return self._request("PUT", f"/millwork/fire-label-rolls/{roll_id}/status", payload, headers)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/millwork/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/millwork/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/millwork/orders/{order_id}", headers=headers)

    def update_order(self, order_id, payload, headers):
        return self._request("PUT", f"/millwork/orders/{order_id}", payload, headers)

    def set_order_status(self, order_id, payload, headers):
        return self._request("PUT", f"/millwork/orders/{order_id}/status", payload, headers)

    def change_order(self, order_id, headers):
        return self._request("POST", f"/millwork/orders/{order_id}/change-order", {}, headers)

    def get_invoice_summary(self, order_id, headers):
        return self._request("GET", f"/millwork/orders/{order_id}/invoice-summary", headers=headers)

    # ------------------------------------------------------------------
    # Openings
    # ------------------------------------------------------------------
    def create_opening(self, payload, headers):
        return self._request("POST", "/millwork/openings", payload, headers)

    def list_openings(self, headers, params=None):
        return self._request("GET", "/millwork/openings", headers=headers, params=params)

    def get_opening(self, opening_id, headers):
        return self._request("GET", f"/millwork/openings/{opening_id}", headers=headers)

    def set_opening_status(self, opening_id, payload, headers):
        return self._request("PUT", f"/millwork/openings/{opening_id}/status", payload, headers)

    def accept_opening(self, opening_id, headers):
        return self._request("POST", f"/millwork/openings/{opening_id}/accept", {}, headers)

    # ------------------------------------------------------------------
    # Shop drawings
    # ------------------------------------------------------------------
    def create_shop_drawing(self, payload, headers):
        return self._request("POST", "/millwork/shop-drawings", payload, headers)

    def list_shop_drawings(self, headers, params=None):
        return self._request("GET", "/millwork/shop-drawings", headers=headers, params=params)

    def get_shop_drawing(self, drawing_id, headers):
        return self._request("GET", f"/millwork/shop-drawings/{drawing_id}", headers=headers)

    def set_shop_drawing_status(self, drawing_id, payload, headers):
        return self._request("PUT", f"/millwork/shop-drawings/{drawing_id}/status", payload, headers)

    # ------------------------------------------------------------------
    # Machining programs
    # ------------------------------------------------------------------
    def create_machining_program(self, payload, headers):
        return self._request("POST", "/millwork/machining-programs", payload, headers)

    def list_machining_programs(self, headers, params=None):
        return self._request("GET", "/millwork/machining-programs", headers=headers, params=params)

    def get_machining_program(self, program_id, headers):
        return self._request("GET", f"/millwork/machining-programs/{program_id}", headers=headers)

    def set_machining_program_status(self, program_id, payload, headers):
        return self._request("PUT", f"/millwork/machining-programs/{program_id}/status", payload, headers)

    # ------------------------------------------------------------------
    # Moulder setup slots
    # ------------------------------------------------------------------
    def create_moulder_setup_slot(self, payload, headers):
        return self._request("POST", "/millwork/moulder-setup-slots", payload, headers)

    def list_moulder_setup_slots(self, headers, params=None):
        return self._request("GET", "/millwork/moulder-setup-slots", headers=headers, params=params)

    def get_moulder_setup_slot(self, slot_id, headers):
        return self._request("GET", f"/millwork/moulder-setup-slots/{slot_id}", headers=headers)

    def set_moulder_setup_slot_status(self, slot_id, payload, headers):
        return self._request("PUT", f"/millwork/moulder-setup-slots/{slot_id}/status", payload, headers)

    # ------------------------------------------------------------------
    # Finishing batches
    # ------------------------------------------------------------------
    def create_finishing_batch(self, payload, headers):
        return self._request("POST", "/millwork/finishing-batches", payload, headers)

    def list_finishing_batches(self, headers, params=None):
        return self._request("GET", "/millwork/finishing-batches", headers=headers, params=params)

    def get_finishing_batch(self, batch_id, headers):
        return self._request("GET", f"/millwork/finishing-batches/{batch_id}", headers=headers)

    def set_finishing_batch_status(self, batch_id, payload, headers):
        return self._request("PUT", f"/millwork/finishing-batches/{batch_id}/status", payload, headers)

    def measure_finishing_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/millwork/finishing-batches/{batch_id}/measure", payload, headers)

    # ------------------------------------------------------------------
    # Label allocations
    # ------------------------------------------------------------------
    def create_label_allocation(self, payload, headers):
        return self._request("POST", "/millwork/label-allocations", payload, headers)

    def list_label_allocations(self, headers, params=None):
        return self._request("GET", "/millwork/label-allocations", headers=headers, params=params)

    def get_label_allocation(self, allocation_id, headers):
        return self._request("GET", f"/millwork/label-allocations/{allocation_id}", headers=headers)

    def set_label_allocation_status(self, allocation_id, payload, headers):
        return self._request("PUT", f"/millwork/label-allocations/{allocation_id}/status", payload, headers)

    # ------------------------------------------------------------------
    # Delivery trips
    # ------------------------------------------------------------------
    def create_delivery_trip(self, payload, headers):
        return self._request("POST", "/millwork/delivery-trips", payload, headers)

    def list_delivery_trips(self, headers, params=None):
        return self._request("GET", "/millwork/delivery-trips", headers=headers, params=params)

    def get_delivery_trip(self, trip_id, headers):
        return self._request("GET", f"/millwork/delivery-trips/{trip_id}", headers=headers)

    def assign_opening(self, trip_id, payload, headers):
        return self._request("POST", f"/millwork/delivery-trips/{trip_id}/assign", payload, headers)

    def unassign_opening(self, trip_id, payload, headers):
        return self._request("POST", f"/millwork/delivery-trips/{trip_id}/unassign", payload, headers)

    def set_delivery_trip_status(self, trip_id, payload, headers):
        return self._request("PUT", f"/millwork/delivery-trips/{trip_id}/status", payload, headers)

    # ------------------------------------------------------------------
    # Punch items
    # ------------------------------------------------------------------
    def create_punch_item(self, payload, headers):
        return self._request("POST", "/millwork/punch-items", payload, headers)

    def list_punch_items(self, headers, params=None):
        return self._request("GET", "/millwork/punch-items", headers=headers, params=params)

    def get_punch_item(self, punch_id, headers):
        return self._request("GET", f"/millwork/punch-items/{punch_id}", headers=headers)

    def set_punch_item_status(self, punch_id, payload, headers):
        return self._request("PUT", f"/millwork/punch-items/{punch_id}/status", payload, headers)

    def begin_rework(self, punch_id, payload, headers):
        return self._request("POST", f"/millwork/punch-items/{punch_id}/begin-rework", payload, headers)

    def resolve_punch_item(self, punch_id, headers):
        return self._request("POST", f"/millwork/punch-items/{punch_id}/resolve", {}, headers)


api_client = ApiClient()
