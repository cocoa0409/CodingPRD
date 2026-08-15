"""Terminal, berth, and vessel registry: creation defaults, field validation,
uniqueness scopes, FK integrity, pagination, and read-after-write consistency."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_berth,
    assert_terminal,
    assert_terminal_counters,
    assert_vessel,
    create_berth,
    create_berth_payload,
    create_terminal,
    create_vessel,
    create_vessel_payload,
    create_port_call_payload,
    make_vessel_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HARBORMASTER = TEST_USERS["harbormaster_headers"]


class TestTerminalCreationDefaults:
    def test_terminal_created_with_clean_operational_defaults(self, api):
        """PRD §3.1: "A newly created terminal starts clean: `posture` is
        `OPERATIONAL`, the occupancy counters `occupied_berth_count`,
        `active_berth_count`, and `free_berth_count` are all zero, and the
        checkpoint counter `ops_run_index` starts at 0."
        PRD §2.6: "`version` — an integer that increments with every
        modification of the resource; it is the basis for the
        optimistic-concurrency rules of §2.8."

        Design: Corner/entities/terminal_creation_applies_defaults
        """
        terminal = create_terminal()
        assert_terminal(terminal)
        assert terminal["posture"] == "OPERATIONAL"
        assert terminal["ops_run_index"] == 0
        assert terminal["occupied_berth_count"] == 0
        assert terminal["active_berth_count"] == 0
        assert terminal["free_berth_count"] == 0
        assert terminal["version"] == 1

    def test_terminal_read_reflects_same_computed_fields_immediately(self, api):
        """PRD §2.10: "Child mutations that change a parent's derived state —
        berth occupancy, aboard counts, invoice totals — propagate upward
        immediately: consistency in this system is immediate, never deferred."
        PRD §3.1: "A newly created terminal starts clean: `posture` is
        `OPERATIONAL`, the occupancy counters `occupied_berth_count`,
        `active_berth_count`, and `free_berth_count` are all zero, and the
        checkpoint counter `ops_run_index` starts at 0."

        Design: Corner/entities/terminal_creation_applies_defaults
        """
        terminal = create_terminal()
        fetched = validate_success(api.get_terminal(terminal["id"], HARBORMASTER))
        assert_terminal(fetched)
        assert fetched["posture"] == terminal["posture"] == "OPERATIONAL"
        assert fetched["ops_run_index"] == terminal["ops_run_index"] == 0
        assert fetched["free_berth_count"] == terminal["free_berth_count"] == 0
        assert fetched["version"] == terminal["version"]


class TestRegistryValidation:
    def test_berth_get_unknown_id_returns_not_found(self, api):
        """PRD §2.9: "3. Existence: path ids and body foreign-key references
        exist, validated left-to-right — otherwise `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/berth_get_not_found_returns_404
        """
        create_terminal()
        resp = api.get_berth(NON_EXISTENT_UUID, HARBORMASTER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_terminal_missing_required_fields_returns_400(self, api):
        """PRD §2.9: "6. Request body shape: required fields present, types and
        enum values valid, integer ranges respected — otherwise
        `ERR_VALIDATION` (400)."
        PRD §3.1: "a `PortAuthorityAdmin` registers the **Terminal** itself: a
        display `name`, the `max_apron_slots` ceiling on how many service orders
        may be concurrently `IN_PROGRESS` anywhere on the apron, and the
        `taxi_dispatch_capacity_per_window` ceiling on ground-transport
        dispatches per fifteen-minute window."

        Design: Corner/entities/terminal_missing_required_field_returns_400
        """
        resp = api.create_terminal({"name": "T1"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        _, meta = validate_paginated(api.list_terminals(ADMIN))
        assert meta["total_count"] == 0, "a rejected create must not persist"

    def test_manifest_entry_unknown_direction_enum_returns_400(self, api):
        """PRD §2.9: "6. Request body shape: required fields present, types and
        enum values valid, integer ranges respected — otherwise
        `ERR_VALIDATION` (400)."
        PRD §3.5: "The `direction` selects the entire flow: an `EMBARK` entry
        begins in `BOOKED`; a `DEBARK` entry begins `ABOARD`."

        Design: Corner/entities/manifest_entry_invalid_enum_returns_400
        """
        terminal = create_terminal()
        vessel = create_vessel(terminal["id"])
        call_resp = api.create_port_call(
            create_port_call_payload(terminal["id"], vessel["id"]),
            make_vessel_agent_headers(vessel["id"]))
        port_call = validate_success(call_resp, 201)

        resp = api.create_manifest_entry(
            port_call["id"],
            {"passenger_ref": "P1", "direction": "SIDEWAYS",
             "cabin_class": "STANDARD"},
            make_vessel_agent_headers(vessel["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_berth_create_unknown_terminal_returns_404(self, api):
        """PRD §2.9: "3. Existence: path ids and body foreign-key references
        exist, validated left-to-right — otherwise `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/berth_create_unknown_terminal_returns_404
        """
        resp = api.create_berth(
            create_berth_payload(NON_EXISTENT_UUID), ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestComputedAndSystemFields:
    def test_port_call_aboard_counters_ignore_client_input(self, api):
        """PRD §3.2: "Two computed counters track the day: `passengers_aboard`
        counts the call's manifest entries currently in `EMBARKED`, and
        `bags_aboard` counts the call's baggage items currently in `LOADED`."
        PRD §3.2: "The creation payload names the hosting `terminal_id`, the
        calling `vessel_id`, a `voyage_ref` that must be unique within the
        terminal (duplicates are rejected with `ERR_VALIDATION`), the scheduled
        arrival `scheduled_eta` and scheduled departure `scheduled_etd`, and the
        booked manifests: `booked_embark_pax` and `booked_debark_pax`, each zero
        or more."

        Design: Corner/entities/port_call_computed_field_input_ignored
        """
        terminal = create_terminal()
        vessel = create_vessel(terminal["id"])
        payload = create_port_call_payload(terminal["id"], vessel["id"])
        payload["passengers_aboard"] = 99
        payload["bags_aboard"] = 99
        resp = api.create_port_call(payload, make_vessel_agent_headers(vessel["id"]))
        port_call = validate_success(resp, 201)
        assert port_call["passengers_aboard"] == 0
        assert port_call["bags_aboard"] == 0

    def test_vessel_create_ignores_client_supplied_id_and_version(self, api):
        """PRD §2.6: "`id` — a server-minted UUID, with no type prefix, assigned
        at creation."
        PRD §2.6: "`version` — an integer that increments with every
        modification of the resource; it is the basis for the
        optimistic-concurrency rules of §2.8."

        Design: Corner/entities/vessel_system_fields_input_ignored
        """
        terminal = create_terminal()
        payload = create_vessel_payload(terminal["id"])
        payload["id"] = "11111111-1111-1111-1111-111111111111"
        payload["version"] = 42
        vessel = validate_success(api.create_vessel(payload, ADMIN), 201)
        assert_vessel(vessel)
        assert vessel["id"] != "11111111-1111-1111-1111-111111111111", (
            "the server mints its own id at creation"
        )
        assert vessel["version"] == 1


class TestListingAndUniqueness:
    def test_berth_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items from the front of the result
        set and defaults to 0. Every list response orders its items by
        `created_at` in ascending order, and the `meta` object of every list
        response carries the four pagination fields `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/berth_list_pagination_envelope
        """
        terminal = create_terminal()
        for code, length, draft in (("B1", 1200, 40.0), ("B2", 1100, 38.0),
                                    ("B3", 1000, 36.0)):
            create_berth(terminal["id"], berth_code=code, length_ft=length,
                         max_draft_ft=draft)

        page1, meta1 = validate_paginated(
            api.list_berths(HARBORMASTER,
                            params={"terminal_id": terminal["id"], "limit": 2,
                                    "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_berths(HARBORMASTER,
                            params={"terminal_id": terminal["id"], "limit": 2,
                                    "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_berth_code_unique_per_terminal(self, api):
        """PRD §3.1: "Berths join the terminal through the same administrator,
        each carrying its owning `terminal_id`, a human-readable `berth_code`
        that must be unique within that terminal (a duplicate is rejected with
        `ERR_VALIDATION`), a usable face `length_ft` of at least 100 feet, and a
        `max_draft_ft` greater than zero."

        Design: Corner/entities/berth_code_duplicate_per_terminal_returns_400
        """
        t1 = create_terminal(name="T1")
        t2 = create_terminal(name="T2", max_apron_slots=2,
                             taxi_dispatch_capacity_per_window=1)
        create_berth(t1["id"], berth_code="B1")

        dup = api.create_berth(
            create_berth_payload(t1["id"], berth_code="B1", length_ft=1100,
                                 max_draft_ft=38.0), ADMIN)
        validate_error(dup, ApiErrorId.ERR_VALIDATION)

        other = validate_success(
            api.create_berth(
                create_berth_payload(t2["id"], berth_code="B1", length_ft=1100,
                                     max_draft_ft=38.0), ADMIN),
            201)
        assert_berth(other)

    def test_voyage_ref_unique_per_terminal(self, api):
        """PRD §3.2: "The creation payload names the hosting `terminal_id`, the
        calling `vessel_id`, a `voyage_ref` that must be unique within the
        terminal (duplicates are rejected with `ERR_VALIDATION`), the scheduled
        arrival `scheduled_eta` and scheduled departure `scheduled_etd`, and the
        booked manifests: `booked_embark_pax` and `booked_debark_pax`, each zero
        or more."

        Design: Corner/entities/voyage_ref_duplicate_per_terminal_returns_400
        """
        terminal = create_terminal()
        vessel = create_vessel(terminal["id"])
        agent = make_vessel_agent_headers(vessel["id"])
        first = api.create_port_call(
            create_port_call_payload(terminal["id"], vessel["id"]), agent)
        validate_success(first, 201)

        dup = api.create_port_call(
            create_port_call_payload(
                terminal["id"], vessel["id"],
                scheduled_eta="2026-08-12T08:00:00Z",
                scheduled_etd="2026-08-12T20:00:00Z"),
            agent)
        validate_error(dup, ApiErrorId.ERR_VALIDATION)


class TestImmediateConsistency:
    def test_created_berth_visible_and_counted_immediately(self, api):
        """PRD §2.10: "Child mutations that change a parent's derived state —
        berth occupancy, aboard counts, invoice totals — propagate upward
        immediately: consistency in this system is immediate, never deferred."
        PRD §3.1: "A berth is born `ACTIVE`."
        PRD §3.1: "Berth creation, removal from service, and return to service
        each recompute the terminal's berth counters and posture per §2.5, and
        the berth's own `status` (`ACTIVE` or `OUT_OF_SERVICE`) is the only
        state it carries."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        terminal = create_terminal()
        berth = create_berth(terminal["id"])

        fetched = validate_success(api.get_berth(berth["id"], HARBORMASTER))
        assert_berth(fetched)
        assert fetched["status"] == "ACTIVE"
        assert fetched["id"] == berth["id"]

        reloaded = validate_success(api.get_terminal(terminal["id"], HARBORMASTER))
        assert_terminal(reloaded)
        assert reloaded["active_berth_count"] == 1
        assert reloaded["free_berth_count"] == 1
        assert_terminal_counters(reloaded)
