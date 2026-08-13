"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient, build_user_headers

# The clock endpoint is restricted to HRAdmin / ComplianceOfficer (PRD
# "Endpoint Definitions"); HRAdmin is the canonical driver when the caller
# does not specify an identity.
_CLOCK_DEFAULT_HEADERS = build_user_headers("test-hr-admin-1", "HRAdmin")


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601},
            headers or _CLOCK_DEFAULT_HEADERS,
        )

    # --- ScreeningVendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/suspend", {}, headers)

    def reinstate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/reinstate", {}, headers)

    # --- VendorAccuracyAudit ---
    def create_audit(self, payload, headers):
        return self._request("POST", "/vendor-accuracy-audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request(
            "GET", "/vendor-accuracy-audits", headers=headers, params=params
        )

    def get_audit(self, audit_id, headers):
        return self._request(
            "GET", f"/vendor-accuracy-audits/{audit_id}", headers=headers
        )

    def finalize_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/vendor-accuracy-audits/{audit_id}/finalize", {}, headers
        )

    # --- ScreeningPackage ---
    def create_package(self, payload, headers):
        return self._request("POST", "/screening-packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request(
            "GET", f"/screening-packages/{package_id}", headers=headers
        )

    def update_package(self, package_id, payload, headers):
        return self._request(
            "PUT", f"/screening-packages/{package_id}", payload, headers
        )

    def activate_package(self, package_id, headers):
        return self._request(
            "POST", f"/screening-packages/{package_id}/activate", {}, headers
        )

    def retire_package(self, package_id, headers):
        return self._request(
            "POST", f"/screening-packages/{package_id}/retire", {}, headers
        )

    # --- JurisdictionRule ---
    def create_jurisdiction_rule(self, payload, headers):
        return self._request("POST", "/jurisdiction-rules", payload, headers)

    def get_jurisdiction_rule(self, rule_id, headers):
        return self._request(
            "GET", f"/jurisdiction-rules/{rule_id}", headers=headers
        )

    def patch_jurisdiction_rule(self, rule_id, payload, headers):
        return self._request(
            "PATCH", f"/jurisdiction-rules/{rule_id}", payload, headers
        )

    def activate_jurisdiction_rule(self, rule_id, headers):
        return self._request(
            "POST", f"/jurisdiction-rules/{rule_id}/activate", {}, headers
        )

    # --- AdjudicationMatrix ---
    def create_matrix(self, payload, headers):
        return self._request("POST", "/adjudication-matrices", payload, headers)

    def get_matrix(self, matrix_id, headers):
        return self._request(
            "GET", f"/adjudication-matrices/{matrix_id}", headers=headers
        )

    def activate_matrix(self, matrix_id, headers):
        return self._request(
            "POST", f"/adjudication-matrices/{matrix_id}/activate", {}, headers
        )

    def retire_matrix(self, matrix_id, headers):
        return self._request(
            "POST", f"/adjudication-matrices/{matrix_id}/retire", {}, headers
        )

    # --- Position ---
    def create_position(self, payload, headers):
        return self._request("POST", "/positions", payload, headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/positions", headers=headers, params=params)

    def get_position(self, position_id, headers):
        return self._request("GET", f"/positions/{position_id}", headers=headers)

    # --- Candidate ---
    def create_candidate(self, payload, headers):
        return self._request("POST", "/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/candidates/{candidate_id}", headers=headers)

    def withdraw_candidate(self, candidate_id, headers):
        return self._request(
            "POST", f"/candidates/{candidate_id}/withdraw", {}, headers
        )

    # --- ScreeningOrder ---
    def create_order(self, payload, headers):
        return self._request("POST", "/screening-orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/screening-orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/screening-orders/{order_id}", headers=headers)

    def capture_consent(self, order_id, payload, headers):
        return self._request(
            "POST", f"/screening-orders/{order_id}/consents", payload, headers
        )

    def list_consents(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/screening-orders/{order_id}/consents",
            headers=headers, params=params,
        )

    def dispatch_order(self, order_id, vendor_id, headers):
        return self._request(
            "POST", f"/screening-orders/{order_id}/dispatch",
            {"vendor_id": vendor_id}, headers,
        )

    def cancel_order(self, order_id, headers):
        return self._request(
            "POST", f"/screening-orders/{order_id}/cancel", {}, headers
        )

    def escalate_order(self, order_id, headers):
        return self._request(
            "POST", f"/screening-orders/{order_id}/escalate", {}, headers
        )

    def create_assessment(self, order_id, payload, headers):
        return self._request(
            "POST", f"/screening-orders/{order_id}/individualized-assessments",
            payload, headers,
        )

    def list_assessments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/screening-orders/{order_id}/individualized-assessments",
            headers=headers, params=params,
        )

    def adjudication_decision(self, order_id, decision, headers):
        return self._request(
            "POST", f"/screening-orders/{order_id}/adjudication-decision",
            {"decision": decision}, headers,
        )

    # --- ConsentRecord (flat action) ---
    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/consents/{consent_id}/revoke", {}, headers)

    # --- ScreeningReport ---
    def create_report(self, payload, headers):
        return self._request("POST", "/screening-reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/screening-reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/screening-reports/{report_id}", headers=headers)

    def list_findings(self, report_id, headers, params=None):
        return self._request(
            "GET", f"/screening-reports/{report_id}/findings",
            headers=headers, params=params,
        )

    # --- AdverseActionCase ---
    def list_cases(self, headers, params=None):
        return self._request(
            "GET", "/adverse-action-cases", headers=headers, params=params
        )

    def get_case(self, case_id, headers):
        return self._request(
            "GET", f"/adverse-action-cases/{case_id}", headers=headers
        )

    def send_final_notice(self, case_id, headers):
        return self._request(
            "POST", f"/adverse-action-cases/{case_id}/send-final-notice", {}, headers
        )

    def abort_case(self, case_id, headers):
        return self._request(
            "POST", f"/adverse-action-cases/{case_id}/abort", {}, headers
        )

    # --- Dispute ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve", payload, headers
        )

    def withdraw_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/withdraw", {}, headers
        )


api_client = ApiClient()
