"""Delivery gating, acknowledgment evidence and the compensating retention ledger."""
from test_helpers import (
    ApiErrorId,
    acknowledge,
    api_client,
    assert_same_instant,
    make_admin_headers,
    patch_employee,
    refresh_assignment,
    refresh_employee,
    refresh_package,
    set_clock,
    setup_released_scenario,
    validate_error,
    validate_success,
)


def test_delivery_is_refused_to_a_terminated_assignee_and_allowed_once_reinstated():
    """PRD §3.7: "Delivery is an `HRComplianceAdmin` action that moves the
    assignment `UNDELIVERED → PENDING` on the acknowledgment dimension and stamps
    `delivered_at` from the logical clock. It requires the assignment to be in
    `UNDELIVERED` ... the owning package to be in `RELEASED`, the assignee's
    `employment_status` to be `ACTIVE` or `ON_LEAVE` (a `TERMINATED` assignee is
    refused with `ERR_EMPLOYEE_NOT_EMPLOYED`, 409)".

    Design: Difficulty/cross_entity_state_dependency/delivery_gated_on_assignee_employment_state
    """
    ctx = setup_released_scenario(
        document={"max_ack_deadline_days": 5}, deliver=False, extra_employees=1
    )
    assignment, employee = ctx["assignment"], ctx["employee"]
    assert assignment["ack_state"] == "UNDELIVERED"
    assert refresh_package(ctx["package"]["id"])["status"] == "RELEASED"

    patch_employee(employee["id"], employment_status="TERMINATED")
    validate_error(
        api_client.deliver_assignment(assignment["id"], make_admin_headers()),
        ApiErrorId.ERR_EMPLOYEE_NOT_EMPLOYED,
    )
    blocked = refresh_assignment(assignment["id"])
    assert blocked["ack_state"] == "UNDELIVERED", (
        f"a refused delivery must not move the assignment, got {blocked['ack_state']}"
    )
    assert blocked["delivered_at"] is None, (
        f"delivered_at must stay null, got {blocked['delivered_at']}"
    )

    patch_employee(employee["id"], employment_status="ACTIVE")
    delivered = validate_success(
        api_client.deliver_assignment(assignment["id"], make_admin_headers())
    )
    assert delivered["ack_state"] == "PENDING", (
        "the identical delivery must succeed once the assignee is employed again, got "
        f"{delivered['ack_state']}"
    )
    assert_same_instant(delivered["delivered_at"], "2026-08-15T00:00:00Z", "delivered_at")
    assert_same_instant(delivered["due_date"], "2026-08-20T00:00:00Z", "due_date")


def test_delivery_to_an_assignee_moved_on_leave_keeps_the_mint_time_deadline():
    """PRD §3.7: "the assignee's `employment_status` to be `ACTIVE` or `ON_LEAVE`"
    ... "Second, if the assignee's `employment_status` is `ON_LEAVE`, add 14 days
    — two extra weeks for someone who is away." ... "The inputs are the
    jurisdiction of the assignment, the document of the assignment's version, and
    the assignee's `employment_status` and `needs_accessible_format` as of the mint
    instant."

    Design: Difficulty/cross_entity_state_dependency/delivery_gated_on_assignee_employment_state
    """
    ctx = setup_released_scenario(document={"max_ack_deadline_days": 5}, deliver=False)
    assignment, employee = ctx["assignment"], ctx["employee"]
    assert_same_instant(assignment["due_date"], "2026-08-20T00:00:00Z", "due_date")

    patch_employee(employee["id"], employment_status="ON_LEAVE")
    delivered = validate_success(
        api_client.deliver_assignment(assignment["id"], make_admin_headers())
    )
    assert delivered["ack_state"] == "PENDING", (
        f"an ON_LEAVE assignee may be delivered to, got {delivered['ack_state']}"
    )
    assert_same_instant(delivered["due_date"], "2026-08-20T00:00:00Z", "due_date")
    assert delivered["days_overdue"] == 0


def _revoked_evidence():
    """One acknowledgment captured on 2026-08-15 and revoked on 2026-08-16, in a
    two-employee jurisdiction whose `retention_years` is 2 so the 1095-day dispute
    floor governs both horizons."""
    ctx = setup_released_scenario(
        jurisdiction={"retention_years": 2},
        document={"max_ack_deadline_days": 5},
        extra_employees=1,
    )
    ack = acknowledge(ctx["assignment"], ctx["employee"]["id"])
    assert_same_instant(ack["captured_at"], "2026-08-15T00:00:00Z", "captured_at")
    set_clock("2026-08-16T00:00:00Z")
    ctx["acknowledgment"] = validate_success(
        api_client.revoke_acknowledgment(
            ack["id"], {"reason": "Wrong rendition read."}, make_admin_headers()
        )
    )
    return ctx


def test_revocation_appends_an_offsetting_retention_row_and_zeroes_the_ledger():
    """PRD §3.7: "The row itself is **never deleted**: its `status` becomes
    `REVOKED` and `revoked_at` is stamped from the logical clock. A compensating
    retention row is appended with `record_kind` of `REVOCATION`, `signed_delta` of
    `-1`, the same `employee_id`, `jurisdiction_id` and `acknowledgment_id` as the
    capture row, and a `retention_until` recomputed by the same calculation at the
    revocation instant. The assignment moves `ACKNOWLEDGED → PENDING`,
    `acknowledged_at` is cleared to null, and the assignee's `open_ack_count` is
    incremented by 1."

    Design: Difficulty/compensating_invariant/revocation_appends_offsetting_retention_row_conserving_ack_ledger
    """
    from test_helpers import acknowledgments_for, retention_rows_for

    ctx = _revoked_evidence()
    revoked = ctx["acknowledgment"]
    assert revoked["status"] == "REVOKED", (
        f"the evidence row must be marked REVOKED, got {revoked['status']}"
    )
    assert_same_instant(revoked["revoked_at"], "2026-08-16T00:00:00Z", "revoked_at")
    assert revoked["signature_text"] == "Typed Full Name", (
        "the evidence row is never deleted or rewritten, so signature_text must "
        f"survive revocation, got {revoked['signature_text']}"
    )

    rows = retention_rows_for(ctx["employee"]["id"])
    assert len(rows) == 2, f"one capture plus one compensating row expected, got {len(rows)}"
    capture, revocation = rows[0], rows[1]
    assert capture["record_kind"] == "CAPTURE"
    assert capture["signed_delta"] == 1
    assert_same_instant(capture["retained_from"], "2026-08-15T00:00:00Z", "retained_from")
    assert_same_instant(
        capture["retention_until"], "2029-08-14T00:00:00.000Z", "retention_until"
    )
    assert revocation["record_kind"] == "REVOCATION"
    assert revocation["signed_delta"] == -1
    assert revocation["acknowledgment_id"] == revoked["id"]
    assert revocation["jurisdiction_id"] == capture["jurisdiction_id"]
    assert_same_instant(
        revocation["retained_from"], "2026-08-16T00:00:00Z", "retained_from"
    )
    assert_same_instant(
        revocation["retention_until"], "2029-08-15T00:00:00.000Z", "retention_until"
    )
    assert sum(row["signed_delta"] for row in rows) == 0, (
        "the signed ledger must net to zero once the only capture is compensated"
    )
    assert acknowledgments_for(ctx["employee"]["id"], "EFFECTIVE") == [], (
        "no EFFECTIVE acknowledgment remains, which the zero ledger sum must match"
    )

    assignment = refresh_assignment(ctx["assignment"]["id"])
    assert assignment["ack_state"] == "PENDING", (
        f"revocation returns the assignment to PENDING, got {assignment['ack_state']}"
    )
    assert assignment["acknowledged_at"] is None
    assert refresh_employee(ctx["employee"]["id"])["open_ack_count"] == 1, (
        "the obligation is open again, so open_ack_count must return to 1"
    )
    assert refresh_package(ctx["package"]["id"])["status"] == "RELEASED"


def test_re_acknowledging_after_a_revocation_leaves_three_append_only_ledger_rows():
    """PRD §2.10: "the signed retention ledger ... the sum of `signed_delta` over
    an employee's retention records equals the number of that employee's
    acknowledgment events whose `status` is `EFFECTIVE`".  PRD §3.7: "The row itself
    is **never deleted**".

    Design: Difficulty/compensating_invariant/revocation_appends_offsetting_retention_row_conserving_ack_ledger
    """
    from test_helpers import acknowledgments_for, retention_rows_for

    ctx = _revoked_evidence()
    employee_id = ctx["employee"]["id"]
    assert len(retention_rows_for(employee_id)) == 2

    again = acknowledge(refresh_assignment(ctx["assignment"]["id"]), employee_id)
    assert again["status"] == "EFFECTIVE"
    assert_same_instant(again["captured_at"], "2026-08-16T00:00:00Z", "captured_at")
    assert again["id"] != ctx["acknowledgment"]["id"], (
        "re-acknowledging appends a fresh evidence row rather than reviving the old one"
    )

    rows = retention_rows_for(employee_id)
    assert len(rows) == 3, (
        f"capture, compensation and recapture are three append-only rows, got {len(rows)}"
    )
    assert [row["record_kind"] for row in rows] == ["CAPTURE", "REVOCATION", "CAPTURE"], (
        f"rows must stay in creation order, got {[row['record_kind'] for row in rows]}"
    )
    assert sum(row["signed_delta"] for row in rows) == 1, (
        "the signed ledger must net to +1 once one effective acknowledgment stands"
    )
    assert_same_instant(
        rows[2]["retention_until"], "2029-08-15T00:00:00.000Z", "retention_until"
    )

    effective = acknowledgments_for(employee_id, "EFFECTIVE")
    assert len(effective) == 1, (
        f"exactly one EFFECTIVE acknowledgment must stand, got {len(effective)}"
    )
    assert len(acknowledgments_for(employee_id)) == 2, (
        "the revoked row is retained alongside the new one"
    )
    assert refresh_assignment(ctx["assignment"]["id"])["ack_state"] == "ACKNOWLEDGED"
    assert refresh_employee(employee_id)["open_ack_count"] == 0
