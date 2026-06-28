"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock (test-driving) ────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── License classes ─────────────────────────────────────────────────
    def create_license_class(self, payload, headers):
        return self._request("POST", "/license-classes", payload, headers)

    def get_license_class(self, class_id, headers):
        return self._request("GET", f"/license-classes/{class_id}", headers=headers)

    def list_license_classes(self, headers, params=None):
        return self._request("GET", "/license-classes", headers=headers, params=params)

    # ─── Quota regions ───────────────────────────────────────────────────
    def create_quota_region(self, payload, headers):
        return self._request("POST", "/quota-regions", payload, headers)

    def get_quota_region(self, region_id, headers):
        return self._request("GET", f"/quota-regions/{region_id}", headers=headers)

    def list_quota_regions(self, headers, params=None):
        return self._request("GET", "/quota-regions", headers=headers, params=params)

    def quota_status(self, region_id, headers, params=None):
        return self._request(
            "GET", f"/quota-regions/{region_id}/quota-status", headers=headers, params=params
        )

    def set_moratorium(self, region_id, payload, headers):
        return self._request(
            "PATCH", f"/quota-regions/{region_id}/moratorium", payload, headers
        )

    # ─── Applicants ──────────────────────────────────────────────────────
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def list_applicant_premises(self, applicant_id, headers, params=None):
        return self._request(
            "GET", f"/applicants/{applicant_id}/premises", headers=headers, params=params
        )

    def list_applicant_applications(self, applicant_id, headers, params=None):
        return self._request(
            "GET", f"/applicants/{applicant_id}/applications", headers=headers, params=params
        )

    def list_applicant_transfer_requests(self, applicant_id, headers, params=None):
        return self._request(
            "GET", f"/applicants/{applicant_id}/transfer-requests", headers=headers, params=params
        )

    # ─── Premises ────────────────────────────────────────────────────────
    def create_premise(self, payload, headers):
        return self._request("POST", "/premises", payload, headers)

    def get_premise(self, premise_id, headers):
        return self._request("GET", f"/premises/{premise_id}", headers=headers)

    def list_premise_transfer_requests(self, premise_id, headers, params=None):
        return self._request(
            "GET", f"/premises/{premise_id}/transfer-requests", headers=headers, params=params
        )

    # ─── License applications ────────────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/license-applications", payload, headers)

    def get_application(self, app_id, headers):
        return self._request("GET", f"/license-applications/{app_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/license-applications", headers=headers, params=params)

    def submit_application(self, app_id, payload, headers):
        return self._request(
            "POST", f"/license-applications/{app_id}/submit", payload, headers
        )

    def begin_review(self, app_id, headers):
        return self._request(
            "POST", f"/license-applications/{app_id}/begin-review", {}, headers
        )

    def open_protest_period(self, app_id, headers):
        return self._request(
            "POST", f"/license-applications/{app_id}/open-protest-period", {}, headers
        )

    def approve_application(self, app_id, headers):
        return self._request(
            "POST", f"/license-applications/{app_id}/approve", {}, headers
        )

    def issue_application(self, app_id, headers):
        return self._request(
            "POST", f"/license-applications/{app_id}/issue", {}, headers
        )

    def deny_application(self, app_id, headers):
        return self._request(
            "POST", f"/license-applications/{app_id}/deny", {}, headers
        )

    def withdraw_application(self, app_id, headers):
        return self._request(
            "POST", f"/license-applications/{app_id}/withdraw", {}, headers
        )

    def pay_fee(self, app_id, payload, headers):
        return self._request(
            "POST", f"/license-applications/{app_id}/pay-fee", payload, headers
        )

    # ─── Background checks ────────────────────────────────────────────────
    def list_application_background_checks(self, app_id, headers, params=None):
        return self._request(
            "GET", f"/license-applications/{app_id}/background-checks", headers=headers, params=params
        )

    def get_background_check(self, bc_id, headers):
        return self._request("GET", f"/background-checks/{bc_id}", headers=headers)

    def resolve_background_check(self, bc_id, payload, headers):
        return self._request(
            "POST", f"/background-checks/{bc_id}/resolve", payload, headers
        )

    # ─── Zoning reviews ──────────────────────────────────────────────────
    def list_application_zoning_reviews(self, app_id, headers, params=None):
        return self._request(
            "GET", f"/license-applications/{app_id}/zoning-reviews", headers=headers, params=params
        )

    def get_zoning_review(self, zr_id, headers):
        return self._request("GET", f"/zoning-reviews/{zr_id}", headers=headers)

    def decide_zoning_review(self, zr_id, payload, headers):
        return self._request(
            "POST", f"/zoning-reviews/{zr_id}/decide", payload, headers
        )

    # ─── Protests & hearings ─────────────────────────────────────────────
    def create_protest(self, payload, headers):
        return self._request("POST", "/protests", payload, headers)

    def get_protest(self, protest_id, headers):
        return self._request("GET", f"/protests/{protest_id}", headers=headers)

    def list_application_protests(self, app_id, headers, params=None):
        return self._request(
            "GET", f"/license-applications/{app_id}/protests", headers=headers, params=params
        )

    def schedule_hearing(self, protest_id, payload, headers):
        return self._request(
            "POST", f"/protests/{protest_id}/schedule-hearing", payload, headers
        )

    def withdraw_protest(self, protest_id, headers):
        return self._request(
            "POST", f"/protests/{protest_id}/withdraw", {}, headers
        )

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def list_protest_hearings(self, protest_id, headers, params=None):
        return self._request(
            "GET", f"/protests/{protest_id}/hearings", headers=headers, params=params
        )

    def list_application_hearings(self, app_id, headers, params=None):
        return self._request(
            "GET", f"/license-applications/{app_id}/hearings", headers=headers, params=params
        )

    def render_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/hearings/{hearing_id}/render", payload, headers
        )

    # ─── Licenses & renewal ──────────────────────────────────────────────
    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def check_renewal_window(self, license_id, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/check-renewal-window", {}, headers
        )

    def renew_license(self, license_id, payload, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/renew", payload, headers
        )

    def reinstate_license(self, license_id, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/reinstate", {}, headers
        )

    def pay_fine(self, license_id, payload, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/pay-fine", payload, headers
        )

    def list_license_server_permits(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/licenses/{license_id}/server-permits", headers=headers, params=params
        )

    def list_license_violations(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/licenses/{license_id}/violations", headers=headers, params=params
        )

    def list_license_administrative_actions(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/licenses/{license_id}/administrative-actions", headers=headers, params=params
        )

    def list_license_compliance_reports(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/licenses/{license_id}/compliance-reports", headers=headers, params=params
        )

    def list_license_transfer_requests(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/licenses/{license_id}/transfer-requests", headers=headers, params=params
        )

    # ─── Server permits ──────────────────────────────────────────────────
    def create_server_permit(self, payload, headers):
        return self._request("POST", "/server-permits", payload, headers)

    def get_server_permit(self, permit_id, headers):
        return self._request("GET", f"/server-permits/{permit_id}", headers=headers)

    def activate_server_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/server-permits/{permit_id}/activate", payload, headers
        )

    def revoke_server_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/server-permits/{permit_id}/revoke", {}, headers
        )

    def check_permit_expiry(self, permit_id, headers):
        return self._request(
            "POST", f"/server-permits/{permit_id}/check-expiry", {}, headers
        )

    # ─── Violations & administrative actions ─────────────────────────────
    def create_violation(self, payload, headers):
        return self._request("POST", "/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def contest_violation(self, violation_id, headers):
        return self._request(
            "POST", f"/violations/{violation_id}/contest", {}, headers
        )

    def sustain_violation(self, violation_id, payload, headers):
        return self._request(
            "POST", f"/violations/{violation_id}/sustain", payload, headers
        )

    def dismiss_violation(self, violation_id, headers):
        return self._request(
            "POST", f"/violations/{violation_id}/dismiss", {}, headers
        )

    def get_administrative_action(self, action_id, headers):
        return self._request(
            "GET", f"/administrative-actions/{action_id}", headers=headers
        )

    def list_violation_administrative_actions(self, violation_id, headers, params=None):
        return self._request(
            "GET", f"/violations/{violation_id}/administrative-actions", headers=headers, params=params
        )

    def enforce_action(self, action_id, headers):
        return self._request(
            "POST", f"/administrative-actions/{action_id}/enforce", {}, headers
        )

    # ─── Compliance reports ──────────────────────────────────────────────
    def create_compliance_report(self, payload, headers):
        return self._request("POST", "/compliance-reports", payload, headers)

    def get_compliance_report(self, report_id, headers):
        return self._request("GET", f"/compliance-reports/{report_id}", headers=headers)

    # ─── Transfer requests ───────────────────────────────────────────────
    def create_transfer_request(self, payload, headers):
        return self._request("POST", "/transfer-requests", payload, headers)

    def get_transfer_request(self, transfer_id, headers):
        return self._request("GET", f"/transfer-requests/{transfer_id}", headers=headers)

    def approve_transfer_request(self, transfer_id, headers):
        return self._request(
            "POST", f"/transfer-requests/{transfer_id}/approve", {}, headers
        )

    def reject_transfer_request(self, transfer_id, headers):
        return self._request(
            "POST", f"/transfer-requests/{transfer_id}/reject", {}, headers
        )


api_client = ApiClient()
