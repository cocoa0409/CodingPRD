"""Design consults: the dual estimate/actual fee model and the consultant
buffer-gap availability check."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client,
    new_customer, new_consultant, book_consult, confirm_booking, complete_booking,
    create_booking_payload, make_customer_headers, TEST_USERS,
)

ADMIN = TEST_USERS["store_admin_headers"]


# ─── Difficulty: dual_variant_calc / estimate ceils vs actual prorates ─────
def _setup_confirmed_booking():
    customer = new_customer(email="c1@x.com", full_name="Cust One")
    consultant = new_consultant(name="Ada", specialty="VERTICAL_FARM",
                                hourly_rate_cents=12000, buffer_minutes=30)
    booking = book_consult(consultant["id"], customer["id"],
                           "2026-07-02T14:00:00Z", "2026-07-02T15:30:00Z")
    return customer, consultant, booking


def test_estimated_fee_ceils_to_whole_hour(api):
    """PRD §3.7: "it measures the scheduled duration as the whole minutes between
    `start_at` and `end_at`, converts that to hours by dividing by 60 and rounding
    up to the next whole hour, and multiplies the whole-hour count by the
    consultant's `hourly_rate_cents`, writing the result to `estimated_fee_cents`."

    Design: Difficulty/dual_variant_calc/consult_fee_estimate_vs_actual
    """
    customer, consultant, booking = _setup_confirmed_booking()
    assert booking["estimated_fee_cents"] == 24000
    assert booking["status"] == "REQUESTED"


def test_actual_fee_prorates_to_the_minute(api):
    """PRD §3.7: "completion moves it `CONFIRMED → COMPLETED` and computes the
    **actual fee** as `hourly_rate_cents` multiplied by `actual_minutes`, divided
    by 60, and rounded half up to whole cents, written to `actual_fee_cents`."

    Design: Difficulty/dual_variant_calc/consult_fee_estimate_vs_actual
    """
    customer, consultant, booking = _setup_confirmed_booking()
    confirm_booking(booking["id"], consultant["id"])
    completed = complete_booking(booking["id"], consultant["id"], actual_minutes=75)
    assert completed["actual_fee_cents"] == 15000
    assert completed["status"] == "COMPLETED"


# ─── Difficulty: resource_temporal_overlap / consultant buffer gap ─────────
def _setup_consultant_with_booking():
    customer = new_customer(email="cb@x.com", full_name="C B")
    consultant = new_consultant(name="Ben", specialty="AQUAPONICS",
                                hourly_rate_cents=10000, buffer_minutes=30)
    book_consult(consultant["id"], customer["id"],
                 "2026-07-02T10:00:00Z", "2026-07-02T11:00:00Z")
    return customer, consultant


def test_booking_within_buffer_rejected(api):
    """PRD §3.7: "the requested window must not fall within `buffer_minutes` of any
    existing `REQUESTED` or `CONFIRMED` booking on that consultant, and a violation
    is rejected with `ERR_CONSULTANT_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/consultant_buffer_gap_rejected_exact_buffer_allowed
    """
    customer, consultant = _setup_consultant_with_booking()
    headers = make_customer_headers(customer["id"])
    res = api.create_booking(
        consultant["id"],
        create_booking_payload(customer["id"], "2026-07-02T11:15:00Z", "2026-07-02T12:00:00Z"),
        headers,
    )
    validate_error(res, "ERR_CONSULTANT_UNAVAILABLE")


def test_booking_well_clear_of_buffer_accepted(api):
    """PRD §3.7: "the requested window must not fall within `buffer_minutes` of any
    existing `REQUESTED` or `CONFIRMED` booking on that consultant, and a violation
    is rejected with `ERR_CONSULTANT_UNAVAILABLE`."
    PRD §3.7: "A new booking starts `REQUESTED`."

    Design: Difficulty/resource_temporal_overlap/consultant_buffer_gap_rejected_exact_buffer_allowed
    """
    customer, consultant = _setup_consultant_with_booking()
    booking = book_consult(consultant["id"], customer["id"],
                           "2026-07-02T13:00:00Z", "2026-07-02T14:00:00Z")
    assert booking["status"] == "REQUESTED"
