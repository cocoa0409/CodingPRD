"""Guardian notifications: channel selection, send gates, the retry cycle,
and the escalation sweep (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    create_athlete_as_trainer,
    create_injury_for,
    first_notification_for_athlete,
    make_parent_guardian_headers,
    make_trainer,
    set_clock,
    trainer_headers,
    validate_error,
    validate_success,
)


class TestChannelSelectionAndRetryCycle:

    def test_channel_choice_and_failed_send_retry_loop(self):
        """PRD §3.8: "a `channel` chosen at creation: `EMAIL` when the
        athlete's `guardian_email` is present, otherwise `PHONE`."
        PRD §3.8: "A transient carrier failure — surfaced in this environment
        as a `PHONE`-channel notification whose `guardian_phone` is the
        literal string `UNREACHABLE` — moves the notification to `FAILED`
        instead, still incrementing `attempts`."
        PRD §3.8: "A trainer requeues a `FAILED` notification with the retry
        action, moving it back to `QUEUED`; the queue–fail–retry loop can
        repeat until delivery succeeds."

        Design: Corner/state_machines/notification_failed_retry_cycle_and_channel_selection
        """
        tr1 = make_trainer()
        athlete_p = create_athlete_as_trainer(
            tr1, full_name="Athlete P", primary_sport="WRESTLING",
            guardian_user_id="g-9205", guardian_email=None,
            guardian_phone="UNREACHABLE")
        athlete_q = create_athlete_as_trainer(
            tr1, full_name="Athlete Q", grade=9, sex="F",
            primary_sport="TENNIS", team_level="FRESHMAN",
            guardian_user_id="g-9206", guardian_email="gq@x.com")
        create_injury_for(athlete_p["id"], tr1, body_region="KNEE",
                          mechanism="takedown")
        create_injury_for(athlete_q["id"], tr1, body_region="ARM_HAND",
                          injury_type="STRAIN", mechanism="swing")

        n_p = first_notification_for_athlete(athlete_p["id"], tr1)
        n_q = first_notification_for_athlete(athlete_q["id"], tr1)
        assert n_p["channel"] == "PHONE", "no email on file -> PHONE channel"
        assert n_q["channel"] == "EMAIL"

        failed = validate_success(api_client.send_guardian_notification(
            n_p["id"], trainer_headers(tr1)))
        assert failed["status"] == "FAILED"
        assert failed["attempts"] == 1

        requeued = validate_success(api_client.retry_guardian_notification(
            n_p["id"], trainer_headers(tr1)))
        assert requeued["status"] == "QUEUED"

        failed_again = validate_success(
            api_client.send_guardian_notification(
                n_p["id"], trainer_headers(tr1)))
        assert failed_again["status"] == "FAILED"
        assert failed_again["attempts"] == 2


class TestSendContactGate:

    def test_send_rejected_when_channel_contact_missing(self):
        """PRD §3.8: "Sending requires the notification to be `QUEUED` or
        `FAILED` (any other state draws `ERR_INVALID_STATE`) and requires the
        channel's contact point to exist on the athlete record —
        `guardian_email` for an `EMAIL` notification, `guardian_phone` for a
        `PHONE` one — otherwise the send is rejected with
        `ERR_GUARDIAN_CONTACT_MISSING`."

        Design: Corner/validations/guardian_contact_missing_on_send
        """
        tr1 = make_trainer()
        athlete = create_athlete_as_trainer(
            tr1, grade=9, sex="F", primary_sport="TRACK",
            team_level="FRESHMAN", guardian_user_id="g-9403",
            guardian_email=None, guardian_phone=None)
        create_injury_for(athlete["id"], tr1, body_region="LOWER_LEG",
                          injury_type="STRAIN", mechanism="sprint")
        notification = first_notification_for_athlete(athlete["id"], tr1)
        assert notification["channel"] == "PHONE", \
            "with no email the channel falls back to PHONE"

        resp = api_client.send_guardian_notification(
            notification["id"], trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_GUARDIAN_CONTACT_MISSING)

        after = validate_success(api_client.get_guardian_notification(
            notification["id"], trainer_headers(tr1)))
        assert after["status"] == "QUEUED", \
            "a rejection is not a delivery attempt"
        assert after["attempts"] == 0


class TestEscalationBoundary:

    def test_sent_escalates_at_exactly_24h_and_stays_acknowledgeable(self):
        """PRD §3.8: "The clock sweep moves a `SENT` notification to
        `ESCALATED` once the clock reaches twenty-four hours after `sent_at`
        (the boundary is inclusive) with no acknowledgement recorded."
        PRD §3.8: "Escalation does not close the loop — a `ParentGuardian`
        may acknowledge a notification in either `SENT` or `ESCALATED`,
        moving it to `ACKNOWLEDGED` and stamping `acknowledged_at`".

        Design: Corner/cross_cutting_layers/notification_escalation_at_24h_boundary
        """
        tr1 = make_trainer()
        athlete = create_athlete_as_trainer(
            tr1, sex="F", team_level="JV", guardian_user_id="g-9802",
            guardian_email="ga@x.com")
        create_injury_for(athlete["id"], tr1, body_region="KNEE",
                          mechanism="cut")
        notification = first_notification_for_athlete(athlete["id"], tr1)
        set_clock("2026-08-02T09:00:00Z")
        sent = validate_success(api_client.send_guardian_notification(
            notification["id"], trainer_headers(tr1)))
        assert_instant_equals(sent["sent_at"], "2026-08-02T09:00:00Z",
                              "sent_at")

        # One second before the window the notification is still SENT.
        set_clock("2026-08-03T08:59:59Z")
        before = validate_success(api_client.get_guardian_notification(
            notification["id"], trainer_headers(tr1)))
        assert before["status"] == "SENT"

        # At exactly sent_at + 24h the sweep escalates it.
        set_clock("2026-08-03T09:00:00Z")
        at = validate_success(api_client.get_guardian_notification(
            notification["id"], trainer_headers(tr1)))
        assert at["status"] == "ESCALATED"

        acked = validate_success(
            api_client.acknowledge_guardian_notification(
                notification["id"], make_parent_guardian_headers("g-9802")))
        assert acked["status"] == "ACKNOWLEDGED"
