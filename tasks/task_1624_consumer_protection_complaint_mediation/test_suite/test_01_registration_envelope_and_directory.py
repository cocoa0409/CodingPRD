"""Registration, response envelope, uniqueness constraints, and the public directory."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_business,
    assert_complaint_event,
    assert_consumer,
    assert_millis_timestamp,
    create_business_payload,
    create_complaint_payload,
    create_consumer_payload,
    create_mediation_room_payload,
    create_mediator_payload,
    is_valid_uuid,
    make_consumer_headers,
    register_business,
    register_consumer,
    register_mediation_room,
    register_mediator,
    file_complaint,
    screen_accept,
    validate_error,
    validate_paginated,
    validate_success,
)

ANON = TEST_USERS["anonymous_headers"]
OFFICER_1 = TEST_USERS["intake_officer_headers"]
DIRECTOR_1 = TEST_USERS["unit_director_headers"]


class TestRegistrationSystemFields:
    def test_consumer_create_returns_server_minted_system_fields(self, api):
        """PRD §2.4: "Every resource in the system carries a server-minted `id` formatted as a bare UUID, with no type prefix."
        PRD §2.4: "Alongside it, every resource except the audit-trail entry carries `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and an integer `version` that increments with every mutation of the resource"
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/entities/c_ent_consumer_create_system_fields
        """
        resp = api.create_consumer(
            create_consumer_payload(full_name="Sys Fields", email="sys@x.com", state_code="OR"),
            ANON,
        )
        body = resp.json()
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")

        consumer = validate_success(resp, 201)
        assert_consumer(consumer)
        assert is_valid_uuid(consumer["id"]), "id must be a bare UUID with no type prefix"
        assert_millis_timestamp(consumer["created_at"], "created_at")
        assert_millis_timestamp(consumer["updated_at"], "updated_at")
        assert isinstance(consumer["version"], int), "version must be an integer"
        assert consumer["full_name"] == "Sys Fields"
        assert consumer["email"] == "sys@x.com"
        assert consumer["state_code"] == "OR"

    def test_business_registration_applies_defaults_and_computed_fields(self, api):
        """PRD §3.1: "The size tier is `SMALL` unless the registrant declares `MEDIUM` or `LARGE`, and the rating method is `LIFETIME` unless `ROLLING_12M` is chosen."
        PRD §3.1: "A freshly registered business starts with a `watch_status` of `CLEAR`, a `pattern_score` of 0, a `rating_score` of 100 in tier `A`, a `published_complaint_count` of 0, an `overdue_response_count` of 0, and a `next_filing_seq` of 1."

        Design: Corner/entities/c_ent_business_computed_defaults
        """
        resp = api.create_business(
            create_business_payload(
                legal_name="DefCo", home_state="WA",
                operates_in_states=["OR", "WA"], naics_code="454110",
            ),
            ANON,
        )
        business = validate_success(resp, 201)
        assert_business(business)
        assert business["size_tier"] == "SMALL", "size_tier defaults to SMALL"
        assert business["rating_method"] == "LIFETIME", "rating_method defaults to LIFETIME"
        assert business["watch_status"] == "CLEAR"
        assert business["pattern_score"] == 0
        assert business["rating_score"] == 100
        assert business["rating_tier"] == "A"
        assert business["published_complaint_count"] == 0
        assert business["overdue_response_count"] == 0
        assert business["next_filing_seq"] == 1

    def test_consumer_registration_missing_email_rejected(self, api):
        """PRD §3.1: "Self-service registration takes a `full_name`, an `email`, a two-letter `state_code` of residence, and an optional `phone`."
        PRD §2.12: "Request shape: required fields are present, types and enum members are valid, and amount rules hold"

        Design: Corner/entities/c_ent_consumer_missing_required_returns_400
        """
        resp = api.create_consumer(
            {"full_name": "No Email", "state_code": "OR"}, ANON
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestRegistrationUniqueness:
    def test_duplicate_email_and_registration_keys_rejected(self, api):
        """PRD §3.1: "Email addresses are unique across consumers, and a duplicate is refused with `ERR_UNIQUENESS_VIOLATION`."
        PRD §3.1: "The combination of `legal_name` and `home_state` is unique; a duplicate draws `ERR_UNIQUENESS_VIOLATION`."
        PRD §3.1: "Registering a mediator takes a `full_name`, an `employee_ref` that must be unique (collisions draw `ERR_UNIQUENESS_VIOLATION`)"
        PRD §3.1: "Mediation rooms are registered with a unique `room_name`, a `capacity`, and a `location`"

        Design: Corner/errors/c_err_uniqueness_across_registrations
        """
        register_consumer(full_name="U1", email="u1@x.com", state_code="OR")
        register_business(legal_name="UniqCo", home_state="OR", operates_in_states=["OR"])
        register_mediator(full_name="Med U", employee_ref="EMP-30")
        register_mediation_room(room_name="Room U", capacity=4, location="Salem")

        dup_consumer = api.create_consumer(
            create_consumer_payload(full_name="U1b", email="u1@x.com", state_code="WA"), ANON
        )
        validate_error(dup_consumer, ApiErrorId.ERR_UNIQUENESS_VIOLATION)

        dup_business = api.create_business(
            create_business_payload(
                legal_name="UniqCo", home_state="OR",
                operates_in_states=["WA"], naics_code="311611",
            ),
            ANON,
        )
        validate_error(dup_business, ApiErrorId.ERR_UNIQUENESS_VIOLATION)

        dup_mediator = api.create_mediator(
            create_mediator_payload(full_name="Med U2", employee_ref="EMP-30"), DIRECTOR_1
        )
        validate_error(dup_mediator, ApiErrorId.ERR_UNIQUENESS_VIOLATION)

        dup_room = api.create_mediation_room(
            create_mediation_room_payload(room_name="Room U", capacity=2, location="Bend"),
            DIRECTOR_1,
        )
        validate_error(dup_room, ApiErrorId.ERR_UNIQUENESS_VIOLATION)

    def test_envelope_success_and_error_arms(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §3.1: "Email addresses are unique across consumers, and a duplicate is refused with `ERR_UNIQUENESS_VIOLATION`."

        Design: Corner/endpoints/c_ep_envelope_success_and_error
        """
        first = api.create_consumer(
            create_consumer_payload(full_name="Env", email="env@x.com", state_code="OR"), ANON
        )
        consumer = validate_success(first, 201)
        assert_consumer(consumer)
        first_body = first.json()
        assert first_body["response_type"] == "object"
        assert first_body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(first_body["meta"]["api_request_timestamp"], str)

        dup = api.create_consumer(
            create_consumer_payload(full_name="Env Dup", email="env@x.com", state_code="OR"),
            ANON,
        )
        err = validate_error(dup, ApiErrorId.ERR_UNIQUENESS_VIOLATION)
        assert err["message"].strip(), "error message must be non-empty"
        dup_body = dup.json()
        assert dup_body["response_type"] == "error"


class TestDirectoryAndReferences:
    def test_business_list_applies_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, and any value below 1 or above 100 is out of range. The `offset` parameter controls how many items are skipped and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/c_ent_business_list_pagination_defaults
        """
        register_business(legal_name="PageCo", home_state="OR", operates_in_states=["OR"])

        data, meta = validate_paginated(api.list_businesses(ANON))
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0, "default offset is 0"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(data) == 1 and data[0]["legal_name"] == "PageCo"

    def test_get_complaint_unknown_id_returns_not_found(self, api):
        """PRD §2.5: "the same pattern gives `ERR_COMPLAINT_NOT_FOUND` for `{complaintId}`"
        PRD §2.5: "Identifiers in a request path are validated sequentially from left to right, and the first identifier that fails to resolve determines the error returned."

        Design: Corner/entities/c_ent_complaint_not_found_returns_404
        """
        resp = api.get_complaint(NON_EXISTENT_UUID, OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_FOUND)

    def test_complaint_with_unknown_business_fk_rejected(self, api):
        """PRD §2.5: "Foreign keys carried in request bodies must resolve as well, drawing from the same error family."
        PRD §2.5: "an unresolvable `{businessId}` yields `ERR_BUSINESS_NOT_FOUND`"

        Design: Corner/entities/c_ent_complaint_fk_business_not_found
        """
        consumer = register_consumer(full_name="FK", email="fk@x.com", state_code="OR")
        payload = create_complaint_payload(consumer["id"], NON_EXISTENT_UUID)
        resp = api.create_complaint(payload, make_consumer_headers(consumer["id"]))
        validate_error(resp, ApiErrorId.ERR_BUSINESS_NOT_FOUND)

    def test_complaint_with_unknown_category_enum_rejected(self, api):
        """PRD §3.2: "Categories are `DECEPTIVE_PRACTICE`, `REFUND_REFUSAL`, `DEFECTIVE_PRODUCT`, `BILLING_DISPUTE`, `WARRANTY_DENIED`, `CONTRACT_VIOLATION`, and `OTHER`."
        PRD §2.12: "Request shape: required fields are present, types and enum members are valid, and amount rules hold"

        Design: Corner/entities/c_ent_complaint_invalid_enum_returns_400
        """
        consumer = register_consumer(full_name="Enum", email="enum@x.com", state_code="OR")
        business = register_business(legal_name="EnumCo", home_state="OR", operates_in_states=["OR"])
        payload = create_complaint_payload(
            consumer["id"], business["id"], category="BOGUS", description="bad enum"
        )
        resp = api.create_complaint(payload, make_consumer_headers(consumer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_event_trail_is_append_only_and_chronological(self, api):
        """PRD §2.4: "A `ComplaintEvent` carries only `id` and `created_at`; both `updated_at` and `version` are absent, because the trail is append-only and individual entries — retrievable by `eventId` — never change after they are written."
        PRD §3.2: "A `CREATED` event opens the case's audit trail"
        PRD §3.2: "Acceptance moves the complaint to `ACCEPTED`, stamps the screening officer into `accepted_by_officer_id` — the anchor for the closure segregation rule of §2.7 — and logs a `STATE_CHANGED` event."
        PRD §2.3: "Unless otherwise specified, every list is returned in creation order — `created_at` ascending."

        Design: Corner/entities/c_ent_event_log_append_only
        """
        consumer = register_consumer(full_name="EV", email="ev@x.com", state_code="OR")
        business = register_business(legal_name="EvCo", home_state="OR", operates_in_states=["OR"])
        complaint = file_complaint(consumer, business, description="events")
        screen_accept(complaint["id"])

        data, meta = validate_paginated(
            api.list_complaint_events(OFFICER_1, params={"complaint_id": complaint["id"]})
        )
        assert len(data) == 2, f"expected CREATED + STATE_CHANGED, got {len(data)} events"
        assert data[0]["event_type"] == "CREATED"
        assert data[1]["event_type"] == "STATE_CHANGED"
        assert data[1]["from_status"] == "RECEIVED"
        assert data[1]["to_status"] == "ACCEPTED"
        for event in data:
            assert_complaint_event(event)
