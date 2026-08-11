"""Billing, standing-series, compliance-doc, and driver state machines:
invalid transitions, terminal-state lockdown, and precondition gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_rate_card,
    create_booked_ride,
    create_client,
    create_client_with_billing_payer,
    create_compliant_driver,
    create_compliance_doc_payload,
    create_driver,
    create_late_cancel_invoice,
    create_payment_payload,
    create_rate_card_payload,
    create_standing_ride_payload,
    get_success_data,
    make_compliance_officer_headers,
    make_family_member_headers,
    set_clock,
    setup_standard_dispatch_env,
    validate_error,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def _setup_issued_fee_invoice():
    """Client with a 240-notice cancelled May ride (fee 1251), invoice
    generated and issued for [2026-05-01, 2026-05-08). Returns (client, invoice)."""
    create_active_rate_card()
    client = create_client()
    invoice, _ = create_late_cancel_invoice(
        client["id"], "2026-05-04T12:00:00Z", "2026-05-04T16:00:00Z",
        "2026-05-01", "2026-05-08", issue=True)
    return client, invoice


def test_issue_issued_invoice_returns_not_issuable(api):
    """PRD §3.8: "Issuing moves the invoice `DRAFT` → `ISSUED` — from any other
    state the attempt is `ERR_INVOICE_NOT_ISSUABLE`"
    PRD §3.8: "the invoice's `due_date` is set fourteen days after
    `period_end`."

    Design: Corner/state_machines/issue_issued_invoice_returns_not_issuable
    """
    _, invoice = _setup_issued_fee_invoice()
    assert invoice["due_date"] == "2026-05-22"
    resp = api_client.issue_invoice(invoice["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUABLE)
    after = validate_success(api_client.get_invoice(invoice["id"], BILLING))
    assert after["due_date"] == "2026-05-22", "due_date unchanged by failed re-issue"
    assert after["charges_cents"] == 1251


def test_void_paid_invoice_returns_not_voidable(api):
    """PRD §3.8: "Voiding anything else — a partially paid, paid, or already
    voided invoice, or one with any money applied — is
    `ERR_INVOICE_NOT_VOIDABLE`."

    Design: Corner/state_machines/void_paid_invoice_returns_not_voidable
    """
    client, member = create_client_with_billing_payer()
    create_active_rate_card()
    invoice, _ = create_late_cancel_invoice(
        client["id"], "2026-05-04T12:00:00Z", "2026-05-04T16:00:00Z",
        "2026-05-01", "2026-05-08", issue=True)
    get_success_data(api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=1251),
        make_family_member_headers(member["id"])))
    resp = api_client.void_invoice(invoice["id"], {"void_reason": "mistake"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_VOIDABLE)
    after = validate_success(api_client.get_invoice(invoice["id"], BILLING))
    assert after["issuance_status"] == "PAID"
    assert after["paid_cents"] == 1251


def test_refund_fully_refunded_payment_returns_not_refundable(api):
    """PRD §3.9: "a fully `REFUNDED` payment refuses further refunds with
    `ERR_PAYMENT_NOT_REFUNDABLE`."
    PRD §3.9: "On success the pool is debited by the credit portion,
    `refunded_cents` (initially zero) grows by the refund amount, and the
    payment moves to `PARTIALLY_REFUNDED`, or to `REFUNDED` when the cumulative
    refunds equal the original amount."

    Design: Corner/state_machines/refund_fully_refunded_payment_returns_not_refundable
    """
    client, member = create_client_with_billing_payer()
    payment = get_success_data(api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=500),
        make_family_member_headers(member["id"])))
    refunded = get_success_data(api_client.refund_payment(
        payment["id"], {"amount_cents": 500, "reason": "full"}, BILLING))
    assert refunded["status"] == "REFUNDED"
    assert refunded["refunded_cents"] == 500
    resp = api_client.refund_payment(
        payment["id"], {"amount_cents": 1, "reason": "extra"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_REFUNDABLE)


def test_activate_active_rate_card_returns_state_invalid(api):
    """PRD §3.3: "Activating a card that is not `DRAFT`, or retiring a card
    already `RETIRED`, is rejected with `ERR_RATE_CARD_STATE_INVALID`;
    retirement is permitted from either `DRAFT` or `ACTIVE`."

    Design: Corner/state_machines/activate_active_rate_card_returns_state_invalid
    """
    card = create_active_rate_card()
    assert card["status"] == "ACTIVE"
    resp = api_client.activate_rate_card(card["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_RATE_CARD_STATE_INVALID)
    after = validate_success(api_client.get_rate_card(card["id"], ADMIN))
    assert after["status"] == "ACTIVE"


def test_pause_ended_series_returns_standing_status_invalid(api):
    """PRD §3.4: "Lifecycle events posted with an `event_type` of `PAUSE`,
    `RESUME`, or `END` move the series `ACTIVE` → `PAUSED`, `PAUSED` →
    `ACTIVE`, or into terminal `ENDED` from either state; an event the current
    status does not permit is `ERR_STANDING_STATUS_INVALID`."

    Design: Corner/state_machines/pause_ended_series_returns_standing_status_invalid
    """
    client, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-05-20T09:00:00Z")
    series = get_success_data(api_client.create_standing_ride(
        create_standing_ride_payload(client["id"]), COORD))
    ended = get_success_data(api_client.standing_ride_status_event(
        series["id"], {"event_type": "END"}, COORD))
    assert ended["status"] == "ENDED"
    resp = api_client.standing_ride_status_event(
        series["id"], {"event_type": "PAUSE"}, COORD)
    validate_error(resp, ApiErrorId.ERR_STANDING_STATUS_INVALID)
    after = validate_success(api_client.get_standing_ride(series["id"], COORD))
    assert after["status"] == "ENDED"


def test_review_approved_doc_returns_already_reviewed(api):
    """PRD §3.2: "A `ComplianceOfficer` reviews with a `decision` of `APPROVE`
    or `REJECT` and an optional `review_note`; the review records
    `reviewed_by_user_id` alongside the note, and any attempt to review a
    document no longer in `PENDING_REVIEW` is rejected with
    `ERR_DOC_ALREADY_REVIEWED`."

    Design: Corner/state_machines/review_approved_doc_returns_already_reviewed
    """
    driver = create_driver()
    doc = get_success_data(api_client.create_compliance_doc(
        create_compliance_doc_payload(driver["id"], "BACKGROUND_CHECK"), COORD))
    reviewed = get_success_data(api_client.review_compliance_doc(
        doc["id"], {"decision": "APPROVE", "review_note": "clear"},
        make_compliance_officer_headers("rev-1")))
    assert reviewed["status"] == "APPROVED"
    assert reviewed["reviewed_by_user_id"] == "rev-1"
    resp = api_client.review_compliance_doc(
        doc["id"], {"decision": "REJECT", "review_note": "second thoughts"},
        make_compliance_officer_headers("rev-2"))
    validate_error(resp, ApiErrorId.ERR_DOC_ALREADY_REVIEWED)
    after = validate_success(api_client.get_compliance_doc(doc["id"], OFFICER))
    assert after["status"] == "APPROVED"
    assert after["reviewed_by_user_id"] == "rev-1", "first reviewer is not overwritten"


def test_activate_offboarded_driver_returns_driver_state_invalid(api):
    """PRD §3.2: "An event that the driver's current status does not permit —
    activating an `OFFBOARDED` driver, for instance — is rejected with
    `ERR_DRIVER_STATE_INVALID`."
    PRD §3.2: "`OFFBOARDED` is terminal."

    Design: Corner/state_machines/activate_offboarded_driver_returns_driver_state_invalid
    """
    driver, _ = create_compliant_driver()
    get_success_data(api_client.driver_status_event(
        driver["id"], {"event_type": "OFFBOARD", "reason": "left the company"}, COORD))
    resp = api_client.driver_status_event(
        driver["id"], {"event_type": "ACTIVATE"}, COORD)
    validate_error(resp, ApiErrorId.ERR_DRIVER_STATE_INVALID)
    after = validate_success(api_client.get_driver(driver["id"], COORD))
    assert after["status"] == "OFFBOARDED"


def test_activate_driver_without_docs_returns_compliance_incomplete(api):
    """PRD §2.9: "The posture is complete on a given date when the driver
    holds, for each of the three required document types — `BACKGROUND_CHECK`,
    `BONDING`, and `INSURANCE` — at least one `APPROVED` document whose
    half-open validity window covers that date."
    PRD §3.2: "Activation (`APPLICANT` → `ACTIVE`) and reinstatement
    (`SUSPENDED` → `ACTIVE`) both require the complete compliance posture of
    §2.9 evaluated at the logical today; an incomplete posture is rejected with
    `ERR_DRIVER_COMPLIANCE_INCOMPLETE`."

    Design: Corner/state_machines/activate_driver_without_docs_returns_compliance_incomplete
    """
    driver = create_driver()
    for doc_type in ("BACKGROUND_CHECK", "BONDING"):
        doc = get_success_data(api_client.create_compliance_doc(
            create_compliance_doc_payload(driver["id"], doc_type), COORD))
        get_success_data(api_client.review_compliance_doc(
            doc["id"], {"decision": "APPROVE"}, OFFICER))
    resp = api_client.driver_status_event(driver["id"], {"event_type": "ACTIVATE"}, COORD)
    validate_error(resp, ApiErrorId.ERR_DRIVER_COMPLIANCE_INCOMPLETE)
    after = validate_success(api_client.get_driver(driver["id"], COORD))
    assert after["status"] == "APPLICANT"


def test_accept_exceeding_daily_cap_returns_cap_exceeded(api):
    """PRD §3.5: "Acceptance rechecks the full eligibility rule at that moment
    — an offer accepted late can still fail: a driver no longer `ACTIVE` or
    whose documents do not cover the pickup date is rejected with
    `ERR_DRIVER_NOT_ELIGIBLE`, a newly created buffered-window conflict with
    `ERR_RIDE_OVERLAP_DRIVER`, and a daily cap that no longer fits with
    `ERR_DRIVER_DAILY_CAP_EXCEEDED`."
    PRD §3.5: "headroom under the daily cap such that `current_load_minutes`
    plus the ride's `estimated_duration_minutes` stays at or below
    `max_daily_service_minutes`"

    Design: Corner/state_machines/accept_exceeding_daily_cap_returns_cap_exceeded
    """
    client, driver = setup_standard_dispatch_env(max_daily_service_minutes=120)
    r1 = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z",
                            estimated_duration_minutes=90)
    r2 = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T14:00:00Z",
                            estimated_duration_minutes=90)
    # PRD §3.2: current_load_minutes counts rides "whose pickup date is the
    # logical today", so the clock must sit on the pickup date for the cap
    # arithmetic to engage.
    set_clock("2026-06-05T08:00:00Z")
    asg2 = get_success_data(api_client.dispatch_ride(r2["id"], COORD))
    asg1 = get_success_data(api_client.dispatch_ride(r1["id"], COORD))
    from test_helpers import make_driver_headers
    get_success_data(api_client.respond_assignment(
        asg1["id"], {"decision": "ACCEPT"}, make_driver_headers(driver["id"])))
    # Load is now 90; accepting another 90-minute offer would reach 180 > 120.
    resp = api_client.respond_assignment(
        asg2["id"], {"decision": "ACCEPT"}, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_DRIVER_DAILY_CAP_EXCEEDED)
    after = validate_success(api_client.get_ride(r2["id"], COORD))
    assert after["status"] == "DISPATCHING"


def test_deactivate_client_with_open_ride_returns_open_work(api):
    """PRD §3.1: "Deactivation — permitted from either `ACTIVE` or `SUSPENDED`
    — is guarded: the client must have no rides in any open state (`SCHEDULED`,
    `DISPATCHING`, `ASSIGNED`, `EN_ROUTE`, `ARRIVED`, or `IN_SERVICE`) and no
    invoices in `DRAFT`, `ISSUED`, or `PARTIALLY_PAID`, otherwise the request
    fails with `ERR_CLIENT_HAS_OPEN_WORK`."

    Design: Corner/state_machines/deactivate_client_with_open_ride_returns_open_work
    """
    client, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-05-20T09:00:00Z")
    create_booked_ride(client["id"], scheduled_pickup_at="2026-06-01T10:00:00Z")
    resp = api_client.patch_client(
        client["id"],
        {"status": "DEACTIVATED", "expected_client_version": client["version"]},
        COORD)
    validate_error(resp, ApiErrorId.ERR_CLIENT_HAS_OPEN_WORK)
    after = validate_success(api_client.get_client(client["id"], COORD))
    assert after["status"] == "ACTIVE"
