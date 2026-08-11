"""The Billing Repair Card SUBMITTED <-> DISPUTED cycle across counter rounds."""
from test_helpers import (
    TEST_USERS, api_client, counter_item, file_counter_bill,
    make_car_owner_rep_headers, scenario_submitted_brc, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
BILLING = TEST_USERS["billing_clerk"]


def _submitted_hose_brc() -> dict:
    """BRC of 22500 (2.0h x 9000 labor + one 4500 part) submitted, owner side."""
    return scenario_submitted_brc(
        actual_hours=2.0,
        part={"part_number": "H-100", "unit_price_cents": 4500, "on_hand_qty": 10,
              "reorder_threshold": 2})


def test_counter_filing_disputes_and_withdrawal_returns_submitted():
    """PRD §3.8: "sets `total_countered_cents` to the sum of item amounts;
    starts the counter-bill `OPEN`; and moves the host card `SUBMITTED` →
    `DISPUTED`."
    PRD §3.8: "The filer may also withdraw an `OPEN` or `REBUTTED` counter
    outright, moving it to `WITHDRAWN`, and the sweep of §2.4 expires any
    counter still active once the dispute window plus a grace of
    `counter_window_days` has passed, moving it to `EXPIRED`; either resolution
    flips the card `DISPUTED` → `SUBMITTED` when it was the last active
    counter."

    Design: Difficulty/non_linear_state_machine/brc_submitted_disputed_cycle
    """
    ctx = _submitted_hose_brc()
    owner = make_car_owner_rep_headers(ctx["owner"]["id"])
    cb1 = file_counter_bill(ctx, [counter_item(ctx["brc_lines"][0]["id"], 1000,
                                               "round 1")])
    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["status"] == "DISPUTED", "filing moves SUBMITTED to DISPUTED"

    withdrawn = validate_success(api_client.withdraw_counter_bill(cb1["id"], owner))
    assert withdrawn["status"] == "WITHDRAWN"
    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["status"] == "SUBMITTED", "resolving the last active counter cycles back"
    assert brc["net_settled_cents"] == 22500, "a withdrawn counter applies no credit"


def test_counter_acceptance_then_brc_acceptance_posts_net():
    """PRD §3.8: "when no active counters remain, the card returns `DISPUTED` →
    `SUBMITTED`."
    PRD §3.7: "The `net_settled_cents` anchors the card: the submitted total
    minus the sum of accepted counter credits, recomputed whenever credits
    land."
    PRD §2.10: "the owner's balance increases by the card's `owner_total_cents`
    minus the owner-responsible share of accepted counter-bill credits".

    Design: Difficulty/non_linear_state_machine/brc_submitted_disputed_cycle
    """
    ctx = _submitted_hose_brc()
    owner = make_car_owner_rep_headers(ctx["owner"]["id"])
    bl_id = ctx["brc_lines"][0]["id"]

    # Round 1 ends by withdrawal; round 2 by shop acceptance of 1500.
    cb1 = file_counter_bill(ctx, [counter_item(bl_id, 1000, "round 1")])
    validate_success(api_client.withdraw_counter_bill(cb1["id"], owner))
    cb2 = file_counter_bill(ctx, [counter_item(bl_id, 1500, "round 2")])
    validate_success(api_client.accept_counter_bill(cb2["id"], BILLING))

    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["status"] == "SUBMITTED"
    assert brc["net_settled_cents"] == 21000, "22500 submitted minus 1500 accepted credit"

    cb1_now = validate_success(api_client.get_counter_bill(cb1["id"], ADMIN))
    cb2_now = validate_success(api_client.get_counter_bill(cb2["id"], ADMIN))
    assert cb1_now["status"] == "WITHDRAWN"
    assert cb2_now["status"] == "ACCEPTED"

    accepted = validate_success(api_client.accept_billing_repair_card(brc["id"], owner))
    assert accepted["status"] == "ACCEPTED"
    owner_now = validate_success(api_client.get_car_owner(ctx["owner"]["id"], ADMIN))
    assert owner_now["outstanding_balance_cents"] == 21000
