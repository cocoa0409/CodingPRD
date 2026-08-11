"""Ceremony foundation: creation defaults, system-managed fields, response
envelope shape, authentication, role authorization, and ceremony OCC."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, is_valid_uuid,
    is_iso8601_timestamp, NON_EXISTENT_UUID, ApiErrorId,
    create_venue_payload, create_ceremony_payload, create_graduate_payload,
    create_venue, create_ceremony, import_graduate, get_ceremony,
    make_graduate_headers, TEST_USERS,
)

CHAIR = TEST_USERS["committee_chair_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
COORDINATOR = TEST_USERS["venue_coordinator_headers"]


class TestCeremonyCreationDefaults:
    def test_ceremony_create_defaults_applied(self, api):
        """PRD §3.1: "A new ceremony starts in `PLANNING` posture with `FAIR`
        weather, and its pools are initialized immediately from the primary
        venue: `effective_capacity` and `open_seat_count` both start at the
        venue's `total_capacity`, `ticket_pool_total` is the capacity
        multiplied by the `ticket_ratio` rounded down, and
        `ticket_pool_remaining` starts equal to the pool total."

        Design: Corner/entities/ceremony_create_defaults_applied
        """
        venue = create_venue(total_capacity=10, accessible_capacity=2)
        res = api.create_ceremony(
            create_ceremony_payload(venue["id"], name="Fall Commencement",
                                    ticket_ratio=1.5), CHAIR)
        ceremony = validate_success(res, 201)
        assert ceremony["readiness_posture"] == "PLANNING"
        assert ceremony["weather_mode"] == "FAIR"
        assert ceremony["rehearsal_required"] is True
        assert ceremony.get("rain_venue_id") is None
        assert ceremony["effective_capacity"] == 10
        assert ceremony["ticket_pool_total"] == 15  # floor(10 * 1.5)
        assert ceremony["ticket_pool_remaining"] == 15
        assert ceremony["open_seat_count"] == 10

    def test_venue_create_system_fields_input_ignored(self, api):
        """PRD §2.4: "The `id` is a server-minted UUID with no type prefix."
        PRD §2.4: "The `version` is an integer that increments by exactly one
        on every mutation of the resource".

        Design: Corner/entities/venue_create_system_fields_input_ignored
        """
        supplied_id = "11111111-2222-4333-8444-555555555555"
        payload = create_venue_payload(name="System Hall", address="9 College Ave",
                                       total_capacity=20, accessible_capacity=2)
        payload["id"] = supplied_id
        payload["version"] = 99
        res = api.create_venue(payload, COORDINATOR)
        venue = validate_success(res, 201)
        assert venue["id"] != supplied_id, "server must mint its own UUID id"
        assert is_valid_uuid(venue["id"])
        assert venue["version"] == 1, f"new resource must start at version 1, got {venue['version']}"
        assert is_iso8601_timestamp(venue["created_at"])
        assert is_iso8601_timestamp(venue["updated_at"])

    def test_graduate_create_missing_required_returns_invalid_request(self, api):
        """PRD §2.11: "Body schema — required fields present, types valid, enum
        values inside their declared domains, and ranges valid (a requested
        ticket count of at least one, an `end_utc` strictly after its
        `start_utc`, capacities of at least one, amounts of at least zero),
        else `ERR_INVALID_REQUEST`."
        PRD §3.2: "Each import names the `ceremony_id`, the student's
        `full_name` (the legal name that becomes the default printed name on
        the diploma) and `email`".

        Design: Corner/entities/graduate_create_missing_required_returns_invalid_request
        """
        venue = create_venue()
        ceremony = create_ceremony(venue["id"])
        payload = create_graduate_payload(ceremony["id"], full_name="No Ceremony")
        del payload["ceremony_id"]
        res = api.create_graduate(payload, REGISTRAR)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_graduate_honor_tier_input_ignored(self, api):
        """PRD §3.2: "The new graduate starts in `PENDING_AUDIT` status with
        `honor_tier` `NONE`, `honor_basis` `NONE`, a `conduct_strike_count` of
        zero, and `walk_privilege_revoked` false."

        Design: Corner/entities/graduate_honor_tier_input_ignored
        """
        venue = create_venue()
        ceremony = create_ceremony(venue["id"])
        payload = create_graduate_payload(ceremony["id"], full_name="Claim Chuck")
        payload["honor_tier"] = "SUMMA_CUM_LAUDE"
        res = api.create_graduate(payload, REGISTRAR)
        graduate = validate_success(res, 201)
        assert graduate["honor_tier"] == "NONE", "client-supplied computed field must be ignored"
        assert graduate["honor_basis"] == "NONE"
        assert graduate["status"] == "PENDING_AUDIT"

    def test_graduate_get_not_found_returns_not_found(self, api):
        """PRD §2.11: "Path existence — path-templated resources are resolved
        left to right along the URL, and the first missing resource yields
        `ERR_NOT_FOUND`."

        Design: Corner/entities/graduate_get_not_found_returns_not_found
        """
        res = api.get_graduate(NON_EXISTENT_UUID, REGISTRAR)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        assert res.status_code == 404

    def test_graduates_list_pagination(self, api):
        """PRD §2.3: "All list endpoints accept the query parameters `limit`
        and `offset`."
        PRD §2.3: "List responses order their items by `created_at` ascending,
        and the `meta` object of a list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/graduates_list_pagination
        """
        venue = create_venue()
        ceremony = create_ceremony(venue["id"])
        for i in range(3):
            import_graduate(ceremony["id"], full_name=f"P {i}",
                            email=f"p{i}@x.edu")

        page1, meta1 = validate_paginated(
            api.list_ceremony_graduates(ceremony["id"], REGISTRAR,
                                        params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_ceremony_graduates(ceremony["id"], REGISTRAR,
                                        params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestResponseEnvelope:
    def test_response_envelope_success_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `data` field contains the resource object or an array of
        resource objects."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        venue = create_venue()
        ceremony = create_ceremony(venue["id"])
        res = api.get_ceremony(ceremony["id"], CHAIR)
        data = validate_success(res, 200)
        body = res.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert data["id"] == ceremony["id"]
        assert data["version"] == 1

    def test_response_envelope_error_shape(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.11: "Path existence — path-templated resources are resolved left
        to right along the URL, and the first missing resource yields
        `ERR_NOT_FOUND`."

        Design: Corner/endpoints/response_envelope_error_shape
        """
        res = api.get_ceremony(NON_EXISTENT_UUID, CHAIR)
        error = validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        body = res.json()
        assert body["response_type"] == "error"
        assert error["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(error["message"], str) and len(error["message"]) > 0
        assert res.status_code == 404


class TestAccessEnforcement:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose headers are missing, or whose
        `X-User-Role` value is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        res = api.get_ceremony(NON_EXISTENT_UUID, headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
        assert res.status_code == 401

    def test_graduate_cannot_create_ceremony_returns_unauthorized(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed
        among the roles authorized for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "A `CommitteeChair` owns the ceremony lifecycle (creation,
        configuration, audit open/lock/reopen, readiness, commencement,
        completion), runs the ticket waterfall, decides appeals, approves
        reader cards, fulfills regalia, issues diplomas, and manages vendor
        contracts."

        Design: Corner/validations/graduate_cannot_create_ceremony_returns_unauthorized
        """
        venue = create_venue()
        ceremony = create_ceremony(venue["id"])
        graduate = import_graduate(ceremony["id"], full_name="Role Rhonda")
        res = api.create_ceremony(
            create_ceremony_payload(venue["id"], name="Rogue Ceremony",
                                    ceremony_date="2026-06-02T15:00:00Z"),
            make_graduate_headers(graduate["id"]))
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert res.status_code == 403


class TestCeremonyOptimisticConcurrency:
    def test_occ_ceremony_patch_stale_returns_412(self, api):
        """PRD §2.6: "Updating a ceremony's configuration requires
        `expected_ceremony_version`, matched against the ceremony's current
        `version`. If any intervening write — a configuration update or any
        lifecycle action — has advanced the ceremony's version since the client
        last read it, the update is rejected, so the client never overwrites a
        configuration it has not observed."
        PRD §2.6: "if that value does not equal the target entity's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_ceremony_patch_stale_returns_412
        """
        venue = create_venue()
        ceremony = create_ceremony(venue["id"])
        assert ceremony["version"] == 1

        first = validate_success(
            api.patch_ceremony(ceremony["id"],
                               {"expected_ceremony_version": 1,
                                "guest_ticket_base_cap": 5}, CHAIR), 200)
        assert first["version"] == 2
        assert first["guest_ticket_base_cap"] == 5

        res = api.patch_ceremony(ceremony["id"],
                                 {"expected_ceremony_version": 1,
                                  "honor_bonus_tickets": 3}, CHAIR)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        assert res.status_code == 412

        after = get_ceremony(ceremony["id"])
        assert after["honor_bonus_tickets"] == 2, "stale PATCH must not apply"
        assert after["guest_ticket_base_cap"] == 5
