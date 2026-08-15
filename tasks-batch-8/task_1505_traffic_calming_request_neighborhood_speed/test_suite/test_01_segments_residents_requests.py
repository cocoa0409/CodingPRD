"""Registration and filing: segment/resident/request creation rules, lookup
errors, and list pagination (PRD §2.3, §2.9, §3.1, §3.2)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_request,
    assert_resident,
    assert_segment,
    assert_timestamp_equals,
    create_request_payload,
    create_resident,
    create_resident_payload,
    create_segment,
    file_request,
    is_valid_uuid,
    make_resident_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSegmentRegistration:
    def test_create_segment_applies_documented_defaults(self):
        """PRD §3.1: "`emergency_route` marks a designated emergency response route and defaults to false; `crash_count_3yr` records reported crashes on the segment over the trailing three years and defaults to 0; and `pedestrian_generator_count` counts adjacent pedestrian generators such as schools, parks, and transit stops, likewise defaulting to 0."
        PRD §2.4: "Every system-stamped timestamp in this document — `petition_opened_at`, `signed_at`, `submitted_at`, `approved_at`, `published_at`, `installed_at`, `cast_at`, and the rest — is taken from this logical clock at the moment the event occurs."

        Design: Corner/entities/create_segment_applies_defaults
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.create_segment(
            {
                "name": "Default Ave",
                "speed_limit_mph": 25,
                "household_count": 12,
                "functional_class": "LOCAL",
            },
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert_segment(data)
        assert data["emergency_route"] is False, (
            f"omitted emergency_route must default to false, got {data['emergency_route']}"
        )
        assert data["crash_count_3yr"] == 0, (
            f"omitted crash_count_3yr must default to 0, got {data['crash_count_3yr']}"
        )
        assert data["pedestrian_generator_count"] == 0, (
            "omitted pedestrian_generator_count must default to 0, "
            f"got {data['pedestrian_generator_count']}"
        )
        assert_timestamp_equals(
            data["created_at"], "2026-08-01T00:00:00Z", "created_at"
        )

    def test_create_segment_invalid_functional_class_rejected(self):
        """PRD §3.1: "A registration that violates these bounds — a speed limit below 15, a missing required field, a wrong-typed value, or an unrecognized classification — is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_segment_invalid_enum_returns_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.create_segment(
            {
                "name": "Bad Ave",
                "speed_limit_mph": 25,
                "household_count": 12,
                "functional_class": "HIGHWAY",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestResidentRegistration:
    def test_create_resident_duplicate_email_rejected(self):
        """PRD §3.1: "A resident record carries a `full_name`, an `email` that must be unique across every registered resident citywide — a duplicate is rejected with `ERR_DUPLICATE_RESIDENT_EMAIL`"

        Design: Corner/entities/create_resident_duplicate_email_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        seg1 = create_segment(name="Dup S1", speed_limit_mph=25, household_count=5)
        seg2 = create_segment(name="Dup S2", speed_limit_mph=25, household_count=5)
        create_resident(seg1["id"], "First", "dup@example.com", "H1")
        resp = api_client.create_resident(
            create_resident_payload(
                full_name="Second",
                email="dup@example.com",
                street_segment_id=seg2["id"],
                household_ref="H9",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESIDENT_EMAIL)

    def test_create_resident_duplicate_household_scoped_to_segment(self):
        """PRD §3.1: "a `household_ref`, typically a street address, that must be unique within that segment; two residents of the same segment cannot share a household reference, and a collision is rejected with `ERR_DUPLICATE_HOUSEHOLD`."

        Design: Corner/entities/create_resident_duplicate_household_on_segment_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        seg1 = create_segment(name="HH S1", speed_limit_mph=25, household_count=5)
        seg2 = create_segment(name="HH S2", speed_limit_mph=25, household_count=5)
        create_resident(seg1["id"], "First", "hh-1@example.com", "H1")
        # Same segment, same household_ref -> conflict.
        resp = api_client.create_resident(
            create_resident_payload(
                full_name="SameHouse",
                email="hh-2@example.com",
                street_segment_id=seg1["id"],
                household_ref="H1",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_HOUSEHOLD)
        # Different segment, same household_ref -> allowed (uniqueness is segment-scoped).
        resp_ok = api_client.create_resident(
            create_resident_payload(
                full_name="OtherSeg",
                email="hh-3@example.com",
                street_segment_id=seg2["id"],
                household_ref="H1",
            ),
            ADMIN,
        )
        data = validate_success(resp_ok, expected_status=201)
        assert_resident(data)


class TestRequestFiling:
    def test_create_request_missing_required_budget_rejected(self):
        """PRD §3.2: "A `Resident` enters the program by filing a traffic calming request against their own segment, supplying the `street_segment_id`, a short `title`, and `requested_budget_cents`"
        PRD §2.10: "Malformed payloads — a missing required field, a wrong type, an invalid enum value, a non-positive amount, an end date before its start date — fail with `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/create_request_missing_required_field_returns_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        seg = create_segment(name="Req Ave", speed_limit_mph=25, household_count=5)
        resident = create_resident(seg["id"], "R1", "rq-r1@example.com", "H1")
        resp = api_client.create_request(
            {"street_segment_id": seg["id"], "title": "No budget given"},
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_request_ignores_client_supplied_system_fields(self):
        """PRD §2.5: "`id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix."
        PRD §3.2: "The filing resident's identity comes from the headers, not the payload: `created_by_resident_id` is set to the caller's `X-User-ID`, and the request is born in `SUBMITTED`."

        Design: Corner/entities/create_request_system_fields_input_ignored
        """
        set_clock("2026-08-01T00:00:00Z")
        seg = create_segment(name="Sys Ave", speed_limit_mph=25, household_count=5)
        resident = create_resident(seg["id"], "R1", "sys-r1@example.com", "H1")
        supplied_id = "00000000-0000-0000-0000-0000000000ff"
        resp = api_client.create_request(
            create_request_payload(
                street_segment_id=seg["id"],
                title="Ignore my fields",
                requested_budget_cents=12345,
                id=supplied_id,
                version=99,
                status="FUNDED",
                created_by_resident_id="forged",
            ),
            make_resident_headers(resident["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_request(data)
        assert data["id"] != supplied_id, "server must mint its own UUID"
        assert is_valid_uuid(data["id"])
        assert data["status"] == "SUBMITTED", (
            f"client-supplied status must be ignored, got {data['status']}"
        )
        assert data["created_by_resident_id"] == resident["id"], (
            "created_by_resident_id must come from X-User-ID, "
            f"got {data['created_by_resident_id']}"
        )

    def test_create_request_on_arterial_segment_rejected(self):
        """PRD §3.2: "the program accepts no requests at all for `ARTERIAL` segments, which are rejected with `ERR_SEGMENT_NOT_ELIGIBLE`."

        Design: Corner/entities/create_request_arterial_segment_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        seg = create_segment(
            name="Arterial Rd",
            speed_limit_mph=45,
            household_count=20,
            functional_class="ARTERIAL",
        )
        resident = create_resident(seg["id"], "R1", "art-r1@example.com", "H1")
        resp = api_client.create_request(
            create_request_payload(
                street_segment_id=seg["id"],
                title="Calm the arterial",
                requested_budget_cents=50000,
            ),
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_ELIGIBLE)

    def test_create_second_active_request_on_segment_rejected(self):
        """PRD §3.2: "a segment may host only one live request at a time: if another request for the same segment sits in any non-terminal stage, the filing fails with `ERR_ACTIVE_REQUEST_EXISTS`."

        Design: Corner/entities/create_request_second_active_on_segment_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        seg = create_segment(name="Busy Ave", speed_limit_mph=25, household_count=5)
        resident = create_resident(seg["id"], "R1", "busy-r1@example.com", "H1")
        file_request(seg["id"], resident["id"], title="First",
                     requested_budget_cents=10000)
        resp = api_client.create_request(
            create_request_payload(
                street_segment_id=seg["id"],
                title="Second",
                requested_budget_cents=20000,
            ),
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_REQUEST_EXISTS)


class TestRequestLookupAndListing:
    def test_get_request_unknown_id_returns_404(self):
        """PRD §2.9: "An unknown segment identifier yields `ERR_SEGMENT_NOT_FOUND`; an unknown resident identifier yields `ERR_RESIDENT_NOT_FOUND`; then, in workflow order, `ERR_REQUEST_NOT_FOUND`, `ERR_SIGNATURE_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, and `ERR_REMOVAL_REQUEST_NOT_FOUND`."

        Design: Corner/entities/request_not_found_returns_404
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.get_request(
            "11111111-2222-3333-4444-555555555555", ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_FOUND)

    def test_list_requests_pagination_pages(self):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to 10, and callers may ask for as few as 1 and as many as 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0."
        PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/list_requests_pagination_and_status_filter
        """
        set_clock("2026-08-01T00:00:00Z")
        seg1 = create_segment(name="Pg S1", speed_limit_mph=25, household_count=5)
        seg2 = create_segment(name="Pg S2", speed_limit_mph=25, household_count=5)
        p1 = create_resident(seg1["id"], "P1", "pg-1@example.com", "H1")
        p2 = create_resident(seg2["id"], "P2", "pg-2@example.com", "H1")
        req1 = file_request(seg1["id"], p1["id"], title="Pg1",
                            requested_budget_cents=1000)
        req2 = file_request(seg2["id"], p2["id"], title="Pg2",
                            requested_budget_cents=2000)

        rows1, meta1 = validate_paginated(
            api_client.list_requests(ADMIN, params={"limit": 1, "offset": 0})
        )
        assert len(rows1) == 1, f"page 1 must hold exactly 1 row, got {len(rows1)}"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1 and meta1["offset"] == 0

        rows2, meta2 = validate_paginated(
            api_client.list_requests(ADMIN, params={"limit": 1, "offset": 1})
        )
        assert len(rows2) == 1, f"page 2 must hold exactly 1 row, got {len(rows2)}"
        assert meta2["has_more"] is False
        assert {rows1[0]["id"], rows2[0]["id"]} == {req1["id"], req2["id"]}, (
            "the two pages must together cover both requests"
        )
