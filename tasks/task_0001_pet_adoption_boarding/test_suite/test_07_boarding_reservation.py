"""Boarding reservation lifecycle + capacity accounting + quoting.
PRD §3.6, §3.7."""
import pytest
from datetime import datetime, timezone, timedelta
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_boarding_reservation, assert_shelter_slot_invariant,
    create_reservation_payload,
    create_shelter, create_animal, fully_vaccinate_animal, create_adopter,
    create_boardable_animal, setup_reservation_scenario,
    fill_shelter_to_capacity, create_reservation,
    future_iso, past_iso,
    PEAK_UTILIZATION, PEAK_SURCHARGE, MEDICAL_MULTIPLIER, BEHAVIORAL_MULTIPLIER,
)


class TestReservationCreate:
    def test_create_reservation_succeeds(self):
        """PRD §3.6: "POST /shelters/{sid}/boarding-reservations"."""
        ctx = setup_reservation_scenario()
        assert ctx["reservation"]["status"] == "RESERVED"
        assert ctx["reservation"]["nights"] == 3
        assert_boarding_reservation(ctx["reservation"])

    def test_create_reservation_increments_reserved_slots(self):
        """PRD §3.6: "atomically increments the shelter's reserved_slots"."""
        ctx = setup_reservation_scenario(boarding_capacity=5)
        resp = api_client.get_shelter(ctx["shelter"]["id"], TEST_USERS["adopter_headers"])
        shelter = validate_success(resp)
        assert shelter["reserved_slots"] == 1
        assert shelter["available_slots"] == 4
        assert_shelter_slot_invariant(shelter)

    def test_create_reservation_animal_not_boardable_when_adopted(self):
        """PRD §3.6: "must not currently be in ADOPTED or RETIRED status
        (else ERR_ANIMAL_NOT_BOARDABLE)"."""
        # Create an adopted animal
        from test_helpers.fixtures import setup_finalizable_application
        ctx = setup_finalizable_application()
        # Finalize it to make animal ADOPTED
        from test_helpers import make_approver_headers
        api_client.finalize_application(
            ctx["application"]["id"], make_approver_headers("approver-01"))
        # Now attempt a boarding reservation
        adopter = create_adopter()
        payload = create_reservation_payload(
            animal_id=ctx["animal"]["id"], owner_id=adopter["id"], nights=2,
        )
        resp = api_client.create_reservation(
            ctx["shelter"]["id"], payload,
            TEST_USERS["boarding_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_BOARDABLE.value)

    def test_create_reservation_vaccination_non_compliant(self):
        """PRD §3.6: "vaccination compliance must hold"."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"], species="DOG")  # no vaccines
        adopter = create_adopter()
        payload = create_reservation_payload(
            animal_id=animal["id"], owner_id=adopter["id"], nights=2,
        )
        resp = api_client.create_reservation(
            shelter["id"], payload, TEST_USERS["boarding_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_VACCINATION_NON_COMPLIANT.value)

    def test_nights_less_than_one_rejected(self):
        """PRD §3.6: "a request that resolves to fewer than one night is rejected as
        ERR_INVALID_REQUEST"."""
        shelter = create_shelter()
        animal = create_boardable_animal(shelter["id"])
        adopter = create_adopter()
        now = datetime.now(timezone.utc) + timedelta(days=1)
        payload = create_reservation_payload(
            animal_id=animal["id"], owner_id=adopter["id"],
            check_in_date=now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            check_out_date=now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )
        resp = api_client.create_reservation(
            shelter["id"], payload, TEST_USERS["boarding_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_shelter_at_capacity(self):
        """PRD §3.7: "When two reservations race for the last open slot, exactly one
        succeeds and the loser receives ERR_SHELTER_AT_CAPACITY"."""
        shelter = create_shelter(boarding_capacity=2)
        # fill to capacity
        fill_shelter_to_capacity(shelter["id"], leaving_free=0)
        # attempt another
        new_animal = create_boardable_animal(shelter["id"])
        adopter = create_adopter()
        payload = create_reservation_payload(
            animal_id=new_animal["id"], owner_id=adopter["id"], nights=2,
        )
        resp = api_client.create_reservation(
            shelter["id"], payload, TEST_USERS["boarding_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_SHELTER_AT_CAPACITY.value)


class TestBoardingQuote:
    def test_quote_base_computation(self):
        """PRD §3.6: "The baseline is the shelter's boarding_rate_per_night multiplied
        by nights" — no multiplier, below peak threshold."""
        # capacity 10, rate 5000, nights 3, NONE special care
        # peak util = 1/10 = 0.1 < 0.8, so no surcharge
        ctx = setup_reservation_scenario(boarding_capacity=10,
                                         boarding_rate_per_night=5000,
                                         special_care_level="NONE",
                                         nights=3)
        assert ctx["reservation"]["quoted_total"] == 15000

    def test_quote_medical_multiplier(self):
        """PRD §3.6: "1.5x when special_care_level == MEDICAL"."""
        ctx = setup_reservation_scenario(boarding_capacity=10,
                                         boarding_rate_per_night=5000,
                                         special_care_level="MEDICAL",
                                         nights=3)
        # 5000*3 = 15000; 15000*1.5 = 22500; no peak surcharge
        assert ctx["reservation"]["quoted_total"] == 22500

    def test_quote_behavioral_multiplier(self):
        """PRD §3.6: "1.25x when special_care_level == BEHAVIORAL"."""
        ctx = setup_reservation_scenario(boarding_capacity=10,
                                         boarding_rate_per_night=5000,
                                         special_care_level="BEHAVIORAL",
                                         nights=4)
        # 5000*4 = 20000; 20000*1.25 = 25000
        assert ctx["reservation"]["quoted_total"] == 25000

    def test_quote_peak_surcharge_applied(self):
        """PRD §3.6: "peak surcharge of ten percent of the baseline is added when ...
        utilization ... stands at eighty percent or higher"."""
        # capacity 5 -> need 4 RESERVED before creating test to push at threshold:
        # 4/5 = 0.8 meets threshold
        shelter = create_shelter(boarding_capacity=5, boarding_rate_per_night=5000)
        # Create 4 reservations to reach utilization of exactly 0.8
        fill_shelter_to_capacity(shelter["id"], leaving_free=1)
        # Now create the 5th (target) — at time of reservation util = 4/5 = 0.8
        animal = create_boardable_animal(shelter["id"])
        adopter = create_adopter()
        reservation = create_reservation(shelter["id"], animal["id"],
                                         adopter["id"], nights=2)
        # base = 5000 * 2 = 10000; surcharge = 0.1 * 10000 = 1000; total = 11000
        assert reservation["quoted_total"] == 11000

    def test_quote_no_peak_below_threshold(self):
        """PRD §3.6: peak surcharge only when utilization >= 0.8."""
        # capacity 10, no prior reservations, util 0.0 < 0.8
        ctx = setup_reservation_scenario(boarding_capacity=10,
                                         boarding_rate_per_night=5000,
                                         special_care_level="NONE", nights=2)
        assert ctx["reservation"]["quoted_total"] == 10000


class TestCheckIn:
    def test_check_in_too_early(self):
        """PRD §3.6: "attempts sooner return ERR_TOO_EARLY_FOR_CHECKIN"."""
        shelter = create_shelter(boarding_capacity=5)
        animal = create_boardable_animal(shelter["id"])
        adopter = create_adopter()
        # check-in far in future
        far = datetime.now(timezone.utc) + timedelta(days=30)
        payload = create_reservation_payload(
            animal_id=animal["id"], owner_id=adopter["id"],
            check_in_date=far.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            check_out_date=(far + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )
        reservation = get_success_data(
            api_client.create_reservation(shelter["id"], payload,
                                          TEST_USERS["boarding_coordinator_headers"])
        )
        resp = api_client.check_in_reservation(
            shelter["id"], reservation["id"],
            TEST_USERS["boarding_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_TOO_EARLY_FOR_CHECKIN.value)

    def test_check_in_moves_animal_to_boarding_only(self):
        """PRD §3.6: "if the animal was AVAILABLE, its status moves to BOARDING_ONLY"."""
        # Need check-in near now. Reservation with check_in_date in the past a bit.
        shelter = create_shelter(boarding_capacity=5)
        animal = create_boardable_animal(shelter["id"])
        adopter = create_adopter()
        now = datetime.now(timezone.utc)
        payload = create_reservation_payload(
            animal_id=animal["id"], owner_id=adopter["id"],
            check_in_date=(now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            check_out_date=(now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )
        reservation = get_success_data(
            api_client.create_reservation(shelter["id"], payload,
                                          TEST_USERS["boarding_coordinator_headers"])
        )
        resp = api_client.check_in_reservation(
            shelter["id"], reservation["id"],
            TEST_USERS["boarding_coordinator_headers"])
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"
        # Animal should be BOARDING_ONLY
        a_resp = api_client.get_animal(shelter["id"], animal["id"],
                                       TEST_USERS["adopter_headers"])
        a = validate_success(a_resp)
        assert a["status"] == "BOARDING_ONLY"


class TestCheckOut:
    def test_check_out_decrements_reserved_slots(self):
        """PRD §3.6: check-out "decrements reserved_slots"."""
        shelter = create_shelter(boarding_capacity=3)
        animal = create_boardable_animal(shelter["id"])
        adopter = create_adopter()
        now = datetime.now(timezone.utc)
        payload = create_reservation_payload(
            animal_id=animal["id"], owner_id=adopter["id"],
            check_in_date=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            check_out_date=(now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )
        reservation = get_success_data(
            api_client.create_reservation(shelter["id"], payload,
                                          TEST_USERS["boarding_coordinator_headers"])
        )
        api_client.check_in_reservation(
            shelter["id"], reservation["id"],
            TEST_USERS["boarding_coordinator_headers"])
        resp = api_client.check_out_reservation(
            shelter["id"], reservation["id"],
            TEST_USERS["boarding_coordinator_headers"])
        data = validate_success(resp)
        assert data["status"] == "COMPLETED"
        # final_total set
        assert data.get("final_total") is not None
        # Shelter slot accounting
        s = get_success_data(api_client.get_shelter(shelter["id"], TEST_USERS["adopter_headers"]))
        assert s["reserved_slots"] == 0

    def test_check_out_releases_boarding_only_animal(self):
        """PRD §3.6: "moves the animal back to AVAILABLE if the completed reservation
        was the sole reason for its BOARDING_ONLY status"."""
        shelter = create_shelter(boarding_capacity=3)
        animal = create_boardable_animal(shelter["id"])
        adopter = create_adopter()
        now = datetime.now(timezone.utc)
        payload = create_reservation_payload(
            animal_id=animal["id"], owner_id=adopter["id"],
            check_in_date=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            check_out_date=(now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )
        reservation = get_success_data(
            api_client.create_reservation(shelter["id"], payload,
                                          TEST_USERS["boarding_coordinator_headers"])
        )
        api_client.check_in_reservation(
            shelter["id"], reservation["id"],
            TEST_USERS["boarding_coordinator_headers"])
        api_client.check_out_reservation(
            shelter["id"], reservation["id"],
            TEST_USERS["boarding_coordinator_headers"])
        a = get_success_data(api_client.get_animal(
            shelter["id"], animal["id"], TEST_USERS["adopter_headers"]))
        assert a["status"] == "AVAILABLE"


class TestCancel:
    def test_cancel_decrements_reserved_slots(self):
        """PRD §3.6: "cancellation decrements reserved_slots"."""
        ctx = setup_reservation_scenario(boarding_capacity=4)
        resp = api_client.cancel_reservation(
            ctx["shelter"]["id"], ctx["reservation"]["id"],
            TEST_USERS["boarding_coordinator_headers"])
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"
        s = get_success_data(api_client.get_shelter(
            ctx["shelter"]["id"], TEST_USERS["adopter_headers"]))
        assert s["reserved_slots"] == 0


class TestSettle:
    def test_settle_requires_completed_settlement(self):
        """PRD §3.6: "requires a COMPLETED settlement for (BOARDING, reservation_id)
        (else ERR_FEE_NOT_SETTLED)"."""
        shelter = create_shelter(boarding_capacity=3)
        animal = create_boardable_animal(shelter["id"])
        adopter = create_adopter()
        now = datetime.now(timezone.utc)
        payload = create_reservation_payload(
            animal_id=animal["id"], owner_id=adopter["id"],
            check_in_date=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            check_out_date=(now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )
        reservation = get_success_data(
            api_client.create_reservation(shelter["id"], payload,
                                          TEST_USERS["boarding_coordinator_headers"])
        )
        api_client.check_in_reservation(
            shelter["id"], reservation["id"],
            TEST_USERS["boarding_coordinator_headers"])
        api_client.check_out_reservation(
            shelter["id"], reservation["id"],
            TEST_USERS["boarding_coordinator_headers"])
        # Attempt settle without a fee settlement
        resp = api_client.settle_reservation(
            shelter["id"], reservation["id"],
            TEST_USERS["finance_officer_headers"])
        validate_error(resp, ApiErrorId.ERR_FEE_NOT_SETTLED.value)
