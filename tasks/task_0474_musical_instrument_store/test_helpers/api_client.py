"""API client: one method per endpoint defined in the Musical Instrument Store PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Customer ------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    # --- InventoryUnit -------------------------------------------------------
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def reserve_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/reserve", payload, headers)

    def release_unit(self, unit_id, headers):
        return self._request("POST", f"/units/{unit_id}/release", headers=headers)

    # --- RentalAgreement -----------------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", "/rental-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/rental-agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/rental-agreements", headers=headers, params=params)

    def post_rent_payment(self, agreement_id, payload, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/payments", payload, headers)

    def list_agreement_payments(self, agreement_id, headers, params=None):
        return self._request("GET", f"/rental-agreements/{agreement_id}/payments", headers=headers, params=params)

    def advance_cycle(self, agreement_id, payload, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/advance-cycle", payload, headers)

    def buyout_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/buyout", payload, headers)

    def return_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/return", headers=headers)

    def repossess_agreement(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/repossess", headers=headers)

    # --- LayawayPlan ---------------------------------------------------------
    def create_layaway(self, payload, headers):
        return self._request("POST", "/layaway-plans", payload, headers)

    def get_layaway(self, plan_id, headers):
        return self._request("GET", f"/layaway-plans/{plan_id}", headers=headers)

    def list_layaways(self, headers, params=None):
        return self._request("GET", "/layaway-plans", headers=headers, params=params)

    def post_layaway_payment(self, plan_id, payload, headers):
        return self._request("POST", f"/layaway-plans/{plan_id}/payments", payload, headers)

    def list_layaway_payments(self, plan_id, headers, params=None):
        return self._request("GET", f"/layaway-plans/{plan_id}/payments", headers=headers, params=params)

    def complete_layaway(self, plan_id, headers):
        return self._request("POST", f"/layaway-plans/{plan_id}/complete", headers=headers)

    def cancel_layaway(self, plan_id, headers):
        return self._request("POST", f"/layaway-plans/{plan_id}/cancel", headers=headers)

    # --- RepairTicket --------------------------------------------------------
    def create_ticket(self, payload, headers):
        return self._request("POST", "/repair-tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/repair-tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/repair-tickets", headers=headers, params=params)

    def claim_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/claim", headers=headers)

    def await_parts_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/await-parts", headers=headers)

    def resume_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/resume", headers=headers)

    def ready_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/ready", headers=headers)

    def close_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/close", headers=headers)

    def cancel_ticket(self, ticket_id, headers):
        return self._request("POST", f"/repair-tickets/{ticket_id}/cancel", headers=headers)

    # --- ConsignmentListing --------------------------------------------------
    def create_consignment(self, payload, headers):
        return self._request("POST", "/consignment-listings", payload, headers)

    def get_consignment(self, listing_id, headers):
        return self._request("GET", f"/consignment-listings/{listing_id}", headers=headers)

    def list_consignments(self, headers, params=None):
        return self._request("GET", "/consignment-listings", headers=headers, params=params)

    def sell_consignment(self, listing_id, headers):
        return self._request("POST", f"/consignment-listings/{listing_id}/sell", headers=headers)

    def withdraw_consignment(self, listing_id, headers):
        return self._request("POST", f"/consignment-listings/{listing_id}/withdraw", headers=headers)

    # --- TradeIn -------------------------------------------------------------
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/trade-ins", payload, headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def accept_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/accept", headers=headers)

    def decline_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/decline", headers=headers)

    # --- FinancingApplication ------------------------------------------------
    def create_financing(self, payload, headers):
        return self._request("POST", "/financing-applications", payload, headers)

    def get_financing(self, application_id, headers):
        return self._request("GET", f"/financing-applications/{application_id}", headers=headers)

    def list_financings(self, headers, params=None):
        return self._request("GET", "/financing-applications", headers=headers, params=params)

    def approve_financing(self, application_id, headers):
        return self._request("POST", f"/financing-applications/{application_id}/approve", headers=headers)

    def deny_financing(self, application_id, headers):
        return self._request("POST", f"/financing-applications/{application_id}/deny", headers=headers)

    def cancel_financing(self, application_id, headers):
        return self._request("POST", f"/financing-applications/{application_id}/cancel", headers=headers)

    # --- SpecialOrder --------------------------------------------------------
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, order_id, headers):
        return self._request("GET", f"/special-orders/{order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def pay_deposit(self, order_id, payload, headers):
        return self._request("POST", f"/special-orders/{order_id}/pay-deposit", payload, headers)

    def place_special_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/place", headers=headers)

    def receive_special_order(self, order_id, payload, headers):
        return self._request("POST", f"/special-orders/{order_id}/receive", payload, headers)

    def fulfill_special_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/fulfill", headers=headers)

    def cancel_special_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/cancel", headers=headers)

    # --- LessonEnrollment ----------------------------------------------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/lesson-enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/lesson-enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/lesson-enrollments", headers=headers, params=params)

    def pause_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/lesson-enrollments/{enrollment_id}/pause", headers=headers)

    def resume_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/lesson-enrollments/{enrollment_id}/resume", headers=headers)

    def end_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/lesson-enrollments/{enrollment_id}/end", headers=headers)


api_client = ApiClient()
