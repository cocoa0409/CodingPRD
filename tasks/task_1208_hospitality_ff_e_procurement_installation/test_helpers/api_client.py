"""API client: one method per endpoint defined in the PRD (§4).

All resources are mounted under the `/api` prefix (PRD §1).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- FFEProject ---
    def create_project(self, payload, headers):
        return self._request("POST", "/api/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/api/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}", headers=headers)

    def transition_project_lifecycle(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/projects/{project_id}/lifecycle-transitions",
            payload, headers,
        )

    def list_project_budget_lines(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/budget-lines",
            headers=headers, params=params,
        )

    def list_project_spec_items(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/spec-items",
            headers=headers, params=params,
        )

    def list_project_purchase_orders(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/purchase-orders",
            headers=headers, params=params,
        )

    def list_project_shipments(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/shipments",
            headers=headers, params=params,
        )

    def list_project_rooms(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/rooms",
            headers=headers, params=params,
        )

    def list_project_installation_windows(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/installation-windows",
            headers=headers, params=params,
        )

    def list_project_change_orders(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/api/projects/{project_id}/change-orders",
            headers=headers, params=params,
        )

    # --- BudgetLine ---
    def create_budget_line(self, payload, headers):
        return self._request("POST", "/api/budget-lines", payload, headers)

    def get_budget_line(self, budget_line_id, headers):
        return self._request("GET", f"/api/budget-lines/{budget_line_id}", headers=headers)

    # --- SpecItem ---
    def create_spec_item(self, payload, headers):
        return self._request("POST", "/api/spec-items", payload, headers)

    def get_spec_item(self, spec_item_id, headers):
        return self._request("GET", f"/api/spec-items/{spec_item_id}", headers=headers)

    def list_spec_item_bids(self, spec_item_id, headers, params=None):
        return self._request(
            "GET", f"/api/spec-items/{spec_item_id}/bids",
            headers=headers, params=params,
        )

    def list_spec_item_po_lines(self, spec_item_id, headers, params=None):
        return self._request(
            "GET", f"/api/spec-items/{spec_item_id}/po-lines",
            headers=headers, params=params,
        )

    def submit_spec_item(self, spec_item_id, headers, payload=None):
        return self._request(
            "POST", f"/api/spec-items/{spec_item_id}/submit",
            payload or {}, headers,
        )

    def brand_review_spec_item(self, spec_item_id, payload, headers):
        return self._request(
            "POST", f"/api/spec-items/{spec_item_id}/brand-review",
            payload, headers,
        )

    # --- VendorBid ---
    def create_bid(self, payload, headers):
        return self._request("POST", "/api/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/api/bids/{bid_id}", headers=headers)

    def sample_decision_bid(self, bid_id, payload, headers):
        return self._request(
            "POST", f"/api/bids/{bid_id}/sample-decision", payload, headers,
        )

    def resubmit_bid(self, bid_id, payload, headers):
        return self._request("POST", f"/api/bids/{bid_id}/resubmit", payload, headers)

    def award_bid(self, bid_id, headers, payload=None):
        return self._request(
            "POST", f"/api/bids/{bid_id}/award", payload or {}, headers,
        )

    # --- PurchaseOrder / POLine ---
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/api/purchase-orders", payload, headers)

    def get_purchase_order(self, purchase_order_id, headers):
        return self._request(
            "GET", f"/api/purchase-orders/{purchase_order_id}", headers=headers,
        )

    def list_purchase_order_lines(self, purchase_order_id, headers, params=None):
        return self._request(
            "GET", f"/api/purchase-orders/{purchase_order_id}/lines",
            headers=headers, params=params,
        )

    def add_purchase_order_line(self, purchase_order_id, payload, headers):
        return self._request(
            "POST", f"/api/purchase-orders/{purchase_order_id}/lines",
            payload, headers,
        )

    def transition_purchase_order(self, purchase_order_id, payload, headers):
        return self._request(
            "POST", f"/api/purchase-orders/{purchase_order_id}/transitions",
            payload, headers,
        )

    def get_po_line(self, po_line_id, headers):
        return self._request("GET", f"/api/po-lines/{po_line_id}", headers=headers)

    def reconcile_po_line(self, po_line_id, headers, payload=None):
        return self._request(
            "POST", f"/api/po-lines/{po_line_id}/reconcile", payload or {}, headers,
        )

    def create_attic_transfer(self, po_line_id, payload, headers):
        return self._request(
            "POST", f"/api/po-lines/{po_line_id}/attic-transfers", payload, headers,
        )

    def list_po_line_attic_movements(self, po_line_id, headers, params=None):
        return self._request(
            "GET", f"/api/po-lines/{po_line_id}/attic-movements",
            headers=headers, params=params,
        )

    def list_po_line_damage_claims(self, po_line_id, headers, params=None):
        return self._request(
            "GET", f"/api/po-lines/{po_line_id}/damage-claims",
            headers=headers, params=params,
        )

    def list_po_line_installation_tasks(self, po_line_id, headers, params=None):
        return self._request(
            "GET", f"/api/po-lines/{po_line_id}/installation-tasks",
            headers=headers, params=params,
        )

    # --- Shipment / ReceivingEvent ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/api/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/api/shipments/{shipment_id}", headers=headers)

    def list_shipment_purchase_orders(self, shipment_id, headers, params=None):
        return self._request(
            "GET", f"/api/shipments/{shipment_id}/purchase-orders",
            headers=headers, params=params,
        )

    def list_shipment_receiving_events(self, shipment_id, headers, params=None):
        return self._request(
            "GET", f"/api/shipments/{shipment_id}/receiving-events",
            headers=headers, params=params,
        )

    def attach_purchase_order(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/purchase-orders",
            payload, headers,
        )

    def transition_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/api/shipments/{shipment_id}/transitions", payload, headers,
        )

    def create_receiving_event(self, payload, headers):
        return self._request("POST", "/api/receiving-events", payload, headers)

    def get_receiving_event(self, receiving_event_id, headers):
        return self._request(
            "GET", f"/api/receiving-events/{receiving_event_id}", headers=headers,
        )

    def transition_receiving_event(self, receiving_event_id, payload, headers):
        return self._request(
            "POST", f"/api/receiving-events/{receiving_event_id}/transitions",
            payload, headers,
        )

    # --- DamageClaim ---
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/api/damage-claims", payload, headers)

    def get_damage_claim(self, damage_claim_id, headers):
        return self._request(
            "GET", f"/api/damage-claims/{damage_claim_id}", headers=headers,
        )

    def transition_damage_claim(self, damage_claim_id, payload, headers):
        return self._request(
            "POST", f"/api/damage-claims/{damage_claim_id}/transitions",
            payload, headers,
        )

    # --- Room / InstallationWindow / InstallationTask ---
    def create_room(self, payload, headers):
        return self._request("POST", "/api/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/api/rooms/{room_id}", headers=headers)

    def list_room_installation_tasks(self, room_id, headers, params=None):
        return self._request(
            "GET", f"/api/rooms/{room_id}/installation-tasks",
            headers=headers, params=params,
        )

    def create_installation_window(self, payload, headers):
        return self._request("POST", "/api/installation-windows", payload, headers)

    def get_installation_window(self, installation_window_id, headers):
        return self._request(
            "GET", f"/api/installation-windows/{installation_window_id}",
            headers=headers,
        )

    def list_installation_window_tasks(self, installation_window_id, headers, params=None):
        return self._request(
            "GET", f"/api/installation-windows/{installation_window_id}/tasks",
            headers=headers, params=params,
        )

    def transition_installation_window(self, installation_window_id, payload, headers):
        return self._request(
            "POST", f"/api/installation-windows/{installation_window_id}/transitions",
            payload, headers,
        )

    def create_installation_task(self, payload, headers):
        return self._request("POST", "/api/installation-tasks", payload, headers)

    def get_installation_task(self, installation_task_id, headers):
        return self._request(
            "GET", f"/api/installation-tasks/{installation_task_id}", headers=headers,
        )

    def complete_installation_task(self, installation_task_id, headers, payload=None):
        return self._request(
            "POST", f"/api/installation-tasks/{installation_task_id}/complete",
            payload or {}, headers,
        )

    # --- ChangeOrder ---
    def create_change_order(self, payload, headers):
        return self._request("POST", "/api/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request(
            "GET", f"/api/change-orders/{change_order_id}", headers=headers,
        )

    def apply_change_order(self, change_order_id, payload, headers):
        return self._request(
            "POST", f"/api/change-orders/{change_order_id}/apply", payload, headers,
        )

    def reject_change_order(self, change_order_id, headers, payload=None):
        return self._request(
            "POST", f"/api/change-orders/{change_order_id}/reject",
            payload or {}, headers,
        )


api_client = ApiClient()
