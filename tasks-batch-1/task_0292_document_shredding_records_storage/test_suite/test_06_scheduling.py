"""Temporal scheduling and retention-clock boundaries: the half-open container
slot-conflict geometry, the closed-with-buffer on-site geometry, and the
inclusive retention-schedule boundary on purge.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_account_with_rate_card,
    setup_stored_box,
    create_container,
    advance_period,
)
from test_helpers import factories as f

CO = TEST_USERS["compliance_officer_headers"]
AM = TEST_USERS["account_manager_headers"]
PO = TEST_USERS["plant_operator_headers"]


# ===========================================================================
# boundary_precision_check / retention_schedule_boundary_ge_on_purge
# ===========================================================================
def test_purge_permitted_at_retention_boundary(api):
    """PRD §3.8: "when the box has a destroy_after_period set, that the account's
    current_period_index has reached at least that period - otherwise the
    retention clock has not elapsed and the purge is rejected with
    ERR_RETENTION_NOT_ELAPSED."

    Box with destroy_after_period 2; after two advance-period calls the current
    period is 2, so 2 >= 2 permits the purge (box -> DESTROYED).

    Design: Difficulty/boundary_precision_check/retention_schedule_boundary_ge_on_purge
    """
    state = setup_stored_box(barcode="BX-1", destroy_after_period=2, with_rate_card=True)
    advance_period(state["account"]["id"])
    advance_period(state["account"]["id"])
    acct = validate_success(api.get_account(state["account"]["id"], CO), 200)
    assert acct["current_period_index"] == 2, f"got {acct['current_period_index']}"
    purged = validate_success(api.purge_box(state["box"]["id"], AM), 200)
    assert purged["status"] == "DESTROYED", f"got {purged['status']}"


def test_purge_rejected_below_retention_boundary(api):
    """PRD §3.8: "otherwise the retention clock has not elapsed and the purge is
    rejected with ERR_RETENTION_NOT_ELAPSED."

    Box with destroy_after_period 2 at current period 1 (1 < 2) is rejected.

    Design: Difficulty/boundary_precision_check/retention_schedule_boundary_ge_on_purge
    """
    state = setup_stored_box(barcode="BX-1", destroy_after_period=2, with_rate_card=True)
    advance_period(state["account"]["id"])  # current_period_index -> 1
    acct = validate_success(api.get_account(state["account"]["id"], CO), 200)
    assert acct["current_period_index"] == 1
    validate_error(api.purge_box(state["box"]["id"], AM),
                   ApiErrorId.ERR_RETENTION_NOT_ELAPSED.value)


# ===========================================================================
# resource_temporal_overlap / container_slot_halfopen_overlap
# ===========================================================================
def test_slot_conflict_on_overlapping_shared_container(api):
    """PRD §3.3: "a new or rescheduled order's window must not overlap any other
    non-terminal order that shares any container. These windows are treated as
    half-open intervals running from the start up to but not including the end, so
    two windows that merely touch - one ending exactly when the other begins - do
    not conflict; a genuine overlap is rejected with ERR_SLOT_CONFLICT."

    First order [09:00,10:00) over container c1; a second order over c1 with
    [09:30,10:30) genuinely overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/container_slot_halfopen_overlap
    """
    account, location, rate_card = setup_account_with_rate_card()
    c1 = create_container(account["id"], location["id"], "CONSOLE", 50, 8.0)
    get_success_data(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="OFF_SITE_PICKUP", cadence="SCHEDULED",
        container_ids=[c1["id"]],
        scheduled_slot_start="2026-07-01T09:00:00Z",
        scheduled_slot_end="2026-07-01T10:00:00Z"), AM))
    validate_error(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="OFF_SITE_PICKUP", cadence="SCHEDULED",
        container_ids=[c1["id"]],
        scheduled_slot_start="2026-07-01T09:30:00Z",
        scheduled_slot_end="2026-07-01T10:30:00Z"), AM),
        ApiErrorId.ERR_SLOT_CONFLICT.value)


def test_touching_slot_does_not_conflict(api):
    """PRD §3.3: "so two windows that merely touch - one ending exactly when the
    other begins - do not conflict."

    A second order over the same container starting exactly when the first ends
    ([10:00,11:00) after [09:00,10:00)) is accepted.

    Design: Difficulty/resource_temporal_overlap/container_slot_halfopen_overlap
    """
    account, location, rate_card = setup_account_with_rate_card()
    c1 = create_container(account["id"], location["id"], "CONSOLE", 50, 8.0)
    get_success_data(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="OFF_SITE_PICKUP", cadence="SCHEDULED",
        container_ids=[c1["id"]],
        scheduled_slot_start="2026-07-01T09:00:00Z",
        scheduled_slot_end="2026-07-01T10:00:00Z"), AM))
    second = validate_success(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="OFF_SITE_PICKUP", cadence="SCHEDULED",
        container_ids=[c1["id"]],
        scheduled_slot_start="2026-07-01T10:00:00Z",
        scheduled_slot_end="2026-07-01T11:00:00Z"), AM), 201)
    assert second["status"] == "SCHEDULED"


# ===========================================================================
# resource_temporal_overlap / onsite_buffered_closed_overlap_at_location
# ===========================================================================
def test_onsite_buffer_conflict_at_same_location(api):
    """PRD §3.3: "the on-site buffer conflict, which applies only among
    non-terminal on-site orders at the same location_id: each such order's window
    is expanded by a thirty-minute buffer on each side - that is, the window runs
    from thirty minutes before its start to thirty minutes after its end - and the
    expanded windows are compared as closed intervals, so even buffered endpoints
    that just touch are treated as a conflict, rejected with
    ERR_ONSITE_BUFFER_CONFLICT."

    First ON_SITE order 09:00-10:00 buffers to [08:30,10:30]; a second ON_SITE
    order at the same location 10:15-11:00 buffers to [09:45,11:30] over a
    different container; the buffered closed windows overlap and the second is
    rejected.

    Design: Difficulty/resource_temporal_overlap/onsite_buffered_closed_overlap_at_location
    """
    account, location, rate_card = setup_account_with_rate_card()
    c1 = create_container(account["id"], location["id"], "CONSOLE", 50, 8.0)
    c2 = create_container(account["id"], location["id"], "CONSOLE", 30, 5.0)
    get_success_data(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[c1["id"]],
        scheduled_slot_start="2026-07-01T09:00:00Z",
        scheduled_slot_end="2026-07-01T10:00:00Z"), AM))
    validate_error(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[c2["id"]],
        scheduled_slot_start="2026-07-01T10:15:00Z",
        scheduled_slot_end="2026-07-01T11:00:00Z"), AM),
        ApiErrorId.ERR_ONSITE_BUFFER_CONFLICT.value)


def test_onsite_buffered_windows_clear_of_each_other_accepted(api):
    """PRD §3.3: "each such order's window is expanded by a thirty-minute buffer
    on each side - that is, the window runs from thirty minutes before its start
    to thirty minutes after its end - and the expanded windows are compared as
    closed intervals, so even buffered endpoints that just touch are treated as a
    conflict, rejected with ERR_ONSITE_BUFFER_CONFLICT."

    First ON_SITE order 09:00-10:00 buffers to [08:30,10:30]; a second ON_SITE
    order at the same location 11:30-12:30 buffers to [11:00,13:00]. The buffered
    closed windows are clear of one another (10:30 < 11:00), so the second order
    is accepted.

    Design: Difficulty/resource_temporal_overlap/onsite_buffered_closed_overlap_at_location
    """
    account, location, rate_card = setup_account_with_rate_card()
    c1 = create_container(account["id"], location["id"], "CONSOLE", 50, 8.0)
    c2 = create_container(account["id"], location["id"], "CONSOLE", 30, 5.0)
    get_success_data(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[c1["id"]],
        scheduled_slot_start="2026-07-01T09:00:00Z",
        scheduled_slot_end="2026-07-01T10:00:00Z"), AM))
    second = validate_success(api.create_order(f.create_order_payload(
        account["id"], location["id"], service_mode="ON_SITE", cadence="SCHEDULED",
        container_ids=[c2["id"]],
        scheduled_slot_start="2026-07-01T11:30:00Z",
        scheduled_slot_end="2026-07-01T12:30:00Z"), AM), 201)
    assert second["status"] == "SCHEDULED"
