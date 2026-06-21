"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework's GenericApiClient; the base _request() handles
HTTP plumbing. Every method returns a raw requests.Response so tests can
assert status codes and envelope shape.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Section ----
    def create_section(self, payload, headers):
        return self._request("POST", "/sections", payload, headers)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/sections/{section_id}", headers=headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/sections", headers=headers, params=params)

    def list_section_seats(self, section_id, headers, params=None):
        return self._request("GET", f"/sections/{section_id}/seats", headers=headers, params=params)

    # ---- Seat ----
    def create_seat(self, payload, headers):
        return self._request("POST", "/seats", payload, headers)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"/seats/{seat_id}", headers=headers)

    def list_seats(self, headers, params=None):
        return self._request("GET", "/seats", headers=headers, params=params)

    # ---- Account ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", {}, headers)

    def list_account_subscriptions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/subscriptions", headers=headers, params=params)

    def grant_points(self, account_id, payload, headers):
        return self._request("POST", f"/_accounts/{account_id}/grant-points", payload, headers)

    # ---- SeasonPlan ----
    def create_season_plan(self, payload, headers):
        return self._request("POST", "/season-plans", payload, headers)

    def get_season_plan(self, plan_id, headers):
        return self._request("GET", f"/season-plans/{plan_id}", headers=headers)

    def list_season_plans(self, headers, params=None):
        return self._request("GET", "/season-plans", headers=headers, params=params)

    # ---- Subscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def activate_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/activate", {}, headers)

    def relocate_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/relocate", payload, headers)

    def relocate_confirm(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/relocate/confirm", payload, headers)

    def relocate_abort(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/relocate/abort", {}, headers)

    def offer_renewal(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/renewal/offer", {}, headers)

    def accept_renewal(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/renewal/accept", payload, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {}, headers)

    def list_subscription_seat_assignments(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/seat-assignments", headers=headers, params=params)

    def list_subscription_parking_addons(self, subscription_id, headers, params=None):
        return self._request("GET", f"/subscriptions/{subscription_id}/parking-addons", headers=headers, params=params)

    # ---- SeatAssignment ----
    def create_seat_assignment(self, payload, headers):
        return self._request("POST", "/seat-assignments", payload, headers)

    def get_seat_assignment(self, assignment_id, headers):
        return self._request("GET", f"/seat-assignments/{assignment_id}", headers=headers)

    def list_seat_assignments(self, headers, params=None):
        return self._request("GET", "/seat-assignments", headers=headers, params=params)

    # ---- PaymentPlan / Installment ----
    def create_payment_plan(self, payload, headers):
        return self._request("POST", "/payment-plans", payload, headers)

    def get_payment_plan(self, plan_id, headers):
        return self._request("GET", f"/payment-plans/{plan_id}", headers=headers)

    def list_payment_plans(self, headers, params=None):
        return self._request("GET", "/payment-plans", headers=headers, params=params)

    def list_payment_plan_installments(self, plan_id, headers, params=None):
        return self._request("GET", f"/payment-plans/{plan_id}/installments", headers=headers, params=params)

    def get_installment(self, installment_id, headers):
        return self._request("GET", f"/installments/{installment_id}", headers=headers)

    def pay_installment(self, plan_id, seq, headers):
        return self._request("POST", f"/payment-plans/{plan_id}/installments/{seq}/pay", {}, headers)

    def default_payment_plan(self, plan_id, headers):
        return self._request("POST", f"/payment-plans/{plan_id}/default", {}, headers)

    # ---- TicketTransfer ----
    def create_ticket_transfer(self, payload, headers):
        return self._request("POST", "/ticket-transfers", payload, headers)

    def get_ticket_transfer(self, transfer_id, headers):
        return self._request("GET", f"/ticket-transfers/{transfer_id}", headers=headers)

    def list_ticket_transfers(self, headers, params=None):
        return self._request("GET", "/ticket-transfers", headers=headers, params=params)

    def forward_ticket_transfer(self, transfer_id, headers):
        return self._request("POST", f"/ticket-transfers/{transfer_id}/forward", {}, headers)

    def list_ticket_transfer(self, transfer_id, headers):
        return self._request("POST", f"/ticket-transfers/{transfer_id}/list", {}, headers)

    def complete_sale(self, transfer_id, payload, headers):
        return self._request("POST", f"/ticket-transfers/{transfer_id}/complete-sale", payload, headers)

    def cancel_ticket_transfer(self, transfer_id, headers):
        return self._request("POST", f"/ticket-transfers/{transfer_id}/cancel", {}, headers)

    # ---- ParkingZone / ParkingAddOn ----
    def create_parking_zone(self, payload, headers):
        return self._request("POST", "/parking-zones", payload, headers)

    def get_parking_zone(self, zone_id, headers):
        return self._request("GET", f"/parking-zones/{zone_id}", headers=headers)

    def list_parking_zones(self, headers, params=None):
        return self._request("GET", "/parking-zones", headers=headers, params=params)

    def create_parking_addon(self, payload, headers):
        return self._request("POST", "/parking-addons", payload, headers)

    def get_parking_addon(self, addon_id, headers):
        return self._request("GET", f"/parking-addons/{addon_id}", headers=headers)

    def list_parking_addons(self, headers, params=None):
        return self._request("GET", "/parking-addons", headers=headers, params=params)


api_client = ApiClient()
