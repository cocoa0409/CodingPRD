"""Order fork (void branch), validation precedence, allergen safety, drawer cash conservation.

Each test docstring cites the verbatim PRD sentence it asserts and ends with a
Design: traceability tag mapping it to its originating design-index instance.
"""
import pytest
from test_helpers import (
    validate_error,
    make_flavor, make_size, make_batch, make_loyalty, make_topping,
    open_drawer, open_order, add_line, pay,
    get_batch, get_flavor, get_drawer, get_order,
    api_client, get_success_data,
    TEST_USERS,
)

SCOOP = TEST_USERS["scooper_headers"]
LEAD = TEST_USERS["shift_lead_headers"]


# ─────────────── non_linear_state_machine / order_void_branch_releases_reservation_only ───────────────

def test_void_releases_reservation_without_cash_or_commit(api):
    """PRD 3.5: "Voiding moves every `ACTIVE` line to `REMOVED` and releases its
    soft hold by lowering each affected batch's `reserved_volume_ml`; because the
    lines were never committed, `remaining_volume_ml` is untouched, no cash moves,
    and no loyalty accrues."

    Design: Difficulty/non_linear_state_machine/order_void_branch_releases_reservation_only
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    batch = make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer(opening_float_cents=10000)
    order = open_order(drawer["id"])
    line = add_line(order["id"], size["id"], flavor["id"])
    voided = get_success_data(api.void_order(order["id"], LEAD))
    assert voided["status"] == "VOID"
    line_after = get_success_data(api.get_order_line(line["id"], LEAD))
    assert line_after["status"] == "REMOVED"
    b = get_batch(batch["id"])
    assert b["reserved_volume_ml"] == 0
    assert b["remaining_volume_ml"] == 500
    assert get_drawer(drawer["id"])["expected_cash_cents"] == 10000


def test_reservation_does_not_reduce_physical_volume_before_void(api):
    """PRD 2.7: "A reservation is a claim on future volume, not a consumption: it
    does **not** reduce `remaining_volume_ml`."
    PRD 2.7: "open-ticket reservations do **not** reduce `total_available_ml` —
    they only shrink per-batch headroom".

    Design: Difficulty/non_linear_state_machine/order_void_branch_releases_reservation_only
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    batch = make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    add_line(order["id"], size["id"], flavor["id"])
    b = get_batch(batch["id"])
    assert b["reserved_volume_ml"] == 180
    assert b["remaining_volume_ml"] == 500
    assert get_flavor(flavor["id"])["total_available_ml"] == 500
    # Voiding then releases the soft hold back to zero.
    get_success_data(api.void_order(order["id"], LEAD))
    assert get_batch(batch["id"])["reserved_volume_ml"] == 0


# ─────────────── priority_pair / state_beats_temporal_on_paid_order_line ───────────────

def test_state_error_precedes_out_of_season_on_paid_order(api):
    """PRD 2.8: "When a single request could fail multiple checks, the checks are
    evaluated in a fixed priority order, and the first failure encountered is the
    error returned. This ordering is a contract".
    PRD 2.8: "5. State legality — the target resource is in a legal state for the
    operation (409); the specific code depends on the resource, e.g.
    `ERR_ORDER_NOT_OPEN`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_paid_order_line
    """
    vanilla = make_flavor(name="Vanilla", par_level_ml=300)
    pumpkin = make_flavor(name="Pumpkin", is_seasonal=True,
                          seasonal_start_utc="2026-09-01T00:00:00Z",
                          seasonal_end_utc="2026-12-01T00:00:00Z", par_level_ml=300)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(vanilla["id"], initial_volume_ml=500)
    make_batch(pumpkin["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    add_line(order["id"], size["id"], vanilla["id"])
    pay(order["id"], payment_method="CARD")  # order now PAID (not OPEN)
    # Pumpkin is out of season at the default clock, but the state check fires first.
    res = api.add_line(order["id"], {"size_option_id": size["id"], "flavor_id": pumpkin["id"]}, SCOOP)
    validate_error(res, "ERR_ORDER_NOT_OPEN")


def test_state_error_precedes_insufficient_headroom_on_paid_order(api):
    """PRD 2.8: "the checks are evaluated in a fixed priority order, and the first
    failure encountered is the error returned. This ordering is a contract".
    PRD 2.8: "5. State legality — the target resource is in a legal state for the
    operation (409); the specific code depends on the resource, e.g.
    `ERR_ORDER_NOT_OPEN`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_paid_order_line
    """
    flavor = make_flavor(name="Vanilla", par_level_ml=300)
    single = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    double = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    make_batch(flavor["id"], initial_volume_ml=90)  # only 90 ml on hand
    drawer = open_drawer()
    order = open_order(drawer["id"])
    add_line(order["id"], single["id"], flavor["id"])  # reserves 90
    pay(order["id"], payment_method="CARD")  # commits all 90 -> PAID, batch depleted
    # A DOUBLE line would need 180 ml (headroom exhausted) AND the order is not OPEN;
    # the state check (step 5) precedes the headroom check (step 6).
    res = api.add_line(order["id"], {"size_option_id": double["id"], "flavor_id": flavor["id"]}, SCOOP)
    validate_error(res, "ERR_ORDER_NOT_OPEN")


# ─────────────── priority_pair / safety_beats_constraint_on_line_add (isolated allergen) ───────────────

def test_allergen_restriction_conflict_from_flavor(api):
    """PRD 3.3: "if the ticket carries a loyalty member, the line's `allergen_label`
    must not intersect that account's `allergen_restrictions`; any overlap rejects
    the line with `ERR_ALLERGEN_RESTRICTION_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_line_add
    """
    flavor = make_flavor(name="PB Swirl", allergens=["MILK", "PEANUT"], par_level_ml=300)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    make_batch(flavor["id"], initial_volume_ml=1000)  # ample headroom: only allergen can fail
    acct = make_loyalty(phone="555-0100", allergen_restrictions=["PEANUT"])
    drawer = open_drawer()
    order = open_order(drawer["id"], loyalty_account_id=acct["id"])
    res = api.add_line(order["id"], {"size_option_id": size["id"], "flavor_id": flavor["id"]}, SCOOP)
    validate_error(res, "ERR_ALLERGEN_RESTRICTION_CONFLICT")


def test_allergen_restriction_conflict_from_topping_in_label(api):
    """PRD 3.3: "The line also computes an `allergen_label`, the union of the
    flavor's `allergens` and the `allergens` of every applied topping."
    PRD 3.3: "the line's `allergen_label` must not intersect that account's
    `allergen_restrictions`; any overlap rejects the line with
    `ERR_ALLERGEN_RESTRICTION_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_line_add
    """
    flavor = make_flavor(name="Vanilla", allergens=["MILK"], par_level_ml=300)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    fudge = make_topping(name="Hot Fudge", price_cents=100, allergens=["SOY"])
    make_batch(flavor["id"], initial_volume_ml=1000)  # ample headroom
    acct = make_loyalty(phone="555-0101", allergen_restrictions=["SOY"])
    drawer = open_drawer()
    order = open_order(drawer["id"], loyalty_account_id=acct["id"])
    # Flavor carries no SOY, but the topping contributes SOY into allergen_label.
    res = api.add_line(order["id"],
                       {"size_option_id": size["id"], "flavor_id": flavor["id"],
                        "topping_ids": [fudge["id"]]}, SCOOP)
    validate_error(res, "ERR_ALLERGEN_RESTRICTION_CONFLICT")


# ─────────────── compensating_invariant / drawer_cash_conserved_across_pay_refund ───────────────

def test_cash_order_pay_then_refund_returns_expected_to_float(api):
    """PRD 3.8: "The drawer's `expected_cash_cents` is the `opening_float_cents`
    plus the sum of `cash_collected_cents` across the drawer's orders minus the sum
    of `cash_refunded_cents` across the drawer's orders".
    PRD 3.5: "the ticket records `cash_refunded_cents` — equal to `total_cents` when
    the original `payment_method` was `CASH` and zero otherwise".
    PRD 3.8: "`gross_sales_cents` is the sum of `total_cents` over the drawer's
    orders in `PAID` or `REFUNDED` status, while `net_sales_cents` is the sum of
    `total_cents` over orders in `PAID` status only."

    Design: Difficulty/compensating_invariant/drawer_cash_conserved_across_pay_refund
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer(opening_float_cents=10000)
    order = open_order(drawer["id"])
    add_line(order["id"], size["id"], flavor["id"])
    pay(order["id"], payment_method="CASH", tendered_cash_cents=400)  # total 381
    assert get_drawer(drawer["id"])["expected_cash_cents"] == 10381
    refunded = get_success_data(api.refund_order(order["id"], LEAD))
    assert refunded["cash_refunded_cents"] == 381
    d = get_drawer(drawer["id"])
    assert d["expected_cash_cents"] == 10000
    assert d["net_sales_cents"] == 0
    assert d["gross_sales_cents"] == 381


def test_card_order_refund_leaves_expected_cash_at_float(api):
    """PRD 3.8: "only cash movements adjust expected cash, and card sales do not."
    PRD 3.5: "the ticket records `cash_refunded_cents` — equal to `total_cents` when
    the original `payment_method` was `CASH` and zero otherwise".
    PRD 3.8: "`gross_sales_cents` is the sum of `total_cents` over the drawer's
    orders in `PAID` or `REFUNDED` status, while `net_sales_cents` is the sum of
    `total_cents` over orders in `PAID` status only."

    Design: Difficulty/compensating_invariant/drawer_cash_conserved_across_pay_refund
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer(opening_float_cents=10000)
    order = open_order(drawer["id"])
    add_line(order["id"], size["id"], flavor["id"])
    pay(order["id"], payment_method="CARD")  # total 381, card -> no cash moved
    assert get_drawer(drawer["id"])["expected_cash_cents"] == 10000
    refunded = get_success_data(api.refund_order(order["id"], LEAD))
    assert refunded["cash_refunded_cents"] == 0
    d = get_drawer(drawer["id"])
    assert d["expected_cash_cents"] == 10000
    assert d["gross_sales_cents"] == 381
    assert d["net_sales_cents"] == 0
