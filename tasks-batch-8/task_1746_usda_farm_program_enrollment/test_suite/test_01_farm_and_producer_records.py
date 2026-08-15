"""Farm / producer / tract / field / yield-observation record claims (PRD §3.1, §2.4)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_tract,
    api_client,
    assert_farm,
    assert_yield_observation,
    create_farm,
    create_farm_payload,
    create_producer_payload,
    create_tract_payload,
    create_yield_record_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SPECIALIST = None  # bound per-test via fixture


@pytest.fixture
def specialist(county_specialist_headers):
    return county_specialist_headers


class TestFarmRecords:
    def test_create_farm_success_201_and_fields(self, api, specialist):
        """PRD §3.1: "The new farm starts in `ACTIVE` `farm_status`, and its
        `total_base_acres` — a computed sum across the farm's tracts — begins at
        zero until tracts are added."
        PRD §4: "New resources are returned with HTTP 201 on creation; actions
        that modify an existing resource return HTTP 200; removal of a membership
        returns HTTP 204 with no content."
        PRD §2.4: "Resources additionally carry `created_at` and `updated_at`
        timestamps in ISO 8601 UTC with three fractional digits, and an integer
        `version` that increments on each mutation."

        Design: Corner/entities/create_farm_success_201_and_fields
        """
        set_clock("2026-02-01T00:00:00Z")
        resp = api.create_farm(
            create_farm_payload(farm_number="F1", county_code="019", program_year=2026),
            specialist,
        )
        farm = validate_success(resp, 201)
        assert_farm(farm)
        assert farm["farm_status"] == "ACTIVE", (
            f"new farm must start ACTIVE, got {farm['farm_status']}"
        )
        # PRD pins version as an integer counter but not its initial value.
        assert isinstance(farm["version"], int)

    def test_get_farm_returns_stored_entity(self, api, specialist):
        """PRD §3.1: "Farms may be listed with optional `county_code` and
        `program_year` filters, and read by any role."
        PRD §4: "| GET | /fsa/farms/{farm_id} | Get farm | Producer,
        CountySpecialist, CountyExecutiveDirector, CountyCommittee |"

        Design: Corner/entities/get_farm_returns_stored_entity
        """
        farm = create_farm(farm_number="F2", county_code="019", program_year=2026)
        fetched = validate_success(api.get_farm(farm["id"], specialist), 200)
        assert_farm(fetched)
        assert fetched["id"] == farm["id"]
        assert fetched["farm_number"] == "F2"

    def test_list_farms_paginated(self, api, specialist):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
        The default `limit` is 10; the minimum is 1 and the maximum is 100. The
        default `offset` is 0. Results are sorted by `created_at` ascending. The
        `meta` block of a list response includes `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/entities/list_farms_paginated
        """
        create_farm(farm_number="F3", county_code="019", program_year=2026)
        create_farm(farm_number="F4", county_code="019", program_year=2026)
        data, meta = validate_paginated(
            api.list_farms(specialist, params={"limit": 1, "offset": 0})
        )
        assert meta["limit"] == 1, f"meta.limit must echo 1, got {meta['limit']}"
        assert meta["total_count"] >= 2, (
            f"two farms were created, total_count={meta['total_count']}"
        )
        assert meta["has_more"] is True, "a second page must exist"

    def test_get_nonexistent_farm_returns_not_found(self, api, specialist):
        """PRD §2.7: "Every path id and every foreign key referenced in the request
        body must resolve to an existing entity; any unresolvable reference is
        rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_farm_returns_not_found
        """
        resp = api.get_farm(NON_EXISTENT_UUID, specialist)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestProducerRecords:
    def test_create_producer_missing_required_field_returns_invalid_request(
        self, api, specialist
    ):
        """PRD §2.8: "and finally request-shape validation (required fields
        present, well-typed values, declared enum members — `ERR_INVALID_REQUEST`,
        HTTP 400)."
        PRD §3.1: "Producers are registered separately by a specialist, who
        supplies `producer_name`, the `tax_id_last4` used for attribution
        matching, and an `entity_type` of `INDIVIDUAL`, `CORPORATION`,
        `PARTNERSHIP`, `TRUST`, or `LLC`."

        Design: Corner/entities/create_producer_missing_required_field_returns_invalid_request
        """
        payload = create_producer_payload()
        del payload["producer_name"]
        resp = api.create_producer(payload, specialist)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_producer_default_agi_status_not_filed(self, api, specialist):
        """PRD §3.1: "A new producer starts with `agi_attestation_status` set to
        `NOT_FILED`, `adjusted_gross_income` null, `conservation_status` set to
        `PENDING`, and `payment_limitation_cap_cents` at the statutory default of
        12500000 (that is, $125,000.00)."

        Design: Corner/entities/producer_default_agi_status_not_filed
        """
        resp = api.create_producer(
            create_producer_payload(
                producer_name="P", tax_id_last4="1234", entity_type="LLC"
            ),
            specialist,
        )
        producer = validate_success(resp, 201)
        assert producer["agi_attestation_status"] == "NOT_FILED"
        assert producer["conservation_status"] == "PENDING"
        assert producer["payment_limitation_cap_cents"] == 12_500_000


class TestComputedAndHierarchicalClaims:
    def test_farm_total_base_acres_computed_from_tracts(self, api, specialist):
        """PRD §3.1: "Adding a tract triggers recomputation of the farm's
        `total_base_acres`." and "The new farm starts in `ACTIVE` `farm_status`,
        and its `total_base_acres` — a computed sum across the farm's tracts —
        begins at zero until tracts are added."

        Design: Corner/entities/farm_total_base_acres_computed_from_tracts
        """
        farm = create_farm(farm_number="F5", county_code="019", program_year=2026)
        add_tract(farm["id"], tract_number="T1", base_acres=60.00, cropland_acres=60.00)
        add_tract(farm["id"], tract_number="T2", base_acres=40.00, cropland_acres=40.00)
        fetched = validate_success(api.get_farm(farm["id"], specialist), 200)
        assert fetched["total_base_acres"] == pytest.approx(100.00), (
            f"total_base_acres must be the sum 60+40=100, got "
            f"{fetched['total_base_acres']}"
        )

    def test_yield_observation_immutable_entity(self, api, specialist):
        """PRD §2.4: "One entity is exempt from the full common-fields contract:
        `YieldObservation` carries only `id` and `created_at`; both `updated_at`
        and `version` are absent on `YieldObservation`."

        Design: Corner/entities/yield_observation_immutable_entity
        """
        farm = create_farm(farm_number="F6", county_code="019", program_year=2026)
        record = validate_success(
            api.create_yield_record(
                farm["id"], create_yield_record_payload(commodity="CORN"), specialist
            ),
            201,
        )
        resp = api.append_yield_observation(
            record["id"],
            {"crop_year": 2021, "actual_yield_bu_per_acre": 180.0},
            specialist,
        )
        observation = validate_success(resp, 201)
        assert_yield_observation(observation)

    def test_child_creation_requires_existing_parent(self, api, specialist):
        """PRD §2.7: "URLs that traverse the Farm → Tract → Field hierarchy (or
        any other parent-child path) validate path parameters left to right. Every
        path id and every foreign key referenced in the request body must resolve
        to an existing entity; any unresolvable reference is rejected with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/child_creation_requires_existing_parent
        """
        resp = api.create_tract(
            NON_EXISTENT_UUID,
            create_tract_payload(tract_number="T1", base_acres=10.00, cropland_acres=10.00),
            specialist,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
