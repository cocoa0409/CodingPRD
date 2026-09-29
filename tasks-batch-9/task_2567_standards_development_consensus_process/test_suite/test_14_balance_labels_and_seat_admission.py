"""
Who may sit on a committee and what the two balance bases make of them: a
provisional label that is not good enough to activate, the two roster guards on
an appointment, a disenfranchising edit that never touches the seat's state
machine, and the pair of verdicts stored side by side on one row.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestProvisionalIsNotBalanced:
    """Sitting exactly at the provisional ceiling still fails the activation guard."""

    def test_two_producers_of_three_seats_cannot_activate(self, api, staff_headers):
        """
        which is why two seats out of three in one category yields 66.7 and not 66.666…:
        that value is above the 50.0 limit and exactly at the 66.7 provisional limit, and
        equality passes.

        the freshly recomputed voting-basis verdict is `BALANCED`, failing which the request
        is refused with `ERR_COMMITTEE_NOT_BALANCED`

        Design: Corner/calculations/a_provisional_balance_label_at_exactly_the_dominance_ceiling_still_blocks_activation
        """
        scenario = fx.Scenario(api)
        scenario.register("p1")
        scenario.register("p5")
        scenario.register("p2")
        scenario.create_committee("p1")
        scenario.appoint("p1", "m1")
        scenario.appoint("p5", "m5")
        scenario.appoint("p2", "m2")

        before = scenario.get_committee()
        a.assert_voting_balance(
            before,
            balance_status="PROVISIONAL",
            active_member_count=3,
            distinct_category_count=2,
            dominance_pct=66.7,
            category_counts={"PRODUCER": 2, "USER": 1},
        )

        response = api.activate_committee(scenario.committee_id, staff_headers)
        validate_error(response, "ERR_COMMITTEE_NOT_BALANCED", 409)

        after = scenario.get_committee()
        assert after["status"] == "FORMING", (
            f"the refused activation left the committee FORMING, got {after['status']}"
        )
        assert after["balance_status"] == "PROVISIONAL", (
            "three seats and two categories reach provisional but no further, got "
            f"{after['balance_status']}"
        )
        a.assert_pct(after["dominance_pct"], 66.7)
        assert after["active_member_count"] == 3, (
            "the seat count was never the problem, got "
            f"{after['active_member_count']}"
        )
        assert after["distinct_category_count"] == 2, (
            f"distinct_category_count expected 2, got {after['distinct_category_count']}"
        )


class TestTheTwoRosterGuards:
    """One seat per participant, and one seat per employer, on any one committee."""

    def test_a_suspended_seat_still_blocks_a_second_appointment(self, api, staff_headers):
        """
        if the participant already holds a seat on this committee in `status` `ACTIVE` or
        `SUSPENDED`, the appointment is refused with `ERR_DUPLICATE_MEMBERSHIP` — a
        `WITHDRAWN` seat, by contrast, may be re-appointed

        Design: Corner/validations/re_appointing_a_sitting_participant_returns_duplicate_membership
        """
        scenario = fx.balanced_active_committee(api)
        scenario.patch_membership("m2", status="SUSPENDED")
        suspended_committee = scenario.get_committee()
        assert suspended_committee["status"] == "SUSPENDED", (
            "losing the USER seat drops the voting basis below balance, got "
            f"{suspended_committee['status']}"
        )

        response = api.create_membership(
            scenario.committee_id,
            f.membership_payload(scenario.pid("p2")),
            staff_headers,
        )
        validate_error(response, "ERR_DUPLICATE_MEMBERSHIP", 409)

        seats, meta = validate_paginated(
            api.list_memberships(
                scenario.staff, {"committee_id": scenario.committee_id}
            )
        )
        a.assert_total_count(meta, 3)
        assert len(seats) == 3, (
            f"no second seat was created for the same participant, got {len(seats)}"
        )
        seat = scenario.get_membership("m2")
        assert seat["status"] == "SUSPENDED", (
            f"the sitting seat is untouched by the refusal, got {seat['status']}"
        )
        after = scenario.get_committee()
        assert after["active_member_count"] == 2, (
            f"active_member_count expected 2, got {after['active_member_count']}"
        )
        assert after["roster_member_count"] == 3, (
            "the roster basis still counts the suspended seat, got "
            f"{after['roster_member_count']}"
        )

    def test_a_second_seat_for_the_same_employer_is_refused(self, api, staff_headers):
        """
        and if the participant carries a non-null `employer_affiliation_code` that some
        other `ACTIVE` or `SUSPENDED` seat on this same committee already carries, the
        appointment is refused with `ERR_AFFILIATION_ALREADY_REPRESENTED`, because one
        employer gets one seat.

        Design: Corner/validations/a_second_seat_for_the_same_employer_code_is_refused_on_the_same_committee
        """
        scenario = fx.balanced_active_committee(api)
        colleague = scenario.register(
            "p6",
            full_name="Ivo Regulator",
            organization="Acme Steel",
            interest_category="REGULATORY",
            employer_affiliation_code="ACME",
        )
        assert colleague["interest_category"] == "REGULATORY", (
            "the newcomer sits in a category nobody holds yet, got "
            f"{colleague['interest_category']}"
        )
        assert colleague["employer_affiliation_code"] == "ACME", (
            "but shares the chair's employer code, got "
            f"{colleague['employer_affiliation_code']}"
        )

        response = api.create_membership(
            scenario.committee_id,
            f.membership_payload(colleague["id"]),
            staff_headers,
        )
        validate_error(response, "ERR_AFFILIATION_ALREADY_REPRESENTED", 409)

        seats, meta = validate_paginated(
            api.list_memberships(
                scenario.staff, {"committee_id": scenario.committee_id}
            )
        )
        a.assert_total_count(meta, 3)
        after = scenario.get_committee()
        assert after["distinct_category_count"] == 3, (
            "no REGULATORY seat was added, got "
            f"{after['distinct_category_count']}"
        )
        assert after["balance_status"] == "BALANCED", (
            f"balance_status expected BALANCED, got {after['balance_status']}"
        )
        assert after["status"] == "ACTIVE", (
            f"the refusal left the committee working, got {after['status']}"
        )


class TestDisenfranchisingASeat:
    """A voting-rights edit never enters the seat's state machine, yet it cascades."""

    def test_removing_voting_rights_holds_the_open_ballot(self, api):
        """
        Every one of these edits recomputes both balance bases on the parent committee and
        re-derives the gate on every work item the committee sponsors, and every one of them
        leaves already-created ballots' `eligible_voter_count` untouched.

        Hop four, because those work items are now gated, sets `hold_reason` to
        `COMMITTEE_UNBALANCED` on every ballot of this committee whose `status` is `OPEN` —
        and a ballot bearing a hold cannot be closed.

        Design: Corner/endpoints/patching_only_voting_rights_leaves_the_seat_active_but_unbalances_the_committee
        """
        scenario = fx.open_subcommittee_ballot(api)
        before_ballot = scenario.get_ballot()
        assert before_ballot["hold_reason"] == "NONE", (
            f"the ballot starts unheld, got {before_ballot['hold_reason']}"
        )
        assert scenario.get_work_item()["consensus_gate"] == "OPEN", (
            "the gate is open before the seat edit"
        )

        seat = scenario.patch_membership("m3", voting_rights=False)

        assert seat["voting_rights"] is False, (
            f"the seat was disenfranchised, got {seat['voting_rights']}"
        )
        assert seat["status"] == "ACTIVE", (
            "a voting-rights-only edit takes no state transition, got "
            f"{seat['status']}"
        )
        assert seat["missed_ballot_streak"] == 0, (
            f"missed_ballot_streak is untouched, got {seat['missed_ballot_streak']}"
        )

        committee = scenario.get_committee()
        assert committee["balance_status"] == "UNBALANCED", (
            "only two seats still vote, below the minimum of three, got "
            f"{committee['balance_status']}"
        )
        assert committee["active_member_count"] == 2, (
            f"active_member_count expected 2, got {committee['active_member_count']}"
        )
        assert committee["status"] == "SUSPENDED", (
            f"the committee follows the verdict down, got {committee['status']}"
        )
        assert committee["roster_member_count"] == 3, (
            "the roster basis ignores voting rights, got "
            f"{committee['roster_member_count']}"
        )

        ballot = scenario.get_ballot()
        assert ballot["hold_reason"] == "COMMITTEE_UNBALANCED", (
            f"hop four holds the open ballot, got {ballot['hold_reason']}"
        )
        assert ballot["status"] == "OPEN", (
            f"a hold is not a close, got {ballot['status']}"
        )
        assert ballot["eligible_voter_count"] == 3, (
            "the frozen denominator is unaffected by the seat change, got "
            f"{ballot['eligible_voter_count']}"
        )
        assert scenario.get_work_item()["consensus_gate"] == "BLOCKED", (
            f"the gate shuts, got {scenario.get_work_item()['consensus_gate']}"
        )


class TestBothVerdictsAreStored:
    """One GET exposes the voting basis and the roster basis at once."""

    def test_an_observer_seat_moves_only_the_roster_basis(self, api):
        """
        counts seats whose `status` is either `ACTIVE` or `SUSPENDED`, regardless of
        `voting_rights`, excluding only withdrawn seats.

        Both label groups, together with `active_member_count`, `roster_member_count`,
        `dominance_pct`, `roster_dominance_pct`, `distinct_category_count` and
        `category_counts`, are recomputed and persisted whenever a seat is appointed,
        whenever a seat's `status` or `voting_rights` is edited, whenever a committee is
        activated, and whenever a seat is suspended by the system for repeated non-return at
        a ballot close.

        Design: Corner/cross_cutting_complexity_layers/both_balance_variants_are_persisted_side_by_side_on_one_committee_row
        """
        scenario = fx.balanced_active_committee(api)
        scenario.register("p6")
        observer = scenario.appoint("p6", "m6", voting_rights=False)
        assert observer["voting_rights"] is False, (
            f"the fourth seat is an observer, got {observer['voting_rights']}"
        )
        assert observer["status"] == "ACTIVE", (
            f"an observer seat is still ACTIVE, got {observer['status']}"
        )
        assert observer["interest_category"] == "ACADEMIC", (
            "the observer's category was snapshotted onto the seat, got "
            f"{observer['interest_category']}"
        )

        committee = scenario.get_committee()

        a.assert_voting_balance(
            committee,
            balance_status="BALANCED",
            active_member_count=3,
            distinct_category_count=3,
            dominance_pct=33.3,
            category_counts={"PRODUCER": 1, "USER": 1, "GENERAL_INTEREST": 1},
        )
        a.assert_roster_balance(
            committee,
            roster_balance_status="BALANCED",
            roster_member_count=4,
            roster_dominance_pct=25.0,
        )
        assert committee["status"] == "ACTIVE", (
            "appointing an observer never destabilises the committee, got "
            f"{committee['status']}"
        )
