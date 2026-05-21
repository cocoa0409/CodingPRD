"""Franchise tax assessment, dual CORP methods, late fees, and credit
reconciliation.

Covers PRD §3.6 (franchise tax base + late-fee formula + pinned credit
evaluation order + segregation rule + refund compensating action).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_franchise_tax_assessment,
    assert_status,
    create_and_activate_entity,
    create_tax_assessment,
    create_tax_assessment_payload,
    credit_deposit,
    get_entity,
    get_tax_assessment,
    list_compliance_events,
    make_filer_headers,
    pay_tax_assessment,
    refund_tax_assessment,
    server_now_year,
    setup_active_corp_with_shares,
    setup_assessment_in_overdue,
    LLC_LP_FLAT_TAX_CENTS,
    CORP_TIER1_TAX_CENTS,
    CORP_TIER2_TAX_CENTS,
    CORP_TIER3_BLOCK_TAX_CENTS,
    LATE_FEE_FLAT_CENTS,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# FLAT method — PRD §3.6 (LLC / LP)
# ---------------------------------------------------------------------------
class TestFlatMethod:

    @pytest.mark.parametrize("entity_type", ["LLC", "LP"])
    def test_flat_base_tax_30000_cents(self, api, entity_type):
        """PRD §3.6 (FLAT): "For an LLC or LP, base_tax_cents is the
        constant 30,000 cents — that is, three hundred dollars — drawn
        from the configuration constant LLC_LP_FLAT_TAX_CENTS."

        Claim: FLAT method on LLC/LP returns base_tax_cents == 30000.
        """
        entity, _ = create_and_activate_entity(entity_type=entity_type)
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(entity["id"], 2024, "FLAT"),
            TEST_USERS["tax_officer_headers"],
        )
        a = validate_success(resp, expected_status=201)
        assert_franchise_tax_assessment(a)
        assert a["base_tax_cents"] == LLC_LP_FLAT_TAX_CENTS, (
            f"FLAT base_tax_cents must be {LLC_LP_FLAT_TAX_CENTS}, "
            f"got {a['base_tax_cents']}"
        )

    def test_llc_with_authorized_shares_method_rejected(self, api):
        """PRD §3.6: "for LLC and LP entities, the only legal value is
        FLAT; for CORP entities, the only legal values are
        AUTHORIZED_SHARES and ASSUMED_PAR_VALUE (and FLAT is not
        permitted). Mismatches are rejected with ERR_INVALID_TAX_METHOD
        and HTTP 422."

        Claim: LLC + AUTHORIZED_SHARES → ERR_INVALID_TAX_METHOD.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "AUTHORIZED_SHARES",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TAX_METHOD.value)

    def test_corp_with_flat_method_rejected(self, api):
        """PRD §3.6: "for CORP entities, the only legal values are
        AUTHORIZED_SHARES and ASSUMED_PAR_VALUE (and FLAT is not
        permitted)."

        Claim: CORP + FLAT → ERR_INVALID_TAX_METHOD.
        """
        entity, _ = setup_active_corp_with_shares(authorized_shares=1000)
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(entity["id"], 2024, "FLAT"),
            TEST_USERS["tax_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TAX_METHOD.value)


# ---------------------------------------------------------------------------
# AUTHORIZED_SHARES — PRD §3.6 tier boundaries
# ---------------------------------------------------------------------------
class TestAuthorizedSharesTiers:

    def test_tier1_at_5000_yields_17500(self, api):
        """PRD §3.6: "when authorized shares are at most 5,000, the
        base tax is 17,500 cents"

        Claim: authorized_shares=5000 (tier-1 boundary, inclusive) →
        base_tax_cents=17500.
        """
        entity, _ = setup_active_corp_with_shares(authorized_shares=5000)
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "AUTHORIZED_SHARES",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        a = validate_success(resp, expected_status=201)
        assert a["base_tax_cents"] == CORP_TIER1_TAX_CENTS, (
            f"5000 shares must yield {CORP_TIER1_TAX_CENTS}, "
            f"got {a['base_tax_cents']}"
        )

    def test_tier2_just_over_5000_yields_25000(self, api):
        """PRD §3.6: "when authorized shares are at most 10,000, the
        base tax is 25,000 cents"

        Claim: authorized_shares=5001 (just past tier-1 boundary) →
        base_tax_cents=25000.
        """
        entity, _ = setup_active_corp_with_shares(authorized_shares=5001)
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "AUTHORIZED_SHARES",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        a = validate_success(resp, expected_status=201)
        assert a["base_tax_cents"] == CORP_TIER2_TAX_CENTS

    def test_tier2_at_10000_yields_25000(self, api):
        """PRD §3.6: "when authorized shares are at most 10,000, the
        base tax is 25,000 cents"

        Claim: authorized_shares=10000 (tier-2 boundary, inclusive) →
        base_tax_cents=25000.
        """
        entity, _ = setup_active_corp_with_shares(authorized_shares=10000)
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "AUTHORIZED_SHARES",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        a = validate_success(resp, expected_status=201)
        assert a["base_tax_cents"] == CORP_TIER2_TAX_CENTS

    def test_tier3_one_block_over_10000_yields_33500(self, api):
        """PRD §3.6: "when authorized shares exceed 10,000, the base tax
        is 25,000 cents plus 8,500 cents for each additional block of
        10,000 shares, where the additional-share count beyond 10,000 is
        divided by 10,000 and rounded up to the next whole block (so
        10,001 shares already counts as one additional block, yielding
        33,500 cents)."

        Claim: authorized_shares=10001 (just over tier-2 boundary) →
        base_tax_cents=33500 (one full additional block charged).
        """
        entity, _ = setup_active_corp_with_shares(authorized_shares=10001)
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "AUTHORIZED_SHARES",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        a = validate_success(resp, expected_status=201)
        expected = CORP_TIER2_TAX_CENTS + CORP_TIER3_BLOCK_TAX_CENTS
        assert a["base_tax_cents"] == expected, (
            f"10001 shares (one additional block) must yield "
            f"{expected}, got {a['base_tax_cents']}"
        )

    def test_authorized_shares_12000_yields_33500(self, api):
        """PRD §3.6: "8,500 cents for each additional block of 10,000
        shares, where the additional-share count beyond 10,000 is
        divided by 10,000 and rounded up to the next whole block"

        Claim: authorized_shares=12000 → 25000 + 1*8500 = 33500.
        """
        entity, _ = setup_active_corp_with_shares(authorized_shares=12000)
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "AUTHORIZED_SHARES",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        a = validate_success(resp, expected_status=201)
        assert a["base_tax_cents"] == 33500


# ---------------------------------------------------------------------------
# ASSUMED_PAR_VALUE — PRD §3.6
# ---------------------------------------------------------------------------
class TestAssumedParValueMethod:

    def test_zero_issued_shares_rejected(self, api):
        """PRD §3.6: "If total_issued_shares is zero the request is
        rejected with ERR_INVALID_INPUT because the method's first step
        is a division by issued shares."

        Claim: ASSUMED_PAR_VALUE + total_issued_shares=0 →
        ERR_INVALID_INPUT.
        """
        entity, _ = setup_active_corp_with_shares(
            authorized_shares=10000, total_gross_assets_cents=100_000_000,
            total_issued_shares=0,
        )
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(
                entity["id"], 2024, "ASSUMED_PAR_VALUE",
            ),
            TEST_USERS["tax_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)


# ---------------------------------------------------------------------------
# tax_year uniqueness — PRD §3.6
# ---------------------------------------------------------------------------
class TestTaxYearUniqueness:

    def test_duplicate_tax_year_rejected(self, api):
        """PRD §3.6: "the tax_year ... must be unique per entity — a
        second assessment with the same tax_year yields
        ERR_DUPLICATE_TAX_YEAR with HTTP 409."

        Claim: second assessment with same (business_entity_id,
        tax_year) → ERR_DUPLICATE_TAX_YEAR.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        # First assessment.
        create_tax_assessment(entity["id"], 2024, "FLAT")
        # Second with same tax_year.
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(entity["id"], 2024, "FLAT"),
            TEST_USERS["tax_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAX_YEAR.value)


# ---------------------------------------------------------------------------
# Late fee + per-line rounding — PRD §3.6
# ---------------------------------------------------------------------------
class TestLateFee:

    def test_assessed_before_due_has_zero_late_fee(self, api):
        """PRD §3.6: "As long as a tax assessment is ASSESSED and the
        clock is at or before due_date, late_fee_cents is zero."

        Claim: freshly assessed (status=ASSESSED) → late_fee_cents=0.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        resp = api.create_tax_assessment(
            create_tax_assessment_payload(entity["id"], 2024, "FLAT"),
            TEST_USERS["tax_officer_headers"],
        )
        a = validate_success(resp, expected_status=201)
        assert_status(a, "ASSESSED")
        assert a["late_fee_cents"] == 0
        assert a["total_due_cents"] == a["base_tax_cents"]

    def test_overdue_assessment_accrues_late_fee_with_flat_penalty(
        self, api,
    ):
        """PRD §3.6: "Add the constant LATE_FEE_FLAT_CENTS of 20,000
        cents (a flat 200-dollar penalty). The sum is late_fee_cents."

        Claim: after the sweep drives an assessment to OVERDUE, its
        late_fee_cents is >= LATE_FEE_FLAT_CENTS (20000) because the
        flat penalty alone is the floor.
        """
        _entity, assessment = setup_assessment_in_overdue(
            authorized_shares=12000, days_past_due=10,
        )
        assert_status(assessment, "OVERDUE")
        assert assessment["late_fee_cents"] >= LATE_FEE_FLAT_CENTS, (
            f"OVERDUE late_fee must include the 20000-cent flat "
            f"penalty, got {assessment['late_fee_cents']}"
        )

    def test_total_due_equals_base_plus_late_fee_when_no_credit(
        self, api,
    ):
        """PRD §3.6: "Second, compute a pre-credit due figure as
        base_tax_cents plus late_fee_cents. ... Fourth, set
        total_due_cents to the pre-credit due figure minus
        credit_applied_cents."
        With credit_balance_cents=0, credit_applied=0, so total_due ==
        base + late_fee.

        Claim: total_due_cents == base_tax_cents + late_fee_cents when
        no credit deposit has been made.
        """
        _entity, assessment = setup_assessment_in_overdue(
            authorized_shares=12000, days_past_due=10,
        )
        expected = assessment["base_tax_cents"] + assessment["late_fee_cents"]
        assert assessment["total_due_cents"] == expected, (
            f"Expected total_due={expected}, "
            f"got {assessment['total_due_cents']}"
        )


# ---------------------------------------------------------------------------
# Credit balance + pinned evaluation order — PRD §3.6
# ---------------------------------------------------------------------------
class TestCreditApplication:

    def test_credit_deposit_increases_balance(self, api):
        """PRD §3.6: "The credit-deposit endpoint, accepting amount_cents,
        lets a TaxOfficer top up an entity's credit_balance_cents by the
        supplied amount."

        Claim: a deposit increases credit_balance_cents by the deposit
        amount.
        """
        entity, _ = create_and_activate_entity()
        before = entity["credit_balance_cents"]
        updated = credit_deposit(entity["id"], 50000)
        assert updated["credit_balance_cents"] == before + 50000

    def test_pay_applies_credit_and_decrements_balance(self, api):
        """PRD §3.6: "Fifth — and only on a payment — atomically
        decrement the entity's credit_balance_cents by
        credit_applied_cents."
        PRD §3.6 (pinned order): "Third, compute a credit_applied_cents
        figure as the smaller of the entity's current
        credit_balance_cents and the pre-credit due figure"

        Claim: paying an LLC FLAT assessment (base=30000) with
        credit_balance=50000 reduces the entity's balance by 30000.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        credit_deposit(entity["id"], 50000)
        # Use the current server year — due_date is March 1 of
        # (current_year + 1) which is in the future, keeping the
        # assessment ASSESSED with late_fee_cents=0.
        assessment = create_tax_assessment(
            entity["id"], server_now_year(), "FLAT",
        )
        # Pre-credit due = 30000; credit_balance = 50000 -> applied = 30000.
        # The pay action will spend exactly 30000 cents.
        paid_resp = api.pay_tax_assessment(
            assessment["id"], make_filer_headers(entity["id"]),
        )
        paid = validate_success(paid_resp)
        assert_status(paid, "PAID")
        # Re-read entity to check balance.
        ent = get_entity(entity["id"], make_filer_headers(entity["id"]))
        assert ent["credit_balance_cents"] == 50000 - LLC_LP_FLAT_TAX_CENTS, (
            f"After pay, balance should be {50000 - LLC_LP_FLAT_TAX_CENTS}, "
            f"got {ent['credit_balance_cents']}"
        )

    def test_refund_restores_credit_balance(self, api):
        """PRD §3.6: "the credit-balance conservation invariant: the
        global sum of every entity's credit_balance_cents plus every
        PAID assessment's credit_applied_cents is preserved across
        pay-refund cycles."
        PRD §3.6: "atomically restores the entity's credit_balance_cents
        by exactly the credit_applied_cents figure that was deducted at
        payment."

        Claim: a pay/refund cycle returns credit_balance_cents to its
        pre-pay value and toggles the assessment back out of PAID.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        credit_deposit(entity["id"], 50000)
        assessment = create_tax_assessment(entity["id"], 2024, "FLAT")
        pay_tax_assessment(assessment["id"], entity["id"])
        # Refund.
        refunded = refund_tax_assessment(assessment["id"])
        assert refunded["status"] != "PAID", (
            "Refund must move status off PAID"
        )
        ent = get_entity(entity["id"], make_filer_headers(entity["id"]))
        assert ent["credit_balance_cents"] == 50000, (
            f"After refund, balance should be 50000, "
            f"got {ent['credit_balance_cents']}"
        )

    def test_credit_capped_at_pre_credit_due(self, api):
        """PRD §3.6: "credit_applied_cents figure as the smaller of the
        entity's current credit_balance_cents and the pre-credit due
        figure — the entity may never apply more credit than it owes"

        Claim: with a credit_balance > pre_credit_due (LLC FLAT=30000),
        only 30000 is applied; the remaining 20000 stays on the entity.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        credit_deposit(entity["id"], 50000)
        # Current server year keeps the assessment ASSESSED (no late
        # fee), so pre_credit_due == base_tax_cents == 30000.
        assessment = create_tax_assessment(
            entity["id"], server_now_year(), "FLAT",
        )
        pay_tax_assessment(assessment["id"], entity["id"])
        ent = get_entity(entity["id"], make_filer_headers(entity["id"]))
        assert ent["credit_balance_cents"] == 20000, (
            f"Only 30000 (pre-credit due) must be applied; remaining "
            f"balance should be 20000, got {ent['credit_balance_cents']}"
        )


# ---------------------------------------------------------------------------
# Payment + segregation rule — PRD §3.6
# ---------------------------------------------------------------------------
class TestPayment:

    def test_pay_assessed_to_paid(self, api):
        """PRD §3.6: "Payment is legal from any non-PAID state —
        ASSESSED, OVERDUE, or DELINQUENT — and transitions the row to
        PAID."

        Claim: paying an ASSESSED row → PAID + emits TAX_PAID event.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        assessment = create_tax_assessment(entity["id"], 2024, "FLAT")
        resp = api.pay_tax_assessment(
            assessment["id"], make_filer_headers(entity["id"]),
        )
        paid = validate_success(resp)
        assert_status(paid, "PAID")
        assert paid.get("paid_at") is not None
        events = list_compliance_events(entity["id"])
        from test_helpers import assert_event_types_present
        assert_event_types_present(events, ["TAX_PAID"])

    def test_pay_already_paid_rejected(self, api):
        """PRD §3.6: "Two Filers racing to pay the same assessment
        serialize on FranchiseTaxAssessment.status; exactly one wins
        and the loser receives ERR_INVALID_STATE because the row is
        already PAID."

        Claim: paying an already-PAID assessment → ERR_INVALID_STATE.
        """
        entity, _ = create_and_activate_entity(entity_type="LLC")
        assessment = create_tax_assessment(entity["id"], 2024, "FLAT")
        pay_tax_assessment(assessment["id"], entity["id"])
        # Second pay attempt.
        resp = api.pay_tax_assessment(
            assessment["id"], make_filer_headers(entity["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
