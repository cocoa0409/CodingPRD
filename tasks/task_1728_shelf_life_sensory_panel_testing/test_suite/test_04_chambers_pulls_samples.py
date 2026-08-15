"""Chambers, sample pulls, and unit custody: capacity boundaries, pull windows,
temperature coherence, aggregate occupancy, and the custody state machine."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_arm,
    add_time_point,
    assert_chamber_occupancy_invariant,
    create_chamber,
    create_client,
    create_draft_study,
    get_chamber,
    get_success_data,
    get_time_point,
    list_sample_units,
    pull_units,
    set_clock,
    setup_study_in_progress,
    submit_and_approve,
    activate,
    validate_error,
    validate_success,
)

LD = TEST_USERS["lab_director_headers"]
SCI = TEST_USERS["scientist_headers"]
PC = TEST_USERS["coordinator_headers"]


def _discard_all(api, unit_ids):
    for uid in unit_ids:
        get_success_data(api.discard_sample_unit(uid, LD))


class TestChamberCapacityEquality:
    def test_pull_filling_chamber_exactly_is_allowed(self, api):
        """PRD §2.9: "a pull is lawful whenever the chamber's `reserved_units` plus the requested `quantity` is less than or equal to `capacity_units` — filling a chamber exactly to capacity is allowed — and is rejected with `ERR_CHAMBER_CAPACITY_EXCEEDED` otherwise."

        Design: Difficulty/boundary_precision_check/chamber_capacity_equality_allowed
        """
        env = setup_study_in_progress(chamber_capacity=5)
        tp0 = env["time_points"][0]
        chamber = env["chamber"]
        arm_c = env["arms"][0]

        p1 = validate_success(api.pull_samples(
            tp0["id"], {"chamber_id": chamber["id"], "arm_id": arm_c["id"],
                        "quantity": 3, "unit_purpose": "RETAIN"}, SCI), 201)
        assert p1["status"] == "PULLED"
        p2 = validate_success(api.pull_samples(
            tp0["id"], {"chamber_id": chamber["id"], "arm_id": arm_c["id"],
                        "quantity": 2, "unit_purpose": "RETAIN"}, SCI), 201)
        assert p2["status"] == "PULLED"
        assert get_chamber(chamber["id"])["reserved_units"] == 5, (
            "3 + 2 == 5: exact-capacity fill is legal")

    def test_pull_beyond_capacity_rejected_and_counter_unchanged(self, api):
        """PRD §2.9: "a pull is lawful whenever the chamber's `reserved_units` plus the requested `quantity` is less than or equal to `capacity_units` — filling a chamber exactly to capacity is allowed — and is rejected with `ERR_CHAMBER_CAPACITY_EXCEEDED` otherwise."

        Design: Difficulty/boundary_precision_check/chamber_capacity_equality_allowed
        """
        env = setup_study_in_progress(chamber_capacity=5)
        tp0 = env["time_points"][0]
        chamber = env["chamber"]
        arm = env["arms"][0]

        pull_units(tp0["id"], chamber["id"], arm["id"], quantity=3,
                   unit_purpose="RETAIN")
        pull_units(tp0["id"], chamber["id"], arm["id"], quantity=2,
                   unit_purpose="RETAIN")

        resp = api.pull_samples(
            tp0["id"], {"chamber_id": chamber["id"], "arm_id": arm["id"],
                        "quantity": 1, "unit_purpose": "RETAIN"}, SCI)
        validate_error(resp, ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED, 409)
        assert get_chamber(chamber["id"])["reserved_units"] == 5, (
            "5 + 1 > 5 rejected; the counter must not move")


class TestPullGuards:
    def test_chamber_temp_mismatch_on_pull(self, api):
        """PRD §3.3: "the chamber's `temp_c` must equal the study's `storage_temp_c` (else `ERR_CHAMBER_TEMP_MISMATCH`)"

        Design: Corner/validations/chamber_temp_mismatch_on_pull
        """
        env = setup_study_in_progress(with_chamber=False)
        tp0 = env["time_points"][0]
        arm = env["arms"][0]
        cold = create_chamber(chamber_code="CH-COLD", temp_c=4, capacity_units=10)
        ambient = create_chamber(chamber_code="CH-AMB", temp_c=20, capacity_units=10)

        resp = api.pull_samples(
            tp0["id"], {"chamber_id": cold["id"], "arm_id": arm["id"],
                        "quantity": 1, "unit_purpose": "EVALUATION"}, SCI)
        validate_error(resp, ApiErrorId.ERR_CHAMBER_TEMP_MISMATCH, 422)
        assert get_chamber(cold["id"])["reserved_units"] == 0

        pulled = validate_success(api.pull_samples(
            tp0["id"], {"chamber_id": ambient["id"], "arm_id": arm["id"],
                        "quantity": 1, "unit_purpose": "EVALUATION"}, SCI), 201)
        assert pulled["status"] == "PULLED"
        assert get_chamber(ambient["id"])["reserved_units"] == 1

    def test_pull_window_violation_too_early_then_ok(self, api):
        """PRD §3.3: "the current study day of §2.4 must be at least the time point's `day_index` and no more than two days past it — both boundaries inclusive — (else `ERR_PULL_WINDOW_VIOLATION`)"

        Design: Corner/validations/pull_window_violation_too_early_then_ok
        """
        env = setup_study_in_progress(day_indexes=(7,))
        tp7 = env["time_points"][0]
        chamber = env["chamber"]
        arm = env["arms"][0]

        # study day 0: 7 <= 0 is false -> violation
        resp = api.pull_samples(
            tp7["id"], {"chamber_id": chamber["id"], "arm_id": arm["id"],
                        "quantity": 1, "unit_purpose": "EVALUATION"}, SCI)
        validate_error(resp, ApiErrorId.ERR_PULL_WINDOW_VIOLATION, 409)

        # study day 7 (2026-08-08): 7 <= 7 <= 9 -> legal
        set_clock("2026-08-08T00:00:00Z")
        pulled = validate_success(api.pull_samples(
            tp7["id"], {"chamber_id": chamber["id"], "arm_id": arm["id"],
                        "quantity": 1, "unit_purpose": "EVALUATION"}, SCI), 201)
        assert pulled["status"] == "PULLED"
        assert get_chamber(chamber["id"])["reserved_units"] == 1


class TestAggregateCapacityAcrossStudies:
    def _two_studies_sharing_chamber(self, api):
        """Chamber cap 6 at 20C + two IN_PROGRESS REAL_TIME studies (1 control
        arm, tp0 each) sharing it."""
        set_clock()
        client = create_client(topup_hours=100)
        chamber = create_chamber(chamber_code="CH-SH", temp_c=20,
                                 capacity_units=6)
        envs = []
        for name, variant in (("Pasta A", "STANDARD_FILM"), ("Pasta B", "VACUUM")):
            study = create_draft_study(client["id"], product_name=name)
            arm = add_arm(study["id"], variant, is_control=True)
            tp0 = add_time_point(study["id"], 0)
            submit_and_approve(study["id"])
            activate(study["id"])
            envs.append({"study": study, "arm": arm, "tp0": tp0})
        return chamber, envs

    def test_second_study_pull_collides_with_aggregate_occupancy(self, api):
        """PRD §2.9: "at all times it equals the number of sample units whose `chamber_id` names that chamber and whose status is either `STORED` or `CHECKED_OUT`"
        PRD §2.9: "a pull is lawful whenever the chamber's `reserved_units` plus the requested `quantity` is less than or equal to `capacity_units` — filling a chamber exactly to capacity is allowed — and is rejected with `ERR_CHAMBER_CAPACITY_EXCEEDED` otherwise."

        Design: Difficulty/resource_temporal_overlap/chamber_aggregate_capacity_across_studies
        """
        chamber, (a, b) = self._two_studies_sharing_chamber(api)
        pull_units(a["tp0"]["id"], chamber["id"], a["arm"]["id"], quantity=4,
                   unit_purpose="RETAIN")
        resp = api.pull_samples(
            b["tp0"]["id"], {"chamber_id": chamber["id"], "arm_id": b["arm"]["id"],
                             "quantity": 3, "unit_purpose": "RETAIN"}, SCI)
        validate_error(resp, ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED, 409)
        assert get_chamber(chamber["id"])["reserved_units"] == 4, (
            "occupancy aggregates across both studies; 4 + 3 > 6 stays rejected")

    def test_pull_succeeds_after_compensation_frees_headroom(self, api):
        """PRD §2.9: "Only transitions that leave the counted set change occupancy: consuming, discarding, expiry by the retain sweep, and the abort cascade each decrement `reserved_units` by one per affected unit, while a pull increments it by the pulled quantity."

        Design: Difficulty/resource_temporal_overlap/chamber_aggregate_capacity_across_studies
        """
        chamber, (a, b) = self._two_studies_sharing_chamber(api)
        pull_units(a["tp0"]["id"], chamber["id"], a["arm"]["id"], quantity=4,
                   unit_purpose="RETAIN")
        validate_error(api.pull_samples(
            b["tp0"]["id"], {"chamber_id": chamber["id"], "arm_id": b["arm"]["id"],
                             "quantity": 3, "unit_purpose": "RETAIN"}, SCI),
            ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED, 409)

        units = list_sample_units(study_id=a["study"]["id"])
        for unit in units[:2]:
            get_success_data(api.checkout_sample_unit(unit["id"], PC))
            get_success_data(api.consume_sample_unit(unit["id"], PC))
        assert get_chamber(chamber["id"])["reserved_units"] == 2, (
            "consuming two units frees two slots")

        pulled = validate_success(api.pull_samples(
            b["tp0"]["id"], {"chamber_id": chamber["id"], "arm_id": b["arm"]["id"],
                             "quantity": 3, "unit_purpose": "RETAIN"}, SCI), 201)
        assert pulled["status"] == "PULLED"
        assert get_chamber(chamber["id"])["reserved_units"] == 5, (
            "2 + 3 = 5 <= 6 now fits")


class TestDiscardConservation:
    def test_pull_then_discard_all_restores_headroom(self, api):
        """PRD §2.9: "Each storage chamber's `reserved_units` is a derived counter with a strict invariant: at all times it equals the number of sample units whose `chamber_id` names that chamber and whose status is either `STORED` or `CHECKED_OUT`."
        PRD §3.3: "A `LabDirector` may discard a unit from either `STORED` or `CHECKED_OUT`, moving it to `DISCARDED` with `session_id` cleared and `reserved_units` decremented by 1."

        Design: Difficulty/compensating_invariant/chamber_pull_discard_conserves_headroom
        """
        env = setup_study_in_progress(chamber_capacity=6)
        tp0, arm, chamber = (env["time_points"][0], env["arms"][0],
                             env["chamber"])
        pull_units(tp0["id"], chamber["id"], arm["id"], quantity=4,
                   unit_purpose="RETAIN")
        assert get_chamber(chamber["id"])["reserved_units"] == 4

        units = list_sample_units(study_id=env["study"]["id"])
        _discard_all(api, [u["id"] for u in units])
        for unit in units:
            refreshed = get_success_data(api.get_sample_unit(unit["id"], LD))
            assert refreshed["status"] == "DISCARDED"
        chamber_now = get_chamber(chamber["id"])
        assert chamber_now["reserved_units"] == 0, (
            "invariant restored exactly, no drift")

    def test_invariant_holds_at_intermediate_steps(self, api):
        """PRD §2.9: "at all times it equals the number of sample units whose `chamber_id` names that chamber and whose status is either `STORED` or `CHECKED_OUT`"

        Design: Difficulty/compensating_invariant/chamber_pull_discard_conserves_headroom
        """
        env = setup_study_in_progress(chamber_capacity=6)
        tp0, arm, chamber = (env["time_points"][0], env["arms"][0],
                             env["chamber"])
        pull_units(tp0["id"], chamber["id"], arm["id"], quantity=4,
                   unit_purpose="RETAIN")

        def occupying_count():
            units = list_sample_units(study_id=env["study"]["id"])
            return sum(1 for u in units if u["status"] in ("STORED", "CHECKED_OUT"))

        assert_chamber_occupancy_invariant(get_chamber(chamber["id"]),
                                           occupying_count())

        units = list_sample_units(study_id=env["study"]["id"])
        _discard_all(api, [units[0]["id"], units[1]["id"]])
        assert get_chamber(chamber["id"])["reserved_units"] == 2
        assert_chamber_occupancy_invariant(get_chamber(chamber["id"]),
                                           occupying_count())


class TestUnitCustodyCycle:
    def _retain_unit_in_progress_study(self, api):
        env = setup_study_in_progress(chamber_capacity=10)
        tp0, arm, chamber = (env["time_points"][0], env["arms"][0],
                             env["chamber"])
        pull_units(tp0["id"], chamber["id"], arm["id"], quantity=1,
                   unit_purpose="RETAIN")
        unit = list_sample_units(study_id=env["study"]["id"])[0]
        return env, chamber, unit

    def test_checkout_return_loop_is_occupancy_neutral(self, api):
        """PRD §3.3: "A `PanelCoordinator` checks out a `STORED` unit, moving it `STORED → CHECKED_OUT`"
        PRD §3.3: "Returning a unit moves it `CHECKED_OUT → STORED` and clears `session_id`; this loop may repeat freely and is occupancy-neutral per §2.9."
        PRD §3.3: "while a `RETAIN` unit may be checked out without a session."

        Design: Difficulty/non_linear_state_machine/sample_unit_checkout_return_cycle
        """
        env, chamber, unit = self._retain_unit_in_progress_study(api)
        uid = unit["id"]

        out1 = validate_success(api.checkout_sample_unit(uid, PC))
        assert out1["status"] == "CHECKED_OUT"
        assert get_chamber(chamber["id"])["reserved_units"] == 1, (
            "CHECKED_OUT still counts as occupying")

        back = validate_success(api.return_sample_unit(uid, PC))
        assert back["status"] == "STORED"
        assert back["session_id"] is None, "return clears session_id"
        assert get_chamber(chamber["id"])["reserved_units"] == 1

        out2 = validate_success(api.checkout_sample_unit(uid, PC))
        assert out2["status"] == "CHECKED_OUT", "the loop re-entered"
        assert get_chamber(chamber["id"])["reserved_units"] == 1

    def test_consume_decrements_and_terminal_consume_rejected(self, api):
        """PRD §3.3: "Consuming a unit moves it `CHECKED_OUT → CONSUMED`, clears `session_id`, and decrements the chamber's `reserved_units` by 1."
        PRD §3.3: "Any checkout, return, consume, or discard attempted from a status that does not permit it is `ERR_INVALID_SAMPLE_STATE`."

        Design: Difficulty/non_linear_state_machine/sample_unit_checkout_return_cycle
        """
        env, chamber, unit = self._retain_unit_in_progress_study(api)
        uid = unit["id"]

        get_success_data(api.checkout_sample_unit(uid, PC))
        consumed = validate_success(api.consume_sample_unit(uid, PC))
        assert consumed["status"] == "CONSUMED"
        assert consumed["session_id"] is None
        assert get_chamber(chamber["id"])["reserved_units"] == 0

        resp = api.consume_sample_unit(uid, PC)
        validate_error(resp, ApiErrorId.ERR_INVALID_SAMPLE_STATE, 409)


class TestTimePointCloseGate:
    def test_time_point_close_from_pending_rejected(self, api):
        """PRD §3.3: "the point may be closed — `EVALUATED → CLOSED`, permitted only from `EVALUATED` (else `ERR_INVALID_TIME_POINT_STATE`)"

        Design: Corner/state_machines/time_point_close_from_pending_rejected
        """
        client = create_client()
        study = create_draft_study(client["id"])
        add_arm(study["id"], "STANDARD_FILM", is_control=True)
        tp0 = add_time_point(study["id"], 0)

        validate_error(api.close_time_point(tp0["id"], SCI),
                       ApiErrorId.ERR_INVALID_TIME_POINT_STATE, 409)
        assert get_time_point(tp0["id"])["status"] == "PENDING"
