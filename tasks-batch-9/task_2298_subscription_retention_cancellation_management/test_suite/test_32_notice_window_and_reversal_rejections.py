"""Two guards that read history rather than the request: the statutory window and reversibility.

A reminder must be scheduled inside the window the law leaves for it, and a ledger row that
has already been undone cannot be undone twice — the compensating row it produced is the
only trace either operation leaves behind.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_instant,
    new_core_plan,
    notices_for,
    get_success_data,
    modifications_for,
    read_modification,
    read_subscription,
    request_modification,
    reverse_modification_payload,
    schedule_notice_payload,
    setup_active_subscription,
    validate_error,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]
RETENTION = TEST_USERS["retention_specialist_headers"]


class TestStatutoryReminderWindow:

    def test_a_reminder_with_one_day_of_lead_time_is_refused(self):
        """The window for the 2026-02-07 renewal closes on 2026-02-04, so 2026-02-06 is out.

        PRD §3.4: "When the notice type is `RENEWAL_REMINDER`, the supplied `scheduled_for`
        must itself lie inside the closed reminder window, and an instant outside it is
        rejected with `ERR_NOTICE_WINDOW_INVALID` (422)."

        Design: Corner/errors/scheduling_a_reminder_outside_the_statutory_window_is_rejected
        """
        plan = new_core_plan(renewal_reminder_days_before=10)
        world = setup_active_subscription(
            clock="2026-01-10", plan=plan,
            subscriber_overrides={"acquisition_channel": "SEARCH"})

        payload = schedule_notice_payload("RENEWAL_REMINDER", "2026-02-06T00:00:00Z",
                                          channel="EMAIL")
        validate_error(api_client.schedule_compliance_notice(
            world["subscription"]["id"], payload, COMPLIANCE),
            ApiErrorId.ERR_NOTICE_WINDOW_INVALID, 422)

        reminders = notices_for(world["subscription"]["id"], notice_type="RENEWAL_REMINDER")
        assert len(reminders) == 1
        assert_instant(reminders[0]["scheduled_for"], "2026-01-28T00:00:00Z", "scheduled_for")
        assert reminders[0]["state"] == "SCHEDULED"

        assert_instant(read_subscription(world["subscription"]["id"])["next_renewal_at"],
                       "2026-02-07T00:00:00Z", "next_renewal_at")


class TestReversalIsOnceOnly:

    def test_an_already_reversed_row_cannot_be_reversed_again(self):
        """The ledger keeps exactly the original and its compensating row, nothing more.

        PRD §3.3: "It is only meaningful on a row whose `state` is `APPLIED` or `SCHEDULED`;
        a row in `REQUESTED`, `REVERSED` or `CANCELLED` is rejected with
        `ERR_MODIFICATION_NOT_REVERSIBLE` (409)."

        Design: Corner/errors/reversing_an_already_reversed_modification_is_rejected
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        applied = request_modification(
            world["subscription"]["id"], "FREQUENCY_CHANGE", world["subscriber_headers"],
            frequency_weeks=8)
        get_success_data(api_client.reverse_modification(
            applied["id"], RETENTION, reverse_modification_payload(reason_note="undo")))

        validate_error(api_client.reverse_modification(
            applied["id"], RETENTION,
            reverse_modification_payload(reason_note="double undo")),
            ApiErrorId.ERR_MODIFICATION_NOT_REVERSIBLE, 409)

        assert read_modification(applied["id"])["state"] == "REVERSED"

        ledger = modifications_for(world["subscription"]["id"])
        assert len(ledger) == 2
        compensating = [row for row in ledger
                        if row["reverses_modification_id"] == applied["id"]]
        assert len(compensating) == 1

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["frequency_weeks"] == 4
        assert subscription["version"] == 3
