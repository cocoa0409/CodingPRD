"""Registration, response envelope, schema validation, and ledger immutability.

Covers handler/animal/team creation defaults, the pagination envelope, the
authentication-context check, body-schema strictness, and the append-only
hour-credit ledger shape.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_animal_payload,
    create_handler_payload,
    create_request_ok,
    create_active_handler,
    create_forming_team,
    create_applicant_handler,
    post_adjustment,
    register_animal,
    make_handler_headers,
    validate_error,
    validate_paginated,
    validate_success,
    assert_hour_credit,
    is_valid_uuid,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


class TestRegistrationAndDefaults:
    def test_handler_creation_defaults(self):
        """PRD §3.1: "A new handler starts in `APPLICANT` status with `lifetime_minutes` at zero and `recognition_tier` `NONE`."
        PRD §2.5: "`id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/handler_creation_defaults
        """
        resp = api_client.create_handler(
            create_handler_payload(
                full_name="New H", email="new@example.org",
                region_code="WA", volunteer_since="2025-01-15",
            ),
            ANONYMOUS,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "APPLICANT", f"Expected APPLICANT, got {data['status']}"
        assert data["lifetime_minutes"] == 0, "lifetime_minutes must start at 0"
        assert data["recognition_tier"] == "NONE", "recognition_tier must start at NONE"
        assert is_valid_uuid(data["id"]), "id must be a bare UUID with no type prefix"
        assert isinstance(data["version"], int), "version must be a system-managed integer"

    def test_handler_missing_required_field_returns_invalid_request(self):
        """PRD §2.7: "Required fields are present, types match, enum values are within their declared sets (otherwise `ERR_INVALID_ENUM_VALUE`), unknown fields are rejected, minimum string lengths hold (an incident `description` runs at least ten characters), and date sanity holds — a start strictly before its end, `effective_from` on or before `effective_until`, `signed_on` not in the future, `approved_minutes` between zero and the scheduled minutes. Violations surface as `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A volunteer joins by self-registering — the one operation open to an `Anonymous` caller — supplying a legal `full_name`, a contact `email` that must be unique across handlers, a free-form two-letter home `region_code`, and the `volunteer_since` date marking when the volunteer first joined any program (this date later drives the experience component of match scoring); a `phone` number is optional."

        Design: Corner/entities/handler_missing_required_field_returns_invalid_request
        """
        resp = api_client.create_handler(
            {"full_name": "No Email", "region_code": "WA", "volunteer_since": "2025-01-15"},
            ANONYMOUS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_animal_invalid_species_returns_invalid_enum(self):
        """PRD §2.7: "Required fields are present, types match, enum values are within their declared sets (otherwise `ERR_INVALID_ENUM_VALUE`), unknown fields are rejected, minimum string lengths hold (an incident `description` runs at least ten characters), and date sanity holds — a start strictly before its end, `effective_from` on or before `effective_until`, `signed_on` not in the future, `approved_minutes` between zero and the scheduled minutes."
        PRD §3.1: "Registration supplies the animal's `name`, `species` (one of `DOG`, `CAT`, `RABBIT`, `GUINEA_PIG`, `BIRD`, `MINIATURE_HORSE`), `breed`, and `date_of_birth`; the server stamps the owning `handler_id` from the caller's `X-User-ID`, and the animal starts `REGISTERED`."

        Design: Corner/entities/animal_invalid_species_returns_invalid_enum
        """
        handler = create_active_handler(full_name="H E")
        resp = api_client.create_animal(
            create_animal_payload(
                name="Larry", species="LLAMA", breed="Alpaca cross",
                date_of_birth="2022-01-01",
            ),
            make_handler_headers(handler["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM_VALUE)

    def test_animal_get_not_found_returns_404(self):
        """PRD §2.7: "Each resource identifier in the path is resolved in left-to-right order, and the first missing one rejects the request with HTTP 404 and the corresponding identifier: `ERR_HANDLER_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_EVALUATOR_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_VACCINATION_RECORD_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_ORIENTATION_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOUR_CREDIT_NOT_FOUND`."

        Design: Corner/entities/animal_get_not_found_returns_404
        """
        resp = api_client.get_animal(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ANIMAL_NOT_FOUND)

    def test_visit_request_listing_pagination_and_envelope(self):
        """PRD §2.3: "`limit` sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at 100. `offset` sets the number of items skipped and defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/entities/visit_request_listing_pagination_and_envelope
        """
        fac_resp = api_client.create_facility(
            {
                "name": "Fac Pg", "facility_type": "SCHOOL", "region_code": "WA",
                "max_visit_minutes": 60, "allowed_species": ["DOG"],
                "min_liability_coverage_cents": 100_000_000,
                "max_overlapping_teams": 2, "visits_per_week_cap": 5,
            },
            ADMIN,
        )
        facility = validate_success(fac_resp, 201)
        fid = facility["id"]
        create_request_ok(fid, "2026-08-10T10:00:00Z", "2026-08-10T10:30:00Z",
                          visit_program="GENERAL", priority="ROUTINE")
        create_request_ok(fid, "2026-08-11T10:00:00Z", "2026-08-11T10:30:00Z",
                          visit_program="READING", priority="HIGH")
        create_request_ok(fid, "2026-08-12T10:00:00Z", "2026-08-12T10:30:00Z",
                          visit_program="REHAB", priority="URGENT")

        page1_resp = api_client.list_visit_requests(
            ADMIN, params={"facility_id": fid, "limit": 2, "offset": 0}
        )
        page1, meta1 = validate_paginated(page1_resp)
        assert len(page1) == 2, f"Page 1 should hold 2 rows, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        body1 = page1_resp.json()
        assert body1["response_type"] == "array", "List response_type must be array"
        assert isinstance(body1["meta"].get("api_request_id"), str)
        assert body1["meta"]["api_request_id"].startswith("req_")

        page2_resp = api_client.list_visit_requests(
            ADMIN, params={"facility_id": fid, "limit": 2, "offset": 2}
        )
        page2, meta2 = validate_paginated(page2_resp)
        assert len(page2) == 1, f"Page 2 should hold 1 row, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_hour_credit_ledger_rows_immutable(self):
        """PRD §2.5: "The hour-credit ledger row is the single exception. Because ledger rows are immutable once posted, an HourCredit carries only `id` and `created_at`; `updated_at` and `version` are absent from it."
        PRD §3.8: "Each row names its `handler_id`, links a `visit_id` unless it is an adjustment, carries its `kind` and signed `minutes`, and may carry a `note` — for an adjustment the `note` records the supplied `reason` label."

        Design: Corner/entities/hour_credit_ledger_rows_immutable
        """
        handler = create_active_handler(full_name="H HC")
        row = post_adjustment(handler["id"], 45, reason="seed")
        assert row["kind"] == "ADJUSTMENT"
        assert row["minutes"] == 45
        assert row["note"] == "seed"

        fetched = validate_success(api_client.get_hour_credit(row["id"], ADMIN))
        assert_hour_credit(fetched)


class TestAuthContextAndSchema:
    def test_missing_auth_headers_returns_400(self):
        """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the operational capacity in which that party acts. A request missing either header, or carrying a role value outside the declared role set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        handler = create_applicant_handler(full_name="H AH")
        resp = api_client.get_handler(handler["id"], {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_unknown_body_field_rejected(self):
        """PRD §2.7: "Required fields are present, types match, enum values are within their declared sets (otherwise `ERR_INVALID_ENUM_VALUE`), unknown fields are rejected, minimum string lengths hold (an incident `description` runs at least ten characters), and date sanity holds — a start strictly before its end, `effective_from` on or before `effective_until`, `signed_on` not in the future, `approved_minutes` between zero and the scheduled minutes. Violations surface as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/unknown_body_field_rejected
        """
        handler = create_active_handler(full_name="H UF")
        payload = create_animal_payload(name="D", species="DOG", breed="Beagle",
                                        date_of_birth="2021-01-01")
        payload["nickname"] = "Buddy"
        resp = api_client.create_animal(payload, make_handler_headers(handler["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestTeamUniquenessAndLifecycle:
    def test_second_team_for_animal_rejected(self):
        """PRD §3.1: "A team pairs one of the handler's animals with the handler under a display `team_name`, formed by a payload carrying the `animal_id`; the animal must belong to the creating handler, and an animal may belong to at most one team not yet `DISSOLVED` — a second formation attempt fails with `ERR_ACTIVE_TEAM_EXISTS`."

        Design: Corner/errors/second_team_for_animal_rejected
        """
        handler = create_active_handler(full_name="H 2T")
        animal = register_animal(handler["id"], name="D")
        create_forming_team(handler["id"], animal["id"], "T-first")
        resp = api_client.create_team(
            {"animal_id": animal["id"], "team_name": "T-second"},
            make_handler_headers(handler["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_TEAM_EXISTS)

    def test_handler_approve_twice_returns_invalid_state(self):
        """PRD §3.1: "A `ProgramAdmin` reviews the application: approval moves the handler `APPLICANT → ACTIVE`, and rejection — a call that carries a `reason` — moves it to the terminal `REJECTED` state; either action on a handler no longer in `APPLICANT` fails with `ERR_HANDLER_NOT_APPLICANT`."

        Design: Corner/state_machines/handler_approve_twice_returns_invalid_state
        """
        handler = create_applicant_handler(full_name="H A2")
        approve1 = api_client.approve_handler(handler["id"], ADMIN)
        validate_success(approve1, 200)
        resp = api_client.approve_handler(handler["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_HANDLER_NOT_APPLICANT)


class TestImmediateConsistency:
    def test_immediate_read_after_write(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §2.5: "`version` is a system-managed integer that increments with every mutation. Any change to a resource — including derived recomputation such as a handler's lifetime minutes, an animal's workload counters, or a team's penalty counters — counts as a mutation that refreshes `updated_at` and increments `version`."

        Design: Corner/consistency/immediate_read_after_write
        """
        created = create_applicant_handler(full_name="H IM")
        approve_resp = api_client.approve_handler(created["id"], ADMIN)
        approved = validate_success(approve_resp, 200)
        assert approved["status"] == "ACTIVE", (
            "The approve response itself must carry the updated state"
        )
        assert approved["version"] == created["version"] + 1, (
            f"version must increment per mutation: create v{created['version']} -> approve v{approved['version']}"
        )
        fetched = validate_success(api_client.get_handler(created["id"], ADMIN))
        assert fetched["status"] == "ACTIVE"
        assert fetched["version"] == approved["version"], (
            "No hidden drift between the write response and a subsequent read"
        )
