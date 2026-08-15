"""Load dispatch windows: half-open overlap semantics, window shape, the
operations checkpoint counter, and decommission gating."""
from test_helpers import (
    ApiErrorId,
    assert_load_dispatch,
    create_boiler,
    create_dispatch,
    create_load_dispatch_payload,
    create_plant,
    get_plant,
    validate_error,
    validate_success,
)


class TestDispatchWindowIntervals:
    def test_dispatch_window_half_open_adjacency(
        self, api, plant_manager_headers
    ):
        """PRD §2.11: "A dispatch window is a half-open interval:
        `window_start_at` is inclusive, `window_end_at` is exclusive. Two
        windows conflict when the first begins before the second ends and the
        second begins before the first ends; windows that merely touch — one
        ending at exactly the instant the other begins — do not conflict."

        Design: Difficulty/resource_temporal_overlap/dispatch_window_half_open_adjacency
        """
        plant = create_plant(name="Adj Plant")
        boiler = create_boiler(plant["id"], tag="B-ADJ")
        first = create_dispatch(
            plant["id"], [boiler["id"]],
            window_start_at="2026-08-10T00:00:00Z",
            window_end_at="2026-08-10T08:00:00Z",
        )
        assert first["status"] == "SCHEDULED"

        # Adjacent: second window begins exactly when the first ends.
        resp = api.create_load_dispatch(
            plant["id"],
            create_load_dispatch_payload(
                window_start_at="2026-08-10T08:00:00Z",
                window_end_at="2026-08-10T16:00:00Z",
                assigned_boiler_ids=[boiler["id"]],
            ),
            plant_manager_headers,
        )
        second = validate_success(resp, expected_status=201)
        assert_load_dispatch(second)
        assert second["status"] == "SCHEDULED"

    def test_dispatch_window_overlap_rejected(self, api, plant_manager_headers):
        """PRD §3.8: "if any assigned boiler already appears in a `SCHEDULED`
        or `ACTIVE` window whose interval conflicts — remember that touching
        windows do not conflict — the creation is refused with
        `ERR_DISPATCH_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/dispatch_window_half_open_adjacency
        """
        plant = create_plant(name="Ovl Plant")
        boiler = create_boiler(plant["id"], tag="B-OVL")
        create_dispatch(
            plant["id"], [boiler["id"]],
            window_start_at="2026-08-10T00:00:00Z",
            window_end_at="2026-08-10T08:00:00Z",
        )

        # Overlapping: 04:00-09:00 pierces the first window's [00:00, 08:00).
        resp = api.create_load_dispatch(
            plant["id"],
            create_load_dispatch_payload(
                window_start_at="2026-08-10T04:00:00Z",
                window_end_at="2026-08-10T09:00:00Z",
                assigned_boiler_ids=[boiler["id"]],
            ),
            plant_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DISPATCH_WINDOW_CONFLICT,
                       expected_status=409)

    def test_dispatch_window_end_not_after_start_returns_400(
        self, api, plant_manager_headers
    ):
        """PRD §2.7: "Dispatch window shape — a window whose `window_end_at`
        is not strictly after its `window_start_at` is rejected with
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/validations/dispatch_window_end_not_after_start_returns_400
        """
        plant = create_plant(name="Wnd Plant")
        boiler = create_boiler(plant["id"], tag="B-WND")
        resp = api.create_load_dispatch(
            plant["id"],
            create_load_dispatch_payload(
                window_start_at="2026-08-10T08:00:00Z",
                window_end_at="2026-08-10T08:00:00Z",  # equal, not strictly after
                assigned_boiler_ids=[boiler["id"]],
            ),
            plant_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestOperationsCheckpoint:
    def test_run_ops_increments_ops_run_index(self, api, plant_manager_headers):
        """PRD §2.4: "it increments the plant's `ops_run_index` by exactly
        one". A new plant starts with `ops_run_index` 0 (PRD §3.1), so two
        checkpoints leave it at 2.

        Design: Corner/endpoints/run_ops_increments_ops_run_index
        """
        plant = create_plant(name="Ops Plant")
        assert plant["ops_run_index"] == 0
        validate_success(api.run_ops(plant["id"], plant_manager_headers))
        validate_success(api.run_ops(plant["id"], plant_manager_headers))
        assert get_plant(plant["id"])["ops_run_index"] == 2


class TestDecommissionGate:
    def test_err_boiler_in_dispatch_blocks_decommission(
        self, api, plant_manager_headers
    ):
        """PRD §3.4: "a `PlantManager` may decommission a `STANDBY` boiler,
        but only while no `SCHEDULED` or `ACTIVE` dispatch window references
        it (else `ERR_BOILER_IN_DISPATCH`)".

        Design: Corner/errors/err_boiler_in_dispatch_blocks_decommission
        """
        plant = create_plant(name="Dec Plant")
        boiler = create_boiler(plant["id"], tag="B-DEC")
        create_dispatch(plant["id"], [boiler["id"]])

        resp = api.decommission_boiler(
            plant["id"], boiler["id"], plant_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_BOILER_IN_DISPATCH)
