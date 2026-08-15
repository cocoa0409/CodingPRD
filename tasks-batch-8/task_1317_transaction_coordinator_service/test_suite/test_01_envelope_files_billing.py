"""Entity shape, response envelope, file-creation request-shape rules, and file pricing."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp, NON_EXISTENT_UUID,
    api_client, ApiErrorId, TEST_USERS,
    assert_coordinator, assert_file, assert_communication,
    create_coordinator_payload, create_file_payload,
    make_coordinator, make_agent, make_template, make_coordinator_with_seller,
    make_active_listing_file,
    ABSENT_UUID,
)


class TestCoordinatorCreation:
    def test_coordinator_creation_applies_defaults_1(self):
        """PRD §3.1: "A newly registered coordinator starts with `status` set to
        `ACTIVE`; the only other value it can take is `SUSPENDED`."
        PRD §2.4: "Every persisted resource carries a server-minted `id` that is a UUID
        with no type prefix."

        Design: Corner/entities/coordinator_creation_applies_defaults
        """
        resp = api_client.create_coordinator(
            create_coordinator_payload(full_name="Casey Coord", email="casey@tc.example",
                                       license_number="TC-1001"),
            TEST_USERS["admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_coordinator(data)
        assert data["status"] == "ACTIVE", "coordinator must start ACTIVE"
        assert data["version"] == 1, "coordinator version starts at 1"

    def test_coordinator_creation_applies_defaults_2(self):
        """PRD §3.1: "A `SystemAdmin` registers each coordinator by supplying
        `full_name`, `email`, and `license_number`. The email must be unique across
        coordinators."
        PRD §2.4: "All entities except `CommunicationEntry` additionally carry
        `created_at` and `updated_at` (ISO 8601 UTC timestamps with three fractional
        digits) and an integer `version` that increments by 1 on every mutation of
        that entity."

        Design: Corner/entities/coordinator_creation_applies_defaults
        """
        resp = api_client.create_coordinator(create_coordinator_payload(),
                                             TEST_USERS["admin_headers"])
        data = validate_success(resp, expected_status=201)
        assert is_iso8601_timestamp(data.get("created_at", ""))
        assert is_iso8601_timestamp(data.get("updated_at", ""))
        assert data["version"] == 1


class TestAgentRoster:
    def test_agent_created_on_acting_coordinators_roster_1(self):
        """PRD §3.1: "The roster owner is recorded automatically: the new agent's
        `coordinator_id` is set from the acting coordinator's `X-User-ID`, and the
        agent starts with `status` `ACTIVE` (the alternative being `INACTIVE`)."

        Design: Corner/entities/agent_created_on_acting_coordinators_roster
        """
        coord1, coord1_h = make_coordinator("Casey Coord")
        coord2, coord2_h = make_coordinator("Dana Coord")
        agent, _agent_h = make_agent(coord1_h, "Seller Sam")
        assert agent["coordinator_id"] == coord1["id"], (
            f"agent coordinator_id must be the acting coordinator's id: "
            f"expected {coord1['id']}, got {agent['coordinator_id']}"
        )
        assert agent["status"] == "ACTIVE"

    def test_agent_created_on_acting_coordinators_roster_2(self):
        """PRD §3.1: "The roster owner is recorded automatically: the new agent's
        `coordinator_id` is set from the acting coordinator's `X-User-ID`, and the
        agent starts with `status` `ACTIVE` (the alternative being `INACTIVE`)."

        Design: Corner/entities/agent_created_on_acting_coordinators_roster
        """
        coord1, coord1_h = make_coordinator("Casey Coord")
        coord2, coord2_h = make_coordinator("Dana Coord")
        make_agent(coord1_h, "Seller Sam")
        rows = get_success_data(api_client.list_agents(coord2_h, params={"limit": 100}))
        assert len(rows) == 1, "only the first coordinator's agent exists"
        assert rows[0]["coordinator_id"] == coord1["id"]
        assert all(r["coordinator_id"] != coord2["id"] for r in rows), \
            "no agent may be registered on the second coordinator's roster"


class TestFileCreationShape:
    def test_file_initial_state_is_draft_1(self):
        """PRD §3.3: "A new file is created in `DRAFT`."
        PRD §3.3: "The file also carries, from the start, `last_audit_status`
        initialized to `NONE` (its other values being `PASS` and `FAIL`) and
        `open_escalation_count` initialized to 0."

        Design: Corner/state_machines/file_initial_state_is_draft
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        payload = create_file_payload(seller_agent_id=seller["id"])
        data = validate_success(api_client.create_file(payload, coord_h), expected_status=201)
        assert_file(data)
        assert data["status"] == "DRAFT", "a new file must start in DRAFT"
        assert data["last_audit_status"] == "NONE"
        assert data["open_escalation_count"] == 0

    def test_file_initial_state_is_draft_2(self):
        """PRD §3.3: "A new file is created in `DRAFT`. Its full lifecycle is
        `DRAFT → ACTIVE → PENDING_CLOSE → CLOSED → ARCHIVED`, with termination
        possible from `ACTIVE` or `PENDING_CLOSE` into `TERMINATED`. `ARCHIVED` and
        `TERMINATED` are terminal."
        PRD §3.3: "The file also carries, from the start, `last_audit_status`
        initialized to `NONE` (its other values being `PASS` and `FAIL`) and
        `open_escalation_count` initialized to 0."

        Design: Corner/state_machines/file_initial_state_is_draft
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        payload = create_file_payload(seller_agent_id=seller["id"])
        data = validate_success(api_client.create_file(payload, coord_h), expected_status=201)
        fetched = validate_success(api_client.get_file(data["id"], coord_h))
        assert fetched["status"] == "DRAFT"
        assert fetched["last_audit_status"] == "NONE"
        assert fetched["open_escalation_count"] == 0

    def test_file_create_missing_state_code_rejected_1(self):
        """PRD §2.5: "Twelfth and last, request shape — missing required field,
        invalid enum member, unknown field (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/file_create_missing_state_code_rejected
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        payload = create_file_payload(seller_agent_id=seller["id"])
        payload.pop("state_code")
        resp = api_client.create_file(payload, coord_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_file_create_missing_state_code_rejected_2(self):
        """PRD §2.5: "Twelfth and last, request shape — missing required field,
        invalid enum member, unknown field (`ERR_INVALID_REQUEST`)."
        PRD §3.3: "A coordinator opens a transaction file with `billing_model`
        (`PER_FILE` or `SUBSCRIPTION`), `state_code`, `contract_type` (`PURCHASE_SALE`
        or `LISTING_ONLY`), `property_address`, `effective_date` in `YYYY-MM-DD` form,
        `closing_date` in `YYYY-MM-DD` form, `list_price_cents`, `seller_agent_id`
        (always required), and the contingency offsets `inspection_offset_days`,
        `appraisal_offset_days`, and `financing_offset_days`, each at least 0."

        Design: Corner/entities/file_create_missing_state_code_rejected
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        payload = create_file_payload(seller_agent_id=seller["id"])
        payload.pop("state_code")
        resp = api_client.create_file(payload, coord_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        rows = get_success_data(api_client.list_files(coord_h, params={"limit": 100}))
        assert rows == [], "a rejected create must persist nothing"

    def test_file_create_extra_field_rejected_1(self):
        """PRD §2.5: "Twelfth and last, request shape — missing required field,
        invalid enum member, unknown field (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/file_create_extra_field_rejected
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        payload = create_file_payload(seller_agent_id=seller["id"])
        payload["fee_estimate_cents"] = 1
        resp = api_client.create_file(payload, coord_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_file_create_extra_field_rejected_2(self):
        """PRD §2.5: "Twelfth and last, request shape — missing required field,
        invalid enum member, unknown field (`ERR_INVALID_REQUEST`)."
        PRD §3.3: "Fields like `template_id`, `template_version`, `fee_estimate_cents`,
        `fee_final_cents`, `terminated_reason`, and `archived_at` are populated later
        by the transitions that own them."

        Design: Corner/entities/file_create_extra_field_rejected
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        payload = create_file_payload(seller_agent_id=seller["id"])
        payload["fee_estimate_cents"] = 1
        resp = api_client.create_file(payload, coord_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        rows = get_success_data(api_client.list_files(coord_h, params={"limit": 100}))
        assert rows == [], "a create carrying an unknown field must persist nothing"

    def test_file_create_invalid_enum_rejected_1(self):
        """PRD §2.5: "Twelfth and last, request shape — missing required field,
        invalid enum member, unknown field (`ERR_INVALID_REQUEST`)."
        PRD §3.3: "A coordinator opens a transaction file with `billing_model`
        (`PER_FILE` or `SUBSCRIPTION`), `state_code`, `contract_type` (`PURCHASE_SALE`
        or `LISTING_ONLY`), `property_address`, `effective_date` in `YYYY-MM-DD` form,
        `closing_date` in `YYYY-MM-DD` form, `list_price_cents`, `seller_agent_id`
        (always required), and the contingency offsets `inspection_offset_days`,
        `appraisal_offset_days`, and `financing_offset_days`, each at least 0."

        Design: Corner/entities/file_create_invalid_enum_rejected
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        payload = create_file_payload(seller_agent_id=seller["id"], contract_type="LEASE")
        resp = api_client.create_file(payload, coord_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_file_create_invalid_enum_rejected_2(self):
        """PRD §2.5: "Twelfth and last, request shape — missing required field,
        invalid enum member, unknown field (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/file_create_invalid_enum_rejected
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        payload = create_file_payload(seller_agent_id=seller["id"], billing_model="MONTHLY")
        resp = api_client.create_file(payload, coord_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestNotFoundAndEnvelope:
    def test_get_nonexistent_file_returns_not_found(self):
        """PRD §2.5: "Third, existence of every path id and body foreign-key id,
        validated left-to-right as the ids appear in the URL and then the payload;
        each unresolved id produces its own entity-specific 404
        (`ERR_COORDINATOR_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`,
        `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_FILE_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`,
        `ERR_DEADLINE_NOT_FOUND`, `ERR_REMINDER_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`,
        `ERR_COMMUNICATION_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`,
        `ERR_SIGNATURE_REQUEST_NOT_FOUND`, `ERR_CLOSING_VERIFICATION_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`)."

        Design: Corner/entities/get_nonexistent_file_returns_not_found
        """
        coord, coord_h = make_coordinator()
        resp = api_client.get_file(ABSENT_UUID, coord_h)
        validate_error(resp, ApiErrorId.ERR_FILE_NOT_FOUND)

    def test_error_envelope_shape_contract(self):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        Design: Corner/errors/error_envelope_shape_contract
        """
        coord, coord_h = make_coordinator()
        resp = api_client.get_file(ABSENT_UUID, coord_h)
        body = resp.json()
        assert body["response_type"] == "error", "error responses must carry response_type 'error'"
        assert body["data"]["error_id"] == "ERR_FILE_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], \
            "error message must be a non-empty string"
        assert "api_request_id" in body["meta"] and "api_request_timestamp" in body["meta"]

    def test_list_files_pagination_envelope(self):
        """PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints."
        PRD §2.3: "List endpoints accept the query parameters `limit` and `offset`.
        `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset`
        defaults to 0."

        Design: Corner/entities/list_files_pagination_envelope
        """
        coord, coord_h, seller, _seller_h = make_coordinator_with_seller()
        payload = create_file_payload(seller_agent_id=seller["id"])
        get_success_data(api_client.create_file(payload, coord_h))
        resp = api_client.list_files(coord_h, params={"limit": 10, "offset": 0})
        data, meta = validate_paginated(resp)
        assert "api_request_id" in meta and "api_request_timestamp" in meta
        assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert resp.json()["response_type"] == "array"


class TestFilePricing:
    def test_computed_read_returns_fee_fields(self):
        """PRD §3.4: "Under `PER_FILE`, the base is 39500 cents for a `PURCHASE_SALE`
        contract or 29500 cents for a `LISTING_ONLY` contract, and a rush surcharge of
        7500 cents is added when the gap between `closing_date` and the activation
        date is strictly less than 10 days — a gap of exactly 10 days does not trigger
        the surcharge."
        PRD §3.4: "On success, activation pins `template_id` and the template's
        current `template_version` onto the file, then instantiates the working set."

        Design: Corner/endpoints/computed_read_returns_fee_fields
        """
        scen = make_active_listing_file(closing_date="2026-08-31")
        fetched = validate_success(api_client.get_file(scen["file"]["id"], scen["coord_h"]))
        assert fetched["fee_estimate_cents"] == 29500, (
            f"LISTING_ONLY file closing 30 days out must price at the 29500 base "
            f"with no rush; got {fetched['fee_estimate_cents']}"
        )
        assert fetched["template_id"] == scen["tmpl"]["id"], "activation must pin template_id"
        assert fetched["template_version"] == scen["tmpl"]["template_version"], \
            "activation must pin the template's current template_version"

    def test_clock_default_drives_time_dependent_rules(self):
        """PRD §2.8: "At startup the current time is exactly 2026-08-01T00:00:00Z and
        never advances on its own."
        PRD §3.4: "Under `PER_FILE`, the base is 39500 cents for a `PURCHASE_SALE`
        contract or 29500 cents for a `LISTING_ONLY` contract, and a rush surcharge of
        7500 cents is added when the gap between `closing_date` and the activation
        date is strictly less than 10 days — a gap of exactly 10 days does not trigger
        the surcharge."

        Design: Corner/cross_cutting_layers/clock_default_drives_time_dependent_rules
        """
        # No clock endpoint is ever called: activation_date must be the 2026-08-01
        # startup default, so a 2026-08-10 closing is 9 days out -> rush applies.
        scen = make_active_listing_file(closing_date="2026-08-10")
        fetched = validate_success(api_client.get_file(scen["file"]["id"], scen["coord_h"]))
        assert fetched["fee_estimate_cents"] == 37000, (
            f"9-day gap must price 29500 base + 7500 rush = 37000 against the default "
            f"logical clock; got {fetched['fee_estimate_cents']}"
        )


class TestCommunicationShape:
    def test_communication_entry_append_only_shape(self):
        """PRD §2.4: "`CommunicationEntry` is the sole exception: it carries only `id`
        and `created_at`; both `updated_at` and `version` are absent on that entity."
        PRD §3.5: "Each entry records `author_role` from the caller's `X-User-Role`
        and starts `OPEN` with `entry_kind` `LOG` (other kinds being `ESCALATION` and
        `SYSTEM`)."

        Design: Corner/entities/communication_entry_append_only_shape
        """
        scen = make_active_listing_file()
        payload = {
            "file_id": scen["file"]["id"],
            "party": "SELLER_AGENT",
            "direction": "OUTBOUND",
            "body": "Please send the executed contract",
        }
        data = validate_success(api_client.create_communication(payload, scen["coord_h"]),
                                expected_status=201)
        assert_communication(data)
        assert data["status"] == "OPEN", "a new communication entry starts OPEN"
        assert data["entry_kind"] == "LOG", "a logged communication starts with entry_kind LOG"
