"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- ServiceZone ----
    def create_service_zone(self, payload, headers):
        return self._request("POST", "/service-zones", payload, headers)

    def list_service_zones(self, headers, params=None):
        return self._request("GET", "/service-zones", headers=headers, params=params)

    def get_service_zone(self, zone_id, headers):
        return self._request("GET", f"/service-zones/{zone_id}", headers=headers)

    def update_service_zone(self, zone_id, payload, headers):
        return self._request("PATCH", f"/service-zones/{zone_id}", payload, headers)

    # ---- Household ----
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    # ---- Subscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def pay_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/pay", payload, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {}, headers)

    def cure_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cure", payload, headers)

    # ---- Cart ----
    def create_cart(self, payload, headers):
        return self._request("POST", "/carts", payload, headers)

    def list_carts(self, headers, params=None):
        return self._request("GET", "/carts", headers=headers, params=params)

    def get_cart(self, cart_id, headers):
        return self._request("GET", f"/carts/{cart_id}", headers=headers)

    def deliver_cart(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/deliver", {}, headers)

    # ---- CollectionRoute ----
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def publish_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/publish", {}, headers)

    # ---- PickupTicket ----
    def create_pickup_ticket(self, payload, headers):
        return self._request("POST", "/pickup-tickets", payload, headers)

    def list_pickup_tickets(self, headers, params=None):
        return self._request("GET", "/pickup-tickets", headers=headers, params=params)

    def get_pickup_ticket(self, ticket_id, headers):
        return self._request("GET", f"/pickup-tickets/{ticket_id}", headers=headers)

    def complete_pickup_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/pickup-tickets/{ticket_id}/complete", payload, headers)

    def report_missed_pickup_ticket(self, ticket_id, headers):
        return self._request("POST", f"/pickup-tickets/{ticket_id}/report-missed", {}, headers)

    def validate_missed_pickup_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/pickup-tickets/{ticket_id}/validate-missed", payload, headers)

    # ---- ContaminationInspection ----
    def create_contamination_inspection(self, payload, headers):
        return self._request("POST", "/contamination-inspections", payload, headers)

    def list_contamination_inspections(self, headers, params=None):
        return self._request("GET", "/contamination-inspections", headers=headers, params=params)

    def get_contamination_inspection(self, inspection_id, headers):
        return self._request("GET", f"/contamination-inspections/{inspection_id}", headers=headers)

    # ---- SurgeEvent ----
    def create_surge_event(self, payload, headers):
        return self._request("POST", "/surge-events", payload, headers)

    def list_surge_events(self, headers, params=None):
        return self._request("GET", "/surge-events", headers=headers, params=params)

    def get_surge_event(self, event_id, headers):
        return self._request("GET", f"/surge-events/{event_id}", headers=headers)

    # ---- SurgeBooking ----
    def create_surge_booking(self, payload, headers):
        return self._request("POST", "/surge-bookings", payload, headers)

    def list_surge_bookings(self, headers, params=None):
        return self._request("GET", "/surge-bookings", headers=headers, params=params)

    def get_surge_booking(self, booking_id, headers):
        return self._request("GET", f"/surge-bookings/{booking_id}", headers=headers)

    def cancel_surge_booking(self, booking_id, headers):
        return self._request("POST", f"/surge-bookings/{booking_id}/cancel", {}, headers)

    # ---- ProcessingFacility ----
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def update_facility(self, facility_id, payload, headers):
        return self._request("PATCH", f"/facilities/{facility_id}", payload, headers)

    # ---- FacilityDelivery ----
    def create_facility_delivery(self, payload, headers):
        return self._request("POST", "/facility-deliveries", payload, headers)

    def list_facility_deliveries(self, headers, params=None):
        return self._request("GET", "/facility-deliveries", headers=headers, params=params)

    def get_facility_delivery(self, delivery_id, headers):
        return self._request("GET", f"/facility-deliveries/{delivery_id}", headers=headers)

    def receive_facility_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/facility-deliveries/{delivery_id}/receive", payload, headers)

    # ---- CompostGivebackEvent ----
    def create_giveback_event(self, payload, headers):
        return self._request("POST", "/giveback-events", payload, headers)

    def list_giveback_events(self, headers, params=None):
        return self._request("GET", "/giveback-events", headers=headers, params=params)

    def get_giveback_event(self, event_id, headers):
        return self._request("GET", f"/giveback-events/{event_id}", headers=headers)

    # ---- CompostClaim ----
    def create_compost_claim(self, payload, headers):
        return self._request("POST", "/compost-claims", payload, headers)

    def list_compost_claims(self, headers, params=None):
        return self._request("GET", "/compost-claims", headers=headers, params=params)

    def get_compost_claim(self, claim_id, headers):
        return self._request("GET", f"/compost-claims/{claim_id}", headers=headers)

    def void_compost_claim(self, claim_id, headers):
        return self._request("POST", f"/compost-claims/{claim_id}/void", {}, headers)

    # ---- ServiceCredit ----
    def list_service_credits(self, headers, params=None):
        return self._request("GET", "/service-credits", headers=headers, params=params)

    def get_service_credit(self, credit_id, headers):
        return self._request("GET", f"/service-credits/{credit_id}", headers=headers)

    def approve_service_credit(self, credit_id, headers):
        return self._request("POST", f"/service-credits/{credit_id}/approve", {}, headers)

    def void_service_credit(self, credit_id, headers):
        return self._request("POST", f"/service-credits/{credit_id}/void", {}, headers)

    # ---- OutreachCampaign ----
    def create_outreach_campaign(self, payload, headers):
        return self._request("POST", "/outreach-campaigns", payload, headers)

    def list_outreach_campaigns(self, headers, params=None):
        return self._request("GET", "/outreach-campaigns", headers=headers, params=params)

    def get_outreach_campaign(self, campaign_id, headers):
        return self._request("GET", f"/outreach-campaigns/{campaign_id}", headers=headers)

    def launch_outreach_campaign(self, campaign_id, headers):
        return self._request("POST", f"/outreach-campaigns/{campaign_id}/launch", {}, headers)

    def update_outreach_campaign(self, campaign_id, payload, headers):
        return self._request("PATCH", f"/outreach-campaigns/{campaign_id}", payload, headers)


api_client = ApiClient()
