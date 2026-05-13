"""Order lifecycle: submission, modification, cancellation, refund, check-in,
completion, customer-accept (PRD §3.4, §3.6, §3.8).
"""

import pytest

from test_helpers import (
    OPERATOR_HEADERS,
    advance_clock,
    assert_order,
    checkin_order,
    checkin_payload,
    complete_order,
    create_draft_order,
    customer_accept,
    drive_order_to,
    expected_gross_price_cents,
    expected_provisional_commission,
    find_claim_for_order,
    get_customer,
    get_order,
    get_settlement_entries,
    iso_in,
    make_customer_headers,
    make_personnel_headers,
    patch_execution,
    patch_execution_payload,
    patch_order_payload,
    setup_basic_scenario,
    setup_order_in_state,
    submit_order,
    validate_error,
    validate_success,
)


# =============================================================================
# Submission (PRD §3.4)
# =============================================================================


def test_submit_order_computes_gross_price_cents(api):
    """PRD §3.4: "On successful submission, the server computes
    gross_price_cents as the service item's base_price_cents multiplied by
    duration_hours."

    Claim: after submit, gross_price_cents = base_price_cents * duration_hours.
    """
    ctx = setup_basic_scenario(base_price_cents=10000)
    order = create_draft_order(ctx, duration_hours=2.5)
    submitted = submit_order(ctx, order["id"])
    expected = expected_gross_price_cents(10000, 2.5)
    assert submitted["gross_price_cents"] == expected
    assert submitted["status"] == "PENDING_DISPATCH"


def test_submit_rejects_when_area_not_serviced(api):
    """PRD §3.4: "the customer's area_code must appear in the service item's
    service_areas list ... The ... area violation [surfaces] as
    ERR_AREA_NOT_SERVICED."

    Claim: submit when Customer.area_code is not in ServiceItem.service_areas
    → ERR_AREA_NOT_SERVICED 422.

    Note: PRD §3.4 also applies the same area check at create time. To exercise
    the submit-time check, we set up a valid pairing, create the draft order,
    then patch the service item's service_areas to remove the customer's area.
    """
    ctx = setup_basic_scenario()
    order = create_draft_order(ctx)
    # Now break the area-customer relationship by narrowing service_areas to
    # something the customer's area_code is not in.
    api.patch_service_item(
        ctx["service_item"]["id"], {"service_areas": ["CN-99-999"]},
        OPERATOR_HEADERS,
    )
    res = api.submit_order(order["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_AREA_NOT_SERVICED", expected_status=422)


def test_submit_rejects_when_item_inactive(api):
    """PRD §3.4: "the service item's active flag must be true ... an
    inactive-item attempt [surfaces] as ERR_ITEM_INACTIVE."

    Claim: submit on an order whose service item has active=false →
    ERR_ITEM_INACTIVE 422.

    Note: PRD §3.4 applies the same active-item check at create time. To reach
    the submit-time check we create the draft order while the item is still
    active, then patch active=false before submitting.
    """
    ctx = setup_basic_scenario()
    order = create_draft_order(ctx)
    api.patch_service_item(
        ctx["service_item"]["id"], {"active": False}, OPERATOR_HEADERS
    )
    res = api.submit_order(order["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_ITEM_INACTIVE", expected_status=422)


def test_submit_rejects_when_lead_time_short(api):
    """PRD §3.4: "scheduled_start_at must be at least one hour in the future
    (the inclusive comparison is scheduled_start_at >= current_time + 1 hour) ...
    The lead-time violation surfaces as ERR_LEAD_TIME_TOO_SHORT."

    Claim: scheduled_start_at < current_time + 1 hour → ERR_LEAD_TIME_TOO_SHORT 422.
    """
    ctx = setup_basic_scenario()
    order = create_draft_order(ctx, scheduled_start_at=iso_in(seconds=30))
    res = api.submit_order(order["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_LEAD_TIME_TOO_SHORT", expected_status=422)


# =============================================================================
# Modification window (PRD §3.4)
# =============================================================================


def test_modify_within_window_succeeds(api):
    """PRD §3.4: "modification is permitted exactly when the current time is
    more than 12 hours before scheduled_start_at — that is,
    current_time < scheduled_start_at - 12 hours."

    Claim: a PATCH to a PENDING_DISPATCH order while still >12h before start
    succeeds and recomputes gross_price_cents.
    """
    ctx = setup_basic_scenario(base_price_cents=10000)
    order = drive_order_to(ctx, "PENDING_DISPATCH")
    res = api.patch_order(
        order["id"],
        patch_order_payload(duration_hours=3.0),
        make_customer_headers(ctx["customer"]["id"]),
    )
    after = validate_success(res)
    assert after["duration_hours"] == 3.0
    assert after["gross_price_cents"] == expected_gross_price_cents(10000, 3.0)


def test_modify_inside_12h_window_rejected(api):
    """PRD §3.4: "A modification attempt that falls inside the 12-hour window
    or against an order not in PENDING_DISPATCH is rejected with
    ERR_MODIFY_WINDOW_CLOSED."

    Claim: a PATCH inside the 12h window → ERR_MODIFY_WINDOW_CLOSED 422.
    """
    ctx = setup_basic_scenario()
    # Place scheduled_start_at 10h in the future — inside the 12h window.
    order = drive_order_to(
        ctx, "PENDING_DISPATCH", scheduled_start_at=iso_in(hours=10)
    )
    res = api.patch_order(
        order["id"],
        patch_order_payload(duration_hours=3.0),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(res, "ERR_MODIFY_WINDOW_CLOSED", expected_status=422)


def test_modify_with_version_conflict(api):
    """PRD §3.4: "Modification can change scheduled_start_at and/or
    duration_hours and accepts an optional version in the request body for
    optimistic concurrency."
    PRD §2.5: "a mismatch is rejected with ERR_VERSION_CONFLICT (HTTP 409)."

    Claim: PATCH /dsd/orders/{id} with stale version → ERR_VERSION_CONFLICT 409.
    """
    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "PENDING_DISPATCH")
    res = api.patch_order(
        order["id"],
        patch_order_payload(duration_hours=3.0, version=order["version"] + 7),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(res, "ERR_VERSION_CONFLICT", expected_status=409)


# =============================================================================
# Cancellation (PRD §3.8)
# =============================================================================


def test_cancel_pending_dispatch_credits_wallet(api):
    """PRD §3.8: "On cancellation, the order's gross_price_cents is added back
    as a positive credit to the customer's wallet_credit_cents."

    Claim: cancelling PENDING_DISPATCH order credits gross_price_cents into
    Customer.wallet_credit_cents.
    """
    ctx = setup_basic_scenario(base_price_cents=10000)
    order = drive_order_to(ctx, "PENDING_DISPATCH")
    gross = order["gross_price_cents"]
    res = api.cancel_order(
        order["id"], make_customer_headers(ctx["customer"]["id"])
    )
    body = validate_success(res)
    assert body["status"] == "CANCELLED"
    refreshed_customer = get_customer(ctx["customer"]["id"])
    assert refreshed_customer["wallet_credit_cents"] == gross


def test_cancel_inside_2h_window_rejected(api):
    """PRD §3.8: "A cancellation attempt inside the 2-hour window is rejected
    with ERR_CANCEL_WINDOW_CLOSED."

    Claim: cancel when current_time >= scheduled_start_at − 2h →
    ERR_CANCEL_WINDOW_CLOSED 422.
    """
    ctx = setup_basic_scenario()
    # Place scheduled_start_at 1h in the future — strictly inside the 2h window.
    order = drive_order_to(
        ctx, "PENDING_DISPATCH", scheduled_start_at=iso_in(hours=1.5)
    )
    res = api.cancel_order(
        order["id"], make_customer_headers(ctx["customer"]["id"])
    )
    validate_error(res, "ERR_CANCEL_WINDOW_CLOSED", expected_status=422)


def test_cancel_dispatched_decrements_assignee_workload(api):
    """PRD §3.8: "If the order was already past PENDING_DISPATCH and had an
    assigned personnel, that personnel's workload_active_orders is decremented
    by one."

    Claim: cancelling a DISPATCHED order decrements the assigned personnel's
    workload_active_orders by 1.
    """
    from test_helpers import get_personnel

    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "DISPATCHED")
    assignee_id = order["assigned_personnel_id"]
    before_p = get_personnel(assignee_id)
    res = api.cancel_order(
        order["id"], make_customer_headers(ctx["customer"]["id"])
    )
    validate_success(res)
    after_p = get_personnel(assignee_id)
    assert after_p["workload_active_orders"] == before_p["workload_active_orders"] - 1


# =============================================================================
# Check-in (PRD §3.6)
# =============================================================================


def test_checkin_face_failed_rejected(api):
    """PRD §3.6: "Failures in the face/location checks surface as
    ERR_CHECKIN_LOCATION_MISMATCH."

    Claim: check-in with checkin_face_passed=false → ERR_CHECKIN_LOCATION_MISMATCH 422.
    """
    ctx, order = setup_order_in_state("ACCEPTED")
    # Ensure we're within the 15-minute early window. drive_order_to does NOT
    # advance the clock until ACCEPTED → it advances at IN_PROGRESS step.
    # So for an ACCEPTED-stop drive, advance the clock manually.
    from datetime import datetime, timezone, timedelta

    sched = datetime.fromisoformat(
        order["scheduled_start_at"].replace("Z", "+00:00")
    )
    now = datetime.now(timezone.utc)
    target = sched - timedelta(minutes=14)
    secs = max(0, int((target - now).total_seconds()))
    if secs > 0:
        advance_clock(secs)
    assignee_id = order["assigned_personnel_id"]
    customer = ctx["customer"]
    res = api.checkin_order(
        order["id"],
        checkin_payload(
            checkin_lat=customer["address_lat"],
            checkin_lng=customer["address_lng"],
            checkin_face_passed=False,
        ),
        make_personnel_headers(assignee_id),
    )
    validate_error(res, "ERR_CHECKIN_LOCATION_MISMATCH", expected_status=422)


def test_checkin_far_from_customer_rejected(api):
    """PRD §3.6: "the haversine distance between the submitted coordinates and
    the customer's address_lat/address_lng be at most 0.2 kilometres. ...
    Failures in the face/location checks surface as ERR_CHECKIN_LOCATION_MISMATCH."

    Claim: check-in coordinates >0.2km away → ERR_CHECKIN_LOCATION_MISMATCH 422.
    """
    from datetime import datetime, timezone, timedelta

    ctx, order = setup_order_in_state("ACCEPTED")
    sched = datetime.fromisoformat(
        order["scheduled_start_at"].replace("Z", "+00:00")
    )
    now = datetime.now(timezone.utc)
    target = sched - timedelta(minutes=14)
    secs = max(0, int((target - now).total_seconds()))
    if secs > 0:
        advance_clock(secs)
    assignee_id = order["assigned_personnel_id"]
    customer = ctx["customer"]
    # Offset ~1 km (much more than 0.2)
    far_lat = customer["address_lat"] + 0.01
    res = api.checkin_order(
        order["id"],
        checkin_payload(
            checkin_lat=far_lat,
            checkin_lng=customer["address_lng"],
            checkin_face_passed=True,
        ),
        make_personnel_headers(assignee_id),
    )
    validate_error(res, "ERR_CHECKIN_LOCATION_MISMATCH", expected_status=422)


# Deleted: test_second_checkin_rejected_execution_already_exists
# Reason (STEP 1b unique-derivability collapse — error precedence silence):
# PRD §2.7 explicitly orders state-checks before uniqueness ("Uniqueness
# constraints ... fire last because they detect collisions that only matter
# once everything else has passed"). A 2nd check-in on an order already in
# IN_PROGRESS trips the state gate (ERR_INVALID_STATE) before any execution-
# uniqueness check could fire, so a PRD-faithful implementation cannot return
# ERR_EXECUTION_ALREADY_EXISTS from this scenario. The test contradicts the
# documented precedence and is therefore not derivable from PRD alone.


# =============================================================================
# Completion (PRD §3.6)
# =============================================================================


def test_complete_without_checklist_rejected(api):
    """PRD §3.6: "A checklist with any false entry or a missing photo is
    rejected with ERR_CHECKLIST_INCOMPLETE."

    Claim: complete with any checklist entry False → ERR_CHECKLIST_INCOMPLETE 422.
    """
    ctx, order = setup_order_in_state("IN_PROGRESS")
    assignee_id = order["assigned_personnel_id"]
    # Submit incomplete checklist (one False).
    patch_execution(
        order["id"],
        assignee_id,
        checklist=[True, False, True],
        before_url="https://photos.example.com/b",
        after_url="https://photos.example.com/a",
    )
    res = api.complete_order(order["id"], make_personnel_headers(assignee_id))
    validate_error(res, "ERR_CHECKLIST_INCOMPLETE", expected_status=422)


def test_complete_without_photos_rejected(api):
    """PRD §3.6: "A checklist with any false entry or a missing photo is
    rejected with ERR_CHECKLIST_INCOMPLETE."

    Claim: complete without a before/after photo → ERR_CHECKLIST_INCOMPLETE 422.
    """
    ctx, order = setup_order_in_state("IN_PROGRESS")
    assignee_id = order["assigned_personnel_id"]
    # Checklist all-true but no photos at all.
    patch_execution(
        order["id"], assignee_id, checklist=[True, True, True]
    )
    res = api.complete_order(order["id"], make_personnel_headers(assignee_id))
    validate_error(res, "ERR_CHECKLIST_INCOMPLETE", expected_status=422)


def test_complete_posts_provisional_commission(api):
    """PRD §3.6: "On success, Order.completed_at and the execution's
    completion_submitted_at are stamped to the current time, and a provisional
    SettlementLedgerEntry is posted with kind COMMISSION and withheld_until
    set to 72 hours past Order.completed_at."
    PRD §3.10: "The provisional amount is computed as gross_price_cents
    multiplied by 0.70 and then rounded half-up to integer cents."

    Claim: completing an order posts a COMMISSION ledger entry with
    amount = round_half_up(gross_price_cents * 0.70).
    """
    ctx, order = setup_order_in_state("COMPLETED")
    expected_provisional = expected_provisional_commission(order["gross_price_cents"])
    entries = get_settlement_entries(order["assigned_personnel_id"])
    commissions = [
        e
        for e in entries
        if e.get("order_id") == order["id"] and e.get("kind") == "COMMISSION"
    ]
    assert len(commissions) == 1
    assert commissions[0]["amount_cents"] == expected_provisional


# =============================================================================
# Customer-accept (PRD §3.6)
# =============================================================================


def test_customer_accept_transitions_and_decrements_workload(api):
    """PRD §3.6: "On success, Order.accepted_at is set to the current time,
    the assigned personnel's workload_active_orders is decremented by one,
    and the final commission is reconciled against the provisional posting."

    Claim: customer-accept moves Order to ACCEPTED_BY_CUSTOMER and decrements
    workload_active_orders by 1.
    """
    from test_helpers import get_personnel

    ctx, order = setup_order_in_state("COMPLETED")
    assignee_id = order["assigned_personnel_id"]
    before_p = get_personnel(assignee_id)
    accepted = customer_accept(ctx, order["id"])
    assert accepted["status"] == "ACCEPTED_BY_CUSTOMER"
    after_p = get_personnel(assignee_id)
    assert after_p["workload_active_orders"] == before_p["workload_active_orders"] - 1


# =============================================================================
# Refund (PRD §3.8)
# =============================================================================


def test_refund_after_complete_within_complaint_window(api):
    """PRD §3.8: "Refund drives the order from COMPLETED to REFUNDED and is
    permitted only inside the 72-hour complaint window — that is,
    current_time < Order.completed_at + 72 hours."

    Claim: refund within 72h after completion succeeds and moves to REFUNDED.
    """
    ctx, order = setup_order_in_state("COMPLETED")
    res = api.refund_order(order["id"], OPERATOR_HEADERS)
    body = validate_success(res)
    assert body["status"] == "REFUNDED"


def test_refund_credits_wallet_and_decrements_workload(api):
    """PRD §3.8: "Refund also adds gross_price_cents back into
    wallet_credit_cents, decrements the assigned personnel's
    workload_active_orders by one, and stamps Order.refunded_at to the
    current time."

    Claim: refund increments Customer.wallet_credit_cents by gross_price_cents
    and decrements personnel.workload_active_orders by 1.
    """
    from test_helpers import get_personnel

    ctx, order = setup_order_in_state("COMPLETED")
    assignee_id = order["assigned_personnel_id"]
    before_p = get_personnel(assignee_id)
    before_c = get_customer(ctx["customer"]["id"])
    gross = order["gross_price_cents"]
    api.refund_order(order["id"], OPERATOR_HEADERS)
    after_p = get_personnel(assignee_id)
    after_c = get_customer(ctx["customer"]["id"])
    assert after_c["wallet_credit_cents"] == before_c["wallet_credit_cents"] + gross
    assert after_p["workload_active_orders"] == before_p["workload_active_orders"] - 1


def test_refund_past_72h_rejected(api):
    """PRD §3.8: "A refund attempt past that window, or against an order
    already in ACCEPTED_BY_CUSTOMER, is rejected with
    ERR_COMPLAINT_PERIOD_EXPIRED."

    Claim: refund called >72h after completed_at → ERR_COMPLAINT_PERIOD_EXPIRED 422.
    """
    ctx, order = setup_order_in_state("COMPLETED")
    # Advance the clock 72h + 1min past completed_at.
    advance_clock(72 * 3600 + 60)
    res = api.refund_order(order["id"], OPERATOR_HEADERS)
    validate_error(res, "ERR_COMPLAINT_PERIOD_EXPIRED", expected_status=422)


def test_refund_after_customer_accept_rejected(api):
    """PRD §3.8: "A refund attempt past that window, or against an order
    already in ACCEPTED_BY_CUSTOMER, is rejected with
    ERR_COMPLAINT_PERIOD_EXPIRED."

    Claim: refund on an ACCEPTED_BY_CUSTOMER order →
    ERR_COMPLAINT_PERIOD_EXPIRED 422.
    """
    ctx, order = setup_order_in_state("ACCEPTED_BY_CUSTOMER")
    res = api.refund_order(order["id"], OPERATOR_HEADERS)
    validate_error(res, "ERR_COMPLAINT_PERIOD_EXPIRED", expected_status=422)
