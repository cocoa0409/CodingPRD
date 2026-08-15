"""Payment waterfall claims: dual-variant class order, intra-class due_date
ordering, and the created_at tie-break (PRD 3.3)."""
from test_helpers import (
    add_charge,
    create_property_payload,
    create_tenant_payload,
    create_lease_payload,
    list_allocations,
    list_charges,
    record_and_post_payment,
    setup_property_tenant_lease,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]


def _charges_by_id(lease_id):
    return {c["id"]: c for c in list_charges(lease_id)}


def test_waterfall_fees_first_split(api):
    """PRD 3.3: "The property's `posting_priority_policy` fixes the class order: under
    `FEES_FIRST`, every charge of kind `LATE_FEE`, `NSF_FEE`, `PLAN_SETUP_FEE`, and
    `DAMAGE_FEE` is paid to zero before any cent reaches a `RENT` charge; under
    `RENT_FIRST`, rent charges are paid first and the fee classes follow."

    Design: Difficulty/dual_variant_calc/waterfall_fees_first_vs_rent_first
    """
    ctx = setup_property_tenant_lease(property_overrides={"posting_priority_policy": "FEES_FIRST"})
    lease_id = ctx["lease"]["id"]
    rent = add_charge(lease_id, amount_cents=200000)
    damage = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)
    payment = record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=100000)

    charges = _charges_by_id(lease_id)
    assert charges[damage["id"]]["outstanding_cents"] == 0
    assert charges[damage["id"]]["status"] == "PAID"
    assert charges[rent["id"]]["outstanding_cents"] == 110000
    assert charges[rent["id"]]["status"] == "PARTIALLY_PAID"

    allocs = sorted(list_allocations(params={"payment_id": payment["id"]}), key=lambda a: a["allocation_order"])
    assert [(a["charge_id"], a["amount_cents"], a["allocation_order"]) for a in allocs] == [
        (damage["id"], 10000, 1),
        (rent["id"], 90000, 2),
    ]


def test_waterfall_rent_first_split(api):
    """PRD 3.3: "The property's `posting_priority_policy` fixes the class order: under
    `FEES_FIRST`, every charge of kind `LATE_FEE`, `NSF_FEE`, `PLAN_SETUP_FEE`, and
    `DAMAGE_FEE` is paid to zero before any cent reaches a `RENT` charge; under
    `RENT_FIRST`, rent charges are paid first and the fee classes follow. The two
    variants are not cosmetic — an identical payment posted against an identical ledger
    produces a different per-charge split under the two policies."

    Design: Difficulty/dual_variant_calc/waterfall_fees_first_vs_rent_first
    """
    ctx = setup_property_tenant_lease(property_overrides={"posting_priority_policy": "RENT_FIRST"})
    lease_id = ctx["lease"]["id"]
    rent = add_charge(lease_id, amount_cents=200000)
    damage = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=10000)
    payment = record_and_post_payment(lease_id, ctx["tenant"]["id"], channel="ACH", amount_cents=100000)

    charges = _charges_by_id(lease_id)
    assert charges[rent["id"]]["outstanding_cents"] == 100000
    assert charges[rent["id"]]["status"] == "PARTIALLY_PAID"
    assert charges[damage["id"]]["outstanding_cents"] == 10000
    assert charges[damage["id"]]["status"] == "OPEN"

    allocs = list_allocations(params={"payment_id": payment["id"]})
    assert len(allocs) == 1
    assert allocs[0]["charge_id"] == rent["id"]
    assert allocs[0]["amount_cents"] == 100000
    assert allocs[0]["allocation_order"] == 1


def test_waterfall_due_date_order_within_fee_class(api):
    """PRD 3.3: "Within a class, charges are ordered by `due_date` ascending, then by
    `created_at` ascending as the tie-break; identifiers are never consulted for
    ordering. The waterfall walks that order, allocating to each charge the lesser of
    the remaining payment money and that charge's outstanding balance, and stops the
    moment no payment money remains."

    Design: Corner/calculations/waterfall_due_date_order_within_fee_class
    """
    ctx = setup_property_tenant_lease(property_overrides={"min_partial_payment_percent": 1})
    lease_id = ctx["lease"]["id"]
    rent = add_charge(lease_id, amount_cents=200000)
    fee_early = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=3000, due_date="2026-08-01")
    fee_late = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=4000, due_date="2026-08-02")
    payment = record_and_post_payment(
        lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=4000, received_date="2026-08-03"
    )

    allocs = sorted(list_allocations(params={"payment_id": payment["id"]}), key=lambda a: a["allocation_order"])
    assert [(a["charge_id"], a["amount_cents"]) for a in allocs] == [
        (fee_early["id"], 3000),
        (fee_late["id"], 1000),
    ]
    charges = _charges_by_id(lease_id)
    assert charges[fee_early["id"]]["status"] == "PAID" and charges[fee_early["id"]]["outstanding_cents"] == 0
    assert charges[fee_late["id"]]["status"] == "PARTIALLY_PAID" and charges[fee_late["id"]]["outstanding_cents"] == 3000
    assert charges[rent["id"]]["status"] == "OPEN" and charges[rent["id"]]["outstanding_cents"] == 200000


def test_waterfall_created_at_tiebreak(api):
    """PRD 3.3: "Within a class, charges are ordered by `due_date` ascending, then by
    `created_at` ascending as the tie-break; identifiers are never consulted for
    ordering."

    Design: Corner/calculations/waterfall_created_at_tiebreak
    """
    ctx = setup_property_tenant_lease(property_overrides={"min_partial_payment_percent": 1})
    lease_id = ctx["lease"]["id"]
    first = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=3000, due_date="2026-08-05")
    second = add_charge(lease_id, kind="DAMAGE_FEE", amount_cents=3000, due_date="2026-08-05")
    payment = record_and_post_payment(
        lease_id, ctx["tenant"]["id"], channel="CARD", amount_cents=3000, received_date="2026-08-05"
    )

    allocs = list_allocations(params={"payment_id": payment["id"]})
    assert len(allocs) == 1
    assert allocs[0]["charge_id"] == first["id"], (
        "The first-created charge must absorb the payment under the created_at tie-break"
    )
    assert allocs[0]["amount_cents"] == 3000
    assert allocs[0]["allocation_order"] == 1

    charges = _charges_by_id(lease_id)
    assert charges[second["id"]]["status"] == "OPEN"
    assert charges[second["id"]]["outstanding_cents"] == 3000
