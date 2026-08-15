"""Condition inventory: owners, parcels, segments, defects, and listings."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_defect,
    make_owner,
    make_parcel,
    make_segment,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
INSP1 = TEST_USERS["inspector_headers"]


class TestParcelOrdinanceAndDefaults:
    def test_owner_responsibility_computed_by_ordinance(self, api):
        """PRD §3.2: "`owner_responsibility_pct` is 0 for city-owned parcels —
        the city self-repairs and such parcels can never be noticed — and 100
        for every other parcel, making the abutting owner fully responsible.
        The parcel's `delinquency_flag` starts false"

        Design: Corner/entities/parcel_creation_computes_owner_responsibility
        """
        owner = make_owner("Ora Ort", "40 Ort St")
        private = validate_success(api.create_parcel(
            {"parcel_number": "P-E1", "owner_id": owner["id"],
             "street_address": "40 Ort St", "street_class": "LOCAL"},
            COORD), 201)
        assert private["owner_responsibility_pct"] == 100
        assert private["delinquency_flag"] is False

        city = validate_success(api.create_parcel(
            {"parcel_number": "P-E2", "owner_id": owner["id"],
             "street_address": "City Lot", "street_class": "LOCAL",
             "is_city_owned": True}, COORD), 201)
        assert city["owner_responsibility_pct"] == 0
        assert city["delinquency_flag"] is False

    def test_hardship_tier_defaults_to_none(self, api):
        """PRD §3.2: "an optional `hardship_tier` — one of `NONE`, `SENIOR_65`,
        or `LOW_INCOME`, defaulting to `NONE`"

        Design: Corner/entities/property_owner_defaults_hardship_none
        """
        owner = validate_success(api.create_property_owner(
            {"full_name": "Pat Pine", "mailing_address": "41 Pine St"},
            COORD), 201)
        assert owner["hardship_tier"] == "NONE"


class TestRequestShape:
    def test_missing_street_class_rejected(self, api):
        """PRD §2.7: "unknown payload fields, missing required fields, wrongly
        typed values, non-positive quantities, invalid enum members, and windows
        whose start is not strictly before their end all fail with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/parcel_missing_street_class_rejected
        """
        owner = make_owner("Rita Rye", "43 Rye St")
        resp = api.create_parcel(
            {"parcel_number": "P-E4", "owner_id": owner["id"],
             "street_address": "43 Rye St"}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_invalid_enums_and_shapes_rejected(self, api):
        """PRD §2.7: "unknown payload fields, missing required fields, wrongly
        typed values, non-positive quantities, invalid enum members, and windows
        whose start is not strictly before their end all fail with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/invalid_enums_and_shapes_rejected
        """
        owner = make_owner("Sal Sage", "44 Sage St")
        make_parcel(owner["id"], "P-E5", "44 Sage St", "LOCAL")

        resp = api.create_parcel(
            {"parcel_number": "P-E6", "owner_id": owner["id"],
             "street_address": "45 Bad St", "street_class": "HIGHWAY"}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        resp = api.create_program_cycle(
            {"cycle_year": 2027, "window_start_date": "2027-06-30",
             "window_end_date": "2027-01-01", "appropriation_cents": 1000000},
            COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        resp = api.create_program_cycle(
            {"cycle_year": 2028, "window_start_date": "2028-01-01",
             "window_end_date": "2028-12-31", "appropriation_cents": 0}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        resp = api.create_defect(
            {"segment_id": NON_EXISTENT_UUID, "defect_type": "SPALLING",
             "area_sqft": 0}, INSP1)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestParcelRetrievalAndListing:
    def test_parcel_get_returns_stored_fields(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §3.2: "two optional booleans: `is_corner_lot`, recording frontage on
        two intersecting streets, and `is_city_owned`, both defaulting to false."

        Design: Corner/entities/parcel_get_returns_stored_fields
        """
        owner = make_owner("Tom Tam", "46 Tam St")
        parcel = make_parcel(owner["id"], "P-E7", "46 Tam St", "COLLECTOR")
        resp = api.get_parcel(parcel["id"], COORD)
        assert resp.status_code == 200
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"]
        data = body["data"]
        assert data["parcel_number"] == "P-E7"
        assert data["street_class"] == "COLLECTOR"
        assert data["is_corner_lot"] is False
        assert data["owner_responsibility_pct"] == 100

    def test_parcel_list_pagination_and_owner_filter(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10 when omitted, must be
        at least 1, and may not exceed 100; `offset` defaults to 0."
        PRD §3.2: "The parcel listing accepts an `owner_id` query filter
        returning a single owner's parcels."

        Design: Corner/entities/parcel_list_pagination_and_filter
        """
        owner = make_owner("Ula Ulm", "47 Ulm St")
        parcel_a = make_parcel(owner["id"], "P-E8A", "47 Ulm St", "LOCAL")
        parcel_b = make_parcel(owner["id"], "P-E8B", "48 Ulm St", "LOCAL")

        resp1 = api.list_parcels(
            COORD, params={"owner_id": owner["id"], "limit": 1, "offset": 0})
        page1, meta1 = validate_paginated(resp1)
        assert resp1.json()["response_type"] == "array"
        assert len(page1) == 1

        resp2 = api.list_parcels(
            COORD, params={"owner_id": owner["id"], "limit": 1, "offset": 1})
        page2, meta2 = validate_paginated(resp2)
        assert len(page2) == 1

        p1, p2 = page1[0]["id"], page2[0]["id"]
        assert p1 != p2
        assert {p1, p2} == {parcel_a["id"], parcel_b["id"]}


class TestForeignKeyExistence:
    def test_body_fk_existence_validated(self, api):
        """PRD §2.7: "Path identifiers and body foreign keys must reference
        existing resources, validated left-to-right: path parameters first, then
        body fields in their declaration order."

        Design: Corner/entities/flat_topology_body_fk_existence
        """
        resp = api.create_parcel(
            {"parcel_number": "P-E9", "owner_id": NON_EXISTENT_UUID,
             "street_address": "49 Nowhere St", "street_class": "LOCAL"}, COORD)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_OWNER_NOT_FOUND)

        resp = api.create_segment(
            {"parcel_id": NON_EXISTENT_UUID, "segment_code": "S-E9-1",
             "length_ft": 10, "width_ft": 5}, INSP1)
        validate_error(resp, ApiErrorId.ERR_PARCEL_NOT_FOUND)

        resp = api.create_defect(
            {"segment_id": NON_EXISTENT_UUID, "defect_type": "SPALLING",
             "area_sqft": 10}, INSP1)
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_FOUND)


class TestInitialStates:
    def test_inventory_initial_states(self, api):
        """PRD §3.2: "A new segment starts `IN_SERVICE` with both condition
        indexes at zero."
        PRD §3.2: "The first defect recorded on an `IN_SERVICE` segment flags it
        (`IN_SERVICE → FLAGGED`)."
        PRD §3.3: "A new notice starts as `DRAFT` with `appeal_status` set to
        `NONE`."

        Design: Corner/state_machines/inventory_initial_states
        """
        owner = make_owner("Wes Wattle", "51 Wat St")
        parcel = make_parcel(owner["id"], "P-S1", "51 Wat St", "LOCAL")

        segment = validate_success(api.create_segment(
            {"parcel_id": parcel["id"], "segment_code": "S-S1-1",
             "length_ft": 20, "width_ft": 5}, INSP1), 201)
        assert segment["status"] == "IN_SERVICE"
        assert segment["open_defect_count"] == 0
        assert segment["condition_screening"] == 0
        assert segment["condition_area_weighted"] == 0

        defect = validate_success(api.create_defect(
            {"segment_id": segment["id"],
             "defect_type": "VERTICAL_SEPARATION",
             "measured_offset_inches": 0.75, "area_sqft": 10}, INSP1), 201)
        assert defect["status"] == "OPEN"

        segment2 = validate_success(api.get_segment(segment["id"], COORD))
        assert segment2["status"] == "FLAGGED"
        assert segment2["open_defect_count"] == 1

        notice = validate_success(api.create_repair_notice(
            {"parcel_id": parcel["id"], "defect_ids": [defect["id"]]},
            COORD), 201)
        assert notice["status"] == "DRAFT"
        assert notice["appeal_status"] == "NONE"


class TestConditionIndexVariants:
    def test_screening_and_area_weighted_diverge(self, api):
        """PRD §3.2: "The screening view, `condition_screening`, is an integer
        equal to the highest severity weight present in that set: the worst
        defect dominates. The area-weighted view, `condition_area_weighted`,
        divides the sum of each defect's severity weight multiplied by its
        `area_sqft` by the sum of the `area_sqft` values, then rounds half-up to
        one decimal place."

        Design: Corner/calculations/segment_condition_index_two_variants
        """
        owner = make_owner("Pia Poplar", "67 Poplar St")
        parcel = make_parcel(owner["id"], "P-C2", "67 Poplar St", "LOCAL")
        segment = make_segment(parcel["id"], "S-C2-1", length_ft=50)

        d1 = validate_success(api.create_defect(
            {"segment_id": segment["id"],
             "defect_type": "VERTICAL_SEPARATION",
             "measured_offset_inches": 0.75, "area_sqft": 10}, INSP1), 201)
        assert d1["severity_class"] == "TRIP_HAZARD"
        d2 = validate_success(api.create_defect(
            {"segment_id": segment["id"], "defect_type": "SPALLING",
             "area_sqft": 15}, INSP1), 201)
        assert d2["severity_class"] == "MINOR"

        seg = validate_success(api.get_segment(segment["id"], COORD))
        assert seg["condition_screening"] == 100
        # (100*10 + 25*15) / 25 = 55.0
        assert seg["condition_area_weighted"] == 55.0
        assert seg["condition_area_weighted"] != seg["condition_screening"]
        assert seg["open_defect_count"] == 2


class TestUniquenessConstraints:
    def test_duplicate_registration_keys_rejected(self, api):
        """PRD §3.2: "A coordinator registers a `PropertyParcel` with its
        assessor `parcel_number` (unique across all parcels, with duplicates
        rejected as `ERR_DUPLICATE_PARCEL_NUMBER`)"
        PRD §3.2: "Each `SidewalkSegment` is registered against its abutting
        `parcel_id` with a unique `segment_code` (duplicates rejected as
        `ERR_DUPLICATE_SEGMENT_CODE`)"
        PRD §3.7: "a `license_number` unique across contractors (duplicates
        rejected as `ERR_DUPLICATE_LICENSE_NUMBER`"

        Design: Corner/errors/duplicate_registration_keys_rejected
        """
        owner = make_owner("Ora Okra", "94 Okra St")
        parcel1 = make_parcel(owner["id"], "P-DUP", "94 Okra St", "LOCAL")
        parcel2 = make_parcel(owner["id"], "P-DUP-2", "95 Okra St", "LOCAL")
        make_segment(parcel1["id"], "S-DUP", length_ft=10)
        make_contractor = api.create_contractor(
            {"company_name": "Acme Paving", "license_number": "L-DUP",
             "insurance_valid_until": "2026-12-31"}, COORD)
        validate_success(make_contractor, 201)

        resp = api.create_parcel(
            {"parcel_number": "P-DUP", "owner_id": owner["id"],
             "street_address": "96 Okra St", "street_class": "LOCAL"}, COORD)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PARCEL_NUMBER)

        resp = api.create_segment(
            {"parcel_id": parcel2["id"], "segment_code": "S-DUP",
             "length_ft": 10, "width_ft": 5}, INSP1)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEGMENT_CODE)

        resp = api.create_contractor(
            {"company_name": "Copycat Concrete", "license_number": "L-DUP",
             "insurance_valid_until": "2026-12-31"}, COORD)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_LICENSE_NUMBER)


class TestCrossEntityListFilters:
    def test_list_endpoints_filter_foreign_keys(self, api):
        """PRD §3.2: "The defect listing accepts `segment_id` and `status`
        query filters"
        PRD §3.3: "The notice listing accepts `parcel_id`, `prior_notice_id`,
        and `status` query filters."
        PRD §3.5: "The application listing accepts `notice_id`, `parcel_id`,
        `owner_id`, and `cycle_id` filters in combination."

        Design: Corner/endpoints/list_endpoints_filter_foreign_keys
        """
        from test_helpers import (
            create_application_payload,
            issue_notice,
            make_cycle,
            make_draft_notice,
            make_owner_headers,
        )
        cycle = make_cycle()
        owner = make_owner("Fox Ficus", "82 Ficus St")
        parcel1 = make_parcel(owner["id"], "P-N1A", "82 Ficus St", "LOCAL")
        parcel2 = make_parcel(owner["id"], "P-N1B", "83 Ficus St", "LOCAL")
        seg1 = make_segment(parcel1["id"], "S-N1A-1")
        seg2 = make_segment(parcel2["id"], "S-N1B-1")
        def1 = make_defect(seg1["id"], "SPALLING", 20)
        def2 = make_defect(seg2["id"], "SPALLING", 20)
        notice1 = issue_notice(
            make_draft_notice(parcel1["id"], [def1["id"]])["id"])
        notice2 = issue_notice(
            make_draft_notice(parcel2["id"], [def2["id"]])["id"])
        app2 = validate_success(api.create_application(
            create_application_payload(notice2["id"], parcel2["id"],
                                       cycle["id"], 50),
            make_owner_headers(owner["id"])), 201)

        rows, _ = validate_paginated(
            api.list_parcels(COORD, params={"owner_id": owner["id"]}))
        assert len(rows) == 2

        rows, _ = validate_paginated(
            api.list_segments(COORD, params={"parcel_id": parcel1["id"]}))
        assert len(rows) == 1 and rows[0]["id"] == seg1["id"]

        rows, _ = validate_paginated(api.list_defects(
            COORD, params={"segment_id": seg2["id"], "status": "UNDER_REPAIR"}))
        assert len(rows) == 1 and rows[0]["id"] == def2["id"]

        rows, _ = validate_paginated(api.list_repair_notices(
            COORD, params={"parcel_id": parcel1["id"], "status": "ISSUED"}))
        assert len(rows) == 1 and rows[0]["id"] == notice1["id"]

        rows, _ = validate_paginated(api.list_applications(
            COORD, params={"parcel_id": parcel2["id"]}))
        assert len(rows) == 1 and rows[0]["id"] == app2["id"]
