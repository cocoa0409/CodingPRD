"""InstallmentAgreement creation, activation, types, and DDIA threshold —
PRD §3.4.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DDIA_THRESHOLD_CENTS,
    LONG_TERM_DEBT_MAX_CENTS,
    assert_installment_agreement,
    create_and_activate_agreement,
    create_installment_agreement_payload,
    create_pending_installment_agreement,
    create_taxpayer,
    create_taxpayer_with_liability,
    create_tax_liability,
    get_installment_agreement,
    get_tax_liability,
    make_taxpayer_headers,
    validate_error,
    validate_success,
)


class TestInstallmentAgreementCreation:

    def test_create_pending_agreement(self, api):
        """PRD §3.4: "The agreement is persisted in status PENDING."

        Claim: a fresh agreement is PENDING.
        """
        taxpayer, liability = create_taxpayer_with_liability(
            original_assessed_amount_cents=1_000_000,
        )
        payload = create_installment_agreement_payload(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="CHECK",
        )
        resp = api.create_installment_agreement(
            payload, make_taxpayer_headers(taxpayer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_installment_agreement(data)
        assert data["status"] == "PENDING"

    def test_short_term_classified_when_four_months_cover_debt(self, api):
        """PRD §3.4: "A SHORT_TERM agreement is one where four months
        of the proposed monthly payment would cover or exceed the sum
        of current_balance_cents across the covered liabilities."

        Claim: $1,000 balance + $300/mo => SHORT_TERM.
        """
        taxpayer, liability = create_taxpayer_with_liability(
            original_assessed_amount_cents=100_000,  # $1,000
        )
        agreement = create_pending_installment_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=30_000,  # $300/mo * 4 = $1,200
            payment_method="CHECK",
        )
        assert agreement["agreement_type"] == "SHORT_TERM"

    def test_long_term_classified_under_50k_with_payoff_before_csed(self, api):
        """PRD §3.4: "A LONG_TERM (streamlined) agreement requires that
        the aggregate covered debt is at most 5,000,000 cents (which is
        $50,000) and that the projected payoff date does not fall after
        the minimum csed_effective_date across the covered liabilities."

        Claim: $30,000 balance + $1,000/mo (DDIA required > $25k) =>
        LONG_TERM.
        """
        taxpayer, liability = create_taxpayer_with_liability(
            monthly_disposable_income_cents=200_000,
            original_assessed_amount_cents=3_000_000,
        )
        agreement = create_pending_installment_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=100_000,
            payment_method="DDIA",
        )
        assert agreement["agreement_type"] == "LONG_TERM"


class TestDDIAThreshold:

    def test_aggregate_debt_exactly_at_threshold_allows_check(self, api):
        """PRD §3.4: "whenever the aggregate covered debt exceeds
        2,500,000 cents (which is $25,000), the payment_method must be
        DDIA; any other method is rejected with ERR_DDIA_REQUIRED."

        Claim: aggregate debt == 2,500,000 (boundary, strict >) is
        allowed with CHECK.

        # difficulty: boundary_precision_check/ddia_threshold_25k_strict_greater_than
        """
        taxpayer, liability = create_taxpayer_with_liability(
            monthly_disposable_income_cents=300_000,
            original_assessed_amount_cents=DDIA_THRESHOLD_CENTS,  # 2_500_000
        )
        payload = create_installment_agreement_payload(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=50_000,
            payment_method="CHECK",
        )
        resp = api.create_installment_agreement(
            payload, make_taxpayer_headers(taxpayer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["payment_method"] == "CHECK"

    def test_aggregate_debt_one_cent_over_threshold_requires_ddia(self, api):
        """PRD §3.4: "whenever the aggregate covered debt exceeds
        2,500,000 cents (which is $25,000), the payment_method must be
        DDIA; any other method is rejected with ERR_DDIA_REQUIRED."

        Claim: aggregate debt == 2,500,001 with CHECK → ERR_DDIA_REQUIRED.

        # difficulty: boundary_precision_check/ddia_threshold_25k_strict_greater_than
        """
        taxpayer, liability = create_taxpayer_with_liability(
            monthly_disposable_income_cents=300_000,
            original_assessed_amount_cents=DDIA_THRESHOLD_CENTS + 1,
        )
        payload = create_installment_agreement_payload(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=50_000,
            payment_method="CHECK",
        )
        resp = api.create_installment_agreement(
            payload, make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DDIA_REQUIRED.value)

    def test_ddia_above_threshold_succeeds(self, api):
        """PRD §3.4: "whenever the aggregate covered debt exceeds
        2,500,000 cents ... the payment_method must be DDIA."

        Claim: aggregate > threshold with DDIA → success.
        """
        taxpayer, liability = create_taxpayer_with_liability(
            monthly_disposable_income_cents=300_000,
            original_assessed_amount_cents=3_000_000,
        )
        payload = create_installment_agreement_payload(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=100_000,
            payment_method="DDIA",
            ddia_bank_account_last4="9876",
        )
        resp = api.create_installment_agreement(
            payload, make_taxpayer_headers(taxpayer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["payment_method"] == "DDIA"
        assert data["ddia_bank_account_last4"] == "9876"


class TestActivationCascade:

    def test_activation_moves_pending_to_active(self, api):
        """PRD §3.4: "Activation is performed by an IRSOfficer,
        advancing agreement.status from PENDING to ACTIVE."

        Claim: activate of a PENDING IA → status == ACTIVE.
        """
        taxpayer, liability = create_taxpayer_with_liability(
            original_assessed_amount_cents=1_000_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="CHECK",
        )
        assert agreement["status"] == "ACTIVE"

    def test_activation_transitions_covered_liability_to_in_agreement(self, api):
        """PRD §3.4: "When activation succeeds, every covered liability
        transitions from OPEN to IN_AGREEMENT."

        Claim: after activation, covered liability.status == IN_AGREEMENT.
        """
        taxpayer, liability = create_taxpayer_with_liability(
            original_assessed_amount_cents=1_000_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="CHECK",
        )
        assert agreement["status"] == "ACTIVE"
        liability_after = get_tax_liability(liability["id"])
        assert liability_after["status"] == "IN_AGREEMENT"

    def test_activation_updates_taxpayer_collection_status(self, api,
                                                            irs_officer_headers):
        """PRD §3.4: "the taxpayer's collection_status is recomputed
        (it becomes IN_AGREEMENT whenever at least one covered
        liability is now IN_AGREEMENT)."

        Claim: post-activation taxpayer.collection_status == IN_AGREEMENT.
        """
        taxpayer, liability = create_taxpayer_with_liability(
            original_assessed_amount_cents=1_000_000,
        )
        create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="CHECK",
        )
        resp = api.get_taxpayer(taxpayer["id"], irs_officer_headers)
        refreshed = validate_success(resp)
        assert refreshed["collection_status"] == "IN_AGREEMENT"


class TestActivationGating:

    def test_activate_rejects_cnc_covered_liability(self, api):
        """PRD §3.4: "fails with ERR_LIABILITY_NOT_ELIGIBLE if any
        covered liability is no longer in OPEN or IN_AGREEMENT."

        # difficulty: cross_entity_state_dependency/ia_activate_depends_on_liability_status

        Claim: a covered liability already in CNC status blocks
        activation with ERR_LIABILITY_NOT_ELIGIBLE.
        """
        from test_helpers import place_cnc
        taxpayer = create_taxpayer(monthly_disposable_income_cents=0)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=500_000,
        )
        # Place liability into CNC.
        place_cnc(taxpayer["id"], [liability["id"]])
        # Now try to draft + activate an IA against the CNC liability.
        # Drafting goes through (since the eligibility check is at
        # activation time per PRD §3.4); the activate call must fail.
        # However, PRD says draft accepts liabilities IN {OPEN, IN_AGREEMENT}
        # so this may fail at draft time. Per PRD §3.4: "Activation
        # ... fails with ERR_LIABILITY_NOT_ELIGIBLE if any covered
        # liability is no longer in OPEN or IN_AGREEMENT."
        # Be defensive: validate the error_id whether it surfaces at
        # draft or activate.
        payload = create_installment_agreement_payload(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=50_000,
            payment_method="CHECK",
        )
        draft_resp = api.create_installment_agreement(
            payload, make_taxpayer_headers(taxpayer["id"]),
        )
        if draft_resp.status_code >= 400:
            validate_error(
                draft_resp, ApiErrorId.ERR_LIABILITY_NOT_ELIGIBLE.value,
            )
            return
        draft = validate_success(draft_resp, expected_status=201)
        activate_resp = api.activate_installment_agreement(
            draft["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        # The activator may be IRSOfficer per PRD §3.4 — but our
        # ownership-gated header is Taxpayer; switch to IRSOfficer.
        from test_helpers import TEST_USERS
        activate_resp = api.activate_installment_agreement(
            draft["id"], TEST_USERS["irs_officer_headers"],
        )
        validate_error(
            activate_resp, ApiErrorId.ERR_LIABILITY_NOT_ELIGIBLE.value,
        )

    def test_activate_returns_invalid_state_on_already_active(self, api):
        """PRD §2.10: "the server evaluates them in a fixed order ...
        State preconditions come next: general status check (priority
        6) returns ERR_INVALID_STATE."

        Claim: a second activate on an already-ACTIVE IA returns
        ERR_INVALID_STATE.
        """
        from test_helpers import TEST_USERS
        taxpayer, liability = create_taxpayer_with_liability(
            original_assessed_amount_cents=1_000_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="CHECK",
        )
        resp = api.activate_installment_agreement(
            agreement["id"], TEST_USERS["irs_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestNextDueDate:

    def test_next_due_date_pinned_30_days_after_activation(self, api):
        """PRD §3.4: "the server pins next_due_date to activation date
        plus 30 days."

        Claim: next_due_date is 30 days after the activation moment.
        """
        from test_helpers import add_days, advance_clock_to, parse_iso
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer, liability = create_taxpayer_with_liability(
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_000_000,
        )
        agreement = create_and_activate_agreement(
            taxpayer["id"], [liability["id"]],
            proposed_monthly_payment_cents=200_000,
            payment_method="CHECK",
        )
        expected_next = parse_iso(add_days("2020-01-01T00:00:00.000Z", 30))
        actual_next = parse_iso(agreement["next_due_date"])
        assert actual_next == expected_next, (
            f"next_due_date should be activation + 30d "
            f"({expected_next.isoformat()}); got {actual_next.isoformat()}"
        )
