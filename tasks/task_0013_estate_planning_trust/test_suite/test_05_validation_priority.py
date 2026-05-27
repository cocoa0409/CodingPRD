"""Validation priority conflicts across different error-category pairs.

PRD §2.9 explicitly lists the validation ordering; these tests assert that a
lower-priority-number error wins over a higher-priority-number error when
both apply to the same request.
"""
import pytest

from test_helpers import (
    validate_error,
    set_clock,
    ApiErrorId,
    bootstrap_estate_in_administration,
    bootstrap_estate_in_draft,
    create_decedent,
    create_estate,
    create_executor,
    accept_executor,
    create_directive,
    witness_directive,
    create_creditor_claim,
    create_asset,
    create_designation,
    finalize_plan,
    register_death,
    file_for_probate,
    create_probate_order,
    enter_probate_order,
    make_executor_headers,
    make_planner_headers,
    make_creditor_headers,
    make_registrar_headers,
    make_judge_headers,
)


class TestStateBeforeSegregationOfDuties:
    """PRD §2.9 priority: state (4) < segregation_of_duties (5). A directive
    that is BOTH not yet WITNESSED AND has physician==executor must surface
    ERR_INVALID_STATE first."""

    def test_state_takes_precedence_over_segregation(self, api):
        """PRD §2.9: "Validations on every request are evaluated in a fixed
        priority order so that the first failure is always reported the same
        way:
        1. Authentication ...
        2. Existence ...
        3. Authorization ...
        4. State — the target resource's current status permits the requested
        transition (ERR_INVALID_STATE, HTTP 409).
        5. Segregation of duties on directive activation — the attesting
        physician is not also the estate's executor
        (ERR_SEGREGATION_OF_DUTIES_VIOLATED, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_segregation_on_directive_activate
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Nina Ortiz",
            domicile_state_code="CA", ssn_last4="5555",
        )
        estate = create_estate(dec["id"])
        executor = create_executor(estate["id"], "Exec N", "EXECUTOR", False)
        executor = accept_executor(executor["id"])
        # Directive in DRAFT (not yet WITNESSED) AND with attester==executor.
        directive = create_directive(
            dec["id"], "DNR", physician_attester_user_id=executor["id"],
        )
        # Try to activate from DRAFT.
        resp = api.activate_directive(directive["id"], make_planner_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_segregation_isolated_when_state_correct(self, api):
        """PRD §3.4: "Whenever physician_attester_user_id is set on any
        directive being activated, it must not equal the parent estate's
        executor_user_id; this segregation prevents the same person from
        acting as both the estate's executor and the attesting physician for
        that estate's medical directives, and is reported as
        ERR_SEGREGATION_OF_DUTIES_VIOLATED."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_segregation_on_directive_activate
        """
        set_clock("2026-01-01T00:00:00Z")
        dec = create_decedent(
            full_legal_name="Nina Ortiz",
            domicile_state_code="CA", ssn_last4="5555",
        )
        estate = create_estate(dec["id"])
        executor = create_executor(estate["id"], "Exec N", "EXECUTOR", False)
        executor = accept_executor(executor["id"])
        # Create LIVING_WILL with attester==executor; advance to NOTARIZED so
        # state precondition is fine; activate should fire segregation only.
        directive = create_directive(
            dec["id"], "LIVING_WILL", physician_attester_user_id=executor["id"],
        )
        witness_directive(directive["id"])
        api.notarize_directive(directive["id"], make_planner_headers())
        resp = api.activate_directive(directive["id"], make_planner_headers())
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATED)


class TestCreditorWindowBeforeFiscalCheck:
    """PRD §2.9: creditor-window (8) < estate-fund-sufficiency (12). A claim
    filed after the 120-day window is rejected at file-time and never reaches
    the payment check."""

    def test_creditor_window_closes_before_payment_check(self, api):
        """PRD §3.6: "On creation, if the parent estate's probate_opened_at
        is already set, the claim's filed_at must fall no later than one
        hundred twenty days after probate_opened_at; a claim filed exactly
        at the one-hundred-twenty-day mark is still accepted, but a claim
        filed even one second beyond that point is rejected with
        ERR_CREDITOR_WINDOW_CLOSED."

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_on_creditor_payment
        """
        # Probate opened around 2026-01-01; 120-day window closes 2026-05-01.
        # We submit at 2026-06-01 → window closed.
        set_clock("2026-01-01T00:00:00Z")
        # Build estate to ADMINISTRATION with small gross 100000.
        ctx = bootstrap_estate_in_administration(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-01T00:00:00Z",
            asset_value_cents=100000,
            domicile_state_code="NY",
        )
        # Advance clock to 2026-06-01 (151 days after probate_opened_at).
        set_clock("2026-06-01T00:00:00Z")
        # Try to file a large claim (500000 > gross 100000). Should fire
        # window-closed first, NOT fund-insufficient.
        resp = api.create_creditor_claim(
            {
                "estate_id": ctx["estate"]["id"],
                "creditor_name": "LateMassive",
                "amount_cents": 500000,
                "claim_class": "UNSECURED",
                "filed_at": "2026-06-01T00:00:00Z",
            },
            make_creditor_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_CREDITOR_WINDOW_CLOSED)

    def test_insufficient_funds_path_only_fires_when_in_window(self, api):
        """PRD §3.6: "If the pool is zero or negative at that point — meaning
        every earlier-priority allowed claim has notionally consumed the full
        estate — the payment is rejected with ERR_INSUFFICIENT_ESTATE_FUNDS"

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_on_creditor_payment
        """
        # Same shape but file the over-large claim INSIDE the window (no
        # window-closed error), allow & pay it from a tiny gross → fund
        # insufficiency surfaces as the only error.
        ctx = bootstrap_estate_in_administration(
            clock="2026-01-01T00:00:00Z",
            date_of_death="2026-01-01T00:00:00Z",
            asset_value_cents=100000,
            domicile_state_code="NY",
        )
        claim = create_creditor_claim(
            ctx["estate"]["id"],
            creditor_name="BiggerThanGross",
            amount_cents=500000, claim_class="UNSECURED",
            filed_at="2026-02-01T00:00:00Z",
        )
        # Allow then attempt to pay.
        api.allow_creditor_claim(
            claim["id"], make_executor_headers(ctx["executor"]["id"]),
        )
        # File a SECURED claim that consumes the full estate.
        sec_claim = create_creditor_claim(
            ctx["estate"]["id"], creditor_name="Sec",
            amount_cents=100000, claim_class="SECURED",
            filed_at="2026-02-02T00:00:00Z",
        )
        api.allow_creditor_claim(
            sec_claim["id"], make_executor_headers(ctx["executor"]["id"]),
        )
        # Pay SECURED first to deplete pool.
        api.pay_creditor_claim(
            sec_claim["id"], make_executor_headers(ctx["executor"]["id"]),
        )
        # Now try to pay the UNSECURED claim — no remaining pool.
        resp = api.pay_creditor_claim(
            claim["id"], make_executor_headers(ctx["executor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ESTATE_FUNDS)
