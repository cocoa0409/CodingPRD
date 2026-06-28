"""Dues proration, payment posting, and the dues-driven member lifecycle."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_council,
    create_troop,
    create_member,
    create_council_and_troop,
    create_dues_invoice_payload,
    create_payment_payload,
)

REG = TEST_USERS["registrar_headers"]
LEAD = TEST_USERS["leader_headers"]


def test_dues_proration_youth_vs_adult_same_month(api):
    """PRD §3.3: "a youth member uses the council's youth_dues_cents and an adult
    member uses the council's adult_dues_cents."
    PRD §3.3: "Otherwise the invoice amount is the base multiplied by the months
    remaining and divided by twelve, with that single proration product rounded
    half-up to a whole number of cents."

    Design: Difficulty/dual_variant_calc/dues_proration_youth_vs_adult_rate
    """
    council = create_council(youth_dues_cents=12000, adult_dues_cents=4500, program_year=2026)
    troop = create_troop(council["id"], unit_number="U-101")
    youth = create_member(troop["id"], member_type="YOUTH", full_name="Y One", birthdate="2014-05-01")
    adult = create_member(troop["id"], member_type="ADULT", full_name="A One", birthdate="1985-05-01")

    youth_inv = validate_success(
        api.create_dues_invoice(youth["id"], create_dues_invoice_payload(issued_on="2026-06-15"), LEAD), 201
    )
    adult_inv = validate_success(
        api.create_dues_invoice(adult["id"], create_dues_invoice_payload(issued_on="2026-06-15"), LEAD), 201
    )

    # June -> months_remaining = 12-(6-1) = 7 (< 9, prorated).
    assert youth_inv["amount_cents"] == 7000, f"youth: expected 7000, got {youth_inv['amount_cents']}"
    assert adult_inv["amount_cents"] == 2625, f"adult: expected 2625, got {adult_inv['amount_cents']}"
    assert youth_inv["amount_cents"] != adult_inv["amount_cents"]


def test_dues_proration_youth_rate_variant_value(api):
    """PRD §3.3: "a youth member uses the council's youth_dues_cents and an adult
    member uses the council's adult_dues_cents."
    PRD §3.3: "Otherwise the invoice amount is the base multiplied by the months
    remaining and divided by twelve, with that single proration product rounded
    half-up to a whole number of cents."

    Design: Difficulty/dual_variant_calc/dues_proration_youth_vs_adult_rate
    """
    council = create_council(youth_dues_cents=12000, adult_dues_cents=4500)
    troop = create_troop(council["id"], unit_number="U-101y")
    youth = create_member(troop["id"], member_type="YOUTH", full_name="Y One")

    inv = validate_success(
        api.create_dues_invoice(youth["id"], create_dues_invoice_payload(issued_on="2026-06-15"), LEAD), 201
    )
    assert inv["amount_cents"] == 7000, f"youth June proration: expected 7000, got {inv['amount_cents']}"


def test_dues_full_months_threshold_april_charges_full(api):
    """PRD §3.3: "There is a full-dues floor of nine months: if the months
    remaining are at least nine, the full base amount is charged with no proration
    discount."

    Design: Difficulty/boundary_precision_check/dues_full_months_threshold_boundary
    """
    council = create_council(youth_dues_cents=12000)
    troop = create_troop(council["id"], unit_number="U-1201")
    youth = create_member(troop["id"], member_type="YOUTH", full_name="Apr Youth")

    # April -> months_remaining = 12-(4-1) = 9 (>= 9, full dues).
    inv = validate_success(
        api.create_dues_invoice(youth["id"], create_dues_invoice_payload(issued_on="2026-04-15"), LEAD), 201
    )
    assert inv["amount_cents"] == 12000, f"April: expected full 12000, got {inv['amount_cents']}"


def test_dues_just_below_full_months_threshold_prorates(api):
    """PRD §3.3: "the system determines the number of whole months remaining in
    the program year through December: this equals twelve minus one less than the
    month number of issued_on."
    PRD §3.3: "Otherwise the invoice amount is the base multiplied by the months
    remaining and divided by twelve, with that single proration product rounded
    half-up to a whole number of cents."

    Design: Difficulty/boundary_precision_check/dues_full_months_threshold_boundary
    """
    council = create_council(youth_dues_cents=12000)
    troop = create_troop(council["id"], unit_number="U-1202")
    youth = create_member(troop["id"], member_type="YOUTH", full_name="May Youth")

    # May -> months_remaining = 12-(5-1) = 8 (< 9, prorated) -> 12000*8/12 = 8000.
    inv = validate_success(
        api.create_dues_invoice(youth["id"], create_dues_invoice_payload(issued_on="2026-05-15"), LEAD), 201
    )
    assert inv["amount_cents"] == 8000, f"May: expected 8000, got {inv['amount_cents']}"


def test_payment_cascade_pays_invoice_registers_youth_bumps_troop_count(api):
    """PRD §3.2: "When the cumulative posted payment amount against a member's OPEN
    invoice reaches or exceeds that invoice's amount, the system itself flips the
    invoice to PAID, advances the member's registration_status from PENDING to
    REGISTERED, and — because a youth's registration changes the troop's head count
    — recomputes the troop's registered_youth_count and recharter_posture."

    Design: Difficulty/transitive_cascade/payment_paid_registered_troop_posture_depth3
    """
    council, troop = create_council_and_troop(
        council_overrides={"youth_dues_cents": 12000}, troop_overrides={"unit_number": "U-701"}
    )
    youth = create_member(troop["id"], member_type="YOUTH", full_name="Cas Youth")
    inv = get_success_data(
        api.create_dues_invoice(youth["id"], create_dues_invoice_payload(issued_on="2026-01-01"), REG)
    )
    assert inv["amount_cents"] == 12000

    validate_success(api.create_payment(create_payment_payload(inv["id"], youth["id"], 12000), REG), 201)

    inv_after = validate_success(api.get_dues_invoice(inv["id"], REG), 200)
    member_after = validate_success(api.get_member(youth["id"], REG), 200)
    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)

    assert inv_after["status"] == "PAID"
    assert member_after["registration_status"] == "REGISTERED"
    assert troop_after["registered_youth_count"] == 1


def test_payment_cascade_full_payment_settles_and_registers(api):
    """PRD §3.3: "When the cumulative posted total reaches or exceeds the invoice
    amount, the invoice is settled to PAID and the member's registration advances
    as described in §3.2, with the owning troop recomputed."

    Design: Difficulty/transitive_cascade/payment_paid_registered_troop_posture_depth3
    """
    council, troop = create_council_and_troop(
        council_overrides={"youth_dues_cents": 12000}, troop_overrides={"unit_number": "U-701b"}
    )
    youth = create_member(troop["id"], member_type="YOUTH", full_name="Cas Youth 2")
    inv = get_success_data(
        api.create_dues_invoice(youth["id"], create_dues_invoice_payload(issued_on="2026-01-01"), REG)
    )

    validate_success(api.create_payment(create_payment_payload(inv["id"], youth["id"], 12000), REG), 201)

    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)
    member_after = validate_success(api.get_member(youth["id"], REG), 200)
    assert member_after["registration_status"] == "REGISTERED"
    assert troop_after["registered_youth_count"] == 1


def test_overpayment_rejected(api):
    """PRD §3.3: "A payment may not push the cumulative posted total for that
    invoice above the invoice's amount_cents; an overpayment is rejected with
    ERR_OVERPAYMENT."

    Design: Corner/validations/overpayment_rejected
    """
    council, troop = create_council_and_troop(
        council_overrides={"youth_dues_cents": 12000}, troop_overrides={"unit_number": "V-1"}
    )
    youth = create_member(troop["id"], member_type="YOUTH", full_name="Op Y")
    inv = get_success_data(
        api.create_dues_invoice(youth["id"], create_dues_invoice_payload(issued_on="2026-01-01"), REG)
    )
    assert inv["amount_cents"] == 12000

    resp = api.create_payment(create_payment_payload(inv["id"], youth["id"], 12001), REG)
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)


def test_computed_troop_dues_account_after_payment(api):
    """PRD §2.5: "The dues_account_cents is the troop's held dues balance, computed
    as the sum of amount_cents across every FundLedgerEntry whose account is
    TROOP_DUES and whose troop_id matches the troop."
    PRD §3.3: "Posting a payment ... immediately writes a FundLedgerEntry crediting
    the payment's amount_cents into TROOP_DUES with a source_kind of PAYMENT."

    Design: Corner/entities/computed_council_fund_balance_after_payment
    """
    council, troop = create_council_and_troop(
        council_overrides={"youth_dues_cents": 12000}, troop_overrides={"unit_number": "U-D"}
    )
    youth = create_member(troop["id"], member_type="YOUTH", full_name="Pay Youth")
    inv = get_success_data(
        api.create_dues_invoice(youth["id"], create_dues_invoice_payload(issued_on="2026-01-01"), REG)
    )
    validate_success(api.create_payment(create_payment_payload(inv["id"], youth["id"], 12000), REG), 201)

    troop_after = validate_success(api.get_troop(troop["id"], REG), 200)
    assert troop_after["dues_account_cents"] == 12000


def test_troop_ledger_subresource_returns_troop_dues_entry(api):
    """PRD §3.9: "A troop-scoped ledger read is available to both roles and returns
    the FundLedgerEntry rows routed to that troop, optionally narrowed by account."

    Design: Corner/endpoints/troop_ledger_subresource_returns_entries
    """
    council, troop = create_council_and_troop(
        council_overrides={"youth_dues_cents": 12000}, troop_overrides={"unit_number": "E-1"}
    )
    youth = create_member(troop["id"], member_type="YOUTH", full_name="E Youth")
    inv = get_success_data(
        api.create_dues_invoice(youth["id"], create_dues_invoice_payload(issued_on="2026-01-01"), REG)
    )
    validate_success(api.create_payment(create_payment_payload(inv["id"], youth["id"], 12000), REG), 201)

    resp = api.list_troop_ledger(troop["id"], REG, params={"account": "TROOP_DUES"})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected 1 TROOP_DUES entry, got {meta['total_count']}"
