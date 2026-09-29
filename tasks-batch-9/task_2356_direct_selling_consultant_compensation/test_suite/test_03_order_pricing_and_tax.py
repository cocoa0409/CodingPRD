"""Order pricing: per-line tax rounding, the jurisdiction snapshot and the shipping threshold."""

from test_helpers import (
    assert_product_order,
    constants as k,
    factories as f,
    find_line,
    fixtures as fx,
    make_consultant_headers,
    TEST_USERS,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _place(api, consultant, lines, order_type="BUSINESS_SUPPLY", state_code="TX", headers=None):
    """Create an order through the endpoint and assert the documented 201."""
    payload = f.product_order_payload(
        consultant["id"],
        lines,
        order_type=order_type,
        posted_period_code=k.PERIOD_2026_08["period_code"],
        ship_to_state_code=state_code,
    )
    response = api.create_product_order(
        payload, headers or make_consultant_headers(consultant["id"])
    )
    return validate_success(response, 201)


def test_line_tax_rounds_on_the_line_so_two_lines_beat_one_aggregate_basis(api):
    """Two 5-unit lines round to 83 cents each and sum to 166 while the identical
    single 10-unit line rounds its 2,000-cent basis once to 165.

    PRD: "`tax_total_cents` is the sum of the already-rounded `line_tax_cents` values; the
    rate is never applied to the order-level basis, because summing rounded lines and
    rounding a summed basis give different answers and only the former is correct here."

    Design: Difficulty/combinatorial_formula/order_tax_rounded_per_line_then_summed_beats_aggregate_basis
    """
    env = fx.setup_environment(api, products=fx.ALL_PRODUCTS)
    mona = fx.enroll_root(api, env, "mona@example.com", "Mona Root")

    split = _place(api, mona, fx.lines_for(env, ("SAMPLE", 5), ("SACHET", 5)))
    single = _place(api, mona, fx.lines_for(env, ("SAMPLE", 10)))

    assert split["srp_basis_cents"] == 2000, "five plus five units carry a 2,000-cent SRP basis"
    assert single["srp_basis_cents"] == 2000, "ten units carry the identical 2,000-cent SRP basis"

    sample_line = find_line(split, env["products"]["SAMPLE"]["id"])
    sachet_line = find_line(split, env["products"]["SACHET"]["id"])
    assert sample_line["line_tax_cents"] == 83, "each 1,000-cent line basis rounds to 83 cents"
    assert sachet_line["line_tax_cents"] == 83, "the second line rounds to 83 cents in its own right"

    assert split["tax_total_cents"] == 166, "the two rounded lines sum to 166 cents of tax"
    assert single["tax_total_cents"] == 165, "one 2,000-cent basis rounds once to 165 cents"
    assert split["tax_total_cents"] - single["tax_total_cents"] == 1, (
        "rounding before summation costs exactly one cent more than rounding after"
    )

    assert split["total_due_cents"] == 2161, "1,000 merchandise plus 166 tax plus 995 shipping"
    assert single["total_due_cents"] == 2160, "1,000 merchandise plus 165 tax plus 995 shipping"


def test_two_orders_with_the_same_basis_share_every_snapshot_but_the_tax_total(api):
    """The split and single orders agree on merchandise, points, jurisdiction snapshot and
    both status dimensions, isolating the one-cent tax divergence.

    PRD: "`line_tax_cents` is that basis multiplied by the snapshotted `tax_rate_bp`, divided
    by 10,000 and rounded half up **on the line**".

    Design: Difficulty/combinatorial_formula/order_tax_rounded_per_line_then_summed_beats_aggregate_basis
    """
    env = fx.setup_environment(api, products=fx.ALL_PRODUCTS)
    mona = fx.enroll_root(api, env, "mona@example.com", "Mona Root")

    split = _place(api, mona, fx.lines_for(env, ("SAMPLE", 5), ("SACHET", 5)))
    single = _place(api, mona, fx.lines_for(env, ("SAMPLE", 10)))

    for order, label in ((split, "split order"), (single, "single-line order")):
        assert_product_order(order)
        assert order["merchandise_subtotal_cents"] == 1000, (
            f"{label}: ten units at 100 cents wholesale is 1,000 cents"
        )
        assert order["shipping_cents"] == 995, (
            f"{label}: 1,000 cents of merchandise is below the 25,000-cent free-shipping threshold"
        )
        assert order["total_volume_points"] == 10, f"{label}: ten units at one point each"
        assert order["commissionable_volume_points"] == 10, (
            f"{label}: both products are commissionable"
        )
        assert order["tax_basis_mode"] == "SRP", f"{label}: TX holds a facilitator agreement"
        assert order["tax_rate_bp"] == 825, f"{label}: the snapshotted TX rate"
        assert order["payment_status"] == "PENDING", f"{label}: a new order is unpaid"
        assert order["fulfillment_status"] == "NEW", f"{label}: a new order is unshipped"

    assert split["tax_total_cents"] != single["tax_total_cents"], (
        "the only field the two orders disagree on is the tax total"
    )


def test_facilitator_flag_switches_the_tax_basis_for_otherwise_identical_orders(api):
    """Two 5-SERUM orders differing only in ship_to_state_code are taxed on suggested retail
    in TX and on wholesale in NV, and each freezes its own snapshot.

    PRD: "Pricing an admitted order begins by snapshotting the jurisdiction registered for
    `ship_to_state_code`: `tax_basis_mode`, `tax_remitter` and `tax_rate_bp` on the order are
    copies of that jurisdiction's basis mode, remitter and rate at the moment of creation, and
    later edits to the jurisdiction never reprice a placed order."

    Design: Corner/validations/facilitator_flag_switches_the_tax_basis_for_otherwise_identical_orders
    """
    env = fx.setup_environment_both_states(api)
    alice = fx.enroll_root(api, env)

    tx_order = _place(api, alice, fx.lines_for(env, ("SERUM", 5)), headers=ADMIN, state_code="TX")
    nv_order = _place(api, alice, fx.lines_for(env, ("SERUM", 5)), headers=ADMIN, state_code="NV")

    assert tx_order["tax_basis_mode"] == "SRP", "a facilitator agreement selects the SRP basis"
    assert tx_order["tax_remitter"] == "COMPANY", (
        "the remitter is COMPANY when a facilitator agreement is active"
    )
    assert tx_order["tax_rate_bp"] == 825, "the TX rate is snapshotted onto the order"
    assert tx_order["srp_basis_cents"] == 20000, "five units at 4,000 cents suggested retail"
    assert tx_order["tax_total_cents"] == 1650, "825 basis points on the 20,000-cent SRP basis"
    assert tx_order["total_due_cents"] == 12645, (
        "10,000 merchandise plus 1,650 tax plus 995 shipping"
    )

    assert nv_order["tax_basis_mode"] == "NET_PRICE", "without a facilitator agreement tax rides wholesale"
    assert nv_order["tax_remitter"] == "CONSULTANT", (
        "the remitter is CONSULTANT when no facilitator agreement is active"
    )
    assert nv_order["tax_rate_bp"] == 685, "the NV rate is snapshotted onto the order"
    assert nv_order["srp_basis_cents"] == 20000, (
        "the suggested-retail roll-up is still recorded under the NET_PRICE basis"
    )
    assert nv_order["tax_total_cents"] == 685, "685 basis points on the 10,000-cent wholesale basis"
    assert nv_order["total_due_cents"] == 11680, (
        "10,000 merchandise plus 685 tax plus 995 shipping"
    )

    assert tx_order["consultant_id"] == nv_order["consultant_id"], (
        "the same consultant, product and quantity produced two different tax bases"
    )
    assert tx_order["merchandise_subtotal_cents"] == nv_order["merchandise_subtotal_cents"] == 10000, (
        "the merchandise subtotal is identical: only the jurisdiction flag differs"
    )


def test_an_order_satisfying_every_check_is_accepted_and_payment_posts_volume(api):
    """A 30-SERUM personal-inventory order clears all four placement rules, and paying it in
    full creates the qualification row without any lock.

    PRD: "Payment is where volume enters the compensation system."

    Design: Corner/validations/an_order_satisfying_every_check_is_accepted_and_posts_volume
    """
    env = fx.setup_environment(api)
    alice = fx.enroll_root(api, env)
    period = env["periods"]["2026-08"]

    order = _place(api, alice, fx.lines_for(env, ("SERUM", 30)), order_type="PERSONAL_INVENTORY")
    assert order["total_due_cents"] == 69900, (
        "60,000 merchandise plus 9,900 tax with no shipping at or above the threshold"
    )
    assert order["payment_status"] == "PENDING", "volume is not posted until money arrives"
    assert order["volume_posted"] is False, "volume_posted starts false"

    paid = validate_success(
        api.pay_product_order(
            order["id"],
            f.pay_order_payload(69900, "PAY-OK"),
            make_consultant_headers(alice["id"]),
        )
    )
    assert paid["payment_status"] == "PAID", "the exact amount is accepted"
    assert paid["volume_posted"] is True, "payment posts the order's volume"
    assert paid["payment_reference"] == "PAY-OK", "the submitted reference is recorded"

    qualification = fx.qualification_of(api, alice["id"], period["id"])
    assert qualification["personal_volume_points"] == 600, "thirty units at twenty points each"
    assert qualification["inventory_volume_points"] == 600, (
        "a PERSONAL_INVENTORY order books its points as inventory volume"
    )
    assert qualification["retail_volume_points"] == 0, "no retail order was placed"
    assert fx.read_period(api, period["id"])["status"] == "OPEN", (
        "the qualification row appeared without any lock"
    )


def test_free_shipping_threshold_is_exclusive_so_a_smaller_order_costs_more(api):
    """250 SAMPLE lands exactly on the 25,000-cent threshold and ships free, while 249 pays
    flat shipping and therefore costs 879 cents more.

    PRD: "`shipping_cents` is the plan's `flat_shipping_cents` when `merchandise_subtotal_cents`
    is strictly below the plan's `free_shipping_threshold_cents`, and 0 when it is at or above
    that threshold."

    Design: Corner/calculations/free_shipping_threshold_is_exclusive_and_makes_a_smaller_order_dearer
    """
    env = fx.setup_environment(api)
    at_threshold = fx.enroll_root(api, env, "atthreshold@example.com", "Ada Threshold")
    below = fx.enroll_consultant(api, env, "below@example.com", "Ben Below")

    at_order = _place(api, at_threshold, fx.lines_for(env, ("SAMPLE", 250)), headers=ADMIN)
    below_order = _place(api, below, fx.lines_for(env, ("SAMPLE", 249)), headers=ADMIN)

    assert at_order["merchandise_subtotal_cents"] == 25000, "250 units at 100 cents wholesale"
    assert at_order["shipping_cents"] == 0, "landing exactly on 25,000 cents ships free"
    assert at_order["tax_total_cents"] == 4125, "825 basis points on the 50,000-cent SRP basis"
    assert at_order["total_due_cents"] == 29125, "25,000 merchandise plus 4,125 tax plus no shipping"

    assert below_order["merchandise_subtotal_cents"] == 24900, "one unit short of the threshold"
    assert below_order["shipping_cents"] == 995, "strictly below the threshold charges flat shipping"
    assert below_order["tax_total_cents"] == 4109, (
        "825 basis points on 49,800 cents is 4,108.5, which rounds half up to 4,109"
    )
    assert below_order["total_due_cents"] == 30004, (
        "24,900 merchandise plus 4,109 tax plus 995 shipping"
    )

    assert below_order["total_due_cents"] - at_order["total_due_cents"] == 879, (
        "buying one unit less costs 879 cents more, so the threshold is non-monotonic"
    )
