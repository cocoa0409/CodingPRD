"""Study lifecycle: abort lockdown, the analysis reopen loop, close-fieldwork
gates, activation fiscal checks, read-your-writes, escrow conservation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_arm,
    add_time_point,
    assert_retainer_conservation,
    create_chamber,
    create_client,
    create_draft_study,
    create_session,
    get_chamber,
    get_client,
    get_study,
    get_success_data,
    get_time_point,
    set_clock,
    setup_study_in_progress,
    submit_and_approve,
    validate_error,
    validate_success,
)

LD = TEST_USERS["lab_director_headers"]
SCI = TEST_USERS["scientist_headers"]


class TestAbortLockdown:
    def test_study_terminal_aborted_lockdown(self, api):
        """PRD §3.2: "A `LabDirector` may abort a study from `DRAFT`, `DESIGN_REVIEW`, `SCHEDULED`, or `IN_PROGRESS`, moving it into the terminal `ABORTED` status; from any other status the attempt is `ERR_INVALID_STUDY_STATE`."
        PRD §3.2: "the study must currently be `DRAFT` (else `ERR_INVALID_STUDY_STATE`)"

        Design: Corner/state_machines/study_terminal_aborted_lockdown
        """
        client = create_client()
        study = create_draft_study(client["id"])
        add_arm(study["id"], "STANDARD_FILM", is_control=True)
        add_time_point(study["id"], 0)

        aborted = validate_success(api.abort_study(study["id"], LD))
        assert aborted["status"] == "ABORTED"

        validate_error(api.submit_design(study["id"], SCI),
                       ApiErrorId.ERR_INVALID_STUDY_STATE, 409)
        assert get_study(study["id"])["status"] == "ABORTED", (
            "terminal ABORTED must not move")


class TestAnalysisReopenCycle:
    def test_reopen_allows_schedule_extension(self, api):
        """PRD §3.2: "Analysis is not one-way: a scientist may reopen fieldwork, moving `ANALYSIS → IN_PROGRESS`, which is precisely what licenses the extended-schedule time-point creation described above"
        PRD §3.2: "after a study has been reopened into fieldwork, additional time points are also accepted, but only when the new `day_index` is strictly greater than the current study day as defined in §2.4, and any attempt outside those two situations is `ERR_INVALID_STUDY_STATE`."

        Design: Difficulty/non_linear_state_machine/study_analysis_reopen_cycle
        """
        env = setup_study_in_progress(day_indexes=(0,))
        study_id = env["study"]["id"]
        get_success_data(api.skip_time_point(env["time_points"][0]["id"], SCI))
        closed = validate_success(api.close_fieldwork(study_id, SCI))
        assert closed["status"] == "ANALYSIS"

        reopened = validate_success(api.reopen_fieldwork(study_id, SCI))
        assert reopened["status"] == "IN_PROGRESS", "cyclic re-entry succeeded"

        # current study day is 0 (activated at the 2026-08-01 default clock);
        # day_index 30 is strictly greater, so the extension is licensed
        tp30 = validate_success(api.create_time_point(
            {"study_id": study_id, "day_index": 30}, SCI), 201)
        assert tp30["status"] == "PENDING"
        assert tp30["day_index"] == 30

    def test_reopen_loop_completes_twice(self, api):
        """PRD §3.2: "the `IN_PROGRESS → ANALYSIS → IN_PROGRESS` loop may repeat as often as the science demands."
        PRD §3.2: "Closure requires that every sampling time point of the study rests in `EVALUATED`, `CLOSED`, or `SKIPPED`"

        Design: Difficulty/non_linear_state_machine/study_analysis_reopen_cycle
        """
        env = setup_study_in_progress(day_indexes=(0,))
        study_id = env["study"]["id"]
        get_success_data(api.skip_time_point(env["time_points"][0]["id"], SCI))
        closed = validate_success(api.close_fieldwork(study_id, SCI))
        assert closed["status"] == "ANALYSIS"

        get_success_data(api.reopen_fieldwork(study_id, SCI))
        tp30 = get_success_data(api.create_time_point(
            {"study_id": study_id, "day_index": 30}, SCI))
        get_success_data(api.skip_time_point(tp30["id"], SCI))
        closed_again = validate_success(api.close_fieldwork(study_id, SCI))
        assert closed_again["status"] == "ANALYSIS", "the loop completed twice"
        assert get_time_point(tp30["id"])["status"] == "SKIPPED"


class TestCloseFieldworkGates:
    def test_close_fieldwork_blocked_then_unblocked(self, api):
        """PRD §3.2: "Closure requires that every sampling time point of the study rests in `EVALUATED`, `CLOSED`, or `SKIPPED` — any straggler in `PENDING` or `PULLED` draws `ERR_OPEN_TIME_POINTS_REMAIN` — and that every evaluation session of the study is `ANALYZED` or `CANCELLED`, else `ERR_SESSIONS_STILL_OPEN`."

        Design: Corner/validations/close_fieldwork_blocked_then_unblocked
        """
        env = setup_study_in_progress(day_indexes=(0,))
        study_id = env["study"]["id"]
        tp0 = env["time_points"][0]
        arm = env["arms"][0]

        # Only the time-point gate can fail: tp0 PENDING, no sessions exist.
        validate_error(api.close_fieldwork(study_id, SCI),
                       ApiErrorId.ERR_OPEN_TIME_POINTS_REMAIN, 409)

        # Only the session gate can fail: tp0 SKIPPED, session still PLANNED.
        session = create_session(study_id, tp0["id"], arm["id"],
                                 "2026-08-02T10:00:00Z", "2026-08-02T11:00:00Z")
        get_success_data(api.skip_time_point(tp0["id"], SCI))
        validate_error(api.close_fieldwork(study_id, SCI),
                       ApiErrorId.ERR_SESSIONS_STILL_OPEN, 409)

        # Both gates satisfied: close succeeds.
        get_success_data(api.cancel_session(session["id"],
                                            TEST_USERS["coordinator_headers"]))
        closed = validate_success(api.close_fieldwork(study_id, SCI))
        assert closed["status"] == "ANALYSIS"


class TestActivationFiscalGate:
    def test_activate_insufficient_retainer(self, api):
        """PRD §3.2: "The reserved hours required are a base of 10 hours, plus 2 hours per sampling time point, plus 4 hours per study arm."
        PRD §3.2: "if the client's `retainer_hours_balance` falls short of the reserved hours required, activation is rejected with `ERR_INSUFFICIENT_RETAINER_HOURS`"

        Design: Corner/validations/activate_insufficient_retainer
        """
        set_clock()
        client = create_client(topup_hours=10)
        study = create_draft_study(client["id"])
        add_arm(study["id"], "STANDARD_FILM", is_control=True)
        add_time_point(study["id"], 0)
        submit_and_approve(study["id"])

        # reserve would be 10 + 2*1 + 4*1 = 16 hours against a 10-hour balance
        validate_error(api.activate_study(study["id"], SCI),
                       ApiErrorId.ERR_INSUFFICIENT_RETAINER_HOURS, 402)
        assert get_study(study["id"])["status"] == "SCHEDULED"
        assert get_client(client["id"])["retainer_hours_balance"] == 10, (
            "a rejected activation must not move the balance")

    def test_activate_state_error_beats_fiscal_error(self, api):
        """PRD §2.6: "At study activation only, the client's retainer balance is checked last — after the study-state gate — and shortfalls are rejected with `ERR_INSUFFICIENT_RETAINER_HOURS` (402)."
        PRD §3.2: "Activation — the `SCHEDULED → IN_PROGRESS` transition driven by a `SensoryScientist`"

        Design: Difficulty/priority_pair_validation_conflict/activate_state_error_beats_fiscal_error
        """
        set_clock()
        # Client never topped up (balance 0): BOTH the state gate (study still
        # DRAFT) and the fiscal gate would fail — the state error must win.
        client = create_client()
        study = create_draft_study(client["id"])
        add_arm(study["id"], "STANDARD_FILM", is_control=True)
        add_time_point(study["id"], 0)

        validate_error(api.activate_study(study["id"], SCI),
                       ApiErrorId.ERR_INVALID_STUDY_STATE, 409)
        assert get_client(client["id"])["retainer_hours_balance"] == 0, (
            "no escrow movement when the state gate fires")
        assert get_study(study["id"])["status"] == "DRAFT"

    def test_activate_state_gate_fires_regardless_of_funds(self, api):
        """PRD §2.6: "At study activation only, the client's retainer balance is checked last — after the study-state gate — and shortfalls are rejected with `ERR_INSUFFICIENT_RETAINER_HOURS` (402)."
        PRD §2.6: "Every request is validated against an ordered ladder of checks, and the first rung that fails determines the error returned."

        Design: Difficulty/priority_pair_validation_conflict/activate_state_error_beats_fiscal_error
        """
        set_clock()
        # Fully funded client, but the study is DRAFT: the state gate alone
        # decides — proving the fiscal check is never reached first.
        client = create_client(topup_hours=100)
        study = create_draft_study(client["id"])
        add_arm(study["id"], "STANDARD_FILM", is_control=True)
        add_time_point(study["id"], 0)

        validate_error(api.activate_study(study["id"], SCI),
                       ApiErrorId.ERR_INVALID_STUDY_STATE, 409)
        assert get_client(client["id"])["retainer_hours_balance"] == 100
        assert get_study(study["id"])["status"] == "DRAFT"


class TestImmediateConsistency:
    def test_immediate_consistency_after_mutation(self, api):
        """PRD §3.2: "On success the study captures `actual_start_utc` from the logical clock, the reserved amount is debited from the client's `retainer_hours_balance` and parked in the study's `reserved_hours_escrow`, and the client's `active_study_count` increases by 1."
        PRD §3.3: "the chamber's `reserved_units` increases by `quantity`; and the time point moves `PENDING → PULLED`"
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_consistency_after_mutation
        """
        set_clock()
        client = create_client(topup_hours=100)
        study = create_draft_study(client["id"])
        arm = add_arm(study["id"], "STANDARD_FILM", is_control=True)
        tp0 = add_time_point(study["id"], 0)
        chamber = create_chamber(chamber_code="CH-IC", temp_c=20, capacity_units=10)
        submit_and_approve(study["id"])

        activated = validate_success(api.activate_study(study["id"], SCI))
        assert activated["reserved_hours_escrow"] == 16, (
            "the mutation response itself carries the escrow (10 + 2*1 + 4*1)")
        assert get_client(client["id"])["retainer_hours_balance"] == 84, (
            "the debit is visible on the very next read")

        pulled = validate_success(api.pull_samples(
            tp0["id"], {"chamber_id": chamber["id"], "arm_id": arm["id"],
                        "quantity": 2, "unit_purpose": "RETAIN"}, SCI), 201)
        assert pulled["status"] == "PULLED"
        assert get_chamber(chamber["id"])["reserved_units"] == 2, (
            "the occupancy increment is visible on the very next read")


class TestRetainerConservation:
    def test_activate_reserves_exactly(self, api):
        """PRD §3.2: "The reserved hours required are a base of 10 hours, plus 2 hours per sampling time point, plus 4 hours per study arm."
        PRD §3.2: "the reserved amount is debited from the client's `retainer_hours_balance` and parked in the study's `reserved_hours_escrow`, and the client's `active_study_count` increases by 1."

        Design: Difficulty/compensating_invariant/retainer_activate_abort_conserves_hours
        """
        env = setup_study_in_progress(day_indexes=(0, 7), topup_hours=100,
                                      with_chamber=False)
        # reserve = 10 + 2*2 time points + 4*1 arm = 18 hours
        client = get_client(env["client"]["id"])
        study = get_study(env["study"]["id"])
        assert client["retainer_hours_balance"] == 82
        assert study["reserved_hours_escrow"] == 18
        assert client["active_study_count"] == 1
        assert_retainer_conservation(client["retainer_hours_balance"],
                                     study["reserved_hours_escrow"], 100.0)

    def test_abort_refunds_escrow_in_full(self, api):
        """PRD §3.2: "the entire `reserved_hours_escrow` is credited back to the client's `retainer_hours_balance` and the escrow zeroed (no consumption is charged); when the study was in `SCHEDULED` or `IN_PROGRESS`, the client's `active_study_count` decreases by 1"

        Design: Difficulty/compensating_invariant/retainer_activate_abort_conserves_hours
        """
        env = setup_study_in_progress(day_indexes=(0, 7), topup_hours=100,
                                      with_chamber=False)
        aborted = validate_success(api.abort_study(env["study"]["id"], LD))
        assert aborted["status"] == "ABORTED"

        client = get_client(env["client"]["id"])
        study = get_study(env["study"]["id"])
        assert client["retainer_hours_balance"] == 100, (
            "escrow fully refunded, zero drift")
        assert study["reserved_hours_escrow"] == 0
        assert client["active_study_count"] == 0
        assert_retainer_conservation(client["retainer_hours_balance"],
                                     study["reserved_hours_escrow"], 100.0)
