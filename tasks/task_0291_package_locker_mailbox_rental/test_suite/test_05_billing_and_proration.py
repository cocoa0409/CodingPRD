"""Invoicing, autopay cascade, proration, and payment rules.

Covers difficulty instances for the dual-variant refund, the depth-3 autopay
cascade, and the conserved invoice balance; plus corner instances for the payment
gate, the reactivation balance gate, immediate charge visibility, the clock guard,
and the forward-without-destination case.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_facility_operator_headers,
    setup_active_agreement, setup_agreement_with_forwarding,
    receive_and_notify_package, create_mail_item, advance_clock,
    get_open_invoice, find_ledger_entries,
)

OP = make_facility_operator_headers()


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / refund_chronological_diverges_from_forward_looking_on_agreement
# ---------------------------------------------------------------------------
def test_refund_chronological_diverges_from_forward_looking_on_agreement(api):
    """PRD §3.7: "The chronological refund, which is the variant actually posted as
    the PRORATED_REFUND credit, is the rental charge multiplied by the unused
    fraction — that is, the rental charge times (term days minus used days), divided
    by term days, with the division performed before a single round-half-up to whole
    cents at the very end."
    PRD §3.7: "The forward-looking figure refunds only whole unused months: it is
    monthly_fee_cents multiplied by the months remaining, where the months remaining
    is term_months minus the used days rounded up to a whole number of months (the
    used days divided by 30, rounded up), and never less than zero."

    Design: Difficulty/dual_variant_calc/refund_chronological_diverges_from_forward_looking_on_agreement
    """
    # monthly 3000, term 3 -> term_days 90, paid 9000. close at used_days 20.
    # chronological = round(9000*(90-20)/90) = round(7000.0) = 7000
    # forward_looking = 3000 * (3 - ceil(20/30)) = 3000 * (3-1) = 6000
    s = setup_active_agreement(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                               term_months=3, autopay_enabled=False, with_locker=False, name="F2")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]
    advance_clock(fac_id, "2026-06-21T00:00:00.000Z")  # used 20 days

    quote = validate_success(api.refund_quote(agr_id, OP))
    assert quote["chronological_refund_cents"] == 7000, "chronological refund at day 20 is 7000c"
    assert quote["forward_looking_refund_cents"] == 6000, "forward-looking refund at day 20 is 6000c"
    assert quote["chronological_refund_cents"] != quote["forward_looking_refund_cents"]

    validate_success(api.close_rental_agreement(agr_id, OP))
    inv = get_open_invoice(agr_id)
    body = api.list_ledger_entries(inv["id"], OP).json()
    refunds = find_ledger_entries(body["data"], reason="PRORATED_REFUND")
    assert len(refunds) == 1, "exactly one PRORATED_REFUND credit posts on close"
    assert refunds[0]["amount_cents"] == 7000, "the posted refund is the chronological 7000c"
    assert refunds[0]["kind"] == "CREDIT", "prorated refund is a CREDIT"
    # forward-looking (6000) is quote-only and must not be posted.
    assert not [e for e in refunds if e["amount_cents"] == 6000], "forward-looking 6000c is never posted"


def test_refund_quote_does_not_change_state(api):
    """PRD §3.7: "A what-if quote is also available without changing any state,
    returning both readings of the refund as chronological_refund_cents and
    forward_looking_refund_cents."

    Design: Difficulty/dual_variant_calc/refund_chronological_diverges_from_forward_looking_on_agreement
    """
    # autopay_enabled keeps the RENTAL charge captured at activation so the
    # balance stays at 0 (at/below the 5,000-cent suspension threshold). PRD §3.3
    # has the clock sweep suspend an ACTIVE agreement only when its balance climbs
    # past that threshold; with the balance at 0 the 20-day clock advance leaves
    # the agreement ACTIVE, isolating the refund-quote's no-op property under test.
    s = setup_active_agreement(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                               term_months=3, autopay_enabled=True, with_locker=False, name="F2b")
    agr_id = s["agreement"]["id"]
    advance_clock(s["facility"]["id"], "2026-06-21T00:00:00.000Z")
    validate_success(api.refund_quote(agr_id, OP))
    after = validate_success(api.get_rental_agreement(agr_id, OP))
    assert after["status"] == "ACTIVE", "refund-quote must not change the agreement state"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / pickup_charge_balance_autopay_depth3
# ---------------------------------------------------------------------------
def test_pickup_charge_balance_autopay_depth3(api):
    """PRD §3.6: "immediately after the charge posts and the balance is recomputed,
    if autopay is on and the invoice's balance_cents is greater than zero, the system
    creates a Payment for exactly that positive balance, with method CARD_AUTOPAY and
    status CAPTURED, after which the recomputed balance returns to zero."
    PRD §3.4: "the finalized overstay charge (if greater than zero) and the pinned
    oversize charge (if greater than zero) are posted to the agreement's invoice as
    CHARGE ledger entries with reasons OVERSTAY and OVERSIZE, raising the balance,
    after which the autopay cascade captures payment if autopay is enabled."

    Design: Difficulty/transitive_cascade/pickup_charge_balance_autopay_depth3
    """
    # autopay ON. RENTAL 9000 captured at activation -> balance 0.
    # OVERSIZE 610 + OVERSTAY 1500 = 2110 new charges -> autopay captures 2110 -> balance 0.
    s = setup_active_agreement(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                               term_months=3, autopay_enabled=True, with_locker=True,
                               locker_size="MEDIUM", name="F7")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]
    pkg = receive_and_notify_package(fac_id, agr_id, size_tier="MEDIUM",
                                     longest_dim_cm=72, weight_g=6200)
    advance_clock(fac_id, "2026-06-08T00:00:00.000Z")  # overstay -> 1500 at pickup
    v = validate_success(api.get_package(pkg["id"], OP))["version"]
    validate_success(api.pickup_package(
        pkg["id"], {"pickup_code": pkg["pickup_code"], "expected_package_version": v}, OP))

    inv = get_open_invoice(agr_id)
    inv = validate_success(api.get_invoice(inv["id"], OP))
    assert inv["balance_cents"] == 0, "autopay drives balance to 0 after the pickup charges"

    payments = api.list_payments(OP, params={"invoice_id": inv["id"]}).json()["data"]
    autopay = [p for p in payments if p["method"] == "CARD_AUTOPAY" and p["amount_cents"] == 2110]
    assert autopay, "an autopay CAPTURED payment of exactly 2110c (610+1500) must exist"
    assert autopay[0]["status"] == "CAPTURED"


def test_pickup_posts_oversize_and_overstay_charges_link1(api):
    """PRD §3.4: "the finalized overstay charge (if greater than zero) and the
    pinned oversize charge (if greater than zero) are posted to the agreement's
    invoice as CHARGE ledger entries with reasons OVERSTAY and OVERSIZE, raising the
    balance, after which the autopay cascade captures payment if autopay is enabled."

    Design: Difficulty/transitive_cascade/pickup_charge_balance_autopay_depth3
    """
    # Verifies the first link of the depth-3 chain: the OVERSIZE/OVERSTAY ledger
    # entries themselves (autopay ON so the balance lands at 0).
    s = setup_active_agreement(clock="2026-06-01T00:00:00.000Z", monthly_fee_cents=3000,
                               term_months=3, autopay_enabled=True, with_locker=True,
                               locker_size="MEDIUM", name="F7b")
    fac_id = s["facility"]["id"]
    agr_id = s["agreement"]["id"]
    pkg = receive_and_notify_package(fac_id, agr_id, size_tier="MEDIUM",
                                     longest_dim_cm=72, weight_g=6200)
    advance_clock(fac_id, "2026-06-08T00:00:00.000Z")
    v = validate_success(api.get_package(pkg["id"], OP))["version"]
    validate_success(api.pickup_package(
        pkg["id"], {"pickup_code": pkg["pickup_code"], "expected_package_version": v}, OP))

    inv = get_open_invoice(agr_id)
    body = api.list_ledger_entries(inv["id"], OP).json()
    oversize = find_ledger_entries(body["data"], reason="OVERSIZE", kind="CHARGE")
    overstay = find_ledger_entries(body["data"], reason="OVERSTAY", kind="CHARGE")
    assert len(oversize) == 1 and oversize[0]["amount_cents"] == 610, "OVERSIZE 610c charge posts"
    assert len(overstay) == 1 and overstay[0]["amount_cents"] == 1500, "OVERSTAY 1500c charge posts"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / invoice_balance_conserved_charge_then_payment
# ---------------------------------------------------------------------------
def test_invoice_balance_conserved_charge_then_payment(api):
    """PRD §3.7: "Completion moves the request REQUESTED → COMPLETED, drives the
    underlying mail item to FORWARDED when the kind is FORWARD or to SCANNED when the
    kind is SCAN, and posts a FORWARDING charge of the pinned fee_cents to the
    agreement's invoice, with autopay capturing afterward if enabled."
    PRD §3.6: "The balance_cents is charges_total_cents minus credits_total_cents
    minus payments_total_cents, and it may go negative, representing an overpayment
    credit."

    Design: Difficulty/compensating_invariant/invoice_balance_conserved_charge_then_payment
    """
    # RENTAL 3000 unpaid (autopay OFF). SCAN forwarding 150 charge -> 3150. Pay 150 -> 3000.
    s = setup_agreement_with_forwarding(kind="SCAN", mailbox_size="MEDIUM",
                                        monthly_fee_cents=3000, term_months=1, name="F18")
    agr_id = s["agreement"]["id"]
    inv = get_open_invoice(agr_id)

    validate_success(api.complete_forwarding_request(s["forwarding_request"]["id"], OP))
    mid = validate_success(api.get_invoice(inv["id"], OP))
    assert mid["balance_cents"] == 3150, "balance rises to 3150 after the 150c FORWARDING charge"

    validate_success(api.create_payment(
        {"invoice_id": inv["id"], "amount_cents": 150, "method": "CARD_MANUAL"}, OP),
        expected_status=201)
    final = validate_success(api.get_invoice(inv["id"], OP))
    assert final["balance_cents"] == 3000, "balance returns to the pre-charge 3000 (conserved)"


def test_payment_settles_invoice_and_zeroes_balance(api):
    """PRD §3.6: "payments_total_cents is the sum of amount_cents over every Payment
    on the invoice whose status is CAPTURED."
    PRD §3.6: "After any capture the invoice balance is recomputed, and the invoice
    moves to SETTLED once its balance is at or below zero."

    Design: Difficulty/compensating_invariant/invoice_balance_conserved_charge_then_payment
    """
    # RENTAL 3000 unpaid; a matching 3000 manual payment conserves the books to a
    # zero balance and settles the invoice.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               autopay_enabled=False, with_locker=False, name="F18b")
    inv = get_open_invoice(s["agreement"]["id"])
    validate_success(api.create_payment(
        {"invoice_id": inv["id"], "amount_cents": 3000, "method": "CARD_MANUAL"}, OP),
        expected_status=201)
    after = validate_success(api.get_invoice(inv["id"], OP))
    assert after["payments_total_cents"] == 3000, "payments_total reflects the captured payment"
    assert after["balance_cents"] == 0, "balance is conserved to 0 after the matching payment"
    assert after["status"] == "SETTLED", "invoice settles when balance reaches zero"


# ---------------------------------------------------------------------------
# Corner: validations / payment_exceeds_balance_returns_error
# ---------------------------------------------------------------------------
def test_payment_exceeds_balance_returns_error(api):
    """PRD §3.6: "A manual payment whose amount_cents exceeds the invoice's positive
    outstanding balance_cents is rejected with ERR_PAYMENT_EXCEEDS_BALANCE."

    Design: Corner/validations/payment_exceeds_balance_returns_error
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               autopay_enabled=False, with_locker=False, name="Depot")
    inv = get_open_invoice(s["agreement"]["id"])
    resp = api.create_payment({"invoice_id": inv["id"], "amount_cents": 5000, "method": "CASH"}, OP)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)


# ---------------------------------------------------------------------------
# Corner: validations / reactivate_blocked_by_high_balance
# ---------------------------------------------------------------------------
def test_reactivate_blocked_by_high_balance(api):
    """PRD §3.3: "Reactivation moves SUSPENDED → ACTIVE, but only when the invoice
    balance has been brought back to at or below that same 5,000-cent threshold; a
    reactivation attempted while the balance still exceeds the threshold is rejected
    with ERR_AGREEMENT_NOT_ACTIVE."

    Design: Corner/validations/reactivate_blocked_by_high_balance
    """
    # monthly 3000, 3 months -> RENTAL 9000 unpaid > 5000 threshold, autopay OFF.
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=3,
                               autopay_enabled=False, with_locker=False, name="Depot")
    agr_id = s["agreement"]["id"]
    validate_success(api.suspend_rental_agreement(agr_id, OP))
    resp = api.reactivate_rental_agreement(agr_id, OP)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value)
    after = validate_success(api.get_rental_agreement(agr_id, OP))
    assert after["status"] == "SUSPENDED", "agreement stays SUSPENDED when reactivate is blocked"


# ---------------------------------------------------------------------------
# Corner: consistency_model / immediate_visibility_of_charges_after_activate
# ---------------------------------------------------------------------------
def test_immediate_visibility_of_charges_after_activate(api):
    """PRD §3.3: "the system opens the agreement's single invoice and posts the first
    rental charge. That charge is a CHARGE ledger entry with reason RENTAL whose
    amount is monthly_fee_cents multiplied by term_months."

    Design: Corner/consistency_model/immediate_visibility_of_charges_after_activate
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               autopay_enabled=False, with_locker=False, name="Depot")
    inv = get_open_invoice(s["agreement"]["id"])
    inv = validate_success(api.get_invoice(inv["id"], OP))
    assert inv["charges_total_cents"] == 3000, "RENTAL charge visible immediately after activation"
    assert inv["balance_cents"] == 3000, "balance equals the unpaid RENTAL charge"


# ---------------------------------------------------------------------------
# Corner: calculations / clock_advance_backwards_rejected
# ---------------------------------------------------------------------------
def test_clock_advance_backwards_rejected(api):
    """PRD §2.6: "The advance request supplies a target instant as to_iso8601; the
    new instant must be greater than or equal to the facility's prior current_utc,
    and a request that would move the clock backward is rejected with
    ERR_INVALID_CLOCK (HTTP 422)."

    Design: Corner/calculations/clock_advance_backwards_rejected
    """
    fac = get_success_data(api.create_facility({"name": "Depot", "time_zone": "UTC"}, OP))
    get_success_data(api.advance_clock(fac["id"], {"to_iso8601": "2026-06-10T00:00:00.000Z"}, OP))
    resp = api.advance_clock(fac["id"], {"to_iso8601": "2026-06-05T00:00:00.000Z"}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_CLOCK.value)
    after = validate_success(api.get_facility(fac["id"], OP))
    assert after["current_utc"] == "2026-06-10T00:00:00.000Z", "current_utc unchanged after a backward attempt"


# ---------------------------------------------------------------------------
# Corner: validations / forward_kind_without_destination_returns_invalid_request
# ---------------------------------------------------------------------------
def test_forward_kind_without_destination_returns_invalid_request(api):
    """PRD §3.7: "A FORWARD request must supply a destination_address, which is
    required for forwarding and ignored for a scan; omitting it on a forward is the
    ERR_INVALID_REQUEST case noted in §2.10."

    Design: Corner/validations/forward_kind_without_destination_returns_invalid_request
    """
    s = setup_active_agreement(monthly_fee_cents=3000, term_months=1,
                               with_locker=False, name="Depot")
    mi = create_mail_item(s["facility"]["id"], s["agreement"]["id"])
    resp = api.create_forwarding_request({"mail_item_id": mi["id"], "kind": "FORWARD"}, OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
