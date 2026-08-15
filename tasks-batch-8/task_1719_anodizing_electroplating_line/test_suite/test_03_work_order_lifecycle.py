"""Work order lifecycle: rework loop, terminal lockdowns, cancel rules, state gates."""
from test_helpers import (
    ApiErrorId,
    MGR,
    OP,
    QC,
    abort_load_run,
    complete_load_run,
    create_compat_rule,
    create_customer,
    create_fixture,
    create_titrated_bath,
    get_success_data,
    get_work_order,
    inspect_work_order,
    make_customer_headers,
    prepare_work_order,
    route_work_order,
    setup_awaiting_inspection,
    setup_routed_order,
    start_load_run,
    strip_and_replate,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_work_order_payload


def test_strip_replate_cycle_closes_loop():
    """PRD §3.6: "Completing the strip returns the order from `STRIPPING` to
    `READY_FOR_ROUTING` — any other state is `ERR_WORK_ORDER_NOT_STRIPPING` — and
    increments `rework_count` by one, clears `pending_strip`, clears `bath_id`,
    `fixture_id`, and `routed_chemistry_family` so the order must be routed afresh, and
    resets `predip_completed` to false so a conditional alloy must be pre-dipped again
    on the next cycle."

    Design: Difficulty/non_linear_state_machine/workorder_strip_replate_cycle
    """
    customer = create_customer(company_name="Epsilon Fasteners")
    create_compat_rule()
    fixture = create_fixture(fixture_code="RACK-05", routing_mode="RACK", capacity_dm2=500,
                             purchase_cost_cents=60000, rated_uses=40)
    bath = create_titrated_bath(bath_code="ANO-5", routing_modes_supported=["RACK"])
    wo = setup_routed_order(customer["id"], bath["id"], fixture_id=fixture["id"],
                            part_number="PN-500", routing_mode="RACK")
    assert wo["status"] == "ROUTED"
    lr = start_load_run(wo["id"], bath_id=bath["id"])
    complete_load_run(lr["id"])
    report = inspect_work_order(wo["id"], thickness_readings_um=[13.0, 14.0, 15.0],
                                defect_type="STAIN")
    assert report["disposition"] == "REWORKABLE_REJECT"
    stripping = get_success_data(
        api_client.start_strip(wo["id"], {"strip_method": "CHEMICAL"}, OP)
    )
    assert stripping["status"] == "STRIPPING"
    ready = get_success_data(api_client.complete_strip(wo["id"], OP))
    assert ready["status"] == "READY_FOR_ROUTING"
    assert ready["rework_count"] == 1
    assert ready["bath_id"] is None
    assert ready["predip_completed"] is False
    # Loop closes: the same order routes again.
    rerouted = route_work_order(wo["id"], bath["id"], fixture_id=fixture["id"])
    assert rerouted["status"] == "ROUTED"


def test_reworkable_reject_sets_pending_strip_and_defect():
    """PRD §3.6: "Everything else — defects `STAIN`, `PITTING`, or `UNDERTHICKNESS`, or
    a thickness failure with `rework_count` below two — is a `REWORKABLE_REJECT`: the
    order moves to `REJECTED` with `pending_strip` set true and the defect recorded as
    `last_defect_type`."

    Design: Difficulty/non_linear_state_machine/workorder_strip_replate_cycle
    """
    customer = create_customer(company_name="Epsilon Fasteners 2")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-5B", routing_modes_supported=["BARREL"])
    wo, _lr = setup_awaiting_inspection(customer["id"], bath["id"], part_number="PN-501")
    report = inspect_work_order(wo["id"], thickness_readings_um=[13.0, 14.0, 15.0],
                                defect_type="STAIN")
    assert report["disposition"] == "REWORKABLE_REJECT"
    refreshed = get_work_order(wo["id"])
    assert refreshed["status"] == "REJECTED"
    assert refreshed["pending_strip"] is True
    assert refreshed["last_defect_type"] == "STAIN"


def test_workorder_terminal_lockdown():
    """PRD §3.7: "Every other combination is rejected with
    `ERR_WORK_ORDER_NOT_CANCELLABLE`: an owner attempting a late-state cancel, and
    anyone at all attempting to cancel an `IN_PROCESS` order, a `COMPLETE` order, or an
    order already in a terminal state."
    PRD §3.7: "Shipping a `COMPLETE` order — a `LineOperator` or `ShopManager` action,
    rejected with `ERR_WORK_ORDER_NOT_COMPLETE` from any other state"

    Design: Corner/state_machines/workorder_terminal_lockdown
    """
    customer = create_customer(company_name="Term Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-T", routing_modes_supported=["BARREL"])
    wo, _lr = setup_awaiting_inspection(customer["id"], bath["id"], part_number="PN-T")
    inspect_work_order(wo["id"])
    shipped = get_success_data(api_client.ship_work_order(wo["id"], OP))
    assert shipped["status"] == "SHIPPED"
    resp_cancel = api_client.cancel_work_order(wo["id"], MGR)
    validate_error(resp_cancel, ApiErrorId.ERR_WORK_ORDER_NOT_CANCELLABLE)
    resp_ship2 = api_client.ship_work_order(wo["id"], OP)
    validate_error(resp_ship2, ApiErrorId.ERR_WORK_ORDER_NOT_COMPLETE)


def test_in_process_cancel_rejected_until_abort():
    """PRD §3.7: "Every other combination is rejected with
    `ERR_WORK_ORDER_NOT_CANCELLABLE`: an owner attempting a late-state cancel, and
    anyone at all attempting to cancel an `IN_PROCESS` order, a `COMPLETE` order, or an
    order already in a terminal state."
    PRD §3.7: "The owner `Customer` — or a `ShopManager` — may cancel an order in any of
    the early states `RECEIVED`, `READY_FOR_ROUTING`, `ROUTED`, or `ROUTE_HELD`; the
    cancellation is free, so `cancellation_fee_cents` is set to zero, and the fixture
    and bath links are cleared, releasing the routing."

    Design: Corner/state_machines/in_process_cancel_rejected_until_abort
    """
    customer = create_customer(company_name="Cancel Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-C", routing_modes_supported=["BARREL"])
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-C")
    lr = start_load_run(wo["id"], bath_id=bath["id"])
    # Cancel while IN_PROCESS is rejected.
    resp = api_client.cancel_work_order(wo["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_CANCELLABLE)
    # After abort the order returns to ROUTED and owner cancel succeeds with fee 0.
    aborted = abort_load_run(lr["id"])
    assert aborted["status"] == "ABORTED"
    assert get_work_order(wo["id"])["status"] == "ROUTED"
    cancelled = get_success_data(
        api_client.cancel_work_order(wo["id"], make_customer_headers(customer["id"]))
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 0


def test_late_cancel_owner_forbidden_manager_fee():
    """PRD §3.7: "A `ShopManager` alone may cancel from the late states
    `AWAITING_INSPECTION`, `REJECTED`, `STRIPPING`, and `AWAITING_LOT_TEST`; this manager
    cancel charges `cancellation_fee_cents` equal to the processing line of the pricing
    formula — step 4 evaluated on the order's current specification — multiplied by 0.5,
    rounded half-up to whole cents, and likewise clears the links."

    Design: Corner/state_machines/late_cancel_owner_forbidden_manager_fee
    """
    customer = create_customer(company_name="Late Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-L", routing_modes_supported=["BARREL"])
    wo, _lr = setup_awaiting_inspection(customer["id"], bath["id"], part_number="PN-L")
    # Ship from AWAITING_INSPECTION is rejected.
    resp_ship = api_client.ship_work_order(wo["id"], OP)
    validate_error(resp_ship, ApiErrorId.ERR_WORK_ORDER_NOT_COMPLETE)
    # Owner cancel from a late state is rejected.
    resp_owner = api_client.cancel_work_order(wo["id"], make_customer_headers(customer["id"]))
    validate_error(resp_owner, ApiErrorId.ERR_WORK_ORDER_NOT_CANCELLABLE)
    # Manager cancel succeeds with fee round_half_up(5625 x 0.5) = 2813.
    cancelled = get_success_data(api_client.cancel_work_order(wo["id"], MGR))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 2813, (
        f"Cancellation fee: expected 2813, got {cancelled['cancellation_fee_cents']}"
    )


def test_initial_states_and_prepare_twice():
    """PRD §3.4: "A new order is `RECEIVED` with `rework_count` zero, `pending_strip`
    false, `predip_completed` false, `completed_load_count` zero, `bath_id` and
    `fixture_id` null, and `final_invoice_cents` null until shipment."
    PRD §3.2: "A new bath starts `ACTIVE` with `amp_hour_used` and `amp_hour_reserved`
    at zero"
    PRD §3.5: "Preparation moves an order from `RECEIVED` to `READY_FOR_ROUTING`. A
    `LineOperator` or `ShopManager` performs it; an order in any other state rejects
    with `ERR_WORK_ORDER_NOT_RECEIVED`."
    PRD §3.5: "Routing assigns a bath and, for rack work, a fixture, moving the order
    from `READY_FOR_ROUTING` — or from `ROUTE_HELD` when re-routing to a healthy bath —
    to `ROUTED`. Any other status rejects with `ERR_WORK_ORDER_NOT_ROUTABLE`."

    Design: Corner/state_machines/initial_states_and_prepare_twice
    """
    customer = create_customer(company_name="Init Co")
    bath = create_titrated_bath(bath_code="ANO-P", routing_modes_supported=["BARREL"])
    assert bath["status"] == "ACTIVE"
    manifest = get_success_data(api_client.create_waste_manifest(
        {"generator_epa_id": "EPA-GEN-P"}, MGR
    ))
    assert manifest["status"] == "DRAFT"
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-P"),
        make_customer_headers(customer["id"]),
    ))
    assert wo["status"] == "RECEIVED"
    assert wo["version"] == 1
    # Route from RECEIVED is rejected.
    resp_route = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath["id"], "planned_duration_minutes": 40,
         "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp_route, ApiErrorId.ERR_WORK_ORDER_NOT_ROUTABLE)
    prepared = prepare_work_order(wo["id"])
    assert prepared["status"] == "READY_FOR_ROUTING"
    resp_p2 = api_client.prepare_work_order(wo["id"], {}, OP)
    validate_error(resp_p2, ApiErrorId.ERR_WORK_ORDER_NOT_RECEIVED)


def test_inspection_before_load_completion_rejected():
    """PRD §3.6: "A `QCInspector` or `ShopManager` records an **InspectionReport**
    against an order in exactly that state — any other state is
    `ERR_WORK_ORDER_NOT_AWAITING_INSPECTION`"

    Design: Corner/state_machines/inspection_before_load_completion_rejected
    """
    customer = create_customer(company_name="Insp Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-Q2", routing_modes_supported=["BARREL"])
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-Q")
    assert wo["status"] == "ROUTED"
    resp = api_client.create_inspection(
        wo["id"], {"thickness_readings_um": [13.0, 14.0, 15.0], "defect_type": "NONE"}, QC
    )
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_AWAITING_INSPECTION)
    # No report persisted.
    data, _meta = validate_paginated(api_client.list_inspections(wo["id"], QC))
    assert len(data) == 0


def test_burn_defect_scraps_immediately():
    """PRD §3.6: "`SCRAP_REJECT` applies when the defect is `BURN` or `ADHESION`
    regardless of thickness, or whenever the inspection does not pass and the order's
    `rework_count` has already reached the maximum of two completed reworks; the order
    moves to the terminal `SCRAPPED` state and no strip cycle is created."
    PRD §3.6: "Starting a strip moves a `REJECTED` order to `STRIPPING` — the operator
    supplies a `strip_method`, and an order not in `REJECTED` rejects with
    `ERR_WORK_ORDER_NOT_REJECTED`"

    Design: Corner/state_machines/burn_defect_scraps_immediately
    """
    customer = create_customer(company_name="Burn Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-B", routing_modes_supported=["BARREL"])
    wo, _lr = setup_awaiting_inspection(customer["id"], bath["id"], part_number="PN-B")
    report = inspect_work_order(wo["id"], thickness_readings_um=[13.0, 14.0, 15.0],
                                defect_type="BURN")
    assert report["disposition"] == "SCRAP_REJECT"
    assert report["thickness_ok"] is True
    refreshed = get_work_order(wo["id"])
    assert refreshed["status"] == "SCRAPPED"
    assert refreshed["rework_count"] == 0
    resp_ss = api_client.start_strip(wo["id"], {"strip_method": "CHEMICAL"}, OP)
    validate_error(resp_ss, ApiErrorId.ERR_WORK_ORDER_NOT_REJECTED)
    resp_cs = api_client.complete_strip(wo["id"], OP)
    validate_error(resp_cs, ApiErrorId.ERR_WORK_ORDER_NOT_STRIPPING)


def test_third_rejection_auto_scraps():
    """PRD §3.6: "`SCRAP_REJECT` applies when the defect is `BURN` or `ADHESION`
    regardless of thickness, or whenever the inspection does not pass and the order's
    `rework_count` has already reached the maximum of two completed reworks; the order
    moves to the terminal `SCRAPPED` state and no strip cycle is created."
    PRD §3.6: "An order accommodates at most two completed strip-and-replate cycles; the
    disposition rules above ensure a third strike scraps the order rather than looping
    it again."

    Design: Corner/state_machines/third_rejection_auto_scraps
    """
    customer = create_customer(company_name="Three Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-3X", routing_modes_supported=["BARREL"])
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-3X")
    # Lap 1: STAIN reject + strip.
    lr1 = start_load_run(wo["id"], bath_id=bath["id"])
    complete_load_run(lr1["id"])
    inspect_work_order(wo["id"], defect_type="STAIN")
    after1 = strip_and_replate(wo["id"])
    assert after1["rework_count"] == 1
    # Lap 2: PITTING reject + strip.
    route_work_order(wo["id"], bath["id"])
    lr2 = start_load_run(wo["id"], bath_id=bath["id"])
    complete_load_run(lr2["id"])
    inspect_work_order(wo["id"], defect_type="PITTING")
    after2 = strip_and_replate(wo["id"])
    assert after2["rework_count"] == 2
    # Lap 3: third reworkable-quality failure scraps the order.
    route_work_order(wo["id"], bath["id"])
    lr3 = start_load_run(wo["id"], bath_id=bath["id"])
    complete_load_run(lr3["id"])
    report3 = inspect_work_order(wo["id"], defect_type="STAIN")
    assert report3["disposition"] == "SCRAP_REJECT"
    final = get_work_order(wo["id"])
    assert final["status"] == "SCRAPPED"
    assert final["rework_count"] == 2


def test_inspection_with_two_readings_rejected():
    """PRD §2.8: "an inspection must carry at least three thickness readings"
    PRD §3.6: "submitting `thickness_readings_um`, an array of at least three positive
    readings in micrometers"

    Design: Corner/entities/inspection_with_two_readings_rejected
    """
    customer = create_customer(company_name="Read Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-I", routing_modes_supported=["BARREL"])
    wo, _lr = setup_awaiting_inspection(customer["id"], bath["id"], part_number="PN-I")
    resp = api_client.create_inspection(
        wo["id"], {"thickness_readings_um": [13.0, 14.0], "defect_type": "NONE"}, QC
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert get_work_order(wo["id"])["status"] == "AWAITING_INSPECTION"
