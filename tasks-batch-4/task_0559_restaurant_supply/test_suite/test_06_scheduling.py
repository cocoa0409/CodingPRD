"""Dock delivery scheduling (half-open overlap, capacity 1, adjacency allowed) and
equipment install scheduling (equipment-line requirement, lead-time gate, crew 60-minute
buffer), including the lead-time-vs-buffer precedence.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    fixtures,
)

WH = TEST_USERS["warehouse_headers"]


def _confirmed_equipment_order(api, acct, sku, lead_time_days):
    prod = fixtures.create_product(api, sku=sku, name="Deck Oven", category="EQUIPMENT",
                                   unit_price_cents=200000, case_qty=1, case_price_cents=200000,
                                   pallet_case_qty=1, pallet_price_cents=200000,
                                   weight_lbs_per_unit=400, fulfillment_type="STOCK",
                                   freight_type="LTL", lead_time_days=lead_time_days,
                                   on_hand_qty=5, par_level=5, reorder_point=1)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 1)
    fixtures.confirm_order(api, order["id"], acct["id"])
    return order


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / dock_half_open_overlap_rejected
# --------------------------------------------------------------------------- #
def _confirmed_order_and_dock(api):
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="RACK-1", name="Sheet Rack", unit_price_cents=4000,
                                   case_qty=4, case_price_cents=15000, pallet_case_qty=4,
                                   pallet_price_cents=56000, weight_lbs_per_unit=20,
                                   fulfillment_type="STOCK", freight_type="LTL", on_hand_qty=50,
                                   par_level=20, reorder_point=4)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 2)
    fixtures.confirm_order(api, order["id"], acct["id"])
    dock = fixtures.create_dock(api, name="Dock D1")
    return order, dock


def test_overlapping_dock_window_rejected(api):
    """PRD §3.9: "the requested window may not overlap any existing `SCHEDULED` appointment on the
    same dock, where overlap uses half-open intersection so that two windows sharing only an
    endpoint (one ending exactly when the other starts) are considered adjacent and permitted; a
    genuine overlap is rejected with `ERR_DOCK_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/dock_half_open_overlap_rejected
    """
    order, dock = _confirmed_order_and_dock(api)
    validate_success(api.create_appointment(
        {"order_id": order["id"], "dock_id": dock["id"],
         "window_start": "2026-05-10T08:00:00Z", "window_end": "2026-05-10T10:00:00Z"}, WH), 201)
    resp = api.create_appointment(
        {"order_id": order["id"], "dock_id": dock["id"],
         "window_start": "2026-05-10T09:00:00Z", "window_end": "2026-05-10T11:00:00Z"}, WH)
    validate_error(resp, ApiErrorId.ERR_DOCK_DOUBLE_BOOKED.value)


def test_adjacent_dock_window_permitted(api):
    """PRD §3.9: "two windows sharing only an endpoint (one ending exactly when the other starts)
    are considered adjacent and permitted".

    Design: Difficulty/resource_temporal_overlap/dock_half_open_overlap_rejected
    """
    order, dock = _confirmed_order_and_dock(api)
    validate_success(api.create_appointment(
        {"order_id": order["id"], "dock_id": dock["id"],
         "window_start": "2026-05-10T08:00:00Z", "window_end": "2026-05-10T10:00:00Z"}, WH), 201)
    appt2 = validate_success(api.create_appointment(
        {"order_id": order["id"], "dock_id": dock["id"],
         "window_start": "2026-05-10T10:00:00Z", "window_end": "2026-05-10T11:00:00Z"}, WH), 201)
    assert appt2["status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / crew_buffer_gap_conflict_rejected
# --------------------------------------------------------------------------- #
def test_crew_job_within_buffer_gap_rejected(api):
    """PRD §3.9: "a crew enforces a 60-minute buffer between jobs: the new job conflicts with any
    existing `SCHEDULED` job on the same crew when the new window's start falls before that job's
    end extended by 60 minutes and that job's start falls before the new window's end extended by 60
    minutes; such a conflict is rejected with `ERR_CREW_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/crew_buffer_gap_conflict_rejected
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = fixtures.create_account(api)
    crew = fixtures.create_crew(api, name="Crew C2")
    order = _confirmed_equipment_order(api, acct, sku="OVEN0-2", lead_time_days=0)
    validate_success(api.create_install_job(
        {"order_id": order["id"], "crew_id": crew["id"],
         "window_start": "2026-05-12T08:00:00Z", "window_end": "2026-05-12T10:00:00Z"}, WH), 201)
    resp = api.create_install_job(
        {"order_id": order["id"], "crew_id": crew["id"],
         "window_start": "2026-05-12T10:30:00Z", "window_end": "2026-05-12T12:00:00Z"}, WH)
    validate_error(resp, ApiErrorId.ERR_CREW_BUFFER_CONFLICT.value)


def test_crew_job_with_full_buffer_gap_permitted(api):
    """PRD §3.9: "a crew enforces a 60-minute buffer between jobs: the new job conflicts with any
    existing `SCHEDULED` job on the same crew when the new window's start falls before that job's
    end extended by 60 minutes and that job's start falls before the new window's end extended by 60
    minutes; such a conflict is rejected with `ERR_CREW_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/crew_buffer_gap_conflict_rejected
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = fixtures.create_account(api)
    crew = fixtures.create_crew(api, name="Crew C2b")
    order = _confirmed_equipment_order(api, acct, sku="OVEN0-2b", lead_time_days=0)
    validate_success(api.create_install_job(
        {"order_id": order["id"], "crew_id": crew["id"],
         "window_start": "2026-05-12T08:00:00Z", "window_end": "2026-05-12T10:00:00Z"}, WH), 201)
    # gap exactly 60 min (new start 11:00 == existing end 10:00 + 60): not a conflict
    job2 = validate_success(api.create_install_job(
        {"order_id": order["id"], "crew_id": crew["id"],
         "window_start": "2026-05-12T11:00:00Z", "window_end": "2026-05-12T12:00:00Z"}, WH), 201)
    assert job2["status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict / install_lead_time_beats_crew_buffer
# --------------------------------------------------------------------------- #
def test_lead_time_error_precedes_crew_buffer_conflict(api):
    """PRD §3.9: "the install may not be scheduled before its equipment lead time has elapsed: the
    `window_start` must be at or after the order's `confirmed_at` plus a number of days equal to the
    largest `lead_time_days` among the order's `EQUIPMENT` lines' products, and an earlier start is
    rejected with `ERR_LEAD_TIME_NOT_ELAPSED`."

    Design: Difficulty/priority_pair_validation_conflict/install_lead_time_beats_crew_buffer
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = fixtures.create_account(api)
    crew = fixtures.create_crew(api, name="Crew C1")
    order_x = _confirmed_equipment_order(api, acct, sku="OVEN0-1", lead_time_days=0)
    validate_success(api.create_install_job(
        {"order_id": order_x["id"], "crew_id": crew["id"],
         "window_start": "2026-05-05T08:00:00Z", "window_end": "2026-05-05T10:00:00Z"}, WH), 201)
    order_y = _confirmed_equipment_order(api, acct, sku="OVEN10-1", lead_time_days=10)
    # 05-05 is both before the 05-11 lead-time floor AND within 60 min of the existing job.
    resp = api.create_install_job(
        {"order_id": order_y["id"], "crew_id": crew["id"],
         "window_start": "2026-05-05T08:30:00Z", "window_end": "2026-05-05T09:30:00Z"}, WH)
    validate_error(resp, ApiErrorId.ERR_LEAD_TIME_NOT_ELAPSED.value)


def test_lead_time_not_elapsed_rejected_in_isolation(api):
    """PRD §3.9: "the install may not be scheduled before its equipment lead time has elapsed: the
    `window_start` must be at or after the order's `confirmed_at` plus a number of days equal to the
    largest `lead_time_days` among the order's `EQUIPMENT` lines' products, and an earlier start is
    rejected with `ERR_LEAD_TIME_NOT_ELAPSED`."

    Design: Difficulty/priority_pair_validation_conflict/install_lead_time_beats_crew_buffer
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = fixtures.create_account(api)
    crew = fixtures.create_crew(api, name="Crew C1-solo")  # no existing jobs -> no buffer conflict
    order_y = _confirmed_equipment_order(api, acct, sku="OVEN10-solo", lead_time_days=10)
    resp = api.create_install_job(
        {"order_id": order_y["id"], "crew_id": crew["id"],
         "window_start": "2026-05-05T08:00:00Z", "window_end": "2026-05-05T10:00:00Z"}, WH)
    validate_error(resp, ApiErrorId.ERR_LEAD_TIME_NOT_ELAPSED.value)


# --------------------------------------------------------------------------- #
# validations / install_job_no_equipment_line_rejected (corner)
# --------------------------------------------------------------------------- #
def test_install_job_without_equipment_line_rejected(api):
    """PRD §3.9: "the order must contain at least one `EQUIPMENT` line, otherwise
    `ERR_NO_EQUIPMENT_LINE`."

    Design: Corner/validations/install_job_no_equipment_line_rejected
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    acct = fixtures.create_account(api)
    crew = fixtures.create_crew(api, name="Crew NX")
    prod = fixtures.create_product(api, sku="NEQ-1", name="Sauce Pan", category="SMALLWARE",
                                   unit_price_cents=900, case_qty=12, case_price_cents=9600,
                                   pallet_case_qty=10, pallet_price_cents=90000, weight_lbs_per_unit=2,
                                   par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 2)
    fixtures.confirm_order(api, order["id"], acct["id"])
    resp = api.create_install_job(
        {"order_id": order["id"], "crew_id": crew["id"],
         "window_start": "2026-05-20T08:00:00Z", "window_end": "2026-05-20T10:00:00Z"}, WH)
    validate_error(resp, ApiErrorId.ERR_NO_EQUIPMENT_LINE.value)


# --------------------------------------------------------------------------- #
# validations / appointment_invalid_time_window_rejected (corner)
# --------------------------------------------------------------------------- #
def test_appointment_non_positive_window_rejected(api):
    """PRD §3.9: "both require `window_end` to be strictly after `window_start`, otherwise
    `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/validations/appointment_invalid_time_window_rejected
    """
    order, dock = _confirmed_order_and_dock(api)
    resp = api.create_appointment(
        {"order_id": order["id"], "dock_id": dock["id"],
         "window_start": "2026-05-10T10:00:00Z", "window_end": "2026-05-10T10:00:00Z"}, WH)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW.value)
