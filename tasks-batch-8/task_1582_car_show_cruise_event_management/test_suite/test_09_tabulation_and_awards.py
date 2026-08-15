"""Tabulation: judged scoring variants, rounding order, award row materialization,
people's-choice tally, winner-withdrawal compensation, and present gating."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_judge_headers,
    create_criteria_scores, create_score_sheet_payload,
    create_event_with_class_and_zone, create_open_event,
    create_registrant_with_vehicle, create_paid_registration,
    sign_waiver, check_in, setup_judging_event, judge_create_and_submit_sheet,
    finalize_event, list_event_awards, create_voter, cast_ballot,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]

# Criteria that produce raw weighted sums 55.0 / 49.25 / 51.25.
CRITERIA_55 = create_criteria_scores(exterior=9, interior=8, engine=8, authenticity=9, condition=8)
CRITERIA_49_25 = create_criteria_scores(exterior=8, interior=8, engine=7, authenticity=8, condition=7)
CRITERIA_51_25 = create_criteria_scores(exterior=8, interior=7, engine=8, authenticity=8, condition=8)


def _tabulating_event_with_three_sheets(api, tabulation_method):
    """Judged event -> TABULATING with one checked-in entry scored by three
    judges whose raw sheet sums are 55.0, 49.25, 51.25."""
    s = setup_judging_event(num_registrations=1, judged=True, award_depth=2,
                            num_judges=3, tabulation_method=tabulation_method)
    reg_id = s["registrations"][0]["id"]
    sheets = []
    for judge, criteria in zip(s["judges"], [CRITERIA_55, CRITERIA_49_25, CRITERIA_51_25]):
        sheets.append(judge_create_and_submit_sheet(reg_id, judge["id"], criteria_scores=criteria))
    ev = validate_success(api.get_event(s["event"]["id"], ORG))
    assert ev["lifecycle_status"] == "TABULATING", "three of three pairs submitted"
    return s, reg_id, sheets


class TestTabulationVariants:
    def test_straight_average_winner_score(self, api):
        """PRD §3.6: "When the event's `tabulation_method` is `STRAIGHT_AVERAGE`,
        or the entry has fewer than three locked sheets, the class score is the
        average of its sheet totals, rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/judged_tabulation_straight_vs_drop_extremes
        """
        s, reg_id, sheets = _tabulating_event_with_three_sheets(api, "STRAIGHT_AVERAGE")
        finalize_event(s["event"]["id"])
        awards = list_event_awards(s["event"]["id"])
        place1 = next(a for a in awards
                      if a["award_kind"] == "CLASS_PLACE" and a["place"] == 1)
        assert place1["winner_registration_id"] == reg_id
        assert place1["winner_score"] == pytest.approx(51.87, abs=0.001), (
            "avg of 55.0 / 49.3 / 51.3")

    def test_drop_extremes_diverges_on_identical_sheets(self, api):
        """PRD §3.6: "Under `DROP_EXTREMES` with three or more locked sheets,
        exactly one highest and one lowest sheet total are discarded before
        averaging, and the result is likewise rounded half-up to two decimals."

        Design: Difficulty/dual_variant_calc/judged_tabulation_straight_vs_drop_extremes
        """
        s, reg_id, sheets = _tabulating_event_with_three_sheets(api, "DROP_EXTREMES")
        finalize_event(s["event"]["id"])
        awards = list_event_awards(s["event"]["id"])
        place1 = next(a for a in awards
                      if a["award_kind"] == "CLASS_PLACE" and a["place"] == 1)
        assert place1["winner_registration_id"] == reg_id
        assert place1["winner_score"] == pytest.approx(51.30, abs=0.001), (
            "drop 55.0 and 49.3; 51.30 != 51.87 straight-average result")


class TestPerSheetRoundingOrder:
    def test_per_sheet_rounding_applied_first(self, api):
        """PRD §3.5: "Each new sheet starts in `DRAFT`, and its `sheet_total` is
        computed at once: the five criterion points are weighted — `EXTERIOR` at
        1.0, `INTERIOR` at 0.75, `ENGINE` at 1.5, `AUTHENTICITY` at 2.0, and
        `CONDITION` at 1.25 — summed, and rounded half-up to one decimal place."

        Design: Difficulty/combinatorial_formula/tabulation_per_sheet_rounding_order
        """
        s, reg_id, sheets = _tabulating_event_with_three_sheets(api, "STRAIGHT_AVERAGE")
        sheet2 = validate_success(api.get_score_sheet(sheets[1]["id"], ORG))
        assert sheet2["sheet_total"] == pytest.approx(49.3, abs=0.001), (
            "raw 49.25 rounded per-sheet to 1 decimal, half-up")

    def test_class_score_uses_rounded_sheet_totals(self, api):
        """PRD §3.6: "The rounding order is pinned: each sheet's total is rounded
        to one decimal first, then the average is taken, then the average is
        rounded to two decimals — averaging unrounded weighted sums and rounding
        once at the end is a different, forbidden order that produces different
        scores."

        Design: Difficulty/combinatorial_formula/tabulation_per_sheet_rounding_order
        """
        s, reg_id, sheets = _tabulating_event_with_three_sheets(api, "STRAIGHT_AVERAGE")
        finalize_event(s["event"]["id"])
        awards = list_event_awards(s["event"]["id"])
        place1 = next(a for a in awards
                      if a["award_kind"] == "CLASS_PLACE" and a["place"] == 1)
        assert place1["winner_score"] == pytest.approx(51.87, abs=0.001), (
            "51.87 from rounded totals 55.0/49.3/51.3; round-once order would give 51.83")


class TestAwardRowMaterialization:
    def test_award_rows_created_at_start_judging(self, api):
        """PRD §3.5: "the award structure materializes in `PENDING`: for each
        class whose `judging_mode` is `JUDGED` or `BOTH`, `award_depth` rows with
        `award_kind` `CLASS_PLACE` are created with `place` running from 1 to
        `award_depth`; for each class whose mode is `PEOPLES_CHOICE` or `BOTH`, a
        single row with `award_kind` `PEOPLES_CHOICE` and a null `place` is
        created; and exactly one `BEST_OF_SHOW` row is created with its
        `class_id` and `place` left null". Also: "if at least one judged class
        exists and every judged class is already complete, meaning no
        `CHECKED_IN` registration in any judged class lacks a `SUBMITTED` or
        `LOCKED` sheet from any judge assigned to that class, the event
        auto-advances `JUDGING` → `TABULATING` immediately."

        Design: Corner/state_machines/award_rows_created_at_start_judging
        """
        # PRD §3.1 restricts class creation to DRAFT/PUBLISHED: create all three
        # classes before opening registration.
        ev, cls_j, zone = create_event_with_class_and_zone(
            class_overrides={"code": "JCLS", "judging_mode": "JUDGED", "award_depth": 2,
                             "min_year": 1950, "max_year": 1975})
        cls_b = get_success_data(api.create_class(ev["id"], {
            "code": "BCLS", "name": "Both", "min_year": 1976, "max_year": 1995,
            "prereg_fee_cents": 3000, "day_of_fee_cents": 4500, "capacity": 40,
            "judging_mode": "BOTH", "award_depth": 1}, ORG))
        cls_p = get_success_data(api.create_class(ev["id"], {
            "code": "PCLS", "name": "Peoples", "min_year": 1900, "max_year": 2026,
            "prereg_fee_cents": 3000, "day_of_fee_cents": 4500, "capacity": 40,
            "judging_mode": "PEOPLES_CHOICE", "award_depth": 1}, ORG))
        get_success_data(api.publish_event(ev["id"], ORG))
        get_success_data(api.open_registration(ev["id"], ORG))
        get_success_data(api.lock_registration(ev["id"], ORG))
        out = validate_success(api.start_judging(ev["id"], ORG))
        assert out["lifecycle_status"] == "TABULATING", (
            "no CHECKED_IN entries: judged classes are vacuously complete")
        awards = list_event_awards(ev["id"])
        def rows(kind, class_id):
            return sorted(
                [a for a in awards if a["award_kind"] == kind and a.get("class_id") == class_id],
                key=lambda a: (a.get("place") or 0))
        assert len(rows("CLASS_PLACE", cls_j["id"])) == 2
        assert {a["place"] for a in rows("CLASS_PLACE", cls_j["id"])} == {1, 2}
        assert len(rows("CLASS_PLACE", cls_b["id"])) == 1
        assert len(rows("PEOPLES_CHOICE", cls_b["id"])) == 1
        assert len(rows("PEOPLES_CHOICE", cls_p["id"])) == 1
        bos = [a for a in awards if a["award_kind"] == "BEST_OF_SHOW"]
        assert len(bos) == 1
        assert bos[0].get("class_id") is None
        assert bos[0].get("place") is None
        for a in awards:
            assert a["status"] == "PENDING"
            assert a["winner_registration_id"] is None


class TestWinnerWithdrawalCompensation:
    def _setup_finalized_winner(self, api):
        s = setup_judging_event(num_registrations=1, judged=True, award_depth=1,
                                num_judges=1)
        reg_id = s["registrations"][0]["id"]
        judge_create_and_submit_sheet(reg_id, s["judges"][0]["id"], criteria_scores=CRITERIA_55)
        finalize_event(s["event"]["id"])
        awards = list_event_awards(s["event"]["id"])
        place1 = next(a for a in awards
                      if a["award_kind"] == "CLASS_PLACE" and a["place"] == 1)
        assert place1["winner_registration_id"] == reg_id
        assert place1["status"] == "FINALIZED"
        return s, reg_id, place1

    def test_winner_withdrawal_reverts_award_to_pending(self, api):
        """PRD §3.4: "any award in `COMPUTED` or `FINALIZED` that this entry had
        won reverts to `PENDING` with its winner fields cleared — awards already
        `PRESENTED` are left standing."

        Design: Corner/state_machines/award_winner_withdrawal_reverts_to_pending
        """
        s, reg_id, award = self._setup_finalized_winner(api)
        get_success_data(api.withdraw_registration(reg_id, {"reason": "left early"}, DESK))
        after = validate_success(api.get_award(award["id"], ORG))
        assert after["status"] == "PENDING"
        assert after["winner_registration_id"] is None

    def test_refinalize_recomputes_to_insufficient_entries(self, api):
        """PRD §3.6: "Places run from 1 to the class's `award_depth`, and when the
        class has fewer scored entries than places, the unfilled places keep a
        null `winner_registration_id` with `tie_break_log` recording
        `INSUFFICIENT_ENTRIES`." PRD §3.6: "Because finalization is repeatable, it
        doubles as the recovery path after a winner's withdrawal reverted an
        award to `PENDING`."

        Design: Corner/state_machines/award_winner_withdrawal_reverts_to_pending
        """
        s, reg_id, award = self._setup_finalized_winner(api)
        get_success_data(api.withdraw_registration(reg_id, {"reason": "left early"}, DESK))
        finalize_event(s["event"]["id"])
        after = validate_success(api.get_award(award["id"], ORG))
        assert after["status"] == "FINALIZED"
        assert after["winner_registration_id"] is None
        assert after["tie_break_log"] == "INSUFFICIENT_ENTRIES"
        reg_after = validate_success(api.get_registration(reg_id, ORG))
        assert reg_after["status"] == "WITHDRAWN"


class TestDropExtremesFallback:
    def test_drop_extremes_fallback_two_sheets(self, api):
        """PRD §3.6: "When the event's `tabulation_method` is `STRAIGHT_AVERAGE`,
        or the entry has fewer than three locked sheets, the class score is the
        average of its sheet totals, rounded half-up to two decimal places."

        Design: Corner/calculations/drop_extremes_fallback_two_sheets
        """
        s = setup_judging_event(num_registrations=1, judged=True, award_depth=1,
                                num_judges=2, tabulation_method="DROP_EXTREMES")
        reg_id = s["registrations"][0]["id"]
        # All-8s sheet: 8*1.0+8*0.75+8*1.5+8*2.0+8*1.25 == 52.0
        s1 = judge_create_and_submit_sheet(reg_id, s["judges"][0]["id"],
                                           criteria_scores=create_criteria_scores(8, 8, 8, 8, 8))
        # All-6s sheet: 6*5.5 == 39.0
        s2 = judge_create_and_submit_sheet(reg_id, s["judges"][1]["id"],
                                           criteria_scores=create_criteria_scores(6, 6, 6, 6, 6))
        assert s1["sheet_total"] == pytest.approx(52.0, abs=0.001)
        assert s2["sheet_total"] == pytest.approx(39.0, abs=0.001)
        finalize_event(s["event"]["id"])
        awards = list_event_awards(s["event"]["id"])
        place1 = next(a for a in awards
                      if a["award_kind"] == "CLASS_PLACE" and a["place"] == 1)
        assert place1["winner_score"] == pytest.approx(45.50, abs=0.001), (
            "fewer than 3 sheets: straight average even under DROP_EXTREMES")


class TestPeoplesChoiceTally:
    def _setup_pc_event(self, api):
        """PC-only event in JUDGING with two checked-in entries RM/RN."""
        ev, cls, zone = create_open_event(
            class_overrides={"code": "SHOW", "min_year": 1900, "max_year": 2026,
                             "judging_mode": "PEOPLES_CHOICE", "award_depth": 1},
            zone_overrides={"arrival_window_start": "2026-08-15T08:00:00Z",
                            "arrival_window_end": "2026-08-15T10:00:00Z"})
        out = {}
        for key, name, email, yr, make, model in [
            ("rm", "RM", "rm@example.com", 1970, "Ford", "Mustang"),
            ("rn", "RN", "rn@example.com", 1972, "Pontiac", "GTO"),
        ]:
            reg, veh = create_registrant_with_vehicle(
                name=name, email=email,
                vehicle_overrides={"year": yr, "make": make, "model": model})
            sign_waiver(ev["id"], reg["id"], signature_name=name)
            r = create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"])
            out[key] = r
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T08:30:00Z"}, ORG))
        out["rm"] = check_in(out["rm"]["id"], zone["id"])
        out["rn"] = check_in(out["rn"]["id"], zone["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T12:30:00Z"}, ORG))
        get_success_data(api.lock_registration(ev["id"], ORG))
        get_success_data(api.start_judging(ev["id"], ORG))
        return ev, cls, out["rm"], out["rn"]

    def test_member_weight_breaks_tally_tie(self, api):
        """PRD §3.6: "Ranking is by higher tally, then by the higher count of
        member ballots — those with `weight` 2 — then by the earlier
        `checked_in_at`, then by the newer vehicle `year`; here `winner_score`
        holds the winning tally." PRD §3.6: "The ballot's `weight` is computed
        from the voter: 2 for a `club_member`, 1 otherwise."

        Design: Corner/calculations/peoples_choice_member_weight_tiebreak
        """
        ev, cls, rm, rn = self._setup_pc_event(api)
        vm1 = create_voter("VM1", "vm1@example.com", club_member=True)
        vm2 = create_voter("VM2", "vm2@example.com", club_member=True)
        cast_ballot(ev["id"], rm["id"], vm1["id"])
        cast_ballot(ev["id"], rm["id"], vm2["id"])
        vn1 = create_voter("VN1", "vn1@example.com")
        cast_ballot(ev["id"], rm["id"], vn1["id"])
        for i in range(2, 6):
            v = create_voter(f"VN{i}", f"vn{i}@example.com")
            cast_ballot(ev["id"], rn["id"], v["id"])
        finalize_event(ev["id"])
        awards = list_event_awards(ev["id"])
        pc = next(a for a in awards if a["award_kind"] == "PEOPLES_CHOICE")
        # RM: 2 member ballots (weight 2) + 1 non-member = tally 5, member_ballots 2.
        # RN: 5 non-member = tally 5, member_ballots 0. Tie broken at level 2.
        assert pc["winner_registration_id"] == rm["id"], (
            "tallies tie at 5; the member-ballot count (2 vs 0) decides")
        assert pc["winner_score"] == pytest.approx(5, abs=0.001)
        bos = next(a for a in awards if a["award_kind"] == "BEST_OF_SHOW")
        assert bos["winner_registration_id"] is None
        assert bos["tie_break_log"] == "INSUFFICIENT_ENTRIES", "no judged classes"

    def test_ballots_voided_when_vehicle_withdraws(self, api):
        """PRD §3.6: "A ballot is born `VALID` and flips to `VOID` the moment its
        voted registration becomes `WITHDRAWN` or `REFUNDED`." and "A class with
        zero valid ballots across all its entries keeps a null winner with
        `tie_break_log` recording `NO_VALID_BALLOTS`." PRD §3.6: "exceptionally,
        directly from `JUDGING` for people's-choice-only events, which have no
        judged class and therefore never auto-advance out of `JUDGING`."

        Design: Corner/calculations/ballots_voided_when_vehicle_withdraws
        """
        ev, cls, zone = create_open_event(
            class_overrides={"judging_mode": "PEOPLES_CHOICE", "award_depth": 1},
            zone_overrides={"arrival_window_start": "2026-08-15T08:00:00Z",
                            "arrival_window_end": "2026-08-15T10:00:00Z"})
        reg, veh = create_registrant_with_vehicle(name="VW", email="vw@example.com")
        sign_waiver(ev["id"], reg["id"], signature_name="VW")
        r1 = create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T08:30:00Z"}, ORG))
        r1 = check_in(r1["id"], zone["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T12:30:00Z"}, ORG))
        get_success_data(api.lock_registration(ev["id"], ORG))
        get_success_data(api.start_judging(ev["id"], ORG))
        voter = create_voter("Voter", "vtr@example.com")
        ballot = cast_ballot(ev["id"], r1["id"], voter["id"])
        get_success_data(api.withdraw_registration(r1["id"], {"reason": "left"}, DESK))
        ballot_after = validate_success(api.get_ballot(ballot["id"], ORG))
        assert ballot_after["status"] == "VOID"
        finalize_event(ev["id"])
        awards = list_event_awards(ev["id"])
        pc = next(a for a in awards if a["award_kind"] == "PEOPLES_CHOICE")
        assert pc["winner_registration_id"] is None
        assert pc["tie_break_log"] == "NO_VALID_BALLOTS"


class TestPresentGating:
    def test_award_present_on_pending_rejected(self, api):
        """PRD §3.6: "Presentation itself moves an award `FINALIZED` →
        `PRESENTED`, its terminal state, and presenting anything not yet
        `FINALIZED` is rejected with `ERR_INVALID_AWARD_STATE`."

        Design: Corner/errors/award_present_on_pending_rejected
        """
        ev, cls, zone = create_open_event()
        get_success_data(api.lock_registration(ev["id"], ORG))
        get_success_data(api.start_judging(ev["id"], ORG))
        awards = list_event_awards(ev["id"])
        assert len(awards) > 0
        pending = awards[0]
        assert pending["status"] == "PENDING"
        resp = api.present_award(pending["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_INVALID_AWARD_STATE)
        after = validate_success(api.get_award(pending["id"], ORG))
        assert after["status"] == "PENDING"
