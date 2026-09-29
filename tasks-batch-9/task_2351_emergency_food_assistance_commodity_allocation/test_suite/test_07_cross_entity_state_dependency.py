"""One entity's own state stays fixed while a neighbour's state decides the answer."""

from test_helpers import (
    AgreementStatus,
    ApiErrorId,
    CycleStatus,
    EligibilityPosture,
    FormulaVariant,
    HoldScope,
    LotStatus,
    OrderStatus,
    RecallClass,
    RecallStatus,
    TrainingStatus,
    TransferStatus,
    assert_agency_axes,
    assert_instant,
    assert_lot_ledger,
    fixtures as fx,
    make_agency_coordinator_headers,
    validate_error,
    validate_success,
)

RICE_CODE = "BULK_RICE"


def _draft_order_whose_agency_training_has_lapsed(api):
    """A DRAFT order that never changes while its agency's training axis lapses."""
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area One", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency One",
        cold_storage_pallet_capacity=10,
        prior_period_pounds_distributed=120000,
        prior_period_allocated_cases=400,
    )
    fx.make_agency_eligible(
        api,
        agency["id"],
        completed_at="2026-07-01T00:00:00Z",
        agreement_start_date="2026-07-01",
        agreement_end_date="2028-06-30",
    )
    rice = fx.create_bulk_rice(api)
    warehouse = fx.create_warehouse(api, name="WH North")
    fx.create_posted_lot(
        api,
        rice["id"],
        warehouse["id"],
        federal_lot_code="FL-R-001",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    cycle = fx.create_cycle(
        api,
        cycle_code="FY27DEP",
        formula_variant=FormulaVariant.STANDARD,
        allocatable_cases=1001,
        admin_funds_pool_cents=5000000,
        offered_commodity_codes=[RICE_CODE],
        order_window_open_at="2026-08-05T00:00:00Z",
        order_window_close_at="2027-12-31T00:00:00Z",
    )
    fx.compute_allocations(api, cycle["id"])
    fx.open_window(api, cycle["id"])

    order = fx.create_order(api, cycle["id"], agency["id"], warehouse["id"])
    fx.add_line(api, order["id"], agency["id"], rice["id"], 10)

    fx.set_clock(api, "2027-07-01T00:00:00Z")
    fx.run_compliance_sweep(api)
    return {"agency": agency, "cycle": cycle, "order": order}


def test_01_the_neighbours_lapsed_training_refuses_the_submit(api):
    """PRD §3.5: "The agency's posture must be `ELIGIBLE`, otherwise
    `ERR_AGENCY_INELIGIBLE`." PRD §3.2: "If `agreement_status` is `ACTIVE` and
    `training_status` is `LAPSED`, the posture is `PROBATION`."

    Design: Difficulty/cross_entity_state_dependency/order_submit_depends_on_agency_training_axis
    """
    env = _draft_order_whose_agency_training_has_lapsed(api)

    response = api.submit_order(
        env["order"]["id"],
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
        payload={},
    )

    validate_error(response, ApiErrorId.ERR_AGENCY_INELIGIBLE, 422)
    agency = fx.read_agency(api, env["agency"]["id"])
    assert_agency_axes(
        agency,
        AgreementStatus.ACTIVE,
        TrainingStatus.LAPSED,
        EligibilityPosture.PROBATION,
    )


def test_02_the_refused_order_keeps_its_own_state_untouched(api):
    """PRD §3.5: "On success `submitted_at` is stamped from the logical clock and the
    order's `version` is incremented; note that `submitted_at` records the *most
    recent* submit, so a resubmission after a revision round trip overwrites it."

    Design: Difficulty/cross_entity_state_dependency/order_submit_depends_on_agency_training_axis
    """
    env = _draft_order_whose_agency_training_has_lapsed(api)

    api.submit_order(
        env["order"]["id"],
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
        payload={},
    )

    order = fx.read_order(api, env["order"]["id"])
    assert order["status"] == OrderStatus.DRAFT, (
        f"the refused order must stay DRAFT but got {order['status']}"
    )
    assert order["submitted_at"] is None, (
        f"submitted_at must stay null but got {order['submitted_at']}"
    )
    cycle = fx.read_cycle(api, env["cycle"]["id"])
    assert cycle["status"] == CycleStatus.OPEN, (
        f"the cycle must stay OPEN but got {cycle['status']}"
    )
    allocation = fx.read_allocation(api, env["cycle"]["id"], env["agency"]["id"])
    assert allocation["cases_committed"] == 0, (
        f"cases_committed must stay 0 but got {allocation['cases_committed']}"
    )


def test_03_healing_the_neighbour_lets_the_same_call_through(api):
    """PRD §3.2: "`LAPSED → CURRENT` is re-training after expiry. It requires
    `completed_at` at or before the current instant, refreshes both timestamps, and
    recomputes the posture — an agency whose agreement is still `ACTIVE` moves from
    `PROBATION` back to `ELIGIBLE` in the same write." PRD §3.5: "Submitting the order
    hands it to compliance review and moves it `DRAFT → SUBMITTED`."

    Design: Difficulty/cross_entity_state_dependency/order_submit_depends_on_agency_training_axis
    """
    env = _draft_order_whose_agency_training_has_lapsed(api)
    api.submit_order(
        env["order"]["id"],
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
        payload={},
    )

    fx.record_training(
        api, env["agency"]["id"], completed_at="2027-07-01T00:00:00Z", attendee_count=5
    )
    healed = fx.read_agency(api, env["agency"]["id"])
    assert_agency_axes(
        healed,
        AgreementStatus.ACTIVE,
        TrainingStatus.CURRENT,
        EligibilityPosture.ELIGIBLE,
    )

    order = validate_success(
        api.submit_order(
            env["order"]["id"],
            headers=make_agency_coordinator_headers(env["agency"]["id"]),
            payload={},
        )
    )
    assert order["status"] == OrderStatus.SUBMITTED, (
        f"status expected SUBMITTED but got {order['status']}"
    )
    assert_instant(order["submitted_at"], "2027-07-01T00:00:00Z", "submitted_at")
    assert order["total_cases_requested"] == 10, (
        f"total_cases_requested expected 10 but got {order['total_cases_requested']}"
    )


def _proposed_transfer_whose_lot_went_on_hold(api):
    """A 20-case PROPOSED transfer whose source lot went to HOLD after the proposal."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    area = fx.create_service_area(
        api, name="Area One", county_code="C001", poverty_population=40000
    )
    agency = fx.create_agency(
        api,
        area["id"],
        name="Agency One",
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
        federal_lot_code="FL-R-001",
        cases_received=100,
        pack_date="2026-06-01",
        best_by_date="2028-06-01",
    )
    transfer = fx.propose_transfer(api, lot["id"], agency["id"], 20)
    recall = fx.raise_recall(
        api,
        lot["id"],
        recall_class=RecallClass.CLASS_I,
        hold_scope=HoldScope.LOT_ONLY,
        reason="Laboratory confirmed listeria in the source pack run.",
    )
    return {"agency": agency, "lot": lot, "transfer": transfer, "recall": recall}


def test_04_the_source_lots_hold_refuses_the_acceptance(api):
    """PRD §3.3: "Accepting a transfer moves it `PROPOSED → ACCEPTED`. It requires the
    acting coordinator to own the receiving agency, requires that agency's posture to
    be `ELIGIBLE` (otherwise `ERR_AGENCY_INELIGIBLE`), and requires the source lot to
    still be in `AVAILABLE` or `WATCH` — a lot that has since gone to `HOLD` answers
    `ERR_RECALL_HOLD_ACTIVE`, and any other status answers `ERR_INVALID_LOT_STATE`."

    Design: Difficulty/cross_entity_state_dependency/transfer_accept_depends_on_source_lot_hold_state
    """
    env = _proposed_transfer_whose_lot_went_on_hold(api)

    response = api.accept_inventory_transfer(
        env["transfer"]["id"],
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_RECALL_HOLD_ACTIVE, 409)


def test_05_the_transfer_keeps_its_own_proposal_state_and_value(api):
    """PRD §3.3: "On success the transfer is written in `status` `PROPOSED` with
    `transferred_value_cents` computed as `cases` multiplied by the
    `entitlement_value_cents_per_case` of the source lot's commodity, the lot's
    `cases_committed` grows by `cases` with `cases_on_hand` deliberately untouched,
    and the lot's `version` is incremented." PRD §3.3: "`accepted_at` and
    `decline_reason` are both null at this point."

    Design: Difficulty/cross_entity_state_dependency/transfer_accept_depends_on_source_lot_hold_state
    """
    env = _proposed_transfer_whose_lot_went_on_hold(api)

    api.accept_inventory_transfer(
        env["transfer"]["id"],
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
    )

    transfer = fx.read_transfer(api, env["transfer"]["id"])
    assert transfer["status"] == TransferStatus.PROPOSED, (
        f"the transfer must stay PROPOSED but got {transfer['status']}"
    )
    assert transfer["accepted_at"] is None, (
        f"accepted_at must stay null but got {transfer['accepted_at']}"
    )
    assert transfer["transferred_value_cents"] == 24000, (
        f"transferred_value_cents expected 24000 but got {transfer['transferred_value_cents']}"
    )
    agency = fx.read_agency(api, env["agency"]["id"])
    assert agency["agency_cases_on_hand"] == 0, (
        f"agency_cases_on_hand must stay 0 but got {agency['agency_cases_on_hand']}"
    )
    assert agency["eligibility_posture"] == EligibilityPosture.ELIGIBLE, (
        "the agency side of the dependency must stay ELIGIBLE but got "
        f"{agency['eligibility_posture']}"
    )


def test_06_the_lot_and_recall_hold_their_ground_across_the_refusal(api):
    """PRD §3.8: "Each covered lot moves `AVAILABLE → HOLD` or `WATCH → HOLD` — a lot
    moved from `WATCH` keeps its existing `monitor_flag`, since the hold says nothing
    about staleness — has its `hold_recall_id` set to the recall's `id`, contributes
    one to the recall's `held_lot_count`, and has its `version` incremented."

    Design: Difficulty/cross_entity_state_dependency/transfer_accept_depends_on_source_lot_hold_state
    """
    env = _proposed_transfer_whose_lot_went_on_hold(api)

    api.accept_inventory_transfer(
        env["transfer"]["id"],
        headers=make_agency_coordinator_headers(env["agency"]["id"]),
    )

    lot = fx.read_lot(api, env["lot"]["id"])
    assert lot["status"] == LotStatus.HOLD, (
        f"the source lot must stay HOLD but got {lot['status']}"
    )
    assert lot["hold_recall_id"] == env["recall"]["id"], (
        f"hold_recall_id expected {env['recall']['id']} but got {lot['hold_recall_id']}"
    )
    assert_lot_ledger(lot, cases_on_hand=100, cases_committed=20, cases_shipped_to_date=0)
    recall = fx.read_recall(api, env["recall"]["id"])
    assert recall["status"] == RecallStatus.INITIATED, (
        f"recall status expected INITIATED but got {recall['status']}"
    )
    assert recall["held_lot_count"] == 1, (
        f"held_lot_count expected 1 but got {recall['held_lot_count']}"
    )
    assert recall["action_count"] == 0, (
        f"action_count expected 0 but got {recall['action_count']}"
    )
