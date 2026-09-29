"""Reserve money and replacement units are conserved across approve, fulfil and
revoke with zero drift."""

from test_helpers import (
    approve_claim,
    assert_reserve_ledger,
    assert_unit_ledger,
    fulfill_claim,
    make_warranty_administrator_headers,
    read_claim,
    read_program,
    read_sku,
    revoke_claim,
    setup_released_lot,
    setup_warranty_scenario,
)

WA_1 = make_warranty_administrator_headers("wa-1")

REPLACEMENT_LINES = (
    {"component_code": "HANDLE", "component_list_price_cents": 1099, "quantity": 1},
    {"component_code": "HEAD", "component_list_price_cents": 2599, "quantity": 1},
    {"component_code": "PIN", "component_list_price_cents": 755, "quantity": 3},
)
EXPECTED_CHARGE_CENTS = 3696
EXPECTED_REPLACEMENT_UNITS = 5
FUNDED_CENTS = 5_000_000
SHIPMENT_REF = "UPS-1Z-0001"


def _released_lot_and_open_claim():
    """A CERTIFIED lot released into finished stock, then a funded programme and a
    three-line claim hung off the same SKU."""
    lot_ctx = setup_released_lot()
    ctx = setup_warranty_scenario(sku_id=lot_ctx["sku"]["id"], lines=REPLACEMENT_LINES)
    ctx["lot"] = lot_ctx["lot"]
    return ctx


# ---------------------------------------------------------------------------
# Reserve money
# ---------------------------------------------------------------------------


def test_approval_debits_the_reserve_by_exactly_the_frozen_charge():
    """A 3696 cent charge against a 5,000,000 cent pot leaves 4,996,304 cents and
    the money identity closes on the nose.

    PRD §3.8: "On the programme, `reserve_balance_cents` is recomputed as the
    funded amount less the charges of all claims now in `APPROVED` or `FULFILLED`
    status, and the programme's `version` increments."

    Design: Difficulty/compensating_invariant/warranty_reserve_money_conserved_across_approve_revoke
    """
    ctx = _released_lot_and_open_claim()
    assert ctx["claim"]["reserve_charge_cents"] == EXPECTED_CHARGE_CENTS
    assert read_program(ctx["program"]["id"])["reserve_balance_cents"] == FUNDED_CENTS

    approved = approve_claim(ctx["claim"]["id"], ctx["program"]["id"], WA_1)
    assert approved["status"] == "APPROVED"

    program = read_program(ctx["program"]["id"])
    assert program["reserve_balance_cents"] == 4_996_304
    assert FUNDED_CENTS == program["reserve_balance_cents"] + EXPECTED_CHARGE_CENTS
    assert program["open_hold_count"] == 0
    assert_reserve_ledger(program, [read_claim(ctx["claim"]["id"])])


def test_revoking_an_approved_claim_returns_the_reserve_to_its_pre_approval_value():
    """The charge stays frozen on the revoked row for audit, but it leaves the
    counted set, so the balance comes back to exactly 5,000,000 cents.

    PRD §2.9: "Because a revoked claim keeps its frozen charge on the row for
    audit while leaving the charged set, an approve-then-revoke pair returns the
    balance to exactly its pre-approval value with zero drift."

    Design: Difficulty/compensating_invariant/warranty_reserve_money_conserved_across_approve_revoke
    """
    ctx = _released_lot_and_open_claim()
    approve_claim(ctx["claim"]["id"], ctx["program"]["id"], WA_1)
    assert read_program(ctx["program"]["id"])["reserve_balance_cents"] == 4_996_304

    revoked = revoke_claim(
        ctx["claim"]["id"], WA_1, revocation_reason="Serial traced to a counterfeit distributor"
    )

    assert revoked["status"] == "REVOKED"
    assert revoked["reserve_charge_cents"] == EXPECTED_CHARGE_CENTS

    program = read_program(ctx["program"]["id"])
    assert program["reserve_balance_cents"] == FUNDED_CENTS
    assert program["reserve_funded_cents"] == FUNDED_CENTS
    assert program["open_hold_count"] == 0
    assert_reserve_ledger(program, [revoked])


# ---------------------------------------------------------------------------
# Physical replacement units
# ---------------------------------------------------------------------------


def test_a_released_lot_banks_its_units_on_hand():
    """Releasing a 500 unit lot credits the SKU's replacement pool and the unit
    identity closes with everything on hand.

    PRD §3.5: "Release sets `disposition` to `RELEASED`, adds the lot's
    `unit_count` to the SKU's `units_received_total`, recomputes `units_on_hand`
    from the unit ledger, and increments both the SKU's `version` and the lot's
    `version`."

    Design: Difficulty/compensating_invariant/replacement_unit_count_conserved_across_approve_fulfill_revoke
    """
    ctx = _released_lot_and_open_claim()
    sku = read_sku(ctx["sku"]["id"])

    assert ctx["lot"]["disposition"] == "RELEASED"
    assert sku["units_received_total"] == 500
    assert sku["units_on_hand"] == 500
    assert sku["units_reserved"] == 0
    assert sku["units_shipped"] == 0
    assert ctx["claim"]["replacement_unit_count"] == EXPECTED_REPLACEMENT_UNITS
    assert_unit_ledger(sku)


def test_approval_moves_replacement_units_from_on_hand_into_reserved():
    """Five units are set aside for the claim; the received total never moves.

    PRD §3.8: "On the SKU, `replacement_unit_count` units move out of
    `units_on_hand` and into `units_reserved`, and the SKU's `version`
    increments."

    Design: Difficulty/compensating_invariant/replacement_unit_count_conserved_across_approve_fulfill_revoke
    """
    ctx = _released_lot_and_open_claim()

    approve_claim(ctx["claim"]["id"], ctx["program"]["id"], WA_1)

    sku = read_sku(ctx["sku"]["id"])
    assert sku["units_received_total"] == 500
    assert sku["units_on_hand"] == 495
    assert sku["units_reserved"] == 5
    assert sku["units_shipped"] == 0
    assert_unit_ledger(sku)


def test_fulfilment_moves_the_reserved_units_into_shipped():
    """Shipping the replacement empties the reserved bucket without touching the
    reserve balance, because the money really was spent.

    PRD §3.8: "The claim moves `APPROVED → FULFILLED`, `replacement_unit_count`
    units move out of `units_reserved` and into `units_shipped` with a SKU
    `version` increment, and the claim's `version` increments."

    Design: Difficulty/compensating_invariant/replacement_unit_count_conserved_across_approve_fulfill_revoke
    """
    ctx = _released_lot_and_open_claim()
    approve_claim(ctx["claim"]["id"], ctx["program"]["id"], WA_1)

    fulfilled = fulfill_claim(ctx["claim"]["id"], WA_1, shipment_ref=SHIPMENT_REF)

    assert fulfilled["status"] == "FULFILLED"
    assert fulfilled["shipment_ref"] == SHIPMENT_REF

    sku = read_sku(ctx["sku"]["id"])
    assert sku["units_received_total"] == 500
    assert sku["units_on_hand"] == 495
    assert sku["units_reserved"] == 0
    assert sku["units_shipped"] == 5
    assert_unit_ledger(sku)
    assert read_program(ctx["program"]["id"])["reserve_balance_cents"] == 4_996_304


def test_revoking_a_fulfilled_claim_writes_the_shipped_units_back_on_hand():
    """The whole approve-fulfil-revoke arc returns all 500 units to on-hand while
    the shipment reference stays on the row as audit history.

    PRD §3.8: "Revoking a `FULFILLED` claim moves them out of `units_shipped` and
    back into `units_on_hand`, because the goods shipped and are being written
    back."

    Design: Difficulty/compensating_invariant/replacement_unit_count_conserved_across_approve_fulfill_revoke
    """
    ctx = _released_lot_and_open_claim()
    approve_claim(ctx["claim"]["id"], ctx["program"]["id"], WA_1)
    fulfill_claim(ctx["claim"]["id"], WA_1, shipment_ref=SHIPMENT_REF)

    revoked = revoke_claim(
        ctx["claim"]["id"], WA_1, revocation_reason="Serial traced to a counterfeit distributor"
    )

    assert revoked["status"] == "REVOKED"
    assert revoked["shipment_ref"] == SHIPMENT_REF
    assert revoked["replacement_unit_count"] == EXPECTED_REPLACEMENT_UNITS

    sku = read_sku(ctx["sku"]["id"])
    assert sku["units_received_total"] == 500
    assert sku["units_on_hand"] == 500
    assert sku["units_reserved"] == 0
    assert sku["units_shipped"] == 0
    assert_unit_ledger(sku)
