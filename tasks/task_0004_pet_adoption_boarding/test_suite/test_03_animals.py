"""Tests for Animal CRUD, state machine, and compliance gates.

Covers: PRD Section 3.2 (Animal Intake, Medical History, Availability),
Table 1 (Animal), Table 2 (Animal state machine), Table 4 priorities 8, 9.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_animal, assert_animal_invariants,
    create_animal_payload, create_vaccination_record_payload,
    create_compliance_hold_payload,
    create_shelter, create_animal_intake, create_available_animal,
    add_vaccinations_for_adoption,
)

_manager = TEST_USERS["manager_headers"]
_case_worker = TEST_USERS["case_worker_headers"]
_vet = TEST_USERS["vet_headers"]


class TestAnimalCreation:
    """PRD 3.2: CaseWorker registers a new animal in INTAKE status."""

    def test_create_animal_success(self):
        """Creating an animal returns an INTAKE entity with derived fields."""
        shelter = create_shelter()
        payload = create_animal_payload(shelter["id"], species="DOG", temperament="CALM")
        resp = api_client.create_animal(payload, _case_worker)
        data = validate_success(resp, 201)
        assert_animal(data)
        assert data["status"] == "INTAKE"
        assert data["species"] == "DOG"
        assert data["shelter_id"] == shelter["id"]
        assert data["vaccination_compliant"] is False  # No vaccinations yet
        assert data["active_hold_count"] == 0
        assert data["adoption_eligible"] is False
        assert "boarding_zone_hint" in data

    def test_create_animal_special_needs_default_empty(self):
        """special_needs defaults to empty array if omitted."""
        shelter = create_shelter()
        payload = create_animal_payload(shelter["id"])
        payload.pop("special_needs", None)
        resp = api_client.create_animal(payload, _case_worker)
        data = validate_success(resp, 201)
        assert data["special_needs"] == []

    def test_create_animal_shelter_not_found(self):
        """FK to non-existent shelter returns ERR_SHELTER_NOT_FOUND."""
        payload = create_animal_payload(NON_EXISTENT_UUID)
        resp = api_client.create_animal(payload, _case_worker)
        validate_error(resp, ApiErrorId.ERR_SHELTER_NOT_FOUND)

    def test_create_animal_negative_age(self):
        """age_months must be >= 0."""
        shelter = create_shelter()
        payload = create_animal_payload(shelter["id"], age_months=-1)
        resp = api_client.create_animal(payload, _case_worker)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_animal_zero_weight(self):
        """weight_kg must be > 0."""
        shelter = create_shelter()
        payload = create_animal_payload(shelter["id"], weight_kg=0)
        resp = api_client.create_animal(payload, _case_worker)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_animal_invalid_species(self):
        """species must be one of enum values."""
        shelter = create_shelter()
        payload = create_animal_payload(shelter["id"], species="DRAGON")
        resp = api_client.create_animal(payload, _case_worker)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAnimalRetrieval:
    def test_get_animal(self):
        animal = create_animal_intake()
        resp = api_client.get_animal(animal["id"], _manager)
        data = validate_success(resp)
        assert_animal(data)

    def test_get_animal_not_found(self):
        resp = api_client.get_animal(NON_EXISTENT_UUID, _manager)
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_FOUND)


class TestAnimalUpdate:
    """PRD 3.2: PATCH editable fields with OCC."""

    def test_patch_animal_recomputes_adoption_eligible(self):
        """After edit, adoption_eligible is recomputed."""
        animal = create_animal_intake()
        resp = api_client.update_animal(animal["id"], {"name": "NewName"}, _case_worker)
        data = validate_success(resp)
        assert data["name"] == "NewName"
        assert data["version"] > animal["version"]

    def test_patch_animal_version_conflict(self):
        """Stale version returns ERR_VERSION_CONFLICT (PRD 2.5)."""
        animal = create_animal_intake()
        v = animal["version"]
        # First update succeeds
        get_success_data(api_client.update_animal(
            animal["id"], {"name": "V1", "version": v}, _case_worker
        ))
        # Second with stale version fails
        resp = api_client.update_animal(
            animal["id"], {"name": "V2", "version": v}, _case_worker
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)

    def test_patch_animal_no_version_bypasses_check(self):
        """Omitting version skips concurrency check (PRD 2.5)."""
        animal = create_animal_intake()
        resp = api_client.update_animal(animal["id"], {"name": "NoVer"}, _case_worker)
        validate_success(resp)


class TestMakeAvailable:
    """PRD 3.2 + Table 2: Animal INTAKE -> AVAILABLE."""

    def test_make_available_success(self):
        """With all vaccinations and no hold, INTAKE -> AVAILABLE."""
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"], species="DOG")
        add_vaccinations_for_adoption(animal["id"], species="DOG")
        resp = api_client.make_animal_available(animal["id"], _case_worker)
        data = validate_success(resp)
        assert data["status"] == "AVAILABLE"
        assert data["vaccination_compliant"] is True
        assert data["adoption_eligible"] is True

    def test_make_available_without_vaccines_fails(self):
        """No vaccinations: ERR_VACCINATION_NOT_COMPLIANT."""
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"])
        resp = api_client.make_animal_available(animal["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_VACCINATION_NOT_COMPLIANT)

    def test_make_available_partial_vaccines_fails_dog(self):
        """DOG missing DHPP (has only RABIES) fails vaccination check."""
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"], species="DOG")
        get_success_data(api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "RABIES"), _vet
        ))
        resp = api_client.make_animal_available(animal["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_VACCINATION_NOT_COMPLIANT)

    def test_make_available_expired_vaccine_fails(self):
        """Vaccine with expiry_date in the past does NOT count as compliant."""
        from test_helpers import past_date
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"], species="DOG")
        # RABIES valid
        get_success_data(api_client.create_vaccination_record(
            create_vaccination_record_payload(animal["id"], "RABIES"), _vet
        ))
        # DHPP expired — expiry_date must be > administered but we'll schedule
        # administered 5 days ago, expiry 1 day ago.
        payload = create_vaccination_record_payload(
            animal["id"], "DHPP",
            administered_days_ago=5,
        )
        payload["expiry_date"] = past_date(days=1)
        get_success_data(api_client.create_vaccination_record(payload, _vet))
        resp = api_client.make_animal_available(animal["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_VACCINATION_NOT_COMPLIANT)

    def test_make_available_blocked_by_high_hold(self):
        """HIGH-severity ACTIVE hold blocks make-available."""
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"], species="DOG")
        add_vaccinations_for_adoption(animal["id"], species="DOG")
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="HIGH"), _vet
        ))
        resp = api_client.make_animal_available(animal["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_HOLD_ACTIVE)

    def test_make_available_blocked_by_critical_hold(self):
        """CRITICAL-severity hold also blocks make-available."""
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"], species="DOG")
        add_vaccinations_for_adoption(animal["id"], species="DOG")
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="CRITICAL"), _vet
        ))
        resp = api_client.make_animal_available(animal["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_HOLD_ACTIVE)

    def test_make_available_not_blocked_by_low_hold(self):
        """LOW-severity hold does NOT block make-available (only HIGH/CRITICAL do)."""
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"], species="DOG")
        add_vaccinations_for_adoption(animal["id"], species="DOG")
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="LOW"), _vet
        ))
        resp = api_client.make_animal_available(animal["id"], _case_worker)
        data = validate_success(resp)
        assert data["status"] == "AVAILABLE"

    def test_make_available_suspended_shelter(self):
        """Suspended shelter blocks make-available."""
        shelter = create_shelter()
        animal = create_animal_intake(shelter_id=shelter["id"], species="DOG")
        add_vaccinations_for_adoption(animal["id"], species="DOG")
        get_success_data(api_client.suspend_shelter(shelter["id"], _manager))
        resp = api_client.make_animal_available(animal["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_SHELTER_SUSPENDED)

    def test_make_available_wrong_state(self):
        """Already-AVAILABLE animal cannot be made-available again."""
        animal = create_available_animal()
        resp = api_client.make_animal_available(animal["id"], _case_worker)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAnimalAdoptionEligible:
    """PRD 3.2: adoption_eligible derived field invariants."""

    def test_adoption_eligible_requires_available_status(self):
        """INTAKE animal cannot be adoption_eligible."""
        animal = create_animal_intake()
        assert animal["adoption_eligible"] is False

    def test_adoption_eligible_requires_vaccination(self):
        """Animal without vaccinations is not adoption_eligible."""
        animal = create_animal_intake(species="DOG")
        assert animal["adoption_eligible"] is False

    def test_available_vaccinated_animal_is_eligible(self):
        """An AVAILABLE + vaccinated animal (no holds) is adoption_eligible."""
        animal = create_available_animal()
        assert_animal_invariants(animal)
        assert animal["adoption_eligible"] is True

    def test_hold_makes_animal_unavailable(self):
        """Creating HIGH hold on AVAILABLE animal pushes it to UNAVAILABLE."""
        animal = create_available_animal()
        get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="HIGH"), _vet
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["status"] == "UNAVAILABLE"
        assert refreshed["adoption_eligible"] is False

    def test_resolve_hold_returns_animal_to_available(self):
        """Resolving last HIGH/CRITICAL hold moves UNAVAILABLE -> AVAILABLE."""
        animal = create_available_animal()
        hold = get_success_data(api_client.create_compliance_hold(
            create_compliance_hold_payload(animal["id"], severity="HIGH"), _vet
        ))
        # Animal is now UNAVAILABLE
        get_success_data(api_client.resolve_compliance_hold(
            hold["id"], {"resolution_notes": "Clear"}, _manager
        ))
        refreshed = get_success_data(api_client.get_animal(animal["id"], _manager))
        assert refreshed["status"] == "AVAILABLE"
        assert refreshed["adoption_eligible"] is True
