"""Entity-level contract: evidence-item intake, reads, lists, shape and reference checks."""

from test_helpers import (
    NON_EXISTENT_UUID,
    adjudicate_case,
    assert_chain_event,
    assert_chain_sequence_gapless,
    assert_evidence_item,
    assert_millisecond_timestamp,
    charge_case,
    disposition_order_payload,
    evidence_item_payload,
    is_valid_uuid,
    issue_notice,
    log_and_store_item,
    log_item,
    read_case,
    read_item,
    set_clock,
    setup_corner_base,
    storage_location_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEvidenceItemIntake:
    """Intake writes the barcode, the derived storage category and both starting states."""

    def test_intake_returns_barcode_and_initial_states_on_both_axes(self, api):
        """Logging one GENERAL item mints the barcode and fixes both starting states.

        PRD 3.2: "The stored `barcode` is then the `agency_code`, a hyphen, the
        `case_number`, a hyphen, the four-character zero-padded `item_sequence`, a hyphen,
        and the check digit."
        PRD 3.2: "For agency `CPD`, case `26-00001` and sequence 1, the barcode is
        `CPD-26-00001-0001-2`."
        PRD 3.2: "`intake_at` is set from the logical clock and becomes the anchor both of
        the preliminary retention variant and of storage-cost recovery at auction
        settlement."
        PRD 3.2: "`custody_state` starts at `LOGGED` and `disposition_state` at
        `RETAINED`, with `storage_location_id`, `current_holder_id` null and
        `open_transfer_count` at 0."
        PRD 3.2: "A `GENERAL` item requires `HIGH_VALUE_VAULT` when its appraised value is
        at least 500000 cents — that is, five thousand dollars or more, with exactly 500000
        already qualifying — and `GENERAL` otherwise."
        PRD 3.2: "A preliminary retention determination is created immediately, writing
        `retention_release_at` and `retention_basis` onto the item."
        PRD 3.2: "Finally the owning case has `item_count` and `undisposed_item_count` each
        incremented by 1 and its `version` incremented by 1."
        PRD 4: "Operations that bring a new resource into existence — registering a room,
        statute, location or custodian, opening a case, logging an evidence item, recording
        a retention determination, requesting a custody transfer, opening a disposition
        order, issuing an owner notice, or scheduling an audit session — return
        `201 Created`."

        Design: Corner/entities/evidence_item_intake_creation_returns_barcode_and_initial_states
        """
        env = setup_corner_base()

        item = validate_success(
            api.create_evidence_item(
                evidence_item_payload(
                    env["case1_id"],
                    item_description="Pawn ticket folder",
                    category="GENERAL",
                    packaging_type="RIGID_BOX",
                    appraised_value_cents=120000,
                    seized_at="2026-07-31T12:00:00Z",
                ),
                env["tech_headers"],
            ),
            201,
        )

        assert_evidence_item(item)
        assert item["item_sequence"] == 1
        assert item["barcode"] == "CPD-26-00001-0001-2"
        assert item["intake_at"] == "2026-08-01T00:00:00.000Z"
        assert item["seized_at"] == "2026-07-31T12:00:00.000Z"
        assert item["custody_state"] == "LOGGED"
        assert item["disposition_state"] == "RETAINED"
        assert item["storage_location_id"] is None
        assert item["current_holder_id"] is None
        assert item["open_transfer_count"] == 0
        # 120000 cents is below the 500000-cent vault threshold, so a plain bin will do.
        assert item["required_storage_category"] == "GENERAL"
        assert item["retention_basis"] == "PRELIMINARY"
        # Intake at 2026-08-01 plus the statute's full 365 whole days.
        assert item["retention_release_at"] == "2027-08-01T00:00:00.000Z"

        determinations, meta = validate_paginated(
            api.list_retention_determinations(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert determinations[0]["resolved_basis"] == "PRELIMINARY"
        assert determinations[0]["superseded"] is False

        case = read_case(env, env["case1_id"])
        assert case["item_count"] == 1
        assert case["undisposed_item_count"] == 1

    def test_is_found_property_defaults_to_false_and_widens_the_notice_window(self, api):
        """Omitting the flag materialises false; supplying true widens the claim window.

        PRD 3.2: "The optional `is_found_property` flag defaults to false; setting it true
        marks the item as found or unclaimed property, which both widens the owner-notice
        window and later exempts the item from the case-status gate on disposition."
        PRD 3.6: "The base period is 90 days when the item's `is_found_property` flag is
        true, and 30 days otherwise."
        PRD 3.6: "Publication earns a further 15 days on top, because a notice in a
        newspaper reaches a claimant more slowly than a certified letter or a conversation;
        `CERTIFIED_MAIL` and `IN_PERSON` add nothing."
        PRD 3.6: "The deadline is `notified_at` plus the sum of the base period and the
        extension, added as whole days."

        Design: Corner/entities/evidence_item_is_found_property_defaults_to_false
        """
        env = setup_corner_base()
        defaulted_payload = evidence_item_payload(
            env["case1_id"],
            item_description="Seized toolbox",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=4000,
            seized_at="2026-07-31T12:00:00Z",
        )
        assert "is_found_property" not in defaulted_payload

        defaulted = validate_success(
            api.create_evidence_item(defaulted_payload, env["tech_headers"]), 201
        )
        explicit = validate_success(
            api.create_evidence_item(
                evidence_item_payload(
                    env["case1_id"],
                    item_description="Bicycle found in alley",
                    category="GENERAL",
                    packaging_type="CHAIN_TAG_ONLY",
                    appraised_value_cents=4000,
                    seized_at="2026-07-31T12:00:00Z",
                    is_found_property=True,
                ),
                env["tech_headers"],
            ),
            201,
        )

        assert defaulted["is_found_property"] is False
        assert explicit["is_found_property"] is True
        # The default is materialised on the stored row rather than left null.
        assert read_item(env, defaulted["id"])["is_found_property"] is False

        seized_claim = issue_notice(env, defaulted["id"], notice_method="CERTIFIED_MAIL")
        found_claim = issue_notice(env, explicit["id"], notice_method="CERTIFIED_MAIL")

        assert seized_claim["notified_at"] == "2026-08-01T00:00:00.000Z"
        # 30 whole days for seized property noticed by certified mail.
        assert seized_claim["claim_deadline_at"] == "2026-08-31T00:00:00.000Z"
        assert found_claim["notified_at"] == "2026-08-01T00:00:00.000Z"
        # 90 whole days for found property noticed by certified mail.
        assert found_claim["claim_deadline_at"] == "2026-10-30T00:00:00.000Z"

    def test_identity_intake_instant_and_sequence_are_server_generated(self, api):
        """Two intakes across a clock move show the server minting identity and instants.

        PRD 2.4: "Every persisted resource is addressed at the API root and carries a
        server-minted `id` formatted as a UUID with no type prefix, plus a `created_at`
        timestamp rendered as an ISO 8601 UTC instant with three fractional digits (for
        example `2026-08-01T00:00:00.000Z`)."
        PRD 3.2: "`intake_at` is set from the logical clock and becomes the anchor both of
        the preliminary retention variant and of storage-cost recovery at auction
        settlement."
        PRD 3.2: "First the service computes `item_sequence` as one more than the number of
        evidence items already recorded against the same `case_id`; disposed items are
        counted, so a sequence number is never reused within a case."
        PRD 3.2: "`custody_state` starts at `LOGGED` and `disposition_state` at
        `RETAINED`, with `storage_location_id`, `current_holder_id` null and
        `open_transfer_count` at 0."

        Design: Corner/entities/evidence_item_system_fields_generated_by_server
        """
        env = setup_corner_base()
        first = log_item(
            env,
            item_description="First intake",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=100,
            seized_at="2026-07-31T12:00:00Z",
        )
        set_clock("2026-08-03T09:30:00Z")

        second = validate_success(
            api.create_evidence_item(
                evidence_item_payload(
                    env["case1_id"],
                    item_description="Second intake",
                    category="GENERAL",
                    packaging_type="PAPER_BAG",
                    appraised_value_cents=100,
                    seized_at="2026-07-31T12:00:00Z",
                ),
                env["tech_headers"],
            ),
            201,
        )

        assert is_valid_uuid(first["id"])
        assert is_valid_uuid(second["id"])
        assert first["id"] != second["id"]
        assert_millisecond_timestamp(first["created_at"])
        assert_millisecond_timestamp(second["created_at"])
        # intake_at tracks the logical clock, not the client-supplied seized_at.
        assert first["intake_at"] == "2026-08-01T00:00:00.000Z"
        assert second["intake_at"] == "2026-08-03T09:30:00.000Z"
        assert first["seized_at"] == "2026-07-31T12:00:00.000Z"
        assert second["seized_at"] == "2026-07-31T12:00:00.000Z"
        assert first["item_sequence"] == 1
        assert second["item_sequence"] == 2
        assert first["barcode"] == "CPD-26-00001-0001-2"
        assert second["barcode"] == "CPD-26-00001-0002-9"
        assert first["custody_state"] == "LOGGED"
        assert second["custody_state"] == "LOGGED"
        assert first["disposition_state"] == "RETAINED"
        assert second["disposition_state"] == "RETAINED"


class TestEvidenceItemReadAndList:
    """Reading one item back, and paging the collection."""

    def test_retrieval_returns_the_stored_row_unchanged(self, api):
        """A read echoes the creation response and mutates nothing.

        PRD 2.4: "Property rooms, offense statutes, storage locations, custodians, cases,
        evidence items, retention determinations, custody transfers, disposition orders,
        owner claims, audit sessions and discrepancies additionally carry `updated_at`,
        refreshed on every mutation, and `version`, an integer that increments by one on
        every mutation — including mutations that only touch derived counters."
        PRD 2.2: "The `data` field contains the resource object or an array of resource
        objects."
        PRD 4: "Every other operation, including all reads, all state transitions on an
        existing resource, the nightly sweep and the clock capability, returns `200 OK`."

        Design: Corner/entities/evidence_item_retrieval_returns_stored_row
        """
        env = setup_corner_base()
        created = log_item(
            env,
            item_description="Pawn ticket folder",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=120000,
            seized_at="2026-07-31T12:00:00Z",
        )

        fetched = validate_success(
            api.get_evidence_item(created["id"], env["aud_headers"]), 200
        )

        assert fetched["id"] == created["id"]
        assert fetched["item_description"] == "Pawn ticket folder"
        assert fetched["category"] == "GENERAL"
        assert fetched["packaging_type"] == "RIGID_BOX"
        assert fetched["appraised_value_cents"] == 120000
        assert fetched["barcode"] == "CPD-26-00001-0001-2"
        assert fetched["case_id"] == env["case1_id"]
        assert fetched["custody_state"] == "LOGGED"
        assert fetched["disposition_state"] == "RETAINED"
        # A read is not a mutation, so neither version nor updated_at moves.
        assert fetched["version"] == created["version"]
        assert fetched["created_at"] == created["created_at"]
        assert fetched["updated_at"] == created["updated_at"]

    def test_listing_pages_disjointly_and_reports_total_count(self, api):
        """Two pages of two cover three items, and the default limit returns them all.

        PRD 2.3: "`limit` sets the maximum number of rows returned; when omitted it
        defaults to 10, its minimum accepted value is 1 and its maximum accepted value is
        100."
        PRD 2.3: "`offset` sets the number of rows to skip and defaults to 0."
        PRD 2.3: "Unless a specific endpoint states otherwise, list endpoints return rows
        sorted by creation timestamp in ascending order."
        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope."
        PRD 2.4: "Evidence items may be filtered by `case_id`, `storage_location_id`,
        `current_holder_id`, `custody_state` and `disposition_state`."

        Design: Corner/entities/evidence_item_listing_paginates_with_total_count
        """
        env = setup_corner_base()
        item1 = log_item(
            env,
            item_description="Item one",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=1000,
            seized_at="2026-07-31T12:00:00Z",
        )
        item2 = log_item(
            env,
            item_description="Item two",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=2000,
            seized_at="2026-07-31T12:05:00Z",
        )
        item3 = log_item(
            env,
            item_description="Item three",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=3000,
            seized_at="2026-07-31T12:10:00Z",
        )

        first_response = api.list_evidence_items(
            env["manager"], params={"case_id": env["case1_id"], "limit": 2, "offset": 0}
        )
        first_page, first_meta = validate_paginated(first_response)
        second_page, second_meta = validate_paginated(
            api.list_evidence_items(
                env["manager"],
                params={"case_id": env["case1_id"], "limit": 2, "offset": 2},
            )
        )

        assert first_response.json()["response_type"] == "array"
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert [row["id"] for row in first_page] == [item1["id"], item2["id"]]

        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["limit"] == 2
        assert second_meta["offset"] == 2
        assert [row["id"] for row in second_page] == [item3["id"]]

        all_rows, all_meta = validate_paginated(
            api.list_evidence_items(env["manager"], params={"case_id": env["case1_id"]})
        )
        assert all_meta["limit"] == 10
        assert all_meta["offset"] == 0
        assert all_meta["total_count"] == 3
        assert all_meta["has_more"] is False
        assert [row["id"] for row in all_rows] == [item1["id"], item2["id"], item3["id"]]


class TestRequestShapeAndReferenceResolution:
    """Shape violations, unknown path identifiers and unresolvable body references."""

    def test_case_read_with_an_unknown_identifier_is_not_found(self, api):
        """A path identifier that matches no case yields that resource's own 404.

        PRD 2.4: "That identifier is resolved before anything in the body is examined, and
        it produces the 404 belonging to its own resource type: `roomId` yields
        `ERR_PROPERTY_ROOM_NOT_FOUND`, `statuteId` yields `ERR_OFFENSE_STATUTE_NOT_FOUND`,
        `locationId` yields `ERR_STORAGE_LOCATION_NOT_FOUND`, `custodianId` yields
        `ERR_CUSTODIAN_NOT_FOUND`, `caseId` yields `ERR_CASE_NOT_FOUND`, `itemId` yields
        `ERR_EVIDENCE_ITEM_NOT_FOUND`, `determinationId` yields
        `ERR_RETENTION_DETERMINATION_NOT_FOUND`, `transferId` yields
        `ERR_CUSTODY_TRANSFER_NOT_FOUND`, `orderId` yields
        `ERR_DISPOSITION_ORDER_NOT_FOUND`, `claimId` yields `ERR_OWNER_CLAIM_NOT_FOUND`,
        `sessionId` yields `ERR_AUDIT_SESSION_NOT_FOUND`, `discrepancyId` yields
        `ERR_DISCREPANCY_NOT_FOUND`, and `eventId` yields `ERR_CHAIN_EVENT_NOT_FOUND`."
        PRD 2.10: "The path-templated identifier resolves — the resource-specific 404 named
        in §2.4, on every endpoint with a templated path segment."

        Design: Corner/entities/case_retrieval_with_unknown_id_not_found
        """
        env = setup_corner_base()

        error = validate_error(
            api.get_case(NON_EXISTENT_UUID, env["manager"]), "ERR_CASE_NOT_FOUND", 404
        )

        assert error["error_id"] == "ERR_CASE_NOT_FOUND"
        rows, meta = validate_paginated(
            api.list_cases(env["manager"], params={"property_room_id": env["room_id"]})
        )
        assert meta["total_count"] == 3
        assert sorted(row["case_number"] for row in rows) == [
            "26-00001",
            "26-00002",
            "26-00003",
        ]

    def test_intake_without_seized_at_is_rejected_and_consumes_no_sequence(self, api):
        """Omitting a required input field is a shape violation that writes nothing.

        PRD 3.2: "Logging an item is the work of an `EvidenceTechnician`, who submits the
        `case_id` the item was seized under, an `item_description` as written in the field,
        the `category` — one of `GENERAL`, `BIOLOGICAL`, `CURRENCY`, `FIREARM`, `NARCOTICS`
        or `OVERSIZED` — the `packaging_type` actually applied, drawn from
        `SEALED_ENVELOPE`, `PAPER_BAG`, `RIGID_BOX`, `SHARPS_TUBE`, `PALLET_WRAP` and
        `CHAIN_TAG_ONLY`, an `appraised_value_cents` of at least 0 and at most 100000000,
        and the `seized_at` instant at which the item was seized or found."
        PRD 2.10: "Request shape: required fields present, types and enum values valid, and
        conditionally required fields honoured — `ERR_INVALID_REQUEST` (400), on every
        endpoint with a request body."
        PRD 3.2: "First the service computes `item_sequence` as one more than the number of
        evidence items already recorded against the same `case_id`; disposed items are
        counted, so a sequence number is never reused within a case."

        Design: Corner/entities/evidence_item_intake_missing_required_seized_at_rejected
        """
        env = setup_corner_base()
        payload = evidence_item_payload(
            env["case1_id"],
            item_description="No seizure timestamp",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=500,
        )
        del payload["seized_at"]

        validate_error(
            api.create_evidence_item(payload, env["tech_headers"]),
            "ERR_INVALID_REQUEST",
            400,
        )

        rows, meta = validate_paginated(
            api.list_evidence_items(env["manager"], params={"case_id": env["case1_id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []
        case = read_case(env, env["case1_id"])
        assert case["item_count"] == 0
        assert case["undisposed_item_count"] == 0

        # No sequence was consumed, so the next successful intake is still number one.
        accepted = log_item(
            env,
            item_description="Pawn ticket folder",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=120000,
            seized_at="2026-07-31T12:00:00Z",
        )
        assert accepted["item_sequence"] == 1
        assert accepted["barcode"] == "CPD-26-00001-0001-2"

    def test_storage_location_enum_and_range_violations_are_rejected(self, api):
        """An undeclared category and a capacity below the floor both fail the shape check.

        PRD 3.1: "Each `StorageLocation` names its owning room through `property_room_id`
        and carries a `code` of 1 to 16 characters that must be unique within that room — a
        duplicate is refused with `ERR_DUPLICATE_LOCATION_CODE` — together with a
        `category` of `GENERAL`, `REFRIGERATED`, `HIGH_VALUE_VAULT` or `OVERSIZED_YARD` and
        a `capacity_slots` count of at least 1 and at most 1000."
        PRD 2.10: "Request shape: required fields present, types and enum values valid, and
        conditionally required fields honoured — `ERR_INVALID_REQUEST` (400), on every
        endpoint with a request body."
        PRD 2.4: "Storage locations may be filtered by `property_room_id`, `category`,
        `status` and `sealed_by_audit_session_id`."

        Design: Corner/entities/storage_location_create_invalid_enum_category_rejected
        """
        env = setup_corner_base()

        validate_error(
            api.create_storage_location(
                storage_location_payload(
                    env["room_id"],
                    code="X-01",
                    category="FREEZER_ANNEX",
                    capacity_slots=4,
                ),
                env["manager"],
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        validate_error(
            api.create_storage_location(
                storage_location_payload(
                    env["room_id"], code="X-02", category="GENERAL", capacity_slots=0
                ),
                env["manager"],
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        rows, meta = validate_paginated(
            api.list_storage_locations(
                env["manager"], params={"property_room_id": env["room_id"]}
            )
        )
        assert meta["total_count"] == 5
        assert sorted(row["code"] for row in rows) == [
            "G-01",
            "G-09",
            "R-01",
            "R-09",
            "V-01",
        ]

    def test_intake_against_an_unknown_case_reports_the_case_not_found(self, api):
        """A body reference that resolves to nothing raises that resource's 404, not 400.

        PRD 2.4: "Identifier fields carried in a request body are resolved afterwards, in
        the order in which the endpoint declares its inputs, and raise the same family of
        404 codes."
        PRD 2.10: "Every identifier field in the request body resolves, in the endpoint's
        declared input order — the resource-specific 404 codes; a scanned `barcode` that
        matches no evidence item yields `ERR_BARCODE_NOT_FOUND` (404)."
        PRD 3.2: "First the service computes `item_sequence` as one more than the number of
        evidence items already recorded against the same `case_id`; disposed items are
        counted, so a sequence number is never reused within a case."

        Design: Corner/entities/evidence_item_requires_existing_parent_case_not_found
        """
        env = setup_corner_base()

        validate_error(
            api.create_evidence_item(
                evidence_item_payload(
                    NON_EXISTENT_UUID,
                    item_description="Orphan item",
                    category="GENERAL",
                    packaging_type="PAPER_BAG",
                    appraised_value_cents=100,
                    seized_at="2026-07-31T12:00:00Z",
                ),
                env["tech_headers"],
            ),
            "ERR_CASE_NOT_FOUND",
            404,
        )

        rows, meta = validate_paginated(api.list_evidence_items(env["manager"]))
        assert meta["total_count"] == 0
        assert rows == []
        # No case consumed a sequence number, so the first real intake is still number one.
        accepted = log_item(
            env,
            item_description="Pawn ticket folder",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=120000,
            seized_at="2026-07-31T12:00:00Z",
        )
        assert accepted["item_sequence"] == 1
        assert accepted["barcode"] == "CPD-26-00001-0001-2"

    def test_disposition_order_with_an_unknown_owner_claim_is_not_found(self, api):
        """A return-to-owner order citing a nonexistent claim fails on that reference.

        PRD 3.7: "An `owner_claim_id` is required when the type is `RETURN_TO_OWNER` and
        must be null for every other type; a `reserve_price_cents` of at least 0 is
        required when the type is `AUCTION` and must be null otherwise."
        PRD 2.10: "Every identifier field in the request body resolves, in the endpoint's
        declared input order — the resource-specific 404 codes; a scanned `barcode` that
        matches no evidence item yields `ERR_BARCODE_NOT_FOUND` (404)."
        PRD 2.4: "Identifier fields carried in a request body are resolved afterwards, in
        the order in which the endpoint declares its inputs, and raise the same family of
        404 codes."
        PRD 3.4: "Any item whose newly computed `retention_release_at` is at or before the
        current instant and whose `custody_state` is `STORED` continues in the same request
        from `RETAINED` to `DISPOSAL_ELIGIBLE`, and the room's `disposal_eligible_count`
        and `posture` are recomputed as a consequence."

        Design: Corner/entities/disposition_order_body_fk_owner_claim_not_found
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Recovered road bicycle",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=40000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        # The FINAL variant floors at intake plus 90 days, which is 2026-10-30.
        set_clock("2026-10-30T00:00:00Z")
        adjudicate_case(env, env["case2_id"])
        matured = read_item(env, item["id"])
        assert matured["retention_release_at"] == "2026-10-30T00:00:00.000Z"
        assert matured["disposition_state"] == "DISPOSAL_ELIGIBLE"

        validate_error(
            api.create_disposition_order(
                disposition_order_payload(
                    item["id"],
                    "RETURN_TO_OWNER",
                    env["tech_id"],
                    owner_claim_id=NON_EXISTENT_UUID,
                ),
                env["tech_headers"],
            ),
            "ERR_OWNER_CLAIM_NOT_FOUND",
            404,
        )

        after = read_item(env, item["id"])
        assert after["disposition_state"] == "DISPOSAL_ELIGIBLE"
        assert after["custody_state"] == "STORED"
        orders, meta = validate_paginated(
            api.list_disposition_orders(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert orders == []


class TestChainOfCustodyLedger:
    """The chain of custody ledger is append-only and carries no version."""

    def test_chain_entries_are_immutable_versionless_and_sequenced(self, api):
        """Intake then storage assignment leave two immutable, gaplessly numbered entries.

        PRD 2.4: "Chain of custody entries are the single exception: a `ChainEvent` is an
        immutable ledger line and carries only `id` and `created_at`; it has neither
        `updated_at` nor `version`."
        PRD 2.12: "Entries also carry `sequence_no`, a 1-based and gapless sequence **per
        evidence item**, assigned in ascending `occurred_at` order and, where two entries
        share an instant, in ascending `created_at` order."
        PRD 2.12: "The chain of custody document for an item is simply that item's entries
        read in `sequence_no` order."
        PRD 3.2: "The first chain of custody entry is appended with `event_type` of
        `INTAKE` and `sequence_no` of 1."
        PRD 3.3: "A successful assignment writes `storage_location_id` onto the item,
        increments the chosen location's `occupied_slots` by 1 and that location's
        `version` by 1, appends a chain entry with `event_type` of `STORAGE_ASSIGN`, and
        recomputes the room's `posture`."
        PRD 2.1: "Chain of custody entries record the acting role in `actor_role` in all
        cases, and populate `actor_custodian_id` only when the acting principal is an
        entity-backed custodian; entries produced by the nightly sweep or by a cascade
        record `SYSTEM` in `actor_role` and leave `actor_custodian_id` null."

        Design: Corner/entities/chain_event_records_are_immutable_and_versionless
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            location_id=env["loc_g_id"],
            item_description="Pawn ticket folder",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=120000,
            seized_at="2026-07-31T12:00:00Z",
        )

        rows, meta = validate_paginated(
            api.list_chain_events(
                env["aud_headers"], params={"evidence_item_id": item["id"]}
            )
        )

        assert meta["total_count"] == 2
        ordered = sorted(rows, key=lambda event: event["sequence_no"])
        assert [(event["sequence_no"], event["event_type"]) for event in ordered] == [
            (1, "INTAKE"),
            (2, "STORAGE_ASSIGN"),
        ]
        assert_chain_sequence_gapless(rows)
        for event in ordered:
            assert_chain_event(event)
            assert event["evidence_item_id"] == item["id"]
            assert event["actor_role"] == "EvidenceTechnician"
            assert event["actor_custodian_id"] == env["tech_id"]
            assert event["occurred_at"] == "2026-08-01T00:00:00.000Z"
            assert "version" not in event or event["version"] is None
            assert "updated_at" not in event or event["updated_at"] is None

        fetched = validate_success(
            api.get_chain_event(ordered[0]["id"], env["aud_headers"]), 200
        )
        assert fetched == ordered[0]
