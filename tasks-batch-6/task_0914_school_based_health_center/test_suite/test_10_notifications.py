"""Telling the family: which guardian is selected, when a notification is
suppressed, and how delivery, retry and acknowledgement behave."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_notification,
    assert_same_instant,
    complete_visit,
    deliver_notification,
    get_notification,
    make_guardian_headers,
    notifications_for_visit,
    set_clock,
    set_guardian_opt_out,
    setup_enrolled_student,
    setup_queued_visit_notification,
    setup_sent_visit_notification,
    setup_visit_in_progress,
    start_visit,
    schedule_visit,
    validate_error,
    validate_paginated,
)

NON_PRIMARY_FIRST = {
    "full_name": "Uncle Non Primary",
    "relationship": "OTHER",
    "contact_email": "uncle@example.org",
    "is_primary": False,
}
PRIMARY_SECOND = {
    "full_name": "Mai Nguyen",
    "relationship": "MOTHER",
    "contact_email": "mai@example.org",
    "is_primary": True,
}
PRIMARY_THIRD = {
    "full_name": "Tan Nguyen",
    "relationship": "FATHER",
    "contact_email": "tan@example.org",
    "is_primary": True,
}


def test_selector_targets_the_earliest_created_primary_guardian(api):
    """PRD §3.2: "Whenever any event in this system raises a parent notification,
    the server takes every guardian row belonging to the event's student as the
    candidate set (there is no status filter on guardians, so every row of that
    student is a candidate), ranks them with `is_primary` true before `is_primary`
    false and, within a group, earlier `created_at` first, breaks any remaining tie
    by `created_at` ascending and never by identifier, and selects the first row."
    PRD §3.2: "Otherwise it is created against them in `QUEUED` with a null
    `suppression_reason` and a `delivery_attempt_count` of 0."

    Design: Corner/calculations/notification_target_selector_ranks_primary_first_then_created_at
    """
    ctx = setup_visit_in_progress(
        setup_enrolled_student(guardians=[NON_PRIMARY_FIRST, PRIMARY_SECOND, PRIMARY_THIRD])
    )
    non_primary, first_primary, second_primary = ctx["guardians"]

    complete_visit(ctx["visit"]["id"], ctx["clinician"]["id"])

    rows, meta = validate_paginated(
        api.list_notifications(ADMIN, params={"visit_id": ctx["visit"]["id"]})
    )
    assert meta["total_count"] == 1, f"Completion raises exactly one notification, got {meta['total_count']}"
    notification = rows[0]

    assert_notification(notification)
    assert notification["event_type"] == "VISIT_COMPLETED"
    assert notification["status"] == "QUEUED"
    assert notification["guardian_id"] == first_primary["id"], (
        "The selector ranks is_primary true first, then earliest created_at"
    )
    assert notification["guardian_id"] != non_primary["id"]
    assert notification["guardian_id"] != second_primary["id"]
    assert notification["suppression_reason"] is None
    assert notification["delivery_attempt_count"] == 0


def test_self_consented_encounter_suppresses_what_guardian_consent_delivers(api):
    """PRD §3.5: "it computes `confidential`, which is true exactly when that
    governing consent was granted by the student themself and false otherwise."
    PRD §3.11: "an encounter governed by a consent the student granted themself is
    `confidential`, and every notification that encounter would otherwise raise is
    created directly in `SUPPRESSED_CONFIDENTIAL` with a `suppression_reason` of
    `CONFIDENTIAL_SERVICE` — the record exists for audit but is never delivered and
    can never be delivered. The identical event on a guardian-consented encounter
    produces a `QUEUED` notification that will be delivered normally."

    Design: Corner/cross_cutting_complexity_layers/self_consented_behavioral_visit_suppresses_the_notification_guardian_consent_does_not
    """
    guardian_consented = setup_enrolled_student(
        discipline="BEHAVIORAL",
        first_name="Ava",
        last_name="Nguyen",
        dob="2010-04-15",
        consents=("BEHAVIORAL_HEALTH",),
    )
    self_consented = setup_enrolled_student(
        discipline="BEHAVIORAL",
        first_name="Ben",
        last_name="Ortiz",
        dob="2010-04-16",
        guardians=[
            {
                "full_name": "Rosa Ortiz",
                "relationship": "MOTHER",
                "contact_email": "rosa@example.org",
                "is_primary": True,
            }
        ],
        consents=(),
        self_consent_categories=("BEHAVIORAL_HEALTH",),
    )

    visit_a = schedule_visit(
        guardian_consented["student"]["id"],
        guardian_consented["school"]["id"],
        guardian_consented["clinician"]["id"],
        visit_type="BEHAVIORAL",
        scheduled_start_at="2026-05-04T10:00:00Z",
    )
    start_visit(visit_a["id"], guardian_consented["clinician"]["id"])
    completed_a = complete_visit(visit_a["id"], guardian_consented["clinician"]["id"])

    visit_b = schedule_visit(
        self_consented["student"]["id"],
        self_consented["school"]["id"],
        self_consented["clinician"]["id"],
        visit_type="BEHAVIORAL",
        scheduled_start_at="2026-05-04T11:00:00Z",
    )
    start_visit(visit_b["id"], self_consented["clinician"]["id"])
    completed_b = complete_visit(visit_b["id"], self_consented["clinician"]["id"])

    assert completed_a["confidential"] is False
    assert completed_a["consent_id"] == guardian_consented["consents"]["BEHAVIORAL_HEALTH"]["id"]
    assert completed_b["confidential"] is True
    assert completed_b["consent_id"] == self_consented["consents"]["BEHAVIORAL_HEALTH"]["id"]

    open_notice = notifications_for_visit(visit_a["id"])
    suppressed = notifications_for_visit(visit_b["id"])
    assert len(open_notice) == 1
    assert len(suppressed) == 1, f"Expected one notification on the confidential encounter, got {len(suppressed)}"

    assert open_notice[0]["status"] == "QUEUED"
    assert open_notice[0]["guardian_id"] == guardian_consented["guardian"]["id"]
    assert open_notice[0]["suppression_reason"] is None
    assert suppressed[0]["status"] == "SUPPRESSED_CONFIDENTIAL"
    assert suppressed[0]["suppression_reason"] == "CONFIDENTIAL_SERVICE"

    assert completed_a["gross_charge_total_cents"] == 15_000
    assert completed_b["gross_charge_total_cents"] == 15_000


def test_opted_out_guardian_yields_a_suppressed_opt_out_notification(api):
    """PRD §3.2: "Otherwise, if the selected guardian has opted out, it is created
    against them with status `SUPPRESSED_OPT_OUT` and a `suppression_reason` of
    `GUARDIAN_OPT_OUT`."
    PRD §3.11: "Four of the seven notification states are terminal: `ACKNOWLEDGED`,
    `UNDELIVERABLE`, `SUPPRESSED_CONFIDENTIAL` and `SUPPRESSED_OPT_OUT`."

    Design: Corner/cross_cutting_complexity_layers/opted_out_guardian_yields_suppressed_opt_out_notification
    """
    ctx = setup_enrolled_student()
    opted_out = set_guardian_opt_out(ctx["guardian"]["id"], True)
    assert opted_out["notification_opt_out"] is True

    ctx = setup_visit_in_progress(ctx)
    complete_visit(ctx["visit"]["id"], ctx["clinician"]["id"])

    rows = notifications_for_visit(ctx["visit"]["id"])
    assert len(rows) == 1
    notification = rows[0]

    assert notification["status"] == "SUPPRESSED_OPT_OUT"
    assert notification["suppression_reason"] == "GUARDIAN_OPT_OUT"
    assert notification["guardian_id"] == ctx["guardian"]["id"]
    assert notification["delivery_attempt_count"] == 0

    resp = api.deliver_notification(notification["id"], {"outcome": "DELIVERED"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_three_failed_deliveries_exhaust_the_notification_and_the_fourth_is_capped(api):
    """PRD §3.11: "From `FAILED`, a further `FAILED` while the counter is still
    strictly below 2 keeps it looping `FAILED → FAILED` with the counter
    incremented; the `FAILED` logged when the counter stands at exactly 2 is the
    third attempt, takes the counter to 3, moves the row `FAILED → UNDELIVERABLE`
    and leaves `suppression_reason` null — an exhausted notification is not a
    suppressed one."
    PRD §3.11: "Once the counter has reached 3, any further attempt is refused with
    `ERR_DELIVERY_ATTEMPTS_EXHAUSTED` — including on a row already sitting in
    `UNDELIVERABLE`, where §2.6 puts the cap check above the state check precisely
    so that this error remains observable."

    Design: Corner/state_machines/notification_delivery_retry_capped_then_further_attempt_rejected
    """
    ctx = setup_queued_visit_notification()
    notification = ctx["notification"]
    assert notification["status"] == "QUEUED"
    assert notification["guardian_id"] == ctx["guardian"]["id"]
    assert notification["delivery_attempt_count"] == 0

    for _ in range(3):
        deliver_notification(notification["id"], "FAILED")

    exhausted = get_notification(notification["id"])
    assert exhausted["status"] == "UNDELIVERABLE"
    assert exhausted["delivery_attempt_count"] == 3
    assert exhausted["sent_at"] is None
    assert exhausted["suppression_reason"] is None

    resp = api.deliver_notification(notification["id"], {"outcome": "FAILED"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_ATTEMPTS_EXHAUSTED.value, 409)


def test_guardian_cannot_acknowledge_another_guardians_notification(api):
    """PRD §3.11: "Acknowledgement belongs to the guardian and to nobody else. It is
    accepted only from `SENT`; the acting `X-User-ID` must equal the notification's
    `guardian_id`, otherwise `ERR_OWNERSHIP_VIOLATION`"

    Design: Corner/rbac/guardian_cannot_acknowledge_another_guardians_notification
    """
    ctx = setup_sent_visit_notification(guardians=[NON_PRIMARY_FIRST, PRIMARY_SECOND])
    non_primary, primary = ctx["guardians"]
    notification = ctx["notification"]
    assert notification["guardian_id"] == primary["id"]

    resp = api.acknowledge_notification(
        notification["id"], make_guardian_headers(non_primary["id"])
    )

    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value, 403)

    reread = get_notification(notification["id"])
    assert reread["status"] == "SENT"
    assert reread["acknowledged_at"] is None


def test_acknowledgement_one_second_past_the_window_is_refused(api):
    """PRD §3.11: "and it must happen while the current logical instant is at or
    before `sent_at` advanced by 14 days — the boundary is inclusive, so an
    acknowledgement at exactly 14 days lands, and one at 14 days and a minute is
    refused with `ERR_ACK_WINDOW_EXPIRED`."

    Design: Corner/errors/error_ack_window_expired_after_fifteen_days
    """
    ctx = setup_sent_visit_notification()
    notification = ctx["notification"]
    assert_same_instant(
        notification["sent_at"], "2026-05-04T09:00:00.000Z", "ParentNotification.sent_at"
    )

    set_clock("2026-05-18T09:00:01Z")
    resp = api.acknowledge_notification(
        notification["id"], make_guardian_headers(ctx["guardian"]["id"])
    )

    validate_error(resp, ApiErrorId.ERR_ACK_WINDOW_EXPIRED.value, 409)

    reread = get_notification(notification["id"])
    assert reread["status"] == "SENT"
    assert reread["acknowledged_at"] is None
