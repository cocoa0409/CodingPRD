"""The two optimistic-concurrency guards on the shared parents, the inclusive posture
threshold that one thousandth of a ton decides, and the immediacy of a mutation response.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BatchStatus,
    ProductionPosture,
    RunStatus,
    assert_no_run_side_effects,
    assert_production_run,
    factories,
    fixtures,
    test_users,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStalePlantVersionGuard:
    """One plant read cannot serve two schedules, because the first schedule advances the
    ledger the second one reasoned about."""

    def test_replaying_one_plant_snapshot_on_a_second_run_is_refused_then_retried(
        self, api: ApiClient
    ) -> None:
        """The refused schedule reserves nothing, and a fresh read lets the same call through.

        PRD: "If that value does not equal the plant's current `version` at the moment the request is processed, the request is rejected with `ERR_STALE_PLANT_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/stale_plant_version_blocks_a_second_schedule_on_the_same_snapshot
        """
        world = fixtures.baseline_with_stucco(api)
        run_a = fixtures.draft_run(api, world, requested_planned_msf=100.0)
        run_b = fixtures.draft_run(
            api,
            world,
            window_start="2026-08-04T06:00:00Z",
            window_end="2026-08-04T10:00:00Z",
            requested_planned_msf=100.0,
        )

        snapshot = world.read_plant()["version"]

        scheduled_a = validate_success(
            api.schedule_run(
                run_a["id"],
                factories.schedule_payload(snapshot),
                test_users.PRODUCTION_SCHEDULER,
            ),
            200,
        )
        assert scheduled_a["status"] == RunStatus.SCHEDULED.value
        assert scheduled_a["stucco_reserved_tons"] == pytest.approx(67.500, abs=0.0005)
        assert world.read_plant()["version"] == snapshot + 1

        validate_error(
            api.schedule_run(
                run_b["id"],
                factories.schedule_payload(snapshot),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.STALE_PLANT_VERSION.value,
            412,
        )

        assert_no_run_side_effects(world.read_run(run_b["id"]), RunStatus.DRAFT.value)
        assert world.read_plant()["stucco_committed_tons"] == pytest.approx(67.500, abs=0.0005)

        fresh = world.read_plant()["version"]
        assert fresh == snapshot + 1
        scheduled_b = validate_success(
            api.schedule_run(
                run_b["id"], factories.schedule_payload(fresh), test_users.PRODUCTION_SCHEDULER
            ),
            200,
        )
        assert scheduled_b["status"] == RunStatus.SCHEDULED.value

        plant = world.read_plant()
        assert plant["stucco_committed_tons"] == pytest.approx(135.000, abs=0.0005)
        assert plant["version"] == snapshot + 2


class TestStaleLotVersionGuard:
    """The lot balance has its own guard and its own code, which is what stops a replayed
    feed from over-drawing a lot."""

    def test_a_replayed_feed_on_the_pre_feed_lot_version_is_refused_then_retried(
        self, api: ApiClient
    ) -> None:
        """20.000 tons are drawn once, not twice, and the retry draws the second 20.000.

        PRD: "A mismatch with the lot's current `version` is rejected with `ERR_STALE_LOT_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/stale_lot_version_blocks_a_replayed_feed
        """
        world = fixtures.compact_batch_world(api, tons_fed=20.0, received_tons=100.0, close=False)
        at_assay = world.lot_a["version"]
        assert world.read_lot_a()["version"] == at_assay + 1, (
            "the first feed already consumed the version captured at assay time"
        )

        validate_error(
            api.create_batch_feed(
                world.batch_id,
                factories.batch_feed_payload(world.lot_a_id, 20.0, 10.0, at_assay),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.STALE_LOT_VERSION.value,
            412,
        )

        refused_lot = world.read_lot_a()
        assert refused_lot["consumed_tons"] == pytest.approx(20.000, abs=0.0005)
        assert refused_lot["remaining_tons"] == pytest.approx(80.000, abs=0.0005)
        assert world.read_batch()["feed_tons_total"] == pytest.approx(20.000, abs=0.0005)

        accepted = validate_success(
            api.create_batch_feed(
                world.batch_id,
                factories.batch_feed_payload(world.lot_a_id, 20.0, 10.0, refused_lot["version"]),
                test_users.MATERIALS_CONTROLLER,
            ),
            201,
        )
        assert accepted["feed_seq"] == 2

        lot = world.read_lot_a()
        assert lot["consumed_tons"] == pytest.approx(40.000, abs=0.0005)
        assert lot["remaining_tons"] == pytest.approx(60.000, abs=0.0005)
        assert lot["version"] == at_assay + 2

        _, meta = validate_paginated(
            api.list_batch_feeds(
                test_users.MATERIALS_CONTROLLER, params={"batch_id": world.batch_id}
            )
        )
        assert meta["total_count"] == 2, "one rejected replay wrote no feed row"


class TestPostureThresholdIsInclusive:
    """Two plants built identically apart from one thousandth of a ton of feed, which is
    enough to move the posture."""

    @staticmethod
    def _plant_credited(
        api: ApiClient, code: str, name: str, tons_fed: float
    ) -> fixtures.World:
        """Credit a plant's silo with exactly ``tons_fed`` multiplied by 0.8437."""
        world = fixtures.baseline(api, plant={"code": code, "name": name})
        world.lot_a = fixtures.synthetic_lot(
            api,
            world.plant_id,
            free_moisture_pct=0.0,
            purity_pct=100.0,
            chloride_ppm=0,
            supplier_name="Bone Dry FGD",
            received_tons=100.0,
        )
        world.batch = fixtures.create_batch(api, world.plant_id)
        fixtures.feed(api, world.batch_id, world.lot_a_id, tons_fed, 0.0)
        fixtures.close_feed(api, world.batch_id)
        fixtures.record_stucco_test(api, world.batch_id)
        world.read_batch()
        world.read_plant()
        return world

    def test_forty_tons_available_is_open_and_one_thousandth_less_is_restricted(
        self, api: ApiClient
    ) -> None:
        """40.000 tons sits on the threshold and 39.999 tons sits below it.

        PRD: "Note the asymmetry: the held-run comparisons are inclusive of the threshold, while the stucco comparison is strict, so a plant sitting on exactly 40.0 available tons with no held runs is `OPEN`."

        Design: Corner/cross_cutting_complexity_layers/posture_flips_open_at_exactly_forty_available_tons
        """
        on_the_line = self._plant_credited(api, "GYP-A", "Cache la Poudre Wallboard", 47.410)
        below = self._plant_credited(api, "GYP-B", "Big Thompson Wallboard", 47.409)

        assert on_the_line.batch["status"] == BatchStatus.COMPLETED.value
        assert on_the_line.batch["stucco_yield_actual_tons"] == pytest.approx(40.000, abs=0.0005)
        assert below.batch["stucco_yield_actual_tons"] == pytest.approx(39.999, abs=0.0005)

        open_plant = on_the_line.read_plant()
        assert open_plant["stucco_on_hand_tons"] == pytest.approx(40.000, abs=0.0005)
        assert open_plant["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert open_plant["stucco_available_tons"] == pytest.approx(40.000, abs=0.0005)
        assert open_plant["held_run_count"] == 0
        assert open_plant["production_posture"] == ProductionPosture.OPEN.value

        restricted_plant = below.read_plant()
        assert restricted_plant["stucco_available_tons"] == pytest.approx(39.999, abs=0.0005)
        assert restricted_plant["held_run_count"] == 0
        assert restricted_plant["production_posture"] == ProductionPosture.RESTRICTED.value

    def test_the_same_thousandth_decides_whether_a_fire_rated_run_may_be_scheduled(
        self, api: ApiClient
    ) -> None:
        """A fire-rated SKU is refused on the RESTRICTED plant and scheduled on the OPEN one.

        PRD: "Scheduling is additionally refused while the posture is `RESTRICTED` when the SKU being produced is fire-rated, with `ERR_POSTURE_RESTRICTED_FIRE_RATED` (HTTP 409); a `RESTRICTED` plant may still schedule non-fire-rated SKUs."

        Design: Corner/cross_cutting_complexity_layers/posture_flips_open_at_exactly_forty_available_tons
        """
        on_the_line = self._plant_credited(api, "GYP-A", "Cache la Poudre Wallboard", 47.410)
        below = self._plant_credited(api, "GYP-B", "Big Thompson Wallboard", 47.409)

        fire_rated: dict[str, object] = {
            "requested_planned_msf": 40.0,
            "line_speed_fpm": 380,
            "paper_tension_lb": 40.0,
            "kiln_dwell_minutes": 50,
        }
        draft_open = fixtures.draft_run(
            api, on_the_line, spec_id=on_the_line.spec_tx_id, **fire_rated
        )
        draft_restricted = fixtures.draft_run(
            api, below, spec_id=below.spec_tx_id, **fire_rated
        )

        validate_error(
            api.schedule_run(
                draft_restricted["id"],
                factories.schedule_payload(below.read_plant()["version"]),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.POSTURE_RESTRICTED_FIRE_RATED.value,
            409,
        )
        assert_no_run_side_effects(
            below.read_run(draft_restricted["id"]), RunStatus.DRAFT.value
        )
        assert below.read_plant()["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)

        scheduled = validate_success(
            api.schedule_run(
                draft_open["id"],
                factories.schedule_payload(on_the_line.read_plant()["version"]),
                test_users.PRODUCTION_SCHEDULER,
            ),
            200,
        )
        assert scheduled["status"] == RunStatus.SCHEDULED.value
        assert scheduled["effective_planned_msf"] == pytest.approx(40.000, abs=0.0005)
        assert scheduled["stucco_reserved_tons"] == pytest.approx(36.400, abs=0.0005)

        plant = on_the_line.read_plant()
        assert plant["stucco_committed_tons"] == pytest.approx(36.400, abs=0.0005)
        assert plant["stucco_available_tons"] == pytest.approx(3.600, abs=0.0005)
        assert plant["production_posture"] == ProductionPosture.RESTRICTED.value


class TestMutationResponseIsAlreadySettled:
    """The schedule response carries its derived figures, and the very next read agrees
    with it field for field."""

    def test_the_schedule_response_and_the_immediate_reads_all_agree(
        self, api: ApiClient
    ) -> None:
        """202.500 committed tons and a flipped posture are visible with no re-read delay.

        PRD: "There is no deferred reconciliation and no eventual consistency: a client that reads a plant, a line, a run and its load orders immediately after an outage approval sees all four already settled."

        Design: Corner/consistency_model/schedule_response_already_reflects_the_new_silo_commitment
        """
        world = fixtures.baseline_with_stucco(api)
        draft = fixtures.draft_run(api, world)

        before = world.read_plant()
        assert before["production_posture"] == ProductionPosture.OPEN.value
        assert before["stucco_available_tons"] == pytest.approx(204.530, abs=0.0005)

        scheduled = validate_success(
            api.schedule_run(
                draft["id"],
                factories.schedule_payload(before["version"]),
                test_users.PRODUCTION_SCHEDULER,
            ),
            200,
        )
        assert_production_run(scheduled)
        assert scheduled["status"] == RunStatus.SCHEDULED.value
        assert scheduled["effective_planned_msf"] == pytest.approx(300.000, abs=0.0005)
        assert scheduled["stucco_reserved_tons"] == pytest.approx(202.500, abs=0.0005)
        assert scheduled["kiln_energy_mmbtu"] == pytest.approx(518.018, abs=0.0005)

        plant = world.read_plant()
        assert plant["stucco_committed_tons"] == pytest.approx(202.500, abs=0.0005)
        assert plant["stucco_available_tons"] == pytest.approx(2.030, abs=0.0005)
        assert plant["production_posture"] == ProductionPosture.RESTRICTED.value

        assert world.read_run(draft["id"]) == scheduled, (
            "the read repeats the mutation response rather than catching up to it"
        )
