"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Subscription plans ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/subscription-plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/subscription-plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/subscription-plans", payload=params, headers=headers)

    # ---- Fleets ----
    def create_fleet(self, payload, headers):
        return self._request("POST", "/fleets", payload, headers)

    def get_fleet(self, fleet_id, headers):
        return self._request("GET", f"/fleets/{fleet_id}", headers=headers)

    def list_fleets(self, headers, params=None):
        return self._request("GET", "/fleets", payload=params, headers=headers)

    def list_fleet_vehicles(self, fleet_id, headers, params=None):
        return self._request("GET", f"/fleets/{fleet_id}/vehicles", payload=params, headers=headers)

    def get_fleet_utilization(self, fleet_id, headers, params=None):
        return self._request("GET", f"/fleets/{fleet_id}/utilization", payload=params, headers=headers)

    # ---- Vehicles ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", payload=params, headers=headers)

    def vehicle_maintenance(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/maintenance", {}, headers)

    def vehicle_maintenance_complete(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/maintenance-complete", {}, headers)

    # ---- Applicants ----
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def decide_eligibility(self, applicant_id, payload, headers):
        return self._request("POST", f"/applicants/{applicant_id}/decide-eligibility", payload, headers)

    # ---- Subscriptions ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/subscriptions/{sub_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", payload=params, headers=headers)

    def assign_vehicle(self, sub_id, payload, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/assign-vehicle", payload, headers)

    def activate_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/activate", {}, headers)

    def initiate_return(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/initiate-return", {}, headers)

    def early_cancel(self, sub_id, payload, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/early-cancel", payload, headers)

    def cancel_quote(self, sub_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{sub_id}/cancel-quote", payload=params, headers=headers)

    def mark_past_due(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/mark-past-due", {}, headers)

    def record_payment(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/record-payment", {}, headers)

    def list_subscription_billing_cycles(self, sub_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{sub_id}/billing-cycles", payload=params, headers=headers)

    def list_subscription_invoices(self, sub_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{sub_id}/invoices", payload=params, headers=headers)

    # ---- Billing cycles ----
    def get_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/billing-cycles/{cycle_id}", headers=headers)

    def list_billing_cycles(self, headers, params=None):
        return self._request("GET", "/billing-cycles", payload=params, headers=headers)

    def close_billing_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/billing-cycles/{cycle_id}/close", payload, headers)

    # ---- Invoices ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", payload=params, headers=headers)

    # ---- Swap requests ----
    def request_swap(self, sub_id, payload, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/swap-requests", payload, headers)

    def get_swap_request(self, swap_id, headers):
        return self._request("GET", f"/swap-requests/{swap_id}", headers=headers)

    def list_swap_requests(self, headers, params=None):
        return self._request("GET", "/swap-requests", payload=params, headers=headers)

    def approve_swap(self, swap_id, payload, headers):
        return self._request("POST", f"/swap-requests/{swap_id}/approve", payload, headers)

    def complete_swap(self, swap_id, headers):
        return self._request("POST", f"/swap-requests/{swap_id}/complete", {}, headers)

    def reject_swap(self, swap_id, headers):
        return self._request("POST", f"/swap-requests/{swap_id}/reject", {}, headers)

    # ---- Return inspections ----
    def create_return_inspection(self, payload, headers):
        return self._request("POST", "/return-inspections", payload, headers)

    def get_return_inspection(self, insp_id, headers):
        return self._request("GET", f"/return-inspections/{insp_id}", headers=headers)

    def list_return_inspections(self, headers, params=None):
        return self._request("GET", "/return-inspections", payload=params, headers=headers)

    def add_damage_line_item(self, insp_id, payload, headers):
        return self._request("POST", f"/return-inspections/{insp_id}/damage-line-items", payload, headers)

    def list_damage_line_items(self, insp_id, headers, params=None):
        return self._request("GET", f"/return-inspections/{insp_id}/damage-line-items", payload=params, headers=headers)

    def assess_inspection(self, insp_id, headers):
        return self._request("POST", f"/return-inspections/{insp_id}/assess", {}, headers)

    def settle_inspection(self, insp_id, headers):
        return self._request("POST", f"/return-inspections/{insp_id}/settle", {}, headers)

    # ---- Couriers ----
    def create_courier(self, payload, headers):
        return self._request("POST", "/couriers", payload, headers)

    def get_courier(self, courier_id, headers):
        return self._request("GET", f"/couriers/{courier_id}", headers=headers)

    def list_couriers(self, headers, params=None):
        return self._request("GET", "/couriers", payload=params, headers=headers)

    # ---- Delivery slots ----
    def create_delivery_slot(self, payload, headers):
        return self._request("POST", "/delivery-slots", payload, headers)

    def get_delivery_slot(self, slot_id, headers):
        return self._request("GET", f"/delivery-slots/{slot_id}", headers=headers)

    def list_delivery_slots(self, headers, params=None):
        return self._request("GET", "/delivery-slots", payload=params, headers=headers)


api_client = ApiClient()
