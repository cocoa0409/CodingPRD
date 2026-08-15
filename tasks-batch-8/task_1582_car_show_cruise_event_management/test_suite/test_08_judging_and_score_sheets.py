"""Judging: score sheet creation gates, submission bubble-up, reopen cycle,
no-show handling, and judge assignment/conflict rules."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_judge_headers,
    create_criteria_scores, create_score_sheet_payload, create_judge_payload,
    create_event_with_class_and_zone, create_open_event,
    create_registrant_with_vehicle, create_paid_registration,
    sign_waiver, check_in, setup_judging_event, judge_create_and_submit_sheet,
    get_judge,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


class TestSheetSubmitBubbleUp:
    def _setup(self, api):
        """JUDGING event, judged class, ONE judge, TWO checked-in entries."""
        return setup_judging_event(num_registrations=2, judged=True,
                                   award_depth=1, num_judges=1)

    def test_first_submit_leaves_event_judging(self, api):
        """PRD §3.5: "if this submission was the last outstanding
        registration-by-judge pair of the last incomplete judged class, the event
        auto-transitions `JUDGING` → `TABULATING`".

        Design: Difficulty/transitive_cascade/sheet_submit_bubble_up_locks_sheets
        """
        s = self._setup(api)
        judge = s["judges"][0]
        sheet = judge_create_and_submit_sheet(
            s["registrations"][0]["id"], judge["id"],
            criteria_scores=create_criteria_scores(exterior=9, interior=8, engine=8,
                                                   authenticity=9, condition=8))
        assert sheet["status"] == "SUBMITTED"
        ev_mid = validate_success(api.get_event(s["event"]["id"], ORG))
        assert ev_mid["lifecycle_status"] == "JUDGING", (
            "the second entry's pair is still outstanding; the event must not advance")

    def test_last_submit_bubbles_to_tabulating_and_locks_sheets(self, api):
        """PRD §3.5: "if this submission was the last outstanding
        registration-by-judge pair of the last incomplete judged class, the event
        auto-transitions `JUDGING` → `TABULATING`, and every `SUBMITTED` score
        sheet for the event locks into `LOCKED`, its terminal state."

        Design: Difficulty/transitive_cascade/sheet_submit_bubble_up_locks_sheets
        """
        s = self._setup(api)
        judge = s["judges"][0]
        s1 = judge_create_and_submit_sheet(
            s["registrations"][0]["id"], judge["id"],
            criteria_scores=create_criteria_scores(exterior=9, interior=8, engine=8,
                                                   authenticity=9, condition=8))
        s2 = judge_create_and_submit_sheet(
            s["registrations"][1]["id"], judge["id"],
            criteria_scores=create_criteria_scores(exterior=7, interior=7, engine=7,
                                                   authenticity=7, condition=7))
        ev_end = validate_success(api.get_event(s["event"]["id"], ORG))
        assert ev_end["lifecycle_status"] == "TABULATING"
        s1_after = validate_success(api.get_score_sheet(s1["id"], ORG))
        s2_after = validate_success(api.get_score_sheet(s2["id"], ORG))
        assert s1_after["status"] == "LOCKED"
        assert s2_after["status"] == "LOCKED"


class TestSheetSubmitReopenCycle:
    def _setup(self, api):
        return setup_judging_event(num_registrations=1, judged=True,
                                   award_depth=1, num_judges=2)

    def test_submit_reopen_resubmit_status_cycle(self, api):
        """PRD §3.5: "An `Organizer` may send a `SUBMITTED` sheet back to `DRAFT`
        — with an optional `reason` — but only while the event remains in
        `JUDGING`".

        Design: Difficulty/non_linear_state_machine/score_sheet_submit_reopen_cycle
        """
        s = self._setup(api)
        judge = s["judges"][0]
        sheet = judge_create_and_submit_sheet(
            s["registrations"][0]["id"], judge["id"],
            criteria_scores=create_criteria_scores(exterior=9, interior=8, engine=8,
                                                   authenticity=9, condition=8))
        assert sheet["status"] == "SUBMITTED"
        reopened = validate_success(api.reopen_score_sheet(sheet["id"], {"reason": "math error"}, ORG))
        assert reopened["status"] == "DRAFT"
        resubmitted = validate_success(api.submit_score_sheet(sheet["id"], make_judge_headers(judge["id"])))
        assert resubmitted["status"] == "SUBMITTED"

    def test_submitted_count_tracks_cycle_and_event_stays_judging(self, api):
        """PRD §3.5: "Reopening decrements the judge's `submitted_sheet_count` by
        one, and a later resubmission raises it again by one, so the count always
        equals the judge's sheets currently in `SUBMITTED` or `LOCKED`."

        Design: Difficulty/non_linear_state_machine/score_sheet_submit_reopen_cycle
        """
        s = self._setup(api)
        judge = s["judges"][0]
        sheet = judge_create_and_submit_sheet(
            s["registrations"][0]["id"], judge["id"],
            criteria_scores=create_criteria_scores(exterior=9, interior=8, engine=8,
                                                   authenticity=9, condition=8))
        validate_success(api.reopen_score_sheet(sheet["id"], {"reason": "math error"}, ORG))
        validate_success(api.submit_score_sheet(sheet["id"], make_judge_headers(judge["id"])))
        judge_after = get_judge(s["event"]["id"], judge["id"])
        assert judge_after["submitted_sheet_count"] == 1, "+1 submit, -1 reopen, +1 resubmit"
        ev = validate_success(api.get_event(s["event"]["id"], ORG))
        assert ev["lifecycle_status"] == "JUDGING", (
            "the second judge's outstanding pair blocks auto-TABULATING")


class TestTemporalBeatsAssignment:
    def _setup(self, api):
        """JUDGING event with judged classes A and B; R1 CHECKED_IN in class B;
        J9 assigned only to A; JX assigned to B but never sheets (keeps the event
        in JUDGING); clock after judging_end_at."""
        # PRD §3.1 restricts class creation to DRAFT/PUBLISHED: create both
        # classes before opening registration.
        ev, cls_b, zone = create_event_with_class_and_zone(
            class_overrides={"code": "CLB", "name": "Class B", "min_year": 1976,
                             "max_year": 1995, "judging_mode": "JUDGED", "award_depth": 1},
            zone_overrides={"arrival_window_start": "2026-08-15T08:00:00Z",
                            "arrival_window_end": "2026-08-15T10:00:00Z"})
        cls_a = get_success_data(api.create_class(
            ev["id"], {"code": "CLA", "name": "Class A", "min_year": 1950,
                       "max_year": 1975, "prereg_fee_cents": 3000,
                       "day_of_fee_cents": 4500, "capacity": 40,
                       "judging_mode": "JUDGED", "award_depth": 1}, ORG))
        get_success_data(api.publish_event(ev["id"], ORG))
        ev = get_success_data(api.open_registration(ev["id"], ORG))
        reg, veh = create_registrant_with_vehicle(
            name="Late", email="late@example.com",
            vehicle_overrides={"year": 1985, "make": "Buick", "model": "Grand National"})
        sign_waiver(ev["id"], reg["id"], signature_name="Late")
        r1 = create_paid_registration(ev["id"], reg["id"], veh["id"], cls_b["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T08:30:00Z"}, ORG))
        check_in(r1["id"], zone["id"])
        j9 = get_success_data(api.create_judge(
            ev["id"], create_judge_payload(name="J9", email="j9@example.com",
                                           assigned_class_ids=[cls_a["id"]]), ORG))
        jx = get_success_data(api.create_judge(
            ev["id"], create_judge_payload(name="JX", email="jx@example.com",
                                           assigned_class_ids=[cls_b["id"]]), ORG))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T12:30:00Z"}, ORG))
        get_success_data(api.lock_registration(ev["id"], ORG))
        get_success_data(api.start_judging(ev["id"], ORG))
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T15:00:00Z"}, ORG))
        return ev, r1, j9

    def test_late_sheet_reports_window_not_assignment(self, api):
        """PRD §2.9: "And because temporal checks at level 8 sit above constraints
        at level 9, a sheet submitted outside the judging window reports
        `ERR_JUDGING_WINDOW_CLOSED` rather than an assignment error."

        Design: Difficulty/priority_pair_validation_conflict/sheet_temporal_beats_judge_assignment
        """
        ev, r1, j9 = self._setup(api)
        resp = api.create_score_sheet(
            create_score_sheet_payload(
                r1["id"], criteria_scores=create_criteria_scores(
                    exterior=9, interior=8, engine=8, authenticity=9, condition=8)),
            make_judge_headers(j9["id"]))
        validate_error(resp, ApiErrorId.ERR_JUDGING_WINDOW_CLOSED)

    def test_late_sheet_creates_no_row(self, api):
        """PRD §3.5: "Creation is a temporal operation too, accepted only inside
        the judging window from `judging_start_at` (inclusive) to
        `judging_end_at` (exclusive), else `ERR_JUDGING_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/sheet_temporal_beats_judge_assignment
        """
        ev, r1, j9 = self._setup(api)
        api.create_score_sheet(
            create_score_sheet_payload(
                r1["id"], criteria_scores=create_criteria_scores(
                    exterior=9, interior=8, engine=8, authenticity=9, condition=8)),
            make_judge_headers(j9["id"]))
        sheets = get_success_data(api.list_score_sheets(
            ORG, params={"judge_id": j9["id"], "registration_id": r1["id"]}))
        assert sheets == [], "no sheet row may be created for the rejected attempt"


class TestNoShowHandling:
    def test_no_show_auto_transition_at_start_judging(self, api):
        """PRD §3.4: "When judging begins, every registration still sitting in
        `CONFIRMED` — the gate no-shows — flips to `NO_SHOW` and the class count
        drops accordingly."

        Design: Corner/state_machines/no_show_auto_transition_at_start_judging
        """
        from test_helpers import get_class
        s = setup_judging_event(num_registrations=2, judged=False, award_depth=1,
                                num_judges=0, checked_in=[1])
        r1 = validate_success(api.get_registration(s["registrations"][0]["id"], ORG))
        r2 = validate_success(api.get_registration(s["registrations"][1]["id"], ORG))
        assert r1["status"] == "NO_SHOW", "never arrived; flipped by start-judging"
        assert r2["status"] == "CHECKED_IN", "checked-in entries are untouched"
        cls_after = get_class(s["event"]["id"], s["cls"]["id"])
        assert cls_after["confirmed_count"] == 1, "NO_SHOW is excluded from the count"

    def test_sheet_for_no_show_registration_rejected(self, api):
        """PRD §3.5: "The target registration must be a `CHECKED_IN` entry in one
        of the judge's assigned classes". PRD §5: `ERR_INVALID_REGISTRATION_STATE`
        409.

        Design: Corner/validations/sheet_for_no_show_registration_rejected
        """
        s = setup_judging_event(num_registrations=2, judged=True, award_depth=1,
                                num_judges=1, checked_in=[1])
        judge = s["judges"][0]
        no_show = s["registrations"][0]
        assert no_show["status"] == "NO_SHOW"
        resp = api.create_score_sheet(
            create_score_sheet_payload(
                no_show["id"], criteria_scores=create_criteria_scores(
                    exterior=9, interior=8, engine=8, authenticity=9, condition=8)),
            make_judge_headers(judge["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REGISTRATION_STATE)


class TestJudgeEligibility:
    def test_judge_conflict_of_interest_rejected(self, api):
        """PRD §3.5: "may never score a class they compete in: when the judge's
        `email` matches a registrant holding a non-terminal registration in that
        same class, creation is rejected with `ERR_JUDGE_CONFLICT_OF_INTEREST`."

        Design: Corner/validations/judge_conflict_of_interest_rejected
        """
        ev, cls, zone = create_open_event(
            class_overrides={"judging_mode": "JUDGED", "award_depth": 1},
            zone_overrides={"arrival_window_start": "2026-08-15T08:00:00Z",
                            "arrival_window_end": "2026-08-15T10:00:00Z"})
        reg, veh = create_registrant_with_vehicle(name="Shared", email="share@example.com")
        sign_waiver(ev["id"], reg["id"], signature_name="Shared")
        r1 = create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T08:30:00Z"}, ORG))
        check_in(r1["id"], zone["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T12:30:00Z"}, ORG))
        judge = get_success_data(api.create_judge(
            ev["id"], create_judge_payload(name="JudgeSelf", email="share@example.com",
                                           assigned_class_ids=[cls["id"]]), ORG))
        get_success_data(api.lock_registration(ev["id"], ORG))
        get_success_data(api.start_judging(ev["id"], ORG))
        resp = api.create_score_sheet(
            create_score_sheet_payload(
                r1["id"], criteria_scores=create_criteria_scores(
                    exterior=9, interior=8, engine=8, authenticity=9, condition=8)),
            make_judge_headers(judge["id"]))
        validate_error(resp, ApiErrorId.ERR_JUDGE_CONFLICT_OF_INTEREST)

    def test_judge_not_assigned_rejected(self, api):
        """PRD §3.5: "an entry in a class outside the judge's
        `assigned_class_ids` is rejected with `ERR_JUDGE_NOT_ASSIGNED`."

        Design: Corner/validations/judge_not_assigned_rejected
        """
        s = setup_judging_event(num_registrations=1, judged=True, award_depth=1,
                                num_judges=1)
        outsider = get_success_data(api.create_judge(
            s["event"]["id"],
            create_judge_payload(name="J0", email="j0@example.com", assigned_class_ids=[]),
            ORG))
        resp = api.create_score_sheet(
            create_score_sheet_payload(
                s["registrations"][0]["id"], criteria_scores=create_criteria_scores(
                    exterior=9, interior=8, engine=8, authenticity=9, condition=8)),
            make_judge_headers(outsider["id"]))
        validate_error(resp, ApiErrorId.ERR_JUDGE_NOT_ASSIGNED)

    def test_duplicate_score_sheet_rejected(self, api):
        """PRD §3.5: "A judge may hold only one sheet per registration — a second
        is rejected with `ERR_DUPLICATE_SCORE_SHEET`".

        Design: Corner/validations/duplicate_score_sheet_rejected
        """
        s = setup_judging_event(num_registrations=2, judged=True, award_depth=1,
                                num_judges=2)
        judge = s["judges"][0]
        target = s["registrations"][0]
        first = get_success_data(api.create_score_sheet(
            create_score_sheet_payload(target["id"], criteria_scores=create_criteria_scores(
                exterior=9, interior=8, engine=8, authenticity=9, condition=8)),
            make_judge_headers(judge["id"])))
        resp = api.create_score_sheet(
            create_score_sheet_payload(target["id"], criteria_scores=create_criteria_scores(
                exterior=5, interior=5, engine=5, authenticity=5, condition=5)),
            make_judge_headers(judge["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCORE_SHEET)
        sheets = get_success_data(api.list_score_sheets(
            ORG, params={"judge_id": judge["id"], "registration_id": target["id"]}))
        assert len(sheets) == 1
        assert sheets[0]["id"] == first["id"]


class TestLockedSheetTerminal:
    def test_sheet_submit_when_locked_rejected(self, api):
        """PRD §3.5: "The sheet must be in `DRAFT` — a `SUBMITTED` or `LOCKED`
        sheet yields `ERR_INVALID_SCORE_SHEET_STATE`, and per §2.9 this own-state
        check is reported before the event's state is examined."

        Design: Corner/errors/sheet_submit_when_locked_rejected
        """
        s = setup_judging_event(num_registrations=1, judged=True, award_depth=1,
                                num_judges=1)
        judge = s["judges"][0]
        sheet = judge_create_and_submit_sheet(
            s["registrations"][0]["id"], judge["id"],
            criteria_scores=create_criteria_scores(exterior=9, interior=8, engine=8,
                                                   authenticity=9, condition=8))
        # The sole judge's submit completed the class: the event is TABULATING
        # and the sheet is LOCKED.
        locked = validate_success(api.get_score_sheet(sheet["id"], ORG))
        assert locked["status"] == "LOCKED"
        resp = api.submit_score_sheet(sheet["id"], make_judge_headers(judge["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_SCORE_SHEET_STATE)
