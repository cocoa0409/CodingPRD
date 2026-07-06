"""Reminders, the event-cancellation cascade, and sponsor/event computed reports."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    make_headers, fixtures,
)

PM = TEST_USERS["program_manager_headers"]
CS = TEST_USERS["clinical_staff_headers"]
NAV = TEST_USERS["patient_navigator_headers"]
BC = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Corner: state_machines — reminder not due / due after clock advance
# ---------------------------------------------------------------------------
def test_reminder_send_when_not_due_returns_error(api):
    """PRD §3.8: "the reminder must be due, meaning the logical clock's current time-of-day
    in minutes-from-midnight is at or past `send_at_min`, or the logical clock's current
    calendar date is later than the event's `event_date` (otherwise `ERR_REMINDER_NOT_DUE`)."
    PRD §2.6: "At startup the clock reads exactly `2026-05-01T00:00:00Z`."

    Design: Corner/state_machines/reminder_send_when_not_due_returns_error
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL",
                                                           event_date="2026-06-11")
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    appt = fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    reminder = validate_success(
        api.create_reminder({"appointment_id": appt["id"], "send_at_min": 500, "channel": "SMS"}, PM),
        expected_status=201,
    )
    # Clock still at 2026-05-01 default (before 2026-06-11, and 0 < 500 minutes-of-day)
    resp = api.send_reminder(reminder["id"], PM)
    validate_error(resp, ApiErrorId.ERR_REMINDER_NOT_DUE.value)
    reread = validate_success(api.get_reminder(reminder["id"], PM))
    assert reread["status"] == "PENDING"


def test_reminder_send_when_due_after_clock_advance_succeeds(api):
    """PRD §3.8: "Sending a reminder advances it from `PENDING` to `SENT`. The reminder must
    be `PENDING` (otherwise `ERR_INVALID_STATE`); the linked appointment must be in
    `SCHEDULED` or `CHECKED_IN` (otherwise `ERR_APPOINTMENT_NOT_ACTIVE`) — a cancelled,
    no-show, or closed appointment cannot be reminded; and the reminder must be due, meaning
    the logical clock's current time-of-day in minutes-from-midnight is at or past
    `send_at_min`"
    PRD §2.6: "A `ProgramManager` may advance or reset the clock by supplying a target
    instant in the `to_iso8601` field"

    Design: Corner/state_machines/reminder_send_when_due_after_clock_advance_succeeds
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL",
                                                           event_date="2026-06-11")
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    appt = fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    reminder = validate_success(
        api.create_reminder({"appointment_id": appt["id"], "send_at_min": 500, "channel": "SMS"}, PM),
        expected_status=201,
    )
    # Advance clock to 09:00 (540 minutes-of-day) on the event date → 540 >= 500
    validate_success(api.set_clock("2026-06-11T09:00:00Z", PM))
    data = validate_success(api.send_reminder(reminder["id"], PM))
    assert data["status"] == "SENT", f"expected SENT, got {data['status']}"


# ---------------------------------------------------------------------------
# Corner: cross_cutting — event cancel cascades to pending reminder
# ---------------------------------------------------------------------------
def test_event_cancel_cascades_pending_reminder_to_cancelled(api):
    """PRD §3.2: "Cancelling from `PUBLISHED` triggers a three-hop cascade: first, every
    appointment on the event that is in `SCHEDULED` or `CHECKED_IN` transitions to
    `CANCELLED` (this cancellation does not increment the participant's no-show strikes)."
    PRD §3.2: "Second, for each of those just-cancelled appointments, every reminder tied to
    it that is still `PENDING` transitions to `CANCELLED`, and — on the billing side — every
    charge tied to it that is in `DRAFT` or `ADJUDICATED` transitions to `VOID`; when such a
    charge drew a grant, that grant's `committed_cents` is reduced by the charge's
    `grant_covered_cents`, restoring headroom."

    Design: Corner/cross_cutting_complexity_layers/event_cancel_cascade_cancels_pending_reminder
    """
    unit, sponsor, event = fixtures.create_published_event(modality="BLOOD_PANEL",
                                                           event_date="2026-06-11")
    participant = fixtures.register_participant(pay_type="SELF_PAY")
    appt = fixtures.book_appointment(event["id"], participant["id"], slot_start_min=540)
    reminder = validate_success(
        api.create_reminder({"appointment_id": appt["id"], "send_at_min": 500, "channel": "SMS"}, PM),
        expected_status=201,
    )
    validate_success(api.cancel_event(event["id"], PM))
    rem = validate_success(api.get_reminder(reminder["id"], PM))
    assert rem["status"] == "CANCELLED", f"expected reminder CANCELLED, got {rem['status']}"
    appt_reread = validate_success(api.get_appointment(appt["id"], PM))
    assert appt_reread["status"] == "CANCELLED", f"expected appointment CANCELLED, got {appt_reread['status']}"


# NOTE: Difficulty/transitive_cascade/event_cancel_cascade_depth3_to_grant is SKIPPED.
# Its asserted outcome (event cancel restores Grant.committed_cents 8000 -> 0 via a voided
# charge) is not PRD-derivable: PRD §3.2 cascades only appointments in SCHEDULED or CHECKED_IN,
# while a charge exists only after screening (§3.7 creates the charge at SCREEN, which moves
# the appointment to SCREENED). A SCREENED appointment is outside the cascade set, so a
# PRD-faithful implementation leaves committed_cents at 8000 — the instance's committed==0
# assertion would fail a correct implementation. Gap left as a gap per the Core rule.


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula — sponsor report nested rates
# ---------------------------------------------------------------------------
def test_sponsor_report_abnormal_rate(api):
    """PRD §3.9: "It returns `events_published` — the number of the sponsor's events in
    `PUBLISHED` or `CLOSED`; `total_screened` — the number of appointments across those
    events in `SCREENED`, `RESULT_READY`, or `CLOSED`; `abnormal_count` — the number of
    appointments in `RESULT_READY` or `CLOSED` whose `result` is `ABNORMAL`; and
    `abnormal_rate_pct` — the abnormal count divided by the total screened, multiplied by 100
    and rounded half up to a whole percent (0 when nothing has been screened)."

    Design: Difficulty/combinatorial_formula/sponsor_report_nested_rates_mode_a
    """
    # One sponsor, one mammography event, two INSURANCE participants: A ABNORMAL, B NORMAL.
    unit = fixtures.create_unit(modality="MAMMOGRAPHY")
    fixtures.create_staff("TECHNOLOGIST", "MAMMOGRAPHY", full_name="Tech T")
    fixtures.create_staff("RADIOLOGIST", "MAMMOGRAPHY", full_name="Rad R")
    sponsor = fixtures.create_sponsor(sponsor_type="EMPLOYER", viewer_user_id="sv1")
    event = fixtures.create_event(sponsor["id"], unit["id"], modality="MAMMOGRAPHY",
                                 event_date="2026-06-10")
    event = fixtures.publish_event(event)
    pa = fixtures.register_participant(pay_type="INSURANCE", insurance_member_id="INS-A", full_name="Pat A")
    pb = fixtures.register_participant(pay_type="INSURANCE", insurance_member_id="INS-B",
                                       full_name="Pat B", date_of_birth="1972-01-01")
    aa = fixtures.book_appointment(event["id"], pa["id"], slot_start_min=540)
    ab = fixtures.book_appointment(event["id"], pb["id"], slot_start_min=570)
    for a in (aa, ab):
        validate_success(api.consent_appointment(a["id"], CS))
        validate_success(api.checkin_appointment(a["id"], CS))
        validate_success(api.screen_appointment(a["id"], CS))
    validate_success(api.deliver_result(aa["id"], {"result": "ABNORMAL", "flagged_urgent": False}, CS))
    validate_success(api.deliver_result(ab["id"], {"result": "NORMAL"}, CS))

    report = validate_success(api.get_sponsor_report(sponsor["id"], PM))
    assert report["total_screened"] == 2, f"expected total_screened 2, got {report['total_screened']}"
    assert report["abnormal_count"] == 1, f"expected abnormal_count 1, got {report['abnormal_count']}"
    assert report["abnormal_rate_pct"] == 50, f"expected abnormal_rate_pct 50, got {report['abnormal_rate_pct']}"
    assert report["referrals_total"] == 1, f"expected referrals_total 1, got {report['referrals_total']}"


def test_sponsor_report_events_published_count(api):
    """PRD §3.9: "It returns `events_published` — the number of the sponsor's events in
    `PUBLISHED` or `CLOSED`"

    Design: Difficulty/combinatorial_formula/sponsor_report_nested_rates_mode_a
    """
    unit = fixtures.create_unit(modality="MAMMOGRAPHY")
    fixtures.create_staff("TECHNOLOGIST", "MAMMOGRAPHY", full_name="Tech T")
    fixtures.create_staff("RADIOLOGIST", "MAMMOGRAPHY", full_name="Rad R")
    sponsor = fixtures.create_sponsor(sponsor_type="EMPLOYER", viewer_user_id="sv1")
    event = fixtures.create_event(sponsor["id"], unit["id"], modality="MAMMOGRAPHY",
                                 event_date="2026-06-10")
    event = fixtures.publish_event(event)
    pa = fixtures.register_participant(pay_type="INSURANCE", insurance_member_id="INS-A", full_name="Pat A")
    pb = fixtures.register_participant(pay_type="INSURANCE", insurance_member_id="INS-B",
                                       full_name="Pat B", date_of_birth="1972-01-01")
    aa = fixtures.book_appointment(event["id"], pa["id"], slot_start_min=540)
    ab = fixtures.book_appointment(event["id"], pb["id"], slot_start_min=570)
    for a in (aa, ab):
        validate_success(api.consent_appointment(a["id"], CS))
        validate_success(api.checkin_appointment(a["id"], CS))
        validate_success(api.screen_appointment(a["id"], CS))
    validate_success(api.deliver_result(aa["id"], {"result": "ABNORMAL", "flagged_urgent": False}, CS))
    validate_success(api.deliver_result(ab["id"], {"result": "NORMAL"}, CS))

    report = validate_success(api.get_sponsor_report(sponsor["id"], PM))
    assert report["events_published"] == 1, f"expected events_published 1, got {report['events_published']}"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula — event fill rate (ratio-then-round)
# ---------------------------------------------------------------------------
def test_event_summary_fill_and_show_rate(api):
    """PRD §3.2: "The fill rate is the booked count divided by capacity, multiplied by 100,
    then rounded half up to a whole percent — the ratio is formed first and rounded once at
    the end, never by rounding the counts beforehand. The show rate is the screened count
    divided by the booked count, multiplied by 100, then rounded half up to a whole percent,
    applying the same ratio-then-round discipline"

    Design: Difficulty/combinatorial_formula/event_fill_rate_ratio_then_round_mode_b
    """
    # capacity 10, 3 booked, 2 screened → fill = round(3/10*100)=30, show = round(2/3*100)=67
    unit = fixtures.create_unit(modality="BLOOD_PANEL", daily_capacity=10)
    fixtures.create_staff("PHLEBOTOMIST", "BLOOD_PANEL", full_name="Phleb P")
    sponsor = fixtures.create_sponsor(sponsor_type="EMPLOYER", viewer_user_id="sv1")
    event = fixtures.create_event(sponsor["id"], unit["id"], modality="BLOOD_PANEL",
                                 event_date="2026-06-11")
    event = fixtures.publish_event(event)
    parts = [
        fixtures.register_participant(pay_type="SELF_PAY", full_name=f"P{i}",
                                      date_of_birth=f"198{i}-01-01")
        for i in range(3)
    ]
    appts = [
        fixtures.book_appointment(event["id"], parts[i]["id"], slot_start_min=540 + 30 * i)
        for i in range(3)
    ]
    # Screen 2 of the 3
    for a in appts[:2]:
        validate_success(api.consent_appointment(a["id"], CS))
        validate_success(api.checkin_appointment(a["id"], CS))
        validate_success(api.screen_appointment(a["id"], CS))

    summary = validate_success(api.get_event_summary(event["id"], PM))
    assert summary["booked_count"] == 3, f"expected booked_count 3, got {summary['booked_count']}"
    assert summary["screened_count"] == 2, f"expected screened_count 2, got {summary['screened_count']}"
    assert summary["fill_rate_pct"] == 30, f"expected fill_rate_pct 30, got {summary['fill_rate_pct']}"
    assert summary["show_rate_pct"] == 67, f"expected show_rate_pct 67, got {summary['show_rate_pct']}"


def test_event_summary_show_rate_ratio_then_round(api):
    """PRD §3.2: "The show rate is the screened count divided by the booked count, multiplied
    by 100, then rounded half up to a whole percent, applying the same ratio-then-round
    discipline; when the booked count is zero, the show rate is reported as 0."

    Design: Difficulty/combinatorial_formula/event_fill_rate_ratio_then_round_mode_b
    """
    unit = fixtures.create_unit(modality="BLOOD_PANEL", daily_capacity=10)
    fixtures.create_staff("PHLEBOTOMIST", "BLOOD_PANEL", full_name="Phleb P")
    sponsor = fixtures.create_sponsor(sponsor_type="EMPLOYER", viewer_user_id="sv1")
    event = fixtures.create_event(sponsor["id"], unit["id"], modality="BLOOD_PANEL",
                                 event_date="2026-06-11")
    event = fixtures.publish_event(event)
    parts = [
        fixtures.register_participant(pay_type="SELF_PAY", full_name=f"P{i}",
                                      date_of_birth=f"198{i}-01-01")
        for i in range(3)
    ]
    appts = [
        fixtures.book_appointment(event["id"], parts[i]["id"], slot_start_min=540 + 30 * i)
        for i in range(3)
    ]
    for a in appts[:2]:
        validate_success(api.consent_appointment(a["id"], CS))
        validate_success(api.checkin_appointment(a["id"], CS))
        validate_success(api.screen_appointment(a["id"], CS))
    summary = validate_success(api.get_event_summary(event["id"], PM))
    # 2/3 = 0.6667 → 66.67% → 67 (ratio-then-round; rounding counts first would misbehave)
    assert summary["show_rate_pct"] == 67, f"expected show_rate_pct 67, got {summary['show_rate_pct']}"


# ---------------------------------------------------------------------------
# Corner: rbac — unknown role rejected
# ---------------------------------------------------------------------------
def test_unknown_role_returns_user_context_error(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. This check precedes every other check on
    every endpoint."

    Design: Corner/rbac/missing_user_context_header_returns_400
    """
    resp = api.create_mobile_unit(
        {"name": "Van A", "modality": "MAMMOGRAPHY", "daily_capacity": 10},
        make_headers("NotARole", "u-1"),
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)
