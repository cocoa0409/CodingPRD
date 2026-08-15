"""Validation claims: state overlays, cross-entity integrity, license gates,
temporal windows, uniqueness and fiscal bounds (PRD 2.7, 3.1-3.9)."""
from test_helpers import (
    ApiErrorId,
    accept_order,
    add_standard_locked_comps,
    assign_order,
    create_appraiser,
    create_client,
    create_complaint,
    create_fee_adjustment_payload,
    create_fee_schedule,
    create_membership,
    create_order,
    create_revision_request,
    draft_complaint,
    first_workfile_of_type,
    get_order,
    make_appraiser_headers,
    make_clientuser_headers,
    make_qc_reviewer_headers,
    scope_order,
    set_clock,
    setup_accepted_order,
    setup_assigned_order,
    setup_delivered_order,
    setup_order_in_analysis,
    setup_order_with_report,
    setup_report_pending_qc,
    submit_complaint,
    submit_for_qc,
    validate_error,
    validate_success,
)
from test_helpers import ADMIN, COMPLIANCE


def test_revision_create_on_undelivered_order_rejected(api):
    """PRD 3.7: "A `ClientUser` — acting only on their own client's orders,
    else `ERR_NOT_RESOURCE_OWNER` — or a `FirmAdmin` opens a revision request
    against a `DELIVERED` order, with any other order state failing as
    `ERR_ORDER_NOT_DELIVERED`."

    Design: Corner/validations/revision_create_on_undelivered_order_rejected
    """
    ctx = setup_accepted_order()
    response = api.create_revision_request(
        ctx["order"]["id"],
        {
            "kind": "CORRECTION",
            "detail": "too early",
            "expected_order_version": ctx["order"]["version"],
        },
        ctx["client_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ORDER_NOT_DELIVERED, 409)


def test_complaint_create_on_inflight_order_rejected(api):
    """PRD 3.8: "A board complaint arrives against a delivered or completed
    order — any other order state fails with `ERR_ORDER_NOT_DELIVERED`".

    Design: Corner/validations/complaint_create_on_inflight_order_rejected
    """
    ctx = setup_assigned_order()
    response = api.create_complaint(
        {
            "order_id": ctx["order"]["id"],
            "respondent_appraiser_id": ctx["appraiser"]["id"],
            "description": "premature",
        },
        COMPLIANCE,
    )
    validate_error(response, ApiErrorId.ERR_ORDER_NOT_DELIVERED, 409)


def test_order_create_for_suspended_client_rejected(api):
    """PRD 3.1: "Suspension blocks new order creation for the client —
    rejected with `ERR_CLIENT_NOT_ACTIVE` — while leaving in-flight orders
    untouched."

    Design: Corner/validations/order_create_for_suspended_client_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    validate_success(api.suspend_client(client["id"], ADMIN), 200)

    blocked = api.create_order(
        {
            "client_id": client["id"],
            "property_address": "5 New St",
            "property_type": "SFR",
            "estimated_value_cents": 45000000,
            "loan_type": "CONVENTIONAL",
            "requested_turn_days": 7,
        },
        make_clientuser_headers(client["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_CLIENT_NOT_ACTIVE, 422)

    validate_success(api.reactivate_client(client["id"], ADMIN), 200)
    created = create_order(client["id"])
    assert created["status"] == "RECEIVED"


def test_assign_appraiser_without_membership_rejected(api):
    """PRD 3.4: "An `ACTIVE` panel membership must exist for the order's
    client — otherwise `ERR_APPRAISER_NOT_ON_PANEL`."

    Design: Corner/validations/assign_appraiser_without_membership_rejected
    """
    ctx = setup_accepted_order(with_appraiser=True, with_membership=False)
    response = api.assign_order(
        ctx["order"]["id"], {"appraiser_id": ctx["appraiser"]["id"]}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_APPRAISER_NOT_ON_PANEL, 422)


def test_start_analysis_by_non_assignee_rejected(api):
    """PRD 3.4: "Any other order state fails with `ERR_INVALID_STATE`, and any
    actor other than the order's assigned appraiser fails with
    `ERR_NOT_ASSIGNED_APPRAISER`."

    Design: Corner/validations/start_analysis_by_non_assignee_rejected
    """
    ctx = setup_assigned_order()
    other = create_appraiser(
        full_name="B", license_number="CR-2", license_level="CERTIFIED_RESIDENTIAL"
    )
    create_membership(ctx["client"]["id"], other["id"])

    response = api.start_analysis(
        ctx["order"]["id"], make_appraiser_headers(other["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_ASSIGNED_APPRAISER, 422)


def test_assign_appraiser_license_expired_rejected(api):
    """PRD 3.4: "And `license_expiry` must fall strictly after the logical
    clock's date — otherwise `ERR_LICENSE_EXPIRED`."

    Design: Corner/validations/assign_appraiser_license_expired_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    create_fee_schedule(client["id"])
    expired = create_appraiser(
        full_name="Expired Ed", license_number="CR-9", license_expiry="2026-07-01"
    )
    create_membership(client["id"], expired["id"])
    order = create_order(client["id"])
    scope_order(order["id"], requires_inspection=False)
    accept_order(order["id"])

    response = api.assign_order(order["id"], {"appraiser_id": expired["id"]}, ADMIN)
    validate_error(response, ApiErrorId.ERR_LICENSE_EXPIRED, 422)


def test_appraiser_reactivate_with_expired_license_rejected(api):
    """PRD 3.2: "Reactivation moves `INACTIVE` back to `ACTIVE` and requires
    the appraiser's `license_expiry` to fall strictly after the logical
    clock's date, failing with `ERR_LICENSE_EXPIRED` otherwise".

    Design: Corner/validations/appraiser_reactivate_with_expired_license_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    appraiser = create_appraiser(license_expiry="2027-06-01")
    validate_success(api.deactivate_appraiser(appraiser["id"], ADMIN), 200)

    set_clock("2027-07-01T00:00:00Z")
    response = api.reactivate_appraiser(appraiser["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_LICENSE_EXPIRED, 422)


def test_high_value_order_rejects_licensed_appraiser(api):
    """PRD 3.4: "The license must cover the tier: `HIGH_VALUE` demands
    `CERTIFIED_RESIDENTIAL`, `COMPLEX` demands `LICENSED` or
    `CERTIFIED_RESIDENTIAL`, and `STANDARD` accepts any level — otherwise
    `ERR_LICENSE_LEVEL_INSUFFICIENT`."

    Design: Corner/validations/high_value_order_rejects_licensed_appraiser
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    create_fee_schedule(
        client["id"], complexity_tier="HIGH_VALUE", base_fee_cents=85000
    )
    licensed = create_appraiser(
        full_name="Larry Licensed", license_level="LICENSED", license_number="LA-1"
    )
    create_membership(client["id"], licensed["id"])
    order = create_order(
        client["id"],
        property_address="1 Mansion Row",
        estimated_value_cents=100000000,
    )
    scope_order(order["id"])
    accept_order(order["id"])

    response = api.assign_order(order["id"], {"appraiser_id": licensed["id"]}, ADMIN)
    validate_error(response, ApiErrorId.ERR_LICENSE_LEVEL_INSUFFICIENT, 422)


def test_qc_reviewer_must_be_certified_residential(api):
    """PRD 3.6: "A pass additionally requires the reviewer's identity to
    resolve to an appraiser record that exists, is `ACTIVE`, and holds
    `CERTIFIED_RESIDENTIAL` — anything less fails with
    `ERR_LICENSE_LEVEL_INSUFFICIENT`."

    Design: Corner/validations/qc_reviewer_must_be_certified_residential
    """
    ctx = setup_order_with_report()
    licensed_reviewer = create_appraiser(
        full_name="Q Licensed", license_level="LICENSED", license_number="LA-2"
    )
    submit_for_qc(ctx["report"]["id"], ctx["appraiser"]["id"])
    response = api.qc_pass_report(
        ctx["report"]["id"], make_qc_reviewer_headers(licensed_reviewer["id"])
    )
    validate_error(response, ApiErrorId.ERR_LICENSE_LEVEL_INSUFFICIENT, 422)


def test_rov_after_90_days_rejected_but_correction_allowed(api):
    """PRD 3.7: "A reconsideration must also be opened within ninety days of
    the order's `first_delivered_at`; a later attempt fails with
    `ERR_ROV_WINDOW_EXPIRED`, while a `CORRECTION` carries no such window."

    Design: Corner/validations/rov_after_90_days_rejected_but_correction_allowed
    """
    ctx = setup_delivered_order(delivery_clock="2026-08-02T00:00:00Z")
    # day 91 after first delivery 2026-08-02
    set_clock("2026-11-01T00:00:00Z")

    v1 = get_order(ctx["order"]["id"])["version"]
    response = api.create_revision_request(
        ctx["order"]["id"],
        {
            "kind": "RECONSIDERATION_OF_VALUE",
            "detail": "value too low",
            "submitted_value_cents": 47000000,
            "expected_order_version": v1,
        },
        ctx["client_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ROV_WINDOW_EXPIRED, 422)

    v2 = get_order(ctx["order"]["id"])["version"]
    created = validate_success(
        api.create_revision_request(
            ctx["order"]["id"],
            {
                "kind": "CORRECTION",
                "detail": "typo still fixable",
                "expected_order_version": v2,
            },
            ctx["client_headers"],
        ),
        201,
    )
    assert created["status"] == "OPEN"


def test_complaint_submit_after_deadline_rejected(api):
    """PRD 3.8: "Submission moves it from `RESPONSE_DRAFTED` to
    `RESPONSE_SUBMITTED` and is a hard deadline: the logical clock must be at
    or before `response_due_at`, and a submission after that instant fails
    with `ERR_RESPONSE_DEADLINE_PASSED`."

    Design: Corner/validations/complaint_submit_after_deadline_rejected
    """
    ctx = setup_delivered_order()
    set_clock("2026-08-10T00:00:00Z")
    complaint = create_complaint(ctx["order"]["id"], ctx["appraiser"]["id"])
    draft_complaint(complaint["id"], "Draft")
    # response_due_at is 2026-08-31; submit one day late
    set_clock("2026-09-01T00:00:00Z")

    response = api.submit_complaint_response(complaint["id"], COMPLIANCE)
    validate_error(response, ApiErrorId.ERR_RESPONSE_DEADLINE_PASSED, 422)


def test_duplicate_active_membership_rejected_then_readd_after_remove(api):
    """PRD 3.1: "At most one `ACTIVE` membership may exist for a given
    (`client_id`, `appraiser_id`) pair: creating a second active row is
    rejected with `ERR_DUPLICATE_PANEL_MEMBERSHIP`, although a pair whose
    earlier membership is `REMOVED` may be created anew."

    Design: Corner/validations/duplicate_active_membership_rejected_then_readd_after_remove
    """
    set_clock("2026-08-01T00:00:00Z")
    client = create_client()
    appraiser = create_appraiser()
    first = create_membership(client["id"], appraiser["id"])

    duplicate = api.create_panel_membership(
        {"client_id": client["id"], "appraiser_id": appraiser["id"]}, ADMIN
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_PANEL_MEMBERSHIP, 422)

    validate_success(api.remove_panel_membership(first["id"], ADMIN), 200)
    readded = validate_success(
        api.create_panel_membership(
            {"client_id": client["id"], "appraiser_id": appraiser["id"]}, ADMIN
        ),
        201,
    )
    assert readded["status"] == "ACTIVE"
    assert readded["id"] != first["id"]


def test_selector_empty_pool_rejected(api):
    """PRD 3.4: "An empty candidate pool rejects the assignment with
    `ERR_NO_ELIGIBLE_APPRAISER`."

    Design: Corner/validations/selector_empty_pool_rejected
    """
    ctx = setup_accepted_order(with_appraiser=False)
    response = api.assign_order(ctx["order"]["id"], {}, ADMIN)
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_APPRAISER, 422)


def test_waiver_above_current_fee_rejected_exact_amount_allowed(api):
    """PRD 3.9: "A `WAIVER` subtracts the amount from `fee_current_cents` and
    accumulates it into `waived_total_cents`, and a waiver whose amount
    exceeds the order's current `fee_current_cents` is rejected with
    `ERR_FEE_WAIVER_EXCEEDS_BALANCE`."

    Design: Corner/validations/waiver_above_current_fee_rejected_exact_amount_allowed
    """
    ctx = setup_accepted_order()  # fee_current 45000
    too_much = api.create_fee_adjustment(
        ctx["order"]["id"],
        create_fee_adjustment_payload("WAIVER", 45001, reason="too much"),
        ADMIN,
    )
    validate_error(too_much, ApiErrorId.ERR_FEE_WAIVER_EXCEEDS_BALANCE, 422)

    exact = validate_success(
        api.create_fee_adjustment(
            ctx["order"]["id"],
            create_fee_adjustment_payload("WAIVER", 45000, reason="full goodwill"),
            ADMIN,
        ),
        200,
    )
    assert exact["fee_current_cents"] == 0
    assert exact["waived_total_cents"] == 45000


def test_appointment_create_window_in_past_rejected(api):
    """PRD 3.4: "`window_start` must fall strictly after the logical clock,
    failing with `ERR_WINDOW_IN_PAST`".

    Design: Corner/validations/appointment_create_window_in_past_rejected
    """
    ctx = setup_assigned_order(desktop=False, order_overrides={"requested_turn_days": 14})
    response = api.create_appointment(
        {
            "order_id": ctx["order"]["id"],
            "appraiser_id": ctx["appraiser"]["id"],
            "window_start": "2026-07-31T09:00:00Z",
            "window_end": "2026-07-31T10:00:00Z",
        },
        ctx["appraiser_headers"],
    )
    validate_error(response, ApiErrorId.ERR_WINDOW_IN_PAST, 422)


def test_order_complete_blocked_by_open_complaint(api):
    """PRD 3.9: "The order's `open_complaint_count` must be zero, failing with
    `ERR_COMPLIANCE_HOLD_ACTIVE` otherwise."

    Design: Corner/validations/order_complete_blocked_by_open_complaint
    """
    ctx = setup_delivered_order()
    create_complaint(ctx["order"]["id"], ctx["appraiser"]["id"])

    response = api.complete_order(ctx["order"]["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_COMPLIANCE_HOLD_ACTIVE, 422)


def test_order_complete_blocked_by_purged_required_workfile(api):
    """PRD 3.9: "And the workfile must be complete: the order's non-`PURGED`
    records must cover `ORDER_FORM`, `COMP_DATA`, `REPORT_PDF`, and
    `CERTIFICATION`, plus `INSPECTION_NOTES` when the order's
    `requires_inspection` is true — any gap fails with
    `ERR_WORKFILE_INCOMPLETE`."

    Design: Corner/validations/order_complete_blocked_by_purged_required_workfile
    """
    ctx = setup_delivered_order(delivery_clock="2026-08-02T00:00:00Z")
    set_clock("2031-08-03T00:00:00Z")
    order_form = first_workfile_of_type(ctx["order"]["id"], "ORDER_FORM")
    validate_success(api.purge_workfile_record(order_form["id"], COMPLIANCE), 200)

    response = api.complete_order(ctx["order"]["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_WORKFILE_INCOMPLETE, 422)
