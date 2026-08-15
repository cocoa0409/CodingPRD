"""Dock doors, sortation batches, trailer creation/ledger reads, and FK
reverse-reachability list endpoints."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_manifest_entry,
    assert_dock_door,
    assert_manifest_entry,
    assert_outbound_trailer,
    assert_trailer_ledger_invariants,
    create_sortation_batch_payload,
    create_trailer_payload,
    get_success_data,
    make_dimensioner_scan,
    make_door,
    make_on_dock_shipment,
    make_route,
    make_terminal_pair,
    make_trailer,
    validate_error,
    validate_paginated,
    validate_success,
)

DISP = TEST_USERS["dispatcher_headers"]
DOCK = TEST_USERS["dock_supervisor_headers"]
CLERK = TEST_USERS["rating_clerk_headers"]


class TestDoorAndBatchCreation:
    def test_initial_states_and_batch_door_kind_guard(self, api):
        """PRD §3.3: "The route is created `PLANNED`."
        PRD §3.5: "Doors are created `AVAILABLE` and cycle through a simple
        lifecycle"
        PRD §3.5: "The trailer is created in posture `LOADING` with
        `loaded_weight_lbs` 0, `loaded_cube_cuft` 0, and `utilization_pct` 0.0."
        PRD §3.5: "The door must be of `door_kind` `INBOUND` — pointing the batch
        at an outbound door is rejected with `ERR_DOOR_KIND_MISMATCH` (HTTP 422)
        — and the terminal must be `ACTIVE`."

        Design: Corner/state_machines/initial_states_on_creation
        """
        origin, dest = make_terminal_pair()
        door = make_door(origin["id"], 38, "OUTBOUND")
        assert_dock_door(door)
        assert door["status"] == "AVAILABLE"

        route = make_route(origin["id"])
        assert route["status"] == "PLANNED"

        trailer = make_trailer(origin["id"], dest["id"], door_id=door["id"])
        assert_outbound_trailer(trailer)
        assert trailer["posture"] == "LOADING"
        assert trailer["loaded_weight_lbs"] == 0
        assert trailer["loaded_cube_cuft"] == 0
        assert trailer["utilization_pct"] == 0.0

        resp = api.create_sortation_batch(
            create_sortation_batch_payload(origin["id"], door["id"], dest["id"]),
            headers=DOCK,
        )
        validate_error(resp, ApiErrorId.ERR_DOOR_KIND_MISMATCH)

    def test_trailer_spotting_at_inbound_door_rejected(self, api):
        """PRD §3.5: "Spotting a trailer requires `terminal_id`,
        `destination_terminal_id`, the `outbound_door_id` it is spotted at —
        which must be an `OUTBOUND` door, else `ERR_DOOR_KIND_MISMATCH` — and the
        two ceilings `max_weight_lbs` and `max_cube_cuft`."

        Design: Corner/errors/error_door_kind_mismatch_on_trailer_create
        """
        origin, dest = make_terminal_pair()
        door = make_door(origin["id"], 47, "INBOUND")
        resp = api.create_trailer(
            create_trailer_payload(origin["id"], dest["id"], door["id"]),
            headers=DOCK,
        )
        validate_error(resp, ApiErrorId.ERR_DOOR_KIND_MISMATCH)

    def test_door_release_blocked_by_active_trailer(self, api):
        """PRD §3.5: "releasing an `OCCUPIED` door returns it to `AVAILABLE` —
        but only when no sortation batch with that door as its `inbound_door_id`
        is `OPEN` or `CLOSED`, and no outbound trailer spotted at that door is in
        posture `LOADING`, `READY`, or `SEALED`."
        PRD §2.8: "5. Entity state preconditions for the requested transition
        (e.g. trailer must be `LOADING` to accept a manifest entry, a stop must
        be `ARRIVED` to complete, a leg must be `EN_ROUTE` to arrive) →
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/dock_door_release_blocked_while_trailer_active
        """
        origin, dest = make_terminal_pair()
        door = make_door(origin["id"], 36, "OUTBOUND")
        validate_success(api.reserve_door(door["id"], headers=DOCK))
        validate_success(api.occupy_door(door["id"], headers=DOCK))
        make_trailer(origin["id"], dest["id"], door_id=door["id"])
        resp = api.release_door(door["id"], headers=DOCK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        door_after = get_success_data(api.get_dock_door(door["id"], headers=DOCK))
        assert door_after["status"] == "OCCUPIED"


class TestTrailerLedgerReads:
    def test_trailer_get_exposes_loaded_ledger(self, api):
        """PRD §2.7: "The trailer's live load is tracked as `loaded_weight_lbs`
        and `loaded_cube_cuft`, each starting at 0 while the trailer is empty,
        and its `utilization_pct` reports the more constraining of the two fill
        ratios as a percentage"
        PRD §3.5: "On success the entry is created with `status` `ACTIVE`, the
        shipment's `handling_status` advances from `ON_DOCK` to `MANIFESTED`, and
        the trailer's ledger absorbs the freight: `loaded_weight_lbs` increases
        by the shipment's `chargeable_weight_lbs`, `loaded_cube_cuft` increases
        by the shipment's ceiling-cube, `utilization_pct` is recomputed per
        §2.7, and the trailer's `version` increments by 1 with `updated_at`
        refreshed."

        Design: Corner/endpoints/trailer_get_returns_computed_ledger
        """
        origin, dest = make_terminal_pair()
        trailer = make_trailer(origin["id"], dest["id"], door_number=43)
        ctx = make_on_dock_shipment(origin["id"], dest["id"],
                                    actual_weight_lbs=26000, length_in=96,
                                    width_in=96, height_in=96)
        entry = add_manifest_entry(trailer["id"], ctx["shipment"]["id"])
        assert_manifest_entry(entry)

        after = get_success_data(api.get_trailer(trailer["id"], headers=DOCK))
        assert after["loaded_weight_lbs"] == 26000
        assert after["loaded_cube_cuft"] == 512  # ceil(96*96*96 / 1728)
        assert after["utilization_pct"] == 65.0
        assert_trailer_ledger_invariants(after)

    def test_manifest_add_immediately_visible(self, api):
        """PRD §3.5: "On success the entry is created with `status` `ACTIVE`, the
        shipment's `handling_status` advances from `ON_DOCK` to `MANIFESTED`, and
        the trailer's ledger absorbs the freight"

        Design: Corner/consistency_model/immediate_consistency_on_manifest_add
        """
        origin, dest = make_terminal_pair()
        trailer = make_trailer(origin["id"], dest["id"], door_number=49)
        ctx = make_on_dock_shipment(origin["id"], dest["id"],
                                    actual_weight_lbs=500)
        entry = add_manifest_entry(trailer["id"], ctx["shipment"]["id"])
        assert entry["status"] == "ACTIVE", (
            "the create response itself carries the ACTIVE entry"
        )
        shipment = get_success_data(api.get_shipment(ctx["shipment"]["id"],
                                                     headers=DOCK))
        assert shipment["handling_status"] == "MANIFESTED", (
            "an immediately-following read must already show MANIFESTED"
        )

    def test_fk_reverse_reachability_lists(self, api):
        """PRD §4: the endpoint table lists "List stops of a route",
        "List manifest entries on a trailer", and "List scans of a shipment" as
        the child-collection reads for each parent resource.
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        origin, dest = make_terminal_pair()
        trailer = make_trailer(origin["id"], dest["id"], door_number=44)
        ctx = make_on_dock_shipment(origin["id"], dest["id"],
                                    actual_weight_lbs=500)
        entry = add_manifest_entry(trailer["id"], ctx["shipment"]["id"])
        scan = make_dimensioner_scan(ctx["shipment"]["id"],
                                     measured_length_in=48, measured_width_in=40,
                                     measured_height_in=48, measured_weight_lbs=500)

        stops, _ = validate_paginated(
            api.list_route_stops(ctx["route"]["id"], headers=DISP))
        assert [s["id"] for s in stops] == [ctx["stop"]["id"]]

        entries, _ = validate_paginated(
            api.list_trailer_manifest_entries(trailer["id"], headers=DOCK))
        assert [e["id"] for e in entries] == [entry["id"]]

        scans, _ = validate_paginated(
            api.list_shipment_dimensioner_scans(ctx["shipment"]["id"],
                                                headers=CLERK))
        assert [s["id"] for s in scans] == [scan["id"]]
