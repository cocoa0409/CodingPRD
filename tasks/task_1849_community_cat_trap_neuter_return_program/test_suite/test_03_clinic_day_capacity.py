"""Clinic day capacity: kitten-season surge branching and full-day boundary."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_coordinator_headers, make_clinic_staff_headers,
    setup_caretaker_with_colony, create_cat, create_partner_clinic,
    create_clinic_day, list_slots, get_day, book_appointment,
    create_appointment_payload,
)


class TestKittenSeasonBranching:
    """Difficulty/combinatorial_formula/clinic_capacity_kitten_season_branching"""

    def test_kitten_admitted_into_surge_slot_in_season(self, api):
        """PRD §2.7: "During kitten season — the months of March through July — a
        booking for a kitten (a cat whose `approximate_age_months` is under six,
        surfaced as the derived `is_kitten` flag) is admitted while `booked_count`
        is strictly less than the sum of `base_capacity` and `surge_capacity`."

        Design: Difficulty/combinatorial_formula/clinic_capacity_kitten_season_branching
        """
        ct, cth, col = setup_caretaker_with_colony()
        adult = create_cat(col, intake_tag="AD1", approximate_age_months=24)
        kitten = create_cat(col, intake_tag="KT1", sex="FEMALE", approximate_age_months=3)
        clinic = create_partner_clinic(name="MarshVet")
        day = create_clinic_day(clinic, service_date="2027-04-15T00:00:00Z",
                                base_capacity=1, surge_capacity=1)
        slots = list_slots(day)

        book_appointment(adult, slots[0], day["id"], cth,
                         trap_date="2027-04-14T00:00:00Z")

        resp = api.create_appointment(
            create_appointment_payload(
                kitten["id"], slots[1]["id"], get_day(day["id"])["version"],
                trap_date="2027-04-14T00:00:00Z"),
            cth)
        appt = validate_success(resp, expected_status=201)
        assert appt["status"] == "SCHEDULED"
        day_after = get_day(day["id"])
        assert day_after["booked_count"] == 2, \
            f"booked_count must reach base+surge (2), got {day_after['booked_count']}"

    def test_adult_in_season_capped_at_base_capacity(self, api):
        """PRD §2.7: "In every other case — an adult cat in any month, or any cat
        outside the season — the booking is admitted only while `booked_count` is
        strictly less than `base_capacity`; surge slots are unreachable for adult
        bookings."

        Design: Difficulty/combinatorial_formula/clinic_capacity_kitten_season_branching
        """
        ct, cth, col = setup_caretaker_with_colony()
        a1 = create_cat(col, intake_tag="SA1", approximate_age_months=24)
        a2 = create_cat(col, intake_tag="SA2", approximate_age_months=30)
        clinic = create_partner_clinic(name="SeasonVet")
        day = create_clinic_day(clinic, service_date="2027-04-15T00:00:00Z",
                                base_capacity=1, surge_capacity=1)
        slots = list_slots(day)
        book_appointment(a1, slots[0], day["id"], cth,
                         trap_date="2027-04-14T00:00:00Z")

        resp = api.create_appointment(
            create_appointment_payload(
                a2["id"], slots[1]["id"], get_day(day["id"])["version"],
                trap_date="2027-04-14T00:00:00Z"),
            cth)
        validate_error(resp, ApiErrorId.ERR_CLINIC_DAY_FULL, expected_status=409)


class TestFullAtExactBaseCapacity:
    """Difficulty/boundary_precision/clinic_day_full_at_exact_base_capacity"""

    def test_booking_at_base_minus_one_admitted(self, api):
        """PRD §2.7: "The comparison is a strict less-than on integers: a booking
        that would bring `booked_count` from one below the applicable limit up to
        that limit succeeds, while a booking made when `booked_count` already
        equals the applicable limit is rejected with `ERR_CLINIC_DAY_FULL` (HTTP
        409) — even if surge slots sit unused on the day."

        Design: Difficulty/boundary_precision_check/clinic_day_full_at_exact_base_capacity
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="E1", approximate_age_months=24)
        clinic = create_partner_clinic(name="EdgeVet")
        day = create_clinic_day(clinic, service_date="2026-08-25T00:00:00Z",
                                base_capacity=1, surge_capacity=1)
        slots = list_slots(day)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   trap_date="2026-08-24T00:00:00Z")
        assert appt["status"] == "SCHEDULED"
        assert get_day(day["id"])["booked_count"] == 1

    def test_booking_at_base_rejected_even_with_surge_open(self, api):
        """PRD §2.7: "a booking made when `booked_count` already equals the
        applicable limit is rejected with `ERR_CLINIC_DAY_FULL` (HTTP 409) — even
        if surge slots sit unused on the day."

        Design: Difficulty/boundary_precision_check/clinic_day_full_at_exact_base_capacity
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat1 = create_cat(col, intake_tag="E1", approximate_age_months=24)
        cat2 = create_cat(col, intake_tag="E2", sex="FEMALE", approximate_age_months=24)
        clinic = create_partner_clinic(name="EdgeVet")
        day = create_clinic_day(clinic, service_date="2026-08-25T00:00:00Z",
                                base_capacity=1, surge_capacity=1)
        slots = list_slots(day)
        book_appointment(cat1, slots[0], day["id"], cth,
                         trap_date="2026-08-24T00:00:00Z")

        resp = api.create_appointment(
            create_appointment_payload(
                cat2["id"], slots[1]["id"], get_day(day["id"])["version"],
                trap_date="2026-08-24T00:00:00Z"),
            cth)
        validate_error(resp, ApiErrorId.ERR_CLINIC_DAY_FULL, expected_status=409)


class TestClinicDayCreation:
    def test_clinic_day_creation_synthesizes_slots(self, api):
        """PRD §3.2: "On creation the server materializes the day's full slot
        inventory — `base_capacity` plus `surge_capacity` `ClinicSlot` rows, each
        recorded against the day's `clinic_day_id`, each standing `OPEN`, and each
        assigned a sequential `slot_index` starting at 1 — and the day begins
        `SCHEDULED` with `booked_count` at 0."

        Design: Corner/endpoints/clinic_day_creation_synthesizes_slots
        """
        clinic = create_partner_clinic(name="SlotVet", voucher_reimbursement_cents=5000)
        resp = api.create_clinic_day(
            {"clinic_id": clinic["id"], "service_date": "2026-09-01T00:00:00Z",
             "base_capacity": 2, "surge_capacity": 1},
            make_clinic_staff_headers())
        day = validate_success(resp, expected_status=201)
        assert day["status"] == "SCHEDULED"
        assert day["booked_count"] == 0
        slots = list_slots(day)
        assert len(slots) == 3, f"expected 3 slots, got {len(slots)}"
        assert sorted(s["slot_index"] for s in slots) == [1, 2, 3]
        assert all(s["status"] == "OPEN" for s in slots)
        assert all(s["clinic_day_id"] == day["id"] for s in slots)


class TestClinicDayCancel:
    def test_clinic_day_cancel_with_bookings_rejected(self, api):
        """PRD §3.2: "Cancelling a day is permitted only while nothing is booked:
        with `booked_count` above zero the cancellation is rejected with
        `ERR_DAY_HAS_BOOKINGS` (HTTP 409); otherwise every `OPEN` slot becomes
        `RELEASED` and the day becomes `CANCELLED`."

        Design: Corner/validations/clinic_day_cancel_with_bookings_rejected
        """
        ct, cth, col = setup_caretaker_with_colony()
        cat = create_cat(col, intake_tag="D1", approximate_age_months=24)
        clinic = create_partner_clinic(name="DayVet", voucher_reimbursement_cents=5000)
        day = create_clinic_day(clinic, service_date="2026-08-23T00:00:00Z",
                                base_capacity=1, surge_capacity=0)
        slots = list_slots(day)
        appt, _ = book_appointment(cat, slots[0], day["id"], cth,
                                   trap_date="2026-08-22T00:00:00Z")

        sh = make_clinic_staff_headers()
        blocked = api.cancel_clinic_day(day["id"], sh)
        validate_error(blocked, ApiErrorId.ERR_DAY_HAS_BOOKINGS, expected_status=409)

        get_success_data(api.cancel_appointment(appt["id"], cth))
        ok = api.cancel_clinic_day(day["id"], sh)
        data = validate_success(ok, expected_status=200)
        assert data["status"] == "CANCELLED"
