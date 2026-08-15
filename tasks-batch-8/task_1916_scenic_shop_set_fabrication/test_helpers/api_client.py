"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/scenic/_clock/set-current-utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- shops ---
    def create_shop(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/shops", payload, headers)

    def get_shop(self, shop_id: str, headers: Dict):
        return self._request("GET", f"/scenic/shops/{shop_id}", headers=headers)

    def get_shop_summary(self, shop_id: str, headers: Dict):
        return self._request("GET", f"/scenic/shops/{shop_id}/summary", headers=headers)

    def run_epoch(self, shop_id: str, headers: Dict):
        return self._request("POST", f"/scenic/shops/{shop_id}/run-epoch", {}, headers)

    # --- clients ---
    def create_client(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/clients", payload, headers)

    def list_clients(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/clients", headers=headers, params=params)

    def get_client(self, client_id: str, headers: Dict):
        return self._request("GET", f"/scenic/clients/{client_id}", headers=headers)

    # --- design packages ---
    def create_design_package(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/design-packages", payload, headers)

    def list_design_packages(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/design-packages", headers=headers, params=params)

    def get_design_package(self, package_id: str, headers: Dict):
        return self._request("GET", f"/scenic/design-packages/{package_id}", headers=headers)

    # --- takeoffs ---
    def create_takeoff(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/takeoffs", payload, headers)

    def list_takeoffs(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/takeoffs", headers=headers, params=params)

    def get_takeoff(self, takeoff_id: str, headers: Dict):
        return self._request("GET", f"/scenic/takeoffs/{takeoff_id}", headers=headers)

    # --- takeoff lines ---
    def create_takeoff_line(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/takeoff-lines", payload, headers)

    def list_takeoff_lines(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/takeoff-lines", headers=headers, params=params)

    def get_takeoff_line(self, line_id: str, headers: Dict):
        return self._request("GET", f"/scenic/takeoff-lines/{line_id}", headers=headers)

    def delete_takeoff_line(self, line_id: str, headers: Dict):
        return self._request("DELETE", f"/scenic/takeoff-lines/{line_id}", headers=headers)

    # --- bids ---
    def create_bid(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/bids", payload, headers)

    def list_bids(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/bids", headers=headers, params=params)

    def get_bid(self, bid_id: str, headers: Dict):
        return self._request("GET", f"/scenic/bids/{bid_id}", headers=headers)

    def submit_bid(self, bid_id: str, headers: Dict):
        return self._request("POST", f"/scenic/bids/{bid_id}/submit", {}, headers)

    def counter_bid(self, bid_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/scenic/bids/{bid_id}/counter", payload, headers)

    def revise_bid(self, bid_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/scenic/bids/{bid_id}/revise", payload, headers)

    def accept_bid(self, bid_id: str, headers: Dict):
        return self._request("POST", f"/scenic/bids/{bid_id}/accept", {}, headers)

    def reject_bid(self, bid_id: str, headers: Dict):
        return self._request("POST", f"/scenic/bids/{bid_id}/reject", {}, headers)

    def withdraw_bid(self, bid_id: str, headers: Dict):
        return self._request("POST", f"/scenic/bids/{bid_id}/withdraw", {}, headers)

    # --- productions ---
    def list_productions(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/productions", headers=headers, params=params)

    def get_production(self, production_id: str, headers: Dict):
        return self._request("GET", f"/scenic/productions/{production_id}", headers=headers)

    def start_build(self, production_id: str, headers: Dict):
        return self._request("POST", f"/scenic/productions/{production_id}/start-build", {}, headers)

    def complete_build(self, production_id: str, headers: Dict):
        return self._request("POST", f"/scenic/productions/{production_id}/complete-build", {}, headers)

    def load_in(self, production_id: str, headers: Dict):
        return self._request("POST", f"/scenic/productions/{production_id}/load-in", {}, headers)

    def strike(self, production_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/scenic/productions/{production_id}/strike", payload, headers)

    def close_production(self, production_id: str, headers: Dict):
        return self._request("POST", f"/scenic/productions/{production_id}/close", {}, headers)

    # --- engineering reviews ---
    def create_engineering_review(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/engineering-reviews", payload, headers)

    def list_engineering_reviews(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/engineering-reviews", headers=headers, params=params)

    def get_engineering_review(self, review_id: str, headers: Dict):
        return self._request("GET", f"/scenic/engineering-reviews/{review_id}", headers=headers)

    def approve_engineering_review(self, review_id: str, headers: Dict):
        return self._request("POST", f"/scenic/engineering-reviews/{review_id}/approve", {}, headers)

    def request_revision_engineering_review(self, review_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/scenic/engineering-reviews/{review_id}/request-revision", payload, headers)

    def resubmit_engineering_review(self, review_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/scenic/engineering-reviews/{review_id}/resubmit", payload, headers)

    # --- finish samples ---
    def create_finish_sample(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/finish-samples", payload, headers)

    def list_finish_samples(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/finish-samples", headers=headers, params=params)

    def get_finish_sample(self, sample_id: str, headers: Dict):
        return self._request("GET", f"/scenic/finish-samples/{sample_id}", headers=headers)

    def approve_finish_sample(self, sample_id: str, headers: Dict):
        return self._request("POST", f"/scenic/finish-samples/{sample_id}/approve", {}, headers)

    def reject_finish_sample(self, sample_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/scenic/finish-samples/{sample_id}/reject", payload, headers)

    def resubmit_finish_sample(self, sample_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/scenic/finish-samples/{sample_id}/resubmit", payload, headers)

    # --- change orders ---
    def create_change_order(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/change-orders", payload, headers)

    def list_change_orders(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/change-orders", headers=headers, params=params)

    def get_change_order(self, co_id: str, headers: Dict):
        return self._request("GET", f"/scenic/change-orders/{co_id}", headers=headers)

    def approve_change_order(self, co_id: str, headers: Dict):
        return self._request("POST", f"/scenic/change-orders/{co_id}/approve", {}, headers)

    def reject_change_order(self, co_id: str, headers: Dict):
        return self._request("POST", f"/scenic/change-orders/{co_id}/reject", {}, headers)

    def withdraw_change_order(self, co_id: str, headers: Dict):
        return self._request("POST", f"/scenic/change-orders/{co_id}/withdraw", {}, headers)

    # --- bay reservations ---
    def create_bay_reservation(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/bay-reservations", payload, headers)

    def list_bay_reservations(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/bay-reservations", headers=headers, params=params)

    def get_bay_reservation(self, reservation_id: str, headers: Dict):
        return self._request("GET", f"/scenic/bay-reservations/{reservation_id}", headers=headers)

    def delete_bay_reservation(self, reservation_id: str, headers: Dict):
        return self._request("DELETE", f"/scenic/bay-reservations/{reservation_id}", headers=headers)

    # --- stock items ---
    def create_stock_item(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/stock-items", payload, headers)

    def list_stock_items(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/stock-items", headers=headers, params=params)

    def get_stock_item(self, item_id: str, headers: Dict):
        return self._request("GET", f"/scenic/stock-items/{item_id}", headers=headers)

    def adjust_stock_item(self, item_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/scenic/stock-items/{item_id}/adjust", payload, headers)

    # --- transport plans ---
    def create_transport_plan(self, payload: Dict, headers: Dict):
        return self._request("POST", "/scenic/transport-plans", payload, headers)

    def list_transport_plans(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/scenic/transport-plans", headers=headers, params=params)

    def get_transport_plan(self, plan_id: str, headers: Dict):
        return self._request("GET", f"/scenic/transport-plans/{plan_id}", headers=headers)

    def confirm_transport_plan(self, plan_id: str, headers: Dict):
        return self._request("POST", f"/scenic/transport-plans/{plan_id}/confirm", {}, headers)

    def cancel_transport_plan(self, plan_id: str, headers: Dict):
        return self._request("POST", f"/scenic/transport-plans/{plan_id}/cancel", {}, headers)


api_client = ApiClient()
