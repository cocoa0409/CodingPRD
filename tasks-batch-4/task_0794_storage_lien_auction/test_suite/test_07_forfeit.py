"""Forfeiture of an unpaid sale: deposit forfeiture cascade to the facility."""
from test_helpers import (
    validate_success,
    make_platform_admin_headers,
    set_clock, setup_sale,
    CLOCK_PAST_PAYMENT_DEADLINE,
)

ADMIN = make_platform_admin_headers()


def _forfeit_unpaid_sale(api):
    """A Sale created at close (20000 deposit held), forfeited after the payment
    deadline. Returns the ctx from setup_sale."""
    ctx = setup_sale(api)
    set_clock(api, CLOCK_PAST_PAYMENT_DEADLINE)  # 2026-03-25 > payment_deadline 2026-03-24
    validate_success(api.forfeit_sale(ctx["sale_id"], ctx["fac_hdr"]))
    return ctx


def test_forfeit_forfeits_deposit_and_suspends_buyer(api):
    """PRD §3.7: "The held deposit is forfeited: the buyer's `deposit_held_cents` is
    reduced by 20000 cents and its `deposit_forfeited_cents` is increased by 20000
    cents, and the facility's `recovery_balance_cents` is increased by that forfeited
    20000 cents."
    PRD §3.7: "The unit returns from `SOLD` to `LIEN_MATURED`, and the buyer's
    `status` moves from `REGISTERED` to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/forfeit_cascade_deposit_to_facility
    """
    ctx = _forfeit_unpaid_sale(api)
    buyer = validate_success(api.get_buyer(ctx["buyer_id"], ADMIN))
    assert buyer["deposit_held_cents"] == 0
    assert buyer["deposit_forfeited_cents"] == 20000
    assert buyer["status"] == "SUSPENDED"


def test_forfeit_credits_facility_and_reverts_unit(api):
    """PRD §3.7: "When the buyer never paid — the sale is still `UNPAID` and the
    logical clock now is strictly past the `payment_deadline` — forfeiture moves
    `payment_status` from `UNPAID` to `FORFEITED` and moves `cleanout_status` from
    `PENDING` to `VOIDED`."
    PRD §3.7: "The held deposit is forfeited: the buyer's `deposit_held_cents` is
    reduced by 20000 cents and its `deposit_forfeited_cents` is increased by 20000
    cents, and the facility's `recovery_balance_cents` is increased by that forfeited
    20000 cents."

    Design: Difficulty/transitive_cascade/forfeit_cascade_deposit_to_facility
    """
    ctx = _forfeit_unpaid_sale(api)
    sale = validate_success(api.get_sale(ctx["sale_id"], ADMIN))
    assert sale["payment_status"] == "FORFEITED"
    assert sale["cleanout_status"] == "VOIDED"
    facility = validate_success(api.get_facility(ctx["fac"], ADMIN))
    assert facility["recovery_balance_cents"] == 20000
    unit = validate_success(api.get_unit(ctx["unit_id"], ADMIN))
    assert unit["status"] == "LIEN_MATURED"
