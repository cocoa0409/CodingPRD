"""Tests for BoardingMatch derivation (compatibility_score, boarding_zone).

Covers: PRD Section 3.5 (BoardingMatch details),
Table 3 (boarding_compatibility_scoring).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_boarding_match,
    create_boarding_reservation_payload,
    create_shelter, create_boarding_ready_animal, setup_fee_schedule,
    create_boarding_confirmed,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]


class TestBoardingZoneAssignment:
    """PRD 3.5 + Table 3: boarding_zone assigned by temperament and species."""

    def test_zone_isolation_for_aggressive(self):
        shelter = create_shelter()
        setup_fee_schedule(shelter["id"])
        animal = create_boarding_ready_animal(
            shelter_id=shelter["id"], species="DOG", temperament="AGGRESSIVE"
        )
        payload = create_boarding_reservation_payload(
            shelter["id"], animal["id"], check_in_days_from_now=1, duration_days=2,
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        match = get_success_data(api_client.get_boarding_match(res["boarding_match_id"], _manager))
        assert match["boarding_zone"] == "ISOLATION"

    def test_zone_active_for_energetic(self):
        shelter = create_shelter()
        setup_fee_schedule(shelter["id"])
        animal = create_boarding_ready_animal(
            shelter_id=shelter["id"], species="DOG", temperament="ENERGETIC"
        )
        payload = create_boarding_reservation_payload(
            shelter["id"], animal["id"], check_in_days_from_now=1, duration_days=2,
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        match = get_success_data(api_client.get_boarding_match(res["boarding_match_id"], _manager))
        assert match["boarding_zone"] == "ACTIVE"

    def test_zone_small_animal_for_cat(self):
        shelter = create_shelter()
        setup_fee_schedule(shelter["id"])
        animal = create_boarding_ready_animal(
            shelter_id=shelter["id"], species="CAT", temperament="CALM"
        )
        payload = create_boarding_reservation_payload(
            shelter["id"], animal["id"], check_in_days_from_now=1, duration_days=2,
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        match = get_success_data(api_client.get_boarding_match(res["boarding_match_id"], _manager))
        assert match["boarding_zone"] == "SMALL_ANIMAL"

    def test_zone_general_for_calm_dog(self):
        shelter = create_shelter()
        setup_fee_schedule(shelter["id"])
        animal = create_boarding_ready_animal(
            shelter_id=shelter["id"], species="DOG", temperament="CALM"
        )
        payload = create_boarding_reservation_payload(
            shelter["id"], animal["id"], check_in_days_from_now=1, duration_days=2,
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        match = get_success_data(api_client.get_boarding_match(res["boarding_match_id"], _manager))
        assert match["boarding_zone"] == "GENERAL"


class TestCompatibilityScoreBase:
    """PRD 3.5 + Table 3: compatibility_score starts at 100 for no concurrent boarders."""

    def test_base_score_100_empty_shelter(self):
        """First reservation at a shelter (no CHECKED_IN animals): score = 100, minus special-needs."""
        shelter = create_shelter()
        setup_fee_schedule(shelter["id"])
        animal = create_boarding_ready_animal(
            shelter_id=shelter["id"], species="DOG", temperament="CALM",
        )
        payload = create_boarding_reservation_payload(
            shelter["id"], animal["id"], check_in_days_from_now=1, duration_days=2,
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        match = get_success_data(api_client.get_boarding_match(res["boarding_match_id"], _manager))
        # No concurrent boarders; special_needs default [] => penalty 0 => 100
        assert match["compatibility_score"] == 100

    def test_special_needs_reduce_score(self):
        """Each special-need tag subtracts 5."""
        shelter = create_shelter()
        setup_fee_schedule(shelter["id"])
        animal = create_boarding_ready_animal(
            shelter_id=shelter["id"], species="DOG", temperament="CALM",
            special_needs=["MEDICATION_REQUIRED", "DIET_RESTRICTED"],
        )
        payload = create_boarding_reservation_payload(
            shelter["id"], animal["id"], check_in_days_from_now=1, duration_days=2,
        )
        res = get_success_data(api_client.create_boarding_reservation(payload, _case_worker))
        res = get_success_data(api_client.confirm_boarding_reservation(res["id"], _manager))
        match = get_success_data(api_client.get_boarding_match(res["boarding_match_id"], _manager))
        # 100 - 2*5 = 90 (no concurrent boarders)
        assert match["compatibility_score"] == 90


class TestBoardingMatchRetrieval:
    def test_get_boarding_match(self):
        shelter, animal, res, invoice, match = create_boarding_confirmed()
        resp = api_client.get_boarding_match(match["id"], _manager)
        data = validate_success(resp)
        assert_boarding_match(data)

    def test_get_boarding_match_not_found(self):
        resp = api_client.get_boarding_match(NON_EXISTENT_UUID, _manager)
        validate_error(resp, ApiErrorId.ERR_BOARDING_MATCH_NOT_FOUND)
