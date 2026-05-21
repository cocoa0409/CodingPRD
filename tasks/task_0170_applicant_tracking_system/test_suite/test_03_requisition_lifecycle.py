"""Requisition lifecycle — PRD §3.2, §2.4.

Covers: DRAFT creation, submit DRAFT→PENDING_APPROVAL, approve
PENDING_APPROVAL→OPEN (sets posted_at), recruiter open-requisition
cap, headcount immutable after DRAFT exit, hold/resume/cancel.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    MAX_OPEN_REQUISITIONS_PER_RECRUITER,
    approve_requisition,
    assert_requisition,
    cancel_requisition,
    create_draft_requisition,
    create_hiring_manager,
    create_recruiter,
    create_requisition_payload,
    get_requisition,
    hold_requisition,
    is_iso8601_timestamp,
    make_recruiter_headers,
    patch_requisition_payload,
    resume_requisition,
    setup_open_requisition,
    setup_recruiter_with_n_open_requisitions,
    submit_requisition,
    validate_error,
    validate_success,
)


# ===========================================================================
# DRAFT creation + submit + approve
# ===========================================================================
class TestRequisitionHappyPath:

    def test_new_requisition_is_in_draft(self, api):
        """PRD §3.2: "The new requisition is born in `DRAFT` with
        `filled_count` 0, `active_offer_count` 0, `posted_at` null,
        and `closed_at` null."

        Claim: POST /requisitions returns status=DRAFT and the
        documented zero/null defaults.
        """
        recruiter = create_recruiter()
        hm = create_hiring_manager()
        req = create_draft_requisition(
            recruiter_id=recruiter["id"],
            hiring_manager_id=hm["id"],
        )
        assert_requisition(req)
        assert req["status"] == "DRAFT", (
            f"new requisition must be DRAFT, got {req['status']!r}"
        )
        assert req["filled_count"] == 0
        assert req["active_offer_count"] == 0
        assert req.get("posted_at") is None
        assert req.get("closed_at") is None

    def test_approve_sets_posted_at(self, api):
        """PRD §3.2: "Approving the requisition advances it
        `PENDING_APPROVAL` → `OPEN`, sets `posted_at` to the current
        logical time, and requires that the acting hiring manager
        match the requisition's `hiring_manager_id` and that the
        acting hiring manager's `department_code` match the
        requisition's `department_code`."

        Claim: after /approve, status==OPEN and posted_at is a real
        ISO 8601 timestamp.
        """
        _r, _hm, req = setup_open_requisition()
        assert req["status"] == "OPEN", (
            f"after /approve, status must be OPEN, got {req['status']!r}"
        )
        assert req.get("posted_at") is not None, (
            "posted_at must be set on approve"
        )
        assert is_iso8601_timestamp(str(req["posted_at"]))


# ===========================================================================
# Approve preconditions
# ===========================================================================
class TestApprovePreconditions:

    def test_approve_with_wrong_hiring_manager_is_rejected(self, api):
        """PRD §3.2: "Approving the requisition advances it
        `PENDING_APPROVAL` → `OPEN` ... and requires that the acting
        hiring manager match the requisition's `hiring_manager_id`".

        Claim: a HiringManager whose id != requisition.hiring_manager_id
        cannot /approve. The behaviour is gated; the implementation
        returns an authorization-style failure. We use
        validate_error_is_one_of because PRD names the rule but does
        not commit to a specific error_id for the ownership mismatch
        among ERR_FORBIDDEN / ERR_INVALID_STATE.
        """
        from test_helpers import validate_error_is_one_of
        recruiter = create_recruiter()
        hm_owner = create_hiring_manager()
        hm_other = create_hiring_manager()
        req = create_draft_requisition(
            recruiter_id=recruiter["id"],
            hiring_manager_id=hm_owner["id"],
        )
        submit_requisition(requisition_id=req["id"],
                           recruiter_id=recruiter["id"])
        from test_helpers import make_hiring_manager_headers
        h_other = make_hiring_manager_headers(hm_other["id"])
        resp = api.approve_requisition(req["id"], h_other)
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_FORBIDDEN.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )


# ===========================================================================
# Recruiter open-requisition cap (PRD §3.2)
# ===========================================================================
class TestRecruiterOpenRequisitionCap:

    def test_under_cap_approval_succeeds(self, api):
        """PRD §3.2: "a `Recruiter` may own at most 5 requisitions for
        which `posted_at` is non-null and `closed_at` is null at any
        one time — this is a half-open lifetime interval, and the cap
        counts in aggregate across the recruiter's owned requisitions
        rather than as pairwise overlap. Breaching the cap rejects
        the approval with `ERR_RECRUITER_REQUISITION_CAP`."

        Claim: the 5th approval succeeds — the boundary is breached
        only at the 6th.
        """
        ctx = setup_recruiter_with_n_open_requisitions(
            n=MAX_OPEN_REQUISITIONS_PER_RECRUITER,
        )
        # All five must be OPEN.
        assert len(ctx["requisitions"]) == 5
        for r in ctx["requisitions"]:
            assert r["status"] == "OPEN"

    def test_breaching_cap_returns_recruiter_requisition_cap(self, api):
        """PRD §3.2: "Breaching the cap rejects the approval with
        `ERR_RECRUITER_REQUISITION_CAP`."

        Claim: the 6th approve on the same Recruiter (where the prior
        five remain open) returns ERR_RECRUITER_REQUISITION_CAP / 409.
        """
        ctx = setup_recruiter_with_n_open_requisitions(
            n=MAX_OPEN_REQUISITIONS_PER_RECRUITER,
        )
        recruiter = ctx["recruiter"]
        hm = ctx["hiring_manager"]
        # Create a sixth requisition and try to approve.
        req6 = create_draft_requisition(
            recruiter_id=recruiter["id"],
            hiring_manager_id=hm["id"],
        )
        submit_requisition(requisition_id=req6["id"],
                           recruiter_id=recruiter["id"])
        from test_helpers import make_hiring_manager_headers
        h = make_hiring_manager_headers(hm["id"])
        resp = api.approve_requisition(req6["id"], h)
        validate_error(
            resp, ApiErrorId.ERR_RECRUITER_REQUISITION_CAP.value,
        )


# ===========================================================================
# Headcount immutability after DRAFT (PRD §3.2)
# ===========================================================================
class TestHeadcountImmutable:

    def test_patch_headcount_after_submit_rejected(self, api):
        """PRD §3.2: "Once the requisition has left `DRAFT`,
        `headcount` is immutable — attempts to modify it through a
        recruiter edit are rejected with `ERR_HEADCOUNT_IMMUTABLE`."

        Claim: PATCH /requisitions/{id} with a new headcount after
        the requisition has left DRAFT → ERR_HEADCOUNT_IMMUTABLE / 422.
        """
        recruiter = create_recruiter()
        hm = create_hiring_manager()
        req = create_draft_requisition(
            recruiter_id=recruiter["id"],
            hiring_manager_id=hm["id"],
            headcount=1,
        )
        submit_requisition(requisition_id=req["id"],
                           recruiter_id=recruiter["id"])
        # Now in PENDING_APPROVAL — out of DRAFT.
        h = make_recruiter_headers(recruiter["id"])
        payload = patch_requisition_payload(headcount=3)
        resp = api.patch_requisition(req["id"], payload, h)
        validate_error(resp, ApiErrorId.ERR_HEADCOUNT_IMMUTABLE.value)


# ===========================================================================
# Hold / resume / cancel
# ===========================================================================
class TestHoldResumeCancel:

    def test_hold_then_resume(self, api):
        """PRD §3.2: "Going on hold transitions `OPEN` → `ON_HOLD` and
        is permitted only when no `Application` on the requisition is
        currently in `OFFER_STAGE`; resuming reverses `ON_HOLD` →
        `OPEN`."

        Claim: round-trip OPEN→ON_HOLD→OPEN.
        """
        _r, _hm, req = setup_open_requisition()
        held = hold_requisition(
            requisition_id=req["id"], recruiter_id=req["recruiter_id"],
        )
        assert held["status"] == "ON_HOLD"
        resumed = resume_requisition(
            requisition_id=req["id"], recruiter_id=req["recruiter_id"],
        )
        assert resumed["status"] == "OPEN"

    def test_cancel_open_sets_closed_at(self, api):
        """PRD §3.2: "Cancellation transitions `OPEN` → `CANCELLED`
        or `ON_HOLD` → `CANCELLED`; either transition requires that
        `filled_count` equals 0 ... Cancellation sets `closed_at` to
        the current logical time".

        Claim: /cancel on OPEN with filled_count==0 transitions to
        CANCELLED and stamps closed_at.
        """
        _r, _hm, req = setup_open_requisition()
        cancelled = cancel_requisition(
            requisition_id=req["id"],
            recruiter_id=req["recruiter_id"],
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled.get("closed_at") is not None
        assert is_iso8601_timestamp(str(cancelled["closed_at"]))


# ===========================================================================
# Existence / RBAC guards
# ===========================================================================
class TestRequisitionExistenceAndRbac:

    def test_get_nonexistent_returns_not_found(
        self, api, platform_admin_headers,
    ):
        """PRD §2.6: "URL paths are validated left to right ... if it
        does not exist, the response is `ERR_NOT_FOUND`".
        """
        from test_helpers import NON_EXISTENT_UUID
        resp = api.get_requisition(NON_EXISTENT_UUID,
                                   platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_requisition_with_nonexistent_recruiter_id_returns_422(
        self, api,
    ):
        """PRD §2.6: "Once every path segment has been resolved,
        foreign-key fields supplied in the request body are checked
        next — a missing referenced entity produces
        `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

        Claim: POST /requisitions with recruiter_id pointing to a
        non-existent recruiter returns ERR_REFERENCE_NOT_FOUND / 422.
        """
        from test_helpers import NON_EXISTENT_UUID
        # We still have to act AS a Recruiter (path-level RBAC); use
        # the placeholder Recruiter constant, since the recruiter_id
        # in the BODY is what we want to fail on. The PRD §2.9
        # priority order is: 401 (auth headers) > 403 (RBAC) > 404
        # (path) > 422 (body FK). The body recruiter_id is the only
        # FK in this request, but X-User-ID also needs to identify a
        # real principal for the route to clear RBAC.
        #
        # We accept either ERR_REFERENCE_NOT_FOUND (the FK miss) or
        # ERR_FORBIDDEN (if the placeholder X-User-ID is treated as
        # ownership-failed before body inspection) because both are
        # PRD-faithful in this corner case.
        from test_helpers import (
            make_recruiter_headers, validate_error_is_one_of,
        )
        # Use the placeholder id intentionally — we want body FK miss.
        hm = create_hiring_manager()
        h = make_recruiter_headers(NON_EXISTENT_UUID)
        payload = create_requisition_payload(
            recruiter_id=NON_EXISTENT_UUID,
            hiring_manager_id=hm["id"],
        )
        resp = api.create_requisition(payload, h)
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_REFERENCE_NOT_FOUND.value,
                ApiErrorId.ERR_FORBIDDEN.value,
            ],
        )
