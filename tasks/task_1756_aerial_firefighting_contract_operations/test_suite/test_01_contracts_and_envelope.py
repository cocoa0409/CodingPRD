"""Contract onboarding, season lifecycle basics, and the response envelope."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_contract,
    create_contract,
    create_contract_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["carrier_ops_headers"]


class TestContractCreation:
    def test_contract_creation_applies_defaults_and_zeroed_counters(self, api):
        """PRD §3.1: "A new contract is born in `DRAFT` with
        `season_billed_cents` and `season_flight_hours_tenths` both zero."
        PRD §3.1: "`min_daily_available_minutes` sets the available-minutes
        threshold an exclusive-use day must reach to bill at full rate; when
        omitted it defaults to 570 minutes"

        Design: Corner/entities/contract_creation_defaults_and_system_fields
        """
        resp = api.create_contract(
            create_contract_payload(),  # min_daily_available_minutes omitted
            OPS,
        )
        contract = validate_success(resp, 201)
        assert_contract(contract)
        assert contract["status"] == "DRAFT", "A new contract is born in DRAFT"
        assert contract["min_daily_available_minutes"] == 570, \
            "omitted min_daily_available_minutes defaults to 570"
        assert contract["season_billed_cents"] == 0
        assert contract["season_flight_hours_tenths"] == 0
        assert is_valid_uuid(contract["id"]), "id is a server-minted UUID"

    def test_contract_invalid_contract_type_rejected(self, api):
        """PRD §2.9: "required fields present, types valid, enum members valid,
        date and datetime formats valid, and the intrinsic orderings:
        `hobbs_stop` strictly after `hobbs_start`, `available_end` strictly
        after `available_start`, `planned_end` strictly after `planned_start`,
        `period_end` on or after `period_start`, `season_end_date` strictly
        after `season_start_date`, and exactly one of an inspection's two
        subjects set. Any violation is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/contract_invalid_enum_rejected
        """
        resp = api.create_contract(
            create_contract_payload(contract_number="EU-2026-009",
                                    contract_type="WET_LEASE"),
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_get_unknown_contract_returns_404(self, api):
        """PRD §2.5: "Each resource has its own not-found error, all HTTP 404:
        `ERR_CONTRACT_NOT_FOUND`, `ERR_AIRCRAFT_NOT_FOUND`,
        `ERR_CREW_MEMBER_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
        `ERR_DISPATCH_ORDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, `ERR_AVAILABILITY_PERIOD_NOT_FOUND`,
        `ERR_INSPECTION_NOT_FOUND`, and `ERR_RETARDANT_LOAD_NOT_FOUND`."

        Design: Corner/entities/contract_not_found_returns_404
        """
        resp = api.get_contract(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND,
                       expected_status=404)


class TestContractLifecycle:
    def test_contract_born_draft_then_activate(self, api):
        """PRD §3.1: "A new contract is born in `DRAFT` with
        `season_billed_cents` and `season_flight_hours_tenths` both zero."
        PRD §3.1: "Activation moves the contract from `DRAFT` to `ACTIVE`."
        PRD §3.1: "Each lifecycle transition increments the contract's `version`."

        Design: Corner/state_machines/contract_initial_state_and_activate
        """
        contract = create_contract()
        assert contract["status"] == "DRAFT"
        v0 = contract["version"]

        activated = validate_success(api.activate_contract(contract["id"], OPS), 200)
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == v0 + 1, \
            "activation increments the contract version by exactly 1"

    def test_resume_from_active_rejected(self, api):
        """PRD §3.1: "a later resume (`SUSPENDED` → `ACTIVE`) lifts it".
        PRD §2.9: "the requested transition must be valid from the entity's
        current state (`ERR_INVALID_STATE`, HTTP 409)".

        Design: Corner/state_machines/contract_resume_from_active_rejected
        """
        contract = create_contract()
        validate_success(api.activate_contract(contract["id"], OPS), 200)

        resp = api.resume_contract(contract["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = validate_success(api.get_contract(contract["id"], OPS), 200)
        assert after["status"] == "ACTIVE", "rejected resume leaves status ACTIVE"

    def test_closed_contract_rejects_further_actions(self, api):
        """PRD §3.1: "Closing is allowed from either `ACTIVE` or `SUSPENDED`,
        but only once no dispatch order of the contract remains in `PLACED`,
        `ACCEPTED`, `PARTIALLY_FILLED`, or `FILLED`."
        PRD §3.1: "`CLOSED` is terminal: any further action on a closed
        contract is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/closed_contract_terminal_lockdown
        """
        contract = create_contract()
        validate_success(api.activate_contract(contract["id"], OPS), 200)
        closed = validate_success(api.close_contract(contract["id"], OPS), 200)
        assert closed["status"] == "CLOSED"

        resp = api.suspend_contract(contract["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)


class TestResponseEnvelope:
    def test_response_envelope_shapes(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format" carrying meta.api_request_id,
        meta.api_request_timestamp, response_type and data; the error envelope
        carries "data": {"error_id": ..., "message": ...}.
        PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        how many items to skip and defaults to 0."

        Design: Corner/endpoints/response_envelope_and_error_shape
        """
        contract = create_contract()

        single = api.get_contract(contract["id"], OPS)
        body = single.json()
        assert single.status_code == 200
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        listing = api.list_contracts(OPS)
        data, meta = validate_paginated(listing)
        assert listing.json()["response_type"] == "array"
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0, "default offset is 0"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert isinstance(data, list) and len(data) == 1

        err = api.get_contract(NON_EXISTENT_UUID, OPS)
        err_body = err.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_CONTRACT_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"].strip()) > 0, \
            "error message must be non-empty"
