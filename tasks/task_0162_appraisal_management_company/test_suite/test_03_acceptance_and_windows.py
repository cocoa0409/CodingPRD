"""Assignment acceptance and inspection-window scheduling conflicts.

Covers queue A (Difficulty) resource_temporal_overlap instances (appraiser
half-open + travel-buffer vs property closed-interval touch) and queue B
validations/state_machines instances for invalid windows and invalid transitions.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, factories, fixtures,
)

COORD = TEST_USERS["coordinator_headers"]


def test_appraiser_window_conflict_within_travel_buffer(api):
    """PRD §3.3: "two windows of the same appraiser collide when the later window starts
    strictly less than sixty minutes after the earlier window ends — that is, when the
    earlier window's end plus sixty minutes is strictly later than the later window's
    start. Only the appraiser's assignments in `ACCEPTED` or `REVISION` are considered. A
    collision is rejected with `ERR_APPRAISER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/appraiser_window_buffer_conflict_half_open_plus_buffer
    """
    appraiser = fixtures.create_appraiser(license_state="CA", full_name="Win A")
    l1 = fixtures.create_lender(panel_ids=[appraiser["id"]], name="Lender W1")
    l2 = fixtures.create_lender(panel_ids=[appraiser["id"]], name="Lender W2")
    p1 = fixtures.create_property(state_code="CA", street_address="20 CA St")
    p2 = fixtures.create_property(state_code="CA", street_address="21 CA St")
    o1 = fixtures.create_order(l1["id"], p1["id"])
    asg1 = fixtures.assign_order(o1["id"], o1["version"])
    fixtures.accept_assignment(asg1["id"], appraiser["id"],
                               inspection_start="2026-06-03T09:00:00Z",
                               inspection_end="2026-06-03T11:00:00Z")
    o2 = fixtures.create_order(l2["id"], p2["id"])
    asg2 = fixtures.assign_order(o2["id"], o2["version"])

    # Second window starts 30 min after the first ends -> within the 60-min buffer.
    resp = api.accept_assignment(
        asg2["id"],
        factories.accept_assignment_payload("2026-06-03T11:30:00Z", "2026-06-03T13:00:00Z"),
        fixtures.make_appraiser_headers(appraiser["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPRAISER_WINDOW_CONFLICT.value, 409)


def test_appraiser_window_exactly_buffer_apart_accepted(api):
    """PRD §3.3: "two windows of the same appraiser collide when the later window starts
    strictly less than sixty minutes after the earlier window ends — that is, when the
    earlier window's end plus sixty minutes is strictly later than the later window's start."

    Design: Difficulty/resource_temporal_overlap/appraiser_window_buffer_conflict_half_open_plus_buffer
    """
    appraiser = fixtures.create_appraiser(license_state="CA", full_name="Win OK A")
    l1 = fixtures.create_lender(panel_ids=[appraiser["id"]], name="Lender WO1")
    l2 = fixtures.create_lender(panel_ids=[appraiser["id"]], name="Lender WO2")
    p1 = fixtures.create_property(state_code="CA", street_address="23 CA St")
    p2 = fixtures.create_property(state_code="CA", street_address="24 CA St")
    o1 = fixtures.create_order(l1["id"], p1["id"])
    asg1 = fixtures.assign_order(o1["id"], o1["version"])
    fixtures.accept_assignment(asg1["id"], appraiser["id"],
                               inspection_start="2026-06-03T09:00:00Z",
                               inspection_end="2026-06-03T11:00:00Z")
    o2 = fixtures.create_order(l2["id"], p2["id"])
    asg2 = fixtures.assign_order(o2["id"], o2["version"])

    # Second window starts exactly 60 min after the first ends (earlier.end+60 == later.start,
    # not strictly later) -> no conflict, accepted.
    data = validate_success(
        api.accept_assignment(
            asg2["id"],
            factories.accept_assignment_payload("2026-06-03T12:00:00Z", "2026-06-03T13:00:00Z"),
            fixtures.make_appraiser_headers(appraiser["id"]),
        ),
        200,
    )
    assert data["status"] == "ACCEPTED", f"window exactly one buffer apart must accept, got {data['status']}"


def test_property_window_conflict_on_boundary_touch(api):
    """PRD §3.3: "the window must not collide with another inspection window on the
    **same property**; here the window is treated as a closed interval that includes both
    endpoints, with no buffer, so even a boundary touch is a conflict, again considering
    only `ACCEPTED` or `REVISION` assignments. A collision is rejected with
    `ERR_PROPERTY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/property_window_closed_interval_touch_conflict
    """
    a1 = fixtures.create_appraiser(license_state="CA", full_name="PW A1")
    a2 = fixtures.create_appraiser(license_state="CA", full_name="PW A2")
    l1 = fixtures.create_lender(panel_ids=[a1["id"]], name="Lender PW1")
    l2 = fixtures.create_lender(panel_ids=[a2["id"]], name="Lender PW2")
    prop = fixtures.create_property(state_code="CA", street_address="22 CA St")
    o1 = fixtures.create_order(l1["id"], prop["id"])
    asg1 = fixtures.assign_order(o1["id"], o1["version"])
    fixtures.accept_assignment(asg1["id"], a1["id"],
                               inspection_start="2026-06-03T09:00:00Z",
                               inspection_end="2026-06-03T11:00:00Z")
    o2 = fixtures.create_order(l2["id"], prop["id"])
    asg2 = fixtures.assign_order(o2["id"], o2["version"])

    # Second window starts exactly at the first window's end -> closed-interval touch.
    resp = api.accept_assignment(
        asg2["id"],
        factories.accept_assignment_payload("2026-06-03T11:00:00Z", "2026-06-03T12:00:00Z"),
        fixtures.make_appraiser_headers(a2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROPERTY_WINDOW_CONFLICT.value, 409)


def test_property_window_disjoint_intervals_accepted(api):
    """PRD §3.3: "the window must not collide with another inspection window on the
    **same property**; here the window is treated as a closed interval that includes both
    endpoints, with no buffer, so even a boundary touch is a conflict, again considering
    only `ACCEPTED` or `REVISION` assignments."

    Design: Difficulty/resource_temporal_overlap/property_window_closed_interval_touch_conflict
    """
    a1 = fixtures.create_appraiser(license_state="CA", full_name="PW OK A1")
    a2 = fixtures.create_appraiser(license_state="CA", full_name="PW OK A2")
    l1 = fixtures.create_lender(panel_ids=[a1["id"]], name="Lender PWO1")
    l2 = fixtures.create_lender(panel_ids=[a2["id"]], name="Lender PWO2")
    prop = fixtures.create_property(state_code="CA", street_address="25 CA St")
    o1 = fixtures.create_order(l1["id"], prop["id"])
    asg1 = fixtures.assign_order(o1["id"], o1["version"])
    fixtures.accept_assignment(asg1["id"], a1["id"],
                               inspection_start="2026-06-03T09:00:00Z",
                               inspection_end="2026-06-03T11:00:00Z")
    o2 = fixtures.create_order(l2["id"], prop["id"])
    asg2 = fixtures.assign_order(o2["id"], o2["version"])

    # Second window is strictly after the first with a gap (no closed-interval touch) -> accepted.
    data = validate_success(
        api.accept_assignment(
            asg2["id"],
            factories.accept_assignment_payload("2026-06-03T12:00:00Z", "2026-06-03T13:00:00Z"),
            fixtures.make_appraiser_headers(a2["id"]),
        ),
        200,
    )
    assert data["status"] == "ACCEPTED", f"disjoint property windows must accept, got {data['status']}"


def test_accept_with_end_before_start_rejected(api):
    """PRD §3.3: "the window itself must be valid: `inspection_end` must be strictly after
    `inspection_start`, else `ERR_INVALID_WINDOW`."

    Design: Corner/validations/invalid_inspection_window_end_before_start
    """
    base = fixtures.setup_order_ready_to_assign()
    order = base["order"]
    asg = fixtures.assign_order(order["id"], order["version"])
    resp = api.accept_assignment(
        asg["id"],
        factories.accept_assignment_payload("2026-06-03T11:00:00Z", "2026-06-03T10:00:00Z"),
        fixtures.make_appraiser_headers(base["appraiser"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value, 422)


def test_accept_already_accepted_assignment_rejected(api):
    """PRD §3.3: "Accepting moves the assignment from `OFFERED` to `ACCEPTED`."
    PRD §2.10: "**State legality** — the target resource must be in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/accept_already_accepted_assignment_returns_invalid_state
    """
    base = fixtures.setup_order_ready_to_assign()
    order = base["order"]
    asg = fixtures.assign_order(order["id"], order["version"])
    fixtures.accept_assignment(asg["id"], base["appraiser"]["id"])
    # A second accept on an ACCEPTED assignment is not a defined transition.
    resp = api.accept_assignment(
        asg["id"],
        factories.accept_assignment_payload("2026-06-04T15:00:00Z", "2026-06-04T17:00:00Z"),
        fixtures.make_appraiser_headers(base["appraiser"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
