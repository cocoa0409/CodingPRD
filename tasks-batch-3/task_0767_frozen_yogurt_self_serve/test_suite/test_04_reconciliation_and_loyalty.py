"""Reconciliation close: dual-variant finalization, loyalty finalization,
voucher issuance, variance, and the loyalty/voucher checkout guards."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    setup_machine_flavor, make_promotion, make_ticket, add_line, do_checkout,
    make_loyalty, make_reconciliation, set_clock, CLOCK_DEFAULT,
    setup_issued_voucher,
)

MANAGER = TEST_USERS["manager_headers"]
SHIFTLEAD = TEST_USERS["shiftlead_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def _promo_ticket_charged(api, gross=7.3):
    """A charged single-line ticket under an active 10% promo. Returns (ticket_id)."""
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    make_promotion(api)
    ticket = make_ticket(api)
    add_line(api, ticket["id"], flavor["id"], gross)
    charged = do_checkout(api, ticket["id"])
    return charged


def test_quoted_variant_rounds_per_line_at_checkout(api):
    """PRD §3.5: "Each cup's `line_quoted_cents` is computed when the cup is
    added, as the net weight times the flavor's per-ounce price, scaled by the
    complement of the seasonal discount, rounded to whole cents, and then
    increased by the flat topping surcharges"

    Design: Difficulty/dual_variant_calc/sale_total_quoted_vs_finalized_rounding
    """
    charged = _promo_ticket_charged(api)
    assert charged["quoted_total_cents"] == 361, \
        f"QUOTED variant (round_half_up(7.3*55*0.9)=361) expected 361, got {charged['quoted_total_cents']}"


def test_finalized_variant_discounts_summed_base_at_close(api):
    """PRD §3.11: "for each cup, a `line_base` is the net weight times
    `price_per_oz_cents` rounded half up to whole cents, plus that cup's topping
    surcharges — with **no** discount applied per line; those `line_base` values
    are summed into `subtotal_base`; the seasonal discount active at the close is
    then applied **once** to that summed base, as `subtotal_base` multiplied by
    (one minus the discount fraction), rounded half up"

    Design: Difficulty/dual_variant_calc/sale_total_quoted_vs_finalized_rounding
    """
    charged = _promo_ticket_charged(api)
    recon = make_reconciliation(api)
    validate_success(api.close_reconciliation(recon["id"], 362, MANAGER))
    got = validate_success(api.get_ticket(charged["id"], CASHIER))
    assert got["final_total_cents"] == 362, \
        f"FINALIZED variant (round_half_up(402*0.9)=362) expected 362, got {got['final_total_cents']}"
    assert got["reconciliation_status"] == "RECONCILED"


def test_close_issues_voucher_and_drains_punch(api):
    """PRD §3.8: "Whenever `punch_count` reaches or exceeds the punch threshold
    of 10, the system issues one **RewardVoucher** and subtracts 10 from
    `punch_count` — so a single close that carries an account across the threshold
    both issues a voucher and leaves the remainder of the punches standing."
    PRD §3.8: "It records its owning `loyalty_account_id`, a fixed cash-off
    `value_cents` of 500, and an `expires_at` set to the issuing clock plus a
    time-to-live of 720 hours (thirty days)."

    Design: Difficulty/transitive_cascade/recon_close_ticket_loyalty_voucher
    """
    bundle = setup_issued_voucher(api)
    loyalty = validate_success(api.get_loyalty(bundle["loyalty"]["id"], CASHIER))
    assert loyalty["punch_count"] == 0, \
        f"crossing the threshold of 10 from 9 must leave punch_count at 0, got {loyalty['punch_count']}"
    vouchers, meta = validate_paginated(api.list_vouchers(CASHIER, params={"loyalty_account_id": loyalty["id"]}))
    assert len(vouchers) == 1, f"exactly one voucher must be issued, got {len(vouchers)}"
    assert vouchers[0]["status"] == "ISSUED"
    assert vouchers[0]["value_cents"] == 500


def test_close_finalizes_loyalty_points(api):
    """PRD §3.8: "For that ticket, the account's `points_lifetime` is increased
    by the ticket's `final_points`, its `points_provisional` is decreased by that
    ticket's `provisional_points` (draining the earlier provisional accrual), and
    its `punch_count` is increased by one."

    Design: Difficulty/transitive_cascade/recon_close_ticket_loyalty_voucher
    """
    bundle = setup_issued_voucher(api)
    loyalty = validate_success(api.get_loyalty(bundle["loyalty"]["id"], CASHIER))
    assert loyalty["points_lifetime"] == 4, \
        f"points_lifetime must rise by final_points floor(402/100)=4, got {loyalty['points_lifetime']}"
    assert loyalty["points_provisional"] == 0, \
        f"points_provisional must drain back to 0 at finalization, got {loyalty['points_provisional']}"
    got_ticket = validate_success(api.get_ticket(bundle["ticket"]["id"], CASHIER))
    assert got_ticket["reconciliation_status"] == "RECONCILED"


def test_checkout_rejected_for_suspended_loyalty(api):
    """PRD §3.5: "If a `loyalty_account_id` is attached, that account must be
    `ACTIVE`, or checkout fails with `ERR_LOYALTY_ACCOUNT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/checkout_requires_loyalty_active
    """
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    loyalty = make_loyalty(api)
    ticket = make_ticket(api, loyalty_account_id=loyalty["id"])
    add_line(api, ticket["id"], flavor["id"], 7.3)
    validate_success(api.suspend_loyalty(loyalty["id"], MANAGER))
    resp = api.checkout(ticket["id"], {}, CASHIER)
    validate_error(resp, ApiErrorId.ERR_LOYALTY_ACCOUNT_SUSPENDED.value)


def test_checkout_rejected_for_suspended_loyalty_leaves_ticket_open(api):
    """PRD §3.5: "Checkout is performed by a `Cashier` and advances the ticket's
    `payment_status` from `OPEN` to `CHARGED`. It requires the ticket to be
    `OPEN` (otherwise `ERR_TICKET_NOT_OPEN`) and to carry at least one cup
    (otherwise `ERR_EMPTY_TICKET`). If a `loyalty_account_id` is attached, that
    account must be `ACTIVE`, or checkout fails with
    `ERR_LOYALTY_ACCOUNT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/checkout_requires_loyalty_active
    """
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    loyalty = make_loyalty(api)
    ticket = make_ticket(api, loyalty_account_id=loyalty["id"])
    add_line(api, ticket["id"], flavor["id"], 7.3)
    validate_success(api.suspend_loyalty(loyalty["id"], MANAGER))
    resp = api.checkout(ticket["id"], {}, CASHIER)
    validate_error(resp, ApiErrorId.ERR_LOYALTY_ACCOUNT_SUSPENDED.value)
    got = validate_success(api.get_ticket(ticket["id"], CASHIER))
    assert got["payment_status"] == "OPEN", \
        f"a rejected checkout must leave payment_status OPEN, got {got['payment_status']}"


def test_void_reverses_provisional_points(api):
    """PRD §3.6: "if a loyalty account is attached, its `points_provisional` is
    reduced by the ticket's `provisional_points`; and if a voucher had been
    redeemed, that voucher reverts from `REDEEMED` back to `ISSUED` (un-redeemed
    and reusable)."

    Design: Difficulty/compensating_invariant/void_conserves_provisional_points
    """
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    loyalty = make_loyalty(api)
    ticket = make_ticket(api, loyalty_account_id=loyalty["id"])
    add_line(api, ticket["id"], flavor["id"], 7.3)
    do_checkout(api, ticket["id"])
    validate_success(api.void_ticket(ticket["id"], SHIFTLEAD))
    got = validate_success(api.get_loyalty(loyalty["id"], CASHIER))
    assert got["points_provisional"] == 0, \
        f"void must reverse provisional points back to 0, got {got['points_provisional']}"


def test_checkout_accrues_then_void_reverses_provisional_points(api):
    """PRD §3.5: "The ticket's `provisional_points` is the floor of
    `quoted_total_cents` divided by 100 — one point per whole hundred cents
    charged. When a loyalty account is attached, that account's
    `points_provisional` is increased by this same amount, reflecting points that
    are earned but not yet finalized."

    Design: Difficulty/compensating_invariant/void_conserves_provisional_points
    """
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    loyalty = make_loyalty(api)
    ticket = make_ticket(api, loyalty_account_id=loyalty["id"])
    add_line(api, ticket["id"], flavor["id"], 7.3)
    do_checkout(api, ticket["id"])
    after_checkout = validate_success(api.get_loyalty(loyalty["id"], CASHIER))
    assert after_checkout["points_provisional"] == 4, \
        f"checkout must accrue floor(402/100)=4 provisional points, got {after_checkout['points_provisional']}"
    validate_success(api.void_ticket(ticket["id"], SHIFTLEAD))
    after_void = validate_success(api.get_loyalty(loyalty["id"], CASHIER))
    assert after_void["points_provisional"] == 0, \
        f"void must return provisional points to 0, got {after_void['points_provisional']}"


def test_reconciliation_cash_variance_computed(api):
    """PRD §3.11: "The `expected_revenue_cents` is the sum of `final_total_cents`
    over exactly the tickets whose `reconciliation_id` equals this reconciliation,
    plus the sum of the `amount_cents` of every posted adjustment. The
    `cash_variance_cents` is the `counted_cash_cents` minus
    `expected_revenue_cents`."

    Design: Corner/calculations/reconciliation_cash_variance_computed
    """
    set_clock(api, CLOCK_DEFAULT)
    machine, flavor = setup_machine_flavor(api)
    ticket = make_ticket(api)
    add_line(api, ticket["id"], flavor["id"], 7.3)
    do_checkout(api, ticket["id"])
    recon = make_reconciliation(api)
    closed = validate_success(api.close_reconciliation(recon["id"], 500, MANAGER))
    assert closed["expected_revenue_cents"] == 402, \
        f"expected_revenue must equal the one ticket's final_total 402, got {closed['expected_revenue_cents']}"
    assert closed["cash_variance_cents"] == 98, \
        f"cash_variance must be 500-402=98, got {closed['cash_variance_cents']}"


def test_cashier_cannot_close_reconciliation(api):
    """PRD §2.1: "When an operator attempts an action their role does not
    authorize, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/cashier_cannot_close_reconciliation
    """
    recon = make_reconciliation(api)
    resp = api.close_reconciliation(recon["id"], 0, CASHIER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
