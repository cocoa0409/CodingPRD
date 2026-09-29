"""The two installation axes, the scheduling resource tests, the audit bars and disposition."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_equipment,
    assert_cents,
    assert_decimal,
    assert_instant,
    assert_utilization_audit,
    cast_vote,
    close_intake,
    close_voting,
    fund,
    get_success_data,
    live_allocation,
    make_asset,
    make_cycle,
    make_department,
    make_facility,
    make_facility_director_headers,
    make_member,
    make_project,
    make_request,
    open_intake,
    pin_clock,
    refresh_asset,
    refresh_cycle,
    refresh_department,
    refresh_facility,
    refresh_project,
    refresh_request,
    run_allocation,
    run_scoring,
    schedule_audit,
    screen,
    submit,
    take_live,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]
_AUDITOR = TEST_USERS["auditor_headers"]

CT32_JUSTIFICATION = (
    "CT-32 replacement doubles interventional CT capacity for the 2030 plan year."
)


def _committee_pair():
    chair = make_member("CHAIR", 3, full_name="Dana Whitfield")
    finance = make_member("FINANCE", 2, full_name="Roy Adeyemi")
    return chair, finance


def _approve(request_id, chair, finance):
    cast_vote(request_id, chair["id"], "APPROVE")
    cast_vote(request_id, finance["id"], "APPROVE")
    return close_voting(request_id, chair["id"])


def _north_facility():
    return make_facility(
        name="North Regional Hospital", code="NRH", region="NORTH",
        max_concurrent_construction=1,
    )


def _ct_asset(facility_id, department_id, **overrides):
    payload = dict(
        modality="CT", model_name="Aquilon CT-32", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=120000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    payload.update(overrides)
    return make_asset(facility_id, department_id, **payload)


def _funded_2030_request():
    """The 2030 CT-32 request carried all the way to FUNDED at its full estimate."""
    pin_clock(CLOCK)
    facility = _north_facility()
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset = _ct_asset(facility["id"], department["id"])
    cycle = make_cycle(
        plan_year=2030, plan_year_start="2030-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.00, facility_contingency_pct=0.00,
    )
    cycle = open_intake(cycle["id"])
    chair, finance = _committee_pair()
    request = make_request(
        cycle["id"], department["id"], asset["id"],
        clinical_justification=CT32_JUSTIFICATION,
        current_annual_volume=1000, projected_annual_volume=2000,
        estimated_capital_cents=100000000, annual_service_contract_cents=10000000,
        disposable_unit_cents=500,
    )
    submit(request["id"], department["id"])
    screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    cycle = run_allocation(cycle["id"], "PRO_RATA", cycle["version"])
    _approve(request["id"], chair, finance)
    request = fund(request["id"])
    return {"facility": facility, "department": department, "asset": asset,
            "cycle": refresh_cycle(cycle["id"]), "request": request}


def _project_on_both_axes():
    """A 2030 project that needs construction, so both axes start unfinished."""
    ctx = _funded_2030_request()
    ctx["project"] = make_project(
        ctx["request"]["id"], ctx["facility"]["id"],
        downtime_start="2030-03-01T00:00:00Z", downtime_end="2030-03-05T00:00:00Z",
        construction_required=True,
        construction_start="2030-02-01T00:00:00Z", construction_end="2030-02-28T00:00:00Z",
    )
    return ctx


def _project_without_construction():
    """A 2030 project with no construction axis at all."""
    ctx = _funded_2030_request()
    ctx["project"] = make_project(
        ctx["request"]["id"], ctx["facility"]["id"],
        downtime_start="2030-03-01T00:00:00Z", downtime_end="2030-03-05T00:00:00Z",
        construction_required=False,
    )
    return ctx


def _implemented_request_with_scheduled_audit():
    """The 2030 request taken live and handed to internal audit."""
    ctx = _project_without_construction()
    advance_equipment(ctx["project"]["id"], ctx["facility"]["id"], steps=3)
    take_live(ctx["project"]["id"], ctx["facility"]["id"])
    ctx["audit"] = schedule_audit(
        ctx["request"]["id"], ctx["project"]["id"],
        "2026-08-01T00:00:00Z", "2027-07-31T00:00:00Z",
    )
    return ctx


def _two_funded_requests_in_one_department():
    """A 2032 cycle whose two funded requests share one department's downtime slot."""
    pin_clock(CLOCK)
    facility = _north_facility()
    department = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    asset_x = _ct_asset(facility["id"], department["id"])
    asset_y = _ct_asset(facility["id"], department["id"],
                        model_name="Aquilon CT-28", acquisition_cost_cents=100000000)
    cycle = make_cycle(
        plan_year=2032, plan_year_start="2032-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.00, facility_contingency_pct=0.00,
    )
    cycle = open_intake(cycle["id"])
    chair, finance = _committee_pair()
    request_x = make_request(
        cycle["id"], department["id"], asset_x["id"],
        clinical_justification="CT-32 replacement doubles interventional CT capacity.",
        current_annual_volume=1000, projected_annual_volume=2000,
        estimated_capital_cents=100000000, annual_service_contract_cents=10000000,
        disposable_unit_cents=500,
    )
    request_y = make_request(
        cycle["id"], department["id"], asset_y["id"],
        clinical_justification="CT-28 replacement lifts routine imaging volume modestly.",
        current_annual_volume=1000, projected_annual_volume=1200,
        estimated_capital_cents=80000000, annual_service_contract_cents=8000000,
        disposable_unit_cents=400,
    )
    for request in (request_x, request_y):
        submit(request["id"], department["id"])
        screen(request["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    cycle = run_allocation(cycle["id"], "PRO_RATA", cycle["version"])
    _approve(request_x["id"], chair, finance)
    _approve(request_y["id"], chair, finance)
    fund(request_x["id"])
    fund(request_y["id"])
    project_1 = make_project(
        request_x["id"], facility["id"],
        downtime_start="2027-03-01T00:00:00Z", downtime_end="2027-03-05T00:00:00Z",
        construction_required=False,
    )
    return {"facility": facility, "cycle": refresh_cycle(cycle["id"]),
            "request_x": request_x, "request_y": request_y, "project_1": project_1}


def _two_funded_requests_in_two_departments():
    """A 2033 cycle whose two funded requests compete for one construction slot."""
    pin_clock(CLOCK)
    facility = _north_facility()
    department_1 = make_department(
        facility["id"], name="Diagnostic Imaging CT", modality_scope="CT"
    )
    department_2 = make_department(
        facility["id"], name="Interventional Radiology", modality_scope="CATH_LAB"
    )
    asset_p = _ct_asset(facility["id"], department_1["id"])
    asset_q = make_asset(
        facility["id"], department_2["id"],
        modality="CATH_LAB", model_name="Vasculon A-9", install_date="2020-08-02T00:00:00Z",
        expected_life_years=8, acquisition_cost_cents=100000000,
        oem_support_end_date="2029-06-01T00:00:00Z",
    )
    cycle = make_cycle(
        plan_year=2033, plan_year_start="2033-01-01T00:00:00Z",
        total_capital_cents=500000000, contingency_pct=0.00, facility_contingency_pct=0.00,
    )
    cycle = open_intake(cycle["id"])
    chair, finance = _committee_pair()
    request_p = make_request(
        cycle["id"], department_1["id"], asset_p["id"],
        clinical_justification="CT-32 replacement doubles interventional CT capacity.",
        current_annual_volume=1000, projected_annual_volume=2000,
        estimated_capital_cents=100000000, annual_service_contract_cents=10000000,
        disposable_unit_cents=500,
    )
    request_q = make_request(
        cycle["id"], department_2["id"], asset_q["id"],
        clinical_justification="Cath lab replacement restores the interventional suite.",
        current_annual_volume=1000, projected_annual_volume=1500,
        estimated_capital_cents=80000000, annual_service_contract_cents=8000000,
        disposable_unit_cents=400,
    )
    submit(request_p["id"], department_1["id"])
    screen(request_p["id"], "ACCEPT")
    submit(request_q["id"], department_2["id"])
    screen(request_q["id"], "ACCEPT")
    close_intake(cycle["id"])
    cycle = run_scoring(cycle["id"])
    cycle = run_allocation(cycle["id"], "PRO_RATA", cycle["version"])
    _approve(request_p["id"], chair, finance)
    _approve(request_q["id"], chair, finance)
    fund(request_p["id"])
    fund(request_q["id"])
    project_1 = make_project(
        request_p["id"], facility["id"],
        downtime_start="2027-03-01T00:00:00Z", downtime_end="2027-03-05T00:00:00Z",
        construction_required=True,
        construction_start="2027-02-01T00:00:00Z", construction_end="2027-02-28T00:00:00Z",
    )
    return {"facility": facility, "request_p": request_p, "request_q": request_q,
            "project_1": project_1}


def _project_rows(api, **params):
    params.setdefault("limit", 100)
    return get_success_data(api.list_installation_projects(_PLANNER, params=params))


# ─── The two installation axes advance independently ─────────────────


def test_the_equipment_axis_advances_while_construction_stands_still(api):
    """PRD §3.10: "The equipment axis walks `AWAITING_DELIVERY → DELIVERED → INSTALLED →
    COMMISSIONED`, one step per call, and never reads the construction axis."
    PRD §3.10: "An unconverged axis is a project-state fault and yields
    `ERR_PROJECT_INVALID_STATE`, whereas a predecessor that is cancelled or not yet
    commissioned yields `ERR_PREDECESSOR_NOT_COMMISSIONED`."

    Design: Difficulty/non_linear_state_machine/installation_project_parallel_axes_advance_independently
    """
    ctx = _project_on_both_axes()
    director = make_facility_director_headers(ctx["facility"]["id"])

    delivered = validate_success(api.advance_equipment(ctx["project"]["id"], director))
    assert delivered["equipment_status"] == "DELIVERED"
    assert delivered["construction_status"] == "DESIGN"

    installed = validate_success(api.advance_equipment(ctx["project"]["id"], director))
    assert installed["equipment_status"] == "INSTALLED"
    assert installed["construction_status"] == "DESIGN"

    response = api.go_live_project(ctx["project"]["id"], director)
    validate_error(response, ApiErrorId.ERR_PROJECT_INVALID_STATE.value, 409)
    assert refresh_project(ctx["project"]["id"])["go_live_at"] is None


def test_going_live_joins_the_axes_only_once_both_have_converged(api):
    """PRD §3.10: "The construction axis walks `DESIGN → PERMIT → BUILD → COMPLETE`, one
    step per call, and never reads the equipment axis."
    PRD §3.10: "On success `go_live_at` is set to the logical clock instant and the
    project's `version` is incremented, and the request moves `FUNDED → IMPLEMENTED` with
    its own `version` incremented."

    Design: Difficulty/non_linear_state_machine/installation_project_parallel_axes_advance_independently
    """
    ctx = _project_on_both_axes()
    director = make_facility_director_headers(ctx["facility"]["id"])
    advance_equipment(ctx["project"]["id"], ctx["facility"]["id"], steps=2)

    for expected in ("PERMIT", "BUILD", "COMPLETE"):
        step = validate_success(api.advance_construction(ctx["project"]["id"], director))
        assert step["construction_status"] == expected
        assert step["equipment_status"] == "INSTALLED"

    commissioned = validate_success(api.advance_equipment(ctx["project"]["id"], director))
    assert commissioned["equipment_status"] == "COMMISSIONED"
    assert commissioned["construction_status"] == "COMPLETE"

    live = validate_success(api.go_live_project(ctx["project"]["id"], director))
    assert_instant(live["go_live_at"], CLOCK, "go_live_at")
    assert live["record_status"] == "ACTIVE"

    request_after = refresh_request(ctx["request"]["id"])
    assert request_after["status"] == "IMPLEMENTED"
    assert_cents(request_after["funded_amount_cents"], 100000000, "funded_amount_cents")
    assert_decimal(request_after["composite_score"], 59.69, "composite_score")
    assert refresh_asset(ctx["asset"]["id"])["status"] == "REPLACEMENT_PENDING"


# ─── The audit metrics at both bars exactly ──────────────────────────


def test_collecting_rounds_the_variance_before_it_tests_the_ceiling(api):
    """PRD §3.11: "`volume_attainment_pct` is `actual_annual_volume` divided by
    `projected_annual_volume_snapshot`, multiplied by one hundred, rounded half up to two
    decimals."
    PRD §3.11: "`opex_variance_pct` is `actual_annual_opex_cents` less
    `baseline_year1_opex_snapshot`, divided by `baseline_year1_opex_snapshot`, multiplied by
    one hundred, rounded half up to two decimals; a negative variance means the equipment
    came in under its business-case operating cost."
    PRD §3.11: "Both comparisons are made **after** the two-decimal rounding."

    Design: Difficulty/boundary_precision_check/audit_volume_and_opex_bars_at_exact_boundary_on_collect
    """
    ctx = _implemented_request_with_scheduled_audit()

    collected = validate_success(
        api.collect_audit(ctx["audit"]["id"],
                          {"actual_annual_volume": 1600,
                           "actual_annual_opex_cents": 11935542},
                          _AUDITOR)
    )
    assert_utilization_audit(collected)
    assert collected["projected_annual_volume_snapshot"] == 2000
    assert_cents(collected["baseline_year1_opex_snapshot"], 10850000,
                 "baseline_year1_opex_snapshot")
    assert_decimal(collected["volume_attainment_pct"], 80.00, "volume_attainment_pct")
    assert_decimal(collected["opex_variance_pct"], 10.00, "opex_variance_pct")


def test_attainment_and_overrun_exactly_on_their_bars_still_pass(api):
    """PRD §3.11: "The audit moves `SCHEDULED → PASSED` when `volume_attainment_pct` is at
    least 80.00 **and** `opex_variance_pct` is at most 10.00; both boundaries are
    inclusive, so an attainment of exactly 80.00 and an overrun of exactly 10.00 both
    pass."
    PRD §3.11: "A passing verdict changes nothing outside the audit row."
    PRD §3.11: "In either branch the actuals and both percentages are written, the audit's
    `version` is incremented, and the request moves `IMPLEMENTED → AUDITED` with its own
    `version` incremented."

    Design: Difficulty/boundary_precision_check/audit_volume_and_opex_bars_at_exact_boundary_on_collect
    """
    ctx = _implemented_request_with_scheduled_audit()

    collected = validate_success(
        api.collect_audit(ctx["audit"]["id"],
                          {"actual_annual_volume": 1600,
                           "actual_annual_opex_cents": 11935542},
                          _AUDITOR)
    )
    assert collected["status"] == "PASSED"

    assert refresh_request(ctx["request"]["id"])["status"] == "AUDITED"

    department_after = refresh_department(ctx["department"]["id"])
    assert department_after["utilization_penalty_points"] == 0
    assert department_after["underperformance_flag"] is False

    request_after = refresh_request(ctx["request"]["id"])
    assert_decimal(request_after["composite_score"], 59.69, "composite_score")
    assert_cents(request_after["baseline_year1_opex_cents"], 10850000,
                 "baseline_year1_opex_cents")


# ─── Disposition waits on the replacement being commissioned ─────────


def test_decommissioning_before_the_replacement_is_commissioned_is_refused(api):
    """PRD §3.11: "It also requires the replacement to be physically in place: the
    installation project of the funding request whose `record_status` is `ACTIVE` must have
    `equipment_status` `COMMISSIONED`, and an asset with no such project, or one whose
    project is not yet commissioned, is rejected with `ERR_INSTALLATION_NOT_COMMISSIONED`."
    PRD §3.10: "A new project starts with `record_status` `ACTIVE`, `equipment_status`
    `AWAITING_DELIVERY`, `go_live_at` null, and `construction_status` `DESIGN` when
    `construction_required` is true or `NOT_REQUIRED` when it is false."

    Design: Difficulty/cross_entity_state_dependency/asset_decommission_depends_on_project_commissioning
    """
    ctx = _project_without_construction()

    response = api.decommission_asset(ctx["asset"]["id"], {"disposition": "SCRAPPED"},
                                      _PLANNER)
    validate_error(response, ApiErrorId.ERR_INSTALLATION_NOT_COMMISSIONED.value, 409)

    asset_after = refresh_asset(ctx["asset"]["id"])
    assert asset_after["status"] == "REPLACEMENT_PENDING"
    assert asset_after["disposition_status"] == "NONE"
    assert refresh_facility(ctx["facility"]["id"])["active_asset_count"] == 1


def test_the_same_decommission_lands_once_the_project_reads_commissioned(api):
    """PRD §3.11: "On success the asset moves `REPLACEMENT_PENDING → DECOMMISSIONED`, its
    `disposition_status` becomes `TRADED_IN` or `SCRAPPED` per the input and its `version`
    is incremented, and the owning facility's `active_asset_count` falls by one with the
    facility's `version` incremented."
    PRD §3.10: "A project created with `construction_required` false has no construction
    axis at all, so `construction_status` stands at `NOT_REQUIRED` and an attempt to
    advance construction is rejected with `ERR_PROJECT_INVALID_STATE`; the same rejection
    covers advancing construction that already reads `COMPLETE`, advancing equipment that
    already reads `COMMISSIONED`, acting on a project whose `record_status` is `CANCELLED`,
    and acting on a project whose `go_live_at` is already set."

    Design: Difficulty/cross_entity_state_dependency/asset_decommission_depends_on_project_commissioning
    """
    ctx = _project_without_construction()
    director = make_facility_director_headers(ctx["facility"]["id"])
    validate_error(api.decommission_asset(ctx["asset"]["id"], {"disposition": "SCRAPPED"},
                                          _PLANNER),
                   ApiErrorId.ERR_INSTALLATION_NOT_COMMISSIONED.value, 409)

    for expected in ("DELIVERED", "INSTALLED", "COMMISSIONED"):
        step = validate_success(api.advance_equipment(ctx["project"]["id"], director))
        assert step["equipment_status"] == expected
        assert step["construction_status"] == "NOT_REQUIRED"
        assert step["go_live_at"] is None

    scrapped = validate_success(
        api.decommission_asset(ctx["asset"]["id"], {"disposition": "SCRAPPED"}, _PLANNER)
    )
    assert scrapped["status"] == "DECOMMISSIONED"
    assert scrapped["disposition_status"] == "SCRAPPED"

    assert refresh_facility(ctx["facility"]["id"])["active_asset_count"] == 0
    assert refresh_request(ctx["request"]["id"])["status"] == "FUNDED"
    project_after = refresh_project(ctx["project"]["id"])
    assert project_after["record_status"] == "ACTIVE"
    assert project_after["go_live_at"] is None


# ─── The department downtime slot: buffered and half-open ────────────


def test_a_buffered_start_reaching_back_into_the_stored_window_conflicts(api):
    """PRD §3.10: "A conflict exists when some other project with `record_status` `ACTIVE`
    in the same `department_id` — excluding the row being edited — has a `downtime_end`
    strictly later than the incoming start minus twenty-four hours **and** a
    `downtime_start` strictly earlier than the incoming end plus twenty-four hours; the
    rejection is `ERR_DOWNTIME_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/department_downtime_buffered_half_open_boundary
    """
    ctx = _two_funded_requests_in_one_department()
    director = make_facility_director_headers(ctx["facility"]["id"])

    response = api.create_installation_project(
        ctx["request_y"]["id"],
        {"downtime_start": "2027-03-05T23:59:59.999Z",
         "downtime_end": "2027-03-10T00:00:00Z", "construction_required": False},
        director,
    )
    validate_error(response, ApiErrorId.ERR_DOWNTIME_WINDOW_CONFLICT.value, 409)

    untouched = refresh_project(ctx["project_1"]["id"])
    assert_instant(untouched["downtime_start"], "2027-03-01T00:00:00Z", "downtime_start")
    assert_instant(untouched["downtime_end"], "2027-03-05T00:00:00Z", "downtime_end")


def test_a_buffered_start_landing_exactly_on_the_stored_end_is_admitted(api):
    """PRD §3.10: "Because the test is strict on both sides, an incoming buffered start
    landing exactly on another window's `downtime_end` does not conflict."
    PRD §3.9: "Where the draw brings the allocation's `available_cents` exactly to zero,
    that row's `posture` moves to `EXHAUSTED`."

    Design: Difficulty/resource_temporal_overlap/department_downtime_buffered_half_open_boundary
    """
    ctx = _two_funded_requests_in_one_department()
    director = make_facility_director_headers(ctx["facility"]["id"])
    validate_error(
        api.create_installation_project(
            ctx["request_y"]["id"],
            {"downtime_start": "2027-03-05T23:59:59.999Z",
             "downtime_end": "2027-03-10T00:00:00Z", "construction_required": False},
            director),
        ApiErrorId.ERR_DOWNTIME_WINDOW_CONFLICT.value, 409,
    )

    created = validate_success(
        api.create_installation_project(
            ctx["request_y"]["id"],
            {"downtime_start": "2027-03-06T00:00:00Z",
             "downtime_end": "2027-03-10T00:00:00Z", "construction_required": False},
            director),
        expected_status=201,
    )
    assert_instant(created["downtime_start"], "2027-03-06T00:00:00Z", "downtime_start")
    assert_instant(created["downtime_end"], "2027-03-10T00:00:00Z", "downtime_end")
    assert created["construction_status"] == "NOT_REQUIRED"
    assert created["equipment_status"] == "AWAITING_DELIVERY"
    assert created["record_status"] == "ACTIVE"
    assert created["go_live_at"] is None

    rows = _project_rows(api, request_id=ctx["request_y"]["id"])
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]

    allocation = live_allocation(ctx["cycle"]["id"], ctx["facility"]["id"])
    assert_cents(allocation["demand_cents"], 180000000, "demand_cents")
    assert_cents(allocation["allocated_cents"], 180000000, "allocated_cents")
    assert_cents(allocation["committed_cents"], 180000000, "committed_cents")
    assert_cents(allocation["available_cents"], 0, "available_cents")
    assert allocation["posture"] == "EXHAUSTED"

    cycle_after = refresh_cycle(ctx["cycle"]["id"])
    assert cycle_after["status"] == "COMMITTED"
    assert cycle_after["exhausted_allocation_count"] == 1
    assert cycle_after["allocation_count"] == 1


# ─── The facility construction slot: raw, closed and counted ─────────


def test_construction_windows_that_merely_touch_occupy_the_same_slot(api):
    """PRD §3.10: "Counting projects with `record_status` `ACTIVE` and
    `construction_required` true in the same `facility_id` — again excluding the row being
    edited — whose **closed** construction interval intersects the incoming closed
    interval, meaning the other project's `construction_start` is at or before the incoming
    end and the incoming start is at or before the other project's `construction_end`, the
    write is rejected with `ERR_CONSTRUCTION_CAPACITY_EXCEEDED` when that count plus one
    exceeds the facility's `max_concurrent_construction`."
    PRD §3.10: "Unlike the downtime test this interval is closed and unbuffered, so two
    projects that merely touch at a single instant do occupy the same capacity slot."

    Design: Difficulty/resource_temporal_overlap/facility_construction_closed_interval_capacity
    """
    ctx = _two_funded_requests_in_two_departments()
    director = make_facility_director_headers(ctx["facility"]["id"])

    response = api.create_installation_project(
        ctx["request_q"]["id"],
        {"downtime_start": "2027-04-01T00:00:00Z", "downtime_end": "2027-04-05T00:00:00Z",
         "construction_required": True, "construction_start": "2027-02-28T00:00:00Z",
         "construction_end": "2027-03-10T00:00:00Z"},
        director,
    )
    validate_error(response, ApiErrorId.ERR_CONSTRUCTION_CAPACITY_EXCEEDED.value, 409)

    untouched = refresh_project(ctx["project_1"]["id"])
    assert_instant(untouched["construction_start"], "2027-02-01T00:00:00Z",
                   "construction_start")
    assert_instant(untouched["construction_end"], "2027-02-28T00:00:00Z", "construction_end")
    assert untouched["construction_status"] == "DESIGN"


def test_starting_construction_one_instant_later_clears_the_capacity_cap(api):
    """PRD §3.10: "The project's `request_id` comes from the path, and its `facility_id` and
    `department_id` are copied from the request's department at creation — construction
    capacity is evaluated per facility while downtime conflicts are evaluated per
    department."
    PRD §3.10: "A new project starts with `record_status` `ACTIVE`, `equipment_status`
    `AWAITING_DELIVERY`, `go_live_at` null, and `construction_status` `DESIGN` when
    `construction_required` is true or `NOT_REQUIRED` when it is false."

    Design: Difficulty/resource_temporal_overlap/facility_construction_closed_interval_capacity
    """
    ctx = _two_funded_requests_in_two_departments()
    director = make_facility_director_headers(ctx["facility"]["id"])
    validate_error(
        api.create_installation_project(
            ctx["request_q"]["id"],
            {"downtime_start": "2027-04-01T00:00:00Z",
             "downtime_end": "2027-04-05T00:00:00Z", "construction_required": True,
             "construction_start": "2027-02-28T00:00:00Z",
             "construction_end": "2027-03-10T00:00:00Z"},
            director),
        ApiErrorId.ERR_CONSTRUCTION_CAPACITY_EXCEEDED.value, 409,
    )

    created = validate_success(
        api.create_installation_project(
            ctx["request_q"]["id"],
            {"downtime_start": "2027-04-01T00:00:00Z",
             "downtime_end": "2027-04-05T00:00:00Z", "construction_required": True,
             "construction_start": "2027-03-01T00:00:00Z",
             "construction_end": "2027-03-10T00:00:00Z"},
            director),
        expected_status=201,
    )
    assert_instant(created["construction_start"], "2027-03-01T00:00:00Z",
                   "construction_start")
    assert_instant(created["construction_end"], "2027-03-10T00:00:00Z", "construction_end")
    assert created["construction_status"] == "DESIGN"
    assert created["equipment_status"] == "AWAITING_DELIVERY"
    assert created["record_status"] == "ACTIVE"

    rows = _project_rows(api, facility_id=ctx["facility"]["id"])
    assert len(rows) == 2

    facility_after = refresh_facility(ctx["facility"]["id"])
    assert facility_after["max_concurrent_construction"] == 1
    assert facility_after["active_asset_count"] == 2
