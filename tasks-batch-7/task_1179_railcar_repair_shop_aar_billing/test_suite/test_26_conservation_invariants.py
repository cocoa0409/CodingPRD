"""Conservation invariants: parts stock across reserve/release, billed money
across counter, acceptance, and settlement."""
from test_helpers import (
    TEST_USERS, api_client, assert_brc_money_conservation,
    assert_part_quantity_invariant, counter_item, file_counter_bill,
    make_car_owner_rep_headers, make_repair_foreman_headers,
    scenario_authorized_wo, scenario_submitted_brc, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
BILLING = TEST_USERS["billing_clerk"]
FOREMAN = "foreman-1"


def test_reserve_holds_the_availability_invariant():
    """PRD §2.9: "the derived `available_qty`, which always equals
    `on_hand_qty` minus `reserved_qty` and must never go negative."
    PRD §2.9: "**Reserving** at authorization requires `available_qty` to be at
    least the planned quantity for every planned part — any shortfall rejects
    the authorization with `ERR_PART_STOCK_INSUFFICIENT` (409) — and then
    increases `reserved_qty` by each planned quantity."

    Design: Difficulty/compensating_invariant/parts_reserve_release_conserves_availability
    """
    ctx = scenario_authorized_wo(
        part={"part_number": "P-500", "description": "Brake pipe bracket",
              "unit_price_cents": 1000, "on_hand_qty": 5, "reorder_threshold": 0})
    part = validate_success(api_client.get_part(ctx["parts"]["part"]["id"], ADMIN))
    assert part["on_hand_qty"] == 5
    assert part["reserved_qty"] == 1
    assert part["available_qty"] == 4, "5 - 1 reserved"
    assert_part_quantity_invariant(part)


def test_release_on_cancel_restores_stock_exactly():
    """PRD §2.9: "**Releasing** on cancellation or rejection decreases
    `reserved_qty` by the planned quantity, restoring availability."
    PRD §3.5: "Cancellation is compensating: `auth_status` and `exec_status`
    move to `CANCELLED`, lines move to `CANCELLED` from `ESTIMATED` or
    `AUTHORIZED`, findings return to `OPEN` from `ESTIMATED` or `AUTHORIZED`,
    a reserved slot is released to `RELEASED` with `reserved_work_order_id`
    cleared, and every part reservation is released with status recomputation".

    Design: Difficulty/compensating_invariant/parts_reserve_release_conserves_availability
    """
    ctx = scenario_authorized_wo(
        part={"part_number": "P-500", "description": "Brake pipe bracket",
              "unit_price_cents": 1000, "on_hand_qty": 5, "reorder_threshold": 0})
    part_id = ctx["parts"]["part"]["id"]
    validate_success(api_client.cancel_work_order(
        ctx["wo"]["id"], {}, make_repair_foreman_headers(FOREMAN)))
    part = validate_success(api_client.get_part(part_id, ADMIN))
    assert part["on_hand_qty"] == 5
    assert part["reserved_qty"] == 0, "the reservation is fully released"
    assert part["available_qty"] == 5, "reserve + release conserves stock with zero drift"
    assert part["status"] == "ACTIVE", "available 5 is above threshold 0"
    assert_part_quantity_invariant(part)
    wo = validate_success(api_client.get_work_order(ctx["wo"]["id"], ADMIN))
    assert wo["auth_status"] == "CANCELLED"
    assert wo["exec_status"] == "CANCELLED"


def _settled_brc_scenario() -> dict:
    """Hose BRC of 22500 submitted, a 2500 counter accepted, the card accepted,
    then settled."""
    ctx = scenario_submitted_brc(
        actual_hours=2.0,
        part={"part_number": "H-100", "unit_price_cents": 4500, "on_hand_qty": 10,
              "reorder_threshold": 2})
    cb = file_counter_bill(ctx, [counter_item(ctx["brc_lines"][0]["id"], 2500,
                                              "labor dispute")])
    validate_success(api_client.accept_counter_bill(cb["id"], BILLING))
    validate_success(api_client.accept_billing_repair_card(
        ctx["brc"]["id"], make_car_owner_rep_headers(ctx["owner"]["id"])))
    ctx["cb"] = cb
    return ctx


def test_net_posting_conserves_billed_money_at_acceptance():
    """PRD §3.7: "The `net_settled_cents` anchors the card: the submitted total
    minus the sum of accepted counter credits, recomputed whenever credits
    land."
    PRD §2.10: "At acceptance — manual or deemed — the owner's balance
    increases by the card's `owner_total_cents` minus the owner-responsible
    share of accepted counter-bill credits, and the handling line's balance
    increases by `handling_line_total_cents` minus the handling share of those
    credits."
    PRD §2.10: "This is deliberately a net posting: counter-bills always
    resolve before acceptance, so the credit is netted into the acceptance
    posting rather than posted separately, and counter-bill acceptance itself
    never touches the ledgers."

    Design: Difficulty/compensating_invariant/brc_money_conservation_through_counter_and_settle
    """
    ctx = _settled_brc_scenario()
    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["status"] == "ACCEPTED"
    assert_brc_money_conservation(brc, accepted_credit_total=2500)
    assert brc["net_settled_cents"] == 20000, "22500 submitted - 2500 accepted credits"
    owner = validate_success(api_client.get_car_owner(ctx["owner"]["id"], ADMIN))
    assert owner["outstanding_balance_cents"] == 20000, "net posting, not gross 22500"


def test_settlement_returns_the_ledger_to_zero_without_drift():
    """PRD §2.10: "At settlement, each balance decreases by the same net party
    share, returning the ledgers toward zero."
    PRD §3.7: "Settling an `ACCEPTED` card moves it to `SETTLED` and unwinds
    the same net party shares from the ledgers."

    Design: Difficulty/compensating_invariant/brc_money_conservation_through_counter_and_settle
    """
    ctx = _settled_brc_scenario()
    settled = validate_success(api_client.settle_billing_repair_card(ctx["brc"]["id"], BILLING))
    assert settled["status"] == "SETTLED"
    owner = validate_success(api_client.get_car_owner(ctx["owner"]["id"], ADMIN))
    assert owner["outstanding_balance_cents"] == 0, (
        "22500 billed == 20000 settled + 2500 credited; no residual drift")
    brc = validate_success(api_client.get_billing_repair_card(ctx["brc"]["id"], ADMIN))
    assert brc["net_settled_cents"] == 20000
