"""Checkout: QUOTED pricing, the minimum-charge floor, voucher redemption,
and the independent payment/reconciliation axes."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_machine_flavor, make_topping, make_promotion, make_ticket, add_line, do_checkout,
    make_reconciliation, set_clock, CLOCK_DEFAULT,
    setup_issued_voucher,
)

MANAGER = TEST_USERS["manager_headers"]
SHIFTLEAD = TEST_USERS["shiftlead_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def test_quoted_total_floored_at_minimum_charge(api):
    """PRD §3.5: "That subtotal is then floored at the minimum ticket charge of
    100 cents — the charge before any voucher is the larger of 100 cents and the
    subtotal."

    Design: Difficulty/combinatorial_formula/sale_total_floor_nonlinear_multiinput
    """
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    topping = make_topping(api, surcharge_cents=30, initial_units=50)
    make_promotion(api)  # 10% active over the default clock
    ticket = make_ticket(api)
    add_line(api, ticket["id"], flavor["id"], 1.0, container_tare_oz=0.5, topping_ids=[topping["id"]])
    charged = do_checkout(api, ticket["id"])
    assert charged["quoted_total_cents"] == 100, \
        f"a 0.5oz cup computing to 55c must clamp up to the 100c minimum, got {charged['quoted_total_cents']}"


def test_quoted_total_above_floor_is_uncapped(api):
    """PRD §3.5: "That subtotal is then floored at the minimum ticket charge of
    100 cents — the charge before any voucher is the larger of 100 cents and the
    subtotal."

    Design: Difficulty/combinatorial_formula/sale_total_floor_nonlinear_multiinput
    """
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    make_promotion(api)  # 10% active over the default clock
    ticket = make_ticket(api)
    add_line(api, ticket["id"], flavor["id"], 4.0)  # round_half_up(4*55*0.9)=198
    charged = do_checkout(api, ticket["id"])
    assert charged["quoted_total_cents"] == 198, \
        f"a subtotal of 198 exceeds the 100c floor and must charge 198, got {charged['quoted_total_cents']}"


def test_checkout_response_reflects_charge_and_total(api):
    """PRD §3.5: "Checkout is performed by a `Cashier` and advances the ticket's
    `payment_status` from `OPEN` to `CHARGED`."
    PRD §3.5: "Each cup's `line_quoted_cents` is computed when the cup is added,
    as the net weight times the flavor's per-ounce price, scaled by the
    complement of the seasonal discount, rounded to whole cents, and then
    increased by the flat topping surcharges"

    Design: Corner/consistency_model/checkout_response_immediately_reflects_charge
    """
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    ticket = make_ticket(api)
    add_line(api, ticket["id"], flavor["id"], 7.3)  # round_half_up(7.3*55)=402, no promo
    resp = api.checkout(ticket["id"], {}, CASHIER)
    data = validate_success(resp)
    assert data["payment_status"] == "CHARGED", \
        f"checkout response body must show payment_status CHARGED, got {data['payment_status']}"
    assert data["quoted_total_cents"] == 402, \
        f"checkout response body must show quoted_total_cents 402, got {data['quoted_total_cents']}"


def test_voucher_redemption_reduces_total_and_flips_voucher(api):
    """PRD §3.5: "Finally, if a voucher is redeemed, its fixed value (500 cents)
    is subtracted, and the result is again floored at 100 cents:
    `quoted_total_cents` is the larger of 100 cents and (the pre-voucher amount
    minus the redeemed voucher value)."
    PRD §3.5: "If a voucher was supplied and accepted, it transitions from
    `ISSUED` to `REDEEMED` and the ticket's `redeemed_voucher_id` is set to it."

    Design: Corner/endpoints/voucher_redeem_reduces_checkout_total
    """
    bundle = setup_issued_voucher(api)
    voucher = bundle["voucher"]
    flavor = bundle["flavor"]
    ticket = make_ticket(api, loyalty_account_id=bundle["loyalty"]["id"])
    add_line(api, ticket["id"], flavor["id"], 20.0)  # round_half_up(20*55)=1100
    resp = api.checkout(ticket["id"], {"voucher_id": voucher["id"]}, CASHIER)
    data = validate_success(resp)
    assert data["quoted_total_cents"] == 600, \
        f"1100c minus the 500c voucher must charge 600, got {data['quoted_total_cents']}"
    assert data["redeemed_voucher_id"] == voucher["id"]
    got_voucher = validate_success(api.get_voucher(voucher["id"], CASHIER))
    assert got_voucher["status"] == "REDEEMED"


def test_payment_axis_stays_charged_through_reconciliation(api):
    """PRD §3.4: "A **SaleTicket** is opened by a `Cashier` and starts life with
    `payment_status` of `OPEN` and `reconciliation_status` of `UNRECONCILED` —
    two independent axes that advance separately."
    PRD §3.11: "every `SaleTicket` that is `CHARGED` and still `UNRECONCILED`
    advances on its reconciliation axis to `RECONCILED` (voided tickets are
    skipped entirely)."

    Design: Difficulty/non_linear_state_machine/sale_ticket_parallel_payment_reconciliation
    """
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    ticket = make_ticket(api)
    add_line(api, ticket["id"], flavor["id"], 7.3)
    do_checkout(api, ticket["id"])
    recon = make_reconciliation(api)
    validate_success(api.close_reconciliation(recon["id"], 402, MANAGER))
    got = validate_success(api.get_ticket(ticket["id"], CASHIER))
    assert got["payment_status"] == "CHARGED", \
        f"the payment axis must stay CHARGED after reconciliation, got {got['payment_status']}"


def test_reconciliation_axis_advances_to_reconciled(api):
    """PRD §3.11: "every `SaleTicket` that is `CHARGED` and still `UNRECONCILED`
    advances on its reconciliation axis to `RECONCILED` (voided tickets are
    skipped entirely)."

    Design: Difficulty/non_linear_state_machine/sale_ticket_parallel_payment_reconciliation
    """
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    ticket = make_ticket(api)
    add_line(api, ticket["id"], flavor["id"], 7.3)
    do_checkout(api, ticket["id"])
    recon = make_reconciliation(api)
    validate_success(api.close_reconciliation(recon["id"], 402, MANAGER))
    got = validate_success(api.get_ticket(ticket["id"], CASHIER))
    assert got["reconciliation_status"] == "RECONCILED", \
        f"the reconciliation axis must advance to RECONCILED at close, got {got['reconciliation_status']}"


def test_double_checkout_rejected(api):
    """PRD §3.5: "It requires the ticket to be `OPEN` (otherwise
    `ERR_TICKET_NOT_OPEN`) and to carry at least one cup (otherwise
    `ERR_EMPTY_TICKET`)."

    Design: Corner/state_machines/double_checkout_rejected
    """
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    ticket = make_ticket(api)
    add_line(api, ticket["id"], flavor["id"], 7.3)
    do_checkout(api, ticket["id"])
    resp = api.checkout(ticket["id"], {}, CASHIER)
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_OPEN.value)


def test_void_open_ticket_rejected(api):
    """PRD §3.6: "The void requires the ticket to be `CHARGED` (otherwise
    `ERR_TICKET_NOT_CHARGED`) and its `reconciliation_status` to still be
    `UNRECONCILED` (otherwise `ERR_TICKET_ALREADY_RECONCILED`) — once a ticket
    has been swept into a closed day it can no longer be voided."

    Design: Corner/state_machines/void_open_ticket_rejected
    """
    ticket = make_ticket(api)
    resp = api.void_ticket(ticket["id"], SHIFTLEAD)
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_CHARGED.value)
