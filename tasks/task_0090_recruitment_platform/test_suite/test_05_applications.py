"""Application lifecycle, anti-spam rate limit, and cascade behaviour
(PRD §3.4)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    RATE_LIMIT_MAX_PER_WINDOW,
    RATE_LIMIT_WINDOW_SECONDS,
    TEST_EPOCH,
    advance_clock_by,
    advance_clock_to,
    assert_application,
    create_application_payload,
    create_candidate,
    create_live_posting,
    create_verified_company,
    forward_application,
    make_candidate_headers,
    make_hr_user_headers,
    mark_application_read,
    reset_clock_to_epoch,
    submit_application,
    take_posting_off_shelf,
    validate_error,
    validate_success,
    NON_EXISTENT_UUID,
)


# ===========================================================================
# Application creation (PRD §3.4)
# ===========================================================================
class TestApplicationCreate:

    def test_create_application_starts_in_submitted(self, api):
        """PRD §3.4: "The application starts in `application_status`
        `SUBMITTED`..."

        Claim: a new Application is in SUBMITTED.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate()
        application = submit_application(candidate["id"], posting["id"])
        assert_application(application)
        assert application["application_status"] == "SUBMITTED"

    def test_company_id_denormalised_from_posting(self, api):
        """PRD §3.4: "the `company_id` is denormalised from the job
        posting at creation time (and never recomputed thereafter, even
        if the posting later changes ownership)."

        Claim: Application.company_id == JobPosting.company_id at
        creation time.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate()
        application = submit_application(candidate["id"], posting["id"])
        assert application["company_id"] == company["id"]

    def test_create_application_default_source_channel_direct(self, api):
        """PRD §3.4: "a `source_channel` (one of `DIRECT`, `ONE_CLICK`,
        or `HEADHUNTER`, defaulting to `DIRECT`)."

        Claim: omitting source_channel yields source_channel==DIRECT.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate()
        payload = create_application_payload(
            candidate_id=candidate["id"], job_posting_id=posting["id"],
        )
        payload.pop("source_channel", None)
        resp = api.create_application(
            payload, make_candidate_headers(candidate["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["source_channel"] == "DIRECT"

    def test_create_application_unknown_posting_returns_reference_not_found(self, api):
        """PRD §2.7 priority 5: body foreign-key existence — unknown
        `job_posting_id` yields ERR_REFERENCE_NOT_FOUND.

        Claim: applying to a non-existent posting yields ERR_REFERENCE_NOT_FOUND.
        """
        candidate = create_candidate()
        payload = create_application_payload(
            candidate_id=candidate["id"], job_posting_id=NON_EXISTENT_UUID,
        )
        resp = api.create_application(
            payload, make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# Anti-spam rate limit (PRD §3.4, validation priority 15)
# ===========================================================================
class TestCandidateRateLimit:

    def test_sixth_application_in_window_rejected(self, api):
        """PRD §3.4: "the platform counts the candidate's `Application`
        rows whose `created_at` falls in the half-open window starting
        sixty seconds before the current instant and ending strictly
        before the current instant. If that count is already five at the
        time of evaluation — so that persisting the new row would carry
        the count to six — the request is rejected with
        ERR_CANDIDATE_RATE_LIMIT."

        Claim: at count==5 in the rolling 60s window, the sixth submission
        yields ERR_CANDIDATE_RATE_LIMIT (and 429).
        """
        reset_clock_to_epoch()
        # PREMIUM tier so the 6 LIVE postings fit under the posting quota.
        company, hr_user = create_verified_company(verification_tier="PREMIUM")
        # Five distinct LIVE postings.
        postings = [
            create_live_posting(company["id"], hr_user["id"])
            for _ in range(RATE_LIMIT_MAX_PER_WINDOW + 1)
        ]
        candidate = create_candidate()
        for i in range(RATE_LIMIT_MAX_PER_WINDOW):
            ok = api.create_application(
                create_application_payload(
                    candidate_id=candidate["id"],
                    job_posting_id=postings[i]["id"],
                ),
                make_candidate_headers(candidate["id"]),
            )
            validate_success(ok, expected_status=201)
        # Sixth submission within the same 60s window.
        resp = api.create_application(
            create_application_payload(
                candidate_id=candidate["id"],
                job_posting_id=postings[RATE_LIMIT_MAX_PER_WINDOW]["id"],
            ),
            make_candidate_headers(candidate["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CANDIDATE_RATE_LIMIT.value)

    def test_first_application_with_zero_count_succeeds(self, api):
        """PRD §3.4: "the platform counts the candidate's `Application`
        rows whose `created_at` falls in the half-open window starting
        sixty seconds before the current instant and ending strictly
        before the current instant. If that count is already five at the
        time of evaluation ... the request is rejected with
        ERR_CANDIDATE_RATE_LIMIT."

        Claim: at count==0, the first submission always succeeds.
        """
        reset_clock_to_epoch()
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate()
        resp = api.create_application(
            create_application_payload(
                candidate_id=candidate["id"], job_posting_id=posting["id"],
            ),
            make_candidate_headers(candidate["id"]),
        )
        validate_success(resp, expected_status=201)

    def test_decay_past_window_admits_new_submission(self, api):
        """PRD §3.4: "the half-open window starting sixty seconds before
        the current instant and ending strictly before the current instant."
        PRD §3.4: "The window is rolling rather than aligned to wall-clock
        minutes."

        Claim: after the rolling window slides past the first five
        applications, a sixth becomes admissible.
        """
        reset_clock_to_epoch()
        # PREMIUM tier so the 6 LIVE postings fit under the posting quota.
        company, hr_user = create_verified_company(verification_tier="PREMIUM")
        postings = [
            create_live_posting(company["id"], hr_user["id"])
            for _ in range(RATE_LIMIT_MAX_PER_WINDOW + 1)
        ]
        candidate = create_candidate()
        for i in range(RATE_LIMIT_MAX_PER_WINDOW):
            api.create_application(
                create_application_payload(
                    candidate_id=candidate["id"],
                    job_posting_id=postings[i]["id"],
                ),
                make_candidate_headers(candidate["id"]),
            )
        # Advance clock by 61 seconds — the first five fall outside the
        # half-open [now()-60s, now()) window.
        advance_clock_by(RATE_LIMIT_WINDOW_SECONDS + 1)
        resp = api.create_application(
            create_application_payload(
                candidate_id=candidate["id"],
                job_posting_id=postings[RATE_LIMIT_MAX_PER_WINDOW]["id"],
            ),
            make_candidate_headers(candidate["id"]),
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Application HR-driven transitions (PRD §3.4)
# ===========================================================================
class TestApplicationTransitions:

    def test_mark_read_advances_submitted_to_read(self, api):
        """PRD §3.4: "Marking the application as read transitions
        `SUBMITTED` to `READ`, sets `read_at` to the current instant,
        and requires the parent `JobPosting` to still be in
        `posting_status` `LIVE`."

        Claim: mark-read moves SUBMITTED → READ and stamps read_at.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate()
        application = submit_application(candidate["id"], posting["id"])
        resp = api.mark_application_read(
            application["id"], make_hr_user_headers(hr_user["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["application_status"] == "READ"
        assert data["read_at"] is not None

    def test_forward_advances_read_to_forwarded(self, api):
        """PRD §3.4: "Forwarding the application internally transitions
        `READ` to `FORWARDED`, sets `forwarded_at` to the current instant."

        Claim: forward moves READ → FORWARDED and stamps forwarded_at.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate()
        application = submit_application(candidate["id"], posting["id"])
        mark_application_read(application["id"], hr_user["id"])
        resp = api.forward_application(
            application["id"], make_hr_user_headers(hr_user["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["application_status"] == "FORWARDED"
        assert data["forwarded_at"] is not None

    def test_reject_from_submitted_moves_to_rejected(self, api):
        """PRD §3.4: "Rejecting the application transitions any
        non-terminal state to `REJECTED`..."

        Claim: HR reject on a SUBMITTED application moves it to REJECTED.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate()
        application = submit_application(candidate["id"], posting["id"])
        resp = api.reject_application(
            application["id"], make_hr_user_headers(hr_user["id"]),
        )
        data = validate_success(resp, expected_status=200)
        assert data["application_status"] == "REJECTED"

    def test_invalid_transition_returns_invalid_state(self, api):
        """PRD §2.7: "State machine — the target resource must be in a
        state from which the requested transition is declared; otherwise
        `ERR_INVALID_STATE`."

        Claim: marking a REJECTED application read yields ERR_INVALID_STATE.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        candidate = create_candidate()
        application = submit_application(candidate["id"], posting["id"])
        api.reject_application(
            application["id"], make_hr_user_headers(hr_user["id"]),
        )
        resp = api.mark_application_read(
            application["id"], make_hr_user_headers(hr_user["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Off-shelf cascade (PRD §3.2, §3.4)
# ===========================================================================
class TestApplicationCascadeOnOffShelf:

    def test_take_off_shelf_closes_applications(self, api):
        """PRD §3.2: "every `Application` referencing this posting whose
        `application_status` is in `SUBMITTED`, `READ`, or `FORWARDED`
        moves to `CLOSED`."

        Claim: take-off-shelf moves applications in {SUBMITTED, READ,
        FORWARDED} to CLOSED.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        c1 = create_candidate()
        c2 = create_candidate()
        c3 = create_candidate()
        a1 = submit_application(c1["id"], posting["id"])  # SUBMITTED
        a2 = submit_application(c2["id"], posting["id"])
        mark_application_read(a2["id"], hr_user["id"])    # READ
        a3 = submit_application(c3["id"], posting["id"])
        mark_application_read(a3["id"], hr_user["id"])
        forward_application(a3["id"], hr_user["id"])      # FORWARDED
        take_posting_off_shelf(posting["id"], hr_user["id"])
        for aid in (a1["id"], a2["id"], a3["id"]):
            data = validate_success(
                api.get_application(
                    aid, make_hr_user_headers(hr_user["id"]),
                ),
                expected_status=200,
            )
            assert data["application_status"] == "CLOSED", (
                f"Application {aid} should cascade to CLOSED, "
                f"got {data['application_status']}"
            )
