"""Pricing announcements, OCC-guarded writes, standing-par supersession, and
the tiered fuel surcharge (PRD §2.6, §3.2, §3.3)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    confirm_order,
    create_order,
    create_pricing_period,
    create_product,
    create_trip,
    deliver_order,
    delivered_line,
    get_invoice_for_order,
    get_pricing_period,
    get_store,
    make_distributor_owner_headers,
    order_line,
    patch_store,
    precool_and_depart,
    publish_announcement,
    set_clock,
    setup_planned_order,
    setup_route_with_store,
    upsert_par,
    validate_error,
    validate_success,
)

TM = TEST_USERS["territory_manager_headers"]
MA = TEST_USERS["market_admin_headers"]

REGULATED_PRODUCT = {
    "regulated": True,
    "weight_lbs_per_unit": 8.6,
    "margin_cents_per_unit": 30,
    "units_per_case": 1,
    "shelf_life_days": 14,
}
# base 2000 + assessment 35 + hauling 60 on 8.6 lb -> milk cost 180.17c/unit.
ANN_299 = {"base": 2000, "assessment": 35, "hauling": 60, "diesel": 299}


def _deliver_one_unit(api, refs, service_date, code_date):
    """Confirm the planned order, run the trip, deliver 1 unit, return invoice."""
    d_id = refs["distributor"]["id"]
    confirm_order(refs["order"]["id"], d_id)
    precool_and_depart(refs["trip"]["id"], refs["driver"]["id"], service_date)
    set_clock(f"{service_date}T09:00:00Z")
    deliver_order(
        refs["order"]["id"], refs["driver"]["id"],
        [delivered_line(refs["product"]["id"], 1, code_date)],
    )
    return get_invoice_for_order(refs["order"]["id"])


class TestMilkPriceTieredSurchargeBoundary:
    def test_diesel_299_no_surcharge_then_300_first_tier(self, api):
        """PRD §3.3: "The fuel surcharge rate is tiered on the announcement's
        `diesel_index_cents`: below 300 cents per gallon there is no surcharge;
        from 300 up to but not including 400 the rate is 1.5 percent — 300
        exactly is surcharged"
        PRD §3.3: "publishing a new announcement of a kind supersedes the
        prior `ACTIVE` announcement of that kind — the prior one moves to
        `SUPERSEDED`"

        Design: Difficulty/combinatorial_formula/milk_price_tiered_surcharge_boundary
        """
        refs = setup_planned_order(prefix="C", quantity_units=1,
                                   product_overrides=dict(REGULATED_PRODUCT))
        d_id = refs["distributor"]["id"]
        period = create_pricing_period("2026-08")
        ann1 = publish_announcement(period["id"], kind="PROVISIONAL", **ANN_299)

        inv1 = _deliver_one_unit(api, refs, "2026-08-10", "2026-08-20")
        assert inv1["subtotal_cents"] == 210, (
            "diesel 299 -> no surcharge; unit 210.170c rounds to 210"
        )

        ann2 = publish_announcement(
            period["id"], kind="PROVISIONAL", base=2000, assessment=35,
            hauling=60, diesel=300,
        )
        ann1_after = validate_success(api.get_announcement(ann1["id"], TM), 200)
        assert ann1_after["status"] == "SUPERSEDED"
        assert ann2["status"] == "ACTIVE"
        period_after = get_pricing_period(period["id"])
        assert period_after["current_provisional_id"] == ann2["id"]

        inv1_after = validate_success(api.get_invoice(inv1["id"], TM), 200)
        assert inv1_after["subtotal_cents"] == 210, (
            "delivery-time price snapshot: a superseding PROVISIONAL publish "
            "does not reprice an existing invoice"
        )

        trip2 = create_trip(refs["route"]["id"], refs["driver"]["id"], d_id,
                            service_date="2026-08-11")
        order2 = create_order(
            refs["store"]["id"], trip2["id"],
            [order_line(refs["product"]["id"], 1)], d_id,
            delivery_window_start="2026-08-11T08:00:00Z",
            delivery_window_end="2026-08-11T08:30:00Z",
        )
        refs2 = dict(refs)
        refs2["trip"] = trip2
        refs2["order"] = order2
        inv2 = _deliver_one_unit(api, refs2, "2026-08-11", "2026-08-21")
        assert inv2["subtotal_cents"] == 213, (
            "diesel 300 -> 1.5% tier (boundary inclusive); unit 212.873c "
            "rounds to 213"
        )

    def test_diesel_400_and_500_higher_tiers(self, api):
        """PRD §3.3: "from 400 up to but not including 500 the rate is 3.0
        percent — 400 exactly takes 3.0 percent; at 500 or above the rate is
        4.5 percent."

        Design: Difficulty/combinatorial_formula/milk_price_tiered_surcharge_boundary
        """
        refs = setup_planned_order(prefix="C3", quantity_units=1,
                                   product_overrides=dict(REGULATED_PRODUCT))
        d_id = refs["distributor"]["id"]
        period = create_pricing_period("2026-08")
        publish_announcement(period["id"], kind="PROVISIONAL", base=2000,
                             assessment=35, hauling=60, diesel=400)
        inv1 = _deliver_one_unit(api, refs, "2026-08-10", "2026-08-20")
        assert inv1["subtotal_cents"] == 216, (
            "diesel 400 -> 3.0% tier; unit 215.575c rounds to 216"
        )

        publish_announcement(period["id"], kind="PROVISIONAL", base=2000,
                             assessment=35, hauling=60, diesel=500)
        trip2 = create_trip(refs["route"]["id"], refs["driver"]["id"], d_id,
                            service_date="2026-08-11")
        order2 = create_order(
            refs["store"]["id"], trip2["id"],
            [order_line(refs["product"]["id"], 1)], d_id,
            delivery_window_start="2026-08-11T08:00:00Z",
            delivery_window_end="2026-08-11T08:30:00Z",
        )
        refs2 = dict(refs)
        refs2["trip"] = trip2
        refs2["order"] = order2
        inv2 = _deliver_one_unit(api, refs2, "2026-08-11", "2026-08-21")
        assert inv2["subtotal_cents"] == 218, (
            "diesel 500 -> 4.5% tier; unit 218.278c rounds to 218"
        )


def test_par_upsert_supersedes_prior(api):
    """PRD §3.2: "At most one par per store–product pair is `ACTIVE` at a
    time: a new par for a pair with an existing `ACTIVE` par supersedes it,
    moving the old one to `SUPERSEDED`, and the upsert increments the store's
    `version` by one."

    Design: Corner/entities/par_upsert_supersedes_prior
    """
    refs = setup_route_with_store(prefix="Y")
    d_id = refs["distributor"]["id"]
    store = refs["store"]
    product = create_product("PAR-1", list_price_cents=100, shelf_life_days=10)

    par1 = upsert_par(store["id"], d_id, product["id"], store["version"], par_mon=10)
    assert par1["status"] == "ACTIVE"
    v_after_first = get_store(store["id"])["version"]
    assert v_after_first == store["version"] + 1

    par2 = upsert_par(store["id"], d_id, product["id"], v_after_first, par_mon=25)
    assert par2["status"] == "ACTIVE" and par2["par_mon"] == 25

    par1_after = validate_success(api.get_standing_par(par1["id"], TM), 200)
    assert par1_after["status"] == "SUPERSEDED"
    v_after_second = get_store(store["id"])["version"]
    assert v_after_second == v_after_first + 1


def test_occ_par_upsert_stale_version(api):
    """PRD §2.6: "Creating a standing par for a store must carry
    `expected_store_version` matching the store's current `version`. Because a
    par upsert legitimately supersedes the prior active par for the same store
    and product, a client acting on a stale view of the store's par set is
    rejected with `ERR_STALE_STORE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_par_upsert_stale_version
    """
    refs = setup_route_with_store(prefix="GA")
    d_id = refs["distributor"]["id"]
    store = refs["store"]
    product = create_product("OCC-1", list_price_cents=100, shelf_life_days=30)
    owner = make_distributor_owner_headers(d_id)

    par1 = upsert_par(store["id"], d_id, product["id"], store["version"], par_mon=5)

    stale = api.upsert_standing_par(
        store["id"],
        {"product_id": product["id"], "expected_store_version": store["version"],
         "par_mon": 9},
        owner,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_STORE_VERSION)

    fresh_version = get_store(store["id"])["version"]
    assert fresh_version == store["version"] + 1
    par2 = upsert_par(store["id"], d_id, product["id"], fresh_version, par_mon=9)
    assert par2["status"] == "ACTIVE"
    par1_after = validate_success(api.get_standing_par(par1["id"], TM), 200)
    assert par1_after["status"] == "SUPERSEDED"


def test_occ_store_patch_stale_and_increment(api):
    """PRD §2.6: "Updating a store's configuration must carry
    `expected_store_version` matching the store's current `version`; changes
    to pull windows, credit limits, deposit rates, and merchandising terms are
    lost-update prone, and a stale basis is rejected with
    `ERR_STALE_STORE_VERSION` (HTTP 412)."
    PRD §3.1: "a successful patch increments the store's `version` by one"

    Design: Corner/complexity_layers/occ_store_patch_stale_and_increment
    """
    refs = setup_route_with_store(prefix="GB")
    d_id = refs["distributor"]["id"]
    store = refs["store"]
    owner = make_distributor_owner_headers(d_id)

    patched = patch_store(store["id"], d_id, store["version"], pull_window_days=6)
    assert patched["pull_window_days"] == 6
    assert patched["version"] == store["version"] + 1

    stale = api.patch_store(
        store["id"],
        {"expected_store_version": store["version"], "credit_limit_cents": 5},
        owner,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_STORE_VERSION)

    after = get_store(store["id"])
    assert after["credit_limit_cents"] == 100000000, (
        "the rejected patch must apply nothing"
    )
    assert after["pull_window_days"] == 6


def test_occ_announcement_publish_stale_version(api):
    """PRD §2.6: "Publishing a price announcement into a pricing period must
    carry `expected_pricing_period_version` matching the period's current
    `version`; because a publish supersedes the prior announcement of its kind
    — and a final announcement reprices open invoices — a stale basis is
    rejected with `ERR_STALE_PRICING_PERIOD_VERSION` (HTTP 412)."
    PRD §3.3: "a successful publish increments the period's `version` by one"

    Design: Corner/complexity_layers/occ_announcement_publish_stale_version
    """
    period = create_pricing_period("2026-08")
    v1 = period["version"]

    ann1 = publish_announcement(period["id"], kind="PROVISIONAL", **ANN_299)

    stale = api.publish_announcement(
        period["id"],
        {
            "kind": "PROVISIONAL",
            "class_i_base_cents_per_cwt": 2050,
            "processor_assessment_cents_per_cwt": 35,
            "hauling_cents_per_cwt": 60,
            "diesel_index_cents": 299,
            "expected_pricing_period_version": v1,
        },
        MA,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PRICING_PERIOD_VERSION)

    v2 = get_pricing_period(period["id"])["version"]
    assert v2 == v1 + 1

    ann2 = publish_announcement(
        period["id"], kind="PROVISIONAL", base=2050, assessment=35,
        hauling=60, diesel=299,
    )
    assert ann2["status"] == "ACTIVE"
    ann1_after = validate_success(api.get_announcement(ann1["id"], TM), 200)
    assert ann1_after["status"] == "SUPERSEDED"
