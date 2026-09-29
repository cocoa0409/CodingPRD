"""API client: one method per endpoint defined in the PRD (PRD §4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Continuing Disclosure & Investor Reporting API.

    Every business path is mounted under the `/disclosure` prefix; the logical
    clock endpoint is not.
    """

    # ------------------------------------------------------------------ #
    # Logical clock (PRD §2.5)
    # ------------------------------------------------------------------ #

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------ #
    # BondIssue (PRD §3.1)
    # ------------------------------------------------------------------ #

    def create_bond_issue(self, payload, headers):
        return self._request("POST", "/disclosure/bond-issues", payload, headers)

    def get_bond_issue(self, issue_id, headers):
        return self._request("GET", f"/disclosure/bond-issues/{issue_id}", headers=headers)

    def list_bond_issues(self, headers, params=None):
        return self._request("GET", "/disclosure/bond-issues", headers=headers, params=params)

    def defease_bond_issue(self, issue_id, payload, headers):
        return self._request(
            "POST", f"/disclosure/bond-issues/{issue_id}/defease", payload, headers
        )

    def create_rating_action(self, issue_id, payload, headers):
        return self._request(
            "POST", f"/disclosure/bond-issues/{issue_id}/rating-actions", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Undertaking (PRD §3.2)
    # ------------------------------------------------------------------ #

    def create_undertaking(self, payload, headers):
        return self._request("POST", "/disclosure/undertakings", payload, headers)

    def get_undertaking(self, undertaking_id, headers):
        return self._request("GET", f"/disclosure/undertakings/{undertaking_id}", headers=headers)

    def list_undertakings(self, headers, params=None):
        return self._request("GET", "/disclosure/undertakings", headers=headers, params=params)

    def suspend_undertaking(self, undertaking_id, payload, headers):
        return self._request(
            "POST", f"/disclosure/undertakings/{undertaking_id}/suspend", payload, headers
        )

    def reinstate_undertaking(self, undertaking_id, headers, payload=None):
        return self._request(
            "POST", f"/disclosure/undertakings/{undertaking_id}/reinstate", payload or {}, headers
        )

    # ------------------------------------------------------------------ #
    # ContentRequirement (PRD §3.2)
    # ------------------------------------------------------------------ #

    def create_content_requirement(self, payload, headers):
        return self._request("POST", "/disclosure/content-requirements", payload, headers)

    def get_content_requirement(self, requirement_id, headers):
        return self._request(
            "GET", f"/disclosure/content-requirements/{requirement_id}", headers=headers
        )

    def list_content_requirements(self, headers, params=None):
        return self._request(
            "GET", "/disclosure/content-requirements", headers=headers, params=params
        )

    # ------------------------------------------------------------------ #
    # AnnualReportCycle (PRD §3.3, §3.4)
    # ------------------------------------------------------------------ #

    def create_annual_report_cycle(self, payload, headers):
        return self._request("POST", "/disclosure/annual-report-cycles", payload, headers)

    def get_annual_report_cycle(self, cycle_id, headers):
        return self._request(
            "GET", f"/disclosure/annual-report-cycles/{cycle_id}", headers=headers
        )

    def list_annual_report_cycles(self, headers, params=None):
        return self._request(
            "GET", "/disclosure/annual-report-cycles", headers=headers, params=params
        )

    def assemble_cycle(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/disclosure/annual-report-cycles/{cycle_id}/assemble", payload or {}, headers
        )

    def withdraw_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/disclosure/annual-report-cycles/{cycle_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------------------ #
    # CycleContentItem (PRD §3.3)
    # ------------------------------------------------------------------ #

    def get_content_item(self, item_id, headers):
        return self._request("GET", f"/disclosure/cycle-content-items/{item_id}", headers=headers)

    def list_content_items(self, headers, params=None):
        return self._request(
            "GET", "/disclosure/cycle-content-items", headers=headers, params=params
        )

    def update_content_item(self, item_id, payload, headers):
        return self._request(
            "PATCH", f"/disclosure/cycle-content-items/{item_id}", payload, headers
        )

    def attest_content_item(self, item_id, headers, payload=None):
        return self._request(
            "POST", f"/disclosure/cycle-content-items/{item_id}/attest", payload or {}, headers
        )

    def reopen_content_item(self, item_id, headers, payload=None):
        return self._request(
            "POST", f"/disclosure/cycle-content-items/{item_id}/reopen", payload or {}, headers
        )

    def waive_content_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/disclosure/cycle-content-items/{item_id}/waive", payload, headers
        )

    # ------------------------------------------------------------------ #
    # MaterialEventNotice (PRD §3.5)
    # ------------------------------------------------------------------ #

    def create_material_event_notice(self, payload, headers):
        return self._request("POST", "/disclosure/material-event-notices", payload, headers)

    def get_material_event_notice(self, notice_id, headers):
        return self._request(
            "GET", f"/disclosure/material-event-notices/{notice_id}", headers=headers
        )

    def list_material_event_notices(self, headers, params=None):
        return self._request(
            "GET", "/disclosure/material-event-notices", headers=headers, params=params
        )

    def determine_material_event_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/disclosure/material-event-notices/{notice_id}/determine", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Filing (PRD §3.7)
    # ------------------------------------------------------------------ #

    def create_filing(self, payload, headers):
        return self._request("POST", "/disclosure/filings", payload, headers)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/disclosure/filings/{filing_id}", headers=headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/disclosure/filings", headers=headers, params=params)

    def submit_filing(self, filing_id, headers, payload=None):
        return self._request(
            "POST", f"/disclosure/filings/{filing_id}/submit", payload or {}, headers
        )

    def resubmit_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/disclosure/filings/{filing_id}/resubmit", payload, headers
        )

    def reject_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/disclosure/filings/{filing_id}/reject", payload, headers)

    def confirm_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/disclosure/filings/{filing_id}/confirm", payload, headers)

    # ------------------------------------------------------------------ #
    # FailureToFileEvent (PRD §3.8)
    # ------------------------------------------------------------------ #

    def get_failure_event(self, event_id, headers):
        return self._request(
            "GET", f"/disclosure/failure-to-file-events/{event_id}", headers=headers
        )

    def list_failure_events(self, headers, params=None):
        return self._request(
            "GET", "/disclosure/failure-to-file-events", headers=headers, params=params
        )

    def remediate_failure_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/disclosure/failure-to-file-events/{event_id}/remediate", payload, headers
        )

    # ------------------------------------------------------------------ #
    # DirectPlacement (PRD §3.6)
    # ------------------------------------------------------------------ #

    def create_direct_placement(self, payload, headers):
        return self._request("POST", "/disclosure/direct-placements", payload, headers)

    def get_direct_placement(self, placement_id, headers):
        return self._request(
            "GET", f"/disclosure/direct-placements/{placement_id}", headers=headers
        )

    def list_direct_placements(self, headers, params=None):
        return self._request(
            "GET", "/disclosure/direct-placements", headers=headers, params=params
        )

    def classify_direct_placement(self, placement_id, headers, payload=None):
        return self._request(
            "POST", f"/disclosure/direct-placements/{placement_id}/classify", payload or {}, headers
        )

    # ------------------------------------------------------------------ #
    # OfficialStatement (PRD §3.9)
    # ------------------------------------------------------------------ #

    def create_official_statement(self, payload, headers):
        return self._request("POST", "/disclosure/official-statements", payload, headers)

    def get_official_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/disclosure/official-statements/{statement_id}", headers=headers
        )

    def list_official_statements(self, headers, params=None):
        return self._request(
            "GET", "/disclosure/official-statements", headers=headers, params=params
        )

    def review_official_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/disclosure/official-statements/{statement_id}/compliance-review",
            payload or {},
            headers,
        )

    def post_official_statement(self, statement_id, headers, payload=None):
        return self._request(
            "POST", f"/disclosure/official-statements/{statement_id}/post", payload or {}, headers
        )

    # ------------------------------------------------------------------ #
    # DisseminationEngagement (PRD §3.10)
    # ------------------------------------------------------------------ #

    def create_engagement(self, payload, headers):
        return self._request("POST", "/disclosure/dissemination-engagements", payload, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"/disclosure/dissemination-engagements/{engagement_id}", headers=headers
        )

    def list_engagements(self, headers, params=None):
        return self._request(
            "GET", "/disclosure/dissemination-engagements", headers=headers, params=params
        )

    def acknowledge_calendar(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"/disclosure/dissemination-engagements/{engagement_id}/acknowledge-calendar",
            payload,
            headers,
        )

    def terminate_engagement(self, engagement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/disclosure/dissemination-engagements/{engagement_id}/terminate",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------ #
    # Calendar sweep (PRD §3.11)
    # ------------------------------------------------------------------ #

    def run_calendar_sweep(self, headers, payload=None):
        return self._request("POST", "/disclosure/calendar-sweeps", payload or {}, headers)


api_client = ApiClient()
