"""API client: one method per PRD-defined endpoint."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Homeowners
    # ------------------------------------------------------------------
    def create_homeowner(self, payload, headers):
        return self._request("POST", "/homeowners", payload, headers)

    def get_homeowner(self, homeowner_id, headers):
        return self._request("GET", f"/homeowners/{homeowner_id}", headers=headers)

    def list_homeowner_properties(self, homeowner_id, headers, params=None):
        return self._request("GET", f"/homeowners/{homeowner_id}/properties",
                             headers=headers, params=params)

    def create_autopay_mandate(self, homeowner_id, payload, headers):
        return self._request("POST", f"/homeowners/{homeowner_id}/autopay-mandate",
                             payload, headers)

    def cancel_autopay_mandate(self, homeowner_id, headers):
        return self._request("DELETE", f"/homeowners/{homeowner_id}/autopay-mandate",
                             headers=headers)

    def list_autopay_mandates(self, homeowner_id, headers, params=None):
        return self._request("GET", f"/homeowners/{homeowner_id}/autopay-mandate",
                             headers=headers, params=params)

    def list_homeowner_arc_requests(self, homeowner_id, headers, params=None):
        return self._request("GET", f"/homeowners/{homeowner_id}/arc-requests",
                             headers=headers, params=params)

    def list_homeowner_arc_reviews(self, homeowner_id, headers, params=None):
        return self._request("GET", f"/homeowners/{homeowner_id}/arc-reviews",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_property_assessments(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/assessments",
                             headers=headers, params=params)

    def list_property_arc_requests(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/arc-requests",
                             headers=headers, params=params)

    def list_property_violations(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/violations",
                             headers=headers, params=params)

    def list_property_work_orders(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/work-orders",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Assessments / Payments
    # ------------------------------------------------------------------
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def pay_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/assessments/{assessment_id}/pay",
                             payload, headers)

    def place_lien(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/place-lien",
                             headers=headers)

    def list_assessment_payments(self, assessment_id, headers, params=None):
        return self._request("GET", f"/assessments/{assessment_id}/payments",
                             headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def reverse_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse",
                             payload, headers)

    # ------------------------------------------------------------------
    # ARC
    # ------------------------------------------------------------------
    def create_arc_request(self, payload, headers):
        return self._request("POST", "/arc-requests", payload, headers)

    def get_arc_request(self, arc_id, headers):
        return self._request("GET", f"/arc-requests/{arc_id}", headers=headers)

    def submit_arc_request(self, arc_id, headers):
        return self._request("POST", f"/arc-requests/{arc_id}/submit", headers=headers)

    def create_arc_review(self, arc_id, payload, headers):
        return self._request("POST", f"/arc-requests/{arc_id}/reviews",
                             payload, headers)

    def list_arc_reviews(self, arc_id, headers, params=None):
        return self._request("GET", f"/arc-requests/{arc_id}/reviews",
                             headers=headers, params=params)

    def finalize_arc_request(self, arc_id, headers):
        return self._request("POST", f"/arc-requests/{arc_id}/finalize",
                             headers=headers)

    # ------------------------------------------------------------------
    # Violations
    # ------------------------------------------------------------------
    def create_violation(self, payload, headers):
        return self._request("POST", "/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def confirm_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/confirm",
                             headers=headers)

    def fine_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/violations/{violation_id}/fine",
                             payload, headers)

    def appeal_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/appeal",
                             headers=headers)

    def adjudicate_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/violations/{violation_id}/adjudicate",
                             payload, headers)

    def resolve_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/violations/{violation_id}/resolve",
                             payload, headers)

    # ------------------------------------------------------------------
    # Amenities / Reservations
    # ------------------------------------------------------------------
    def create_amenity(self, payload, headers):
        return self._request("POST", "/amenities", payload, headers)

    def get_amenity(self, amenity_id, headers):
        return self._request("GET", f"/amenities/{amenity_id}", headers=headers)

    def list_amenity_reservations(self, amenity_id, headers, params=None):
        return self._request("GET", f"/amenities/{amenity_id}/reservations",
                             headers=headers, params=params)

    def create_amenity_reservation(self, payload, headers):
        return self._request("POST", "/amenity-reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/amenity-reservations",
                             headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/amenity-reservations/{reservation_id}",
                             headers=headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST",
                             f"/amenity-reservations/{reservation_id}/cancel",
                             headers=headers)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST",
                             f"/amenity-reservations/{reservation_id}/check-in",
                             headers=headers)

    # ------------------------------------------------------------------
    # Motions / Ballots
    # ------------------------------------------------------------------
    def create_motion(self, payload, headers):
        return self._request("POST", "/motions", payload, headers)

    def get_motion(self, motion_id, headers):
        return self._request("GET", f"/motions/{motion_id}", headers=headers)

    def cast_ballot(self, motion_id, payload, headers):
        return self._request("POST", f"/motions/{motion_id}/ballots",
                             payload, headers)

    def list_motion_ballots(self, motion_id, headers, params=None):
        return self._request("GET", f"/motions/{motion_id}/ballots",
                             headers=headers, params=params)

    def list_ballots(self, headers, params=None):
        return self._request("GET", "/ballots", headers=headers, params=params)

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"/ballots/{ballot_id}", headers=headers)

    def close_motion(self, motion_id, headers):
        return self._request("POST", f"/motions/{motion_id}/close", headers=headers)

    # ------------------------------------------------------------------
    # Work Orders
    # ------------------------------------------------------------------
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def assign_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/assign",
                             payload, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/start",
                             headers=headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete",
                             headers=headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel",
                             headers=headers)

    def invoice_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/invoice",
                             headers=headers)

    def mark_paid_work_order(self, work_order_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/mark-paid",
                             headers=headers)

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    def create_document(self, payload, headers):
        return self._request("POST", "/documents", payload, headers)

    def list_documents(self, headers, params=None):
        return self._request("GET", "/documents", headers=headers, params=params)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/documents/{document_id}", headers=headers)

    # ------------------------------------------------------------------
    # Test-driving surface
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def set_grace_policy(self, grace_policy, headers):
        return self._request("POST", "/_config/grace-policy",
                             {"grace_policy": grace_policy}, headers)


api_client = ApiClient()
