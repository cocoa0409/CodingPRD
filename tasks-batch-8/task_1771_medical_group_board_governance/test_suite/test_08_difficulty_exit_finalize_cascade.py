"""Difficulty queue: transitive cascade — exit finalize depth-3 chain."""
from test_helpers import (
    add_member,
    adopt_buyout_approval,
    appoint_seat,
    appraise_valuation,
    create_board_seat,
    create_committee,
    create_policy,
    create_shareholder,
    finalize_exit,
    get_board_seat,
    get_committee,
    get_exit_valuation,
    get_physician,
    get_policy,
    initiate_exit,
)


def _setup_exit_ready():
    """S (1000 shares) EXITING with APPRAISED valuation; sole CHAIR of a quorum-1
    committee; holds SEAT-1 with no successor; adopted BUYOUT_APPROVAL by T."""
    create_policy(total_shares_authorized=1000000, board_quorum_count=1)
    s = create_shareholder("Dr S", 1000, "2012-01-01T00:00:00Z")
    t = create_shareholder("Dr T", 1000, "2013-01-01T00:00:00Z")
    committee = create_committee(
        name="Quality Committee", committee_type="QUALITY", quorum_count=1
    )
    add_member(committee["id"], s["id"], "CHAIR")
    seat = create_board_seat("SEAT-1", "CLINICAL")
    appoint_seat(seat["id"], s["id"], "2026-08-01T00:00:00Z", "2029-08-01T00:00:00Z")
    valuation = initiate_exit(s["id"], "VOLUNTARY")
    appraised = appraise_valuation(valuation, 90000000)
    motion = adopt_buyout_approval(t, appraised["id"])
    return s, t, committee, seat, appraised, motion


class TestExitFinalizeThreeHopCascade:
    def test_finalize_link1_physician_exited_and_shares_returned(self, api):
        """PRD §3.6: "Finalization sets `approving_motion_id`, computes
        `payment_schedule_cents` — 40 percent of `final_value_cents` at finalization,
        30 percent at plus 12 months, 30 percent at plus 24 months, the first two
        entries rounded half-up and the last entry absorbing the rounding residue — and
        fires the exit cascade in three links. First, the physician moves from
        `EXITING` to `EXITED`, `shares_held` goes to 0, and the returned shares flow
        back to `treasury_shares`."
        final = round(90000000 * 0.5 * 0.85) = 38250000; schedule 40/30/30.

        Design: Difficulty/transitive_cascade/exit_finalize_three_hop_cascade
        """
        s, _t, _c, _seat, appraised, motion = _setup_exit_ready()
        assert appraised["final_value_cents"] == 38250000

        finalized = finalize_exit(appraised["id"], motion["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["approving_motion_id"] == motion["id"]
        assert finalized["payment_schedule_cents"] == [15300000, 11475000, 11475000], (
            f"40/30/30 of 38250000 with last entry absorbing residue, "
            f"got {finalized['payment_schedule_cents']}"
        )

        physician = get_physician(s["id"])
        assert physician["partnership_status"] == "EXITED"
        assert physician["shares_held"] == 0
        policy = get_policy()
        assert policy["treasury_shares"] == 999000, (
            f"998000 authorized remainder + 1000 returned shares, got {policy['treasury_shares']}"
        )

    def test_finalize_links2_and3_seat_vacated_and_committee_impaired(self, api):
        """PRD §3.6: "Second, any board seat the physician holds is vacated — or its
        booked successor is promoted. Third, the physician's committee memberships are
        removed, and any committee that falls below quorum becomes `IMPAIRED`; this
        impairment re-check cascades through the affected committees."

        Design: Difficulty/transitive_cascade/exit_finalize_three_hop_cascade
        """
        s, _t, committee, seat, appraised, motion = _setup_exit_ready()
        finalize_exit(appraised["id"], motion["id"])

        seat_after = get_board_seat(seat["id"])
        assert seat_after["status"] == "VACANT", (
            "no successor booked -> the held seat is vacated"
        )
        assert seat_after["current_holder_physician_id"] is None

        committee_after = get_committee(committee["id"])
        assert committee_after["active_member_count"] == 0
        assert committee_after["members"] == []
        assert committee_after["status"] == "IMPAIRED", (
            "0 members < quorum 1 -> the exit cascade impairs the committee"
        )
        assert get_exit_valuation(appraised["id"])["status"] == "FINALIZED"
