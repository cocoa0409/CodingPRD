"""Employee notification lifecycle and assessment retention/archival
(PRD §2.5, §3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    make_employee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["firm_admin_headers"]
IH = TEST_USERS["ih_headers"]
SSM = TEST_USERS["ssm_headers"]


def _notification_for(api, assessment_id, employee_id):
    rows, meta = validate_paginated(
        api.list_notifications(
            IH,
            params={
                "employee_id": employee_id,
                "exposure_assessment_id": assessment_id,
            },
        )
    )
    assert meta["total_count"] == 1
    return rows[0]


def test_notification_fanout_one_pending_per_member(api):
    """PRD §3.9: "The moment an assessment is signed, every current member of
    the group receives a notification: one `PENDING` record per membership,
    each naming the `employee_id` and the `exposure_assessment_id`, with
    `sent_at`, `sent_by_user_id`, and `acknowledged_at` all null."
    PRD §3.9: "An assessment signed on Monday 2026-08-10 therefore produces
    notifications due Monday 2026-08-31."

    Design: Difficulty/boundary_precision_check/notification_overdue_strictly_after_due_date
    """
    ctx = fx.setup_signed_assessment(masses=(12, 10, 8), member_count=3)
    assessment = ctx.assessment

    rows, meta = validate_paginated(
        api.list_notifications(
            IH, params={"exposure_assessment_id": assessment["id"]}
        )
    )
    assert meta["total_count"] == 3, "one notification per current member"
    member_ids = {e["id"] for e in ctx.employees}
    assert {n["employee_id"] for n in rows} == member_ids
    for note in rows:
        assert note["status"] == "PENDING"
        assert note["due_date"] == "2026-08-31"
        assert note["exposure_assessment_id"] == assessment["id"]
        assert note["sent_at"] is None
        assert note["sent_by_user_id"] is None
        assert note["acknowledged_at"] is None


def test_notification_overdue_strictly_after_due_date(api):
    """PRD §3.9: "The clock sweep of §2.5 moves a `PENDING` notification to
    `OVERDUE` once the current date is strictly later than its `due_date` — on
    the due date itself it remains `PENDING`".
    PRD §2.5: "every notification in `PENDING` status whose `due_date` is
    before the new current date transitions to `OVERDUE`."
    PRD §2.5: "On an expiry date or due date itself, nothing transitions —
    the date must be strictly in the past."

    Design: Difficulty/boundary_precision_check/notification_overdue_strictly_after_due_date
    """
    ctx = fx.setup_signed_assessment(masses=(12, 10, 8), member_count=3)
    note = _notification_for(api, ctx.assessment["id"], ctx.employees[0]["id"])
    assert note["due_date"] == "2026-08-31"

    fx.set_clock("2026-08-31T00:00:00Z")  # the due date itself
    assert fx.get_notification(note["id"])["status"] == "PENDING"

    fx.set_clock("2026-09-01T00:00:00Z")  # strictly past it
    assert fx.get_notification(note["id"])["status"] == "OVERDUE"


def test_notification_send_ack_sequence(api):
    """PRD §3.9: "Sending is shared between the `IndustrialHygienist` and the
    `SiteSafetyManager`: a notification in `PENDING` or `OVERDUE` moves to
    `SENT`, stamping `sent_at` and `sent_by_user_id` and incrementing the
    notification's `version`; sending from any other status is rejected with
    `ERR_NOTIFICATION_INVALID_STATE` (409)."
    PRD §3.9: "Acknowledgment belongs to the worker alone: an `Employee`
    acknowledges a `SENT` notification, moving it to its terminal
    `ACKNOWLEDGED` status, stamping `acknowledged_at`, and incrementing its
    `version`, but only when the caller's `X-User-ID` equals the
    notification's `employee_id`; anyone else's attempt is rejected with
    `ERR_ACK_FORBIDDEN` (403), and acknowledging from any status other than
    `SENT` is `ERR_NOTIFICATION_INVALID_STATE`."

    Design: Corner/state_machines/notification_send_ack_sequence
    """
    ctx = fx.setup_signed_assessment(masses=(12, 10, 8), member_count=3)
    e1, e2 = ctx.employees[0], ctx.employees[1]
    note = _notification_for(api, ctx.assessment["id"], e1["id"])

    sent = validate_success(api.send_notification(note["id"], SSM), 200)
    assert sent["status"] == "SENT"
    assert sent["sent_by_user_id"] == "u_ssm_1"
    assert_instant_equals(sent["sent_at"], "2026-08-10T00:00:00Z")
    assert sent["version"] == note["version"] + 1

    res = api.send_notification(note["id"], SSM)
    validate_error(res, ApiErrorId.ERR_NOTIFICATION_INVALID_STATE, 409)

    # Acknowledgment by a different employee id is forbidden.
    res = api.acknowledge_notification(note["id"], make_employee_headers(e2["id"]))
    validate_error(res, ApiErrorId.ERR_ACK_FORBIDDEN, 403)

    acked = validate_success(
        api.acknowledge_notification(note["id"], make_employee_headers(e1["id"])),
        200,
    )
    assert acked["status"] == "ACKNOWLEDGED"
    assert acked["acknowledged_at"] is not None
    assert acked["version"] == sent["version"] + 1


def test_archive_retention_and_legal_hold(api):
    """PRD §3.9: "A `CIHDirector` may toggle an assessment's `legal_hold` flag
    (default false) through the assessment update operation, which increments
    the assessment's `version`; a hold blocks archival. A `FirmAdmin` archives
    an assessment from `SIGNED` or `SUPERSEDED` — any other `review_status` is
    rejected with `ERR_ASSESSMENT_INVALID_STATE` — provided the current
    logical date is on or after `retention_until` (earlier attempts are
    rejected with `ERR_RETENTION_NOT_MET`, 409) and `legal_hold` is false (a
    live hold is rejected with `ERR_LEGAL_HOLD_ACTIVE`, 409). Archival moves
    the assessment to `ARCHIVED`, clears `is_current`, increments its
    `version`, and excludes it from the assessment list unless the caller
    passes `include_archived` as true; an archived assessment remains
    retrievable directly by its identifier."
    PRD §3.9: "an assessment signed 2026-08-10 under a thirty-year retention
    may be archived on 2056-08-10 itself, the gate being inclusive."
    PRD §2.8: "Eighth, segregation-of-duties and safety gates (§2.9). Ninth,
    temporal windows: the plan collection window, the batch intake window, and
    the retention gate."

    With a live hold the safety gate is the earlier pipeline stage, so it is
    reported even though retention is also unmet.

    Design: Corner/cross_cutting_complexity_layers/archive_retention_and_legal_hold
    """
    ctx = fx.setup_signed_assessment(masses=(12, 10, 8), member_count=1)
    asm = ctx.assessment
    assert asm["retention_until"] == "2056-08-10"
    assert asm["legal_hold"] is False

    held = fx.set_legal_hold(asm["id"], True)
    assert held["legal_hold"] is True
    res = api.archive_assessment(asm["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_LEGAL_HOLD_ACTIVE, 409)

    released = fx.set_legal_hold(asm["id"], False)
    assert released["version"] == held["version"] + 1

    # Retention is unmet at the 2026-08-10 signature date.
    res = api.archive_assessment(asm["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_RETENTION_NOT_MET, 409)

    # One day before the retention date the gate is still closed.
    fx.set_clock("2056-08-09T00:00:00Z")
    res = api.archive_assessment(asm["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_RETENTION_NOT_MET, 409)

    # On retention_until itself the gate opens (inclusive).
    fx.set_clock("2056-08-10T00:00:00Z")
    archived = validate_success(api.archive_assessment(asm["id"], ADMIN), 200)
    assert archived["review_status"] == "ARCHIVED"
    assert archived["is_current"] is False

    rows, meta = validate_paginated(
        api.list_exposure_assessments(ADMIN, params={"seg_id": ctx.seg["id"]})
    )
    assert meta["total_count"] == 0, "archived rows leave the default list"

    rows, meta = validate_paginated(
        api.list_exposure_assessments(
            ADMIN, params={"seg_id": ctx.seg["id"], "include_archived": True}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == asm["id"]

    direct = validate_success(api.get_exposure_assessment(asm["id"], ADMIN), 200)
    assert direct["review_status"] == "ARCHIVED"
