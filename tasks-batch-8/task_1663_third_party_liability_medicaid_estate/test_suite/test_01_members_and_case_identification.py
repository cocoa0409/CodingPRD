"""Member registration, case identification, listings, and episode dedupe (PRD §2.2–§2.4, §3.1–§3.2)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_member,
    assert_tpl_case,
    create_case,
    create_member,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
SPEC = TEST_USERS["specialist_headers"]


class TestMemberRegistration:
    def test_member_create_missing_medicaid_id_rejected(self, api):
        """PRD §3.1: "A `SystemAdmin` registers each Medicaid beneficiary as a Member by supplying the member's `medicaid_id` — the state Medicaid beneficiary identifier, unique across all members — together with the member's legal `full_name` and the two-letter `state_code` of the member's Medicaid program."
        PRD §2.8: "Request-body shape: required fields present, enum values valid, amounts positive where the workflow requires a positive amount, and fee fractions inside their allowed interval — failure is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/member_create_missing_required_returns_invalid_request
        """
        resp = api.create_member(
            {"full_name": "No Id", "state_code": "CA"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api.list_cases(SPEC))
        assert data == [] and meta["total_count"] == 0, (
            "A rejected registration must not persist anything"
        )

    def test_member_create_ignores_client_supplied_system_fields(self, api):
        """PRD §2.4: "`id` (string): a unique, server-minted identifier for the resource, formatted as a UUID with no type prefix."
        PRD §2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, indicating when the resource was first created."

        Design: Corner/entities/member_create_system_field_input_ignored
        """
        supplied_id = "11111111-1111-1111-1111-111111111111"
        supplied_created = "2020-01-01T00:00:00.000Z"
        resp = api.create_member(
            {
                "medicaid_id": "M-SF-1",
                "full_name": "Sys Fields",
                "state_code": "CA",
                "id": supplied_id,
                "version": 9,
                "created_at": supplied_created,
            },
            ADMIN,
        )
        member = validate_success(resp, 201)
        assert_member(member)
        assert member["id"] != supplied_id, (
            "The server must mint its own id, ignoring the client-supplied one"
        )
        assert member["created_at"] != supplied_created, (
            "created_at must record when the resource was first created"
        )
        assert member["medicaid_id"] == "M-SF-1"


class TestCaseLookup:
    def test_get_case_nonexistent_returns_not_found(self, api):
        """PRD §2.10: "The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not name an existing resource, and no later check runs"

        Design: Corner/entities/entity_get_nonexistent_returns_not_found
        """
        resp = api.get_case(NON_EXISTENT_UUID, SPEC)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestCaseListing:
    def test_list_cases_pagination_envelope_defaults(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0."
        PRD §2.3: "List responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_endpoint_pagination_envelope_defaults
        """
        member = create_member(state_code="CA")
        create_case(member["id"], injury_date="2026-01-01")
        resp = api.list_cases(SPEC, params={"member_id": member["id"]})
        data, meta = validate_paginated(resp)
        assert isinstance(resp.json()["meta"]["api_request_id"], str)
        assert isinstance(resp.json()["meta"]["api_request_timestamp"], str)
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(data) == 1

    def test_list_cases_filter_by_member_id_scopes_results(self, api):
        """PRD §3.2: "Caseworkers can retrieve a case's claims as a list, and can list cases themselves filtered by `member_id` or `status`."

        Design: Corner/endpoints/list_filter_member_id_scopes_results
        """
        member_a = create_member(state_code="CA")
        member_b = create_member(state_code="CA")
        case_a = create_case(member_a["id"], injury_date="2026-01-01")
        case_b = create_case(member_b["id"], injury_date="2026-01-01")
        data, meta = validate_paginated(
            api.list_cases(SPEC, params={"member_id": member_a["id"]})
        )
        ids = [c["id"] for c in data]
        assert meta["total_count"] == 1, (
            f"member_id filter must scope results, got {meta['total_count']}"
        )
        assert ids == [case_a["id"]]
        assert case_b["id"] not in ids


class TestDuplicateEpisodeWindow:
    def test_overlapping_injury_date_inside_window_rejected(self, api):
        """PRD §3.2: "If the same member already has a non-terminal case — one not yet `RESOLVED`, `CLOSED_NO_RECOVERY`, or `SOL_EXPIRED` — and the new case's `injury_date` falls on or after the existing case's `injury_date` and before the calendar date ninety days after it, the identification is rejected with `ERR_DUPLICATE_EPISODE_CASE` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/duplicate_episode_half_open_window
        """
        member = create_member(state_code="CA", medicaid_id="M-OV-1")
        create_case(member["id"], injury_date="2026-01-01")
        # Day 89 of the half-open window [2026-01-01, 2026-04-01).
        resp = api.create_case(
            {
                "member_id": member["id"],
                "attorney_name": "Atty A",
                "attorney_email": "a@x.com",
                "injury_date": "2026-03-31",
                "third_party_insurer": "InsCo2",
            },
            SPEC,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EPISODE_CASE)

    def test_injury_date_exactly_ninety_days_after_permitted(self, api):
        """PRD §3.2: "The window is half-open: an `injury_date` exactly ninety days after the existing case's injury date is permitted."

        Design: Difficulty/resource_temporal_overlap/duplicate_episode_half_open_window
        """
        member = create_member(state_code="CA", medicaid_id="M-OV-1B")
        create_case(member["id"], injury_date="2026-01-01")
        resp = api.create_case(
            {
                "member_id": member["id"],
                "attorney_name": "Atty A",
                "attorney_email": "a@x.com",
                "injury_date": "2026-04-01",
                "third_party_insurer": "InsCo3",
            },
            SPEC,
        )
        case3 = validate_success(resp, 201)
        assert_tpl_case(case3)
        assert case3["status"] == "IDENTIFIED"
        data, meta = validate_paginated(
            api.list_cases(SPEC, params={"member_id": member["id"]})
        )
        assert meta["total_count"] == 2, (
            f"Both cases must exist after the permitted second identification, "
            f"got {meta['total_count']}"
        )
