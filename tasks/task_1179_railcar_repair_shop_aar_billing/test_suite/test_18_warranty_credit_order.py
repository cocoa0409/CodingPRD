"""Warranty credit evaluation order: final minus accepted counters minus prior
warranty credits, capped by the claimed rework cost; honored credits then
shrink the remaining counterable value of the line."""
from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, counter_item, file_counter_bill,
    file_warranty_claim, make_car_owner_rep_headers, scenario_submitted_brc,
    validate_error, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
BILLING = TEST_USERS["billing_clerk"]
QI = TEST_USERS["quality_inspector"]


def _honored_warranty_scenario() -> dict:
    """Hose line finalized at 22500 (2.0h x 9000 + one 4500 part); BRC
    submitted; a 2500 counter accepted; a 15000 warranty claim validated and
    honored."""
    ctx = scenario_submitted_brc(
        actual_hours=2.0,
        part={"part_number": "H-100", "unit_price_cents": 4500, "on_hand_qty": 10,
              "reorder_threshold": 2})
    cb = file_counter_bill(ctx, [counter_item(ctx["brc_lines"][0]["id"], 2500,
                                              "labor hour dispute")])
    validate_success(api_client.accept_counter_bill(cb["id"], BILLING))
    wc = file_warranty_claim(ctx, ctx["wo_lines"][0]["id"],
                             failure_defect_group="AIR_HOSE",
                             claimed_rework_cost_cents=15000,
                             description="hose failed again after 3 weeks")
    validate_success(api_client.validate_warranty_claim(wc["id"], QI))
    validate_success(api_client.honor_warranty_claim(wc["id"], BILLING))
    ctx["cb"] = cb
    ctx["wc"] = wc
    return ctx


def test_warranty_credit_uses_pinned_evaluation_order():
    """PRD §3.9: "The credit is the smaller of two amounts: the repair line's
    `final_total_cents` minus the card line's `accepted_credit_cents` and minus
    any `warranty_credit_cents` previously honored on that line, on the one
    hand; and the claim's `claimed_rework_cost_cents` on the other."
    PRD §3.9: "The honored credit is added to the card line's
    `warranty_credit_cents` when a card line exists for the repair line".

    Design: Difficulty/combinatorial_formula/warranty_credit_pinned_evaluation_order
    """
    ctx = _honored_warranty_scenario()
    claim = validate_success(api_client.get_warranty_claim(ctx["wc"]["id"], ADMIN))
    assert claim["status"] == "HONORED"
    assert claim["credit_cents"] == 15000, "min(22500 - 2500 - 0, 15000)"

    brc_line = validate_success(api_client.get_brc_line(ctx["brc_lines"][0]["id"], ADMIN))
    assert brc_line["warranty_credit_cents"] == 15000
    assert brc_line["accepted_credit_cents"] == 2500


def test_honored_credit_shrinks_remaining_counterable_value():
    """PRD §3.8: "The per-line check then requires each item's
    `counter_amount_cents` to be no more than the referenced card line's
    `final_amount_cents` minus its `accepted_credit_cents` minus its
    `warranty_credit_cents`, else `ERR_CREDIT_EXCEEDS_REMAINING`."
    PRD §2.10: "At acceptance — manual or deemed — the owner's balance
    increases by the card's `owner_total_cents` minus the owner-responsible
    share of accepted counter-bill credits".
    PRD §2.10: "Honored warranty credits decrease each party's balance by that
    party's share of the credit at honor time."

    Design: Difficulty/combinatorial_formula/warranty_credit_pinned_evaluation_order
    """
    ctx = _honored_warranty_scenario()
    owner = make_car_owner_rep_headers(ctx["owner"]["id"])
    bl_id = ctx["brc_lines"][0]["id"]

    # Line remaining is 22500 - 2500 - 15000 = 5000; 5001 breaches it even
    # though the aggregate 60% cap (13500) still has headroom.
    resp = api_client.create_counter_bill(
        ctx["brc"]["id"], {"items": [counter_item(bl_id, 5001, "second round")]}, owner)
    validate_error(resp, ApiErrorId.ERR_CREDIT_EXCEEDS_REMAINING, expected_status=409)

    validate_success(api_client.accept_billing_repair_card(ctx["brc"]["id"], owner))
    owner_now = validate_success(api_client.get_car_owner(ctx["owner"]["id"], ADMIN))
    assert owner_now["outstanding_balance_cents"] == 5000, (
        "net posting 22500 - 2500 accepted counter = 20000 at acceptance, "
        "minus the 15000 warranty share honored earlier")
