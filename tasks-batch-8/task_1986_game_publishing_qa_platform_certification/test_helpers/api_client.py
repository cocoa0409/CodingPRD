"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and ops run (PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def ops_run(self, headers):
        return self._request("POST", "/qa-cert/ops/run", {}, headers)

    # ------------------------------------------------------------------
    # Game titles (PRD §3.1)
    # ------------------------------------------------------------------
    def create_title(self, payload, headers):
        return self._request("POST", "/qa-cert/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/qa-cert/titles/{title_id}", headers=headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/qa-cert/titles", headers=headers, params=params)

    def transition_title(self, title_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/titles/{title_id}/transition", payload, headers
        )

    def set_embargo(self, title_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/titles/{title_id}/embargo", payload, headers
        )

    # ------------------------------------------------------------------
    # QA vendors (PRD §3.3)
    # ------------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/qa-cert/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/qa-cert/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/qa-cert/vendors", headers=headers, params=params)

    def transition_vendor(self, vendor_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/vendors/{vendor_id}/transition", payload, headers
        )

    def get_vendor_invoice(self, vendor_id, headers, params=None):
        return self._request(
            "GET", f"/qa-cert/vendors/{vendor_id}/invoice", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Test plans (PRD §3.2)
    # ------------------------------------------------------------------
    def create_test_plan(self, payload, headers):
        return self._request("POST", "/qa-cert/test-plans", payload, headers)

    def get_test_plan(self, plan_id, headers):
        return self._request("GET", f"/qa-cert/test-plans/{plan_id}", headers=headers)

    def list_test_plans(self, headers, params=None):
        return self._request("GET", "/qa-cert/test-plans", headers=headers, params=params)

    def add_plan_entry(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/test-plans/{plan_id}/entries", payload, headers
        )

    def transition_test_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/test-plans/{plan_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Assignments (PRD §3.3)
    # ------------------------------------------------------------------
    def create_assignment(self, payload, headers):
        return self._request("POST", "/qa-cert/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/qa-cert/assignments/{assignment_id}", headers=headers
        )

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/qa-cert/assignments", headers=headers, params=params)

    def transition_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/assignments/{assignment_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Builds (PRD §3.4)
    # ------------------------------------------------------------------
    def create_build(self, payload, headers):
        return self._request("POST", "/qa-cert/builds", payload, headers)

    def get_build(self, build_id, headers):
        return self._request("GET", f"/qa-cert/builds/{build_id}", headers=headers)

    def list_builds(self, headers, params=None):
        return self._request("GET", "/qa-cert/builds", headers=headers, params=params)

    def transition_build(self, build_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/builds/{build_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Bug reports (PRD §3.4)
    # ------------------------------------------------------------------
    def create_bug(self, payload, headers):
        return self._request("POST", "/qa-cert/bugs", payload, headers)

    def get_bug(self, bug_id, headers):
        return self._request("GET", f"/qa-cert/bugs/{bug_id}", headers=headers)

    def list_bugs(self, headers, params=None):
        return self._request("GET", "/qa-cert/bugs", headers=headers, params=params)

    def triage_bug(self, bug_id, payload, headers):
        return self._request("POST", f"/qa-cert/bugs/{bug_id}/triage", payload, headers)

    def transition_bug(self, bug_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/bugs/{bug_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Submission packages (PRD §3.5)
    # ------------------------------------------------------------------
    def create_submission_package(self, title_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/titles/{title_id}/submission-packages", payload, headers
        )

    def get_submission_package(self, package_id, headers):
        return self._request(
            "GET", f"/qa-cert/submission-packages/{package_id}", headers=headers
        )

    def list_submission_packages(self, headers, params=None):
        return self._request(
            "GET", "/qa-cert/submission-packages", headers=headers, params=params
        )

    def transition_submission_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/submission-packages/{package_id}/transition",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Compliance checklists (PRD §3.6)
    # ------------------------------------------------------------------
    def get_checklist(self, checklist_id, headers):
        return self._request(
            "GET", f"/qa-cert/compliance-checklists/{checklist_id}", headers=headers
        )

    def list_checklists(self, headers, params=None):
        return self._request(
            "GET", "/qa-cert/compliance-checklists", headers=headers, params=params
        )

    def verify_checklist_item(self, checklist_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/compliance-checklists/{checklist_id}/items/verify",
            payload, headers,
        )

    def waive_checklist_item(self, checklist_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/compliance-checklists/{checklist_id}/items/waive",
            payload, headers,
        )

    def decide_waiver(self, checklist_id, payload, headers):
        return self._request(
            "POST",
            f"/qa-cert/compliance-checklists/{checklist_id}/items/waiver-decision",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Certification findings (PRD §3.7)
    # ------------------------------------------------------------------
    def create_finding(self, package_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/submission-packages/{package_id}/findings",
            payload, headers,
        )

    def get_finding(self, finding_id, headers):
        return self._request(
            "GET", f"/qa-cert/cert-findings/{finding_id}", headers=headers
        )

    def list_findings(self, headers, params=None):
        return self._request(
            "GET", "/qa-cert/cert-findings", headers=headers, params=params
        )

    def transition_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/cert-findings/{finding_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Age-rating filings (PRD §3.8)
    # ------------------------------------------------------------------
    def create_age_rating_filing(self, payload, headers):
        return self._request("POST", "/qa-cert/age-rating-filings", payload, headers)

    def get_age_rating_filing(self, filing_id, headers):
        return self._request(
            "GET", f"/qa-cert/age-rating-filings/{filing_id}", headers=headers
        )

    def list_age_rating_filings(self, headers, params=None):
        return self._request(
            "GET", "/qa-cert/age-rating-filings", headers=headers, params=params
        )

    def transition_age_rating_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/age-rating-filings/{filing_id}/transition",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Localization packs (PRD §3.8)
    # ------------------------------------------------------------------
    def create_localization_pack(self, payload, headers):
        return self._request("POST", "/qa-cert/localization-packs", payload, headers)

    def get_localization_pack(self, pack_id, headers):
        return self._request(
            "GET", f"/qa-cert/localization-packs/{pack_id}", headers=headers
        )

    def list_localization_packs(self, headers, params=None):
        return self._request(
            "GET", "/qa-cert/localization-packs", headers=headers, params=params
        )

    def transition_localization_pack(self, pack_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/localization-packs/{pack_id}/transition",
            payload, headers,
        )

    # ------------------------------------------------------------------
    # Release windows (PRD §3.9)
    # ------------------------------------------------------------------
    def create_release_window(self, payload, headers):
        return self._request("POST", "/qa-cert/release-windows", payload, headers)

    def get_release_window(self, window_id, headers):
        return self._request(
            "GET", f"/qa-cert/release-windows/{window_id}", headers=headers
        )

    def list_release_windows(self, headers, params=None):
        return self._request(
            "GET", "/qa-cert/release-windows", headers=headers, params=params
        )

    def transition_release_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/release-windows/{window_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Certification blackout windows (PRD §3.9)
    # ------------------------------------------------------------------
    def create_blackout_window(self, payload, headers):
        return self._request("POST", "/qa-cert/cert-blackout-windows", payload, headers)

    def get_blackout_window(self, window_id, headers):
        return self._request(
            "GET", f"/qa-cert/cert-blackout-windows/{window_id}", headers=headers
        )

    def list_blackout_windows(self, headers, params=None):
        return self._request(
            "GET", "/qa-cert/cert-blackout-windows", headers=headers, params=params
        )

    def delete_blackout_window(self, window_id, headers):
        return self._request(
            "DELETE", f"/qa-cert/cert-blackout-windows/{window_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Hotfixes (PRD §3.9)
    # ------------------------------------------------------------------
    def create_hotfix(self, payload, headers):
        return self._request("POST", "/qa-cert/hotfixes", payload, headers)

    def get_hotfix(self, hotfix_id, headers):
        return self._request("GET", f"/qa-cert/hotfixes/{hotfix_id}", headers=headers)

    def list_hotfixes(self, headers, params=None):
        return self._request("GET", "/qa-cert/hotfixes", headers=headers, params=params)

    def transition_hotfix(self, hotfix_id, payload, headers):
        return self._request(
            "POST", f"/qa-cert/hotfixes/{hotfix_id}/transition", payload, headers
        )


api_client = ApiClient()
