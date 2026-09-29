"""
Endpoint client for the standards-development consensus API.

One method per endpoint in the PRD's endpoint table. Every method returns the raw
response so tests can assert on status codes as well as bodies. Headers are always
explicit — there is no implicit "current user".
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """HTTP surface of the standards-development consensus API."""

    # ------------------------------------------------------------ generic escape
    def call(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        """Send an arbitrary request; used by access-control and path tests."""
        return self._request(method, path, payload, headers)

    # -------------------------------------------------------------- participants
    def create_participant(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/participants", params or {}, headers
        )

    def get_participant(self, participant_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/participants/{participant_id}", None, headers
        )

    # ---------------------------------------------------------------- committees
    def create_committee(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/committees", payload, headers)

    def list_committees(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/committees", params or {}, headers)

    def get_committee(self, committee_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/committees/{committee_id}", None, headers
        )

    def activate_committee(self, committee_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/committees/{committee_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    # --------------------------------------------------------------- memberships
    def create_membership(self, committee_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/committees/{committee_id}/memberships",
            payload,
            headers,
        )

    def list_memberships(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/memberships", params or {}, headers)

    def get_membership(self, membership_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/memberships/{membership_id}", None, headers
        )

    def update_membership(self, membership_id, payload, headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/memberships/{membership_id}", payload, headers
        )

    # ---------------------------------------------------------------- work items
    def create_work_item(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/work-items", payload, headers)

    def list_work_items(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/work-items", params or {}, headers)

    def get_work_item(self, work_item_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/work-items/{work_item_id}", None, headers
        )

    def approve_scope(self, work_item_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/work-items/{work_item_id}/approve-scope",
            payload,
            headers,
        )

    def create_draft(self, work_item_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/work-items/{work_item_id}/drafts", payload, headers
        )

    def publish_work_item(self, work_item_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/work-items/{work_item_id}/publish",
            payload if payload is not None else {},
            headers,
        )

    def periodic_review(self, work_item_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/work-items/{work_item_id}/periodic-review",
            payload,
            headers,
        )

    # -------------------------------------------------------------------- drafts
    def list_drafts(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/drafts", params or {}, headers)

    def get_draft(self, draft_id, headers):
        return self._request("GET", f"{API_PREFIX}/drafts/{draft_id}", None, headers)

    # ------------------------------------------------------------------- ballots
    def create_ballot(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/ballots", payload, headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/ballots", params or {}, headers)

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"{API_PREFIX}/ballots/{ballot_id}", None, headers)

    def close_ballot(self, ballot_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/ballots/{ballot_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def cast_vote(self, ballot_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/ballots/{ballot_id}/votes", payload, headers
        )

    # --------------------------------------------------------------------- votes
    def list_votes(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/votes", params or {}, headers)

    def get_vote(self, vote_id, headers):
        return self._request("GET", f"{API_PREFIX}/votes/{vote_id}", None, headers)

    def update_vote(self, vote_id, payload, headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/votes/{vote_id}", payload, headers
        )

    def adjudicate_vote(self, vote_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/votes/{vote_id}/adjudicate", payload, headers
        )

    # ------------------------------------------------------------ public reviews
    def create_public_review(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/public-reviews", payload, headers)

    def list_public_reviews(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/public-reviews", params or {}, headers
        )

    def get_public_review(self, public_review_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/public-reviews/{public_review_id}", None, headers
        )

    def close_public_review(self, public_review_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/public-reviews/{public_review_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def approve_disposition(self, public_review_id, headers, payload=None):
        return self._request(
            "POST",
            f"{API_PREFIX}/public-reviews/{public_review_id}/approve-disposition",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------ comments
    def create_comment(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/comments", payload, headers)

    def list_comments(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/comments", params or {}, headers)

    def get_comment(self, comment_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/comments/{comment_id}", None, headers
        )

    def dispose_comment(self, comment_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/comments/{comment_id}/disposition", payload, headers
        )

    # -------------------------------------------------------- patent disclosures
    def create_patent_disclosure(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/patent-disclosures", payload, headers
        )

    def list_patent_disclosures(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/patent-disclosures", params or {}, headers
        )

    def get_patent_disclosure(self, disclosure_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/patent-disclosures/{disclosure_id}", None, headers
        )

    def submit_commitment(self, disclosure_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/patent-disclosures/{disclosure_id}/commitment",
            payload,
            headers,
        )

    # ------------------------------------------------------------------- appeals
    def create_appeal(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/appeals", params or {}, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"{API_PREFIX}/appeals/{appeal_id}", None, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/appeals/{appeal_id}/decide", payload, headers
        )

    # --------------------------------------------------------- maintenance items
    def create_maintenance_item(self, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/maintenance-items", payload, headers
        )

    def list_maintenance_items(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/maintenance-items", params or {}, headers
        )

    def get_maintenance_item(self, maintenance_item_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/maintenance-items/{maintenance_item_id}", None, headers
        )

    def resolve_maintenance_item(self, maintenance_item_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/maintenance-items/{maintenance_item_id}/resolve",
            payload,
            headers,
        )

    # ------------------------------------------------------------- logical clock
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)
