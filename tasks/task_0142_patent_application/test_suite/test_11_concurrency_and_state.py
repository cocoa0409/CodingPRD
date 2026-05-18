"""Concurrency, OCC, and state-precondition tests.

Covers PRD §2.5 (OCC), §2.10 (concurrency semantics for state-affecting
operations), and §2.11 (validation priority).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_applicant,
    create_application_payload,
    create_draft_application,
    file_application,
    make_applicant_headers,
    pay_filing_fees,
    run_race,
    setup_allowed_application,
    setup_filed_application,
    setup_under_examination,
    validate_error,
    validate_success,
)


# ===========================================================================
# OCC version conflict (PRD §2.5)
# ===========================================================================
class TestOCCVersionConflict:

    def test_patch_application_stale_version_yields_version_conflict(self, api):
        """PRD §2.5: "if a version value is supplied, it must equal the
        entity's current version exactly, and any other value causes
        the request to be rejected with ERR_VERSION_CONFLICT (HTTP
        409)."
        """
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(a)
        v0 = app["version"]
        first = api.patch_application(
            app["id"], {"title": "t1", "version": v0},
            make_applicant_headers(a["id"]),
        )
        validate_success(first, 200)
        res = api.patch_application(
            app["id"], {"title": "t2", "version": v0},
            make_applicant_headers(a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)


# ===========================================================================
# State-affecting concurrency (PRD §2.10)
# ===========================================================================
class TestRaceConditions:

    def test_two_examiners_begin_examination_race(self, api, examiner_headers, examiner_headers_alt):
        """PRD §2.10: "Two examiners simultaneously beginning examination
        on the same FILED application serialise on the application's
        status and version. At most one transition to UNDER_EXAMINATION
        succeeds; the loser receives ERR_INVALID_STATE because the
        application's status is no longer FILED at commit time."
        """
        from test_helpers import examination_fee_cents, pay_fee
        a, app = setup_filed_application()
        pay_fee(a, app, "EXAMINATION", examination_fee_cents(a["entity_size"]))
        results = run_race(
            lambda: api.begin_examination(app["id"], examiner_headers),
            lambda: api.begin_examination(app["id"], examiner_headers_alt),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # The loser must be ERR_INVALID_STATE per PRD §2.10.
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value, (
            "PRD §2.10: loser of begin-examination race must receive "
            "ERR_INVALID_STATE"
        )

    def test_two_grant_calls_race_on_allowed_application(self, api, examiner_headers, examiner_headers_alt):
        """PRD §2.10: "Two grant calls racing on the same ALLOWED
        application after the issue fee has been paid serialise on the
        application's status and version. At most one transition to
        GRANTED succeeds; the loser receives ERR_INVALID_STATE."
        """
        from test_helpers import issue_fee_cents, pay_fee
        a, allowed = setup_allowed_application()
        pay_fee(a, allowed, "ISSUE", issue_fee_cents(a["entity_size"]))
        results = run_race(
            lambda: api.grant_application(allowed["id"], examiner_headers),
            lambda: api.grant_application(allowed["id"], examiner_headers_alt),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_INVALID_STATE.value, (
            "PRD §2.10: loser of grant race must receive ERR_INVALID_STATE"
        )


# ===========================================================================
# State precondition / segregation of duties (PRD §2.11)
# ===========================================================================
class TestInvalidState:

    def test_grant_from_filed_rejected_invalid_state(self, api, examiner_headers):
        """PRD §2.11: "(6) state-machine preconditions yield
        ERR_INVALID_STATE".

        Claim: an Examiner /grant call on a FILED (not ALLOWED)
        application yields ERR_INVALID_STATE.
        """
        a, app = setup_filed_application()
        res = api.grant_application(app["id"], examiner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_allow_from_filed_rejected_invalid_state(self, api, examiner_headers):
        """PRD §2.11 priority 6: state-precondition violation yields
        ERR_INVALID_STATE."""
        a, app = setup_filed_application()
        res = api.allow_application(app["id"], examiner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_file_already_filed_rejected_invalid_state(self, api):
        """PRD §2.11 priority 6: re-filing on a FILED application is a
        state violation."""
        a, app = setup_filed_application()
        res = api.file_application(app["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
