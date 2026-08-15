"""Housing: certification lifecycle, aggregate capacity over half-open windows,
the per-worker one-bed rule, occupancy conservation, and end-of-work cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_certified_unit,
    create_housing_unit,
    create_housing_unit_payload,
    end_assignment,
    get_success_data,
    move_worker_into_housing,
    record_inspection,
    set_clock,
    setup_active_order_pipeline,
    setup_two_grower_scenario,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["contractor_admin_headers"]


class TestAggregateCapacity:
    def _three_workers_and_unit(self, api):
        s = setup_active_order_pipeline(
            passports=("P0001", "P0002", "P0003"),
            requested_worker_count=3,
        )
        unit = create_certified_unit(s["grower"]["id"], name="Camp B", capacity=2)
        move_worker_into_housing(unit["id"], s["workers"]["P0001"]["id"], s["assignments"]["P0001"]["id"])
        move_worker_into_housing(unit["id"], s["workers"]["P0002"]["id"], s["assignments"]["P0002"]["id"])
        return s, unit

    def test_third_overlapping_movein_rejected(self, api):
        """PRD 3.5: "Capacity enforcement is aggregate, not pairwise: the move-in
        is rejected with `ERR_HOUSING_CAPACITY_EXCEEDED` when the number of the
        unit's `OCCUPIED` assignments overlapping the new window, plus the new
        arrival, would exceed the unit's `capacity`."
        PRD 3.5: "Two windows overlap when each begins before the other ends; pure
        adjacency — one worker's move-in landing exactly on another's move-out —
        does not count as an overlap."

        Design: Difficulty/resource_temporal_overlap/housing_half_open_interval_aggregate_capacity
        """
        s, unit = self._three_workers_and_unit(api)

        resp = api.create_housing_assignment(
            {
                "housing_unit_id": unit["id"],
                "worker_id": s["workers"]["P0003"]["id"],
                "worker_assignment_id": s["assignments"]["P0003"]["id"],
                "move_in_date": "2026-09-01",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_HOUSING_CAPACITY_EXCEEDED)

    def test_rejected_movein_leaves_occupied_count_unchanged(self, api):
        """PRD 3.5: "`occupied_count`, the number of housing assignments of the
        unit currently in `OCCUPIED` status."

        Design: Difficulty/resource_temporal_overlap/housing_half_open_interval_aggregate_capacity
        """
        s, unit = self._three_workers_and_unit(api)
        validate_error(
            api.create_housing_assignment(
                {
                    "housing_unit_id": unit["id"],
                    "worker_id": s["workers"]["P0003"]["id"],
                    "worker_assignment_id": s["assignments"]["P0003"]["id"],
                    "move_in_date": "2026-09-01",
                },
                ADMIN,
            ),
            ApiErrorId.ERR_HOUSING_CAPACITY_EXCEEDED,
        )
        current = get_success_data(api.get_housing_unit(unit["id"], ADMIN))
        assert current["occupied_count"] == 2


class TestOccupancyConservation:
    def test_movein_then_vacate_returns_occupied_count_to_zero(self, api):
        """PRD 3.5: "A successful move-in creates the assignment in `OCCUPIED`
        status with `move_out_date` null and refreshes the unit's
        `occupied_count`."
        PRD 3.5: "The stay moves to `VACATED` and the unit's `occupied_count` is
        recomputed."

        Design: Difficulty/compensating_invariant/housing_movein_vacate_pair_conserves_occupied_count
        """
        s = setup_active_order_pipeline(passports=("P0001",))
        unit = create_certified_unit(s["grower"]["id"], name="Camp A", capacity=2)
        assert get_success_data(api.get_housing_unit(unit["id"], ADMIN))["occupied_count"] == 0

        ha = move_worker_into_housing(
            unit["id"], s["workers"]["P0001"]["id"], s["assignments"]["P0001"]["id"]
        )
        assert ha["status"] == "OCCUPIED" and ha["move_out_date"] is None
        assert get_success_data(api.get_housing_unit(unit["id"], ADMIN))["occupied_count"] == 1

        validate_success(
            api.vacate_housing_assignment(ha["id"], {"move_out_date": "2026-09-05"}, ADMIN), 200
        )
        assert get_success_data(api.get_housing_unit(unit["id"], ADMIN))["occupied_count"] == 0

    def test_vacated_row_records_move_out_and_terminal_status(self, api):
        """PRD 3.5: "Vacating is the mirror action: a `ContractorAdmin` ends an
        `OCCUPIED` stay — anything else is rejected with
        `ERR_HOUSING_ASSIGNMENT_INVALID_STATE` — by supplying a `move_out_date`,
        which must not fall before the `move_in_date` (else
        `ERR_INVALID_DATE_RANGE`). The stay moves to `VACATED` and the unit's
        `occupied_count` is recomputed."

        Design: Difficulty/compensating_invariant/housing_movein_vacate_pair_conserves_occupied_count
        """
        s = setup_active_order_pipeline(passports=("P0001",))
        unit = create_certified_unit(s["grower"]["id"], name="Camp A", capacity=2)
        ha = move_worker_into_housing(
            unit["id"], s["workers"]["P0001"]["id"], s["assignments"]["P0001"]["id"]
        )

        vacated = validate_success(
            api.vacate_housing_assignment(ha["id"], {"move_out_date": "2026-09-05"}, ADMIN), 200
        )
        assert vacated["status"] == "VACATED"
        assert vacated["move_out_date"] == "2026-09-05"
        assert get_success_data(api.get_housing_unit(unit["id"], ADMIN))["occupied_count"] == 0


class TestLifecycleAndGuards:
    def test_housing_lifecycle_and_guard_battery(self, api):
        """PRD 3.5: "First, the unit must be `CERTIFIED` at move-in and the clock
        date must not be past its `certification_valid_until`; otherwise the move
        is rejected with `ERR_HOUSING_NOT_CERTIFIED`."
        PRD 3.5: "A `ContractorAdmin` may expire a unit, but only while its
        `inspection_status` is `CERTIFIED` (else `ERR_HOUSING_UNIT_INVALID_STATE`)
        and only once the clock date is strictly later than
        `certification_valid_until` — while the clock date is still on or before
        that date, the attempt is rejected with
        `ERR_HOUSING_CERTIFICATION_STILL_VALID`."
        PRD 3.5: "Independently, a worker may occupy only one bed: if the same
        worker already holds any other `OCCUPIED` housing assignment, in any unit,
        whose window overlaps the new one, the move-in is rejected with
        `ERR_WORKER_HOUSING_OVERLAP`."
        PRD 3.5: "The result flips the unit's `inspection_status`: a `PASS`
        recorded against an `UNINSPECTED`, `FAILED`, or `EXPIRED` unit moves it to
        `CERTIFIED` and sets `certified_on` to the inspection's `inspected_on` —
        the latter two being the recertification legs of the cycle — while a `FAIL`
        moves an `UNINSPECTED` or `CERTIFIED` unit to `FAILED`, clearing
        `certified_on` to null when the unit had been certified."

        Design: Corner/errors/housing_lifecycle_and_guard_battery
        """
        s = setup_active_order_pipeline(passports=("P0001",))
        g1 = s["grower"]["id"]
        wa = s["workers"]["P0001"]
        asg = s["assignments"]["P0001"]

        u_un = create_housing_unit(g1, name="U-UN", capacity=2)
        u_ok = create_certified_unit(g1, name="U-OK", capacity=2, inspected_on="2026-08-01")
        u_fail = create_housing_unit(g1, name="U-FAIL", capacity=2)
        record_inspection(u_fail["id"], "2026-08-01", "FAIL", deficiency_codes=["SANITATION"])
        u_exp = create_certified_unit(g1, name="U-EXP", capacity=2, inspected_on="2026-08-01")

        # Move-in to an UNINSPECTED unit.
        resp = api.create_housing_assignment(
            {"housing_unit_id": u_un["id"], "worker_id": wa["id"],
             "worker_assignment_id": asg["id"], "move_in_date": "2026-09-01"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_HOUSING_NOT_CERTIFIED)

        # Expire while still inside validity (certified 2026-08-01 -> until 2027-08-01).
        resp = api.expire_housing_unit(u_ok["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_HOUSING_CERTIFICATION_STILL_VALID)

        # Expire requires CERTIFIED; U-FAIL is FAILED.
        resp = api.expire_housing_unit(u_fail["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_HOUSING_UNIT_INVALID_STATE)

        # Successful move-in, then the same worker into another unit: one bed rule.
        ha1 = move_worker_into_housing(u_ok["id"], wa["id"], asg["id"])
        resp = api.create_housing_assignment(
            {"housing_unit_id": u_exp["id"], "worker_id": wa["id"],
             "worker_assignment_id": asg["id"], "move_in_date": "2026-09-01"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WORKER_HOUSING_OVERLAP)

        # Double vacate: the second is rejected; move_out stays 2026-09-05.
        validate_success(api.vacate_housing_assignment(ha1["id"], {"move_out_date": "2026-09-05"}, ADMIN), 200)
        resp = api.vacate_housing_assignment(ha1["id"], {"move_out_date": "2026-09-06"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_HOUSING_ASSIGNMENT_INVALID_STATE)
        assert get_success_data(api.get_housing_assignment(ha1["id"], ADMIN))["move_out_date"] == "2026-09-05"

        # Past certification_valid_until (2027-08-01): expire succeeds.
        set_clock("2027-08-02T00:00:00Z")
        expired = validate_success(api.expire_housing_unit(u_exp["id"], ADMIN), 200)
        assert expired["inspection_status"] == "EXPIRED"

        # Recertification leg: EXPIRED -> CERTIFIED via a fresh PASS.
        record_inspection(u_exp["id"], "2027-08-02", "PASS")
        recertified = get_success_data(api.get_housing_unit(u_exp["id"], ADMIN))
        assert recertified["inspection_status"] == "CERTIFIED"
        assert recertified["certified_on"] == "2027-08-02"
        # certified_on + 365 days (2028 is a leap year, so this lands on 2028-08-01).
        assert recertified["certification_valid_until"] == "2028-08-01"

        # Cure leg: FAILED -> CERTIFIED via a fresh PASS.
        record_inspection(u_fail["id"], "2027-08-02", "PASS")
        assert get_success_data(api.get_housing_unit(u_fail["id"], ADMIN))["inspection_status"] == "CERTIFIED"

    def test_assignment_end_vacates_housing_conditional_cascade(self, api):
        """PRD 3.6: "Both cascade identically: every `OCCUPIED` housing stay of the
        assignment is vacated with `move_out_date` set to `ended_on`, the wage
        reconciliation is recomputed (it stays `OPEN`, its basis window now
        anchored at `ended_on`), and the worker moves to `DEPARTED` — but only when
        the worker holds no other `PLANNED` or `ACTIVE` assignment."
        PRD 3.5: "Vacating also happens automatically: whenever a worker assignment
        reaches `COMPLETED`, `TERMINATED`, or `TRANSFERRED_OUT`, every `OCCUPIED`
        housing assignment tied to it is vacated with `move_out_date` set to the
        assignment's `ended_on`."

        Design: Corner/state_machines/assignment_end_vacates_housing_conditional_cascade
        """
        s = setup_active_order_pipeline(passports=("P0001",))
        unit = create_certified_unit(s["grower"]["id"], name="Camp A", capacity=2)
        ha = move_worker_into_housing(
            unit["id"], s["workers"]["P0001"]["id"], s["assignments"]["P0001"]["id"]
        )

        set_clock("2026-09-05T00:00:00Z")
        ended = end_assignment(s["assignments"]["P0001"]["id"], "COMPLETED")
        assert ended["status"] == "COMPLETED"
        assert ended["end_reason"] == "COMPLETED"
        assert ended["ended_on"] == "2026-09-05"
        assert ended["guarantee_eligible"] is True

        ha_now = get_success_data(api.get_housing_assignment(ha["id"], ADMIN))
        assert ha_now["status"] == "VACATED"
        assert ha_now["move_out_date"] == "2026-09-05"
        assert get_success_data(api.get_housing_unit(unit["id"], ADMIN))["occupied_count"] == 0
        assert get_success_data(api.get_worker(s["workers"]["P0001"]["id"], ADMIN))["status"] == "DEPARTED"


class TestReferentialBeforeCapacity:
    def _full_unit_and_cross_grower_assignment(self, api):
        """G1's unit U1 (capacity 1) CERTIFIED and full with W_A; W_C WORKING on
        G2's J2 — a move-in would violate BOTH grower coherence and capacity."""
        s = setup_two_grower_scenario(start_j2_assignment=True)
        unit = create_certified_unit(s["g1"]["id"], name="Camp A", capacity=1)
        move_worker_into_housing(unit["id"], s["wa"]["id"], s["asg_a"]["id"])
        return s, unit

    def test_cross_grower_movein_reports_referential_error_not_capacity(self, api):
        """PRD 2.9: "Eighth, cross-entity referential coherence is verified —
        grower matching, transfer-grower distinctness, worker-to-order and
        worker-to-petition linkage (`ERR_GROWER_MISMATCH`,
        `ERR_SAME_GROWER_TRANSFER`, `ERR_WORKER_ORDER_MISMATCH`,
        `ERR_WORKER_NOT_ON_PETITION`). Ninth, uniqueness, capacity, and
        guarded-transition constraints run (duplicates, ceilings, quotas, and the
        transition guards such as `ERR_UNDECIDED_APPLICATIONS_REMAIN`,
        `ERR_OPEN_ASSIGNMENTS_REMAIN`, `ERR_UNFINALIZED_RECONCILIATIONS_REMAIN`,
        and `ERR_OPEN_PETITIONS_EXIST`)."
        PRD 3.5: "Second, the referenced worker assignment must be `ACTIVE` and the
        job order it belongs to must belong to the same grower that owns the unit;
        a cross-grower placement is rejected with `ERR_GROWER_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/housing_referential_vs_capacity_priority
        """
        s, unit = self._full_unit_and_cross_grower_assignment(api)

        resp = api.create_housing_assignment(
            {"housing_unit_id": unit["id"], "worker_id": s["wh"]["id"],
             "worker_assignment_id": s["asg_c"]["id"], "move_in_date": "2026-09-15"},
            ADMIN,
        )
        # Referential coherence (eighth) is reported before capacity (ninth).
        validate_error(resp, ApiErrorId.ERR_GROWER_MISMATCH)

    def test_rejected_cross_grower_movein_leaves_occupancy_unchanged(self, api):
        """PRD 3.5: "`occupied_count`, the number of housing assignments of the
        unit currently in `OCCUPIED` status."
        PRD 2.9: "When a request would violate several rules at once, the server
        evaluates checks in a fixed priority order and reports the earliest
        failure."

        Design: Difficulty/priority_pair_validation_conflict/housing_referential_vs_capacity_priority
        """
        s, unit = self._full_unit_and_cross_grower_assignment(api)
        validate_error(
            api.create_housing_assignment(
                {"housing_unit_id": unit["id"], "worker_id": s["wh"]["id"],
                 "worker_assignment_id": s["asg_c"]["id"], "move_in_date": "2026-09-15"},
                ADMIN,
            ),
            ApiErrorId.ERR_GROWER_MISMATCH,
        )
        assert get_success_data(api.get_housing_unit(unit["id"], ADMIN))["occupied_count"] == 1
