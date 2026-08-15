"""Registry basics, auth validation, RBAC, and the response envelope (PRD §2, §3.1)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_tenant_units,
    assert_building,
    assert_owner,
    assign_verifier,
    create_and_open_cycle,
    create_building,
    create_building_payload,
    create_cycle_payload,
    create_owner,
    create_verifier,
    is_valid_uuid,
    make_officer_headers,
    make_owner_headers,
    make_tenant_rep_headers,
    make_verifier_headers,
    request_consent,
    setup_submitted_report,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
UTILITY = TEST_USERS["utility_agent_headers"]


class TestOwnerRegistration:
    def test_owner_create_applies_system_defaults(self, api):
        """PRD §3.1: "Registering a building owner requires the owner's legal `name`
        and `contact_email`; a newly registered owner starts with `standing` of
        `NORMAL` and `outstanding_fines_cents` of zero."

        Design: Corner/entities/e_owner_create_applies_defaults
        """
        resp = api.create_owner(
            {"name": "Owner Zero", "contact_email": "oz@x.com"}, OFFICER
        )
        owner = validate_success(resp, 201)
        assert_owner(owner)
        assert owner["standing"] == "NORMAL", "A new owner starts NORMAL"
        assert owner["outstanding_fines_cents"] == 0, "A new owner starts with zero exposure"
        assert is_valid_uuid(owner["id"]), "id is a bare UUID"

    def test_owner_create_ignores_client_supplied_computed_fields(self, api):
        """PRD §3.1: "Registering a building owner requires the owner's legal `name`
        and `contact_email`; a newly registered owner starts with `standing` of
        `NORMAL` and `outstanding_fines_cents` of zero."

        Client-supplied standing/exposure cannot override the system-managed defaults.

        Design: Corner/entities/e_owner_computed_fields_input_ignored
        """
        resp = api.create_owner(
            {
                "name": "Owner Rigged",
                "contact_email": "or@x.com",
                "standing": "RESTRICTED",
                "outstanding_fines_cents": 999999,
            },
            OFFICER,
        )
        owner = validate_success(resp, 201)
        assert owner["standing"] == "NORMAL", "client-supplied standing is ignored"
        assert owner["outstanding_fines_cents"] == 0, "client-supplied exposure is ignored"


class TestBuildingRegistration:
    def test_building_create_missing_floor_area_rejected(self, api):
        """PRD §3.2: "A building is registered with its street `address`, its
        `gross_floor_area_sqft` (which must be strictly greater than zero), and its
        `property_type`, one of `OFFICE`, `MULTIFAMILY`, `RETAIL`, `HOTEL`, or
        `INDUSTRIAL`."
        PRD §2.8: "Required fields present, enum values valid, numbers positive where
        required, date ranges coherent, string minimum lengths honored, and partial
        replacement field sets refused (`ERR_INVALID_REQUEST`, `ERR_INVALID_DATE_RANGE`)."

        Design: Corner/entities/e_building_create_missing_required_field_returns_invalid_request
        """
        owner = create_owner()
        payload = {"address": "1 Incomplete St", "property_type": "OFFICE"}
        resp = api.create_building(payload, make_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_building_create_invalid_property_type_rejected(self, api):
        """PRD §3.2: "A building is registered with its street `address`, its
        `gross_floor_area_sqft` (which must be strictly greater than zero), and its
        `property_type`, one of `OFFICE`, `MULTIFAMILY`, `RETAIL`, `HOTEL`, or
        `INDUSTRIAL`."
        PRD §2.8: "Required fields present, enum values valid, numbers positive where
        required, date ranges coherent, string minimum lengths honored, and partial
        replacement field sets refused (`ERR_INVALID_REQUEST`, `ERR_INVALID_DATE_RANGE`)."

        Design: Corner/entities/e_building_create_invalid_enum_rejected
        """
        owner = create_owner()
        payload = create_building_payload(property_type="CASTLE")
        resp = api.create_building(payload, make_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_missing_building_returns_not_found(self, api):
        """PRD §2.8: "Every path- or body-referenced resource must exist, validated
        left to right (`ERR_NOT_FOUND`)."

        Design: Corner/entities/e_get_building_not_found_returns_404
        """
        resp = api.get_building(NON_EXISTENT_UUID, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_buildings_list_pagination_window(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
        return. If not provided, it defaults to 10, with a minimum of 1 and maximum
        of 100. The `offset` parameter specifies the number of items to skip and
        defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/e_buildings_list_pagination_envelope
        """
        owner = create_owner()
        for area in (30000, 31000, 32000):
            create_building(owner["id"], gross_floor_area_sqft=area)

        data, meta = validate_paginated(
            api.list_buildings(OFFICER, params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2, "limit windows the result set"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        for b in data:
            assert_building(b)


class TestAuthContext:
    def test_request_without_role_header_rejected(self, api):
        """PRD §2.1: "A request whose headers are missing, empty, or whose role value
        is not one of these five declared roles is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/v_missing_auth_header_returns_400
        """
        resp = api.list_buildings(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_owner_role_cannot_create_cycle(self, api):
        """PRD §2.1: "Every endpoint also carries a list of roles permitted to invoke
        it; a caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_ROLE`."
        PRD §4: POST `/v1/reporting-cycles` is authorized for ComplianceOfficer only.

        Design: Corner/validations/v_wrong_role_on_cycle_create_forbidden
        """
        owner = create_owner()
        resp = api.create_reporting_cycle(
            create_cycle_payload(), make_owner_headers(owner["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestEntityBackedOwnership:
    def test_tenant_cannot_grant_other_units_consent(self, api):
        """PRD §2.1: "When `X-User-Role` is `TenantRep`, `X-User-ID` is the `id` of
        the `TenantUnit` the caller represents; consent decisions on a grant are
        authorized only when the grant's `tenant_unit_id` equals `X-User-ID`."
        PRD §2.1: "A failure of any of these entity-backed ownership checks is
        rejected with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/r_tenant_cannot_grant_other_units_consent
        """
        owner = create_owner()
        building = create_building(owner["id"])
        u1, u2 = add_tenant_units(
            building["id"], owner["id"], [("U1", 20000, "OFFICE"), ("U2", 15000, "RETAIL")]
        )
        grant = request_consent(u1["id"], owner["id"])

        resp = api.grant_consent(
            grant["id"],
            {"valid_from": "2027-01-01", "valid_to": "2027-12-31"},
            make_tenant_rep_headers(u2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        still = validate_success(api.get_consent_grant(grant["id"], OFFICER))
        assert still["status"] == "REQUESTED", "grant untouched by the rejected attempt"

    def test_verifier_cannot_signoff_others_record(self, api):
        """PRD §3.6: "The assigned `DataVerifier` — the caller whose `X-User-ID`
        equals the record's `verifier_id`, else `ERR_NOT_RESOURCE_OWNER` — then
        signs off or rejects."

        Design: Corner/rbac/r_verifier_cannot_signoff_others_record
        """
        ctx = setup_submitted_report()
        v1 = create_verifier()
        v2 = create_verifier()
        record = assign_verifier(ctx["report"]["id"], v1["id"], ctx["owner"]["id"])

        resp = api.sign_off_verification(record["id"], make_verifier_headers(v2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        still = validate_success(api.get_verification_record(record["id"], OFFICER))
        assert still["status"] == "PENDING", "record stays PENDING after the rejected sign-off"

    def test_read_endpoints_open_to_any_role(self, api):
        """PRD §2.1: "Read endpoints accept any authenticated role."

        Design: Corner/rbac/r_read_endpoints_open_to_any_role
        """
        owner = create_owner()
        verifier = create_verifier()
        building = create_building(owner["id"])
        units = add_tenant_units(building["id"], owner["id"], [("U1", 20000, "OFFICE")])

        for headers in (
            make_verifier_headers(verifier["id"]),
            make_tenant_rep_headers(units[0]["id"]),
            UTILITY,
            make_officer_headers("officer-9"),
        ):
            data = validate_success(api.get_building(building["id"], headers))
            assert data["id"] == building["id"]


class TestBodyReferenceExistence:
    def test_report_create_with_unknown_building_returns_not_found(self, api):
        """PRD §2.9: "Body-referenced resources — a `building_id` or `cycle_id` in a
        creation payload, for instance — are validated under the same existence tier."
        PRD §2.8: "Every path- or body-referenced resource must exist, validated
        left to right (`ERR_NOT_FOUND`)."

        Design: Corner/errors/err_body_reference_not_found
        """
        owner = create_owner()
        cycle = create_and_open_cycle(covered_property_types=["OFFICE"])
        resp = api.create_benchmark_report(
            {"building_id": NON_EXISTENT_UUID, "cycle_id": cycle["id"]},
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
