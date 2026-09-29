"""API client: one method per endpoint defined in the PRD."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/fleet"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    # ---------------- stores ----------------
    def create_store(self, payload, headers):
        return self._request("POST", f"{BASE}/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"{BASE}/stores/{store_id}", headers=headers)

    def list_stores(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/stores", headers=headers, params=params)

    def set_store_status(self, store_id, payload, headers):
        return self._request("POST", f"{BASE}/stores/{store_id}/status", payload, headers)

    # ---------------- domiciles ----------------
    def create_domicile(self, payload, headers):
        return self._request("POST", f"{BASE}/domiciles", payload, headers)

    def get_domicile(self, domicile_id, headers):
        return self._request("GET", f"{BASE}/domiciles/{domicile_id}", headers=headers)

    def list_domiciles(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/domiciles", headers=headers, params=params)

    def get_cost_benchmark(self, domicile_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/domiciles/{domicile_id}/cost-benchmark", headers=headers,
            params=params,
        )

    # ---------------- driver pay plans ----------------
    def create_pay_plan(self, payload, headers):
        return self._request("POST", f"{BASE}/driver-pay-plans", payload, headers)

    def get_pay_plan(self, pay_plan_id, headers):
        return self._request("GET", f"{BASE}/driver-pay-plans/{pay_plan_id}", headers=headers)

    def list_pay_plans(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/driver-pay-plans", headers=headers, params=params)

    def patch_pay_plan(self, pay_plan_id, payload, headers):
        return self._request("PATCH", f"{BASE}/driver-pay-plans/{pay_plan_id}", payload, headers)

    # ---------------- drivers ----------------
    def create_driver(self, payload, headers):
        return self._request("POST", f"{BASE}/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"{BASE}/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/drivers", headers=headers, params=params)

    def assign_pay_plan(self, driver_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/drivers/{driver_id}/pay-plan-assignments", payload, headers
        )

    def hos_reset(self, driver_id, payload, headers):
        return self._request("POST", f"{BASE}/drivers/{driver_id}/hos-reset", payload, headers)

    def adjust_duty_log(self, driver_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/drivers/{driver_id}/duty-log-adjustments", payload, headers
        )

    def terminate_driver(self, driver_id, payload, headers):
        return self._request("POST", f"{BASE}/drivers/{driver_id}/termination", payload, headers)

    # ---------------- tractors ----------------
    def create_tractor(self, payload, headers):
        return self._request("POST", f"{BASE}/tractors", payload, headers)

    def get_tractor(self, tractor_id, headers):
        return self._request("GET", f"{BASE}/tractors/{tractor_id}", headers=headers)

    def list_tractors(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/tractors", headers=headers, params=params)

    def patch_tractor(self, tractor_id, payload, headers):
        return self._request("PATCH", f"{BASE}/tractors/{tractor_id}", payload, headers)

    # ---------------- trailers ----------------
    def create_trailer(self, payload, headers):
        return self._request("POST", f"{BASE}/trailers", payload, headers)

    def get_trailer(self, trailer_id, headers):
        return self._request("GET", f"{BASE}/trailers/{trailer_id}", headers=headers)

    def list_trailers(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/trailers", headers=headers, params=params)

    # ---------------- replenishment orders ----------------
    def create_order(self, payload, headers):
        return self._request("POST", f"{BASE}/replenishment-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{BASE}/replenishment-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/replenishment-orders", headers=headers, params=params)

    def cancel_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/replenishment-orders/{order_id}/cancel", payload, headers
        )

    # ---------------- trips ----------------
    def create_trip(self, payload, headers):
        return self._request("POST", f"{BASE}/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"{BASE}/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/trips", headers=headers, params=params)

    def add_trip_stop(self, trip_id, payload, headers):
        return self._request("POST", f"{BASE}/trips/{trip_id}/stops", payload, headers)

    def list_stops_of_trip(self, trip_id, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/trips/{trip_id}/stops", headers=headers, params=params)

    def delete_trip_stop(self, trip_id, trip_stop_id, headers):
        return self._request(
            "DELETE", f"{BASE}/trips/{trip_id}/stops/{trip_stop_id}", headers=headers
        )

    def plan_trip(self, trip_id, headers, payload=None):
        return self._request("POST", f"{BASE}/trips/{trip_id}/plan", payload or {}, headers)

    def assign_trip_resources(self, trip_id, payload, headers):
        return self._request("POST", f"{BASE}/trips/{trip_id}/assignments", payload, headers)

    def link_backhaul_offer(self, trip_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/trips/{trip_id}/backhaul-assignments", payload, headers
        )

    def dispatch_trip(self, trip_id, headers, payload=None):
        return self._request("POST", f"{BASE}/trips/{trip_id}/dispatch", payload or {}, headers)

    def complete_trip(self, trip_id, payload, headers):
        return self._request("POST", f"{BASE}/trips/{trip_id}/complete", payload, headers)

    def cancel_trip(self, trip_id, payload, headers):
        return self._request("POST", f"{BASE}/trips/{trip_id}/cancel", payload, headers)

    def get_pay_preview(self, trip_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/trips/{trip_id}/pay-preview", headers=headers, params=params
        )

    def re_accrue_trip(self, trip_id, payload, headers):
        return self._request("POST", f"{BASE}/trips/{trip_id}/re-accrue", payload, headers)

    def dispute_settlement(self, trip_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/trips/{trip_id}/settlement-dispute", payload, headers
        )

    # ---------------- trip stops ----------------
    def get_trip_stop(self, trip_stop_id, headers):
        return self._request("GET", f"{BASE}/trip-stops/{trip_stop_id}", headers=headers)

    def list_trip_stops(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/trip-stops", headers=headers, params=params)

    def arrive_at_stop(self, trip_stop_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/trip-stops/{trip_stop_id}/arrive", payload or {}, headers
        )

    def complete_stop(self, trip_stop_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/trip-stops/{trip_stop_id}/complete", payload, headers
        )

    # ---------------- backhaul offers ----------------
    def create_backhaul_offer(self, payload, headers):
        return self._request("POST", f"{BASE}/backhaul-offers", payload, headers)

    def get_backhaul_offer(self, offer_id, headers):
        return self._request("GET", f"{BASE}/backhaul-offers/{offer_id}", headers=headers)

    def list_backhaul_offers(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/backhaul-offers", headers=headers, params=params)

    def submit_offer_review(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/backhaul-offers/{offer_id}/submit-review", payload or {}, headers
        )

    def revise_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/backhaul-offers/{offer_id}/revise", payload, headers
        )

    def accept_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/backhaul-offers/{offer_id}/accept", payload or {}, headers
        )

    def reject_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/backhaul-offers/{offer_id}/reject", payload, headers
        )

    def withdraw_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/backhaul-offers/{offer_id}/withdraw", payload or {}, headers
        )

    def run_offer_expiration_sweep(self, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/backhaul-offers/expiration-sweep", payload or {}, headers
        )

    # ---------------- maintenance work orders ----------------
    def create_work_order(self, payload, headers):
        return self._request("POST", f"{BASE}/maintenance-work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request(
            "GET", f"{BASE}/maintenance-work-orders/{work_order_id}", headers=headers
        )

    def list_work_orders(self, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/maintenance-work-orders", headers=headers, params=params
        )

    def defer_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/maintenance-work-orders/{work_order_id}/defer", payload, headers
        )

    def reschedule_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/maintenance-work-orders/{work_order_id}/reschedule", payload, headers
        )

    def start_work_order(self, work_order_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/maintenance-work-orders/{work_order_id}/start", payload or {}, headers
        )

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/maintenance-work-orders/{work_order_id}/complete", payload, headers
        )

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/maintenance-work-orders/{work_order_id}/cancel", payload, headers
        )

    # ---------------- pay statements ----------------
    def get_pay_statement(self, statement_id, headers):
        return self._request("GET", f"{BASE}/pay-statements/{statement_id}", headers=headers)

    def list_pay_statements(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/pay-statements", headers=headers, params=params)

    def settle_pay_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/pay-statements/{statement_id}/settle", payload, headers
        )

    def reverse_pay_statement(self, statement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/pay-statements/{statement_id}/reverse", payload, headers
        )

    # ---------------- route postings ----------------
    def create_route_posting(self, payload, headers):
        return self._request("POST", f"{BASE}/route-postings", payload, headers)

    def get_route_posting(self, posting_id, headers):
        return self._request("GET", f"{BASE}/route-postings/{posting_id}", headers=headers)

    def list_route_postings(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/route-postings", headers=headers, params=params)

    def award_route_posting(self, posting_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/route-postings/{posting_id}/award", payload or {}, headers
        )

    def cancel_route_posting(self, posting_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/route-postings/{posting_id}/cancel", payload, headers
        )

    # ---------------- route bids ----------------
    def create_route_bid(self, payload, headers):
        return self._request("POST", f"{BASE}/route-bids", payload, headers)

    def get_route_bid(self, bid_id, headers):
        return self._request("GET", f"{BASE}/route-bids/{bid_id}", headers=headers)

    def list_route_bids(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/route-bids", headers=headers, params=params)

    def withdraw_route_bid(self, bid_id, headers, payload=None):
        return self._request(
            "POST", f"{BASE}/route-bids/{bid_id}/withdraw", payload or {}, headers
        )

    # ---------------- telematics events ----------------
    def create_telematics_event(self, payload, headers):
        return self._request("POST", f"{BASE}/telematics-events", payload, headers)

    def get_telematics_event(self, event_id, headers):
        return self._request("GET", f"{BASE}/telematics-events/{event_id}", headers=headers)

    def list_telematics_events(self, headers, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/telematics-events", headers=headers, params=params)

    def coach_telematics_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/telematics-events/{event_id}/coach", payload, headers
        )


api_client = ApiClient()
