"""Match review: segregation of duties, sample-size floor, weight bounds,
and RBAC denials (PRD §2.9, §3.5, §2.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_benchmark,
    analyst_headers,
    bootstrap_org,
    create_active_vendor,
    create_job_payload,
    create_open_survey,
    make_analyst_headers,
    make_manager_headers,
    propose_match,
    validate_error,
    validate_success,
)

VENDOR_ADMIN = TEST_USERS["vendor_admin_headers"]
BOOTSTRAP_MGR = {"X-User-ID": "emp_mgr_bootstrap", "X-User-Role": "CompManager"}


def _reviewed_match(api, sample_size=50):
    """OPEN survey + benchmark + PROPOSED->REVIEWED match."""
    bundle = bootstrap_org()
    vendor = create_active_vendor(bundle)
    survey = create_open_survey(bundle, vendor)
    benchmark = add_benchmark(bundle, survey, sample_size=sample_size)
    match = propose_match(bundle, survey, bundle["job"], benchmark)
    reviewed = validate_success(api.review_match(
        match["id"], make_manager_headers(bundle["manager"]["id"])))
    return bundle, match, reviewed


class TestMatchSegregationOfDuties:
    def test_self_approval_rejected_with_sod_violation(self, api):
        """PRD §2.9: "The person who approves a survey job match must not be
        the person who proposed it, and the person who approves a market
        adjustment must not be the person who proposed it."
        PRD §2.9: "Both checks compare the caller's `X-User-ID` against the
        record's `proposed_by_employee_id`, and both reject a self-approval
        with `ERR_SOD_VIOLATION` (HTTP 409)."

        Design: Corner/rbac/sod_match_approve_same_user_rejected
        """
        bundle, match, _ = _reviewed_match(api)
        # Approver identity equals the proposer's Employee id.
        resp = api.approve_match(
            match["id"], make_manager_headers(bundle["analyst"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    def test_sod_fires_before_sample_size_floor(self, api):
        """PRD §3.5: "From `REVIEWED`, approval moves the match to `APPROVED`
        and enforces two checks in ladder order: segregation of duties first,
        so the approving `X-User-ID` must differ from the match's
        `proposed_by_employee_id` (`ERR_SOD_VIOLATION`), then the statistical
        floor requiring the benchmark's `sample_size` to be at least 5
        (`ERR_SAMPLE_SIZE_TOO_SMALL`)."

        Both guards fail here (approver == proposer, sample_size 3); the
        ladder order makes SoD the surfaced error.

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_sample_size_on_match_approve
        """
        bundle, match, _ = _reviewed_match(api, sample_size=3)
        resp = api.approve_match(
            match["id"], make_manager_headers(bundle["analyst"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    def test_sample_size_floor_fires_when_sod_satisfied(self, api):
        """PRD §3.5: "then the statistical floor requiring the benchmark's
        `sample_size` to be at least 5 (`ERR_SAMPLE_SIZE_TOO_SMALL`)."

        With a distinct approver, the SoD guard passes and the sample-size
        floor is the rejecting guard.

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_sample_size_on_match_approve
        """
        bundle, match, _ = _reviewed_match(api, sample_size=3)
        resp = api.approve_match(
            match["id"], make_manager_headers(bundle["manager"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SAMPLE_SIZE_TOO_SMALL)


class TestSampleSizeBoundary:
    def test_sample_size_exactly_five_allows_approve(self, api):
        """PRD §3.5: "the statistical floor requiring the benchmark's
        `sample_size` to be at least 5 (`ERR_SAMPLE_SIZE_TOO_SMALL`)."

        sample_size == 5 satisfies "at least 5" and approval succeeds.

        Design: Difficulty/boundary_precision_check/sample_size_exactly_five_allows_approve
        """
        bundle, match, _ = _reviewed_match(api, sample_size=5)
        approved = validate_success(api.approve_match(
            match["id"], make_manager_headers(bundle["manager"]["id"])))
        assert approved["status"] == "APPROVED"
        assert approved["reviewer_employee_id"] == bundle["manager"]["id"], (
            "Approval stamps reviewer_employee_id with the approver's identity")

    def test_sample_size_four_rejected(self, api):
        """PRD §3.5: "the statistical floor requiring the benchmark's
        `sample_size` to be at least 5 (`ERR_SAMPLE_SIZE_TOO_SMALL`)."

        sample_size == 4 is one below the floor and is rejected.

        Design: Difficulty/boundary_precision_check/sample_size_exactly_five_allows_approve
        """
        bundle, match, _ = _reviewed_match(api, sample_size=4)
        resp = api.approve_match(
            match["id"], make_manager_headers(bundle["manager"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SAMPLE_SIZE_TOO_SMALL)


class TestMatchWeightBounds:
    def test_invalid_match_weight_rejected(self, api):
        """PRD §3.5: "The weight must be an integer from 1 to 100 inclusive;
        an out-of-range or non-integer weight is rejected with
        `ERR_INVALID_WEIGHT` (HTTP 422) both at proposal time and again at
        review time."

        Design: Corner/validations/invalid_match_weight_rejected
        """
        bundle = bootstrap_org()
        vendor = create_active_vendor(bundle)
        survey = create_open_survey(bundle, vendor)
        benchmark = add_benchmark(bundle, survey)
        resp = api.create_match(
            survey["id"],
            {"job_id": bundle["job"]["id"], "benchmark_id": benchmark["id"],
             "match_confidence": "HIGH", "match_weight_pct": 101,
             "proposed_by_employee_id": bundle["analyst"]["id"]},
            analyst_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_INVALID_WEIGHT)


class TestMatchRbac:
    def test_analyst_cannot_approve_match(self, api):
        """PRD §2.1: "a caller whose role is valid but not permitted for the
        requested endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."
        PRD §4: "`/matches/{id}/approve` | Manager approves a REVIEWED match
        (SoD enforced) | CompManager".

        Design: Corner/endpoints/analyst_cannot_approve_match
        """
        bundle, match, _ = _reviewed_match(api)
        resp = api.approve_match(match["id"], analyst_headers(bundle))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_vendor_admin_cannot_create_job(self, api):
        """PRD §2.1: "a caller whose role is valid but not permitted for the
        requested endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."
        PRD §3.2: "A `CompManager` creates each Job with a `job_code` that is
        unique within the org".

        Design: Corner/endpoints/vendor_admin_cannot_create_job
        """
        bundle = bootstrap_org()
        resp = api.create_job(bundle["org"]["id"],
                              create_job_payload(job_code="ENG.IC9X"),
                              VENDOR_ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
