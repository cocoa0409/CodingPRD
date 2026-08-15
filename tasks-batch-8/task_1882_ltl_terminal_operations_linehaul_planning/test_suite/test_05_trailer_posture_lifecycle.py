"""Trailer posture lifecycle: reopen cycles, posture gating of manifest writes,
OCC on seal, and the ARRIVED terminal-state lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_manifest_entry,
    create_manifest_entry_payload,
    create_seal_payload,
    get_success_data,
    get_trailer,
    make_delivered_shipment,
    make_on_dock_shipment,
    make_ready_trailer,
    make_sealed_trailer,
    make_terminal_pair,
    validate_error,
    validate_success,
)

DOCK = TEST_USERS["dock_supervisor_headers"]
DISP = TEST_USERS["dispatcher_headers"]


class TestReopenCycle:
    def test_reopen_from_ready_returns_to_loading(self, api):
        """PRD §3.5: "A `READY` or `SEALED` trailer may be reopened back to
        `LOADING` — for a `SEALED` trailer only if no linehaul leg referencing
        it is currently `EN_ROUTE` — which re-enables manifest add/remove and
        likewise bumps `version`."
        PRD §2.6: "Every successful manifest add, manifest remove, seal, or
        reopen increments the trailer's `version` by exactly 1 and refreshes its
        `updated_at`."

        Design: Difficulty/non_linear_state_machine/outbound_trailer_posture_reopen_cycle
        """
        origin, dest = make_terminal_pair(origin_code="CHI", dest_code="ATL")
        ctx = make_ready_trailer(origin["id"], dest["id"], door_number=24)
        trailer = ctx["trailer"]
        assert trailer["posture"] == "READY"
        v_ready = trailer["version"]

        reopened = validate_success(api.reopen_trailer(trailer["id"],
                                                       headers=DOCK))
        assert reopened["posture"] == "LOADING", "READY -> LOADING reopen cycle"
        # The manifest ledger survives the posture cycle untouched.
        assert reopened["loaded_weight_lbs"] == 26000
        assert reopened["loaded_cube_cuft"] == 512
        assert reopened["utilization_pct"] == 65.0
        assert reopened["version"] == v_ready + 1, (
            "reopen bumps the trailer version by exactly 1"
        )

    def test_reopen_from_sealed_rearms_manifest_writes(self, api):
        """PRD §3.5: "A `READY` or `SEALED` trailer may be reopened back to
        `LOADING` — for a `SEALED` trailer only if no linehaul leg referencing
        it is currently `EN_ROUTE` — which re-enables manifest add/remove and
        likewise bumps `version`."

        Design: Difficulty/non_linear_state_machine/outbound_trailer_posture_reopen_cycle
        """
        origin, dest = make_terminal_pair(origin_code="CHI", dest_code="ATL")
        ctx = make_sealed_trailer(origin["id"], dest["id"], door_number=24)
        trailer = ctx["trailer"]
        assert trailer["posture"] == "SEALED"

        # A second shipment is rated and waiting on the dock.
        ctx_b = make_on_dock_shipment(origin["id"], dest["id"],
                                      actual_weight_lbs=1000, length_in=48,
                                      width_in=40, height_in=48)

        reopened = validate_success(api.reopen_trailer(trailer["id"],
                                                       headers=DOCK))
        assert reopened["posture"] == "LOADING"
        # Manifest writes are re-armed after the SEALED -> LOADING reopen.
        entry_b = add_manifest_entry(trailer["id"], ctx_b["shipment"]["id"],
                                     load_position=2)
        assert entry_b["status"] == "ACTIVE"
        after = get_trailer(trailer["id"])
        assert after["loaded_weight_lbs"] == 27000
        assert after["loaded_cube_cuft"] == 566


class TestManifestPostureGate:
    def _ready_trailer_plus_second_shipment(self, origin, dest):
        ctx = make_ready_trailer(origin["id"], dest["id"], door_number=31)
        ctx_b = make_on_dock_shipment(origin["id"], dest["id"],
                                      actual_weight_lbs=1000, length_in=48,
                                      width_in=40, height_in=48)
        return ctx, ctx_b

    def test_manifest_add_rejected_when_trailer_ready(self, api):
        """PRD §3.5: "The trailer's `posture` must be `LOADING` — manifesting
        into a `READY`, `SEALED`, or later trailer is `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/manifest_add_gated_by_trailer_posture
        """
        origin, dest = make_terminal_pair()
        ctx, ctx_b = self._ready_trailer_plus_second_shipment(origin, dest)
        trailer = ctx["trailer"]
        assert trailer["posture"] == "READY"
        resp = api.create_manifest_entry(
            trailer["id"],
            create_manifest_entry_payload(ctx_b["shipment"]["id"],
                                          trailer["version"], load_position=2),
            headers=DOCK,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        shipment_b = get_success_data(api.get_shipment(ctx_b["shipment"]["id"],
                                                       headers=DOCK))
        assert shipment_b["handling_status"] == "ON_DOCK"

    def test_manifest_add_succeeds_after_reopen(self, api):
        """PRD §3.5: "A `READY` or `SEALED` trailer may be reopened back to
        `LOADING` — for a `SEALED` trailer only if no linehaul leg referencing
        it is currently `EN_ROUTE` — which re-enables manifest add/remove and
        likewise bumps `version`."
        PRD §3.5: "On success the entry is created with `status` `ACTIVE`, the
        shipment's `handling_status` advances from `ON_DOCK` to `MANIFESTED`"

        Design: Difficulty/cross_entity_state_dependency/manifest_add_gated_by_trailer_posture
        """
        origin, dest = make_terminal_pair()
        ctx, ctx_b = self._ready_trailer_plus_second_shipment(origin, dest)
        trailer = ctx["trailer"]
        validate_success(api.reopen_trailer(trailer["id"], headers=DOCK))
        entry_b = add_manifest_entry(trailer["id"], ctx_b["shipment"]["id"],
                                     load_position=2)
        assert entry_b["status"] == "ACTIVE"
        shipment_b = get_success_data(api.get_shipment(ctx_b["shipment"]["id"],
                                                       headers=DOCK))
        assert shipment_b["handling_status"] == "MANIFESTED"


class TestArrivedLockdown:
    def test_arrived_trailer_rejects_posture_writes(self, api):
        """PRD §3.5: "Success moves posture from `LOADING` to `READY`."
        PRD §3.5: "A `READY` or `SEALED` trailer may be reopened back to
        `LOADING`"
        PRD §3.5: "An empty trailer in `LOADING` or `READY` may be voided
        outright (`VOIDED` is terminal), which frees its outbound door for
        release."
        PRD §3.6: "the arrival cascades: the trailer's posture moves
        `DISPATCHED` → `ARRIVED` (terminal)"
        PRD §2.8: "5. Entity state preconditions for the requested transition
        (e.g. trailer must be `LOADING` to accept a manifest entry, a stop must
        be `ARRIVED` to complete, a leg must be `EN_ROUTE` to arrive) →
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_state_lockdown_on_arrived_trailer
        """
        ctx = make_delivered_shipment(door_number=37)
        trailer = ctx["trailer"]
        assert trailer["posture"] == "ARRIVED"
        for call in (
            lambda: api.reopen_trailer(trailer["id"], headers=DOCK),
            lambda: api.void_trailer(trailer["id"], headers=DOCK),
            lambda: api.mark_trailer_ready(trailer["id"], headers=DOCK),
        ):
            validate_error(call(), ApiErrorId.ERR_INVALID_STATE)
        assert get_trailer(trailer["id"])["posture"] == "ARRIVED"


class TestSealOcc:
    def test_seal_with_stale_version_rejected(self, api):
        """PRD §2.6: "**Sealing a trailer** likewise requires
        `expected_trailer_version` in the request body, matching the trailer's
        current `version`. A mismatch is rejected with
        `ERR_STALE_TRAILER_VERSION` (HTTP 412)."
        PRD §3.5: "**Sealing** moves `READY` → `SEALED` and is the second
        OCC-guarded write: the request carries `expected_trailer_version` and a
        mismatch is `ERR_STALE_TRAILER_VERSION`; sealing also increments the
        trailer's `version`."

        Design: Corner/errors/error_stale_trailer_version_on_seal
        """
        origin, dest = make_terminal_pair()
        ctx = make_ready_trailer(origin["id"], dest["id"], door_number=46)
        trailer = ctx["trailer"]
        v_now = trailer["version"]
        stale = v_now - 1

        resp = api.seal_trailer(trailer["id"], create_seal_payload(stale),
                                headers=DOCK)
        validate_error(resp, ApiErrorId.ERR_STALE_TRAILER_VERSION)
        assert get_trailer(trailer["id"])["posture"] == "READY"

        sealed = validate_success(api.seal_trailer(
            trailer["id"], create_seal_payload(v_now), headers=DOCK))
        assert sealed["posture"] == "SEALED"
        assert sealed["version"] == v_now + 1
