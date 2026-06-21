"""Validation precedence, boundary precision, cross-entity guards, and resource
temporal/capacity overlap.

Covers the priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, and resource_temporal_overlap difficulty instances.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    setup_base_shop,
    setup_in_production_project,
    setup_contracted_project,
    setup_ready_for_delivery_project,
    create_shop,
    create_material,
    create_machine,
    create_customer,
    create_project,
    add_spec,
)

ADMIN = TEST_USERS["shop_admin_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]
DESIGNER = TEST_USERS["designer_headers"]
INSTALLER = TEST_USERS["installer_headers"]


# ===========================================================================
# Difficulty / priority_pair_validation_conflict
# ===========================================================================
def test_build_job_create_state_beats_deposit_check(api):
    """PRD §4: "then that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`, 409); then cross-shop
    reference resolution (`ERR_CROSS_SHOP_REFERENCE`, 409); then the remaining
    domain checks — machine-online, machine time-conflict, install capacity,
    stock sufficiency, deposit-paid, credit-hold, empty-draw, build/change/punch/
    balance guards"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_build_job_create
    """
    # Project still DRAFT (never contracted): the state check fires before the
    # deposit-paid fiscal guard.
    shop, material, customer = setup_base_shop()
    machine = create_machine(shop["id"], changeover_buffer_min=0)
    project = create_project(shop["id"], customer["id"], margin_policy="STANDARD")
    add_spec(shop["id"], project["id"], material["id"], quantity=4, base_unit_price_cents=100000)

    resp = api.create_build_job(
        shop["id"], project["id"],
        {"machine_id": machine["id"], "start_utc": "2026-07-06T09:00:00Z", "end_utc": "2026-07-06T12:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_build_job_start_safety_beats_temporal(api):
    """PRD §3.6: "A scheduled build job is started by a manager or admin, which
    requires the job's machine to be `ONLINE` (otherwise `ERR_MACHINE_OFFLINE`)
    and moves the job to `IN_PROGRESS`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_build_job_start
    """
    # Project IN_PRODUCTION with a SCHEDULED build job; machine taken OFFLINE before start.
    ctx = setup_in_production_project(
        specs=[{"quantity": 4}], finish_code="PAINT",
        build_start="2026-07-07T09:00:00Z", build_end="2026-07-07T12:00:00Z",
    )
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    machine_id = ctx["machine"]["id"]
    bj_id = ctx["build_job"]["id"]

    get_success_data(api.update_machine(shop_id, machine_id, {"status": "OFFLINE"}, MANAGER))
    resp = api.start_build_job(shop_id, proj_id, bj_id, MANAGER)
    validate_error(resp, ApiErrorId.ERR_MACHINE_OFFLINE.value)


# ===========================================================================
# Difficulty / boundary_precision_check
# ===========================================================================
def test_reservation_sheets_equal_available_succeeds(api):
    """PRD §3.6: "A reservation may be created only when its requested `sheets`
    does not exceed the material's `available_sheets` at create time; a request
    that would over-allocate is rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/boundary_precision_check/reservation_sheets_equal_available_succeeds_one_more_fails
    """
    # Material on_hand=5, available=5. sheets==5 (boundary) succeeds.
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN", restock=5)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    mat_id = ctx["material"]["id"]
    dep_id = ctx["deposit_draw"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    get_success_data(api.issue_draw(shop_id, proj_id, dep_id, MANAGER))
    get_success_data(api.pay_draw(shop_id, proj_id, dep_id, cust))

    resp = api.create_reservation(shop_id, proj_id, {"material_id": mat_id, "sheets": 5}, MANAGER)
    data = validate_success(resp, 201)
    assert data["status"] == "HELD", f"sheets==available (5==5) must succeed in HELD, got {data['status']}"


def test_reservation_sheets_over_available_rejected(api):
    """PRD §3.6: "A reservation may be created only when its requested `sheets`
    does not exceed the material's `available_sheets` at create time; a request
    that would over-allocate is rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/boundary_precision_check/reservation_sheets_equal_available_succeeds_one_more_fails
    """
    # Material on_hand=5, available=5. sheets==6 (available+1) is rejected.
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN", restock=5)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    mat_id = ctx["material"]["id"]
    dep_id = ctx["deposit_draw"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    get_success_data(api.issue_draw(shop_id, proj_id, dep_id, MANAGER))
    get_success_data(api.pay_draw(shop_id, proj_id, dep_id, cust))

    resp = api.create_reservation(shop_id, proj_id, {"material_id": mat_id, "sheets": 6}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


def test_measure_with_zero_specs_rejected(api):
    """PRD §3.5: "This measure step requires that at least one `CabinetSpec`
    exists on the project — otherwise it is rejected with `ERR_NO_SPECS` — and
    that every spec has positive `width_mm`, `height_mm`, and `depth_mm` and a
    `quantity` of at least one."

    Design: Difficulty/boundary_precision_check/measure_with_zero_specs_empty_set_boundary
    """
    shop = create_shop(tax_rate_bps=0)
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], margin_policy="STANDARD")
    resp = api.measure_project(shop["id"], project["id"], DESIGNER)
    validate_error(resp, ApiErrorId.ERR_NO_SPECS.value)


def test_measure_with_one_spec_succeeds(api):
    """PRD §3.5: "This measure step requires that at least one `CabinetSpec`
    exists on the project — otherwise it is rejected with `ERR_NO_SPECS`"

    Design: Difficulty/boundary_precision_check/measure_with_zero_specs_empty_set_boundary
    """
    # The one-spec side of the zero-count boundary: a single spec passes measure.
    shop = create_shop(tax_rate_bps=0)
    material = create_material(shop["id"])
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], margin_policy="STANDARD")
    add_spec(shop["id"], project["id"], material["id"], quantity=1, base_unit_price_cents=100000)
    measured = validate_success(api.measure_project(shop["id"], project["id"], DESIGNER))
    assert measured["status"] == "MEASURED", f"one spec must allow measure, got {measured['status']}"


# ===========================================================================
# Difficulty / cross_entity_state_dependency
# ===========================================================================
def test_build_job_blocked_until_deposit_paid(api):
    """PRD §3.6: "Crucially, scheduling the first build job on a `CONTRACTED`
    project is what moves the project to `IN_PRODUCTION`, and that transition is
    gated: the project's `paid_to_date_cents` must be at least its
    `deposit_required_cents`, otherwise the build job is refused with
    `ERR_DEPOSIT_UNPAID`."

    Design: Difficulty/cross_entity_state_dependency/build_job_blocked_until_project_contracted_and_deposit_paid
    """
    # CONTRACTED project; deposit NOT paid (paid_to_date 0 < deposit_required).
    ctx = setup_contracted_project(specs=[{"quantity": 4}], finish_code="PAINT")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    machine = create_machine(shop_id, changeover_buffer_min=0)

    resp = api.create_build_job(
        shop_id, proj_id,
        {"machine_id": machine["id"], "start_utc": "2026-07-08T09:00:00Z", "end_utc": "2026-07-08T12:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_UNPAID.value)


def test_installation_start_blocked_until_project_ready(api):
    """PRD §3.9: "An installer starts a scheduled installation, which requires the
    project to be in `READY_FOR_DELIVERY` (otherwise `ERR_PROJECT_NOT_READY`) and
    moves it to `IN_PROGRESS`."

    Design: Difficulty/cross_entity_state_dependency/installation_start_blocked_until_project_ready
    """
    # Project IN_PRODUCTION (not marked ready); an Installation SCHEDULED.
    ctx = setup_in_production_project(
        specs=[{"quantity": 4}], finish_code="PAINT",
        shop_overrides={"tax_rate_bps": 0, "deposit_pct_bps": 3000, "max_installs_per_day": 2},
        build_start="2026-07-09T09:00:00Z", build_end="2026-07-09T12:00:00Z",
    )
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    inst = get_success_data(api.create_installation(
        shop_id, proj_id,
        {"install_date": "2026-08-01", "window_start_utc": "2026-08-01T08:00:00Z", "window_end_utc": "2026-08-01T12:00:00Z"},
        MANAGER,
    ))
    resp = api.start_installation(shop_id, proj_id, inst["id"], INSTALLER)
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_READY.value)


# ===========================================================================
# Difficulty / resource_temporal_overlap
# ===========================================================================
def test_build_job_overlap_within_changeover_buffer(api):
    """PRD §3.6: "A new build job's time interval, from `start_utc` up to but not
    including `end_utc`, must not collide with any other non-cancelled build job
    on the same machine, and the collision test extends the machine's
    `changeover_buffer_min` gap onto either side of the interval; a clash is
    rejected with `ERR_MACHINE_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/build_job_overlap_with_changeover_buffer_on_machine
    """
    # Shared machine changeover_buffer_min=30. P1 build job 09:00-12:00; P2 attempts
    # 12:20-13:00 -> within the 30-min buffer after 12:00 -> conflict.
    shop, material, customer = setup_base_shop()
    machine = create_machine(shop["id"], name="CNC-O", changeover_buffer_min=30)

    # Project 1 -> IN_PRODUCTION with a build job 09:00-12:00.
    p1 = create_project(shop["id"], customer["id"], margin_policy="STANDARD")
    add_spec(shop["id"], p1["id"], material["id"], quantity=4, base_unit_price_cents=100000)
    get_success_data(api.create_finish_selection(shop["id"], p1["id"], {"finish_code": "PAINT"}, DESIGNER))
    get_success_data(api.measure_project(shop["id"], p1["id"], DESIGNER))
    p1q = get_success_data(api.quote_project(shop["id"], p1["id"], DESIGNER))
    cust = make_customer_headers(customer["id"])
    get_success_data(api.contract_project(shop["id"], p1["id"], {"expected_project_version": p1q["version"]}, cust))
    p1_dep = next(d for d in api.list_draws(shop["id"], p1["id"], MANAGER).json()["data"] if d["draw_type"] == "DEPOSIT")
    get_success_data(api.issue_draw(shop["id"], p1["id"], p1_dep["id"], MANAGER))
    get_success_data(api.pay_draw(shop["id"], p1["id"], p1_dep["id"], cust))
    get_success_data(api.create_build_job(shop["id"], p1["id"], {"machine_id": machine["id"], "start_utc": "2026-07-10T09:00:00Z", "end_utc": "2026-07-10T12:00:00Z"}, MANAGER))

    # Project 2 -> IN_PRODUCTION; attempt build job 12:20-13:00 on the same machine.
    p2 = create_project(shop["id"], customer["id"], margin_policy="STANDARD")
    add_spec(shop["id"], p2["id"], material["id"], quantity=4, base_unit_price_cents=100000)
    get_success_data(api.create_finish_selection(shop["id"], p2["id"], {"finish_code": "PAINT"}, DESIGNER))
    get_success_data(api.measure_project(shop["id"], p2["id"], DESIGNER))
    p2q = get_success_data(api.quote_project(shop["id"], p2["id"], DESIGNER))
    get_success_data(api.contract_project(shop["id"], p2["id"], {"expected_project_version": p2q["version"]}, cust))
    p2_dep = next(d for d in api.list_draws(shop["id"], p2["id"], MANAGER).json()["data"] if d["draw_type"] == "DEPOSIT")
    get_success_data(api.issue_draw(shop["id"], p2["id"], p2_dep["id"], MANAGER))
    get_success_data(api.pay_draw(shop["id"], p2["id"], p2_dep["id"], cust))

    resp = api.create_build_job(shop["id"], p2["id"], {"machine_id": machine["id"], "start_utc": "2026-07-10T12:20:00Z", "end_utc": "2026-07-10T13:00:00Z"}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_MACHINE_TIME_CONFLICT.value)


def test_installation_aggregate_daily_capacity_overflow(api):
    """PRD §3.9: "The `install_date` counts against the shop's
    `max_installs_per_day` aggregate daily capacity across the whole shop: if the
    number of non-cancelled installations already scheduled for that date is at
    the shop's limit, a new installation for that date is rejected with
    `ERR_INSTALL_CAPACITY_FULL`."

    Design: Difficulty/resource_temporal_overlap/installation_aggregate_daily_capacity_overflow
    """
    # Shop max_installs_per_day=1. Two READY projects scheduling installs on the
    # same date; the 2nd overflows aggregate capacity.
    common = dict(
        shop_overrides={"tax_rate_bps": 0, "deposit_pct_bps": 3000, "max_installs_per_day": 1},
        specs=[{"quantity": 4}], finish_code="PAINT",
    )
    q1 = setup_ready_for_delivery_project(build_start="2026-07-11T09:00:00Z", build_end="2026-07-11T12:00:00Z", **common)
    shop_id = q1["shop"]["id"]
    get_success_data(api.create_installation(
        shop_id, q1["project"]["id"],
        {"install_date": "2026-09-01", "window_start_utc": "2026-09-01T08:00:00Z", "window_end_utc": "2026-09-01T12:00:00Z"},
        MANAGER,
    ))

    # Second READY project in the SAME shop scheduling on 2026-09-01.
    customer2 = create_customer(shop_id)
    p2 = create_project(shop_id, customer2["id"], margin_policy="STANDARD")
    add_spec(shop_id, p2["id"], q1["material"]["id"], quantity=4, base_unit_price_cents=100000)
    get_success_data(api.create_finish_selection(shop_id, p2["id"], {"finish_code": "PAINT"}, DESIGNER))
    get_success_data(api.measure_project(shop_id, p2["id"], DESIGNER))
    p2q = get_success_data(api.quote_project(shop_id, p2["id"], DESIGNER))
    cust2 = make_customer_headers(customer2["id"])
    get_success_data(api.contract_project(shop_id, p2["id"], {"expected_project_version": p2q["version"]}, cust2))
    p2_dep = next(d for d in api.list_draws(shop_id, p2["id"], MANAGER).json()["data"] if d["draw_type"] == "DEPOSIT")
    get_success_data(api.issue_draw(shop_id, p2["id"], p2_dep["id"], MANAGER))
    get_success_data(api.pay_draw(shop_id, p2["id"], p2_dep["id"], cust2))
    bj = get_success_data(api.create_build_job(shop_id, p2["id"], {"machine_id": q1["machine"]["id"], "start_utc": "2026-07-12T09:00:00Z", "end_utc": "2026-07-12T12:00:00Z"}, MANAGER))
    get_success_data(api.start_build_job(shop_id, p2["id"], bj["id"], MANAGER))
    get_success_data(api.complete_build_job(shop_id, p2["id"], bj["id"], MANAGER))
    get_success_data(api.mark_ready(shop_id, p2["id"], MANAGER))

    resp = api.create_installation(
        shop_id, p2["id"],
        {"install_date": "2026-09-01", "window_start_utc": "2026-09-01T13:00:00Z", "window_end_utc": "2026-09-01T17:00:00Z"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INSTALL_CAPACITY_FULL.value)
