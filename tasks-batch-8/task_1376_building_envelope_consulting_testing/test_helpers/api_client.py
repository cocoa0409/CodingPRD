"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload,
                             headers)

    # --- Engagement ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/engagements", params or {}, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}",
                             headers=headers)

    def activate_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/activate",
                             {}, headers)

    def begin_close_out(self, engagement_id, headers):
        return self._request("POST",
                             f"/engagements/{engagement_id}/begin-close-out",
                             {}, headers)

    def close_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/close",
                             {}, headers)

    # --- Assembly ---
    def create_assembly(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/assemblies",
                             payload, headers)

    def list_assemblies(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/assemblies",
                             params or {}, headers)

    def get_assembly(self, engagement_id, assembly_id, headers):
        return self._request(
            "GET", f"/engagements/{engagement_id}/assemblies/{assembly_id}",
            headers=headers)

    # --- DesignReview ---
    def create_design_review(self, engagement_id, payload, headers):
        return self._request("POST",
                             f"/engagements/{engagement_id}/design-reviews",
                             payload, headers)

    def list_design_reviews(self, engagement_id, headers, params=None):
        return self._request("GET",
                             f"/engagements/{engagement_id}/design-reviews",
                             params or {}, headers)

    def get_design_review(self, engagement_id, review_id, headers):
        return self._request(
            "GET",
            f"/engagements/{engagement_id}/design-reviews/{review_id}",
            headers=headers)

    def start_review(self, engagement_id, review_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/design-reviews/{review_id}/start-review",
            {}, headers)

    def issue_comments(self, engagement_id, review_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/design-reviews/{review_id}/issue-comments",
            {}, headers)

    def submit_revision(self, engagement_id, review_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/design-reviews/{review_id}/submit-revision",
            {}, headers)

    def approve_review(self, engagement_id, review_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/design-reviews/{review_id}/approve",
            {}, headers)

    def reject_review(self, engagement_id, review_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/design-reviews/{review_id}/reject",
            {}, headers)

    # --- ChamberSlot ---
    def create_chamber_slot(self, engagement_id, payload, headers):
        return self._request("POST",
                             f"/engagements/{engagement_id}/chamber-slots",
                             payload, headers)

    def list_chamber_slots(self, engagement_id, headers, params=None):
        return self._request("GET",
                             f"/engagements/{engagement_id}/chamber-slots",
                             params or {}, headers)

    def get_chamber_slot(self, engagement_id, slot_id, headers):
        return self._request(
            "GET", f"/engagements/{engagement_id}/chamber-slots/{slot_id}",
            headers=headers)

    def release_chamber_slot(self, engagement_id, slot_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/chamber-slots/{slot_id}/release",
            {}, headers)

    # --- MockUp ---
    def create_mock_up(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/mock-ups",
                             payload, headers)

    def list_mock_ups(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/mock-ups",
                             params or {}, headers)

    def get_mock_up(self, engagement_id, mock_up_id, headers):
        return self._request(
            "GET", f"/engagements/{engagement_id}/mock-ups/{mock_up_id}",
            headers=headers)

    def begin_construction(self, engagement_id, mock_up_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/mock-ups/{mock_up_id}/begin-construction",
            {}, headers)

    def declare_ready(self, engagement_id, mock_up_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/mock-ups/{mock_up_id}/declare-ready",
            {}, headers)

    def begin_testing(self, engagement_id, mock_up_id, payload, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/mock-ups/{mock_up_id}/begin-testing",
            payload, headers)

    def record_mock_up_result(self, engagement_id, mock_up_id, payload,
                              headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/mock-ups/{mock_up_id}/record-result",
            payload, headers)

    def mark_remediated(self, engagement_id, mock_up_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/mock-ups/{mock_up_id}/mark-remediated",
            {}, headers)

    # --- FieldTest ---
    def create_field_test(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/field-tests",
                             payload, headers)

    def list_field_tests(self, engagement_id, headers, params=None):
        return self._request("GET",
                             f"/engagements/{engagement_id}/field-tests",
                             params or {}, headers)

    def get_field_test(self, engagement_id, field_test_id, headers):
        return self._request(
            "GET", f"/engagements/{engagement_id}/field-tests/{field_test_id}",
            headers=headers)

    def begin_field_test(self, engagement_id, field_test_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/field-tests/{field_test_id}/begin",
            {}, headers)

    def record_field_test_result(self, engagement_id, field_test_id, payload,
                                 headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/field-tests/{field_test_id}/record-result",
            payload, headers)

    def begin_diagnosis(self, engagement_id, field_test_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/field-tests/{field_test_id}/begin-diagnosis",
            {}, headers)

    def complete_diagnosis(self, engagement_id, field_test_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/field-tests/{field_test_id}/complete-diagnosis",
            {}, headers)

    def certify_field_test(self, engagement_id, field_test_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/field-tests/{field_test_id}/certify",
            {}, headers)

    # --- Survey ---
    def create_survey(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/surveys",
                             payload, headers)

    def list_surveys(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/surveys",
                             params or {}, headers)

    def get_survey(self, engagement_id, survey_id, headers):
        return self._request(
            "GET", f"/engagements/{engagement_id}/surveys/{survey_id}",
            headers=headers)

    def complete_survey(self, engagement_id, survey_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/surveys/{survey_id}/complete",
            {}, headers)

    def analyze_survey(self, engagement_id, survey_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/surveys/{survey_id}/analyze",
            {}, headers)

    def void_survey(self, engagement_id, survey_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/surveys/{survey_id}/void",
            {}, headers)

    # --- Anomaly ---
    def create_anomaly(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/anomalies",
                             payload, headers)

    def list_anomalies(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/anomalies",
                             params or {}, headers)

    def get_anomaly(self, engagement_id, anomaly_id, headers):
        return self._request(
            "GET", f"/engagements/{engagement_id}/anomalies/{anomaly_id}",
            headers=headers)

    def verify_anomaly(self, engagement_id, anomaly_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/anomalies/{anomaly_id}/verify",
            {}, headers)

    def dismiss_anomaly(self, engagement_id, anomaly_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/anomalies/{anomaly_id}/dismiss",
            {}, headers)

    # --- RemediationPlan ---
    def create_remediation_plan(self, engagement_id, payload, headers):
        return self._request("POST",
                             f"/engagements/{engagement_id}/remediation-plans",
                             payload, headers)

    def list_remediation_plans(self, engagement_id, headers, params=None):
        return self._request("GET",
                             f"/engagements/{engagement_id}/remediation-plans",
                             params or {}, headers)

    def get_remediation_plan(self, engagement_id, plan_id, headers):
        return self._request(
            "GET",
            f"/engagements/{engagement_id}/remediation-plans/{plan_id}",
            headers=headers)

    def issue_remediation_plan(self, engagement_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/remediation-plans/{plan_id}/issue",
            payload, headers)

    def complete_remediation_plan(self, engagement_id, plan_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/remediation-plans/{plan_id}/complete",
            {}, headers)

    def withdraw_remediation_plan(self, engagement_id, plan_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/remediation-plans/{plan_id}/withdraw",
            {}, headers)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, engagement_id, payload, headers):
        return self._request("POST",
                             f"/engagements/{engagement_id}/warranty-claims",
                             payload, headers)

    def list_warranty_claims(self, engagement_id, headers, params=None):
        return self._request("GET",
                             f"/engagements/{engagement_id}/warranty-claims",
                             params or {}, headers)

    def get_warranty_claim(self, engagement_id, claim_id, headers):
        return self._request(
            "GET", f"/engagements/{engagement_id}/warranty-claims/{claim_id}",
            headers=headers)

    def manufacturer_acknowledge(self, engagement_id, claim_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/warranty-claims/{claim_id}/manufacturer-acknowledge",
            {}, headers)

    def manufacturer_decide(self, engagement_id, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/warranty-claims/{claim_id}/manufacturer-decide",
            payload, headers)

    def escalate_claim(self, engagement_id, claim_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/warranty-claims/{claim_id}/escalate",
            {}, headers)

    def resolve_claim(self, engagement_id, claim_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/warranty-claims/{claim_id}/resolve",
            {}, headers)

    # --- LitigationHold ---
    def create_litigation_hold(self, engagement_id, payload, headers):
        return self._request("POST",
                             f"/engagements/{engagement_id}/litigation-holds",
                             payload, headers)

    def list_litigation_holds(self, engagement_id, headers, params=None):
        return self._request("GET",
                             f"/engagements/{engagement_id}/litigation-holds",
                             params or {}, headers)

    def get_litigation_hold(self, engagement_id, hold_id, headers):
        return self._request(
            "GET",
            f"/engagements/{engagement_id}/litigation-holds/{hold_id}",
            headers=headers)

    def release_litigation_hold(self, engagement_id, hold_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/litigation-holds/{hold_id}/release",
            {}, headers)

    # --- MaintenanceVisit ---
    def create_maintenance_visit(self, engagement_id, payload, headers):
        return self._request("POST",
                             f"/engagements/{engagement_id}/maintenance-visits",
                             payload, headers)

    def list_maintenance_visits(self, engagement_id, headers, params=None):
        return self._request("GET",
                             f"/engagements/{engagement_id}/maintenance-visits",
                             params or {}, headers)

    def get_maintenance_visit(self, engagement_id, visit_id, headers):
        return self._request(
            "GET",
            f"/engagements/{engagement_id}/maintenance-visits/{visit_id}",
            headers=headers)

    def complete_maintenance_visit(self, engagement_id, visit_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/maintenance-visits/{visit_id}/complete",
            {}, headers)

    def cancel_maintenance_visit(self, engagement_id, visit_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/maintenance-visits/{visit_id}/cancel",
            {}, headers)

    # --- Invoice ---
    def create_invoice(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/invoices",
                             payload, headers)

    def list_invoices(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/invoices",
                             params or {}, headers)

    def get_invoice(self, engagement_id, invoice_id, headers):
        return self._request(
            "GET", f"/engagements/{engagement_id}/invoices/{invoice_id}",
            headers=headers)

    def issue_invoice(self, engagement_id, invoice_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/invoices/{invoice_id}/issue",
            {}, headers)

    def mark_invoice_paid(self, engagement_id, invoice_id, headers):
        return self._request(
            "POST",
            f"/engagements/{engagement_id}/invoices/{invoice_id}/mark-paid",
            {}, headers)

    def void_invoice(self, engagement_id, invoice_id, headers):
        return self._request(
            "POST", f"/engagements/{engagement_id}/invoices/{invoice_id}/void",
            {}, headers)

    # --- Flat single-resource GETs / reverse-reachability listings ---
    def get_assembly_flat(self, assembly_id, headers):
        return self._request("GET", f"/assemblies/{assembly_id}",
                             headers=headers)

    def list_assembly_design_reviews(self, assembly_id, headers, params=None):
        return self._request("GET", f"/assemblies/{assembly_id}/design-reviews",
                             params or {}, headers)

    def list_assembly_mock_ups(self, assembly_id, headers, params=None):
        return self._request("GET", f"/assemblies/{assembly_id}/mock-ups",
                             params or {}, headers)

    def list_assembly_field_tests(self, assembly_id, headers, params=None):
        return self._request("GET", f"/assemblies/{assembly_id}/field-tests",
                             params or {}, headers)

    def list_assembly_surveys(self, assembly_id, headers, params=None):
        return self._request("GET", f"/assemblies/{assembly_id}/surveys",
                             params or {}, headers)

    def get_chamber_slot_flat(self, slot_id, headers):
        return self._request("GET", f"/chamber-slots/{slot_id}", headers=headers)

    def list_chamber_slot_mock_ups(self, slot_id, headers, params=None):
        return self._request("GET", f"/chamber-slots/{slot_id}/mock-ups",
                             params or {}, headers)

    def get_field_test_flat(self, field_test_id, headers):
        return self._request("GET", f"/field-tests/{field_test_id}",
                             headers=headers)

    def list_field_test_anomalies(self, field_test_id, headers, params=None):
        return self._request("GET", f"/field-tests/{field_test_id}/anomalies",
                             params or {}, headers)

    def get_survey_flat(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}", headers=headers)

    def list_survey_anomalies(self, survey_id, headers, params=None):
        return self._request("GET", f"/surveys/{survey_id}/anomalies",
                             params or {}, headers)

    def get_anomaly_flat(self, anomaly_id, headers):
        return self._request("GET", f"/anomalies/{anomaly_id}", headers=headers)

    def list_anomaly_warranty_claims(self, anomaly_id, headers, params=None):
        return self._request("GET",
                             f"/anomalies/{anomaly_id}/warranty-claims",
                             params or {}, headers)

    def get_remediation_plan_flat(self, plan_id, headers):
        return self._request("GET", f"/remediation-plans/{plan_id}",
                             headers=headers)

    def list_remediation_plans_flat(self, headers, params=None):
        return self._request("GET", "/remediation-plans", params or {},
                             headers)


api_client = ApiClient()
