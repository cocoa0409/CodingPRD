"""Quality sampling: dry-matter assay correction, release gating, retain-expiry
rules, terminal-state lockdown, and the batch rework loop (PRD §3.6, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_operator_headers, make_quality_tech_headers,
    setup_mixed_batch, setup_released_batch, setup_batching_batch,
    collect_sample, enter_sample_result, release_batch,
    record_weighment, mix_batch,
)

MM = TEST_USERS["mill_manager_headers"]


class TestAssayDualVariant:
    def test_dry_matter_correction_flips_assay_to_pass(self, api):
        """PRD §3.8: "`protein_dry_matter` is the as-fed protein divided by one minus the moisture fraction (the `moisture_pct` value divided by one hundred), rounded half-up to two decimals; `fiber_dry_matter` is computed identically from `crude_fiber_pct_actual`."
        PRD §3.8: "the sample passes exactly when `protein_dry_matter` is at least the order's `pinned_min_protein_pct` and `fiber_dry_matter` is at most the order's `pinned_max_fiber_pct`, and equality passes on both sides."

        Design: Difficulty/dual_variant_calc/sample_assay_as_fed_vs_dry_matter_flips_outcome
        """
        ctx = setup_mixed_batch()  # pinned floors: min protein 19.5, max fiber 5.0
        sample = collect_sample(ctx["batch"]["id"], ctx["qt"]["id"])

        # As-fed protein 18.72 < 19.5 would fail as-fed; corrected:
        # 18.72 / (1 - 0.04) = 19.50 exactly, and 4.8 / 0.96 = 5.00 exactly.
        result = enter_sample_result(sample["id"], ctx["qt"]["id"],
                                     protein_pct_actual=18.72,
                                     crude_fiber_pct_actual=4.8,
                                     moisture_pct=4.0)
        assert result["protein_dry_matter"] == pytest.approx(19.5, abs=0.001)
        assert result["fiber_dry_matter"] == pytest.approx(5.0, abs=0.001)
        assert result["result"] == "PASS", (
            "the dry-matter basis alone gates release; equality passes on both sides")

    def test_dry_matter_pass_keeps_batch_mixed_no_hold_cascade(self, api):
        """PRD §3.8: "The dry-matter basis alone gates release; the as-fed figures stand as reporting context only, so the same assay can read one way as-fed and the opposite way on dry matter whenever moisture is above zero."
        PRD §3.8: "A failing sample moves `PENDING` → `FAIL` and detonates a cascade in the same request: the batch moves `MIXED` → `HOLD`, the order's `blocked` recomputes to true, and every delivery trip of the order in `PLANNED` or `LOADING` is cancelled with its compartment allocations released — cancelled trips are not auto-revived if the batch later recovers."

        Design: Difficulty/dual_variant_calc/sample_assay_as_fed_vs_dry_matter_flips_outcome
        """
        ctx = setup_mixed_batch()
        sample = collect_sample(ctx["batch"]["id"], ctx["qt"]["id"])
        enter_sample_result(sample["id"], ctx["qt"]["id"], 18.72, 4.8, 4.0)

        batch = validate_success(api.get_batch(ctx["batch"]["id"], MM), 200)
        assert batch["status"] == "MIXED", (
            "a PASS outcome must not fire the FAIL cascade; the batch stays MIXED")


class TestReleaseGating:
    def test_batch_release_without_pass_sample_rejected(self, api):
        """PRD §3.8: "A passing sample moves `PENDING` → `PASS` and unlocks the batch: a `QualityTech` may then release the batch `MIXED` → `RELEASED`, an act refused with `ERR_QUALITY_NOT_PASSED` unless a `PASS` sample exists for it."

        Design: Corner/state_machines/batch_release_without_pass_sample_rejected
        """
        ctx = setup_mixed_batch()
        # One sample collected but still PENDING — no PASS exists for the batch.
        collect_sample(ctx["batch"]["id"], ctx["qt"]["id"])

        resp = api.release_batch(
            ctx["batch"]["id"], make_quality_tech_headers(ctx["qt"]["id"]))
        validate_error(resp, ApiErrorId.ERR_QUALITY_NOT_PASSED)

        batch = validate_success(api.get_batch(ctx["batch"]["id"], MM), 200)
        assert batch["status"] == "MIXED"

    def test_retain_sample_expiry_rules(self, api):
        """PRD §3.8: "A `RETAIN` sample additionally requires a `retain_expiry_date` strictly after the current clock — a missing or non-future date is rejected with `ERR_RETAIN_EXPIRY_INVALID` — while a `COMPOSITE` sample carries none."

        Design: Corner/errors/retain_sample_expiry_rules
        """
        ctx = setup_mixed_batch()
        qt_headers = make_quality_tech_headers(ctx["qt"]["id"])

        # Missing retain_expiry_date.
        r1 = api.create_sample(
            {"batch_id": ctx["batch"]["id"], "sample_type": "RETAIN"}, qt_headers)
        validate_error(r1, ApiErrorId.ERR_RETAIN_EXPIRY_INVALID)

        # Past date (logical clock reads 2026-05-01T00:00:00Z at startup).
        r2 = api.create_sample(
            {"batch_id": ctx["batch"]["id"], "sample_type": "RETAIN",
             "retain_expiry_date": "2026-04-01T00:00:00Z"}, qt_headers)
        validate_error(r2, ApiErrorId.ERR_RETAIN_EXPIRY_INVALID)

        # Future date accepted.
        ok = api.create_sample(
            {"batch_id": ctx["batch"]["id"], "sample_type": "RETAIN",
             "retain_expiry_date": "2026-12-31T00:00:00Z"}, qt_headers)
        sample = validate_success(ok, 201)
        assert sample["result"] == "PENDING"


class TestTerminalBatchLockdown:
    def test_terminal_batch_released_accepts_no_further_transitions(self, api):
        """PRD §3.8: "An `Operator` may rework the batch, moving `HOLD` → `BATCHING`"
        PRD §3.6: "Separately, a `MillManager` may cancel a `PLANNED` batch outright — `PLANNED` → `CANCELLED`, freeing the line window and incrementing the batch's `version`."
        PRD §2.11: "State preconditions — transition from-states and cross-entity state requirements, including blocked bins and blocked orders (`ERR_INVALID_STATE`, `ERR_BIN_BLOCKED`, `ERR_ORDER_BLOCKED`)."

        Design: Corner/state_machines/terminal_batch_released_accepts_no_further_transitions
        """
        ctx = setup_released_batch()
        batch_id = ctx["batch"]["id"]
        assert ctx["batch"]["status"] == "RELEASED"

        # rework is defined only from HOLD.
        r1 = api.rework_batch(batch_id, make_operator_headers(ctx["op"]["id"]))
        validate_error(r1, ApiErrorId.ERR_INVALID_STATE)

        # cancel is defined only from PLANNED.
        r2 = api.cancel_batch(batch_id, MM)
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE)

        batch = validate_success(api.get_batch(batch_id, MM), 200)
        assert batch["status"] == "RELEASED"


class TestBatchReworkCycle:
    def _hold_setup(self, api):
        """Batch MIXED, then a FAIL sample (dry-matter protein 17.0 < 19.5)
        puts it on HOLD."""
        ctx = setup_mixed_batch()
        sample = collect_sample(ctx["batch"]["id"], ctx["qt"]["id"])
        failed = enter_sample_result(sample["id"], ctx["qt"]["id"], 17.0, 4.0, 0)
        assert failed["result"] == "FAIL"
        batch = validate_success(api.get_batch(ctx["batch"]["id"], MM), 200)
        assert batch["status"] == "HOLD"
        ctx["sample_fail"] = failed
        return ctx

    def test_batch_rework_cycle_traverses_hold_batching_mixed(self, api):
        """PRD §3.8: "An `Operator` may rework the batch, moving `HOLD` → `BATCHING`; the order's `blocked` recomputes — false again once no batch of the order remains in `HOLD` — and during the rework window the operator may void `RECORDED` weighments and record replacements before mixing again."
        PRD §3.8: "A failed batch may be re-sampled with a fresh `PENDING` sample after rework."

        Design: Difficulty/non_linear_state_machine/batch_rework_cycle_hold_to_batching_to_mixed
        """
        ctx = self._hold_setup(api)
        op_headers = make_operator_headers(ctx["op"]["id"])

        # HOLD -> BATCHING (rework).
        reworked = validate_success(api.rework_batch(ctx["batch"]["id"], op_headers), 200)
        assert reworked["status"] == "BATCHING"

        # Void the SBM weighment and record a replacement, then mix again.
        voided = validate_success(
            api.void_weighment(ctx["w_sbm"]["id"], op_headers), 200)
        assert voided["status"] == "VOID"
        record_weighment(ctx["batch"]["id"], ctx["sbm"]["id"],
                         ctx["bin_sbm"]["id"], 3.000, ctx["op"]["id"])
        remixed = validate_success(api.mix_batch(ctx["batch"]["id"], op_headers), 200)
        assert remixed["status"] == "MIXED"

        # Fresh sample after rework passes; the batch releases.
        sample2 = collect_sample(ctx["batch"]["id"], ctx["qt"]["id"])
        passed = enter_sample_result(sample2["id"], ctx["qt"]["id"], 20.0, 4.0, 0)
        assert passed["result"] == "PASS"
        released = release_batch(ctx["batch"]["id"], ctx["qt"]["id"])
        assert released["status"] == "RELEASED"

    def test_rework_clears_order_blocked_flag(self, api):
        """PRD §3.8: "An `Operator` may rework the batch, moving `HOLD` → `BATCHING`; the order's `blocked` recomputes — false again once no batch of the order remains in `HOLD` — and during the rework window the operator may void `RECORDED` weighments and record replacements before mixing again."
        PRD §3.5: "The order's `blocked` flag, used by several gates above, is derived: true exactly when any batch of the order sits in `HOLD`."

        Design: Difficulty/non_linear_state_machine/batch_rework_cycle_hold_to_batching_to_mixed
        """
        ctx = self._hold_setup(api)
        blocked_order = validate_success(api.get_order(ctx["order"]["id"], MM), 200)
        assert blocked_order["blocked"] is True, "derived: a batch in HOLD blocks the order"

        validate_success(
            api.rework_batch(ctx["batch"]["id"], make_operator_headers(ctx["op"]["id"])), 200)
        unblocked_order = validate_success(api.get_order(ctx["order"]["id"], MM), 200)
        assert unblocked_order["blocked"] is False, (
            "rework clears the only HOLD batch, so blocked recomputes to false")
