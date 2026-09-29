"""
Lifecycles that are not a straight line.

A panel leaves production and comes back to it, and the second attempt on the
identical from-state succeeds only because a separate remediation call cleared a
computed flag. A treatment batch loops on its own state, decaying its yield each
time, until a hard bound refuses the loop instead of moving the batch anywhere.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_GROUND_CONTROL_DEFECT_OPEN,
    ERR_REWORK_LIMIT_EXCEEDED,
)
from test_helpers.assertions import assert_purity, assert_tons
from test_helpers.constants import (
    COARSE,
    DECISION_PASS,
    DECISION_REWORK,
    FINDING_DEFECT,
    HELD_REASON_GROUND_CONTROL,
    HIGHWAY_DEICING,
    HOIST_DERATED,
    LOT_AVAILABLE,
    PANEL_PRODUCING,
    PANEL_SUSPENDED,
    QC_PASSED,
    QC_PENDING,
    RUN_HELD,
    RUN_SCHEDULED,
)
from test_helpers.test_users import GROUND_CONTROL, LAB_LEAD, MINE_PLANNER

CLOCK = "2026-08-10T00:00:00Z"


def _derated_mine_with_held_run(api):
    """
    Two producing panels, a 3000 t run over six hours on the first of them
    (500.0000 t/h), then a DEFECT inspection on that panel: the panel suspends, the
    shaft derates rather than going down because the second panel keeps producing,
    and the run is held for ground control.
    """
    fx.set_clock(api, CLOCK)
    mine = fx.create_mine(api, name="Retsof", rated_hoist_tons_per_day=24000)

    first = fx.create_panel(
        api, mine["id"], panel_code="P-1", pillar_recovery_allowed=True
    )
    fx.develop(api, first["id"])
    fx.start_production(api, first["id"])

    second = fx.create_panel(
        api, mine["id"], panel_code="P-2", pillar_recovery_allowed=True
    )
    fx.develop(api, second["id"])
    fx.start_production(api, second["id"])

    run = fx.create_run(
        api,
        mine["id"],
        first["id"],
        planned_tons=3000,
        hoist_window_start="2026-08-11T00:00:00Z",
        hoist_window_end="2026-08-11T06:00:00Z",
    )
    inspection = fx.file_inspection(
        api,
        first["id"],
        FINDING_DEFECT,
        roof_span_ft=42.0,
        convergence_rate_in_per_day=0.35,
    )
    return {
        "mine": fx.refresh_mine(api, mine["id"]),
        "panel": fx.refresh_panel(api, first["id"]),
        "other_panel": fx.refresh_panel(api, second["id"]),
        "run": fx.refresh_run(api, run["id"]),
        "inspection": inspection,
    }


def test_suspended_panel_re_enters_production_only_after_remediation(api):
    """
    `SUSPENDED → PRODUCING` is a declared edge, so the first attempt is refused by
    the open-defect guard rather than by the from-state, and the identical call
    succeeds once remediation has cleared the flag — while the permanent defect
    tally stands still at 1.

    PRD §3.2: "Bringing a panel into production — the same planner operation serves
    both `DEVELOPED → PRODUCING` and the `SUSPENDED → PRODUCING` re-entry — requires
    that the panel carry no open defect, that the mine's `compliance_state` be
    exactly `COMPLIANT`, and that the mine's `hoist_state` not be `HOIST_DOWN`."

    PRD §3.3: "Until remediation is recorded, a panel with `open_defect` true may not
    re-enter production and may not host a new or reinstated run; all three refusals
    carry `ERR_GROUND_CONTROL_DEFECT_OPEN`."

    PRD §3.3: "The `ground_control_defect_count` tally is **permanent and is never
    decremented** — it is what counts toward the third-defect abandonment."

    PRD §3.3: "Each record also carries `caused_suspension`, a computed boolean that
    is true only when filing this particular record was what moved its panel out of
    production."

    Design: Difficulty/non_linear_state_machine/panel_producing_suspended_producing_cycle_guarded_by_open_defect
    """
    world = _derated_mine_with_held_run(api)
    panel = world["panel"]
    assert panel["status"] == PANEL_SUSPENDED
    assert panel["open_defect"] is True
    assert panel["ground_control_defect_count"] == 1
    assert world["inspection"]["caused_suspension"] is True

    blocked = api.start_production(panel["id"], MINE_PLANNER)
    validate_error(blocked, ERR_GROUND_CONTROL_DEFECT_OPEN, 409)
    assert fx.refresh_panel(api, panel["id"])["status"] == PANEL_SUSPENDED

    remediated = get_success_data(
        api.remediate_defect(panel["id"], f.remediate_payload(), GROUND_CONTROL)
    )
    assert remediated["open_defect"] is False
    assert remediated["ground_control_defect_count"] == 1
    assert remediated["status"] == PANEL_SUSPENDED

    reproduced = get_success_data(api.start_production(panel["id"], MINE_PLANNER))
    assert reproduced["status"] == PANEL_PRODUCING
    assert reproduced["suspended_by_user_id"] is None

    mine = fx.refresh_mine(api, world["mine"]["id"])
    assert mine["producing_panel_count"] == 2
    # The shaft dimension is not restored by the panel returning to production.
    assert mine["hoist_state"] == HOIST_DERATED
    assert_tons(
        mine["effective_hoist_tons_per_day"], 13200.00, "effective_hoist_tons_per_day"
    )
    assert fx.refresh_panel(api, world["other_panel"]["id"])["status"] == PANEL_PRODUCING


def test_held_run_loops_back_to_scheduled_by_re_running_every_guard(api):
    """
    The run held by the suspension is not un-held by the panel's return; a planner
    reinstates it explicitly, and the loop-back passes because 500.0000 t/h still
    fits inside the derated 550.00 t/h the mine now offers.

    PRD §3.4: "Reinstatement deliberately re-runs **every** guard the original
    creation ran: the mine must be `COMPLIANT`, its shaft must not be `HOIST_DOWN`,
    the panel must be `PRODUCING` with no open defect, the aggregate half-open
    window sweep must still fit the run's hourly rate inside the mine's current
    hourly capacity, and the panel reserve must still accommodate it."

    PRD §3.4: "On success the run's `planned_tons` is added back into the mine's
    `scheduled_hoist_tons_open`, and both the run's and the mine's `version`
    increment by 1."

    Design: Difficulty/non_linear_state_machine/panel_producing_suspended_producing_cycle_guarded_by_open_defect
    """
    world = _derated_mine_with_held_run(api)
    held = world["run"]
    assert held["status"] == RUN_HELD
    assert held["held_reason"] == HELD_REASON_GROUND_CONTROL
    assert_tons(
        world["mine"]["scheduled_hoist_tons_open"], 0.00, "scheduled_hoist_tons_open"
    )

    get_success_data(
        api.remediate_defect(world["panel"]["id"], f.remediate_payload(), GROUND_CONTROL)
    )
    get_success_data(api.start_production(world["panel"]["id"], MINE_PLANNER))

    reinstated = get_success_data(api.reinstate_run(held["id"], MINE_PLANNER))

    assert reinstated["status"] == RUN_SCHEDULED
    assert reinstated["held_reason"] is None

    mine = fx.refresh_mine(api, world["mine"]["id"])
    assert_tons(
        mine["scheduled_hoist_tons_open"], 3000.00, "scheduled_hoist_tons_open"
    )
    assert mine["hoist_state"] == HOIST_DERATED


def _pending_batch(api):
    """
    A single PENDING highway-deicing batch on 6000 t of hoisted feed: coarse screen
    at 2 percent moisture, so the untouched yield is 5527.20 t at 95.500 purity.
    """
    fx.set_clock(api, CLOCK)
    world = fx.hoisted_run(
        api,
        mine_kwargs=dict(name="Retsof", rated_hoist_tons_per_day=24000),
        panel_kwargs=dict(panel_code="P-1", pillar_recovery_allowed=True),
        hoisted_tons=6000,
        planned_tons=6000,
        hoist_window_start="2026-08-11T00:00:00Z",
        hoist_window_end="2026-08-11T06:00:00Z",
    )
    world["depot"] = fx.create_depot(api, name="Depot A")
    world["batch"] = fx.create_batch(
        api,
        world["run"]["id"],
        world["depot"]["id"],
        product_line=HIGHWAY_DEICING,
        screen_spec=COARSE,
        anticaking_ppm=30,
        input_tons=6000,
        moisture_pct=2.0,
    )
    return world


def test_rework_self_loop_decays_the_yield_and_freezes_the_purity(api):
    """
    Two reworks leave the batch on the state it started from while the yield falls
    by a compounding factor — 0.97 then 0.9409 of the original 5527.20 t — and the
    assay the batch was created with never moves.

    PRD §3.5: "The batch's `yield_tons` is `input_tons` multiplied by the screen's
    yield factor, multiplied by one minus `moisture_pct` divided by 100, multiplied
    by the rework loss factor, rounded half up to two decimal places."

    PRD §3.5: "Each accepted rework increases `rework_count` by 1 and recomputes
    `yield_tons` with the loss factor of 0.97 raised to the new `rework_count` — so a
    once-reworked batch keeps 97 percent of its original yield and a twice-reworked
    batch 94.09 percent of it, since the exponent grows with each loop."

    PRD §3.5: "`purity_pct_nacl` is **not** recomputed, and the parent run's
    `open_batch_count` is left unchanged, because the batch is still pending."

    Design: Difficulty/non_linear_state_machine/treatment_batch_pending_self_loop_bounded_at_two_reworks
    """
    world = _pending_batch(api)
    batch = world["batch"]
    assert batch["qc_state"] == QC_PENDING
    assert batch["rework_count"] == 0
    assert_tons(batch["yield_tons"], 5527.20, "yield_tons")
    assert_purity(batch["purity_pct_nacl"], 95.500)

    open_before = fx.refresh_run(api, world["run"]["id"])["open_batch_count"]

    first = fx.decide_batch(api, batch["id"], DECISION_REWORK)
    assert first["qc_state"] == QC_PENDING
    assert first["rework_count"] == 1
    assert_tons(first["yield_tons"], 5361.38, "yield_tons")
    assert_purity(first["purity_pct_nacl"], 95.500)

    second = fx.decide_batch(api, batch["id"], DECISION_REWORK)
    assert second["qc_state"] == QC_PENDING
    assert second["rework_count"] == 2
    assert_tons(second["yield_tons"], 5200.54, "yield_tons")
    assert_purity(second["purity_pct_nacl"], 95.500)

    # Still pending, so nothing has been counted off the parent run.
    assert fx.refresh_run(api, world["run"]["id"])["open_batch_count"] == open_before
    assert fx.lots_of_batch(api, batch["id"]) == []


def test_third_rework_is_refused_and_the_batch_still_passes_on_the_decayed_yield(api):
    """
    The bound on the self-loop is not a state change: the third rework is refused
    outright, the counter stays at 2, and the batch then leaves `PENDING` by the only
    routes left to it, minting exactly one lot for the twice-decayed tonnage.

    PRD §3.5: "It is accepted only while `rework_count` is strictly less than 2; a
    third attempt is refused with `ERR_REWORK_LIMIT_EXCEEDED` and the batch must then
    be passed or failed."

    PRD §3.5: "On a pass, the server mints a `StockpileLot` at the batch's `depot_id`
    with `tons_on_hand` and `tons_available` both equal to `yield_tons`,
    `tons_reserved` at 0, `lot_state` at `AVAILABLE`, and `product_line`,
    `purity_pct_nacl` and `storage_kind` copied from the batch."

    Design: Difficulty/non_linear_state_machine/treatment_batch_pending_self_loop_bounded_at_two_reworks
    """
    world = _pending_batch(api)
    batch = world["batch"]
    fx.decide_batch(api, batch["id"], DECISION_REWORK)
    fx.decide_batch(api, batch["id"], DECISION_REWORK)

    refused = api.qc_decision(
        batch["id"], f.qc_decision_payload(DECISION_REWORK), LAB_LEAD
    )
    validate_error(refused, ERR_REWORK_LIMIT_EXCEEDED, 409)

    held = fx.refresh_batch(api, batch["id"])
    assert held["qc_state"] == QC_PENDING
    assert held["rework_count"] == 2
    assert_tons(held["yield_tons"], 5200.54, "yield_tons")

    passed = fx.decide_batch(api, batch["id"], DECISION_PASS)
    assert passed["qc_state"] == QC_PASSED
    assert passed["rework_count"] == 2
    assert_tons(passed["yield_tons"], 5200.54, "yield_tons")
    assert_purity(passed["purity_pct_nacl"], 95.500)

    lot = fx.lot_of_batch(api, batch["id"])
    assert lot["lot_state"] == LOT_AVAILABLE
    assert lot["depot_id"] == world["depot"]["id"]
    assert lot["product_line"] == HIGHWAY_DEICING
    assert_tons(lot["tons_on_hand"], 5200.54, "tons_on_hand")
    assert_tons(lot["tons_available"], 5200.54, "tons_available")
    assert_tons(lot["tons_reserved"], 0.00, "tons_reserved")
    assert_purity(lot["purity_pct_nacl"], 95.500)
