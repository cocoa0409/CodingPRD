"""HR-binding integrity and JobPosting lifecycle (PRD §3.1, §3.2)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    POSTING_LISTED_TTL_DAYS,
    TEST_EPOCH,
    advance_clock_to,
    approve_posting,
    assert_job_posting,
    bind_hr_user,
    create_company,
    create_job_posting,
    create_job_posting_payload,
    create_live_posting,
    create_verified_company,
    make_hr_user_headers,
    reject_posting_payload,
    reset_clock_to_epoch,
    submit_company_verification,
    submit_posting_review,
    take_posting_off_shelf,
    validate_error,
    validate_success,
)


# ===========================================================================
# HR-binding referential integrity (PRD §2.7 priority 6)
# ===========================================================================
class TestHrBinding:

    def test_unbound_hr_user_cannot_create_job_posting(
        self, api, hr_user_fallback_headers,
    ):
        """PRD §2.7: "HR-binding referential integrity — for any HR-actor
        endpoint, the acting `HrUser` must have `binding_status` equal to
        `ACTIVE` against the target `Company`; otherwise `ERR_HR_NOT_BOUND`."

        Claim: an HrUser whose binding to the target Company is not
        ACTIVE cannot create a JobPosting for that Company.
        """
        company, _bound = create_verified_company()
        # Use the fallback HR header — not bound to this Company.
        resp = api.create_job_posting(
            create_job_posting_payload(company_id=company["id"]),
            hr_user_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_HR_NOT_BOUND.value)

    def test_bound_hr_user_can_create_job_posting(self, api):
        """PRD §2.7: HR-binding integrity passes when the acting HrUser's
        binding to the Company is ACTIVE.

        Claim: a bound HrUser can create a JobPosting; response is 201.
        """
        company, hr_user = create_verified_company()
        resp = api.create_job_posting(
            create_job_posting_payload(company_id=company["id"]),
            make_hr_user_headers(hr_user["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_job_posting(data)
        assert data["posting_status"] == "DRAFT"


# ===========================================================================
# JobPosting create + salary-range guard (PRD §3.2)
# ===========================================================================
class TestJobPostingCreate:

    def test_create_posting_starts_in_draft(self, api):
        """PRD §3.2: "An HR user creates a `JobPosting` in `DRAFT` state
        by supplying the owning `company_id`, the `title`, the
        `description`, the `salary_min_cents`, the `salary_max_cents`,
        and an array of `benefits` tags."

        Claim: creation yields posting_status==DRAFT with the supplied fields.
        """
        company, hr_user = create_verified_company()
        resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"],
                title="Lead Engineer",
                salary_min_cents=10_000_00,
                salary_max_cents=15_000_00,
                benefits=["MEAL", "EQUITY"],
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["posting_status"] == "DRAFT"
        assert data["title"] == "Lead Engineer"
        assert sorted(data["benefits"]) == ["EQUITY", "MEAL"]

    def test_salary_min_greater_than_max_rejected_on_create(self, api):
        """PRD §3.2: "Posting creation enforces the salary range sanity
        check immediately, rejecting submissions where `salary_min_cents`
        is greater than `salary_max_cents`, or where either bound is at
        or below zero, with `ERR_INVALID_SALARY_RANGE`."

        Claim: salary_min_cents > salary_max_cents → ERR_INVALID_SALARY_RANGE.
        """
        company, hr_user = create_verified_company()
        resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"],
                salary_min_cents=20_000_00,
                salary_max_cents=15_000_00,
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SALARY_RANGE.value)

    def test_salary_zero_rejected_on_create(self, api):
        """PRD §3.2: "rejecting submissions ... where either bound is at
        or below zero, with `ERR_INVALID_SALARY_RANGE`."

        Claim: salary_min_cents = 0 → ERR_INVALID_SALARY_RANGE.
        """
        company, hr_user = create_verified_company()
        resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"],
                salary_min_cents=0,
                salary_max_cents=1_000_00,
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SALARY_RANGE.value)

    def test_salary_negative_rejected_on_create(self, api):
        """PRD §3.2: "rejecting submissions ... where either bound is at
        or below zero, with `ERR_INVALID_SALARY_RANGE`."

        Claim: negative salary_max_cents → ERR_INVALID_SALARY_RANGE.
        """
        company, hr_user = create_verified_company()
        resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"],
                salary_min_cents=-100,
                salary_max_cents=1_000_00,
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SALARY_RANGE.value)

    def test_body_unknown_company_id_returns_reference_not_found(
        self, api,
    ):
        """PRD §2.7: "Body foreign-key existence — any body-referenced
        foreign key (for example, `company_id`, `candidate_id`,
        `job_posting_id`, `headhunter_contract_id`, `application_id`,
        `offer_id`) that does not refer to an existing row yields
        `ERR_REFERENCE_NOT_FOUND` (404)."

        Claim: create-job-posting with unknown company_id yields
        ERR_REFERENCE_NOT_FOUND.
        """
        # Use the fallback HR header — we expect the body FK check to
        # surface ERR_REFERENCE_NOT_FOUND.
        resp = api.create_job_posting(
            create_job_posting_payload(company_id=NON_EXISTENT_UUID),
            make_hr_user_headers("hr-fallback-001"),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# Submit-for-review (PRD §3.2)
# ===========================================================================
class TestSubmitReview:

    def test_submit_review_requires_company_verified(self, api):
        """PRD §3.2: "Submitting the posting for review requires the
        owning company to be in `VERIFIED` status..."

        Claim: submit-review against a DRAFT (unverified) company yields
        ERR_INVALID_STATE.
        """
        company = create_company()
        hr_user = bind_hr_user(company["id"])
        # Create posting via the bound HR user, but company is not VERIFIED.
        # The HR-binding check (priority 6) is satisfied; the state-machine
        # precondition fires next.
        posting_resp = api.create_job_posting(
            create_job_posting_payload(company_id=company["id"]),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        resp = api.submit_review_posting(
            posting["id"], make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_submit_review_advances_to_under_review(self, api):
        """PRD §3.2: "On success the row advances from `DRAFT` to
        `UNDER_REVIEW` and the platform computes the `content_fingerprint`."

        Claim: submit-review moves DRAFT → UNDER_REVIEW.
        """
        company, hr_user = create_verified_company()
        posting_resp = api.create_job_posting(
            create_job_posting_payload(company_id=company["id"]),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        resp = api.submit_review_posting(
            posting["id"], make_hr_user_headers(hr_user["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["posting_status"] == "UNDER_REVIEW"


# ===========================================================================
# Approve / reject / revise cycle (PRD §3.2)
# ===========================================================================
class TestPostingApprovalCycle:

    def test_approve_advances_under_review_to_live(self, api):
        """PRD §3.2: "Approval advances `UNDER_REVIEW` to `LIVE`."

        Claim: approve moves UNDER_REVIEW → LIVE.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        assert posting["posting_status"] == "LIVE"

    def test_reject_records_reason(self, api, platform_admin_headers):
        """PRD §3.2: "Rejection advances `UNDER_REVIEW` to `REJECTED` and
        records a categorised `review_rejection_reason` (one of
        `DISCRIMINATORY_WORDING`, `ILLEGAL_TERMS`, `DUPLICATE`, or `OTHER`)."

        Claim: reject moves UNDER_REVIEW → REJECTED and writes the reason.
        """
        company, hr_user = create_verified_company()
        posting_resp = api.create_job_posting(
            create_job_posting_payload(company_id=company["id"]),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        submit_posting_review(posting["id"], hr_user["id"])
        resp = api.reject_posting(
            posting["id"], reject_posting_payload("OTHER"),
            platform_admin_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["posting_status"] == "REJECTED"
        assert data["review_rejection_reason"] == "OTHER"

    def test_revise_clears_rejection_reason(self, api):
        """PRD §3.2: "An HR user may then revise the posting, transitioning
        from `REJECTED` back to `DRAFT` and clearing `review_rejection_reason`."

        Claim: revise moves REJECTED → DRAFT and clears
        review_rejection_reason.
        """
        company, hr_user = create_verified_company()
        posting_resp = api.create_job_posting(
            create_job_posting_payload(company_id=company["id"]),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        submit_posting_review(posting["id"], hr_user["id"])
        # Reject as admin.
        from test_helpers import TEST_USERS
        api.reject_posting(
            posting["id"], reject_posting_payload("OTHER"),
            TEST_USERS["platform_admin_headers"],
        )
        resp = api.revise_posting(
            posting["id"], make_hr_user_headers(hr_user["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["posting_status"] == "DRAFT"
        assert data.get("review_rejection_reason") in (None, "")


# ===========================================================================
# Take-off-shelf (PRD §3.2)
# ===========================================================================
class TestTakeOffShelf:

    def test_take_off_shelf_decrements_active_count(self, api):
        """PRD §3.2: "Both transitions ... decrement the owning company's
        `active_job_posting_count`."

        Claim: take-off-shelf reduces Company.active_job_posting_count by 1.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        # Re-read company to fetch fresh active_job_posting_count.
        from test_helpers import TEST_USERS
        c1 = validate_success(
            api.get_company(company["id"], TEST_USERS["platform_admin_headers"]),
            expected_status=200,
        )
        assert c1["active_job_posting_count"] == 1
        take_posting_off_shelf(posting["id"], hr_user["id"])
        c2 = validate_success(
            api.get_company(company["id"], TEST_USERS["platform_admin_headers"]),
            expected_status=200,
        )
        assert c2["active_job_posting_count"] == 0

    def test_take_off_shelf_sets_off_shelf_at(self, api):
        """PRD §3.2: "Both transitions set `off_shelf_at` to the current
        instant."

        Claim: take-off-shelf populates off_shelf_at.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        out = take_posting_off_shelf(posting["id"], hr_user["id"])
        assert out["posting_status"] == "OFF_SHELF"
        assert out["off_shelf_at"] is not None


# ===========================================================================
# Auto-expiry of LIVE postings (PRD §3.2)
# ===========================================================================
class TestPostingExpiry:

    def test_clock_advance_past_listed_plus_30_days_expires_posting(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: "The clock-advance capability auto-expires the
        posting once the current instant is at or after `listed_at` plus
        thirty days, advancing `LIVE` to `EXPIRED`."

        Claim: clock-advance to listed_at + 30 days transitions LIVE → EXPIRED.
        """
        reset_clock_to_epoch()
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        listed_at = posting["listed_at"]
        # Advance clock by 31 days from TEST_EPOCH (listed_at == TEST_EPOCH).
        advance_clock_to(
            TEST_EPOCH + timedelta(days=POSTING_LISTED_TTL_DAYS + 1),
        )
        data = validate_success(
            api.get_job_posting(posting["id"], platform_admin_headers),
            expected_status=200,
        )
        assert data["posting_status"] == "EXPIRED"


# ===========================================================================
# Posting list filtering (PRD §3.2)
# ===========================================================================
class TestPostingListing:

    def test_filter_by_company_id(self, api, platform_admin_headers):
        """PRD §3.2: "The list endpoint over postings accepts optional
        `company_id`, `posting_status`, and `industry` filters."

        Claim: filtering list_job_postings by company_id returns only
        postings for that company.
        """
        company_a, hr_a = create_verified_company()
        company_b, hr_b = create_verified_company()
        create_live_posting(company_a["id"], hr_a["id"])
        create_live_posting(company_a["id"], hr_a["id"])
        create_live_posting(company_b["id"], hr_b["id"])
        resp = api.list_job_postings(
            platform_admin_headers, params={"company_id": company_a["id"]},
        )
        data = validate_success(resp, expected_status=200)
        assert all(p["company_id"] == company_a["id"] for p in data)
        assert len(data) == 2

    def test_filter_by_posting_status(self, api, platform_admin_headers):
        """PRD §3.2: "The list endpoint over postings accepts optional
        `company_id`, `posting_status`, and `industry` filters."

        Claim: filtering by posting_status returns only matching rows.
        """
        company, hr_user = create_verified_company()
        live_posting = create_live_posting(company["id"], hr_user["id"])
        # Also: create a draft.
        draft_resp = api.create_job_posting(
            create_job_posting_payload(company_id=company["id"], title="Draft One"),
            make_hr_user_headers(hr_user["id"]),
        )
        draft = validate_success(draft_resp, expected_status=201)
        resp = api.list_job_postings(
            platform_admin_headers,
            params={"company_id": company["id"], "posting_status": "LIVE"},
        )
        data = validate_success(resp, expected_status=200)
        ids = {p["id"] for p in data}
        assert live_posting["id"] in ids
        assert draft["id"] not in ids


# ===========================================================================
# Approval guards (PRD §3.2): prohibited content, duplicate, quota
# ===========================================================================
class TestApprovalGuards:

    def test_approve_prohibited_content_returns_prohibited_content(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: "The prohibited-content guard scans the posting body
        against a discriminatory-wording and illegal-terms dictionary; a
        hit yields `ERR_PROHIBITED_CONTENT`."

        Claim: a posting whose description contains a banned discriminatory
        word is rejected at approval with ERR_PROHIBITED_CONTENT.
        """
        company, hr_user = create_verified_company()
        # PRD §3.2 references "discriminatory wording" as the banned-class
        # category. The implementation MUST treat a clearly discriminatory
        # term as prohibited; we use a literal example commonly cited as
        # discriminatory in employment context.
        posting_resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"],
                title="Looking for a young male candidate",
                description=(
                    "We only hire male applicants. Female candidates need "
                    "not apply."
                ),
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        submit_posting_review(posting["id"], hr_user["id"])
        resp = api.approve_posting(posting["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PROHIBITED_CONTENT.value)

    def test_approve_duplicate_fingerprint_returns_duplicate_posting(
        self, api, platform_admin_headers,
    ):
        """PRD §3.2: "The duplicate-posting guard then checks that no other
        `JobPosting` with `posting_status` equal to `LIVE` for the same
        `company_id` shares this row's `content_fingerprint`; if such a
        row exists, the approval is rejected with `ERR_DUPLICATE_POSTING`."

        Claim: a second posting with the same content_fingerprint as an
        existing LIVE one on the same Company → ERR_DUPLICATE_POSTING on
        approve.
        """
        company, hr_user = create_verified_company()
        # First LIVE posting:
        create_live_posting(
            company["id"], hr_user["id"],
            title="Backend Engineer", description="Build backend services.",
        )
        # Second posting with same title+description:
        posting_resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"],
                title="Backend Engineer",
                description="Build backend services.",
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        submit_posting_review(posting["id"], hr_user["id"])
        resp = api.approve_posting(posting["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_POSTING.value)

    def test_approve_at_quota_returns_quota_exceeded(self, api, platform_admin_headers):
        """PRD §3.2: "Approval also gates on the company's posting quota:
        `active_job_posting_count` must be strictly less than
        `posting_quota_limit`, where the strict inequality means that
        equality already means the quota is exhausted and yields
        `ERR_POSTING_QUOTA_EXCEEDED`."

        Claim: at active_job_posting_count == posting_quota_limit (== 5
        for BASIC tier), approve yields ERR_POSTING_QUOTA_EXCEEDED.
        """
        company, hr_user = create_verified_company(verification_tier="BASIC")
        # Take quota to 5.
        for _ in range(5):
            create_live_posting(company["id"], hr_user["id"])
        # Sixth posting:
        posting_resp = api.create_job_posting(
            create_job_posting_payload(
                company_id=company["id"], title="Sixth Role",
                description="The sixth different posting title.",
            ),
            make_hr_user_headers(hr_user["id"]),
        )
        posting = validate_success(posting_resp, expected_status=201)
        submit_posting_review(posting["id"], hr_user["id"])
        resp = api.approve_posting(posting["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_POSTING_QUOTA_EXCEEDED.value)

    def test_approve_below_quota_succeeds(self, api):
        """PRD §3.2: "active_job_posting_count must be strictly less than
        posting_quota_limit."

        Claim: at active_job_posting_count==4 (BASIC quota=5), approving
        the fifth posting succeeds (4 < 5).
        """
        company, hr_user = create_verified_company(verification_tier="BASIC")
        for _ in range(4):
            create_live_posting(company["id"], hr_user["id"])
        posting = create_live_posting(company["id"], hr_user["id"])
        assert posting["posting_status"] == "LIVE"
