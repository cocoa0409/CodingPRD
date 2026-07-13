"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- ProductionCompany ----
    def create_production_company(self, payload, headers):
        return self._request("POST", "/production-companies", payload, headers)

    def get_production_company(self, company_id, headers):
        return self._request("GET", f"/production-companies/{company_id}", headers=headers)

    # ---- Department ----
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    # ---- Officer ----
    def create_officer(self, payload, headers):
        return self._request("POST", "/officers", payload, headers)

    def get_officer(self, officer_id, headers):
        return self._request("GET", f"/officers/{officer_id}", headers=headers)

    def update_officer(self, officer_id, payload, headers):
        return self._request("PATCH", f"/officers/{officer_id}", payload, headers)

    # ---- StreetSegment ----
    def create_street_segment(self, payload, headers):
        return self._request("POST", "/street-segments", payload, headers)

    def get_street_segment(self, segment_id, headers):
        return self._request("GET", f"/street-segments/{segment_id}", headers=headers)

    # ---- PermitApplication ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def add_location_detail(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/location-details", payload, headers)

    def list_location_details(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/location-details", headers=headers, params=params)

    def submit_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/submit", payload, headers)

    def withdraw_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", payload, headers)

    def issue_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/issue", payload, headers)

    def wrap_request_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/wrap-request", payload, headers)

    def wrap_close_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/wrap-close", payload, headers)

    # ---- InsuranceCertificate ----
    def submit_insurance_certificate(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/insurance-certificates", payload, headers)

    def list_insurance_certificates(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/insurance-certificates", headers=headers, params=params)

    def verify_insurance_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/insurance-certificates/{certificate_id}/verify", payload, headers)

    # ---- Rider ----
    def add_rider(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/riders", payload, headers)

    def list_riders(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/riders", headers=headers, params=params)

    def decide_rider(self, rider_id, payload, headers):
        return self._request("POST", f"/riders/{rider_id}/decision", payload, headers)

    # ---- NeighborhoodNotification ----
    def create_notification(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/notifications", payload, headers)

    def list_notifications(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/notifications", headers=headers, params=params)

    # ---- Payments / LedgerEntry ----
    def create_payment(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/payments", payload, headers)

    def list_payments(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/payments", headers=headers, params=params)

    # ---- DepartmentReview ----
    def get_department_review(self, review_id, headers):
        return self._request("GET", f"/department-reviews/{review_id}", headers=headers)

    def list_department_reviews(self, headers, params=None):
        return self._request("GET", "/department-reviews", headers=headers, params=params)

    def decide_department_review(self, review_id, payload, headers):
        return self._request("POST", f"/department-reviews/{review_id}/decision", payload, headers)

    # ---- RoadClosureBooking ----
    def create_road_closure_booking(self, payload, headers):
        return self._request("POST", "/road-closure-bookings", payload, headers)

    def get_road_closure_booking(self, booking_id, headers):
        return self._request("GET", f"/road-closure-bookings/{booking_id}", headers=headers)

    def list_road_closure_bookings(self, headers, params=None):
        return self._request("GET", "/road-closure-bookings", headers=headers, params=params)

    # ---- OfficerAssignment ----
    def create_officer_assignment(self, payload, headers):
        return self._request("POST", "/officer-assignments", payload, headers)

    def get_officer_assignment(self, assignment_id, headers):
        return self._request("GET", f"/officer-assignments/{assignment_id}", headers=headers)

    def list_officer_assignments(self, headers, params=None):
        return self._request("GET", "/officer-assignments", headers=headers, params=params)

    def cancel_officer_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/officer-assignments/{assignment_id}/cancel", payload, headers)


api_client = ApiClient()
