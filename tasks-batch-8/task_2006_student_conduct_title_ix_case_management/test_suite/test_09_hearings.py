"""Hearings: scheduling rules, calendar buffer, adjourn cycle, cross-exam."""
from test_helpers import (
    ApiErrorId,
    appoint_both_advisors,
    ask_question,
    close_cross_exam,
    convene_hearing,
    create_case,
    cross_exam_question_payload,
    drive_case_to_deliberation,
    drive_to_hearing_preparation,
    get_case,
    hearing_payload,
    make_advisor_headers,
    make_cast,
    make_coordinator_headers,
    make_decision_maker_headers,
    rule_question,
    schedule_hearing,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


def _case_with_scheduled_hearing(cast, categories=("OTHER_SEX_BASED",), slot="2026-09-01T10:00:00Z"):
    """Drive to HEARING_PREPARATION, appoint both advisors, schedule a hearing."""
    case = create_case(cast, categories=list(categories))
    drive_to_hearing_preparation(case["id"], cast)
    appoint_both_advisors(case["id"], cast)
    hearing = schedule_hearing(case["id"], cast["coord"]["id"], cast["dm"]["id"], scheduled_at=slot)
    return case, hearing


def _case_with_in_session_hearing(cast, categories=("OTHER_SEX_BASED",)):
    case, hearing = _case_with_scheduled_hearing(cast, categories=categories)
    hearing = convene_hearing(hearing["id"], cast["dm"]["id"])
    return case, hearing


class TestHearingCancelGate:
    def test_hearing_cancel_from_in_session_rejected(self, api):
        """PRD 3.4: "A `SCHEDULED` hearing may be cancelled by the decision-maker
        or the coordinator (`SCHEDULED → CANCELLED`, `HEARING_CANCELLED`), and
        dismissal of the case cascades a cancellation onto hearings in
        `SCHEDULED` or `ADJOURNED` (§3.1); `COMPLETED` and `CANCELLED` are the
        hearing's terminal states."
        PRD 2.11: "**State** — the target entity must be in a from-state from which
        the requested transition exists in its machine, with terminal states
        rejecting all further transitions (`ERR_INVALID_STATE_TRANSITION`, 409)".

        Design: Corner/state_machines/hearing_cancel_from_in_session_rejected
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case, hearing = _case_with_in_session_hearing(cast)
        resp = api.cancel_hearing(hearing["id"], make_decision_maker_headers(cast["dm"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        after = validate_success(
            api.get_hearing(hearing["id"], make_coordinator_headers(cast["coord"]["id"]))
        )
        assert after["status"] == "IN_SESSION", "in-flight hearings are not cancelled"


class TestHearingLeadTime:
    def test_hearing_ten_day_lead_boundary(self, api):
        """PRD 2.8: "The hearing lead rule is re-checked at hearing scheduling:
        the hearing's `scheduled_at` must be at least 10 days after the
        scheduling instant, in addition to being strictly in the future. A
        shortfall is rejected with `ERR_NOTICE_LEAD_TIME_INSUFFICIENT` (422)."
        PRD 3.4: "A scheduled hearing lands in `SCHEDULED`, automatically issues
        the `HEARING` notice to `BOTH` parties with the hearing time as its
        `scheduled_event_at`, appends `HEARING_SCHEDULED`, and increments the
        case `version`."

        Design: Corner/calculations/hearing_ten_day_lead_boundary
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm")
        case = create_case(cast, categories=["SEXUAL_HARASSMENT"], received_via="EMAIL")
        drive_to_hearing_preparation(case["id"], cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        # Scheduling at the default clock 2026-08-01T00:00:00Z: one second under
        # ten days of lead is a shortfall.
        short = api.schedule_hearing(
            case["id"],
            hearing_payload(cast["dm"]["id"], scheduled_at="2026-08-10T23:59:59Z"),
            coord_h,
        )
        validate_error(short, ApiErrorId.ERR_NOTICE_LEAD_TIME_INSUFFICIENT)

        # Exactly ten days out is accepted ("at least 10 days").
        exact = api.schedule_hearing(
            case["id"],
            hearing_payload(cast["dm"]["id"], scheduled_at="2026-08-11T00:00:00Z"),
            coord_h,
        )
        hearing = validate_success(exact, 201)
        assert hearing["status"] == "SCHEDULED"
        notices, _ = validate_paginated(api.list_case_notices(case["id"], coord_h))
        hearing_notices = [n for n in notices if n["notice_type"] == "HEARING"]
        assert len(hearing_notices) == 1
        assert hearing_notices[0]["recipient_side"] == "BOTH"


class TestLiveHearingSingleton:
    def test_second_live_hearing_rejected(self, api):
        """PRD 3.4: "Only one hearing per case may be live — `SCHEDULED`,
        `IN_SESSION`, `ADJOURNED`, or `DELIBERATION` — failing as
        `ERR_ACTIVE_HEARING_EXISTS` (409)."

        Design: Corner/validations/second_live_hearing_rejected
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "dm2", "advc", "advr")
        case = create_case(cast, categories=["SEXUAL_HARASSMENT"], received_via="EMAIL")
        drive_to_hearing_preparation(case["id"], cast)
        schedule_hearing(case["id"], cast["coord"]["id"], cast["dm"]["id"])

        # A second hearing fails even with a free decision-maker at a
        # conflict-free time.
        resp = api.schedule_hearing(
            case["id"],
            hearing_payload(
                cast["dm2"]["id"], scheduled_at="2026-09-05T10:00:00Z",
                modality="IN_PERSON",
            ),
            make_coordinator_headers(cast["coord"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_HEARING_EXISTS)


class TestAdjournReconveneCycle:
    def test_hearing_adjourn_reconvene_cycle_reason_cleared(self, api):
        """PRD 3.4: "In session, the hearing may **adjourn** — requiring a
        non-empty `adjourn_reason`, which is recorded — moving `IN_SESSION →
        ADJOURNED` with `HEARING_ADJOURNED`, and later **reconvene**, moving
        `ADJOURNED → IN_SESSION`, clearing `adjourn_reason`, and appending
        `HEARING_RECONVENED`; the adjourn/reconvene loop may repeat any number
        of times while questions accumulate and are ruled."

        Design: Difficulty/non_linear_state_machine/hearing_adjourn_reconvene_cycle
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case, hearing = _case_with_in_session_hearing(cast)
        dm_h = make_decision_maker_headers(cast["dm"]["id"])
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        adjourned = validate_success(
            api.adjourn_hearing(hearing["id"], {"adjourn_reason": "lunch recess"}, dm_h)
        )
        assert adjourned["status"] == "ADJOURNED"
        assert adjourned["adjourn_reason"] == "lunch recess"
        reconvened = validate_success(api.reconvene_hearing(hearing["id"], dm_h))
        assert reconvened["status"] == "IN_SESSION"
        assert reconvened.get("adjourn_reason") is None, "reconvene clears the reason"

        # Second lap: the cycle is re-enterable.
        validate_success(
            api.adjourn_hearing(hearing["id"], {"adjourn_reason": "party ill"}, dm_h)
        )
        again = validate_success(api.reconvene_hearing(hearing["id"], dm_h))
        assert again["status"] == "IN_SESSION"
        assert again.get("adjourn_reason") is None

    def test_hearing_cycle_question_sequence_accumulates(self, api):
        """PRD 3.4: "The question lands in `PENDING` with a 1-based `sequence` in
        submission order within the hearing and `QUESTION_ASKED` appended; every
        question is bound to its hearing through `hearing_id`."
        PRD 3.4: "the adjourn/reconvene loop may repeat any number of times
        while questions accumulate and are ruled."

        Design: Difficulty/non_linear_state_machine/hearing_adjourn_reconvene_cycle
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case, hearing = _case_with_in_session_hearing(cast)
        dm_h = make_decision_maker_headers(cast["dm"]["id"])

        q1 = ask_question(hearing["id"], cast["advc"]["id"], "RESPONDENT", "Q one")
        assert q1["sequence"] == 1 and q1["ruling"] == "PENDING"

        api.adjourn_hearing(hearing["id"], {"adjourn_reason": "lunch recess"}, dm_h)
        api.reconvene_hearing(hearing["id"], dm_h)

        q2 = ask_question(hearing["id"], cast["advr"]["id"], "COMPLAINANT", "Q two")
        assert q2["sequence"] == 2, "sequence accumulates across the cycle, never resets"

        api.adjourn_hearing(hearing["id"], {"adjourn_reason": "party ill"}, dm_h)
        api.reconvene_hearing(hearing["id"], dm_h)

        questions, _ = validate_paginated(
            api.list_cross_exam_questions(
                hearing["id"], make_coordinator_headers(cast["coord"]["id"])
            )
        )
        assert [q["sequence"] for q in questions] == [1, 2]


class TestCrossExamEligibility:
    def test_cross_exam_questioner_must_be_opposing_advisor(self, api):
        """PRD 3.4: "The asker must hold an `ACTIVE` appointment on the hearing's
        case, and the `target_side` must be the *opposing* side of the asker's
        appointment — advisors cross-examine the other party, never their own —
        failing as `ERR_QUESTIONER_NOT_CASE_ADVISOR` (422)."

        Design: Corner/validations/cross_exam_questioner_must_be_opposing_advisor
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr", "out")
        case, hearing = _case_with_in_session_hearing(cast)

        # (a) An advisor-eligible person with no appointment on the case.
        outsider = api.ask_cross_exam_question(
            hearing["id"],
            cross_exam_question_payload(cast["out"]["id"], "RESPONDENT",
                                        question_text="outsider question"),
            make_advisor_headers(cast["out"]["id"]),
        )
        validate_error(outsider, ApiErrorId.ERR_QUESTIONER_NOT_CASE_ADVISOR)

        # (b) The complainant's advisor cannot target their own side.
        own_side = api.ask_cross_exam_question(
            hearing["id"],
            cross_exam_question_payload(cast["advc"]["id"], "COMPLAINANT",
                                        question_text="own-side question"),
            make_advisor_headers(cast["advc"]["id"]),
        )
        validate_error(own_side, ApiErrorId.ERR_QUESTIONER_NOT_CASE_ADVISOR)

        questions, meta = validate_paginated(
            api.list_cross_exam_questions(
                hearing["id"], make_coordinator_headers(cast["coord"]["id"])
            )
        )
        assert questions == [] and meta["total_count"] == 0, (
            "rejected questions must not persist"
        )


class TestCrossExamRulingGates:
    def test_cross_exam_disallow_reason_and_pending_gate(self, api):
        """PRD 3.4: "a ruling of `DISALLOWED` — the relevance exclusion — requires
        a non-empty `ruling_reason` explaining it on the record, records the
        reason, moves the question `PENDING → DISALLOWED`, and appends
        `QUESTION_RULED`."
        PRD 3.4: "When cross-examination is complete, the decision-maker closes
        it — again, anyone else is `ERR_NOT_HEARING_DECISION_MAKER` — and the
        hearing must have **zero** questions still `PENDING`, failing as
        `ERR_PENDING_QUESTIONS_REMAIN` (422). Closing moves the hearing
        `IN_SESSION → DELIBERATION`, moves the case `HEARING_IN_PROGRESS →
        DELIBERATION`, appends `CROSS_EXAM_CLOSED`, and increments the case
        `version`."
        PRD 2.11: "**Request schema** — missing required fields, wrong types, unknown
        enum members, empty arrays where a non-empty array is required, and
        malformed datetimes, failing as `ERR_INVALID_REQUEST` (400)."

        Design: Corner/state_machines/cross_exam_disallow_reason_and_pending_gate
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm", "advc", "advr")
        case, hearing = _case_with_in_session_hearing(cast)
        dm_h = make_decision_maker_headers(cast["dm"]["id"])
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        q1 = ask_question(hearing["id"], cast["advc"]["id"], "RESPONDENT", "Q one")
        q2 = ask_question(hearing["id"], cast["advr"]["id"], "COMPLAINANT", "Q two")

        # A relevance exclusion must be explained on the record.
        no_reason = api.rule_cross_exam_question(
            q1["id"], {"ruling": "DISALLOWED"}, dm_h
        )
        validate_error(no_reason, ApiErrorId.ERR_INVALID_REQUEST)

        disallowed = rule_question(q1["id"], cast["dm"]["id"], "DISALLOWED",
                                   ruling_reason="not relevant")
        assert disallowed["ruling"] == "DISALLOWED"
        assert disallowed["ruling_reason"] == "not relevant"

        # The aggregate gate reads child rows: q2 still PENDING blocks the close.
        blocked = api.close_cross_exam(hearing["id"], dm_h)
        validate_error(blocked, ApiErrorId.ERR_PENDING_QUESTIONS_REMAIN)

        rule_question(q2["id"], cast["dm"]["id"], "ALLOWED")
        closed = close_cross_exam(hearing["id"], cast["dm"]["id"])
        assert closed["status"] == "DELIBERATION"
        assert get_case(case["id"], cast["coord"]["id"])["status"] == "DELIBERATION"


class TestDecisionMakerCalendarBuffer:
    def _two_cases_in_hearing_preparation(self, cast):
        case_a = create_case(cast, categories=["SEXUAL_HARASSMENT"])
        drive_to_hearing_preparation(case_a["id"], cast)
        case_b = create_case(cast, categories=["STALKING"], received_via="EMAIL",
                             occurred_at="2026-07-16T22:00:00Z")
        drive_to_hearing_preparation(case_b["id"], cast)
        return case_a, case_b

    def test_decision_maker_calendar_buffer_gap(self, api):
        """PRD 2.8: "For any one decision-maker, the occupancy intervals of that
        person's non-cancelled hearings must neither overlap nor sit closer than
        a 60-minute buffer on either side: a gap of exactly 60 minutes passes,
        and a gap of 59 minutes fails. Conflicts are rejected with
        `ERR_HEARING_TIME_CONFLICT` (422)."

        Design: Difficulty/resource_temporal_overlap/decision_maker_calendar_buffer_gap
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm")
        case_a, case_b = self._two_cases_in_hearing_preparation(cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        # Case A hearing occupies [2026-09-01T10:00, 2026-09-01T11:00).
        schedule_hearing(case_a["id"], cast["coord"]["id"], cast["dm"]["id"])

        # 59-minute gap after the prior hearing's end: rejected.
        tight = api.schedule_hearing(
            case_b["id"],
            hearing_payload(cast["dm"]["id"], scheduled_at="2026-09-01T11:59:00Z"),
            coord_h,
        )
        validate_error(tight, ApiErrorId.ERR_HEARING_TIME_CONFLICT)

        # Exactly 60 minutes of buffer passes.
        ok = api.schedule_hearing(
            case_b["id"],
            hearing_payload(cast["dm"]["id"], scheduled_at="2026-09-01T12:00:00Z"),
            coord_h,
        )
        hearing_b = validate_success(ok, 201)
        assert hearing_b["status"] == "SCHEDULED"

    def test_decision_maker_calendar_lists_both_hearings(self, api):
        """PRD 3.4: "Hearings list per case with a `status` filter, and a
        filtered calendar list by `decision_maker_id` and `status` supports
        occupancy discovery."
        PRD 2.8: "For any one decision-maker, the occupancy intervals of that
        person's non-cancelled hearings must neither overlap nor sit closer than
        a 60-minute buffer on either side: a gap of exactly 60 minutes passes,
        and a gap of 59 minutes fails."

        Design: Difficulty/resource_temporal_overlap/decision_maker_calendar_buffer_gap
        """
        cast = make_cast("comp", "resp", "coord", "inv", "dm")
        case_a, case_b = self._two_cases_in_hearing_preparation(cast)
        coord_h = make_coordinator_headers(cast["coord"]["id"])

        hearing_a = schedule_hearing(case_a["id"], cast["coord"]["id"], cast["dm"]["id"])
        tight = api.schedule_hearing(
            case_b["id"],
            hearing_payload(cast["dm"]["id"], scheduled_at="2026-09-01T11:59:00Z"),
            coord_h,
        )
        validate_error(tight, ApiErrorId.ERR_HEARING_TIME_CONFLICT)
        hearing_b = validate_success(
            api.schedule_hearing(
                case_b["id"],
                hearing_payload(cast["dm"]["id"], scheduled_at="2026-09-01T12:00:00Z"),
                coord_h,
            ),
            201,
        )

        calendar, _ = validate_paginated(
            api.list_hearings(coord_h, params={"decision_maker_id": cast["dm"]["id"]})
        )
        calendar_ids = {h["id"] for h in calendar}
        assert calendar_ids == {hearing_a["id"], hearing_b["id"]}, (
            "the rejected 59-minute attempt must not occupy the calendar"
        )
