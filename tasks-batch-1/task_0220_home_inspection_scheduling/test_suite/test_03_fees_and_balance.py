"""Fee engine (tiered sqft, type multiplier, add-ons), the quoted/final dual variant,
the order balance ledger, and the re-inspection discount bands.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    setup_base_config, create_requested_order, setup_requested_order,
    setup_scheduled_order, setup_delivered_order, setup_delivered_failing_parent,
    create_property, reinspect,
)
from test_helpers import factories as F

SCHED = TEST_USERS["scheduler_headers"]


# ---------------------------------------------------------------------------
# combinatorial fee: tiered sqft x type multiplier, add-ons added AFTER multiply
# ---------------------------------------------------------------------------
def test_seller_tiered_fee_with_type_multiplier_and_addon(api):
    """PRD §3.7: "an inspection-type multiplier is applied to the sum of
    `base_rate_cents` and that square-footage component: the multiplier is 1.00 for
    `BUYER`, 0.90 for `SELLER`, 0.75 for `FOUR_POINT`, and 0.60 for `WIND_MIT`, and the
    product is rounded half up to whole cents at this step."
    PRD §3.7: "Third, the prices of all `ACTIVE` add-ons are summed as flat amounts —
    they are not subject to the type multiplier — and added to the rounded typed amount
    to give the final fee in cents."

    Design: Difficulty/combinatorial_formula/tiered_sqft_times_type_multiplier_mode_a
    """
    # SELLER 3000 sqft + TERMITE: (15000 + 2000*12 + 1000*8)*0.90 = 42300; +8500 = 50800.
    cfg, order = setup_requested_order(inspection_type="SELLER",
                                       certifications=["SELLER"], client_role="SELLER",
                                       square_footage=3000, year_built=1995)
    api_client.create_addon(order["id"], F.create_addon_payload("TERMITE"), SCHED)
    scheduled = validate_success(api.schedule_order(
        order["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-02T13:00:00Z"),
        SCHED))
    assert scheduled["quoted_fee_cents"] == 50800


def test_buyer_fee_spans_all_three_tiers(api):
    """PRD §3.7: "The square-footage component in cents is the tier-1 footage times
    `tier1_rate_cents_per_sqft`, plus the tier-2 footage times `tier2_rate_cents_per_sqft`,
    plus the tier-3 footage times `tier3_rate_cents_per_sqft`."
    PRD §3.1: "The first boundary defaults to 2000 and must be greater than 0; the
    second defaults to 4000 and must be strictly greater than `tier1_max_sqft`."

    Design: Difficulty/combinatorial_formula/tiered_sqft_times_type_multiplier_mode_a
    """
    # BUYER 5000 sqft: (15000 + 2000*12 + 2000*8 + 1000*5)*1.0 = 60000.
    cfg, order = setup_requested_order(inspection_type="BUYER", certifications=["BUYER"],
                                       square_footage=5000)
    scheduled = validate_success(api.schedule_order(
        order["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-02T13:00:00Z"),
        SCHED))
    assert scheduled["quoted_fee_cents"] == 60000


def test_wind_mit_type_multiplier_applied(api):
    """PRD §3.7: "the multiplier is 1.00 for `BUYER`, 0.90 for `SELLER`, 0.75 for
    `FOUR_POINT`, and 0.60 for `WIND_MIT`, and the product is rounded half up to whole
    cents at this step."

    Design: Corner/calculations/corner_wind_mit_type_multiplier_fee
    """
    # WIND_MIT 1500 sqft: (15000 + 1500*12)*0.60 = 19800.
    cfg, order = setup_requested_order(inspection_type="WIND_MIT",
                                       certifications=["WIND_MIT"], square_footage=1500)
    scheduled = validate_success(api.schedule_order(
        order["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-08-04T13:00:00Z"),
        SCHED))
    assert scheduled["quoted_fee_cents"] == 19800


# ---------------------------------------------------------------------------
# boundary: tier1 inclusive boundary at 2000 vs 2001
# ---------------------------------------------------------------------------
def test_tier1_boundary_2000_vs_2001(api):
    """PRD §3.7: "The footage that falls within tier 1 is the lesser of the input
    footage and `tier1_max_sqft`; the footage within tier 2 is the input footage capped
    at `tier2_max_sqft` minus `tier1_max_sqft`, but never less than 0."
    PRD §3.1: "The first boundary defaults to 2000 and must be greater than 0."

    Design: Difficulty/boundary_precision_check/sqft_tier1_boundary_2000_vs_2001_on_schedule
    """
    cfg = setup_base_config(certifications=["BUYER"])
    prop_a = cfg["property"]  # default 2200 -> override via fresh props
    prop_2000 = create_property(square_footage=2000, address_line="A 2000")
    prop_2001 = create_property(square_footage=2001, address_line="B 2001")
    order_a = create_requested_order(cfg, property_id=prop_2000["id"])
    order_b = create_requested_order(cfg, property_id=prop_2001["id"])
    sched_a = validate_success(api.schedule_order(
        order_a["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-10T13:00:00Z"),
        SCHED))
    sched_b = validate_success(api.schedule_order(
        order_b["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-11T13:00:00Z"),
        SCHED))
    # 2000 wholly in tier 1: (15000 + 2000*12)*1.0 = 39000.
    assert sched_a["quoted_fee_cents"] == 39000
    # 2001 pushes 1 sqft into tier 2: (15000 + 2000*12 + 1*8)*1.0 = 39008.
    assert sched_b["quoted_fee_cents"] == 39008


def test_tier2_tier3_boundary_4000_vs_4001(api):
    """PRD §3.7: "the footage within tier 2 is the input footage capped at
    `tier2_max_sqft` minus `tier1_max_sqft`, but never less than 0; the footage in tier 3
    is the input footage minus `tier2_max_sqft`, but never less than 0."
    PRD §3.1: "the second defaults to 4000 and must be strictly greater than
    `tier1_max_sqft`."

    Design: Difficulty/boundary_precision_check/sqft_tier1_boundary_2000_vs_2001_on_schedule
    """
    cfg = setup_base_config(certifications=["BUYER"])
    prop_4000 = create_property(square_footage=4000, address_line="A 4000")
    prop_4001 = create_property(square_footage=4001, address_line="B 4001")
    order_a = create_requested_order(cfg, property_id=prop_4000["id"])
    order_b = create_requested_order(cfg, property_id=prop_4001["id"])
    sched_a = validate_success(api.schedule_order(
        order_a["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-10T13:00:00Z"),
        SCHED))
    sched_b = validate_success(api.schedule_order(
        order_b["id"],
        F.schedule_order_payload(cfg["inspector"]["id"], "2026-07-11T13:00:00Z"),
        SCHED))
    # 4000 wholly within tiers 1+2: (15000 + 2000*12 + 2000*8)*1.0 = 55000.
    assert sched_a["quoted_fee_cents"] == 55000
    # 4001 pushes 1 sqft into tier 3: 55000 + 1*5 = 55005.
    assert sched_b["quoted_fee_cents"] == 55005


# ---------------------------------------------------------------------------
# dual variant: quoted (recorded sqft) vs final (measured sqft)
# ---------------------------------------------------------------------------
def test_quoted_vs_final_fee_diverge_on_measured_sqft(api):
    """PRD §3.7: "The forward-looking `quoted_fee_cents` is computed at scheduling (and
    at re-inspection) from the property's recorded `square_footage`; the
    `final_fee_cents` is computed at delivery from the report's `measured_square_footage`
    and is null until the order is `DELIVERED`."

    Design: Difficulty/dual_variant_calc/inspection_fee_quoted_vs_final_on_order
    """
    # Property recorded 2500, measured 2200, BUYER + RADON.
    # quoted = (15000+2000*12+500*8)*1.0 + 9900 = 43000 + 9900 = 52900.
    # final  = (15000+2000*12+200*8)*1.0 + 9900 = 40600 + 9900 = 50500.
    cfg, order, report, _ = setup_delivered_order(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-01T13:00:00Z", square_footage=2500,
        measured_square_footage=2200, addons=["RADON"], pay_amount=52900)
    assert order["status"] == "DELIVERED"
    assert order["quoted_fee_cents"] == 52900
    assert order["final_fee_cents"] == 50500
    assert order["final_fee_cents"] != order["quoted_fee_cents"]


def test_quoted_equals_final_when_measured_matches_recorded(api):
    """PRD §3.7: "The two may diverge whenever the measured footage differs from the
    recorded footage."
    PRD §3.7: "the `final_fee_cents` is computed at delivery from the report's
    `measured_square_footage` and is null until the order is `DELIVERED`."

    Design: Difficulty/dual_variant_calc/inspection_fee_quoted_vs_final_on_order
    """
    # Recorded 2200, measured 2200 -> quoted == final == 40600 (BUYER, no add-on).
    cfg, order, report, _ = setup_delivered_order(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-26T13:00:00Z", square_footage=2200,
        measured_square_footage=2200, addons=None, pay_amount=43000)
    assert order["quoted_fee_cents"] == 40600
    assert order["final_fee_cents"] == 40600
    assert order["final_fee_cents"] == order["quoted_fee_cents"]


# ---------------------------------------------------------------------------
# add-on duration and price pinning
# ---------------------------------------------------------------------------
def test_addon_recomputes_order_duration(api):
    """PRD §3.4: "An order's `duration_minutes` is the sum of a base value keyed on
    `inspection_type` — 180 minutes for `BUYER`, 150 for `SELLER`, 90 for `FOUR_POINT`,
    and 60 for `WIND_MIT` — plus the `added_duration_minutes` of every `ACTIVE` add-on
    on the order."
    PRD §3.4: "sets its `added_duration_minutes` from the fixed table where RADON
    contributes 30 minutes, TERMITE 20 minutes, and SEWER 45 minutes."

    Design: Corner/calculations/corner_addon_recompute_order_duration
    """
    cfg, order = setup_requested_order(inspection_type="BUYER")
    addon = validate_success(
        api.create_addon(order["id"], F.create_addon_payload("RADON"), SCHED), 201)
    assert addon["added_duration_minutes"] == 30
    refreshed = validate_success(api.get_inspection_order(order["id"], SCHED))
    assert refreshed["duration_minutes"] == 210


def test_addon_price_pinned_from_fee_schedule(api):
    """PRD §3.4: "pins its `price_cents` from the order's pinned fee schedule (the
    `addon_radon_cents`, `addon_termite_cents`, or `addon_sewer_cents` value)."

    Design: Corner/calculations/corner_addon_price_pinned_from_fee_schedule
    """
    cfg, order = setup_requested_order(inspection_type="BUYER")
    addon = validate_success(
        api.create_addon(order["id"], F.create_addon_payload("TERMITE"), SCHED), 201)
    assert addon["price_cents"] == 8500


def test_scheduled_order_quoted_fee_recomputed_after_addon(api):
    """PRD §3.4: "Creating an add-on recomputes the order's `duration_minutes`, and if
    the order is already `SCHEDULED`, recomputes its `quoted_fee_cents`; the order's
    `version` is incremented."

    Design: Corner/cross_cutting_complexity_layers/corner_derived_field_reconciliation_quoted_after_addon
    """
    # SCHEDULED BUYER 2200 quoted 40600; adding RADON (9900) -> 50500.
    cfg, order = setup_scheduled_order(inspection_type="BUYER", certifications=["BUYER"],
                                       scheduled_start="2026-08-19T13:00:00Z",
                                       square_footage=2200)
    assert order["quoted_fee_cents"] == 40600
    api_client.create_addon(order["id"], F.create_addon_payload("RADON"), SCHED)
    refreshed = validate_success(api.get_inspection_order(order["id"], SCHED))
    assert refreshed["quoted_fee_cents"] == 50500


# ---------------------------------------------------------------------------
# order balance after partial payment
# ---------------------------------------------------------------------------
def test_order_balance_after_partial_payment(api):
    """PRD §3.5: "From that effective fee, `amount_due_cents` is the effective fee minus
    `amount_paid_cents` plus `amount_refunded_cents`."
    PRD §3.5: "it is 0 while the order is `REQUESTED`, the `quoted_fee_cents` while the
    order is `SCHEDULED`, `IN_PROGRESS`, or `REPORT_DRAFT`, and the `final_fee_cents`
    once the order is `DELIVERED`."

    Design: Corner/calculations/corner_order_balance_after_partial_payment
    """
    # Scheduled BUYER 2200 quoted 40600; pay 20000 -> due 40600 - 20000 = 20600.
    cfg, order = setup_scheduled_order(inspection_type="BUYER", certifications=["BUYER"],
                                       scheduled_start="2026-08-05T13:00:00Z",
                                       square_footage=2200)
    paid = validate_success(
        api.pay_order(order["id"], F.pay_order_payload(20000), SCHED))
    assert paid["amount_due_cents"] == 20600


# ---------------------------------------------------------------------------
# re-inspection discount: band keyed on parent final_fee_cents
# ---------------------------------------------------------------------------
def test_reinspection_discount_mid_band(api):
    """PRD §3.8: "Then a discount fraction is selected by a band keyed on the parent
    order's `final_fee_cents`: when the parent's `final_fee_cents` is below 50000 cents,
    the fraction is the schedule's `reinspection_discount_pct`; when it is at least 50000
    but below 100000 cents, the fraction is `reinspection_discount_pct` plus 0.10; and
    when it is 100000 cents or more, the fraction is `reinspection_discount_pct` plus
    0.20, capped at a maximum of 0.90."
    PRD §3.8: "The re-inspection's fee is then the quoted fee multiplied by one minus
    the selected fraction, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/reinspection_fee_circular_discount_mode_c
    """
    # Parent BUYER 2500 + RADON, measured 2200 -> final 50500 (band [50000,100000) -> d=0.6).
    # New order BUYER 2500 no add-on quoted 43000 -> reinspect = round(43000*0.4) = 17200.
    cfg, parent, report = setup_delivered_failing_parent(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-19T13:00:00Z", property_sqft=2500,
        measured_square_footage=2200, defects=[("Panel", "MAJOR"), ("Foundation", "CRITICAL")],
        addons=["RADON"], pay_amount=52900)
    assert parent["final_fee_cents"] == 50500
    resp = reinspect(parent["id"], cfg["inspector"]["id"], "2026-07-22T13:00:00Z",
                     parent["version"])
    child = validate_success(resp, 201)
    assert child["order_kind"] == "REINSPECTION"
    assert child["quoted_fee_cents"] == 17200


def test_reinspection_discount_low_band(api):
    """PRD §3.8: "when the parent's `final_fee_cents` is below 50000 cents, the fraction
    is the schedule's `reinspection_discount_pct`."
    PRD §3.8: "The re-inspection's fee is then the quoted fee multiplied by one minus
    the selected fraction, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/reinspection_fee_low_band_discount_half
    """
    # Parent SELLER 2000 no add-on -> final 35100 (< 50000 -> d=0.5).
    # New order SELLER 2000 quoted 35100 -> reinspect = round(35100*0.5) = 17550.
    cfg, parent, report = setup_delivered_failing_parent(
        inspection_type="SELLER", certifications=["SELLER"], client_role="SELLER",
        scheduled_start="2026-07-20T13:00:00Z", property_sqft=2000,
        measured_square_footage=2000, defects=[("Panel", "MAJOR"), ("Foundation", "CRITICAL")],
        addons=None, pay_amount=35100)
    assert parent["final_fee_cents"] == 35100
    resp = reinspect(parent["id"], cfg["inspector"]["id"], "2026-07-23T13:00:00Z",
                     parent["version"])
    child = validate_success(resp, 201)
    assert child["quoted_fee_cents"] == 17550


def test_reinspection_spawns_scheduled_child_parent_stays_delivered(api):
    """PRD §3.8: "the parent remains `DELIVERED`, while a brand-new order is created in
    `SCHEDULED` with `order_kind` of `REINSPECTION` and its `parent_order_id` set to the
    parent's `id`."

    Design: Difficulty/combinatorial_formula/reinspection_fee_circular_discount_mode_c
    """
    cfg, parent, report = setup_delivered_failing_parent(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-09-01T13:00:00Z", property_sqft=2500,
        measured_square_footage=2200, defects=[("Panel", "MAJOR"), ("Foundation", "CRITICAL")],
        addons=["RADON"], pay_amount=52900)
    resp = reinspect(parent["id"], cfg["inspector"]["id"], "2026-09-04T13:00:00Z",
                     parent["version"])
    child = validate_success(resp, 201)
    assert child["order_kind"] == "REINSPECTION"
    assert child["status"] == "SCHEDULED"
    assert child["parent_order_id"] == parent["id"]
    parent_after = validate_success(api.get_inspection_order(parent["id"], SCHED))
    assert parent_after["status"] == "DELIVERED"


def test_reinspection_low_band_child_is_scheduled_reinspection(api):
    """PRD §3.8: "a brand-new order is created in `SCHEDULED` with `order_kind` of
    `REINSPECTION` and its `parent_order_id` set to the parent's `id`."

    Design: Difficulty/combinatorial_formula/reinspection_fee_low_band_discount_half
    """
    cfg, parent, report = setup_delivered_failing_parent(
        inspection_type="SELLER", certifications=["SELLER"], client_role="SELLER",
        scheduled_start="2026-09-05T13:00:00Z", property_sqft=2000,
        measured_square_footage=2000, defects=[("Panel", "MAJOR"), ("Foundation", "CRITICAL")],
        addons=None, pay_amount=35100)
    resp = reinspect(parent["id"], cfg["inspector"]["id"], "2026-09-08T13:00:00Z",
                     parent["version"])
    child = validate_success(resp, 201)
    assert child["order_kind"] == "REINSPECTION"
    assert child["status"] == "SCHEDULED"
    assert child["parent_order_id"] == parent["id"]
