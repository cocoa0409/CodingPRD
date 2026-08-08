"""Spray notices: issuing, delivery retries, the acknowledgement window, and the
notice discipline that scheduling enforces."""

import test_helpers as fx
from test_helpers import (
    ADMIN,
    MANAGER,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_acknowledgement_boundary_belongs_to_the_operator_not_the_district(api):
    """PRD §3.8: "Acknowledgement is permitted while the logical clock is at or
    before `sent_at` plus 24 hours, inclusive at the boundary, so an
    acknowledgement landing at exactly 24 hours still succeeds; later than that it
    is refused with `ERR_ACK_WINDOW_EXPIRED` (HTTP 422)."
    PRD §3.8: "At exactly 24 hours the operator may still acknowledge, so expiring
    at that instant is refused with `ERR_ACK_WINDOW_OPEN` (HTTP 409)."

    Design: Corner/state_machines/corner_notification_ack_window_boundary_and_expire_gate
    """
    bundle = fx.setup_plan_scenario(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        sensitive_sites=[
            {"site_type": "APIARY", "x_m": 960, "y_m": 1280},
            {"site_type": "ORGANIC_FARM", "operator_name": "Green Row Farm",
             "contact_email": "farm@example.com", "x_m": 700, "y_m": 0},
        ],
        routes=[{"center_x_m": 0, "center_y_m": 0}],
    )
    apiary, farm = bundle["sites"]
    bee_notice = fx.issue_notification(bundle["plan"]["id"], apiary["id"], channel="EMAIL")
    farm_notice = fx.issue_notification(bundle["plan"]["id"], farm["id"], channel="EMAIL")
    fx.notification_action(bee_notice["id"], "SEND")
    fx.notification_action(farm_notice["id"], "SEND")

    fx.set_clock("2026-06-02T00:00:00.000Z")
    premature_expiry = api.transition_notification(
        bee_notice["id"], {"action": "EXPIRE"}, ADMIN
    )
    validate_error(premature_expiry, ApiErrorId.ERR_ACK_WINDOW_OPEN.value, 409)

    acknowledged = validate_success(
        api.transition_notification(
            bee_notice["id"], {"action": "ACKNOWLEDGE"},
            fx.make_site_operator_headers(apiary["id"]),
        )
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_at"] == "2026-06-02T00:00:00.000Z"
    assert acknowledged["sent_at"] == "2026-06-01T00:00:00.000Z"
    assert acknowledged["attempt_count"] == 1

    fx.set_clock("2026-06-02T00:01:00.000Z")
    late_ack = api.transition_notification(
        farm_notice["id"], {"action": "ACKNOWLEDGE"},
        fx.make_site_operator_headers(farm["id"]),
    )
    validate_error(late_ack, ApiErrorId.ERR_ACK_WINDOW_EXPIRED.value, 422)

    expired = validate_success(
        api.transition_notification(farm_notice["id"], {"action": "EXPIRE"}, ADMIN)
    )
    assert expired["status"] == "EXPIRED"


def test_delivery_retries_exhaust_after_three_attempts(api):
    """PRD §3.8: "Sending advances `QUEUED → SENT`, requires the parent plan to be
    `APPROVED` or `SCHEDULED`, increases `attempt_count` by 1, and stamps `sent_at`
    with the logical clock."
    PRD §3.8: "The district allows at most 3 delivery attempts in total: sending or
    requeueing while `attempt_count` has already reached 3 is refused with
    `ERR_NOTIFICATION_ATTEMPTS_EXHAUSTED` (HTTP 409)."
    PRD §3.8: "From `FAILED` the admin either requeues, advancing `FAILED →
    QUEUED` so a further send may be attempted, or gives up, advancing `FAILED →
    UNDELIVERABLE`, which is terminal."

    Design: Corner/state_machines/corner_notification_retry_cycle_exhausts_after_three_attempts
    """
    bundle = fx.setup_plan_scenario(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        sensitive_sites=[{"site_type": "APIARY", "x_m": 960, "y_m": 1280}],
        routes=[{"center_x_m": 0, "center_y_m": 0}],
    )
    notice = fx.issue_notification(
        bundle["plan"]["id"], bundle["site"]["id"], channel="PHONE"
    )

    fx.notification_action(notice["id"], "SEND")
    fx.notification_action(notice["id"], "FAIL", failure_reason="Number unreachable")
    fx.notification_action(notice["id"], "REQUEUE")
    fx.notification_action(notice["id"], "SEND")
    fx.notification_action(notice["id"], "FAIL", failure_reason="Voicemail full")
    fx.notification_action(notice["id"], "REQUEUE")
    third_send = fx.notification_action(notice["id"], "SEND")
    assert third_send["attempt_count"] == 3
    fx.notification_action(notice["id"], "FAIL", failure_reason="Line disconnected")

    exhausted = api.transition_notification(notice["id"], {"action": "REQUEUE"}, ADMIN)
    validate_error(
        exhausted, ApiErrorId.ERR_NOTIFICATION_ATTEMPTS_EXHAUSTED.value, 409
    )

    abandoned = validate_success(
        api.transition_notification(notice["id"], {"action": "ABANDON"}, ADMIN)
    )
    assert abandoned["status"] == "UNDELIVERABLE"
    assert abandoned["attempt_count"] == 3
    assert abandoned["failure_reason"] == "Line disconnected"


def test_notice_cannot_be_issued_against_a_draft_plan(api):
    """PRD §3.8: "A notice may only be issued while the plan is `APPROVED` or
    `SCHEDULED`; issuing one against a plan in any other state is refused with
    `ERR_INVALID_TRANSITION`."

    Design: Corner/endpoints/corner_notification_creation_on_draft_plan_rejected
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    apiary = fx.create_sensitive_site(area["id"], site_type="APIARY", x_m=960, y_m=1280)
    assessment = fx.open_assessment(area["id"], "2026-06-01")
    plan = fx.create_plan(area["id"], assessment["id"], "LARVICIDE")

    response = api.create_notification(
        plan["id"], {"sensitive_site_id": apiary["id"], "channel": "EMAIL"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_TRANSITION.value, 409)

    assert fx.read_plan(plan["id"])["status"] == "DRAFT"
    _, meta = validate_paginated(
        api.list_notifications(ADMIN, params={"treatment_plan_id": plan["id"]})
    )
    assert meta["total_count"] == 0


def test_unknown_protected_site_in_notice_body_returns_not_found(api):
    """PRD §2.5: "A body reference that does not resolve produces the 404 code for
    that reference's entity, so an unresolvable `sensitive_site_id` yields
    `ERR_SENSITIVE_SITE_NOT_FOUND` and an unresolvable `trigger_assessment_id`
    yields `ERR_RISK_ASSESSMENT_NOT_FOUND`."

    Design: Corner/errors/corner_unknown_sensitive_site_in_notification_body_returns_not_found
    """
    bundle = fx.setup_plan_scenario(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        product_overrides={"received_total_ml": 1000.0},
    )

    response = api.create_notification(
        bundle["plan"]["id"],
        {"sensitive_site_id": "00000000-0000-4000-8000-0000000000cc", "channel": "EMAIL"},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_SENSITIVE_SITE_NOT_FOUND.value, 404)


def test_schedule_blocked_while_a_notice_is_still_queued(api):
    """PRD §3.8: "Second, every notice of the plan must be in `ACKNOWLEDGED` or
    `EXPIRED`; a notice still `QUEUED`, still `SENT`, sitting in `FAILED`, or
    written off as `UNDELIVERABLE` is refused with `ERR_NOTIFICATION_INCOMPLETE`
    (HTTP 409)."
    PRD §3.8: "A `DistrictAdmin` issues a **spray notice** against a plan, naming
    the `sensitive_site_id` being notified and optionally the `channel` of record —
    `EMAIL`, `SMS`, or `PHONE`, defaulting to `EMAIL`."

    Design: Corner/validations/corner_plan_schedule_with_queued_notification_rejected
    """
    bundle = fx.setup_committed_route(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        sensitive_sites=[{"site_type": "APIARY", "x_m": 960, "y_m": 1280}],
        routes=[{"center_x_m": 0, "center_y_m": 0}],
    )
    notice = fx.issue_notification(bundle["plan"]["id"], bundle["site"]["id"])

    blocked = api.transition_treatment_plan(
        bundle["plan"]["id"],
        {"action": "SCHEDULE", "scheduled_start_at": "2026-06-05T09:00:00.000Z"},
        MANAGER,
    )
    validate_error(blocked, ApiErrorId.ERR_NOTIFICATION_INCOMPLETE.value, 409)

    fx.notification_action(notice["id"], "SEND")
    fx.notification_action(
        notice["id"], "ACKNOWLEDGE", fx.make_site_operator_headers(bundle["site"]["id"])
    )
    scheduled = validate_success(
        api.transition_treatment_plan(
            bundle["plan"]["id"],
            {"action": "SCHEDULE", "scheduled_start_at": "2026-06-05T09:00:00.000Z"},
            MANAGER,
        )
    )

    assert scheduled["status"] == "SCHEDULED"
    refreshed_notice = fx.read_notification(notice["id"])
    assert refreshed_notice["status"] == "ACKNOWLEDGED"
    assert refreshed_notice["channel"] == "EMAIL"


def test_aerial_schedule_forty_seven_hours_ahead_is_refused(api):
    """PRD §3.8: "Fourth, the lead time must be sufficient: the interval from the
    logical clock to `scheduled_start_at` must be at least 48 hours for an `AERIAL`
    plan and at least 24 hours for a `LARVICIDE` or `ADULTICIDE` plan, inclusive at
    the boundary so exactly the required lead passes; a shorter lead is refused
    with `ERR_NOTIFICATION_LEAD_TIME` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/aerial_schedule_lead_time_exactly_forty_eight_hours_is_allowed
    """
    bundle = fx.setup_aerial_plan_awaiting_schedule()

    response = api.transition_treatment_plan(
        bundle["plan"]["id"],
        {"action": "SCHEDULE", "scheduled_start_at": "2026-06-02T23:00:00.000Z"},
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_NOTIFICATION_LEAD_TIME.value, 422)

    plan = fx.read_plan(bundle["plan"]["id"])
    assert plan["status"] == "APPROVED"
    assert plan["scheduled_start_at"] is None


def test_aerial_schedule_at_exactly_forty_eight_hours_is_accepted(api):
    """PRD §3.8: "Fourth, the lead time must be sufficient: the interval from the
    logical clock to `scheduled_start_at` must be at least 48 hours for an `AERIAL`
    plan and at least 24 hours for a `LARVICIDE` or `ADULTICIDE` plan, inclusive at
    the boundary so exactly the required lead passes; a shorter lead is refused
    with `ERR_NOTIFICATION_LEAD_TIME` (HTTP 422)."
    PRD §3.8: "On success `scheduled_start_at` is stored."

    Design: Difficulty/boundary_precision_check/aerial_schedule_lead_time_exactly_forty_eight_hours_is_allowed
    """
    bundle = fx.setup_aerial_plan_awaiting_schedule()

    scheduled = validate_success(
        api.transition_treatment_plan(
            bundle["plan"]["id"],
            {"action": "SCHEDULE", "scheduled_start_at": "2026-06-03T00:00:00.000Z"},
            MANAGER,
        )
    )

    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["scheduled_start_at"] == "2026-06-03T00:00:00.000Z"
    assert scheduled["required_approvals"] == 2
    assert fx.read_notification(bundle["notification"]["id"])["status"] == "ACKNOWLEDGED"
    fx.assert_index(
        fx.read_route(bundle["route"]["id"])["estimated_volume_ml"], 2000.00,
        "estimated_volume_ml",
    )
