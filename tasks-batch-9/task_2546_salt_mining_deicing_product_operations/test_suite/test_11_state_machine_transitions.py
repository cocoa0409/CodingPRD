"""
State transitions across the mining, treatment, storage and commercial lifecycles.

These tests drive the documented edges of the salt operation: the production run from
scheduled through hoisted to closed, the panel into and out of production, the bid
contract from draft through the award fork to its season-end fork, the shipment from
planned through loaded to received or cancelled, and the delivery order through
allocation and delivery — including the refusals that guard each edge and the cascades
that fire alongside it (PRD §3.1-§3.9).
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import (
    ERR_CONTRACT_INVALID_STATE,
    ERR_MINE_WITHDRAWAL_ORDER_ACTIVE,
    ERR_RUN_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_amount,
    assert_common_fields,
    assert_hoist_capacity_view,
    assert_lot_tonnage,
    assert_money,
    assert_purity,
    assert_rate_per_hour,
    assert_tons,
    assert_version_bumped,
    assert_version_unchanged,
    only,
)
from test_helpers.constants import (
    ACTION_CITE,
    ACTION_CLEAR,
    ACTION_WITHDRAW,
    ALLOCATION_CONSUMED,
    CITED,
    COARSE,
    COMPLIANT,
    CONTRACT_AWARDED,
    CONTRACT_FORFEITED,
    CONTRACT_LOST,
    CONTRACT_SUBMITTED,
    COVERED,
    DECISION_PASS,
    DEPOT_OPEN,
    HELD_REASON_CAPACITY,
    HIGHWAY_DEICING,
    HOIST_AVAILABLE,
    HOIST_DERATED,
    JURISDICTION_STATE,
    LOT_AVAILABLE,
    MODE_RAIL,
    ORDER_DELIVERED,
    OUTCOME_AWARD,
    OUTCOME_LOSE,
    PANEL_DEVELOPED,
    PANEL_PRODUCING,
    PENALTY_NONE,
    QC_PASSED,
    QC_PENDING,
    RUN_CLOSED,
    RUN_HELD,
    RUN_HOISTED,
    RUN_SCHEDULED,
    SHIPMENT_CANCELLED,
    SHIPMENT_LOADED,
    SHIPMENT_RECEIVED,
    WITHDRAWAL_ORDER,
)
from test_helpers.test_users import (
    COMPLIANCE,
    CONTRACT_ADMIN,
    CONTRACT_ADMIN_ALT,
    LAB_LEAD,
    LOGISTICS,
    MINE_PLANNER,
    make_depot_manager_headers,
)

# The instant every test starts on, rendered the way the server renders stamps:
# "an ISO 8601 UTC instant with exactly three fractional digits" (PRD §2.4, §2.5).
EPOCH_STAMP = "2026-08-01T00:00:00.000Z"

# 100000 gross tons at a 50 percent extraction ratio, a 96.00 grade in the top grade
# tier and insolubles of 2.00 inside the forgiven band: 50000.00 recoverable tons.
PANEL_KWARGS = {
    "panel_code": "P-1",
    "gross_tons_in_place": 100000,
    "extraction_ratio_pct": 50,
    "grade_pct_nacl": 96.00,
    "insolubles_pct": 2.00,
}

# A 1000-ton run across a full 24-hour hoist window: 41.6667 tons per hour.
RUN_KWARGS = {
    "planned_tons": 1000,
    "hoist_window_start": "2026-08-02T00:00:00Z",
    "hoist_window_end": "2026-08-03T00:00:00Z",
}

# A coarse-screened highway deicing batch of 1000 dry input tons: 940.00 tons of
# yield at a purity of 96.500.
BATCH_KWARGS = {
    "product_line": HIGHWAY_DEICING,
    "screen_spec": COARSE,
    "anticaking_ppm": 20.00,
    "corrosion_inhibitor_pct": 0.50,
    "input_tons": 1000,
    "moisture_pct": 0.00,
    "storage_kind": COVERED,
}

SYRACUSE_DEPOT = {
    "name": "Syracuse Market Depot",
    "state_code": "NY",
    "covered_capacity_tons": 5000,
    "open_pad_capacity_tons": 5000,
    "loadout_rate_tons_per_hour": 500,
    "outbound_freight_rate_per_ton": 12.500,
}

ROCHESTER_DEPOT = {
    "name": "Rochester Market Depot",
    "state_code": "NY",
    "covered_capacity_tons": 5000,
    "open_pad_capacity_tons": 5000,
    "loadout_rate_tons_per_hour": 400,
    "outbound_freight_rate_per_ton": 8.000,
}

CONTRACT_KWARGS = {
    "committed_tons": 1000,
    "guaranteed_price_per_ton": 80.00,
    "failure_to_supply_penalty_per_ton": 30.00,
}

ORDER_KWARGS = {
    "requested_tons": 500,
    "required_by": "2026-12-01T00:00:00Z",
    "market_index_price_per_ton": 82.00,
}


def test_production_run_opens_scheduled_with_zero_hoisted_tonnage(api):
    """
    Scheduling shaft time against a producing panel opens the run on the scheduled
    state with nothing hoisted yet, derives the hourly rate the window implies, and
    books the planned tonnage into the mine's open schedule.

    PRD §3.4: "A new run opens with `status` at `SCHEDULED`, `hoisted_tons` at 0, `held_reason` null, `open_batch_count` at 0, and `version` at 1, and its `planned_tons` is added into the mine's `scheduled_hoist_tons_open`."
    PRD §3.4: "From the window the server derives `planned_tons_per_hour`: the run's `planned_tons` divided by the exact length of the window in hours (which may be fractional), rounded half up to four decimal places."

    Design: Corner/state_machines/production_run_create_starts_in_scheduled_with_zero_hoisted
    """
    world = fx.mine_with_producing_panel(api, panel_kwargs=PANEL_KWARGS)

    resp = api.create_run(
        f.run_payload(
            world["mine"]["id"],
            world["panel"]["id"],
            fx.mine_version(api, world["mine"]["id"]),
            **RUN_KWARGS,
        ),
        MINE_PLANNER,
    )
    run = validate_success(resp, 201)

    assert run["mine_id"] == world["mine"]["id"]
    assert run["panel_id"] == world["panel"]["id"]
    assert run["status"] == RUN_SCHEDULED
    assert run["held_reason"] is None
    assert run["open_batch_count"] == 0
    assert_tons(run["planned_tons"], 1000.00, "planned_tons")
    assert_tons(run["hoisted_tons"], 0.00, "hoisted_tons")
    assert_rate_per_hour(run["planned_tons_per_hour"], 41.6667)
    assert_common_fields(run, expected_version=1)

    mine = fx.refresh_mine(api, world["mine"]["id"])
    assert_tons(mine["scheduled_hoist_tons_open"], 1000.00, "scheduled_hoist_tons_open")

    panel = fx.refresh_panel(api, world["panel"]["id"])
    assert panel["status"] == PANEL_PRODUCING
    assert_tons(panel["mined_tons"], 0.00, "mined_tons")


def test_bid_contract_submit_moves_draft_to_submitted_and_stamps_submitter(api):
    """
    Submitting a drafted bid moves it out of draft and records who submitted it, which
    is the stamp the later award decision is compared against; the contract's value is
    still unset, because only an award computes it.

    PRD §3.8: "Submitting a draft advances `DRAFT → SUBMITTED` and stamps `submitted_by_user_id` with the submitting `X-User-ID`."
    PRD §3.8: "A draft opens with `status` at `DRAFT`, `fulfilled_tons` at 0, `take_pct` at 0, `penalty_accrued_usd` at 0, `supply_reliability_score` at 100, `breach_watch` false, `contract_value_usd`, `season_penalty_usd`, `penalty_reconciliation_delta_usd`, `submitted_by_user_id` and `decided_by_user_id` all null, and `version` at 1."

    Design: Corner/state_machines/bid_contract_submit_moves_draft_to_submitted_and_stamps_submitter
    """
    forecast = fx.create_forecast(api)
    draft = fx.create_contract(api, forecast["id"], **CONTRACT_KWARGS)

    resp = api.submit_contract(draft["id"], CONTRACT_ADMIN)
    submitted = validate_success(resp, 200)

    assert submitted["status"] == CONTRACT_SUBMITTED
    assert submitted["submitted_by_user_id"] == CONTRACT_ADMIN["X-User-ID"]
    assert submitted["decided_by_user_id"] is None
    assert submitted["contract_value_usd"] is None
    assert_tons(submitted["fulfilled_tons"], 0.00, "fulfilled_tons")
    assert_amount(submitted["take_pct"], 0.00, 2, "take_pct")
    assert_money(submitted["penalty_accrued_usd"], 0.00, "penalty_accrued_usd")
    assert_amount(
        submitted["supply_reliability_score"], 100.00, 2, "supply_reliability_score"
    )
    assert submitted["breach_watch"] is False
    assert_version_bumped(submitted, draft)


def test_bid_contract_decision_forks_to_awarded_or_lost(api):
    """
    The single decision operation splits two submitted bids down mutually exclusive
    branches: the awarded bid gains the value of the tonnage it promised, while the lost
    bid is terminal with no value at all.

    PRD §3.8: "An `outcome` of `AWARD` moves `SUBMITTED → AWARDED` and computes the contract's `contract_value_usd` as `committed_tons` multiplied by `guaranteed_price_per_ton`, rounded half up to two decimal places; the contract can then proceed to activation."
    PRD §3.8: "An `outcome` of `LOSE` moves `SUBMITTED → LOST`, which is terminal: `contract_value_usd` stays null, because a lost bid has no value to compute, and no delivery order may ever reference a lost contract."

    Design: Corner/state_machines/bid_contract_decision_forks_to_awarded_or_lost
    """
    forecast = fx.create_forecast(api)
    winner = fx.create_contract(api, forecast["id"], **CONTRACT_KWARGS)
    loser = fx.create_contract(
        api,
        forecast["id"],
        customer_name="Onondaga County DOT",
        jurisdiction_level=JURISDICTION_STATE,
        committed_tons=2000,
        guaranteed_price_per_ton=78.00,
        failure_to_supply_penalty_per_ton=30.00,
    )
    fx.submit_contract(api, winner["id"])
    fx.submit_contract(api, loser["id"])

    awarded = validate_success(
        api.decide_contract(
            winner["id"],
            f.decision_payload(OUTCOME_AWARD, note="Lowest responsive bid"),
            CONTRACT_ADMIN_ALT,
        ),
        200,
    )
    lost = validate_success(
        api.decide_contract(
            loser["id"],
            f.decision_payload(OUTCOME_LOSE, note="Undercut on freight"),
            CONTRACT_ADMIN_ALT,
        ),
        200,
    )

    assert awarded["status"] == CONTRACT_AWARDED
    assert_money(awarded["contract_value_usd"], 80000.00, "contract_value_usd")
    assert awarded["decided_by_user_id"] == CONTRACT_ADMIN_ALT["X-User-ID"]

    assert lost["status"] == CONTRACT_LOST
    assert lost["contract_value_usd"] is None
    assert lost["decided_by_user_id"] == CONTRACT_ADMIN_ALT["X-User-ID"]

    by_award, award_meta = validate_paginated(
        api.list_contracts(
            CONTRACT_ADMIN,
            {"season_forecast_id": forecast["id"], "status": CONTRACT_AWARDED},
        )
    )
    assert award_meta["total_count"] == 1
    assert only(by_award)["id"] == winner["id"]

    by_loss, loss_meta = validate_paginated(
        api.list_contracts(
            CONTRACT_ADMIN,
            {"season_forecast_id": forecast["id"], "status": CONTRACT_LOST},
        )
    )
    assert loss_meta["total_count"] == 1
    assert only(by_loss)["id"] == loser["id"]


def test_close_on_a_scheduled_run_returns_run_invalid_state(api):
    """
    A run that has not yet hoisted cannot be closed: the explicit close is reachable
    only from the hoisted state, and the refusal leaves both the run and the mine's open
    schedule exactly as they were.

    PRD §2.6: "Applies to `POST /salt/production-runs/{id}/hoist` (needs `SCHEDULED`), `POST /salt/production-runs/{id}/close` (needs `HOISTED`), `POST /salt/production-runs/{id}/reinstate` (needs `HELD`) and `POST /salt/treatment-batches` (needs the parent run `HOISTED` or `CLOSED`)."
    PRD §3.4: "A run with **zero** batches, on the other hand, never auto-closes, because the automatic path requires that at least one batch exist; such a run is closed explicitly by a `MinePlanner`, and the explicit close requires `open_batch_count` to already stand at 0."

    Design: Corner/state_machines/close_on_scheduled_run_returns_run_invalid_state
    """
    world = fx.scheduled_run(api, panel_kwargs=PANEL_KWARGS, **RUN_KWARGS)

    resp = api.close_run(world["run"]["id"], MINE_PLANNER)
    validate_error(resp, ERR_RUN_INVALID_STATE, 409)

    run = fx.refresh_run(api, world["run"]["id"])
    assert run["status"] == RUN_SCHEDULED
    assert_tons(run["hoisted_tons"], 0.00, "hoisted_tons")
    assert_version_unchanged(run, world["run"])

    mine = fx.refresh_mine(api, world["mine"]["id"])
    assert_tons(mine["scheduled_hoist_tons_open"], 1000.00, "scheduled_hoist_tons_open")


def test_resubmitting_a_submitted_bid_contract_returns_contract_invalid_state(api):
    """
    Submission is reachable only from draft, so a second submission on an already
    submitted bid is refused and cannot overwrite the stamp that records who submitted
    it first.

    PRD §2.6: "11. **Contract state** — `ERR_CONTRACT_INVALID_STATE` (409) when the bid contract is not in the state the operation requires."
    PRD §2.6: "The screening order below is therefore **normative**: the checks are evaluated in the sequence given, the first violated check is the one whose `error_id` and HTTP status the client receives, and **no side effect of any later stage is applied**."

    Design: Corner/state_machines/resubmitting_a_submitted_bid_contract_returns_contract_invalid_state
    """
    forecast = fx.create_forecast(api)
    draft = fx.create_contract(api, forecast["id"], **CONTRACT_KWARGS)
    submitted = fx.submit_contract(api, draft["id"])

    resp = api.submit_contract(draft["id"], CONTRACT_ADMIN_ALT)
    validate_error(resp, ERR_CONTRACT_INVALID_STATE, 409)

    reread = fx.refresh_contract(api, draft["id"])
    assert reread["status"] == CONTRACT_SUBMITTED
    assert reread["submitted_by_user_id"] == CONTRACT_ADMIN["X-User-ID"]
    assert_version_unchanged(reread, submitted)


def test_start_production_while_mine_under_withdrawal_order_rejected(api):
    """
    A regulator's withdrawal order shuts the whole mine down: a developed panel cannot
    be brought into production while the order stands, whatever the shaft is doing.

    PRD §2.6: "22. **Withdrawal order** — `ERR_MINE_WITHDRAWAL_ORDER_ACTIVE` (409) when the mine's `compliance_state` is `WITHDRAWAL_ORDER`, regardless of hoist availability or remaining reserve."
    PRD §3.2: "Bringing a panel into production — the same planner operation serves both `DEVELOPED → PRODUCING` and the `SUSPENDED → PRODUCING` re-entry — requires that the panel carry no open defect, that the mine's `compliance_state` be exactly `COMPLIANT`, and that the mine's `hoist_state` not be `HOIST_DOWN`."

    Design: Corner/state_machines/start_production_while_mine_under_withdrawal_order_rejected
    """
    mine = fx.create_mine(api)
    panel = fx.create_panel(api, mine["id"], **PANEL_KWARGS)
    developed = fx.develop(api, panel["id"])
    assert developed["status"] == PANEL_DEVELOPED
    withdrawn = fx.compliance_action(
        api, mine["id"], ACTION_WITHDRAW, note="Roof fall in the west panels"
    )
    assert withdrawn["compliance_state"] == WITHDRAWAL_ORDER
    assert withdrawn["hoist_state"] == HOIST_AVAILABLE

    # The compliance action itself recomputes the reserve of every live panel on the
    # mine (PRD §3.1), and "a recomputation of a derived field counts as a mutation"
    # (PRD §2.4) — so the baseline for the refused request is the panel as it stands
    # after the withdrawal order, not before it.
    before_refusal = fx.refresh_panel(api, panel["id"])
    assert before_refusal["status"] == PANEL_DEVELOPED

    resp = api.start_production(panel["id"], MINE_PLANNER)
    validate_error(resp, ERR_MINE_WITHDRAWAL_ORDER_ACTIVE, 409)

    reread = fx.refresh_panel(api, panel["id"])
    assert reread["status"] == PANEL_DEVELOPED
    assert_version_unchanged(reread, before_refusal)

    reread_mine = fx.refresh_mine(api, mine["id"])
    assert reread_mine["producing_panel_count"] == 0
    assert_tons(
        reread_mine["effective_hoist_tons_per_day"], 0.00, "effective_hoist_tons_per_day"
    )


def test_start_production_is_accepted_once_the_withdrawal_order_is_cleared(api):
    """
    Clearing the withdrawal order returns the mine to compliance and restores its
    nameplate capacity, and the very same panel then enters production and is counted.

    PRD §3.1: "Every compliance action stamps `last_compliance_action_at` from the logical clock, recomputes `effective_hoist_tons_per_day`, and increments the mine's `version` by 1."
    PRD §3.2: "Entering production increments the mine's `producing_panel_count` by 1, clears `suspended_by_user_id` back to null, and bumps both the panel's and the mine's `version`."

    Design: Corner/state_machines/start_production_while_mine_under_withdrawal_order_rejected
    """
    mine = fx.create_mine(api)
    panel = fx.create_panel(api, mine["id"], **PANEL_KWARGS)
    fx.develop(api, panel["id"])
    fx.compliance_action(api, mine["id"], ACTION_WITHDRAW, note="Roof fall")
    validate_error(
        api.start_production(panel["id"], MINE_PLANNER),
        ERR_MINE_WITHDRAWAL_ORDER_ACTIVE,
        409,
    )

    cleared = validate_success(
        api.compliance_action(
            mine["id"],
            f.compliance_action_payload(ACTION_CLEAR, note="Ground rehabilitated"),
            COMPLIANCE,
        ),
        200,
    )
    assert cleared["compliance_state"] == COMPLIANT
    assert_tons(
        cleared["effective_hoist_tons_per_day"], 24000.00, "effective_hoist_tons_per_day"
    )

    producing = validate_success(api.start_production(panel["id"], MINE_PLANNER), 200)
    assert producing["status"] == PANEL_PRODUCING
    assert producing["suspended_by_user_id"] is None
    assert fx.refresh_mine(api, mine["id"])["producing_panel_count"] == 1


def test_qc_pass_mints_lot_and_updates_depot_and_run_counters(api):
    """
    Passing quality control on one of a run's two pending batches is the only operation
    that creates tonnage: it mints a stockpile lot carrying the batch's own assay, grows
    the receiving shed's occupancy, and leaves the run's second batch still pending.

    PRD §3.5: "On a pass, the server mints a `StockpileLot` at the batch's `depot_id` with `tons_on_hand` and `tons_available` both equal to `yield_tons`, `tons_reserved` at 0, `lot_state` at `AVAILABLE`, and `product_line`, `purity_pct_nacl` and `storage_kind` copied from the batch."
    PRD §3.5: "The parent run's `open_batch_count` decreases by 1 and the run auto-closes if that brings it to 0."
    PRD §3.6: "`covered_utilization_pct` is `covered_stored_tons` multiplied by 100, divided by `covered_capacity_tons`, rounded half up to two decimal places — and it reads exactly 0 when `covered_capacity_tons` is 0, rather than erroring."

    Design: Corner/state_machines/qc_pass_mints_lot_and_updates_depot_and_run_counters
    """
    world = fx.hoisted_run(
        api, panel_kwargs=PANEL_KWARGS, hoisted_tons=1000, **RUN_KWARGS
    )
    depot = fx.create_depot(api, **SYRACUSE_DEPOT)
    first = fx.create_batch(
        api, world["run"]["id"], depot["id"], **dict(BATCH_KWARGS, input_tons=700)
    )
    second = fx.create_batch(
        api, world["run"]["id"], depot["id"], **dict(BATCH_KWARGS, input_tons=300)
    )
    assert_tons(first["yield_tons"], 658.00, "yield_tons")

    resp = api.qc_decision(
        first["id"], f.qc_decision_payload(DECISION_PASS, note="On spec"), LAB_LEAD
    )
    passed = validate_success(resp, 200)

    assert passed["qc_state"] == QC_PASSED
    assert passed["qc_decided_by_user_id"] == LAB_LEAD["X-User-ID"]

    lot = fx.lot_of_batch(api, first["id"])
    assert lot["depot_id"] == depot["id"]
    assert lot["product_line"] == HIGHWAY_DEICING
    assert lot["storage_kind"] == COVERED
    assert lot["lot_state"] == LOT_AVAILABLE
    assert_purity(lot["purity_pct_nacl"], 96.500)
    assert_lot_tonnage(lot, on_hand=658.00, reserved=0.00, available=658.00)

    reread_depot = fx.refresh_depot(api, depot["id"])
    assert_tons(reread_depot["covered_stored_tons"], 658.00, "covered_stored_tons")
    assert_tons(reread_depot["open_pad_stored_tons"], 0.00, "open_pad_stored_tons")
    assert_amount(
        reread_depot["covered_utilization_pct"], 13.16, 2, "covered_utilization_pct"
    )
    assert reread_depot["depot_state"] == DEPOT_OPEN

    run = fx.refresh_run(api, world["run"]["id"])
    assert run["status"] == RUN_HOISTED
    assert run["open_batch_count"] == 1

    still_pending = fx.refresh_batch(api, second["id"])
    assert still_pending["qc_state"] == QC_PENDING
    assert fx.lots_of_batch(api, second["id"]) == []


def test_run_auto_closes_only_when_the_last_child_batch_leaves_pending(api):
    """
    A run with two batches closes itself the instant the second one leaves quality
    control, inside that same request, and both minted lots sit in the receiving shed.

    PRD §3.4: "A run's `open_batch_count` counts the treatment batches on it whose quality control is still pending."
    PRD §3.4: "The moment the **last** such batch leaves the pending state, the run closes itself automatically inside that same request."

    Design: Corner/state_machines/run_auto_closes_only_when_the_last_child_batch_leaves_pending
    """
    world = fx.hoisted_run(
        api, panel_kwargs=PANEL_KWARGS, hoisted_tons=1000, **RUN_KWARGS
    )
    depot = fx.create_depot(api, **SYRACUSE_DEPOT)
    first = fx.create_batch(
        api, world["run"]["id"], depot["id"], **dict(BATCH_KWARGS, input_tons=700)
    )
    second = fx.create_batch(
        api, world["run"]["id"], depot["id"], **dict(BATCH_KWARGS, input_tons=300)
    )
    fx.decide_batch(api, first["id"], DECISION_PASS)

    midway = fx.refresh_run(api, world["run"]["id"])
    assert midway["status"] == RUN_HOISTED
    assert midway["open_batch_count"] == 1

    resp = api.qc_decision(
        second["id"], f.qc_decision_payload(DECISION_PASS), LAB_LEAD
    )
    validate_success(resp, 200)

    run = fx.refresh_run(api, world["run"]["id"])
    assert run["status"] == RUN_CLOSED
    assert run["open_batch_count"] == 0
    assert_tons(run["hoisted_tons"], 1000.00, "hoisted_tons")

    lots = fx.lots_at_depot(api, depot["id"])
    assert len(lots) == 2
    assert sorted(round(float(lot["tons_on_hand"]), 2) for lot in lots) == [282.00, 658.00]

    reread_depot = fx.refresh_depot(api, depot["id"])
    assert_tons(reread_depot["covered_stored_tons"], 940.00, "covered_stored_tons")
    assert_amount(
        reread_depot["covered_utilization_pct"], 18.80, 2, "covered_utilization_pct"
    )
    assert reread_depot["depot_state"] == DEPOT_OPEN

    # Closing the run is not a panel transition: the panel keeps producing.
    assert fx.refresh_panel(api, world["panel"]["id"])["status"] == PANEL_PRODUCING


def test_close_season_derives_forfeited_from_child_order_tonnage(api):
    """
    Closing the season on a contract that delivered only half its commitment forfeits it
    by arithmetic rather than by the caller's choice, prices the season shortfall net of
    the forgiven tolerance band, and docks the reliability scorecard.

    PRD §3.8: "A `ContractAdministrator` closes an `ACTIVE` contract with an optional `note`, and the server compares the contract's `take_pct` against its `min_take_pct`: a `take_pct` at or above the minimum takes `ACTIVE → CLOSED`, and a `take_pct` strictly below it takes `ACTIVE → FORFEITED`."
    PRD §3.8: "The billable shortfall is the season shortfall minus that tolerance, floored at 0, and the `season_penalty_usd` is the billable shortfall multiplied by `failure_to_supply_penalty_per_ton`, rounded half up to two decimal places."
    PRD §3.8: "The score is 100 minus both haircuts, clamped to lie between 0 and 100 inclusive."

    Design: Corner/state_machines/close_season_derives_forfeited_from_child_order_tonnage
    """
    world = fx.delivered_order(
        api,
        order_kwargs=ORDER_KWARGS,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE_DEPOT,
        run_kwargs=RUN_KWARGS,
        batch_kwargs=BATCH_KWARGS,
        contract_kwargs=CONTRACT_KWARGS,
        hoisted_tons=1000,
    )
    contract_id = world["contract"]["id"]

    resp = api.close_season(
        contract_id, CONTRACT_ADMIN, f.note_payload("Season closed under the minimum")
    )
    closed = validate_success(resp, 200)

    assert closed["status"] == CONTRACT_FORFEITED
    assert_tons(closed["fulfilled_tons"], 500.00, "fulfilled_tons")
    assert_tons(closed["open_committed_tons"], 500.00, "open_committed_tons")
    assert_amount(closed["take_pct"], 50.00, 2, "take_pct")
    assert_money(closed["season_penalty_usd"], 9000.00, "season_penalty_usd")
    assert_money(closed["penalty_accrued_usd"], 0.00, "penalty_accrued_usd")
    assert_money(
        closed["penalty_reconciliation_delta_usd"],
        9000.00,
        "penalty_reconciliation_delta_usd",
    )
    assert_amount(
        closed["supply_reliability_score"], 75.00, 2, "supply_reliability_score"
    )

    ledger = fx.contract_ledger(api, contract_id)
    assert_amount(
        ledger["supply_reliability_score"], 75.00, 2, "supply_reliability_score"
    )
    assert_tons(ledger["fulfilled_tons"], 500.00, "fulfilled_tons")

    # Closing the season cascades to no delivery order.
    order = fx.refresh_order(api, world["order"]["id"])
    assert order["status"] == ORDER_DELIVERED
    assert order["penalty_state"] == PENALTY_NONE


def test_hoist_and_compliance_dimensions_multiply_and_move_independently(api):
    """
    The shaft dimension and the regulator dimension sit on the same mine row and move
    through different operations: derating the shaft and then citing the mine multiplies
    both factors together, and clearing the citation leaves the shaft where it was.

    PRD §3.1: "Because the product is taken over *both* dimensions, a mine that is simultaneously cited and derated offers 0.55 multiplied by 0.80 — that is, 0.44 — of nameplate, not the weaker of the two factors."
    PRD §3.1: "Neither dimension constrains the other's transitions; different operators drive them through different operations; and neither has a terminal value, so a mine can cycle through all combinations indefinitely."

    Design: Corner/state_machines/hoist_and_compliance_dimensions_multiply_and_move_independently
    """
    mine = fx.create_mine(api)

    derated = validate_success(
        api.set_hoist_status(
            mine["id"],
            f.hoist_status_payload(HOIST_DERATED, note="Skip rope on reduced duty"),
            MINE_PLANNER,
        ),
        200,
    )
    assert derated["hoist_state"] == HOIST_DERATED
    assert derated["compliance_state"] == COMPLIANT
    assert_tons(
        derated["effective_hoist_tons_per_day"], 13200.00, "effective_hoist_tons_per_day"
    )

    cited = validate_success(
        api.compliance_action(
            mine["id"],
            f.compliance_action_payload(ACTION_CITE, note="Ventilation citation"),
            COMPLIANCE,
        ),
        200,
    )
    assert cited["hoist_state"] == HOIST_DERATED
    assert cited["compliance_state"] == CITED
    assert_tons(
        cited["effective_hoist_tons_per_day"], 10560.00, "effective_hoist_tons_per_day"
    )
    assert cited["last_compliance_action_at"] == EPOCH_STAMP

    view = fx.hoist_capacity(api, mine["id"])
    assert_hoist_capacity_view(
        view,
        rated=24000.00,
        hoist_factor=0.55,
        compliance_factor=0.80,
        effective=10560.00,
        scheduled_open=0.00,
        scheduled_run_count=0,
    )
    assert_amount(view["mine_hourly_capacity"], 440.00, 2, "mine_hourly_capacity")

    cleared = validate_success(
        api.compliance_action(
            mine["id"],
            f.compliance_action_payload(ACTION_CLEAR, note="Citation abated"),
            COMPLIANCE,
        ),
        200,
    )
    assert cleared["compliance_state"] == COMPLIANT
    assert cleared["hoist_state"] == HOIST_DERATED
    assert_tons(
        cleared["effective_hoist_tons_per_day"], 13200.00, "effective_hoist_tons_per_day"
    )


def test_shipment_receipt_moves_tonnage_from_one_depot_to_another(api):
    """
    Repositioning salt is a two-step transfer driven by the two depot managers: the
    origin manager loads the tonnage out of its pile and the destination manager receives
    it into a brand-new lot that carries the same provenance and assay.

    PRD §3.7: "Loading takes the tonnage physically out of the origin pile: the lot's `tons_on_hand` and `tons_available` each fall by the shipment's `tons`, `tons_reserved` is untouched, the origin depot's stored-tonnage figures and `covered_utilization_pct` are recomputed, and a lot drained to exactly 0 `tons_on_hand` with 0 `tons_reserved` moves `AVAILABLE → DEPLETED`."
    PRD §3.7: "Receipt **mints a new stockpile lot** at the destination with `tons_on_hand` and `tons_available` both equal to the shipment's `tons`, `tons_reserved` at 0, `lot_state` at `AVAILABLE`, `storage_kind` equal to the shipment's `destination_storage_kind`, and `treatment_batch_id`, `product_line` and `purity_pct_nacl` all copied from the source lot so that provenance and assay survive the move."

    Design: Corner/state_machines/shipment_receipt_moves_tonnage_from_one_depot_to_another
    """
    world = fx.lot_at_depot(
        api,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE_DEPOT,
        run_kwargs=RUN_KWARGS,
        hoisted_tons=1000,
        **BATCH_KWARGS,
    )
    origin_id = world["depot"]["id"]
    destination = fx.create_depot(api, **ROCHESTER_DEPOT)
    shipment = fx.create_shipment(
        api,
        world["lot"]["id"],
        origin_id,
        destination["id"],
        tons=400,
        mode=MODE_RAIL,
        destination_storage_kind=COVERED,
    )

    loaded = validate_success(
        api.load_shipment(shipment["id"], make_depot_manager_headers(origin_id)), 200
    )
    assert loaded["status"] == SHIPMENT_LOADED
    assert loaded["received_lot_id"] is None

    received = validate_success(
        api.receive_shipment(
            shipment["id"], make_depot_manager_headers(destination["id"])
        ),
        200,
    )
    assert received["status"] == SHIPMENT_RECEIVED
    assert received["received_lot_id"] is not None

    source_lot = fx.refresh_lot(api, world["lot"]["id"])
    assert source_lot["lot_state"] == LOT_AVAILABLE
    assert_lot_tonnage(source_lot, on_hand=540.00, reserved=0.00, available=540.00)

    origin_depot = fx.refresh_depot(api, origin_id)
    assert_tons(origin_depot["covered_stored_tons"], 540.00, "covered_stored_tons")
    assert_amount(
        origin_depot["covered_utilization_pct"], 10.80, 2, "covered_utilization_pct"
    )

    minted = only(fx.lots_at_depot(api, destination["id"]))
    assert minted["id"] == received["received_lot_id"]
    assert minted["treatment_batch_id"] == world["batch"]["id"]
    assert minted["product_line"] == HIGHWAY_DEICING
    assert minted["storage_kind"] == COVERED
    assert minted["lot_state"] == LOT_AVAILABLE
    assert_purity(minted["purity_pct_nacl"], 96.500)
    assert_lot_tonnage(minted, on_hand=400.00, reserved=0.00, available=400.00)

    destination_depot = fx.refresh_depot(api, destination["id"])
    assert_tons(destination_depot["covered_stored_tons"], 400.00, "covered_stored_tons")
    assert_amount(
        destination_depot["covered_utilization_pct"], 8.00, 2, "covered_utilization_pct"
    )
    assert destination_depot["depot_state"] == DEPOT_OPEN

    # The move conserves tonnage: 540.00 left behind plus 400.00 arrived.
    assert_tons(
        round(
            float(source_lot["tons_on_hand"]) + float(minted["tons_on_hand"]), 2
        ),
        940.00,
        "transferred tonnage",
    )


def test_deliver_syncs_contract_ledger_and_freezes_the_invoice(api):
    """
    Delivering an allocated order consumes its reserved tonnage, stamps the delivery
    instant, and computes the invoice line by line: product at the guaranteed price,
    freight at the source depot's own rate, no storm surcharge on a routine order and no
    credit while the market sits under the guarantee ceiling.

    PRD §3.9: "The order's `storm_surcharge_usd` is 6 percent of the sum of those two subtotals, rounded half up to two decimal places, when the order's `storm_priority` is `STORM_EMERGENCY`, and is exactly 0.00 when it is `ROUTINE`."
    PRD §3.9: "The credit is the amount by which the order's `market_index_price_per_ton` exceeds that ceiling — floored at 0, so a market at or below the ceiling yields no credit — multiplied by the order's total allocated tonnage, rounded half up to two decimal places."
    PRD §3.9: "The order's `invoice_total_usd` is then the `product_subtotal_usd` plus the `freight_subtotal_usd` plus the `storm_surcharge_usd` minus the `guarantee_credit_usd`, rounded half up to two decimal places."
    PRD §3.8: "`fulfilled_tons` is the sum of `allocated_tons` across the contract's delivery orders whose `status` is `DELIVERED` — only delivered orders count, so allocating tonnage moves nothing here."

    Design: Corner/state_machines/deliver_syncs_contract_ledger_and_freezes_the_invoice
    """
    world = fx.allocated_order(
        api,
        order_kwargs=ORDER_KWARGS,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE_DEPOT,
        run_kwargs=RUN_KWARGS,
        batch_kwargs=BATCH_KWARGS,
        contract_kwargs=CONTRACT_KWARGS,
        hoisted_tons=1000,
    )
    order_id = world["order"]["id"]
    contract_id = world["contract"]["id"]

    before = fx.contract_ledger(api, contract_id)
    assert_tons(before["fulfilled_tons"], 0.00, "fulfilled_tons")
    assert_amount(before["take_pct"], 0.00, 2, "take_pct")

    resp = api.deliver_order(order_id, LOGISTICS)
    delivered = validate_success(resp, 200)

    assert delivered["status"] == ORDER_DELIVERED
    assert delivered["delivered_at"] == EPOCH_STAMP
    assert_tons(delivered["allocated_tons"], 500.00, "allocated_tons")
    assert_money(delivered["product_subtotal_usd"], 40000.00, "product_subtotal_usd")
    assert_money(delivered["freight_subtotal_usd"], 6250.00, "freight_subtotal_usd")
    assert_money(delivered["storm_surcharge_usd"], 0.00, "storm_surcharge_usd")
    assert_money(delivered["guarantee_credit_usd"], 0.00, "guarantee_credit_usd")
    assert_money(delivered["invoice_total_usd"], 46250.00, "invoice_total_usd")

    for allocation in fx.allocations_of_order(api, order_id):
        assert allocation["state"] == ALLOCATION_CONSUMED

    assert_lot_tonnage(
        fx.refresh_lot(api, world["lot"]["id"]),
        on_hand=440.00,
        reserved=0.00,
        available=440.00,
    )

    after = fx.contract_ledger(api, contract_id)
    assert_tons(after["fulfilled_tons"], 500.00, "fulfilled_tons")
    assert_tons(after["open_committed_tons"], 500.00, "open_committed_tons")
    assert_amount(after["take_pct"], 50.00, 2, "take_pct")

    depot = fx.refresh_depot(api, world["depot"]["id"])
    assert_tons(depot["covered_stored_tons"], 440.00, "covered_stored_tons")
    assert_amount(depot["covered_utilization_pct"], 8.80, 2, "covered_utilization_pct")


def test_cancelling_a_loaded_shipment_restores_the_origin_lot_with_zero_drift(api):
    """
    Cancelling a shipment that has already been loaded puts every ton back where it came
    from: the origin lot and its shed return to exactly the figures they held before the
    load, and nothing at all lands at the destination.

    PRD §3.7: "Cancelling a `LOADED` shipment must put the tonnage back: the source lot's `tons_on_hand` and `tons_available` each rise by the shipment's `tons`, a source lot that had gone `DEPLETED` on the load is restored to `AVAILABLE`, and the origin depot's stored tonnage and `covered_utilization_pct` are recomputed."
    PRD §3.6: "Three tonnage figures live on each lot, and their relationship is a **conserved-quantity invariant** that must hold exactly, with zero drift at two decimal places, after every request that touches the lot: `tons_available` equals `tons_on_hand` minus the sum of `tons` across the lot's allocations whose `state` is `RESERVED`."

    Design: Corner/state_machines/cancelling_a_loaded_shipment_restores_the_origin_lot_with_zero_drift
    """
    world = fx.lot_at_depot(
        api,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE_DEPOT,
        run_kwargs=RUN_KWARGS,
        hoisted_tons=1000,
        **BATCH_KWARGS,
    )
    origin_id = world["depot"]["id"]
    destination = fx.create_depot(api, **ROCHESTER_DEPOT)
    shipment = fx.create_shipment(
        api,
        world["lot"]["id"],
        origin_id,
        destination["id"],
        tons=400,
        mode=MODE_RAIL,
        destination_storage_kind=COVERED,
    )
    validate_success(
        api.load_shipment(shipment["id"], make_depot_manager_headers(origin_id)), 200
    )
    assert_lot_tonnage(
        fx.refresh_lot(api, world["lot"]["id"]),
        on_hand=540.00,
        reserved=0.00,
        available=540.00,
    )

    resp = api.cancel_shipment(
        shipment["id"], LOGISTICS, f.cancel_payload("Rail embargo on the interchange")
    )
    cancelled = validate_success(resp, 200)

    assert cancelled["status"] == SHIPMENT_CANCELLED
    assert cancelled["received_lot_id"] is None

    restored = fx.refresh_lot(api, world["lot"]["id"])
    assert restored["lot_state"] == LOT_AVAILABLE
    assert_lot_tonnage(restored, on_hand=940.00, reserved=0.00, available=940.00)

    origin_depot = fx.refresh_depot(api, origin_id)
    assert_tons(origin_depot["covered_stored_tons"], 940.00, "covered_stored_tons")
    assert_amount(
        origin_depot["covered_utilization_pct"], 18.80, 2, "covered_utilization_pct"
    )

    destination_depot = fx.refresh_depot(api, destination["id"])
    assert_tons(destination_depot["covered_stored_tons"], 0.00, "covered_stored_tons")
    assert_amount(
        destination_depot["covered_utilization_pct"], 0.00, 2, "covered_utilization_pct"
    )
    assert fx.lots_at_depot(api, destination["id"]) == []


def test_capacity_refit_holds_only_scheduled_runs_and_spares_the_hoisted_one(api):
    """
    Derating the shaft re-fits the schedule to the smaller hourly capacity: the run that
    no longer fits is held for capacity and gives its tonnage back to the open schedule,
    while the run that has already hoisted is left alone because it holds no window.

    PRD §3.1: "While the aggregate concurrent hourly rate of the mine's `SCHEDULED` runs exceeds the mine's new hourly capacity at any instant, the offending run whose window starts latest is moved to `HELD` with `held_reason` set to `CAPACITY` — candidates are scanned by hoist window start descending and, where two windows start together, by `created_at` descending — and the loop repeats until the remaining schedule fits."
    PRD §3.4: "Runs that are `HELD`, `HOISTED`, `CLOSED` or `VOIDED` release their window and contribute nothing."

    Design: Corner/state_machines/capacity_refit_holds_only_scheduled_runs_and_spares_the_hoisted_one
    """
    world = fx.mine_with_producing_panel(api, panel_kwargs=PANEL_KWARGS)
    mine_id = world["mine"]["id"]
    panel_id = world["panel"]["id"]

    first = fx.create_run(
        api,
        mine_id,
        panel_id,
        planned_tons=24000,
        hoist_window_start="2026-08-02T00:00:00Z",
        hoist_window_end="2026-08-03T00:00:00Z",
    )
    assert_rate_per_hour(first["planned_tons_per_hour"], 1000.0000)
    fx.hoist(api, first["id"], 24000)

    second = validate_success(
        api.create_run(
            f.run_payload(
                mine_id,
                panel_id,
                fx.mine_version(api, mine_id),
                planned_tons=14400,
                hoist_window_start="2026-08-05T00:00:00Z",
                hoist_window_end="2026-08-06T00:00:00Z",
            ),
            MINE_PLANNER,
        ),
        201,
    )
    assert second["status"] == RUN_SCHEDULED
    assert_rate_per_hour(second["planned_tons_per_hour"], 600.0000)

    resp = api.set_hoist_status(
        mine_id,
        f.hoist_status_payload(HOIST_DERATED, note="Hoist motor on reduced duty"),
        MINE_PLANNER,
    )
    derated = validate_success(resp, 200)
    assert derated["hoist_state"] == HOIST_DERATED
    assert_tons(
        derated["effective_hoist_tons_per_day"], 13200.00, "effective_hoist_tons_per_day"
    )
    assert_tons(derated["scheduled_hoist_tons_open"], 0.00, "scheduled_hoist_tons_open")

    held = fx.refresh_run(api, second["id"])
    assert held["status"] == RUN_HELD
    assert held["held_reason"] == HELD_REASON_CAPACITY

    spared = fx.refresh_run(api, first["id"])
    assert spared["status"] == RUN_HOISTED
    assert spared["held_reason"] is None
    assert_tons(spared["hoisted_tons"], 24000.00, "hoisted_tons")

    view = fx.hoist_capacity(api, mine_id)
    assert_hoist_capacity_view(
        view,
        rated=24000.00,
        hoist_factor=0.55,
        compliance_factor=1.00,
        effective=13200.00,
        scheduled_open=0.00,
        scheduled_run_count=0,
    )
    assert_amount(view["mine_hourly_capacity"], 550.00, 2, "mine_hourly_capacity")

    panel = fx.refresh_panel(api, panel_id)
    assert panel["status"] == PANEL_PRODUCING
    assert_tons(panel["mined_tons"], 24000.00, "mined_tons")
