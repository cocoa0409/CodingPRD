"""Grant creation defaults, registry rules, and pagination (PRD §2.2-§2.4, §3.1-§3.2)."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_grant,
    assert_school,
    build_user_headers,
    create_grant_payload,
    is_valid_uuid,
    open_grant,
    register_school,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = build_user_headers("director-1", "FederalProgramsDirector")
ANALYST = build_user_headers("analyst-1", "ComplianceAnalyst")


class TestGrantCreation:

    def test_grant_creation_defaults_and_system_fields(self):
        """PRD §3.1: "The new grant enters `SETUP` with `carryover_waiver_status`
        at `NONE`, `ranking_version` at 0, `monitoring_clearance` at
        `NOT_MONITORED`, and both ledger totals at zero. The system immediately
        derives `net_allocable_cents` as the total allocation plus the carryover
        in minus the administrative reserve, and it recomputes the provisional
        carryover fields described in §3.10 on every subsequent fiscal event."
        PRD §3.1: "optionally `carryover_in_cents` from the prior year
        (defaulting to zero, never negative), `admin_reserve_cents` taken off
        the top for district-level administration (defaulting to zero, never
        negative, and never exceeding the sum of the total allocation and the
        carryover in), and `equitable_count_method`, which selects the
        equitable-services share variant and defaults to `CONSULTATION_AGREED`
        (the alternative is `VERIFIED_COUNT`)."
        PRD §2.4: "`id` (string): A unique, server-generated identifier
        formatted as a UUID, with no type prefix." and "`created_at` (string):
        An ISO 8601 UTC timestamp with three fractional digits (e.g.,
        `2025-05-24T10:30:00.123Z`) recording when the resource was first
        created."

        Design: Corner/entities/grant_creation_defaults_and_system_fields
        """
        resp = api_client.create_grant(
            create_grant_payload(fiscal_year=2051,
                                 total_allocation_cents=8_000_000,
                                 poverty_measure="MEDICAID_DIRECT_CERT"),
            DIRECTOR,
        )
        data = validate_success(resp, expected_status=201)
        assert_grant(data)
        assert data["carryover_in_cents"] == 0, "carryover_in_cents default"
        assert data["admin_reserve_cents"] == 0, "admin_reserve_cents default"
        assert data["equitable_count_method"] == "CONSULTATION_AGREED", \
            "equitable_count_method default"
        assert data["status"] == "SETUP"
        assert data["ranking_version"] == 0
        assert data["monitoring_clearance"] == "NOT_MONITORED"
        assert data["liquidated_cents"] == 0 and data["pending_cents"] == 0
        assert data["net_allocable_cents"] == 8_000_000
        assert is_valid_uuid(data["id"])
        # Three fractional digits on the creation timestamp (PRD §2.4 example).
        assert "." in data["created_at"], "created_at must carry fractions"
        frac = data["created_at"].split(".", 1)[1].rstrip("Z")
        assert len(frac) == 3, \
            f"created_at must have three fractional digits: {data['created_at']}"

    def test_grant_rejects_readonly_fields_returns_invalid_request(self):
        """PRD §2.8: "Fourth, body schema: required fields present, types
        correct, enum membership honored, charged amounts strictly positive,
        and no unknown or read-only fields supplied, all rejected as
        `ERR_INVALID_REQUEST` (HTTP 400); date-range inversions surface as
        `ERR_INVALID_DATE_RANGE` (HTTP 400) and sub-minimum narratives as
        `ERR_NARRATIVE_TOO_SHORT` (HTTP 400) at this same tier."
        PRD §2.4: "`version` (integer): A system-managed integer that
        increments with every modification to the resource, enabling
        optimistic concurrency control."

        Design: Corner/entities/grant_rejects_readonly_fields_returns_invalid_request
        """
        resp = api_client.create_grant(
            create_grant_payload(fiscal_year=2052,
                                 total_allocation_cents=1_000_000,
                                 poverty_measure="CENSUS_SAIPE",
                                 version=99),
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # No grant row created for that fiscal year.
        rows, meta = validate_paginated(
            api_client.list_grants(DIRECTOR, params={"fiscal_year": 2052}))
        assert meta["total_count"] == 0 and rows == []

    def test_get_missing_grant_returns_not_found(self):
        """PRD §2.8: "Third, existence: every resource id appearing in the
        path and every foreign-key id in the body must resolve, validated left
        to right — path parameters first, then body fields in their declared
        order — with the first miss rejected as `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_missing_grant_returns_not_found
        """
        resp = api_client.get_grant(
            "00000000-0000-4000-8000-000000000000", DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestSchoolRegistry:

    def test_school_list_pagination_defaults(self):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "List-based responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/school_list_pagination_defaults
        """
        for i in range(1, 12):
            register_school(f"S{i:02d}", f"100{i:03d}")
        page1, meta1 = validate_paginated(api_client.list_schools(ANALYST))
        assert len(page1) == 10, "default limit splits 11 rows into 10 + 1"
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10 and meta1["offset"] == 0
        for row in page1:
            assert_school(row)
        page2, meta2 = validate_paginated(
            api_client.list_schools(ANALYST, params={"offset": 10}))
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 11
        # PRD §2.3: "all list endpoints return resources sorted by their
        # creation timestamp in ascending order."
        assert page2[0]["nces_id"] == "100011"

    def test_duplicate_fiscal_year_rejected(self):
        """PRD §3.1: "the `fiscal_year` (unique across all grants and between
        2020 and 2100 inclusive)" and "Creating a second grant for an
        already-used `fiscal_year` is rejected with
        `ERR_DUPLICATE_FISCAL_YEAR`."

        Design: Corner/errors/duplicate_fiscal_year_rejected
        """
        open_grant(2069, 5_000_000)
        resp = api_client.create_grant(
            create_grant_payload(fiscal_year=2069,
                                 total_allocation_cents=7_000_000,
                                 poverty_measure="MEDICAID_DIRECT_CERT"),
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FISCAL_YEAR)

    def test_close_out_from_setup_returns_invalid_state(self):
        """PRD §3.10: "Close-out is the director's final act on the grant,
        moving it from `ALLOCATED` to the terminal `CLOSED_OUT`, and four
        gates guard it beyond the state check itself."
        PRD §3.1: "Any operation whose grant-state precondition fails is
        rejected with `ERR_GRANT_INVALID_STATE`."

        Design: Corner/state_machines/close_out_from_setup_returns_invalid_state
        """
        grant = open_grant(2054, 5_000_000)
        resp = api_client.close_out(grant["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_GRANT_INVALID_STATE)
        after = validate_success(api_client.get_grant(grant["id"], DIRECTOR))
        assert after["status"] == "SETUP", "grant must stay SETUP"


class TestAuthContext:

    def test_missing_auth_header_rejected(self):
        """PRD §2.1: "Each request must include `X-User-ID` to identify the
        acting user and `X-User-Role` to specify their operational capacity."
        and "Failure to provide both headers, or supplying a role the system
        does not recognize, results in an
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        # No identity headers at all.
        resp = api_client.list_grants(headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        # A role the system does not recognize.
        resp = api_client.list_grants(
            headers=build_user_headers("user-9", "SuperUser"))
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
