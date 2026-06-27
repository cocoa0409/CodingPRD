"""API client: one method per endpoint defined in the Grain Elevator Coop PRD §4.

All resources mount under /commodities; the logical clock under /_clock.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Commodity ---
    def create_commodity(self, payload, headers):
        return self._request("POST", "/commodities", payload, headers)

    def get_commodity(self, commodity_id, headers):
        return self._request("GET", f"/commodities/{commodity_id}", headers=headers)

    # --- PriceBoard ---
    def create_price_board(self, payload, headers):
        return self._request("POST", "/commodities/price-boards", payload, headers)

    def get_price_board(self, board_id, headers):
        return self._request("GET", f"/commodities/price-boards/{board_id}", headers=headers)

    def list_price_boards(self, headers, params=None):
        return self._request("GET", "/commodities/price-boards", headers=headers, params=params)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/commodities/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/commodities/members/{member_id}", headers=headers)

    def list_member_allocations(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/commodities/members/{member_id}/allocations", headers=headers, params=params
        )

    # --- ScaleTicket ---
    def create_scale_ticket(self, payload, headers):
        return self._request("POST", "/commodities/scale-tickets", payload, headers)

    def get_scale_ticket(self, ticket_id, headers):
        return self._request("GET", f"/commodities/scale-tickets/{ticket_id}", headers=headers)

    def list_scale_tickets(self, headers, params=None):
        return self._request("GET", "/commodities/scale-tickets", headers=headers, params=params)

    def grade_scale_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/commodities/scale-tickets/{ticket_id}/grade", {}, headers
        )

    def void_scale_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/commodities/scale-tickets/{ticket_id}/void", {}, headers
        )

    # --- StoragePosition ---
    def get_storage_position(self, position_id, headers):
        return self._request("GET", f"/commodities/storage-positions/{position_id}", headers=headers)

    def list_storage_positions(self, headers, params=None):
        return self._request(
            "GET", "/commodities/storage-positions", headers=headers, params=params
        )

    def freeze_charge(self, position_id, headers):
        return self._request(
            "POST", f"/commodities/storage-positions/{position_id}/freeze-charge", {}, headers
        )

    def unfreeze_charge(self, position_id, headers):
        return self._request(
            "POST", f"/commodities/storage-positions/{position_id}/unfreeze-charge", {}, headers
        )

    # --- WarehouseReceipt ---
    def create_warehouse_receipt(self, payload, headers):
        return self._request("POST", "/commodities/warehouse-receipts", payload, headers)

    def get_warehouse_receipt(self, receipt_id, headers):
        return self._request("GET", f"/commodities/warehouse-receipts/{receipt_id}", headers=headers)

    def list_warehouse_receipts(self, headers, params=None):
        return self._request(
            "GET", "/commodities/warehouse-receipts", headers=headers, params=params
        )

    # --- Contract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/commodities/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/commodities/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/commodities/contracts", headers=headers, params=params)

    def fix_price(self, contract_id, headers):
        return self._request(
            "POST", f"/commodities/contracts/{contract_id}/fix-price", {}, headers
        )

    def cancel_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/commodities/contracts/{contract_id}/cancel", {}, headers
        )

    # --- Settlement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/commodities/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/commodities/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/commodities/settlements", headers=headers, params=params)

    def post_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/commodities/settlements/{settlement_id}/post", payload, headers
        )

    def cancel_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/commodities/settlements/{settlement_id}/cancel", {}, headers
        )

    # --- LoadoutBay ---
    def create_loadout_bay(self, payload, headers):
        return self._request("POST", "/commodities/loadout-bays", payload, headers)

    def get_loadout_bay(self, bay_id, headers):
        return self._request("GET", f"/commodities/loadout-bays/{bay_id}", headers=headers)

    def list_loadout_bays(self, headers, params=None):
        return self._request("GET", "/commodities/loadout-bays", headers=headers, params=params)

    # --- DryerLine ---
    def create_dryer_line(self, payload, headers):
        return self._request("POST", "/commodities/dryer-lines", payload, headers)

    def get_dryer_line(self, line_id, headers):
        return self._request("GET", f"/commodities/dryer-lines/{line_id}", headers=headers)

    def list_dryer_lines(self, headers, params=None):
        return self._request("GET", "/commodities/dryer-lines", headers=headers, params=params)

    # --- DryingReservation ---
    def create_drying_reservation(self, payload, headers):
        return self._request("POST", "/commodities/drying-reservations", payload, headers)

    def get_drying_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/commodities/drying-reservations/{reservation_id}", headers=headers
        )

    def list_drying_reservations(self, headers, params=None):
        return self._request(
            "GET", "/commodities/drying-reservations", headers=headers, params=params
        )

    def release_drying_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/commodities/drying-reservations/{reservation_id}/release", {}, headers
        )

    # --- Shipment ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/commodities/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/commodities/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/commodities/shipments", headers=headers, params=params)

    def load_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/commodities/shipments/{shipment_id}/load", {}, headers
        )

    def ship_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/commodities/shipments/{shipment_id}/ship", {}, headers
        )

    def cancel_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/commodities/shipments/{shipment_id}/cancel", {}, headers
        )

    # --- HedgePosition ---
    def create_hedge_position(self, payload, headers):
        return self._request("POST", "/commodities/hedge-positions", payload, headers)

    def get_hedge_position(self, position_id, headers):
        return self._request("GET", f"/commodities/hedge-positions/{position_id}", headers=headers)

    def list_hedge_positions(self, headers, params=None):
        return self._request("GET", "/commodities/hedge-positions", headers=headers, params=params)

    def mark_hedge_position(self, position_id, payload, headers):
        return self._request(
            "POST", f"/commodities/hedge-positions/{position_id}/mark", payload, headers
        )

    def meet_call(self, position_id, payload, headers):
        return self._request(
            "POST", f"/commodities/hedge-positions/{position_id}/meet-call", payload, headers
        )

    def close_hedge_position(self, position_id, headers):
        return self._request(
            "POST", f"/commodities/hedge-positions/{position_id}/close", {}, headers
        )

    # --- PatronagePeriod ---
    def create_patronage_period(self, payload, headers):
        return self._request("POST", "/commodities/patronage-periods", payload, headers)

    def get_patronage_period(self, period_id, headers):
        return self._request("GET", f"/commodities/patronage-periods/{period_id}", headers=headers)

    def list_period_allocations(self, period_id, headers, params=None):
        return self._request(
            "GET", f"/commodities/patronage-periods/{period_id}/allocations",
            headers=headers, params=params,
        )

    def close_patronage_period(self, period_id, headers):
        return self._request(
            "POST", f"/commodities/patronage-periods/{period_id}/close", {}, headers
        )

    # --- Logical clock (test-driving facility) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
