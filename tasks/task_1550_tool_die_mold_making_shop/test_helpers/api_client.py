"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- ToolDesign ---
    def create_tool_design(self, payload, headers):
        return self._request("POST", "/tool-designs", payload, headers)

    def list_tool_designs(self, headers, params=None):
        return self._request("GET", "/tool-designs", headers=headers, params=params)

    def get_tool_design(self, design_id, headers):
        return self._request("GET", f"/tool-designs/{design_id}", headers=headers)

    def submit_tool_design(self, design_id, headers):
        return self._request("POST", f"/tool-designs/{design_id}/submit", {}, headers)

    def review_tool_design(self, design_id, payload, headers):
        return self._request("POST", f"/tool-designs/{design_id}/review", payload, headers)

    def revise_tool_design(self, design_id, payload, headers):
        return self._request("POST", f"/tool-designs/{design_id}/revise", payload, headers)

    # --- Quote ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def issue_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/issue", {}, headers)

    def respond_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/respond", payload, headers)

    # --- BuildJob ---
    def create_build_job(self, payload, headers):
        return self._request("POST", "/build-jobs", payload, headers)

    def list_build_jobs(self, headers, params=None):
        return self._request("GET", "/build-jobs", headers=headers, params=params)

    def get_build_job(self, job_id, headers):
        return self._request("GET", f"/build-jobs/{job_id}", headers=headers)

    def advance_build_job(self, job_id, payload, headers):
        return self._request("POST", f"/build-jobs/{job_id}/advance", payload, headers)

    def hold_build_job(self, job_id, headers):
        return self._request("POST", f"/build-jobs/{job_id}/hold", {}, headers)

    def resume_build_job(self, job_id, headers):
        return self._request("POST", f"/build-jobs/{job_id}/resume", {}, headers)

    def record_payment(self, job_id, payload, headers):
        return self._request("POST", f"/build-jobs/{job_id}/payments", payload, headers)

    def get_build_job_summary(self, job_id, headers):
        return self._request("GET", f"/build-jobs/{job_id}/summary", headers=headers)

    # --- BuildMilestone ---
    def list_build_milestones(self, headers, params=None):
        return self._request("GET", "/build-milestones", headers=headers, params=params)

    def get_build_milestone(self, milestone_id, headers):
        return self._request("GET", f"/build-milestones/{milestone_id}", headers=headers)

    def complete_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/build-milestones/{milestone_id}/complete", payload, headers)

    def invoice_milestone(self, milestone_id, headers):
        return self._request("POST", f"/build-milestones/{milestone_id}/invoice", {}, headers)

    # --- ProgressInvoice / Payment reads ---
    def list_progress_invoices(self, headers, params=None):
        return self._request("GET", "/progress-invoices", headers=headers, params=params)

    def get_progress_invoice(self, invoice_id, headers):
        return self._request("GET", f"/progress-invoices/{invoice_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # --- TryoutSample ---
    def create_tryout_sample(self, payload, headers):
        return self._request("POST", "/tryout-samples", payload, headers)

    def list_tryout_samples(self, headers, params=None):
        return self._request("GET", "/tryout-samples", headers=headers, params=params)

    def get_tryout_sample(self, sample_id, headers):
        return self._request("GET", f"/tryout-samples/{sample_id}", headers=headers)

    def submit_tryout_sample(self, sample_id, payload, headers):
        return self._request("POST", f"/tryout-samples/{sample_id}/submit", payload, headers)

    def buyoff_decision(self, sample_id, payload, headers):
        return self._request("POST", f"/tryout-samples/{sample_id}/buyoff-decision", payload, headers)

    def initiate_rework(self, sample_id, payload, headers):
        return self._request("POST", f"/tryout-samples/{sample_id}/initiate-rework", payload, headers)

    # --- EngineeringChange / ReworkAuthorization ---
    def create_engineering_change(self, payload, headers):
        return self._request("POST", "/engineering-changes", payload, headers)

    def list_engineering_changes(self, headers, params=None):
        return self._request("GET", "/engineering-changes", headers=headers, params=params)

    def get_engineering_change(self, eco_id, headers):
        return self._request("GET", f"/engineering-changes/{eco_id}", headers=headers)

    def assess_engineering_change(self, eco_id, payload, headers):
        return self._request("POST", f"/engineering-changes/{eco_id}/assess", payload, headers)

    def customer_decision_engineering_change(self, eco_id, payload, headers):
        return self._request("POST", f"/engineering-changes/{eco_id}/customer-decision", payload, headers)

    def verify_engineering_change(self, eco_id, headers):
        return self._request("POST", f"/engineering-changes/{eco_id}/verify", {}, headers)

    def list_rework_authorizations(self, headers, params=None):
        return self._request("GET", "/rework-authorizations", headers=headers, params=params)

    def get_rework_authorization(self, ra_id, headers):
        return self._request("GET", f"/rework-authorizations/{ra_id}", headers=headers)

    def start_rework_authorization(self, ra_id, headers):
        return self._request("POST", f"/rework-authorizations/{ra_id}/start", {}, headers)

    def complete_rework_authorization(self, ra_id, payload, headers):
        return self._request("POST", f"/rework-authorizations/{ra_id}/complete", payload, headers)

    def cancel_rework_authorization(self, ra_id, headers):
        return self._request("POST", f"/rework-authorizations/{ra_id}/cancel", {}, headers)

    # --- ToolAsset / shipping & lien ---
    def list_tool_assets(self, headers, params=None):
        return self._request("GET", "/tool-assets", headers=headers, params=params)

    def get_tool_asset(self, tool_id, headers):
        return self._request("GET", f"/tool-assets/{tool_id}", headers=headers)

    def ship_tool_asset(self, tool_id, payload, headers):
        return self._request("POST", f"/tool-assets/{tool_id}/ship", payload, headers)

    def deliver_tool_asset(self, tool_id, headers):
        return self._request("POST", f"/tool-assets/{tool_id}/deliver", {}, headers)

    # --- ShotReport ---
    def create_shot_report(self, payload, headers):
        return self._request("POST", "/shot-reports", payload, headers)

    def list_shot_reports(self, headers, params=None):
        return self._request("GET", "/shot-reports", headers=headers, params=params)

    def get_shot_report(self, report_id, headers):
        return self._request("GET", f"/shot-reports/{report_id}", headers=headers)

    def reverse_shot_report(self, report_id, headers):
        return self._request("POST", f"/shot-reports/{report_id}/reverse", {}, headers)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def review_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/review", payload, headers)

    def close_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/close", {}, headers)

    # --- SpareInsert ---
    def create_spare_insert(self, payload, headers):
        return self._request("POST", "/spare-inserts", payload, headers)

    def list_spare_inserts(self, headers, params=None):
        return self._request("GET", "/spare-inserts", headers=headers, params=params)

    def get_spare_insert(self, insert_id, headers):
        return self._request("GET", f"/spare-inserts/{insert_id}", headers=headers)

    def allocate_spare_insert(self, insert_id, payload, headers):
        return self._request("POST", f"/spare-inserts/{insert_id}/allocate", payload, headers)

    def restock_spare_insert(self, insert_id, payload, headers):
        return self._request("POST", f"/spare-inserts/{insert_id}/restock", payload, headers)

    def discontinue_spare_insert(self, insert_id, headers):
        return self._request("POST", f"/spare-inserts/{insert_id}/discontinue", {}, headers)

    # --- PressReservation / MachineReservation ---
    def create_press_reservation(self, payload, headers):
        return self._request("POST", "/press-reservations", payload, headers)

    def list_press_reservations(self, headers, params=None):
        return self._request("GET", "/press-reservations", headers=headers, params=params)

    def get_press_reservation(self, res_id, headers):
        return self._request("GET", f"/press-reservations/{res_id}", headers=headers)

    def cancel_press_reservation(self, res_id, headers):
        return self._request("POST", f"/press-reservations/{res_id}/cancel", {}, headers)

    def create_machine_reservation(self, payload, headers):
        return self._request("POST", "/machine-reservations", payload, headers)

    def list_machine_reservations(self, headers, params=None):
        return self._request("GET", "/machine-reservations", headers=headers, params=params)

    def get_machine_reservation(self, res_id, headers):
        return self._request("GET", f"/machine-reservations/{res_id}", headers=headers)

    def cancel_machine_reservation(self, res_id, headers):
        return self._request("POST", f"/machine-reservations/{res_id}/cancel", {}, headers)

    # --- Test-driving clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
