"""Subledger cutoffs (boundary semantics, cascade) and accrual estimates."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_subledger_cutoff_payload, create_accrual_payload,
    set_clock, setup_open_period_with_entity,
    CONTROLLER, PREPARER, APPROVER,
)
from test_helpers import api_client


class TestCutoffBoundary:
    def test_cutoff_inclusive_excludes_transaction_at_cutoff(self, api):
        """PRD §3.3: "under `INCLUSIVE`, transactions strictly before `cutoff_at`
        are included and a transaction exactly at `cutoff_at` is excluded,
        belonging to the next period".
        PRD §3.3: "`boundary_transaction_count` counts the transactions whose
        timestamp equals `cutoff_at` exactly — under both rules".

        Design: Difficulty/resource_temporal_overlap/cutoff_boundary_inclusive_vs_exclusive_at_instant
        """
        period, entity, ep = setup_open_period_with_entity()
        # Seed three AR transactions: before / at / after the cutoff instant
        get_success_data(api.seed_subledger(
            {"entity_id": entity["id"], "subledger": "AR",
             "ts": "2026-01-02T00:00:00Z", "amount_minor": 1000, "account_code": "1200-AR"},
            CONTROLLER))
        get_success_data(api.seed_subledger(
            {"entity_id": entity["id"], "subledger": "AR",
             "ts": "2026-01-31T00:00:00Z", "amount_minor": 500, "account_code": "1200-AR"},
            CONTROLLER))
        get_success_data(api.seed_subledger(
            {"entity_id": entity["id"], "subledger": "AR",
             "ts": "2026-02-01T00:00:00Z", "amount_minor": 700, "account_code": "1200-AR"},
            CONTROLLER))

        cut = get_success_data(api.create_subledger_cutoff(
            ep["id"],
            create_subledger_cutoff_payload(subledger="AR", cutoff_at="2026-01-31T00:00:00Z",
                                              cutoff_rule="INCLUSIVE"),
            PREPARER))
        executed = validate_success(api.cut_subledger_cutoff(cut["id"], PREPARER), 200)
        assert executed["pre_cutoff_total_minor"] == 1000
        assert executed["boundary_transaction_count"] == 1

    def test_cutoff_exclusive_at_end_includes_transaction_at_cutoff(self, api):
        """PRD §3.3: "under `EXCLUSIVE_AT_END`, transactions at or before
        `cutoff_at` are included, so boundary transactions sit inside the total."

        Design: Difficulty/resource_temporal_overlap/cutoff_boundary_inclusive_vs_exclusive_at_instant
        """
        period, entity, ep = setup_open_period_with_entity()
        get_success_data(api.seed_subledger(
            {"entity_id": entity["id"], "subledger": "AR",
             "ts": "2026-01-02T00:00:00Z", "amount_minor": 1000, "account_code": "1200-AR"},
            CONTROLLER))
        get_success_data(api.seed_subledger(
            {"entity_id": entity["id"], "subledger": "AR",
             "ts": "2026-01-31T00:00:00Z", "amount_minor": 500, "account_code": "1200-AR"},
            CONTROLLER))
        get_success_data(api.seed_subledger(
            {"entity_id": entity["id"], "subledger": "AR",
             "ts": "2026-02-01T00:00:00Z", "amount_minor": 700, "account_code": "1200-AR"},
            CONTROLLER))

        cut = get_success_data(api.create_subledger_cutoff(
            ep["id"],
            create_subledger_cutoff_payload(subledger="AR", cutoff_at="2026-01-31T00:00:00Z",
                                              cutoff_rule="EXCLUSIVE_AT_END"),
            PREPARER))
        executed = validate_success(api.cut_subledger_cutoff(cut["id"], PREPARER), 200)
        assert executed["pre_cutoff_total_minor"] == 1500
        assert executed["boundary_transaction_count"] == 1


class TestCutoffCascade:
    def test_last_confirm_bubbles_entity_period_to_subledger_cut(self, api):
        """PRD §3.3: "Confirmation carries a bubble-up cascade: the moment every
        cutoff of an entity-period has reached `CONFIRMED`, the entity-period
        itself advances from `PREPARING` to `SUBLEDGER_CUT`, every accrual
        estimate on it has its provisional amount computed (§3.4), and a
        `SUBLEDGER_CUT` audit event is appended."

        Design: Difficulty/transitive_cascade/cutoff_confirm_to_entityperiod_to_accrual_cascade
        """
        period, entity, ep = setup_open_period_with_entity()
        # Create and cut BOTH cutoffs first: per PRD §3.3 the entity-period
        # bubbles to SUBLEDGER_CUT the moment every existing cutoff is
        # CONFIRMED, and cutting is only allowed while PREPARING — so no
        # confirm may happen until both cutoffs exist and are cut.
        cut_ar = get_success_data(api.create_subledger_cutoff(
            ep["id"], create_subledger_cutoff_payload(subledger="AR"), PREPARER))
        cut_ap = get_success_data(api.create_subledger_cutoff(
            ep["id"], create_subledger_cutoff_payload(subledger="AP"), PREPARER))
        get_success_data(api.cut_subledger_cutoff(cut_ar["id"], PREPARER))
        get_success_data(api.cut_subledger_cutoff(cut_ap["id"], PREPARER))

        # Confirm AR only — AP still CUT, so no bubble-up yet
        get_success_data(api.confirm_subledger_cutoff(cut_ar["id"], APPROVER))

        # accrual spec attached to AR cutoff
        acc = get_success_data(api.create_accrual(
            ep["id"], create_accrual_payload(cut_ar["id"]), PREPARER))

        # sanity: entity-period still PREPARING (AP not yet confirmed)
        pre = validate_success(api.get_entity_period(ep["id"], PREPARER), 200)
        assert pre["status"] == "PREPARING"

        # last confirm bubbles the entity-period up
        get_success_data(api.confirm_subledger_cutoff(cut_ap["id"], APPROVER))
        post = validate_success(api.get_entity_period(ep["id"], PREPARER), 200)
        assert post["status"] == "SUBLEDGER_CUT"

    def test_accrual_provisional_recomputed_on_subledger_cut(self, api):
        """PRD §3.3: "the moment every cutoff of an entity-period has reached
        `CONFIRMED`, the entity-period itself advances from `PREPARING` to
        `SUBLEDGER_CUT`, every accrual estimate on it has its provisional amount
        computed (§3.4), and a `SUBLEDGER_CUT` audit event is appended."
        PRD §3.4: "The estimate starts in `PROVISIONAL`, and its
        `provisional_amount_minor` is computed in functional-currency minor units
        when the entity-period reaches `SUBLEDGER_CUT`."

        Design: Difficulty/transitive_cascade/cutoff_confirm_to_entityperiod_to_accrual_cascade
        """
        period, entity, ep = setup_open_period_with_entity()
        # Create and cut both cutoffs before any confirm (see above: the first
        # confirm of the only cutoff would bubble the entity-period out of
        # PREPARING and make any further cut illegal).
        cut_ar = get_success_data(api.create_subledger_cutoff(
            ep["id"], create_subledger_cutoff_payload(subledger="AR"), PREPARER))
        cut_ap = get_success_data(api.create_subledger_cutoff(
            ep["id"], create_subledger_cutoff_payload(subledger="AP"), PREPARER))
        get_success_data(api.cut_subledger_cutoff(cut_ar["id"], PREPARER))
        get_success_data(api.cut_subledger_cutoff(cut_ap["id"], PREPARER))
        get_success_data(api.confirm_subledger_cutoff(cut_ar["id"], APPROVER))

        acc = get_success_data(api.create_accrual(
            ep["id"], create_accrual_payload(cut_ar["id"]), PREPARER))

        # confirm AP → entity-period advances → accrual recomputed (PRIOR_PERIOD with
        # no prior periods yields 0)
        get_success_data(api.confirm_subledger_cutoff(cut_ap["id"], APPROVER))
        accruals = validate_success(api.list_accruals_for_entity_period(ep["id"], PREPARER), 200)
        assert len(accruals) == 1
        assert accruals[0]["id"] == acc["id"]
        assert accruals[0]["status"] == "PROVISIONAL"
        assert isinstance(accruals[0]["provisional_amount_minor"], int)


class TestAccrualTrueUp:
    def test_accrual_provisional_zero_with_no_prior_periods(self, api):
        """PRD §3.4: "Under `PRIOR_PERIOD`, the provisional is simply the prior
        single period's posted net amount, with no division at all."

        Design: Difficulty/dual_variant_calc/accrual_estimation_provisional_vs_final_material_trueup
        """
        period, entity, ep = setup_open_period_with_entity()
        cut = get_success_data(api.create_subledger_cutoff(
            ep["id"], create_subledger_cutoff_payload(subledger="AR"), PREPARER))
        get_success_data(api.cut_subledger_cutoff(cut["id"], PREPARER))
        get_success_data(api.confirm_subledger_cutoff(cut["id"], APPROVER))
        # entity-period is now SUBLEDGER_CUT
        acc = get_success_data(api.create_accrual(
            ep["id"], create_accrual_payload(cut["id"]), PREPARER))
        # accrual created after SUBLEDGER_CUT → recompute on demand
        recomputed = validate_success(api.recompute_accrual(acc["id"], PREPARER), 200)
        # PRIOR_PERIOD with no prior periods → 0
        assert recomputed["provisional_amount_minor"] == 0

    def test_accrual_trueup_at_materiality_blocks_reconciled(self, api):
        """PRD §3.4: "The system computes `true_up_delta_minor` as the final amount
        minus the provisional amount, preserving sign. This delta is the
        materiality trip-wire: when its absolute value is at or above the period's
        `materiality_threshold_minor`, the entity-period is blocked from advancing
        to `RECONCILED` until a balancing journal entry posts, and the block
        surfaces at mark-reconciled time as `ERR_ACCRUAL_MATERIAL_TRUEUP`."

        Design: Difficulty/dual_variant_calc/accrual_estimation_provisional_vs_final_material_trueup
        """
        period, entity, ep = setup_open_period_with_entity()
        cut = get_success_data(api.create_subledger_cutoff(
            ep["id"], create_subledger_cutoff_payload(subledger="AR"), PREPARER))
        get_success_data(api.cut_subledger_cutoff(cut["id"], PREPARER))
        get_success_data(api.confirm_subledger_cutoff(cut["id"], APPROVER))
        acc = get_success_data(api.create_accrual(
            ep["id"], create_accrual_payload(cut["id"]), PREPARER))
        recomputed = validate_success(api.recompute_accrual(acc["id"], PREPARER), 200)
        assert recomputed["provisional_amount_minor"] == 0

        trued = validate_success(api.true_up_accrual(acc["id"],
                                                       {"final_amount_minor": 10000},
                                                       PREPARER), 200)
        assert trued["true_up_delta_minor"] == 10000

        res = api.mark_entity_period_reconciled(ep["id"], PREPARER)
        validate_error(res, ApiErrorId.ERR_ACCRUAL_MATERIAL_TRUEUP, expected_status=409)
        after = validate_success(api.get_entity_period(ep["id"], PREPARER), 200)
        assert after["status"] == "SUBLEDGER_CUT"
