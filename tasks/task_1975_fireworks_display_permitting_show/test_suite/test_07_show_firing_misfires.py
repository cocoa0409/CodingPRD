"""Firing, misfire logging, soak window, dud-halt cascade, sweep
reconciliation (PRD §3.7, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_expend_payload,
    create_misfire_payload,
    create_sweep_payload,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    set_clock,
    setup_event_in_progress,
    setup_event_show_complete,
)


class TestDudHaltCascade:
    def test_first_misfire_below_threshold_no_halt(self, api):
        """PRD §3.7: "On each new misfire the halt threshold is computed as the larger of an absolute floor of 2 duds and the event's `fired_count` — evaluated before this misfire, since misfires never change `fired_count` — multiplied by the 5-percent dud-rate limit and rounded up."
        PRD §3.7: "If the resulting `dud_count` has reached the threshold and the event is `IN_PROGRESS`, the system halts the show automatically: the event moves `IN_PROGRESS → SHOW_COMPLETE` with `termination_reason` set to `DUD_HALT`."

        Design: Difficulty/transitive_cascade/dud_halt_cascade
        """
        ctx = setup_event_in_progress(checkout_qty=20, expend_qty=20,
                                      decision_clock="2026-09-01T20:00:00Z")
        get_success_data(api.create_misfire(
            ctx["ev"]["id"], create_misfire_payload(ctx["batch"]["id"],
                                                    shell_description="4in dud #1"),
            ctx["crew_headers"],
        ))
        mid = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert mid["dud_count"] == 1
        assert mid["status"] == "IN_PROGRESS"

    def test_second_misfire_at_threshold_halts(self, api):
        """PRD §3.7: "If the resulting `dud_count` has reached the threshold
        and the event is `IN_PROGRESS`, the system halts the show
        automatically: the event moves `IN_PROGRESS → SHOW_COMPLETE` with
        `termination_reason` set to `DUD_HALT`."

        Design: Difficulty/transitive_cascade/dud_halt_cascade
        """
        ctx = setup_event_in_progress(checkout_qty=20, expend_qty=20,
                                      decision_clock="2026-09-01T20:00:00Z")
        get_success_data(api.create_misfire(
            ctx["ev"]["id"], create_misfire_payload(ctx["batch"]["id"],
                                                    shell_description="4in dud #1"),
            ctx["crew_headers"],
        ))
        get_success_data(api.create_misfire(
            ctx["ev"]["id"], create_misfire_payload(ctx["batch"]["id"],
                                                    shell_description="4in dud #2"),
            ctx["crew_headers"],
        ))
        end = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert end["dud_count"] == 2
        assert end["status"] == "SHOW_COMPLETE"
        assert end["termination_reason"] == "DUD_HALT"


class TestDudHaltThresholdScaling:
    def test_threshold_scales_with_fired_count(self, api):
        """PRD §3.7: "On each new misfire the halt threshold is computed as the larger of an absolute floor of 2 duds and the event's `fired_count` — evaluated before this misfire, since misfires never change `fired_count` — multiplied by the 5-percent dud-rate limit and rounded up."
        With fired_count 100 the threshold is max(2, ceil(5.0)) = 5, so the 4th misfire does not halt and the 5th does.

        Design: Corner/calculations/dud_halt_threshold_scales_with_fired_count
        """
        ctx = setup_event_in_progress(
            checkout_qty=120, expend_qty=100,
            decision_clock="2026-09-01T20:00:00Z",
            batch_overrides={"quantity_units": 200},
            magazine_overrides={"capacity_new_lbs": 200.00},
        )
        for i in range(4):
            get_success_data(api.create_misfire(
                ctx["ev"]["id"],
                create_misfire_payload(ctx["batch"]["id"], shell_description=f"dud {i+1}"),
                ctx["crew_headers"],
            ))
        mid = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert mid["dud_count"] == 4
        assert mid["status"] == "IN_PROGRESS"
        get_success_data(api.create_misfire(
            ctx["ev"]["id"], create_misfire_payload(ctx["batch"]["id"],
                                                    shell_description="dud 5"),
            ctx["crew_headers"],
        ))
        end = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert end["status"] == "SHOW_COMPLETE"
        assert end["termination_reason"] == "DUD_HALT"


class TestMisfireDisposal:
    def test_dispose_before_show_complete_rejected(self, api):
        """PRD §3.7: "Disposal of a dud is permitted once the event has
        reached `SHOW_COMPLETE` or `SWEEP_VERIFIED` (earlier attempts fail
        with `ERR_INVALID_STATE`)".

        Design: Corner/state_machines/misfire_dispose_before_show_complete_rejected
        """
        ctx = setup_event_in_progress(checkout_qty=20, expend_qty=5,
                                      decision_clock="2026-09-01T20:00:00Z")
        mf = get_success_data(api.create_misfire(
            ctx["ev"]["id"], create_misfire_payload(ctx["batch"]["id"]),
            ctx["crew_headers"],
        ))
        set_clock("2026-09-01T20:20:00Z")  # 20 min > 15 min soak, but event IN_PROGRESS
        resp = api.dispose_misfire(mf["id"], {"disposal_method": "SOAK_CRUSH"},
                                   ctx["op_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_soak_boundary_one_second_early_rejected(self, api):
        """PRD §3.7: "the clock has reached `soak_until` — earlier is
        `ERR_SOAK_INCOMPLETE`" and "Logging sets `soak_until` to 15 minutes
        after creation — disposal is allowed at or after that instant,
        inclusive".

        Design: Corner/calculations/soak_boundary_exact_15_minutes
        """
        ctx = setup_event_in_progress(checkout_qty=20, expend_qty=5,
                                      decision_clock="2026-09-01T21:00:00Z")
        set_clock("2026-09-01T22:00:00Z")
        mf = get_success_data(api.create_misfire(
            ctx["ev"]["id"], create_misfire_payload(ctx["batch"]["id"]),
            ctx["crew_headers"],
        ))
        validate_success(api.complete_show(ctx["ev"]["id"], ctx["op_headers"]))
        set_clock("2026-09-01T22:14:59Z")  # soak_until is 22:15:00
        resp = api.dispose_misfire(mf["id"], {"disposal_method": "SOAK_CRUSH"},
                                   ctx["op_headers"])
        validate_error(resp, ApiErrorId.ERR_SOAK_INCOMPLETE)
        assert resp.status_code == 409

    def test_soak_boundary_exact_instant_accepted(self, api):
        """PRD §3.7: "disposal is allowed at or after that instant,
        inclusive" — at exactly created_at + 15 minutes the disposal succeeds:
        "Disposal ... moves the record `LOGGED → DISPOSED`".

        Design: Corner/calculations/soak_boundary_exact_15_minutes
        """
        ctx = setup_event_in_progress(checkout_qty=20, expend_qty=5,
                                      decision_clock="2026-09-01T21:00:00Z")
        set_clock("2026-09-01T22:00:00Z")
        mf = get_success_data(api.create_misfire(
            ctx["ev"]["id"], create_misfire_payload(ctx["batch"]["id"]),
            ctx["crew_headers"],
        ))
        validate_success(api.complete_show(ctx["ev"]["id"], ctx["op_headers"]))
        set_clock("2026-09-01T22:15:00Z")  # exactly soak_until
        resp = api.dispose_misfire(mf["id"], {"disposal_method": "SOAK_CRUSH"},
                                   ctx["op_headers"])
        data = validate_success(resp)
        assert data["status"] == "DISPOSED"


class TestSweepReconciliation:
    def test_sweep_blocked_by_undisposed_misfire(self, api):
        """PRD §3.8: "Reconciliation gates sweep creation: if any misfire of
        the event is still `LOGGED`, the sweep is rejected with
        `ERR_SWEEP_RECONCILE_FAILED` — every dud must be disposed first."

        Design: Corner/validations/sweep_blocked_by_undisposed_misfire
        """
        ctx = setup_event_in_progress(checkout_qty=20, expend_qty=20,
                                      decision_clock="2026-09-01T20:00:00Z")
        mf = get_success_data(api.create_misfire(
            ctx["ev"]["id"], create_misfire_payload(ctx["batch"]["id"]),
            ctx["crew_headers"],
        ))
        validate_success(api.complete_show(ctx["ev"]["id"], ctx["op_headers"]))
        bad = api.create_sweep(ctx["ev"]["id"], create_sweep_payload(), ctx["crew_headers"])
        validate_error(bad, ApiErrorId.ERR_SWEEP_RECONCILE_FAILED)
        assert bad.status_code == 422
        # Dispose (soak long past) then sweep succeeds, starting PENDING (§3.8).
        set_clock("2026-09-01T22:30:00Z")
        validate_success(api.dispose_misfire(mf["id"], {"disposal_method": "BURN_PIT"},
                                             ctx["op_headers"]))
        ok = api.create_sweep(ctx["ev"]["id"], create_sweep_payload(), ctx["crew_headers"])
        sweep = validate_success(ok, expected_status=201)
        assert sweep["verdict"] == "PENDING"


class TestDerivedFieldReconciliation:
    def test_derived_fields_reconciled_after_expend(self, api):
        """PRD §3.4: "An `EXPEND` movement additionally grows the parent
        event's `fired_count` by the expended quantity" and "After every
        movement, `quantity_remaining` is `quantity_units` minus
        `qty_expended`"; PRD §2.9: "derived fields (`dud_count`,
        `fired_count`, `current_new_lbs`, batch statuses) are recomputed
        immediately".

        Design: Corner/cross_cutting_layers/derived_fields_reconciled_after_expend
        """
        ctx = setup_event_in_progress(checkout_qty=20, expend_qty=0,
                                      decision_clock="2026-09-01T20:00:00Z")
        get_success_data(api.create_movement(
            ctx["batch"]["id"], create_expend_payload(ctx["ev"]["id"], 7),
            ctx["op_headers"],
        ))
        batch = get_success_data(api.get_batch(ctx["batch"]["id"], ctx["op_headers"]))
        assert batch["quantity_remaining"] == 43
        assert batch["qty_at_show"] == 13
        assert batch["qty_expended"] == 7
        ev = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert ev["fired_count"] == 7
