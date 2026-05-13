"""Concurrency and optimistic-concurrency control (PRD §2.4, §2.11)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    REV,
    REV_ALT,
    assert_exactly_one_succeeds,
    create_rights_holder,
    create_share,
    create_work_draft,
    make_rights_holder_headers,
    patch_share_payload,
    run_race,
    setup_approved_recording_work,
    submit_work,
    take_review,
    validate_error,
    validate_success,
)


class TestVersionConflict:

    def test_stale_version_on_share_patch_rejected(self, api):
        """PRD §2.4: 'When the client supplies version, the server
        compares it against the current row's version; a mismatch is
        rejected with ERR_VERSION_CONFLICT (HTTP 409).'

        Claim: PATCH share with stale version → ERR_VERSION_CONFLICT (409).
        """
        h, work, share = setup_approved_recording_work()
        # First, advance the share's version with one successful PATCH.
        validate_success(api.patch_share(
            work["id"], share["id"],
            patch_share_payload(share_percent=80.00),
            make_rights_holder_headers(h["id"]),
        ), 200)
        # Now PATCH again with the ORIGINAL share's version (now stale).
        resp = api.patch_share(
            work["id"], share["id"],
            patch_share_payload(share_percent=60.00, version=share["version"]),
            make_rights_holder_headers(h["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value, 409)


class TestRaceConditions:

    def test_two_approvals_serialise(self, api):
        """PRD §2.11: 'Two RegistrationReviewer approvals on the same
        work race; exactly one succeeds. The loser sees the work no
        longer in UNDER_REVIEW and receives ERR_INVALID_STATE (HTTP
        409).'

        Claim: two concurrent POST /royalty/works/{id}/approve calls
        produce exactly one 2xx success and one 4xx failure.
        """
        h = create_rights_holder()
        work = create_work_draft(h["id"], rights_type="RECORDING")
        create_share(work["id"], h["id"], h["id"], 100.00)
        submit_work(work["id"], h["id"])
        take_review(work["id"])
        results = run_race(
            lambda: api.approve_work(work["id"], REV),
            lambda: api.approve_work(work["id"], REV_ALT),
        )
        assert_exactly_one_succeeds(results[0], results[1])
