"""Roster admission defaults, expert reads, roster maintenance errors, auth."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    assert_expert, ApiErrorId,
    create_expert_payload, create_expert, set_clock,
    TEST_USERS, make_expert_headers,
    setup_scenario,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["case_manager_headers"]


class TestExpertAdmission:

    def test_minimal_create_applies_roster_defaults(self, api):
        """PRD §3.1: "both integers that default to 0 and may never be negative" and
        "`max_concurrent_engagements`, an integer of at least 1 defaulting to 5" and
        "A newly admitted expert's `roster_status` begins at `ACTIVE`, and both computed
        ratings — `rating_simple` and `rating_decayed` — read 0.0 until evaluations exist."

        Design: Corner/entities/expert_creation_applies_defaults
        """
        res = api.create_expert(create_expert_payload(full_name="Default Dan", specialty_area="med"), ADMIN)
        expert = validate_success(res, 201)
        assert_expert(expert)
        assert expert["roster_status"] == "ACTIVE"
        assert expert["daubert_challenge_count"] == 0
        assert expert["daubert_exclusion_count"] == 0
        assert expert["max_concurrent_engagements"] == 5

        fetched = validate_success(api.get_expert(expert["id"], ADMIN), 200)
        assert fetched["roster_status"] == "ACTIVE"
        assert fetched["rating_simple"] == 0.0
        assert fetched["rating_decayed"] == 0.0
        assert fetched["evaluation_count"] == 0
        assert fetched["active_engagement_count"] == 0

    def test_computed_rating_field_input_ignored(self, api):
        """PRD §3.1: "both computed ratings — `rating_simple` and `rating_decayed` — read
        0.0 until evaluations exist."

        Design: Corner/entities/expert_create_computed_field_input_ignored
        """
        res = api.create_expert(
            create_expert_payload(full_name="Inflated Ivy", specialty_area="med",
                                  rating_decayed=9.9),
            ADMIN)
        expert = validate_success(res, 201)
        fetched = validate_success(api.get_expert(expert["id"], ADMIN), 200)
        assert fetched["rating_decayed"] == 0.0, (
            "client-supplied computed field must not override the server's 0.0")

    def test_get_unknown_expert_returns_not_found(self, api):
        """PRD §2.11: "the system resolves each identifier in path order and rejects the
        request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
        resolve to an existing resource".

        Design: Corner/entities/expert_get_not_found_returns_404
        """
        res = api.get_expert(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_expert_search_pagination_and_specialty_filter(self, api):
        """PRD §3.1: "Sourcing staff search the roster with optional `specialty_area` and
        `roster_status` filters, paginated by `limit` and `offset`."
        PRD §2.3: "Paginated and non-paginated list-based responses include the following
        fields in the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/expert_list_pagination_envelope
        """
        for name, spec in [("P1", "med"), ("P2", "med"), ("P3", "econ")]:
            create_expert(full_name=name, specialty_area=spec)

        data, meta = validate_paginated(api.list_experts(CM, params={"limit": 2, "offset": 0}))
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(data) == 2

        data, meta = validate_paginated(api.list_experts(CM, params={"specialty_area": "econ"}))
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert data[0]["specialty_area"] == "econ"

    def test_roster_status_invalid_enum_rejected(self, api):
        """PRD §2.11: "then the request body shape is checked — required fields present,
        types correct, enum members valid — with violations yielding `ERR_INVALID_REQUEST`
        (HTTP 400)".
        PRD §3.1: "Standing on the roster is a state machine over `ACTIVE`, `PROBATION`,
        and `REMOVED`."

        Design: Corner/entities/roster_status_invalid_enum_rejected
        """
        expert = create_expert(full_name="Enum Eve")
        res = api.set_roster_status(expert["id"], {"to_status": "FROZEN", "rationale": "bad"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestRosterRemovalGuard:

    def test_remove_blocked_while_signed_engagement_exists(self, api):
        """PRD §3.1: "Removal is blocked while the expert's `active_engagement_count` is
        greater than zero, failing with `ERR_EXPERT_HAS_ACTIVE_ENGAGEMENTS`" and
        "because `SIGNED` and `ACTIVE` engagements both count, activating an engagement
        never changes `active_engagement_count`, while signing, terminating, and closing do."

        Design: Corner/errors/expert_remove_with_active_engagement_rejected
        """
        sc = setup_scenario(target_state="SIGNED", fund=False)
        expert = sc["expert"]

        res = api.set_roster_status(
            expert["id"], {"to_status": "REMOVED", "rationale": "cleanup"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_EXPERT_HAS_ACTIVE_ENGAGEMENTS)

        fetched = validate_success(api.get_expert(expert["id"], ADMIN), 200)
        assert fetched["roster_status"] == "ACTIVE"
        assert fetched["active_engagement_count"] == 1


class TestAuthentication:

    def test_missing_headers_rejected_unauthenticated(self, api):
        """PRD §2.1: "A request whose headers are missing, or whose role header is not one
        of these declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/expert_list_missing_header_unauthenticated
        """
        res = api.list_experts(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
