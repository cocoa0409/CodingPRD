"""Corner: entity creation defaults, computed fields, immutability, listing, not-found."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_application,
    assert_assignment,
    assert_inspection,
    assert_vendor,
    assert_zone,
    create_application_payload,
    create_festival_payload,
    create_vendor,
    create_vendor_payload,
    create_zone_payload,
    is_valid_uuid,
    make_vendor_headers,
    setup_curated_with_booth,
    setup_open_festival,
    setup_reserved_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
VM = TEST_USERS["vendor_manager_headers"]
OPS = TEST_USERS["ops_headers"]
HI = TEST_USERS["health_inspector_headers"]


class TestFestivalCreate:
    def test_festival_create_applies_defaults(self, api):
        """PRD §3.1: "A new festival begins in `PLANNING` status."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/festival_create_applies_defaults
        """
        resp = api.create_festival(create_festival_payload(name="Default Fest"), DIRECTOR)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PLANNING", f"new festival must begin PLANNING, got {data['status']}"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"]), "id must be a UUID without any type prefix"


class TestVendorCreate:
    def test_vendor_create_applies_defaults(self, api):
        """PRD §3.2: "A new vendor starts in `APPROVED` status with
        `compliance_strikes` at zero".

        Design: Corner/entities/vendor_create_applies_defaults
        """
        resp = api.create_vendor(create_vendor_payload(legal_name="Defaults LLC"), VM)
        data = validate_success(resp, expected_status=201)
        assert_vendor(data)
        assert data["status"] == "APPROVED"
        assert data["compliance_strikes"] == 0


class TestApplicationRequiredFields:
    def test_application_missing_category_returns_invalid_request(self, api):
        """PRD §2.10: "missing required fields, malformed values, and enum
        violations surface as `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/application_missing_category_returns_invalid_request
        """
        scen = setup_open_festival(name="Req Fest")
        vendor = create_vendor(legal_name="Req LLC")
        payload = create_application_payload(vendor["id"], scen["festival"]["id"])
        del payload["category"]
        resp = api.create_application(payload, make_vendor_headers(vendor["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestZoneComputedFields:
    def test_zone_computed_field_input_ignored(self, api):
        """PRD §3.1: "Zones expose two computed counters that start at zero:
        `reserved_power_amps`, the sum of `power_draw_amps` over the zone's
        assignments in `RESERVED`, `CONFIRMED`, or `ACTIVE`, and
        `reserved_water_hookups`, the count of those assignments whose
        `requires_water` is true".

        Design: Corner/entities/zone_computed_field_input_ignored
        """
        festival = validate_success(
            api.create_festival(create_festival_payload(name="Computed Fest"), DIRECTOR),
            expected_status=201,
        )
        payload = create_zone_payload(festival["id"])
        payload["reserved_power_amps"] = 999  # client-supplied computed field
        data = validate_success(api.create_zone(payload, OPS), expected_status=201)
        assert_zone(data)
        assert data["reserved_power_amps"] == 0, "computed counters start at zero"
        assert data["reserved_water_hookups"] == 0


class TestInspectionImmutability:
    def test_inspection_record_is_immutable_event(self, api):
        """PRD §2.4: "an `InspectionRecord` is an immutable event and carries only
        `id` and `created_at` — `updated_at` and `version` are absent, and no
        endpoint modifies an inspection after it is recorded."
        PRD §3.4: "An inspection is recorded with its outcome already known, so
        its `status` is always `COMPLETED` at creation".

        Design: Corner/entities/inspection_record_is_immutable_event
        """
        scen = setup_reserved_assignment(name="Imm Fest")
        resp = api.create_inspection(
            {"assignment_id": scen["assignment"]["id"], "type": "FIRE_SAFETY", "result": "PASS"},
            HI,
        )
        data = validate_success(resp, expected_status=201)
        assert_inspection(data)
        assert data["status"] == "COMPLETED"


class TestVendorListPagination:
    def test_vendor_list_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/entities/vendor_list_pagination_envelope
        """
        validate_success(api.create_vendor(create_vendor_payload(legal_name="Page One"), VM), expected_status=201)
        validate_success(api.create_vendor(create_vendor_payload(legal_name="Page Two"), VM), expected_status=201)

        resp1 = api.list_vendors(VM, params={"limit": 1, "offset": 0})
        data1, meta1 = validate_paginated(resp1)
        assert len(data1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        resp2 = api.list_vendors(VM, params={"limit": 1, "offset": 1})
        data2, meta2 = validate_paginated(resp2)
        assert len(data2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

        body = resp1.json()
        assert body["response_type"] == "array"
        assert body["meta"].get("api_request_id"), "envelope must carry meta.api_request_id"
        assert data1[0]["id"] != data2[0]["id"]


class TestFestivalNotFound:
    def test_get_missing_festival_returns_not_found(self, api):
        """PRD §2.6: "every foreign key supplied in a request body must reference
        an existing resource; the first missing reference surfaces the
        corresponding not-found error — one of `ERR_FESTIVAL_NOT_FOUND`".

        Design: Corner/entities/get_missing_festival_returns_not_found
        """
        resp = api.get_festival(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_FESTIVAL_NOT_FOUND)


class TestAssignmentDenormalization:
    def test_assignment_denormalizes_festival_and_zone(self, api):
        """PRD §2.6: "each of those resources carries a denormalized `festival_id`
        stamped at creation from the referenced chain (an assignment additionally
        carries a denormalized `zone_id` taken from its booth's zone, refreshed on
        reassignment)".

        Design: Corner/entities/assignment_denormalizes_festival_and_zone
        """
        scen = setup_curated_with_booth(name="Denorm Fest")
        resp = api.create_assignment(
            {"application_id": scen["app"]["id"], "booth_id": scen["booth"]["id"],
             "power_draw_amps": 20, "requires_water": False},
            OPS,
        )
        data = validate_success(resp, expected_status=201)
        assert_assignment(data)
        assert data["festival_id"] == scen["festival"]["id"], "festival_id denormalized from booth.zone"
        assert data["zone_id"] == scen["zone"]["id"], "zone_id denormalized from booth.zone_id"


class TestBoothZoneFilter:
    def test_booth_children_reachable_via_zone_filter(self, api):
        """PRD §3.1: "The zone list filters by `festival_id`; the booth list
        filters by `zone_id` and `status`."

        Design: Corner/entities/booth_children_reachable_via_zone_filter
        """
        festival = validate_success(
            api.create_festival(create_festival_payload(name="FK Fest"), DIRECTOR),
            expected_status=201,
        )
        z1 = validate_success(api.create_zone(create_zone_payload(festival["id"], name="North"), OPS), expected_status=201)
        z2 = validate_success(api.create_zone(create_zone_payload(festival["id"], name="South"), OPS), expected_status=201)
        validate_success(api.create_booth({"zone_id": z1["id"], "label": "N-01", "power_outlet_max_amps": 60, "has_water_hookup": False}, OPS), expected_status=201)
        validate_success(api.create_booth({"zone_id": z2["id"], "label": "S-01", "power_outlet_max_amps": 60, "has_water_hookup": False}, OPS), expected_status=201)

        data, meta = validate_paginated(api.list_booths(OPS, params={"zone_id": z1["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["label"] == "N-01", f"only z1's booth returned, got {data}"
