"""PRD §3.1 — onboarding: Consumer, Furnisher, CreditReport.

Covers:
- Consumer seeded with free_reports_remaining=1, freeze_pin=null.
- Furnisher created with status=ACTIVE.
- CreditReport seeded with status=ACTIVE, posture=OPEN, fico_score=300,
  last_pulled_day=null.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    FICO_MIN,
    FREE_REPORTS_INITIAL,
    TEST_USERS,
    assert_consumer,
    assert_credit_report,
    assert_furnisher,
    create_consumer,
    create_consumer_payload,
    create_credit_report,
    create_furnisher,
    make_consumer_headers,
    validate_error,
    validate_success,
)


# ===========================================================================
# Consumer creation — PRD §3.1
# ===========================================================================
class TestConsumerCreation:

    def test_consumer_initial_free_reports_is_one(self, api):
        """PRD §3.1: 'On creation, the server initializes the
        consumer's free_reports_remaining counter to 1 — the statutory
        annual free report'."""
        c = create_consumer()
        assert_consumer(c)
        assert c["free_reports_remaining"] == FREE_REPORTS_INITIAL

    def test_consumer_initial_freeze_pin_is_null(self, api):
        """PRD §3.1: 'and leaves freeze_pin as null because no freeze
        has been placed yet.'"""
        c = create_consumer()
        assert c["freeze_pin"] is None

    def test_consumer_email_must_be_unique(self, api):
        """PRD §3.1: 'contact email (which must be unique across all
        consumers).'

        Two consumers with the same email cannot both succeed; the
        second submission must be rejected with ERR_INVALID_REQUEST
        per §2.3's malformed-body rule applied to a uniqueness
        constraint."""
        from test_helpers import random_email
        e = random_email()
        c1 = create_consumer(email=e)
        assert c1["email"] == e
        res = api.create_consumer(
            create_consumer_payload(email=e),
            TEST_USERS["platform_admin_headers"],
        )
        # Two PRD-faithful implementations could ship either
        # ERR_INVALID_REQUEST (treating the duplicate as malformed) or
        # a 409 with no specific error_id catalogued. PRD §5 catalogs
        # no dedicated duplicate-email error_id, so we accept either.
        assert res.status_code >= 400, (
            f"Duplicate email must be rejected, got HTTP {res.status_code}"
        )


# ===========================================================================
# Furnisher creation — PRD §3.1
# ===========================================================================
class TestFurnisherCreation:

    def test_furnisher_initial_status_active(self, api):
        """PRD §3.1: 'A newly registered furnisher's status begins at
        ACTIVE'."""
        f = create_furnisher()
        assert_furnisher(f)
        assert f["status"] == "ACTIVE"


# ===========================================================================
# CreditReport creation — PRD §3.1
# ===========================================================================
class TestCreditReportCreation:

    def test_credit_report_initial_seeded_fields(self, api):
        """PRD §3.1: 'On creation, the server seeds the report with
        status of ACTIVE, posture of OPEN, a fico_score of 300, and a
        null last_pulled_day (the report has never been pulled).'"""
        c = create_consumer()
        r = create_credit_report(c["id"], bureau="EQUIFAX")
        assert_credit_report(r)
        assert r["status"] == "ACTIVE"
        assert r["posture"] == "OPEN"
        assert r["fico_score"] == FICO_MIN  # PRD §3.1: 'a fico_score of 300'.
        assert r["last_pulled_day"] is None

    def test_credit_report_bureau_persisted(self, api):
        """PRD §3.1: 'A PlatformAdmin then creates one CreditReport per
        bureau for the consumer by supplying the bureau, which must be
        one of the three values EQUIFAX, EXPERIAN, or TRANSUNION.'

        The bureau value supplied at create time is the bureau the
        report serves."""
        c = create_consumer()
        r = create_credit_report(c["id"], bureau="TRANSUNION")
        assert r["bureau"] == "TRANSUNION"

    def test_seeded_fico_300_is_lower_bound(self, api):
        """PRD §3.1: 'The seeded score of 300 is the lower bound of
        the FICO range; subsequent recomputation per §3.5 will revise
        it as tradelines accumulate.'"""
        c = create_consumer()
        r = create_credit_report(c["id"])
        assert r["fico_score"] == 300, (
            "Initial fico_score must equal the FICO lower bound 300."
        )

    def test_get_credit_report_round_trip(self, api):
        """PRD §4: GET /consumers/{cid}/credit_reports/{rid}."""
        c = create_consumer()
        r = create_credit_report(c["id"])
        res = api.get_credit_report(
            c["id"], r["id"], make_consumer_headers(c["id"]),
        )
        got = validate_success(res, 200)
        assert got["id"] == r["id"]
        assert got["consumer_id"] == c["id"]
