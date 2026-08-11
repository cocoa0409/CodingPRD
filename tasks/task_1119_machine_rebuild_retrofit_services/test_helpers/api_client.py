"""API client: one method per endpoint defined in the PRD (§4 routing summary)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    # --- Machine ---
    def create_machine(self, payload, headers):
        return self._request("POST", "/api/machines", payload, headers)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/api/machines/{machine_id}", headers=headers)

    def list_machines(self, headers, params=None):
        return self._request("GET", "/api/machines", headers=headers, params=params)

    # --- Assessment ---
    def create_assessment(self, machine_id, payload, headers):
        return self._request("POST", f"/api/machines/{machine_id}/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/api/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/api/assessments", headers=headers, params=params)

    def submit_assessment(self, assessment_id, headers):
        return self._request("POST", f"/api/assessments/{assessment_id}/submit", {}, headers)

    def return_assessment(self, assessment_id, headers):
        return self._request("POST", f"/api/assessments/{assessment_id}/return", {}, headers)

    def accept_assessment(self, assessment_id, headers):
        return self._request("POST", f"/api/assessments/{assessment_id}/accept", {}, headers)

    # --- RebuildProject ---
    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/api/projects", headers=headers, params=params)

    def record_decision(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/decision", payload, headers)

    def compute_quote(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/quote", payload, headers)

    def send_quote(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/quote/send", {}, headers)

    def approve_quote(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/quote/approve", {}, headers)

    def begin_sourcing(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/begin-sourcing", {}, headers)

    def add_part_line(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/part-lines", payload, headers)

    def start_rebuild(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/start-rebuild", {}, headers)

    def declare_ready(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/declare-ready", {}, headers)

    def create_acceptance_test(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/acceptance-tests", {}, headers)

    def resolve_escalation(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/escalation/resolve", payload, headers)

    def begin_training(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/begin-training", payload, headers)

    def create_shipment_stage(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/shipment-stages", payload, headers)

    def deliver_project(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/deliver", {}, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/cancel", {}, headers)

    def apply_trade_in(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/trade-in/apply", payload, headers)

    def revoke_trade_in(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/trade-in/revoke", {}, headers)

    # --- ProjectPartLine ---
    def get_part_line(self, line_id, headers):
        return self._request("GET", f"/api/part-lines/{line_id}", headers=headers)

    def list_part_lines(self, headers, params=None):
        return self._request("GET", "/api/part-lines", headers=headers, params=params)

    def fulfill_part_line(self, line_id, headers):
        return self._request("POST", f"/api/part-lines/{line_id}/fulfill", {}, headers)

    def cancel_part_line(self, line_id, headers):
        return self._request("POST", f"/api/part-lines/{line_id}/cancel", {}, headers)

    # --- ReverseEngineeringJob ---
    def get_re_job(self, job_id, headers):
        return self._request("GET", f"/api/re-jobs/{job_id}", headers=headers)

    def list_re_jobs(self, headers, params=None):
        return self._request("GET", "/api/re-jobs", headers=headers, params=params)

    def capture_spec(self, job_id, headers):
        return self._request("POST", f"/api/re-jobs/{job_id}/capture-spec", {}, headers)

    def fabricate(self, job_id, payload, headers):
        return self._request("POST", f"/api/re-jobs/{job_id}/fabricate", payload, headers)

    def validate_re_job(self, job_id, headers):
        return self._request("POST", f"/api/re-jobs/{job_id}/validate", {}, headers)

    def fail_re_job(self, job_id, headers):
        return self._request("POST", f"/api/re-jobs/{job_id}/fail", {}, headers)

    # --- AcceptanceTest ---
    def get_acceptance_test(self, test_id, headers):
        return self._request("GET", f"/api/acceptance-tests/{test_id}", headers=headers)

    def list_acceptance_tests(self, headers, params=None):
        return self._request("GET", "/api/acceptance-tests", headers=headers, params=params)

    def record_acceptance_test(self, test_id, payload, headers):
        return self._request("POST", f"/api/acceptance-tests/{test_id}/record", payload, headers)

    # --- TrainingRecord ---
    def get_training_record(self, record_id, headers):
        return self._request("GET", f"/api/training-records/{record_id}", headers=headers)

    def list_training_records(self, headers, params=None):
        return self._request("GET", "/api/training-records", headers=headers, params=params)

    def log_session(self, record_id, headers):
        return self._request("POST", f"/api/training-records/{record_id}/log-session", {}, headers)

    def deliver_documentation(self, record_id, headers):
        return self._request("POST", f"/api/training-records/{record_id}/deliver-documentation", {}, headers)

    # --- DowntimeWindow ---
    def create_downtime_window(self, payload, headers):
        return self._request("POST", "/api/downtime-windows", payload, headers)

    def get_downtime_window(self, window_id, headers):
        return self._request("GET", f"/api/downtime-windows/{window_id}", headers=headers)

    def list_downtime_windows(self, headers, params=None):
        return self._request("GET", "/api/downtime-windows", headers=headers, params=params)

    def cancel_downtime_window(self, window_id, headers):
        return self._request("POST", f"/api/downtime-windows/{window_id}/cancel", {}, headers)

    # --- ShipmentStage ---
    def get_shipment_stage(self, stage_id, headers):
        return self._request("GET", f"/api/shipment-stages/{stage_id}", headers=headers)

    def list_shipment_stages(self, headers, params=None):
        return self._request("GET", "/api/shipment-stages", headers=headers, params=params)

    def ship_stage(self, stage_id, headers):
        return self._request("POST", f"/api/shipment-stages/{stage_id}/ship", {}, headers)

    def receive_stage(self, stage_id, headers):
        return self._request("POST", f"/api/shipment-stages/{stage_id}/receive", {}, headers)

    def install_stage(self, stage_id, headers):
        return self._request("POST", f"/api/shipment-stages/{stage_id}/install", {}, headers)

    def replan_stage(self, stage_id, payload, headers):
        return self._request("POST", f"/api/shipment-stages/{stage_id}/replan", payload, headers)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/api/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/api/warranty-claims", headers=headers, params=params)

    def approve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/approve", payload, headers)

    def reject_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/reject", payload, headers)

    def remediate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/warranty-claims/{claim_id}/remediate", payload, headers)

    # --- TradeInOffer ---
    def create_trade_in_offer(self, machine_id, payload, headers):
        return self._request("POST", f"/api/machines/{machine_id}/trade-in-offers", payload, headers)

    def get_trade_in_offer(self, offer_id, headers):
        return self._request("GET", f"/api/trade-in-offers/{offer_id}", headers=headers)

    def list_trade_in_offers(self, headers, params=None):
        return self._request("GET", "/api/trade-in-offers", headers=headers, params=params)

    def accept_trade_in_offer(self, offer_id, headers):
        return self._request("POST", f"/api/trade-in-offers/{offer_id}/accept", {}, headers)

    def decline_trade_in_offer(self, offer_id, headers):
        return self._request("POST", f"/api/trade-in-offers/{offer_id}/decline", {}, headers)

    # --- Part ---
    def create_part(self, payload, headers):
        return self._request("POST", "/api/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/api/parts/{part_id}", headers=headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/api/parts", headers=headers, params=params)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
