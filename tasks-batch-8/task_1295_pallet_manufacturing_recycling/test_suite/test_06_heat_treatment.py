"""Heat-treatment runs: chamber exclusivity, dwell, capacity, species purity."""
import pytest

from test_helpers import (
    HT,
    ApiErrorId,
    api_client,
    assign_lot_to_run,
    create_active_spec,
    create_ht_run,
    create_new_build_lot,
    get_ht_run,
    get_lot,
    publish_lumber_index,
    set_clock,
    setup_pending_ht_lot,
    start_ht_run,
    validate_error,
    validate_success,
)


class TestCompleteRequiresRunning:

    def test_complete_staging_run_rejected_not_running(self):
        """PRD §3.5: "Completion moves `RUNNING` to `COMPLETED`, requires the
        run to be `RUNNING` (else `ERR_HT_NOT_RUNNING`), and enforces the dwell
        requirement: the logical clock's current instant must be at least six
        hours past `started_at`, else `ERR_HT_DWELL_SHORT`."
        PRD §2.8: "State permission: the target resource's state permits the
        requested transition per the state machines of §3, else the
        transition-specific rejection (or `ERR_INVALID_STATE` where no specific
        code exists)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_ht_complete
        """
        _spec, lot = setup_pending_ht_lot(quantity_total=10)
        run = create_ht_run(chamber_code="CH-1", species_profile="PINE",
                            capacity_pallets=100)
        assign_lot_to_run(run["id"], lot["id"])
        # The run is STAGING: state gate fires before any dwell evaluation.
        resp = api_client.complete_ht_run(run["id"], HT)
        validate_error(resp, ApiErrorId.ERR_HT_NOT_RUNNING)
        assert resp.status_code == 409

    def test_rejected_complete_leaves_run_and_lot_untouched(self):
        """PRD §3.5: "Completion moves `RUNNING` to `COMPLETED`, requires the
        run to be `RUNNING` (else `ERR_HT_NOT_RUNNING`)"
        PRD §2.9: "An inventory lot has a `quality_grade` (`NEW`, `A`, or `B`)
        and a `heat_treat_status` (`NOT_REQUIRED`, `PENDING_HT`, or
        `HT_CERTIFIED`); the heat-treatment axis is monotonic — a lot moves
        from `PENDING_HT` to `HT_CERTIFIED` and never backward, and a lot
        created as `NOT_REQUIRED` never enters the heat-treatment axis at all —
        while the quality axis is untouched by stamping."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_ht_complete
        """
        _spec, lot = setup_pending_ht_lot(quantity_total=10)
        run = create_ht_run(chamber_code="CH-1", species_profile="PINE",
                            capacity_pallets=100)
        assign_lot_to_run(run["id"], lot["id"])
        resp = api_client.complete_ht_run(run["id"], HT)
        validate_error(resp, ApiErrorId.ERR_HT_NOT_RUNNING)
        run_after = get_ht_run(run["id"])
        lot_after = get_lot(lot["id"])
        assert run_after["status"] == "STAGING", (
            f"rejected complete must leave the run STAGING, "
            f"got {run_after['status']}"
        )
        assert lot_after["heat_treat_status"] == "PENDING_HT"
        assert lot_after["ispm15_mark_id"] is None


class TestChamberOccupancy:

    def _setup_two_staging_runs_same_chamber(self):
        _spec, lot1 = setup_pending_ht_lot(quantity_total=10)
        spec = _spec
        lot2 = create_new_build_lot(spec["id"], 10)
        run1 = create_ht_run(chamber_code="CH-1")
        assign_lot_to_run(run1["id"], lot1["id"])
        run2 = create_ht_run(chamber_code="CH-1")
        assign_lot_to_run(run2["id"], lot2["id"])
        return run1, run2, lot1, lot2

    def test_second_run_start_while_chamber_running_rejected(self):
        """PRD §2.10: "Additionally, one physical chamber can host only one
        running treatment at a time: starting a run while another run with the
        same `chamber_code` is already `RUNNING` is rejected with
        `ERR_CHAMBER_OCCUPIED`."

        Design: Difficulty/resource_temporal_overlap/ht_chamber_point_in_time_occupancy
        """
        run1, run2, _l1, _l2 = self._setup_two_staging_runs_same_chamber()
        start_ht_run(run1["id"])
        resp = api_client.start_ht_run(run2["id"], HT)
        validate_error(resp, ApiErrorId.ERR_CHAMBER_OCCUPIED)
        assert resp.status_code == 409
        run2_after = get_ht_run(run2["id"])
        assert run2_after["status"] == "STAGING", (
            f"rejected start must leave run2 STAGING, got {run2_after['status']}"
        )

    def test_chamber_released_after_completion_allows_new_run(self):
        """PRD §2.10: "Additionally, one physical chamber can host only one
        running treatment at a time: starting a run while another run with the
        same `chamber_code` is already `RUNNING` is rejected with
        `ERR_CHAMBER_OCCUPIED`."
        PRD §3.5: "Completion moves `RUNNING` to `COMPLETED`, requires the run
        to be `RUNNING` (else `ERR_HT_NOT_RUNNING`), and enforces the dwell
        requirement: the logical clock's current instant must be at least six
        hours past `started_at`, else `ERR_HT_DWELL_SHORT`."

        Design: Difficulty/resource_temporal_overlap/ht_chamber_point_in_time_occupancy
        """
        run1, run2, _l1, _l2 = self._setup_two_staging_runs_same_chamber()
        start_ht_run(run1["id"])
        set_clock("2026-08-01T07:00:00Z")  # 7h dwell
        done = validate_success(api_client.complete_ht_run(run1["id"], HT))
        assert done["status"] == "COMPLETED"
        # Occupancy is state-derived: a COMPLETED run no longer blocks CH-1.
        started2 = validate_success(api_client.start_ht_run(run2["id"], HT))
        assert started2["status"] == "RUNNING"


class TestCompletionStampsLots:

    def test_ht_complete_certifies_assigned_lots(self):
        """PRD §3.5: "At completion `completed_at` is stamped and the run mints
        its `ispm15_mark_id` in the format `HT-<chamber_code>-<yyyymmdd>-<seq>`;
        every assigned lot flips its `heat_treat_status` from `PENDING_HT` to
        `HT_CERTIFIED` with the run's `ispm15_mark_id` copied onto the lot,
        while `quality_grade` stays exactly as it was — the two axes are
        parallel (§2.9)."

        Design: Corner/state_machines/ht_complete_stamps_lots_with_ispm15
        """
        _spec, lot = setup_pending_ht_lot(quantity_total=10)
        run = create_ht_run(chamber_code="CH-9", species_profile="PINE",
                            capacity_pallets=100)
        assign_lot_to_run(run["id"], lot["id"])
        start_ht_run(run["id"])
        set_clock("2026-08-01T07:00:00Z")  # 7h >= 6h dwell
        resp = api_client.complete_ht_run(run["id"], HT)
        done = validate_success(resp)
        assert done["status"] == "COMPLETED"
        assert done["ispm15_mark_id"], "completion must mint an ISPM-15 mark"
        assert done["ispm15_mark_id"].startswith("HT-CH-9-"), (
            f"mark must follow HT-<chamber_code>-..., "
            f"got {done['ispm15_mark_id']}"
        )
        lot_after = get_lot(lot["id"])
        assert lot_after["heat_treat_status"] == "HT_CERTIFIED"
        assert lot_after["ispm15_mark_id"] == done["ispm15_mark_id"], (
            "the run's mark must be copied onto every assigned lot"
        )
        assert lot_after["quality_grade"] == "NEW", (
            "stamping must not touch the quality axis"
        )

    def test_ht_fail_releases_lots_pending(self):
        """PRD §3.5: "Failing a `RUNNING` run (else `ERR_HT_NOT_RUNNING`)
        releases its lots: they remain `PENDING_HT`, are unassigned from the
        failed run, and are free to join a new one."

        Design: Corner/state_machines/ht_fail_releases_lots_back_to_pending
        """
        _spec, lot = setup_pending_ht_lot(quantity_total=10)
        run = create_ht_run(chamber_code="CH-9", species_profile="PINE",
                            capacity_pallets=100)
        assign_lot_to_run(run["id"], lot["id"])
        start_ht_run(run["id"])
        resp = api_client.fail_ht_run(run["id"], HT)
        failed = validate_success(resp)
        assert failed["status"] == "FAILED"
        lot_after = get_lot(lot["id"])
        assert lot_after["heat_treat_status"] == "PENDING_HT"
        # The released lot can join a new run.
        run2 = create_ht_run(chamber_code="CH-9", species_profile="PINE",
                             capacity_pallets=100)
        reassigned = validate_success(
            api_client.assign_lot_to_run(run2["id"], {"lot_id": lot["id"]}, HT))
        assert reassigned["loaded_pallets"] == 10


class TestAssignmentGates:

    def test_ht_assign_exact_fit_then_overflow(self):
        """PRD §2.10: "A heat-treatment run declares `capacity_pallets` and
        accumulates `loaded_pallets` as lots are assigned; an assignment that
        would push `loaded_pallets` beyond `capacity_pallets` is rejected with
        `ERR_HT_CAPACITY_EXCEEDED`."

        Design: Corner/validations/ht_capacity_exact_fit_and_overflow
        """
        _spec, lot1 = setup_pending_ht_lot(quantity_total=20)
        spec = _spec
        lot2 = create_new_build_lot(spec["id"], 10)
        lot3 = create_new_build_lot(spec["id"], 1)
        run = create_ht_run(chamber_code="CH-3", species_profile="PINE",
                            capacity_pallets=30)
        r1 = validate_success(
            api_client.assign_lot_to_run(run["id"], {"lot_id": lot1["id"]}, HT))
        assert r1["loaded_pallets"] == 20
        # Exact fit: 20 + 10 == 30 == capacity_pallets -> admitted (<= gate).
        r2 = validate_success(
            api_client.assign_lot_to_run(run["id"], {"lot_id": lot2["id"]}, HT))
        assert r2["loaded_pallets"] == 30
        resp = api_client.assign_lot_to_run(run["id"], {"lot_id": lot3["id"]},
                                            HT)
        validate_error(resp, ApiErrorId.ERR_HT_CAPACITY_EXCEEDED)
        assert resp.status_code == 422
        run_after = get_ht_run(run["id"])
        assert run_after["loaded_pallets"] == 30, (
            "rejected assignment must not add to loaded_pallets"
        )

    def test_ht_assign_species_mismatch_rejected(self):
        """PRD §3.5: "species purity must hold — the lot's spec's
        `lumber_species` must equal the run's `species_profile`, else
        `ERR_HT_SPECIES_MISMATCH`"

        Design: Corner/validations/ht_species_mismatch_rejected
        """
        set_clock()
        publish_lumber_index(species="OAK", price_per_mbf_cents=600000)
        oak_spec = create_active_spec(
            spec_code="OAK-48X40-15B", lumber_species="OAK",
            requires_heat_treatment_default=True)
        oak_lot = create_new_build_lot(oak_spec["id"], 5)
        assert oak_lot["heat_treat_status"] == "PENDING_HT"
        run = create_ht_run(chamber_code="CH-4", species_profile="PINE",
                            capacity_pallets=100)
        resp = api_client.assign_lot_to_run(run["id"],
                                            {"lot_id": oak_lot["id"]}, HT)
        validate_error(resp, ApiErrorId.ERR_HT_SPECIES_MISMATCH)
        assert resp.status_code == 422
        run_after = get_ht_run(run["id"])
        assert run_after["loaded_pallets"] == 0

    def test_start_empty_run_rejected(self):
        """PRD §3.5: "Starting the run moves `STAGING` to `RUNNING` and
        requires at least one assigned pallet (else `ERR_HT_EMPTY`) on top of
        the `STAGING` status (else `ERR_HT_NOT_STAGING`) and the
        chamber-exclusivity rule of §2.10 (`ERR_CHAMBER_OCCUPIED`); `started_at`
        is stamped from the logical clock."

        Design: Corner/errors/error_ht_empty_on_start
        """
        run = create_ht_run(chamber_code="CH-7", species_profile="PINE",
                            capacity_pallets=100)
        resp = api_client.start_ht_run(run["id"], HT)
        validate_error(resp, ApiErrorId.ERR_HT_EMPTY)
        assert resp.status_code == 422
