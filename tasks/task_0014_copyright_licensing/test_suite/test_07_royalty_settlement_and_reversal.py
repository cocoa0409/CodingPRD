"""Royalty statement settlement, reversal, and the advance-recoupment
invariant under reversal (PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_royalty_dual_variant_scenario,
    setup_effective_license,
    create_final_statement,
    settle_statement,
    reverse_statement,
    royalty_statement_payload,
    emit_event_payload,
    unique_event_id,
    make_rights_holder_headers,
    ADMIN_HEADERS,
)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

class TestRoyaltySettlement:
    """PRD §3.7: "Settlement happens when a payment processor emits a
    PAYMENT_RECEIVED event ... the event's payload.amount_cents must equal
    the statement's net_payable_cents exactly (ERR_PAYMENT_AMOUNT_MISMATCH
    otherwise) ... On success the statement transitions from DRAFT to
    SETTLED, settled_at is stamped to the current instant, and the license's
    cumulative_advance_recouped_cents is increased by exactly the
    advance_recouped_cents of this statement."
    """

    def test_payment_amount_mismatch_rejected(self, api):
        """PRD §3.7: payload.amount_cents != net_payable_cents → ERR_PAYMENT_AMOUNT_MISMATCH."""
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        s = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        # Wrong amount.
        payload = emit_event_payload(
            source="PAYMENT",
            event_type="PAYMENT_RECEIVED",
            ref_entity="RoyaltyStatement",
            ref_id=s["id"],
            payload={"amount_cents": s["net_payable_cents"] + 1, "currency": "USD"},
            external_event_id=unique_event_id("pay-mismatch"),
        )
        resp = api.emit_event(payload, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)

    def test_payment_correct_amount_settles_and_increments_ledger(self, api):
        """PRD §3.7: settled statement increases cumulative_advance_recouped_cents."""
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        s = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        before = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        settle_statement(api, s)
        after = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        assert after["cumulative_advance_recouped_cents"] == \
            before["cumulative_advance_recouped_cents"] + s["advance_recouped_cents"], (
            f"PRD §3.7: cumulative_advance_recouped_cents must increment by "
            f"advance_recouped_cents={s['advance_recouped_cents']}; "
            f"before={before['cumulative_advance_recouped_cents']}, "
            f"after={after['cumulative_advance_recouped_cents']}"
        )
        # Statement now SETTLED with settled_at stamped.
        from test_helpers import get_royalty_statement
        s_after = get_royalty_statement(api, license_data["id"], s["id"])
        assert s_after["status"] == "SETTLED"
        assert s_after.get("settled_at") is not None


# ---------------------------------------------------------------------------
# Reversal
# ---------------------------------------------------------------------------

class TestRoyaltyReversal:
    """PRD §3.7: "Reversal is the inverse, and is the only operation that
    may transition a SETTLED statement to a terminal REVERSED. ... reversal_of_id
    must resolve to a SETTLED statement on the same license, and refund_cents
    must be non-null on a reversal entry (a non-resolving reversal_of_id is
    rejected with ERR_INVALID_REVERSAL). ... the original statement must
    still be in SETTLED (otherwise ERR_INVALID_STATE). On success the
    original statement's status flips to REVERSED, and the license's
    cumulative_advance_recouped_cents is decreased by exactly the original
    statement's advance_recouped_cents."
    """

    def test_reversal_pointer_to_non_settled_rejected(self, api):
        """PRD §3.7: reversal_of_id must point to a SETTLED statement →
        else ERR_INVALID_REVERSAL."""
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        # Create DRAFT statement (NOT settled).
        s = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        # Try to create a reversal pointing at the DRAFT statement.
        headers = make_rights_holder_headers(licensor["id"])
        body = royalty_statement_payload(
            period_start_at="2026-02-01T00:00:00.000Z",
            period_end_at="2026-03-01T00:00:00.000Z",
            gross_revenue_cents=0,
            variant="FINAL",
            reversal_of_id=s["id"],
            refund_cents=s["net_payable_cents"],
        )
        resp = api.create_royalty_statement(license_data["id"], body, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REVERSAL.value)

    def test_reversal_compensates_advance_recoupment_invariant(self, api):
        """PRD §3.7: 'On success the original statement's status flips to
        REVERSED, and the license's cumulative_advance_recouped_cents is
        decreased by exactly the original statement's advance_recouped_cents.'

        # difficulty: compensating_invariant/advance_recoupment_invariant_under_reversal
        """
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        # 1) Create + settle a FINAL statement.
        s = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        assert s["advance_recouped_cents"] == 50_000
        settle_statement(api, s)
        post_settle = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        assert post_settle["cumulative_advance_recouped_cents"] == 50_000

        # 2) Reverse it.
        reverse_statement(api, license_data, licensor, s,
                            refund_cents=s["net_payable_cents"],
                            period_start_at="2026-02-01T00:00:00.000Z",
                            period_end_at="2026-03-01T00:00:00.000Z")

        # 3) Original statement is now REVERSED.
        from test_helpers import get_royalty_statement
        s_after = get_royalty_statement(api, license_data["id"], s["id"])
        assert s_after["status"] == "REVERSED", (
            f"PRD §3.7: original statement must flip to REVERSED; got {s_after['status']}"
        )

        # 4) cumulative_advance_recouped_cents must be back to 0.
        post_reverse = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        assert post_reverse["cumulative_advance_recouped_cents"] == 0, (
            f"PRD §3.7 (advance-recoupment invariant): after settle+reverse the "
            f"cumulative_advance_recouped_cents must equal pre-settle value "
            f"(0 here); got {post_reverse['cumulative_advance_recouped_cents']}"
        )

    def test_invariant_holds_when_only_settled_no_reversal(self, api):
        """PRD §3.7 (advance-recoupment invariant): 'at all times, a license's
        cumulative_advance_recouped_cents equals the sum of advance_recouped_cents
        across its SETTLED statements, less the sum of the original
        advance_recouped_cents of any SETTLED statement that has been paired
        into a REVERSED outcome.'

        With one settle and zero reversals, the invariant reads:
        cumulative == sum(advance_recouped_cents over SETTLED statements).

        # difficulty: compensating_invariant/advance_recoupment_invariant_under_reversal
        """
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        s = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        settle_statement(api, s)
        license_after = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        assert license_after["cumulative_advance_recouped_cents"] == s["advance_recouped_cents"], (
            f"PRD §3.7 (invariant): post-settle cumulative must equal "
            f"sum of SETTLED advance_recouped_cents = {s['advance_recouped_cents']}; "
            f"got {license_after['cumulative_advance_recouped_cents']}"
        )

    def test_refund_amount_mismatch_rejected(self, api):
        """PRD §3.7: 'its payload.amount_cents must equal the reversal entry's
        refund_cents (otherwise ERR_PAYMENT_AMOUNT_MISMATCH).'"""
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        s = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        settle_statement(api, s)

        # Create reversal entry with refund_cents=net_payable_cents.
        headers = make_rights_holder_headers(licensor["id"])
        body = royalty_statement_payload(
            period_start_at="2026-02-01T00:00:00.000Z",
            period_end_at="2026-03-01T00:00:00.000Z",
            gross_revenue_cents=0,
            variant="FINAL",
            reversal_of_id=s["id"],
            refund_cents=s["net_payable_cents"],
        )
        resp = api.create_royalty_statement(license_data["id"], body, headers)
        reversal_entry = validate_success(resp, expected_status=201)

        # PAYMENT_REFUNDED with mismatched amount → ERR_PAYMENT_AMOUNT_MISMATCH.
        bad = emit_event_payload(
            source="PAYMENT",
            event_type="PAYMENT_REFUNDED",
            ref_entity="RoyaltyStatement",
            ref_id=reversal_entry["id"],
            payload={"amount_cents": s["net_payable_cents"] - 1, "currency": "USD"},
            external_event_id=unique_event_id("refund-mismatch"),
        )
        resp = api.emit_event(bad, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)


# ---------------------------------------------------------------------------
# Manual termination blocked by pending settlements
# ---------------------------------------------------------------------------

class TestTerminationPendingSettlements:
    """PRD §3.6: "Manual termination is restricted to the licensor_id ... and
    may proceed only when every RoyaltyStatement for the license is in one
    of SETTLED, REVERSED, or DRAFT — meaning there are no in-flight payment
    events for DRAFT statements. A pending settlement blocks termination
    with ERR_HAS_PENDING_SETTLEMENTS."

    NOTE: PRD prose mentions ERR_HAS_PENDING_SETTLEMENTS only in the context
    of a "pending settlement" — i.e., an in-flight payment. PRD does not name
    the literal-state pre-condition that triggers it; what is testable is the
    error code's existence in §5 and the prose calling it out for in-flight
    settlements. We exercise the documented happy-path (statements in
    {SETTLED, REVERSED, DRAFT} permit termination) and skip the unfaithful
    inverse where PRD does not commit to a synchronous trigger.
    """

    def test_terminate_with_only_draft_settled_reversed_succeeds(self, api):
        """PRD §3.6: 'may proceed only when every RoyaltyStatement for the
        license is in one of SETTLED, REVERSED, or DRAFT.'

        With one SETTLED and one DRAFT statement, termination should succeed.
        """
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        # SETTLED statement
        s1 = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        settle_statement(api, s1)
        # DRAFT statement (never settled) — also acceptable per PRD §3.6.
        create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-02-01T00:00:00.000Z",
            period_end_at="2026-03-01T00:00:00.000Z",
            gross_revenue_cents=500_000,
        )
        license_data = api.get_license(license_data["id"], ADMIN_HEADERS).json()["data"]
        headers = make_rights_holder_headers(licensor["id"])
        resp = api.terminate_license(license_data["id"], headers,
                                       payload={"version": license_data["version"]})
        data = validate_success(resp)
        assert data["status"] == "TERMINATED"


# ---------------------------------------------------------------------------
# Listing royalty statements with status filter
# ---------------------------------------------------------------------------

class TestRoyaltyStatementListing:
    """PRD §3.7: "Statements may also be filtered when listed by their status
    query parameter (along with limit and offset)."
    """

    def test_list_statements_filters_by_status(self, api):
        """PRD §3.7: GET /licenses/{id}/royalty-statements?status=DRAFT
        returns only DRAFT statements."""
        bundle = setup_royalty_dual_variant_scenario(api)
        licensor = bundle["licensor"]
        license_data = bundle["license"]
        s1 = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-01-01T00:00:00.000Z",
            period_end_at="2026-02-01T00:00:00.000Z",
            gross_revenue_cents=1_000_000,
        )
        settle_statement(api, s1)
        s2 = create_final_statement(
            api, license_data, licensor,
            period_start_at="2026-02-01T00:00:00.000Z",
            period_end_at="2026-03-01T00:00:00.000Z",
            gross_revenue_cents=500_000,
        )
        # Filter by DRAFT — must include s2 but not s1.
        resp = api.list_royalty_statements(license_data["id"], ADMIN_HEADERS,
                                            params={"status": "DRAFT", "limit": 100})
        body = resp.json()
        assert resp.status_code == 200
        ids = [r["id"] for r in (body.get("data") or [])]
        assert s2["id"] in ids
        assert s1["id"] not in ids

        # Filter by SETTLED — must include s1 but not s2.
        resp = api.list_royalty_statements(license_data["id"], ADMIN_HEADERS,
                                            params={"status": "SETTLED", "limit": 100})
        body = resp.json()
        ids = [r["id"] for r in (body.get("data") or [])]
        assert s1["id"] in ids
        assert s2["id"] not in ids
