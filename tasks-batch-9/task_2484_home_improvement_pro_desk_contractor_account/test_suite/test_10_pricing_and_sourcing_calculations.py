"""Pricing, sourcing and aggregate computations of the pro desk API."""

import pytest

from test_helpers import (
    CREDIT_MANAGER,
    PLATFORM_ADMIN,
    PRO_DESK_ASSOCIATE,
    SKU_MORTAR_BAG,
    SKU_SHINGLE_BUNDLE,
    ApiErrorId,
    api_client,
    create_credit_line,
    create_draft_order,
    create_pro_account,
    create_pro_account_payload,
    create_store,
    create_store_stock,
    file_tax_exempt_certificate,
    get_success_data,
    make_contractor_admin_headers,
    pay_order,
    read_credit_line,
    read_pro_account,
    read_pro_order,
    read_store_stock,
    request_return,
    set_clock,
    setup_fulfilled_will_call_order,
    setup_invoiced_will_call_order,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    verify_tax_exempt_certificate,
)


# --------------------------------------------------------------------------- #
# The tier ladder                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "baseline_volume_cents,expected_tier_code,expected_tier_discount_pct",
    [
        (4_999_999, "MEMBER", 0.00),
        (5_000_000, "GOLD", 0.05),
        (19_999_999, "GOLD", 0.05),
        (20_000_000, "PLATINUM", 0.08),
        (49_999_999, "PLATINUM", 0.08),
        (50_000_000, "DIAMOND", 0.12),
    ],
)
def test_account_tier_opens_inclusively_at_each_ladder_volume(
    baseline_volume_cents, expected_tier_code, expected_tier_discount_pct
):
    """PRD §2.9: "Remember that trailing volume is stored in cents, so the `GOLD` opening figure is five million cents, `PLATINUM`'s is twenty million cents and `DIAMOND`'s is fifty million cents."
    PRD §2.9: "Each opening figure is an **inclusive** lower bound: an account sitting exactly on a rung's opening volume qualifies for that rung."
    PRD §2.9: "The account's tier is the qualifying rung with the greatest opening volume, and the account's discount is that rung's discount."
    PRD §2.9: "**`MEMBER`** opens at zero trailing volume. It grants no discount, accrues no rebate, and permits quote terms of at most 15 days."
    PRD §2.9: "**`GOLD`** opens once trailing volume reaches fifty thousand dollars. It grants a 5 percent discount, accrues rebate at 1.0 percent of invoiced volume, and permits quote terms of at most 30 days."
    PRD §2.9: "**`PLATINUM`** opens once trailing volume reaches two hundred thousand dollars. It grants an 8 percent discount, accrues rebate at 2.0 percent, and permits quote terms of at most 60 days."
    PRD §2.9: "**`DIAMOND`** opens once trailing volume reaches five hundred thousand dollars. It grants a 12 percent discount, accrues rebate at 3.0 percent, and permits quote terms of at most 90 days."
    PRD §3.2: "`baseline_volume_cents`, a non-negative integer defaulting to 0, is trailing volume carried over from the legacy system and is always counted in the trailing window regardless of dates."
    PRD §3.2: "Opening the account immediately performs a **tier review**, so a newly created account already reports a `trailing_volume_cents`, a `tier_code`, a `tier_discount_pct` and a `tier_reviewed_at` stamp rather than nulls."

    Design: Corner/calculations/tier_selection_is_inclusive_at_every_table_threshold
    """
    store = create_store()

    account = validate_success(
        api_client.create_pro_account(
            create_pro_account_payload(
                store["id"],
                business_name="Threshold Contracting",
                baseline_volume_cents=baseline_volume_cents,
            ),
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    assert account["trailing_volume_cents"] == baseline_volume_cents
    assert account["tier_code"] == expected_tier_code
    assert account["tier_discount_pct"] == pytest.approx(expected_tier_discount_pct)


# --------------------------------------------------------------------------- #
# Return valuation rounding                                                    #
# --------------------------------------------------------------------------- #


def test_return_refund_rounds_once_on_the_summed_gross_refund():
    """PRD §3.9: "The mode is `QUOTED_TERM` when the order names a `job_quote_id` and the approval instant is at or before that quote's `term_end`; otherwise it is `CURRENT_LIST`."
    PRD §3.9: "Under `CURRENT_LIST`, each returned line is instead revalued from scratch at today's price: the fulfillment store's current `list_unit_price_cents` for that line's `sku`, reduced by the account's currently persisted `tier_discount_pct`, rounded half up to a whole cent."
    PRD §3.9: "Returned lines are processed in their order lines' `created_at` ascending order, and `gross_refund_cents` is the sum over them of the applicable unit figure multiplied by the returned `qty_units`."
    PRD §3.9: "The age policy charges nothing when the elapsed whole days since `fulfilled_at` are within 30, and 10 percent beyond that."
    PRD §3.9: "`restocking_fee_cents` is then that percentage applied to `gross_refund_cents` and rounded half up to a whole cent — **one single rounding, on the summed gross, never per line**, which is the deliberate opposite of the per-unit rounding used when order lines were priced."
    PRD §3.9: "`tax_refund_cents` is 0 when the original order's `tax_exempt_applied` was true, and otherwise that net goods figure multiplied by the fulfillment store's `tax_rate_pct`, rounded half up to a whole cent — note that the refunded tax is computed on the goods net of the restocking fee, not on the gross."
    PRD §3.9: "Finally, `refund_total_cents` is the net goods figure plus `tax_refund_cents`."
    PRD §3.6: "When `tax_exempt_applied` is true, `tax_cents` is 0; otherwise `tax_cents` is the tax base multiplied by the fulfillment store's `tax_rate_pct`, rounded half up to a whole cent in a single rounding on the summed base, never per line."
    PRD §3.9: "or approves it, which moves it from `REQUESTED` to `APPROVED`, stamps `approved_by_user_id` with the acting associate's `X-User-ID`, increments its `version`, and is where the whole refund is valued."

    Design: Corner/calculations/restocking_and_tax_refund_round_half_up_once_on_the_summed_gross
    """
    store = create_store(tax_rate_pct=0.0825)
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account = create_pro_account(store["id"], business_name="Rounding Roofers")

    bundle = setup_fulfilled_will_call_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 3)],
        stage_start="2026-08-01T09:00:00Z",
        stage_hours=24,
        payment_method="CARD",
    )
    order = bundle["order"]
    order_line = bundle["order_lines"][0]
    assert order["total_cents"] == 6492

    # 45 whole days after fulfilment: past the 30-day free band, inside the window.
    set_clock("2026-09-15T00:00:00Z")
    request = request_return(
        order["id"], account["id"], [(order_line["id"], 3)], reason_code="OVER_ORDERED"
    )

    approved = validate_success(
        api_client.approve_return_request(request["id"], PRO_DESK_ASSOCIATE),
        expected_status=200,
    )

    assert approved["status"] == "APPROVED"
    assert approved["valuation_mode"] == "CURRENT_LIST"
    assert approved["gross_refund_cents"] == 5997
    assert approved["restocking_fee_pct"] == pytest.approx(0.10)
    assert approved["restocking_fee_cents"] == 600
    assert approved["tax_refund_cents"] == 445
    assert approved["refund_total_cents"] == 5842
    assert approved["approved_by_user_id"] == PRO_DESK_ASSOCIATE["X-User-ID"]


# --------------------------------------------------------------------------- #
# Multi-store sourcing                                                         #
# --------------------------------------------------------------------------- #


def test_sourcing_drains_the_fulfillment_store_then_walks_distance_rank():
    """PRD §3.7: "For a given SKU, a store is a candidate when its `region_code` equals the `region_code` of the order's fulfillment store **and** it holds a stock position for that SKU whose `on_hand_units` less `reserved_units` is strictly greater than zero."
    PRD §3.7: "First, the order's own fulfillment store sorts ahead of every other store — this is a two-valued key, the fulfillment store against everybody else, not a distance comparison."
    PRD §3.7: "Second, `distance_rank` ascending, so nearer stores are drained before farther ones."
    PRD §3.7: "For each line, the server tracks the units still to be found, walks the ranked candidates in order, takes at each store the smaller of the units still needed and that store's `available_units`, plans a reservation for that store when the take is positive, subtracts it from the remainder, and stops as soon as the remainder reaches zero."
    PRD §3.7: "Its `status` starts at `HELD` and its `released_reason_code` is null."
    PRD §3.7: "Every sourcing store then has its `reserved_units` recomputed as the sum of `qty_units` across its own reservations in `HELD` or `ALLOCATED`, with `available_units` following."
    PRD §3.6: "Then, for each line, `list_unit_price_cents` is copied from the fulfillment store's stock position for that SKU — never from a sourcing store's position, however the units eventually get sourced."
    PRD §4: "Note that the sourcing call on a pro order responds with `201 Created` even though it reads as an action on an existing order, because its purpose is to create that order's reservation records."

    Design: Corner/calculations/waterfall_fills_the_fulfillment_store_first_then_by_distance_rank
    """
    fulfillment_store = create_store(store_code="HD-101", distance_rank=1)
    near_store = create_store(store_code="HD-103", distance_rank=2)
    far_store = create_store(store_code="HD-102", distance_rank=3)

    fulfillment_stock = create_store_stock(
        fulfillment_store["id"],
        SKU_SHINGLE_BUNDLE,
        on_hand_units=5,
        list_unit_price_cents=1999,
    )
    near_stock = create_store_stock(
        near_store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=4, list_unit_price_cents=1999
    )
    far_stock = create_store_stock(
        far_store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=100, list_unit_price_cents=1899
    )

    account = create_pro_account(
        fulfillment_store["id"], business_name="Waterfall Framing"
    )
    order, order_lines = create_draft_order(
        account["id"],
        fulfillment_store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
        job_lot_required=False,
    )
    submit_order(order["id"], account["id"])

    reservations = validate_success(
        api_client.reserve_pro_order(order["id"], PRO_DESK_ASSOCIATE),
        expected_status=201,
    )

    assert len(reservations) == 3
    by_store = {row["store_id"]: row for row in reservations}
    assert by_store[fulfillment_store["id"]]["qty_units"] == 5
    assert by_store[near_store["id"]]["qty_units"] == 4
    assert by_store[far_store["id"]]["qty_units"] == 1
    for row in reservations:
        assert row["status"] == "HELD"
        assert row["order_line_id"] == order_lines[0]["id"]

    refreshed = read_pro_order(order["id"], account["id"])
    assert refreshed["fulfillment_status"] == "RESERVED"
    assert refreshed["subtotal_cents"] == 19990

    fulfillment_position = read_store_stock(fulfillment_stock["id"])
    assert fulfillment_position["reserved_units"] == 5
    assert fulfillment_position["available_units"] == 0
    near_position = read_store_stock(near_stock["id"])
    assert near_position["reserved_units"] == 4
    assert near_position["available_units"] == 0
    far_position = read_store_stock(far_stock["id"])
    assert far_position["reserved_units"] == 1
    assert far_position["available_units"] == 99

    priced_line = get_success_data(
        api_client.get_order_line(
            order_lines[0]["id"], make_contractor_admin_headers(account["id"])
        )
    )
    assert priced_line["list_unit_price_cents"] == 1999
    assert priced_line["effective_unit_price_cents"] == 1999


def test_reservation_is_rejected_whole_when_one_line_cannot_be_covered():
    """PRD §3.7: "Allocation is a strict waterfall, and the lines are processed in their own `created_at` ascending order."
    PRD §3.7: "If any line finishes the walk with units still unfound, the entire call — every line, not just the short one — is rejected with `ERR_INSUFFICIENT_JOB_LOT`."
    PRD §3.7: "**Rejection is atomic in the strongest sense: no reservation row and no change to any store's `reserved_units` survives a failed reservation call.**"
    PRD §3.7: "A caller who retries after a rejection must see exactly the inventory picture that existed before."

    Design: Corner/calculations/sourcing_is_all_or_nothing_across_lines_when_region_stock_falls_short
    """
    store = create_store()
    coverable_stock = create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=6, list_unit_price_cents=1999
    )
    short_stock = create_store_stock(
        store["id"], SKU_MORTAR_BAG, on_hand_units=2, list_unit_price_cents=2000
    )

    account = create_pro_account(store["id"], business_name="Short Supply Siding")
    order, _ = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 4), (SKU_MORTAR_BAG, 4)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
    )
    submit_order(order["id"], account["id"])

    validate_error(
        api_client.reserve_pro_order(order["id"], PRO_DESK_ASSOCIATE),
        ApiErrorId.ERR_INSUFFICIENT_JOB_LOT.value,
        expected_status=409,
    )

    rows, meta = validate_paginated(
        api_client.list_reservations(
            PRO_DESK_ASSOCIATE, params={"pro_order_id": order["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    coverable_position = read_store_stock(coverable_stock["id"])
    assert coverable_position["reserved_units"] == 0
    assert coverable_position["available_units"] == 6
    short_position = read_store_stock(short_stock["id"])
    assert short_position["reserved_units"] == 0
    assert short_position["available_units"] == 2

    assert read_pro_order(order["id"], account["id"])["fulfillment_status"] == "SUBMITTED"


def test_job_lot_required_order_refuses_the_split_its_twin_accepts():
    """PRD §3.7: "Then the job-lot rule is applied to the finished plan: if the order's `job_lot_required` is true and the plan draws on more than one distinct store, the entire call is rejected with `ERR_JOB_LOT_SPLIT_NOT_ALLOWED`."
    PRD §3.7: "**Rejection is atomic in the strongest sense: no reservation row and no change to any store's `reserved_units` survives a failed reservation call.**"
    PRD §3.7: "For each line, the server tracks the units still to be found, walks the ranked candidates in order, takes at each store the smaller of the units still needed and that store's `available_units`, plans a reservation for that store when the take is positive, subtracts it from the remainder, and stops as soon as the remainder reaches zero."
    PRD §3.6: "`job_lot_required` demands that every line be sourced from one single store for dye-lot consistency"

    Design: Corner/calculations/job_lot_required_rejects_a_two_store_split_that_otherwise_succeeds
    """
    first_store = create_store(store_code="HD-101", distance_rank=1)
    second_store = create_store(store_code="HD-102", distance_rank=2)
    first_stock = create_store_stock(
        first_store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=6, list_unit_price_cents=1999
    )
    second_stock = create_store_stock(
        second_store["id"],
        SKU_SHINGLE_BUNDLE,
        on_hand_units=6,
        list_unit_price_cents=1999,
    )

    account = create_pro_account(first_store["id"], business_name="Single Lot Builders")

    lot_order, _ = create_draft_order(
        account["id"],
        first_store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
        job_lot_required=True,
    )
    submit_order(lot_order["id"], account["id"])

    split_order, _ = create_draft_order(
        account["id"],
        first_store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="WILL_CALL",
        job_lot_required=False,
    )
    submit_order(split_order["id"], account["id"])

    validate_error(
        api_client.reserve_pro_order(lot_order["id"], PRO_DESK_ASSOCIATE),
        ApiErrorId.ERR_JOB_LOT_SPLIT_NOT_ALLOWED.value,
        expected_status=409,
    )
    _, lot_meta = validate_paginated(
        api_client.list_reservations(
            PRO_DESK_ASSOCIATE, params={"pro_order_id": lot_order["id"]}
        )
    )
    assert lot_meta["total_count"] == 0
    assert (
        read_pro_order(lot_order["id"], account["id"])["fulfillment_status"]
        == "SUBMITTED"
    )

    split_reservations = validate_success(
        api_client.reserve_pro_order(split_order["id"], PRO_DESK_ASSOCIATE),
        expected_status=201,
    )
    assert len(split_reservations) == 2
    split_by_store = {row["store_id"]: row for row in split_reservations}
    assert split_by_store[first_store["id"]]["qty_units"] == 6
    assert split_by_store[second_store["id"]]["qty_units"] == 4
    assert (
        read_pro_order(split_order["id"], account["id"])["fulfillment_status"]
        == "RESERVED"
    )

    first_position = read_store_stock(first_stock["id"])
    assert first_position["reserved_units"] == 6
    assert first_position["available_units"] == 0
    second_position = read_store_stock(second_stock["id"])
    assert second_position["reserved_units"] == 4
    assert second_position["available_units"] == 2


# --------------------------------------------------------------------------- #
# Order total assembly                                                         #
# --------------------------------------------------------------------------- #


def test_delivery_pricing_preview_applies_freight_and_lift_gate_charges():
    """PRD §3.6: "Before committing, the contractor or the desk can ask for a **read-only pricing preview**, which runs the whole pricing computation against the current clock and the current tier and persists nothing at all."
    PRD §3.6: "A `DELIVERY` order starts from a base freight surcharge of $89.00, and a `WILL_CALL` order starts from zero and stays there — `freight_surcharge_cents` is always 0 for will-call."
    PRD §3.6: "When a `DELIVERY` order's `subtotal_cents` reaches $2,500.00 the freight is waived to 0; the threshold is inclusive, so an order landing exactly on $2,500.00 pays no freight."
    PRD §3.6: "Below it, `freight_surcharge_cents` is the full $89.00."
    PRD §3.6: "The lift-gate fee is next and it is **never** waived, not even on an order whose freight has been waived: `lift_gate_fee_cents` is $45.00 when the order's `delivery_mode` is `DELIVERY` and its `lift_gate_required` is true, and 0 otherwise."
    PRD §3.6: "The tax base is the sum of `subtotal_cents`, `freight_surcharge_cents` and `lift_gate_fee_cents` — freight and the lift-gate fee are taxable."
    PRD §3.6: "When `tax_exempt_applied` is true, `tax_cents` is 0; otherwise `tax_cents` is the tax base multiplied by the fulfillment store's `tax_rate_pct`, rounded half up to a whole cent in a single rounding on the summed base, never per line."
    PRD §3.6: "Finally, `total_cents` is the sum of `subtotal_cents`, `freight_surcharge_cents`, `lift_gate_fee_cents` and `tax_cents`."

    Design: Corner/calculations/delivery_preview_applies_freight_and_lift_gate_constants
    """
    store = create_store(tax_rate_pct=0.0825, lift_gate_available=True)
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account = create_pro_account(store["id"], business_name="Freight Test Framing")
    headers = make_contractor_admin_headers(account["id"])

    lift_order, _ = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="DELIVERY",
        lift_gate_required=True,
    )
    plain_order, _ = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="DELIVERY",
        lift_gate_required=False,
    )

    lift_preview = validate_success(
        api_client.get_pricing_preview(lift_order["id"], headers), expected_status=200
    )
    plain_preview = validate_success(
        api_client.get_pricing_preview(plain_order["id"], headers), expected_status=200
    )

    assert lift_preview["freight_surcharge_cents"] == 8900
    assert lift_preview["lift_gate_fee_cents"] == 4500
    assert lift_preview["tax_cents"] == 2755
    assert lift_preview["total_cents"] == 36145

    assert plain_preview["freight_surcharge_cents"] == 8900
    assert plain_preview["lift_gate_fee_cents"] == 0
    assert plain_preview["tax_cents"] == 2383
    assert plain_preview["total_cents"] == 31273

    for preview in (lift_preview, plain_preview):
        assert preview["tier_code_applied"] == "MEMBER"
        assert preview["subtotal_cents"] == 19990
        assert preview["list_subtotal_cents"] == 19990
        assert preview["discount_cents"] == 0

    unpriced = read_pro_order(lift_order["id"], account["id"])
    assert unpriced["total_cents"] is None
    assert unpriced["priced_at"] is None


def test_resale_purchase_with_verified_certificate_zeroes_only_the_tax():
    """PRD §3.4: "A successful verification moves `status` from `PENDING` to `VERIFIED`, stamps `verified_at` with the current clock instant, and increments the certificate's `version`."
    PRD §3.4: "That derived array holds exactly those `state_code` values for which the account has a certificate whose `status` is `VERIFIED` and whose `expires_on` is strictly after the current clock date — the same strict comparison, applied continuously, so a verified certificate silently drops out of the array on the day it expires without any transition being recorded against it."
    PRD §3.6: "The order's `tax_exempt_applied` is true when its `resale_purchase` is true **and** the fulfillment store's `state_code` is among the account's `tax_exempt_state_codes` evaluated at the pricing instant."
    PRD §3.6: "When `tax_exempt_applied` is true, `tax_cents` is 0; otherwise `tax_cents` is the tax base multiplied by the fulfillment store's `tax_rate_pct`, rounded half up to a whole cent in a single rounding on the summed base, never per line."
    PRD §3.6: "A `DELIVERY` order starts from a base freight surcharge of $89.00, and a `WILL_CALL` order starts from zero and stays there — `freight_surcharge_cents` is always 0 for will-call."
    PRD §3.6: "The lift-gate fee is next and it is **never** waived, not even on an order whose freight has been waived: `lift_gate_fee_cents` is $45.00 when the order's `delivery_mode` is `DELIVERY` and its `lift_gate_required` is true, and 0 otherwise."
    PRD §3.6: "Finally, `total_cents` is the sum of `subtotal_cents`, `freight_surcharge_cents`, `lift_gate_fee_cents` and `tax_cents`."

    Design: Corner/calculations/resale_purchase_with_verified_certificate_zeroes_only_the_tax_leg
    """
    store = create_store(state_code="IL", tax_rate_pct=0.0825, lift_gate_available=True)
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account = create_pro_account(store["id"], business_name="Resale Roofing Supply")

    certificate = file_tax_exempt_certificate(
        account["id"],
        state_code="IL",
        certificate_number="IL-777",
        expires_on="2027-06-30",
    )
    verified = verify_tax_exempt_certificate(certificate["id"])
    assert verified["status"] == "VERIFIED"
    assert read_pro_account(account["id"])["tax_exempt_state_codes"] == ["IL"]

    exempt_order, _ = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="DELIVERY",
        lift_gate_required=True,
        resale_purchase=True,
    )
    taxed_order, _ = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 10)],
        payment_method="CARD",
        delivery_mode="DELIVERY",
        lift_gate_required=True,
        resale_purchase=False,
    )

    priced_exempt = validate_success(
        api_client.submit_pro_order(
            exempt_order["id"], make_contractor_admin_headers(account["id"])
        ),
        expected_status=200,
    )
    priced_taxed = validate_success(
        api_client.submit_pro_order(
            taxed_order["id"], make_contractor_admin_headers(account["id"])
        ),
        expected_status=200,
    )

    assert priced_exempt["tax_exempt_applied"] is True
    assert priced_exempt["freight_surcharge_cents"] == 8900
    assert priced_exempt["lift_gate_fee_cents"] == 4500
    assert priced_exempt["tax_cents"] == 0
    assert priced_exempt["total_cents"] == 33390

    assert priced_taxed["tax_exempt_applied"] is False
    assert priced_taxed["tax_cents"] == 2755
    assert priced_taxed["total_cents"] == 36145


# --------------------------------------------------------------------------- #
# Trailing volume versus credit exposure                                       #
# --------------------------------------------------------------------------- #


def test_trailing_volume_and_exposure_filter_orders_oppositely():
    """PRD §3.2: "An order counts toward the window when its `credit_status` is either `INVOICED` or `PAID`, and its `invoiced_at` instant is at or after the window's opening instant and at or before the current clock instant."
    PRD §3.2: "Orders in `DRAFT`, `SUBMITTED`, `UNBILLED`, `AUTHORIZED` or `VOIDED` never contribute, which means an order that has been authorized against the credit line but not yet invoiced does not move the tier by a single cent."
    PRD §3.2: "`trailing_volume_cents` is then the account's `baseline_volume_cents` plus the sum of `net_volume_cents` across the account's in-window orders, where an order's `net_volume_cents` is its `subtotal_cents` less its `credited_gross_refund_cents` — returns net out at their gross refund value, before any restocking fee."
    PRD §3.3: "It is the sum of `total_cents` across the account's orders whose `credit_status` is `AUTHORIZED` or `INVOICED`, less the sum of `credited_refund_cents` across those same orders."
    PRD §3.3: "Orders in `PAID` or `VOIDED` leave the exposure base entirely, and orders that have never been submitted never enter it."
    PRD §3.3: "`available_cents` is `limit_cents` less `exposure_cents`."
    PRD §3.3: "Its threshold is 90 percent of the limit: the freeze threshold in cents is `limit_cents` multiplied by nine tenths, rounded half up to a whole cent."
    PRD §3.2: "The delta is added to `baseline_volume_cents`, which is what makes the correction permanent rather than window-bound, the correction counts as a tier review event, and the account's `version` increases by one."
    PRD §3.2: "Each of them recomputes all three tier figures and re-stamps `tier_reviewed_at` with the current logical clock instant."

    Design: Corner/calculations/trailing_volume_counts_only_invoiced_or_paid_orders_while_exposure_counts_only_open_ones
    """
    store = create_store(tax_rate_pct=0.0825)
    create_store_stock(
        store["id"], SKU_SHINGLE_BUNDLE, on_hand_units=600, list_unit_price_cents=1999
    )
    account = create_pro_account(
        store["id"],
        business_name="Filter Test Contracting",
        tier_review_mode="PINNED_AT_REVIEW",
        baseline_volume_cents=0,
    )
    credit_line = create_credit_line(
        account["id"], limit_cents=2_000_000, terms_days=30
    )

    # Leg one: authorized only.
    open_order, _ = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 100)],
        payment_method="CREDIT_LINE",
        delivery_mode="WILL_CALL",
    )
    submit_order(open_order["id"], account["id"])

    # Leg two: invoiced then settled.
    paid_bundle = setup_invoiced_will_call_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 100)],
        stage_start="2026-08-01T09:00:00Z",
        stage_hours=24,
        payment_method="CREDIT_LINE",
    )
    pay_order(paid_bundle["order"]["id"], 216_392)

    # Leg three: authorized then voided by cancellation.
    void_order, _ = create_draft_order(
        account["id"],
        store["id"],
        lines=[(SKU_SHINGLE_BUNDLE, 100)],
        payment_method="CREDIT_LINE",
        delivery_mode="WILL_CALL",
    )
    submit_order(void_order["id"], account["id"])
    get_success_data(
        api_client.cancel_pro_order(
            void_order["id"],
            "CUSTOMER_CHANGE",
            make_contractor_admin_headers(account["id"]),
        )
    )

    assert (
        read_pro_order(open_order["id"], account["id"])["credit_status"] == "AUTHORIZED"
    )
    assert (
        read_pro_order(paid_bundle["order"]["id"], account["id"])["credit_status"]
        == "PAID"
    )
    assert read_pro_order(void_order["id"], account["id"])["credit_status"] == "VOIDED"

    before = read_pro_account(account["id"])
    assert before["trailing_volume_cents"] == 199_900
    assert before["tier_code"] == "MEMBER"

    line_before = read_credit_line(credit_line["id"])
    assert line_before["exposure_cents"] == 216_392
    assert line_before["available_cents"] == 1_783_608
    assert line_before["status"] == "ACTIVE"

    adjusted = validate_success(
        api_client.adjust_pro_account_volume(
            account["id"], 4_800_100, "legacy migration true-up", CREDIT_MANAGER
        ),
        expected_status=200,
    )
    assert adjusted["id"] == account["id"]

    after = read_pro_account(account["id"])
    assert after["baseline_volume_cents"] == 4_800_100
    assert after["trailing_volume_cents"] == 5_000_000
    assert after["tier_code"] == "GOLD"
    assert after["tier_discount_pct"] == pytest.approx(0.05)
    assert after["tier_reviewed_at"].startswith("2026-08-01T00:00:00")

    line_after = read_credit_line(credit_line["id"])
    assert line_after["exposure_cents"] == 216_392
