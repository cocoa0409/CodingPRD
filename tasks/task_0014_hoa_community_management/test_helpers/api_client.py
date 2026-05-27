"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted under the root path `/hoa` per PRD §4.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Community ───────────────────────────────────────────────────
    def create_community(self, payload, headers):
        return self._request("POST", "/hoa/communities", payload, headers)

    def get_community(self, community_id, headers):
        return self._request(
            "GET", f"/hoa/communities/{community_id}", headers=headers,
        )

    # ── Owner ───────────────────────────────────────────────────────
    def create_owner(self, payload, headers):
        return self._request("POST", "/hoa/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request(
            "GET", f"/hoa/owners/{owner_id}", headers=headers,
        )

    def list_owners(self, headers, params=None):
        return self._request(
            "GET", "/hoa/owners", headers=headers, params=params,
        )

    # ── Property ────────────────────────────────────────────────────
    def create_property(self, payload, headers):
        return self._request("POST", "/hoa/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request(
            "GET", f"/hoa/properties/{property_id}", headers=headers,
        )

    def list_properties(self, headers, params=None):
        return self._request(
            "GET", "/hoa/properties", headers=headers, params=params,
        )

    # ── Assessment & Payment ────────────────────────────────────────
    def create_assessment(self, payload, headers):
        return self._request("POST", "/hoa/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/hoa/assessments/{assessment_id}", headers=headers,
        )

    def list_assessments(self, headers, params=None):
        return self._request(
            "GET", "/hoa/assessments", headers=headers, params=params,
        )

    def get_projected_balance(self, assessment_id, as_of_iso8601, headers):
        return self._request(
            "GET", f"/hoa/assessments/{assessment_id}/projected-balance",
            headers=headers, params={"as_of_iso8601": as_of_iso8601},
        )

    def waive_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/hoa/assessments/{assessment_id}/waive", {}, headers,
        )

    def create_payment(self, payload, headers):
        return self._request("POST", "/hoa/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request(
            "GET", "/hoa/payments", headers=headers, params=params,
        )

    def get_payment(self, payment_id, headers):
        return self._request(
            "GET", f"/hoa/payments/{payment_id}", headers=headers,
        )

    def reverse_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/hoa/payments/{payment_id}/reverse", {}, headers,
        )

    # ── Violation ───────────────────────────────────────────────────
    def create_violation(self, payload, headers):
        return self._request("POST", "/hoa/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request(
            "GET", f"/hoa/violations/{violation_id}", headers=headers,
        )

    def list_violations(self, headers, params=None):
        return self._request(
            "GET", "/hoa/violations", headers=headers, params=params,
        )

    def contest_violation(self, violation_id, headers):
        return self._request(
            "POST", f"/hoa/violations/{violation_id}/contest", {}, headers,
        )

    def uphold_violation(self, violation_id, headers):
        return self._request(
            "POST", f"/hoa/violations/{violation_id}/uphold", {}, headers,
        )

    def dismiss_violation(self, violation_id, headers):
        return self._request(
            "POST", f"/hoa/violations/{violation_id}/dismiss", {}, headers,
        )

    def pay_violation_fine(self, violation_id, headers):
        return self._request(
            "POST", f"/hoa/violations/{violation_id}/pay-fine", {}, headers,
        )

    # ── ACC Requests ────────────────────────────────────────────────
    def create_acc_request(self, payload, headers):
        return self._request("POST", "/hoa/acc-requests", payload, headers)

    def get_acc_request(self, acc_id, headers):
        return self._request(
            "GET", f"/hoa/acc-requests/{acc_id}", headers=headers,
        )

    def list_acc_requests(self, headers, params=None):
        return self._request(
            "GET", "/hoa/acc-requests", headers=headers, params=params,
        )

    def approve_acc_request(self, acc_id, headers):
        return self._request(
            "POST", f"/hoa/acc-requests/{acc_id}/approve", {}, headers,
        )

    def reject_acc_request(self, acc_id, headers):
        return self._request(
            "POST", f"/hoa/acc-requests/{acc_id}/reject", {}, headers,
        )

    def request_revision_acc(self, acc_id, headers):
        return self._request(
            "POST", f"/hoa/acc-requests/{acc_id}/request-revision", {}, headers,
        )

    def resubmit_acc_request(self, acc_id, headers):
        return self._request(
            "POST", f"/hoa/acc-requests/{acc_id}/resubmit", {}, headers,
        )

    def withdraw_acc_request(self, acc_id, headers):
        return self._request(
            "POST", f"/hoa/acc-requests/{acc_id}/withdraw", {}, headers,
        )

    # ── BoardElection & Vote ────────────────────────────────────────
    def create_election(self, payload, headers):
        return self._request("POST", "/hoa/elections", payload, headers)

    def get_election(self, election_id, headers):
        return self._request(
            "GET", f"/hoa/elections/{election_id}", headers=headers,
        )

    def list_elections(self, headers, params=None):
        return self._request(
            "GET", "/hoa/elections", headers=headers, params=params,
        )

    def open_election(self, election_id, expected_community_version, headers):
        return self._request(
            "POST", f"/hoa/elections/{election_id}/open",
            {"expected_community_version": expected_community_version}, headers,
        )

    def close_election(self, election_id, headers):
        return self._request(
            "POST", f"/hoa/elections/{election_id}/close", {}, headers,
        )

    def certify_election(self, election_id, headers):
        return self._request(
            "POST", f"/hoa/elections/{election_id}/certify", {}, headers,
        )

    def invalidate_election(self, election_id, headers):
        return self._request(
            "POST", f"/hoa/elections/{election_id}/invalidate", {}, headers,
        )

    def create_vote(self, payload, headers):
        return self._request("POST", "/hoa/votes", payload, headers)

    def list_votes(self, headers, params=None):
        return self._request(
            "GET", "/hoa/votes", headers=headers, params=params,
        )

    def get_vote(self, vote_id, headers):
        return self._request(
            "GET", f"/hoa/votes/{vote_id}", headers=headers,
        )

    def retract_vote(self, vote_id, headers):
        return self._request(
            "POST", f"/hoa/votes/{vote_id}/retract", {}, headers,
        )

    # ── Lien ────────────────────────────────────────────────────────
    def get_lien(self, lien_id, headers):
        return self._request(
            "GET", f"/hoa/liens/{lien_id}", headers=headers,
        )

    def list_liens(self, headers, params=None):
        return self._request(
            "GET", "/hoa/liens", headers=headers, params=params,
        )

    def satisfy_lien(self, lien_id, headers):
        return self._request(
            "POST", f"/hoa/liens/{lien_id}/satisfy", {}, headers,
        )

    def initiate_foreclosure(self, lien_id, headers):
        return self._request(
            "POST", f"/hoa/liens/{lien_id}/initiate-foreclosure", {}, headers,
        )

    # ── ReserveComponent & ReserveStudy ─────────────────────────────
    def create_reserve_component(self, payload, headers):
        return self._request(
            "POST", "/hoa/reserve-components", payload, headers,
        )

    def list_reserve_components(self, headers, params=None):
        return self._request(
            "GET", "/hoa/reserve-components",
            headers=headers, params=params,
        )

    def get_reserve_component(self, component_id, headers):
        return self._request(
            "GET", f"/hoa/reserve-components/{component_id}", headers=headers,
        )

    def create_reserve_study(self, payload, headers):
        return self._request(
            "POST", "/hoa/reserve-studies", payload, headers,
        )

    def get_reserve_study(self, study_id, headers):
        return self._request(
            "GET", f"/hoa/reserve-studies/{study_id}", headers=headers,
        )

    def list_reserve_studies(self, headers, params=None):
        return self._request(
            "GET", "/hoa/reserve-studies", headers=headers, params=params,
        )

    # ── Clock (test-driving) ────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/hoa/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )


api_client = ApiClient()
