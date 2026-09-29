"""Entity-level guarantees: system-set defaults, computed fields the client
cannot dictate, read-back fidelity, list envelopes, and the shape of the three
append-only witnesses."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors, factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_deadline,
    assert_field,
    assert_ledger_entry,
    assert_money,
    assert_movement_state,
    assert_points,
    assert_witness_record_shape,
)
from test_helpers.fixtures import (
    M1_OBLIGATION,
    M1_SEAL,
    M1_TRANSIT_DAYS,
    build_departed_movement,
    build_empty_world,
    build_filed_movement,
    build_registered_world,
)

UNKNOWN_MOVEMENT_ID = "00000000-0000-0000-0000-000000009999"
UNKNOWN_BOND_ID = "00000000-0000-0000-0000-000000008888"
UNKNOWN_PORT_ID = "00000000-0000-0000-0000-000000007777"


class TestCreationDefaults:
    """A creation answers with the server's own opening values, not the
    client's."""

    def test_a_new_carrier_opens_with_its_compliance_posture_zeroed(self, client):
        """Registering a carrier with nothing but a name and an IRS number yields an
        ACTIVE carrier at 0.0 points with all three live counters at zero.

        PRD: "A newly registered carrier opens with `custodial_status` of `ACTIVE`, `sanction_points` of 0.0, `overdue_movement_count` of 0, `open_claim_count` of 0, and `suspension_reason` null."
        PRD: "Most resources additionally carry `updated_at`, refreshed on every mutation of the record, and `version`, an integer that starts at 1 on creation and increments by one on each mutation."

        Design: Corner/entities/carrier_created_with_system_defaults
        """
        world = build_empty_world(client)

        carrier = validate_success(
            client.create_carrier(factories.carrier_payload(), world.officer), 201
        )

        assert is_valid_uuid(carrier["id"]), (
            f"the minted carrier id should be a bare UUID but it is {carrier['id']!r}"
        )
        assert_field(carrier, "name", factories.CARRIER_NAME, "carrier")
        assert_field(carrier, "irs_number", factories.CARRIER_IRS_NUMBER, "carrier")
        assert_field(carrier, "custodial_status", "ACTIVE", "carrier")
        assert_points(carrier["sanction_points"], 0.0)
        assert_field(carrier, "overdue_movement_count", 0, "carrier")
        assert_field(carrier, "open_claim_count", 0, "carrier")
        assert_field(carrier, "suspension_reason", None, "carrier")
        assert_field(carrier, "version", 1, "carrier")
        assert is_iso8601_timestamp(carrier["created_at"]), (
            f"created_at should be an ISO 8601 UTC instant but it is "
            f"{carrier['created_at']!r}"
        )

    def test_a_port_without_the_warehouse_flag_defaults_to_having_one(self, client):
        """Omitting go_warehouse_available stores true, because the general-order
        sweep reads that flag to decide whether cargo can go to warehouse.

        PRD: "The optional `go_warehouse_available` flag states whether a general-order warehouse serves the port and defaults to true."
        PRD: "A port's `open_hold_count` starts at 0 and is thereafter the live count of examination holds at that port whose `status` is `OPEN`, counting every hold type including those that occupy no scheduled window."

        Design: Corner/entities/port_go_warehouse_available_defaults_to_true
        """
        world = build_empty_world(client)

        port = validate_success(
            client.create_port(
                factories.port_chicago_payload(go_warehouse_available=None),
                world.officer,
            ),
            201,
        )

        assert_field(port, "go_warehouse_available", True, "port")
        assert_field(port, "exam_capacity_slots", 2, "port")
        assert_field(port, "open_hold_count", 0, "port")
        assert_field(port, "version", 1, "port")


class TestComputedFieldsAndReadBack:
    """Derived values are computed once at filing and echoed unchanged
    afterwards."""

    def test_a_movement_read_later_still_reports_its_filing_time_derivation(
        self, client
    ):
        """Nineteen days after the filing the read still answers 41.75, 35 days and
        the 2026-09-05 deadline anchored at the filing instant.

        PRD: "The value stored at filing is never recomputed for the life of the movement."
        PRD: "At filing it is set to `filed_at`, the logical-clock instant the electronic filing was accepted, and it stays at `filed_at` for the whole life of the movement unless an approved diversion rebases it."

        Design: Corner/entities/movement_read_back_matches_stored_fields
        """
        world = build_filed_movement(client)
        movement_id = world.movements["MAN-0001"]
        world.set_clock("2026-08-20T00:00:00Z")

        movement = validate_success(
            client.get_movement(movement_id, world.officer), 200
        )

        assert_field(movement, "manifest_reference", "MAN-0001", "movement")
        assert_money(movement["obligation_amount"], M1_OBLIGATION, "obligation_amount")
        assert_field(movement, "filed_at", "2026-08-01T00:00:00Z", "movement")
        assert_deadline(
            movement,
            anchor="2026-08-01T00:00:00Z",
            deadline="2026-09-05T00:00:00Z",
            transit_days_allowed=M1_TRANSIT_DAYS,
        )
        assert_field(movement, "overdue_days", 0, "movement")
        assert_field(movement, "arrival_port_id", None, "movement")
        assert_field(movement, "seal_number", None, "movement")

    def test_client_supplied_derived_values_are_ignored(self, client):
        """A filing that also sends an obligation of 9,999.99, a December deadline
        and a CLOSED status is stored with the server's own 41.75, 2026-09-05 and
        FILED.

        PRD: "Unknown body fields are ignored rather than rejected."
        PRD: "An accepted filing lands the movement at `transit_status` `FILED` and `custody_status` `BONDED`, with `seal_intact` false because no seal has yet been applied, `seal_number` null, `arrival_port_id` null, `arrival_reported_at` null, `export_reported_at` null, `go_deadline_utc` null, `go_grace_applied` false, `diversion_flag` false, `extension_days_granted` 0, `overdue_days` 0, and `cancellation_reason` null."

        Design: Corner/entities/obligation_and_deadline_are_computed_server_side_input_ignored
        """
        world = build_registered_world(client)

        movement = validate_success(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0001",
                    bond_id=world.bond_id,
                    obligation_amount=9999.99,
                    transit_deadline_utc="2026-12-31T00:00:00Z",
                    transit_status="CLOSED",
                ),
                world.carrier,
            ),
            201,
        )

        assert_money(movement["obligation_amount"], M1_OBLIGATION, "obligation_amount")
        assert_deadline(movement, deadline="2026-09-05T00:00:00Z")
        assert_movement_state(
            movement, transit_status="FILED", custody_status="BONDED"
        )
        assert_field(movement, "version", 1, "movement")
        assert_bond_amounts(world.read_bond(), obligated=M1_OBLIGATION)


class TestMovementListing:
    """The movement list reports the pre-pagination count and honours the state
    filter."""

    def _four_movements_one_departed(self, client):
        world = build_registered_world(client)
        for reference in ("MAN-0001", "MAN-0002", "MAN-0003", "MAN-0004"):
            world.file_movement(reference)
        world.depart(world.movements["MAN-0001"], M1_SEAL)
        return world

    def test_a_two_row_window_still_reports_the_full_match_count(self, client):
        """With four movements on file, limit 2 and offset 0 return two rows while
        total_count stays 4 and has_more is true.

        PRD: "`total_count` reflects the number of records matching the filters before pagination is applied, and `has_more` is true exactly when records beyond the current window remain."

        Design: Corner/entities/movement_list_paginates_and_filters_by_transit_status
        """
        world = self._four_movements_one_departed(client)

        rows, meta = validate_paginated(
            client.list_movements(
                world.officer,
                params={"carrier_id": world.carrier_id, "limit": 2, "offset": 0},
            )
        )

        assert len(rows) == 2, f"a limit of 2 should return 2 rows, not {len(rows)}"
        assert meta["total_count"] == 4, (
            f"total_count should count all four matching movements, not "
            f"{meta['total_count']}"
        )
        assert meta["limit"] == 2, "the echoed limit should be the requested 2"
        assert meta["offset"] == 0, "the echoed offset should be the requested 0"
        assert meta["has_more"] is True, (
            "two of four rows were returned, so has_more must be true"
        )

        assert_bond_amounts(
            world.read_bond(), obligated=167.00, open_movement_count=4
        )

    def test_filtering_by_transit_status_returns_only_the_departed_movement(
        self, client
    ):
        """Three movements are still FILED and one has departed, so the IN_TRANSIT
        filter answers with exactly that one and no more pages.

        PRD: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/movement_list_paginates_and_filters_by_transit_status
        """
        world = self._four_movements_one_departed(client)

        rows, meta = validate_paginated(
            client.list_movements(
                world.officer,
                params={
                    "carrier_id": world.carrier_id,
                    "transit_status": "IN_TRANSIT",
                },
            )
        )

        assert len(rows) == 1, (
            f"exactly one movement has departed, so the filter should return 1 row, "
            f"not {len(rows)}"
        )
        assert rows[0]["id"] == world.movements["MAN-0001"], (
            "the filtered row should be the movement that departed"
        )
        assert_movement_state(rows[0], transit_status="IN_TRANSIT")
        assert meta["total_count"] == 1, (
            f"total_count should be 1 under the filter, not {meta['total_count']}"
        )
        assert meta["has_more"] is False, (
            "the single matching row fits the window, so has_more must be false"
        )


class TestImmutableWitnesses:
    """Ledger entries and seal events are history: they carry no version and no
    way to be rewritten."""

    def test_the_filing_ledger_entry_is_an_append_only_record(self, client):
        """The one OBLIGATE entry the filing wrote exposes id and created_at and
        neither version nor updated_at.

        PRD: "Three record types are append-only witnesses rather than living entities, and they carry **only** `id` and `created_at`: `BondObligationLedgerEntry`, `SealEvent`, and `ComplianceSweep`."

        Design: Corner/entities/ledger_entries_and_seal_events_are_immutable_records
        """
        world = build_departed_movement(client)

        entries = world.ledger_entries(bond_id=world.bond_id)
        assert len(entries) == 1, (
            f"the filing should have written exactly one entry, not {len(entries)}"
        )
        assert_ledger_entry(
            entries[0],
            entry_type="OBLIGATE",
            amount=M1_OBLIGATION,
            balance_after=M1_OBLIGATION,
            reason_code="MOVEMENT_FILED",
        )
        assert_witness_record_shape(entries[0], "a bond obligation ledger entry")

    def test_the_departure_seal_event_is_an_append_only_record(self, client):
        """Departure writes one APPLIED event naming the seal and the origin port,
        and it too carries no version field.

        PRD: "For those three, both `updated_at` and `version` are absent from the representation entirely."

        Design: Corner/entities/ledger_entries_and_seal_events_are_immutable_records
        """
        world = build_departed_movement(client)

        events = world.seal_events(world.movements["MAN-0001"])
        assert len(events) == 1, (
            f"departure should have written exactly one seal event, not {len(events)}"
        )
        assert_field(events[0], "event_type", "APPLIED", "seal event")
        assert_field(events[0], "seal_number", M1_SEAL, "seal event")
        assert_field(events[0], "port_code", factories.PORT_NY_CODE, "seal event")
        assert_field(events[0], "resulting_seal_intact", True, "seal event")
        assert_witness_record_shape(events[0], "a seal event")


class TestUnresolvedIdentifiers:
    """A well-formed identifier that names nothing is a 404 on every path."""

    def test_reading_an_unknown_movement_is_not_found(self, client):
        """A valid but unused UUID on the movement read path answers
        ERR_MOVEMENT_NOT_FOUND.

        PRD: "**Existence.** Each referenced record exists, with a distinct error per record type: `ERR_CARRIER_NOT_FOUND`, `ERR_BOND_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, and `ERR_RESOURCE_NOT_FOUND` for a ledger entry read."

        Design: Corner/entities/unknown_movement_id_not_found
        """
        world = build_empty_world(client)

        validate_error(
            client.get_movement(UNKNOWN_MOVEMENT_ID, world.officer),
            api_errors.ERR_MOVEMENT_NOT_FOUND,
        )

    def test_releasing_cargo_from_an_unknown_movement_is_not_found(self, client):
        """The same unused UUID on a write path answers with the same not-found
        refusal rather than a shape or server error.

        PRD: "Release requires that the movement's `transit_status` be `ARRIVED` or `EXPORTED`, that no examination hold on the movement remain `OPEN` — otherwise `ERR_HOLD_OPEN` — that `seal_intact` be true, and that `custody_status` not already be `GENERAL_ORDER`."
        PRD: "**Existence.** Each referenced record exists, with a distinct error per record type: `ERR_CARRIER_NOT_FOUND`, `ERR_BOND_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, and `ERR_RESOURCE_NOT_FOUND` for a ledger entry read."

        Design: Corner/entities/unknown_movement_id_not_found
        """
        world = build_empty_world(client)

        validate_error(
            client.release_cargo(
                UNKNOWN_MOVEMENT_ID,
                factories.cargo_release_payload("ENTRY_FILED"),
                world.officer,
            ),
            api_errors.ERR_MOVEMENT_NOT_FOUND,
        )

    def test_a_hold_against_an_unknown_movement_leaves_the_port_untouched(self, client):
        """The hold is refused as not found and the port's open hold count stays at
        zero.

        PRD: "A `CBPOfficer` interrupts a movement by placing an examination hold, naming the `movement_id`, the `port_id` whose examination resources the hold consumes, the `hold_type`, and a short `reason_code` explaining why."

        Design: Corner/entities/examination_hold_on_unknown_movement_not_found
        """
        world = build_empty_world(client)
        world.register_port("chicago", factories.port_chicago_payload())

        validate_error(
            client.place_hold(
                factories.unscheduled_hold_payload(
                    UNKNOWN_MOVEMENT_ID, world.ports["chicago"]
                ),
                world.officer,
            ),
            api_errors.ERR_MOVEMENT_NOT_FOUND,
        )

        assert_field(world.read_port("chicago"), "open_hold_count", 0, "port")

    def test_a_filing_naming_an_unknown_bond_is_not_found(self, client):
        """The bond foreign key is resolved before any business rule, so an unknown
        bond_id is a not-found refusal and nothing is filed.

        PRD: "**Existence.** Each referenced record exists, with a distinct error per record type: `ERR_CARRIER_NOT_FOUND`, `ERR_BOND_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, and `ERR_RESOURCE_NOT_FOUND` for a ledger entry read."

        Design: Corner/entities/filing_with_unknown_bond_and_port_ids_not_found
        """
        world = build_registered_world(client)

        validate_error(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0096",
                    bond_id=UNKNOWN_BOND_ID,
                ),
                world.carrier,
            ),
            api_errors.ERR_BOND_NOT_FOUND,
        )

        assert_bond_amounts(world.read_bond(), obligated=0.00)
        _rows, meta = world.movement_list(carrier_id=world.carrier_id)
        assert meta["total_count"] == 0, "a refused filing must not be stored"

    def test_a_filing_naming_an_unknown_destination_port_is_not_found(self, client):
        """An unknown destination port is likewise a not-found refusal rather than a
        routing complaint.

        PRD: "The filing declares the `carrier_id` (which must equal the filer's own `X-User-ID`), the `in_bond_type`, the `origin_port_id` where the movement begins, the `destination_port_id` it routes to, the `manifest_reference` from the carrier's manifest or bill, the declared `cargo_value` in dollars, the `gross_weight_kg`, and the `package_count`."

        Design: Corner/entities/filing_with_unknown_bond_and_port_ids_not_found
        """
        world = build_registered_world(client)

        validate_error(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    UNKNOWN_PORT_ID,
                    "MAN-0095",
                    bond_id=world.bond_id,
                ),
                world.carrier,
            ),
            api_errors.ERR_PORT_NOT_FOUND,
        )

        assert_bond_amounts(world.read_bond(), obligated=0.00)


class TestRequestShape:
    """Shape validation happens before any lookup or arithmetic."""

    def test_a_filing_without_a_cargo_value_is_refused(self, client):
        """cargo_value has no default, so omitting it fails shape validation and the
        bond is never touched.

        PRD: "**Request shape.** All required body fields present with the declared type, enum values in range, money non-negative with at most two fractional digits, integers non-negative, datetimes valid ISO 8601 UTC — otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/filing_without_cargo_value_returns_invalid_request
        """
        world = build_registered_world(client)

        validate_error(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0099",
                    cargo_value=None,
                    bond_id=world.bond_id,
                ),
                world.carrier,
            ),
            api_errors.ERR_INVALID_REQUEST,
        )

        assert_bond_amounts(world.read_bond(), obligated=0.00)
        _rows, meta = world.movement_list(carrier_id=world.carrier_id)
        assert meta["total_count"] == 0, "a refused filing must not be stored"

    def test_an_in_bond_type_outside_the_enum_is_refused(self, client):
        """An in_bond_type of IX is not one of the three statutory forms, so the
        filing fails on shape rather than on route geometry.

        PRD: "The `in_bond_type` selects among the three statutory forms."

        Design: Corner/entities/invalid_in_bond_type_enum_returns_invalid_request
        """
        world = build_registered_world(client)

        validate_error(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0098",
                    in_bond_type="IX",
                    bond_id=world.bond_id,
                ),
                world.carrier,
            ),
            api_errors.ERR_INVALID_REQUEST,
        )

        assert_bond_amounts(world.read_bond(), obligated=0.00)

    def test_a_cargo_value_of_zero_is_refused(self, client):
        """Zero is not a positive declared value, so the filing fails shape
        validation just as a missing field would.

        PRD: "`cargo_value` and `gross_weight_kg` must both be strictly greater than zero and `package_count` at least 1, or the filing fails shape validation."

        Design: Corner/entities/invalid_in_bond_type_enum_returns_invalid_request
        """
        world = build_registered_world(client)

        validate_error(
            client.file_movement(
                factories.movement_payload(
                    world.carrier_id,
                    world.ports["ny"],
                    world.ports["chicago"],
                    "MAN-0097",
                    cargo_value=0,
                    bond_id=world.bond_id,
                ),
                world.carrier,
            ),
            api_errors.ERR_INVALID_REQUEST,
        )

        assert_bond_amounts(world.read_bond(), obligated=0.00)
