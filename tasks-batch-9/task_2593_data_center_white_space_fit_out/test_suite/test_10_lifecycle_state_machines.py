"""Lifecycle state machines of the fit-out: package supersede and witness ordering,
load bank terminality, the lockdown of a rejected method of procedure, the
system-driven walk into LIVE, and the custody handover of a release packet."""
import pytest

from test_helpers import (
    api_client,
    assert_custody_partition,
    assert_hall_power_ledger_balances,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    CA,
    CM,
    CM2,
    FP,
    OM,
    WA,
    accept_packet,
    add_powered_rack,
    advance_phase,
    approve_mop,
    approve_script,
    certify_package,
    create_mop,
    create_package,
    create_packet,
    create_tenant,
    execute_script,
    prove_zone_and_cooling,
    read_cage,
    read_hall,
    read_load_bank_test,
    read_mop,
    read_package,
    read_packet,
    read_rack,
    run_passing_load_bank,
    schedule_load_bank,
    set_clock,
    setup_commissioning_hall,
    setup_fit_out_hall,
    setup_planning_hall,
    setup_secured_cage,
    submit_mop,
    submit_packet,
    witness_package,
)


class TestCommissioningPackageSupersede:
    """Opening a package for a hall and level that already carries a live package is an
    unconditional supersede of the prior row."""

    def _commissioning_hall_with_l1(self, code):
        ctx = setup_commissioning_hall(code)
        ctx["first"] = create_package(ctx["hall_id"], "L1", target_load_kw=10.00)
        return ctx

    def test_second_package_on_the_same_hall_and_level_supersedes_the_first(self):
        """The prior L1 package is driven to SUPERSEDED with superseded_by_package_id
        pointing at the new row, while the new row opens at DRAFT on script revision 0
        and the hall — whose only live package is now a draft — stays in COMMISSIONING.

        PRD: "Opening a package for a hall and level that already has a package whose
        `package_state` is anything other than `SUPERSEDED` supersedes that prior
        package: its `superseded_by_package_id` is set to the new package's identifier,
        its `package_state` becomes `SUPERSEDED`, and it stops participating in the
        hall's evaluation for going live."
        PRD: "A new package opens with `script_revision` at 0, `executed_by_user_id`,
        `witnessed_by_user_id`, `superseded_by_package_id` and `measured_load_kw` all
        null."
        PRD: "The create also increments the hall's `version`."

        Design: Corner/state_machines/commissioning_package_supersede_on_same_hall_and_level
        """
        ctx = self._commissioning_hall_with_l1("CX36")
        first = ctx["first"]
        hall_before = read_hall(ctx["hall_id"])

        second = validate_success(
            api_client.create_commissioning_package(
                {
                    "hall_id": ctx["hall_id"],
                    "level": "L1",
                    "title": "L1 documentation review rev B",
                    "target_load_kw": 10.00,
                    "expected_hall_version": hall_before["version"],
                },
                CA,
            ),
            201,
        )

        assert second["package_state"] == "DRAFT"
        assert second["script_status"] == "NOT_STARTED"
        assert second["witness_status"] == "PENDING"
        assert second["script_revision"] == 0
        assert second["superseded_by_package_id"] is None
        assert second["measured_load_kw"] is None
        assert second["executed_by_user_id"] is None
        assert second["witnessed_by_user_id"] is None

        superseded = read_package(first["id"])
        assert superseded["package_state"] == "SUPERSEDED"
        assert superseded["superseded_by_package_id"] == second["id"], (
            "the prior package points at the row that superseded it"
        )

        hall_after = read_hall(ctx["hall_id"])
        assert hall_after["version"] == hall_before["version"] + 1
        assert hall_after["status"] == "COMMISSIONING", (
            "a hall whose only non-superseded package is a draft cannot go live"
        )

    def test_supersede_ignores_the_prior_state_and_leaves_other_levels_alone(self):
        """A package already at IN_EXECUTION is still superseded — the supersede is keyed
        on hall and level, not on the prior package's own state — and the SUPERSEDED
        projection outranks its untouched SCRIPT_APPROVED script dimension, while the
        hall's L2 package is left at DRAFT.

        PRD: "Opening a package for a hall and level that already has a package whose
        `package_state` is anything other than `SUPERSEDED` supersedes that prior
        package: its `superseded_by_package_id` is set to the new package's identifier,
        its `package_state` becomes `SUPERSEDED`, and it stops participating in the
        hall's evaluation for going live."
        PRD: "The branch order is the specification: being superseded outranks
        everything, and being blocked outranks having been rejected."

        Design: Corner/state_machines/commissioning_package_supersede_on_same_hall_and_level
        """
        ctx = self._commissioning_hall_with_l1("CX36B")
        first = ctx["first"]
        approved = approve_script(first["id"], 1)
        assert approved["package_state"] == "IN_EXECUTION"

        second_level = create_package(ctx["hall_id"], "L2", target_load_kw=10.00)
        replacement = create_package(ctx["hall_id"], "L1", target_load_kw=12.00)

        superseded = read_package(first["id"])
        assert superseded["package_state"] == "SUPERSEDED"
        assert superseded["superseded_by_package_id"] == replacement["id"]
        assert superseded["script_status"] == "SCRIPT_APPROVED", (
            "the supersede projection does not rewrite the script dimension"
        )

        other_level = read_package(second_level["id"])
        assert other_level["package_state"] == "DRAFT", (
            "an L2 package is not in the supersede set of an L1 create"
        )
        assert other_level["superseded_by_package_id"] is None
        assert replacement["package_state"] == "DRAFT"
        assert replacement["level"] == "L1"

        rows, meta = validate_paginated(
            api_client.list_commissioning_packages(CA, {"hall_id": ctx["hall_id"]})
        )
        assert meta["total_count"] == 3, "supersede is not a delete"
        states = {row["id"]: row["package_state"] for row in rows}
        assert states[first["id"]] == "SUPERSEDED"
        assert states[replacement["id"]] == "DRAFT"


class TestWitnessRequiresAnExecutedScript:
    """The witness dimension only opens once the script dimension has reached EXECUTED,
    and a superseded package can never be signed."""

    def _hall_with_approved_script(self, code):
        ctx = setup_commissioning_hall(code)
        package = create_package(ctx["hall_id"], "L1", target_load_kw=10.00)
        ctx["package"] = approve_script(package["id"], 1)
        ctx["package_id"] = package["id"]
        return ctx

    def test_witnessing_a_script_approved_package_is_refused(self):
        """Signing a package whose script is only SCRIPT_APPROVED is refused with
        ERR_INVALID_STATE, and the package is left exactly where it stood: witness
        dimension PENDING with no signature recorded and the projection at IN_EXECUTION.

        PRD: "The package's `script_status` must be `EXECUTED` — witnessing before
        execution, or witnessing a `SUPERSEDED` package, is refused with
        `ERR_INVALID_STATE` — and the witnessing `X-User-ID` must differ from the
        package's `executed_by_user_id`, failing which the request is refused with
        `ERR_WITNESS_SAME_AS_EXECUTOR`."

        Design: Corner/state_machines/commissioning_package_witness_before_execute_rejected
        """
        ctx = self._hall_with_approved_script("CX37")
        assert ctx["package"]["script_status"] == "SCRIPT_APPROVED"
        assert ctx["package"]["witness_status"] == "PENDING"

        validate_error(
            api_client.witness_package(
                ctx["package_id"],
                {"decision": "WITNESSED", "witness_note": "Signed before the run."},
                WA,
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )

        after = read_package(ctx["package_id"])
        assert after["witness_status"] == "PENDING"
        assert after["witnessed_by_user_id"] is None, "no signature was recorded"
        assert after["script_status"] == "SCRIPT_APPROVED"
        assert after["package_state"] == "IN_EXECUTION"
        assert after["executed_by_user_id"] is None
        assert read_hall(ctx["hall_id"])["status"] == "COMMISSIONING"

    def test_witnessing_a_superseded_package_is_refused(self):
        """A package whose script reached EXECUTED but which a later package superseded
        can no longer be witnessed: the request is refused with ERR_INVALID_STATE and the
        package keeps its SUPERSEDED projection with no witness recorded.

        PRD: "The package's `script_status` must be `EXECUTED` — witnessing before
        execution, or witnessing a `SUPERSEDED` package, is refused with
        `ERR_INVALID_STATE` — and the witnessing `X-User-ID` must differ from the
        package's `executed_by_user_id`, failing which the request is refused with
        `ERR_WITNESS_SAME_AS_EXECUTOR`."
        PRD: "If `superseded_by_package_id` is set, the package state is `SUPERSEDED`."

        Design: Corner/state_machines/commissioning_package_witness_before_execute_rejected
        """
        ctx = self._hall_with_approved_script("CX37B")
        executed = execute_script(ctx["package_id"])
        assert executed["script_status"] == "EXECUTED"
        assert executed["executed_by_user_id"] == "u-ca-1"

        replacement = create_package(ctx["hall_id"], "L1", target_load_kw=10.00)

        validate_error(
            api_client.witness_package(
                ctx["package_id"], {"decision": "WITNESSED"}, WA
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )

        after = read_package(ctx["package_id"])
        assert after["package_state"] == "SUPERSEDED"
        assert after["superseded_by_package_id"] == replacement["id"]
        assert after["witness_status"] == "PENDING"
        assert after["witnessed_by_user_id"] is None
        assert after["script_status"] == "EXECUTED"
        assert read_hall(ctx["hall_id"])["status"] == "COMMISSIONING", (
            "a superseded package never certifies its hall"
        )


class TestLoadBankRunOrderAndTerminality:
    """A load bank run may only be completed from RUNNING, and COMPLETED and ABORTED
    close the row for good."""

    def _hall_with_scheduled_run(self, code):
        ctx = setup_commissioning_hall(code)
        package = create_package(ctx["hall_id"], "L4", target_load_kw=10.00)
        approve_script(package["id"], 1)
        ctx["package_id"] = package["id"]
        ctx["run"] = schedule_load_bank(
            package["id"], 10.00, "2026-08-05T02:00:00Z", "2026-08-05T06:00:00Z"
        )
        return ctx

    def test_completing_before_the_run_starts_is_refused_and_the_completed_run_locks(
        self,
    ):
        """Completing a SCHEDULED run is refused with ERR_INVALID_STATE and leaves its
        measurements null; once started and completed the run grades PASS, publishes the
        package's measured_load_kw, and a late abort is refused with ERR_INVALID_STATE
        without touching the recorded result.

        PRD: "Completing a run is permitted only from `RUNNING`, advances it `RUNNING →
        COMPLETED`, and records `measured_kw` and `measured_return_delta_t_f`."
        PRD: "Starting, completing or aborting a run outside its declared from-state is
        refused with `ERR_INVALID_STATE`."
        PRD: "Completion then re-derives the parent package's `measured_load_kw` as the
        highest `measured_kw` among that package's `COMPLETED` runs, and the run stops
        occupying the hall's reserve window."

        Design: Corner/state_machines/load_bank_test_out_of_order_and_post_terminal_calls_rejected
        """
        ctx = self._hall_with_scheduled_run("CX38")
        run_id = ctx["run"]["id"]
        assert ctx["run"]["status"] == "SCHEDULED"

        validate_error(
            api_client.complete_load_bank_test(
                run_id, {"measured_kw": 10.00, "measured_return_delta_t_f": 12.0}, CA
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        untouched = read_load_bank_test(run_id)
        assert untouched["status"] == "SCHEDULED"
        assert untouched["measured_kw"] is None
        assert untouched["measured_return_delta_t_f"] is None
        assert untouched["result"] is None

        set_clock("2026-08-05T03:00:00Z")
        started = validate_success(api_client.start_load_bank_test(run_id, CA), 200)
        assert started["status"] == "RUNNING"

        completed = validate_success(
            api_client.complete_load_bank_test(
                run_id, {"measured_kw": 10.00, "measured_return_delta_t_f": 12.0}, CA
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["measured_kw"] == pytest.approx(10.00, abs=0.005)
        assert completed["measured_return_delta_t_f"] == pytest.approx(12.0, abs=0.05)
        assert completed["result"] == "PASS"
        assert read_package(ctx["package_id"])["measured_load_kw"] == pytest.approx(
            10.00, abs=0.005
        )

        validate_error(
            api_client.abort_load_bank_test(
                run_id, {"abort_reason": "Late cancellation attempt."}, CA
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        final = read_load_bank_test(run_id)
        assert final["status"] == "COMPLETED", "COMPLETED is terminal"
        assert final["result"] == "PASS"
        assert final["abort_reason"] is None
        assert final["measured_kw"] == pytest.approx(10.00, abs=0.005)

    def test_an_aborted_run_refuses_both_start_and_complete(self):
        """Aborting a SCHEDULED run is permitted, records the reason and leaves
        measured_kw null; the aborted row is terminal, so starting it inside its window
        and completing it are both refused with ERR_INVALID_STATE and the parent package
        never publishes a measured load.

        PRD: "Aborting is permitted from either `SCHEDULED` or `RUNNING`, drives the run
        to `ABORTED`, records the supplied `abort_reason`, leaves `measured_kw` null, and
        frees both the run's reserve slice and its concurrency slot; `COMPLETED` and
        `ABORTED` are the two terminal states of a run."
        PRD: "Starting, completing or aborting a run outside its declared from-state is
        refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/load_bank_test_out_of_order_and_post_terminal_calls_rejected
        """
        ctx = self._hall_with_scheduled_run("CX38B")
        run_id = ctx["run"]["id"]

        aborted = validate_success(
            api_client.abort_load_bank_test(
                run_id, {"abort_reason": "Crew stood down."}, CA
            ),
            200,
        )
        assert aborted["status"] == "ABORTED"
        assert aborted["abort_reason"] == "Crew stood down."
        assert aborted["measured_kw"] is None
        assert aborted["result"] is None

        set_clock("2026-08-05T03:00:00Z")
        validate_error(
            api_client.start_load_bank_test(run_id, CA),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        validate_error(
            api_client.complete_load_bank_test(
                run_id, {"measured_kw": 10.00, "measured_return_delta_t_f": 12.0}, CA
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )

        final = read_load_bank_test(run_id)
        assert final["status"] == "ABORTED"
        assert final["measured_kw"] is None
        assert final["result"] is None
        assert read_package(ctx["package_id"])["measured_load_kw"] is None, (
            "only a COMPLETED run publishes a measured load"
        )


class TestRejectedMopIsTerminal:
    """A REJECT decision closes change control on that method of procedure for good."""

    def _rejected_mop(self, code):
        ctx = setup_planning_hall(code)
        mop = create_mop(
            ctx["hall_id"],
            "BUSWAY",
            ctx["bw_a"]["id"],
            title="Trunk torque check",
            risk_class="MEDIUM",
            backout_plan="Re-torque and re-close the tap box.",
            window_start="2026-08-10T02:00:00Z",
            window_end="2026-08-10T06:00:00Z",
            author_user_id="u-elec-1",
        )
        submit_mop(mop["id"], "u-elec-1")
        ctx["mop_id"] = mop["id"]
        ctx["rejected"] = approve_mop(
            mop["id"],
            role_headers=CM,
            user_id="u-cm-1",
            decision="REJECT",
            comment="Backout plan does not cover the B feed.",
        )
        return ctx

    def test_an_approve_after_a_reject_is_refused_and_appends_no_record(self):
        """The REJECT drives the MOP to REJECTED with no quorum credit, and a later
        APPROVE from an independent operations manager is refused with ERR_INVALID_STATE,
        leaving the immutable approval trail at its single REJECT row.

        PRD: "A `REJECT` appends its record and moves the MOP `UNDER_REVIEW → REJECTED`,
        which is terminal."
        PRD: "**Declared from-state (`ERR_INVALID_STATE`, 409)** — the addressed row sits
        in a state from which the requested transition is declared."
        PRD: "`REJECT` and `REQUEST_REVISION` records never count toward a quorum."

        Design: Corner/state_machines/mop_approvals_after_reject_rejected
        """
        ctx = self._rejected_mop("CX39")
        assert ctx["rejected"]["status"] == "REJECTED"
        assert ctx["rejected"]["approval_count"] == 0, (
            "a REJECT decision credits no quorum vote"
        )

        validate_error(
            api_client.create_mop_approval(
                ctx["mop_id"], {"decision": "APPROVE", "comment": "Reconsidered."}, OM
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )

        after = read_mop(ctx["mop_id"])
        assert after["status"] == "REJECTED"
        assert after["approval_count"] == 0
        assert after["required_approval_count"] == 1, "MEDIUM risk needs one vote"

        rows, meta = validate_paginated(
            api_client.list_mop_approvals(ctx["mop_id"], CM)
        )
        assert meta["total_count"] == 1, "the refused decision appended no record"
        assert rows[0]["decision"] == "REJECT"
        assert rows[0]["sequence"] == 1
        assert rows[0]["approver_role"] == "ChangeManager"
        assert rows[0]["approver_user_id"] == "u-cm-1"
        assert rows[0]["mop_id"] == ctx["mop_id"]

        hall = read_hall(ctx["hall_id"])
        assert hall["open_mop_count"] == 0, "a rejected MOP occupies no window"
        assert hall["release_posture"] == "OPEN"

    def test_a_revision_request_and_a_schedule_after_a_reject_are_refused(self):
        """Neither a further REQUEST_REVISION decision nor a schedule attempt can revive a
        REJECTED method of procedure: both are refused with ERR_INVALID_STATE and the MOP
        keeps its revision count, its null execution stamps and its single approval row.

        PRD: "A `REJECT` appends its record and moves the MOP `UNDER_REVIEW → REJECTED`,
        which is terminal."
        PRD: "**Scheduling** is the `ChangeManager`'s exclusive act and advances an
        approved MOP `APPROVED → SCHEDULED`."
        PRD: "**Declared from-state (`ERR_INVALID_STATE`, 409)** — the addressed row sits
        in a state from which the requested transition is declared."

        Design: Corner/state_machines/mop_approvals_after_reject_rejected
        """
        ctx = self._rejected_mop("CX39B")

        validate_error(
            api_client.create_mop_approval(
                ctx["mop_id"],
                {"decision": "REQUEST_REVISION", "comment": "Please redo the plan."},
                CM2,
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        validate_error(
            api_client.schedule_mop(ctx["mop_id"], {}, CM),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )

        after = read_mop(ctx["mop_id"])
        assert after["status"] == "REJECTED"
        assert after["revision_count"] == 0
        assert after["executed_at"] is None
        assert after["closed_at"] is None
        assert after["pre_execution_target_state"] is None

        rows, meta = validate_paginated(
            api_client.list_mop_approvals(ctx["mop_id"], CM)
        )
        assert meta["total_count"] == 1
        assert rows[0]["decision"] == "REJECT"

        hall = read_hall(ctx["hall_id"])
        assert hall["open_mop_count"] == 0
        assert hall["release_posture"] == "OPEN"


class TestHallBubblesUpToLive:
    """Nobody requests the last phase step: the hall walks into LIVE by itself once the
    L4 and L5 packages are certified."""

    def test_only_the_certified_l4_and_l5_pair_bubbles_the_hall_up_to_live(self):
        """A certified L1 alone leaves the hall in COMMISSIONING, adding a certified L4
        still leaves it there because the level set lacks L5, and the L5 witness decision
        is what flips the hall to LIVE with its ledger and posture re-derived.

        PRD: "`COMMISSIONING → LIVE` is evaluated by the system after **every**
        commissioning-package witness decision, and it fires when three conditions hold
        together: the hall has at least one commissioning package whose `package_state`
        is anything other than `SUPERSEDED`; every one of those non-superseded packages
        stands at `CERTIFIED`; and the set of commissioning levels among them includes
        both `L4` and `L5`."
        PRD: "A hall with a single certified `L1` package does not go live; a hall whose
        `L4` package is certified but whose `L5` package is still `IN_EXECUTION` does not
        go live either."
        PRD: "if the hall has at least one MOP whose status is `IN_EXECUTION`,
        `release_posture` is `LOCKED`; otherwise, if the hall's `at_risk_rack_count` is
        greater than 0 **or** its `thermal_posture` is anything other than `NOMINAL`, the
        posture is `RESTRICTED`; otherwise it is `OPEN`."

        Design: Corner/state_machines/hall_bubbles_up_to_live_when_l4_and_l5_certify
        """
        ctx = setup_commissioning_hall("CX40")

        pkg_l1 = certify_package(ctx["hall_id"], "L1", target_load_kw=10.00)
        assert pkg_l1["package_state"] == "CERTIFIED"
        assert read_hall(ctx["hall_id"])["status"] == "COMMISSIONING", (
            "one certified L1 package does not carry a hall into LIVE"
        )

        pkg_l4 = certify_package(
            ctx["hall_id"],
            "L4",
            target_load_kw=10.00,
            window_start="2026-08-05T02:00:00Z",
            window_end="2026-08-05T06:00:00Z",
            clock_inside="2026-08-05T03:00:00Z",
        )
        assert pkg_l4["package_state"] == "CERTIFIED"
        assert read_hall(ctx["hall_id"])["status"] == "COMMISSIONING", (
            "the level set still lacks L5"
        )

        pkg_l5 = certify_package(
            ctx["hall_id"],
            "L5",
            target_load_kw=10.00,
            window_start="2026-08-06T02:00:00Z",
            window_end="2026-08-06T06:00:00Z",
            clock_inside="2026-08-06T03:00:00Z",
        )
        assert pkg_l5["package_state"] == "CERTIFIED"

        hall = read_hall(ctx["hall_id"])
        assert hall["status"] == "LIVE", "the L4/L5 pair fires the system transition"
        assert hall["release_posture"] == "OPEN"
        assert hall["thermal_posture"] == "NOMINAL"
        assert hall["open_mop_count"] == 0
        assert hall["at_risk_rack_count"] == 0
        assert hall["committed_kw"] == pytest.approx(15.00, abs=0.005)
        assert hall["commissioning_reserve_kw"] == pytest.approx(25.00, abs=0.005)
        assert hall["spare_kw"] == pytest.approx(360.00, abs=0.005)
        assert hall["chargeable_kw"] == pytest.approx(15.68, abs=0.005)
        assert_hall_power_ledger_balances(hall)
        assert read_package(pkg_l1["id"])["package_state"] == "CERTIFIED"
        assert read_package(pkg_l4["id"])["package_state"] == "CERTIFIED"

    def test_the_witness_decision_fires_the_transition_and_live_is_then_terminal(self):
        """With the L4 certified and the L5 sitting at IN_EXECUTION the hall stays in
        COMMISSIONING; the L5 witness signature certifies the package, bumps the hall
        version and turns it LIVE, after which the phase capability refuses both LIVE and
        a step back to COMMISSIONING.

        PRD: "`WITNESSED` sets `witness_status` to `WITNESSED`, stamps
        `witnessed_by_user_id` with the acting `X-User-ID`, brings `package_state` to
        `CERTIFIED`, and then triggers the hall's evaluation for going live described in
        §3.1 — incrementing the hall's `version` when that transition actually fires."
        PRD: "A hall walks `PLANNING → FIT_OUT → COMMISSIONING → LIVE`, and `LIVE` is
        terminal."
        PRD: "`LIVE` is never accepted from this capability at all; naming a
        non-successor, naming a phase the hall has already passed, or naming `LIVE` is
        rejected with `ERR_HALL_PHASE_INVALID`."

        Design: Corner/state_machines/hall_bubbles_up_to_live_when_l4_and_l5_certify
        """
        ctx = setup_commissioning_hall("CX40B")
        certify_package(
            ctx["hall_id"],
            "L4",
            target_load_kw=10.00,
            window_start="2026-08-05T02:00:00Z",
            window_end="2026-08-05T06:00:00Z",
            clock_inside="2026-08-05T03:00:00Z",
        )
        package = create_package(ctx["hall_id"], "L5", target_load_kw=10.00)
        approve_script(package["id"], 1)
        run_passing_load_bank(
            package["id"],
            target_kw=10.00,
            window_start="2026-08-06T02:00:00Z",
            window_end="2026-08-06T06:00:00Z",
            clock_inside="2026-08-06T03:00:00Z",
        )
        in_execution = execute_script(package["id"], "u-ca-1")
        assert in_execution["package_state"] == "IN_EXECUTION"
        before = read_hall(ctx["hall_id"])
        assert before["status"] == "COMMISSIONING", (
            "an L5 still in execution does not carry the hall over"
        )

        certified = witness_package(package["id"], "WITNESSED", "u-wa-1")
        assert certified["witness_status"] == "WITNESSED"
        assert certified["witnessed_by_user_id"] == "u-wa-1"
        assert certified["package_state"] == "CERTIFIED"

        hall = read_hall(ctx["hall_id"])
        assert hall["status"] == "LIVE"
        assert hall["version"] == before["version"] + 1, (
            "the witness decision that fires the transition bumps the hall version"
        )

        validate_error(
            api_client.advance_hall_phase(
                ctx["hall_id"], {"target_status": "LIVE"}, FP
            ),
            ApiErrorId.ERR_HALL_PHASE_INVALID.value,
            409,
        )
        validate_error(
            api_client.advance_hall_phase(
                ctx["hall_id"], {"target_status": "COMMISSIONING"}, FP
            ),
            ApiErrorId.ERR_HALL_PHASE_INVALID.value,
            409,
        )
        after = read_hall(ctx["hall_id"])
        assert after["status"] == "LIVE", "LIVE is terminal"
        assert after["version"] == hall["version"], "the refusals wrote nothing"


class TestReleaseAcceptanceReleasesRacksAndCage:
    """Acceptance is the only place custody changes hands, and once it has happened the
    packet is closed to any further decision."""

    def _submitted_packet(self, code, tenant_code):
        tenant = create_tenant(
            tenant_code,
            contracted_kw=100.00,
            contract_start_date="2026-01-01T00:00:00Z",
        )
        ctx = setup_fit_out_hall(code)
        ctx["tenant"] = tenant
        ctx["tenant_id"] = tenant["id"]
        cage_ctx = setup_secured_cage(
            ctx["hall_id"],
            tenant["id"],
            label="CG-1",
            perimeter_length_m=40.0,
            camera_coverage_m=38.0,
            reader_zones=("Z-N", "Z-S"),
        )
        ctx.update(cage_ctx)
        prove_zone_and_cooling(ctx)
        add_powered_rack(
            ctx,
            design_kw=15.00,
            asset_tag="AT-0001",
            cage_id=cage_ctx["cage_id"],
            tenant_id=tenant["id"],
        )
        advance_phase(ctx["hall_id"], "COMMISSIONING")
        certify_package(
            ctx["hall_id"],
            "L4",
            target_load_kw=10.00,
            window_start="2026-08-05T02:00:00Z",
            window_end="2026-08-05T06:00:00Z",
            clock_inside="2026-08-05T03:00:00Z",
        )
        certify_package(
            ctx["hall_id"],
            "L5",
            target_load_kw=10.00,
            window_start="2026-08-06T02:00:00Z",
            window_end="2026-08-06T06:00:00Z",
            clock_inside="2026-08-06T03:00:00Z",
        )
        packet = create_packet(ctx["hall_id"], cage_ctx["cage_id"], "AB-CX41-R1")
        ctx["packet"] = submit_packet(packet["id"])
        ctx["packet_id"] = packet["id"]
        return ctx

    def test_acceptance_releases_the_powered_rack_and_the_cage_without_moving_custody(
        self,
    ):
        """The operations manager's acceptance stamps the packet, drives the cage's single
        POWERED rack to RELEASED and the cage SECURED -> RELEASED, bumps the cage version,
        and leaves the custody partition exactly where it stood because both statuses sit
        on the operations side.

        PRD: "**Acceptance** is the `OperationsManager`'s act and advances a packet
        `SUBMITTED → ACCEPTED`."
        PRD: "The packet's status becomes `ACCEPTED` and `accepted_by_user_id` is stamped
        with the accepting manager's `X-User-ID`. Every rack of the cage at `POWERED`
        moves `POWERED → RELEASED`. The cage itself moves `SECURED → RELEASED`."
        PRD: "because both `POWERED` and `RELEASED` sit on the operations side of the
        partition, `custody_ops_count` and `custody_fitout_count` do not move at all when
        racks are released"
        PRD: "`released_kw` is the cage-restricted branch of the chargeable roll-up of
        §3.4: each in-scope rack's `design_kw` multiplied by 1.045 and rounded to two
        decimal places **first**, then summed, then rounded to two decimal places again."

        Design: Corner/state_machines/release_packet_accept_releases_racks_and_cage_then_locks
        """
        ctx = self._submitted_packet("CX41", "CXT41")
        submitted = ctx["packet"]
        assert submitted["status"] == "SUBMITTED"
        assert submitted["rack_in_scope_count"] == 1
        assert submitted["released_kw"] == pytest.approx(15.68, abs=0.005)
        assert submitted["asset_tag_completion_pct"] == pytest.approx(100.00, abs=0.005)
        assert submitted["accepted_by_user_id"] is None

        before_hall = read_hall(ctx["hall_id"])
        assert before_hall["status"] == "LIVE"
        assert before_hall["release_posture"] == "OPEN"
        assert before_hall["custody_ops_count"] == 1
        assert before_hall["custody_fitout_count"] == 0
        cage_version_before = read_cage(ctx["cage_id"])["version"]

        accepted = accept_packet(ctx["packet_id"], "u-om-1")
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_by_user_id"] == "u-om-1"
        assert accepted["rejected_reason"] is None
        assert accepted["released_kw"] == pytest.approx(15.68, abs=0.005)

        rack = read_rack(ctx["rack_1"]["id"])
        assert rack["status"] == "RELEASED"
        assert rack["asset_tag"] == "AT-0001"
        assert rack["energized_feed_count"] == rack["required_feed_count"]

        cage = read_cage(ctx["cage_id"])
        assert cage["operational_status"] == "RELEASED"
        assert cage["version"] == cage_version_before + 1

        hall = read_hall(ctx["hall_id"])
        assert hall["custody_ops_count"] == 1, "a released rack stays on the ops side"
        assert hall["custody_fitout_count"] == 0
        assert hall["rack_total_count"] == 1
        assert hall["chargeable_kw"] == pytest.approx(15.68, abs=0.005)
        assert_custody_partition(hall)

    def test_an_accepted_packet_takes_no_further_decision(self):
        """Both decisions are declared out of SUBMITTED only, so once custody has been
        taken a rejection and a second acceptance are refused with ERR_INVALID_STATE, and
        the packet, the rack and the cage all stay exactly as the handover left them.

        PRD: "**Rejection** advances a packet `SUBMITTED → REJECTED` on the
        `OperationsManager`'s word, recording the supplied `rejected_reason`."
        PRD: "**Acceptance** is the `OperationsManager`'s act and advances a packet
        `SUBMITTED → ACCEPTED`."
        PRD: "**Declared from-state (`ERR_INVALID_STATE`, 409)** — the addressed row sits
        in a state from which the requested transition is declared."

        Design: Corner/state_machines/release_packet_accept_releases_racks_and_cage_then_locks
        """
        ctx = self._submitted_packet("CX41B", "CXT41B")
        accept_packet(ctx["packet_id"], "u-om-1")

        validate_error(
            api_client.reject_release_packet(
                ctx["packet_id"], {"rejected_reason": "drawings were stale"}, OM
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )
        validate_error(
            api_client.accept_release_packet(ctx["packet_id"], OM),
            ApiErrorId.ERR_INVALID_STATE.value,
            409,
        )

        packet = read_packet(ctx["packet_id"])
        assert packet["status"] == "ACCEPTED"
        assert packet["rejected_reason"] is None, "the refused rejection stored no reason"
        assert packet["accepted_by_user_id"] == "u-om-1"
        assert packet["supersedes_packet_id"] is None

        assert read_rack(ctx["rack_1"]["id"])["status"] == "RELEASED"
        assert read_cage(ctx["cage_id"])["operational_status"] == "RELEASED"
        hall = read_hall(ctx["hall_id"])
        assert hall["status"] == "LIVE"
        assert hall["custody_ops_count"] == 1
        assert_custody_partition(hall)
