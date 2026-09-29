"""Outage windows: the buffer geometry, the activation gates and the posture ladder."""
from test_helpers import (
    ApiErrorId,
    api_client,
    activate_outage,
    begin_testing,
    complete_outage,
    create_procurement_order,
    hold_staging,
    list_outage_windows,
    make_building_representative_headers,
    plan_outage,
    read_car,
    read_group,
    read_outage_window,
    read_posture,
    read_procurement_order,
    read_project,
    send_outage_notice,
    set_clock,
    setup_approved_option,
    setup_installed_equipment,
    setup_planned_outage,
    setup_project_with_cars,
    setup_two_cars_ready_for_outage,
    setup_two_groups_ready_for_outage,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import INITIAL_CLOCK_TIMESTAMP
from test_helpers.fixtures import PM

WINDOW_START = "2026-08-10T08:00:00Z"
WINDOW_END = "2026-08-12T18:00:00Z"


def test_the_service_floor_outranks_staging_pressure_on_the_posture_ladder():
    """The posture is an ordered ladder and the first matching clause wins; no later clause
    can soften an earlier verdict. If any hoistway group of the project has fewer cars in
    service than its declared floor — that is, its `cars_in_service` is strictly less than
    its `min_cars_in_service` — the posture is `FROZEN`. Otherwise, if the project's
    `active_outage_count` has reached or passed its `max_concurrent_outages`, or if
    committed staging footage has passed the pressure line, the posture is `RESTRICTED`.

    Raising the floor above the number of cars currently in service moves the project to
    `FROZEN` immediately, with no outage having been touched.

    Design: Difficulty/combinatorial_formula/downtime_posture_ladder_service_floor_outranks_staging_pressure
    """
    ctx = setup_two_cars_ready_for_outage(
        num_cars=2, min_cars_in_service=1, max_concurrent_outages=2,
        staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    group_id = ctx["group"]["id"]
    car_one, _ = ctx["cars"]

    pressure_order = create_procurement_order(
        ctx["scope_options"][0]["id"],
        item_type="POWER_UNIT",
        lead_time_days=30,
        required_staging_sqft=1100,
    )
    hold_staging(project_id, pressure_order["id"], sqft=1100,
                 hold_start="2026-08-05T00:00:00Z",
                 hold_end="2026-08-30T00:00:00Z")

    window = plan_outage(car_one["id"], start_at=WINDOW_START, end_at=WINDOW_END)
    send_outage_notice(window["id"])
    set_clock("2026-08-10T09:00:00Z")
    activate_outage(window["id"])

    restricted = read_posture(project_id)
    assert restricted["downtime_posture"] == "RESTRICTED"
    assert restricted["active_outage_count"] == 1
    assert restricted["staging_committed_sqft"] == 1100
    assert restricted["groups_below_floor"] == 0

    group = read_group(group_id)
    assert group["car_count"] == 2
    assert group["cars_in_service"] == 1

    validate_success(
        api_client.patch_elevator_group(group_id, {"min_cars_in_service": 2}, PM)
    )

    frozen = read_posture(project_id)
    assert frozen["downtime_posture"] == "FROZEN"
    assert frozen["downtime_posture"] != "RESTRICTED"
    assert frozen["groups_below_floor"] == 1
    assert frozen["active_outage_count"] == 1
    assert frozen["staging_committed_sqft"] == 1100
    assert read_project(project_id)["max_concurrent_outages"] == 2


def test_the_pressure_line_is_crossed_only_strictly_and_yields_to_the_floor():
    """The staging pressure line sits at 85 percent of the yard and is crossed only
    strictly. To avoid any floating-point division, the comparison is stated as an integer
    cross-multiplication: `staging_committed_sqft` multiplied by 100 must be strictly
    greater than `staging_area_sqft` multiplied by 85 for the pressure clause to fire. A
    project sitting at exactly 85 percent of its yard is therefore not `RESTRICTED` on that
    account.

    Otherwise the posture is `OPEN`, which is also the value a newly opened project starts
    with.

    Design: Difficulty/combinatorial_formula/downtime_posture_ladder_service_floor_outranks_staging_pressure
    """
    ctx = setup_two_cars_ready_for_outage(
        num_cars=2, min_cars_in_service=0, max_concurrent_outages=2,
        staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    group_id = ctx["group"]["id"]
    option_id = ctx["scope_options"][0]["id"]
    assert read_project(project_id)["staging_committed_sqft"] == 0

    on_the_line = create_procurement_order(
        option_id, item_type="POWER_UNIT", lead_time_days=30,
        required_staging_sqft=1020,
    )
    hold_staging(project_id, on_the_line["id"], sqft=1020,
                 hold_start="2026-08-05T00:00:00Z",
                 hold_end="2026-08-30T00:00:00Z")
    assert 1020 * 100 == 1200 * 85
    at_the_line = read_posture(project_id)
    assert at_the_line["staging_committed_sqft"] == 1020
    assert at_the_line["downtime_posture"] == "OPEN"
    assert at_the_line["groups_below_floor"] == 0

    one_more = create_procurement_order(
        option_id, item_type="DOOR_OPERATOR", lead_time_days=30,
        required_staging_sqft=1,
    )
    hold_staging(project_id, one_more["id"], sqft=1,
                 hold_start="2026-08-05T00:00:00Z",
                 hold_end="2026-08-30T00:00:00Z")
    assert 1021 * 100 > 1200 * 85
    over_the_line = read_posture(project_id)
    assert over_the_line["staging_committed_sqft"] == 1021
    assert over_the_line["downtime_posture"] == "RESTRICTED"

    window = plan_outage(ctx["cars"][0]["id"], start_at=WINDOW_START, end_at=WINDOW_END)
    send_outage_notice(window["id"])
    set_clock("2026-08-10T09:00:00Z")
    activate_outage(window["id"])
    validate_success(
        api_client.patch_elevator_group(group_id, {"min_cars_in_service": 2}, PM)
    )

    frozen = read_posture(project_id)
    assert frozen["downtime_posture"] == "FROZEN"
    assert frozen["groups_below_floor"] == 1
    assert frozen["staging_committed_sqft"] == 1021
    assert frozen["active_outage_count"] == 1


def test_activation_is_refused_when_the_bank_would_drop_below_its_floor():
    """Then the safety gates: the group's `cars_in_service` counted *after* this
    activation must still be at or above the group's `min_cars_in_service`, and an
    activation that would drop the bank below its service floor is refused with
    `ERR_GROUP_SERVICE_FLOOR`; and unless the building's `occupancy_type` is `VACANT`,
    it must not be the case that the project's posture is `RESTRICTED` while this
    window's `temporary_service_plan` is `STAIRS_ONLY` — a stairs-only outage is
    tolerable in a comfortable project but not in a project already under pressure —
    with that combination refused by `ERR_TEMP_SERVICE_PLAN_INADEQUATE`.

    Design: Difficulty/cross_entity_state_dependency/outage_activation_depends_on_elevator_group_service_floor
    """
    ctx = setup_two_cars_ready_for_outage(
        num_cars=3, min_cars_in_service=2, max_concurrent_outages=3,
        staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    group_id = ctx["group"]["id"]
    car_one, car_two, _ = ctx["cars"]

    first = plan_outage(car_one["id"], start_at=WINDOW_START, end_at=WINDOW_END)
    second = plan_outage(
        car_two["id"],
        start_at="2026-08-20T08:00:00Z",
        end_at="2026-08-22T18:00:00Z",
    )
    send_outage_notice(first["id"])
    send_outage_notice(second["id"])

    set_clock("2026-08-10T09:00:00Z")
    activate_outage(first["id"])
    group = read_group(group_id)
    assert group["cars_in_service"] == 2
    assert group["min_cars_in_service"] == 2

    set_clock("2026-08-20T09:00:00Z")
    response = api_client.activate_outage_window(second["id"], PM)
    validate_error(response, ApiErrorId.ERR_GROUP_SERVICE_FLOOR, expected_status=409)
    error_id = response.json()["data"]["error_id"]
    assert error_id != "ERR_CONCURRENCY_CAP_EXCEEDED"
    assert error_id != "ERR_OUTAGE_BUFFER_CONFLICT"

    stored = read_outage_window(second["id"])
    assert stored["status"] == "PLANNED"
    assert stored["activated_at"] is None
    assert read_group(group_id)["cars_in_service"] == 2

    project = read_project(project_id)
    assert project["active_outage_count"] == 1
    assert project["max_concurrent_outages"] == 3


def test_the_service_floor_gate_reads_the_group_and_not_the_project():
    """An accepted activation moves the window `PLANNED → ACTIVE`, stamps `activated_at`
    from the logical clock, advances the car `PROCURING → OUTAGE_ACTIVE` on the work
    dimension while leaving `compliance_status` alone, refreshes the group's
    `cars_in_service` (which drops by one, since the car is no longer available) and
    the project's `active_outage_count` (which rises by one), recomputes the project's
    `downtime_posture`, and increments the project's `version` by 1.

    Two counters on `ElevatorGroup` are defined the same way: `car_count` is the
    number of cars whose `group_id` is this group, and `cars_in_service` is the number
    of cars in this group whose `work_status` is anything other than `OUTAGE_ACTIVE` —
    which means a car undergoing acceptance testing counts as in service, because
    testing runs on a car that has been returned to the hoistway for acceptance runs.

    Design: Difficulty/cross_entity_state_dependency/outage_activation_depends_on_elevator_group_service_floor
    """
    ctx = setup_two_cars_ready_for_outage(
        num_cars=3, min_cars_in_service=2, max_concurrent_outages=3,
        staging_area_sqft=1200,
    )
    group_id = ctx["group"]["id"]
    car_one = ctx["cars"][0]

    assert read_group(group_id)["cars_in_service"] == 3

    window = plan_outage(car_one["id"], start_at=WINDOW_START, end_at=WINDOW_END)
    send_outage_notice(window["id"])
    set_clock("2026-08-10T09:00:00Z")
    activated = activate_outage(window["id"])

    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] == "2026-08-10T09:00:00.000Z"

    car = read_car(car_one["id"])
    assert car["work_status"] == "OUTAGE_ACTIVE"
    assert car["compliance_status"] == "TRIGGERS_CLEARED"

    group = read_group(group_id)
    assert group["car_count"] == 3
    assert group["cars_in_service"] == 2
    assert read_project(ctx["project"]["id"])["active_outage_count"] == 1


def test_back_to_back_windows_in_one_group_conflict_on_the_inflated_buffer():
    """The **group outage buffer** is a pairwise, buffer-inflated conflict over closed
    intervals. Two outage windows on cars in the same hoistway group conflict when each
    one's start falls strictly before the other's end extended forward by the project's
    `outage_buffer_hours`. Because the buffer inflates both ends, adjacency is *illegal*:
    back-to-back outages in one group are rejected, and one single conflicting sibling is
    fatal — there is no summation and no capacity to spread across.

    Design: Difficulty/resource_temporal_overlap/outage_buffer_pairwise_inflation_makes_adjacency_illegal
    """
    ctx = setup_two_cars_ready_for_outage(
        num_cars=2, min_cars_in_service=0, max_concurrent_outages=2,
        staging_area_sqft=1200, outage_buffer_hours=4,
    )
    car_one, car_two = ctx["cars"]
    first = plan_outage(car_one["id"], start_at=WINDOW_START, end_at=WINDOW_END)

    response = api_client.create_outage_window(
        {
            "car_id": car_two["id"],
            "start_at": WINDOW_END,
            "end_at": "2026-08-14T18:00:00Z",
            "temporary_service_plan": "ADJACENT_CAR",
        },
        PM,
    )
    validate_error(
        response, ApiErrorId.ERR_OUTAGE_BUFFER_CONFLICT, expected_status=409
    )

    _, meta = list_outage_windows(car_id=car_two["id"])
    assert meta["total_count"] == 0
    assert read_car(car_two["id"])["work_status"] == "PROCURING"
    assert read_outage_window(first["id"])["status"] == "PLANNED"
    assert read_project(ctx["project"]["id"])["active_outage_count"] == 0


def test_a_window_starting_exactly_one_buffer_later_is_legal():
    """Finally the group buffer conflict of §2.10 is evaluated against every window in
    status `PLANNED` or `ACTIVE` whose car shares the new window's group, the new window's
    own car included: a conflict exists when the new window's `start_at` falls strictly
    before a sibling's `end_at` extended forward by the project's `outage_buffer_hours`, and
    simultaneously that sibling's `start_at` falls strictly before the new window's `end_at`
    extended forward by the same buffer.

    A planned window is created in status `PLANNED` with `extension_hours` at zero,
    `notice_count` at zero, and `advance_notice_sent_at`, `notice_lead_hours`,
    `activated_at` and `completed_at` all null.

    Design: Difficulty/resource_temporal_overlap/outage_buffer_pairwise_inflation_makes_adjacency_illegal
    """
    ctx = setup_two_cars_ready_for_outage(
        num_cars=2, min_cars_in_service=0, max_concurrent_outages=2,
        staging_area_sqft=1200, outage_buffer_hours=4,
    )
    car_one, car_two = ctx["cars"]
    first = plan_outage(car_one["id"], start_at=WINDOW_START, end_at=WINDOW_END)

    response = api_client.create_outage_window(
        {
            "car_id": car_two["id"],
            "start_at": "2026-08-12T22:00:00Z",
            "end_at": "2026-08-14T22:00:00Z",
            "temporary_service_plan": "ADJACENT_CAR",
        },
        PM,
    )
    second = validate_success(response, expected_status=201)

    assert second["status"] == "PLANNED"
    assert second["notice_count"] == 0
    assert second["advance_notice_sent_at"] is None
    assert second["notice_lead_hours"] is None
    assert second["extension_hours"] == 0
    assert second["activated_at"] is None
    assert second["completed_at"] is None

    assert read_outage_window(first["id"])["status"] == "PLANNED"
    assert read_project(ctx["project"]["id"])["active_outage_count"] == 0


def test_begin_testing_is_refused_when_the_only_order_was_cancelled():
    """The car's approved scope option must have at least one procurement order whose
    status is not `CANCELLED`, and every such live order must be in status `INSTALLED`; a
    car whose equipment is still in crates, and equally an approved option with no
    procurement order at all, is refused with `ERR_PROCUREMENT_NOT_INSTALLED` — an approved
    option with zero live orders is a failure, not a vacuous success.

    Design: Difficulty/boundary_precision_check/begin_testing_rejected_when_no_live_procurement_orders
    """
    ctx = setup_approved_option(staging_area_sqft=1200, base_price_cents=5_000_000)
    project_id = ctx["project"]["id"]
    order = create_procurement_order(
        ctx["scope_option"]["id"],
        item_type="CONTROLLER",
        lead_time_days=30,
        required_staging_sqft=400,
    )
    validate_success(api_client.cancel_procurement_order(order["id"], PM))
    assert read_procurement_order(order["id"])["status"] == "CANCELLED"

    rows, meta = validate_paginated(
        api_client.list_procurement_orders(
            PM, params={"scope_option_id": ctx["scope_option"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "CANCELLED"

    window = plan_outage(ctx["car"]["id"], start_at=WINDOW_START, end_at=WINDOW_END)
    send_outage_notice(window["id"])
    set_clock("2026-08-10T09:00:00Z")
    activate_outage(window["id"])
    # The window has to be COMPLETED before begin-testing, so the only condition
    # still unmet is the procurement one this scenario is about.
    complete_outage(window["id"])

    response = api_client.begin_testing_elevator_car(ctx["car"]["id"], PM)
    validate_error(
        response, ApiErrorId.ERR_PROCUREMENT_NOT_INSTALLED, expected_status=409
    )

    assert read_car(ctx["car"]["id"])["work_status"] == "OUTAGE_ACTIVE"
    assert read_group(ctx["group"]["id"])["cars_in_service"] == 0
    assert read_project(project_id)["active_outage_count"] == 0
    assert read_outage_window(window["id"])["status"] == "COMPLETED"


def test_begin_testing_succeeds_once_every_live_order_is_installed():
    """On success the car advances `OUTAGE_ACTIVE → TESTING`, the group's `cars_in_service`
    rises by one because a car in `TESTING` counts as in service, the project's
    `active_outage_count` and `downtime_posture` are refreshed, and the project's `version`
    increments by 1.

    The car's latest outage window — the one with the greatest `completed_at`, ties broken
    by the earlier `created_at` — must be in status `COMPLETED`.

    Design: Difficulty/boundary_precision_check/begin_testing_rejected_when_no_live_procurement_orders
    """
    ctx = setup_installed_equipment(staging_area_sqft=1200)
    project_id = ctx["project"]["id"]
    window = plan_outage(ctx["car"]["id"], start_at=WINDOW_START, end_at=WINDOW_END)
    send_outage_notice(window["id"])
    set_clock("2026-08-10T09:00:00Z")
    activate_outage(window["id"])

    premature = api_client.begin_testing_elevator_car(ctx["car"]["id"], PM)
    validate_error(premature, ApiErrorId.ERR_OUTAGE_STATE_INVALID, expected_status=409)

    complete_outage(window["id"])
    assert read_procurement_order(ctx["procurement_order"]["id"])["status"] == "INSTALLED"

    tested = begin_testing(ctx["car"]["id"])
    assert tested["work_status"] == "TESTING"
    assert read_group(ctx["group"]["id"])["cars_in_service"] == 1
    assert read_project(project_id)["active_outage_count"] == 0


def test_activating_a_window_whose_notice_never_went_out_is_refused():
    """Then the temporal gates: any declared `predecessor_window_id` must point at a
    window whose status is `COMPLETED`, and a predecessor that has not finished
    refuses the activation with `ERR_PREDECESSOR_NOT_COMPLETE`; the group buffer
    conflict is re-evaluated, because the sibling set may have changed since the
    window was planned, refusing with `ERR_OUTAGE_BUFFER_CONFLICT`;
    `advance_notice_sent_at` must not be null and the window's `notice_lead_hours`
    must be at or above the project's `tenant_notice_lead_hours`, with an unsent or
    late notice refused by `ERR_TENANT_NOTICE_LEAD_UNMET`; and the logical clock must
    still be strictly before the window's `end_at`, since a window whose planned end
    has already arrived or passed can no longer be activated and is refused with
    `ERR_WINDOW_EXPIRED`.

    From the first notice onward the window carries `notice_lead_hours`, the number of
    hours from `advance_notice_sent_at` to the window's `start_at`, carried to two
    decimal places; before the first notice it is null.

    Design: Corner/state_machines/activating_an_outage_without_a_tenant_notice_is_rejected
    """
    ctx = setup_installed_equipment(staging_area_sqft=1200)
    window = plan_outage(ctx["car"]["id"], start_at=WINDOW_START, end_at=WINDOW_END)

    response = api_client.activate_outage_window(window["id"], PM)
    validate_error(
        response, ApiErrorId.ERR_TENANT_NOTICE_LEAD_UNMET, expected_status=409
    )

    stored = read_outage_window(window["id"])
    assert stored["status"] == "PLANNED"
    assert stored["activated_at"] is None
    assert stored["notice_count"] == 0
    assert stored["advance_notice_sent_at"] is None
    assert stored["notice_lead_hours"] is None

    assert read_car(ctx["car"]["id"])["work_status"] == "PROCURING"
    assert read_project(ctx["project"]["id"])["active_outage_count"] == 0
    assert read_group(ctx["group"]["id"])["cars_in_service"] == 1


def test_the_posture_read_reports_all_four_figures_on_a_quiet_project():
    """It is also available as a computed read that re-evaluates the ladder and returns the
    posture together with the three inputs that decided it — `downtime_posture`,
    `active_outage_count`, `staging_committed_sqft`, and `groups_below_floor`, the count of
    this project's groups whose `cars_in_service` has fallen below their
    `min_cars_in_service` — without writing anything.

    Design: Corner/endpoints/posture_read_reports_all_four_derived_figures_on_a_quiet_project
    """
    ctx = setup_project_with_cars(num_cars=2, min_cars_in_service=1)
    project_id = ctx["project"]["id"]

    posture = validate_success(
        api_client.get_project_posture(
            project_id, make_building_representative_headers(project_id)
        )
    )
    assert posture["downtime_posture"] == "OPEN"
    assert posture["active_outage_count"] == 0
    assert posture["staging_committed_sqft"] == 0
    assert posture["groups_below_floor"] == 0

    group = read_group(ctx["group"]["id"])
    assert group["cars_in_service"] == 2
    assert group["min_cars_in_service"] == 1

    project = read_project(project_id)
    assert project["downtime_posture"] == "OPEN"
    assert project["active_outage_count"] == 0
    assert project["staging_committed_sqft"] == 0


def test_the_first_notice_stamps_the_clock_and_later_ones_only_count():
    """Sending the notice for an upcoming outage stamps `advance_notice_sent_at` from the
    logical clock *on the first notice only* and increments `notice_count` by 1. Every
    later notice for the same window increments `notice_count` again but never moves
    `advance_notice_sent_at` — a reminder sent the day before does not reset the clock on a
    notice that went out three weeks ago. From the first notice onward the window carries
    `notice_lead_hours`, the number of hours from `advance_notice_sent_at` to the window's
    `start_at`, carried to two decimal places; before the first notice it is null.

    Design: Corner/endpoints/first_tenant_notice_stamps_the_clock_and_later_notices_only_count
    """
    ctx = setup_approved_option(staging_area_sqft=1200)
    project_id = ctx["project"]["id"]
    window = plan_outage(ctx["car"]["id"], start_at=WINDOW_START, end_at=WINDOW_END)
    assert window["notice_lead_hours"] is None

    first = validate_success(api_client.send_outage_notice(window["id"], PM))
    assert first["advance_notice_sent_at"] == INITIAL_CLOCK_TIMESTAMP
    assert first["notice_count"] == 1
    assert first["notice_lead_hours"] == 224.00

    second = validate_success(
        api_client.send_outage_notice(
            window["id"], make_building_representative_headers(project_id)
        )
    )
    assert second["notice_count"] == 2
    assert second["advance_notice_sent_at"] == INITIAL_CLOCK_TIMESTAMP

    stored = read_outage_window(window["id"])
    assert stored["status"] == "PLANNED"
    assert stored["notice_lead_hours"] == 224.00
    assert stored["notice_lead_hours"] >= read_project(project_id)[
        "tenant_notice_lead_hours"
    ]


def test_a_stairs_only_plan_in_an_occupied_building_is_refused():
    """If the building's `occupancy_type` is `OCCUPIED`, the window may not declare
    `STAIRS_ONLY` as its temporary service plan — asking residents of an occupied tower to
    walk is not a plan — and such a request is refused with
    `ERR_TEMP_SERVICE_PLAN_INADEQUATE`.

    Design: Corner/errors/stairs_only_temporary_service_in_an_occupied_building_is_rejected
    """
    ctx = setup_approved_option(occupancy_type="OCCUPIED", staging_area_sqft=1200)
    assert read_project(ctx["project"]["id"])["occupancy_type"] == "OCCUPIED"

    payload = {
        "car_id": ctx["car"]["id"],
        "start_at": WINDOW_START,
        "end_at": WINDOW_END,
        "temporary_service_plan": "STAIRS_ONLY",
    }
    response = api_client.create_outage_window(payload, PM)
    validate_error(
        response, ApiErrorId.ERR_TEMP_SERVICE_PLAN_INADEQUATE, expected_status=409
    )

    _, meta = list_outage_windows(car_id=ctx["car"]["id"])
    assert meta["total_count"] == 0
    assert read_car(ctx["car"]["id"])["work_status"] == "PROCURING"

    payload["temporary_service_plan"] = "ADJACENT_CAR"
    accepted = validate_success(
        api_client.create_outage_window(payload, PM), expected_status=201
    )
    assert accepted["temporary_service_plan"] == "ADJACENT_CAR"


def test_a_stairs_only_plan_in_a_vacant_building_is_accepted():
    """If the building's `occupancy_type` is `OCCUPIED`, the window may not declare
    `STAIRS_ONLY` as its temporary service plan — asking residents of an occupied tower to
    walk is not a plan — and such a request is refused with
    `ERR_TEMP_SERVICE_PLAN_INADEQUATE`.

    A planned window is created in status `PLANNED` with `extension_hours` at zero,
    `notice_count` at zero, and `advance_notice_sent_at`, `notice_lead_hours`,
    `activated_at` and `completed_at` all null.

    Design: Corner/validations/stairs_only_temporary_service_is_accepted_in_a_vacant_building
    """
    ctx = setup_approved_option(
        occupancy_type="VACANT",
        building_name="Brentwood Annex",
        staging_area_sqft=1200,
    )
    assert read_project(ctx["project"]["id"])["occupancy_type"] == "VACANT"

    response = api_client.create_outage_window(
        {
            "car_id": ctx["car"]["id"],
            "start_at": WINDOW_START,
            "end_at": WINDOW_END,
            "temporary_service_plan": "STAIRS_ONLY",
        },
        PM,
    )
    window = validate_success(response, expected_status=201)

    assert window["temporary_service_plan"] == "STAIRS_ONLY"
    assert window["status"] == "PLANNED"
    assert window["extension_hours"] == 0
    assert window["notice_count"] == 0
    assert window["advance_notice_sent_at"] is None
    assert window["notice_lead_hours"] is None
    assert read_car(ctx["car"]["id"])["work_status"] == "PROCURING"


def test_activating_a_window_after_its_planned_end_is_refused():
    """Then the temporal gates: any declared `predecessor_window_id` must point at a
    window whose status is `COMPLETED`, and a predecessor that has not finished
    refuses the activation with `ERR_PREDECESSOR_NOT_COMPLETE`; the group buffer
    conflict is re-evaluated, because the sibling set may have changed since the
    window was planned, refusing with `ERR_OUTAGE_BUFFER_CONFLICT`;
    `advance_notice_sent_at` must not be null and the window's `notice_lead_hours`
    must be at or above the project's `tenant_notice_lead_hours`, with an unsent or
    late notice refused by `ERR_TENANT_NOTICE_LEAD_UNMET`; and the logical clock must
    still be strictly before the window's `end_at`, since a window whose planned end
    has already arrived or passed can no longer be activated and is refused with
    `ERR_WINDOW_EXPIRED`.

    Design: Corner/errors/activating_an_outage_window_after_its_end_at_is_rejected
    """
    ctx = setup_planned_outage(
        start_at=WINDOW_START, end_at=WINDOW_END, with_notice=True,
        staging_area_sqft=1200,
    )
    window_id = ctx["outage_window"]["id"]
    assert ctx["outage_window"]["advance_notice_sent_at"] == INITIAL_CLOCK_TIMESTAMP

    set_clock("2026-08-13T00:00:00Z")
    response = api_client.activate_outage_window(window_id, PM)
    validate_error(response, ApiErrorId.ERR_WINDOW_EXPIRED, expected_status=409)

    stored = read_outage_window(window_id)
    assert stored["status"] == "PLANNED"
    assert stored["activated_at"] is None
    assert stored["advance_notice_sent_at"] == INITIAL_CLOCK_TIMESTAMP

    assert read_car(ctx["car"]["id"])["work_status"] == "PROCURING"
    project = read_project(ctx["project"]["id"])
    assert project["active_outage_count"] == 0
    assert project["downtime_posture"] == "OPEN"


def test_completing_a_window_that_never_activated_is_refused():
    """The window must be in status `ACTIVE`, or the request is refused with
    `ERR_OUTAGE_STATE_INVALID`.

    The car's `work_status` must be `OUTAGE_ACTIVE`, or the request is refused with
    `ERR_CAR_STATE_INVALID`.

    Design: Corner/errors/completing_an_outage_window_that_never_activated_is_rejected
    """
    ctx = setup_installed_equipment(staging_area_sqft=1200)
    window = plan_outage(ctx["car"]["id"], start_at=WINDOW_START, end_at=WINDOW_END)

    response = api_client.complete_outage_window(window["id"], PM)
    validate_error(response, ApiErrorId.ERR_OUTAGE_STATE_INVALID, expected_status=409)

    stored = read_outage_window(window["id"])
    assert stored["status"] == "PLANNED"
    assert stored["activated_at"] is None
    assert stored["completed_at"] is None
    assert read_car(ctx["car"]["id"])["work_status"] == "PROCURING"

    follow_up = api_client.begin_testing_elevator_car(ctx["car"]["id"], PM)
    validate_error(follow_up, ApiErrorId.ERR_CAR_STATE_INVALID, expected_status=409)
    assert read_car(ctx["car"]["id"])["work_status"] == "PROCURING"


def test_a_predecessor_that_has_not_finished_is_refused():
    """If a `predecessor_window_id` is declared, the predecessor must belong to a car of
    the same hoistway group as the new window's car, and a predecessor from another
    group is refused with `ERR_CAR_GROUP_MISMATCH`; the new window's `start_at` must
    also fall at or after the predecessor's `end_at`, and a window that starts before
    its predecessor finishes is refused with `ERR_PREDECESSOR_NOT_COMPLETE`.

    Optionally the window declares a `predecessor_window_id`, the self-referential
    sequencing link that chains one car's outage behind another's; it is left null for
    the first car in a sequence.

    Design: Corner/errors/an_outage_predecessor_that_is_not_complete_is_rejected
    """
    ctx = setup_two_cars_ready_for_outage(
        num_cars=2, min_cars_in_service=0, max_concurrent_outages=2,
        staging_area_sqft=1200, outage_buffer_hours=4,
    )
    car_one, car_two = ctx["cars"]
    first = plan_outage(car_one["id"], start_at=WINDOW_START, end_at=WINDOW_END)

    # start_at falls before the predecessor's end_at (2026-08-12T18:00Z) while the
    # window itself clears the group buffer, so the predecessor rule is the only
    # rule this request can trip.
    response = api_client.create_outage_window(
        {
            "car_id": car_two["id"],
            "start_at": "2026-08-08T08:00:00Z",
            "end_at": "2026-08-09T08:00:00Z",
            "temporary_service_plan": "ADJACENT_CAR",
            "predecessor_window_id": first["id"],
        },
        PM,
    )
    validate_error(
        response, ApiErrorId.ERR_PREDECESSOR_NOT_COMPLETE, expected_status=409
    )

    _, meta = list_outage_windows(car_id=car_two["id"])
    assert meta["total_count"] == 0
    assert read_outage_window(first["id"])["status"] == "PLANNED"


def test_a_predecessor_from_another_hoistway_group_is_refused():
    """If a `predecessor_window_id` is declared, the predecessor must belong to a car of
    the same hoistway group as the new window's car, and a predecessor from another
    group is refused with `ERR_CAR_GROUP_MISMATCH`; the new window's `start_at` must
    also fall at or after the predecessor's `end_at`, and a window that starts before
    its predecessor finishes is refused with `ERR_PREDECESSOR_NOT_COMPLETE`.

    The scope of the check is the `ElevatorGroup`, not the project, so windows on cars
    of a different group never conflict even when they overlap perfectly in time.

    Design: Corner/errors/an_outage_predecessor_from_another_elevator_group_is_rejected
    """
    ctx = setup_two_groups_ready_for_outage(
        cars_per_group=(1, 1), min_cars_in_service=(0, 0),
        max_concurrent_outages=2, staging_area_sqft=1200,
    )
    group_a, group_b = ctx["groups"]
    car_a, car_b = ctx["cars"]
    first = plan_outage(car_a["id"], start_at=WINDOW_START, end_at=WINDOW_END)

    payload = {
        "car_id": car_b["id"],
        "start_at": "2026-09-01T08:00:00Z",
        "end_at": "2026-09-03T18:00:00Z",
        "temporary_service_plan": "ADJACENT_CAR",
        "predecessor_window_id": first["id"],
    }
    response = api_client.create_outage_window(payload, PM)
    validate_error(response, ApiErrorId.ERR_CAR_GROUP_MISMATCH, expected_status=409)
    assert response.json()["data"]["error_id"] != "ERR_PREDECESSOR_NOT_COMPLETE"

    _, meta = list_outage_windows(car_id=car_b["id"])
    assert meta["total_count"] == 0
    assert read_car(car_a["id"])["group_id"] == group_a["id"]
    assert read_car(car_b["id"])["group_id"] == group_b["id"]

    payload.pop("predecessor_window_id")
    accepted = validate_success(
        api_client.create_outage_window(payload, PM), expected_status=201
    )
    assert accepted["status"] == "PLANNED"


def test_a_second_activation_at_the_concurrency_cap_is_refused():
    """Then the countable gates: the project's `active_outage_count` must be strictly
    below its `max_concurrent_outages`, and an activation at the cap is refused with
    `ERR_CONCURRENCY_CAP_EXCEEDED`; and the project's `downtime_posture` must not be
    `FROZEN`, or the activation is refused with `ERR_PROJECT_FROZEN`.

    Otherwise, if the project's `active_outage_count` has reached or passed its
    `max_concurrent_outages`, or if committed staging footage has passed the pressure
    line, the posture is `RESTRICTED`.

    Design: Corner/errors/activating_a_second_outage_at_the_concurrency_cap_is_rejected
    """
    ctx = setup_two_groups_ready_for_outage(
        cars_per_group=(1, 1), min_cars_in_service=(0, 0),
        max_concurrent_outages=1, staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    car_a, car_b = ctx["cars"]

    first = plan_outage(
        car_a["id"], start_at=WINDOW_START, end_at="2026-08-15T18:00:00Z"
    )
    second = plan_outage(
        car_b["id"],
        start_at="2026-08-10T09:00:00Z",
        end_at="2026-08-15T18:00:00Z",
    )
    send_outage_notice(first["id"])
    send_outage_notice(second["id"])
    set_clock("2026-08-10T10:00:00Z")

    activated = activate_outage(first["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] == "2026-08-10T10:00:00.000Z"

    project = read_project(project_id)
    assert project["active_outage_count"] == 1
    assert project["downtime_posture"] == "RESTRICTED"

    response = api_client.activate_outage_window(second["id"], PM)
    validate_error(
        response, ApiErrorId.ERR_CONCURRENCY_CAP_EXCEEDED, expected_status=409
    )
    assert response.json()["data"]["error_id"] != "ERR_OUTAGE_BUFFER_CONFLICT"

    stored = read_outage_window(second["id"])
    assert stored["status"] == "PLANNED"
    assert stored["activated_at"] is None
    assert read_car(car_b["id"])["work_status"] == "PROCURING"
    assert read_car(car_a["id"])["work_status"] == "OUTAGE_ACTIVE"
    assert read_project(project_id)["active_outage_count"] == 1


def test_cars_in_service_reconciles_across_activate_complete_and_begin_testing():
    """Completing an outage closes the window but does *not* return the car to service. On
    success it moves `ACTIVE → COMPLETED`, `completed_at` is stamped from the logical clock,
    and the project's `active_outage_count` and `downtime_posture` are refreshed. The car's
    `work_status` stays exactly at `OUTAGE_ACTIVE`: physically the hoistway is closed until
    the equipment has been proven, and the car leaves `OUTAGE_ACTIVE` only when it is
    returned to acceptance testing.

    On success the car advances `OUTAGE_ACTIVE → TESTING`, the group's `cars_in_service`
    rises by one because a car in `TESTING` counts as in service, the project's
    `active_outage_count` and `downtime_posture` are refreshed, and the project's `version`
    increments by 1.

    Design: Corner/cross_cutting_complexity_layers/cars_in_service_reconciles_across_activate_complete_and_begin_testing
    """
    ctx = setup_installed_equipment(staging_area_sqft=1200)
    project_id = ctx["project"]["id"]
    group_id = ctx["group"]["id"]
    window = plan_outage(ctx["car"]["id"], start_at=WINDOW_START, end_at=WINDOW_END)
    send_outage_notice(window["id"])
    set_clock("2026-08-10T09:00:00Z")

    group = read_group(group_id)
    assert group["car_count"] == 1
    assert group["cars_in_service"] == 1
    before = read_project(project_id)
    assert before["active_outage_count"] == 0

    activate_outage(window["id"])
    assert read_group(group_id)["cars_in_service"] == 0
    after_activate = read_project(project_id)
    assert after_activate["active_outage_count"] == 1
    assert after_activate["downtime_posture"] == "OPEN"
    assert read_car(ctx["car"]["id"])["work_status"] == "OUTAGE_ACTIVE"

    complete_outage(window["id"])
    after_complete = read_project(project_id)
    assert after_complete["active_outage_count"] == 0
    assert after_complete["downtime_posture"] == "OPEN"
    assert read_group(group_id)["cars_in_service"] == 0
    assert read_car(ctx["car"]["id"])["work_status"] == "OUTAGE_ACTIVE"

    begin_testing(ctx["car"]["id"])
    assert read_car(ctx["car"]["id"])["work_status"] == "TESTING"
    assert read_group(group_id)["cars_in_service"] == 1
    final = read_project(project_id)
    assert final["downtime_posture"] == "OPEN"
    assert final["version"] > after_complete["version"] > after_activate["version"]
