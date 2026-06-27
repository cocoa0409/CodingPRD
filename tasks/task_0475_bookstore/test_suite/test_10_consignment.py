"""Local-author consignment: payout tiering at the unit-10 boundary, the
fulfill->consignment-sold cascade, termination cascade, and the local-author
guard."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    create_consignment_agreement_payload,
    make_member, make_title,
    setup_agreement, setup_agreement_with_copies,
    setup_agreement_with_units_sold, setup_consignment_sale_via_fulfill,
)

BOOKSELLER = TEST_USERS["bookseller_headers"]
INVMGR = TEST_USERS["inventory_manager_headers"]
ADMIN = TEST_USERS["store_admin_headers"]


def test_consignment_payout_tenth_unit_uses_040_tier(api):
    """PRD §3.9: "when fewer than ten units have sold the commission rate is forty
    hundredths". And: "The boundary is exact: the tenth unit to sell (nine sold
    before it) still earns the forty-hundredths tier".

    Design: Difficulty/boundary_precision_check/consignment_tier_boundary_unit_10_drops_to_035
    """
    # 9 already sold; the next sale is the 10th (u==9 before counting) -> 0.40 tier.
    ctx = setup_agreement_with_units_sold(units_already_sold=9, sale_price_cents=2000,
                                          list_price_cents=2000)
    tenth_copy_id = ctx["next_copy_ids"][0]
    sold = validate_success(api.mark_copy_sold(tenth_copy_id, BOOKSELLER))
    # payout = round(2000 * (1 - 0.40)) = 1200.
    assert sold["payout_cents"] == 1200


def test_consignment_payout_eleventh_unit_drops_to_035_tier(api):
    """PRD §3.9: "when at least ten but fewer than twenty-five units have sold it
    is thirty-five hundredths". And: "the eleventh unit (ten sold before it) earns
    the thirty-five-hundredths tier."

    Design: Difficulty/boundary_precision_check/consignment_tier_boundary_unit_10_drops_to_035
    """
    # 9 already sold; sell the 10th (still 0.40), then the 11th (u==10) -> 0.35 tier.
    ctx = setup_agreement_with_units_sold(units_already_sold=9, sale_price_cents=2000,
                                          list_price_cents=2000)
    tenth_copy_id, eleventh_copy_id = ctx["next_copy_ids"]
    validate_success(api.mark_copy_sold(tenth_copy_id, BOOKSELLER))
    sold11 = validate_success(api.mark_copy_sold(eleventh_copy_id, BOOKSELLER))
    # payout = round(2000 * (1 - 0.35)) = 1300.
    assert sold11["payout_cents"] == 1300


def test_fulfill_cascades_consignment_copy_sold(api):
    """PRD §3.5: "For any sold copy whose `source` is `CONSIGNMENT`, the system
    cascades into its backing `ConsignmentCopy`, transitioning that copy from
    `ON_SHELF` to `SOLD`, which computes the copy's `payout_cents` and bumps its
    agreement's `units_sold_to_date` and `total_payout_cents`".

    Design: Difficulty/transitive_cascade/fulfill_to_consignment_sold_to_agreement_counters
    """
    ctx = setup_consignment_sale_via_fulfill(sale_price_cents=2000,
                                             list_price_cents=2000)
    validate_success(api.fulfill_order(ctx["order"]["id"], BOOKSELLER))
    agreement = validate_success(
        api.get_consignment_agreement(ctx["agreement"]["id"], INVMGR)
    )
    assert agreement["units_sold_to_date"] == 1


def test_fulfill_cascade_bumps_agreement_total_payout(api):
    """PRD §3.9: "The copy's `payout_cents` is its `sale_price_cents` multiplied by
    one minus the selected commission rate, rounded half-up to whole cents." And:
    "when fewer than ten units have sold the commission rate is forty hundredths".

    Design: Difficulty/transitive_cascade/fulfill_to_consignment_sold_to_agreement_counters
    """
    ctx = setup_consignment_sale_via_fulfill(sale_price_cents=2000,
                                             list_price_cents=2000)
    validate_success(api.fulfill_order(ctx["order"]["id"], BOOKSELLER))
    agreement = validate_success(
        api.get_consignment_agreement(ctx["agreement"]["id"], INVMGR)
    )
    # First sale: u=0 -> 0.40 tier -> payout round(2000*0.60)=1200.
    assert agreement["total_payout_cents"] == 1200


def test_terminate_returns_onshelf_copies_and_removes_stock(api):
    """PRD §3.9: "Termination returns every `ON_SHELF` copy to its author by
    cascading each from `ON_SHELF` to `RETURNED_TO_AUTHOR`; for any backing stock
    item still `AVAILABLE` it removes that copy from inventory by flipping it to
    `RETURNED_TO_PUBLISHER`. The title's `on_hand_qty` is then recomputed".

    Design: Corner/state_machines/consignment_terminate_returns_onshelf_copies
    """
    ctx = setup_agreement_with_copies(num_copies=2, sale_price_cents=1500,
                                      list_price_cents=1500)
    title_id = ctx["title"]["id"]
    mid = validate_success(api.get_title(title_id, INVMGR))
    assert mid["on_hand_qty"] == 2
    terminated = validate_success(
        api.terminate_consignment_agreement(ctx["agreement"]["id"], INVMGR)
    )
    assert terminated["state"] == "TERMINATED"
    final_title = validate_success(api.get_title(title_id, INVMGR))
    assert final_title["on_hand_qty"] == 0


def test_consignment_agreement_non_local_author_rejected(api):
    """PRD §3.9: "The named author must be a member whose `is_local_author` is
    true; otherwise creation is rejected with `ERR_NOT_LOCAL_AUTHOR` (HTTP 422)."

    Design: Corner/validations/consignment_agreement_non_local_author_rejected
    """
    member = make_member()  # is_local_author defaults to false
    title = make_title(list_price_cents=1000, headers=INVMGR)
    resp = api.create_consignment_agreement(
        create_consignment_agreement_payload(member["id"], title["id"]), INVMGR
    )
    validate_error(resp, ApiErrorId.ERR_NOT_LOCAL_AUTHOR)
