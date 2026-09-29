"""One typed method per endpoint of the certification service.

Collections are flat top-level peers, so every path here is rooted at the
service origin with no prefix and no resource nested inside another. Query
parameters are dropped only when they are ``None``; a deliberately invalid value
such as ``limit=0`` is passed through so the request-shape rung can be exercised.
"""

from prd_bench_local_runner.testing import GenericApiClient


def _query(**kwargs):
    return {key: value for key, value in kwargs.items() if value is not None}


class ApiClient(GenericApiClient):
    """HTTP surface of the Smart Home Interoperability Certification API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers=headers,
        )

    def set_clock_raw(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # ------------------------------------------------------------------
    # Specifications
    # ------------------------------------------------------------------

    def create_specification(self, payload, headers=None):
        return self._request("POST", "/specifications", payload, headers=headers)

    def get_specification(self, specification_id, headers=None):
        return self._request(
            "GET", "/specifications/{}".format(specification_id), headers=headers
        )

    def list_specifications(self, headers=None, **params):
        return self._request(
            "GET", "/specifications", headers=headers, params=_query(**params)
        )

    def ratify_specification(self, specification_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/specifications/{}/ratify".format(specification_id),
            payload or {},
            headers=headers,
        )

    def deprecate_specification(self, specification_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/specifications/{}/deprecate".format(specification_id),
            payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Feature sets
    # ------------------------------------------------------------------

    def create_feature_set(self, payload, headers=None):
        return self._request("POST", "/feature-sets", payload, headers=headers)

    def get_feature_set(self, feature_set_id, headers=None):
        return self._request(
            "GET", "/feature-sets/{}".format(feature_set_id), headers=headers
        )

    def list_feature_sets(self, headers=None, **params):
        return self._request(
            "GET", "/feature-sets", headers=headers, params=_query(**params)
        )

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------

    def create_member(self, payload, headers=None):
        return self._request("POST", "/members", payload, headers=headers)

    def get_member(self, member_id, headers=None):
        return self._request("GET", "/members/{}".format(member_id), headers=headers)

    def list_members(self, headers=None, **params):
        return self._request("GET", "/members", headers=headers, params=_query(**params))

    def execute_ip_commitment(self, member_id, payload, headers=None):
        return self._request(
            "POST",
            "/members/{}/ip-commitment".format(member_id),
            payload,
            headers=headers,
        )

    def withdraw_ip_commitment(self, member_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/members/{}/ip-commitment/withdraw".format(member_id),
            payload or {},
            headers=headers,
        )

    def set_tool_access(self, member_id, payload, headers=None):
        return self._request(
            "POST",
            "/members/{}/tool-access".format(member_id),
            payload,
            headers=headers,
        )

    def purchase_credits(self, member_id, payload, headers=None):
        return self._request(
            "POST", "/members/{}/credits".format(member_id), payload, headers=headers
        )

    def get_credit_ledger(self, member_id, headers=None, variant=None):
        return self._request(
            "GET",
            "/members/{}/credit-ledger".format(member_id),
            headers=headers,
            params=_query(variant=variant),
        )

    # ------------------------------------------------------------------
    # Test laboratories
    # ------------------------------------------------------------------

    def create_test_laboratory(self, payload, headers=None):
        return self._request("POST", "/test-laboratories", payload, headers=headers)

    def get_test_laboratory(self, laboratory_id, headers=None):
        return self._request(
            "GET", "/test-laboratories/{}".format(laboratory_id), headers=headers
        )

    def list_test_laboratories(self, headers=None, **params):
        return self._request(
            "GET", "/test-laboratories", headers=headers, params=_query(**params)
        )

    def accreditation_decision(self, laboratory_id, payload, headers=None):
        return self._request(
            "POST",
            "/test-laboratories/{}/accreditation-decision".format(laboratory_id),
            payload,
            headers=headers,
        )

    def competency_review(self, laboratory_id, payload, headers=None):
        return self._request(
            "POST",
            "/test-laboratories/{}/competency-review".format(laboratory_id),
            payload,
            headers=headers,
        )

    def get_competency(self, laboratory_id, headers=None, variant=None):
        return self._request(
            "GET",
            "/test-laboratories/{}/competency".format(laboratory_id),
            headers=headers,
            params=_query(variant=variant),
        )

    # ------------------------------------------------------------------
    # Certification submissions
    # ------------------------------------------------------------------

    def create_submission(self, payload, headers=None):
        return self._request("POST", "/submissions", payload, headers=headers)

    def get_submission(self, submission_id, headers=None):
        return self._request(
            "GET", "/submissions/{}".format(submission_id), headers=headers
        )

    def list_submissions(self, headers=None, **params):
        return self._request(
            "GET", "/submissions", headers=headers, params=_query(**params)
        )

    def submit_submission(self, submission_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/submissions/{}/submit".format(submission_id),
            payload or {},
            headers=headers,
        )

    def start_review(self, submission_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/submissions/{}/start-review".format(submission_id),
            payload or {},
            headers=headers,
        )

    def return_for_info(self, submission_id, payload, headers=None):
        return self._request(
            "POST",
            "/submissions/{}/return-for-info".format(submission_id),
            payload,
            headers=headers,
        )

    def conformance_decision(self, submission_id, payload, headers=None):
        return self._request(
            "POST",
            "/submissions/{}/conformance-decision".format(submission_id),
            payload,
            headers=headers,
        )

    def security_decision(self, submission_id, payload, headers=None):
        return self._request(
            "POST",
            "/submissions/{}/security-decision".format(submission_id),
            payload,
            headers=headers,
        )

    def issue_credential(self, submission_id, payload, headers=None):
        return self._request(
            "POST",
            "/submissions/{}/issue-credential".format(submission_id),
            payload,
            headers=headers,
        )

    def withdraw_submission(self, submission_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/submissions/{}/withdraw".format(submission_id),
            payload or {},
            headers=headers,
        )

    def get_readiness(self, submission_id, headers=None, variant=None):
        return self._request(
            "GET",
            "/submissions/{}/readiness".format(submission_id),
            headers=headers,
            params=_query(variant=variant),
        )

    # ------------------------------------------------------------------
    # Test plans
    # ------------------------------------------------------------------

    def create_test_plan(self, payload, headers=None):
        return self._request("POST", "/test-plans", payload, headers=headers)

    def get_test_plan(self, test_plan_id, headers=None):
        return self._request(
            "GET", "/test-plans/{}".format(test_plan_id), headers=headers
        )

    def list_test_plans(self, headers=None, **params):
        return self._request(
            "GET", "/test-plans", headers=headers, params=_query(**params)
        )

    def issue_test_plan(self, test_plan_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/test-plans/{}/issue".format(test_plan_id),
            payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Test sessions
    # ------------------------------------------------------------------

    def create_test_session(self, payload, headers=None):
        return self._request("POST", "/test-sessions", payload, headers=headers)

    def get_test_session(self, test_session_id, headers=None):
        return self._request(
            "GET", "/test-sessions/{}".format(test_session_id), headers=headers
        )

    def list_test_sessions(self, headers=None, **params):
        return self._request(
            "GET", "/test-sessions", headers=headers, params=_query(**params)
        )

    def start_test_session(self, test_session_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/test-sessions/{}/start".format(test_session_id),
            payload or {},
            headers=headers,
        )

    def append_results(self, test_session_id, payload, headers=None):
        return self._request(
            "POST",
            "/test-sessions/{}/results".format(test_session_id),
            payload,
            headers=headers,
        )

    def complete_test_session(self, test_session_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/test-sessions/{}/complete".format(test_session_id),
            payload or {},
            headers=headers,
        )

    def cancel_test_session(self, test_session_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/test-sessions/{}/cancel".format(test_session_id),
            payload or {},
            headers=headers,
        )

    def dispute_line(self, test_session_id, payload, headers=None):
        return self._request(
            "POST",
            "/test-sessions/{}/dispute-line".format(test_session_id),
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Plugfests
    # ------------------------------------------------------------------

    def create_plugfest(self, payload, headers=None):
        return self._request("POST", "/plugfests", payload, headers=headers)

    def get_plugfest(self, plugfest_id, headers=None):
        return self._request("GET", "/plugfests/{}".format(plugfest_id), headers=headers)

    def list_plugfests(self, headers=None, **params):
        return self._request(
            "GET", "/plugfests", headers=headers, params=_query(**params)
        )

    def lock_plugfest(self, plugfest_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/plugfests/{}/lock".format(plugfest_id),
            payload or {},
            headers=headers,
        )

    def close_plugfest(self, plugfest_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/plugfests/{}/close".format(plugfest_id),
            payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Plugfest participations
    # ------------------------------------------------------------------

    def create_participation(self, payload, headers=None):
        return self._request("POST", "/plugfest-participations", payload, headers=headers)

    def get_participation(self, participation_id, headers=None):
        return self._request(
            "GET",
            "/plugfest-participations/{}".format(participation_id),
            headers=headers,
        )

    def list_participations(self, headers=None, **params):
        return self._request(
            "GET", "/plugfest-participations", headers=headers, params=_query(**params)
        )

    def record_outcome(self, participation_id, payload, headers=None):
        return self._request(
            "POST",
            "/plugfest-participations/{}/record-outcome".format(participation_id),
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Certification listings
    # ------------------------------------------------------------------

    def create_listing(self, payload, headers=None):
        return self._request("POST", "/listings", payload, headers=headers)

    def get_listing(self, listing_id, headers=None):
        return self._request("GET", "/listings/{}".format(listing_id), headers=headers)

    def list_listings(self, headers=None, **params):
        return self._request("GET", "/listings", headers=headers, params=_query(**params))

    def publish_listing(self, listing_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/listings/{}/publish".format(listing_id),
            payload or {},
            headers=headers,
        )

    def withdraw_listing(self, listing_id, payload, headers=None):
        return self._request(
            "POST",
            "/listings/{}/withdraw".format(listing_id),
            payload,
            headers=headers,
        )

    def report_firmware_revision(self, listing_id, payload, headers=None):
        return self._request(
            "POST",
            "/listings/{}/firmware-revisions".format(listing_id),
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Noncompliance cases
    # ------------------------------------------------------------------

    def create_noncompliance_case(self, payload, headers=None):
        return self._request("POST", "/noncompliance-cases", payload, headers=headers)

    def get_noncompliance_case(self, case_id, headers=None):
        return self._request(
            "GET", "/noncompliance-cases/{}".format(case_id), headers=headers
        )

    def list_noncompliance_cases(self, headers=None, **params):
        return self._request(
            "GET", "/noncompliance-cases", headers=headers, params=_query(**params)
        )

    def advance_case(self, case_id, payload, headers=None):
        return self._request(
            "POST",
            "/noncompliance-cases/{}/advance".format(case_id),
            payload,
            headers=headers,
        )

    def close_case(self, case_id, payload=None, headers=None):
        return self._request(
            "POST",
            "/noncompliance-cases/{}/close".format(case_id),
            payload or {},
            headers=headers,
        )


# A single shared client; the runner supplies API_BASE_URL.
api_client = ApiClient()
