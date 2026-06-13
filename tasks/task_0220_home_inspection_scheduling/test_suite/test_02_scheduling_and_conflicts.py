"""Scheduling guards: certification, territory, double-booking, same-day, capacity,
inspector-active dependency, validation precedence, and the daily-minutes ledger.
"""
import pytest
from test_helpers import (
    api_client,
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_base_config, create_requested_order, setup_requested_order,
    setup_scheduled_order, create_inspector, create_property,
)
from test_helpers import factories as F

SCHED = TEST_USERS["scheduler_headers"]


# ---------------------------------------------------------------------------
# certification + four-point eligibility
# ---------------------------------------------------------------------------
def test_schedule_four_point_too_new_property_rejected(api):
    """PRD §3.3: "if the type is `FOUR_POINT`, the property's `year_built` must be no
    later than 2000; a failure of either certification or four-point eligibility raises
    `ERR_INSPECTOR_NOT_CERTIFIED`."

    Design: Corner/validations/corner_four_point_too_new_property_rejected
    """
    cfg, order = setup_requested_order(inspection_type="FOUR_POINT",
                                       certifications=["FOUR_POINT"], year_built=2010)
    resp = api.schedule_order(
        order["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-08-06T13:00:00Z"),
        SCHED)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_NOT_CERTIFIED.value)


# ---------------------------------------------------------------------------
# territory mismatch
# ---------------------------------------------------------------------------
def test_schedule_property_outside_territory_rejected(api):
    """PRD §3.3: "The property's `zip_code` must lie inside the assigned inspector's
    territory ZIP list, or the request fails with `ERR_TERRITORY_MISMATCH`."

    Design: Corner/validations/corner_schedule_territory_mismatch_rejected
    """
    cfg, order = setup_requested_order(certifications=["BUYER"], zip_code="90210",
                                       territory_zip_codes=["33101"])
    resp = api.schedule_order(
        order["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-08-07T13:00:00Z"),
        SCHED)
    validate_error(resp, ApiErrorId.ERR_TERRITORY_MISMATCH.value)


# ---------------------------------------------------------------------------
# daily capacity exceeded
# ---------------------------------------------------------------------------
def test_schedule_exceeding_daily_capacity_rejected(api):
    """PRD §3.3: "Finally, adding this order's on-site minutes to the inspector's
    already-booked minutes for that calendar date must not exceed their
    `daily_capacity_minutes`, or the request fails with `ERR_DAILY_CAPACITY_EXCEEDED`."

    Design: Corner/validations/corner_daily_capacity_exceeded_rejected
    """
    # BUYER base 180 + RADON 30 = 210 minutes; capacity 200 -> exceeded.
    cfg, order = setup_requested_order(certifications=["BUYER"],
                                       daily_capacity_minutes=200)
    api_client.create_addon(order["id"], F.create_addon_payload("RADON"), SCHED)
    resp = api.schedule_order(
        order["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-08-08T13:00:00Z"),
        SCHED)
    validate_error(resp, ApiErrorId.ERR_DAILY_CAPACITY_EXCEEDED.value)


# ---------------------------------------------------------------------------
# resource temporal overlap — inspector half-open buffer
# ---------------------------------------------------------------------------
def test_inspector_double_booked_within_travel_buffer(api):
    """PRD §3.3: "The `scheduled_start` must not collide with another of that
    inspector's appointments once the territory travel buffer is applied as a half-open
    overlap window, or the request fails with `ERR_INSPECTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/inspector_travel_buffer_overlap_half_open
    """
    cfg, _ = setup_scheduled_order(inspection_type="BUYER", certifications=["BUYER"],
                                   scheduled_start="2026-07-15T13:00:00Z")
    prop2 = create_property(address_line="2 B St")
    order2 = create_requested_order(cfg, property_id=prop2["id"])
    # First order occupies 13:00 + 180 + 30 buffer -> through 16:30; 16:00 collides.
    resp = api.schedule_order(
        order2["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-15T16:00:00Z"),
        SCHED)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED.value)


def test_inspector_double_booked_distinct_property_same_inspector(api):
    """PRD §3.4: "Scheduling and re-inspection debit this figure; unscheduling and
    cancellation credit back the same `duration_minutes` for the same date, so the
    ledger never drifts."
    PRD §3.3: "The `scheduled_start` must not collide with another of that inspector's
    appointments once the territory travel buffer is applied as a half-open overlap
    window, or the request fails with `ERR_INSPECTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/inspector_travel_buffer_overlap_half_open
    """
    cfg, _ = setup_scheduled_order(inspection_type="BUYER", certifications=["BUYER"],
                                   scheduled_start="2026-07-15T13:00:00Z")
    prop2 = create_property(address_line="3 C St")
    order2 = create_requested_order(cfg, property_id=prop2["id"])
    # 14:00 is strictly inside the 13:00-16:30 buffered occupancy.
    resp = api.schedule_order(
        order2["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-15T14:00:00Z"),
        SCHED)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED.value)


# ---------------------------------------------------------------------------
# resource temporal overlap — property same-day closed bucket
# ---------------------------------------------------------------------------
def test_same_property_same_day_conflict_rejected(api):
    """PRD §3.3: "No other non-terminal order for the same `property_id` may share the
    calendar date being booked, or the request fails with `ERR_PROPERTY_SAME_DAY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/property_same_calendar_day_conflict_closed
    """
    cfg = setup_base_config(certifications=["BUYER"])
    insp2 = create_inspector(cfg["territory"]["id"], certifications=["BUYER"],
                             full_name="Ivo")
    order1 = create_requested_order(cfg)
    get_success_data(api.schedule_order(
        order1["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-16T09:00:00Z"),
        SCHED))
    order2 = create_requested_order(cfg)  # same property
    # Different inspector, non-overlapping clock time, but same UTC calendar date.
    resp = api.schedule_order(
        order2["id"],
        F.schedule_order_payload(insp2["id"], "2026-07-16T18:00:00Z"),
        SCHED)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_SAME_DAY_CONFLICT.value)


def test_same_property_same_day_conflict_different_clock_time(api):
    """PRD §3.3: "No other non-terminal order for the same `property_id` may share the
    calendar date being booked, or the request fails with `ERR_PROPERTY_SAME_DAY_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/property_same_calendar_day_conflict_closed
    """
    cfg = setup_base_config(certifications=["BUYER"])
    insp2 = create_inspector(cfg["territory"]["id"], certifications=["BUYER"],
                             full_name="Ivo")
    order1 = create_requested_order(cfg)
    get_success_data(api.schedule_order(
        order1["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-16T06:00:00Z"),
        SCHED))
    order2 = create_requested_order(cfg)
    resp = api.schedule_order(
        order2["id"],
        F.schedule_order_payload(insp2["id"], "2026-07-16T22:00:00Z"),
        SCHED)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_SAME_DAY_CONFLICT.value)


# ---------------------------------------------------------------------------
# validation precedence — certified (referential) beats double-booked (temporal)
# ---------------------------------------------------------------------------
def test_not_certified_beats_double_booked_precedence(api):
    """PRD §3.3: "Relative to one another these business checks run in the order:
    inspector-not-certified (and four-point eligibility), then territory match, then
    double-booking, then same-day property conflict, then daily-capacity."
    PRD §3.3: "The inspector must be certified for the order's `inspection_type` (the
    type must appear in their `certifications`) ... a failure of either certification or
    four-point eligibility raises `ERR_INSPECTOR_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/schedule_double_booked_and_not_certified_temporal_beats_referential
    """
    # Inspector certified ONLY for SELLER. First SELLER order occupies the slot,
    # then a BUYER order for an overlapping slot is BOTH not-certified (BUYER not in
    # certs) AND double-booked. Certification check precedes double-booking.
    cfg = setup_base_config(certifications=["SELLER"], client_role="SELLER")
    order1 = create_requested_order(cfg, inspection_type="SELLER")
    get_success_data(api.schedule_order(
        order1["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-09T13:00:00Z"),
        SCHED))
    prop2 = create_property(address_line="2 B St")
    order2 = create_requested_order(cfg, inspection_type="BUYER", property_id=prop2["id"])
    resp = api.schedule_order(
        order2["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-09T14:00:00Z"),
        SCHED)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_NOT_CERTIFIED.value)


def test_not_certified_precedes_double_booked_other_slot(api):
    """PRD §3.3: "Relative to one another these business checks run in the order:
    inspector-not-certified (and four-point eligibility), then territory match, then
    double-booking, then same-day property conflict, then daily-capacity."
    PRD §3.3: "The inspector must be certified for the order's `inspection_type` (the
    type must appear in their `certifications`) ... a failure of either certification or
    four-point eligibility raises `ERR_INSPECTOR_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/schedule_double_booked_and_not_certified_temporal_beats_referential
    """
    # Same conflict pair, a different overlapping slot: the certification check still
    # pre-empts the double-booking check.
    cfg = setup_base_config(certifications=["SELLER"], client_role="SELLER")
    order1 = create_requested_order(cfg, inspection_type="SELLER")
    get_success_data(api.schedule_order(
        order1["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-09T13:00:00Z"),
        SCHED))
    prop2 = create_property(address_line="3 C St")
    order2 = create_requested_order(cfg, inspection_type="BUYER", property_id=prop2["id"])
    resp = api.schedule_order(
        order2["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-09T15:00:00Z"),
        SCHED)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_NOT_CERTIFIED.value)


# ---------------------------------------------------------------------------
# compensating invariant — schedule/unschedule conserve inspector minutes
# ---------------------------------------------------------------------------
def test_schedule_then_unschedule_conserves_daily_minutes(api):
    """PRD §3.4: "Scheduling and re-inspection debit this figure; unscheduling and
    cancellation credit back the same `duration_minutes` for the same date, so the
    ledger never drifts."
    PRD §3.3: "unscheduling a `SCHEDULED` order returns it to `REQUESTED`, clears
    `inspector_id`, `scheduled_start`, `scheduled_date`, and `quoted_fee_cents`, and
    credits that inspector's daily ledger for the prior `scheduled_date` by the same
    `duration_minutes` so net daily load is unchanged, then increments the order's
    `version`."

    Design: Difficulty/compensating_invariant/schedule_unschedule_conserves_inspector_daily_minutes
    """
    cfg, order = setup_requested_order(certifications=["BUYER"])
    api_client.create_addon(order["id"], F.create_addon_payload("RADON"), SCHED)  # 210 min
    get_success_data(api.schedule_order(
        order["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-17T13:00:00Z"),
        SCHED))
    load_before = get_success_data(api.get_inspector_daily_load(
        cfg["inspector"]["id"], SCHED, params={"date": "2026-07-17"}))
    assert load_before["booked_minutes"] == 210
    get_success_data(api.unschedule_order(order["id"], SCHED))
    load_after = get_success_data(api.get_inspector_daily_load(
        cfg["inspector"]["id"], SCHED, params={"date": "2026-07-17"}))
    assert load_after["booked_minutes"] == 0


def test_schedule_then_cancel_credits_back_daily_minutes(api):
    """PRD §3.9: "If the order had been booked (it was `SCHEDULED`, `IN_PROGRESS`, or
    `REPORT_DRAFT`), the inspector's daily scheduled-minutes ledger is credited back by
    the order's `duration_minutes` for its `scheduled_date`, leaving net daily load
    unchanged."
    PRD §3.4: "For a given inspector and calendar date, booked minutes are the sum of
    the `duration_minutes` of every one of that inspector's orders whose `scheduled_date`
    equals the date and whose `status` is one of `SCHEDULED`, `IN_PROGRESS`,
    `REPORT_DRAFT`, or `DELIVERED`."

    Design: Difficulty/compensating_invariant/schedule_unschedule_conserves_inspector_daily_minutes
    """
    # BUYER base 180 booked on the date, then cancelling the SCHEDULED order credits
    # the 180 back to 0.
    cfg, order = setup_scheduled_order(inspection_type="BUYER", certifications=["BUYER"],
                                       scheduled_start="2026-07-27T13:00:00Z")
    load_before = get_success_data(api.get_inspector_daily_load(
        cfg["inspector"]["id"], SCHED, params={"date": "2026-07-27"}))
    assert load_before["booked_minutes"] == 180
    get_success_data(api.cancel_order(order["id"], SCHED))
    load_after = get_success_data(api.get_inspector_daily_load(
        cfg["inspector"]["id"], SCHED, params={"date": "2026-07-27"}))
    assert load_after["booked_minutes"] == 0
