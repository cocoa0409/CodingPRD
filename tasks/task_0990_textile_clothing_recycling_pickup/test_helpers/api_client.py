"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- ServiceZone ---
    def create_zone(self, payload, headers):
        return self._request("POST", "/service-zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/service-zones/{zone_id}", headers=headers)

    def replace_charity_split(self, zone_id, payload, headers):
        return self._request("PUT", f"/service-zones/{zone_id}/charity-split", payload, headers)

    def list_zone_residents(self, zone_id, headers, params=None):
        return self._request("GET", f"/service-zones/{zone_id}/residents", headers=headers, params=params)

    def list_zone_dropboxes(self, zone_id, headers, params=None):
        return self._request("GET", f"/service-zones/{zone_id}/dropboxes", headers=headers, params=params)

    def list_zone_sponsor_funds(self, zone_id, headers, params=None):
        return self._request("GET", f"/service-zones/{zone_id}/sponsor-funds", headers=headers, params=params)

    def list_zone_reporting_periods(self, zone_id, headers, params=None):
        return self._request("GET", f"/service-zones/{zone_id}/reporting-periods", headers=headers, params=params)

    def create_reporting_period(self, zone_id, payload, headers):
        return self._request("POST", f"/service-zones/{zone_id}/reporting-periods", payload, headers)

    # --- Resident ---
    def create_resident(self, payload, headers):
        return self._request("POST", "/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/residents/{resident_id}", headers=headers)

    def reactivate_resident(self, resident_id, headers):
        return self._request("POST", f"/residents/{resident_id}/reactivate", {}, headers)

    def list_resident_bag_kits(self, resident_id, headers, params=None):
        return self._request("GET", f"/residents/{resident_id}/bag-kits", headers=headers, params=params)

    def order_bag_kit(self, resident_id, payload, headers):
        return self._request("POST", f"/residents/{resident_id}/bag-kits", payload, headers)

    def list_resident_pickup_requests(self, resident_id, headers, params=None):
        return self._request("GET", f"/residents/{resident_id}/pickup-requests", headers=headers, params=params)

    # --- BagKit ---
    def dispatch_bag_kit(self, kit_id, headers):
        return self._request("POST", f"/bag-kits/{kit_id}/dispatch", {}, headers)

    def deliver_bag_kit(self, kit_id, headers):
        return self._request("POST", f"/bag-kits/{kit_id}/deliver", {}, headers)

    def retire_bag_kit(self, kit_id, headers):
        return self._request("POST", f"/bag-kits/{kit_id}/retire", {}, headers)

    # --- PickupRequest ---
    def create_pickup_request(self, payload, headers):
        return self._request("POST", "/pickup-requests", payload, headers)

    def get_pickup_request(self, pickup_id, headers):
        return self._request("GET", f"/pickup-requests/{pickup_id}", headers=headers)

    def reschedule_pickup(self, pickup_id, payload, headers):
        return self._request("POST", f"/pickup-requests/{pickup_id}/reschedule", payload, headers)

    def cancel_pickup(self, pickup_id, headers):
        return self._request("POST", f"/pickup-requests/{pickup_id}/cancel", {}, headers)

    def rebook_pickup(self, pickup_id, payload, headers):
        return self._request("POST", f"/pickup-requests/{pickup_id}/rebook", payload, headers)

    def route_pickup(self, pickup_id, payload, headers):
        return self._request("POST", f"/pickup-requests/{pickup_id}/route", payload, headers)

    def mark_collected(self, pickup_id, payload, headers):
        return self._request("POST", f"/pickup-requests/{pickup_id}/mark-collected", payload, headers)

    def mark_no_show(self, pickup_id, headers):
        return self._request("POST", f"/pickup-requests/{pickup_id}/mark-no-show", {}, headers)

    def list_pickup_weight_tickets(self, pickup_id, headers, params=None):
        return self._request("GET", f"/pickup-requests/{pickup_id}/weight-tickets", headers=headers, params=params)

    # --- Partner & RoutingAssignment ---
    def create_partner(self, payload, headers):
        return self._request("POST", "/partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"/partners/{partner_id}", headers=headers)

    def remediate_partner(self, partner_id, headers):
        return self._request("POST", f"/partners/{partner_id}/remediate", {}, headers)

    def list_partner_routing_assignments(self, partner_id, headers, params=None):
        return self._request("GET", f"/partners/{partner_id}/routing-assignments", headers=headers, params=params)

    def create_routing_assignment(self, ticket_id, headers):
        return self._request("POST", f"/weight-tickets/{ticket_id}/routing-assignments", {}, headers)

    def list_ticket_routing_assignments(self, ticket_id, headers, params=None):
        return self._request("GET", f"/weight-tickets/{ticket_id}/routing-assignments", headers=headers, params=params)

    def accept_routing_assignment(self, assignment_id, headers):
        return self._request("POST", f"/routing-assignments/{assignment_id}/accept", {}, headers)

    def decline_routing_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/routing-assignments/{assignment_id}/decline", payload, headers)

    def complete_routing_assignment(self, assignment_id, headers):
        return self._request("POST", f"/routing-assignments/{assignment_id}/complete", {}, headers)

    # --- DropBox & FillReading ---
    def create_dropbox(self, payload, headers):
        return self._request("POST", "/dropboxes", payload, headers)

    def get_dropbox(self, dropbox_id, headers):
        return self._request("GET", f"/dropboxes/{dropbox_id}", headers=headers)

    def create_fill_reading(self, dropbox_id, payload, headers):
        return self._request("POST", f"/dropboxes/{dropbox_id}/fill-readings", payload, headers)

    def list_fill_readings(self, dropbox_id, headers, params=None):
        return self._request("GET", f"/dropboxes/{dropbox_id}/fill-readings", headers=headers, params=params)

    def create_dropbox_collection(self, dropbox_id, payload, headers):
        return self._request("POST", f"/dropboxes/{dropbox_id}/collections", payload, headers)

    def list_dropbox_weight_tickets(self, dropbox_id, headers, params=None):
        return self._request("GET", f"/dropboxes/{dropbox_id}/weight-tickets", headers=headers, params=params)

    # --- WeightTicket ---
    def get_weight_ticket(self, ticket_id, headers):
        return self._request("GET", f"/weight-tickets/{ticket_id}", headers=headers)

    def certify_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/weight-tickets/{ticket_id}/certify", payload, headers)

    def void_ticket(self, ticket_id, headers):
        return self._request("POST", f"/weight-tickets/{ticket_id}/void", {}, headers)

    # --- ContaminationReport ---
    def create_contamination_report(self, ticket_id, payload, headers):
        return self._request("POST", f"/weight-tickets/{ticket_id}/contamination-reports", payload, headers)

    def list_contamination_reports(self, ticket_id, headers, params=None):
        return self._request("GET", f"/weight-tickets/{ticket_id}/contamination-reports", headers=headers, params=params)

    def adjudicate_report(self, report_id, payload, headers):
        return self._request("POST", f"/contamination-reports/{report_id}/adjudicate", payload, headers)

    def dismiss_report(self, report_id, headers):
        return self._request("POST", f"/contamination-reports/{report_id}/dismiss", {}, headers)

    # --- DiversionCredit ---
    def create_diversion_credit(self, ticket_id, headers):
        return self._request("POST", f"/weight-tickets/{ticket_id}/diversion-credits", {}, headers)

    def list_ticket_diversion_credits(self, ticket_id, headers, params=None):
        return self._request("GET", f"/weight-tickets/{ticket_id}/diversion-credits", headers=headers, params=params)

    def get_diversion_credit(self, credit_id, headers):
        return self._request("GET", f"/diversion-credits/{credit_id}", headers=headers)

    def finalize_credit(self, credit_id, headers):
        return self._request("POST", f"/diversion-credits/{credit_id}/finalize", {}, headers)

    def dispute_credit(self, credit_id, payload, headers):
        return self._request("POST", f"/diversion-credits/{credit_id}/dispute", payload, headers)

    def void_credit(self, credit_id, headers):
        return self._request("POST", f"/diversion-credits/{credit_id}/void", {}, headers)

    def settle_credit(self, credit_id, headers):
        return self._request("POST", f"/diversion-credits/{credit_id}/settle", {}, headers)

    # --- SponsorFund ---
    def create_sponsor_fund(self, payload, headers):
        return self._request("POST", "/sponsor-funds", payload, headers)

    def get_sponsor_fund(self, fund_id, headers):
        return self._request("GET", f"/sponsor-funds/{fund_id}", headers=headers)

    def topup_fund(self, fund_id, payload, headers):
        return self._request("POST", f"/sponsor-funds/{fund_id}/topups", payload, headers)

    def close_fund(self, fund_id, headers):
        return self._request("POST", f"/sponsor-funds/{fund_id}/close", {}, headers)

    def list_fund_diversion_credits(self, fund_id, headers, params=None):
        return self._request("GET", f"/sponsor-funds/{fund_id}/diversion-credits", headers=headers, params=params)

    # --- Charity ---
    def create_charity(self, payload, headers):
        return self._request("POST", "/charities", payload, headers)

    def get_charity(self, charity_id, headers):
        return self._request("GET", f"/charities/{charity_id}", headers=headers)

    def get_charity_allocations(self, charity_id, headers):
        return self._request("GET", f"/charities/{charity_id}/allocations", headers=headers)

    # --- ReportingPeriod ---
    def get_reporting_period(self, period_id, headers):
        return self._request("GET", f"/reporting-periods/{period_id}", headers=headers)

    def close_reporting_period(self, period_id, headers):
        return self._request("POST", f"/reporting-periods/{period_id}/close", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
