"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- MobilityProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/mobility/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/mobility/programs/{program_id}", headers=headers)

    # --- Employee ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/mobility/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/mobility/employees/{employee_id}", headers=headers)

    # --- AllowancePolicy ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/mobility/allowance-policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/mobility/allowance-policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/mobility/allowance-policies", headers=headers, params=params)

    # --- Assignment ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/mobility/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/mobility/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/mobility/assignments", headers=headers, params=params)

    def submit_assignment(self, assignment_id, headers):
        return self._request("POST", f"/mobility/assignments/{assignment_id}/submit", headers=headers)

    def approve_bu(self, assignment_id, headers):
        return self._request("POST", f"/mobility/assignments/{assignment_id}/approve-bu", headers=headers)

    def reject_bu(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/mobility/assignments/{assignment_id}/reject-bu", payload, headers)

    def approve_mobility(self, assignment_id, headers):
        return self._request("POST", f"/mobility/assignments/{assignment_id}/approve-mobility", headers=headers)

    def reject_mobility(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/mobility/assignments/{assignment_id}/reject-mobility", payload, headers)

    def initiate_repatriation(self, assignment_id, payload, headers):
        return self._request("POST", f"/mobility/assignments/{assignment_id}/initiate-repatriation", payload, headers)

    def complete_repatriation(self, assignment_id, headers):
        return self._request("POST", f"/mobility/assignments/{assignment_id}/complete-repatriation", headers=headers)

    def close_assignment(self, assignment_id, headers):
        return self._request("POST", f"/mobility/assignments/{assignment_id}/close", headers=headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/mobility/assignments/{assignment_id}/cancel", headers=headers)

    # --- CompensationPackage ---
    def create_package(self, payload, headers):
        return self._request("POST", "/mobility/compensation-packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/mobility/compensation-packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/mobility/compensation-packages", headers=headers, params=params)

    def submit_package(self, package_id, headers):
        return self._request("POST", f"/mobility/compensation-packages/{package_id}/submit", headers=headers)

    def approve_package(self, package_id, headers):
        return self._request("POST", f"/mobility/compensation-packages/{package_id}/approve", headers=headers)

    def revise_package(self, package_id, headers):
        return self._request("POST", f"/mobility/compensation-packages/{package_id}/revise", headers=headers)

    # --- PayrollSplit ---
    def create_split(self, payload, headers):
        return self._request("POST", "/mobility/payroll-splits", payload, headers)

    def get_split(self, split_id, headers):
        return self._request("GET", f"/mobility/payroll-splits/{split_id}", headers=headers)

    def list_splits(self, headers, params=None):
        return self._request("GET", "/mobility/payroll-splits", headers=headers, params=params)

    def activate_split(self, split_id, headers):
        return self._request("POST", f"/mobility/payroll-splits/{split_id}/activate", headers=headers)

    def suspend_split(self, split_id, headers):
        return self._request("POST", f"/mobility/payroll-splits/{split_id}/suspend", headers=headers)

    def resume_split(self, split_id, headers):
        return self._request("POST", f"/mobility/payroll-splits/{split_id}/resume", headers=headers)

    def terminate_split(self, split_id, headers):
        return self._request("POST", f"/mobility/payroll-splits/{split_id}/terminate", headers=headers)

    # --- ShadowPayrollRecord ---
    def create_record(self, payload, headers):
        return self._request("POST", "/mobility/shadow-payroll-records", payload, headers)

    def get_record(self, record_id, headers):
        return self._request("GET", f"/mobility/shadow-payroll-records/{record_id}", headers=headers)

    def list_records(self, headers, params=None):
        return self._request("GET", "/mobility/shadow-payroll-records", headers=headers, params=params)

    def post_record(self, record_id, headers):
        return self._request("POST", f"/mobility/shadow-payroll-records/{record_id}/post", headers=headers)

    def void_record(self, record_id, headers):
        return self._request("POST", f"/mobility/shadow-payroll-records/{record_id}/void", headers=headers)

    # --- Settlement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/mobility/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/mobility/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/mobility/settlements", headers=headers, params=params)

    def submit_settlement(self, settlement_id, headers):
        return self._request("POST", f"/mobility/settlements/{settlement_id}/submit", headers=headers)

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/mobility/settlements/{settlement_id}/approve", headers=headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/mobility/settlements/{settlement_id}/dispute", payload, headers)

    def recalculate_settlement(self, settlement_id, headers):
        return self._request("POST", f"/mobility/settlements/{settlement_id}/recalculate", headers=headers)

    def settle_settlement(self, settlement_id, headers):
        return self._request("POST", f"/mobility/settlements/{settlement_id}/settle", headers=headers)

    # --- VendorEngagement ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/mobility/vendor-engagements", payload, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/mobility/vendor-engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/mobility/vendor-engagements", headers=headers, params=params)

    def send_data(self, engagement_id, headers):
        return self._request("POST", f"/mobility/vendor-engagements/{engagement_id}/send-data", headers=headers)

    def return_draft(self, engagement_id, headers):
        return self._request("POST", f"/mobility/vendor-engagements/{engagement_id}/return-draft", headers=headers)

    def start_review(self, engagement_id, headers):
        return self._request("POST", f"/mobility/vendor-engagements/{engagement_id}/start-review", headers=headers)

    def request_revision(self, engagement_id, headers):
        return self._request("POST", f"/mobility/vendor-engagements/{engagement_id}/request-revision", headers=headers)

    def accept_engagement(self, engagement_id, headers):
        return self._request("POST", f"/mobility/vendor-engagements/{engagement_id}/accept", headers=headers)

    def mark_filed(self, engagement_id, payload, headers):
        return self._request("POST", f"/mobility/vendor-engagements/{engagement_id}/mark-filed", payload, headers)

    def close_engagement(self, engagement_id, headers):
        return self._request("POST", f"/mobility/vendor-engagements/{engagement_id}/close", headers=headers)

    # --- CertificateOfCoverage ---
    def create_certificate(self, payload, headers):
        return self._request("POST", "/mobility/certificates-of-coverage", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/mobility/certificates-of-coverage/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/mobility/certificates-of-coverage", headers=headers, params=params)

    def submit_certificate(self, certificate_id, headers):
        return self._request("POST", f"/mobility/certificates-of-coverage/{certificate_id}/submit", headers=headers)

    def mark_issued(self, certificate_id, payload, headers):
        return self._request("POST", f"/mobility/certificates-of-coverage/{certificate_id}/mark-issued", payload, headers)

    def mark_rejected(self, certificate_id, headers):
        return self._request("POST", f"/mobility/certificates-of-coverage/{certificate_id}/mark-rejected", headers=headers)

    # --- CostProjection ---
    def create_projection(self, payload, headers):
        return self._request("POST", "/mobility/cost-projections", payload, headers)

    def get_projection(self, projection_id, headers):
        return self._request("GET", f"/mobility/cost-projections/{projection_id}", headers=headers)

    def list_projections(self, headers, params=None):
        return self._request("GET", "/mobility/cost-projections", headers=headers, params=params)

    # --- ExtensionRequest ---
    def create_extension(self, payload, headers):
        return self._request("POST", "/mobility/extension-requests", payload, headers)

    def get_extension(self, extension_id, headers):
        return self._request("GET", f"/mobility/extension-requests/{extension_id}", headers=headers)

    def list_extensions(self, headers, params=None):
        return self._request("GET", "/mobility/extension-requests", headers=headers, params=params)

    def approve_extension(self, extension_id, headers):
        return self._request("POST", f"/mobility/extension-requests/{extension_id}/approve", headers=headers)

    def decline_extension(self, extension_id, headers):
        return self._request("POST", f"/mobility/extension-requests/{extension_id}/decline", headers=headers)

    # --- ChargebackEntry ---
    def get_chargeback(self, entry_id, headers):
        return self._request("GET", f"/mobility/chargeback-entries/{entry_id}", headers=headers)

    def list_chargebacks(self, headers, params=None):
        return self._request("GET", "/mobility/chargeback-entries", headers=headers, params=params)

    def post_chargeback(self, entry_id, headers):
        return self._request("POST", f"/mobility/chargeback-entries/{entry_id}/post", headers=headers)

    def void_chargeback(self, entry_id, headers):
        return self._request("POST", f"/mobility/chargeback-entries/{entry_id}/void", headers=headers)


api_client = ApiClient()
