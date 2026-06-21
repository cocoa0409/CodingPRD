"""API client: one method per endpoint defined in the PRD.

API surface is mounted under `/lottery` for domain endpoints and
`/_clock` for the test-driving system clock (PRD §2.9 + Endpoint table §4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Districts ----
    def create_district(self, payload, headers):
        return self._request("POST", "/lottery/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/lottery/districts/{district_id}", headers=headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/lottery/districts", headers=headers, params=params)

    def update_district(self, district_id, payload, headers):
        return self._request(
            "PATCH", f"/lottery/districts/{district_id}", payload, headers
        )

    # ---- Schools ----
    def create_school(self, payload, headers):
        return self._request("POST", "/lottery/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/lottery/schools/{school_id}", headers=headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", "/lottery/schools", headers=headers, params=params)

    def update_school(self, school_id, payload, headers):
        return self._request("PATCH", f"/lottery/schools/{school_id}", payload, headers)

    def get_school_acceptance_rate(self, school_id, headers):
        return self._request(
            "GET", f"/lottery/schools/{school_id}/acceptance-rate", headers=headers
        )

    # ---- Boundary Rules ----
    def create_boundary_rule(self, payload, headers):
        return self._request("POST", "/lottery/boundary-rules", payload, headers)

    def get_boundary_rule(self, rule_id, headers):
        return self._request("GET", f"/lottery/boundary-rules/{rule_id}", headers=headers)

    def list_boundary_rules(self, headers, params=None):
        return self._request(
            "GET", "/lottery/boundary-rules", headers=headers, params=params
        )

    # ---- Enrollment Windows ----
    def create_window(self, payload, headers):
        return self._request("POST", "/lottery/windows", payload, headers)

    def get_window(self, window_id, headers):
        return self._request("GET", f"/lottery/windows/{window_id}", headers=headers)

    def list_windows(self, headers, params=None):
        return self._request("GET", "/lottery/windows", headers=headers, params=params)

    def open_window(self, window_id, headers):
        return self._request(
            "POST", f"/lottery/windows/{window_id}/open", {}, headers
        )

    def close_window(self, window_id, headers):
        return self._request(
            "POST", f"/lottery/windows/{window_id}/close", {}, headers
        )

    def run_lottery(self, window_id, payload, headers):
        return self._request(
            "POST", f"/lottery/windows/{window_id}/run-lottery", payload, headers
        )

    def expire_offers(self, window_id, headers):
        return self._request(
            "POST", f"/lottery/windows/{window_id}/expire-offers", {}, headers
        )

    def finalize_window(self, window_id, headers):
        return self._request(
            "POST", f"/lottery/windows/{window_id}/finalize", {}, headers
        )

    # ---- Families & Students ----
    def register_family(self, payload, headers):
        return self._request("POST", "/lottery/families/register", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/lottery/families/{family_id}", headers=headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/lottery/families", headers=headers, params=params)

    def get_family_risk_preview(self, family_id, headers):
        return self._request(
            "GET", f"/lottery/families/{family_id}/risk-preview", headers=headers
        )

    def get_family_risk_final(self, family_id, headers):
        return self._request(
            "GET", f"/lottery/families/{family_id}/risk-final", headers=headers
        )

    def create_student(self, payload, headers):
        return self._request("POST", "/lottery/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/lottery/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/lottery/students", headers=headers, params=params)

    # ---- Sibling Bonds ----
    def create_sibling_bond(self, payload, headers):
        return self._request("POST", "/lottery/sibling-bonds", payload, headers)

    def get_sibling_bond(self, bond_id, headers):
        return self._request(
            "GET", f"/lottery/sibling-bonds/{bond_id}", headers=headers
        )

    def list_sibling_bonds(self, headers, params=None):
        return self._request(
            "GET", "/lottery/sibling-bonds", headers=headers, params=params
        )

    # ---- Applications ----
    def create_application(self, payload, headers):
        return self._request("POST", "/lottery/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/lottery/applications/{application_id}", headers=headers
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", "/lottery/applications", headers=headers, params=params
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/lottery/applications/{application_id}/submit", {}, headers
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/lottery/applications/{application_id}/withdraw", {}, headers
        )

    def reject_application(self, application_id, headers):
        return self._request(
            "POST", f"/lottery/applications/{application_id}/reject", {}, headers
        )

    def get_application_weight_preview(self, application_id, headers):
        return self._request(
            "GET",
            f"/lottery/applications/{application_id}/weight-preview",
            headers=headers,
        )

    # ---- Offers ----
    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/lottery/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/lottery/offers", headers=headers, params=params)

    def accept_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/lottery/offers/{offer_id}/accept", payload, headers
        )

    def decline_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/lottery/offers/{offer_id}/decline", {}, headers
        )

    # ---- Waitlist Entries ----
    def get_waitlist_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/lottery/waitlist-entries/{entry_id}", headers=headers
        )

    def list_waitlist_entries(self, headers, params=None):
        return self._request(
            "GET", "/lottery/waitlist-entries", headers=headers, params=params
        )

    # ---- System clock (test-driving, PRD §2.9) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def get_clock(self, headers):
        return self._request("GET", "/_clock/current", headers=headers)


api_client = ApiClient()
