"""Builder registration, application intake, hold axis, and validation ordering."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_builder,
    create_booking,
    create_builder,
    create_builder_payload,
    create_crew,
    create_permit_payload,
    create_service_application_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_builder_headers,
    setup_draft_app,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBuilderCreation:
    def test_builder_creation_applies_active_default(self, api, rep_headers):
        """PRD §3.1: "A `NewBusinessRep` or a `SystemAdmin` registers a builder with its `company_name`, `contact_email`, and `license_number`; the account starts in `ACTIVE` status."
        PRD §2.4: "`id` (string): a server-minted UUID with no type prefix."
        PRD §2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation."

        Design: Corner/entities/builder_creation_applies_defaults
        """
        resp = api.create_builder(create_builder_payload(), rep_headers)
        data = validate_success(resp, expected_status=201)
        assert_builder(data)
        assert data["status"] == "ACTIVE", (
            f"new builder must default to ACTIVE, got {data['status']}"
        )
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert isinstance(data["version"], int) and data["version"] >= 0

    def test_builder_creation_ignores_client_system_fields(self, api, rep_headers):
        """PRD §2.4: "Every primary resource carries a standard set of system-managed fields:"
        PRD §2.4: "`id` (string): a server-minted UUID with no type prefix."

        Design: Corner/entities/builder_system_fields_input_ignored
        """
        client_id = "99999999-8888-7777-6666-555555555555"
        payload = create_builder_payload(
            id=client_id, version=42, created_at="1999-01-01T00:00:00Z"
        )
        resp = api.create_builder(payload, rep_headers)
        data = validate_success(resp, expected_status=201)
        assert data["id"] != client_id, "server must mint its own id, not the client's"
        assert data["version"] != 42, "client-supplied version must be ignored"
        assert data["created_at"] != "1999-01-01T00:00:00Z", (
            "client-supplied created_at must be ignored"
        )
        assert is_valid_uuid(data["id"])


class TestBuilderSuspension:
    def test_suspended_builder_cannot_create_application(self, api, admin_headers, rep_headers):
        """PRD §3.1: "A suspended builder cannot open new applications and cannot submit draft ones: both attempts are rejected with `ERR_BUILDER_SUSPENDED` (HTTP 422)."

        Design: Corner/errors/suspended_builder_rejected
        """
        builder = create_builder()
        resp = api.patch_builder(builder["id"], {"status": "SUSPENDED"}, admin_headers)
        validate_success(resp)

        builder_headers = make_builder_headers(builder["id"])
        resp = api.create_service_application(
            create_service_application_payload(builder["id"]), builder_headers
        )
        validate_error(resp, ApiErrorId.ERR_BUILDER_SUSPENDED, expected_status=422)

        list_resp = api.list_service_applications(
            rep_headers, params={"builder_id": builder["id"]}
        )
        data, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 0, "no application may be persisted for a suspended builder"


class TestApplicationIntake:
    def test_invalid_pressure_class_rejected(self, api, rep_headers):
        """PRD §2.6: "Separately from this ordered stack, malformed request bodies — a missing required field, a value of the wrong type, an enum member outside the declared set, a non-positive quantity, footage, or money amount, a time window whose end does not fall strictly after its start, or a road-cut permit with an empty crossing list — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "an optional `pressure_class_requested` — `LOW` for standard 0.25 psi delivery or `MEDIUM` for 2 psi delivery, defaulting to `LOW` when omitted."

        Design: Corner/entities/application_invalid_enum_rejected
        """
        builder = create_builder()
        builder_headers = make_builder_headers(builder["id"])
        resp = api.create_service_application(
            create_service_application_payload(builder["id"], pressure_class_requested="HIGH"),
            builder_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        list_resp = api.list_service_applications(
            rep_headers, params={"builder_id": builder["id"]}
        )
        _, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 0, "rejected creation must not persist a row"

    def test_initial_states_pinned(self, api, coordinator_headers, supervisor_headers):
        """PRD §3.1: "The application starts in `DRAFT`."
        PRD §3.5: "The booking starts in `REQUESTED`."
        PRD §3.4: "Creation starts the permit in `DRAFT` and computes its `permit_fee_cents`."
        PRD §3.4: "then total the individually rounded segment fees and add the flat filing fee of 7,500 cents ($75.00)."

        Design: Corner/state_machines/initial_states_pinned
        """
        ctx = setup_draft_app()
        assert ctx["app"]["status"] == "DRAFT"

        crew = create_crew(specialty="GENERAL")
        booking = create_booking(ctx["app"]["id"], crew["id"], start=540, end=660)
        assert booking["status"] == "REQUESTED", (
            f"new crew booking must start REQUESTED, got {booking['status']}"
        )

        resp = api.create_permit(
            create_permit_payload(ctx["app"]["id"], permit_type="EASEMENT", crossings=[]),
            coordinator_headers,
        )
        permit = validate_success(resp, expected_status=201)
        assert permit["status"] == "DRAFT"
        assert permit["permit_fee_cents"] == 7500, (
            f"crossing-free permit pays the filing fee alone: expected 7500, "
            f"got {permit['permit_fee_cents']}"
        )

    def test_cancelled_application_is_terminal(self, api):
        """PRD §3.9: "The owning builder or a `NewBusinessRep` may cancel any application that is not already in a terminal state (`COMPLETED`, `REJECTED`, `CANCELLED`, or `EXPIRED` — attempts there meet `ERR_APPLICATION_TERMINAL`)"
        PRD §2.5: "`COMPLETED`, `REJECTED`, `CANCELLED`, and `EXPIRED` are the application's terminal states; once an application is terminal, every mutation targeting it or any of its children is rejected with `ERR_APPLICATION_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/cancelled_application_is_terminal
        """
        ctx = setup_draft_app()
        app_id = ctx["app"]["id"]
        resp = api.cancel_application(app_id, ctx["builder_headers"])
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"

        resp = api.cancel_application(app_id, ctx["builder_headers"])
        validate_error(resp, ApiErrorId.ERR_APPLICATION_TERMINAL, expected_status=409)

        after = get_success_data(api.get_service_application(app_id, ctx["builder_headers"]))
        assert after["status"] == "CANCELLED"
        assert after["version"] == cancelled["version"], (
            "a rejected cancel must not mutate the application"
        )

    def test_hold_blocks_child_writes_until_resumed(self, api, rep_headers):
        """PRD §2.5: "A hold never changes the spine status, but any `hold_status` other than `NOT_HELD` freezes the application: every child-entity mutation and every spine transition is rejected with `ERR_APPLICATION_ON_HOLD` (HTTP 409) until the hold is cleared."
        PRD §3.9: "Holding it with a free-text `reason` — recorded on the application as `hold_reason` — sets the hold axis to `HELD_BY_BUILDER` when the actor is the owning `Builder`, or to `HELD_BY_UTILITY` when the actor is a `NewBusinessRep` or `FieldSupervisor`; resuming clears it back to `NOT_HELD`."

        Design: Corner/state_machines/hold_gate_blocks_child_writes
        """
        ctx = setup_draft_app()
        app_id = ctx["app"]["id"]
        resp = api.hold_application(
            app_id, {"reason": "customer financing"}, ctx["builder_headers"]
        )
        held = validate_success(resp)
        assert held["hold_status"] == "HELD_BY_BUILDER"
        assert held["status"] == "DRAFT", "a hold must not move the spine"

        resp = api.create_appliance_load(
            {
                "service_application_id": app_id,
                "appliance_type": "FURNACE",
                "quantity": 1,
                "btuh_input_rating": 80000,
            },
            ctx["builder_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_ON_HOLD, expected_status=409)

        resp = api.resume_application(app_id, ctx["builder_headers"])
        resumed = validate_success(resp)
        assert resumed["hold_status"] == "NOT_HELD"

        resp = api.create_appliance_load(
            {
                "service_application_id": app_id,
                "appliance_type": "FURNACE",
                "quantity": 1,
                "btuh_input_rating": 80000,
            },
            ctx["builder_headers"],
        )
        validate_success(resp, expected_status=201)

    def test_confirm_load_from_draft_rejected(self, api, rep_headers):
        """PRD §3.1: "Confirming the load moves the application from `SUBMITTED` to `LOAD_CONFIRMED` and freezes the load rows for the rest of the journey"
        PRD §2.6: "7. **Entity state machine validity** — the target entity's current state must permit the requested transition, else `ERR_INVALID_STATE` or the more specific member of the state-gate family (`ERR_INVOICE_NOT_PAYABLE`, `ERR_INVOICE_NOT_REFUNDABLE`, `ERR_COMMITMENT_NOT_REVISABLE`, `ERR_SERVICE_LINE_NOT_INSTALLED`, `ERR_METER_NOT_READY`), all HTTP 409."
        PRD §3.1: "editing and deleting individual rows is permitted only while the application is `DRAFT`."

        Design: Corner/state_machines/confirm_load_from_draft_rejected
        """
        ctx = setup_draft_app(
            loads=[{"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 80000}]
        )
        app_id = ctx["app"]["id"]
        resp = api.confirm_load(app_id, rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = get_success_data(api.get_service_application(app_id, rep_headers))
        assert after["status"] == "DRAFT", "rejected confirm-load must not move the spine"

        load = ctx["loads"][0]
        resp = api.patch_appliance_load(
            load["id"],
            {"expected_load_version": load["version"], "quantity": 2},
            ctx["builder_headers"],
        )
        validate_success(resp)


class TestValidationOrdering:
    def test_missing_application_beats_state_check(self, api, rep_headers):
        """PRD §2.6: "When several checks could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic:"
        PRD §2.6: "4. **Existence** — path identifiers and body foreign-key references are resolved left to right, path parameters first and then body fields in their declared order; the first unresolved reference produces that entity's own 404 error (see §2.10)."

        Design: Corner/validations/missing_app_beats_state_check
        """
        resp = api.confirm_load(NON_EXISTENT_UUID, rep_headers)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND, expected_status=404)

    def test_role_denial_beats_existence(self, api, rep_headers):
        """PRD §2.6: "When several checks could reject the same request, the server evaluates them in a fixed order so that the surfaced error is deterministic:"
        PRD §2.6: "2. **Role authorization** — the acting role is on the endpoint's authorized list, else `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: the payments endpoint is authorized for BillingClerk only.

        Design: Corner/validations/role_denial_beats_existence
        """
        builder = create_builder()
        builder_headers = make_builder_headers(builder["id"])
        resp = api.record_payment(
            NON_EXISTENT_UUID, {"amount_cents": 100, "method": "ACH"}, builder_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
