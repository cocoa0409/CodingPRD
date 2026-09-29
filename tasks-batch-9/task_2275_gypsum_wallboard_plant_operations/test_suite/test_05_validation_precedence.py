"""Requests that break two rules at once, where the screening order decides which
error comes back: a state check ahead of a balance check, a safety check ahead of a
window check, and a posture check ahead of a balance check.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BatchStatus,
    LotStatus,
    ProductionPosture,
    RunStatus,
    StuccoQualityFlag,
    assert_no_run_side_effects,
    factories,
    fixtures,
    test_users,
    validate_error,
    validate_paginated,
)


class TestLotStateBeatsLotBalance:
    """A 500-ton draw on an unassayed 300-ton lot violates the state precondition of
    band 8 and the balance rule of band 20 at the same time."""

    @staticmethod
    def _unassayed_lot_and_batch(api: ApiClient) -> tuple[str, str, int]:
        plant = fixtures.create_plant(api)
        lot = fixtures.create_lot(api, factories.synthetic_lot_payload(plant["id"]))
        batch = fixtures.create_batch(api, plant["id"])
        return lot["id"], batch["id"], lot["version"]

    def test_the_unapproved_lot_decides_the_error_not_the_short_balance(
        self, api: ApiClient
    ) -> None:
        """Feeding 500 tons of a RECEIVED lot reports the status, never the tonnage.

        PRD: "When more than one rule could reject a request, the system evaluates checks in a fixed order and returns the error belonging to the first check that fails."

        Design: Difficulty/priority_pair_validation_conflict/lot_not_approved_precedes_lot_tons_insufficient
        """
        lot_id, batch_id, lot_version = self._unassayed_lot_and_batch(api)

        body = validate_error(
            api.create_batch_feed(
                batch_id,
                factories.batch_feed_payload(lot_id, 500.0, 9.4, lot_version),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.LOT_NOT_APPROVED.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.LOT_TONS_INSUFFICIENT.value, (
            "the balance rule sits eleven bands later and must not be reported"
        )

        lot = fixtures.read_lot(api, lot_id)
        assert lot["status"] == LotStatus.RECEIVED.value
        assert lot["consumed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert lot["remaining_tons"] == pytest.approx(300.000, abs=0.0005)
        assert lot["version"] == 1, "a refused feed is not a mutation of the lot"

        batch = fixtures.read_batch(api, batch_id)
        assert batch["status"] == BatchStatus.PLANNED.value
        assert batch["feed_tons_total"] == pytest.approx(0.000, abs=0.0005)

        _, meta = validate_paginated(
            api.list_batch_feeds_of_batch(batch_id, test_users.MATERIALS_CONTROLLER)
        )
        assert meta["total_count"] == 0, "no feed row was written"

    def test_the_short_balance_is_reported_once_the_lot_is_approved(
        self, api: ApiClient
    ) -> None:
        """With the state check satisfied the very same 500-ton draw reports the balance.

        PRD: "**Balance sufficiency.** `ERR_LOT_TONS_INSUFFICIENT` (HTTP 409) on feed creation; `ERR_STUCCO_INSUFFICIENT` (HTTP 409) on run scheduling; `ERR_RUN_MSF_INSUFFICIENT` (HTTP 409) on load staging."

        Design: Difficulty/priority_pair_validation_conflict/lot_not_approved_precedes_lot_tons_insufficient
        """
        plant = fixtures.create_plant(api)
        lot = fixtures.synthetic_lot(api, plant["id"])
        batch = fixtures.create_batch(api, plant["id"])

        assert lot["status"] == LotStatus.APPROVED.value
        assert lot["remaining_tons"] == pytest.approx(300.000, abs=0.0005)

        validate_error(
            api.create_batch_feed(
                batch["id"],
                factories.batch_feed_payload(lot["id"], 500.0, 9.4, lot["version"]),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.LOT_TONS_INSUFFICIENT.value,
            409,
        )

        after = fixtures.read_lot(api, lot["id"])
        assert after["consumed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert after["version"] == lot["version"], "the refused draw moved nothing"


class TestFireRatedStuccoBeatsLineWindow:
    """A TYPE_X run drawing MARGINAL stucco into a window already occupied by a
    scheduled run breaks the band 11 material gate and the band 14 window rule."""

    @staticmethod
    def _marginal_batch_world(api: ApiClient):
        """B1 completed on a MARGINAL sample, B2 completed PASS, R1 scheduled."""
        world = fixtures.baseline_with_lots(api)
        world.batch = fixtures.fed_batch(api, world)
        fixtures.record_stucco_test(api, world.batch_id, free_water_pct=0.35)
        world.read_batch()
        fixtures.second_batch_completed(api, world)
        return fixtures.scheduled_run(api, world)

    def test_the_nonconforming_stucco_decides_the_error_not_the_occupied_window(
        self, api: ApiClient
    ) -> None:
        """A fire-rated draft on MARGINAL stucco reports 422, never the window conflict.

        PRD: "When the SKU is fire-rated there is a stricter material gate: the batch's `stucco_quality_flag` must be exactly `PASS`, and `MARGINAL`, `FAIL` and `PENDING` all fail with `ERR_FIRE_RATED_STUCCO_NONCONFORMING`."

        Design: Difficulty/priority_pair_validation_conflict/fire_rated_stucco_precedes_line_window_conflict
        """
        world = self._marginal_batch_world(api)
        batch = world.read_batch()
        assert batch["stucco_quality_flag"] == StuccoQualityFlag.MARGINAL.value
        assert batch["status"] == BatchStatus.COMPLETED.value

        tx_run = fixtures.draft_run(
            api,
            world,
            spec_id=world.spec_tx_id,
            window_start="2026-08-03T08:00:00Z",
            window_end="2026-08-03T12:00:00Z",
            requested_planned_msf=100.0,
            line_speed_fpm=380,
            paper_tension_lb=42.0,
            kiln_dwell_minutes=50,
        )

        body = validate_error(
            api.schedule_run(
                tx_run["id"],
                factories.schedule_payload(world.plant_version()),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.FIRE_RATED_STUCCO_NONCONFORMING.value,
            422,
        )
        assert body["error_id"] != ApiErrorId.LINE_WINDOW_CONFLICT.value, (
            "the window conflict sits three bands later than the material gate"
        )

        assert_no_run_side_effects(world.read_run(tx_run["id"]), RunStatus.DRAFT.value)

        plant = world.read_plant()
        assert plant["stucco_committed_tons"] == pytest.approx(202.500, abs=0.0005), (
            "only the standard run's reservation is committed"
        )
        assert plant["stucco_available_tons"] == pytest.approx(94.777, abs=0.0005), (
            "297.277 credited by the two batches less the 202.500 already committed"
        )
        assert plant["production_posture"] == ProductionPosture.OPEN.value, (
            "94.777 available tons is well above the 40.0-ton floor"
        )

    def test_the_window_conflict_is_reported_for_a_sku_the_material_gate_ignores(
        self, api: ApiClient
    ) -> None:
        """A standard SKU is not gated on the flag, so the same overlap reports 409.

        PRD: "and it must not overlap any other run on the same line whose `status` is `SCHEDULED` or `RUNNING`, judged under the half-open convention, or the request fails with `ERR_LINE_WINDOW_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/fire_rated_stucco_precedes_line_window_conflict
        """
        world = self._marginal_batch_world(api)

        overlapping = fixtures.draft_run(
            api,
            world,
            window_start="2026-08-03T08:00:00Z",
            window_end="2026-08-03T12:00:00Z",
            requested_planned_msf=100.0,
        )

        validate_error(
            api.schedule_run(
                overlapping["id"],
                factories.schedule_payload(world.plant_version()),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.LINE_WINDOW_CONFLICT.value,
            409,
        )

        assert_no_run_side_effects(world.read_run(overlapping["id"]), RunStatus.DRAFT.value)
        assert world.read_plant()["stucco_committed_tons"] == pytest.approx(202.500, abs=0.0005)


class TestPostureBeatsStuccoBalance:
    """On a RESTRICTED plant with 2.030 tons free, a fire-rated schedule breaks the
    band 10 posture gate and the band 20 balance rule together."""

    def test_the_restricted_posture_decides_the_error_not_the_missing_tonnage(
        self, api: ApiClient
    ) -> None:
        """The fire-rated posture gate answers first even though the tonnage is absent.

        PRD: "Scheduling is additionally refused while the posture is `RESTRICTED` when the SKU being produced is fire-rated, with `ERR_POSTURE_RESTRICTED_FIRE_RATED` (HTTP 409); a `RESTRICTED` plant may still schedule non-fire-rated SKUs."

        Design: Difficulty/priority_pair_validation_conflict/posture_restricted_precedes_stucco_insufficient
        """
        world = fixtures.scheduled_run(api)

        before = world.read_plant()
        assert before["stucco_available_tons"] == pytest.approx(2.030, abs=0.0005), (
            "204.530 credited less the 202.500 the standard run reserved"
        )
        assert before["production_posture"] == ProductionPosture.RESTRICTED.value
        assert before["stucco_committed_tons"] == pytest.approx(202.500, abs=0.0005)

        tx_run = fixtures.draft_run(
            api,
            world,
            spec_id=world.spec_tx_id,
            window_start="2026-08-04T06:00:00Z",
            window_end="2026-08-04T10:00:00Z",
            requested_planned_msf=100.0,
            line_speed_fpm=380,
            paper_tension_lb=42.0,
            kiln_dwell_minutes=50,
        )

        body = validate_error(
            api.schedule_run(
                tx_run["id"],
                factories.schedule_payload(world.plant_version()),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.POSTURE_RESTRICTED_FIRE_RATED.value,
            409,
        )
        assert body["error_id"] != ApiErrorId.STUCCO_INSUFFICIENT.value, (
            "the 91.000-ton reservation is unaffordable, but that check is ten bands later"
        )

        assert_no_run_side_effects(world.read_run(tx_run["id"]), RunStatus.DRAFT.value)
        assert world.read_plant()["stucco_committed_tons"] == pytest.approx(202.500, abs=0.0005)

    def test_the_balance_is_reported_for_the_sku_the_posture_gate_lets_through(
        self, api: ApiClient
    ) -> None:
        """A standard SKU passes the posture gate and then fails on the empty silo.

        PRD: "If that reservation is strictly greater than the plant's `stucco_available_tons`, the schedule is refused with `ERR_STUCCO_INSUFFICIENT`; a reservation exactly equal to what is available is accepted."

        Design: Difficulty/priority_pair_validation_conflict/posture_restricted_precedes_stucco_insufficient
        """
        world = fixtures.scheduled_run(api)
        assert world.read_plant()["production_posture"] == ProductionPosture.RESTRICTED.value

        second_regular = fixtures.draft_run(
            api,
            world,
            window_start="2026-08-04T06:00:00Z",
            window_end="2026-08-04T10:00:00Z",
            requested_planned_msf=100.0,
        )

        validate_error(
            api.schedule_run(
                second_regular["id"],
                factories.schedule_payload(world.plant_version()),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.STUCCO_INSUFFICIENT.value,
            409,
        )

        assert_no_run_side_effects(world.read_run(second_regular["id"]), RunStatus.DRAFT.value)
        plant = world.read_plant()
        assert plant["stucco_available_tons"] == pytest.approx(2.030, abs=0.0005), (
            "the refused reservation left the balance where it was"
        )
