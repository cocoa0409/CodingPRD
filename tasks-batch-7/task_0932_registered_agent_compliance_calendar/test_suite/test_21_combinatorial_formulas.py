"""Nested rounding in the allocation split, and the pre-insert volume discount."""
from test_helpers import (
    ADMIN,
    DE_RULE_FULL,
    assert_allocation_split,
    assert_payment_identity,
    capture,
    draft_standalone_filing,
    new_obligation,
    new_payment,
    read_client,
    read_filing,
    read_payment,
    setup_active_home_registration,
    validate_paginated,
)

SHARE_FACTS = {
    "authorized_shares": 8000,
    "issued_shares": 4000,
    "total_gross_assets_cents": 12000000,
}


def _dissolution_scene():
    """An ACTIVE Delaware registration, a DRAFT dissolution filing whose two portions
    are both exactly 4900, and a payment authorized for one cent over half of it."""
    scene = setup_active_home_registration(
        DE_RULE_FULL, entity_overrides=dict(SHARE_FACTS)
    )
    scene["filing"] = draft_standalone_filing(
        scene["registration"]["id"], "DISSOLUTION", expedite_tier="NONE"
    )
    scene["payment"] = new_payment(scene["client"]["id"], 4901)
    return scene


def _six_obligation_scene():
    """An ACTIVE Delaware registration carrying five open obligations."""
    scene = setup_active_home_registration(
        DE_RULE_FULL, entity_overrides=dict(SHARE_FACTS)
    )
    registration_id = scene["registration"]["id"]
    new_obligation(registration_id, "ANNUAL_REPORT", 2027)
    new_obligation(registration_id, "FRANCHISE_TAX", 2027)
    new_obligation(registration_id, "ANNUAL_REPORT", 2028)
    new_obligation(registration_id, "FRANCHISE_TAX", 2028)
    scene["fifth"] = new_obligation(registration_id, "ANNUAL_REPORT", 2029)
    return scene


def test_allocation_rounds_the_state_half_first_and_takes_the_service_remainder(api):
    """PRD §3.8: "The row's `state_portion_cents` is the amount placed multiplied by the
    filing's `state_portion_cents` and divided by the filing's `total_fee_cents`,
    rounded half up to a whole cent; its `service_portion_cents` is then the amount
    placed **minus** that state portion."
    PRD §2.7: "On every `PaymentAllocation` row, `state_portion_cents` and
    `service_portion_cents` sum to exactly `amount_cents`. This is what forces the
    pinned rounding order described in Section 3.8: the state portion is rounded and the
    service portion takes the remainder, rather than both being rounded independently."

    Design: Difficulty/combinatorial_formula/allocation_split_rounds_state_portion_first_then_remainder
    """
    scene = _dissolution_scene()

    capture(scene["payment"]["id"], 4901, scene["filing"]["id"])

    rows, meta = validate_paginated(
        api.list_payment_allocations(scene["payment"]["id"], ADMIN)
    )
    assert meta["total_count"] == 1
    row = rows[0]
    assert row["amount_cents"] == 4901
    # 4901 * 4900 / 9800 = 2450.5, which rounds half up to 2451; the service half is
    # the remainder 4901 - 2451 = 2450. Rounding both halves independently would give
    # 2451 + 2451 = 4902 and break the split identity by one cent.
    assert row["state_portion_cents"] == 2451
    assert row["service_portion_cents"] == 2450
    assert_allocation_split(row)
    assert row["sequence_index"] == 0
    assert row["is_reversal"] is False


def test_the_partly_funded_filing_and_its_payment_still_balance(api):
    """PRD §3.7: "For a standalone filing, `state_fee_cents` comes from the jurisdiction
    rule by kind: `foreign_qualification_fee_cents` for a `FOREIGN_QUALIFICATION`,
    `withdrawal_fee_cents` for a `WITHDRAWAL`, `dissolution_fee_cents` for a
    `DISSOLUTION`, and for a `REINSTATEMENT` the `back_fee_total_cents` already assessed
    on the reinstatement case; and `service_fee_cents` is the base service charge of
    4900 cents."
    PRD §3.7: "a single filing read exposes its full refundability split alongside
    `paid_amount_cents`, which is at all times the net sum of the `amount_cents` of
    every allocation row pointing at it, reversal rows included as negatives."
    PRD §2.7: "For every `Payment`, `captured_amount_cents` equals the sum of
    `allocated_amount_cents`, `unallocated_amount_cents` and `refunded_amount_cents`, as
    exact integers with no tolerance."

    Design: Difficulty/combinatorial_formula/allocation_split_rounds_state_portion_first_then_remainder
    """
    scene = _dissolution_scene()

    capture(scene["payment"]["id"], 4901, scene["filing"]["id"])

    filing = read_filing(scene["filing"]["id"])
    # dissolution_fee_cents 4900 with no expedite, plus the 4900 base service charge.
    assert filing["state_portion_cents"] == 4900
    assert filing["service_portion_cents"] == 4900
    assert filing["total_fee_cents"] == 9800
    assert filing["paid_amount_cents"] == 4901

    payment = read_payment(scene["payment"]["id"])
    assert payment["captured_amount_cents"] == 4901
    assert payment["allocated_amount_cents"] == 4901
    assert payment["unallocated_amount_cents"] == 0
    assert_payment_identity(payment)


def test_the_sixth_obligation_earns_the_volume_discount_the_fifth_did_not(api):
    """PRD §3.5: "the server counts the client's compliance obligations in one of the
    four open statuses — `SCHEDULED`, `DUE_SOON`, `IN_GRACE` or `DELINQUENT` — across
    every registration of every one of the client's legal entities, **measured before
    the new row is inserted**, and applies the discount when that count is 5 or more."
    PRD §3.5: "The discount itself is 4900 multiplied by 1500 and divided by 10000,
    rounded half up, which is exactly 735 cents, so the discounted service fee is
    exactly 4165 cents and the undiscounted fee is 4900 cents."

    Design: Difficulty/combinatorial_formula/service_fee_volume_discount_uses_pre_insert_open_count
    """
    scene = _six_obligation_scene()

    sixth = new_obligation(scene["registration"]["id"], "FRANCHISE_TAX", 2029)

    # The fifth row saw a prior open count of 4 and paid the undiscounted fee.
    assert scene["fifth"]["service_fee_cents"] == 4900
    # The sixth row saw a prior open count of 5 and earned the discount.
    assert sixth["service_fee_cents"] == 4165


def test_the_discount_flows_through_to_the_total_and_the_client_rollup(api):
    """PRD §3.5: "`total_due_cents` is `state_fee_cents` plus `franchise_tax_cents` plus
    `late_fee_cents` plus `service_fee_cents`."
    PRD §2.11: "`portfolio_open_obligation_count` is the number of obligations in one of
    the four open statuses across every registration of every legal entity of the
    client; `portfolio_outstanding_cents` is the sum of `total_due_cents` over exactly
    those same rows; and `portfolio_entity_count` is the number of the client's legal
    entities whose `lifecycle_status` is anything other than `DISSOLVED`."

    Design: Difficulty/combinatorial_formula/service_fee_volume_discount_uses_pre_insert_open_count
    """
    scene = _six_obligation_scene()

    sixth = new_obligation(scene["registration"]["id"], "FRANCHISE_TAX", 2029)

    # Fifth row: 5000 annual-report fee + 0 tax + 0 late + 4900 service = 9900.
    assert scene["fifth"]["total_due_cents"] == 9900
    # Sixth row: 5000 franchise-tax filing fee + 25000 tier tax + 0 late + 4165 = 34165.
    assert sixth["total_due_cents"] == 34165

    client = read_client(scene["client"]["id"])
    assert client["portfolio_open_obligation_count"] == 6
    # 9900 (AR27) + 34900 (FT27) + 9900 (AR28) + 34900 (FT28) + 9900 (AR29) +
    # 34165 (FT29) = 133665.
    assert client["portfolio_outstanding_cents"] == 133665
