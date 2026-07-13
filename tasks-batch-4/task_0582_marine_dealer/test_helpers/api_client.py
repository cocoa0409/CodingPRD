"""API client: one method per endpoint defined in the Marine Dealer PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- Unit ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def list_unit_for_sale(self, unit_id, headers):
        return self._request("POST", f"/units/{unit_id}/list", {}, headers)

    # --- FloorPlan ---
    def create_floor_plan(self, payload, headers):
        return self._request("POST", "/floor-plans", payload, headers)

    def get_floor_plan(self, floor_plan_id, headers):
        return self._request("GET", f"/floor-plans/{floor_plan_id}", headers=headers)

    def list_floor_plans(self, headers, params=None):
        return self._request("GET", "/floor-plans", headers=headers, params=params)

    def curtail_floor_plan(self, floor_plan_id, payment_cents, headers):
        return self._request("POST", f"/floor-plans/{floor_plan_id}/curtail",
                             {"payment_cents": payment_cents}, headers)

    # --- Deal ---
    def create_deal(self, payload, headers):
        return self._request("POST", "/deals", payload, headers)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def sign_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/sign", {}, headers)

    def fund_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/fund", {}, headers)

    def deliver_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/deliver", {}, headers)

    def cancel_deal(self, deal_id, headers):
        return self._request("POST", f"/deals/{deal_id}/cancel", {}, headers)

    # --- Consignment ---
    def create_consignment(self, payload, headers):
        return self._request("POST", "/consignments", payload, headers)

    def get_consignment(self, consignment_id, headers):
        return self._request("GET", f"/consignments/{consignment_id}", headers=headers)

    def list_consignments(self, headers, params=None):
        return self._request("GET", "/consignments", headers=headers, params=params)

    def return_consignment(self, consignment_id, headers):
        return self._request("POST", f"/consignments/{consignment_id}/return", {}, headers)

    # --- RepairOrder ---
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def get_repair_order(self, repair_order_id, headers):
        return self._request("GET", f"/repair-orders/{repair_order_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def start_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/start", {}, headers)

    def complete_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/complete", {}, headers)

    def reopen_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/reopen", {}, headers)

    def invoice_repair_order(self, repair_order_id, headers):
        return self._request("POST", f"/repair-orders/{repair_order_id}/invoice", {}, headers)

    # --- ServiceLine ---
    def create_service_line(self, payload, headers):
        return self._request("POST", "/service-lines", payload, headers)

    def get_service_line(self, service_line_id, headers):
        return self._request("GET", f"/service-lines/{service_line_id}", headers=headers)

    def list_service_lines(self, headers, params=None):
        return self._request("GET", "/service-lines", headers=headers, params=params)

    def void_service_line(self, service_line_id, headers):
        return self._request("POST", f"/service-lines/{service_line_id}/void", {}, headers)

    # --- Part ---
    def create_part(self, payload, headers):
        return self._request("POST", "/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/parts/{part_id}", headers=headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/parts", headers=headers, params=params)

    def receive_part(self, part_id, quantity, headers):
        return self._request("POST", f"/parts/{part_id}/receive", {"quantity": quantity}, headers)

    # --- Berth ---
    def create_berth(self, payload, headers):
        return self._request("POST", "/berths", payload, headers)

    def get_berth(self, berth_id, headers):
        return self._request("GET", f"/berths/{berth_id}", headers=headers)

    def close_berth(self, berth_id, headers):
        return self._request("POST", f"/berths/{berth_id}/close", {}, headers)

    # --- ServiceBay ---
    def create_service_bay(self, payload, headers):
        return self._request("POST", "/service-bays", payload, headers)

    def get_service_bay(self, service_bay_id, headers):
        return self._request("GET", f"/service-bays/{service_bay_id}", headers=headers)

    # --- SlipReservation ---
    def create_slip_reservation(self, payload, headers):
        return self._request("POST", "/slip-reservations", payload, headers)

    def get_slip_reservation(self, reservation_id, headers):
        return self._request("GET", f"/slip-reservations/{reservation_id}", headers=headers)

    def list_slip_reservations(self, headers, params=None):
        return self._request("GET", "/slip-reservations", headers=headers, params=params)

    def end_slip_reservation(self, reservation_id, headers):
        return self._request("POST", f"/slip-reservations/{reservation_id}/end", {}, headers)

    def cancel_slip_reservation(self, reservation_id, headers):
        return self._request("POST", f"/slip-reservations/{reservation_id}/cancel", {}, headers)


api_client = ApiClient()
