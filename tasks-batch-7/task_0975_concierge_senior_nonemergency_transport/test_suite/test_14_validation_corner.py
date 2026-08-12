"""Validation corner cases: window violations, invoice set rules, payment and
refund caps, referential integrity, dispute gating, and authentication order."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_active_rate_card,
    create_booked_ride,
    create_client,
    create_client_with_billing_payer,
    create_completed_ride,
    create_compliant_driver,
    create_compliance_doc_payload,
    create_driver,
    create_family_member_payload,
    create_invoice_payload,
    create_late_cancel_invoice,
    create_payment_payload,
    create_rate_card_payload,
    create_standing_ride_payload,
    get_success_data,
    make_client_headers,
    make_family_member_headers,
    seed_credit_via_payment,
    set_clock,
    validate_error,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.6: "The `X-User-Role` and `X-User-ID` headers must be present and
    recognized; otherwise `ERR_UNAUTHENTICATED`."
    PRD §2.6: "Path-referenced and body-referenced ids must exist, validated
    left to right; the first missing reference yields `ERR_NOT_FOUND`."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    resp = api_client.get_ride(NON_EXISTENT_UUID, headers=None)
    # Authentication (stage 2) precedes existence (stage 6): 401, not 404.
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_doc_window_invalid_returns_422(api):
    """PRD §3.2: "A submission whose `valid_until` is not strictly after
    `valid_from` is rejected with `ERR_DOC_WINDOW_INVALID`."

    Design: Corner/validations/doc_window_invalid_returns_422
    """
    driver = create_driver()
    resp = api_client.create_compliance_doc(
        create_compliance_doc_payload(driver["id"], "BONDING",
                                      valid_from="2026-06-01", valid_until="2026-06-01"),
        COORD)
    validate_error(resp, ApiErrorId.ERR_DOC_WINDOW_INVALID)


def test_rate_window_invalid_returns_422(api):
    """PRD §3.3: "Activation requires an internally valid window —
    `effective_from` strictly before `effective_to`, else
    `ERR_RATE_WINDOW_INVALID`"

    Design: Corner/validations/rate_window_invalid_returns_422
    """
    # PRD §3.3 pins the window check to activation: creation of the DRAFT
    # succeeds, and activation of the invalid window is what is rejected.
    card = get_success_data(api_client.create_rate_card(
        create_rate_card_payload(effective_from="2026-07-01", effective_to="2026-01-01"),
        ADMIN))
    resp = api_client.activate_rate_card(card["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_RATE_WINDOW_INVALID)
    after = validate_success(api_client.get_rate_card(card["id"], ADMIN))
    assert after["status"] == "DRAFT", "rejected activation leaves the card DRAFT"


def test_standing_window_invalid_returns_422(api):
    """PRD §3.4: "an inclusive `starts_on` / `ends_on` calendar range; an
    `ends_on` earlier than `starts_on` is rejected with
    `ERR_STANDING_WINDOW_INVALID`."

    Design: Corner/validations/standing_window_invalid_returns_422
    """
    client = create_client()
    resp = api_client.create_standing_ride(
        create_standing_ride_payload(client["id"], starts_on="2026-06-01",
                                     ends_on="2026-05-01"),
        COORD)
    validate_error(resp, ApiErrorId.ERR_STANDING_WINDOW_INVALID)


def test_invoice_period_invalid_returns_422(api):
    """PRD §3.8: "A `BillingAdmin` generates an invoice for a `client_id` over
    the half-open period from `period_start` to `period_end`; a `period_end`
    not strictly after `period_start` is rejected with
    `ERR_INVOICE_PERIOD_INVALID`"

    Design: Corner/validations/invoice_period_invalid_returns_422
    """
    client = create_client()
    resp = api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-06-08",
                               period_end="2026-06-01"),
        BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_INVALID)


def test_invoice_period_overlap_returns_409(api):
    """PRD §3.8: "a period intersecting any existing non-`VOIDED` invoice for
    that client with `ERR_INVOICE_PERIOD_OVERLAP` (touching boundaries do not
    intersect)"

    Design: Corner/validations/invoice_period_overlap_returns_409
    """
    create_active_rate_card()
    client = create_client()
    create_late_cancel_invoice(
        client["id"], "2026-05-04T12:00:00Z", "2026-05-04T16:00:00Z",
        "2026-05-01", "2026-05-08")
    resp = api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-05-05",
                               period_end="2026-05-12"),
        BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP)


def test_invoice_empty_period_returns_422(api):
    """PRD §3.8: "a period containing no billable work with
    `ERR_INVOICE_EMPTY`."

    Design: Corner/validations/invoice_empty_period_returns_422
    """
    client = create_client()
    resp = api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-07-01",
                               period_end="2026-07-08"),
        BILLING)
    validate_error(resp, ApiErrorId.ERR_INVOICE_EMPTY)


def test_payment_amount_zero_returns_422(api):
    """PRD §3.9: "Money arrives as a `Payment` naming the `client_id`, a
    tendered `amount_cents`, and a `method` of `CARD`, `ACH`, or `CHECK`; a
    non-positive amount is rejected with `ERR_PAYMENT_AMOUNT_INVALID`."

    Design: Corner/validations/payment_amount_zero_returns_422
    """
    client, member = create_client_with_billing_payer()
    resp = api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=0),
        make_family_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID)


def test_refund_exceeds_settled_returns_422(api):
    """PRD §3.9: "the amount may not exceed the payment's `amount_cents` minus
    its already `refunded_cents` (else `ERR_REFUND_EXCEEDS_SETTLED`)"

    Design: Corner/validations/refund_exceeds_settled_returns_422
    """
    client = create_client()
    payment = get_success_data(api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=500), BILLING))
    resp = api_client.refund_payment(
        payment["id"], {"amount_cents": 501, "reason": "too much"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_SETTLED)
    after = validate_success(api_client.get_payment(payment["id"], BILLING))
    assert after["status"] == "SETTLED"
    assert after["refunded_cents"] == 0


def _setup_credit_spent_refund():
    """Client credit 1000 from payment P; completed ride (fare 4500); invoice
    generated consuming all 1000 credit and issued. Returns (payment, invoice)."""
    client, member = create_client_with_billing_payer()
    create_active_rate_card()
    payment = seed_credit_via_payment(client["id"], 1000, payer_member_id=member["id"])
    driver, _ = create_compliant_driver()
    set_clock("2026-05-20T09:00:00Z")
    create_completed_ride(
        client["id"], driver["id"], "2026-06-01T10:00:00Z",
        estimated_duration_minutes=60, estimated_distance_miles=10,
        actual_distance_miles=10, service_minutes=60)
    invoice = get_success_data(api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-06-01", period_end="2026-06-08"),
        BILLING))
    get_success_data(api_client.issue_invoice(invoice["id"], BILLING))
    return payment, invoice


def test_refund_credit_spent_returns_409(api):
    """PRD §3.9: "Whatever portion of the refund exceeds the reversed
    applications was originally a credit-pool remainder, and that credit
    portion may not exceed the client's current `credit_balance_cents` — a
    client who has already spent the credit cannot refund it, and the entire
    refund is rejected with `ERR_REFUND_CREDIT_SPENT`."

    Design: Corner/validations/refund_credit_spent_returns_409
    """
    payment, _ = _setup_credit_spent_refund()
    # The 1000 remainder became credit and invoice generation consumed it all;
    # the refund's credit portion (1000) exceeds the current balance (0).
    resp = api_client.refund_payment(
        payment["id"], {"amount_cents": 1000, "reason": "want it back"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_REFUND_CREDIT_SPENT)
    after = validate_success(api_client.get_payment(payment["id"], BILLING))
    assert after["status"] == "SETTLED"
    assert after["refunded_cents"] == 0


def test_return_link_to_cancelled_ride_returns_mismatch(api):
    """PRD §3.4: "a `linked_return_ride_id` must target a ride of the **same
    client**, of kind `APPOINTMENT`, still `SCHEDULED`, and with no return link
    of its own — any mismatch is `ERR_RETURN_LINK_MISMATCH`"

    Design: Corner/validations/return_link_to_cancelled_ride_returns_mismatch
    """
    client = create_client()
    create_active_rate_card()
    set_clock("2026-05-20T09:00:00Z")
    r1 = create_booked_ride(client["id"], kind="APPOINTMENT",
                            scheduled_pickup_at="2026-06-03T10:00:00Z")
    get_success_data(api_client.cancel_ride(
        r1["id"], {"cancel_note": "rescheduled"}, make_client_headers(client["id"])))
    resp = api_client.create_ride(
        {"client_id": client["id"], "kind": "GROCERY",
         "scheduled_pickup_at": "2026-06-03T13:00:00Z",
         "estimated_duration_minutes": 45, "estimated_distance_miles": 10,
         "origin_zone": "north", "linked_return_ride_id": r1["id"]},
        make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_RETURN_LINK_MISMATCH)


def test_raise_dispute_on_draft_invoice_returns_action_invalid(api):
    """PRD §3.9: "raising is only meaningful against an invoice in `ISSUED` or
    `PARTIALLY_PAID` with dispute dimension `NONE`, and any other combination
    is `ERR_DISPUTE_ACTION_INVALID`."

    Design: Corner/validations/raise_dispute_on_draft_invoice_returns_action_invalid
    """
    create_active_rate_card()
    client = create_client()
    invoice, _ = create_late_cancel_invoice(
        client["id"], "2026-05-04T12:00:00Z", "2026-05-04T16:00:00Z",
        "2026-05-01", "2026-05-08", issue=False)
    assert invoice["issuance_status"] == "DRAFT"
    resp = api_client.invoice_dispute_event(
        invoice["id"], {"action": "RAISE"}, make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_ACTION_INVALID)
