"""Speaker-point tabulation variants, break determination, and the end-to-end
publication/certification flow."""
from test_helpers import (
    TEST_USERS,
    determine_breaks,
    get_contract,
    get_division,
    get_entry,
    get_order,
    get_school,
    get_tournament,
    pairing_members,
    pay_contract,
    play_pairing_ballot,
    setup_ballot_round,
    setup_break_boundary_scenario,
    setup_completed_tournament_for_publication,
    setup_speaker_divergence_scenario,
    tabulate,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
TAB = TEST_USERS["tabstaff_headers"]


def _finish_round_three(ws):
    """Round 3 trigger sequence: first member wins pairing 1 (28/24) and
    pairing 2 (22/20); verify both; tabulate."""
    non_bye = [p for p in ws["r3_pairings"] if not p.get("is_bye")]
    plans = [("first", 28, 24), ("first", 22, 20)]
    for i, pairing in enumerate(non_bye):
        (pos, w_pts, l_pts) = plans[i]
        play_pairing_ballot(pairing["id"], ws["staff_judges"][i]["id"],
                            pos, w_pts, l_pts)
    tabulate(ws["rounds"]["d"][2]["id"])


class TestSpeakerPointVariants:
    def test_raw_and_high_low_adjusted_diverge(self, api):
        """PRD §3.5: "The entry's `speaker_points_raw` is the plain sum of all
        contributions. Its `speaker_points_adjusted` is the high-low-adjusted
        variant: with at least three contributions, the raw sum minus the maximum
        contribution minus the minimum contribution; with fewer than three, it
        equals the raw sum — identical data, different number."
        PRD §3.5: "plus one bye-award contribution of 27 points per bye received".

        Design: Difficulty/dual_variant_calc/speaker_points_high_low_adjusted_divergence
        """
        ws = setup_speaker_divergence_scenario()
        _finish_round_three(ws)

        e1 = get_entry(ws["entries"]["e"][0]["id"])
        # Contributions: 27 (round-1 bye) + 26 (round-2 win) + 22 (round-3 win).
        assert e1["speaker_points_raw"] == 75
        # >= 3 contributions: 75 - max 27 - min 22 = 26.
        assert e1["speaker_points_adjusted"] == 26
        assert e1["wins"] == 3, "bye award counts as a win"
        assert e1["speaker_points_raw"] != e1["speaker_points_adjusted"], (
            "the two variants diverge on identical ballot data")

    def test_bye_goes_to_lowest_ordered_entry_without_bye(self, api):
        """PRD §3.4: "When the eligible count is odd, exactly one bye is awarded
        to the lowest-ordered entry whose `has_received_bye` is still false".
        PRD §3.4: "A bye pairing is created directly in `VERIFIED` status with
        that entry as its winner and `is_bye` true, and it contributes a win plus
        a fixed award of 27 speaker points to the entry. In the round's pairing
        list, the bye pairing is emitted after all regular pairings."

        Design: Difficulty/dual_variant_calc/speaker_points_high_low_adjusted_divergence
        """
        ws = setup_speaker_divergence_scenario()
        _finish_round_three(ws)

        e1_id = ws["entries"]["e"][0]["id"]
        bye_pairing = ws["r1_pairings"][-1]
        assert bye_pairing["is_bye"] is True, "bye emitted after regular pairings"
        assert bye_pairing["status"] == "VERIFIED"
        members = pairing_members(bye_pairing["id"])
        assert len(members) == 1
        assert members[0]["entry_id"] == e1_id, (
            "E1 was the lowest-ordered entry in created_at order")
        assert bye_pairing["winner_entry_id"] == e1_id

        e1 = get_entry(e1_id)
        assert e1["has_received_bye"] is True
        assert e1["wins"] == 3


class TestBreakWinThreshold:
    def test_threshold_exact_breaks_threshold_minus_one_does_not(self, api):
        """PRD §3.6: "The win threshold is derived from the tournament's
        `prelim_round_count`: divide the round count by two, round down, and add
        one — a 4-round tournament requires 3 wins, and a 5-round tournament also
        requires 3. Debate candidates are the entries whose `wins` are at least
        the threshold; meeting the threshold exactly qualifies, while one win
        fewer does not."
        PRD §3.6: "The advancing set is the first `bracket_size` entries of the
        division's standings order restricted to candidates: each becomes
        `ADVANCED` and receives a `seed` from 1 to `bracket_size` in standings
        order. Every other `COMPETING` entry becomes `ELIMINATED` with
        `final_placement` `NON_BREAKING`."

        Design: Difficulty/boundary_precision_check/break_win_threshold_boundary
        """
        ws = setup_break_boundary_scenario()
        division = determine_breaks(ws["divisions"]["d"]["id"])
        # n = 6 competing, size_cap = 2, candidates = 2 -> bracket_size 2.
        assert division["bracket_size"] == 2

        a1 = get_entry(ws["entries"]["a"][0]["id"])
        a2 = get_entry(ws["entries"]["a"][1]["id"])
        b2 = get_entry(ws["entries"]["b"][1]["id"])
        # 2-round tournament: threshold floor(2/2)+1 = 2. A1 and A2 qualify at 2.
        assert a1["status"] == "ADVANCED" and a1["seed"] == 1
        assert a1["wins"] == 2
        assert a2["status"] == "ADVANCED" and a2["seed"] == 2, (
            "adjusted 57 < A1's 58 decides the seed order")
        # B2 sits at threshold - 1 = 1 win and does not break.
        assert b2["wins"] == 1
        assert b2["status"] == "ELIMINATED"
        assert b2["final_placement"] == "NON_BREAKING"

    def test_opponent_strength_breaks_the_tie(self, api):
        """PRD §3.5: "Opponent strength is debate-only and computed in a pinned
        order: at tabulate time, all wins for the division are recomputed first,
        and only then is each entry's `opponent_strength` evaluated as the sum of
        the current wins of its distinct preliminary opponents."
        PRD §3.5: "Debate sorts by `wins` descending, then
        `speaker_points_adjusted` descending, then `opponent_strength` descending,
        then `speaker_points_raw` descending, with `created_at` ascending as the
        final tie-break — `id` is never used, so ties are impossible."

        Design: Difficulty/boundary_precision_check/break_win_threshold_boundary
        """
        ws = setup_break_boundary_scenario()
        determine_breaks(ws["divisions"]["d"]["id"])

        a1 = get_entry(ws["entries"]["a"][0]["id"])
        # A1's distinct prelim opponents: B1 (0 wins) and B2 (1 win) -> 1.
        assert a1["opponent_strength"] == 1

        b2 = get_entry(ws["entries"]["b"][1]["id"])
        c1 = get_entry(ws["entries"]["c"][0]["id"])
        # B2's distinct prelim opponents: C2 (0 wins) and A1 (2 wins) -> 2.
        # C1's: A2 (2 wins) and B1 (0 wins) -> 2.
        assert b2["opponent_strength"] == 2
        assert c1["opponent_strength"] == 2
        assert b2["prelim_rank"] == 3
        assert c1["prelim_rank"] == 4


class TestInsufficientBreakCandidates:
    def test_two_competing_entries_rejected(self, api):
        """PRD §3.6: "Let *n* be the number of the division's entries still
        `COMPETING`; fewer than 4 such entries fails with
        `ERR_INSUFFICIENT_BREAK_CANDIDATES` (HTTP 409)."

        Design: Corner/validations/breaks_with_too_few_competing_rejected
        """
        ws = setup_ballot_round(stage="tabulated", name="BF")
        resp = api.determine_breaks(ws["divisions"]["d"]["id"], TAB)
        validate_error(resp, "ERR_INSUFFICIENT_BREAK_CANDIDATES")
        assert get_division(ws["divisions"]["d"]["id"])["bracket_size"] is None


class TestPublicationEndToEnd:
    def test_qualification_points_and_certification_gate(self, api):
        """PRD §3.7: "At that moment, every entry of the tournament not in
        `REGISTERED` receives its `qualification_points` from the placement tier
        table: `CHAMPION` earns 10, `RUNNER_UP` 8, `SEMIFINALIST` 6,
        `QUARTERFINALIST` 4, `OCTOFINALIST` 2, and `NON_BREAKING` 1; `WITHDRAWN`
        entries receive 0."
        PRD §3.7: "Certifying qualifications requires `results_visibility`
        `PUBLISHED` (otherwise `ERR_TOURNAMENT_PHASE_FORBIDDEN`) and every
        hired-judge contract of every school in the tournament to be in `PAID` or
        `CANCELLED` (otherwise `ERR_UNPAID_CONTRACTS_REMAIN`, HTTP 409)."
        PRD §3.8: "An awards order's `awards_count` is the sum of `bracket_size`
        over the tournament's divisions whose `bracket_size` is set."

        Design: Corner/calculations/qualification_points_and_certification_gate
        """
        ws = setup_completed_tournament_for_publication()
        alpha_id = ws["schools"]["a"]["id"]

        publish_results = validate_success(
            api.publish_results(ws["t"]["id"], DIRECTOR))
        assert publish_results["results_visibility"] == "PUBLISHED"
        assert publish_results["status"] == "COMPLETED"

        a1 = get_entry(ws["entries"]["a"][0]["id"])
        assert a1["status"] == "FINISHED"
        assert a1["final_placement"] == "CHAMPION"
        assert a1["qualification_points"] == 10

        a2 = get_entry(ws["entries"]["a"][1]["id"])
        assert a2["final_placement"] == "RUNNER_UP", "lost the field-2 elim"
        assert a2["qualification_points"] == 8

        b2 = get_entry(ws["entries"]["b"][1]["id"])
        assert b2["final_placement"] == "NON_BREAKING"
        assert b2["qualification_points"] == 1

        withdrawn = get_entry(ws["withdrawn_entry"]["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["qualification_points"] == 0

        # Alpha's contract is CONFIRMED (accepted, unpaid): certification blocked.
        assert get_contract(ws["contract"]["id"])["status"] == "CONFIRMED"
        resp = api.certify_qualifications(ws["t"]["id"], DIRECTOR)
        validate_error(resp, "ERR_UNPAID_CONTRACTS_REMAIN")

        pay_contract(ws["contract"]["id"], alpha_id)
        assert get_school(alpha_id)["invoice_balance_cents"] == 5000, (
            "entry fees 5000 + final fee 5000 - payment 5000")

        certified = validate_success(
            api.certify_qualifications(ws["t"]["id"], DIRECTOR))
        assert certified["results_visibility"] == "CERTIFIED"
        final = get_tournament(ws["t"]["id"])
        assert final["status"] == "COMPLETED", "results axis never mutates status"
        assert final["results_visibility"] == "CERTIFIED"

        awards = get_order(ws["awards_order"]["id"])
        assert awards["status"] == "SUBMITTED"
        assert awards["awards_count"] == 2, "sum of bracket_size (2)"
        assert awards["frozen_awards_count"] == 2
