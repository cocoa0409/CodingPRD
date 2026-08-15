"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Property / LeaseSpace ---
    def create_property(self, payload, headers):
        return self._request("POST", "/api/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/api/properties/{property_id}", headers=headers)

    def create_lease_space(self, property_id, payload, headers):
        return self._request(
            "POST", f"/api/properties/{property_id}/lease-spaces", payload, headers
        )

    def list_lease_spaces(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/api/properties/{property_id}/lease-spaces", headers=headers, params=params
        )

    def get_lease_space(self, space_id, headers):
        return self._request("GET", f"/api/lease-spaces/{space_id}", headers=headers)

    def list_space_leases(self, space_id, headers):
        return self._request("GET", f"/api/lease-spaces/{space_id}/leases", headers=headers)

    # --- Tenant / Lease ---
    def create_tenant(self, payload, headers):
        return self._request("POST", "/api/tenants", payload, headers)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/api/tenants/{tenant_id}", headers=headers)

    def list_tenant_leases(self, tenant_id, headers):
        return self._request("GET", f"/api/tenants/{tenant_id}/leases", headers=headers)

    def create_lease(self, payload, headers):
        return self._request("POST", "/api/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/api/leases/{lease_id}", headers=headers)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/api/leases/{lease_id}/activate", headers=headers)

    def list_lease_projects(self, lease_id, headers):
        return self._request("GET", f"/api/leases/{lease_id}/ti-projects", headers=headers)

    # --- Contractor registry ---
    def create_contractor(self, payload, headers):
        return self._request("POST", "/api/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/api/contractors/{contractor_id}", headers=headers)

    def qualify_contractor(self, contractor_id, headers):
        return self._request("POST", f"/api/contractors/{contractor_id}/qualify", headers=headers)

    def suspend_contractor(self, contractor_id, headers):
        return self._request("POST", f"/api/contractors/{contractor_id}/suspend", headers=headers)

    def reinstate_contractor(self, contractor_id, headers):
        return self._request("POST", f"/api/contractors/{contractor_id}/reinstate", headers=headers)

    def revoke_contractor(self, contractor_id, headers):
        return self._request("POST", f"/api/contractors/{contractor_id}/revoke", headers=headers)

    def list_contractor_engagements(self, contractor_id, headers):
        return self._request(
            "GET", f"/api/contractors/{contractor_id}/contractor-engagements", headers=headers
        )

    def list_contractor_waivers(self, contractor_id, headers):
        return self._request(
            "GET", f"/api/contractors/{contractor_id}/lien-waivers", headers=headers
        )

    # --- TIProject lifecycle ---
    def create_ti_project(self, lease_id, payload, headers):
        return self._request("POST", f"/api/leases/{lease_id}/ti-projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/ti-projects/{project_id}", headers=headers)

    def begin_plan_review(self, project_id, headers):
        return self._request(
            "POST", f"/api/ti-projects/{project_id}/begin-plan-review", headers=headers
        )

    def begin_pre_construction(self, project_id, headers):
        return self._request(
            "POST", f"/api/ti-projects/{project_id}/begin-pre-construction", headers=headers
        )

    def start_construction(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/ti-projects/{project_id}/start-construction", payload, headers
        )

    def begin_punch(self, project_id, headers):
        return self._request("POST", f"/api/ti-projects/{project_id}/begin-punch", headers=headers)

    def issue_occupancy_certificate(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/ti-projects/{project_id}/issue-occupancy-certificate", payload, headers
        )

    def complete_project(self, project_id, headers):
        return self._request("POST", f"/api/ti-projects/{project_id}/complete", headers=headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/api/ti-projects/{project_id}/cancel", headers=headers)

    # --- WorkLetter negotiation ---
    def create_work_letter(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/ti-projects/{project_id}/work-letters", payload, headers
        )

    def list_work_letters(self, project_id, headers):
        return self._request("GET", f"/api/ti-projects/{project_id}/work-letters", headers=headers)

    def get_work_letter(self, work_letter_id, headers):
        return self._request("GET", f"/api/work-letters/{work_letter_id}", headers=headers)

    def propose_work_letter(self, work_letter_id, headers):
        return self._request("POST", f"/api/work-letters/{work_letter_id}/propose", headers=headers)

    def counter_work_letter(self, work_letter_id, payload, headers):
        return self._request(
            "POST", f"/api/work-letters/{work_letter_id}/counter", payload, headers
        )

    def accept_work_letter(self, work_letter_id, headers):
        return self._request("POST", f"/api/work-letters/{work_letter_id}/accept", headers=headers)

    def execute_work_letter(self, work_letter_id, headers):
        return self._request("POST", f"/api/work-letters/{work_letter_id}/execute", headers=headers)

    def withdraw_work_letter(self, work_letter_id, headers):
        return self._request(
            "POST", f"/api/work-letters/{work_letter_id}/withdraw", headers=headers
        )

    # --- Plan review ---
    def create_plan_submission(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/ti-projects/{project_id}/plan-submissions", payload, headers
        )

    def list_plan_submissions(self, project_id, headers):
        return self._request(
            "GET", f"/api/ti-projects/{project_id}/plan-submissions", headers=headers
        )

    def get_plan_submission(self, submission_id, headers):
        return self._request("GET", f"/api/plan-submissions/{submission_id}", headers=headers)

    def start_review(self, submission_id, headers):
        return self._request(
            "POST", f"/api/plan-submissions/{submission_id}/start-review", headers=headers
        )

    def approve_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/api/plan-submissions/{submission_id}/approve", headers=headers
        )

    def request_revision(self, submission_id, headers):
        return self._request(
            "POST", f"/api/plan-submissions/{submission_id}/request-revision", headers=headers
        )

    def reject_final_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/api/plan-submissions/{submission_id}/reject-final", headers=headers
        )

    def create_review_comment(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/api/plan-submissions/{submission_id}/comments", payload, headers
        )

    def list_review_comments(self, submission_id, headers):
        return self._request(
            "GET", f"/api/plan-submissions/{submission_id}/comments", headers=headers
        )

    def get_review_comment(self, comment_id, headers):
        return self._request("GET", f"/api/plan-review-comments/{comment_id}", headers=headers)

    def resolve_review_comment(self, comment_id, headers):
        return self._request(
            "POST", f"/api/plan-review-comments/{comment_id}/resolve", headers=headers
        )

    # --- Contractor engagements ---
    def create_engagement(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/ti-projects/{project_id}/contractor-engagements", payload, headers
        )

    def list_project_engagements(self, project_id, headers):
        return self._request(
            "GET", f"/api/ti-projects/{project_id}/contractor-engagements", headers=headers
        )

    def get_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"/api/contractor-engagements/{engagement_id}", headers=headers
        )

    def acknowledge_rules(self, engagement_id, headers):
        return self._request(
            "POST", f"/api/contractor-engagements/{engagement_id}/acknowledge-rules", headers=headers
        )

    def approve_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/api/contractor-engagements/{engagement_id}/approve", headers=headers
        )

    def activate_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/api/contractor-engagements/{engagement_id}/activate", headers=headers
        )

    def suspend_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/api/contractor-engagements/{engagement_id}/suspend", headers=headers
        )

    def reinstate_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/api/contractor-engagements/{engagement_id}/reinstate", headers=headers
        )

    def terminate_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/api/contractor-engagements/{engagement_id}/terminate", headers=headers
        )

    def complete_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"/api/contractor-engagements/{engagement_id}/complete", headers=headers
        )

    # --- Schedule milestones ---
    def create_milestone(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/api/contractor-engagements/{engagement_id}/milestones", payload, headers
        )

    def list_milestones(self, engagement_id, headers):
        return self._request(
            "GET", f"/api/contractor-engagements/{engagement_id}/milestones", headers=headers
        )

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/api/schedule-milestones/{milestone_id}", headers=headers)

    def confirm_milestone(self, milestone_id, headers):
        return self._request(
            "POST", f"/api/schedule-milestones/{milestone_id}/confirm", headers=headers
        )

    def complete_milestone(self, milestone_id, headers):
        return self._request(
            "POST", f"/api/schedule-milestones/{milestone_id}/complete", headers=headers
        )

    def cancel_milestone(self, milestone_id, headers):
        return self._request(
            "POST", f"/api/schedule-milestones/{milestone_id}/cancel", headers=headers
        )

    # --- Change orders ---
    def create_change_order(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/ti-projects/{project_id}/change-orders", payload, headers
        )

    def list_change_orders(self, project_id, headers):
        return self._request("GET", f"/api/ti-projects/{project_id}/change-orders", headers=headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/api/change-orders/{change_order_id}", headers=headers)

    def submit_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/api/change-orders/{change_order_id}/submit", headers=headers
        )

    def approve_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/api/change-orders/{change_order_id}/approve", headers=headers
        )

    def reject_change_order(self, change_order_id, headers):
        return self._request(
            "POST", f"/api/change-orders/{change_order_id}/reject", headers=headers
        )

    def void_change_order(self, change_order_id, headers):
        return self._request("POST", f"/api/change-orders/{change_order_id}/void", headers=headers)

    # --- Disbursements & lien waivers ---
    def create_draw(self, project_id, payload, headers):
        return self._request(
            "POST", f"/api/ti-projects/{project_id}/disbursement-requests", payload, headers
        )

    def list_draws(self, project_id, headers):
        return self._request(
            "GET", f"/api/ti-projects/{project_id}/disbursement-requests", headers=headers
        )

    def get_draw(self, draw_id, headers):
        return self._request("GET", f"/api/disbursement-requests/{draw_id}", headers=headers)

    def submit_draw(self, draw_id, headers):
        return self._request(
            "POST", f"/api/disbursement-requests/{draw_id}/submit", headers=headers
        )

    def approve_draw(self, draw_id, payload, headers):
        return self._request(
            "POST", f"/api/disbursement-requests/{draw_id}/approve", payload, headers
        )

    def pay_draw(self, draw_id, headers):
        return self._request("POST", f"/api/disbursement-requests/{draw_id}/pay", headers=headers)

    def reject_draw(self, draw_id, headers):
        return self._request(
            "POST", f"/api/disbursement-requests/{draw_id}/reject", headers=headers
        )

    def void_draw(self, draw_id, headers):
        return self._request("POST", f"/api/disbursement-requests/{draw_id}/void", headers=headers)

    def create_lien_waiver(self, draw_id, payload, headers):
        return self._request(
            "POST", f"/api/disbursement-requests/{draw_id}/lien-waivers", payload, headers
        )

    def list_lien_waivers(self, draw_id, headers):
        return self._request(
            "GET", f"/api/disbursement-requests/{draw_id}/lien-waivers", headers=headers
        )

    def get_lien_waiver(self, waiver_id, headers):
        return self._request("GET", f"/api/lien-waivers/{waiver_id}", headers=headers)

    def verify_lien_waiver(self, waiver_id, headers):
        return self._request("POST", f"/api/lien-waivers/{waiver_id}/verify", headers=headers)

    def reject_lien_waiver(self, waiver_id, headers):
        return self._request("POST", f"/api/lien-waivers/{waiver_id}/reject", headers=headers)

    # --- Punch list ---
    def create_punch_item(self, project_id, payload, headers):
        return self._request("POST", f"/api/ti-projects/{project_id}/punch-items", payload, headers)

    def list_project_punch_items(self, project_id, headers):
        return self._request("GET", f"/api/ti-projects/{project_id}/punch-items", headers=headers)

    def list_engagement_punch_items(self, engagement_id, headers):
        return self._request(
            "GET", f"/api/contractor-engagements/{engagement_id}/punch-items", headers=headers
        )

    def get_punch_item(self, punch_item_id, headers):
        return self._request("GET", f"/api/punch-items/{punch_item_id}", headers=headers)

    def start_punch_item(self, punch_item_id, headers):
        return self._request("POST", f"/api/punch-items/{punch_item_id}/start", headers=headers)

    def resolve_punch_item(self, punch_item_id, headers):
        return self._request("POST", f"/api/punch-items/{punch_item_id}/resolve", headers=headers)

    def verify_punch_item(self, punch_item_id, headers):
        return self._request("POST", f"/api/punch-items/{punch_item_id}/verify", headers=headers)

    def reopen_punch_item(self, punch_item_id, headers):
        return self._request("POST", f"/api/punch-items/{punch_item_id}/reopen", headers=headers)

    # --- Overage invoices ---
    def create_overage_invoice(self, project_id, headers, payload=None):
        return self._request(
            "POST", f"/api/ti-projects/{project_id}/overage-invoices", payload, headers
        )

    def list_overage_invoices(self, project_id, headers):
        return self._request(
            "GET", f"/api/ti-projects/{project_id}/overage-invoices", headers=headers
        )

    def get_overage_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/overage-invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/overage-invoices/{invoice_id}/issue", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/overage-invoices/{invoice_id}/pay", headers=headers)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/overage-invoices/{invoice_id}/dispute", headers=headers)

    def reissue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/overage-invoices/{invoice_id}/reissue", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/overage-invoices/{invoice_id}/void", headers=headers)


api_client = ApiClient()
