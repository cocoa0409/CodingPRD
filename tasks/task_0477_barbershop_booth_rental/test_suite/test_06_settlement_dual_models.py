"""Daily settlement under the two compensation models (PRD §3.10).

Covers the dual-variant settlement payout calculation, the money-conservation
invariant, the already-settled guard, and the OCC stale-barber-version guard.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    assert_settlement,
    assert_settlement_conserves_money,
    setup_shop_with_barber_chair_shift,
    paid_appointment,
    paid_walkin,
    setup_shop_with_active_barber,
    barber_version,
    settle,
    TEST_USERS,
    make_customer_headers,
)

OWNER = TEST_USERS["shop_owner_headers"]


def _dual_model_scenario():
    """Build the dual-variant fixture: a BOOTH_RENT barber (B1, rent 5000) and a
    COMMISSION barber (B2, commission 40, product commission 10), each PAID one
    identical ticket (Haircut 3000 + Beard 1500 addon + Pomade 1200 + tip 500)
    on business_date 2026-06-10. Returns (b1, b2)."""
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={
            "name": "Fade House",
            "tax_rate_pct": 8.5,
            "default_booth_rent_cents": 5000,
            "default_commission_pct": 40,
            "product_commission_pct": 10,
            "punch_reward_threshold": 10,
        },
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    shop = ctx["shop"]
    b1 = get_success_data(
        api_client.create_barber(
            {
                "shop_id": shop["id"], "full_name": "Bo", "license_number": "L1",
                "license_expires_on": "2027-01-01", "comp_model": "BOOTH_RENT",
                "booth_rent_cents": 5000,
            },
            OWNER,
        )
    )
    get_success_data(api_client.activate_license(b1["id"], OWNER))
    b2 = get_success_data(
        api_client.create_barber(
            {
                "shop_id": shop["id"], "full_name": "Cy", "license_number": "L2",
                "license_expires_on": "2027-01-01", "comp_model": "COMMISSION",
                "commission_pct": 40,
            },
            OWNER,
        )
    )
    get_success_data(api_client.activate_license(b2["id"], OWNER))

    # Each settled barber gets a dedicated chair so its 09:00-18:00 shift never
    # collides (closed-buffer rule, PRD §3.3) with the shift the base fixture
    # already scheduled for ctx["barber"] on ctx["chair"].
    chair1b = get_success_data(
        api_client.create_chair({"shop_id": shop["id"], "label": "Chair 1B"}, OWNER)
    )
    chair2 = get_success_data(
        api_client.create_chair({"shop_id": shop["id"], "label": "Chair 2"}, OWNER)
    )
    addon = get_success_data(
        api_client.create_addon(
            {"shop_id": shop["id"], "name": "Beard", "price_cents": 1500, "extra_minutes": 15},
            OWNER,
        )
    )
    product = get_success_data(
        api_client.create_product(
            {"shop_id": shop["id"], "name": "Pomade", "price_cents": 1200,
             "stock_qty": 5, "commission_eligible": True},
            OWNER,
        )
    )
    # Shifts for both barbers (auto-thread shop version).
    v1 = get_success_data(api_client.get_shop(shop["id"], OWNER))["version"]
    get_success_data(api_client.create_shift(
        {"shop_id": shop["id"], "barber_id": b1["id"], "chair_id": chair1b["id"],
         "start_utc": "2026-06-10T09:00:00Z", "end_utc": "2026-06-10T18:00:00Z",
         "expected_shop_version": v1}, OWNER))
    v2 = get_success_data(api_client.get_shop(shop["id"], OWNER))["version"]
    get_success_data(api_client.create_shift(
        {"shop_id": shop["id"], "barber_id": b2["id"], "chair_id": chair2["id"],
         "start_utc": "2026-06-10T09:00:00Z", "end_utc": "2026-06-10T18:00:00Z",
         "expected_shop_version": v2}, OWNER))

    lines = {
        "service_line_ids": [ctx["service"]["id"]],
        "addon_line_ids": [addon["id"]],
        "product_lines": [{"product_sku_id": product["id"], "qty": 1}],
        "tip_cents": 500,
    }
    # B1 (booth-rent) ticket on chair 1B (its own shift's chair).
    ctx_b1 = dict(ctx)
    ctx_b1["barber"] = b1
    ctx_b1["chair"] = chair1b
    paid_appointment(ctx_b1, start_utc="2026-06-10T10:00:00Z", addon_ids=[addon["id"]], lines=lines)
    # B2 (commission) ticket on chair 2.
    ctx_b2 = dict(ctx)
    ctx_b2["barber"] = b2
    ctx_b2["chair"] = chair2
    cust2 = get_success_data(
        api_client.create_customer(
            {"shop_id": shop["id"], "full_name": "Dan", "email": "dan@x.com"}, OWNER)
    )
    ctx_b2["customer"] = cust2
    paid_appointment(ctx_b2, start_utc="2026-06-10T10:00:00Z", addon_ids=[addon["id"]], lines=lines)
    return b1, b2


def test_booth_rent_settlement_payout(api):
    """PRD §3.10: "Under the `BOOTH_RENT` variant, `booth_rent_charged_cents` is
    the barber's `booth_rent_cents`, `shop_commission_cents` is zero, and
    `barber_payout_cents` is the sum of tips plus service revenue plus product
    revenue minus the barber's `booth_rent_cents` — the barber keeps the gross
    take and simply pays the flat daily rent."

    Design: Difficulty/dual_variant_calc/settlement_payout_booth_rent_vs_commission
    """
    b1, _ = _dual_model_scenario()
    v = barber_version(b1["id"])
    res = api.create_settlement(
        b1["id"], {"business_date": "2026-06-10", "expected_barber_version": v}, OWNER
    )
    st = validate_success(res, 201)
    assert_settlement(st)
    assert st["barber_payout_cents"] == 1200, st
    assert st["booth_rent_charged_cents"] == 5000
    assert st["shop_commission_cents"] == 0


def test_commission_settlement_payout(api):
    """PRD §3.10: "Under the `COMMISSION` variant, `booth_rent_charged_cents` is
    zero, and two commissions are figured independently. The shop's service take
    is the service revenue multiplied by the barber's `commission_pct` divided by
    100, rounded half-up; the barber's product earn is the commission-eligible
    product subtotal multiplied by the shop's `product_commission_pct` divided by
    100, rounded half-up."

    Design: Difficulty/dual_variant_calc/settlement_payout_booth_rent_vs_commission
    """
    _, b2 = _dual_model_scenario()
    v = barber_version(b2["id"])
    res = api.create_settlement(
        b2["id"], {"business_date": "2026-06-10", "expected_barber_version": v}, OWNER
    )
    st = validate_success(res, 201)
    assert st["barber_payout_cents"] == 3320, st
    assert st["booth_rent_charged_cents"] == 0
    assert st["shop_commission_cents"] == 2880


def test_commission_settlement_conserves_money_split(api):
    """PRD §3.10: "The `shop_commission_cents` is the shop's service take plus the
    portion of product revenue the barber did not earn — that is, the service take
    plus the difference of total product revenue minus the barber's product earn.
    The `barber_payout_cents` is the sum of tips plus the service revenue net of
    the shop's service take plus the barber's product earn."

    Design: Difficulty/compensating_invariant/commission_settlement_conserves_money_split
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={
            "name": "Conserve Money Shop", "tax_rate_pct": 8.5,
            "default_booth_rent_cents": 0, "default_commission_pct": 40,
            "product_commission_pct": 10,
        },
        barber_overrides={"full_name": "Cy", "license_number": "L2", "commission_pct": 40},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    shop = ctx["shop"]
    addon = get_success_data(api_client.create_addon(
        {"shop_id": shop["id"], "name": "Beard", "price_cents": 1500, "extra_minutes": 15}, OWNER))
    product = get_success_data(api_client.create_product(
        {"shop_id": shop["id"], "name": "Pomade", "price_cents": 1200,
         "stock_qty": 5, "commission_eligible": True}, OWNER))
    paid_appointment(
        ctx, start_utc="2026-06-10T10:00:00Z", addon_ids=[addon["id"]],
        lines={
            "service_line_ids": [ctx["service"]["id"]],
            "addon_line_ids": [addon["id"]],
            "product_lines": [{"product_sku_id": product["id"], "qty": 1}],
            "tip_cents": 500,
        },
    )
    v = barber_version(ctx["barber"]["id"])
    st = validate_success(api.create_settlement(
        ctx["barber"]["id"],
        {"business_date": "2026-06-10", "expected_barber_version": v}, OWNER), 201)
    assert st["barber_payout_cents"] == 3320
    assert st["shop_commission_cents"] == 2880
    assert st["tip_total_cents"] == 500
    assert st["service_revenue_cents"] == 4500
    assert st["product_revenue_cents"] == 1200
    assert_settlement_conserves_money(st)
    assert (st["barber_payout_cents"] + st["shop_commission_cents"]) == 6200


def test_settlement_money_split_booth_rent_total(api):
    """PRD §3.10: "`barber_payout_cents` is the sum of tips plus service revenue
    plus product revenue minus the barber's `booth_rent_cents` — the barber keeps
    the gross take and simply pays the flat daily rent."

    Design: Difficulty/compensating_invariant/commission_settlement_conserves_money_split
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={
            "name": "Booth Conserve", "tax_rate_pct": 0,
            "default_booth_rent_cents": 5000, "default_commission_pct": 0,
        },
        barber_overrides={"booth_rent_cents": 5000},
        comp_model="BOOTH_RENT",
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    paid_appointment(
        ctx, start_utc="2026-06-10T10:00:00Z",
        lines={"service_line_ids": [ctx["service"]["id"]], "tip_cents": 200},
    )
    v = barber_version(ctx["barber"]["id"])
    st = validate_success(api.create_settlement(
        ctx["barber"]["id"],
        {"business_date": "2026-06-10", "expected_barber_version": v}, OWNER), 201)
    # tips 200 + svc 3000 + prod 0 - rent 5000 = -1800
    assert st["service_revenue_cents"] == 3000
    assert st["tip_total_cents"] == 200
    assert st["booth_rent_charged_cents"] == 5000
    assert st["barber_payout_cents"] == 200 + 3000 + 0 - 5000


def test_settle_already_settled_date_rejected(api):
    """PRD §3.10: "There may be at most one settlement per barber per
    `business_date`; a second attempt, or any checkout aimed at a barber-and-date
    already settled, is refused with `ERR_DATE_ALREADY_SETTLED`."

    Design: Corner/endpoints/settle_already_settled_date_returns_date_already_settled
    """
    ctx = setup_shop_with_active_barber(
        shop_overrides={"default_commission_pct": 30},
        barber_overrides={"commission_pct": 30},
    )
    paid_walkin(ctx)
    settle(ctx["barber"]["id"], business_date="2026-06-10")
    v2 = barber_version(ctx["barber"]["id"])
    res = api.create_settlement(
        ctx["barber"]["id"],
        {"business_date": "2026-06-10", "expected_barber_version": v2}, OWNER
    )
    validate_error(res, "ERR_DATE_ALREADY_SETTLED")


def test_settlement_stale_barber_version_rejected(api):
    """PRD §2.7: "Because every ticket checkout bumps the barber's `version` as it
    reconciles `unsettled_revenue_cents`, a settlement computed against a stale
    revenue snapshot would overwrite figures the client never saw; such a request
    is rejected with `ERR_STALE_BARBER_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_barber_version_on_settlement_create
    """
    ctx = setup_shop_with_active_barber(
        shop_overrides={"default_commission_pct": 30},
        barber_overrides={"commission_pct": 30},
    )
    stale_v = barber_version(ctx["barber"]["id"])  # observed BEFORE checkout bumps it
    paid_walkin(ctx)  # bumps Barber.version
    res = api.create_settlement(
        ctx["barber"]["id"],
        {"business_date": "2026-06-10", "expected_barber_version": stale_v}, OWNER
    )
    validate_error(res, "ERR_STALE_BARBER_VERSION")


def test_customer_cannot_create_settlement(api):
    """PRD §2.1: "When a request carries a syntactically valid user context but the
    role is not permitted to perform the requested operation — or an entity-backed
    actor reaches for a resource it does not own — the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/customer_cannot_settle_barber_returns_forbidden
    """
    ctx = setup_shop_with_active_barber(
        shop_overrides={"default_commission_pct": 0},
    )
    cust = ctx["customer"]
    v = barber_version(ctx["barber"]["id"])
    res = api.create_settlement(
        ctx["barber"]["id"],
        {"business_date": "2026-06-10", "expected_barber_version": v},
        make_customer_headers(cust["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE")
