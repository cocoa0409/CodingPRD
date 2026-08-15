"""Intercompany elimination rounding/gates and flux explanation lifecycle."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_entity_payload, create_elim_pair_payload, create_flux_payload,
    create_reconciliation_payload, create_fx_rate_payload,
    set_clock, create_period, create_entity, open_period, get_entity_period_for,
    setup_open_period_with_entity, register_identity_fx_rate,
    drive_entity_period_to_reconciled, drive_entity_period_to_subledger_cut,
    CONTROLLER, PREPARER, APPROVER,
    make_preparer_headers,
)
from test_helpers import api_client


def _setup_two_entity_period():
    """Period P1 (USD reporting) with EUR entity A and USD entity B, both RECONCILED
    and translated; EUR->USD PERIOD_END rate registered."""
    set_clock("2026-01-15T00:00:00Z")
    period = create_period()
    ent_a = create_entity(entity_code="EUA", name="EU A",
                           functional_currency="EUR", ownership_pct=100,
                           translation_method="CURRENT_RATE")
    ent_b = create_entity(entity_code="USB", name="US B",
                           functional_currency="USD", ownership_pct=100,
                           translation_method="CURRENT_RATE")
    open_period(period["id"])
    ep_a = get_entity_period_for(period["id"], ent_a["id"])
    ep_b = get_entity_period_for(period["id"], ent_b["id"])
    return period, ent_a, ent_b, ep_a, ep_b


def _drive_both_to_reconciled(period, ep_a, ep_b, register_eur_rate=True):
    if register_eur_rate:
        # CURRENT_RATE translation needs PERIOD_END (translated balance) and
        # AVERAGE (CTA plug) — PRD §3.7.
        register_identity_fx_rate(period["id"], from_ccy="EUR", to_ccy="USD",
                                   rate_kind="PERIOD_END", rate=1.10)
        register_identity_fx_rate(period["id"], from_ccy="EUR", to_ccy="USD",
                                   rate_kind="AVERAGE", rate=1.05)
    # cutoffs for both
    drive_entity_period_to_subledger_cut(ep_a["id"], subledger="AR")
    drive_entity_period_to_subledger_cut(ep_b["id"], subledger="AP")
    # translations — the EUR entity can only translate when its rates exist;
    # mark-reconciled itself does not require a translation run.
    if register_eur_rate:
        get_success_data(api_client.translate_entity_period(ep_a["id"], CONTROLLER))
    get_success_data(api_client.translate_entity_period(ep_b["id"], CONTROLLER))
    # mark reconciled
    get_success_data(api_client.mark_entity_period_reconciled(ep_a["id"], PREPARER))
    get_success_data(api_client.mark_entity_period_reconciled(ep_b["id"], PREPARER))


class TestIntercompanyElimination:
    def test_per_side_rounding_then_min(self, api):
        """PRD §3.8: "The recompute then works each side independently: side A's
        absolute amount is translated to reporting currency and rounded half up,
        side B's absolute amount likewise, and only then are the two rounded
        results compared — translating the minimum of the raw amounts is never
        correct. The `eliminated_amount_minor` is the smaller of the two rounded
        translated sides".

        Design: Difficulty/combinatorial_formula/intercompany_elimination_per_side_rounding_then_min
        """
        period, ent_a, ent_b, ep_a, ep_b = _setup_two_entity_period()
        _drive_both_to_reconciled(period, ep_a, ep_b)
        pair = get_success_data(api.create_elim_pair(
            period["id"],
            create_elim_pair_payload(ep_a["id"], ep_b["id"],
                                      amount_a_minor=100000, amount_b_minor=-109800),
            PREPARER))
        matched = validate_success(api.match_elim_pair(pair["id"], PREPARER), 200)
        # a_rep = round(100000*1.10) = 110000; b_rep = round(109800*1.0) = 109800
        assert matched["eliminated_amount_minor"] == 109800
        assert matched["residual_minor"] == 200

    def test_residual_sign_indicates_larger_side(self, api):
        """PRD §3.8: "The `residual_minor` is side A's rounded translated absolute
        minus side B's, with sign preserved — a positive residual means side A is
        larger".

        Design: Difficulty/combinatorial_formula/intercompany_elimination_per_side_rounding_then_min
        """
        period, ent_a, ent_b, ep_a, ep_b = _setup_two_entity_period()
        _drive_both_to_reconciled(period, ep_a, ep_b)
        pair = get_success_data(api.create_elim_pair(
            period["id"],
            create_elim_pair_payload(ep_a["id"], ep_b["id"],
                                      amount_a_minor=100000, amount_b_minor=-109800),
            PREPARER))
        matched = validate_success(api.match_elim_pair(pair["id"], PREPARER), 200)
        # positive residual → side A larger after per-side rounding
        assert matched["residual_minor"] > 0
        assert abs(matched["residual_minor"]) <= 500


class TestFxRateMissing:
    def test_fx_rate_missing_blocks_elim_match(self, api):
        """PRD §3.8: "FX rates must exist for any side whose functional currency is
        not the reporting currency — a missing rate is rejected with
        `ERR_FX_RATE_MISSING`".

        Design: Corner/errors/fx_rate_missing_blocks_temporal_translation
        """
        period, ent_a, ent_b, ep_a, ep_b = _setup_two_entity_period()
        # NO EUR->USD rate registered
        _drive_both_to_reconciled(period, ep_a, ep_b, register_eur_rate=False)
        pair = get_success_data(api.create_elim_pair(
            period["id"],
            create_elim_pair_payload(ep_a["id"], ep_b["id"],
                                      amount_a_minor=100000, amount_b_minor=-110000),
            PREPARER))
        res = api.match_elim_pair(pair["id"], PREPARER)
        validate_error(res, ApiErrorId.ERR_FX_RATE_MISSING, expected_status=409)
        after = validate_success(api.list_elim_pairs_for_period(period["id"], PREPARER), 200)
        matched = [p for p in after if p["id"] == pair["id"]][0]
        assert matched["status"] == "PROPOSED"


class TestReadyGateDependsOnElim:
    def test_entityperiod_ready_blocked_by_out_of_tolerance_elim(self, api):
        """PRD §3.9: "every elimination pair touching it must satisfy the residual
        rule of §3.8".
        PRD §3.8: "advancing any entity-period to `READY_FOR_CONSOL` requires every
        pair touching it to be `MATCHED` or `ELIMINATED` with an absolute residual
        no greater than five hundred, or the advance is rejected with
        `ERR_ELIM_RESIDUAL_EXCEEDED`."

        Design: Difficulty/cross_entity_state_dependency/entityperiod_ready_depends_on_elimpair_resolved
        """
        period, ent_a, ent_b, ep_a, ep_b = _setup_two_entity_period()
        _drive_both_to_reconciled(period, ep_a, ep_b)
        # residual = round(200000*1.10) - 215000 = 220000 - 215000 = 5000 (> 500)
        pair = get_success_data(api.create_elim_pair(
            period["id"],
            create_elim_pair_payload(ep_a["id"], ep_b["id"],
                                      amount_a_minor=200000, amount_b_minor=-215000),
            PREPARER))
        get_success_data(api.match_elim_pair(pair["id"], PREPARER))
        res = api.mark_entity_period_ready(ep_a["id"], PREPARER)
        validate_error(res, ApiErrorId.ERR_ELIM_RESIDUAL_EXCEEDED, expected_status=409)
        after = validate_success(api.get_entity_period(ep_a["id"], PREPARER), 200)
        assert after["status"] == "RECONCILED"

    def test_entityperiod_ready_succeeds_when_elim_within_tolerance(self, api):
        """PRD §3.8: "advancing any entity-period to `READY_FOR_CONSOL` requires
        every pair touching it to be `MATCHED` or `ELIMINATED` with an absolute
        residual no greater than five hundred".

        Design: Difficulty/cross_entity_state_dependency/entityperiod_ready_depends_on_elimpair_resolved
        """
        period, ent_a, ent_b, ep_a, ep_b = _setup_two_entity_period()
        _drive_both_to_reconciled(period, ep_a, ep_b)
        # residual = round(100000*1.10) - 109800 = 200 (<= 500)
        pair = get_success_data(api.create_elim_pair(
            period["id"],
            create_elim_pair_payload(ep_a["id"], ep_b["id"],
                                      amount_a_minor=100000, amount_b_minor=-109800),
            PREPARER))
        get_success_data(api.match_elim_pair(pair["id"], PREPARER))
        ready = validate_success(api.mark_entity_period_ready(ep_a["id"], PREPARER), 200)
        assert ready["status"] == "READY_FOR_CONSOL"


class TestFluxVariance:
    def test_flux_pct_floor_path_triggers_requirement(self, api):
        """PRD §3.9: "The `requires_explanation` flag is true when the absolute
        variance is at or above the period's `materiality_threshold_minor`, or
        when `variance_pct` is at least 10.0".
        PRD §3.9: "A zero prior balance with any non-zero current balance pushes
        the floored denominator to one, making the percentage effectively always
        at or above ten and the explanation mandatory."

        Design: Difficulty/combinatorial_formula/flux_variance_materiality_or_pct_tiered_gate
        """
        period, entity, ep = setup_open_period_with_entity()
        f1 = validate_success(api.create_flux(
            ep["id"],
            create_flux_payload(account_code="4000-REV",
                                  prior_balance_minor=0, current_balance_minor=5000),
            PREPARER), 201)
        assert f1["requires_explanation"] is True

    def test_flux_below_both_thresholds_not_required(self, api):
        """PRD §3.9: "The `requires_explanation` flag is true when the absolute
        variance is at or above the period's `materiality_threshold_minor`, or
        when `variance_pct` is at least 10.0".

        Design: Difficulty/combinatorial_formula/flux_variance_materiality_or_pct_tiered_gate
        """
        period, entity, ep = setup_open_period_with_entity()
        f2 = validate_success(api.create_flux(
            ep["id"],
            create_flux_payload(account_code="5000-COGS",
                                  prior_balance_minor=1000000, current_balance_minor=1000500),
            PREPARER), 201)
        assert f2["requires_explanation"] is False

    def test_flux_at_materiality_boundary_required(self, api):
        """PRD §3.9: "a variance exactly at materiality is mandatory, and a
        percentage of exactly 10.0 is mandatory."

        Design: Difficulty/combinatorial_formula/flux_variance_materiality_or_pct_tiered_gate
        """
        period, entity, ep = setup_open_period_with_entity()
        f3 = validate_success(api.create_flux(
            ep["id"],
            create_flux_payload(account_code="6000-OPEX",
                                  prior_balance_minor=100000, current_balance_minor=110000),
            PREPARER), 201)
        assert f3["requires_explanation"] is True
        assert f3["variance_pct"] == pytest.approx(10.0, abs=0.01)


class TestFluxAcceptDependsOnRecon:
    def test_flux_accept_blocked_by_uncleared_recon(self, api):
        """PRD §3.9: "A `Controller` accepts an `EXPLAINED` row — but when
        `reconciliation_id` is set, the linked reconciliation must already be
        `CLEARED`, otherwise acceptance is rejected with
        `ERR_FLUX_RECON_NOT_CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/flux_accept_depends_on_reconciliation_cleared
        """
        period, entity, ep = setup_open_period_with_entity()
        drive_entity_period_to_subledger_cut(ep["id"])
        rec = validate_success(api.create_reconciliation(
            ep["id"],
            create_reconciliation_payload(account_code="4000-REV", recon_type="SUBLEDGER_GL",
                                           gl_balance_minor=200000, subledger_balance_minor=199700),
            PREPARER), 201)
        # recon is OPEN; move to IN_REVIEW (still not CLEARED)
        get_success_data(api.review_reconciliation(rec["id"], make_preparer_headers("prep-1")))
        flux = validate_success(api.create_flux(
            ep["id"],
            create_flux_payload(account_code="4000-REV",
                                  prior_balance_minor=100000, current_balance_minor=200000,
                                  reconciliation_id=rec["id"]),
            PREPARER), 201)
        get_success_data(api.explain_flux(flux["id"],
                                            {"explanation_text": "driven by new customer contract"},
                                            PREPARER))
        res = api.accept_flux(flux["id"], CONTROLLER)
        validate_error(res, ApiErrorId.ERR_FLUX_RECON_NOT_CLEARED, expected_status=409)

    def test_flux_accept_succeeds_after_recon_cleared(self, api):
        """PRD §3.9: "A `Controller` accepts an `EXPLAINED` row — but when
        `reconciliation_id` is set, the linked reconciliation must already be
        `CLEARED`, otherwise acceptance is rejected with
        `ERR_FLUX_RECON_NOT_CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/flux_accept_depends_on_reconciliation_cleared
        """
        period, entity, ep = setup_open_period_with_entity()
        drive_entity_period_to_subledger_cut(ep["id"])
        # within tolerance → can be cleared directly after review
        rec = validate_success(api.create_reconciliation(
            ep["id"],
            create_reconciliation_payload(account_code="4000-REV", recon_type="SUBLEDGER_GL",
                                           gl_balance_minor=200000, subledger_balance_minor=199700),
            PREPARER), 201)
        get_success_data(api.review_reconciliation(rec["id"], make_preparer_headers("prep-1")))
        flux = validate_success(api.create_flux(
            ep["id"],
            create_flux_payload(account_code="4000-REV",
                                  prior_balance_minor=100000, current_balance_minor=200000,
                                  reconciliation_id=rec["id"]),
            PREPARER), 201)
        get_success_data(api.explain_flux(flux["id"],
                                            {"explanation_text": "driven by new customer contract"},
                                            PREPARER))
        # clear with a DIFFERENT preparer (SoD vs reviewer)
        get_success_data(api.clear_reconciliation(rec["id"], make_preparer_headers("prep-2")))
        accepted = validate_success(api.accept_flux(flux["id"], CONTROLLER), 200)
        assert accepted["status"] == "ACCEPTED"
