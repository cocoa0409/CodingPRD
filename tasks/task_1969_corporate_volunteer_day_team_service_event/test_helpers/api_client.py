"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- NonprofitPartner ---
    def create_nonprofit_partner(self, payload, headers):
        return self._request("POST", "/nonprofit-partners", payload, headers)

    def list_nonprofit_partners(self, headers, params=None):
        return self._request("GET", "/nonprofit-partners", headers=headers, params=params)

    def get_nonprofit_partner(self, partner_id, headers):
        return self._request("GET", f"/nonprofit-partners/{partner_id}", headers=headers)

    # --- ServiceProject ---
    def create_service_project(self, payload, headers):
        return self._request("POST", "/service-projects", payload, headers)

    def list_service_projects(self, headers, params=None):
        return self._request("GET", "/service-projects", headers=headers, params=params)

    def get_service_project(self, project_id, headers):
        return self._request("GET", f"/service-projects/{project_id}", headers=headers)

    def vet_project(self, project_id, headers):
        return self._request("POST", f"/service-projects/{project_id}/vet", {}, headers)

    def match_project(self, project_id, payload, headers):
        return self._request("POST", f"/service-projects/{project_id}/match", payload, headers)

    def lock_project(self, project_id, headers):
        return self._request("POST", f"/service-projects/{project_id}/lock", {}, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/service-projects/{project_id}/cancel", {}, headers)

    # --- ServiceEvent ---
    def create_service_event(self, payload, headers):
        return self._request("POST", "/service-events", payload, headers)

    def list_service_events(self, headers, params=None):
        return self._request("GET", "/service-events", headers=headers, params=params)

    def get_service_event(self, event_id, headers):
        return self._request("GET", f"/service-events/{event_id}", headers=headers)

    def open_registration(self, event_id, headers):
        return self._request("POST", f"/service-events/{event_id}/open-registration", {}, headers)

    def lock_registration(self, event_id, headers):
        return self._request("POST", f"/service-events/{event_id}/lock-registration", {}, headers)

    def begin_event(self, event_id, headers):
        return self._request("POST", f"/service-events/{event_id}/begin", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/service-events/{event_id}/complete", {}, headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/service-events/{event_id}/close", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/service-events/{event_id}/cancel", {}, headers)

    def reschedule_event(self, event_id, payload, headers):
        return self._request("POST", f"/service-events/{event_id}/reschedule", payload, headers)

    def bump_waiver_version(self, event_id, headers):
        return self._request("POST", f"/service-events/{event_id}/bump-waiver-version", {}, headers)

    def rebook_event(self, event_id, payload, headers):
        return self._request("POST", f"/service-events/{event_id}/rebook", payload, headers)

    # --- EmployeeVolunteer ---
    def create_employee_volunteer(self, payload, headers):
        return self._request("POST", "/employee-volunteers", payload, headers)

    def list_employee_volunteers(self, headers, params=None):
        return self._request("GET", "/employee-volunteers", headers=headers, params=params)

    def get_employee_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/employee-volunteers/{volunteer_id}", headers=headers)

    # --- Registration ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def confirm_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/confirm", {}, headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/cancel", {}, headers)

    def check_in_registration(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/check-in", {}, headers)

    def sign_waiver(self, registration_id, payload, headers):
        return self._request("POST", f"/registrations/{registration_id}/sign-waiver", payload, headers)

    def verify_waiver(self, registration_id, headers):
        return self._request("POST", f"/registrations/{registration_id}/verify-waiver", {}, headers)

    def assign_transport(self, registration_id, payload, headers):
        return self._request("POST", f"/registrations/{registration_id}/assign-transport", payload, headers)

    # --- ProcurementOrder ---
    def create_procurement_order(self, payload, headers):
        return self._request("POST", "/procurement-orders", payload, headers)

    def list_procurement_orders(self, headers, params=None):
        return self._request("GET", "/procurement-orders", headers=headers, params=params)

    def get_procurement_order(self, order_id, headers):
        return self._request("GET", f"/procurement-orders/{order_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/procurement-orders/{order_id}/submit", {}, headers)

    def approve_order(self, order_id, headers):
        return self._request("POST", f"/procurement-orders/{order_id}/approve", {}, headers)

    def reject_order(self, order_id, payload, headers):
        return self._request("POST", f"/procurement-orders/{order_id}/reject", payload, headers)

    def receive_order(self, order_id, headers):
        return self._request("POST", f"/procurement-orders/{order_id}/receive", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/procurement-orders/{order_id}/cancel", {}, headers)

    # --- Vehicle / TransportManifest ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def create_transport_manifest(self, payload, headers):
        return self._request("POST", "/transport-manifests", payload, headers)

    def list_transport_manifests(self, headers, params=None):
        return self._request("GET", "/transport-manifests", headers=headers, params=params)

    def get_transport_manifest(self, manifest_id, headers):
        return self._request("GET", f"/transport-manifests/{manifest_id}", headers=headers)

    def confirm_manifest(self, manifest_id, headers):
        return self._request("POST", f"/transport-manifests/{manifest_id}/confirm", {}, headers)

    def cancel_manifest(self, manifest_id, headers):
        return self._request("POST", f"/transport-manifests/{manifest_id}/cancel", {}, headers)

    # --- MealPlan ---
    def create_meal_plan(self, event_id, payload, headers):
        return self._request("POST", f"/service-events/{event_id}/meal-plans", payload, headers)

    def list_meal_plans(self, headers, params=None):
        return self._request("GET", "/meal-plans", headers=headers, params=params)

    def get_meal_plan(self, meal_plan_id, headers):
        return self._request("GET", f"/meal-plans/{meal_plan_id}", headers=headers)

    def order_meal_plan(self, meal_plan_id, headers):
        return self._request("POST", f"/meal-plans/{meal_plan_id}/order", {}, headers)

    def fulfill_meal_plan(self, meal_plan_id, headers):
        return self._request("POST", f"/meal-plans/{meal_plan_id}/fulfill", {}, headers)

    def cancel_meal_plan(self, meal_plan_id, headers):
        return self._request("POST", f"/meal-plans/{meal_plan_id}/cancel", {}, headers)

    # --- SupervisionAssignment ---
    def create_supervision_assignment(self, payload, headers):
        return self._request("POST", "/supervision-assignments", payload, headers)

    def list_supervision_assignments(self, headers, params=None):
        return self._request("GET", "/supervision-assignments", headers=headers, params=params)

    def get_supervision_assignment(self, assignment_id, headers):
        return self._request("GET", f"/supervision-assignments/{assignment_id}", headers=headers)

    def withdraw_supervision_assignment(self, assignment_id, headers):
        return self._request("POST", f"/supervision-assignments/{assignment_id}/withdraw", {}, headers)

    # --- Sponsorship ---
    def create_sponsorship(self, payload, headers):
        return self._request("POST", "/sponsorships", payload, headers)

    def list_sponsorships(self, headers, params=None):
        return self._request("GET", "/sponsorships", headers=headers, params=params)

    def get_sponsorship(self, sponsorship_id, headers):
        return self._request("GET", f"/sponsorships/{sponsorship_id}", headers=headers)

    def commit_sponsorship(self, sponsorship_id, headers):
        return self._request("POST", f"/sponsorships/{sponsorship_id}/commit", {}, headers)

    def settle_sponsorship(self, sponsorship_id, headers):
        return self._request("POST", f"/sponsorships/{sponsorship_id}/settle", {}, headers)

    def withdraw_sponsorship(self, sponsorship_id, headers):
        return self._request("POST", f"/sponsorships/{sponsorship_id}/withdraw", {}, headers)

    # --- ImpactRecord ---
    def create_impact_record(self, payload, headers):
        return self._request("POST", "/impact-records", payload, headers)

    def list_impact_records(self, headers, params=None):
        return self._request("GET", "/impact-records", headers=headers, params=params)

    def get_impact_record(self, record_id, headers):
        return self._request("GET", f"/impact-records/{record_id}", headers=headers)

    def verify_impact_record(self, record_id, headers):
        return self._request("POST", f"/impact-records/{record_id}/verify", {}, headers)

    def publish_impact_record(self, record_id, headers):
        return self._request("POST", f"/impact-records/{record_id}/publish", {}, headers)

    def reject_impact_record(self, record_id, payload, headers):
        return self._request("POST", f"/impact-records/{record_id}/reject", payload, headers)

    def resubmit_impact_record(self, record_id, headers):
        return self._request("POST", f"/impact-records/{record_id}/resubmit", {}, headers)

    # --- FeedbackSurvey ---
    def create_feedback_survey(self, payload, headers):
        return self._request("POST", "/feedback-surveys", payload, headers)

    def list_feedback_surveys(self, headers, params=None):
        return self._request("GET", "/feedback-surveys", headers=headers, params=params)

    def get_feedback_survey(self, survey_id, headers):
        return self._request("GET", f"/feedback-surveys/{survey_id}", headers=headers)

    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
