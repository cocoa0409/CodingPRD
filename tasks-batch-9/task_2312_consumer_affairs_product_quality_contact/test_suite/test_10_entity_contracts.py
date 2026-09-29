"""The entity contract itself: projections, defaults, ownership of computed
fields, append-only ledgers, and the shape of a not-found answer."""

from test_helpers import (
    ADMIN,
    CLOCK_EPOCH,
    CLOCK_EPOCH_MS,
    ApiErrorId,
    add_complaint,
    add_contact,
    add_lot,
    assert_append_only_common_fields,
    assert_ids_exactly,
    assert_pagination_meta,
    assert_request_meta,
    assert_two_decimal_value,
    assert_versioned_common_fields,
    complaint_payload,
    consumer_payload,
    contact_payload,
    production_line_payload,
    production_lot_payload,
    run_quality_ops,
    seed_base_world,
    seed_shipped_kit,
    set_clock,
    staff_user_payload,
    triage,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_IDS = [f"00000000-0000-4000-8000-00000000000{c}" for c in "123456789abc"]


class TestEntityProjections:
    def test_staff_user_creation_returns_every_declared_field(self, api):
        """The registration answer carries the four common fields and version 1.

        PRD: "A `StaffUser` is registered with a human-readable `staff_code` (1
        to 32 characters, unique across all staff), a `full_name`, and exactly one
        `role` drawn from `CARE_AGENT`, `CARE_SUPERVISOR`, `QUALITY_LEAD`, or
        `REGULATORY_OFFICER`."

        Design: Corner/entities/corner_staff_user_creation_returns_every_declared_field
        """
        set_clock(api, CLOCK_EPOCH)

        response = api.create_staff_user(
            staff_user_payload(
                "AG1", "Ada Grant", "CARE_AGENT", authority_tier="TIER_2", is_active=True
            ),
            ADMIN,
        )
        staff = validate_success(response, 201)

        assert staff["staff_code"] == "AG1"
        assert staff["full_name"] == "Ada Grant"
        assert staff["role"] == "CARE_AGENT"
        assert staff["authority_tier"] == "TIER_2"
        assert staff["is_active"] is True
        assert_versioned_common_fields(staff, expected_version=1)
        assert staff["created_at"] == CLOCK_EPOCH_MS
        assert staff["updated_at"] == staff["created_at"]
        assert_request_meta(response)

    def test_consumer_read_returns_stored_values_and_a_zeroed_ledger(self, api):
        """A consumer with no history reads back neutral sentiment and empty accounts.

        PRD: "A newly created consumer's `sentiment_index` starts at the neutral
        baseline of 50."

        Design: Corner/entities/corner_consumer_retrieval_returns_stored_values
        """
        world = seed_base_world(
            api,
            actor_keys=("ag1",),
            consumer={
                "email": "rin@example.com",
                "phone": "+13125550100",
                "postal_code": "60601",
            },
            create_lot=False,
        )

        consumer = validate_success(
            api.get_consumer(world["consumer"]["id"], world.headers("ag1"))
        )

        assert consumer["external_ref"] == "C-1"
        assert consumer["full_name"] == "Rin Sato"
        assert consumer["email"] == "rin@example.com"
        assert consumer["phone"] == "+13125550100"
        assert consumer["postal_code"] == "60601"
        assert_two_decimal_value(consumer["sentiment_index"], 50.00)
        assert consumer["goodwill_authorized_cents"] == 0
        assert consumer["goodwill_outstanding_cents"] == 0
        assert consumer["goodwill_paid_cents"] == 0
        assert consumer["goodwill_voided_cents"] == 0
        assert consumer["complaint_count"] == 0
        assert consumer["open_kit_count"] == 0

    def test_complaint_listing_pages_with_the_envelope_counts(self, api):
        """Two pages of three complaints: the total is unpaged and has_more flips.

        PRD: "List responses report `limit`, `offset`, `total_count`, and
        `has_more` inside the envelope's `meta` object."

        Design: Corner/entities/corner_complaint_listing_paginates_with_envelope_fields
        """
        world = seed_base_world(api, actor_keys=("ag1",))
        add_contact(api, world, "ct1", channel="EMAIL", raw_message="Three issues.")
        for key, complaint_type in (
            ("q1", "QUALITY"),
            ("q2", "QUALITY"),
            ("q3", "PACKAGING"),
        ):
            add_complaint(api, world, key, complaint_type=complaint_type)
        agent = world.headers("ag1")

        first, first_meta = validate_paginated(
            api.list_complaints(agent, {"limit": 2, "offset": 0})
        )
        second, second_meta = validate_paginated(
            api.list_complaints(agent, {"limit": 2, "offset": 2})
        )

        assert len(first) == 2
        assert_pagination_meta(
            first_meta, total_count=3, has_more=True, limit=2, offset=0
        )
        assert len(second) == 1
        assert_pagination_meta(
            second_meta, total_count=3, has_more=False, limit=2, offset=2
        )
        assert_ids_exactly(
            first + second,
            [world["complaints"][key]["id"] for key in ("q1", "q2", "q3")],
        )


class TestNotFoundAnswers:
    def test_unknown_complaint_id_uses_the_complaint_specific_code(self, api):
        """A well-formed but unknown identifier is a typed 404, not a generic one.

        PRD: "Every `{id}` path parameter resolves to an existing row of the
        expected entity — otherwise a 404 specific to that entity:
        `ERR_CONSUMER_NOT_FOUND`, `ERR_PLANT_NOT_FOUND`,
        `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
        `ERR_PRODUCTION_LOT_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`,
        `ERR_COMPLAINT_NOT_FOUND`, `ERR_SAMPLE_KIT_NOT_FOUND`,
        `ERR_REMEDY_NOT_FOUND`, `ERR_REGULATORY_REPORT_NOT_FOUND`,
        `ERR_TREND_SIGNAL_NOT_FOUND`, `ERR_RESPONSE_TEMPLATE_NOT_FOUND`, or
        `ERR_STAFF_USER_NOT_FOUND`."

        Design: Corner/entities/corner_complaint_not_found_returns_404
        """
        world = seed_base_world(api, actor_keys=("ag1",), create_lot=False)

        response = api.get_complaint(
            "00000000-0000-4000-8000-000000000000", world.headers("ag1")
        )

        error = validate_error(response, ApiErrorId.COMPLAINT_NOT_FOUND, 404)
        assert error["message"].strip()

    def test_each_entity_path_answers_with_its_own_not_found_code(self, api):
        """Twelve reads, twelve distinct codes, no shared fallback.

        PRD: "Where a path nests identifiers, they are resolved strictly left to
        right and the first unresolvable one determines the error."

        Design: Corner/entities/corner_every_entity_path_404_uses_its_own_error_code
        """
        world = seed_base_world(api, actor_keys=("sup1", "ql1", "ro1"), create_lot=False)
        supervisor = world.headers("sup1")
        lead = world.headers("ql1")
        officer = world.headers("ro1")

        probes = [
            (api.get_staff_user(UNKNOWN_IDS[0], ADMIN), ApiErrorId.STAFF_USER_NOT_FOUND),
            (api.get_consumer(UNKNOWN_IDS[1], supervisor), ApiErrorId.CONSUMER_NOT_FOUND),
            (api.get_plant(UNKNOWN_IDS[2], lead), ApiErrorId.PLANT_NOT_FOUND),
            (
                api.get_production_line(UNKNOWN_IDS[3], lead),
                ApiErrorId.PRODUCTION_LINE_NOT_FOUND,
            ),
            (api.get_product(UNKNOWN_IDS[4], lead), ApiErrorId.PRODUCT_NOT_FOUND),
            (
                api.get_production_lot(UNKNOWN_IDS[5], lead),
                ApiErrorId.PRODUCTION_LOT_NOT_FOUND,
            ),
            (api.get_contact(UNKNOWN_IDS[6], supervisor), ApiErrorId.CONTACT_NOT_FOUND),
            (
                api.get_sample_kit(UNKNOWN_IDS[7], supervisor),
                ApiErrorId.SAMPLE_KIT_NOT_FOUND,
            ),
            (api.get_remedy(UNKNOWN_IDS[8], supervisor), ApiErrorId.REMEDY_NOT_FOUND),
            (
                api.get_regulatory_report(UNKNOWN_IDS[9], officer),
                ApiErrorId.REGULATORY_REPORT_NOT_FOUND,
            ),
            (api.get_trend_signal(UNKNOWN_IDS[10], lead), ApiErrorId.TREND_SIGNAL_NOT_FOUND),
            (
                api.get_response_template(UNKNOWN_IDS[11], supervisor),
                ApiErrorId.RESPONSE_TEMPLATE_NOT_FOUND,
            ),
        ]

        seen = []
        for response, expected in probes:
            error = validate_error(response, expected, 404)
            seen.append(error["error_id"])
        assert len(set(seen)) == 12, "two entity reads shared one not-found code"


class TestInputDiscipline:
    def test_contact_without_a_channel_is_a_validation_error(self, api):
        """A missing required body field is a 400, and nothing is written.

        PRD: "All required body fields for the endpoint are present — otherwise
        `ERR_VALIDATION` (400)."

        Design: Corner/entities/corner_contact_missing_required_channel_returns_validation
        """
        world = seed_base_world(api, actor_keys=("ag1",), create_lot=False)
        agent = world.headers("ag1")

        response = api.create_contact(
            {
                "consumer_id": world["consumer"]["id"],
                "received_at": CLOCK_EPOCH,
                "raw_message": "No channel supplied.",
            },
            agent,
        )
        validate_error(response, ApiErrorId.VALIDATION, 400)

        _rows, meta = validate_paginated(api.list_contacts(agent))
        assert meta["total_count"] == 0

    def test_omitted_optional_fields_take_their_declared_defaults(self, api):
        """Five defaults across three entities, including an enum and two booleans.

        PRD: "Each staff member also carries an `authority_tier` — one of
        `TIER_1`, `TIER_2`, or `TIER_3`, defaulting to `TIER_1` when omitted —
        that caps the goodwill they may approve, and an `is_active` boolean that
        defaults to true."

        Design: Corner/entities/corner_defaults_applied_when_optional_fields_omitted
        """
        set_clock(api, CLOCK_EPOCH)
        staff = validate_success(
            api.create_staff_user(staff_user_payload("AG1", "Ada Grant", "CARE_AGENT"), ADMIN),
            201,
        )
        assert staff["authority_tier"] == "TIER_1"
        assert staff["is_active"] is True

        world = seed_base_world(api, actor_keys=("ag2",))
        agent = world.headers("ag2")
        consumer = validate_success(
            api.create_consumer(consumer_payload("C-9", "Noa Vale"), agent), 201
        )
        assert consumer["is_vulnerable_flag"] is False

        contact = validate_success(
            api.create_contact(
                contact_payload(consumer["id"], channel="PHONE", raw_message="Stale pack."),
                agent,
            ),
            201,
        )
        complaint = validate_success(
            api.create_complaint(
                complaint_payload(contact["id"], complaint_type="QUALITY"), agent
            ),
            201,
        )
        assert complaint["foreign_object_class"] == "NONE"
        assert complaint["units_claimed"] == 1
        assert_two_decimal_value(complaint["provisional_severity_score"], 10.00)
        assert complaint["provisional_severity_band"] == "S4"

    def test_client_supplied_computed_fields_are_ignored_without_an_error(self, api):
        """Injected severity, identification and status values never reach the record.

        PRD: "Fields the server owns — everything described in this document as
        computed or system-assigned — are never accepted from a client. If
        supplied they are silently ignored and never stored. This step produces
        no error and no rejection."

        Design: Corner/entities/corner_computed_severity_fields_with_client_input_ignored
        """
        world = seed_base_world(api, actor_keys=("ag1",))
        add_contact(api, world, "ct1", channel="WEB", raw_message="Injecting fields.")

        complaint = validate_success(
            api.create_complaint(
                complaint_payload(
                    world["contacts"]["ct1"]["id"],
                    complaint_type="QUALITY",
                    provisional_severity_score=99.99,
                    provisional_severity_band="S1",
                    product_identification_status="UNRESOLVED",
                    handling_status="CLOSED",
                ),
                world.headers("ag1"),
            ),
            201,
        )

        assert_two_decimal_value(complaint["provisional_severity_score"], 10.00)
        assert complaint["provisional_severity_band"] == "S4"
        assert complaint["product_identification_status"] == "RESOLVED"
        assert complaint["lot_id"] == world["lot"]["id"]
        assert complaint["handling_status"] == "INTAKE"

    def test_client_supplied_system_fields_are_ignored_and_version_advances(self, api):
        """An injected id, created_at and version are all discarded.

        PRD: "Every resource in this system carries a server-minted `id`
        formatted as a UUID with no type prefix, and a `created_at` timestamp
        expressed as an ISO 8601 UTC instant with three fractional digits (for
        example `2026-08-01T00:00:00.000Z`)."

        Design: Corner/entities/corner_system_fields_are_server_minted_and_input_ignored
        """
        set_clock(api, CLOCK_EPOCH)
        world = seed_base_world(api, actor_keys=("ag1",), create_lot=False)
        agent = world.headers("ag1")

        created = validate_success(
            api.create_consumer(
                consumer_payload(
                    "C-2",
                    "Noa Vale",
                    postal_code="60601",
                    id="11111111-1111-4111-8111-111111111111",
                    created_at="1999-01-01T00:00:00Z",
                    version=42,
                ),
                agent,
            ),
            201,
        )
        assert created["id"] != "11111111-1111-4111-8111-111111111111"
        assert created["created_at"] == CLOCK_EPOCH_MS
        assert created["version"] == 1

        patched = validate_success(
            api.update_consumer(created["id"], {"phone": "+13125550101"}, agent)
        )
        assert patched["version"] == 2
        assert patched["phone"] == "+13125550101"
        assert patched["created_at"] == created["created_at"]

    def test_bad_enums_and_a_negative_count_are_all_validation_errors(self, api):
        """Two enum violations and one out-of-range integer share the same code.

        PRD: "Every enum field carries one of its declared values and every
        numeric field falls inside its declared range — otherwise
        `ERR_VALIDATION` (400)."

        Design: Corner/entities/corner_invalid_enum_and_out_of_range_inputs_rejected
        """
        world = seed_base_world(api, actor_keys=("ag1",), create_lot=False)
        agent = world.headers("ag1")
        add_contact(api, world, "ct1", raw_message="Bad enums incoming.")
        contact_id = world["contacts"]["ct1"]["id"]

        bad_type = api.create_complaint(
            {"contact_id": contact_id, "complaint_type": "MYSTERY"}, agent
        )
        bad_object = api.create_complaint(
            {
                "contact_id": contact_id,
                "complaint_type": "QUALITY",
                "foreign_object_class": "SPIKY",
            },
            agent,
        )
        negative_units = api.create_production_lot(
            production_lot_payload(
                world["product"]["id"],
                world["line"]["id"],
                batch_code="NEG-1",
                units_produced=-5,
            ),
            ADMIN,
        )

        for response in (bad_type, bad_object, negative_units):
            validate_error(response, ApiErrorId.VALIDATION, 400)

        _complaints, complaint_meta = validate_paginated(api.list_complaints(agent))
        assert complaint_meta["total_count"] == 0
        _lots, lot_meta = validate_paginated(api.list_production_lots(agent))
        assert lot_meta["total_count"] == 0


class TestAppendOnlyLedgers:
    def test_custody_events_carry_no_version_and_are_never_edited(self, api):
        """The dispatch event exposes id and created_at and nothing else common.

        PRD: "A `CustodyEvent` carries only `id` and `created_at`: it has no
        `updated_at` and no `version`, and no endpoint mutates or deletes one."

        Design: Corner/entities/corner_custody_event_is_immutable_and_carries_no_version
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        add_contact(api, world, "ct1", raw_message="Soft matter in the pack.")
        add_complaint(
            api, world, "cp1",
            complaint_type="FOREIGN_MATERIAL", foreign_object_class="SOFT",
        )
        world["complaints"]["cp1"] = triage(
            api, world, world["complaints"]["cp1"]["id"]
        )
        seed_shipped_kit(
            api, world, world["complaints"]["cp1"]["id"], "k1",
            kit_code="K-301", seal_id_issued="SEAL-301",
        )
        agent = world.headers("ag1")

        events, meta = validate_paginated(
            api.list_custody_events(world["kits"]["k1"]["id"], agent)
        )

        assert meta["total_count"] == 1
        event = events[0]
        assert event["event_type"] == "KIT_ISSUED"
        assert event["sequence_no"] == 1
        assert_append_only_common_fields(event)

        kit = validate_success(api.get_sample_kit(world["kits"]["k1"]["id"], agent))
        assert kit["custody_event_count"] == 1

    def test_signal_memberships_are_immutable_and_navigable_from_both_sides(self, api):
        """Three system-authored junction rows, readable from signal and complaint.

        PRD: "A `SignalMembership` is likewise limited to `id` and `created_at`,
        with no `updated_at` and no `version`, and no update endpoint exists for
        it."

        Design: Corner/entities/corner_signal_membership_is_an_immutable_junction_row
        """
        world = seed_base_world(
            api, actor_keys=("ag1", "ql1"), product="mug", create_lot=False
        )
        add_lot(
            api, world, "lotb", product_key="mug", batch_code="LOT-B",
            code_date="2026-07-10T00:00:00Z", units_produced=100000,
        )
        add_contact(api, world, "ct1", channel="SOCIAL", raw_message="Three chipped mugs.")
        for key in ("b1", "b2", "b3"):
            add_complaint(
                api, world, key,
                complaint_type="FOREIGN_MATERIAL", reported_batch_code="LOTB",
            )
        set_clock(api, "2026-08-02T00:00:00Z")
        run_quality_ops(api, world, dry_run=False)
        lead = world.headers("ql1")
        signals, _meta = validate_paginated(
            api.list_trend_signals(lead, {"lot_id": world["lots"]["lotb"]["id"]})
        )
        signal_id = signals[0]["id"]

        members, member_meta = validate_paginated(
            api.list_signal_memberships(signal_id, lead)
        )
        assert member_meta["total_count"] == 3
        for member in members:
            assert member["severity_weight"] == 1
            assert member["included_variant"] == "PROVISIONAL"
            assert_append_only_common_fields(member)

        from_complaint, complaint_meta = validate_paginated(
            api.list_complaint_signal_memberships(
                world["complaints"]["b1"]["id"], lead
            )
        )
        assert complaint_meta["total_count"] == 1
        assert from_complaint[0]["trend_signal_id"] == signal_id


class TestReferenceIntegrity:
    def test_line_creation_requires_an_existing_plant(self, api):
        """A body reference to a missing parent answers with the parent's own 404.

        PRD: "Every reference supplied in a request body resolves to an existing
        row of the referenced entity, checked after path-level existence, yielding
        the same family of 404 codes."

        Design: Corner/entities/corner_production_line_requires_an_existing_plant
        """
        world = seed_base_world(api, actor_keys=("ql1",), create_lot=False)
        lead = world.headers("ql1")

        refused = api.create_production_line(
            production_line_payload(
                "00000000-0000-4000-8000-0000000000ff",
                line_code="L-99",
                nominal_units_per_hour=9000,
            ),
            ADMIN,
        )
        validate_error(refused, ApiErrorId.PLANT_NOT_FOUND, 404)

        accepted = validate_success(
            api.create_production_line(
                production_line_payload(
                    world["plant"]["id"], line_code="L-02", nominal_units_per_hour=12000
                ),
                ADMIN,
            ),
            201,
        )
        assert accepted["plant_id"] == world["plant"]["id"]

        _lines, meta = validate_paginated(
            api.list_plant_production_lines(world["plant"]["id"], lead)
        )
        assert meta["total_count"] == 2, "the refused line was written anyway"

    def test_duplicate_link_is_navigable_from_the_surviving_complaint(self, api):
        """The self-referential link is recorded on the marked row alone.

        PRD: "Marking is permitted from `INTAKE` or from `TRIAGED`, and in both
        cases the complaint moves to `DUPLICATE` with `duplicate_of_complaint_id`
        recorded."

        Design: Corner/entities/corner_complaint_self_referential_duplicate_link_is_navigable
        """
        world = seed_base_world(api, actor_keys=("ag1", "sup1"))
        add_contact(
            api, world, "ct1", channel="EMAIL",
            raw_message="Same pack reported twice.",
        )
        for key in ("cpa", "cpb"):
            add_complaint(api, world, key, complaint_type="QUALITY")
        supervisor = world.headers("sup1")

        validate_success(
            api.mark_complaint_duplicate(
                world["complaints"]["cpb"]["id"],
                {"duplicate_of_complaint_id": world["complaints"]["cpa"]["id"]},
                supervisor,
            )
        )

        marked, marked_meta = validate_paginated(
            api.list_complaints(
                supervisor,
                {"duplicate_of_complaint_id": world["complaints"]["cpa"]["id"]},
            )
        )
        assert marked_meta["total_count"] == 1
        assert marked[0]["id"] == world["complaints"]["cpb"]["id"]

        _rows, duplicate_meta = validate_paginated(
            api.list_complaints(supervisor, {"handling_status": "DUPLICATE"})
        )
        assert duplicate_meta["total_count"] == 1

        survivor = validate_success(
            api.get_complaint(world["complaints"]["cpa"]["id"], supervisor)
        )
        assert survivor["duplicate_of_complaint_id"] is None
        assert survivor["handling_status"] == "INTAKE"
