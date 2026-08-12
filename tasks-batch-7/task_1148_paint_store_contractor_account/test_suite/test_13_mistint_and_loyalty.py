"""Mistint price decay with floor (PRD §3.9), loyalty redemption math
(PRD §3.7), and PLATINUM multiplier application (PRD §3.1, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_loyalty_redemption_payload,
    create_mistint_listing_payload,
    create_product,
    make_contractor_headers,
    place_and_pay_order,
    set_logical_clock,
    setup_account_at_tier,
    setup_account_job_product,
    setup_mistint_listing,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
MANAGER = TEST_USERS["manager_headers"]


def test_mistint_floor_binds_after_twenty_weeks(api):
    """PRD §3.9: "From then on the price decays with age: letting the whole
    started weeks be the logical-clock time from the listing's `created_at` to
    now, divided into full seven-day weeks and truncated down, the decayed
    price is `list_price_cents` multiplied by 0.90 once per started week,
    rounded half up; the floor price is 25 percent of `cost_basis_cents`,
    rounded half up; and `current_price_cents` is the larger of the two — the
    listing never prices below a quarter of its cost." PRD §3.9: "Marking a
    listing sold — `LISTED` to `SOLD`, by a `StoreAssociate` — captures that
    instant's `current_price_cents` into `sold_price_cents` (null until the
    sale) ...".

    Cost basis 10000 lists at 5000; after 20 started weeks the decayed 608
    falls below the 2500 floor, so the sale captures 2500.

    Design: Corner/calculations/mistint_decay_floor_binds_after_twenty_weeks
    """
    product, listing = setup_mistint_listing(cost_basis_cents=10_000, quantity=1,
                                             sku="P-DEC")
    assert listing["list_price_cents"] == 5000, (
        "creation fixes list price at half the cost basis")
    set_logical_clock("2026-09-18T00:00:00Z")
    resp = api.mark_mistint_sold(listing["id"], {}, ASSOCIATE)
    sold = validate_success(resp, expected_status=200)
    assert sold["sold_price_cents"] == 2500, (
        f"floor round_half_up(10000 * 0.25) = 2500 binds over decayed "
        f"round_half_up(5000 * 0.9^20) = 608, got {sold['sold_price_cents']}")
    assert sold["status"] == "SOLD"


def _setup_points_balance(api):
    """STANDARD account with 800 points from a paid 4x20000 order."""
    account, _, job, product = setup_account_job_product(
        company_name="Red Co", credit_limit_cents=1_000_000,
        jurisdiction_code="VT-OPEN", jurisdiction_name="Vermont",
        job_name="J", sku="P-RED", list_price_cents=20_000)
    place_and_pay_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 4}],
                        headers=ASSOCIATE)
    return account


def test_redeem_posts_negative_delta_and_recomputes_balance(api):
    """PRD §3.7: "Redemption is the owning `Contractor` spending points: the
    request names the `contractor_account_id` and a `points_to_redeem`,
    requires the account `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`), and requires
    the current `loyalty_points_balance` to be at least `points_to_redeem`
    (else `ERR_INSUFFICIENT_POINTS`, HTTP 422). An accepted redemption posts a
    `REDEEM` entry with negative `points_delta` equal to the points spent and
    a `note` recording a credit of `credit_cents` equal to the points redeemed
    — one point is one cent of credit — and the balance is recomputed."

    Redeeming 300 of the 800-point balance leaves 500.

    Design: Corner/calculations/loyalty_redeem_posts_negative_delta
    """
    account = _setup_points_balance(api)
    owner = make_contractor_headers(account["id"])
    resp = api.create_loyalty_redemption(
        create_loyalty_redemption_payload(account["id"], 300), owner)
    redeem = validate_success(resp, expected_status=201)
    assert redeem["type"] == "REDEEM"
    assert redeem["points_delta"] == -300, (
        f"the REDEEM entry posts negative the points spent, "
        f"got {redeem['points_delta']}")
    account_after = validate_success(api.get_contractor_account(account["id"], ADMIN))
    assert account_after["loyalty_points_balance"] == 500, (
        f"800 - 300 = 500, got {account_after['loyalty_points_balance']}")


def test_redeem_beyond_balance_rejected(api):
    """PRD §3.7: "Redemption is the owning `Contractor` spending points: the
    request names the `contractor_account_id` and a `points_to_redeem`,
    requires the account `ACTIVE` (else `ERR_ACCOUNT_SUSPENDED`), and requires
    the current `loyalty_points_balance` to be at least `points_to_redeem`
    (else `ERR_INSUFFICIENT_POINTS`, HTTP 422)."

    After redeeming 300 of 800, a further 501 exceeds the remaining 500.

    Design: Corner/calculations/loyalty_redeem_posts_negative_delta
    """
    account = _setup_points_balance(api)
    owner = make_contractor_headers(account["id"])
    validate_success(api.create_loyalty_redemption(
        create_loyalty_redemption_payload(account["id"], 300), owner),
        expected_status=201)
    resp = api.create_loyalty_redemption(
        create_loyalty_redemption_payload(account["id"], 501), owner)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS)


def test_platinum_tier_earns_five_x_points(api):
    """PRD §3.1: "The evaluation recomputes `ytd_net_volume_cents` at that
    instant and assigns `tier` by inclusive thresholds: `PLATINUM` when the
    volume reaches 40,000,000 cents ($400,000), otherwise `GOLD` when it
    reaches 15,000,000 cents ($150,000), otherwise `SILVER` when it reaches
    5,000,000 cents ($50,000), otherwise `STANDARD`. A volume exactly equal to
    a threshold earns that tier." PRD §3.7: "Earning happens at payment: the
    posted `EARN` entry's `points_delta` is the whole dollars of merchandise —
    the order's `subtotal_cents` divided by 100 and truncated down —
    multiplied by the tier multiplier from the order's `tier_snapshot`, which
    is 1 for `STANDARD`, 2 for `SILVER`, 3 for `GOLD`, and 5 for `PLATINUM`;
    the floor is taken before the multiplication."

    After crossing 40,000,000 the tier evaluates to PLATINUM; the next paid
    order snapshots PLATINUM. Per PRD §3.6 the 15% PLATINUM tier discount
    applies at line pricing, so the 10,000-list-price line prices to a
    discounted subtotal of 8,500, and per PRD §3.7 the EARN entry keys off
    the order's (discounted) `subtotal_cents`: floor(8500/100) * 5 = 425
    points, bringing the balance to 400,000 + 425 = 400,425.

    Design: Corner/calculations/platinum_tier_earns_five_x_points
    """
    account, job, big_order = setup_account_at_tier(
        "Plat Co", 40_000_000, jurisdiction_code="FL-OPEN", sku_prefix="P-PLAT")
    assert account["tier"] == "PLATINUM", (
        f"V == 40000000 meets the inclusive PLATINUM threshold, "
        f"got {account['tier']}")
    p_sm = create_product(sku="P-SM", name="Can", list_price_cents=10_000)
    order = place_and_pay_order(account["id"], job["id"],
                                [{"product_id": p_sm["id"], "quantity": 1}],
                                headers=ASSOCIATE)
    assert order["tier_snapshot"] == "PLATINUM", (
        f"the account's tier at creation is frozen into the order, "
        f"got {order['tier_snapshot']}")
    assert order["subtotal_cents"] == 8500, (
        f"the 15% PLATINUM tier discount prices the line at "
        f"round_half_up(10000 * 0.85) = 8500, got {order['subtotal_cents']}")
    account_after = validate_success(api.get_contractor_account(account["id"], ADMIN))
    assert account_after["loyalty_points_balance"] == 400_425, (
        f"400000 from the first order at STANDARD mult 1, plus 425 at "
        f"PLATINUM mult 5, got {account_after['loyalty_points_balance']}")
    resp = api.list_loyalty_transactions(
        ASSOCIATE, params={"contractor_account_id": account["id"],
                           "order_id": order["id"]})
    entries = validate_success(resp, expected_status=200)
    earns = [t for t in entries if t["type"] == "EARN"]
    assert len(earns) == 1 and earns[0]["points_delta"] == 425, (
        f"floor(8500/100) * 5 = 425, got {earns}")


def test_written_off_mistint_cannot_be_sold(api):
    """PRD §3.9: "A `StoreManager` may instead write a listing off — `LISTED`
    to `WRITTEN_OFF`. Either action from a non-`LISTED` state is
    `ERR_INVALID_STATE`, and each bumps the listing's `version`."

    Design: Corner/state_machines/written_off_mistint_cannot_be_sold
    """
    product, listing = setup_mistint_listing(cost_basis_cents=4000, quantity=2,
                                             sku="P-MT")
    resp = api.write_off_mistint(listing["id"], MANAGER)
    written_off = validate_success(resp, expected_status=200)
    assert written_off["status"] == "WRITTEN_OFF"
    resp = api.mark_mistint_sold(listing["id"], {}, ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_mistint_listing(listing["id"], ASSOCIATE))
    assert after["status"] == "WRITTEN_OFF", (
        f"the terminal state must not move, got {after['status']}")
