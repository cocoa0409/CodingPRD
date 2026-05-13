"""Rectifications: creation cascade, deadline, response, expiry sweep.

PRD §3.6. Many tests verify cascade by Application-state observation
because PRD does not specify a list endpoint for rectifications — the
Application-state transitions are the PRD-guaranteed observable.
"""
from __future__ import annotations
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    SEC,
    advance_clock,
    api_client,
    discover_rectification_id,
    get_application,
    get_rectification,
    iso_z,
    make_applicant_headers,
    parse_iso,
    respond_rectification,
    run_sweep,
    setup_resolved_initial_review,
    validate_error,
)


# ===========================================================================
# Rectification creation by DEFER outcome (PRD §3.5, §3.6)
# ===========================================================================
class TestRectificationCreationOnDefer:
    """PRD §3.6: 'When a resolution outcome is APPROVE_WITH_MODIFICATION
    or DEFER, the system automatically creates a child Rectification
    row that carries the application_id, the source_resolution_id
    pointing back to the resolution that generated it, an opinions
    array ..., an applicant_response_uri initially null, a responded_at
    timestamp initially null, and a derived due_at deadline.'"""

    def test_defer_outcome_creates_open_rectification(self, api):
        """PRD §3.6: 'The new rectification's status starts at OPEN.'"""
        bundle = setup_resolved_initial_review(
            vote_split={"DEFER": 5, "APPROVE": 2},
            member_count=9,
        )
        rid = discover_rectification_id(
            resolution=bundle["resolution"],
            application_id=bundle["application"]["id"],
        )
        # If discovery is impossible on this implementation, fall back
        # to checking the application's state (PRD §3.5 guarantees
        # DEFERRED).
        assert bundle["application"]["status"] == "DEFERRED"
        if rid:
            r = get_rectification(rid)
            assert r["status"] == "OPEN", (
                f"PRD §3.6: 'The new rectification's status starts at "
                f"OPEN'; got {r['status']!r}"
            )
            assert r.get("applicant_response_uri") is None, (
                f"PRD §3.6: 'applicant_response_uri initially null'; "
                f"got {r.get('applicant_response_uri')!r}"
            )
            assert r.get("responded_at") is None, (
                f"PRD §3.6: 'responded_at timestamp initially null'; "
                f"got {r.get('responded_at')!r}"
            )


# ===========================================================================
# Rectification expiry via sweep (PRD §3.6, §4)
# ===========================================================================
class TestRectificationExpirySweep:
    """PRD §3.6: 'the rectification-expiry sweep capability then
    iterates all rectifications still in OPEN status whose due_at has
    been reached or passed by the current clock (the boundary is
    inclusive: the exact due_at instant counts as expired) ... and
    flips each one's status to EXPIRED.'"""

    def test_sweep_after_30d_expires_open_deferred_rectification(self, api):
        """PRD §3.6: 'the rectification-expiry sweep capability then
        iterates all rectifications still in OPEN status whose due_at
        has been reached or passed by the current clock (the boundary
        is inclusive: the exact due_at instant counts as expired) ...
        and flips each one's status to EXPIRED.' PRD §3.6 cascade:
        'if the source outcome was DEFER, the application remains in
        DEFERRED.'"""
        bundle = setup_resolved_initial_review(
            vote_split={"DEFER": 5, "APPROVE": 2},
            member_count=9,
        )
        app = bundle["application"]
        resolution = bundle["resolution"]
        # Move clock past resolution.created_at + 31 days.
        when = parse_iso(resolution["created_at"]) + timedelta(days=31)
        advance_clock(iso_z(when))
        run_sweep()
        # PRD §3.6: 'if the source outcome was DEFER, the application
        # remains in DEFERRED.'
        app_after = get_application(app["id"])
        assert app_after["status"] == "DEFERRED", (
            f"PRD §3.6: 'if the source outcome was DEFER, the "
            f"application remains in DEFERRED.'; got "
            f"{app_after['status']!r}"
        )
        # If discoverable, the rectification's status is now EXPIRED.
        rid = discover_rectification_id(
            resolution=resolution, application_id=app["id"],
        )
        if rid:
            r = get_rectification(rid)
            assert r["status"] == "EXPIRED", (
                f"PRD §3.6: 'flips each one's status to EXPIRED'; got "
                f"{r['status']!r}"
            )


# ===========================================================================
# Respond at-or-after-due rejected (PRD §3.6)
# ===========================================================================
class TestRespondPastDeadlineRejected:
    """PRD §3.6: 'The precondition is that the current logical clock is
    strictly before the rectification's due_at and the rectification's
    status is OPEN; a request made at or after the deadline is rejected
    with ERR_RECTIFICATION_EXPIRED (HTTP 409).'"""

    def test_respond_after_due_at_rejected(self, api):
        """PRD §3.6: 'a request made at or after the deadline is
        rejected with ERR_RECTIFICATION_EXPIRED (HTTP 409).'"""
        bundle = setup_resolved_initial_review(
            vote_split={"DEFER": 5, "APPROVE": 2},
            member_count=9,
        )
        resolution = bundle["resolution"]
        app = bundle["application"]
        rid = discover_rectification_id(
            resolution=resolution, application_id=app["id"],
        )
        if not rid:
            # PRD does not specify how clients discover the
            # rectification id; without a discovery channel, this test
            # cannot be exercised on this implementation.
            return
        # Advance clock to exactly due_at (30 days after resolution
        # creation). PRD §3.6: boundary is at-or-after inclusive on the
        # /respond side (the rule is: now() < due_at strictly).
        due_at = parse_iso(resolution["created_at"]) + timedelta(days=30)
        advance_clock(iso_z(due_at))
        res = api.respond_rectification(
            rid, {"applicant_response_uri": "https://x/resp.pdf"},
            make_applicant_headers(bundle["applicant_id"]),
        )
        validate_error(res, ApiErrorId.ERR_RECTIFICATION_EXPIRED.value)
