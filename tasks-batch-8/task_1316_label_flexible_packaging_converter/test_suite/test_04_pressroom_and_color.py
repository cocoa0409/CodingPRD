"""Pressroom execution: press occupancy, Delta-E measurement and judgment,
and the complete-press color gate."""
from test_helpers import (
    EST,
    PRESS_OP,
    QM,
    api_client,
    approve_job,
    assert_color_measurement,
    create_job_for,
    create_press,
    current_artwork_version,
    get_job,
    job_chain,
    judge_measurement,
    pass_color_gate,
    record_measurement,
    release_job,
    run_press_cycle,
    setup_plant,
    start_press,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPressOccupancy:

    def test_start_press_from_quoted_rejected(self):
        """PRD §3.6: "A `PressOperator` takes a released job onto press; the job
        must be `RELEASED` (`ERR_JOB_NOT_RELEASED`), and the press must be free
        — one job at a time per press, so if another job is currently
        `ON_PRESS` on the referenced press the attempt is rejected with
        `ERR_PRESS_OCCUPIED`. The job is now `ON_PRESS`."

        Design: Corner/state_machines/start_press_from_quoted_rejected
        """
        chain = job_chain(stop_at="QUOTED", account_name="Skip Co",
                          artwork_code="AW-SK", substrate_code="SK-1",
                          recipe_code="INK-SK", die_code="D-SK",
                          press_code="P-SK", quantity_ordered=2000)
        resp = api_client.start_press(chain["job"]["id"], PRESS_OP)
        validate_error(resp, "ERR_JOB_NOT_RELEASED", expected_status=409)

    def test_second_job_on_occupied_press_rejected(self):
        """PRD §3.6: "A `PressOperator` takes a released job onto press; the job
        must be `RELEASED` (`ERR_JOB_NOT_RELEASED`), and the press must be free
        — one job at a time per press, so if another job is currently
        `ON_PRESS` on the referenced press the attempt is rejected with
        `ERR_PRESS_OCCUPIED`. The job is now `ON_PRESS`."

        Design: Difficulty/cross_entity_state_dependency/start_press_depends_on_press_occupancy
        """
        plant = setup_plant(account_name="CrossDep B", artwork_code="AW-14",
                            substrate_code="BOPP-38", recipe_code="INK-14",
                            die_code="D-14", press_code="P-14")
        j1 = create_job_for(plant, quantity_ordered=2000, repeat_length_mm=76)
        j2 = create_job_for(plant, quantity_ordered=2000, repeat_length_mm=76)
        for job in (j1, j2):
            approve_job(job["id"])
            release_job(job["id"], current_artwork_version(plant))
        started = start_press(j1["id"])
        assert started["status"] == "ON_PRESS"

        resp = api_client.start_press(j2["id"], PRESS_OP)
        validate_error(resp, "ERR_PRESS_OCCUPIED", expected_status=409)
        assert get_job(j2["id"])["status"] == "RELEASED", \
            "rejected start-press must leave the second job RELEASED"

    def test_job_on_other_press_not_blocked(self):
        """PRD §3.6: "A `PressOperator` takes a released job onto press; the job
        must be `RELEASED` (`ERR_JOB_NOT_RELEASED`), and the press must be free
        — one job at a time per press, so if another job is currently
        `ON_PRESS` on the referenced press the attempt is rejected with
        `ERR_PRESS_OCCUPIED`. The job is now `ON_PRESS`."

        Design: Difficulty/cross_entity_state_dependency/start_press_depends_on_press_occupancy
        """
        plant = setup_plant(account_name="CrossDep B2", artwork_code="AW-14X",
                            substrate_code="BOPP-38X", recipe_code="INK-14X",
                            die_code="D-14X", press_code="P-14X")
        other_press = create_press(press_code="P-14Y", station_count=4,
                                   setup_waste_ft=300,
                                   run_waste_pct_numerator=5)
        j1 = create_job_for(plant, quantity_ordered=2000, repeat_length_mm=76)
        plant_other = dict(plant)
        plant_other["press"] = other_press
        j2 = create_job_for(plant_other, quantity_ordered=2000,
                            repeat_length_mm=76)
        approve_job(j1["id"])
        release_job(j1["id"], current_artwork_version(plant))
        approve_job(j2["id"])
        release_job(j2["id"], current_artwork_version(plant))
        start_press(j1["id"])

        started2 = start_press(j2["id"])
        # Occupancy is per-press: the job on the other press starts cleanly.
        assert started2["status"] == "ON_PRESS"

    def test_occupation_blocks_until_complete_press(self):
        """PRD §3.6: "A `PressOperator` takes a released job onto press; the job
        must be `RELEASED` (`ERR_JOB_NOT_RELEASED`), and the press must be free
        — one job at a time per press, so if another job is currently
        `ON_PRESS` on the referenced press the attempt is rejected with
        `ERR_PRESS_OCCUPIED`. The job is now `ON_PRESS`."
        PRD §3.6: "Completion records the good quantity on the job, where it
        later drives the invoice, and moves the job `ON_PRESS` → `PRINTED`."

        Design: Difficulty/resource_temporal_overlap/press_singleton_occupation_until_terminal
        """
        plant = setup_plant(account_name="Overlap A", artwork_code="AW-15",
                            substrate_code="BOPP-39", recipe_code="INK-15",
                            die_code="D-15", press_code="P-15")
        j1 = create_job_for(plant, quantity_ordered=2000, repeat_length_mm=76)
        j2 = create_job_for(plant, quantity_ordered=2000, repeat_length_mm=76)
        for job in (j1, j2):
            approve_job(job["id"])
            release_job(job["id"], current_artwork_version(plant))
        start_press(j1["id"])

        blocked = api_client.start_press(j2["id"], PRESS_OP)
        validate_error(blocked, "ERR_PRESS_OCCUPIED", expected_status=409)
        assert get_job(j2["id"])["status"] == "RELEASED"

    def test_occupation_lifts_at_complete_press(self):
        """PRD §3.6: "A `PressOperator` takes a released job onto press; the job
        must be `RELEASED` (`ERR_JOB_NOT_RELEASED`), and the press must be free
        — one job at a time per press, so if another job is currently
        `ON_PRESS` on the referenced press the attempt is rejected with
        `ERR_PRESS_OCCUPIED`. The job is now `ON_PRESS`."
        PRD §3.6: "Completion records the good quantity on the job, where it
        later drives the invoice, and moves the job `ON_PRESS` → `PRINTED`."

        Design: Difficulty/resource_temporal_overlap/press_singleton_occupation_until_terminal
        """
        plant = setup_plant(account_name="Overlap A2", artwork_code="AW-15B",
                            substrate_code="BOPP-39B", recipe_code="INK-15B",
                            die_code="D-15B", press_code="P-15B")
        j1 = create_job_for(plant, quantity_ordered=2000, repeat_length_mm=76)
        j2 = create_job_for(plant, quantity_ordered=2000, repeat_length_mm=76)
        for job in (j1, j2):
            approve_job(job["id"])
            release_job(job["id"], current_artwork_version(plant))
        start_press(j1["id"])
        validate_error(api_client.start_press(j2["id"], PRESS_OP),
                       "ERR_PRESS_OCCUPIED", expected_status=409)

        run_press_cycle(j1["id"], good_quantity_produced=2000)
        assert get_job(j1["id"])["status"] == "PRINTED"

        started2 = start_press(j2["id"])
        assert started2["status"] == "ON_PRESS", \
            "the occupation window ends when the first job leaves ON_PRESS"

    def test_occupancy_invariant_single_cycle(self):
        """PRD §3.6: "A `PressOperator` takes a released job onto press; the job
        must be `RELEASED` (`ERR_JOB_NOT_RELEASED`), and the press must be free
        — one job at a time per press, so if another job is currently
        `ON_PRESS` on the referenced press the attempt is rejected with
        `ERR_PRESS_OCCUPIED`. The job is now `ON_PRESS`."

        Design: Difficulty/compensating_invariant/press_occupancy_conserved_over_start_complete_cycle
        """
        plant = setup_plant(account_name="Invariant B", artwork_code="AW-18",
                            substrate_code="BOPP-42", recipe_code="INK-18",
                            die_code="D-18", press_code="P-18")
        j1 = create_job_for(plant, quantity_ordered=2000, repeat_length_mm=76)
        j2 = create_job_for(plant, quantity_ordered=2000, repeat_length_mm=76)
        for job in (j1, j2):
            approve_job(job["id"])
            release_job(job["id"], current_artwork_version(plant))

        start_press(j1["id"])
        run_press_cycle(j1["id"], good_quantity_produced=2000)
        started2 = start_press(j2["id"])
        assert started2["status"] == "ON_PRESS", (
            "start→complete on the first job returns the press's occupation "
            "count to zero, so the second job may start")

    def test_occupancy_invariant_repeated_cycles(self):
        """PRD §3.6: "A `PressOperator` takes a released job onto press; the job
        must be `RELEASED` (`ERR_JOB_NOT_RELEASED`), and the press must be free
        — one job at a time per press, so if another job is currently
        `ON_PRESS` on the referenced press the attempt is rejected with
        `ERR_PRESS_OCCUPIED`. The job is now `ON_PRESS`."

        Design: Difficulty/compensating_invariant/press_occupancy_conserved_over_start_complete_cycle
        """
        plant = setup_plant(account_name="Invariant B2", artwork_code="AW-18R",
                            substrate_code="BOPP-42R", recipe_code="INK-18R",
                            die_code="D-18R", press_code="P-18R")
        jobs = [create_job_for(plant, quantity_ordered=2000,
                               repeat_length_mm=76) for _ in range(3)]
        for job in jobs:
            approve_job(job["id"])
            release_job(job["id"], current_artwork_version(plant))

        # Three consecutive start→complete cycles on the same press: the
        # 0-or-1 occupation invariant holds across every repetition.
        for job in jobs:
            started = start_press(job["id"])
            assert started["status"] == "ON_PRESS"
            run_press_cycle(job["id"], good_quantity_produced=2000)
            assert get_job(job["id"])["status"] == "PRINTED"


class TestColorMeasurement:

    def test_measurement_record_while_released_rejected(self):
        """PRD §3.6: "Recording requires the parent job to be `ON_PRESS`
        (`ERR_JOB_NOT_ON_PRESS`), and each measurement is born in `PENDING`,
        tied to its job by the system-recorded `job_id`."

        Design: Corner/state_machines/measurement_record_while_released_rejected
        """
        chain = job_chain(stop_at="RELEASED", account_name="Meas Co",
                          artwork_code="AW-M", substrate_code="M-1",
                          recipe_code="INK-M", die_code="D-M",
                          press_code="P-M", quantity_ordered=2000)
        resp = api_client.record_color_measurement(
            chain["job"]["id"], {"station_no": 1, "delta_e": 1.0}, PRESS_OP)
        validate_error(resp, "ERR_JOB_NOT_ON_PRESS", expected_status=409)

    def test_delta_e_exactly_two_passes(self):
        """PRD §3.6: "Passing a measurement requires its `delta_e` to be at
        most 2.0; an attempt to judge `PASS` with a higher reading is rejected
        with `ERR_DELTA_E_EXCEEDS_LIMIT`."
        PRD §2.7: "Color error is recorded as a decimal Delta-E 2000 value and
        judged against a pass limit of 2.0."

        Design: Difficulty/boundary_precision_check/delta_e_exactly_two_passes
        """
        chain = job_chain(stop_at="ON_PRESS", account_name="Boundary Co",
                          artwork_code="AW-11", substrate_code="BOPP-35",
                          recipe_code="INK-11", die_code="D-11",
                          press_code="P-11", quantity_ordered=2000)
        job_id = chain["job"]["id"]
        m_edge = record_measurement(job_id, station_no=1, delta_e=2.0)
        judged = judge_measurement(job_id, m_edge["id"], "PASS")
        assert judged["verdict"] == "PASS", \
            "delta_e == 2.0 sits at the inclusive pass boundary"

    def test_delta_e_above_two_rejected_and_stays_pending(self):
        """PRD §3.6: "Passing a measurement requires its `delta_e` to be at
        most 2.0; an attempt to judge `PASS` with a higher reading is rejected
        with `ERR_DELTA_E_EXCEEDS_LIMIT`."
        PRD §2.7: "Color error is recorded as a decimal Delta-E 2000 value and
        judged against a pass limit of 2.0."

        Design: Difficulty/boundary_precision_check/delta_e_exactly_two_passes
        """
        chain = job_chain(stop_at="ON_PRESS", account_name="Boundary Co 2",
                          artwork_code="AW-11B", substrate_code="BOPP-35B",
                          recipe_code="INK-11B", die_code="D-11B",
                          press_code="P-11B", quantity_ordered=2000)
        job_id = chain["job"]["id"]
        m_over = record_measurement(job_id, station_no=2, delta_e=2.01)
        resp = api_client.judge_color_measurement(
            job_id, m_over["id"], {"verdict": "PASS"}, QM)
        validate_error(resp, "ERR_DELTA_E_EXCEEDS_LIMIT", expected_status=422)

        rows, _ = validate_paginated(
            api_client.list_color_measurements(job_id, QM))
        row = next(r for r in rows if r["id"] == m_over["id"])
        assert row["verdict"] == "PENDING", \
            "rejected PASS judgment must leave the measurement PENDING"

    def test_measurement_double_judge_rejected(self):
        """PRD §3.6: "Either judgment requires the measurement to still be
        `PENDING` (`ERR_MEASUREMENT_ALREADY_JUDGED`) and the parent job to be
        `ON_PRESS` (`ERR_JOB_NOT_ON_PRESS`). Judging increments the
        measurement's `version`, and `PASS` and `FAIL` are both terminal
        verdicts."

        Design: Corner/state_machines/measurement_double_judge_rejected
        """
        chain = job_chain(stop_at="ON_PRESS", account_name="Judge Co",
                          artwork_code="AW-J", substrate_code="J-1",
                          recipe_code="INK-J", die_code="D-J",
                          press_code="P-J", quantity_ordered=2000)
        job_id = chain["job"]["id"]
        m = record_measurement(job_id, station_no=1, delta_e=1.1)
        judged = judge_measurement(job_id, m["id"], "PASS")
        assert judged["verdict"] == "PASS"

        resp = api_client.judge_color_measurement(
            job_id, m["id"], {"verdict": "FAIL"}, QM)
        validate_error(resp, "ERR_MEASUREMENT_ALREADY_JUDGED",
                       expected_status=409)

        rows, _ = validate_paginated(
            api_client.list_color_measurements(job_id, QM))
        row = next(r for r in rows if r["id"] == m["id"])
        assert row["verdict"] == "PASS", "judged verdict is immutable"

    def test_color_measurement_fail_then_remeasure_same_station(self):
        """PRD §3.6: "A `FAIL` verdict does not block the press. The operator
        may record a replacement measurement for the same station, which simply
        appends a new `PENDING` row alongside the old one — the failed row
        stays `FAIL` and never re-opens; color history is revision-by-append
        rather than overwrite."
        PRD §3.6: "Completing the press run is the fork where quality gates the
        schedule. The `PressOperator` supplies `good_quantity_produced`, which
        must be present and greater than zero (`ERR_INVALID_GOOD_QTY`), and
        every color measurement on record for the job must carry the verdict
        `PASS` — with the further requirement that at least one measurement
        exists, since an empty measurement log proves nothing
        (`ERR_COLOR_NOT_APPROVED`). Completion records the good quantity on the
        job, where it later drives the invoice, and moves the job `ON_PRESS` →
        `PRINTED`."

        Design: Corner/state_machines/color_measurement_fail_then_remeasure_same_station
        """
        chain = job_chain(stop_at="ON_PRESS", account_name="Remeasure Co",
                          artwork_code="AW-RM", substrate_code="RM-1",
                          recipe_code="INK-RM", die_code="D-RM",
                          press_code="P-RM", quantity_ordered=2000)
        job_id = chain["job"]["id"]
        m1 = record_measurement(job_id, station_no=1, delta_e=3.7)
        judged1 = judge_measurement(job_id, m1["id"], "FAIL")
        assert judged1["verdict"] == "FAIL"

        m2 = record_measurement(job_id, station_no=1, delta_e=1.3)
        assert_color_measurement(m2)
        assert m2["verdict"] == "PENDING"
        judged2 = judge_measurement(job_id, m2["id"], "PASS")
        assert judged2["verdict"] == "PASS"

        completed = validate_success(api_client.complete_press(
            job_id, {"good_quantity_produced": 2000}, PRESS_OP))
        assert completed["status"] == "PRINTED", (
            "the replacement PASS governs the station; the failed row does "
            "not block the press")

        rows, _ = validate_paginated(
            api_client.list_color_measurements(job_id, QM))
        row1 = next(r for r in rows if r["id"] == m1["id"])
        assert row1["verdict"] == "FAIL", \
            "the failed row stays FAIL — history is revision-by-append"

    def test_complete_press_with_pending_measurement_rejected(self):
        """PRD §3.6: "Completing the press run is the fork where quality gates
        the schedule. The `PressOperator` supplies `good_quantity_produced`,
        which must be present and greater than zero (`ERR_INVALID_GOOD_QTY`),
        and every color measurement on record for the job must carry the
        verdict `PASS` — with the further requirement that at least one
        measurement exists, since an empty measurement log proves nothing
        (`ERR_COLOR_NOT_APPROVED`)."

        Design: Corner/state_machines/complete_press_with_pending_measurement_rejected
        """
        chain = job_chain(stop_at="ON_PRESS", account_name="Pend Co",
                          artwork_code="AW-P", substrate_code="PE-1",
                          recipe_code="INK-P", die_code="D-P",
                          press_code="P-P", quantity_ordered=2000)
        job_id = chain["job"]["id"]
        record_measurement(job_id, station_no=1, delta_e=1.4)  # left PENDING

        resp = api_client.complete_press(
            job_id, {"good_quantity_produced": 2000}, PRESS_OP)
        validate_error(resp, "ERR_COLOR_NOT_APPROVED", expected_status=422)
        assert get_job(job_id)["status"] == "ON_PRESS"

    def test_complete_press_zero_good_qty_rejected(self):
        """PRD §3.6: "The `PressOperator` supplies `good_quantity_produced`,
        which must be present and greater than zero (`ERR_INVALID_GOOD_QTY`),
        and every color measurement on record for the job must carry the
        verdict `PASS` — with the further requirement that at least one
        measurement exists, since an empty measurement log proves nothing
        (`ERR_COLOR_NOT_APPROVED`)."

        Design: Corner/validations/complete_press_zero_good_qty_rejected
        """
        chain = job_chain(stop_at="ON_PRESS", account_name="ZeroQty Co",
                          artwork_code="AW-Z", substrate_code="Z-1",
                          recipe_code="INK-Z", die_code="D-Z",
                          press_code="P-Z", quantity_ordered=2000)
        job_id = chain["job"]["id"]
        pass_color_gate(job_id, station_no=1, delta_e=1.0)

        resp = api_client.complete_press(
            job_id, {"good_quantity_produced": 0}, PRESS_OP)
        validate_error(resp, "ERR_INVALID_GOOD_QTY", expected_status=422)
        assert get_job(job_id)["status"] == "ON_PRESS"

    def test_job_measurements_list_reverse_reachability(self):
        """PRD §3.6: "Recording requires the parent job to be `ON_PRESS`
        (`ERR_JOB_NOT_ON_PRESS`), and each measurement is born in `PENDING`,
        tied to its job by the system-recorded `job_id`."
        PRD §4: GET `/label-jobs/jobs/{id}/color-measurements` — "List a job's
        color measurements".

        Design: Corner/endpoints/job_measurements_list_reverse_reachability
        """
        chain = job_chain(stop_at="ON_PRESS", account_name="ListM Co",
                          artwork_code="AW-LM", substrate_code="LM-1",
                          recipe_code="INK-LM", die_code="D-LM",
                          press_code="P-LM", quantity_ordered=2000)
        job_id = chain["job"]["id"]
        m1 = record_measurement(job_id, station_no=1, delta_e=1.1)
        m2 = record_measurement(job_id, station_no=2, delta_e=1.9)

        data, meta = validate_paginated(
            api_client.list_color_measurements(job_id, QM))
        ids = {row["id"] for row in data}
        assert ids == {m1["id"], m2["id"]}
        assert meta["total_count"] == 2
