"""Difficulty queue A: validation-pipeline priority pairs — the earlier
check wins when two rules are violated by one call (PRD 2.7)."""
from test_helpers import (
    accept_revision,
    confirm_appointment,
    create_appointment,
    create_appraiser,
    create_client,
    create_complaint,
    create_membership,
    create_order,
    get_order,
    open_revision_on_delivered,
    relock_comps,
    scope_order,
    accept_order,
    assign_order,
    set_clock,
    setup_assigned_order,
    setup_delivered_order,
    submit_for_qc,
    validate_error,
    validate_success,
)
from test_helpers import ADMIN, ApiErrorId


def _setup_deliver_with_hold_and_wrong_state():
    """Order delivered, complaint open (legal hold active), revision accepted
    and resubmitted so the report sits PENDING_QC — deliver then violates
    both the state rule (report not QC_PASSED) and the hold rule."""
    ctx = setup_delivered_order(delivery_clock="2026-08-02T00:00:00Z")
    set_clock("2026-08-05T00:00:00Z")
    complaint = create_complaint(ctx["order"]["id"], ctx["appraiser"]["id"])
    ctx["complaint"] = complaint
    rr = open_revision_on_delivered(ctx, detail="Fix commentary")
    accept_revision(rr["id"])
    relock_comps(ctx)
    submit_for_qc(ctx["report"]["id"], ctx["appraiser"]["id"])
    return ctx


def test_state_error_beats_safety_error_on_deliver(api):
    """PRD 2.7: "Every incoming request passes through an ordered validation
    pipeline, and the first failing check determines the rejection — later
    checks are not evaluated, so a request that would violate two rules always
    surfaces the earlier one."
    PRD 2.7: "5. State preconditions: the target entity is in the
    transition's required from-state (`ERR_INVALID_STATE`, 409);
    revision-request creation and complaint creation use
    `ERR_ORDER_NOT_DELIVERED` (409) for their order-state overlay instead."
    PRD 2.7: "7. License, signature, and safety gates (422): expired licenses
    (`ERR_LICENSE_EXPIRED`), insufficient license level
    (`ERR_LICENSE_LEVEL_INSUFFICIENT`), missing supervisor co-signature
    (`ERR_SIGNATURE_COSIGN_REQUIRED`), co-signer mismatch
    (`ERR_SUPERVISOR_SIGNATURE_MISMATCH`), reviewer conflicts
    (`ERR_SOD_REVIEWER_CONFLICT`), open-complaint holds
    (`ERR_COMPLIANCE_HOLD_ACTIVE`), workfile completeness
    (`ERR_WORKFILE_INCOMPLETE`), desktop-appraisal restrictions
    (`ERR_DESKTOP_NOT_ALLOWED`), and ineligible comparables
    (`ERR_COMP_INELIGIBLE`)."

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_deliver
    """
    ctx = _setup_deliver_with_hold_and_wrong_state()
    response = api.deliver_report(ctx["report"]["id"], ctx["appraiser_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_state_error_deliver_leaves_no_partial_side_effects(api):
    """PRD 2.7: "A request rejected at any step mutates no resource."
    PRD 2.7: "the first failing check determines the rejection — later checks
    are not evaluated".

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_safety_error_on_deliver
    """
    ctx = _setup_deliver_with_hold_and_wrong_state()
    api.deliver_report(ctx["report"]["id"], ctx["appraiser_headers"])

    report = validate_success(api.get_report(ctx["report"]["id"], ADMIN), 200)
    assert report["status"] == "PENDING_QC", "rejected deliver moved nothing"
    order = get_order(ctx["order"]["id"])
    assert order["open_complaint_count"] == 1
    assert order["status"] == "QC_REVIEW"


def _setup_referential_vs_temporal_confirm():
    """Order1 ASSIGNED to A with A's CONFIRMED appointment
    2026-08-02 09:00-10:00; order2 ASSIGNED to B with a PROPOSED appointment
    naming A at 10:15-11:15 (both an assignee mismatch and a buffered
    overlap for A)."""
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    from test_helpers import create_fee_schedule

    create_fee_schedule(client["id"])
    appraiser_a = create_appraiser(full_name="Ann Appraiser", license_number="CR-1001")
    appraiser_b = create_appraiser(full_name="Bob Appraiser", license_number="CR-1002")
    create_membership(client["id"], appraiser_a["id"])
    create_membership(client["id"], appraiser_b["id"])

    order1 = create_order(client["id"], property_address="1 First St")
    order1 = scope_order(order1["id"])
    order1 = accept_order(order1["id"])
    assign_order(order1["id"], appraiser_a["id"])
    appt1 = create_appointment(
        order1["id"], appraiser_a["id"], "2026-08-02T09:00:00Z", "2026-08-02T10:00:00Z"
    )
    confirm_appointment(appt1["id"], appraiser_a["id"])

    order2 = create_order(client["id"], property_address="2 Second St")
    order2 = scope_order(order2["id"])
    order2 = accept_order(order2["id"])
    assign_order(order2["id"], appraiser_b["id"])
    # proposal deliberately names A, not order2's assignee B
    appt2 = create_appointment(
        order2["id"],
        appraiser_a["id"],
        "2026-08-02T10:15:00Z",
        "2026-08-02T11:15:00Z",
        as_admin=True,
    )
    return appraiser_a, appt2


def test_referential_error_beats_temporal_error_on_confirm(api):
    """PRD 2.7: "Every incoming request passes through an ordered validation
    pipeline, and the first failing check determines the rejection — later
    checks are not evaluated, so a request that would violate two rules always
    surfaces the earlier one."
    PRD 2.7: "8. Cross-entity integrity (422): active-client checks
    (`ERR_CLIENT_NOT_ACTIVE`), panel membership (`ERR_APPRAISER_NOT_ON_PANEL`),
    assignee eligibility (`ERR_APPRAISER_NOT_ASSIGNABLE`), assignee identity
    (`ERR_NOT_ASSIGNED_APPRAISER`), and supervisor certification
    (`ERR_SUPERVISOR_NOT_CERTIFIED`)."
    PRD 2.7: "9. Temporal windows (422): appointment window timing
    (`ERR_WINDOW_IN_PAST`), appointment overlap (`ERR_APPOINTMENT_OVERLAP`),
    fee-schedule window overlap (`ERR_SCHEDULE_WINDOW_OVERLAP`), the
    reconsideration-of-value window (`ERR_ROV_WINDOW_EXPIRED`), the complaint
    response deadline (`ERR_RESPONSE_DEADLINE_PASSED`), and retention expiry
    (`ERR_RETENTION_NOT_EXPIRED`)."
    PRD 3.4: "the appointment's `appraiser_id` must equal the order's
    `assigned_appraiser_id` (`ERR_NOT_ASSIGNED_APPRAISER`)."

    Design: Difficulty/priority_pair_validation_conflict/referential_error_beats_temporal_error_on_confirm
    """
    appraiser_a, appt2 = _setup_referential_vs_temporal_confirm()
    from test_helpers import make_appraiser_headers

    response = api.confirm_appointment(
        appt2["id"], make_appraiser_headers(appraiser_a["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_ASSIGNED_APPRAISER, 422)


def test_referential_rejection_leaves_appointment_proposed(api):
    """PRD 2.7: "A request rejected at any step mutates no resource."

    Design: Difficulty/priority_pair_validation_conflict/referential_error_beats_temporal_error_on_confirm
    """
    appraiser_a, appt2 = _setup_referential_vs_temporal_confirm()
    from test_helpers import make_appraiser_headers

    api.confirm_appointment(appt2["id"], make_appraiser_headers(appraiser_a["id"]))

    appointment = validate_success(api.get_appointment(appt2["id"], ADMIN), 200)
    assert appointment["status"] == "PROPOSED"
