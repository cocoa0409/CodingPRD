"""Resource-overlap geometries: operatory half-open window + cleanup buffer
(exclusive) versus kennel aggregate per-day capacity.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_household, create_patient, create_operatory, create_kennel,
    create_estimate, present_estimate, approve_estimate,
    create_appointment_in_exam, book_surgery, reserve_boarding,
    TEST_USERS,
)

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]


def _approved_estimate(api, patient_id, unit_price=30000):
    est = create_estimate(patient_id, line_items=[
        {"service_code": "S", "qty": 1, "unit_price_cents": unit_price, "eligible_for_plan_discount": False}],
        deposit_required_cents=0)
    present_estimate(est["id"])
    approve_estimate(est["id"])
    return est


class TestOperatoryBufferOverlap:
    """A surgery window plus the cleanup buffer must not overlap another surgery (PRD 3.8)."""

    def test_second_surgery_in_buffer_zone_rejected(self, api):
        """PRD 3.8: "a new surgery's window taken together with the operatory's
        `cleanup_buffer_minutes` appended after its end ... must not overlap the
        equivalently buffered interval of any other non-cancelled surgery in the same
        operatory; a conflict is refused with `ERR_OPERATORY_CONFLICT`."

        Surgery A 09:00-10:00 with a 30-min buffer reserves through 10:30; a second
        surgery 10:15-11:00 overlaps the buffer and is rejected.

        Design: Difficulty/resource_temporal_overlap/operatory_halfopen_plus_buffer_overlap
        """
        operatory = create_operatory(cleanup_buffer_minutes=30, name="OR-5")
        hh = create_household("Hale")
        _, pat1 = create_patient(household_id=hh["id"], name="P1", species="DOG", weight_kg=10)
        _, pat2 = create_patient(household_id=hh["id"], name="P2", species="DOG", weight_kg=10)
        est1 = _approved_estimate(api, pat1["id"])
        est2 = _approved_estimate(api, pat2["id"])
        appt1 = create_appointment_in_exam(pat1["id"],
                                           scheduled_start="2026-07-08T08:00:00Z",
                                           scheduled_end="2026-07-08T12:00:00Z")
        book_surgery(appt1["id"], operatory["id"], est1["id"],
                     window_start="2026-07-08T09:00:00Z",
                     window_end="2026-07-08T10:00:00Z", procedure_name="A")
        appt2 = create_appointment_in_exam(pat2["id"],
                                           scheduled_start="2026-07-08T08:00:00Z",
                                           scheduled_end="2026-07-08T12:00:00Z")
        res = api.create_surgery({
            "appointment_id": appt2["id"], "operatory_id": operatory["id"],
            "estimate_id": est2["id"], "procedure_name": "B",
            "window_start": "2026-07-08T10:15:00Z",
            "window_end": "2026-07-08T11:00:00Z",
        }, VETERINARIAN)
        validate_error(res, "ERR_OPERATORY_CONFLICT", expected_status=409)

    def test_second_surgery_after_buffer_clears_allowed(self, api):
        """PRD 3.8: "the half-open interval from `window_start` up to `window_end` plus
        the buffer — must not overlap the equivalently buffered interval of any other
        non-cancelled surgery".

        Surgery A 09:00-10:00 reserves through 10:30; a second surgery booked 10:30-11:00
        (its own buffered start at exactly 10:30, the half-open boundary) does not overlap
        and is allowed.

        Design: Difficulty/resource_temporal_overlap/operatory_halfopen_plus_buffer_overlap
        """
        operatory = create_operatory(cleanup_buffer_minutes=30, name="OR-5b")
        hh = create_household("Hale2")
        _, pat1 = create_patient(household_id=hh["id"], name="P1", species="DOG", weight_kg=10)
        _, pat2 = create_patient(household_id=hh["id"], name="P2", species="DOG", weight_kg=10)
        est1 = _approved_estimate(api, pat1["id"])
        est2 = _approved_estimate(api, pat2["id"])
        appt1 = create_appointment_in_exam(pat1["id"],
                                           scheduled_start="2026-07-08T08:00:00Z",
                                           scheduled_end="2026-07-08T13:00:00Z")
        book_surgery(appt1["id"], operatory["id"], est1["id"],
                     window_start="2026-07-08T09:00:00Z",
                     window_end="2026-07-08T10:00:00Z", procedure_name="A")
        appt2 = create_appointment_in_exam(pat2["id"],
                                           scheduled_start="2026-07-08T08:00:00Z",
                                           scheduled_end="2026-07-08T13:00:00Z")
        res = api.create_surgery({
            "appointment_id": appt2["id"], "operatory_id": operatory["id"],
            "estimate_id": est2["id"], "procedure_name": "B",
            "window_start": "2026-07-08T10:30:00Z",
            "window_end": "2026-07-08T11:00:00Z",
        }, VETERINARIAN)
        validate_success(res, 201)


class TestKennelAggregateCapacity:
    """A kennel allows up to capacity overlapping stays per day (PRD 3.9)."""

    def test_third_overlapping_stay_exceeds_capacity_rejected(self, api):
        """PRD 3.9: "for every inclusive day a new boarding stay would span, the count of
        non-cancelled stays already covering that day in that kennel must remain at or
        below the kennel's `capacity`; if admitting the new stay would exceed capacity on
        even one overlapping day, the reservation is refused with `ERR_KENNEL_AT_CAPACITY`."

        Capacity 2; two stays already cover 2026-07-12; a third covering that day pushes
        the count to 3 > 2 and is rejected.

        Design: Difficulty/resource_temporal_overlap/kennel_aggregate_capacity_overlap
        """
        ken = create_kennel(capacity=2, name="K-2")
        hh = create_household("Ives")
        _, p1 = create_patient(household_id=hh["id"], name="Q1", species="DOG", weight_kg=10)
        _, p2 = create_patient(household_id=hh["id"], name="Q2", species="DOG", weight_kg=10)
        _, p3 = create_patient(household_id=hh["id"], name="Q3", species="DOG", weight_kg=10)
        reserve_boarding(p1["id"], ken["id"], check_in_date="2026-07-11T00:00:00Z",
                         check_out_date="2026-07-13T00:00:00Z", nightly_rate_cents=5000)
        reserve_boarding(p2["id"], ken["id"], check_in_date="2026-07-12T00:00:00Z",
                         check_out_date="2026-07-14T00:00:00Z", nightly_rate_cents=5000)
        res = api.create_boarding_stay({
            "patient_id": p3["id"], "kennel_id": ken["id"],
            "check_in_date": "2026-07-12T00:00:00Z",
            "check_out_date": "2026-07-12T00:00:00Z",
            "nightly_rate_cents": 5000,
        }, RECEPTIONIST)
        validate_error(res, "ERR_KENNEL_AT_CAPACITY", expected_status=409)

    def test_stay_up_to_capacity_allowed(self, api):
        """PRD 3.9: "the count of non-cancelled stays already covering that day in that
        kennel must remain at or below the kennel's `capacity`".

        Capacity 2; with one stay covering 2026-07-12, a second stay covering that day
        keeps the count at 2 (<= capacity) and is allowed.

        Design: Difficulty/resource_temporal_overlap/kennel_aggregate_capacity_overlap
        """
        ken = create_kennel(capacity=2, name="K-2b")
        hh = create_household("Ives2")
        _, p1 = create_patient(household_id=hh["id"], name="Q1", species="DOG", weight_kg=10)
        _, p2 = create_patient(household_id=hh["id"], name="Q2", species="DOG", weight_kg=10)
        reserve_boarding(p1["id"], ken["id"], check_in_date="2026-07-11T00:00:00Z",
                         check_out_date="2026-07-13T00:00:00Z", nightly_rate_cents=5000)
        res = api.create_boarding_stay({
            "patient_id": p2["id"], "kennel_id": ken["id"],
            "check_in_date": "2026-07-12T00:00:00Z",
            "check_out_date": "2026-07-12T00:00:00Z",
            "nightly_rate_cents": 5000,
        }, RECEPTIONIST)
        validate_success(res, 201)
