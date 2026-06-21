"""Entity creation, computed fields, immutability, listing, and basic validation
of the catalog/owner/pet surface.

Corner queue: entities.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
)
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_pet, assert_vaccination_record
from test_helpers.constants import NONEXISTENT_UUID


class TestPetCreation:
    def test_create_pet_returns_201_with_computed_defaults(self, api):
        """PRD §3.2: "At creation the server sets muzzle_required to true exactly
        when the supplied behavioral_flag is AGGRESSIVE (otherwise false), and sets
        vaccination_status to EXPIRED because no records exist yet."

        Design: Corner/entities/create_pet_returns_201_with_computed_fields
        """
        breed = fx.create_breed(base_service_minutes=60)
        customer = fx.create_customer(service_zip="10001")
        resp = api.create_pet({
            "customer_id": customer["id"], "breed_id": breed["id"],
            "name": "Rex", "weight_lbs": 30,
        }, fx.make_customer_headers(customer["id"]))
        data = validate_success(resp, 201)
        assert_pet(data)
        assert data["muzzle_required"] is False, data
        assert data["vaccination_status"] == "EXPIRED", data

    def test_aggressive_pet_muzzle_required_true(self, api):
        """PRD §3.2: "At creation the server sets muzzle_required to true exactly
        when the supplied behavioral_flag is AGGRESSIVE (otherwise false)."

        Design: Corner/entities/aggressive_pet_muzzle_required_true_on_create
        """
        breed = fx.create_breed(base_service_minutes=70, size_class="GIANT")
        customer = fx.create_customer(service_zip="10002")
        pet = fx.create_pet(customer["id"], breed["id"], name="Killer",
                            weight_lbs=90, behavioral_flag="AGGRESSIVE")
        assert pet["muzzle_required"] is True, pet

    def test_patch_behavioral_flag_reconciles_muzzle(self, api):
        """PRD §3.2: "when behavioral_flag is amended the server reconciles
        muzzle_required to match (true if and only if the new flag is AGGRESSIVE);
        each such amendment bumps the pet's version."

        Design: Corner/entities/patch_pet_behavioral_flag_reconciles_muzzle
        """
        breed = fx.create_breed(base_service_minutes=60, coat_type="DOUBLE", size_class="LARGE")
        customer = fx.create_customer(service_zip="10003")
        pet = fx.create_pet(customer["id"], breed["id"], name="Max",
                            weight_lbs=50, behavioral_flag="CALM")
        assert pet["muzzle_required"] is False, pet
        resp = api.patch_pet(pet["id"], {"behavioral_flag": "AGGRESSIVE"},
                             fx.make_customer_headers(customer["id"]))
        data = validate_success(resp, 200)
        assert data["muzzle_required"] is True, data

    def test_get_nonexistent_pet_404(self, api):
        """PRD §2.9: "The first identifier that does not resolve causes the request
        to be rejected with ERR_NOT_FOUND (HTTP 404)."

        Design: Corner/entities/get_nonexistent_pet_returns_not_found
        """
        resp = api.get_pet(NONEXISTENT_UUID, fx.ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_pet_missing_weight_invalid_request(self, api):
        """PRD §3.2: "the pet's name, and its weight_lbs which must be greater than
        zero."
        PRD §3.4 (ordering): "then body well-formedness."

        Design: Corner/entities/create_pet_missing_required_field_invalid_request
        """
        breed = fx.create_breed(base_service_minutes=55, coat_type="CURLY", size_class="MEDIUM")
        customer = fx.create_customer(service_zip="10004")
        resp = api.create_pet({
            "customer_id": customer["id"], "breed_id": breed["id"], "name": "NoWeight",
        }, fx.make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestCatalogValidation:
    def test_create_breed_invalid_coat_enum(self, api):
        """PRD §2.5: "A Breed carries a coat_type that is one of SMOOTH, DOUBLE,
        CURLY, WIRE, or HAIRLESS ... a request supplying any other value for an
        enumerated field is malformed."

        Design: Corner/entities/create_breed_invalid_coat_enum_invalid_request
        """
        resp = api.create_breed({
            "name": "Bad", "coat_type": "FLUFFY",
            "size_class": "MEDIUM", "base_service_minutes": 60,
        }, fx.ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestImmutabilityAndListing:
    def test_vaccination_record_has_no_version(self, api):
        """PRD §2.4: "a VaccinationRecord and an appointment-add-on link carry only
        an id and a created_at — they have neither an updated_at nor a version,
        because they are immutable once written."

        Design: Corner/entities/vaccination_record_immutable_no_version
        """
        breed = fx.create_breed(base_service_minutes=50)
        customer = fx.create_customer(service_zip="10005")
        pet = fx.create_pet(customer["id"], breed["id"], name="Vee", weight_lbs=40)
        fx.upload_rabies(pet["id"], customer["id"])
        resp = api.list_pet_vaccinations(pet["id"], fx.make_customer_headers(customer["id"]))
        data, _ = validate_paginated(resp)
        assert len(data) >= 1, data
        assert_vaccination_record(data[0])

    def test_list_customer_pets_paginated(self, api):
        """PRD §2.3: "Each list response surfaces the effective limit, the effective
        offset, the total_count of records matching the query before pagination, and
        a has_more boolean indicating whether further records remain beyond the
        returned page."

        Design: Corner/entities/list_customer_pets_paginated
        """
        breed = fx.create_breed(base_service_minutes=50)
        customer = fx.create_customer(service_zip="10006")
        ch = fx.make_customer_headers(customer["id"])
        fx.create_pet(customer["id"], breed["id"], name="P1", weight_lbs=20)
        fx.create_pet(customer["id"], breed["id"], name="P2", weight_lbs=25)
        resp = api.list_customer_pets(customer["id"], ch, params={"limit": 10, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, data
        assert meta["total_count"] == 2, meta
        assert meta["has_more"] is False, meta
