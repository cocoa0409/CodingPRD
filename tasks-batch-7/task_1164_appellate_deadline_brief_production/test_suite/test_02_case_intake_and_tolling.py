"""Case intake: judgment event, notice-of-appeal deadline, tolling, posture."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_case, assert_appeal_event, assert_deadline,
    assert_instant_equal, add_calendar_days, iso_utc, parse_ts,
    find_deadline,
    create_event_payload,
    create_court, create_attorney, create_case, attorney_headers,
    file_and_accept_notice,
    reset_clock,
    TEST_DEFAULTS,
)


def _noa_deadline(api, case_id, headers):
    res = api.list_case_deadlines(case_id, headers)
    data = get_success_data(res)
    rows = data if isinstance(data, list) else [data]
    return find_deadline(rows, "NOTICE_OF_APPEAL")


class TestCaseCreationCascade:
    def test_case_creation_creates_judgment_event_and_notice_deadline(self, api):
        """PRD §3.2: "The new case opens with `posture` set to `OPEN`, and two
        things happen automatically: an appeal event of `event_type`
        `JUDGMENT_ENTERED` is recorded with its `occurred_at` taken from
        `judgment_entered_at`, and a deadline of `kind` `NOTICE_OF_APPEAL` is
        created with its `basis_event_id` pointing back at that judgment event."
        PRD §3.2: "The provisional figure, `provisional_due_at`, is computed
        immediately from the judgment event: take the judgment event's
        `occurred_at`, add the court's `appeal_deadline_days` calendar days
        preserving the time-of-day, and — when the court's
        `weekend_holiday_rollforward` flag is set — keep advancing one calendar
        day at a time while the result lands on a weekend or a court holiday."

        Design: Corner/entities/case_creation_cascade_creates_record_and_schedule
        """
        reset_clock()
        court = create_court(code="CC1", appeal_deadline_days=30,
                             weekend_holiday_rollforward=False)
        attorney = create_attorney(admitted_court_ids=[court["id"]])
        res = api.create_case(
            {
                "court_id": court["id"],
                "docket_number": "CC-1",
                "caption": "CC1",
                "lead_attorney_id": attorney["id"],
                "appellant_side": "APPELLANT",
                "judgment_entered_at": "2026-05-01T00:00:00Z",
            },
            attorney_headers(attorney),
        )
        case = validate_success(res, 201)
        assert_case(case)
        assert case["posture"] == "OPEN"

        headers = attorney_headers(attorney)
        events = get_success_data(api.list_events(case["id"], headers))
        events = events if isinstance(events, list) else [events]
        assert len(events) == 1, f"expected exactly one auto-created event, got {len(events)}"
        assert_appeal_event(events[0])
        assert events[0]["event_type"] == "JUDGMENT_ENTERED"
        assert_instant_equal(events[0]["occurred_at"], "2026-05-01T00:00:00Z")

        deadline = _noa_deadline(api, case["id"], headers)
        assert_deadline(deadline)
        assert deadline["basis_event_id"] == events[0]["id"], (
            "NOTICE_OF_APPEAL deadline must point back at the judgment event"
        )
        expected = iso_utc(add_calendar_days("2026-05-01T00:00:00Z", 30))
        assert_instant_equal(deadline["provisional_due_at"], expected)
        assert_instant_equal(deadline["final_due_at"], expected)

    def test_case_posture_open_initial_state(self, api):
        """PRD §3.2: "The new case opens with `posture` set to `OPEN`, and two
        things happen automatically: an appeal event of `event_type`
        `JUDGMENT_ENTERED` is recorded with its `occurred_at` taken from
        `judgment_entered_at`, and a deadline of `kind` `NOTICE_OF_APPEAL` is
        created with its `basis_event_id` pointing back at that judgment event."

        Design: Corner/state_machines/case_posture_open_initial_state
        """
        reset_clock()
        court = create_court(code="SM4")
        attorney = create_attorney(admitted_court_ids=[court["id"]])
        case = create_case(court, attorney)
        assert case["posture"] == "OPEN", f"new case posture must be OPEN, got {case['posture']}"


class TestDerivedPosture:
    def test_posture_reconciles_to_record_pending_on_notice_accept(self, api):
        """PRD §3.2: "When the clerk accepts that filing, the case's
        `notice_filed_at` is set to the filing's `filed_at`, the case's posture
        moves from `OPEN` to `RECORD_PENDING`, and three auto-creations fire: a
        record row in `PENDING_DESIGNATION`, a briefing schedule row in
        `PENDING`, and deadline rows of kinds `RECORD_DESIGNATION` and
        `TRANSCRIPT_ORDER`."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_case_posture
        """
        reset_clock()
        court = create_court(code="CC-DFR")
        attorney = create_attorney(admitted_court_ids=[court["id"]])
        case = create_case(court, attorney)
        assert case["posture"] == "OPEN"

        filing = file_and_accept_notice(case, attorney)
        headers = attorney_headers(attorney)
        case_after = validate_success(api.get_case(case["id"], headers), 200)
        assert case_after["posture"] == "RECORD_PENDING", (
            f"posture after accepted notice must be RECORD_PENDING, got {case_after['posture']}"
        )
        filing_after = validate_success(api.get_filing(filing["id"], headers), 200)
        assert filing_after["status"] == "ACCEPTED"
        assert_instant_equal(
            case_after["notice_filed_at"], filing_after["filed_at"],
            "notice_filed_at must be set from the filing's filed_at",
        )


class TestNoticeOfAppealTolling:
    """Difficulty rule: dual_variant_calc — provisional vs final deadline."""

    def _setup_tolled_case(self, api):
        reset_clock()
        court = create_court(code="CA9", jurisdiction_type="FEDERAL",
                             appeal_deadline_days=30, weekend_holiday_rollforward=False)
        attorney = create_attorney(admitted_court_ids=[court["id"]])
        case = create_case(court, attorney,
                           judgment_entered_at="2026-06-01T12:00:00Z")
        return court, attorney, case

    def test_provisional_equals_final_until_tolling_event(self, api):
        """PRD §3.2: "The operative figure, `final_due_at`, simply equals the
        provisional figure until something adjusts it; a deadline row also tracks
        `tolled` (whether a tolling event currently suspends it), `met` (whether
        the corresponding act has been performed), and `met_at` (when it was
        satisfied, null while unmet)."
        PRD §3.2: "When a `POST_JUDGMENT_MOTION_FILED` event lands, the case's
        unmet `NOTICE_OF_APPEAL` deadline is marked `tolled` — the clock is
        suspended."

        Design: Difficulty/dual_variant_calc/notice_of_appeal_provisional_vs_final_after_tolling
        """
        _, attorney, case = self._setup_tolled_case(api)
        headers = attorney_headers(attorney)

        deadline = _noa_deadline(api, case["id"], headers)
        expected = iso_utc(add_calendar_days("2026-06-01T12:00:00Z", 30))
        assert_instant_equal(deadline["provisional_due_at"], expected)
        assert_instant_equal(deadline["final_due_at"], deadline["provisional_due_at"])
        assert deadline["tolled"] is False

        res = api.create_event(
            case["id"],
            create_event_payload("POST_JUDGMENT_MOTION_FILED", "2026-06-05T00:00:00Z"),
            headers,
        )
        validate_success(res, 201)
        deadline = _noa_deadline(api, case["id"], headers)
        assert deadline["tolled"] is True, "unmet NOTICE_OF_APPEAL must be tolled once a post-judgment motion is filed"
        assert_instant_equal(deadline["provisional_due_at"], expected)

    def test_final_due_at_extends_by_tolling_delta_on_motion_decision(self, api):
        """PRD §3.2: "When the matching `POST_JUDGMENT_MOTION_DECIDED` event
        lands, tolling resolves: the system finds the most recent
        `POST_JUDGMENT_MOTION_FILED` event occurring before the decision event,
        measures the elapsed time from that filing to the decision, and sets
        `final_due_at` on each unmet `NOTICE_OF_APPEAL` deadline to
        `provisional_due_at` plus that tolling delta, clearing `tolled` back to
        false."

        Design: Difficulty/dual_variant_calc/notice_of_appeal_provisional_vs_final_after_tolling
        """
        _, attorney, case = self._setup_tolled_case(api)
        headers = attorney_headers(attorney)
        validate_success(api.create_event(
            case["id"],
            create_event_payload("POST_JUDGMENT_MOTION_FILED", "2026-06-05T00:00:00Z"),
            headers,
        ), 201)
        validate_success(api.create_event(
            case["id"],
            create_event_payload("POST_JUDGMENT_MOTION_DECIDED", "2026-06-25T00:00:00Z"),
            headers,
        ), 201)

        deadline = _noa_deadline(api, case["id"], headers)
        expected_provisional = iso_utc(add_calendar_days("2026-06-01T12:00:00Z", 30))
        expected_final = iso_utc(add_calendar_days("2026-06-01T12:00:00Z", 30 + 20))
        assert_instant_equal(
            deadline["provisional_due_at"], expected_provisional,
            "provisional must stay anchored to judgment + appeal_deadline_days",
        )
        assert_instant_equal(
            deadline["final_due_at"], expected_final,
            "final must equal provisional plus the 20-day tolling delta",
        )
        assert parse_ts(deadline["final_due_at"]) != parse_ts(deadline["provisional_due_at"])
        assert deadline["tolled"] is False, "tolled must clear once the motion is decided"
