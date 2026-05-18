"""PRD §3.1 — TradelineItem creation and field semantics.

Covers:
- Tradeline seeded with reported_dofd_day = original_dofd_day.
- verification_status starts at UNVERIFIED.
- fico_calculation recomputes on create.
- Account ref uniqueness per (credit_report_id, furnisher_id).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_extra_tradeline,
    assert_tradeline_item,
    create_consumer,
    create_credit_report,
    create_furnisher,
    create_tradeline_item,
    create_tradeline_item_payload,
    get_credit_report,
    make_furnisher_headers,
    setup_consumer_furnisher_report_tradeline,
    validate_success,
)


# ===========================================================================
# Tradeline seeding semantics — PRD §3.1
# ===========================================================================
class TestTradelineSeeding:

    def test_reported_dofd_starts_equal_to_original(self, api):
        """PRD §3.1: 'On creation, the server copies original_dofd_day
        into reported_dofd_day'."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        assert_tradeline_item(t)
        assert t["reported_dofd_day"] == t["original_dofd_day"]

    def test_verification_status_starts_unverified(self, api):
        """PRD §3.1: 'sets verification_status to UNVERIFIED'."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        assert t["verification_status"] == "UNVERIFIED"

    def test_fico_recomputes_on_tradeline_create(self, api):
        """PRD §3.1: 'immediately recomputes the owning report's
        fico_score per §3.5.'

        Claim: creating a LATE_90 tradeline with balance 500_000 cents
        drives the report's fico_score away from the seeded 300."""
        c = create_consumer()
        f = create_furnisher()
        r = create_credit_report(c["id"], bureau="EQUIFAX")
        # Seeded score is 300 per PRD §3.1.
        assert r["fico_score"] == 300
        create_tradeline_item(
            r["id"], furnisher_id=f["id"],
            furnisher_headers=make_furnisher_headers(f["id"]),
            original_dofd_day=100, balance_cents=500_000,
            payment_status="LATE_90",
        )
        r2 = get_credit_report(c["id"], r["id"])
        # With one LATE_90 tradeline the score is recomputed by §3.5
        # and must lie strictly above 300 (LATE_90 contributes
        # payment_score=20; utilization_score=50; etc.). Both two
        # PRD-only readers arrive at the same conclusion: the score
        # moves off the initial 300 floor.
        assert r2["fico_score"] > 300, (
            "fico_score must be recomputed and move off 300 after "
            "tradeline create per PRD §3.1 + §3.5"
        )


# ===========================================================================
# Account-ref uniqueness — PRD §3.1
# ===========================================================================
class TestAccountRefUniqueness:

    def test_duplicate_account_ref_same_report_and_furnisher_rejected(self, api):
        """PRD §3.1: 'the furnisher-side account_ref (which must be
        unique per (credit_report_id, furnisher_id))'.

        A second tradeline with the same (credit_report_id,
        furnisher_id, account_ref) must be rejected. PRD §5 lists no
        specific error_id for the duplication, so we accept any 4xx
        with a structured error envelope."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        same_ref = t["account_ref"]
        res = api.create_tradeline_item(
            r["id"],
            create_tradeline_item_payload(
                furnisher_id=f["id"],
                account_ref=same_ref,
            ),
            make_furnisher_headers(f["id"]),
        )
        assert res.status_code >= 400, (
            f"Duplicate account_ref must be rejected, got HTTP "
            f"{res.status_code}"
        )
        body = res.json()
        assert body.get("response_type") == "error"


# ===========================================================================
# GET tradeline — PRD §4
# ===========================================================================
class TestGetTradeline:

    def test_get_round_trip(self, api):
        """PRD §4: GET
        /credit_reports/{rid}/tradeline_items/{tid}. Returns the
        TradelineItem with all PRD-declared fields."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        from test_helpers import TEST_USERS
        res = api.get_tradeline_item(
            r["id"], t["id"], TEST_USERS["bureau_operator_headers"],
        )
        got = validate_success(res, 200)
        assert got["id"] == t["id"]
        assert_tradeline_item(got)
