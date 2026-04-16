"""
Tests for ComplianceHold creation, resolution, and cascading effects on animals and shelter.
Claims from Tables 1, 2, 3 (shelter_compliance_score), 5, 6.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_compliance_hold,
    create_compliance_hold_payload,
    create_resolve_hold_payload,
    create_shelter,
    create_available_animal,
    create_animal_in_shelter,
    vaccinate_animal,
    make_animal_available,
    create_hold_on_animal,
    resolve_hold,
    create_boarding_reservation,
    confirm_boarding,
    check_in_boarding,
    create_shelter_with_fee_schedules,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    HOLD_PENALTY_POINTS,
)


class TestComplianceHoldCreation:
    """POST /compliance-holds."""

    def test_create_hold_success(self, api, vet_headers):
        """Create compliance hold -> 201 + ACTIVE status."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        payload = create_compliance_hold_payload(animal["id"], severity="MEDIUM")
        res = api.create_compliance_hold(payload, vet_headers)
        hold = validate_success(res, 201)
        assert_compliance_hold(hold)
        assert hold["status"] == "ACTIVE"
        assert hold["animal_id"] == animal["id"]
        assert hold["severity"] == "MEDIUM"

    def test_create_hold_nonexistent_animal(self, api, vet_headers):
        """FK to non-existent animal -> ERR_ANIMAL_NOT_FOUND."""
        payload = create_compliance_hold_payload(NON_EXISTENT_UUID)
        res = api.create_compliance_hold(payload, vet_headers)
        validate_error(res, ApiErrorId.ERR_ANIMAL_NOT_FOUND)

    def test_get_nonexistent_hold(self, api, vet_headers):
        """ERR_HOLD_NOT_FOUND."""
        res = api.get_compliance_hold(NON_EXISTENT_UUID, vet_headers)
        validate_error(res, ApiErrorId.ERR_HOLD_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", [
        "animal_id", "hold_type", "reason", "severity",
    ])
    def test_create_hold_missing_field(self, api, vet_headers, missing_field):
        """Missing required field -> ERR_INVALID_REQUEST."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        payload = create_compliance_hold_payload(animal["id"])
        del payload[missing_field]
        res = api.create_compliance_hold(payload, vet_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_list_holds_with_filters(self, api, vet_headers):
        """GET /compliance-holds supports filters."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        create_hold_on_animal(animal["id"], severity="HIGH")

        data, meta = validate_paginated(
            api.list_compliance_holds(vet_headers, params={"animal_id": animal["id"]})
        )
        assert meta["total_count"] >= 1


class TestHighCriticalHoldCascade:
    """Table 2: HIGH/CRITICAL hold makes animal UNAVAILABLE."""

    def test_high_hold_makes_animal_unavailable(self, api, vet_headers, caseworker_headers):
        """Creating a HIGH hold on AVAILABLE animal -> animal UNAVAILABLE."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        assert animal["status"] == "AVAILABLE"

        create_hold_on_animal(animal["id"], severity="HIGH")

        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "UNAVAILABLE"
        assert animal_after["adoption_eligible"] is False

    def test_critical_hold_makes_animal_unavailable(self, api, vet_headers, caseworker_headers):
        """Creating a CRITICAL hold on AVAILABLE animal -> animal UNAVAILABLE."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        create_hold_on_animal(animal["id"], severity="CRITICAL")

        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "UNAVAILABLE"

    def test_low_hold_does_not_change_status(self, api, vet_headers, caseworker_headers):
        """LOW hold -> animal remains AVAILABLE."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        create_hold_on_animal(animal["id"], severity="LOW")

        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "AVAILABLE"

    def test_medium_hold_does_not_change_status(self, api, vet_headers, caseworker_headers):
        """MEDIUM hold -> animal remains AVAILABLE."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        create_hold_on_animal(animal["id"], severity="MEDIUM")

        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "AVAILABLE"

    def test_hold_on_boarding_animal_stays_in_care(self, api, caseworker_headers, manager_headers):
        """HIGH hold on BOARDING animal -> UNAVAILABLE but reservation not cancelled."""
        shelter = create_shelter_with_fee_schedules()
        animal = create_available_animal(shelter["id"], include_bordetella=True)
        reservation = create_boarding_reservation(shelter["id"], animal["id"])
        confirm_boarding(reservation["id"])
        check_in_boarding(reservation["id"])

        animal_state = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_state["status"] == "BOARDING"

        create_hold_on_animal(animal["id"], severity="HIGH")

        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "UNAVAILABLE"

        # Reservation should NOT be cancelled
        res_after = validate_success(
            api.get_boarding_reservation(reservation["id"], caseworker_headers), 200,
        )
        assert res_after["status"] == "CHECKED_IN"


class TestComplianceHoldResolution:
    """POST /compliance-holds/{id}/resolve and cascading effects."""

    def test_resolve_hold_success(self, api, manager_headers):
        """Resolve hold -> RESOLVED status."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        hold = create_hold_on_animal(animal["id"], severity="HIGH")

        payload = create_resolve_hold_payload(resolution_notes="Cleared by vet")
        res = api.resolve_compliance_hold(hold["id"], payload, manager_headers)
        resolved = validate_success(res, 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_by"] is not None
        assert resolved["resolution_notes"] == "Cleared by vet"

    def test_resolve_restores_animal_to_available(self, api, manager_headers, caseworker_headers):
        """Resolving all HIGH/CRITICAL holds -> animal reverts to AVAILABLE."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        hold = create_hold_on_animal(animal["id"], severity="HIGH")

        animal_state = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_state["status"] == "UNAVAILABLE"

        resolve_hold(hold["id"])

        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "AVAILABLE"
        assert animal_after["adoption_eligible"] is True

    def test_resolve_one_of_two_holds_stays_unavailable(self, api, manager_headers, caseworker_headers):
        """Resolving one of two HIGH holds -> animal still UNAVAILABLE."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        hold1 = create_hold_on_animal(animal["id"], severity="HIGH")
        hold2 = create_hold_on_animal(
            animal["id"], severity="CRITICAL", hold_type="QUARANTINE",
        )

        resolve_hold(hold1["id"])

        animal_after = validate_success(api.get_animal(animal["id"], caseworker_headers), 200)
        assert animal_after["status"] == "UNAVAILABLE"

    def test_resolve_requires_resolution_notes(self, api, manager_headers):
        """Resolve without resolution_notes -> ERR_INVALID_REQUEST."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        hold = create_hold_on_animal(animal["id"], severity="LOW")

        res = api.resolve_compliance_hold(hold["id"], {}, manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_resolve_already_resolved(self, api, manager_headers):
        """Resolving an already-RESOLVED hold -> ERR_INVALID_STATE."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        hold = create_hold_on_animal(animal["id"], severity="LOW")
        resolve_hold(hold["id"])

        res = api.resolve_compliance_hold(
            hold["id"], create_resolve_hold_payload(), manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestShelterComplianceScore:
    """Table 3: shelter_compliance_score aggregation calculation."""

    def test_compliance_score_all_compliant_no_holds(self, api, manager_headers):
        """All animals compliant, no holds -> score = 100."""
        shelter = create_shelter()
        create_available_animal(shelter["id"])
        create_available_animal(shelter["id"], name="Animal 2")

        shelter_data = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        assert shelter_data["compliance_score"] == pytest.approx(100, abs=0.01)

    def test_compliance_score_with_hold_penalty(self, api, manager_headers):
        """One active hold -> score reduced by HOLD_PENALTY_POINTS."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        create_hold_on_animal(animal["id"], severity="LOW")

        shelter_data = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        # 1 compliant animal out of 1, base=100, minus 5 (one hold) = 95
        assert shelter_data["compliance_score"] == pytest.approx(
            100 - HOLD_PENALTY_POINTS, abs=0.01,
        )

    def test_compliance_score_mixed_compliance(self, api, manager_headers, caseworker_headers):
        """Mix of compliant and non-compliant animals."""
        shelter = create_shelter()
        # Animal 1: compliant (available)
        create_available_animal(shelter["id"])
        # Animal 2: not compliant (no vaccinations, still in INTAKE)
        create_animal_in_shelter(shelter["id"], name="Unvaccinated")

        shelter_data = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        # 1 compliant out of 2 = 50%, no holds -> 50.00
        assert shelter_data["compliance_score"] == pytest.approx(50.0, abs=0.01)

    def test_compliance_score_no_animals(self, api, manager_headers):
        """Shelter with no non-adopted animals -> score = 100."""
        shelter = create_shelter()
        shelter_data = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        assert shelter_data["compliance_score"] == pytest.approx(100, abs=0.01)

    def test_compliance_score_recomputed_on_hold_resolution(self, api, manager_headers):
        """Resolving a hold -> compliance_score increases."""
        shelter = create_shelter()
        animal = create_available_animal(shelter["id"])
        hold = create_hold_on_animal(animal["id"], severity="LOW")

        before = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)
        resolve_hold(hold["id"])
        after = validate_success(api.get_shelter(shelter["id"], manager_headers), 200)

        assert after["compliance_score"] > before["compliance_score"]
