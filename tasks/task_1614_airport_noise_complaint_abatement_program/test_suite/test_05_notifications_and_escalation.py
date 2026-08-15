"""Operator notifications: lifecycle legality, the response-length minimum, the
overdue auto-escalation sweep, the escalation standing cascade with grace
revocation, the linked-complaint close gate, and notification counter
conservation across the withdrawal cascade."""
from test_helpers import (
    ApiErrorId,
    assert_notification_cardinality,
    assert_same_instant,
    begin_review,
    correlate_complaint,
    close_complaint,
    create_complaint,
    create_complainant,
    create_notification,
    create_operated_flight,
    create_operator,
    make_complainant_headers,
    make_operator_rep_headers,
    send_notification,
    set_clock,
    setup_sent_notification,
    setup_responded_notification,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["noise_office_admin_headers"]
ANALYST = TEST_USERS["noise_analyst_headers"]
LIAISON = TEST_USERS["community_liaison_headers"]


def test_notification_acknowledge_from_draft_rejected(api):
    """PRD 3.5: "Acting on another operator's notification is rejected with
    `ERR_NOT_RESOURCE_OWNER`; acting from the wrong state is rejected with
    `ERR_INVALID_NOTIFICATION_STATE`."

    Design: Corner/state_machines/notification_acknowledge_from_draft_rejected
    """
    complainant = create_complainant(full_name="SM Six", email="sm6@x.com")
    complaint = create_complaint(complainant["id"], "2026-07-15T09:00:00Z")
    operator = create_operator(name="Air Ten")
    notification = create_notification(
        operator["id"], complaint_id=complaint["id"], severity="ADVISORY"
    )
    assert notification["status"] == "DRAFT"

    response = api.acknowledge_notification(
        notification["id"], {}, make_operator_rep_headers(operator["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_NOTIFICATION_STATE)


def test_notification_short_response_rejected(api):
    """PRD 3.5: "The representative then responds: the `response_text` must be at
    least twenty characters long (else `ERR_RESPONSE_TOO_SHORT`), and a valid
    response stamps `responded_at` and moves the notification to
    `RESPONSE_RECEIVED`."

    Design: Corner/state_machines/notification_short_response_rejected
    """
    ctx = setup_sent_notification()
    validate_success(
        api.acknowledge_notification(
            ctx["notification"]["id"], {}, make_operator_rep_headers(ctx["operator"]["id"])
        ),
        200,
    )

    response = api.respond_notification(
        ctx["notification"]["id"],
        {"response_text": "too short!"},
        make_operator_rep_headers(ctx["operator"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RESPONSE_TOO_SHORT)

    reread = validate_success(api.get_notification(ctx["notification"]["id"], ANALYST))
    assert reread["status"] == "ACKNOWLEDGED"


def test_notification_auto_escalates_after_due_at_on_clock_advance(api):
    """PRD 2.4: "Advancing the clock fires exactly one automatic sweep: any operator
    notification whose response deadline has passed while it sits unanswered is
    escalated, with the full escalation cascade that implies (see §3.5)."
    PRD 3.5: "Sending moves `DRAFT` to `SENT`: `sent_at` is stamped, `due_at` is set
    to exactly ten days after `sent_at` — the response SLA".
    PRD 3.5: "the operator's `compliance_standing` is demoted one level (`GOOD` to
    `WATCH`, `WATCH` to `PROBATION`, while `PROBATION` stays)".

    Design: Corner/state_machines/notification_auto_escalates_after_due_at_on_clock_advance
    """
    ctx = setup_sent_notification()
    # Sent at the startup clock 2026-08-01T00:00:00Z, so due 2026-08-11.
    assert_same_instant(ctx["notification"]["due_at"], "2026-08-11T00:00:00Z", "due_at")

    set_clock("2026-08-12T00:00:00Z")

    notification = validate_success(api.get_notification(ctx["notification"]["id"], ANALYST))
    assert notification["status"] == "ESCALATED"
    assert notification["severity"] == "ESCALATION"

    operator = validate_success(api.get_operator(ctx["operator"]["id"], ANALYST))
    assert operator["compliance_standing"] == "WATCH"
    assert operator["curfew_grace_minutes"] == 15


def _operator_with_two_sent_notifications(api):
    complainant = create_complainant(full_name="Esc One", email="esc1@x.com")
    operator = create_operator(name="Air Six")
    complaint_a = create_complaint(complainant["id"], "2026-07-15T12:02:00Z",
                                   disturbance_type="LOUD_EVENT")
    complaint_b = create_complaint(complainant["id"], "2026-07-16T12:02:00Z",
                                   channel="APP")
    n1 = create_notification(operator["id"], complaint_id=complaint_a["id"],
                             subject="Complaint 1")
    n2 = create_notification(operator["id"], complaint_id=complaint_b["id"],
                             subject="Complaint 2")
    send_notification(n1["id"])
    send_notification(n2["id"])
    return operator, n1, n2


def test_escalation_demotes_operator_standing_one_level_per_event(api):
    """PRD 3.5: "Either path moves the notification to `ESCALATED`, raises its
    `severity` to `ESCALATION`, records the `escalation_reason`, and fires
    **cascade C**: the operator's `compliance_standing` is demoted one level
    (`GOOD` to `WATCH`, `WATCH` to `PROBATION`, while `PROBATION` stays)".

    Design: Difficulty/transitive_cascade/notification_escalation_demotes_standing_and_revokes_grace
    """
    operator, n1, n2 = _operator_with_two_sent_notifications(api)
    assert operator["compliance_standing"] == "GOOD"

    escalated = validate_success(
        api.escalate_notification(n1["id"], {"escalation_reason": "no response"}, ADMIN), 200
    )
    assert escalated["status"] == "ESCALATED"
    assert escalated["severity"] == "ESCALATION"

    mid = validate_success(api.get_operator(operator["id"], ADMIN))
    assert mid["compliance_standing"] == "WATCH"

    validate_success(
        api.escalate_notification(n2["id"], {"escalation_reason": "repeat offender"}, ADMIN),
        200,
    )
    final = validate_success(api.get_operator(operator["id"], ADMIN))
    assert final["compliance_standing"] == "PROBATION"


def test_escalation_landing_on_probation_revokes_curfew_grace(api):
    """PRD 3.5: "an operator landing on `PROBATION` through escalation has its
    `curfew_grace_minutes` revoked to 0 and its future violation points weighted by
    the 1.25 standing multiplier."
    PRD 3.1: "A new operator begins with `compliance_standing` of `GOOD` and a
    `curfew_grace_minutes` allowance of 15 minutes".

    Design: Difficulty/transitive_cascade/notification_escalation_demotes_standing_and_revokes_grace
    """
    operator, n1, n2 = _operator_with_two_sent_notifications(api)
    assert operator["curfew_grace_minutes"] == 15

    validate_success(
        api.escalate_notification(n1["id"], {"escalation_reason": "no response"}, ADMIN), 200
    )
    after_first = validate_success(api.get_operator(operator["id"], ADMIN))
    # Hop two only fires when the demotion lands on PROBATION.
    assert after_first["compliance_standing"] == "WATCH"
    assert after_first["curfew_grace_minutes"] == 15

    validate_success(
        api.escalate_notification(n2["id"], {"escalation_reason": "repeat offender"}, ADMIN),
        200,
    )
    after_second = validate_success(api.get_operator(operator["id"], ADMIN))
    assert after_second["compliance_standing"] == "PROBATION"
    assert after_second["curfew_grace_minutes"] == 0


def test_notification_close_blocked_while_linked_complaint_open(api):
    """PRD 3.5: "From `RESPONSE_RECEIVED`, closing requires any linked complaint to
    be in a terminal state — `CLOSED_SUBSTANTIATED`, `CLOSED_UNSUBSTANTIATED`, or
    `WITHDRAWN` — else `ERR_LINKED_COMPLAINT_OPEN`".

    Design: Difficulty/cross_entity_state_dependency/notification_close_gated_by_linked_complaint_terminal
    """
    ctx = setup_responded_notification()
    # The linked complaint still sits in RECEIVED (non-terminal).
    response = api.close_notification(
        ctx["notification"]["id"], {"closed_outcome": "RESOLVED"}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_LINKED_COMPLAINT_OPEN)

    reread = validate_success(api.get_notification(ctx["notification"]["id"], ANALYST))
    assert reread["status"] == "RESPONSE_RECEIVED"


def test_notification_close_unlocks_after_complaint_terminal_with_on_time_credit(api):
    """PRD 3.5: "the notification becomes `CLOSED` with `closed_at` stamped and
    `closed_outcome` recorded as `RESOLVED`."
    PRD 3.5: "when `closed_at` is at or before `due_at` the operator's
    `on_time_responses_90d` — the count of notifications closed on time within the
    trailing ninety days — increments."

    Design: Difficulty/cross_entity_state_dependency/notification_close_gated_by_linked_complaint_terminal
    """
    complainant = create_complainant(full_name="Gate One", email="g1@x.com", zone_code="Z1")
    operator = create_operator(name="Air Seven")
    flight = create_operated_flight(
        operator["id"], "2026-07-15T12:00:00Z",
        scheduled_at="2026-07-15T11:55:00Z", zone_code="Z1",
    )
    complaint = create_complaint(complainant["id"], "2026-07-15T12:02:00Z",
                                 disturbance_type="LOUD_EVENT")
    version = begin_review(complaint["id"])
    notification = create_notification(operator["id"], complaint_id=complaint["id"])
    send_notification(notification["id"])
    validate_success(
        api.acknowledge_notification(
            notification["id"], {}, make_operator_rep_headers(operator["id"])
        ),
        200,
    )
    validate_success(
        api.respond_notification(
            notification["id"],
            {"response_text": "We adjusted the climb profile."},
            make_operator_rep_headers(operator["id"]),
        ),
        200,
    )

    # Drive the linked complaint to a terminal state.
    correlate_complaint(complaint["id"], version, flight_id=flight["id"])
    close_complaint(complaint["id"], "SUBSTANTIATED")

    closed = validate_success(
        api.close_notification(notification["id"], {"closed_outcome": "RESOLVED"}, ANALYST),
        200,
    )
    assert closed["status"] == "CLOSED"
    assert closed["closed_outcome"] == "RESOLVED"

    operator_after = validate_success(api.get_operator(operator["id"], ANALYST))
    # Closed on the same logical day it was sent, well inside the ten-day SLA.
    assert operator_after["on_time_responses_90d"] == 1
    assert operator_after["notifications_open"] == 0
    assert operator_after["notifications_closed"] == 1


def test_withdrawal_auto_closes_draft_notifications(api):
    """PRD 3.4: "Withdrawal fires **cascade D**: any linked operator notification
    still in `DRAFT` closes automatically to `AUTO_CLOSED` with `closed_outcome`
    `COMPLAINT_WITHDRAWN`, and the affected operators' notification counters are
    recomputed".

    Design: Difficulty/compensating_invariant/operator_notification_conservation_with_auto_close
    """
    complainant = create_complainant(full_name="Inv Two", email="inv2@x.com")
    operator = create_operator(name="Air Eight")
    complaint_a = create_complaint(complainant["id"], "2026-07-05T08:00:00Z",
                                   disturbance_type="LOUD_EVENT")
    complaint_b = create_complaint(complainant["id"], "2026-07-06T08:00:00Z")
    n1 = create_notification(operator["id"], complaint_id=complaint_a["id"],
                             severity="ADVISORY", subject="N1")
    n2 = create_notification(operator["id"], complaint_id=complaint_b["id"],
                             severity="ADVISORY", subject="N2")
    send_notification(n1["id"])

    validate_success(
        api.withdraw_complaint(
            complaint_b["id"], {}, make_complainant_headers(complainant["id"])
        ),
        200,
    )

    swept = validate_success(api.get_notification(n2["id"], ANALYST))
    assert swept["status"] == "AUTO_CLOSED"
    assert swept["closed_outcome"] == "COMPLAINT_WITHDRAWN"

    unaffected = validate_success(api.get_notification(n1["id"], ANALYST))
    assert unaffected["status"] == "SENT"


def test_notification_cardinality_and_sent_total_survive_auto_close(api):
    """PRD 3.5: "the invariant `notifications_draft` + `notifications_open` +
    `notifications_closed` equals the total notifications ever created for the
    operator holds at all times."
    PRD 3.5: "The `notifications_sent_total` counter is a lifetime count of
    notifications that reached `SENT` or beyond; a draft that is auto-closed
    without ever being sent never joins it."

    Design: Difficulty/compensating_invariant/operator_notification_conservation_with_auto_close
    """
    complainant = create_complainant(full_name="Inv Two", email="inv2@x.com")
    operator = create_operator(name="Air Eight")
    complaint_a = create_complaint(complainant["id"], "2026-07-05T08:00:00Z",
                                   disturbance_type="LOUD_EVENT")
    complaint_b = create_complaint(complainant["id"], "2026-07-06T08:00:00Z")
    n1 = create_notification(operator["id"], complaint_id=complaint_a["id"],
                             severity="ADVISORY", subject="N1")
    n2 = create_notification(operator["id"], complaint_id=complaint_b["id"],
                             severity="ADVISORY", subject="N2")
    send_notification(n1["id"])

    validate_success(
        api.withdraw_complaint(
            complaint_b["id"], {}, make_complainant_headers(complainant["id"])
        ),
        200,
    )

    operator_after = validate_success(api.get_operator(operator["id"], ANALYST))
    assert operator_after["notifications_draft"] == 0
    assert operator_after["notifications_open"] == 1
    assert operator_after["notifications_closed"] == 1
    assert_notification_cardinality(operator_after)
    # N2 went DRAFT -> AUTO_CLOSED without ever being sent.
    assert operator_after["notifications_sent_total"] == 1
