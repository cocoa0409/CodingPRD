"""Contractor registration, auth/validation pipeline, RBAC, and list envelope."""
from test_helpers import (
    DUPLICATE_LICENSE_IDS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    admin_headers,
    assert_contractor,
    create_contractor,
    create_contractor_payload,
    create_plan,
    create_property,
    create_property_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_technician_headers,
    setup_inspection_site,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

MARSHAL = TEST_USERS["fire_marshal_headers"]


class TestContractorCreation:
    def test_contractor_create_applies_defaults(self, api):
        """PRD §3.1: "A new contractor starts with `compliance_score` 1000 and
        `posture` `GOOD_STANDING`, and its `status` is `ACTIVE`."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix.
        `created_at` is an ISO 8601 UTC timestamp with three fractional digits
        recording when the resource was created."

        Design: Corner/entities/contractor_create_success_and_defaults
        """
        resp = api.create_contractor(
            create_contractor_payload(legal_name="Default Co",
                                      state_license_no="C-9000"),
            MARSHAL,
        )
        con = validate_success(resp, 201)
        assert_contractor(con)
        assert con["compliance_score"] == 1000, "compliance_score starts at 1000"
        assert con["posture"] == "GOOD_STANDING"
        assert con["status"] == "ACTIVE"
        assert is_valid_uuid(con["id"]), "id is a bare UUID with no type prefix"
        assert is_iso8601_timestamp(con["created_at"])
        assert isinstance(con["version"], int), "version is an integer"

    def test_contractor_duplicate_license_number_rejected(self, api):
        """PRD §3.1: "The license number is unique across all contractors; a
        conflicting registration is rejected with `ERR_DUPLICATE_CONSTRAINT`
        (carrying the specialized alias `ERR_DUPLICATE_LICENSE_NO`)."

        Design: Corner/entities/contractor_duplicate_license_rejected
        """
        create_contractor(legal_name="First Co", state_license_no="C-9100")
        resp = api.create_contractor(
            create_contractor_payload(legal_name="Copycat Co",
                                      state_license_no="C-9100"),
            MARSHAL,
        )
        validate_error_is_one_of(resp, DUPLICATE_LICENSE_IDS)
        assert resp.status_code == 409, (
            f"duplicate license conflict must be HTTP 409, got {resp.status_code}")


class TestValidationPipeline:
    def test_missing_required_field_rejected(self, api):
        """PRD §2.6: "18. **Request shape** — all required body fields must be
        present with correct scalar types; failure yields `ERR_INVALID_REQUEST`."
        PRD §3.1: "A `FireMarshal` onboards a fire protection service contractor
        by registering its `legal_name` and `state_license_no`."

        Design: Corner/validations/missing_required_field_rejected
        """
        resp = api.create_contractor({"legal_name": "NoLicense Co"}, MARSHAL)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_not_found_on_bad_path_id(self, api):
        """PRD §2.6: "3. **Path existence** — every identifier in the URL path
        must exist, validated left to right; the first missing identifier yields
        `ERR_NOT_FOUND`."

        Design: Corner/validations/not_found_on_bad_path_id
        """
        resp = api.get_contractor(NON_EXISTENT_UUID, MARSHAL)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_invalid_enum_rejected(self, api):
        """PRD §2.6: "14. **Enum membership** — every enum field value must lie
        in its declared set; failure yields `ERR_INVALID_ENUM`."
        PRD §3.2: "an `occupancy_class` — one of `ASSEMBLY`, `BUSINESS`,
        `EDUCATIONAL`, `MERCANTILE`, `RESIDENTIAL`, or `STORAGE`"

        Design: Corner/validations/invalid_enum_rejected
        """
        con = create_contractor(legal_name="Enum Co", state_license_no="C-9990")
        resp = api.create_property(
            create_property_payload(con["id"], address_line="1 Enum Way",
                                    occupancy_class="HOSPITAL"),
            admin_headers(con),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


class TestRoleAuthorization:
    def test_technician_cannot_publish_plan(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/fire-compliance/inspection-plans/{id}/publish` |
        Publish a plan (computes the final prorated fee) | ContractorAdmin |"

        Design: Corner/rbac/technician_cannot_publish_plan
        """
        ctx = setup_inspection_site(legal_name="RBAC Co")
        prop = get_success_data(api.get_property(ctx["prop"]["id"], ctx["admin"]))
        plan = create_plan(ctx["con"], prop, plan_year=2026)
        resp = api.publish_plan(plan["id"], make_technician_headers(ctx["tech"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = validate_success(api.get_plan(plan["id"], ctx["admin"]))
        assert after["plan_posture"] == "DRAFT", (
            "the rejected publish must leave the plan in DRAFT")


class TestListPagination:
    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter specifies how many items to skip and defaults to 0."
        PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_pagination_envelope
        """
        con = create_contractor(legal_name="Page Co", state_license_no="C-9994")
        p1 = create_property(con, address_line="1 Page St")
        p2 = create_property(con, address_line="2 Page St",
                             occupancy_class="MERCANTILE")

        data1, meta1 = validate_paginated(
            api.list_properties(admin_headers(con), params={"limit": 1, "offset": 0}))
        assert len(data1) == 1, "first page returns exactly one property"
        assert meta1["limit"] == 1 and meta1["offset"] == 0
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_properties(admin_headers(con), params={"limit": 1, "offset": 1}))
        assert len(data2) == 1, "second page returns the other property"
        assert meta2["has_more"] is False
        assert data1[0]["id"] != data2[0]["id"], "pages must not overlap"
        assert {data1[0]["id"], data2[0]["id"]} == {p1["id"], p2["id"]}
