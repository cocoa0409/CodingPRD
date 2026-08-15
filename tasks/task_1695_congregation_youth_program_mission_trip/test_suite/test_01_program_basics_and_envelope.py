"""Program creation, system-managed fields, response envelope, pagination,
and the destination-type insurance-tier derivation."""
from test_helpers import (
    ApiErrorId,
    assert_program,
    assert_same_instant,
    assert_trip,
    create_program,
    create_program_payload,
    create_trip,
    is_valid_uuid,
    make_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = make_director_headers()
MISSING = "11111111-1111-4111-8111-111111111111"


class TestProgramPolicyDefaults:
    def test_program_create_applies_policy_defaults(self, api):
        """PRD §3.1: "`max_award_pct_bp` (the maximum award as basis points of a
        registration's cost basis, defaulting to 5000 and bounded between 0 and
        10000), `per_registration_cap_cents` (an absolute cap on any single award,
        defaulting to 150000 cents and never negative), and
        `default_chaperone_ratio` (the maximum number of youth per cleared
        chaperone, defaulting to 5 and at least 1)."
        PRD §3.1: "A new program starts `OPEN` with its scholarship fund triple
        initialized: `scholarship_reserved_cents` at 0, `scholarship_disbursed_cents`
        at 0, and `scholarship_available_cents` equal to the total pool."

        Design: Corner/entities/program_create_applies_policy_defaults
        """
        resp = api.create_program(
            create_program_payload(scholarship_fund_total_cents=250000),
            DIRECTOR)
        data = validate_success(resp, 201)
        assert_program(data)
        assert data["max_award_pct_bp"] == 5000
        assert data["per_registration_cap_cents"] == 150000
        assert data["default_chaperone_ratio"] == 5
        assert data["status"] == "OPEN"
        assert data["scholarship_reserved_cents"] == 0
        assert data["scholarship_disbursed_cents"] == 0
        assert data["scholarship_available_cents"] == 250000


class TestSystemMintedFields:
    def test_server_minted_system_fields_on_create(self, api):
        """PRD §2.5: "`id`: a server-minted UUID with no type prefix.
        `created_at`: an ISO 8601 UTC timestamp with three fractional digits,
        fixed at creation. `updated_at`: an ISO 8601 UTC timestamp refreshed on
        every mutation."
        PRD §2.4: "Before any operator sets it, the clock reads exactly
        `2026-08-01T00:00:00Z`" and "The system never reads the wall clock."

        Design: Corner/entities/server_minted_system_fields_on_create
        """
        program = create_program(name="Minted", scholarship_fund_total_cents=1000)
        # assert_program pins the id shape and the three-fractional-digit
        # created_at/updated_at format from the common-fields rule.
        assert_program(program)
        assert is_valid_uuid(program["id"])
        assert program["created_at"] == program["updated_at"], (
            "created_at and updated_at coincide at creation")
        assert_same_instant(program["created_at"], "2026-08-01T00:00:00Z",
                            "created_at")


class TestResponseEnvelope:
    def test_response_envelope_success_error_and_pagination_shapes(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources." and "The `api_request_id` is a
        server-generated unique identifier for the request that starts with
        `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error. The `message` provides a human-readable
        explanation of what went wrong."
        PRD §2.3: "the `meta` object of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/response_envelope_success_error_and_pagination_shapes
        """
        # success envelope on an object response
        resp = api.create_program(
            create_program_payload(name="Envelope"),
            DIRECTOR)
        body = resp.json()
        assert resp.status_code == 201
        assert body["response_type"] == "object"
        assert isinstance(body["data"], dict) and body["data"]["id"]
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        # error envelope
        err_resp = api.get_program(MISSING, DIRECTOR)
        err = validate_error(err_resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND)
        assert err_resp.status_code == 404
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert isinstance(err_body["meta"]["api_request_id"], str)

        # list envelope
        list_resp = api.list_trips(DIRECTOR)
        data, meta = validate_paginated(list_resp)
        assert list_resp.json()["response_type"] == "array"
        assert isinstance(data, list)
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"list meta missing {field}"


class TestListPagination:
    def test_list_pagination_limit_offset_has_more(self, api):
        """PRD §2.3: "`limit` caps the number of returned items: it defaults to 10
        when omitted, may not be less than 1, and may not exceed 100. `offset` says
        how many items to skip and defaults to 0. Every list response is sorted by
        `created_at` in ascending order unless explicitly stated otherwise, and the
        `meta` object of a list response carries `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/entities/list_pagination_limit_offset_has_more
        """
        program = create_program()
        for name in ("T1", "T2", "T3"):
            create_trip(program["id"], name=name)

        page1, meta1 = validate_paginated(
            api.list_trips(DIRECTOR, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_trips(DIRECTOR, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        default_page, default_meta = validate_paginated(
            api.list_trips(DIRECTOR))
        assert len(default_page) == 3
        assert default_meta["limit"] == 10
        assert default_meta["offset"] == 0
        assert default_meta["has_more"] is False


class TestInsuranceTierDerivation:
    def test_trip_required_insurance_tier_derived_from_destination_type(self, api):
        """PRD §3.2: "The destination type determines the `required_insurance_tier`
        stamped on the trip: `NONE` for in-state, `DOMESTIC` for out-of-state, and
        `INTERNATIONAL` for international travel."

        Design: Corner/entities/trip_required_insurance_tier_derived_from_destination_type
        """
        program = create_program()
        cases = [
            ("IN_STATE", "NONE"),
            ("OUT_OF_STATE", "DOMESTIC"),
            ("INTERNATIONAL", "INTERNATIONAL"),
        ]
        for destination_type, expected_tier in cases:
            trip = create_trip(program["id"], name=f"T-{destination_type}",
                               destination_type=destination_type,
                               start_date="2027-06-15", end_date="2027-06-16",
                               emergency_protocol_text="")
            assert_trip(trip)
            assert trip["required_insurance_tier"] == expected_tier, (
                f"{destination_type} must stamp {expected_tier}, "
                f"got {trip['required_insurance_tier']}")
