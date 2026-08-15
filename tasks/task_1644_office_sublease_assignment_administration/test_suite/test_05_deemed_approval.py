"""Deemed approval: business-day deadline, reminder gate, and the exact firing instant (PRD §2.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    add_certified_measurement,
    build_submitted_transfer,
    create_draft_transfer,
    get_review_fresh,
    get_transfer,
    make_tenant_headers,
    set_clock,
    standard_portfolio,
    submit_transfer,
    validate_error,
)


def test_consent_deadline_skips_weekend(api):
    """PRD §3.4: "The deadline arithmetic is business-day arithmetic per §2.5: counting begins on the first business day strictly after the submission calendar day — for a submission landing on a Saturday or Sunday, counting begins the following Monday — and advances one business day at a time, skipping weekends, until the lease's `consent_window_business_days` count is exhausted; the deadline lands at exactly 17:00:00.000Z on that final counted day."
    PRD §2.5: "Business days are Monday through Friday; Saturdays and Sundays are skipped, and there is no holiday calendar. A business day ends at exactly 17:00:00.000Z, and every deadline in this domain lands at that instant on its final counted day."

    Design: Corner/calculations/consent_deadline_business_day_weekend_skip
    """
    ctx = standard_portfolio(clock=CLOCK["FRIDAY_SUBMIT"])
    transfer = create_draft_transfer(ctx)
    add_certified_measurement(transfer["id"])
    submitted = submit_transfer(transfer["id"])

    assert submitted["submitted_at"] == CLOCK["FRIDAY_SUBMIT"]
    # Fri 8/14 submission: bd1 Mon 8/17 ... bd5 Fri 8/21 — the weekend is skipped.
    assert submitted["consent_deadline"] == CLOCK["FRIDAY_DEADLINE"]


def test_reminder_before_deadline_premature(api):
    """PRD §3.6: "a notice sent while the clock is still at or before the deadline, after the review has been decided, or twice over is rejected with `ERR_REMINDER_PREMATURE` (HTTP 409). A valid notice stamps `reminder_sent_at` with the logical clock."

    Design: Corner/cross_cutting_layers/reminder_before_deadline_premature
    """
    ctx = build_submitted_transfer(clock=CLOCK["MONDAY_SUBMIT"])
    tr_id = ctx["transfer"]["id"]
    tenant = make_tenant_headers(ctx["pt"]["id"])

    resp = api.remind_transfer_request(tr_id, tenant)
    validate_error(resp, ApiErrorId.ERR_REMINDER_PREMATURE, 409)

    set_clock(CLOCK["JUST_AFTER_DEADLINE"])
    reminded = api.remind_transfer_request(tr_id, tenant)
    assert reminded.status_code == 200
    transfer = get_transfer(tr_id)
    assert transfer["reminder_sent_at"] == CLOCK["JUST_AFTER_DEADLINE"]

    resp2 = api.remind_transfer_request(tr_id, tenant)
    validate_error(resp2, ApiErrorId.ERR_REMINDER_PREMATURE, 409)


def test_remind_rejected_when_deemed_approval_disabled(api):
    """PRD §3.6: "Where `deemed_approval_enabled` is false, landlord silence is never consent, and a reminder notice sent on such a lease is rejected with `ERR_DEEMED_APPROVAL_DISABLED` (HTTP 409) — a rejection that takes precedence over `ERR_REMINDER_PREMATURE` when both could apply."

    Design: Corner/state_machines/remind_rejected_when_deemed_approval_disabled
    """
    ctx = build_submitted_transfer(
        clock=CLOCK["MONDAY_SUBMIT"],
        lease_overrides={"deemed_approval_enabled": False},
    )
    set_clock("2026-08-18T10:00:00.000Z")  # past the Monday 8/17 17:00Z deadline
    resp = api.remind_transfer_request(
        ctx["transfer"]["id"], make_tenant_headers(ctx["pt"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DEEMED_APPROVAL_DISABLED, 409)

    transfer = get_transfer(ctx["transfer"]["id"])
    assert transfer.get("reminder_sent_at") is None
    assert transfer["status"] == "SUBMITTED"


def test_deemed_approval_fires_exactly_at_instant(api):
    """PRD §3.6: "When the clock reaches or passes the instant two business days after the consent deadline — the same business-day counting and the same 17:00:00.000Z landing rule as the deadline itself — and the lease has deemed approval enabled, the review is still `PENDING`, and `reminder_sent_at` is set to an instant at or after the `consent_deadline`, the transfer auto-transitions from `SUBMITTED` or `CONSENT_PENDING` to `DEEMED_APPROVED`."

    Design: Difficulty/boundary_precision_check/deemed_approval_timer_boundary_one_minute
    """
    ctx = build_submitted_transfer(clock=CLOCK["MONDAY_SUBMIT"])
    tr_id = ctx["transfer"]["id"]

    set_clock(CLOCK["AFTER_DEADLINE"])  # 2026-08-17T18:00Z: past the deadline
    resp = api.remind_transfer_request(tr_id, make_tenant_headers(ctx["pt"]["id"]))
    assert resp.status_code == 200

    set_clock(CLOCK["DEEMED_INSTANT_MINUS_1MIN"])
    assert get_transfer(tr_id)["status"] == "SUBMITTED", (
        "one minute before deadline + 2 business days the timer has not fired"
    )

    set_clock(CLOCK["DEEMED_INSTANT"])
    transfer = get_transfer(tr_id)
    assert transfer["status"] == "DEEMED_APPROVED"
    assert transfer["consent_granted_at"] == CLOCK["DEEMED_INSTANT"]


def test_deemed_approval_never_releases_liability(api):
    """PRD §3.6: "The transition stamps `consent_granted_at`, flips the review's `decision` to `GRANTED` with `decided_at` set, and — because no landlord ever spoke — the deemed grant never carries conditions and never releases the assignor: `release_of_assignor` is forced to false."

    Design: Difficulty/boundary_precision_check/deemed_approval_timer_boundary_one_minute
    """
    ctx = build_submitted_transfer(clock=CLOCK["MONDAY_SUBMIT"])
    tr_id = ctx["transfer"]["id"]

    set_clock(CLOCK["AFTER_DEADLINE"])
    api.remind_transfer_request(tr_id, make_tenant_headers(ctx["pt"]["id"]))
    set_clock(CLOCK["DEEMED_INSTANT"])

    transfer = get_transfer(tr_id)
    assert transfer["status"] == "DEEMED_APPROVED"
    assert transfer["liability_released"] is False, "deemed approval never releases"

    review = get_review_fresh(ctx["consent_review"]["id"])
    assert review["decision"] == "GRANTED"
    assert review["decided_at"] is not None
    assert review["release_of_assignor"] is False
    assert review["conditions_imposed_count"] == 0, "a deemed grant carries no conditions"
