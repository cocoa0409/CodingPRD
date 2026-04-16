"""Vaccination records and compliance — PRD §3.1, §3.2."""
import pytest
from datetime import datetime, timezone, timedelta
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    validate_success, validate_error,
    assert_vaccination,
    create_vaccination_payload,
    create_shelter, create_animal, fully_vaccinate_animal,
    past_iso, future_iso, now_iso,
    required_vaccines_for_species,
)


class TestVaccinationRecord:
    def test_veterinarian_can_record(self):
        """PRD §3.1: "available to both ShelterAdmin and Veterinarian"."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        resp = api_client.create_vaccination(
            shelter["id"], animal["id"], create_vaccination_payload(),
            TEST_USERS["veterinarian_headers"])
        data = validate_success(resp, expected_status=201)
        assert_vaccination(data)

    def test_adopter_cannot_record(self):
        """PRD §2.1 / §3.1: vaccinations are recorded by ShelterAdmin or Veterinarian."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        resp = api_client.create_vaccination(
            shelter["id"], animal["id"], create_vaccination_payload(),
            TEST_USERS["adopter_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_bad_vaccine_type_rejected(self):
        """PRD §2.7 + §3.1: vaccine_type one of enumerated set; else ERR_INVALID_REQUEST."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        resp = api_client.create_vaccination(
            shelter["id"], animal["id"],
            create_vaccination_payload(vaccine_type="LICORICE"),
            TEST_USERS["shelter_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestComplianceSummary:
    @pytest.mark.parametrize("species,required", [
        ("DOG", {"RABIES", "DISTEMPER", "PARVO", "BORDETELLA"}),
        ("CAT", {"RABIES", "DISTEMPER", "FELV"}),
        ("RABBIT", {"RABIES"}),
        ("OTHER", {"RABIES"}),
    ])
    def test_missing_vaccines_reported(self, species, required):
        """PRD §3.2: "a DOG must be current on RABIES, DISTEMPER, PARVO, and BORDETELLA;
        a CAT on RABIES, DISTEMPER, and FELV; a RABBIT on RABIES; OTHER species on RABIES alone"
        — for each required vaccine, if none exists, reason=VACCINE_MISSING."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"], species=species)
        resp = api_client.get_compliance(shelter["id"], animal["id"],
                                         TEST_USERS["adopter_headers"])
        data = validate_success(resp)
        assert data["status"] == "NON_COMPLIANT"
        assert set(data["missing"]) == required

    def test_fully_vaccinated_is_compliant(self):
        """PRD §3.2: all required vaccines with unexpired expires_date → COMPLIANT."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"], species="DOG")
        fully_vaccinate_animal(shelter["id"], animal["id"], species="DOG")
        resp = api_client.get_compliance(shelter["id"], animal["id"],
                                         TEST_USERS["adopter_headers"])
        data = validate_success(resp)
        assert data["status"] == "COMPLIANT"

    def test_expired_vaccine_is_non_compliant(self):
        """PRD §3.2: "if one does exist but its expires_date is less than or equal to
        the current instant, the reason is VACCINE_EXPIRED.\""""
        shelter = create_shelter()
        animal = create_animal(shelter["id"], species="RABBIT")
        api_client.create_vaccination(
            shelter["id"], animal["id"],
            create_vaccination_payload(
                vaccine_type="RABIES",
                administered_date=past_iso(400),
                expires_date=past_iso(1),  # expired
            ),
            TEST_USERS["shelter_admin_headers"],
        )
        resp = api_client.get_compliance(shelter["id"], animal["id"],
                                         TEST_USERS["adopter_headers"])
        data = validate_success(resp)
        assert data["status"] == "NON_COMPLIANT"
        assert "RABIES" in data["expired"]

    def test_latest_record_wins(self):
        """PRD §3.1: "the latest record per vaccine_type ... is the authoritative statement
        of coverage"."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"], species="RABBIT")
        # first record: expired
        api_client.create_vaccination(
            shelter["id"], animal["id"],
            create_vaccination_payload(
                vaccine_type="RABIES",
                administered_date=past_iso(400),
                expires_date=past_iso(1),
            ),
            TEST_USERS["shelter_admin_headers"],
        )
        # second record: current, administered more recently
        api_client.create_vaccination(
            shelter["id"], animal["id"],
            create_vaccination_payload(
                vaccine_type="RABIES",
                administered_date=past_iso(1),
                expires_date=future_iso(365),
            ),
            TEST_USERS["shelter_admin_headers"],
        )
        resp = api_client.get_compliance(shelter["id"], animal["id"],
                                         TEST_USERS["adopter_headers"])
        data = validate_success(resp)
        assert data["status"] == "COMPLIANT"

    def test_list_vaccinations(self):
        """PRD §3.1: GET /shelters/{sid}/animals/{aid}/vaccinations lists records."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"], species="DOG")
        fully_vaccinate_animal(shelter["id"], animal["id"], species="DOG")
        from test_helpers import validate_paginated
        resp = api_client.list_vaccinations(shelter["id"], animal["id"],
                                            TEST_USERS["adopter_headers"])
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 4

    def test_vaccinations_are_append_only(self):
        """PRD §2.9 / Table 1 note: "VaccinationRecord is append-only — it is never
        updated and never deleted." — multiple records for same vaccine_type allowed."""
        shelter = create_shelter()
        animal = create_animal(shelter["id"])
        api_client.create_vaccination(
            shelter["id"], animal["id"],
            create_vaccination_payload(vaccine_type="RABIES"),
            TEST_USERS["shelter_admin_headers"])
        # second one with same vaccine_type must succeed (not replace)
        resp = api_client.create_vaccination(
            shelter["id"], animal["id"],
            create_vaccination_payload(vaccine_type="RABIES", lot_number="LOT-B-0002"),
            TEST_USERS["shelter_admin_headers"])
        validate_success(resp, expected_status=201)
        from test_helpers import validate_paginated
        resp2 = api_client.list_vaccinations(shelter["id"], animal["id"],
                                             TEST_USERS["adopter_headers"],
                                             params={"vaccine_type": "RABIES"})
        data, meta = validate_paginated(resp2)
        assert meta["total_count"] == 2
