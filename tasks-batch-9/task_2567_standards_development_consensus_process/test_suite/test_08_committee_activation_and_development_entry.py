"""
Getting a committee to the point where it can do work: the activation edge and
its two guards, the refusal to replay activation, the seat-suspension cascade
that only an explicit activation reverses, and the first draft it then issues.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import fixtures as fx


class TestActivationEdge:
    """FORMING to ACTIVE fires once the chair is seated and the roster balances."""

    def test_activation_reports_the_freshly_recomputed_counters(self, api):
        """
        Both balance bases are recomputed and persisted before that verdict is read, so
        `balance_status`, `roster_balance_status`, `dominance_pct`,
        `roster_dominance_pct`, `distinct_category_count`, `category_counts`,
        `active_member_count` and `roster_member_count` are all current when activation
        succeeds.

        Design: Corner/state_machines/committee_activation_transitions_forming_to_active
        """
        scenario = fx.Scenario(api)
        scenario.register_core()
        scenario.create_committee("p1")
        for participant_key, seat_key in (("p1", "m1"), ("p2", "m2"), ("p3", "m3")):
            scenario.appoint(participant_key, seat_key)
        assert scenario.get_committee()["status"] == "FORMING", (
            "the committee has not been activated yet"
        )

        activated = scenario.activate_committee()

        assert activated["status"] == "ACTIVE", (
            f"status expected ACTIVE, got {activated['status']}"
        )
        a.assert_voting_balance(
            activated,
            balance_status="BALANCED",
            active_member_count=3,
            distinct_category_count=3,
            dominance_pct=33.3,
            category_counts={"PRODUCER": 1, "USER": 1, "GENERAL_INTEREST": 1},
        )
        a.assert_roster_balance(
            activated,
            roster_balance_status="BALANCED",
            roster_member_count=3,
            roster_dominance_pct=33.3,
        )
        stored = scenario.get_committee()
        assert stored["status"] == "ACTIVE", "the activation was persisted"
        assert stored["balance_status"] == "BALANCED", (
            f"balance_status expected BALANCED, got {stored['balance_status']}"
        )

    def test_activation_with_an_unseated_chair_is_refused(self, api, staff_headers):
        """
        the participant named as `chair_participant_id` holds a seat on this very
        committee whose `status` is `ACTIVE` and whose `voting_rights` is true, failing
        which the request is refused with `ERR_CHAIR_NOT_MEMBER`

        Design: Corner/state_machines/committee_activation_without_the_chair_holding_a_seat_is_rejected
        """
        scenario = fx.Scenario(api)
        scenario.register_core()
        scenario.register("p6", interest_category="REGULATORY")
        scenario.create_committee("p1")
        for participant_key, seat_key in (("p2", "m2"), ("p3", "m3"), ("p6", "m6")):
            scenario.appoint(participant_key, seat_key)

        before = scenario.get_committee()
        a.assert_voting_balance(
            before,
            balance_status="BALANCED",
            active_member_count=3,
            distinct_category_count=3,
            dominance_pct=33.3,
        )

        response = api.activate_committee(scenario.committee_id, staff_headers)
        validate_error(response, "ERR_CHAIR_NOT_MEMBER", 409)

        after = scenario.get_committee()
        assert after["status"] == "FORMING", (
            f"the refused activation left the committee FORMING, got {after['status']}"
        )
        assert after["balance_status"] == "BALANCED", (
            "a balanced roster is not enough to open the edge, got "
            f"{after['balance_status']}"
        )
        assert after["active_member_count"] == 3, (
            f"active_member_count expected 3, got {after['active_member_count']}"
        )

    def test_activating_an_already_active_committee_is_refused(self, api, staff_headers):
        """
        A committee moves from `FORMING` to `ACTIVE`, or from `SUSPENDED` back to
        `ACTIVE`, only when three things hold in this order: the committee is currently
        in `FORMING` or `SUSPENDED`. Activating a committee that is already `ACTIVE` is
        refused with `ERR_INVALID_COMMITTEE_STATE`.

        Design: Corner/state_machines/a_second_activate_on_an_active_committee_is_rejected_rather_than_idempotent
        """
        scenario = fx.balanced_active_committee(api)
        before = scenario.get_committee()

        response = api.activate_committee(scenario.committee_id, staff_headers)
        validate_error(response, "ERR_INVALID_COMMITTEE_STATE", 409)

        after = scenario.get_committee()
        assert after["status"] == "ACTIVE", (
            f"the committee is untouched by the refusal, got {after['status']}"
        )
        assert after["balance_status"] == "BALANCED", (
            f"balance_status expected BALANCED, got {after['balance_status']}"
        )
        assert after["active_member_count"] == 3, (
            f"active_member_count expected 3, got {after['active_member_count']}"
        )
        a.assert_version_unchanged(before, after)


class TestSeatCascadeAndItsReverseTrip:
    """Losing balance suspends the committee; only an activation call restores it."""

    def test_restoring_the_seat_alone_leaves_the_committee_suspended(self, api):
        """
        When a seat change drops the voting-basis verdict below `BALANCED`, a four-hop
        cascade runs inside the same request. Hop one recomputes the committee's
        counters. Hop two moves the committee from `ACTIVE` to `SUSPENDED`. The reverse
        trip is the activation described above.

        Design: Corner/state_machines/reactivating_a_suspended_seat_needs_an_explicit_committee_reactivation
        """
        scenario = fx.work_item_in_development(api)

        scenario.patch_membership("m3", status="SUSPENDED")
        suspended = scenario.get_committee()
        assert scenario.get_membership("m3")["status"] == "SUSPENDED", (
            "the seat edit was applied"
        )
        assert suspended["status"] == "SUSPENDED", (
            f"the committee follows the seat down, got {suspended['status']}"
        )
        assert suspended["active_member_count"] == 2, (
            f"active_member_count expected 2, got {suspended['active_member_count']}"
        )
        assert suspended["balance_status"] == "UNBALANCED", (
            f"balance_status expected UNBALANCED, got {suspended['balance_status']}"
        )
        assert suspended["roster_member_count"] == 3, (
            "the roster basis still counts the suspended seat, got "
            f"{suspended['roster_member_count']}"
        )
        assert scenario.get_work_item()["consensus_gate"] == "BLOCKED", (
            "hop three gates the sponsored work item"
        )

        scenario.patch_membership("m3", status="ACTIVE")
        restored = scenario.get_committee()
        assert restored["active_member_count"] == 3, (
            f"active_member_count expected 3, got {restored['active_member_count']}"
        )
        assert restored["balance_status"] == "BALANCED", (
            f"balance_status expected BALANCED, got {restored['balance_status']}"
        )
        assert restored["status"] == "SUSPENDED", (
            "no system edge returns a committee to ACTIVE, got "
            f"{restored['status']}"
        )
        assert scenario.get_work_item()["consensus_gate"] == "BLOCKED", (
            "the gate stays shut while the committee is suspended"
        )

        scenario.activate_committee()
        reactivated = scenario.get_committee()
        assert reactivated["status"] == "ACTIVE", (
            f"the explicit activation restores the committee, got {reactivated['status']}"
        )
        a.assert_pct(reactivated["dominance_pct"], 33.3)
        assert scenario.get_work_item()["consensus_gate"] == "OPEN", (
            "the restored committee reopens its work item's gate"
        )

    def test_first_revision_opens_in_drafting_on_a_work_item_in_development(self, api):
        """
        A new draft opens in `status` `DRAFTING`, with `unresolved_negative_count` and
        `ballot_round_count` at 0 — the latter being simply how many ballots have been
        opened on this revision — and with `recirculation_required` false.

        Design: Corner/state_machines/first_draft_creation_moves_the_work_item_from_scope_approved_to_in_development
        """
        scenario = fx.work_item_in_development(api)

        draft = scenario.add_draft(total_clause_count=40, changed_clause_count=0)

        a.assert_has_fields(draft, "Draft")
        assert draft["status"] == "DRAFTING", (
            f"a new draft opens in DRAFTING, got {draft['status']}"
        )
        assert draft["revision_number"] == 1, (
            f"a draft with no predecessor is revision 1, got {draft['revision_number']}"
        )
        a.assert_ratio(draft["substantive_change_ratio"], 0.0000)
        assert draft["prior_draft_id"] is None, (
            f"prior_draft_id expected null, got {draft['prior_draft_id']}"
        )
        assert draft["ballot_round_count"] == 0, (
            f"ballot_round_count starts at 0, got {draft['ballot_round_count']}"
        )
        assert draft["unresolved_negative_count"] == 0, (
            f"unresolved_negative_count starts at 0, got {draft['unresolved_negative_count']}"
        )
        assert draft["recirculation_required"] is False, (
            f"recirculation_required starts false, got {draft['recirculation_required']}"
        )
        assert draft["work_item_id"] == scenario.work_item_id, (
            "the work item identifier arrives from the path"
        )

        work_item = scenario.get_work_item()
        assert work_item["progress_status"] == "IN_DEVELOPMENT", (
            f"progress_status expected IN_DEVELOPMENT, got {work_item['progress_status']}"
        )
        assert work_item["designation"] == "STD-1400", (
            f"designation expected STD-1400, got {work_item['designation']}"
        )
        assert work_item["sponsoring_committee_id"] == scenario.committee_id, (
            "the sponsoring committee was persisted by the scope approval"
        )
