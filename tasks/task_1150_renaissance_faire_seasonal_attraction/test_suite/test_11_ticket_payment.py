"""Ticket order payment: minting, capacity, idempotency, parallel status
dimensions, and the OCC-guarded reprice edit."""
from test_helpers import (
    ApiErrorId,
    assert_order_money_invariant,
    create_ticket_order_payload,
    get_order,
    get_season,
    make_build_season,
    make_faire_day,
    make_order,
    make_paid_order,
    set_clock,
    setup_paid_day_order,
    setup_season_build_with_sales_day,
    tickets_of_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, GATE, OPERATOR
from test_helpers.test_users import make_guest_headers


def test_pay_mints_quantity_valid_tickets(api, any_headers):
    """PRD §3.5: "On success the order becomes `PAID` and `quantity` tickets are
    minted in `VALID` status, each carrying the order's `order_id`: `DAY` and
    `GROUP` orders mint `ticket_type` `DAY` tickets bound to the order's
    `faire_day_id`, while `SEASON` orders mint `ticket_type` `SEASON` passes whose
    `faire_day_id` is null. The season's `outstanding_admissions` grows by the
    `quantity` minted."

    Design: Corner/state_machines/pay_mints_quantity_valid_tickets
    """
    season, day = setup_season_build_with_sales_day()
    order = make_order(season["id"], "g-mint@example.com", "DAY", 3, 3000, day["id"])

    paid = validate_success(
        api.pay_order(order["id"], make_guest_headers("g-mint@example.com")), 200
    )
    assert paid["payment_status"] == "PAID"

    tickets = tickets_of_order(order["id"])
    assert len(tickets) == 3
    for ticket in tickets:
        assert ticket["status"] == "VALID"
        assert ticket["faire_day_id"] == day["id"]
        assert ticket["order_id"] == order["id"]

    assert get_season(season["id"])["outstanding_admissions"] == 3


def test_double_pay_rejected(api):
    """PRD §3.5: "Payment is the buyer's own act — the caller's `X-User-ID` must
    equal the order's `buyer_email`, else `ERR_NOT_RESOURCE_OWNER` — and requires
    the order to be `UNPAID`, else `ERR_ORDER_NOT_UNPAID`."

    Design: Corner/state_machines/double_pay_rejected
    """
    season, day, order = setup_paid_day_order(quantity=2, buyer_email="g-i@example.com")
    res = api.pay_order(order["id"], make_guest_headers("g-i@example.com"))
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_UNPAID, expected_status=409)

    # No duplicate minting on the rejected repeat.
    assert get_season(season["id"])["outstanding_admissions"] == 2
    assert len(tickets_of_order(order["id"])) == 2


def test_day_at_capacity_on_pay(api):
    """PRD §3.5: "For `DAY` and `GROUP` orders the faire day's capacity gate
    applies: minting the order's tickets must keep the day's `tickets_sold_count` —
    the count of that day's tickets in `VALID` or `REDEEMED` status — plus the
    order's `quantity` at or below the season's `daily_capacity`, else the payment
    is rejected with `ERR_DAY_AT_CAPACITY`."

    Design: Corner/validations/day_at_capacity_on_pay
    """
    season, day = setup_season_build_with_sales_day(daily_capacity=1)
    o1 = make_order(season["id"], "g-c1@example.com", "DAY", 1, 3000, day["id"])
    o2 = make_order(season["id"], "g-c2@example.com", "DAY", 1, 3000, day["id"])
    validate_success(api.pay_order(o1["id"], make_guest_headers("g-c1@example.com")), 200)

    res = api.pay_order(o2["id"], make_guest_headers("g-c2@example.com"))
    validate_error(res, ApiErrorId.ERR_DAY_AT_CAPACITY, expected_status=409)

    # The rejected payment minted nothing.
    assert get_season(season["id"])["outstanding_admissions"] == 1
    day_after = validate_success(api.get_faire_day(day["id"], ANY), 200)
    assert day_after["tickets_sold_count"] == 1
    assert get_order(o2["id"])["payment_status"] == "UNPAID"


def test_ticket_order_parallel_dimensions_independent(api, gate_agent_headers):
    """PRD §3.5: "An order's `redemption_status` tracks its tickets automatically as
    they change state. When a ticket of an `UNREDEEMED` order is redeemed while
    others remain `VALID`, the order becomes `PARTIALLY_REDEEMED`"
    PRD §3.5: "when the refund falls short of the remaining retained amount the
    order becomes `PARTIALLY_REFUNDED`"

    Design: Corner/state_machines/ticket_order_parallel_dimensions_independent
    """
    set_clock()
    season = make_build_season(name="Parallel Revel", volunteer_min_hours=0)
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    season = validate_success(api.open_season(season["id"], OPERATOR), 200)
    validate_success(api.open_sales(day["id"], OPERATOR), 200)
    # The order is placed and paid while the day is OPEN_FOR_SALES (§3.5), then
    # the gates open so a ticket can be redeemed.
    order = make_paid_order(season["id"], "g-p@example.com", "DAY", 2, 3000, day["id"])
    set_clock("2026-06-06T07:00:00Z")
    validate_success(api.open_gates(day["id"], OPERATOR), 200)

    # Redemption moves only the redemption dimension.
    ticket = tickets_of_order(order["id"])[0]
    validate_success(api.redeem_ticket(ticket["id"], gate_agent_headers), 200)
    after_redeem = get_order(order["id"])
    assert after_redeem["redemption_status"] == "PARTIALLY_REDEEMED"
    assert after_redeem["payment_status"] == "PAID"

    # Refund moves only the payment dimension.
    validate_success(
        api.refund_order(order["id"], {"refund_cents": 1000}, gate_agent_headers), 200
    )
    after_refund = get_order(order["id"])
    assert after_refund["payment_status"] == "PARTIALLY_REFUNDED"
    assert after_refund["redemption_status"] == "PARTIALLY_REDEEMED"
    assert_order_money_invariant(after_refund)


def test_occ_order_reprice_success_and_reprice_value(api):
    """PRD §3.5: "While an order remains `UNPAID`, the buyer may revise its
    `quantity` or its `faire_day_id` through the OCC-guarded edit of §2.8, which
    requires `expected_order_version` and increments the order's `version` by 1 on
    success; editing an order in any other payment state is rejected with
    `ERR_ORDER_NOT_UNPAID`, and every successful edit reprices the order exactly as
    at placement, recomputing `discount_pct`, `total_cents`, and `retained_cents`."

    Design: Corner/cross_cutting_layers/occ_order_reprice_stale_version
    """
    season, day = setup_season_build_with_sales_day()
    order = make_order(season["id"], "g-occ@example.com", "DAY", 3, 3000, day["id"])
    assert order["total_cents"] == 9450  # 3 * 3000 + 3 * 150

    patched = validate_success(
        api.patch_ticket_order(
            order["id"],
            {"expected_order_version": order["version"], "quantity": 4},
            make_guest_headers("g-occ@example.com"),
        ),
        200,
    )
    # 4 * 3000 + 4 * 150 = 12600, repriced in the same request.
    assert patched["quantity"] == 4
    assert patched["total_cents"] == 12600
    assert patched["version"] == order["version"] + 1
    assert_order_money_invariant(patched)


def test_occ_order_reprice_stale_version_rejected(api):
    """PRD §2.8: "Editing an unpaid ticket order requires the analogous
    `expected_order_version`, matched against the order's current `version`; a
    mismatch is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). The order
    remains `UNPAID` across edits, so a later edit carrying a previously observed
    version would otherwise reprice from a stale base."

    Design: Corner/cross_cutting_layers/occ_order_reprice_stale_version
    """
    season, day = setup_season_build_with_sales_day()
    order = make_order(season["id"], "g-occ@example.com", "DAY", 3, 3000, day["id"])
    stale_version = order["version"]
    validate_success(
        api.patch_ticket_order(
            order["id"],
            {"expected_order_version": stale_version, "quantity": 4},
            make_guest_headers("g-occ@example.com"),
        ),
        200,
    )

    res = api.patch_ticket_order(
        order["id"],
        {"expected_order_version": stale_version, "quantity": 5},
        make_guest_headers("g-occ@example.com"),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    # The rejected replay left the order at its last accepted edit.
    reread = get_order(order["id"])
    assert reread["quantity"] == 4
    assert reread["total_cents"] == 12600


def test_immediate_consistency_on_mutation(api, any_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §3.5: "every successful edit reprices the order exactly as at placement,
    recomputing `discount_pct`, `total_cents`, and `retained_cents`."

    Design: Corner/consistency_model/immediate_consistency_on_mutation
    """
    season, day = setup_season_build_with_sales_day()
    order = make_order(season["id"], "g-imm@example.com", "DAY", 3, 3000, day["id"])

    patched = validate_success(
        api.patch_ticket_order(
            order["id"],
            {"expected_order_version": order["version"], "quantity": 5},
            make_guest_headers("g-imm@example.com"),
        ),
        200,
    )
    # 5 * 3000 + 5 * 150 = 15750 — recomputed in the same request's response.
    assert patched["total_cents"] == 15750

    reread = validate_success(api.get_ticket_order(order["id"], ANY), 200)
    assert reread["quantity"] == 5
    assert reread["total_cents"] == 15750
