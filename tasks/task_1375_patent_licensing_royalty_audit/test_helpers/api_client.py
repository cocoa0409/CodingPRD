"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Licensees
    # ------------------------------------------------------------------
    def create_licensee(self, payload, headers):
        return self._request("POST", "/licensing/licensees", payload, headers)

    def list_licensees(self, headers, params=None):
        return self._request("GET", "/licensing/licensees", headers=headers, params=params)

    def get_licensee(self, licensee_id, headers):
        return self._request("GET", f"/licensing/licensees/{licensee_id}", headers=headers)

    def licensee_lifecycle(self, licensee_id, payload, headers):
        return self._request("POST", f"/licensing/licensees/{licensee_id}/lifecycle", payload, headers)

    # ------------------------------------------------------------------
    # License agreements
    # ------------------------------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", "/licensing/license-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/licensing/license-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/licensing/license-agreements/{agreement_id}", headers=headers)

    def patch_agreement(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/licensing/license-agreements/{agreement_id}", payload, headers)

    def agreement_lifecycle(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/licensing/license-agreements/{agreement_id}/lifecycle", payload, headers
        )

    # ------------------------------------------------------------------
    # Milestones
    # ------------------------------------------------------------------
    def create_milestone(self, payload, headers):
        return self._request("POST", "/licensing/milestones", payload, headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/licensing/milestones", headers=headers, params=params)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/licensing/milestones/{milestone_id}", headers=headers)

    # ------------------------------------------------------------------
    # Sublicense grants
    # ------------------------------------------------------------------
    def create_sublicense_grant(self, payload, headers):
        return self._request("POST", "/licensing/sublicense-grants", payload, headers)

    def list_sublicense_grants(self, headers, params=None):
        return self._request("GET", "/licensing/sublicense-grants", headers=headers, params=params)

    def get_sublicense_grant(self, grant_id, headers):
        return self._request("GET", f"/licensing/sublicense-grants/{grant_id}", headers=headers)

    def sublicense_decision(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/licensing/sublicense-grants/{grant_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Royalty reports
    # ------------------------------------------------------------------
    def create_royalty_report(self, payload, headers):
        return self._request("POST", "/licensing/royalty-reports", payload, headers)

    def list_royalty_reports(self, headers, params=None):
        return self._request("GET", "/licensing/royalty-reports", headers=headers, params=params)

    def get_royalty_report(self, report_id, headers):
        return self._request("GET", f"/licensing/royalty-reports/{report_id}", headers=headers)

    def validate_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/licensing/royalty-reports/{report_id}/validate", payload, headers
        )

    def accept_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/licensing/royalty-reports/{report_id}/accept", payload, headers
        )

    def void_acceptance(self, report_id, payload, headers):
        return self._request(
            "POST", f"/licensing/royalty-reports/{report_id}/void-acceptance", payload, headers
        )

    # ------------------------------------------------------------------
    # Audits
    # ------------------------------------------------------------------
    def create_audit(self, payload, headers):
        return self._request("POST", "/licensing/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/licensing/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/licensing/audits/{audit_id}", headers=headers)

    def advance_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/licensing/audits/{audit_id}/advance", payload, headers)

    # ------------------------------------------------------------------
    # Audit findings
    # ------------------------------------------------------------------
    def create_audit_finding(self, payload, headers):
        return self._request("POST", "/licensing/audit-findings", payload, headers)

    def list_audit_findings(self, headers, params=None):
        return self._request("GET", "/licensing/audit-findings", headers=headers, params=params)

    def get_audit_finding(self, finding_id, headers):
        return self._request("GET", f"/licensing/audit-findings/{finding_id}", headers=headers)

    def resolve_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/licensing/audit-findings/{finding_id}/resolution", payload, headers
        )

    def dispute_finding(self, finding_id, headers):
        return self._request(
            "POST", f"/licensing/audit-findings/{finding_id}/dispute", {}, headers
        )

    # ------------------------------------------------------------------
    # Disputes
    # ------------------------------------------------------------------
    def list_disputes(self, headers, params=None):
        return self._request("GET", "/licensing/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/licensing/disputes/{dispute_id}", headers=headers)

    def submit_offer(self, dispute_id, payload, headers):
        return self._request("POST", f"/licensing/disputes/{dispute_id}/offers", payload, headers)

    def accept_offer(self, dispute_id, headers):
        return self._request("POST", f"/licensing/disputes/{dispute_id}/accept-offer", {}, headers)

    def ratify_dispute(self, dispute_id, headers):
        return self._request("POST", f"/licensing/disputes/{dispute_id}/ratify", {}, headers)

    def arbitrate_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/licensing/disputes/{dispute_id}/arbitrate", payload, headers
        )

    # ------------------------------------------------------------------
    # Distribution runs
    # ------------------------------------------------------------------
    def create_distribution_run(self, payload, headers):
        return self._request("POST", "/licensing/distribution-runs", payload, headers)

    def list_distribution_runs(self, headers, params=None):
        return self._request("GET", "/licensing/distribution-runs", headers=headers, params=params)

    def get_distribution_run(self, run_id, headers):
        return self._request("GET", f"/licensing/distribution-runs/{run_id}", headers=headers)

    def approve_distribution_run(self, run_id, headers):
        return self._request("POST", f"/licensing/distribution-runs/{run_id}/approve", {}, headers)

    def void_distribution_run(self, run_id, payload, headers):
        return self._request("POST", f"/licensing/distribution-runs/{run_id}/void", payload, headers)

    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/licensing/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
