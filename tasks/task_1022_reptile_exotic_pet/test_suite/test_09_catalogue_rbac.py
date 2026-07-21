"""Catalogue CRUD, care-sheet, reverse-reachability listings, RBAC and pagination."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID, make_customer_headers,
    create_species_payload, create_feeder_batch_payload,
    create_species, intake_animal, create_customer, create_permit,
)

_SM = TEST_USERS["store_manager_headers"]
_SALES = TEST_USERS["sales_associate_headers"]
_VET = TEST_USERS["vet_tech_headers"]


class TestSpeciesCatalogue:
    def test_create_species_returns_stored_fields(self, api):
        """PRD §3.1: "a dedicated care-sheet view returns just the husbandry projection — `care_temp_low_c`, `care_temp_high_c`, `care_humidity_low_pct`, `care_humidity_high_pct`, `feed_interval_days`, and `care_feeder_type`."
        PRD §2.4: "version`: an integer that starts at 1 on creation"

        Design: Corner/entities/create_species_success
        """
        payload = create_species_payload(
            common_name="Ball Python", scientific_name="Python regius",
            min_quarantine_days=7, warranty_days=30, care_feeder_type="MOUSE_ADULT")
        data = validate_success(api.create_species(payload, headers=_SM), expected_status=201)
        assert data["care_feeder_type"] == "MOUSE_ADULT"
        assert data["version"] == 1

    def test_create_species_missing_required_field_returns_validation(self, api):
        """PRD §2.8: "Only then are body fields validated for presence, type, and legal enum values (`ERR_VALIDATION`)"

        Design: Corner/entities/species_create_missing_required_returns_validation
        """
        payload = {
            "common_name": "X", "scientific_name": "Y", "min_quarantine_days": 7,
            "care_temp_low_c": 20, "care_temp_high_c": 30, "care_humidity_low_pct": 40,
            "care_humidity_high_pct": 60, "feed_interval_days": 7, "care_feeder_type": "CRICKET",
        }  # warranty_days omitted
        resp = api.create_species(payload, headers=_SM)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_care_sheet_returns_husbandry_projection(self, api):
        """PRD §3.1: "a dedicated care-sheet view returns just the husbandry projection — `care_temp_low_c`, `care_temp_high_c`, `care_humidity_low_pct`, `care_humidity_high_pct`, `feed_interval_days`, and `care_feeder_type`."

        Design: Corner/entities/care_sheet_computed_read
        """
        species = create_species(api, common_name="Bearded Dragon",
                                 scientific_name="Pogona vitticeps", care_feeder_type="DUBIA",
                                 care_humidity_high_pct=40, min_quarantine_days=5, warranty_days=14)
        data = validate_success(api.get_care_sheet(species["id"], headers=_SALES))
        assert data["care_feeder_type"] == "DUBIA"
        assert data["care_humidity_high_pct"] == 40


class TestAnimalDefaultsAndNotFound:
    def test_animal_defaults_sex_unknown_and_status_intake(self, api):
        """PRD §3.2: "an optional `sex` (one of `MALE`, `FEMALE`, or `UNKNOWN`, defaulting to `UNKNOWN`)" "A freshly intaken animal has `health_status` of `HEALTHY` and `status` of `INTAKE"

        Design: Corner/entities/animal_defaults_applied
        """
        species = create_species(api, min_quarantine_days=0, warranty_days=30)
        animal = intake_animal(api, species["id"], list_price_cents=15000,
                               acquisition_cost_cents=5000)  # no sex supplied
        assert animal["sex"] == "UNKNOWN"
        assert animal["status"] == "INTAKE"

    def test_get_unknown_animal_returns_not_found(self, api):
        """PRD §2.8: "the existence of every resource referenced in the path or body is checked left-to-right; the first unresolved reference produces the most specific applicable not-found error (for example `ERR_SPECIES_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND" ")"

        Design: Corner/entities/animal_get_not_found_returns_404
        """
        resp = api.get_animal(NON_EXISTENT_UUID, headers=_SM)
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_FOUND.value)


class TestReverseReachabilityListings:
    def test_list_permits_by_customer(self, api):
        """PRD §3.3: "Permits and a customer's permit list are readable by the customer, a `SalesAssociate`, or a `StoreManager`."

        Design: Corner/endpoints/list_permits_by_customer_reverse_reachability
        """
        customer = create_customer(api, email="rr-permits@x.com")
        permit = create_permit(api, customer["id"], permit_number="P-9", permit_class="CLASS_I")
        resp = api.list_customer_permits(customer["id"], headers=_SALES)
        data, _meta = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["id"] == permit["id"]

    def test_list_animals_filtered_by_species(self, api):
        """PRD §3.2: "Animals may be fetched by id or listed with filters on `species_id` and `status`."

        Design: Corner/endpoints/list_animals_filtered_by_species
        """
        species = create_species(api, common_name="Sand Boa", scientific_name="Eryx colubrinus",
                                 min_quarantine_days=0, warranty_days=30)
        animal = intake_animal(api, species["id"], morph="Nuclear",
                               list_price_cents=12000, acquisition_cost_cents=4000)
        resp = api.list_animals(headers=_SALES, params={"species_id": species["id"]})
        data, _meta = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["id"] == animal["id"]


class TestRbacDenials:
    def test_vettech_cannot_create_feeder_batch(self, api):
        """PRD §2.1: "When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/vettech_cannot_create_feeder_batch_returns_unauthorized
        """
        resp = api.create_feeder_batch(create_feeder_batch_payload(), headers=_VET)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_customer_cannot_intake_animal(self, api):
        """PRD §2.1: "When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/customer_cannot_intake_animal_returns_unauthorized
        """
        customer = create_customer(api, email="rbac-intake@x.com")
        resp = api.create_animal(
            {"species_id": NON_EXISTENT_UUID, "morph": "x",
             "acquisition_cost_cents": 1000, "list_price_cents": 2000},
            headers=make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


class TestPagination:
    def test_list_species_limit_zero_returns_invalid_pagination(self, api):
        """PRD §2.3: "A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION`."

        Design: Corner/validations/list_species_invalid_pagination_returns_error
        """
        resp = api.list_species(headers=_SM, params={"limit": 0})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)
