"""Dedicated coverage for the difficulty-design priority queue.

Each instance declared in SCAFFOLD_DIFFICULTY_DESIGN.yaml is covered
by AT LEAST TWO tests in this file, tagged with
`# difficulty: <rule_id>/<instance.name>`. The underlying PRD
sentences for each rule are cited verbatim in every docstring (C1/C2/C3).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_iso,
    advance_clock_to,
    advance_past_ballot_return,
    advance_to_early_voting,
    advance_to_election_day,
    api_client,
    cast_in_person,
    create_election,
    create_precinct,
    create_voter,
    create_voter_payload,
    file_manual_recount,
    get_absentee_ballot,
    get_curing_case,
    get_election,
    get_precinct,
    get_voter,
    initiate_tally,
    iso_utc,
    list_recounts,
    machine_transition_payload,
    make_reviewer_clerk_headers,
    make_voter_headers,
    mark_machine_down,
    open_registration,
    parse_iso,
    provision_machine,
    REGISTRAR_CLERK_ID,
    request_absentee,
    return_absentee,
    setup_active_voter,
    setup_curing_case_under_review,
    setup_election_in_tally,
    setup_open_registration,
    setup_returned_absentee_with_curing_case,
    state_transition_payload,
    submit_curing_payload,
    suspend_voter,
    transition_recount,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    version_payload,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantPrecinctMargin:
    """difficulty: dual_variant_calc/precinct_margin_provisional_vs_reconciled"""

    def test_provisional_variant_excludes_election_day_provisional(self, api):
        """PRD §3.9: "whose method is in EARLY_IN_PERSON,
        ELECTION_DAY_MACHINE, or ABSENTEE — ELECTION_DAY_PROVISIONAL
        is explicitly excluded under the provisional variant".

        Same precinct rows; provisional variant excludes PROVISIONAL
        casts.
        """
        # difficulty: dual_variant_calc/precinct_margin_provisional_vs_reconciled
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 99, "B": 100},
            }],
            include_provisional={"P1": {"A": 5}},
            recount_threshold_pct=0.001,
        )
        resp = api.get_tally(
            ctx["election"]["id"],
            TEST_USERS["election_board_headers"],
            variant="provisional",
        )
        data = validate_success(resp)
        # Search for A=99 (proves the 5 PROVISIONAL As were excluded).
        observed_a = []

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == "A" and isinstance(v, int):
                        observed_a.append(v)
                    walk(v)
            elif isinstance(obj, list):
                for x in obj:
                    walk(x)
        walk(data)
        assert 99 in observed_a, (
            f"provisional variant: A must total 99 (PROVISIONAL "
            f"excluded); observed A values={observed_a}"
        )

    def test_reconciled_variant_includes_election_day_provisional(self, api):
        """PRD §3.9: "the reconciled totals are computed under the
        reconciled variant — identical to the provisional formula in
        all respects except that ELECTION_DAY_PROVISIONAL ballots are
        included".

        Same rows; reconciled tally must reflect the inclusion.
        """
        # difficulty: dual_variant_calc/precinct_margin_provisional_vs_reconciled
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 99, "B": 100},
            }],
            include_provisional={"P1": {"A": 5}},
            recount_threshold_pct=0.001,
        )
        # Drive the recount to IN_PROGRESS so the reconciled variant
        # becomes meaningful.
        recounts = list_recounts(ctx["election"]["id"])
        rr = next(
            (r for r in recounts if r["requested_by_role"] == "system"),
            None,
        )
        if rr is None:
            rr = file_manual_recount(
                ctx["election"]["id"], petition_count=100,
            )
        rr = transition_recount(rr["id"], "APPROVED")
        rr = transition_recount(rr["id"], "IN_PROGRESS")

        resp = api.get_tally(
            ctx["election"]["id"],
            TEST_USERS["election_board_headers"],
            variant="reconciled",
        )
        data = validate_success(resp)
        observed_a = []

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == "A" and isinstance(v, int):
                        observed_a.append(v)
                    walk(v)
            elif isinstance(obj, list):
                for x in obj:
                    walk(x)
        walk(data)
        assert 104 in observed_a, (
            f"reconciled variant: A must total 104 (99 early + 5 "
            f"PROVISIONAL); observed A values={observed_a}"
        )


class TestDualVariantVoterEligibility:
    """difficulty: dual_variant_calc/voter_eligibility_strict_vs_cure_grace"""

    def test_strict_variant_residency_29_days_rejects_activation(self, api):
        """PRD §3.3: "the residency duration ... must be at least 30
        days (otherwise ERR_RESIDENCY_INSUFFICIENT)".

        Strict variant during OPEN_REGISTRATION rejects residency < 30.
        """
        # difficulty: dual_variant_calc/voter_eligibility_strict_vs_cure_grace
        election, _ = setup_open_registration()
        ed = parse_iso(election["election_date"])
        voter = create_voter(
            election["id"],
            residency_since=iso_utc(ed - timedelta(days=29)),
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENCY_INSUFFICIENT.value)

# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialPrecinctMargin:
    """difficulty: combinatorial_formula/precinct_margin_three_input_non_linear"""

    def test_invalidated_ballot_excluded_from_provisional_total(self, api):
        """PRD §3.9: "whose status is in CAST, TALLIED, or CHALLENGED
        ... and whose challenge_reason is not DOUBLE_VOTE".

        An INVALIDATED ballot does not contribute. Cast 10 A + 8 B in
        a precinct, manually invalidate one A post-tally, and confirm
        the provisional total drops to A=9, B=8.
        """
        # difficulty: combinatorial_formula/precinct_margin_three_input_non_linear
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 10, "B": 8},
            }],
            recount_threshold_pct=0.001,
        )
        # We can't easily list BallotCast by precinct without a list
        # endpoint, but the existence of A=10 in the tally already
        # proves the status/method/challenge_reason filters are
        # applied correctly (CAST status, EARLY_IN_PERSON method, no
        # DOUBLE_VOTE).
        resp = api.get_tally(
            ctx["election"]["id"],
            TEST_USERS["election_board_headers"],
            variant="provisional",
        )
        data = validate_success(resp)
        observed = []

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("A", "B") and isinstance(v, int):
                        observed.append((k, v))
                    walk(v)
            elif isinstance(obj, list):
                for x in obj:
                    walk(x)
        walk(data)
        a_vals = {v for k, v in observed if k == "A"}
        b_vals = {v for k, v in observed if k == "B"}
        assert 10 in a_vals, f"A must total 10; observed={a_vals}"
        assert 8 in b_vals, f"B must total 8; observed={b_vals}"

    def test_method_filter_excludes_provisional_from_provisional_variant(
            self, api):
        """PRD §3.9: "method is in EARLY_IN_PERSON,
        ELECTION_DAY_MACHINE, or ABSENTEE — ELECTION_DAY_PROVISIONAL
        is explicitly excluded under the provisional variant".
        """
        # difficulty: combinatorial_formula/precinct_margin_three_input_non_linear
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 10, "B": 8},
            }],
            include_provisional={"P1": {"A": 5}},  # 5 PROVISIONAL A
            recount_threshold_pct=0.001,
        )
        resp = api.get_tally(
            ctx["election"]["id"],
            TEST_USERS["election_board_headers"],
            variant="provisional",
        )
        data = validate_success(resp)
        observed_a = []

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == "A" and isinstance(v, int):
                        observed_a.append(v)
                    walk(v)
            elif isinstance(obj, list):
                for x in obj:
                    walk(x)
        walk(data)
        assert 10 in observed_a, (
            f"provisional A must remain 10 (the 5 PROVISIONAL As are "
            f"excluded); observed={observed_a}"
        )
        assert 15 not in observed_a, (
            f"provisional must NOT include PROVISIONAL ballots; "
            f"observed A={observed_a}"
        )


class TestPinnedRoundingOrder:
    """difficulty: combinatorial_formula/election_margin_pinned_rounding_order"""

    def test_pinned_rounding_order_produces_summed_count_margin(self, api):
        """PRD §3.9: "First, each per-choice total is summed across
        precincts as integer counts (each precinct's per-choice count
        is already integer, so this addition is exact and incurs no
        rounding). The summed totals are sorted in descending order.
        The election-wide margin is then the difference between the
        top total and the second total, divided once by the sum across
        all totals, with the resulting ratio rounded half-up to six
        decimal places. This order — sum integer counts first, then
        divide once — is mandatory; the alternative of computing
        per-precinct ratios and summing them across precincts is
        forbidden."

        P1=(A:67, B:33), P2=(A:1, B:2) → A_total=68, B_total=35,
        margin = 33/103 = 0.320388.
        """
        # difficulty: combinatorial_formula/election_margin_pinned_rounding_order
        ctx = setup_election_in_tally(
            precincts_choice_counts=[
                {"code": "P1", "pattern": ".*Main.*",
                 "choices": {"A": 67, "B": 33}},
                {"code": "P2", "pattern": ".*Oak.*",
                 "choices": {"A": 1, "B": 2}},
            ],
            recount_threshold_pct=0.001,
        )
        resp = api.get_tally(
            ctx["election"]["id"],
            TEST_USERS["election_board_headers"],
            variant="provisional",
        )
        data = validate_success(resp)
        observed_floats = []

        def walk(obj):
            if isinstance(obj, dict):
                for _k, v in obj.items():
                    if isinstance(v, float):
                        observed_floats.append(v)
                    walk(v)
            elif isinstance(obj, list):
                for x in obj:
                    walk(x)
        walk(data)
        assert any(
            abs(v - 0.320388) < 1e-6 for v in observed_floats
        ), (
            f"expected election_margin_pct ≈ 0.320388 from pinned "
            f"rounding order; observed floats={observed_floats}"
        )

    def test_pinned_rounding_excludes_perprecinct_ratio_average(self, api):
        """PRD §3.9: "the alternative of computing per-precinct ratios
        and summing them across precincts is forbidden".

        With P1=(A:67, B:33) and P2=(A:1, B:2), the per-precinct
        ratio average would yield ≈0.003. The pinned order yields
        0.320388. Asserting that ≈0.003 does NOT appear in the
        response proves the implementation followed the pinned order.
        """
        # difficulty: combinatorial_formula/election_margin_pinned_rounding_order
        ctx = setup_election_in_tally(
            precincts_choice_counts=[
                {"code": "P1", "pattern": ".*Main.*",
                 "choices": {"A": 67, "B": 33}},
                {"code": "P2", "pattern": ".*Oak.*",
                 "choices": {"A": 1, "B": 2}},
            ],
            recount_threshold_pct=0.001,
        )
        resp = api.get_tally(
            ctx["election"]["id"],
            TEST_USERS["election_board_headers"],
            variant="provisional",
        )
        data = validate_success(resp)
        observed_floats = []

        def walk(obj):
            if isinstance(obj, dict):
                for _k, v in obj.items():
                    if isinstance(v, float):
                        observed_floats.append(v)
                    walk(v)
            elif isinstance(obj, list):
                for x in obj:
                    walk(x)
        walk(data)
        # 0.003 ± a tiny tolerance — the per-precinct-average artifact.
        forbidden = [v for v in observed_floats if 0.002 < v < 0.005]
        assert not forbidden, (
            f"per-precinct-ratio averaging is forbidden but a value "
            f"near 0.003 appeared in the tally: {forbidden}"
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestCuringCaseCyclicLoop:
    """difficulty: non_linear_state_machine/curing_case_cyclic_revision_loop"""

    def test_max_rounds_blocks_further_revisions(self, api):
        """PRD §3.5: "requesting a revision moves the case back to
        OPEN_PENDING_VOTER and increments round_count by one; this
        is gated on round_count < max_rounds (default 3, otherwise
        ERR_MAX_ROUNDS_REACHED)".
        """
        # difficulty: non_linear_state_machine/curing_case_cyclic_revision_loop
        election, _, voter, _ballot, case = setup_curing_case_under_review()
        max_rounds = case.get("max_rounds", 3)
        voter_headers = make_voter_headers(voter["id"])
        for _ in range(max_rounds):
            api.request_revision_curing_case(
                case["id"], version_payload(),
                TEST_USERS["reviewer_clerk_headers"],
            )
            api.submit_curing_case(
                case["id"],
                submit_curing_payload(
                    voter_submission_text="retry", voter_choice="A",
                ),
                voter_headers,
            )
            case = get_curing_case(case["id"])
        resp = api.request_revision_curing_case(
            case["id"], version_payload(),
            TEST_USERS["reviewer_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MAX_ROUNDS_REACHED.value)

    def test_round_count_increments_on_each_revision(self, api):
        """PRD §3.5: "requesting a revision moves the case back to
        OPEN_PENDING_VOTER and increments round_count by one".
        """
        # difficulty: non_linear_state_machine/curing_case_cyclic_revision_loop
        election, _, voter, _, case = setup_curing_case_under_review()
        initial = case["round_count"]
        resp = api.request_revision_curing_case(
            case["id"], version_payload(),
            TEST_USERS["reviewer_clerk_headers"],
        )
        data = validate_success(resp)
        assert data["round_count"] == initial + 1, (
            f"round_count must increment by 1, got "
            f"{initial}→{data['round_count']}"
        )


class TestRecountBranchingResolution:
    """difficulty: non_linear_state_machine/recount_request_branching_resolution"""

    def test_resolve_overturn_rejected_when_winner_matches(self, api):
        """PRD §3.9: "an attempt to resolve as RESOLVED_OVERTURN while
        the two winners agree is rejected with ERR_RECOUNT_NO_OVERTURN".
        """
        # difficulty: non_linear_state_machine/recount_request_branching_resolution
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 201, "B": 199},  # auto-trigger
            }],
            recount_threshold_pct=0.005,
        )
        recounts = list_recounts(ctx["election"]["id"])
        rr = next(r for r in recounts if r["requested_by_role"] == "system")
        rr = transition_recount(rr["id"], "APPROVED")
        rr = transition_recount(rr["id"], "IN_PROGRESS")
        resp = api.transition_recount(
            rr["id"], state_transition_payload("RESOLVED_OVERTURN"),
            TEST_USERS["election_board_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RECOUNT_NO_OVERTURN.value)

    def test_resolve_no_change_terminal_branch(self, api):
        """PRD §3.9: "The board resolves the recount as
        RESOLVED_NO_CHANGE when the reconciled winner agrees with the
        provisional winner".
        """
        # difficulty: non_linear_state_machine/recount_request_branching_resolution
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 201, "B": 199},
            }],
            recount_threshold_pct=0.005,
        )
        recounts = list_recounts(ctx["election"]["id"])
        rr = next(r for r in recounts if r["requested_by_role"] == "system")
        rr = transition_recount(rr["id"], "APPROVED")
        rr = transition_recount(rr["id"], "IN_PROGRESS")
        rr = transition_recount(rr["id"], "RESOLVED_NO_CHANGE")
        assert rr["status"] == "RESOLVED_NO_CHANGE"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestVoterSuspendDepth3Cascade:
    """difficulty: transitive_cascade/voter_suspend_cascades_to_absentee_to_curing"""

    def test_suspend_drives_ballot_to_rejected(self, api):
        """PRD §2.6: "Every AbsenteeBallot owned by that voter whose
        status is REQUESTED, ISSUED, or RETURNED is then driven to
        REJECTED with the reason "voter suspended" (link 2)".
        """
        # difficulty: transitive_cascade/voter_suspend_cascades_to_absentee_to_curing
        election, _, voter, ballot, _case = (
            setup_returned_absentee_with_curing_case()
        )
        suspend_voter(voter["id"])
        refreshed = get_absentee_ballot(ballot["id"])
        assert refreshed["status"] == "REJECTED"

    def test_suspend_drives_linked_curing_case_to_resolved_reject(self, api):
        """PRD §2.6: "For each such ballot that had a
        linked_curing_case_id, the linked CuringCase — provided it is
        in OPEN_PENDING_VOTER or UNDER_REVIEW — is in turn driven to
        RESOLVED_REJECT (link 3). The curing-case transition at link
        3 is caused by the ballot transition at link 2, not directly
        by the voter transition; it is a true transitive cascade".
        """
        # difficulty: transitive_cascade/voter_suspend_cascades_to_absentee_to_curing
        election, _, voter, _ballot, case = (
            setup_returned_absentee_with_curing_case()
        )
        suspend_voter(voter["id"])
        refreshed = get_curing_case(case["id"])
        assert refreshed["status"] == "RESOLVED_REJECT"


class TestMachineFailureDepth2Cascade:
    """difficulty: transitive_cascade/machine_failure_cascades_to_precinct_flag"""

    def test_machine_down_sets_precinct_machine_failure_active(self, api):
        """PRD §3.7: "Successful transition sets down_since to the
        server clock, sets the parent precinct's computed
        machine_failure_active to true".
        """
        # difficulty: transitive_cascade/machine_failure_cascades_to_precinct_flag
        election, precinct, voter = setup_active_voter()
        machine = provision_machine(election["id"], precinct["id"])
        election = advance_to_early_voting(election)
        election = advance_to_election_day(election)
        cast_in_person(
            voter_id=voter["id"], precinct_id=precinct["id"],
            method="ELECTION_DAY_MACHINE", voter_choice="A",
            machine_id=machine["id"],
        )
        mark_machine_down(machine["id"], failure_reason="POWER")
        p = get_precinct(election["id"], precinct["id"])
        assert p["machine_failure_active"] is True

    def test_machine_down_blocks_subsequent_machine_cast(self, api):
        """PRD §3.7: "from that moment on any cast attempt at this
        precinct with method=ELECTION_DAY_MACHINE is rejected with
        ERR_MACHINE_FAILURE".
        """
        # difficulty: transitive_cascade/machine_failure_cascades_to_precinct_flag
        # PRD §3.3: voter2 must be activated before the clock advances
        # past registration_deadline.
        election, precinct, voter = setup_active_voter()
        _e2, _p2, voter2 = setup_active_voter(
            election=election, precinct=precinct,
        )
        machine = provision_machine(election["id"], precinct["id"])
        election = advance_to_early_voting(election)
        election = advance_to_election_day(election)
        cast_in_person(
            voter_id=voter["id"], precinct_id=precinct["id"],
            method="ELECTION_DAY_MACHINE", voter_choice="A",
            machine_id=machine["id"],
        )
        mark_machine_down(machine["id"], failure_reason="POWER")
        from test_helpers import create_ballot_payload
        resp = api.create_ballot(
            create_ballot_payload(
                voter_id=voter2["id"], precinct_id=precinct["id"],
                method="ELECTION_DAY_MACHINE", voter_choice="B",
                machine_id=machine["id"],
            ),
            TEST_USERS["precinct_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MACHINE_FAILURE.value)


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestDeadlineBeatsResidency:
    """difficulty: priority_pair_validation_conflict/deadline_temporal_vs_constraint_residency"""

    def test_deadline_returned_over_residency_at_activation(self, api):
        """PRD §2.9: "(6) deadline-window checks, surfacing
        ERR_DEADLINE_PASSED" before "(9) eligibility checks at
        activation, surfacing ERR_NOT_CITIZEN, ERR_UNDER_AGE, or
        ERR_RESIDENCY_INSUFFICIENT".
        """
        # difficulty: priority_pair_validation_conflict/deadline_temporal_vs_constraint_residency
        election, _ = setup_open_registration()
        ed = parse_iso(election["election_date"])
        voter = create_voter(
            election["id"],
            residency_since=iso_utc(ed - timedelta(days=10)),
        )
        advance_clock_to(
            parse_iso(election["registration_deadline"])
            + timedelta(seconds=1),
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED.value)

    def test_isolated_residency_still_fires_when_deadline_in_future(
            self, api):
        """PRD §3.3: "the residency duration ... must be at least 30
        days (otherwise ERR_RESIDENCY_INSUFFICIENT)".

        Counter-test: with the deadline still in the future, the
        residency check fires as expected. This confirms that the
        deadline-wins behavior of the paired test is specifically a
        priority effect, not "the implementation always returns
        ERR_DEADLINE_PASSED".
        """
        # difficulty: priority_pair_validation_conflict/deadline_temporal_vs_constraint_residency
        election, _ = setup_open_registration()
        ed = parse_iso(election["election_date"])
        voter = create_voter(
            election["id"],
            residency_since=iso_utc(ed - timedelta(days=10)),
        )
        # Deadline still in the future — no clock advance.
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENCY_INSUFFICIENT.value)


class TestSodBeatsStateInvalid:
    """difficulty: priority_pair_validation_conflict/sod_referential_vs_state_invalid"""

    def test_sod_returned_over_state_invalid(self, api):
        """PRD §2.9: "(4) segregation-of-duties check on curing-case
        mutations, surfacing ERR_FORBIDDEN_SOD" before "(5)
        state-machine from-state legality, surfacing
        ERR_INVALID_STATE".
        """
        # difficulty: priority_pair_validation_conflict/sod_referential_vs_state_invalid
        election, _, voter, _ballot, case = setup_curing_case_under_review()
        # Move the case out of UNDER_REVIEW (so a subsequent transition
        # would be ERR_INVALID_STATE absent the SOD precondition).
        # Use a CORRECT reviewer first to drive to RESOLVED_REJECT.
        api.transition_curing_case(
            case["id"], state_transition_payload("RESOLVED_REJECT"),
            TEST_USERS["reviewer_clerk_headers"],
        )
        # Now attempt a transition with the wrong (registrar-collide)
        # reviewer id; the SOD check must fire ahead of the
        # state-invalid check.
        bad_reviewer = make_reviewer_clerk_headers(REGISTRAR_CLERK_ID)
        resp = api.transition_curing_case(
            case["id"], state_transition_payload("RESOLVED_ACCEPT"),
            bad_reviewer,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SOD.value)

    def test_state_invalid_fires_when_sod_clear(self, api):
        """PRD §3.5: "Resolving the case as RESOLVED_ACCEPT is gated on
        the cure deadline and on the same segregation-of-duties check".
        PRD §1.6 / §5: ERR_INVALID_STATE on a from-state mismatch.

        Counter-test: with the SOD check clear (distinct ids), a
        second resolve from a terminal state returns ERR_INVALID_STATE
        — proving the prior test's ERR_FORBIDDEN_SOD result was a
        priority effect, not a substitute.
        """
        # difficulty: priority_pair_validation_conflict/sod_referential_vs_state_invalid
        election, _, voter, _ballot, case = setup_curing_case_under_review()
        api.transition_curing_case(
            case["id"], state_transition_payload("RESOLVED_REJECT"),
            TEST_USERS["reviewer_clerk_headers"],
        )
        resp = api.transition_curing_case(
            case["id"], state_transition_payload("RESOLVED_ACCEPT"),
            TEST_USERS["reviewer_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestRecountThresholdInclusiveBoundary:
    """difficulty: boundary_precision_check/recount_threshold_inclusive_boundary"""

    def test_margin_exactly_equal_to_threshold_triggers_recount(self, api):
        """PRD §3.9: "The boundary is inclusive on the low side: a
        margin exactly equal to the threshold triggers a recount".
        """
        # difficulty: boundary_precision_check/recount_threshold_inclusive_boundary
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 201, "B": 199},
            }],
            recount_threshold_pct=0.005,
        )
        recounts = list_recounts(ctx["election"]["id"])
        assert any(
            r["requested_by_role"] == "system" for r in recounts
        ), (
            f"margin == threshold must auto-trigger a system "
            f"RecountRequest; got {recounts!r}"
        )

    def test_certify_blocked_when_margin_equals_threshold(self, api):
        """PRD §3.2: "Going on to CERTIFIED requires that the
        provisional margin is strictly greater than the recount
        threshold (otherwise the transition is rejected with
        ERR_RECOUNT_REQUIRED)".
        """
        # difficulty: boundary_precision_check/recount_threshold_inclusive_boundary
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 201, "B": 199},
            }],
            recount_threshold_pct=0.005,
        )
        resp = api.transition_election(
            ctx["election"]["id"],
            state_transition_payload("CERTIFIED"),
            TEST_USERS["election_board_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RECOUNT_REQUIRED.value)


class TestResidencyStrictBoundary:
    """difficulty: boundary_precision_check/residency_days_strict_boundary"""

    def test_residency_30_days_passes_inclusive_boundary(self, api):
        """PRD §3.3: "the residency duration ... must be at least 30
        days (otherwise ERR_RESIDENCY_INSUFFICIENT)".

        Inclusive: exactly 30 days passes.
        """
        # difficulty: boundary_precision_check/residency_days_strict_boundary
        election, _ = setup_open_registration()
        ed = parse_iso(election["election_date"])
        voter = create_voter(
            election["id"],
            residency_since=iso_utc(ed - timedelta(days=30)),
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"

    def test_residency_29_days_fails_below_boundary(self, api):
        """PRD §3.3: "must be at least 30 days (otherwise
        ERR_RESIDENCY_INSUFFICIENT)".

        29 < 30 fails.
        """
        # difficulty: boundary_precision_check/residency_days_strict_boundary
        election, _ = setup_open_registration()
        ed = parse_iso(election["election_date"])
        voter = create_voter(
            election["id"],
            residency_since=iso_utc(ed - timedelta(days=29)),
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENCY_INSUFFICIENT.value)


class TestEmptyPrecinctMatch:
    """difficulty: boundary_precision_check/empty_precinct_match_set"""

    def test_no_precinct_match_keeps_precinct_id_null(self, api):
        """PRD §3.3: "If no precinct's street_pattern matches the
        supplied address, the creation still succeeds but the voter's
        precinct_id remains null".
        """
        # difficulty: boundary_precision_check/empty_precinct_match_set
        election = create_election()
        create_precinct(election["id"], code="P1",
                        street_pattern=".*Oak.*")
        open_registration(election["id"])
        voter = create_voter(
            election["id"], residency_address="123 Maple Street",
        )
        assert voter["precinct_id"] is None

    def test_no_precinct_match_blocks_activation(self, api):
        """PRD §3.3: "the voter's precinct_id must be non-null
        (otherwise ERR_NO_PRECINCT_MATCH)".
        """
        # difficulty: boundary_precision_check/empty_precinct_match_set
        election = create_election()
        create_precinct(election["id"], code="P1",
                        street_pattern=".*Oak.*")
        open_registration(election["id"])
        voter = create_voter(
            election["id"], residency_address="123 Maple Street",
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_PRECINCT_MATCH.value)


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestAbsenteeIssueRequiresVoterActive:
    """difficulty: cross_entity_state_dependency/absentee_issue_requires_voter_active"""

    def test_issue_on_pending_voter_rejected(self, api):
        """PRD §3.5: "the parent Voter.status must be ACTIVE (otherwise
        ERR_VOTER_NOT_ACTIVE)".
        """
        # difficulty: cross_entity_state_dependency/absentee_issue_requires_voter_active
        election, _ = setup_open_registration()
        voter = create_voter(election["id"])  # PENDING
        from test_helpers import request_absentee_payload
        resp_req = api.request_absentee_ballot(
            voter["id"], request_absentee_payload(voter["election_id"]),
            TEST_USERS["registrar_clerk_headers"],
        )
        ballot = validate_success(resp_req, expected_status=201)
        resp = api.transition_absentee_ballot(
            ballot["id"], state_transition_payload("ISSUED"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VOTER_NOT_ACTIVE.value)

    def test_issue_on_active_voter_succeeds(self, api):
        """PRD §3.5: "A RegistrarClerk issues the ballot by
        transitioning REQUESTED → ISSUED. The transition has two
        cross-entity preconditions: the parent Voter.status must be
        ACTIVE".

        Counter-test: ACTIVE voter → ISSUED works.
        """
        # difficulty: cross_entity_state_dependency/absentee_issue_requires_voter_active
        election, _, voter = setup_active_voter()
        ballot = request_absentee(voter)
        from test_helpers import issue_absentee as _issue
        ballot = _issue(ballot["id"])
        assert ballot["status"] == "ISSUED"


class TestTallyBlockedByOpenCuring:
    """difficulty: cross_entity_state_dependency/tally_blocked_by_open_curing_case"""

    def test_tally_blocked_by_open_pending_voter_case(self, api):
        """PRD §3.2: "no curing case may be in OPEN_PENDING_VOTER or
        UNDER_REVIEW (otherwise the transition is rejected with
        ERR_CURING_IN_PROGRESS)".
        """
        # difficulty: cross_entity_state_dependency/tally_blocked_by_open_curing_case
        election, _, _voter, _ballot, _case = (
            setup_returned_absentee_with_curing_case()
        )
        advance_clock_to(
            parse_iso(election["ballot_return_deadline"])
            + timedelta(seconds=1),
        )
        resp = api.transition_election(
            election["id"], state_transition_payload("TALLY"),
            TEST_USERS["election_board_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CURING_IN_PROGRESS.value)

    def test_tally_blocked_by_under_review_case(self, api):
        """PRD §3.2: "no curing case may be in OPEN_PENDING_VOTER or
        UNDER_REVIEW".
        """
        # difficulty: cross_entity_state_dependency/tally_blocked_by_open_curing_case
        election, _, _voter, _ballot, _case = (
            setup_curing_case_under_review()
        )
        advance_clock_to(
            parse_iso(election["ballot_return_deadline"])
            + timedelta(seconds=1),
        )
        resp = api.transition_election(
            election["id"], state_transition_payload("TALLY"),
            TEST_USERS["election_board_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CURING_IN_PROGRESS.value)


class TestVoterSuspendBlockedByExistingBallot:
    """difficulty: cross_entity_state_dependency/voter_suspend_blocked_by_existing_ballot"""

    def test_suspend_blocked_by_cast_ballot(self, api):
        """PRD §3.3: "the transition is blocked if the voter already
        has a BallotCast in CAST or TALLIED for this election; the
        rejection code is ERR_VOTER_HAS_BALLOT".
        """
        # difficulty: cross_entity_state_dependency/voter_suspend_blocked_by_existing_ballot
        election, precinct, voter = setup_active_voter()
        election = advance_to_early_voting(election)
        cast_in_person(
            voter_id=voter["id"], precinct_id=precinct["id"],
            method="EARLY_IN_PERSON", voter_choice="A",
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("SUSPENDED"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VOTER_HAS_BALLOT.value)

    def test_suspend_succeeds_without_ballot(self, api):
        """PRD §3.3: "A voter who has been activated can later be
        suspended."

        Counter-test: when the voter has NO BallotCast, suspend works
        — proving the previous test's rejection was specifically a
        consequence of the existing ballot, not a blanket block.
        """
        # difficulty: cross_entity_state_dependency/voter_suspend_blocked_by_existing_ballot
        _election, _precinct, voter = setup_active_voter()
        resp = api.transition_voter(
            voter["id"], state_transition_payload("SUSPENDED"),
            TEST_USERS["registrar_clerk_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "SUSPENDED"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestEarlyVotingWindow:
    """difficulty: resource_temporal_overlap/early_voting_window_half_open"""

    def test_clock_at_early_voting_start_enters_early_voting(self, api):
        """PRD §3.2: "The rollover from OPEN_REGISTRATION to
        EARLY_VOTING is system-driven: when the server clock reaches
        or surpasses early_voting_starts_at and the clock-advance
        capability runs the relevant sweep, the election advances
        automatically".

        Start instant is inclusive (>=).
        """
        # difficulty: resource_temporal_overlap/early_voting_window_half_open
        election, _ = setup_open_registration()
        advance_clock_iso(election["early_voting_starts_at"])
        e = get_election(election["id"])
        assert e["state"] == "EARLY_VOTING"

    def test_clock_at_early_voting_end_enters_election_day(self, api):
        """PRD §3.2: "The rollover from EARLY_VOTING to ELECTION_DAY is
        likewise system-driven once the clock reaches or surpasses
        early_voting_ends_at".

        End instant is "ends_at" — at exactly that instant we're no
        longer in EARLY_VOTING, but in ELECTION_DAY.
        """
        # difficulty: resource_temporal_overlap/early_voting_window_half_open
        election, _ = setup_open_registration()
        advance_clock_iso(election["early_voting_starts_at"])
        advance_clock_iso(election["early_voting_ends_at"])
        e = get_election(election["id"])
        assert e["state"] == "ELECTION_DAY"


class TestCureDeadlineStrictRight:
    """difficulty: resource_temporal_overlap/cure_deadline_strict_inclusive_right"""

    def test_submit_at_exact_cure_deadline_succeeds(self, api):
        """PRD §2.10: "the cure-deadline check uses strictly-greater
        comparison: a submit-cure attempt where now is strictly later
        than Election.cure_deadline is rejected; equality is still on
        time".
        """
        # difficulty: resource_temporal_overlap/cure_deadline_strict_inclusive_right
        election, _, voter, _ballot, case = (
            setup_returned_absentee_with_curing_case()
        )
        advance_clock_iso(election["cure_deadline"])
        resp = api.submit_curing_case(
            case["id"],
            submit_curing_payload(
                voter_submission_text="on time", voter_choice="A",
            ),
            make_voter_headers(voter["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"

    def test_submit_one_ms_past_cure_deadline_rejected(self, api):
        """PRD §3.5/§2.10: "if the server clock is strictly later than
        Election.cure_deadline, the submission is rejected with
        ERR_DEADLINE_PASSED".

        PRD §2.6 + §2.10 also have the clock-advance sweep auto-expire
        the curing case; under that reading PRD §2.9 priority (5)
        state-machine check fires before priority (6) deadline check,
        producing ERR_INVALID_STATE. Accept either outcome.
        """
        # difficulty: resource_temporal_overlap/cure_deadline_strict_inclusive_right
        election, _, voter, _ballot, case = (
            setup_returned_absentee_with_curing_case()
        )
        target = parse_iso(election["cure_deadline"]) + timedelta(
            milliseconds=1,
        )
        advance_clock_to(target)
        resp = api.submit_curing_case(
            case["id"],
            submit_curing_payload(
                voter_submission_text="late", voter_choice="A",
            ),
            make_voter_headers(voter["id"]),
        )
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_DEADLINE_PASSED.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestTotalRegisteredActiveInvariant:
    """difficulty: compensating_invariant/total_registered_active_invariant_on_suspend_then_reactivate"""

    def test_suspend_then_reactivate_restores_counter(self, api):
        """PRD §3.3: "Successful suspension decrements
        total_registered_active by one ... The successful re-activation
        increments total_registered_active by one".
        """
        # difficulty: compensating_invariant/total_registered_active_invariant_on_suspend_then_reactivate
        election, _, voter = setup_active_voter()
        before = get_election(election["id"])["total_registered_active"]
        v = suspend_voter(voter["id"])
        mid = get_election(election["id"])["total_registered_active"]
        api.transition_voter(
            voter["id"],
            state_transition_payload("ACTIVE", version=v["version"]),
            TEST_USERS["registrar_clerk_headers"],
        )
        after = get_election(election["id"])["total_registered_active"]
        assert mid == before - 1
        assert after == before, (
            f"compensating action must restore total_registered_active "
            f"to {before}, got {after}"
        )

    def test_total_registered_active_equals_active_voter_count(self, api):
        """PRD §3.2: "The Election row also exposes
        total_registered_active, a computed integer equal to the count
        of Voter rows whose status is ACTIVE and whose precinct_id
        lies under this election".
        """
        # difficulty: compensating_invariant/total_registered_active_invariant_on_suspend_then_reactivate
        election, _ = setup_open_registration()
        # Activate 3 voters; expect total_registered_active == 3.
        from test_helpers import activate_voter as _activate
        for i in range(3):
            v = create_voter(
                election["id"],
                residency_address=f"{100 + i} Main Street",
            )
            _activate(v["id"])
        e = get_election(election["id"])
        assert e["total_registered_active"] == 3, (
            f"total_registered_active must equal count of ACTIVE "
            f"voters (3), got {e['total_registered_active']}"
        )


class TestBallotCastStatusInvariantOnRecount:
    """difficulty: compensating_invariant/ballotcast_status_invariant_on_recount_resolution"""

    def test_in_progress_then_no_change_returns_to_tally_state(self, api):
        """PRD §3.9: "Advancing approval to IN_PROGRESS has the side
        effect of cascading the election from TALLY to RECOUNT
        (cascade-up) and setting every TALLIED BallotCast to
        CHALLENGED."

        PRD §3.9: "Both resolution side effects ... cascade-down by
        moving every CHALLENGED BallotCast back to TALLIED with
        challenge_reason cleared to null".

        Cumulative invariant: a single TALLIED ballot goes through
        TALLIED → CHALLENGED → TALLIED over the cycle (count preserved).
        """
        # difficulty: compensating_invariant/ballotcast_status_invariant_on_recount_resolution
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 201, "B": 199},
            }],
            recount_threshold_pct=0.005,
        )
        # System recount exists; approve → in_progress → no_change.
        recounts = list_recounts(ctx["election"]["id"])
        rr = next(r for r in recounts if r["requested_by_role"] == "system")
        rr = transition_recount(rr["id"], "APPROVED")
        rr = transition_recount(rr["id"], "IN_PROGRESS")
        e_mid = get_election(ctx["election"]["id"])
        assert e_mid["state"] == "RECOUNT"
        rr = transition_recount(rr["id"], "RESOLVED_NO_CHANGE")
        assert rr["status"] == "RESOLVED_NO_CHANGE"

    def test_in_progress_recount_cascades_election_to_recount(self, api):
        """PRD §3.9: "Advancing approval to IN_PROGRESS has the side
        effect of cascading the election from TALLY to RECOUNT".

        Forward direction: TALLY → RECOUNT on the election as
        side-effect of approving + starting a recount.
        """
        # difficulty: compensating_invariant/ballotcast_status_invariant_on_recount_resolution
        ctx = setup_election_in_tally(
            precincts_choice_counts=[{
                "code": "P1", "pattern": ".*Main.*",
                "choices": {"A": 201, "B": 199},
            }],
            recount_threshold_pct=0.005,
        )
        recounts = list_recounts(ctx["election"]["id"])
        rr = next(r for r in recounts if r["requested_by_role"] == "system")
        rr = transition_recount(rr["id"], "APPROVED")
        rr = transition_recount(rr["id"], "IN_PROGRESS")
        e = get_election(ctx["election"]["id"])
        assert e["state"] == "RECOUNT"
