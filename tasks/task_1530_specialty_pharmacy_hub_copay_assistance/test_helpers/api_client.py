"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- DrugProgram ---
    def create_drug_program(self, payload, headers):
        return self._request("POST", "/hub/drug-programs", payload, headers)

    # --- FoundationPool ---
    def create_foundation_pool(self, payload, headers):
        return self._request("POST", "/hub/foundation-pools", payload, headers)

    def get_foundation_pool(self, pool_id, headers):
        return self._request("GET", f"/hub/foundation-pools/{pool_id}",
                             headers=headers)

    def list_pool_grants(self, pool_id, headers, params=None):
        return self._request("GET",
                             f"/hub/foundation-pools/{pool_id}/copay-assistances",
                             headers=headers, params=params)

    # --- Enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/hub/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/hub/enrollments/{enrollment_id}",
                             headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/hub/enrollments",
                             headers=headers, params=params)

    def discontinue_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST",
                             f"/hub/enrollments/{enrollment_id}/discontinue",
                             payload, headers)

    # --- BenefitsInvestigation ---
    def create_benefits_investigation(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/hub/enrollments/{enrollment_id}/benefits-investigation",
            payload, headers)

    def get_benefits_investigation(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/hub/enrollments/{enrollment_id}/benefits-investigation",
            headers=headers, params=params)

    # --- PriorAuthorization ---
    def create_prior_authorization(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/hub/enrollments/{enrollment_id}/prior-authorization",
            payload, headers)

    def list_prior_authorizations(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/hub/enrollments/{enrollment_id}/prior-authorizations",
            headers=headers, params=params)

    def record_pa_decision(self, pa_id, payload, headers):
        return self._request("POST",
                             f"/hub/prior-authorizations/{pa_id}/decision",
                             payload, headers)

    def appeal_prior_authorization(self, pa_id, payload, headers):
        return self._request("POST",
                             f"/hub/prior-authorizations/{pa_id}/appeal",
                             payload, headers)

    # --- CopayAssistance ---
    def match_copay_assistance(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/hub/enrollments/{enrollment_id}/copay-assistance/match",
            payload, headers)

    def release_copay_assistance(self, assistance_id, headers, payload=None):
        return self._request("POST",
                             f"/hub/copay-assistances/{assistance_id}/release",
                             payload, headers)

    def list_copay_assistances(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/hub/enrollments/{enrollment_id}/copay-assistances",
            headers=headers, params=params)

    # --- NurseVisit ---
    def create_nurse_visit(self, enrollment_id, payload, headers):
        return self._request("POST",
                             f"/hub/enrollments/{enrollment_id}/nurse-visits",
                             payload, headers)

    def list_nurse_visits(self, enrollment_id, headers, params=None):
        return self._request("GET",
                             f"/hub/enrollments/{enrollment_id}/nurse-visits",
                             headers=headers, params=params)

    def resolve_nurse_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/hub/nurse-visits/{visit_id}/resolve",
                             payload, headers)

    # --- Shipment ---
    def create_shipment(self, enrollment_id, payload, headers):
        return self._request("POST",
                             f"/hub/enrollments/{enrollment_id}/shipments",
                             payload, headers)

    def list_shipments(self, enrollment_id, headers, params=None):
        return self._request("GET",
                             f"/hub/enrollments/{enrollment_id}/shipments",
                             headers=headers, params=params)

    def ship_shipment(self, shipment_id, headers, payload=None):
        return self._request("POST", f"/hub/shipments/{shipment_id}/ship",
                             payload, headers)

    def deliver_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/hub/shipments/{shipment_id}/deliver",
                             payload, headers)

    def spoil_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/hub/shipments/{shipment_id}/spoil",
                             payload, headers)

    # --- AdverseEvent ---
    def create_adverse_event(self, enrollment_id, payload, headers):
        return self._request("POST",
                             f"/hub/enrollments/{enrollment_id}/adverse-events",
                             payload, headers)

    def list_adverse_events(self, enrollment_id, headers, params=None):
        return self._request("GET",
                             f"/hub/enrollments/{enrollment_id}/adverse-events",
                             headers=headers, params=params)

    def acknowledge_adverse_event(self, ae_id, headers, payload=None):
        return self._request("POST",
                             f"/hub/adverse-events/{ae_id}/acknowledge",
                             payload, headers)

    # --- OutcomeReport ---
    def create_outcome_report(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/hub/enrollments/{enrollment_id}/outcome-reports",
            payload, headers)

    def list_outcome_reports(self, enrollment_id, headers, params=None):
        return self._request("GET",
                             f"/hub/enrollments/{enrollment_id}/outcome-reports",
                             headers=headers, params=params)

    def submit_outcome_report(self, report_id, headers, payload=None):
        return self._request("POST",
                             f"/hub/outcome-reports/{report_id}/submit",
                             payload, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/hub/_clock/set_current_utc",
                             payload, headers)


api_client = ApiClient()
