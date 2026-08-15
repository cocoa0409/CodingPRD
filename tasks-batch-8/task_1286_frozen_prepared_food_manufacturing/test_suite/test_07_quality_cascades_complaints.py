"""CCP fail cascade and complaint contagion (PRD §3.6, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_film_lot,
    create_packaging_line,
    file_and_resolve_valid_complaint,
    file_complaint,
    get_film_lot,
    get_lot,
    investigate_complaint,
    make_qa_manager_headers,
    pin_clock,
    record_ccp,
    resolve_complaint,
    schedule_run,
    setup_contagion_scenario,
    setup_frozen_batch,
    setup_released_lot,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["production_planner_headers"]
QA_TECH = TEST_USERS["qa_technician_headers"]
QA_MGR = TEST_USERS["qa_manager_headers"]


class TestCcpFailCascade:
    def _frozen_batch_with_scheduled_run(self):
        """FROZEN batch with one SCHEDULED run (6000 units -> 2671 m reserved)."""
        env = setup_frozen_batch()
        env["line"] = create_packaging_line()
        env["film"] = create_film_lot()
        env["run"] = schedule_run(
            env["line"]["id"], env["batch"]["id"], env["film"]["id"],
            planned_start="2026-08-03T08:00:00Z", units_planned=6000,
        )
        assert env["run"]["reserved_film_m"] == 2671
        return env

    def test_ccp_fail_holds_batch(self, api):
        """PRD §3.6: "When a `FAIL` is recorded while the batch is `FROZEN` or
        `PACKED`, the batch immediately moves to `ON_HOLD` with
        `hold_origin_state` recording the state it occupied and `hold_reason` set
        to the failure marker formed by prefixing the check type — a marker of the
        form CCP-fail colon check-type that later governs the resume gate of §3.3."
        PRD §3.6: "The check's `result` is computed, never supplied: `PASS` when
        the test piece was detected, `FAIL` otherwise."

        Design: Difficulty/transitive_cascade/ccp_fail_cascade_depth3
        """
        pin_clock()
        env = self._frozen_batch_with_scheduled_run()
        check = record_ccp(env["batch"]["id"], "METAL_DETECTOR", False, "qa-tech-1")
        assert check["result"] == "FAIL", "result is computed from test_piece_detected"

        batch = validate_success(api.get_batch(env["batch"]["id"], PLANNER))
        assert batch["status"] == "ON_HOLD", (
            f"hop 1: the failed check holds its batch, got {batch['status']}"
        )
        assert batch["hold_origin_state"] == "FROZEN"
        assert batch["hold_reason"] == "CCP_FAIL:METAL_DETECTOR", (
            f"hold_reason carries the CCP failure marker, got {batch['hold_reason']}"
        )

    def test_ccp_fail_cancels_runs_and_releases_film(self, api):
        """PRD §3.6: "Every `SCHEDULED` line run of the batch transitions to
        `CANCELLED` in the same request, and each cancelled run releases its film
        reservation, dropping its film lot's `meters_reserved` by that run's
        `reserved_film_m`; the batch's `version` increments."
        PRD §3.5: "at every moment, the meters reserved plus the meters consumed
        plus the meters available equal the meters received."

        Design: Difficulty/transitive_cascade/ccp_fail_cascade_depth3
        """
        pin_clock()
        env = self._frozen_batch_with_scheduled_run()
        mid = get_film_lot(env["film"]["id"])
        assert mid["meters_reserved"] == 2671 and mid["meters_available"] == 7329

        record_ccp(env["batch"]["id"], "METAL_DETECTOR", False, "qa-tech-1")

        run = validate_success(api.get_line_run(env["run"]["id"], PLANNER))
        assert run["status"] == "CANCELLED", (
            f"hop 2: the hold cancels the batch's SCHEDULED run, got {run['status']}"
        )
        lot = get_film_lot(env["film"]["id"])
        assert lot["meters_reserved"] == 0, (
            f"hop 3: the cancellation releases the reservation, got {lot['meters_reserved']}"
        )
        assert lot["meters_available"] == 10000


class TestComplaintLifecycle:
    def test_complaint_resolve_twice_rejected(self, api):
        """PRD §3.8: "Resolving a complaint that is still `OPEN`, or one already
        resolved, is rejected with `ERR_COMPLAINT_STATE`, and a resolved state —
        `RESOLVED_VALID` or `RESOLVED_INVALID` — is terminal."
        PRD §3.8: "First, the lot's `valid_complaint_count` grows by one."

        Design: Corner/state_machines/complaint_resolve_twice_rejected
        """
        pin_clock()
        env = setup_released_lot()
        complaint = file_and_resolve_valid_complaint(
            env["lot"]["id"], units_affected=1, complaint_type="TEXTURE"
        )
        assert complaint["status"] == "RESOLVED_VALID"

        resp = api.resolve_complaint(
            complaint["id"], {"verdict": "INVALID"}, make_qa_manager_headers("qa-mgr-9")
        )
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_STATE, expected_status=409)
        lot = get_lot(env["lot"]["id"])
        assert lot["valid_complaint_count"] == 1, (
            "a rejected second resolve must not run the contagion increment again"
        )

    def test_complaint_units_above_produced_rejected(self, api):
        """PRD §3.8: "`units_affected` may not exceed the lot's `cases_produced`,
        an aggregate check that fails with `ERR_COMPLAINT_UNITS_INVALID`
        (HTTP 422)."
        PRD §2.4: "12. **Aggregate fiscal check.** A complaint's `units_affected`
        does not exceed the complained lot's `cases_produced`; otherwise
        `ERR_COMPLAINT_UNITS_INVALID` (HTTP 422)."

        Design: Corner/validations/complaint_units_above_produced_rejected
        """
        pin_clock()
        env = setup_released_lot()  # 6000 RETAIL units -> 500 cases
        assert env["lot"]["cases_produced"] == 500
        resp = api.create_complaint(
            {
                "lot_id": env["lot"]["id"],
                "complaint_type": "FREEZER_BURN",
                "units_affected": 501,
            },
            QA_TECH,
        )
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_UNITS_INVALID, expected_status=422)

    def test_segregation_complaint_resolve_same_user_rejected(self, api):
        """PRD §3.8: "Segregation binds here as everywhere: the resolver's
        `X-User-ID` must differ from the complaint's `reported_by_user_id`,
        otherwise `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.8: "Resolution belongs to a `QAManager`, who supplies a `verdict`
        of `VALID` or `INVALID` and an optional `notes`."

        Design: Corner/rbac/segregation_complaint_resolve_same_user_rejected
        """
        pin_clock()
        env = setup_released_lot()
        complaint = file_complaint(
            env["lot"]["id"], units_affected=2, reporter="shared-user"
        )
        investigate_complaint(complaint["id"], "qa-tech-2")
        # The reporter attempts to resolve their own complaint (as QAManager).
        resp = api.resolve_complaint(
            complaint["id"], {"verdict": "VALID"}, make_qa_manager_headers("shared-user")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        resolved = validate_success(
            api.resolve_complaint(
                complaint["id"], {"verdict": "VALID"}, make_qa_manager_headers("qa-mgr-9")
            ),
            expected_status=200,
        )
        assert resolved["status"] == "RESOLVED_VALID"


class TestComplaintCountBoundary:
    def test_two_valid_complaints_leave_lot_released(self, api):
        """PRD §3.8: "Second, when that count reaches at least three and the lot is
        currently `RELEASED`, the lot moves to `QUARANTINED` and its order's
        `releasable_cases` falls by the lot's `cases_on_hand` — the threshold is
        inclusive, so exactly the third valid complaint triggers the quarantine."

        Design: Difficulty/boundary_precision_check/complaint_count_exactly_three_quarantines
        """
        pin_clock()
        env = setup_released_lot(
            order_over={"units_planned": 7200},
            batch_units=7200,
            cell_over={"capacity_kg": 2500},
            cycle_over={"load_kg": 1900},
            run_over={"units_planned": 7200},
            complete_run_over={"units_packed": 7200, "film_meters_consumed": 3205},
        )
        # Nothing was shipped, so the recipe-rate path stays inert
        # ("When shipped volume is positive ..."); only the count path applies.
        file_and_resolve_valid_complaint(env["lot"]["id"], units_affected=1)
        file_and_resolve_valid_complaint(
            env["lot"]["id"], units_affected=1, complaint_type="TEXTURE"
        )
        lot = get_lot(env["lot"]["id"])
        assert lot["valid_complaint_count"] == 2
        assert lot["release_status"] == "RELEASED", (
            f"two valid complaints are below the threshold of three, got {lot['release_status']}"
        )

    def test_third_valid_complaint_quarantines_lot(self, api):
        """PRD §3.8: "Second, when that count reaches at least three and the lot is
        currently `RELEASED`, the lot moves to `QUARANTINED` and its order's
        `releasable_cases` falls by the lot's `cases_on_hand` — the threshold is
        inclusive, so exactly the third valid complaint triggers the quarantine."

        Design: Difficulty/boundary_precision_check/complaint_count_exactly_three_quarantines
        """
        pin_clock()
        env = setup_released_lot(
            order_over={"units_planned": 7200},
            batch_units=7200,
            cell_over={"capacity_kg": 2500},
            cycle_over={"load_kg": 1900},
            run_over={"units_planned": 7200},
            complete_run_over={"units_packed": 7200, "film_meters_consumed": 3205},
        )
        file_and_resolve_valid_complaint(env["lot"]["id"], units_affected=1)
        file_and_resolve_valid_complaint(
            env["lot"]["id"], units_affected=1, complaint_type="TEXTURE"
        )
        file_and_resolve_valid_complaint(
            env["lot"]["id"], units_affected=1, complaint_type="OFF_ODOR"
        )
        lot = get_lot(env["lot"]["id"])
        assert lot["valid_complaint_count"] == 3
        assert lot["release_status"] == "QUARANTINED", (
            f"the threshold is inclusive: exactly the third valid complaint "
            f"quarantines, got {lot['release_status']}"
        )


class TestComplaintContagionCascade:
    def test_third_complaint_quarantines_origin_lot(self, api):
        """PRD §3.8: "First, the lot's `valid_complaint_count` grows by one.
        Second, when that count reaches at least three and the lot is currently
        `RELEASED`, the lot moves to `QUARANTINED` and its order's
        `releasable_cases` falls by the lot's `cases_on_hand` — the threshold is
        inclusive, so exactly the third valid complaint triggers the quarantine."

        Design: Difficulty/transitive_cascade/complaint_valid_contagion_cascade
        """
        env = setup_contagion_scenario()
        assert env["lot1"]["valid_complaint_count"] == 2
        file_and_resolve_valid_complaint(env["lot1"]["id"], units_affected=1)
        lot1 = get_lot(env["lot1"]["id"])
        assert lot1["valid_complaint_count"] == 3
        assert lot1["release_status"] == "QUARANTINED", (
            f"hop 1+2: the third valid complaint quarantines its lot, got {lot1['release_status']}"
        )

    def test_recipe_rate_contagion_quarantines_sibling_lot(self, api):
        """PRD §3.8: "When shipped volume is positive and the ratio of affected to
        shipped reaches or exceeds 0.005, compared in exact rational arithmetic
        with no floating-point rounding so that a ratio landing exactly on the
        threshold triggers, every lot of that recipe currently in `RELEASED`
        status moves to `QUARANTINED`, each one recomputing its own order's
        `releasable_cases` as it falls."

        Design: Difficulty/transitive_cascade/complaint_valid_contagion_cascade
        """
        env = setup_contagion_scenario()
        file_and_resolve_valid_complaint(env["lot1"]["id"], units_affected=1)
        # affected = 2 + 2 + 1 = 5 cases; shipped = 500 + 500 = 1000 cases;
        # 5/1000 = 0.005 lands exactly on the threshold and triggers.
        lot2 = get_lot(env["lot2"]["id"])
        assert lot2["release_status"] == "QUARANTINED", (
            f"hop 3: the recipe-rate path quarantines the sibling RELEASED lot, "
            f"got {lot2['release_status']}"
        )
        lot1 = get_lot(env["lot1"]["id"])
        assert lot1["release_status"] == "QUARANTINED"
