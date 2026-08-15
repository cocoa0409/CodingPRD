"""State-machine claims: invalid transitions, terminal-state lockdowns,
idempotency, and multi-step happy paths (PRD 3.1-3.9)."""
from test_helpers import (
    ApiErrorId,
    accept_order,
    add_locked_comp,
    assign_order,
    cancel_order,
    close_complaint,
    confirm_appointment,
    create_appraiser,
    create_client,
    create_comparable,
    create_complaint,
    create_fee_schedule,
    create_membership,
    create_order,
    create_report,
    create_revision_request,
    draft_complaint,
    first_workfile_of_type,
    get_order,
    scope_order,
    set_clock,
    setup_accepted_order,
    setup_assigned_order,
    setup_delivered_order,
    setup_order_in_analysis,
    setup_order_with_report,
    setup_report_pending_qc,
    setup_report_qc_passed,
    start_analysis,
    submit_complaint,
    submit_for_qc,
    validate_error,
    validate_success,
    verify_comparable,
)
from test_helpers import ADMIN, COMPLIANCE


def test_order_accept_before_scope_rejected(api):
    """PRD 3.3: "Acceptance — again a `FirmAdmin` action, again requiring an
    `ACTIVE` client — moves `SCOPE_DETERMINED` to `ACCEPTED`".
    PRD 2.7: "State preconditions: the target entity is in the transition's
    required from-state (`ERR_INVALID_STATE`, 409)".

    Design: Corner/state_machines/order_accept_before_scope_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    order = create_order(client["id"])

    response = api.accept_order(order["id"], {}, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    fresh = validate_success(api.get_order(order["id"], ADMIN), 200)
    assert fresh["status"] == "RECEIVED"


def test_order_cancel_twice_rejected_with_zero_fee_first_time(api):
    """PRD 3.9: "The cancellation fee, stored in `cancellation_fee_cents`, is
    zero when cancelling from `RECEIVED` or `SCOPE_DETERMINED`".
    PRD 3.9: "`CANCELLED` is terminal."

    Design: Corner/state_machines/order_cancel_twice_rejected_with_zero_fee_first_time
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    order = create_order(client["id"])

    first = validate_success(
        api.cancel_order(order["id"], {"reason": "client withdrew"}, ADMIN), 200
    )
    assert first["status"] == "CANCELLED"
    assert first["cancellation_fee_cents"] == 0

    second = api.cancel_order(order["id"], {"reason": "again"}, ADMIN)
    validate_error(second, ApiErrorId.ERR_INVALID_STATE, 409)


def test_client_terminated_is_terminal(api):
    """PRD 3.1: "terminate a client from either `ACTIVE` or `SUSPENDED` into
    the terminal `TERMINATED` state. Invoking any of these against a client in
    the wrong from-state is rejected with `ERR_INVALID_STATE`."
    PRD 3.1: "Termination goes further: every `ACTIVE` panel membership the
    client holds is moved to `REMOVED`".

    Design: Corner/state_machines/client_terminated_is_terminal
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    appraiser = create_appraiser()
    membership = create_membership(client["id"], appraiser["id"])

    terminated = validate_success(api.terminate_client(client["id"], ADMIN), 200)
    assert terminated["status"] == "TERMINATED"

    response = api.reactivate_client(client["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    fetched = validate_success(
        api.get_panel_membership(membership["id"], ADMIN), 200
    )
    assert fetched["status"] == "REMOVED"


def test_order_complete_before_delivery_rejected(api):
    """PRD 3.9: "Completion is the order's final gate, performed by a
    `FirmAdmin` from `DELIVERED`."

    Design: Corner/state_machines/order_complete_before_delivery_rejected
    """
    ctx = setup_accepted_order()
    response = api.complete_order(ctx["order"]["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_order_completion_happy_path_after_delivery(api):
    """PRD 3.9: "Completion stamps `completed_at` and lands the order in the
    terminal `COMPLETED` state."
    PRD 3.9: "the order's non-`PURGED` records must cover `ORDER_FORM`,
    `COMP_DATA`, `REPORT_PDF`, and `CERTIFICATION`, plus `INSPECTION_NOTES`
    when the order's `requires_inspection` is true — any gap fails with
    `ERR_WORKFILE_INCOMPLETE`."

    Design: Corner/state_machines/order_completion_happy_path_after_delivery
    """
    ctx = setup_delivered_order(delivery_clock="2026-08-02T00:00:00Z")
    response = api.complete_order(ctx["order"]["id"], ADMIN)
    completed = validate_success(response, 200)
    assert completed["status"] == "COMPLETED"
    assert completed["completed_at"] == "2026-08-02T00:00:00Z"


def test_appointment_complete_from_proposed_rejected(api):
    """PRD 3.4: "Once the logical clock has reached `window_end`, the assigned
    appraiser completes the appointment — `CONFIRMED` to `COMPLETED`, with an
    earlier attempt failing as `ERR_WINDOW_IN_PAST`".
    PRD 2.7: "State preconditions: the target entity is in the transition's
    required from-state (`ERR_INVALID_STATE`, 409)".

    Design: Corner/state_machines/appointment_complete_from_proposed_rejected
    """
    ctx = setup_assigned_order(desktop=False, order_overrides={"requested_turn_days": 14})
    from test_helpers import create_appointment

    appointment = create_appointment(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        "2026-08-02T09:00:00Z",
        "2026-08-02T10:00:00Z",
    )
    response = api.complete_appointment(
        appointment["id"], ctx["appraiser_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_appointment_no_show_terminal_lockdown(api):
    """PRD 3.4: "When the borrower fails to appear, marking the appointment
    `NO_SHOW` — open to the appraiser or a `FirmAdmin` — increments the
    appraiser's `no_show_count` and leaves the order in `INSPECTION_SCHEDULED`,
    where a fresh appointment is required."

    Design: Corner/state_machines/appointment_no_show_terminal_lockdown
    """
    ctx = setup_assigned_order(desktop=False, order_overrides={"requested_turn_days": 14})
    from test_helpers import create_appointment

    appointment = create_appointment(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        "2026-08-02T09:00:00Z",
        "2026-08-02T10:00:00Z",
    )
    confirm_appointment(appointment["id"], ctx["appraiser"]["id"])
    set_clock("2026-08-02T10:30:00Z")

    no_show = validate_success(api.no_show_appointment(appointment["id"], ADMIN), 200)
    assert no_show["status"] == "NO_SHOW"

    # NO_SHOW is terminal: completing it now is a wrong-from-state rejection.
    response = api.complete_appointment(appointment["id"], ctx["appraiser_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    order = get_order(ctx["order"]["id"])
    assert order["status"] == "INSPECTION_SCHEDULED"
    appraiser = validate_success(
        api.get_appraiser(ctx["appraiser"]["id"], ADMIN), 200
    )
    assert appraiser["no_show_count"] == 1


def test_comparable_lock_from_draft_rejected(api):
    """PRD 3.5: "Locking — `VERIFIED` to `LOCKED` — is the appraiser's
    declaration that a comparable supports the value conclusion."

    Design: Corner/state_machines/comparable_lock_from_draft_rejected
    """
    ctx = setup_order_in_analysis()
    comp = create_comparable(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="1 Pine St",
        sale_price_cents=44000000,
        sale_date="2026-06-15",
        distance_miles=0.40,
        site_adjustment_cents=0,
        gla_adjustment_cents=0,
        condition_adjustment_cents=0,
    )
    response = api.lock_comparable(comp["id"], ctx["appraiser_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_comparable_double_verify_rejected(api):
    """PRD 3.5: "Verification moves a comparable from `DRAFT` to `VERIFIED`
    and is only available while the order is `IN_ANALYSIS` or `IN_REVISION`;
    any other order state is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/comparable_double_verify_rejected
    """
    ctx = setup_order_in_analysis()
    comp = create_comparable(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="1 Pine St",
        sale_price_cents=44000000,
        sale_date="2026-06-15",
        distance_miles=0.40,
        site_adjustment_cents=0,
        gla_adjustment_cents=0,
        condition_adjustment_cents=0,
    )
    verify_comparable(comp["id"], ctx["appraiser"]["id"])

    response = api.verify_comparable(comp["id"], ctx["appraiser_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_comparable_excluded_is_terminal(api):
    """PRD 3.5: "A comparable still in `DRAFT` or `VERIFIED` may instead be
    excluded, moving it to the terminal `EXCLUDED` state."

    Design: Corner/state_machines/comparable_excluded_is_terminal
    """
    ctx = setup_order_in_analysis()
    comp = create_comparable(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        address="1 Pine St",
        sale_price_cents=44000000,
        sale_date="2026-06-15",
        distance_miles=0.40,
        site_adjustment_cents=0,
        gla_adjustment_cents=0,
        condition_adjustment_cents=0,
    )
    excluded = validate_success(
        api.exclude_comparable(comp["id"], ctx["appraiser_headers"]), 200
    )
    assert excluded["status"] == "EXCLUDED"

    response = api.verify_comparable(comp["id"], ctx["appraiser_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_report_qc_pass_from_draft_rejected(api):
    """PRD 3.6: "A passing verdict records the acting reviewer's id in
    `reviewer_id` and moves the report from `PENDING_QC` to `QC_PASSED`."
    PRD 2.7: "State preconditions: the target entity is in the transition's
    required from-state (`ERR_INVALID_STATE`, 409)".

    Design: Corner/state_machines/report_qc_pass_from_draft_rejected
    """
    ctx = setup_order_with_report(with_reviewer=True)
    response = api.qc_pass_report(ctx["report"]["id"], ctx["reviewer_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_report_qc_fail_cycle_returns_to_draft(api):
    """PRD 3.6: "A failing verdict carries the reviewer's `notes`, increments
    `qc_fail_count`, returns the report to `DRAFT`, and moves the order from
    `QC_REVIEW` back to `IN_REVISION` when an `ACCEPTED` revision request
    exists on the order, or to `DRAFTING` otherwise."
    PRD 3.6: "Submission is allowed from `DRAFT`, or from `UNDER_REVISION`
    during a revision cycle — any other report state is `ERR_INVALID_STATE`".

    Design: Corner/state_machines/report_qc_fail_cycle_returns_to_draft
    """
    ctx = setup_report_pending_qc()
    failed = validate_success(
        api.qc_fail_report(
            ctx["report"]["id"],
            {"notes": "Missing cost approach discussion"},
            ctx["reviewer_headers"],
        ),
        200,
    )
    assert failed["status"] == "DRAFT"
    assert failed["qc_fail_count"] == 1

    order = get_order(ctx["order"]["id"])
    assert order["status"] == "DRAFTING"

    resubmitted = validate_success(
        api.submit_report_for_qc(ctx["report"]["id"], ctx["appraiser_headers"]), 200
    )
    assert resubmitted["status"] == "PENDING_QC"


def test_revision_accept_after_rebut_rejected(api):
    """PRD 3.7: "Alternatively, the firm rebuts an `OPEN` request, recording a
    required `rebuttal`; a rebuttal charges no fee and leaves both the order
    and the report in `DELIVERED`."
    PRD 3.7: "`REBUTTED`, `SUPERSEDED`, and `RESOLVED` are all terminal."

    Design: Corner/state_machines/revision_accept_after_rebut_rejected
    """
    ctx = setup_delivered_order()
    rr = create_revision_request(
        ctx["order"]["id"], ctx["client"]["id"], detail="Fix photo caption"
    )

    rebutted = validate_success(
        api.rebut_revision_request(
            rr["id"], {"rebuttal": "Original stands per workfile"}, ADMIN
        ),
        200,
    )
    assert rebutted["status"] == "REBUTTED"

    response = api.accept_revision_request(rr["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    order = get_order(ctx["order"]["id"])
    assert order["fee_current_cents"] == 45000
    assert order["status"] == "DELIVERED"


def test_revision_supersede_marks_prior_open(api):
    """PRD 3.7: "The new request starts `OPEN`, and if another request was
    already `OPEN` on the same order, the earlier one is moved to `SUPERSEDED`
    as part of the same write — which is exactly why the order's `version`
    advances at creation and why the concurrency guard exists."

    Design: Corner/state_machines/revision_supersede_marks_prior_open
    """
    ctx = setup_delivered_order()
    v1 = get_order(ctx["order"]["id"])["version"]
    rr1 = validate_success(
        api.create_revision_request(
            ctx["order"]["id"],
            {"kind": "CORRECTION", "detail": "First", "expected_order_version": v1},
            ctx["client_headers"],
        ),
        201,
    )
    assert rr1["status"] == "OPEN"

    v2 = get_order(ctx["order"]["id"])["version"]
    assert v2 == v1 + 1
    rr2 = validate_success(
        api.create_revision_request(
            ctx["order"]["id"],
            {
                "kind": "RECONSIDERATION_OF_VALUE",
                "detail": "Second, with value",
                "submitted_value_cents": 46000000,
                "expected_order_version": v2,
            },
            ctx["client_headers"],
        ),
        201,
    )
    assert rr2["status"] == "OPEN"

    rr1_after = validate_success(api.get_revision_request(rr1["id"], ADMIN), 200)
    assert rr1_after["status"] == "SUPERSEDED"


def test_workfile_purge_before_delivery_rejected(api):
    """PRD 3.8: "Its `retention_until` must be set and must fall strictly
    before the logical clock, failing with `ERR_RETENTION_NOT_EXPIRED`
    otherwise — and a null pin, meaning the order was never delivered, can
    never pass this gate."

    Design: Corner/state_machines/workfile_purge_before_delivery_rejected
    """
    ctx = setup_accepted_order()
    record = first_workfile_of_type(ctx["order"]["id"], "ORDER_FORM")

    response = api.purge_workfile_record(record["id"], COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_RETENTION_NOT_EXPIRED, 422)


def test_complaint_submit_before_draft_rejected(api):
    """PRD 3.8: "Submission moves it from `RESPONSE_DRAFTED` to
    `RESPONSE_SUBMITTED` and is a hard deadline".
    PRD 2.7: "State preconditions: the target entity is in the transition's
    required from-state (`ERR_INVALID_STATE`, 409)".

    Design: Corner/state_machines/complaint_submit_before_draft_rejected
    """
    ctx = setup_delivered_order()
    set_clock("2026-08-05T00:00:00Z")
    complaint = create_complaint(ctx["order"]["id"], ctx["appraiser"]["id"])

    response = api.submit_complaint_response(complaint["id"], COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_appraiser_deactivate_blocked_then_allowed_after_cancel(api):
    """PRD 3.2: "Deactivation moves `ACTIVE` to `INACTIVE` and is refused with
    `ERR_APPRAISER_HAS_OPEN_ASSIGNMENTS` while the appraiser still holds
    orders in any working state — `ASSIGNED`, `INSPECTION_SCHEDULED`,
    `INSPECTED`, `IN_ANALYSIS`, `DRAFTING`, or `QC_REVIEW`."
    PRD 3.9: "from `ACCEPTED` or `ASSIGNED` it is half of `fee_current_cents`,
    rounded half-up to whole cents — a 45500-cent fee yields a 22750-cent
    cancellation fee. Cancelling also moves every `PROPOSED` or `CONFIRMED`
    appointment on the order to `CANCELLED`".

    Design: Corner/state_machines/appraiser_deactivate_blocked_then_allowed_after_cancel
    """
    ctx = setup_assigned_order(desktop=False, order_overrides={"requested_turn_days": 14})
    from test_helpers import create_appointment

    appointment = create_appointment(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        "2026-08-02T09:00:00Z",
        "2026-08-02T10:00:00Z",
    )

    blocked = api.deactivate_appraiser(ctx["appraiser"]["id"], ADMIN)
    validate_error(blocked, ApiErrorId.ERR_APPRAISER_HAS_OPEN_ASSIGNMENTS, 422)

    cancelled = validate_success(
        api.cancel_order(ctx["order"]["id"], {"reason": "client pulled"}, ADMIN), 200
    )
    assert cancelled["status"] == "CANCELLED"
    # fee_current 45000 (schedule base, no rush/addons) -> half is 22500
    assert cancelled["cancellation_fee_cents"] == 22500

    appt_after = validate_success(
        api.get_appointment(appointment["id"], ADMIN), 200
    )
    assert appt_after["status"] == "CANCELLED"

    retry = validate_success(
        api.deactivate_appraiser(ctx["appraiser"]["id"], ADMIN), 200
    )
    assert retry["status"] == "INACTIVE"


def test_appraiser_deactivate_reactivate_roundtrip_then_double_deactivate_rejected(api):
    """PRD 3.2: "Deactivation moves `ACTIVE` to `INACTIVE` and is refused with
    `ERR_APPRAISER_HAS_OPEN_ASSIGNMENTS` while the appraiser still holds
    orders in any working state — `ASSIGNED`, `INSPECTION_SCHEDULED`,
    `INSPECTED`, `IN_ANALYSIS`, `DRAFTING`, or `QC_REVIEW`. Reactivation
    moves `INACTIVE` back to `ACTIVE` and requires the appraiser's
    `license_expiry` to fall strictly after the logical clock's date, failing
    with `ERR_LICENSE_EXPIRED` otherwise; the same unexpired-license rule
    recurs at assignment (§3.4) and at delivery (§3.6). Both transitions
    reject a wrong from-state with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/appraiser_deactivate_reactivate_roundtrip_then_double_deactivate_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    appraiser = create_appraiser()

    validate_success(api.deactivate_appraiser(appraiser["id"], ADMIN), 200)
    reactivated = validate_success(
        api.reactivate_appraiser(appraiser["id"], ADMIN), 200
    )
    assert reactivated["status"] == "ACTIVE"

    validate_success(api.deactivate_appraiser(appraiser["id"], ADMIN), 200)
    second = api.deactivate_appraiser(appraiser["id"], ADMIN)
    validate_error(second, ApiErrorId.ERR_INVALID_STATE, 409)


def test_panel_membership_remove_twice_rejected(api):
    """PRD 3.1: "A membership leaves the panel through removal, moving from
    `ACTIVE` to the terminal `REMOVED` state — a removal attempted against a
    membership that is not `ACTIVE` fails with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/panel_membership_remove_twice_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    appraiser = create_appraiser()
    membership = create_membership(client["id"], appraiser["id"])

    removed = validate_success(
        api.remove_panel_membership(membership["id"], ADMIN), 200
    )
    assert removed["status"] == "REMOVED"

    response = api.remove_panel_membership(membership["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


def test_complaint_closed_terminal_lockdown(api):
    """PRD 3.8: "Either close stamps `closed_at`, decrements the order's
    `open_complaint_count` by one, and, when that decrement brings the count
    to zero, returns every `LEGAL_HOLD` workfile record of the order to
    `ACTIVE`."
    PRD 3.8: "`NO_ACTION` closes the complaint to `CLOSED_NO_ACTION`, and
    `SANCTIONED` closes it to `CLOSED_SANCTIONED` — both terminal."

    Design: Corner/state_machines/complaint_closed_terminal_lockdown
    """
    ctx = setup_delivered_order()
    complaint = create_complaint(ctx["order"]["id"], ctx["appraiser"]["id"])
    draft_complaint(complaint["id"])
    submit_complaint(complaint["id"])
    closed = close_complaint(complaint["id"], "NO_ACTION")
    assert closed["status"] == "CLOSED_NO_ACTION"

    response = api.draft_complaint_response(
        complaint["id"], {"response_text": "too late"}, COMPLIANCE
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    order = get_order(ctx["order"]["id"])
    assert order["open_complaint_count"] == 0
    order_form = first_workfile_of_type(ctx["order"]["id"], "ORDER_FORM")
    assert order_form["status"] == "ACTIVE"
