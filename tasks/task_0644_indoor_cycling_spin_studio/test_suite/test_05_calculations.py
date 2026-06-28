"""Money/credit calculations: pack refunds (CLASS_PACK unused-value & MEMBERSHIP
prorata), retail tiered pricing with wallet split, strike accumulation, first-ride comp,
and the compensating (conserved-quantity) invariants.

Translates queue-A `dual_variant_calc`, `combinatorial_formula`, `compensating_invariant`
and queue-B `calculations` instances.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    make_member_headers,
    make_instructor_headers,
    fixtures,
)

MGR = TEST_USERS["studio_manager_headers"]


def _accumulate_class_pack_consumed(ctx_estate, member, pack, n_rides, start_day=2):
    """Book + attend n_rides on distinct sessions to drive pack.consumed_credits up."""
    studio_id = ctx_estate["studio"]["id"]
    bike_id = ctx_estate["bikes"][0]["id"]
    instr_id = ctx_estate["instructor"]["id"]
    for i in range(n_rides):
        day = start_day + i
        s = fixtures.create_session(
            studio_id, ctx_estate["room"]["id"], instr_id,
            start_utc=f"2026-06-{day:02d}T10:00:00Z", end_utc=f"2026-06-{day:02d}T11:00:00Z",
        )
        r = fixtures.book(studio_id, s["id"], member["id"], bike_id, s["version"])
        fixtures.set_clock(f"2026-06-{day:02d}T10:30:00Z")
        fixtures.check_in(studio_id, s["id"], r["id"], instr_id)


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / pack_refund_class_pack_unused_value
# ---------------------------------------------------------------------------
def test_class_pack_refund_unused_value(api):
    """PRD 3.9: "For a `CLASS_PACK` the refund is *unused-value* based and ignores
    elapsed time: the per-credit value is the pack's `price_cents` divided by its
    `purchased_credits`, rounded half-up to whole cents, and the refund is that
    per-credit value multiplied by the pack's remaining credits, where remaining credits
    are recomputed at refund time as purchased minus consumed."

    Design: Difficulty/dual_variant_calc/pack_refund_class_pack_unused_value
    """
    # 10-credit pack for 10000 (per-credit 1000); consume 3 -> remaining 7 -> refund 7000.
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    member, pack = fixtures.setup_member_with_pack(
        studio_id, purchased_credits=10, price_cents=10000
    )
    # First ride is comped, so to consume 3 real credits we attend 4 rides (1 comp + 3 paid).
    _accumulate_class_pack_consumed(estate, member, pack, n_rides=4, start_day=2)
    after = fixtures.get_pack(pack["id"], member["id"])
    assert after["remaining_credits"] == 7
    pack_v = after["version"]
    resp = api.refund_credit_pack(pack["id"], {"expected_pack_version": pack_v}, MGR)
    refunded = validate_success(resp)
    assert refunded["status"] == "REFUNDED"
    assert refunded["remaining_credits"] == 7
    member_after = fixtures.get_member(member["id"])
    assert member_after["wallet_credit_cents"] == 7000


def test_class_pack_refund_zero_consumed_full_value(api):
    """PRD 3.9: "the refund is that per-credit value multiplied by the pack's remaining
    credits, where remaining credits are recomputed at refund time as purchased minus
    consumed."
    PRD 3.9: "A successful refund credits the computed amount to the member's
    `wallet_credit_cents`, moves the pack to `REFUNDED` (terminal)".

    Design: Difficulty/dual_variant_calc/pack_refund_class_pack_unused_value
    """
    # 10-credit pack for 10000, nothing consumed -> remaining 10 -> refund 10000.
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio()
    member, pack = fixtures.setup_member_with_pack(
        studio["id"], purchased_credits=10, price_cents=10000
    )
    resp = api.refund_credit_pack(pack["id"], {"expected_pack_version": pack["version"]}, MGR)
    refunded = validate_success(resp)
    assert refunded["status"] == "REFUNDED"
    assert fixtures.get_member(member["id"])["wallet_credit_cents"] == 10000


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / member_strike_threshold_count
# ---------------------------------------------------------------------------
def test_member_strike_count_three_suspends(api):
    """PRD 2.9: "the active strike count is the number of penalty charges belonging to
    the member that count as a strike, have not been waived, and whose charge time falls
    on or after the start of that 30-day window and on or before the current clock
    instant."
    PRD 2.9: "When a newly created strike-bearing charge causes the active strike count
    to reach three or more, the member's account transitions from `ACTIVE` to
    `SUSPENDED`."

    Design: Difficulty/dual_variant_calc/member_strike_threshold_count
    """
    ctx = fixtures.setup_member_with_late_cancels(num_strikes=3, final_strike=True)
    member = fixtures.get_member(ctx["member"]["id"])
    assert member["active_strike_count"] == 3
    assert member["account_status"] == "SUSPENDED"


def test_member_strike_count_within_window_counted(api):
    """PRD 2.9: "A penalty charge marked as counting toward strikes contributes to a
    member's `active_strike_count` for a fixed trailing window of 30 days measured
    backward from the current logical-clock instant."

    Design: Difficulty/dual_variant_calc/member_strike_threshold_count
    """
    # Two late cancels within window -> count == 2.
    ctx = fixtures.setup_member_with_late_cancels(num_strikes=2, final_strike=True)
    member = fixtures.get_member(ctx["member"]["id"])
    assert member["active_strike_count"] == 2


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / retail_total_tier_then_wallet_split
# ---------------------------------------------------------------------------
def test_retail_tier_then_wallet_split(api):
    """PRD 3.10: "a quantity of 6 or more units earns a 10 percent discount. The
    discounted total is the subtotal minus the discount, where the discount is the
    subtotal multiplied by the chosen percentage and rounded half-up to whole cents.
    Payment is then split: if `pay_from_wallet` is true, the `wallet_applied_cents` is
    the smaller of the member's `wallet_credit_cents` and the discounted total, and the
    `card_charged_cents` is the discounted total minus that wallet portion".

    Design: Difficulty/combinatorial_formula/retail_total_tier_then_wallet_split
    """
    # Build a member with wallet 2000 (via a late-cancel fee waive), then order qty 6 @1000.
    ctx = fixtures.setup_booked_reservation(
        n_bikes=1, start_utc="2026-06-05T18:00:00Z", end_utc="2026-06-05T19:00:00Z",
    )
    studio_id = ctx["studio"]["id"]
    member_id = ctx["member"]["id"]
    fixtures.set_clock("2026-06-05T12:00:00Z")  # late window
    fixtures.cancel_reservation(studio_id, ctx["session"]["id"], ctx["reservation"]["id"], member_id)
    # Waive the 2000-cent late fee -> wallet becomes 2000.
    charges = validate_success(
        api.list_penalty_charges(make_member_headers(member_id), params={"member_id": member_id})
    )
    charge_id = charges[0]["id"]
    api.waive_penalty_charge(charge_id, MGR)
    assert fixtures.get_member(member_id)["wallet_credit_cents"] == 2000
    # Stock a product 1000 cents and order qty 6 with wallet.
    product = fixtures.create_product(
        studio_id, sku="BOTTLE", name="Water Bottle", unit_price_cents=1000, stock_qty=10
    )
    resp = api.create_retail_order(
        {
            "member_id": member_id,
            "studio_id": studio_id,
            "product_id": product["id"],
            "quantity": 6,
            "pay_from_wallet": True,
        },
        make_member_headers(member_id),
    )
    order = validate_success(resp, expected_status=201)
    # subtotal 6000; 10% discount -> discounted 5400; wallet 2000 -> card 3400.
    assert order["subtotal_cents"] == 6000
    assert order["wallet_applied_cents"] == 2000
    assert order["card_charged_cents"] == 3400
    assert fixtures.get_member(member_id)["wallet_credit_cents"] == 0


def test_retail_wallet_covers_entire_discounted_total(api):
    """PRD 3.10: "if `pay_from_wallet` is true, the `wallet_applied_cents` is the
    smaller of the member's `wallet_credit_cents` and the discounted total, and the
    `card_charged_cents` is the discounted total minus that wallet portion".
    PRD 3.10: "a quantity of at least 3 but fewer than 6 units earns a 5 percent
    discount."

    Design: Difficulty/combinatorial_formula/retail_total_tier_then_wallet_split
    """
    # Wallet 2000 covers an order whose discounted total is below 2000.
    ctx = fixtures.setup_booked_reservation(
        n_bikes=1, start_utc="2026-06-05T18:00:00Z", end_utc="2026-06-05T19:00:00Z",
    )
    studio_id = ctx["studio"]["id"]
    member_id = ctx["member"]["id"]
    fixtures.set_clock("2026-06-05T12:00:00Z")
    fixtures.cancel_reservation(studio_id, ctx["session"]["id"], ctx["reservation"]["id"], member_id)
    charges = validate_success(
        api.list_penalty_charges(make_member_headers(member_id), params={"member_id": member_id})
    )
    api.waive_penalty_charge(charges[0]["id"], MGR)
    assert fixtures.get_member(member_id)["wallet_credit_cents"] == 2000
    # qty 3 @500 = 1500 subtotal; 5% discount = 75 -> discounted 1425.
    product = fixtures.create_product(
        studio_id, sku="SOCK", name="Grip Socks", unit_price_cents=500, stock_qty=10
    )
    resp = api.create_retail_order(
        {
            "member_id": member_id,
            "studio_id": studio_id,
            "product_id": product["id"],
            "quantity": 3,
            "pay_from_wallet": True,
        },
        make_member_headers(member_id),
    )
    order = validate_success(resp, expected_status=201)
    assert order["subtotal_cents"] == 1500
    assert order["wallet_applied_cents"] == 1425  # min(2000, 1425)
    assert order["card_charged_cents"] == 0
    assert fixtures.get_member(member_id)["wallet_credit_cents"] == 575


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / pack_refund_round_per_credit_then_multiply
# ---------------------------------------------------------------------------
def test_pack_refund_round_per_credit_then_multiply(api):
    """PRD 3.9: "the per-credit value is the pack's `price_cents` divided by its
    `purchased_credits`, rounded half-up to whole cents, and the refund is that
    per-credit value multiplied by the pack's remaining credits".
    PRD 2.6: "Wherever a calculation produces a fractional cent ... the result is rounded
    to a whole number of cents using the round-half-up convention".

    Design: Difficulty/combinatorial_formula/pack_refund_round_per_credit_then_multiply
    """
    # 10000 over 3 credits -> per-credit round_half_up(3333.33)=3333; consume 1 -> remaining 2;
    # refund 3333*2 = 6666 (NOT round(10000*2/3)=6667).
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    member, pack = fixtures.setup_member_with_pack(
        studio_id, purchased_credits=3, price_cents=10000
    )
    # First ride comped, so 2 rides leave consumed at 1 real credit -> remaining 2.
    _accumulate_class_pack_consumed(estate, member, pack, n_rides=2, start_day=2)
    after = fixtures.get_pack(pack["id"], member["id"])
    assert after["remaining_credits"] == 2
    resp = api.refund_credit_pack(pack["id"], {"expected_pack_version": after["version"]}, MGR)
    validate_success(resp)
    assert fixtures.get_member(member["id"])["wallet_credit_cents"] == 6666


def test_pack_refund_round_per_credit_seven_credits(api):
    """PRD 3.9: "the per-credit value is the pack's `price_cents` divided by its
    `purchased_credits`, rounded half-up to whole cents, and the refund is that
    per-credit value multiplied by the pack's remaining credits".

    Design: Difficulty/combinatorial_formula/pack_refund_round_per_credit_then_multiply
    """
    # 10000 over 7 credits -> per-credit round_half_up(1428.57)=1429; consume 2 real
    # credits -> remaining 5; refund 1429*5 = 7145 (NOT round(10000*5/7)=7143).
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    member, pack = fixtures.setup_member_with_pack(
        studio_id, purchased_credits=7, price_cents=10000
    )
    # 3 rides: first comped, two paid -> consumed 2 -> remaining 5.
    _accumulate_class_pack_consumed(estate, member, pack, n_rides=3, start_day=2)
    after = fixtures.get_pack(pack["id"], member["id"])
    assert after["remaining_credits"] == 5
    resp = api.refund_credit_pack(pack["id"], {"expected_pack_version": after["version"]}, MGR)
    validate_success(resp)
    assert fixtures.get_member(member["id"])["wallet_credit_cents"] == 7145


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / early_cancel_conserves_pack_credits
# ---------------------------------------------------------------------------
def test_early_cancel_conserves_pack_credits(api):
    """PRD 3.5: "An **early** cancellation moves attendance to `EARLY_CANCELLED` and
    billing to `CREDIT_REFUNDED`. If a `CLASS_PACK` was charged, its `consumed_credits`
    is decremented by one and an `EXHAUSTED` pack thereby returns to `ACTIVE` (the
    conserved-credit invariant)."

    Design: Difficulty/compensating_invariant/early_cancel_conserves_pack_credits
    """
    # 5-credit pack. First ride is comped, so to get a real debit the member must already
    # have ridden once. Use a checked-in first ride, then book a second (real debit), then
    # early-cancel the second -> consumed returns to 0.
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    member, pack = fixtures.setup_member_with_pack(studio_id, purchased_credits=5, price_cents=5000)
    # First ride (comp).
    s1 = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc="2026-06-02T10:00:00Z", end_utc="2026-06-02T11:00:00Z",
    )
    r1 = fixtures.book(studio_id, s1["id"], member["id"], estate["bikes"][0]["id"], s1["version"])
    fixtures.set_clock("2026-06-02T10:30:00Z")
    fixtures.check_in(studio_id, s1["id"], r1["id"], estate["instructor"]["id"])
    # Second ride debits one credit (remaining 4).
    s2 = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc="2026-06-20T18:00:00Z", end_utc="2026-06-20T19:00:00Z",
    )
    r2 = fixtures.book(studio_id, s2["id"], member["id"], estate["bikes"][0]["id"], s2["version"])
    mid = fixtures.get_pack(pack["id"], member["id"])
    assert mid["remaining_credits"] == 4
    # Early-cancel the second booking -> credit conserved back to 5, consumed back to 0.
    fixtures.set_clock("2026-06-19T00:00:00Z")
    cancelled = fixtures.cancel_reservation(studio_id, s2["id"], r2["id"], member["id"])
    assert cancelled["attendance_status"] == "EARLY_CANCELLED"
    final = fixtures.get_pack(pack["id"], member["id"])
    assert final["consumed_credits"] == 0
    assert final["remaining_credits"] == 5


def test_session_cancel_conserves_pack_credits(api):
    """PRD 3.2: "as a consequence of each such refund, any class-pack that had been
    charged has its `consumed_credits` decremented by one, and a pack that was sitting in
    `EXHAUSTED` returns to `ACTIVE`."

    Design: Difficulty/compensating_invariant/early_cancel_conserves_pack_credits
    """
    # Same conserved quantity (pack credits) restored by a studio session-cancel refund.
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    member, pack = fixtures.setup_member_with_pack(studio_id, purchased_credits=5, price_cents=5000)
    # First ride comp + check-in, then a real-credit booking on a future session.
    s1 = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc="2026-06-02T10:00:00Z", end_utc="2026-06-02T11:00:00Z",
    )
    r1 = fixtures.book(studio_id, s1["id"], member["id"], estate["bikes"][0]["id"], s1["version"])
    fixtures.set_clock("2026-06-02T10:30:00Z")
    fixtures.check_in(studio_id, s1["id"], r1["id"], estate["instructor"]["id"])
    s2 = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc="2026-06-20T18:00:00Z", end_utc="2026-06-20T19:00:00Z",
    )
    fixtures.book(studio_id, s2["id"], member["id"], estate["bikes"][0]["id"], s2["version"])
    assert fixtures.get_pack(pack["id"], member["id"])["remaining_credits"] == 4
    # Studio cancels the session -> the held credit is restored.
    validate_success(api.cancel_session(studio_id, s2["id"], MGR))
    final = fixtures.get_pack(pack["id"], member["id"])
    assert final["consumed_credits"] == 0
    assert final["remaining_credits"] == 5


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant / penalty_waive_conserves_wallet_cents
# ---------------------------------------------------------------------------
def test_penalty_waive_credits_wallet_and_drops_strike(api):
    """PRD 3.8: "Waiving sets the charge's `waived` to true, credits the member's
    `wallet_credit_cents` by the charge's `amount_cents`, and recomputes the member's
    `active_strike_count` so the waived charge no longer counts."
    PRD 3.5: "The system creates a penalty charge of kind `LATE_CANCEL` with
    `amount_cents` snapshotted from the studio's `late_cancel_fee_cents`".

    Design: Difficulty/compensating_invariant/penalty_waive_conserves_wallet_cents
    """
    ctx = fixtures.setup_booked_reservation(
        n_bikes=1, start_utc="2026-06-05T18:00:00Z", end_utc="2026-06-05T19:00:00Z",
    )
    studio_id = ctx["studio"]["id"]
    member_id = ctx["member"]["id"]
    fixtures.set_clock("2026-06-05T12:00:00Z")  # late window
    fixtures.cancel_reservation(studio_id, ctx["session"]["id"], ctx["reservation"]["id"], member_id)
    charges = validate_success(
        api.list_penalty_charges(make_member_headers(member_id), params={"member_id": member_id})
    )
    charge_id = charges[0]["id"]
    resp = api.waive_penalty_charge(charge_id, MGR)
    waived = validate_success(resp)
    assert waived["waived"] is True
    assert waived["amount_cents"] == 2000
    member = fixtures.get_member(member_id)
    assert member["wallet_credit_cents"] == 2000
    assert member["active_strike_count"] == 0


def test_no_show_fee_waive_conserves_wallet_cents(api):
    """PRD 3.8: "Waiving sets the charge's `waived` to true, credits the member's
    `wallet_credit_cents` by the charge's `amount_cents`".
    PRD 3.4: "the system creates a penalty charge of kind `NO_SHOW` with `amount_cents`
    snapshotted from the studio's `no_show_fee_cents`".

    Design: Difficulty/compensating_invariant/penalty_waive_conserves_wallet_cents
    """
    # Conserved monetary quantity: a NO_SHOW fee (3000) is made whole by the waive credit.
    ctx = fixtures.setup_booked_reservation(
        n_bikes=1, start_utc="2026-06-05T18:00:00Z", end_utc="2026-06-05T19:00:00Z",
    )
    studio_id = ctx["studio"]["id"]
    member_id = ctx["member"]["id"]
    fixtures.set_clock("2026-06-05T19:30:00Z")
    validate_success(api.complete_session(studio_id, ctx["session"]["id"], MGR))
    charges = validate_success(
        api.list_penalty_charges(make_member_headers(member_id), params={"member_id": member_id})
    )
    no_show = [c for c in charges if c["kind"] == "NO_SHOW"][0]
    assert no_show["amount_cents"] == 3000
    waived = validate_success(api.waive_penalty_charge(no_show["id"], MGR))
    assert waived["waived"] is True
    member = fixtures.get_member(member_id)
    assert member["wallet_credit_cents"] == 3000
    assert member["active_strike_count"] == 0


# ---------------------------------------------------------------------------
# Queue B: calculations
# ---------------------------------------------------------------------------
def test_first_ride_comp_no_credit_debited(api):
    """PRD 3.3: "When the comp applies, the reservation's `first_ride_discount_applied`
    is set true and its `credit_pack_id` is left null because no pack was debited."

    Design: Corner/calculations/first_ride_comp_no_credit_debited
    """
    ctx = fixtures.setup_booking_ready(n_bikes=1, purchased_credits=5)
    res = fixtures.book(
        ctx["studio"]["id"], ctx["session"]["id"], ctx["member"]["id"],
        ctx["bikes"][0]["id"], ctx["session"]["version"],
    )
    assert res["first_ride_discount_applied"] is True
    assert res["credit_pack_id"] is None
    pack = fixtures.get_pack(ctx["pack"]["id"], ctx["member"]["id"])
    assert pack["remaining_credits"] == 5


def test_retail_discount_tier_5pct_at_qty_3(api):
    """PRD 3.10: "a quantity of at least 3 but fewer than 6 units earns a 5 percent
    discount ... The discounted total is the subtotal minus the discount, where the
    discount is the subtotal multiplied by the chosen percentage and rounded half-up to
    whole cents."

    Design: Corner/calculations/retail_discount_tier_05_at_qty_3
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio()
    member = fixtures.register_member(studio["id"])
    product = fixtures.create_product(
        studio["id"], sku="SOCK", name="Grip Socks", unit_price_cents=500, stock_qty=10
    )
    resp = api.create_retail_order(
        {
            "member_id": member["id"],
            "studio_id": studio["id"],
            "product_id": product["id"],
            "quantity": 3,
        },
        make_member_headers(member["id"]),
    )
    order = validate_success(resp, expected_status=201)
    # subtotal 1500; 5% discount = 75; card 1425; no wallet.
    assert order["subtotal_cents"] == 1500
    assert order["wallet_applied_cents"] == 0
    assert order["card_charged_cents"] == 1425


def test_retail_no_discount_below_tier(api):
    """PRD 3.10: "a quantity of fewer than 3 units earns no discount".

    Design: Corner/calculations/retail_no_discount_below_tier
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio()
    member = fixtures.register_member(studio["id"])
    product = fixtures.create_product(
        studio["id"], sku="BOTTLE", name="Bottle", unit_price_cents=1000, stock_qty=10
    )
    resp = api.create_retail_order(
        {
            "member_id": member["id"],
            "studio_id": studio["id"],
            "product_id": product["id"],
            "quantity": 2,
        },
        make_member_headers(member["id"]),
    )
    order = validate_success(resp, expected_status=201)
    assert order["subtotal_cents"] == 2000
    assert order["card_charged_cents"] == 2000


def test_membership_refund_prorata_time(api):
    """PRD 3.9: "For a `MEMBERSHIP` the refund is *time-prorated* and ignores any credit
    count: the total days are the number of days between the pack's `activated_at` and
    its `expires_at` (counting the start day and excluding the end day); the used days
    are the number of days between `activated_at` and the current clock instant, clamped
    to lie between zero and the total days; the unused days are the total days minus the
    used days; and the refund is the pack's `price_cents` multiplied by unused days
    divided by total days, rounded half-up to whole cents."

    Design: Corner/calculations/membership_refund_prorata_time
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    studio = fixtures.create_studio()
    member = fixtures.register_member(studio["id"])
    pack = fixtures.create_credit_pack(
        member["id"], kind="MEMBERSHIP", purchased_credits=0, price_cents=12000,
        expires_at="2026-01-31T00:00:00Z",
    )
    fixtures.set_clock("2026-01-11T00:00:00Z")  # 10 used of 30 total -> 20 unused
    live = fixtures.get_pack(pack["id"], member["id"])
    resp = api.refund_credit_pack(pack["id"], {"expected_pack_version": live["version"]}, MGR)
    refunded = validate_success(resp)
    assert refunded["status"] == "REFUNDED"
    # round(12000 * 20 / 30) = 8000
    assert fixtures.get_member(member["id"])["wallet_credit_cents"] == 8000


def test_expired_pack_refunds_zero(api):
    """PRD 3.9: "Regardless of kind, if the pack is `EXPIRED` at refund time the refund
    amount is zero."

    Design: Corner/calculations/expired_pack_refunds_zero
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    studio = fixtures.create_studio()
    member = fixtures.register_member(studio["id"])
    pack = fixtures.create_credit_pack(
        member["id"], purchased_credits=5, price_cents=5000, expires_at="2026-02-01T00:00:00Z"
    )
    fixtures.set_clock("2026-02-02T00:00:00Z")  # past expiry
    live = fixtures.get_pack(pack["id"], member["id"])
    assert live["status"] == "EXPIRED"
    resp = api.refund_credit_pack(pack["id"], {"expected_pack_version": live["version"]}, MGR)
    refunded = validate_success(resp)
    assert refunded["status"] == "REFUNDED"
    assert fixtures.get_member(member["id"])["wallet_credit_cents"] == 0
