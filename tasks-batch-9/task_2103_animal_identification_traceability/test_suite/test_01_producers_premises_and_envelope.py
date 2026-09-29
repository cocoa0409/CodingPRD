"""Producer and premises records, response envelope, pagination and the programme clock."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    apply_tag_payload,
    ain_for_serial,
    approve_premises,
    approve_supplier,
    assert_envelope_meta,
    assert_millisecond_timestamp,
    assert_premises,
    assert_producer,
    create_premises_payload,
    create_producer_payload,
    is_valid_uuid,
    issue_lot,
    make_producer_headers,
    make_program_admin_headers,
    make_state_official_headers,
    propose_hold,
    read_premises,
    read_producer,
    read_supplier,
    read_tag_lot,
    register_premises,
    register_producer,
    register_supplier,
    set_clock,
    setup_lot_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers("admin-reg")
OFFICIAL = make_state_official_headers("saho-1")


class TestProducerRecord:
    def test_producer_creation_mints_id_version_and_programme_defaults(self, api):
        """PRD §2.4: "Every persisted record carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC string with three fractional digits (for example `2026-08-01T00:00:00.000Z`)."
        PRD §2.4: "Most records additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 and increments by one on every mutation of that record — including mutations that only touch derived counters such as an animal count or a conformance score."
        PRD §3.1: "Newly registered producers begin with `enrollment_status` `NOT_ENROLLED`, a null `enrolled_at`, an `enrolled_head_count` of 0, an `incentive_tier` of `TIER_0`, an `on_time_movement_pct` of 100.00, an `incentive_balance_cents` of 0, and a `lifetime_clawback_cents` of 0."
        PRD §4: "Endpoints that bring a new resource into existence respond with HTTP 201; every other successful operation, including every state transition and every read, responds with HTTP 200."

        Design: Corner/entities/create_producer_mints_system_fields_and_defaults
        """
        payload = create_producer_payload(
            legal_name="Alpine Cattle", contact_email="ops@alpine.example", state_code="CO"
        )
        producer = validate_success(api.create_producer(payload, ADMIN), expected_status=201)
        assert_producer(producer)
        assert is_valid_uuid(producer["id"]), "id must be a bare UUID with no type prefix"
        assert producer["version"] == 1, "version starts at 1"
        assert producer["enrollment_status"] == "NOT_ENROLLED"
        assert producer["enrolled_at"] is None
        assert producer["enrolled_head_count"] == 0
        assert producer["incentive_tier"] == "TIER_0"
        assert producer["on_time_movement_pct"] == 100.00
        assert producer["incentive_balance_cents"] == 0
        assert producer["lifetime_clawback_cents"] == 0
        assert_millisecond_timestamp(producer["created_at"], "created_at")
        assert producer["created_at"] == "2026-08-01T00:00:00.000Z", (
            "the logical clock reads 2026-08-01T00:00:00Z before any client sets it"
        )

    def test_producer_privacy_level_defaults_to_standard_when_omitted(self, api):
        """PRD §2.7: "Producers regard herd composition and movement history as commercially sensitive, so every `Producer` record carries a `privacy_level` of either `STANDARD` or `RESTRICTED`, defaulting to `STANDARD` when the field is omitted at registration."
        PRD §3.1: "The optional `privacy_level` may be supplied as `RESTRICTED`; when it is omitted the producer is created as `STANDARD`."

        Design: Corner/entities/producer_privacy_level_defaults_to_standard_when_omitted
        """
        defaulted = validate_success(
            api.create_producer(
                create_producer_payload(legal_name="Default Co", contact_email="a@x.example"),
                ADMIN,
            ),
            expected_status=201,
        )
        assert defaulted["privacy_level"] == "STANDARD"

        restricted = validate_success(
            api.create_producer(
                create_producer_payload(
                    legal_name="Restricted Co",
                    contact_email="b@x.example",
                    privacy_level="RESTRICTED",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert restricted["privacy_level"] == "RESTRICTED"


class TestPremisesRegistration:
    def test_premises_creation_without_capacity_is_a_request_shape_failure(self, api):
        """PRD §3.1: "A registration supplies `producer_id`, a `pin` — the Premises Identification Number, exactly seven characters over the digits 0–9 and uppercase A–Z, and globally unique across the programme, with a collision rejected as `ERR_DUPLICATE_PIN` — an `operation_type` of `COW_CALF`, `FEEDLOT`, `MARKET` or `HARVEST_FACILITY`, the two-letter uppercase `state_code` of the location itself, and a `capacity` of at least one animal."
        PRD §2.5: "Every required body field is present; every scalar has the right type; every enum value names a recognised member"
        PRD §2.5: "Any failure here is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/premises_creation_missing_required_capacity_returns_invalid_request
        """
        producer = register_producer(legal_name="Alpine Cattle")
        payload = create_premises_payload(producer["id"], operation_type="COW_CALF")
        del payload["capacity"]

        resp = api.create_premises(payload, make_producer_headers(producer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        rows, meta = validate_paginated(
            api.list_premises(ADMIN, params={"producer_id": producer["id"]})
        )
        assert rows == [], "the rejected registration must persist nothing"
        assert meta["total_count"] == 0

    def test_premises_creation_with_unrecognised_operation_type_is_rejected(self, api):
        """PRD §3.1: "A registration supplies `producer_id`, a `pin` — the Premises Identification Number, exactly seven characters over the digits 0–9 and uppercase A–Z, and globally unique across the programme, with a collision rejected as `ERR_DUPLICATE_PIN` — an `operation_type` of `COW_CALF`, `FEEDLOT`, `MARKET` or `HARVEST_FACILITY`, the two-letter uppercase `state_code` of the location itself, and a `capacity` of at least one animal."
        PRD §2.5: "Any failure here is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/premises_invalid_operation_type_enum_returns_invalid_request
        """
        producer = register_producer(legal_name="Alpine Cattle")
        payload = create_premises_payload(
            producer["id"], operation_type="DAIRY", state_code="CO", capacity=10
        )
        resp = api.create_premises(payload, make_producer_headers(producer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_single_resource_reads_answer_with_their_own_not_found_error(self, api):
        """PRD §2.5: "Every resource named by a path segment resolves, validated strictly left to right — for a trace-hit response path, the trace request is resolved before the hit animal. The first unresolved segment decides the error, drawn from `ERR_PRODUCER_NOT_FOUND`, `ERR_PREMISES_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_TAG_LOT_NOT_FOUND`, `ERR_TAG_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_SIGHTING_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_TRACE_REQUEST_NOT_FOUND`, `ERR_HOLD_ORDER_NOT_FOUND`, `ERR_RECONCILIATION_RUN_NOT_FOUND`, or `ERR_AWARD_NOT_FOUND`."

        Design: Corner/entities/get_premises_with_unknown_id_returns_not_found
        """
        probes = [
            (api.get_premises, ApiErrorId.ERR_PREMISES_NOT_FOUND),
            (api.get_animal, ApiErrorId.ERR_ANIMAL_NOT_FOUND),
            (api.get_sighting, ApiErrorId.ERR_SIGHTING_NOT_FOUND),
            (api.get_movement_event, ApiErrorId.ERR_MOVEMENT_NOT_FOUND),
            (api.get_trace_request, ApiErrorId.ERR_TRACE_REQUEST_NOT_FOUND),
            (api.get_hold_order, ApiErrorId.ERR_HOLD_ORDER_NOT_FOUND),
            (api.get_tag, ApiErrorId.ERR_TAG_NOT_FOUND),
            (api.get_tag_lot, ApiErrorId.ERR_TAG_LOT_NOT_FOUND),
            (api.get_device_supplier, ApiErrorId.ERR_SUPPLIER_NOT_FOUND),
            (api.get_producer, ApiErrorId.ERR_PRODUCER_NOT_FOUND),
        ]
        for reader, expected_error in probes:
            resp = reader(NON_EXISTENT_UUID, ADMIN)
            validate_error(resp, expected_error, expected_status=404)

    def test_premises_list_filters_by_producer_and_paginates(self, api):
        """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. `offset` skips a number of leading rows and defaults to 0; it may not be negative."
        PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. `total_count` reflects the number of rows the caller is entitled to see after filtering, and `has_more` is true when rows remain beyond the current window."
        PRD §3.1: "Premises can be listed and narrowed by `producer_id`, `state_code`, `operation_type`, `registration_status` and `health_status`; each producer's accrued awards can be listed through its own reverse-lookup listing, optionally narrowed by award `status`; and each premises exposes its own reconciliation history, likewise narrowable by run `status`."

        Design: Corner/entities/premises_list_paginates_and_filters_by_producer
        """
        producer = register_producer(legal_name="Three Peaks")
        headers = make_producer_headers(producer["id"])
        for operation_type in ("COW_CALF", "FEEDLOT", "MARKET"):
            register_premises(
                producer["id"], operation_type=operation_type, state_code="CO", capacity=10
            )

        first_page, first_meta = validate_paginated(
            api.list_premises(headers, params={"producer_id": producer["id"], "limit": 2, "offset": 0})
        )
        assert len(first_page) == 2, "limit 2 must return exactly two rows"
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_page, second_meta = validate_paginated(
            api.list_premises(headers, params={"producer_id": producer["id"], "limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        for row in first_page + second_page:
            assert row["producer_id"] == producer["id"]
            assert row["registration_status"] == "PENDING_REVIEW"

    def test_second_approval_of_an_active_premises_is_an_invalid_transition(self, api):
        """PRD §3.1: "Approval by a `StateAnimalHealthOfficial` moves a premises from `PENDING_REVIEW` to `ACTIVE`, and is permitted only while the premises is in `PENDING_REVIEW`; attempting it from any other registration state is an invalid transition."
        PRD §2.5: "A tag lot whose status was forced by an external event — `RECALLED` or `VOIDED` — cannot supply an application and yields `ERR_LOT_NOT_ISSUABLE`; a `DEPLETED` lot is instead treated as a capacity failure and is handled in band 16; every other invalid transition yields `ERR_INVALID_STATE`."
        PRD §2.5: "Rules are evaluated **strictly in ascending priority order**, the first failing rule alone decides the response, and no side effect of any kind is applied once a rule has failed."

        Design: Corner/state_machines/approve_premises_twice_returns_invalid_state
        """
        producer = register_producer(legal_name="Twice Co")
        premises = register_premises(producer["id"], capacity=10)
        approved = approve_premises(premises["id"])
        assert approved["registration_status"] == "ACTIVE"

        resp = api.approve_premises(premises["id"], OFFICIAL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = read_premises(premises["id"])
        assert after["registration_status"] == "ACTIVE"
        assert after["version"] == approved["version"], (
            "a rejected transition applies no side effect, so version must not move"
        )


class TestDeclaredInitialStates:
    def test_new_records_start_in_their_declared_initial_states(self, api):
        """PRD §3.1: "A freshly registered premises begins with `registration_status` `PENDING_REVIEW`, `health_status` `CLEAR`, `animal_count` 0, `pending_hold_count` 0, and a null `last_hold_released_at` and `last_reconciliation_run_at`."
        PRD §3.2: "The new record begins in `PENDING_REVIEW` with `registered_by_user_id` set to the acting administrator's `X-User-ID`, a null `approved_by_user_id`, a `defect_report_count` of 0, a `conformance_score` of 100.00, `probation` false and an `issuance_cap` of 10000."
        PRD §3.3: "A successful issuance creates the lot in status `ISSUED`, increments the supplier's `version` by one, and re-derives the supplier's `issued_tag_count`, `conformance_score`, `probation` and `issuance_cap`."
        PRD §3.4: "The animal is created with `lifecycle_status` `ACTIVE`, `trace_status` `NORMAL`, `current_premises_id` equal to the birth premises, and its `ain` denormalised from the device."
        PRD §3.6: "A proposed hold is created in `PROPOSED` with `issued_by_user_id` set to the acting official's `X-User-ID`, a null `released_at`, and an `appeal_count` of 0."

        Design: Corner/state_machines/entities_start_in_their_declared_initial_states
        """
        producer = register_producer(legal_name="Initial Co")
        premises = register_premises(producer["id"], capacity=10)
        assert_premises(premises)
        assert premises["registration_status"] == "PENDING_REVIEW"
        assert premises["health_status"] == "CLEAR"
        assert premises["animal_count"] == 0
        assert premises["pending_hold_count"] == 0

        supplier = register_supplier(company_name="AllFlex North")
        assert supplier["status"] == "PENDING_REVIEW"
        assert supplier["approved_by_user_id"] is None
        assert supplier["defect_report_count"] == 0
        assert supplier["conformance_score"] == 100.00
        assert supplier["probation"] is False
        assert supplier["issuance_cap"] == 10000

        approve_premises(premises["id"])
        approve_supplier(supplier["id"])
        lot = issue_lot(supplier["id"], premises["id"], quantity=10)
        assert lot["status"] == "ISSUED"

        animal = validate_success(
            api.apply_tag(
                lot["id"],
                apply_tag_payload(
                    ain_for_serial(lot["serial_start"]),
                    premises["id"],
                    species="OVINE",
                    birth_date="2026-04-06",
                ),
                make_producer_headers(producer["id"]),
            ),
            expected_status=201,
        )
        assert animal["lifecycle_status"] == "ACTIVE"
        assert animal["trace_status"] == "NORMAL"
        assert animal["sighting_count"] == 1
        assert animal["last_sequence_no"] == 1

        hold = propose_hold(
            premises["id"],
            effective_from="2026-08-01T00:00:00Z",
            effective_until="2026-08-05T00:00:00Z",
        )
        assert hold["status"] == "PROPOSED"
        assert hold["released_at"] is None
        assert hold["appeal_count"] == 0


class TestEnvelopeAndPagination:
    def test_success_and_error_envelopes_match_the_fixed_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
        PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

        Design: Corner/endpoints/success_and_error_envelopes_match_the_fixed_shape
        """
        create_resp = api.create_producer(
            create_producer_payload(legal_name="Envelope Co", contact_email="ops@envelope.example"),
            ADMIN,
        )
        producer = validate_success(create_resp, expected_status=201)
        body = create_resp.json()
        assert_envelope_meta(body)
        assert body["response_type"] == "object"
        assert body["data"]["id"] == producer["id"]

        list_resp = api.list_premises(ADMIN, params={"producer_id": producer["id"]})
        rows, meta = validate_paginated(list_resp)
        assert list_resp.json()["response_type"] == "array"
        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "limit defaults to 10 when omitted"
        assert meta["offset"] == 0, "offset defaults to 0"

        error_resp = api.get_producer(NON_EXISTENT_UUID, ADMIN)
        error_data = validate_error(
            error_resp, ApiErrorId.ERR_PRODUCER_NOT_FOUND, expected_status=404
        )
        assert error_resp.json()["response_type"] == "error"
        assert error_data["message"].strip(), "message must be a non-empty explanation"

    def test_limit_outside_its_permitted_range_is_rejected(self, api):
        """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. `offset` skips a number of leading rows and defaults to 0; it may not be negative."
        PRD §2.3: "A `limit` outside its permitted range or a negative `offset` is a request-shape failure, not a silent clamp."
        PRD §2.5: "Any failure here is `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/pagination_limit_outside_bounds_is_rejected
        """
        producer = register_producer(legal_name="Page Co")

        too_large = api.list_premises(ADMIN, params={"producer_id": producer["id"], "limit": 101})
        validate_error(too_large, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        too_small = api.list_premises(ADMIN, params={"producer_id": producer["id"], "limit": 0})
        validate_error(too_small, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        at_bound = api.list_premises(ADMIN, params={"producer_id": producer["id"], "limit": 100})
        _rows, meta = validate_paginated(at_bound)
        assert meta["limit"] == 100, "limit 100 sits on the permitted upper bound"


class TestProgrammeClock:
    def test_logical_clock_reads_the_fixed_default_before_any_client_sets_it(self, api):
        """PRD §2.4: "Time in this system is a **logical clock**, never the host's wall clock. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. A `ProgramAdmin` may advance or rewind it through an administrative test-driving capability that accepts a single `to_iso8601` field and answers with the resulting `current_utc` value."
        PRD §2.4: "Every persisted record carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC string with three fractional digits (for example `2026-08-01T00:00:00.000Z`)."

        Design: Corner/endpoints/logical_clock_defaults_to_2026_08_01_before_any_set
        """
        first = validate_success(
            api.create_producer(
                create_producer_payload(legal_name="Clock Co", contact_email="ops@clock.example"),
                ADMIN,
            ),
            expected_status=201,
        )
        assert first["created_at"] == "2026-08-01T00:00:00.000Z"

        current_utc = set_clock("2026-09-15T12:30:00Z")
        assert current_utc.startswith("2026-09-15T12:30:00"), (
            f"the clock must answer with the instant it was driven to, got {current_utc!r}"
        )

        second = validate_success(
            api.create_producer(
                create_producer_payload(
                    legal_name="Clock Co Two", contact_email="ops2@clock.example"
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert second["created_at"] == "2026-09-15T12:30:00.000Z"


class TestVersionsAndImmediateConsistency:
    def test_version_advances_on_direct_mutation_and_on_cascaded_counter_change(self, api):
        """PRD §2.4: "Most records additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 and increments by one on every mutation of that record — including mutations that only touch derived counters such as an animal count or a conformance score."
        PRD §2.8: "Every record a cascade touches is a record that was mutated: its `updated_at` is refreshed and its `version` is incremented, even when the only change was a derived counter."
        PRD §3.3: "A successful issuance creates the lot in status `ISSUED`, increments the supplier's `version` by one, and re-derives the supplier's `issued_tag_count`, `conformance_score`, `probation` and `issuance_cap`."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation_including_cascades
        """
        producer = register_producer(legal_name="Version Co")
        premises = register_premises(producer["id"], capacity=10)
        assert premises["version"] == 1

        approved_premises = approve_premises(premises["id"])
        assert approved_premises["version"] == 2

        supplier = register_supplier(company_name="AllFlex North")
        assert supplier["version"] == 1
        approved_supplier = approve_supplier(supplier["id"])
        assert approved_supplier["version"] == 2

        lot = issue_lot(supplier["id"], premises["id"], quantity=10)
        assert read_supplier(supplier["id"])["version"] == 3, (
            "issuing a lot increments the supplier version by one"
        )

        validate_success(
            api.apply_tag(
                lot["id"],
                apply_tag_payload(ain_for_serial(lot["serial_start"]), premises["id"]),
                make_producer_headers(producer["id"]),
            ),
            expected_status=201,
        )
        after_apply = read_premises(premises["id"])
        assert after_apply["animal_count"] == 1
        assert after_apply["version"] > approved_premises["version"], (
            "the cascaded animal_count change is a mutation and must bump the premises version"
        )

    def test_apply_tag_response_already_carries_the_cascaded_projection(self, api):
        """PRD §3.4: "The animal is created with `lifecycle_status` `ACTIVE`, `trace_status` `NORMAL`, `current_premises_id` equal to the birth premises, and its `ain` denormalised from the device."
        PRD §3.4: "The lot's `applied_count` rises by one and its `unapplied_count` falls by one, moving the lot from `ISSUED` to `ACTIVE` on the first such application and from `ACTIVE` to `DEPLETED` if `unapplied_count` reaches 0. The birth premises' `animal_count` rises by one, and the owning producer's `enrolled_head_count` and `incentive_tier` are re-derived."

        Design: Corner/consistency_model/cascade_results_are_visible_in_the_triggering_response
        """
        scenario = setup_lot_scenario(capacity=10, quantity=10)
        lot = scenario["lot"]
        premises = scenario["premises"]

        animal = validate_success(
            api.apply_tag(
                lot["id"],
                apply_tag_payload(ain_for_serial(lot["serial_start"]), premises["id"]),
                scenario["producer_headers"],
            ),
            expected_status=201,
        )
        assert animal["current_premises_id"] == premises["id"], (
            "the projection is already applied in the creating response"
        )
        assert animal["lifecycle_status"] == "ACTIVE"

        assert read_premises(premises["id"])["animal_count"] == 1
        lot_after = read_tag_lot(lot["id"])
        assert lot_after["applied_count"] == 1
        assert lot_after["unapplied_count"] == 9
        assert lot_after["status"] == "ACTIVE"

        producer_after = read_producer(scenario["producer"]["id"])
        assert producer_after["enrolled_head_count"] == 1
        assert producer_after["incentive_tier"] == "TIER_1"
