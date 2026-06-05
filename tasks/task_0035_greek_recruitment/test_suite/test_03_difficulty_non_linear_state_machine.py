"""Difficulty Rule 3 — non_linear_state_machine.

Two branching/revert patterns:
  (A) Party SCHEDULED -> {OPEN, CANCELLED}; OPEN -> {COMPLETED, CANCELLED},
      with divergent invitation cascade per branch.
  (B) PNM MATCHED -> BID_ACCEPTED, then a chapter-officer rescind reverts the
      PNM back to ACTIVE — a state that would otherwise be terminal.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    create_chapter,
    create_round,
    register_and_activate_pnm,
    create_and_open_party,
    create_party,
    create_invitation,
    accept_invitation,
    complete_party,
    cancel_party,
    setup_round_with_accepted_bid,
    rescind_bid_match_payload,
    make_chapter_officer_headers,
    make_pnm_headers,
    TEST_USERS,
)


class TestPartyBranchingCompleteVsCancel:
    """Two parties: one completes (ACCEPTED -> ATTENDED, INVITED -> NO_SHOW);
    the other cancels (INVITED -> DECLINED)."""

    @staticmethod
    def _setup_two_parties_with_invites():
        set_clock("2026-09-01T00:00:00Z")
        ch_f = create_chapter(
            name="Zeta",
            greek_type="SORORITY",
            quota_total=5,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 nlsm1")
        w1 = register_and_activate_pnm(full_name="W1", gpa=3.50)
        w2 = register_and_activate_pnm(full_name="W2", gpa=3.50)
        # Party A — will COMPLETE
        p_complete = create_and_open_party(
            rnd["id"],
            ch_f["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
            capacity=10,
        )
        # Party B — will CANCEL (still SCHEDULED)
        p_cancel = create_party(
            rnd["id"],
            ch_f["id"],
            scheduled_start_utc="2026-09-06T18:00:00Z",
            duration_minutes=60,
            capacity=10,
        )
        inv_w1_c = create_invitation(p_complete["id"], w1["id"], ch_f["id"])
        inv_w2_c = create_invitation(p_complete["id"], w2["id"], ch_f["id"])
        inv_w1_x = create_invitation(p_cancel["id"], w1["id"], ch_f["id"])
        # w1 accepts complete-party invite, w2 leaves it INVITED.
        accept_invitation(inv_w1_c["id"], w1["id"])
        return ch_f, p_complete, p_cancel, inv_w1_c, inv_w2_c, inv_w1_x

    def test_complete_branch_advances_accepted_to_attended_and_invited_to_no_show(
        self, api
    ):
        """PRD §3.2: "Completing a party transitions `status` from `OPEN` to `COMPLETED` and cascades: every `PartyInvitation` on the party whose `rsvp_status` is `ACCEPTED` advances to `ATTENDED` (a terminal state), and every invitation whose `rsvp_status` is still `INVITED` advances to `NO_SHOW` (also terminal); PNMs themselves remain `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/nlsm_party_branching_open_cancel_complete
        """
        (
            ch_f,
            p_complete,
            p_cancel,
            inv_w1_c,
            inv_w2_c,
            inv_w1_x,
        ) = self._setup_two_parties_with_invites()
        completed = validate_success(
            api.complete_party(
                p_complete["id"], make_chapter_officer_headers(ch_f["id"])
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        inv_w1_c_after = validate_success(
            api.get_invitation(
                inv_w1_c["id"], TEST_USERS["panhellenic_admin_headers"]
            ),
            200,
        )
        assert inv_w1_c_after["rsvp_status"] == "ATTENDED"
        inv_w2_c_after = validate_success(
            api.get_invitation(
                inv_w2_c["id"], TEST_USERS["panhellenic_admin_headers"]
            ),
            200,
        )
        assert inv_w2_c_after["rsvp_status"] == "NO_SHOW"

    def test_cancel_branch_advances_non_terminal_invitations_to_declined(self, api):
        """PRD §3.2: "Cancelling a party — which the officer may do from either `SCHEDULED` or `OPEN` — transitions `status` to `CANCELLED` and likewise cascades, but with a critical distinction from completion: every non-terminal invitation on the party advances to `DECLINED`, not `NO_SHOW`, because the chapter, not the PNM, is the cancelling party."

        Design: Difficulty/non_linear_state_machine/nlsm_party_branching_open_cancel_complete
        """
        (
            ch_f,
            p_complete,
            p_cancel,
            inv_w1_c,
            inv_w2_c,
            inv_w1_x,
        ) = self._setup_two_parties_with_invites()
        cancelled = validate_success(
            api.cancel_party(
                p_cancel["id"], make_chapter_officer_headers(ch_f["id"])
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        inv_w1_x_after = validate_success(
            api.get_invitation(
                inv_w1_x["id"], TEST_USERS["panhellenic_admin_headers"]
            ),
            200,
        )
        assert inv_w1_x_after["rsvp_status"] == "DECLINED"


class TestPnmBranchingRevertViaRescind:
    """A PNM goes MATCHED -> BID_ACCEPTED via accept, then ChapterOfficer
    rescind pushes them back to ACTIVE — a revert from a would-be terminal state."""

    @staticmethod
    def _setup_and_rescind():
        ctx = setup_round_with_accepted_bid(
            chapter_name="Eta",
            greek_type="SORORITY",
            quota_total=2,
            dues_per_member_cents=20000,
            legacy_priority_slots=0,
            pnm_full_name="X1",
            cycle_label="Fall 2026 nlsm2",
        )
        ch_g = ctx["chapter"]
        bid = ctx["bid_match"]
        v_after_accept = ctx["chapter_version_after_accept"]
        rescind_res = api_client.rescind_bid_match(
            bid["id"],
            rescind_bid_match_payload(expected_chapter_version=v_after_accept),
            make_chapter_officer_headers(ch_g["id"]),
        )
        rescinded_bid = get_success_data(rescind_res)
        return ch_g, ctx["pnm"], rescinded_bid

    def test_bid_status_becomes_declined_after_rescind(self, api):
        """PRD §3.6: "On a successful rescind, the bid's `status` transitions to `DECLINED` (the rescission is modeled as a `DECLINED` bid distinguished from a PNM decline by the trailing refund entry on its `bid_match_id`)"

        Design: Difficulty/non_linear_state_machine/nlsm_pnm_branching_revert_via_rescind
        """
        ch_g, pnm, rescinded_bid = self._setup_and_rescind()
        assert rescinded_bid["status"] == "DECLINED"

    def test_pnm_reverts_to_active_with_cleared_matched_chapter(self, api):
        """PRD §3.6: "The PNM is pushed back to `ACTIVE` with `matched_chapter_id` cleared to null so the chapter has the opportunity to refill the slot before `BID_DAY` closes."

        Design: Difficulty/non_linear_state_machine/nlsm_pnm_branching_revert_via_rescind
        """
        ch_g, pnm, rescinded_bid = self._setup_and_rescind()
        pnm_after = validate_success(
            api.get_pnm(pnm["id"], TEST_USERS["panhellenic_admin_headers"]), 200
        )
        assert pnm_after["status"] == "ACTIVE"
        assert pnm_after.get("matched_chapter_id") is None

    def test_chapter_pledged_count_decremented_after_rescind(self, api):
        """PRD §3.6: "The chapter's `pledged_count` is decremented (and `legacy_pledged_count` is decremented as well if `priority_kind` is `LEGACY`), freeing the slot."

        Design: Difficulty/non_linear_state_machine/nlsm_pnm_branching_revert_via_rescind
        """
        ch_g, pnm, rescinded_bid = self._setup_and_rescind()
        ch_after = validate_success(
            api.get_chapter(ch_g["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert ch_after["pledged_count"] == 0
