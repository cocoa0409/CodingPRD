"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Seller ----
    def create_seller(self, payload, headers):
        return self._request("POST", "/yard/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/yard/sellers/{seller_id}", headers=headers)

    def list_sellers(self, headers, params=None):
        return self._request("GET", "/yard/sellers", headers=headers, params=params)

    def patch_seller(self, seller_id, payload, headers):
        return self._request("PATCH", f"/yard/sellers/{seller_id}", payload, headers)

    def ban_seller(self, seller_id, headers):
        return self._request("POST", f"/yard/sellers/{seller_id}/ban", {}, headers)

    # ---- CommodityPrice ----
    def create_commodity_price(self, payload, headers):
        return self._request("POST", "/yard/commodity-prices", payload, headers)

    def get_commodity_price(self, price_id, headers):
        return self._request("GET", f"/yard/commodity-prices/{price_id}", headers=headers)

    def list_commodity_prices(self, headers, params=None):
        return self._request("GET", "/yard/commodity-prices", headers=headers, params=params)

    # ---- ScaleTicket ----
    def create_ticket(self, payload, headers):
        return self._request("POST", "/yard/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/yard/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/yard/tickets", headers=headers, params=params)

    def add_line_item(self, ticket_id, payload, headers):
        return self._request("POST", f"/yard/tickets/{ticket_id}/line-items", payload, headers)

    def list_ticket_line_items(self, ticket_id, headers, params=None):
        return self._request("GET", f"/yard/tickets/{ticket_id}/line-items", headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/yard/line-items/{line_item_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/yard/line-items", headers=headers, params=params)

    def weigh_out(self, ticket_id, payload, headers):
        return self._request("POST", f"/yard/tickets/{ticket_id}/weigh-out", payload, headers)

    def theft_hold(self, ticket_id, headers):
        return self._request("POST", f"/yard/tickets/{ticket_id}/theft-hold", {}, headers)

    def clear_hold(self, ticket_id, headers):
        return self._request("POST", f"/yard/tickets/{ticket_id}/clear-hold", {}, headers)

    def release_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/yard/tickets/{ticket_id}/release", payload, headers)

    def report_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/yard/tickets/{ticket_id}/report", payload, headers)

    # ---- Payout ----
    def create_payout(self, payload, headers):
        return self._request("POST", "/yard/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/yard/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/yard/payouts", headers=headers, params=params)

    def settle_payout(self, payout_id, headers):
        return self._request("POST", f"/yard/payouts/{payout_id}/settle", {}, headers)

    def void_payout(self, payout_id, headers):
        return self._request("POST", f"/yard/payouts/{payout_id}/void", {}, headers)

    # ---- Container ----
    def create_container(self, payload, headers):
        return self._request("POST", "/yard/containers", payload, headers)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/yard/containers/{container_id}", headers=headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/yard/containers", headers=headers, params=params)

    def dispatch_container(self, container_id, payload, headers):
        return self._request("POST", f"/yard/containers/{container_id}/dispatch", payload, headers)

    # ---- MillShipment ----
    def create_mill_shipment(self, payload, headers):
        return self._request("POST", "/yard/mill-shipments", payload, headers)

    def get_mill_shipment(self, shipment_id, headers):
        return self._request("GET", f"/yard/mill-shipments/{shipment_id}", headers=headers)

    def list_mill_shipments(self, headers, params=None):
        return self._request("GET", "/yard/mill-shipments", headers=headers, params=params)

    def settle_mill_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/yard/mill-shipments/{shipment_id}/settle", payload, headers)

    # ---- HedgePosition ----
    def create_hedge(self, payload, headers):
        return self._request("POST", "/yard/hedges", payload, headers)

    def get_hedge(self, hedge_id, headers):
        return self._request("GET", f"/yard/hedges/{hedge_id}", headers=headers)

    def list_hedges(self, headers, params=None):
        return self._request("GET", "/yard/hedges", headers=headers, params=params)

    def close_hedge(self, hedge_id, headers):
        return self._request("POST", f"/yard/hedges/{hedge_id}/close", {}, headers)

    # ---- TheftReport ----
    def get_theft_report(self, report_id, headers):
        return self._request("GET", f"/yard/theft-reports/{report_id}", headers=headers)

    def list_theft_reports(self, headers, params=None):
        return self._request("GET", "/yard/theft-reports", headers=headers, params=params)

    def create_theft_report(self, payload, headers):
        return self._request("POST", "/yard/theft-reports", payload, headers)

    def clear_theft_report(self, report_id, headers):
        return self._request("POST", f"/yard/theft-reports/{report_id}/clear", {}, headers)


api_client = ApiClient()
