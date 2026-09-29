"""API client: one method per endpoint defined in the PRD (§4).

Every path is mounted under the `/cyber` prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cyber"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # The underwriting control catalog
    # ------------------------------------------------------------------
    def create_control_requirement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/control-requirements", payload, headers)

    def list_control_requirements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/control-requirements", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # The response panel
    # ------------------------------------------------------------------
    def create_panel_vendor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/panel-vendors", payload, headers)

    def update_panel_vendor(self, vendor_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/panel-vendors/{vendor_id}", payload, headers
        )

    def list_panel_vendors(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/panel-vendors", headers=headers, params=params
        )

    def get_panel_vendor(self, vendor_id, headers):
        return self._request(
            "GET", f"{PREFIX}/panel-vendors/{vendor_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Insured accounts
    # ------------------------------------------------------------------
    def create_insured_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/insured-accounts", payload, headers)

    def get_insured_account(self, insured_account_id, headers):
        return self._request(
            "GET", f"{PREFIX}/insured-accounts/{insured_account_id}", headers=headers
        )

    def list_insured_accounts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/insured-accounts", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/applications/{application_id}", headers=headers
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/applications", headers=headers, params=params
        )

    def create_control_attestation(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/control-attestations",
            payload,
            headers,
        )

    def list_application_control_attestations(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/applications/{application_id}/control-attestations",
            headers=headers,
            params=params,
        )

    def get_control_attestation(self, attestation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/control-attestations/{attestation_id}", headers=headers
        )

    def list_control_attestations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/control-attestations", headers=headers, params=params
        )

    def get_control_posture(self, application_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/applications/{application_id}/control-posture",
            headers=headers,
        )

    def submit_application(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def resubmit_controls(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/resubmit-controls",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # External scanning
    # ------------------------------------------------------------------
    def create_external_scan(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/external-scans",
            payload,
            headers,
        )

    def list_application_external_scans(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/applications/{application_id}/external-scans",
            headers=headers,
            params=params,
        )

    def get_external_scan(self, scan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/external-scans/{scan_id}", headers=headers
        )

    def list_external_scans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/external-scans", headers=headers, params=params
        )

    def complete_external_scan(self, scan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/external-scans/{scan_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Quoting, declining, binding
    # ------------------------------------------------------------------
    def quote_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/quote", payload, headers
        )

    def decline_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/decline", payload, headers
        )

    def bind_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/bind", payload, headers
        )

    # ------------------------------------------------------------------
    # Policies and the coverage tower
    # ------------------------------------------------------------------
    def get_policy(self, policy_id, headers):
        return self._request("GET", f"{PREFIX}/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/policies", headers=headers, params=params)

    def list_policy_coverage_sections(self, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/policies/{policy_id}/coverage-sections",
            headers=headers,
            params=params,
        )

    def get_coverage_section(self, section_id, headers):
        return self._request(
            "GET", f"{PREFIX}/coverage-sections/{section_id}", headers=headers
        )

    def list_coverage_sections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/coverage-sections", headers=headers, params=params
        )

    def get_policy_loss_summary(self, policy_id, headers):
        return self._request(
            "GET", f"{PREFIX}/policies/{policy_id}/loss-summary", headers=headers
        )

    def create_warranty_report(self, policy_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/warranty-reports", payload, headers
        )

    def cancel_policy(self, policy_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------------
    # Incident claims
    # ------------------------------------------------------------------
    def create_incident_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/incident-claims", payload, headers)

    def get_incident_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/incident-claims/{claim_id}", headers=headers
        )

    def list_incident_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/incident-claims", headers=headers, params=params
        )

    def triage_incident_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/incident-claims/{claim_id}/triage",
            payload if payload is not None else {},
            headers,
        )

    def confirm_coverage(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/incident-claims/{claim_id}/confirm-coverage", payload, headers
        )

    def deny_incident_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/incident-claims/{claim_id}/deny", payload, headers
        )

    # ------------------------------------------------------------------
    # Vendor engagements
    # ------------------------------------------------------------------
    def create_vendor_engagement(self, claim_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/incident-claims/{claim_id}/vendor-engagements",
            payload,
            headers,
        )

    def get_vendor_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/vendor-engagements/{engagement_id}", headers=headers
        )

    def list_vendor_engagements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/vendor-engagements", headers=headers, params=params
        )

    def log_engagement_hours(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/vendor-engagements/{engagement_id}/log-hours",
            payload,
            headers,
        )

    def complete_vendor_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/vendor-engagements/{engagement_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Proofs of loss and payments
    # ------------------------------------------------------------------
    def create_proof_of_loss(self, claim_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/incident-claims/{claim_id}/proofs-of-loss",
            payload,
            headers,
        )

    def get_proof_of_loss(self, proof_id, headers):
        return self._request(
            "GET", f"{PREFIX}/proofs-of-loss/{proof_id}", headers=headers
        )

    def list_proofs_of_loss(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/proofs-of-loss", headers=headers, params=params
        )

    def request_proof_info(self, proof_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/proofs-of-loss/{proof_id}/request-info", payload, headers
        )

    def accept_proof_of_loss(self, proof_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/proofs-of-loss/{proof_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    def get_claim_payment(self, payment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/claim-payments/{payment_id}", headers=headers
        )

    def list_claim_payments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/claim-payments", headers=headers, params=params
        )

    def reverse_claim_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claim-payments/{payment_id}/reverse", payload, headers
        )

    # ------------------------------------------------------------------
    # Renewal assessments
    # ------------------------------------------------------------------
    def create_renewal_assessment(self, policy_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/renewal-assessments", payload, headers
        )

    def get_renewal_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/renewal-assessments/{assessment_id}", headers=headers
        )

    def list_renewal_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/renewal-assessments", headers=headers, params=params
        )

    def submit_remediation(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/renewal-assessments/{assessment_id}/submit-remediation",
            payload,
            headers,
        )

    def verify_remediation(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/renewal-assessments/{assessment_id}/verify-remediation",
            payload,
            headers,
        )

    def issue_renewal_quote(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/renewal-assessments/{assessment_id}/issue-renewal-quote",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Portfolio aggregation
    # ------------------------------------------------------------------
    def create_systemic_scenario(self, payload, headers):
        return self._request("POST", f"{PREFIX}/systemic-scenarios", payload, headers)

    def get_systemic_scenario(self, scenario_id, headers):
        return self._request(
            "GET", f"{PREFIX}/systemic-scenarios/{scenario_id}", headers=headers
        )

    def list_systemic_scenarios(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/systemic-scenarios", headers=headers, params=params
        )

    def model_systemic_scenario(self, scenario_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/systemic-scenarios/{scenario_id}/model",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Logical clock and epoch processing
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def run_epoch(self, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/_ops/run-epoch",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Raw escape hatches for negative tests that must omit or corrupt
    # headers / bodies that the typed methods always supply.
    # ------------------------------------------------------------------
    def raw_post(self, path, payload=None, headers=None, params=None):
        return self._request("POST", f"{PREFIX}{path}", payload, headers, params)

    def raw_get(self, path, headers=None, params=None):
        return self._request("GET", f"{PREFIX}{path}", headers=headers, params=params)

    def raw_patch(self, path, payload=None, headers=None):
        return self._request("PATCH", f"{PREFIX}{path}", payload, headers)


api_client = ApiClient()
