"""Long-lead procurement and the pointwise staging yard, plus the rescind cascade."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_procurement_order,
    hold_staging,
    install_order,
    issue_procurement_order,
    list_staging_reservations,
    project_version,
    read_car,
    read_posture,
    read_procurement_order,
    read_project,
    read_scope_option,
    read_staging_reservation,
    receive_order,
    release_staging,
    rescind_scope_option,
    setup_approved_option,
    setup_orders_for_staging,
    setup_project_with_cars,
    setup_scoped_car,
    submit_scope_option,
    submit_survey,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import INITIAL_CLOCK_TIMESTAMP
from test_helpers.fixtures import PM, SM, countersign_survey, create_scope_option

HOLD_START = "2026-08-05T00:00:00Z"
HOLD_END = "2026-08-20T00:00:00Z"


def test_a_hold_that_fills_the_yard_to_the_last_square_foot_is_accepted():
    """The hold is refused with `ERR_STAGING_CAPACITY_EXCEEDED` only when that figure
    *strictly exceeds* the yard: a hold that fills the yard to exactly `staging_area_sqft`
    succeeds, and one additional square foot fails.

    Design: Difficulty/boundary_precision_check/staging_hold_exactly_at_yard_capacity_is_allowed
    """
    ctx = setup_orders_for_staging(
        [
            {"item_type": "CONTROLLER", "required_staging_sqft": 500},
            {"item_type": "MACHINE", "required_staging_sqft": 700},
        ],
        staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    order_a, order_b = ctx["procurement_orders"]

    hold_staging(project_id, order_a["id"], sqft=500, hold_start=HOLD_START,
                 hold_end="2026-08-25T00:00:00Z")
    assert read_project(project_id)["staging_committed_sqft"] == 500

    at_capacity = hold_staging(
        project_id,
        order_b["id"],
        sqft=700,
        hold_start="2026-08-10T00:00:00Z",
        hold_end="2026-08-20T00:00:00Z",
    )
    assert at_capacity["status"] == "HELD"
    assert at_capacity["sqft"] == 700
    assert at_capacity["released_at"] is None

    project = read_project(project_id)
    assert project["staging_committed_sqft"] == 1200
    assert project["staging_area_sqft"] == 1200
    assert project["downtime_posture"] == "RESTRICTED"
    assert read_posture(project_id)["downtime_posture"] == "RESTRICTED"


def test_one_square_foot_past_the_yard_is_refused():
    """The hold is refused with `ERR_STAGING_CAPACITY_EXCEEDED` only when that figure
    *strictly exceeds* the yard: a hold that fills the yard to exactly `staging_area_sqft`
    succeeds, and one additional square foot fails.

    For each instant within the new hold's own span, the footage of every candidate
    overlapping the new hold at that instant is summed; the peak of those sums across the
    new hold's span, plus the new hold's own `sqft`, is compared against the project's
    `staging_area_sqft`.

    Design: Difficulty/boundary_precision_check/staging_hold_exactly_at_yard_capacity_is_allowed
    """
    ctx = setup_orders_for_staging(
        [
            {"item_type": "CONTROLLER", "required_staging_sqft": 500},
            {"item_type": "MACHINE", "required_staging_sqft": 700},
            {"item_type": "DOOR_OPERATOR", "required_staging_sqft": 1},
        ],
        staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    order_a, order_b, order_c = ctx["procurement_orders"]

    hold_staging(project_id, order_a["id"], sqft=500, hold_start=HOLD_START,
                 hold_end="2026-08-25T00:00:00Z")
    hold_staging(project_id, order_b["id"], sqft=700,
                 hold_start="2026-08-10T00:00:00Z", hold_end="2026-08-20T00:00:00Z")
    assert read_project(project_id)["staging_committed_sqft"] == 1200

    response = api_client.create_staging_reservation(
        {
            "procurement_order_id": order_c["id"],
            "sqft": 1,
            "hold_start": "2026-08-12T00:00:00Z",
            "hold_end": "2026-08-15T00:00:00Z",
            "expected_project_version": project_version(project_id),
        },
        SM,
    )
    validate_error(
        response, ApiErrorId.ERR_STAGING_CAPACITY_EXCEEDED, expected_status=409
    )

    assert read_project(project_id)["staging_committed_sqft"] == 1200
    rows, meta = list_staging_reservations(order_c["id"])
    assert meta["total_count"] == 0
    assert rows == []


def test_holds_that_meet_at_one_instant_do_not_overlap_in_the_yard():
    """Each staging reservation occupies the yard from `hold_start` inclusive to `hold_end`
    exclusive; the interval is written closed at the start and open at the end. Two holds
    overlap when the first starts strictly before the second ends and the second starts
    strictly before the first ends, which means a hold that begins at exactly the instant
    another hold ends does not overlap it at all. Adjacency is legal, touching holds may
    reuse the same square footage, and the capacity test is a sum over all simultaneously
    held footage rather than a pairwise veto.

    Design: Difficulty/resource_temporal_overlap/staging_yard_pointwise_additive_capacity_with_legal_adjacency
    """
    ctx = setup_orders_for_staging(
        [
            {"item_type": "CONTROLLER", "required_staging_sqft": 600},
            {"item_type": "MACHINE", "required_staging_sqft": 600},
        ],
        staging_area_sqft=1000,
    )
    project_id = ctx["project"]["id"]
    order_a, order_b = ctx["procurement_orders"]

    hold_staging(project_id, order_a["id"], sqft=600,
                 hold_start="2026-08-05T00:00:00Z", hold_end="2026-08-10T00:00:00Z")

    adjacent = hold_staging(
        project_id,
        order_b["id"],
        sqft=600,
        hold_start="2026-08-10T00:00:00Z",
        hold_end="2026-08-15T00:00:00Z",
    )
    assert adjacent["status"] == "HELD"
    assert adjacent["sqft"] == 600

    project = read_project(project_id)
    assert project["staging_committed_sqft"] == 1200
    assert project["staging_area_sqft"] == 1000
    # Both holds were accepted because they merely touch, but the interval-independent
    # staging ledger now sits past the pressure line (1200 * 100 > 1000 * 85).
    assert project["downtime_posture"] == "RESTRICTED"
    posture = read_posture(project_id)
    assert posture["active_outage_count"] == 0
    assert posture["groups_below_floor"] == 0


def test_the_capacity_test_uses_the_pointwise_peak_and_not_the_naive_sum():
    """For each instant within the new hold's own span, the footage of every candidate
    overlapping the new hold at that instant is summed; the peak of those sums across the
    new hold's span, plus the new hold's own `sqft`, is compared against the project's
    `staging_area_sqft`.

    Because the intervals are half-open, a new hold beginning at exactly the instant an
    existing hold ends sees zero overlap and has the whole yard available to it, even if
    the two holds together far exceed the yard's size; and a hold nested entirely inside a
    longer existing hold sees the longer hold's footage across its whole span, so nesting
    is never cheaper than partial overlap.

    Design: Difficulty/resource_temporal_overlap/staging_yard_pointwise_additive_capacity_with_legal_adjacency
    """
    ctx = setup_orders_for_staging(
        [
            {"item_type": "CONTROLLER", "required_staging_sqft": 600},
            {"item_type": "MACHINE", "required_staging_sqft": 600},
            {"item_type": "DOOR_OPERATOR", "required_staging_sqft": 600},
        ],
        staging_area_sqft=1000,
    )
    project_id = ctx["project"]["id"]
    order_a, order_b, order_c = ctx["procurement_orders"]

    hold_staging(project_id, order_a["id"], sqft=600,
                 hold_start="2026-08-05T00:00:00Z", hold_end="2026-08-10T00:00:00Z")
    hold_staging(project_id, order_b["id"], sqft=600,
                 hold_start="2026-08-10T00:00:00Z", hold_end="2026-08-15T00:00:00Z")

    response = api_client.create_staging_reservation(
        {
            "procurement_order_id": order_c["id"],
            "sqft": 600,
            "hold_start": "2026-08-09T00:00:00Z",
            "hold_end": "2026-08-12T00:00:00Z",
            "expected_project_version": project_version(project_id),
        },
        SM,
    )
    validate_error(
        response, ApiErrorId.ERR_STAGING_CAPACITY_EXCEEDED, expected_status=409
    )

    _, meta = list_staging_reservations(order_c["id"])
    assert meta["total_count"] == 0
    assert read_project(project_id)["staging_committed_sqft"] == 1200

    order = read_procurement_order(order_c["id"])
    assert order["status"] == "ORDERED"
    assert order["staging_reservation_id"] is None


def test_release_and_install_both_return_the_yard_ledger_to_zero():
    """Release is the exact compensating action for the original hold: the reservation
    moves `HELD → RELEASED`, `released_at` is stamped from the logical clock, precisely the
    `sqft` that the hold added is subtracted from the project's `staging_committed_sqft` so
    the ledger returns to its pre-hold value, the `downtime_posture` is recomputed, and the
    project's `version` increments by 1.

    On success the order moves `STAGED → INSTALLED`, the linked reservation moves
    `HELD → RELEASED` with `released_at` stamped from the logical clock, the released
    `sqft` is subtracted from the project's `staging_committed_sqft`, the project's
    `downtime_posture` is recomputed against the freed capacity, and the project's
    `version` increments by 1.

    Design: Difficulty/compensating_invariant/staging_committed_sqft_returns_to_zero_across_hold_lifecycle
    """
    ctx = setup_orders_for_staging(
        [
            {"item_type": "CONTROLLER", "required_staging_sqft": 500},
            {"item_type": "MACHINE", "required_staging_sqft": 300},
        ],
        staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    order_a, order_b = ctx["procurement_orders"]

    hold_a = hold_staging(project_id, order_a["id"], sqft=500,
                          hold_start=HOLD_START, hold_end=HOLD_END)
    hold_b = hold_staging(project_id, order_b["id"], sqft=300,
                          hold_start="2026-08-06T00:00:00Z",
                          hold_end="2026-08-21T00:00:00Z")
    receive_order(order_b["id"], hold_b["id"])

    assert read_project(project_id)["staging_committed_sqft"] == 800
    assert read_project(project_id)["downtime_posture"] == "OPEN"

    release_staging(hold_a["id"])

    released = read_staging_reservation(hold_a["id"])
    assert released["status"] == "RELEASED"
    assert released["released_at"] == INITIAL_CLOCK_TIMESTAMP
    assert released["sqft"] == 500
    assert read_project(project_id)["staging_committed_sqft"] == 300
    assert read_procurement_order(order_a["id"])["status"] == "ORDERED"

    install_order(order_b["id"])

    cascaded = read_staging_reservation(hold_b["id"])
    assert cascaded["status"] == "RELEASED"
    assert cascaded["released_at"] == INITIAL_CLOCK_TIMESTAMP
    assert cascaded["sqft"] == 300

    installed = read_procurement_order(order_b["id"])
    assert installed["status"] == "INSTALLED"
    assert installed["staging_reservation_id"] == hold_b["id"]

    project = read_project(project_id)
    assert project["staging_committed_sqft"] == 0
    assert project["downtime_posture"] == "OPEN"


def test_no_held_reservation_survives_either_unwind_path():
    """`staging_committed_sqft` is the sum of `sqft` over every staging reservation in
    status `HELD` whose order chain — reservation to procurement order to scope option to
    car to project — resolves to this project; note that this ledger is deliberately
    interval-independent, counting every held reservation regardless of whether its
    interval is in the past, present or future.

    Because these are conserved quantities, every compensating action must return them to
    their pre-action value. Releasing a staging hold subtracts exactly the footage the hold
    added. A ledger that drifts is a defect even when no individual operation looks wrong
    in isolation.

    Design: Difficulty/compensating_invariant/staging_committed_sqft_returns_to_zero_across_hold_lifecycle
    """
    ctx = setup_orders_for_staging(
        [
            {"item_type": "CONTROLLER", "required_staging_sqft": 500},
            {"item_type": "MACHINE", "required_staging_sqft": 300},
        ],
        staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    order_a, order_b = ctx["procurement_orders"]

    hold_a = hold_staging(project_id, order_a["id"], sqft=500,
                          hold_start=HOLD_START, hold_end=HOLD_END)
    hold_b = hold_staging(project_id, order_b["id"], sqft=300,
                          hold_start="2026-08-06T00:00:00Z",
                          hold_end="2026-08-21T00:00:00Z")
    receive_order(order_b["id"], hold_b["id"])
    release_staging(hold_a["id"])
    install_order(order_b["id"])

    for order in (order_a, order_b):
        _, meta = list_staging_reservations(order["id"], status="HELD")
        assert meta["total_count"] == 0

    _, released_a = list_staging_reservations(order_a["id"], status="RELEASED")
    assert released_a["total_count"] == 1
    _, released_b = list_staging_reservations(order_b["id"], status="RELEASED")
    assert released_b["total_count"] == 1

    assert read_project(project_id)["staging_committed_sqft"] == 0
    assert read_staging_reservation(hold_a["id"])["sqft"] == 500
    assert read_staging_reservation(hold_b["id"])["sqft"] == 300


def _cascade_fixture():
    """An approved option with a held order, an installed order and a planned window."""
    ctx = setup_approved_option(staging_area_sqft=1200, base_price_cents=5_000_000)
    project_id = ctx["project"]["id"]
    option_id = ctx["scope_option"]["id"]

    order_a = create_procurement_order(
        option_id, item_type="CONTROLLER", lead_time_days=30, required_staging_sqft=1100
    )
    issue_procurement_order(order_a["id"])
    hold_a = hold_staging(project_id, order_a["id"], sqft=1100,
                          hold_start=HOLD_START, hold_end="2026-08-30T00:00:00Z")
    receive_order(order_a["id"], hold_a["id"])

    order_b = create_procurement_order(
        option_id, item_type="MACHINE", lead_time_days=30, required_staging_sqft=100
    )
    issue_procurement_order(order_b["id"])
    hold_b = hold_staging(project_id, order_b["id"], sqft=100,
                          hold_start=HOLD_START, hold_end="2026-08-30T00:00:00Z")
    receive_order(order_b["id"], hold_b["id"])
    install_order(order_b["id"])

    window = validate_success(
        api_client.create_outage_window(
            {
                "car_id": ctx["car"]["id"],
                "start_at": "2026-08-10T08:00:00Z",
                "end_at": "2026-08-12T18:00:00Z",
                "temporary_service_plan": "ADJACENT_CAR",
            },
            PM,
        ),
        expected_status=201,
    )
    ctx.update(
        {
            "order_a": order_a,
            "order_b": order_b,
            "hold_a": hold_a,
            "hold_b": hold_b,
            "outage_window": window,
        }
    )
    return ctx


def test_rescission_cancels_the_live_orders_and_spares_the_installed_one():
    """The second link, caused by the first, cancels every procurement order of that option
    sitting in `DRAFT`, `ORDERED` or `STAGED`; orders already `INSTALLED` are left
    untouched, because the equipment is in the hoistway.

    The first link moves the option `APPROVED → SUPERSEDED` and removes its
    `total_price_cents` from the project's `approved_scope_value_cents`.

    Design: Difficulty/transitive_cascade/scope_rescind_unwinds_procurement_staging_posture_and_outage
    """
    ctx = _cascade_fixture()
    project_id = ctx["project"]["id"]

    before = read_project(project_id)
    assert before["approved_scope_value_cents"] == 5_000_000
    assert before["staging_committed_sqft"] == 1100
    assert before["downtime_posture"] == "RESTRICTED"

    rescind_scope_option(ctx["scope_option"]["id"])

    assert read_scope_option(ctx["scope_option"]["id"])["status"] == "SUPERSEDED"
    assert read_project(project_id)["approved_scope_value_cents"] == 0
    assert read_procurement_order(ctx["order_a"]["id"])["status"] == "CANCELLED"
    assert read_procurement_order(ctx["order_b"]["id"])["status"] == "INSTALLED"


def test_rescission_frees_the_yard_the_posture_the_car_and_the_window():
    """The third link, caused by the second, releases every staging reservation of a
    cancelled order that was still in status `HELD`, and each released reservation's `sqft`
    leaves the project's `staging_committed_sqft`. The fourth link, caused by the third,
    recomputes the project's `downtime_posture` from the reduced staging commitment. The
    fifth link, caused by the first, moves the car `PROCURING → SCOPED` on the work
    dimension, clears its `approved_scope_option_id` back to null, and — because no option
    in `DRAFT`, `SUBMITTED` or `APPROVED` remains for that car after the rescission —
    resets `compliance_status` all the way back to `NOT_EVALUATED`, from
    `TRIGGERS_CLEARED` or from `TRIGGERS_OPEN` alike. The sixth link, caused by the fifth,
    cancels every outage window of that car still in status `PLANNED`.

    Design: Difficulty/transitive_cascade/scope_rescind_unwinds_procurement_staging_posture_and_outage
    """
    ctx = _cascade_fixture()
    project_id = ctx["project"]["id"]

    rescind_scope_option(ctx["scope_option"]["id"])

    released = read_staging_reservation(ctx["hold_a"]["id"])
    assert released["status"] == "RELEASED"
    assert released["sqft"] == 1100
    assert released["released_at"] == INITIAL_CLOCK_TIMESTAMP

    project = read_project(project_id)
    assert project["staging_committed_sqft"] == 0
    assert project["downtime_posture"] == "OPEN"
    assert project["status"] == "EXECUTION"

    car = read_car(ctx["car"]["id"])
    assert car["work_status"] == "SCOPED"
    assert car["compliance_status"] == "NOT_EVALUATED"
    assert car["approved_scope_option_id"] is None

    window = validate_success(
        api_client.get_outage_window(ctx["outage_window"]["id"], PM)
    )
    assert window["status"] == "CANCELLED"


def test_releasing_an_already_released_hold_is_refused():
    """The reservation must be in status `HELD`; releasing a reservation that is already
    `RELEASED` is refused with `ERR_RESERVATION_STATE_INVALID`.

    Design: Corner/errors/releasing_an_already_released_staging_hold_is_rejected
    """
    ctx = setup_orders_for_staging(
        [{"item_type": "CONTROLLER", "required_staging_sqft": 400}],
        staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    order = ctx["procurement_orders"][0]
    hold = hold_staging(project_id, order["id"], sqft=400,
                        hold_start=HOLD_START, hold_end=HOLD_END)

    first = validate_success(
        api_client.release_staging_reservation(hold["id"], SM)
    )
    assert first["status"] == "RELEASED"
    assert first["released_at"] == INITIAL_CLOCK_TIMESTAMP
    assert read_project(project_id)["staging_committed_sqft"] == 0

    second = api_client.release_staging_reservation(hold["id"], SM)
    validate_error(
        second, ApiErrorId.ERR_RESERVATION_STATE_INVALID, expected_status=409
    )

    stored = read_staging_reservation(hold["id"])
    assert stored["status"] == "RELEASED"
    assert stored["sqft"] == 400
    assert stored["released_at"] == INITIAL_CLOCK_TIMESTAMP
    assert read_project(project_id)["staging_committed_sqft"] == 0
    assert read_procurement_order(order["id"])["status"] == "ORDERED"


def test_installing_an_order_that_was_never_received_is_refused():
    """The order must be in `STAGED` and the project must not be frozen.

    On success the order moves `DRAFT → ORDERED`, `ordered_at` is stamped from the logical
    clock, `promised_delivery_date` is derived as `ordered_at` advanced by
    `lead_time_days` whole days, and the project's `version` increments by 1.

    Design: Corner/errors/installing_a_procurement_order_that_was_never_received_is_rejected
    """
    ctx = setup_orders_for_staging(
        [{"item_type": "CONTROLLER", "lead_time_days": 30,
          "required_staging_sqft": 400}],
        staging_area_sqft=1200,
    )
    order = ctx["procurement_orders"][0]

    response = api_client.install_procurement_order(order["id"], SM)
    validate_error(
        response, ApiErrorId.ERR_PROCUREMENT_STATE_INVALID, expected_status=409
    )

    stored = read_procurement_order(order["id"])
    assert stored["status"] == "ORDERED"
    assert stored["staging_reservation_id"] is None
    assert stored["ordered_at"] == INITIAL_CLOCK_TIMESTAMP
    assert stored["promised_delivery_date"].startswith("2026-08-31")
    assert read_project(ctx["project"]["id"])["staging_committed_sqft"] == 0


def test_a_staging_hold_on_a_frozen_project_is_refused():
    """A frozen project accepts no new hold at all, refusing it with `ERR_PROJECT_FROZEN`.

    `FROZEN` is a hard lock: while a project is frozen, activating an outage window,
    creating a staging hold, issuing a procurement order, installing staged equipment, and
    returning a car to acceptance testing are all refused with `ERR_PROJECT_FROZEN`.

    Design: Corner/errors/staging_hold_while_the_project_is_frozen_is_rejected
    """
    ctx = setup_orders_for_staging(
        [{"item_type": "DOOR_OPERATOR", "lead_time_days": 20,
          "required_staging_sqft": 200}],
        staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    group_id = ctx["group"]["id"]
    order = ctx["procurement_orders"][0]

    window = validate_success(
        api_client.create_outage_window(
            {
                "car_id": ctx["car"]["id"],
                "start_at": "2026-08-10T08:00:00Z",
                "end_at": "2026-08-15T18:00:00Z",
                "temporary_service_plan": "ADJACENT_CAR",
            },
            PM,
        ),
        expected_status=201,
    )
    validate_success(api_client.send_outage_notice(window["id"], PM))
    validate_success(api_client.activate_outage_window(window["id"], SM))
    assert read_project(project_id)["downtime_posture"] == "OPEN"

    validate_success(
        api_client.patch_elevator_group(group_id, {"min_cars_in_service": 1}, PM)
    )
    posture = read_posture(project_id)
    assert posture["downtime_posture"] == "FROZEN"
    assert posture["groups_below_floor"] == 1

    payload = {
        "procurement_order_id": order["id"],
        "sqft": 200,
        "hold_start": "2026-08-12T00:00:00Z",
        "hold_end": "2026-08-20T00:00:00Z",
        "expected_project_version": project_version(project_id),
    }
    frozen = api_client.create_staging_reservation(payload, SM)
    validate_error(frozen, ApiErrorId.ERR_PROJECT_FROZEN, expected_status=409)

    _, meta = list_staging_reservations(order["id"])
    assert meta["total_count"] == 0
    assert read_project(project_id)["staging_committed_sqft"] == 0

    validate_success(
        api_client.patch_elevator_group(group_id, {"min_cars_in_service": 0}, PM)
    )
    assert read_posture(project_id)["downtime_posture"] == "OPEN"

    payload["expected_project_version"] = project_version(project_id)
    retried = validate_success(
        api_client.create_staging_reservation(payload, SM), expected_status=201
    )
    assert retried["status"] == "HELD"
    assert read_project(project_id)["staging_committed_sqft"] == 200


def test_issuing_an_order_whose_option_is_only_submitted_is_refused():
    """Issuing the order to the factory requires the parent option to have reached
    `APPROVED`; issuing against an option that has not been approved is refused with
    `ERR_SCOPE_OPTION_NOT_APPROVED`.

    The order is created in status `DRAFT` with `ordered_at`, `promised_delivery_date` and
    `staging_reservation_id` all null.

    Design: Corner/state_machines/issuing_a_procurement_order_before_option_approval_is_rejected
    """
    ctx = setup_scoped_car(tier="CONTROLLER_ONLY", base_price_cents=5_000_000)
    submit_scope_option(ctx["scope_option"]["id"])
    order = create_procurement_order(
        ctx["scope_option"]["id"],
        item_type="CONTROLLER",
        lead_time_days=30,
        required_staging_sqft=400,
    )
    assert order["status"] == "DRAFT"

    response = api_client.issue_procurement_order(order["id"], PM)
    validate_error(
        response, ApiErrorId.ERR_SCOPE_OPTION_NOT_APPROVED, expected_status=409
    )

    stored = read_procurement_order(order["id"])
    assert stored["status"] == "DRAFT"
    assert stored["ordered_at"] is None
    assert stored["promised_delivery_date"] is None
    assert read_scope_option(ctx["scope_option"]["id"])["status"] == "SUBMITTED"
    assert read_project(ctx["project"]["id"])["status"] == "SCOPING"


def test_receiving_an_order_against_another_orders_reservation_is_refused():
    """The caller — a `ProjectManager` or a `ServiceManager` — supplies the
    `staging_reservation_id`, and three things must hold: the order must be in status
    `ORDERED`, or the request is refused with `ERR_PROCUREMENT_STATE_INVALID`; the named
    reservation must be in status `HELD`; and the reservation must belong to the very order
    being received, or the request is refused with `ERR_RESERVATION_ORDER_MISMATCH`.

    Design: Corner/endpoints/receiving_an_order_with_another_orders_reservation_is_rejected
    """
    ctx = setup_orders_for_staging(
        [
            {"item_type": "CONTROLLER", "required_staging_sqft": 400},
            {"item_type": "DOOR_OPERATOR", "required_staging_sqft": 200},
        ],
        staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    order_a, order_b = ctx["procurement_orders"]
    hold_a = hold_staging(project_id, order_a["id"], sqft=400,
                          hold_start=HOLD_START, hold_end=HOLD_END)

    response = api_client.receive_procurement_order(
        order_b["id"], {"staging_reservation_id": hold_a["id"]}, SM
    )
    validate_error(
        response, ApiErrorId.ERR_RESERVATION_ORDER_MISMATCH, expected_status=409
    )

    stored_b = read_procurement_order(order_b["id"])
    assert stored_b["status"] == "ORDERED"
    assert stored_b["staging_reservation_id"] is None

    stored_a = read_procurement_order(order_a["id"])
    assert stored_a["status"] == "ORDERED"
    assert stored_a["staging_reservation_id"] is None

    assert read_staging_reservation(hold_a["id"])["status"] == "HELD"
    assert read_project(project_id)["staging_committed_sqft"] == 400


def test_a_stale_project_version_on_a_second_option_create_is_a_precondition_failure():
    """A `POST /scope-options` request must carry `expected_project_version` as a required,
    non-optional input field whose value is the `version` the client last observed on the
    target project — the value returned by reading that project. If the project's current
    `version` differs from the supplied `expected_project_version`, the create is refused
    with `ERR_STALE_PROJECT_VERSION` and HTTP 412.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_project_version_on_scope_option_creation_returns_412
    """
    ctx = setup_project_with_cars(num_cars=2)
    project_id = ctx["project"]["id"]
    car_one, car_two = ctx["cars"]
    for car in (car_one, car_two):
        survey = submit_survey(
            car["id"],
            controller_condition="GOOD",
            machine_condition="GOOD",
            door_equipment_condition="EXCELLENT",
        )
        countersign_survey(survey["id"])

    observed = project_version(project_id)

    first = create_scope_option(
        project_id,
        car_one["id"],
        tier="CONTROLLER_ONLY",
        base_price_cents=5_000_000,
        expected_project_version=observed,
    )
    assert first["status"] == "DRAFT"
    assert read_project(project_id)["version"] == observed + 1

    stale = api_client.create_scope_option(
        {
            "car_id": car_two["id"],
            "tier": "CONTROLLER_ONLY",
            "base_price_cents": 5_000_000,
            "expected_project_version": observed,
        },
        PM,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PROJECT_VERSION, expected_status=412)

    _, meta = validate_paginated(
        api_client.list_scope_options(PM, params={"car_id": car_two["id"]})
    )
    assert meta["total_count"] == 0
    assert read_car(car_two["id"])["work_status"] == "SURVEYED"
    assert read_project(project_id)["version"] == observed + 1

    retried = create_scope_option(
        project_id,
        car_two["id"],
        tier="CONTROLLER_ONLY",
        base_price_cents=5_000_000,
        expected_project_version=project_version(project_id),
    )
    assert retried["status"] == "DRAFT"


def test_a_stale_project_version_on_a_second_staging_hold_is_a_precondition_failure():
    """**Optimistic concurrency** — `ERR_STALE_PROJECT_VERSION`, HTTP 412, on
    `POST /scope-options` and `POST /staging-reservations`.

    It is deliberately checked after the request is known to be well formed but before any
    state precondition, so that a caller holding a stale view of the project is told to
    re-read rather than being told about a state it cannot yet see.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_project_version_on_staging_hold_returns_412
    """
    ctx = setup_orders_for_staging(
        [
            {"item_type": "CONTROLLER", "lead_time_days": 30,
             "required_staging_sqft": 400},
            {"item_type": "DOOR_OPERATOR", "lead_time_days": 20,
             "required_staging_sqft": 200},
        ],
        staging_area_sqft=1200,
    )
    project_id = ctx["project"]["id"]
    order_a, order_b = ctx["procurement_orders"]
    observed = project_version(project_id)

    first = hold_staging(project_id, order_a["id"], sqft=400,
                         hold_start=HOLD_START, hold_end=HOLD_END,
                         expected_project_version=observed)
    assert first["status"] == "HELD"
    project = read_project(project_id)
    assert project["staging_committed_sqft"] == 400
    assert project["version"] == observed + 1

    stale = api_client.create_staging_reservation(
        {
            "procurement_order_id": order_b["id"],
            "sqft": 200,
            "hold_start": HOLD_START,
            "hold_end": HOLD_END,
            "expected_project_version": observed,
        },
        SM,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PROJECT_VERSION, expected_status=412)

    _, meta = list_staging_reservations(order_b["id"])
    assert meta["total_count"] == 0

    after = read_project(project_id)
    assert after["staging_committed_sqft"] == 400
    assert after["version"] == observed + 1
    assert after["staging_area_sqft"] == 1200
