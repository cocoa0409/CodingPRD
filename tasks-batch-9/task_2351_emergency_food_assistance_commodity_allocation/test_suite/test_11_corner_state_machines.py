"""Cold starts, single-step transitions, refused transitions and the cascades they carry."""

from test_helpers import (
    AgreementStatus,
    AllocationStatus,
    ApiErrorId,
    CancelReason,
    CycleStatus,
    Disposition,
    DrawPosture,
    EligibilityPosture,
    HoldScope,
    LotStatus,
    MonitorFlag,
    OrderStatus,
    RecallActionStatus,
    RecallClass,
    RecallStatus,
    TrainingStatus,
    TransferStatus,
    assert_agency,
    assert_agency_axes,
    assert_allocation_cycle,
    assert_instant,
    assert_inventory_lot,
    assert_lot_ledger,
    assert_ratio,
    assert_version_incremented,
    factories as f,
    fixtures as fx,
    find_by,
    make_agency_coordinator_headers,
    make_second_state_admin_headers,
    program_case_total,
    validate_error,
    validate_success,
)

RICE_CODE = "BULK_RICE"
SECOND_ADMIN = make_second_state_admin_headers()


def _rice_warehouse_and_area(api):
    """The clock at the epoch, one DRY commodity, one warehouse and one county."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    return {"rice": rice, "warehouse": warehouse, "area": area}


def test_01_a_new_agency_starts_cold_on_both_eligibility_axes(api):
    """PRD §3.2: "A freshly registered agency starts with `agreement_status` `PENDING`,
    `training_status` `REQUIRED`, and `eligibility_posture` `INELIGIBLE`, and it does not
    move its service area's `eligible_agency_count`, because a pending agency is not
    eligible."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    env = _rice_warehouse_and_area(api)

    agency = fx.create_agency(
        api, env["area"]["id"], name="Agency Alpha", cold_storage_pallet_capacity=10
    )

    assert_agency(agency)
    assert_agency_axes(
        agency,
        AgreementStatus.PENDING,
        TrainingStatus.REQUIRED,
        EligibilityPosture.INELIGIBLE,
    )
    area = fx.read_service_area(api, env["area"]["id"])
    assert area["eligible_agency_count"] == 0, (
        "a pending agency may not move eligible_agency_count but the area reads "
        f"{area['eligible_agency_count']}"
    )


def test_02_a_new_lot_and_a_new_cycle_both_start_cold(api):
    """PRD §3.3: "The lot lands in `status` `RECEIVED` with `cases_on_hand` at 0,
    `cases_committed` at 0, `cases_shipped_to_date` at 0, `monitor_flag` at `NONE`, and
    `slow_moving_index` at 0.0; `posted_at`, `last_monitored_at`, and `hold_recall_id`
    are all null." PRD §3.4: "The cycle lands in `status` `DRAFT` with `draw_posture`
    `NOT_STARTED`, `total_allocated_cases` at 0, `eligible_agency_count` at 0,
    `admin_funds_allocated_cents` at 0, and `allocation_locked_at` null."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    env = _rice_warehouse_and_area(api)

    lot = fx.create_inventory_lot(
        api,
        env["rice"]["id"],
        env["warehouse"]["id"],
        federal_lot_code="FL-1001",
        cases_received=100,
        pack_date="2026-07-01",
        best_by_date="2028-01-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27A",
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )

    assert_inventory_lot(lot)
    assert lot["status"] == LotStatus.RECEIVED, (
        f"a fresh lot expected RECEIVED but got {lot['status']}"
    )
    assert_lot_ledger(lot, cases_on_hand=0, cases_committed=0, cases_shipped_to_date=0)
    assert lot["monitor_flag"] == MonitorFlag.NONE, (
        f"monitor_flag expected NONE but got {lot['monitor_flag']}"
    )
    assert_ratio(lot["slow_moving_index"], 0.0, "slow_moving_index")
    assert lot["posted_at"] is None, f"posted_at expected null but got {lot['posted_at']}"
    assert lot["last_monitored_at"] is None, (
        f"last_monitored_at expected null but got {lot['last_monitored_at']}"
    )
    assert lot["hold_recall_id"] is None, (
        f"hold_recall_id expected null but got {lot['hold_recall_id']}"
    )

    assert_allocation_cycle(cycle)
    assert cycle["status"] == CycleStatus.DRAFT, (
        f"a fresh cycle expected DRAFT but got {cycle['status']}"
    )
    assert cycle["draw_posture"] == DrawPosture.NOT_STARTED, (
        f"draw_posture expected NOT_STARTED but got {cycle['draw_posture']}"
    )
    assert cycle["total_allocated_cases"] == 0, (
        f"total_allocated_cases expected 0 but got {cycle['total_allocated_cases']}"
    )
    assert cycle["eligible_agency_count"] == 0, (
        f"eligible_agency_count expected 0 but got {cycle['eligible_agency_count']}"
    )
    assert cycle["admin_funds_allocated_cents"] == 0, (
        f"admin_funds_allocated_cents expected 0 but got "
        f"{cycle['admin_funds_allocated_cents']}"
    )
    assert cycle["allocation_locked_at"] is None, (
        f"allocation_locked_at expected null but got {cycle['allocation_locked_at']}"
    )


def _received_lot(api):
    """A 100-case receipt recorded at the epoch, still unposted."""
    env = _rice_warehouse_and_area(api)
    env["lot"] = fx.create_inventory_lot(
        api,
        env["rice"]["id"],
        env["warehouse"]["id"],
        federal_lot_code="FL-1001",
        cases_received=100,
        pack_date="2026-07-01",
        best_by_date="2028-01-01",
    )
    return env


def test_03_posting_seeds_the_cases_and_stamps_the_posting_instant(api):
    """PRD §3.3: "A `StateAdmin` posts a lot, moving it `RECEIVED → AVAILABLE`:
    `cases_on_hand` is set to `cases_received`, `cases_committed` is set to 0, and
    `posted_at` is stamped from the logical clock." PRD §3.3: "The lot's `version` is
    incremented."

    Design: Corner/state_machines/posting_a_received_lot_moves_it_to_available_and_seeds_cases_on_hand
    """
    env = _received_lot(api)
    fx.set_clock(api, "2026-08-02T09:00:00Z")

    posted = validate_success(api.post_inventory_lot(env["lot"]["id"], headers=fx.ADMIN))

    assert posted["status"] == LotStatus.AVAILABLE, (
        f"status expected AVAILABLE but got {posted['status']}"
    )
    assert_lot_ledger(posted, cases_on_hand=100, cases_committed=0, cases_shipped_to_date=0)
    assert_instant(posted["posted_at"], "2026-08-02T09:00:00Z", "posted_at")
    assert_version_incremented(posted["version"], env["lot"]["version"])
    assert posted["monitor_flag"] == MonitorFlag.NONE, (
        f"posting may not score the lot but monitor_flag reads {posted['monitor_flag']}"
    )
    assert_ratio(posted["slow_moving_index"], 0.0, "slow_moving_index")


def test_04_posting_an_already_posted_lot_is_refused_and_writes_nothing(api):
    """PRD §3.3: "Posting requires the lot to be in `RECEIVED` — any other status answers
    `ERR_INVALID_LOT_STATE` — and requires that no recall in `INITIATED`, `NOTIFYING`, or
    `MONITORING` covers the lot, otherwise `ERR_RECALL_HOLD_ACTIVE`." PRD §2.11: "The
    rule is that every cascade named in §3 is part of the same transaction as its
    trigger: either the whole chain lands or nothing does."

    Design: Corner/state_machines/posting_an_already_posted_lot_returns_invalid_lot_state
    """
    env = _received_lot(api)
    posted = fx.post_inventory_lot(api, env["lot"]["id"])

    response = api.post_inventory_lot(env["lot"]["id"], headers=fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_LOT_STATE, 409)
    lot = fx.read_lot(api, env["lot"]["id"])
    assert lot["status"] == LotStatus.AVAILABLE, (
        f"the lot must stay AVAILABLE but got {lot['status']}"
    )
    assert_lot_ledger(lot, cases_on_hand=100, cases_committed=0, cases_shipped_to_date=0)
    assert lot["version"] == posted["version"], (
        f"the refused post must not bump the version from {posted['version']} "
        f"but the lot reads {lot['version']}"
    )


def _draft_cycle(api):
    """One cycle sitting in DRAFT because no allocation run has happened."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    fx.create_bulk_rice(api)
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27A",
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    return cycle


def test_05_opening_the_window_of_a_draft_cycle_is_refused(api):
    """PRD §3.4: "Once allocations exist, a `StateAdmin` opens the order window, moving
    the cycle `ALLOCATED → OPEN`." PRD §2.10: "The addressed row is in a state that
    admits the requested transition — `ERR_INVALID_ORDER_STATE`,
    `ERR_INVALID_CYCLE_STATE`, `ERR_INVALID_LOT_STATE`, `ERR_INVALID_APPOINTMENT_STATE`,
    `ERR_INVALID_TRANSFER_STATE`, `ERR_INVALID_RECALL_STATE`,
    `ERR_INVALID_RECALL_ACTION_STATE`, `ERR_INVALID_DISTRIBUTION_STATE`, or
    `ERR_AGREEMENT_NOT_RENEWABLE`, whichever machine owns the row."

    Design: Corner/state_machines/open_window_on_a_draft_cycle_returns_invalid_cycle_state
    """
    cycle = _draft_cycle(api)

    response = api.open_order_window(cycle["id"], headers=fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_CYCLE_STATE, 409)
    reread = fx.read_cycle(api, cycle["id"])
    assert reread["status"] == CycleStatus.DRAFT, (
        f"the cycle must stay DRAFT but got {reread['status']}"
    )
    assert reread["allocation_locked_at"] is None, (
        f"allocation_locked_at expected null but got {reread['allocation_locked_at']}"
    )
    assert reread["version"] == cycle["version"], (
        f"the refused transition must not bump the version from {cycle['version']} "
        f"but the cycle reads {reread['version']}"
    )


def test_06_closing_and_finalizing_a_draft_cycle_are_refused_too(api):
    """PRD §3.4: "Closing the window later moves the cycle `OPEN → CLOSED` and cascades
    conditionally: every commodity order of that cycle still sitting in `DRAFT` is
    cancelled with `cancel_reason` set to `WINDOW_CLOSED`, while `SUBMITTED` and later
    orders survive so that review can finish after the window shuts." PRD §3.9:
    "**Finalizing the cycle** moves it `CLOSED → RECONCILED` and is a `StateAdmin` act."
    PRD §3.4: "Running the allocation moves the cycle `DRAFT → ALLOCATED` and is the
    heart of the program."

    Design: Corner/state_machines/open_window_on_a_draft_cycle_returns_invalid_cycle_state
    """
    cycle = _draft_cycle(api)

    validate_error(
        api.close_order_window(cycle["id"], headers=fx.ADMIN),
        ApiErrorId.ERR_INVALID_CYCLE_STATE,
        409,
    )
    validate_error(
        api.finalize_cycle(cycle["id"], headers=fx.ADMIN),
        ApiErrorId.ERR_INVALID_CYCLE_STATE,
        409,
    )

    reread = fx.read_cycle(api, cycle["id"])
    assert reread["status"] == CycleStatus.DRAFT, (
        f"the cycle must stay DRAFT but got {reread['status']}"
    )
    _rows, meta = fx.list_rows_and_meta(
        api.list_cycle_allocations(cycle["id"], headers=fx.ADMIN)
    )
    assert meta["total_count"] == 0, (
        f"a cycle that never ran may hold no entitlement row but total_count is "
        f"{meta['total_count']}"
    )


def _cancelled_order(api):
    """One eligible agency, an OPEN cycle, and a DRAFT order cancelled as WITHDRAWN."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27A",
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    fx.add_line(api, order["id"], agency["id"], rice["id"], 10)
    fx.cancel_order(api, order["id"], agency["id"], cancel_reason="WITHDRAWN")
    return {"agency": agency, "cycle": cycle, "order": order}


def test_07_a_cancelled_order_refuses_every_further_transition(api):
    """PRD §3.5: "Cancelling an order that is already `DELIVERED` or `CANCELLED` answers
    `ERR_INVALID_ORDER_STATE`." PRD §3.6: "The order must actually be in `SUBMITTED`,
    otherwise `ERR_INVALID_ORDER_STATE`." PRD §2.10: "The addressed row is in a state
    that admits the requested transition — `ERR_INVALID_ORDER_STATE`,
    `ERR_INVALID_CYCLE_STATE`, `ERR_INVALID_LOT_STATE`, `ERR_INVALID_APPOINTMENT_STATE`,
    `ERR_INVALID_TRANSFER_STATE`, `ERR_INVALID_RECALL_STATE`,
    `ERR_INVALID_RECALL_ACTION_STATE`, `ERR_INVALID_DISTRIBUTION_STATE`, or
    `ERR_AGREEMENT_NOT_RENEWABLE`, whichever machine owns the row."

    Design: Corner/state_machines/a_cancelled_order_cannot_be_submitted_or_cancelled_again
    """
    env = _cancelled_order(api)
    order_id = env["order"]["id"]
    coordinator = make_agency_coordinator_headers(env["agency"]["id"])

    validate_error(
        api.submit_order(order_id, headers=coordinator),
        ApiErrorId.ERR_INVALID_ORDER_STATE,
        409,
    )
    validate_error(
        api.cancel_order(order_id, f.cancel_reason_payload("DUPLICATE"), headers=coordinator),
        ApiErrorId.ERR_INVALID_ORDER_STATE,
        409,
    )
    validate_error(
        api.approve_order(order_id, headers=fx.SECOND_REVIEWER),
        ApiErrorId.ERR_INVALID_ORDER_STATE,
        409,
    )
    validate_error(
        api.return_order_for_revision(order_id, headers=fx.SECOND_REVIEWER),
        ApiErrorId.ERR_INVALID_ORDER_STATE,
        409,
    )


def test_08_the_cancelled_order_and_its_entitlement_stay_exactly_as_they_were(api):
    """PRD §3.5: "From `DRAFT` or `SUBMITTED` there are no commitments to release, so the
    cancellation merely writes `cancel_reason`." PRD §3.4: "The sum of `allocated_cases`
    across the cycle's entitlement rows equals the cycle's `allocatable_cases` exactly,
    and the cycle's `total_allocated_cases` is written from that sum." PRD §3.4: "Every
    entitlement row created by the run records its `cycle_id` and `agency_id` along with
    every formula intermediate — `poverty_factor`, `poverty_share`, `prior_share`,
    `raw_score`, `floor_cases`, `allocated_cases` — and starts its draw counters at
    `cases_committed` 0, `cases_delivered` 0, `cases_remaining` equal to
    `allocated_cases`, and `status` `ENTITLED`."

    Design: Corner/state_machines/a_cancelled_order_cannot_be_submitted_or_cancelled_again
    """
    env = _cancelled_order(api)
    coordinator = make_agency_coordinator_headers(env["agency"]["id"])
    api.submit_order(env["order"]["id"], headers=coordinator)

    order = fx.read_order(api, env["order"]["id"])
    assert order["status"] == OrderStatus.CANCELLED, (
        f"the order must stay CANCELLED but got {order['status']}"
    )
    assert order["cancel_reason"] == "WITHDRAWN", (
        f"cancel_reason expected WITHDRAWN but got {order['cancel_reason']}"
    )
    assert order["total_cases_approved"] == 0, (
        f"total_cases_approved expected 0 but got {order['total_cases_approved']}"
    )
    assert order["revision_count"] == 0, (
        f"revision_count expected 0 but got {order['revision_count']}"
    )

    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["allocated_cases"] == 1000, (
        f"the only eligible agency expected all 1000 cases but got "
        f"{allocation['allocated_cases']}"
    )
    assert allocation["cases_committed"] == 0, (
        f"cases_committed expected 0 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_remaining"] == 1000, (
        f"cases_remaining expected 1000 but got {allocation['cases_remaining']}"
    )
    assert allocation["status"] == AllocationStatus.ENTITLED, (
        f"entitlement status expected ENTITLED but got {allocation['status']}"
    )


def _recall_without_downstream_exposure(api):
    """A posted lot nobody ever received from, then a CLASS_II recall raised by adm-1."""
    env = _rice_warehouse_and_area(api)
    env["lot"] = fx.create_posted_lot(
        api,
        env["rice"]["id"],
        env["warehouse"]["id"],
        federal_lot_code="FL-1001",
        cases_received=100,
        pack_date="2026-07-01",
        best_by_date="2028-01-01",
    )
    env["recall"] = fx.raise_recall(
        api,
        env["lot"]["id"],
        recall_class=RecallClass.CLASS_II,
        hold_scope=HoldScope.LOT_ONLY,
        reason="Glass fragment report on the federal lot.",
    )
    return env


def test_09_dispatching_notices_needs_at_least_one_action(api):
    """PRD §3.8: "**Dispatching notices** moves the recall `INITIATED → NOTIFYING` and
    requires an `action_count` of at least 1, otherwise `ERR_INVALID_RECALL_STATE`." PRD
    §3.8: "It lands in `status` `INITIATED` with `held_lot_count`, `action_count`,
    `acknowledged_count`, `dispositioned_count`, and `accounted_cases` all at 0 and
    `notices_dispatched_at` null."

    Design: Corner/state_machines/dispatch_notices_on_a_recall_with_no_actions_returns_invalid_recall_state
    """
    env = _recall_without_downstream_exposure(api)

    response = api.dispatch_recall_notices(env["recall"]["id"], headers=fx.ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_RECALL_STATE, 409)
    recall = fx.read_recall(api, env["recall"]["id"])
    assert recall["status"] == RecallStatus.INITIATED, (
        f"the recall must stay INITIATED but got {recall['status']}"
    )
    assert recall["action_count"] == 0, (
        f"action_count expected 0 but got {recall['action_count']}"
    )
    assert recall["notices_dispatched_at"] is None, (
        f"notices_dispatched_at expected null but got {recall['notices_dispatched_at']}"
    )
    assert recall["held_lot_count"] == 1, (
        f"held_lot_count expected 1 but got {recall['held_lot_count']}"
    )


def test_10_a_recall_with_no_exposure_closes_straight_from_initiated(api):
    """PRD §3.8: "The zero-exposure escape hatch is `INITIATED → CLOSED`, available when
    the recall's `action_count` is 0: a recall raised on a lot with no delivered or
    transferred cases downstream has no action to dispatch, so it never needs to pass
    through `NOTIFYING` and `MONITORING` at all." PRD §3.8: "If no disposition was
    `DESTROYED`, the recall releases: each held lot moves `HOLD → AVAILABLE` with
    `hold_recall_id` cleared back to null, every delivery appointment that this lot's
    hold had put into `BLOCKED` moves `BLOCKED → SCHEDULED`, and every order in `HELD`
    whose `lot_assignments` reference the lot moves `HELD → APPROVED` — and where its
    appointment came back to `SCHEDULED`, the order continues on to `SCHEDULED` in the
    same cascade."

    Design: Corner/state_machines/dispatch_notices_on_a_recall_with_no_actions_returns_invalid_recall_state
    """
    env = _recall_without_downstream_exposure(api)
    api.dispatch_recall_notices(env["recall"]["id"], headers=fx.ADMIN)

    closed = validate_success(
        api.close_recall(env["recall"]["id"], headers=SECOND_ADMIN)
    )

    assert closed["status"] == RecallStatus.CLOSED, (
        f"status expected CLOSED but got {closed['status']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert lot["status"] == LotStatus.AVAILABLE, (
        f"the released lot expected AVAILABLE but got {lot['status']}"
    )
    assert lot["hold_recall_id"] is None, (
        f"hold_recall_id expected null but got {lot['hold_recall_id']}"
    )
    assert_lot_ledger(lot, cases_on_hand=100, cases_committed=0, cases_shipped_to_date=0)


def _recall_with_one_exposed_agency(api):
    """An agency holding 20 transferred cases, then a CLASS_I recall on the source lot."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    lot = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-1001",
        cases_received=100,
        pack_date="2026-07-01",
        best_by_date="2028-01-01",
    )
    transfer = fx.propose_transfer(api, lot["id"], agency["id"], 20)
    fx.accept_transfer(api, transfer["id"], agency["id"])
    recall = fx.raise_recall(
        api,
        lot["id"],
        recall_class=RecallClass.CLASS_I,
        hold_scope=HoldScope.LOT_ONLY,
        reason="Listeria positive on the federal lot.",
    )
    actions = fx.recall_actions_of(api, recall["id"])
    assert len(actions) == 1, f"expected exactly one recall action but got {len(actions)}"
    return {
        "agency": agency,
        "lot": lot,
        "recall": recall,
        "action": actions[0],
    }


def test_11_the_exposed_agency_gets_one_action_that_dispatch_notifies(api):
    """PRD §3.8: "For every agency that already received cases from a held lot, whether
    by confirmed delivery or by accepted transfer, the recall creates one `RecallAction`
    in `status` `PENDING_NOTICE` recording the `recall_id`, the `agency_id`, and an
    `exposed_cases` count captured at creation, with `disposition`, `cases_accounted`,
    `notified_at`, `acknowledged_at`, and `dispositioned_at` all empty." PRD §3.8: "Every
    action of the recall that is in `PENDING_NOTICE` moves `PENDING_NOTICE → NOTIFIED`
    with `notified_at` stamped from the logical clock, the recall's
    `notices_dispatched_at` is stamped from the same clock, and the recall's `version` is
    incremented."

    Design: Corner/state_machines/recall_lifecycle_bubbles_to_monitoring_and_returned_cases_restore_the_source_lot
    """
    env = _recall_with_one_exposed_agency(api)

    assert env["recall"]["status"] == RecallStatus.INITIATED, (
        f"a fresh recall expected INITIATED but got {env['recall']['status']}"
    )
    assert env["recall"]["held_lot_count"] == 1, (
        f"held_lot_count expected 1 but got {env['recall']['held_lot_count']}"
    )
    assert env["action"]["exposed_cases"] == 20, (
        f"exposed_cases expected 20 but got {env['action']['exposed_cases']}"
    )
    assert env["action"]["status"] == RecallActionStatus.PENDING_NOTICE, (
        f"action status expected PENDING_NOTICE but got {env['action']['status']}"
    )

    recall = validate_success(
        api.dispatch_recall_notices(env["recall"]["id"], headers=fx.ADMIN)
    )

    assert recall["status"] == RecallStatus.NOTIFYING, (
        f"status expected NOTIFYING but got {recall['status']}"
    )
    assert recall["action_count"] == 1, (
        f"action_count expected 1 but got {recall['action_count']}"
    )
    assert_instant(
        recall["notices_dispatched_at"], "2026-08-01T00:00:00Z", "notices_dispatched_at"
    )
    action = fx.read_recall_action(api, env["action"]["id"])
    assert action["status"] == RecallActionStatus.NOTIFIED, (
        f"action status expected NOTIFIED but got {action['status']}"
    )
    assert_instant(action["notified_at"], "2026-08-01T00:00:00Z", "notified_at")


def test_12_the_last_acknowledgement_bubbles_the_recall_up_to_monitoring(api):
    """PRD §3.8: "The acknowledgement stamps `acknowledged_at` from the logical clock,
    raises the recall's `acknowledged_count` — which counts every action in
    `ACKNOWLEDGED` or `DISPOSITIONED` — and increments the action's `version`." PRD §3.8:
    "When `acknowledged_count` reaches `action_count`, the acknowledgement bubbles up and
    moves the recall `NOTIFYING → MONITORING`, a transition that writes no field beyond
    the recall's own counters."

    Design: Corner/state_machines/recall_lifecycle_bubbles_to_monitoring_and_returned_cases_restore_the_source_lot
    """
    env = _recall_with_one_exposed_agency(api)
    fx.dispatch_notices(api, env["recall"]["id"])

    action = validate_success(
        api.acknowledge_recall_action(
            env["action"]["id"],
            headers=make_agency_coordinator_headers(env["agency"]["id"]),
        )
    )

    assert action["status"] == RecallActionStatus.ACKNOWLEDGED, (
        f"action status expected ACKNOWLEDGED but got {action['status']}"
    )
    assert_instant(action["acknowledged_at"], "2026-08-01T00:00:00Z", "acknowledged_at")
    recall = fx.read_recall(api, env["recall"]["id"])
    assert recall["acknowledged_count"] == 1, (
        f"acknowledged_count expected 1 but got {recall['acknowledged_count']}"
    )
    assert recall["status"] == RecallStatus.MONITORING, (
        "the last acknowledgement must bubble the recall to MONITORING but it reads "
        f"{recall['status']}"
    )
    assert recall["dispositioned_count"] == 0, (
        f"dispositioned_count expected 0 but got {recall['dispositioned_count']}"
    )


def test_13_returned_cases_travel_back_and_closure_releases_the_lot(api):
    """PRD §3.8: "Under `RETURNED_TO_STATE` the cases physically travel back: the
    agency's `agency_cases_on_hand` falls by `cases_accounted` and the source lot's
    `cases_on_hand` rises by the same amount, keeping the program case total of §2.9
    conserved." PRD §3.8: "The report writes `disposition`, `cases_accounted`, and
    `dispositioned_at`, raises the recall's `dispositioned_count` by one and its
    `accounted_cases` by `cases_accounted`, and increments the action's `version`." PRD
    §3.8: "The normal path is `MONITORING → CLOSED`, available once the recall's
    `dispositioned_count` equals its `action_count`."

    Design: Corner/state_machines/recall_lifecycle_bubbles_to_monitoring_and_returned_cases_restore_the_source_lot
    """
    env = _recall_with_one_exposed_agency(api)
    fx.dispatch_notices(api, env["recall"]["id"])
    fx.acknowledge_action(api, env["action"]["id"], env["agency"]["id"])

    action = fx.report_disposition(
        api,
        env["action"]["id"],
        env["agency"]["id"],
        disposition=Disposition.RETURNED_TO_STATE,
        cases_accounted=20,
    )

    assert action["status"] == RecallActionStatus.DISPOSITIONED, (
        f"action status expected DISPOSITIONED but got {action['status']}"
    )
    assert action["disposition"] == Disposition.RETURNED_TO_STATE, (
        f"disposition expected RETURNED_TO_STATE but got {action['disposition']}"
    )
    assert action["cases_accounted"] == 20, (
        f"cases_accounted expected 20 but got {action['cases_accounted']}"
    )
    recall = fx.read_recall(api, env["recall"]["id"])
    assert recall["dispositioned_count"] == 1, (
        f"dispositioned_count expected 1 but got {recall['dispositioned_count']}"
    )
    assert recall["accounted_cases"] == 20, (
        f"accounted_cases expected 20 but got {recall['accounted_cases']}"
    )
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 0, (
        f"agency_cases_on_hand expected 0 but got {agency['agency_cases_on_hand']}"
    )
    held = fx.read_lot(api, env["lot"]["id"])
    assert held["cases_on_hand"] == 100, (
        f"the returned cases expected cases_on_hand 100 but got {held['cases_on_hand']}"
    )

    closed = validate_success(
        api.close_recall(env["recall"]["id"], headers=SECOND_ADMIN)
    )
    assert closed["status"] == RecallStatus.CLOSED, (
        f"status expected CLOSED but got {closed['status']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert lot["status"] == LotStatus.AVAILABLE, (
        f"the released lot expected AVAILABLE but got {lot['status']}"
    )
    assert lot["hold_recall_id"] is None, (
        f"hold_recall_id expected null but got {lot['hold_recall_id']}"
    )


def _proposed_transfer(api):
    """A 20-case transfer proposal against a posted 100-case lot."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    lot = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-1001",
        cases_received=100,
        pack_date="2026-07-01",
        best_by_date="2028-01-01",
    )
    transfer = fx.propose_transfer(api, lot["id"], agency["id"], 20)
    return {"agency": agency, "lot": lot, "transfer": transfer}


def test_14_accepting_a_transfer_moves_the_cases_between_the_two_ledger_terms(api):
    """PRD §3.3: "The cases then physically move: the lot's `cases_on_hand` and
    `cases_committed` each fall by `cases`, its `cases_shipped_to_date` rises by `cases`,
    the receiving agency's `agency_cases_on_hand` rises by `cases`, and `accepted_at` is
    stamped from the logical clock." PRD §3.3: "On success the transfer is written in
    `status` `PROPOSED` with `transferred_value_cents` computed as `cases` multiplied by
    the `entitlement_value_cents_per_case` of the source lot's commodity, the lot's
    `cases_committed` grows by `cases` with `cases_on_hand` deliberately untouched, and
    the lot's `version` is incremented." PRD §2.9: "Same shape: cases leave the lot's
    `cases_on_hand` and `cases_committed`, accumulate into `cases_shipped_to_date`, and
    arrive in the receiving agency's `agency_cases_on_hand`."

    Design: Corner/state_machines/accepting_a_transfer_syncs_the_lot_ledger_and_the_agency_on_hand_count
    """
    env = _proposed_transfer(api)
    before_lot = fx.read_lot(api, env["lot"]["id"])
    assert_lot_ledger(
        before_lot, cases_on_hand=100, cases_committed=20, cases_shipped_to_date=0
    )
    before_total = program_case_total(
        [before_lot], [fx.read_agency(api, env["agency"]["id"])]
    )

    transfer = validate_success(
        api.accept_inventory_transfer(
            env["transfer"]["id"],
            headers=make_agency_coordinator_headers(env["agency"]["id"]),
        )
    )

    assert transfer["status"] == TransferStatus.ACCEPTED, (
        f"status expected ACCEPTED but got {transfer['status']}"
    )
    assert_instant(transfer["accepted_at"], "2026-08-01T00:00:00Z", "accepted_at")
    assert transfer["transferred_value_cents"] == 24000, (
        f"transferred_value_cents expected 24000 but got {transfer['transferred_value_cents']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert_lot_ledger(lot, cases_on_hand=80, cases_committed=0, cases_shipped_to_date=20)
    assert lot["status"] == LotStatus.AVAILABLE, (
        f"a lot with cases left expected AVAILABLE but got {lot['status']}"
    )
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 20, (
        f"agency_cases_on_hand expected 20 but got {agency['agency_cases_on_hand']}"
    )
    after_total = program_case_total([lot], [agency])
    assert after_total == before_total, (
        f"the program case total moved from {before_total} to {after_total} across the accept"
    )


def _two_agencies_one_approved_one_draft(api):
    """Alpha's 10-case order is APPROVED; Bravo's 15-case order is left in DRAFT."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agencies = []
    for name in ("Agency Alpha", "Agency Bravo"):
        agency = fx.create_agency(
            api,
            area["id"],
            name=name,
            cold_storage_pallet_capacity=10,
            prior_period_pounds_distributed=60000,
            prior_period_allocated_cases=400,
        )
        fx.make_agency_eligible(api, agency["id"])
        agencies.append(agency)
    alpha, bravo = agencies

    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    lot = fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-1001",
        cases_received=100,
        pack_date="2026-07-01",
        best_by_date="2028-01-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27A",
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    approved = fx.create_order(api, cycle["id"], alpha["id"], warehouse["id"])
    fx.add_line(api, approved["id"], alpha["id"], rice["id"], 10)
    fx.submit_order(api, approved["id"], alpha["id"])
    fx.approve_order(api, approved["id"])

    draft = fx.create_order(api, cycle["id"], bravo["id"], warehouse["id"])
    fx.add_line(api, draft["id"], bravo["id"], rice["id"], 15)

    return {
        "alpha": alpha,
        "bravo": bravo,
        "cycle": cycle,
        "lot": lot,
        "approved": approved,
        "draft": draft,
    }


def test_15_closing_the_window_cancels_the_draft_order_only(api):
    """PRD §3.4: "Closing the window later moves the cycle `OPEN → CLOSED` and cascades
    conditionally: every commodity order of that cycle still sitting in `DRAFT` is
    cancelled with `cancel_reason` set to `WINDOW_CLOSED`, while `SUBMITTED` and later
    orders survive so that review can finish after the window shuts." PRD §2.11: "When an
    order window closes, only `DRAFT` orders of that cycle are cancelled; `SUBMITTED` and
    later orders survive precisely so that review can continue after the window shuts."

    Design: Corner/state_machines/closing_the_order_window_cancels_only_draft_orders
    """
    env = _two_agencies_one_approved_one_draft(api)

    cycle = validate_success(api.close_order_window(env["cycle"]["id"], headers=fx.ADMIN))

    assert cycle["status"] == CycleStatus.CLOSED, (
        f"status expected CLOSED but got {cycle['status']}"
    )
    draft = fx.read_order(api, env["draft"]["id"])
    assert draft["status"] == OrderStatus.CANCELLED, (
        f"the draft order expected CANCELLED but got {draft['status']}"
    )
    assert draft["cancel_reason"] == CancelReason.WINDOW_CLOSED, (
        f"cancel_reason expected WINDOW_CLOSED but got {draft['cancel_reason']}"
    )


def test_16_the_approved_order_keeps_its_reservation_across_the_close(api):
    """PRD §3.6: "On success `approved_at` is stamped from the logical clock,
    `approved_by_user_id` records the reviewer's `X-User-ID`, each reserved lot's
    `cases_committed` carries its new reservation, the entitlement's `cases_committed`
    grows by `total_cases_approved` with `cases_remaining` recomputed and its `status`
    moved to `PARTIALLY_DRAWN`, the cycle's `draw_posture` is recomputed, and the order's
    `version` is incremented." PRD §3.4: "**Step one — the poverty factor.** Each
    included agency's `poverty_factor` is its service area's `poverty_population` divided
    by that same area's `eligible_agency_count`, rounded half up to four decimals."

    Design: Corner/state_machines/closing_the_order_window_cancels_only_draft_orders
    """
    env = _two_agencies_one_approved_one_draft(api)

    fx.close_window(api, env["cycle"]["id"])

    approved = fx.read_order(api, env["approved"]["id"])
    assert approved["status"] == OrderStatus.APPROVED, (
        f"the approved order must survive as APPROVED but got {approved['status']}"
    )
    assert approved["cancel_reason"] is None, (
        f"cancel_reason expected null but got {approved['cancel_reason']}"
    )
    assert approved["total_cases_approved"] == 10, (
        f"total_cases_approved expected 10 but got {approved['total_cases_approved']}"
    )
    lot = fx.read_lot(api, env["lot"]["id"])
    assert lot["cases_committed"] == 10, (
        f"the surviving reservation expected cases_committed 10 but got {lot['cases_committed']}"
    )
    alpha_allocation = fx.read_allocation(api, env["cycle"]["id"], env["alpha"]["id"])
    assert alpha_allocation["allocated_cases"] == 500, (
        f"two equal agencies expected 500 cases each but Alpha got "
        f"{alpha_allocation['allocated_cases']}"
    )
    assert alpha_allocation["cases_committed"] == 10, (
        f"cases_committed expected 10 but got {alpha_allocation['cases_committed']}"
    )
    assert alpha_allocation["cases_remaining"] == 490, (
        f"cases_remaining expected 490 but got {alpha_allocation['cases_remaining']}"
    )
    bravo_allocation = fx.read_allocation(api, env["cycle"]["id"], env["bravo"]["id"])
    assert bravo_allocation["cases_committed"] == 0, (
        f"cases_committed expected 0 but got {bravo_allocation['cases_committed']}"
    )
    assert bravo_allocation["cases_remaining"] == 500, (
        f"cases_remaining expected 500 but got {bravo_allocation['cases_remaining']}"
    )


def _one_draft_order(api):
    """One eligible agency with a first DRAFT order and its entitlement versions."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area North", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency Alpha",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(api, agency["id"])
    fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27A",
        allocatable_cases=1000,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])
    fx.set_clock(api, "2026-08-06T00:00:00Z")

    before = fx.read_allocation(api, cycle["id"], agency["id"])
    first = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    after = fx.read_allocation(api, cycle["id"], agency["id"])
    return {
        "agency": agency,
        "cycle": cycle,
        "warehouse": warehouse,
        "first": first,
        "version_before": before["version"],
        "version_after": after["version"],
    }


def test_17_a_second_create_supersedes_the_first_draft(api):
    """PRD §3.5: "Creation is *superseding*: any existing order of the same agency in the
    same cycle that is still in `DRAFT` is cancelled with `cancel_reason` set to
    `SUPERSEDED`, so an agency never accumulates competing drafts." PRD §3.5: "The new
    order lands in `status` `DRAFT` with `line_count` 0, `total_cases_requested` 0,
    `total_cases_approved` 0, `total_pounds` 0.0, `total_pallets` 0, `revision_count` 0,
    and `last_returned_by_user_id`, `approved_by_user_id`, `submitted_at`, `approved_at`,
    and `cancel_reason` all null."

    Design: Corner/state_machines/a_second_draft_order_supersedes_the_first_and_bumps_the_allocation_version
    """
    env = _one_draft_order(api)

    second = validate_success(
        api.create_commodity_order(
            f.commodity_order_payload(
                env["cycle"]["id"],
                env["agency"]["id"],
                env["warehouse"]["id"],
                env["version_after"],
            ),
            headers=make_agency_coordinator_headers(env["agency"]["id"]),
        ),
        201,
    )

    assert second["status"] == OrderStatus.DRAFT, (
        f"status expected DRAFT but got {second['status']}"
    )
    assert second["line_count"] == 0, (
        f"line_count expected 0 but got {second['line_count']}"
    )
    assert second["total_cases_requested"] == 0, (
        f"total_cases_requested expected 0 but got {second['total_cases_requested']}"
    )
    assert second["revision_count"] == 0, (
        f"revision_count expected 0 but got {second['revision_count']}"
    )
    assert second["cancel_reason"] is None, (
        f"cancel_reason expected null but got {second['cancel_reason']}"
    )
    first = fx.read_order(api, env["first"]["id"])
    assert first["status"] == OrderStatus.CANCELLED, (
        f"the first draft expected CANCELLED but got {first['status']}"
    )
    assert first["cancel_reason"] == CancelReason.SUPERSEDED, (
        f"cancel_reason expected SUPERSEDED but got {first['cancel_reason']}"
    )
    rows, meta = fx.list_rows_and_meta(
        api.list_commodity_orders(
            headers=fx.ADMIN,
            params={"cycle_id": env["cycle"]["id"], "agency_id": env["agency"]["id"]},
        )
    )
    assert meta["total_count"] == 2, (
        f"both orders must remain readable but total_count is {meta['total_count']}"
    )
    survivor = find_by(rows, status=OrderStatus.DRAFT)
    assert survivor["id"] == second["id"], (
        f"the surviving draft expected {second['id']} but got {survivor['id']}"
    )


def test_18_each_order_creation_bumps_the_parent_entitlement_version(api):
    """PRD §3.5: "Creation increments the parent entitlement's `version` by one — which is
    exactly why a client issuing a second create must re-read the entitlement first." PRD
    §3.4: "Every entitlement row created by the run records its `cycle_id` and
    `agency_id` along with every formula intermediate — `poverty_factor`,
    `poverty_share`, `prior_share`, `raw_score`, `floor_cases`, `allocated_cases` — and
    starts its draw counters at `cases_committed` 0, `cases_delivered` 0,
    `cases_remaining` equal to `allocated_cases`, and `status` `ENTITLED`."

    Design: Corner/state_machines/a_second_draft_order_supersedes_the_first_and_bumps_the_allocation_version
    """
    env = _one_draft_order(api)
    assert_version_incremented(env["version_after"], env["version_before"])

    validate_success(
        api.create_commodity_order(
            f.commodity_order_payload(
                env["cycle"]["id"],
                env["agency"]["id"],
                env["warehouse"]["id"],
                env["version_after"],
            ),
            headers=make_agency_coordinator_headers(env["agency"]["id"]),
        ),
        201,
    )

    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert_version_incremented(allocation["version"], env["version_after"])
    assert allocation["cases_committed"] == 0, (
        f"cases_committed expected 0 but got {allocation['cases_committed']}"
    )
    assert allocation["cases_remaining"] == allocation["allocated_cases"], (
        f"cases_remaining expected {allocation['allocated_cases']} but got "
        f"{allocation['cases_remaining']}"
    )
    assert allocation["allocated_cases"] == 1000, (
        f"the only eligible agency expected all 1000 cases but got "
        f"{allocation['allocated_cases']}"
    )
