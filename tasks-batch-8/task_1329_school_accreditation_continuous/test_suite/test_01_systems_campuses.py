"""Systems and campuses: creation defaults, structural validation, 404, pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_campus,
    assert_institution_system,
    create_campus_payload,
    create_system_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSystemCreation:
    def test_create_system_applies_membership_defaults(self, api, officer_headers):
        """PRD §3.1: "The new system starts with `accreditation_status` of
        `CANDIDATE` and a `fee_credit_cents` ledger at 0".
        PRD §3.1: "The system's `current_term_id` points at whichever of its
        terms is active and is null when none is."

        Design: Corner/entities/create_system_required_fields_and_defaults
        """
        created = validate_success(
            api.create_system(create_system_payload(name="New County",
                                                    system_type="DISTRICT"),
                              officer_headers),
            expected_status=201)
        assert_institution_system(created)
        assert created["accreditation_status"] == "CANDIDATE"
        assert created["fee_credit_cents"] == 0
        assert created["current_term_id"] is None

        fetched = validate_success(api.get_system(created["id"], officer_headers))
        assert_institution_system(fetched)
        assert fetched["id"] == created["id"]
        assert fetched["accreditation_status"] == "CANDIDATE"
        assert fetched["fee_credit_cents"] == 0
        assert fetched["current_term_id"] is None

    def test_create_system_missing_name_rejected(self, api, officer_headers):
        """PRD §2.5: "Purely structural problems — a missing required field, an
        enum value outside its allowed set, an `enrollment` below 1, a `rating`
        outside 1 through 4, or a `closes_at` that is not strictly after
        `opens_at` — are reported as `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_system_missing_name_returns_validation
        """
        payload = create_system_payload(name="New County", system_type="DISTRICT")
        del payload["name"]
        resp = api.create_system(payload, officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_get_system_not_found(self, api, officer_headers):
        """PRD §2.5: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) at the first path segment that does not correspond to an
        existing resource within its parent's scope."

        Design: Corner/entities/get_system_not_found
        """
        resp = api.get_system(NON_EXISTENT_UUID, officer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCampusCreation:
    def test_campus_enrollment_zero_rejected(self, api, officer_headers):
        """PRD §2.5: "Purely structural problems — a missing required field, an
        enum value outside its allowed set, an `enrollment` below 1, a `rating`
        outside 1 through 4, or a `closes_at` that is not strictly after
        `opens_at` — are reported as `ERR_VALIDATION` (HTTP 400)."
        PRD §3.1: "Campuses are created under a system by an officer, each with
        a `name` and an integer `enrollment` of at least 1".

        Design: Corner/entities/campus_enrollment_below_one_rejected
        """
        system = get_success_data(api.create_system(
            create_system_payload(name="C County", system_type="DISTRICT"),
            officer_headers))
        resp = api.create_campus(system["id"],
                                 create_campus_payload(name="Zero Campus",
                                                       enrollment=0),
                                 officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_list_campuses_pagination_envelope(self, api, officer_headers):
        """PRD §2.3: "List responses include the following fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."
        PRD §2.3: "If not provided, it defaults to 10, with a minimum of 1 and
        a maximum of 100. The `offset` parameter specifies the number of items
        to skip and defaults to 0."

        Design: Corner/entities/list_campuses_pagination_envelope
        """
        system = get_success_data(api.create_system(
            create_system_payload(name="Paged County", system_type="DISTRICT"),
            officer_headers))
        for name, enrollment in (("C1", 100), ("C2", 200)):
            created = validate_success(
                api.create_campus(system["id"],
                                  create_campus_payload(name=name,
                                                        enrollment=enrollment),
                                  officer_headers),
                expected_status=201)
            assert_campus(created)

        data, meta = validate_paginated(
            api.list_campuses(system["id"], officer_headers))
        assert isinstance(data, list) and len(data) == 2
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        for campus in data:
            assert_campus(campus)
