"""The manifest ledger: capacity ceilings, the readiness gate, destination and
OS&D gates, OCC on the trailer version, and the add/remove compensation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_manifest_entry,
    assert_trailer_ledger_invariants,
    create_manifest_entry_payload,
    get_success_data,
    make_on_dock_shipment,
    make_osd_case,
    make_route,
    make_terminal,
    make_terminal_pair,
    make_trailer,
    get_trailer,
    validate_error,
    validate_paginated,
    validate_success,
)

DISP = TEST_USERS["dispatcher_headers"]
DOCK = TEST_USERS["dock_supervisor_headers"]
OSD = TEST_USERS["osd_clerk_headers"]


def _three_on_dock_shipments(origin_id, dest_id, weights):
    """Rated, on-dock shipments sharing one dispatched route."""
    route = make_route(origin_id)
    ctxs = []
    for i, w in enumerate(weights):
        ctxs.append(make_on_dock_shipment(
            origin_id, dest_id, route=route, stop_sequence=i + 1,
            planned_arrival_minute=540 + i * 10, actual_weight_lbs=w))
    return route, ctxs


class TestCapacityBoundary:
    def test_manifest_exactly_at_weight_cap_allowed(self, api):
        """PRD §3.5: "The projected load must fit: the trailer's current
        `loaded_weight_lbs` plus the shipment's `chargeable_weight_lbs` must not
        exceed `max_weight_lbs`, and the current `loaded_cube_cuft` plus the
        shipment's cube must not exceed `max_cube_cuft`. A projection that is
        strictly greater on either axis is rejected with
        `ERR_TRAILER_OVER_CAPACITY` (HTTP 422); a projection landing exactly at
        either cap is allowed."

        Design: Difficulty/boundary_precision_check/trailer_capacity_exactly_at_cap_allowed
        """
        origin, dest = make_terminal_pair()
        trailer = make_trailer(origin["id"], dest["id"], door_number=28,
                               max_weight_lbs=1000, max_cube_cuft=500)
        _, ctxs = _three_on_dock_shipments(origin["id"], dest["id"],
                                           [600, 400, 401])
        add_manifest_entry(trailer["id"], ctxs[0]["shipment"]["id"],
                           load_position=1)
        entry_b = add_manifest_entry(trailer["id"], ctxs[1]["shipment"]["id"],
                                     load_position=2)
        assert entry_b["status"] == "ACTIVE", (
            "600 + 400 = 1000 lands exactly at the 1000-lb cap and is allowed"
        )
        after = get_trailer(trailer["id"])
        assert after["loaded_weight_lbs"] == 1000
        assert after["utilization_pct"] == 100.0

    def test_manifest_one_pound_over_cap_rejected(self, api):
        """PRD §3.5: "A projection that is strictly greater on either axis is
        rejected with `ERR_TRAILER_OVER_CAPACITY` (HTTP 422); a projection
        landing exactly at either cap is allowed."

        Design: Difficulty/boundary_precision_check/trailer_capacity_exactly_at_cap_allowed
        """
        origin, dest = make_terminal_pair()
        trailer = make_trailer(origin["id"], dest["id"], door_number=28,
                               max_weight_lbs=1000, max_cube_cuft=500)
        _, ctxs = _three_on_dock_shipments(origin["id"], dest["id"],
                                           [600, 400, 401])
        add_manifest_entry(trailer["id"], ctxs[0]["shipment"]["id"],
                           load_position=1)
        add_manifest_entry(trailer["id"], ctxs[1]["shipment"]["id"],
                           load_position=2)
        version = get_trailer(trailer["id"])["version"]
        resp = api.create_manifest_entry(
            trailer["id"],
            create_manifest_entry_payload(ctxs[2]["shipment"]["id"], version,
                                          load_position=3),
            headers=DOCK,
        )
        # 1000 + 401 = 1401 > 1000: strictly-greater rejects.
        validate_error(resp, ApiErrorId.ERR_TRAILER_OVER_CAPACITY)
        after = get_trailer(trailer["id"])
        assert after["loaded_weight_lbs"] == 1000, (
            "a rejected write must not partially mutate the ledger"
        )


class TestUtilizationGate:
    def _trailer_with_two_on_dock(self, origin, dest):
        trailer = make_trailer(origin["id"], dest["id"], door_number=23,
                               max_weight_lbs=10000, max_cube_cuft=2000)
        route = make_route(origin["id"])
        ctx_a = make_on_dock_shipment(
            origin["id"], dest["id"], route=route, stop_sequence=1,
            planned_arrival_minute=540, actual_weight_lbs=4000,
            length_in=96, width_in=96, height_in=96)
        ctx_b = make_on_dock_shipment(
            origin["id"], dest["id"], route=route, stop_sequence=2,
            planned_arrival_minute=560, actual_weight_lbs=2500,
            length_in=60, width_in=48, height_in=48)
        return trailer, ctx_a, ctx_b

    def test_mark_ready_rejected_below_utilization_floor(self, api):
        """PRD §3.5: "Marking a trailer ready requires at least one `ACTIVE`
        manifest entry aboard and `utilization_pct` of at least 60.0 — a trailer
        running 59.9 percent utilized, however close, is rejected with
        `ERR_TRAILER_NOT_LOADABLE` (HTTP 422), as is an empty trailer."
        PRD §2.7: "The minimum utilization a trailer must reach before it may be
        marked ready for dispatch is 60.0 percent."

        Design: Difficulty/combinatorial_formula/trailer_utilization_circular_gating
        """
        origin, dest = make_terminal_pair()
        trailer, ctx_a, _ = self._trailer_with_two_on_dock(origin, dest)
        add_manifest_entry(trailer["id"], ctx_a["shipment"]["id"],
                           load_position=1)
        # 4000/10000 = 40.0% weight-binding vs 512/2000 = 25.6% cube -> 40.0.
        after_add = get_trailer(trailer["id"])
        assert after_add["utilization_pct"] == 40.0
        resp = api.mark_trailer_ready(trailer["id"], headers=DOCK)
        validate_error(resp, ApiErrorId.ERR_TRAILER_NOT_LOADABLE)

    def test_utilization_recomputed_then_mark_ready_succeeds(self, api):
        """PRD §2.7: "the larger of loaded weight divided by maximum weight and
        loaded cube divided by maximum cube, multiplied by 100, rounded half-up
        to one decimal place. A trailer 95% full by cube but only 40% full by
        weight therefore reports 95.0 — the binding constraint drives the
        number"
        PRD §3.5: "Success moves posture from `LOADING` to `READY`."

        Design: Difficulty/combinatorial_formula/trailer_utilization_circular_gating
        """
        origin, dest = make_terminal_pair()
        trailer, ctx_a, ctx_b = self._trailer_with_two_on_dock(origin, dest)
        add_manifest_entry(trailer["id"], ctx_a["shipment"]["id"],
                           load_position=1)
        add_manifest_entry(trailer["id"], ctx_b["shipment"]["id"],
                           load_position=2)
        after = get_trailer(trailer["id"])
        assert after["loaded_weight_lbs"] == 6500
        assert after["loaded_cube_cuft"] == 592  # 512 + 80
        # weight-binding: max(6500/10000, 592/2000) * 100 = 65.0
        assert after["utilization_pct"] == 65.0
        assert_trailer_ledger_invariants(after)
        ready = validate_success(api.mark_trailer_ready(trailer["id"],
                                                        headers=DOCK))
        assert ready["posture"] == "READY"


class TestReadinessFloor:
    def test_mark_ready_empty_trailer_rejected(self, api):
        """PRD §3.5: "Marking a trailer ready requires at least one `ACTIVE`
        manifest entry aboard and `utilization_pct` of at least 60.0 — a trailer
        running 59.9 percent utilized, however close, is rejected with
        `ERR_TRAILER_NOT_LOADABLE` (HTTP 422), as is an empty trailer."

        Design: Difficulty/boundary_precision_check/mark_ready_empty_manifest_and_utilization_floor
        """
        origin, dest = make_terminal_pair()
        trailer = make_trailer(origin["id"], dest["id"], door_number=29)
        resp = api.mark_trailer_ready(trailer["id"], headers=DOCK)
        validate_error(resp, ApiErrorId.ERR_TRAILER_NOT_LOADABLE)

    def test_mark_ready_at_exactly_sixty_percent(self, api):
        """PRD §3.5: "Marking a trailer ready requires at least one `ACTIVE`
        manifest entry aboard and `utilization_pct` of at least 60.0"
        PRD §2.7: "The minimum utilization a trailer must reach before it may be
        marked ready for dispatch is 60.0 percent."

        Design: Difficulty/boundary_precision_check/mark_ready_empty_manifest_and_utilization_floor
        """
        origin, dest = make_terminal_pair()
        trailer = make_trailer(origin["id"], dest["id"], door_number=30)
        ctx = make_on_dock_shipment(origin["id"], dest["id"],
                                    actual_weight_lbs=24000, length_in=96,
                                    width_in=96, height_in=96)
        add_manifest_entry(trailer["id"], ctx["shipment"]["id"])
        after = get_trailer(trailer["id"])
        assert after["utilization_pct"] == 60.0, (
            "24000/40000 = 60.0 sits exactly on the floor"
        )
        ready = validate_success(api.mark_trailer_ready(trailer["id"],
                                                        headers=DOCK))
        assert ready["posture"] == "READY", "the 60.0 floor is inclusive"


class TestDestinationAndOsdGates:
    def _denver_bound_on_dock_shipment(self, origin, dest_den):
        return make_on_dock_shipment(origin["id"], dest_den["id"],
                                     actual_weight_lbs=500)

    def test_manifest_destination_mismatch_rejected(self, api):
        """PRD §3.5: "The trailer's `destination_terminal_id` must equal the
        shipment's `destination_terminal_id` — loading freight onto a trailer
        bound elsewhere is `ERR_DESTINATION_MISMATCH` (HTTP 422)."

        Design: Corner/errors/error_destination_mismatch
        """
        origin, dest = make_terminal_pair()
        den = make_terminal(code="DEN", name="Denver", dock_doors=8)
        trailer = make_trailer(origin["id"], dest["id"], door_number=45)
        ctx = self._denver_bound_on_dock_shipment(origin, den)
        version = get_trailer(trailer["id"])["version"]
        resp = api.create_manifest_entry(
            trailer["id"],
            create_manifest_entry_payload(ctx["shipment"]["id"], version),
            headers=DOCK,
        )
        validate_error(resp, ApiErrorId.ERR_DESTINATION_MISMATCH)

    def test_osd_hold_beats_destination_mismatch(self, api):
        """PRD §2.8: "When a request violates more than one rule, the server
        evaluates checks in a fixed priority order and returns the error from the
        earliest matching check — a caller never sees a low-priority business
        error masking an authentication failure or a not-found path."
        PRD §2.8: "7. OS&D safety hold — the freight must not be under an active
        claim hold before loading → `ERR_SHIPMENT_ON_OSD_HOLD`. 8. Destination
        alignment between trailer and shipment → `ERR_DESTINATION_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/osd_hold_safety_beats_destination_constraint
        """
        origin, dest = make_terminal_pair()
        den = make_terminal(code="DEN", name="Denver", dock_doors=8)
        trailer = make_trailer(origin["id"], dest["id"], door_number=26)
        ctx = self._denver_bound_on_dock_shipment(origin, den)
        make_osd_case(ctx["shipment"]["id"], case_kind="SHORTAGE",
                      claimed_amount_cents=5000, item_amounts_cents=[5000])
        version = get_trailer(trailer["id"])["version"]
        resp = api.create_manifest_entry(
            trailer["id"],
            create_manifest_entry_payload(ctx["shipment"]["id"], version),
            headers=DOCK,
        )
        # Both p7 (hold) and p8 (destination mismatch) fail; p7 wins.
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_ON_OSD_HOLD)
        shipment = get_success_data(api.get_shipment(ctx["shipment"]["id"],
                                                     headers=DISP))
        assert shipment["handling_status"] == "ON_DOCK"
        assert get_trailer(trailer["id"])["version"] == version, (
            "a rejected write must not advance the trailer version"
        )

    def test_osd_hold_alone_blocks_manifest(self, api):
        """PRD §3.5: "The shipment must not be under an OS&D hold — `osd_hold`
        must be `false`, meaning no linked case is `OPEN` (see §3.8) — else
        `ERR_SHIPMENT_ON_OSD_HOLD` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/osd_hold_safety_beats_destination_constraint
        """
        origin, dest = make_terminal_pair()
        trailer = make_trailer(origin["id"], dest["id"], door_number=26)
        ctx = make_on_dock_shipment(origin["id"], dest["id"],
                                    actual_weight_lbs=500)
        make_osd_case(ctx["shipment"]["id"], case_kind="SHORTAGE",
                      claimed_amount_cents=5000, item_amounts_cents=[5000])
        version = get_trailer(trailer["id"])["version"]
        resp = api.create_manifest_entry(
            trailer["id"],
            create_manifest_entry_payload(ctx["shipment"]["id"], version),
            headers=DOCK,
        )
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_ON_OSD_HOLD)


class TestOccPrecedence:
    def _trailer_with_one_manifested(self, origin, dest, weights=(600, 2000),
                                     max_weight=1000, max_cube=500,
                                     door_number=27):
        trailer = make_trailer(origin["id"], dest["id"], door_number=door_number,
                               max_weight_lbs=max_weight, max_cube_cuft=max_cube)
        _, ctxs = _three_on_dock_shipments(origin["id"], dest["id"],
                                           list(weights))
        v0 = get_trailer(trailer["id"])["version"]
        add_manifest_entry(trailer["id"], ctxs[0]["shipment"]["id"],
                           load_position=1)
        return trailer, ctxs, v0

    def test_stale_version_beats_capacity_check(self, api):
        """PRD §2.8: "Two consequences of this ordering are worth internalizing.
        First, a stale trailer version (priority 6) surfaces before the
        destination-mismatch check (priority 8) and the capacity check (priority
        14): a client holding an obsolete `version` always hears about the
        staleness first, and re-reading the trailer is the correct response
        before re-attempting."

        Design: Difficulty/priority_pair_validation_conflict/occ_stale_version_beats_capacity_fiscal
        """
        origin, dest = make_terminal_pair()
        trailer, ctxs, v0 = self._trailer_with_one_manifested(origin, dest)
        # Second shipment (2000 lbs) would blow the 1000-lb cap AND the client
        # holds the stale pre-add version: the OCC error must surface first.
        resp = api.create_manifest_entry(
            trailer["id"],
            create_manifest_entry_payload(ctxs[1]["shipment"]["id"], v0,
                                          load_position=2),
            headers=DOCK,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_TRAILER_VERSION)
        assert get_trailer(trailer["id"])["loaded_weight_lbs"] == 600

    def test_over_capacity_with_fresh_version_rejected(self, api):
        """PRD §3.5: "A projection that is strictly greater on either axis is
        rejected with `ERR_TRAILER_OVER_CAPACITY` (HTTP 422); a projection
        landing exactly at either cap is allowed."

        Design: Difficulty/priority_pair_validation_conflict/occ_stale_version_beats_capacity_fiscal
        """
        origin, dest = make_terminal_pair()
        trailer, ctxs, _ = self._trailer_with_one_manifested(origin, dest)
        version = get_trailer(trailer["id"])["version"]
        resp = api.create_manifest_entry(
            trailer["id"],
            create_manifest_entry_payload(ctxs[1]["shipment"]["id"], version,
                                          load_position=2),
            headers=DOCK,
        )
        # Version is fresh, so the capacity ceiling is the failing check.
        validate_error(resp, ApiErrorId.ERR_TRAILER_OVER_CAPACITY)
        assert get_trailer(trailer["id"])["loaded_weight_lbs"] == 600


class TestManifestEntryIntegrity:
    def test_double_manifest_second_trailer_rejected(self, api):
        """PRD §3.5: "A shipment may hold at most one `ACTIVE` manifest entry
        across the network; attempting to manifest a shipment that already has
        an `ACTIVE` entry is a state violation."
        PRD §3.5: "The shipment's `handling_status` must be `ON_DOCK` and its
        `rating_status` must be `RATED` or `RERATED` — freight that is unrated,
        mid-inspection, billed, or already moving cannot be loaded (state
        failures again surface as `ERR_INVALID_STATE`)."

        Design: Corner/validations/error_double_manifest_second_trailer_returns_invalid_state
        """
        origin, dest = make_terminal_pair()
        trailer_a = make_trailer(origin["id"], dest["id"], door_number=41)
        trailer_b = make_trailer(origin["id"], dest["id"], door_number=42)
        ctx = make_on_dock_shipment(origin["id"], dest["id"],
                                    actual_weight_lbs=500)
        add_manifest_entry(trailer_a["id"], ctx["shipment"]["id"])
        version_b = get_trailer(trailer_b["id"])["version"]
        resp = api.create_manifest_entry(
            trailer_b["id"],
            create_manifest_entry_payload(ctx["shipment"]["id"], version_b),
            headers=DOCK,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        shipment = get_success_data(api.get_shipment(ctx["shipment"]["id"],
                                                     headers=DOCK))
        assert shipment["handling_status"] == "MANIFESTED"
        entries, _ = validate_paginated(
            api.list_trailer_manifest_entries(trailer_a["id"], headers=DOCK))
        assert len(entries) == 1 and entries[0]["status"] == "ACTIVE"


class TestAddRemoveCompensation:
    def _setup(self, api):
        origin, dest = make_terminal_pair()
        trailer = make_trailer(origin["id"], dest["id"], door_number=34)
        route = make_route(origin["id"])
        ctx_a = make_on_dock_shipment(
            origin["id"], dest["id"], route=route, stop_sequence=1,
            planned_arrival_minute=540, actual_weight_lbs=26000,
            length_in=96, width_in=96, height_in=96)
        ctx_b = make_on_dock_shipment(
            origin["id"], dest["id"], route=route, stop_sequence=2,
            planned_arrival_minute=560, actual_weight_lbs=1000,
            length_in=48, width_in=40, height_in=48)
        v0 = get_trailer(trailer["id"])["version"]
        add_manifest_entry(trailer["id"], ctx_a["shipment"]["id"],
                           load_position=1)
        return trailer, ctx_a, ctx_b, v0

    def test_manifest_add_remove_leaves_ledger_unchanged(self, api):
        """PRD §3.5: "Removal sets the entry's `status` to `REMOVED`, returns the
        shipment from `MANIFESTED` to `ON_DOCK`, subtracts the shipment's weight
        and cube from the trailer's loaded totals, recomputes utilization, and
        increments the trailer's `version`."

        Design: Difficulty/compensating_invariant/manifest_add_remove_preserves_loaded_ledger
        """
        trailer, _, ctx_b, _ = self._setup(api)
        entry_b = add_manifest_entry(trailer["id"], ctx_b["shipment"]["id"],
                                     load_position=2)
        loaded = get_trailer(trailer["id"])
        assert loaded["loaded_weight_lbs"] == 27000
        assert loaded["loaded_cube_cuft"] == 566  # 512 + ceil(48*40*48/1728)=54

        removed = validate_success(
            api.remove_manifest_entry(entry_b["id"], headers=DOCK))
        assert removed["status"] == "REMOVED"
        after = get_trailer(trailer["id"])
        assert after["loaded_weight_lbs"] == 26000, "weight ledger drift-free"
        assert after["loaded_cube_cuft"] == 512, "cube ledger drift-free"
        assert after["utilization_pct"] == 65.0
        shipment_b = get_success_data(api.get_shipment(ctx_b["shipment"]["id"],
                                                       headers=DOCK))
        assert shipment_b["handling_status"] == "ON_DOCK"

    def test_manifest_add_and_remove_each_increment_version(self, api):
        """PRD §2.6: "Every successful manifest add, manifest remove, seal, or
        reopen increments the trailer's `version` by exactly 1 and refreshes its
        `updated_at`."

        Design: Difficulty/compensating_invariant/manifest_add_remove_preserves_loaded_ledger
        """
        trailer, _, ctx_b, v0 = self._setup(api)
        v1 = get_trailer(trailer["id"])["version"]
        assert v1 == v0 + 1, "manifest add bumped the version by exactly 1"
        entry_b = add_manifest_entry(trailer["id"], ctx_b["shipment"]["id"],
                                     load_position=2)
        v2 = get_trailer(trailer["id"])["version"]
        assert v2 == v1 + 1
        validate_success(api.remove_manifest_entry(entry_b["id"], headers=DOCK))
        v3 = get_trailer(trailer["id"])["version"]
        assert v3 == v2 + 1, "manifest remove bumped the version by exactly 1"


class TestOccVersionObservability:
    def test_trailer_version_increments_and_stale_reuse_rejected(self, api):
        """PRD §2.6: "Every successful manifest add, manifest remove, seal, or
        reopen increments the trailer's `version` by exactly 1 and refreshes its
        `updated_at`."
        PRD §2.6: "**Manifesting a shipment onto a trailer** requires the request
        body to carry `expected_trailer_version`, the value of the trailer's
        `version` the client last observed. If that value does not equal the
        trailer's current `version`, the request is rejected with
        `ERR_STALE_TRAILER_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_version_increments_on_every_mutation
        """
        origin, dest = make_terminal_pair()
        trailer = make_trailer(origin["id"], dest["id"], door_number=48)
        v0 = trailer["version"]
        _, ctxs = _three_on_dock_shipments(origin["id"], dest["id"], [500, 700])
        add_manifest_entry(trailer["id"], ctxs[0]["shipment"]["id"])
        v1 = get_trailer(trailer["id"])["version"]
        assert v1 == v0 + 1, "exactly one increment per manifest add"
        # Reusing the pre-mutation version with a fresh, loadable shipment:
        # the staleness is the failing check.
        resp = api.create_manifest_entry(
            trailer["id"],
            create_manifest_entry_payload(ctxs[1]["shipment"]["id"], v0,
                                          load_position=2),
            headers=DOCK,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_TRAILER_VERSION)
        after = get_trailer(trailer["id"])
        assert after["version"] == v1
        assert after["loaded_weight_lbs"] == 500
