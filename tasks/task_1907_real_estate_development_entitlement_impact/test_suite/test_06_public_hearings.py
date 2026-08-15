"""Public hearings: the statutory 20-day notice boundary and the cyclic
continue / re-notice / held path."""
from test_helpers import (
    ApiErrorId,
    assert_hearing,
    continue_hearing_payload,
    create_hearing_payload,
    get_application,
    renotice_hearing_payload,
    schedule_hearing,
    set_clock,
    setup_under_review_application,
    validate_error,
    validate_success,
)


class TestNoticeLeadBoundary:
    def test_notice_lead_exactly_twenty_days_accepted(self, api):
        """PRD 3.5: "the new hearing must satisfy the statutory notice lead: its
        `hearing_date` must fall at least 20 days after its `notice_posted_date`,
        where exactly 20 days satisfies the rule and 19 days is rejected with
        `ERR_INSUFFICIENT_NOTICE`."
        PRD 3.5: "the act of scheduling moves the application to
        `HEARING_SCHEDULED`."

        Design: Difficulty/boundary_precision_check/hearing_notice_lead_exactly_twenty_days
        """
        ctx = setup_under_review_application()
        hearing = schedule_hearing(
            ctx,
            hearing_date="2026-09-01T00:00:00Z",
            notice_posted_date="2026-08-12T00:00:00Z",
        )
        assert_hearing(hearing)
        assert hearing["status"] == "SCHEDULED"

        after = get_application(ctx["application"]["id"], ctx["reviewer_headers"])
        assert after["status"] == "HEARING_SCHEDULED", (
            f"scheduling must move the application to HEARING_SCHEDULED, "
            f"got {after['status']}"
        )

    def test_notice_lead_nineteen_days_rejected(self, api):
        """PRD 3.5: "exactly 20 days satisfies the rule and 19 days is rejected
        with `ERR_INSUFFICIENT_NOTICE`."

        Design: Difficulty/boundary_precision_check/hearing_notice_lead_exactly_twenty_days
        """
        ctx = setup_under_review_application()
        payload = create_hearing_payload(
            hearing_date="2026-09-01T00:00:00Z",
            notice_posted_date="2026-08-13T00:00:00Z",
        )
        response = api.create_hearing(
            ctx["application"]["id"], payload, ctx["reviewer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_NOTICE)

        after = get_application(ctx["application"]["id"], ctx["reviewer_headers"])
        assert after["status"] == "UNDER_REVIEW", (
            f"rejected scheduling must leave the application UNDER_REVIEW, "
            f"got {after['status']}"
        )


class TestContinueRenoticeCycle:
    def test_continue_renotice_held_cycle(self, api):
        """PRD 3.5: "staff may continue the hearing to a `new_hearing_date`,
        moving it to `CONTINUED`; a continued hearing is not terminal".
        PRD 3.5: "Returning a `CONTINUED` hearing to `SCHEDULED` requires a
        re-notice carrying a fresh `hearing_date` and `notice_posted_date` pair
        that again satisfies the 20-day lead."
        PRD 3.5: "Once the logical clock reaches the `hearing_date` — the
        boundary instant itself counts — staff mark the hearing `HELD`", and
        "marking a hearing held leaves the application parked in
        `HEARING_SCHEDULED` until someone advances it."

        Design: Difficulty/non_linear_state_machine/public_hearing_cyclic_continue_renotice
        """
        ctx = setup_under_review_application()
        hearing = schedule_hearing(ctx)
        hearing_id = hearing["id"]

        continued = validate_success(
            api.continue_hearing(
                hearing_id,
                continue_hearing_payload("2026-09-10T00:00:00Z"),
                ctx["reviewer_headers"],
            )
        )
        assert continued["status"] == "CONTINUED"

        # Re-notice against the NEW date with a 26-day lead (>= 20 days).
        renoticed = validate_success(
            api.renotice_hearing(
                hearing_id,
                renotice_hearing_payload(
                    "2026-09-10T00:00:00Z", "2026-08-15T00:00:00Z"
                ),
                ctx["reviewer_headers"],
            )
        )
        assert renoticed["status"] == "SCHEDULED", (
            f"valid re-notice must return the hearing to SCHEDULED, got {renoticed['status']}"
        )

        set_clock("2026-09-10T00:00:00Z")
        held = validate_success(
            api.mark_hearing_held(hearing_id, ctx["reviewer_headers"])
        )
        assert held["status"] == "HELD", (
            f"SCHEDULED→CONTINUED→SCHEDULED→HELD cycle must end HELD, got {held['status']}"
        )

        after = get_application(ctx["application"]["id"], ctx["reviewer_headers"])
        assert after["status"] == "HEARING_SCHEDULED", (
            "marking a hearing held must leave the application parked in "
            f"HEARING_SCHEDULED, got {after['status']}"
        )

    def test_renotice_with_insufficient_lead_against_new_date_rejected(self, api):
        """PRD 3.5: "Returning a `CONTINUED` hearing to `SCHEDULED` requires a
        re-notice carrying a fresh `hearing_date` and `notice_posted_date` pair
        that again satisfies the 20-day lead", and per PRD 3.5's notice rule
        "19 days is rejected with `ERR_INSUFFICIENT_NOTICE`" — the lead is
        re-validated against the NEW hearing date, not the original one.

        Design: Difficulty/non_linear_state_machine/public_hearing_cyclic_continue_renotice
        """
        ctx = setup_under_review_application()
        hearing = schedule_hearing(ctx)
        hearing_id = hearing["id"]
        validate_success(
            api.continue_hearing(
                hearing_id,
                continue_hearing_payload("2026-09-10T00:00:00Z"),
                ctx["reviewer_headers"],
            )
        )

        # 19-day lead measured against the new hearing date.
        response = api.renotice_hearing(
            hearing_id,
            renotice_hearing_payload("2026-09-10T00:00:00Z", "2026-08-22T00:00:00Z"),
            ctx["reviewer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_NOTICE)

        fetched = validate_success(api.get_hearing(hearing_id, ctx["reviewer_headers"]))
        assert fetched["status"] == "CONTINUED", (
            f"rejected re-notice must leave the hearing CONTINUED, got {fetched['status']}"
        )
