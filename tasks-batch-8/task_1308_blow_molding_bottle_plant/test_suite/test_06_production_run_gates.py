"""Production-run start gates: mold installation, state-vs-safety priority, quality-hold blockouts, cavitation, resin compatibility, lot release state, spec-revision baseline, release material gate, and close validations."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_production_run_payload, close_production_run_payload,
    setup_qualified_plant, setup_scheduled_order, setup_released_scenario,
    setup_running_scenario, setup_closed_run_scenario,
    create_lot, install_mold, open_blockout, set_clock, release_order,
    submit_spec, begin_qualification, create_qualification_run, execute_run,
    submit_review, review_run,
    get_order, list_order_slots,
    api_client, ApiErrorId, TEST_USERS,
    SLOT_START, SLOT_END, RUN_CLOCK,
)

ADMIN = TEST_USERS["plant_admin"]
ENGINEER = TEST_USERS["process_engineer"]
TECH = TEST_USERS["quality_technician"]
SCHEDULER = TEST_USERS["production_scheduler"]


def _run_payload(ctx, lot_id=None):
    return create_production_run_payload(
        ctx["order"]["id"], ctx["line"]["id"], ctx["mold"]["id"],
        lot_id or ctx["lot"]["id"])


class TestRunRequiresInstalledMold:
    def test_run_create_rejected_when_mold_in_storage(self, api):
        """PRD §3.6: "The mold must be `INSTALLED` and installed on exactly this line, else `ERR_MOLD_NOT_INSTALLED`".

Design: Difficulty/cross_entity_state_dependency/run_requires_installed_mold"""
        ctx = setup_released_scenario(install=False)
        assert get_success_data(api.get_mold(ctx["mold"]["id"], ENGINEER))["status"] \
            == "STORAGE"
        res = api.create_production_run(_run_payload(ctx), ENGINEER)
        validate_error(res, ApiErrorId.ERR_MOLD_NOT_INSTALLED)

    def test_run_create_after_install_advances_order_slot_line(self, api):
        """PRD §3.6: "A successful start snapshots the mold's `effective_cavities` into `cavities_active_at_start`" and "The first run of an order ripples outward in the same gesture: the order moves `RELEASED` → `RUNNING`, the occupying slot moves `CONFIRMED` → `IN_PROGRESS`, and the line moves `CHANGEOVER` → `RUNNING`."

Design: Difficulty/cross_entity_state_dependency/run_requires_installed_mold"""
        ctx = setup_released_scenario(install=False)
        install_mold(ctx["mold"]["id"], ctx["line"]["id"])
        run = validate_success(
            api.create_production_run(_run_payload(ctx), ENGINEER), 201)
        assert run["status"] == "OPEN"
        assert run["cavities_active_at_start"] == 8
        assert get_order(ctx["order"]["id"])["status"] == "RUNNING"
        slots = list_order_slots(ctx["order"]["id"])
        assert slots[0]["status"] == "IN_PROGRESS"
        line = get_success_data(api.get_machine_line(ctx["line"]["id"], ENGINEER))
        assert line["status"] == "RUNNING"


class TestStateBeforeSafety:
    def _setup_scheduled_with_hold_blockout(self, api, clear_blockout=False):
        """Order SCHEDULED (never released); mold installed with an OPEN QUALITY_HOLD blockout (optionally cleared again); clock in window."""
        ctx = setup_qualified_plant()
        ctx["order"] = setup_scheduled_order(ctx)
        ctx["lot"] = create_lot(release=True)
        ctx["mold"] = install_mold(ctx["mold"]["id"], ctx["line"]["id"])
        blk = open_blockout(ctx["mold"]["id"], 3, "QUALITY_HOLD")
        if clear_blockout:
            get_success_data(api.clear_cavity_blockout(blk["id"], ENGINEER))
        set_clock()
        return ctx

    def test_state_error_masks_safety_error(self, api):
        """PRD §2.9: "a failure at an earlier stage masks every later stage" — "Sixth come business-safety rules (quality-hold blockouts and resin compatibility)". PRD §3.6: "The order must be `RELEASED` or `RUNNING`, else `ERR_ORDER_NOT_RELEASED`."

Design: Difficulty/priority_pair_validation_conflict/run_start_state_before_safety"""
        ctx = self._setup_scheduled_with_hold_blockout(api)
        # order only SCHEDULED (P5) AND mold carries an OPEN QUALITY_HOLD
        # blockout (P6); the state error must win.
        res = api.create_production_run(_run_payload(ctx), ENGINEER)
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_RELEASED)

    def test_state_error_persists_after_blockout_cleared(self, api):
        """PRD §2.9: "a failure at an earlier stage masks every later stage." With the safety violation removed, the state rule still rejects on its own — the earlier response was not caused by the blockout.
PRD §3.6: "The order must be `RELEASED` or `RUNNING`, else `ERR_ORDER_NOT_RELEASED`."

Design: Difficulty/priority_pair_validation_conflict/run_start_state_before_safety"""
        ctx = self._setup_scheduled_with_hold_blockout(api, clear_blockout=True)
        res = api.create_production_run(_run_payload(ctx), ENGINEER)
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_RELEASED)


class TestSafetyAndCapacityGates:
    def test_quality_hold_blockout_blocks_run_start(self, api):
        """PRD §3.6: "any `OPEN` blockout on the mold with reason `QUALITY_HOLD` or `CONTAMINATION_HOLD` stops the start with `ERR_QUALITY_HOLD_BLOCKOUT`".

Design: Corner/validations/quality_hold_blockout_blocks_run_start"""
        ctx = setup_released_scenario(blockouts=[(3, "QUALITY_HOLD")])
        # effective cavitation 7 >= 4 is fine; the safety hold alone rejects
        res = api.create_production_run(_run_payload(ctx), ENGINEER)
        validate_error(res, ApiErrorId.ERR_QUALITY_HOLD_BLOCKOUT)

    def test_insufficient_cavitation_blocks_run_start(self, api):
        """PRD §3.6: "the mold's `effective_cavities` must be at least the spec's `min_cavitation_required`, else `ERR_INSUFFICIENT_CAVITATION`".

Design: Corner/validations/insufficient_cavitation_blocks_run_start"""
        ctx = setup_released_scenario(
            mold_overrides={"mold_code": "M4", "base_cavities": 4},
            blockouts=[(2, "DAMAGE")])
        # effective 4 - 1 = 3 < spec.min_cavitation_required 4
        res = api.create_production_run(_run_payload(ctx), ENGINEER)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_CAVITATION)

    def test_resin_incompatible_blocks_run_start(self, api):
        """PRD §3.6: "the spec's `resin_type` must appear in the mold's `compatible_resins`, else `ERR_RESIN_INCOMPATIBLE`".

Design: Corner/validations/resin_incompatible_blocks_run_start"""
        ctx = setup_released_scenario(
            mold_overrides={"mold_code": "MH", "compatible_resins": ["HDPE"]})
        res = api.create_production_run(_run_payload(ctx), ENGINEER)
        validate_error(res, ApiErrorId.ERR_RESIN_INCOMPATIBLE)

    def test_quarantined_lot_blocks_run_start(self, api):
        """PRD §3.6: "The resin lot — and the colorant lot when given — must be `RELEASED` or `IN_USE`, else `ERR_MATERIAL_LOT_NOT_RELEASED`."

Design: Corner/validations/quarantined_lot_blocks_run_start"""
        ctx = setup_qualified_plant()
        ctx["order"] = setup_scheduled_order(ctx)
        lot_q = create_lot(lot_code="R-100", received_kg=500)  # QUARANTINED
        create_lot(lot_code="R-101", received_kg=500, release=True)  # order gate
        ctx["mold"] = install_mold(ctx["mold"]["id"], ctx["line"]["id"])
        ctx["order"] = release_order(ctx["order"]["id"])
        set_clock()
        res = api.create_production_run(_run_payload(ctx, lot_id=lot_q["id"]),
                                        ENGINEER)
        validate_error(res, ApiErrorId.ERR_MATERIAL_LOT_NOT_RELEASED)


class TestSpecRevisionBaseline:
    def _setup_stale_baseline(self, api):
        """Order RELEASED at content_revision 1; the spec is then edited twice and re-qualified at revision 3 without re-baselining the order."""
        ctx = setup_released_scenario()
        spec_id = ctx["spec"]["id"]
        validate_success(
            api.patch_bottle_spec(spec_id, {"target_weight_g": 23}, ENGINEER), 200)
        validate_success(
            api.patch_bottle_spec(spec_id, {"neck_finish": "PCO1810"}, ENGINEER), 200)
        submit_spec(spec_id)
        begin = begin_qualification(spec_id)
        qrun = create_qualification_run(spec_id, begin["version"])
        execute_run(qrun["id"], measured_mean_weight_g=23.1)
        submit_review(qrun["id"])
        review_run(qrun["id"], "APPROVE", ctx["customer"]["id"])
        spec = get_success_data(api.get_bottle_spec(spec_id, ENGINEER))
        assert spec["status"] == "QUALIFIED" and spec["content_revision"] == 3
        return ctx

    def test_stale_baseline_blocks_run_after_requalification(self, api):
        """PRD §3.6: "the order's `spec_revision_baseline` must equal the spec's current `content_revision` — a stale baseline means the spec moved since release and the start is refused with `ERR_SPEC_REVISION_STALE`, curable by rescheduling to re-pin."

Design: Corner/validations/spec_revision_stale_blocks_run_after_requalification"""
        ctx = self._setup_stale_baseline(api)
        res = api.create_production_run(_run_payload(ctx), ENGINEER)
        validate_error(res, ApiErrorId.ERR_SPEC_REVISION_STALE)
        # re-qualification did not retroactively re-baseline the order
        assert get_order(ctx["order"]["id"])["status"] == "RELEASED"


class TestReleaseMaterialGate:
    def test_insufficient_material_blocks_release(self, api):
        """PRD §3.5: "The material gate then requires the total `available_kg` across matching `RELEASED` and `IN_USE` resin lots" "to cover the order's theoretical draw plus a five percent uplift" — "A shortfall is `ERR_INSUFFICIENT_MATERIAL`."

Design: Corner/validations/insufficient_material_blocks_release"""
        ctx = setup_qualified_plant()
        ctx["order"] = setup_scheduled_order(ctx)
        create_lot(release=True, lot_code="R-100", received_kg=50)
        # needs 3000 * 22 / 1000 * 1.05 = 69.3 kg; only 50.0 kg available
        res = api.release_production_order(ctx["order"]["id"], SCHEDULER)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_MATERIAL)
        assert get_order(ctx["order"]["id"])["status"] == "SCHEDULED"


class TestOrderAndCloseStates:
    def test_cancel_running_order_rejected(self, api):
        """PRD §3.5: "cancellation is available from `DRAFT`, `SCHEDULED`, `RELEASED`, or `HELD`" — a RUNNING order is not in that set.
PRD §2.9: "a transition that is simply not defined for the resource's current state is rejected with `ERR_INVALID_STATE` (HTTP 409)".

Design: Corner/state_machines/order_cancel_from_running_returns_invalid_state"""
        ctx = setup_running_scenario()
        res = api.cancel_production_order(ctx["order"]["id"], SCHEDULER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(ctx["order"]["id"])["status"] == "RUNNING"

    def test_close_twice_rejected_and_no_double_debit(self, api):
        """PRD §3.6: "Only an `OPEN` run whose order is still `RUNNING` can close." A second close targets a CLOSED run.
PRD §2.9: "a transition that is simply not defined for the resource's current state is rejected with `ERR_INVALID_STATE` (HTTP 409)".

Design: Corner/state_machines/run_close_twice_returns_invalid_state"""
        ctx = setup_closed_run_scenario()
        res = api.close_production_run(
            ctx["run"]["id"], close_production_run_payload(), ENGINEER)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        lot = get_success_data(api.get_material_lot(ctx["lot"]["id"], TECH))
        assert lot["consumed_kg"] == 360.0, (
            f"rejected second close must not debit again, got "
            f"{lot['consumed_kg']}")

    def test_close_counts_exceeding_production_rejected(self, api):
        """PRD §3.6: "The reported units must be physically possible: `good_count` plus `scrap_count` no greater than `cycles_completed` times the `cavities_active_at_start` snapshot, else `ERR_COUNT_EXCEEDS_PRODUCTION`."

Design: Corner/endpoints/close_counts_exceed_production_rejected"""
        ctx = setup_running_scenario()
        res = api.close_production_run(
            ctx["run"]["id"],
            close_production_run_payload(cycles_completed=10, good_count=100,
                                         scrap_count=0, actual_drawdown_kg=2.0),
            ENGINEER)
        # 100 > 10 * 8 cavities
        validate_error(res, ApiErrorId.ERR_COUNT_EXCEEDS_PRODUCTION)
        lot = get_success_data(api.get_material_lot(ctx["lot"]["id"], TECH))
        assert lot["consumed_kg"] == 0, "failed close must debit nothing"
        run = get_success_data(api.get_production_run(ctx["run"]["id"], ENGINEER))
        assert run["status"] == "OPEN"
