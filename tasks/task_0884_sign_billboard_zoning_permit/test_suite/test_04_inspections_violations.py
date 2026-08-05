"""Inspection scheduling/recording and the violation cure/escalation cascade."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_planner_headers, make_inspector_headers,
    create_parcel, create_inspector, create_issued_permit,
    create_permit_with_scheduled_inspection, schedule_inspection, revoke_permit,
    cite_violation, setup_escalatable_permit_violation,
)


# ── Inspection requires an ACTIVE permit (Difficulty) ────────────────────────
def test_schedule_inspection_on_issued_permit_rejected(api):
    """PRD §3.5: "The permit must be `ACTIVE`, else `ERR_PERMIT_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/inspection_requires_permit_active
    """
    parcel, applicant, app, permit = create_issued_permit(api)
    inspector = create_inspector(api)
    resp = api.create_inspection(
        {"permit_id": permit["id"], "inspector_id": inspector["id"],
         "scheduled_start": "2026-06-01T10:00:00Z", "scheduled_end": "2026-06-01T11:00:00Z"},
        make_planner_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_INACTIVE)


def test_schedule_inspection_on_revoked_permit_rejected(api):
    """PRD §3.5: "The permit must be `ACTIVE`, else `ERR_PERMIT_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/inspection_requires_permit_active
    """
    parcel, applicant, app, permit = create_issued_permit(api)
    revoked = revoke_permit(api, permit["id"])
    assert revoked["status"] == "REVOKED"
    inspector = create_inspector(api)
    resp = api.create_inspection(
        {"permit_id": permit["id"], "inspector_id": inspector["id"],
         "scheduled_start": "2026-06-01T10:00:00Z", "scheduled_end": "2026-06-01T11:00:00Z"},
        make_planner_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_INACTIVE)


# ── Inspector buffered scheduling conflict (Difficulty) ──────────────────────
def test_second_inspection_within_buffer_rejected(api):
    """PRD §3.5: "Scheduling is protected against inspector double-booking: a new window
    may not fall within 60 minutes of another `SCHEDULED` inspection for the same
    inspector — the buffer applies on both sides of the existing window — else
    `ERR_INSPECTION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/inspection_buffer_conflict_rejected
    """
    (parcel, applicant, app, permit, inspector,
     inspection_a) = create_permit_with_scheduled_inspection(api)
    resp = api.create_inspection(
        {"permit_id": permit["id"], "inspector_id": inspector["id"],
         "scheduled_start": "2026-06-01T11:30:00Z", "scheduled_end": "2026-06-01T12:30:00Z"},
        make_planner_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INSPECTION_OVERLAP)


def test_second_inspection_outside_buffer_allowed(api):
    """PRD §3.5: "Scheduling is protected against inspector double-booking: a new window
    may not fall within 60 minutes of another `SCHEDULED` inspection for the same
    inspector — the buffer applies on both sides of the existing window — else
    `ERR_INSPECTION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/inspection_buffer_conflict_rejected
    """
    (parcel, applicant, app, permit, inspector,
     inspection_a) = create_permit_with_scheduled_inspection(api)
    # 13:00 is 120 minutes after the first window's 11:00 end — well outside the buffer.
    second = schedule_inspection(api, permit["id"], inspector["id"],
                                 "2026-06-01T13:00:00Z", "2026-06-01T14:00:00Z")
    assert second["status"] == "SCHEDULED"


# ── Depth-3 escalation cascade (Difficulty) ──────────────────────────────────
def test_escalation_escalates_violation_and_revokes_permit(api):
    """PRD §3.7: "Escalation advances the violation `OPEN → ESCALATED` and triggers a
    three-part cascade: first, a `RemovalOrder` is created in its sole `ISSUED` state,
    with `issued_at` equal to the escalation instant and a `compliance_deadline` set to
    that instant plus the removal-compliance period of 15 days, linked back through
    `violation_id`; second, if the violation carries a `permit_id`, that permit is driven
    to `REVOKED` (with the revocation's own refund and slot-release effects); and third,
    that revoked permit's `SCHEDULED` inspections are moved to `CANCELLED`."

    Design: Difficulty/transitive_cascade/escalation_removal_revoke_cancel_depth3
    """
    (parcel, applicant, permit, inspector, inspection,
     violation) = setup_escalatable_permit_violation(api)
    escalated = validate_success(api.escalate_violation(violation["id"], make_planner_headers()))
    assert escalated["status"] == "ESCALATED"
    fetched_permit = validate_success(api.get_permit(permit["id"], make_planner_headers()))
    assert fetched_permit["status"] == "REVOKED"


def test_escalation_cancels_inspection_and_issues_removal_order(api):
    """PRD §3.7: "second, if the violation carries a `permit_id`, that permit is driven
    to `REVOKED` (with the revocation's own refund and slot-release effects); and third,
    that revoked permit's `SCHEDULED` inspections are moved to `CANCELLED`."

    Design: Difficulty/transitive_cascade/escalation_removal_revoke_cancel_depth3
    """
    (parcel, applicant, permit, inspector, inspection,
     violation) = setup_escalatable_permit_violation(api)
    api.escalate_violation(violation["id"], make_planner_headers())
    fetched_inspection = validate_success(
        api.get_inspection(inspection["id"], make_planner_headers()))
    assert fetched_inspection["status"] == "CANCELLED"
    orders = validate_success(
        api.list_removal_orders(make_planner_headers(), params={"violation_id": violation["id"]}))
    assert len(orders) == 1
    assert orders[0]["status"] == "ISSUED"


# ── Inspection recording ownership (Corner) ──────────────────────────────────
def test_record_inspection_by_wrong_inspector_rejected(api):
    """PRD §3.5: "Recording is permitted only when the inspection's `inspector_id` equals
    the caller's `X-User-ID`."
    PRD §2.1: "an ownership-scoped role acts on a resource it does not own — the request
    is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/state_machines/record_inspection_wrong_inspector_rejected
    """
    (parcel, applicant, app, permit, inspector_a,
     inspection) = create_permit_with_scheduled_inspection(api)
    inspector_b = create_inspector(api, name="Inspector B")
    resp = api.record_inspection(
        inspection["id"], {"outcome": "PASS"}, make_inspector_headers(inspector_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ── Violation cure / escalate temporal gates (Corner) ────────────────────────
def test_cure_open_violation_before_deadline_succeeds(api):
    """PRD §3.7: "A planner may mark it `CURED`, which is legal only on or before the
    `cure_deadline` — a cure attempt after the deadline is not permitted."

    Design: Corner/state_machines/cure_violation_before_deadline_succeeds
    """
    parcel = create_parcel(api)
    violation = cite_violation(api, parcel["id"], kind="NO_PERMIT")
    cured = validate_success(api.cure_violation(violation["id"], make_planner_headers()))
    assert cured["status"] == "CURED"


def test_escalate_before_cure_deadline_rejected(api):
    """PRD §3.7: "escalation is legal only strictly after the `cure_deadline` has passed;
    escalating on or before the deadline is refused with `ERR_CURE_PERIOD_ACTIVE`."

    Design: Corner/state_machines/escalate_before_cure_deadline_rejected
    """
    parcel = create_parcel(api)
    violation = cite_violation(api, parcel["id"], kind="ABANDONED")
    resp = api.escalate_violation(violation["id"], make_planner_headers())
    validate_error(resp, ApiErrorId.ERR_CURE_PERIOD_ACTIVE)
