"""Composite setup helpers.

Nearly every interesting claim in this contract needs a plant that already
exists: a settlement quote to price against, qualified compounds on an ACTIVE
listing file, a released SKU, a customer with credit, a rod heat with mass, and
often a lot walked all the way to CONFORMING on a loaded reel. These helpers
build that state through declared endpoints only, so a test body can be a
trigger plus assertions.

Every helper takes the ``ApiClient`` as its first argument and uses the lenient
``get_success_data`` validator, so a broken precondition reports as a setup
failure rather than as a confusing assertion mismatch.

Tiers
-----
1. State progression — walk one entity's state machine to a target state.
2. Entity hierarchy — definition layer (compounds, listing file, SKU) and the
   commercial layer (customer, order, rod heat) built together.
3. Full lifecycle shortcuts — lot through EXTRUDED / TESTED / CONFORMING, reel
   loaded, shipment staged, shipment invoiced.
4. Accumulation / threshold targeting — float-window price history, rod heats
   sized so a scrap lands exactly on the alert threshold, accounts positioned
   just under a credit limit.
5. Finalization / terminal state — returned reels, cancelled orders and
   scrapped lots for lockdown probes.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import CLOCK_EPOCH, TEST_DEFAULTS, THHN_12_CU_MARKING
from .factories import (
    create_catalog_product_payload,
    create_customer_order_payload,
    create_customer_payload,
    create_factory_inspection_payload,
    create_insulation_compound_payload,
    create_jacket_compound_payload,
    create_listing_certification_payload,
    create_metal_price_quote_payload,
    create_production_lot_payload,
    create_reel_payload,
    create_reel_return_payload,
    create_rod_purchase_lot_payload,
    create_shipment_payload,
    drawing_step_payload,
    extrusion_step_payload,
    hipot_test_payload,
    load_reel_payload,
    partial_discharge_test_payload,
    rework_disposition_payload,
    scrap_disposition_payload,
    spark_test_payload,
    stranding_step_payload,
)
from .test_users import (
    ADMIN,
    BILLING,
    BUYER,
    CERT_OFFICER,
    CLERK,
    ENGINEER,
    QE_DISPOSITIONER,
    QE_RELEASER,
    QE_TESTER,
    make_customer_headers,
)

# ===========================================================================
# Primitives
# ===========================================================================


def set_clock(api, current_utc=CLOCK_EPOCH):
    """Pin the logical UTC clock. Only PlantAdmin may move it."""
    return get_success_data(api.set_current_utc(current_utc, ADMIN))


def create_metal_quote(api, **overrides):
    return get_success_data(
        api.create_metal_price_quote(create_metal_price_quote_payload(**overrides), BUYER)
    )


def create_rod_lot(api, **overrides):
    return get_success_data(
        api.create_rod_purchase_lot(create_rod_purchase_lot_payload(**overrides), BUYER)
    )


def current_rod_lot_version(api, rod_lot_id):
    """Re-read a heat so the next allocation carries a fresh expected version."""
    return get_success_data(api.get_rod_purchase_lot(rod_lot_id, BUYER))["version"]


def current_order_version(api, order_id):
    """Re-read an order so the next staging carries a fresh expected version."""
    return get_success_data(api.get_customer_order(order_id, CLERK))["version"]


def create_qualified_compound(api, payload):
    """Create a compound and walk it DRAFT -> QUALIFIED."""
    compound = get_success_data(api.create_compound(payload, ENGINEER))
    return get_success_data(api.qualify_compound(compound["id"], ENGINEER))


def create_active_certification(api, cert_overrides=None, inspection_overrides=None):
    """Create a listing file and pass its first factory visit, so it goes ACTIVE."""
    cert = get_success_data(
        api.create_listing_certification(
            create_listing_certification_payload(**(cert_overrides or {})), CERT_OFFICER
        )
    )
    get_success_data(
        api.create_factory_inspection(
            cert["id"],
            create_factory_inspection_payload(**(inspection_overrides or {})),
            CERT_OFFICER,
        )
    )
    return get_success_data(api.get_listing_certification(cert["id"], CERT_OFFICER))


def create_released_product(api, insulation_compound_id, listing_certification_id,
                            **overrides):
    product = get_success_data(
        api.create_catalog_product(
            create_catalog_product_payload(
                insulation_compound_id, listing_certification_id, **overrides
            ),
            ENGINEER,
        )
    )
    return get_success_data(api.release_catalog_product(product["id"], ENGINEER))


def create_draft_product(api, insulation_compound_id, listing_certification_id,
                          **overrides):
    return get_success_data(
        api.create_catalog_product(
            create_catalog_product_payload(
                insulation_compound_id, listing_certification_id, **overrides
            ),
            ENGINEER,
        )
    )


def create_customer(api, **overrides):
    return get_success_data(api.create_customer(create_customer_payload(**overrides), BILLING))


def create_order(api, customer_id, product_id, **overrides):
    return get_success_data(
        api.create_customer_order(
            create_customer_order_payload(customer_id, product_id, **overrides), BILLING
        )
    )


def create_reel(api, **overrides):
    return get_success_data(api.create_reel(create_reel_payload(**overrides), CLERK))


# ===========================================================================
# Tier 2: Entity hierarchy
# ===========================================================================


def setup_lv_catalog(api, clock=CLOCK_EPOCH, quote_overrides=None,
                     product_overrides=None, with_jacket=False):
    """Clock + COPPER quote + qualified insulation (+ jacket) + ACTIVE UL file +
    released LV_600 THHN 12 AWG copper SKU.

    Returns a dict with keys ``insulation``, ``jacket`` (or None),
    ``certification``, ``product`` and ``quote``.
    """
    set_clock(api, clock)
    quote = create_metal_quote(api, **(quote_overrides or {}))
    insulation = create_qualified_compound(api, create_insulation_compound_payload())
    jacket = None
    overrides = dict(product_overrides or {})
    if with_jacket:
        jacket = create_qualified_compound(api, create_jacket_compound_payload())
        overrides.setdefault("jacket_compound_id", jacket["id"])
    certification = create_active_certification(api)
    product = create_released_product(
        api, insulation["id"], certification["id"], **overrides
    )
    return {
        "quote": quote,
        "insulation": insulation,
        "jacket": jacket,
        "certification": certification,
        "product": product,
    }


def setup_mv_catalog(api, clock=CLOCK_EPOCH):
    """The MV_15KV variant: an MV_105 SKU rated 105 C on a 15 kV class, which the
    PRD derives as marking-exempt and partial-discharge-required.

    Returns the same shape as :func:`setup_lv_catalog`.
    """
    set_clock(api, clock)
    quote = create_metal_quote(api)
    insulation = create_qualified_compound(
        api,
        create_insulation_compound_payload(
            compound_code="EPR-105-INS", temp_rating_c=105, max_voltage_v=15000,
            flame_test="FT4", filler_pct=8.0,
        ),
    )
    certification = create_active_certification(api)
    product = create_released_product(
        api,
        insulation["id"],
        certification["id"],
        product_code="MV105-2-CU",
        awg_size="2",
        application_rating="MV_105",
        voltage_class="MV_15KV",
        temp_rating_c=105,
        insulation_thickness_mils=175.0,
        conductor_lbs_per_kft=205.0,
        base_target_kft=20.0,
    )
    return {
        "quote": quote,
        "insulation": insulation,
        "jacket": None,
        "certification": certification,
        "product": product,
    }


def setup_baseline(api, clock=CLOCK_EPOCH, quote_overrides=None,
                   product_overrides=None, customer_overrides=None,
                   order_overrides=None, rod_overrides=None, with_order=True,
                   with_jacket=False):
    """The canonical plant: definition layer + customer + order + rod heat.

    Returns a dict with ``quote``, ``insulation``, ``jacket``, ``certification``,
    ``product``, ``customer``, ``order`` (or None) and ``rod_lot``.
    """
    world = setup_lv_catalog(
        api,
        clock=clock,
        quote_overrides=quote_overrides,
        product_overrides=product_overrides,
        with_jacket=with_jacket,
    )
    world["customer"] = create_customer(api, **(customer_overrides or {}))
    world["order"] = (
        create_order(
            api,
            world["customer"]["id"],
            world["product"]["id"],
            **(order_overrides or {}),
        )
        if with_order
        else None
    )
    world["rod_lot"] = create_rod_lot(api, **(rod_overrides or {}))
    return world


def setup_definitions_and_rod(api, clock=CLOCK_EPOCH, product_overrides=None,
                              rod_overrides=None):
    """Definition layer + rod heat, with no customer or order.

    The PRD makes ``order_id`` optional on a production lot, so this is the
    smallest world in which a lot can be created.
    """
    world = setup_lv_catalog(api, clock=clock, product_overrides=product_overrides)
    world["customer"] = None
    world["order"] = None
    world["rod_lot"] = create_rod_lot(api, **(rod_overrides or {}))
    return world


# ===========================================================================
# Tier 1 / Tier 3: ProductionLot state progression and lifecycle shortcuts
# ===========================================================================


def create_lot(api, world, **overrides):
    """Allocate a production lot against the world's rod heat with a fresh version."""
    rod_version = current_rod_lot_version(api, world["rod_lot"]["id"])
    payload = create_production_lot_payload(
        world["product"]["id"], world["rod_lot"]["id"], rod_version, **overrides
    )
    if world.get("order") and "order_id" not in payload:
        payload["order_id"] = world["order"]["id"]
    return get_success_data(api.create_production_lot(payload, ENGINEER))


def advance_lot_to_drawn(api, lot_id):
    return get_success_data(
        api.create_process_step(lot_id, drawing_step_payload(), ENGINEER)
    )


def advance_lot_to_stranded(api, lot_id):
    advance_lot_to_drawn(api, lot_id)
    return get_success_data(
        api.create_process_step(lot_id, stranding_step_payload(), ENGINEER)
    )


def advance_lot_to_extruded(api, lot_id, extrusion_overrides=None, from_stranded=True):
    """Walk QUEUED -> DRAWN -> STRANDED -> EXTRUDED (or skip stranding for SOLID)."""
    if from_stranded:
        advance_lot_to_stranded(api, lot_id)
    else:
        advance_lot_to_drawn(api, lot_id)
    return get_success_data(
        api.create_process_step(
            lot_id, extrusion_step_payload(**(extrusion_overrides or {})), ENGINEER
        )
    )


def record_inline_tests(api, lot_id, hipot_overrides=None, spark_overrides=None,
                         tester_headers=QE_TESTER):
    """Record the inline pair (SPARK then HIPOT) that promotes EXTRUDED -> TESTED."""
    spark = get_success_data(
        api.create_cable_test(lot_id, spark_test_payload(**(spark_overrides or {})),
                              tester_headers)
    )
    hipot = get_success_data(
        api.create_cable_test(lot_id, hipot_test_payload(**(hipot_overrides or {})),
                              tester_headers)
    )
    return {"spark": spark, "hipot": hipot}


def record_partial_discharge(api, lot_id, tester_headers=QE_TESTER, **overrides):
    return get_success_data(
        api.create_cable_test(
            lot_id, partial_discharge_test_payload(**overrides), tester_headers
        )
    )


def advance_lot_to_tested(api, lot_id, extrusion_overrides=None, hipot_overrides=None,
                          from_stranded=True, tester_headers=QE_TESTER):
    advance_lot_to_extruded(
        api, lot_id, extrusion_overrides=extrusion_overrides, from_stranded=from_stranded
    )
    record_inline_tests(
        api, lot_id, hipot_overrides=hipot_overrides, tester_headers=tester_headers
    )
    return get_success_data(api.get_production_lot(lot_id, ENGINEER))


def release_lot(api, lot_id, packaged_length_ft, releaser_headers=QE_RELEASER):
    return get_success_data(
        api.release_production_lot(
            lot_id, {"packaged_length_ft": packaged_length_ft}, releaser_headers
        )
    )


def setup_released_lot(api, world=None, planned_length_ft=5000, lot_overrides=None,
                       extrusion_overrides=None, **baseline_kwargs):
    """A CONFORMING lot ready to load: create -> extrude -> test -> release.

    Returns ``(world, lot)`` where ``lot`` is the released lot payload.
    """
    if world is None:
        world = setup_baseline(api, **baseline_kwargs)
    overrides = dict(lot_overrides or {})
    overrides.setdefault("planned_length_ft", planned_length_ft)
    lot = create_lot(api, world, **overrides)
    advance_lot_to_tested(api, lot["id"], extrusion_overrides=extrusion_overrides)
    lot = release_lot(api, lot["id"], planned_length_ft)
    return world, lot


def setup_nonconforming_lot(api, world=None, planned_length_ft=5000,
                            extrusion_overrides=None, **baseline_kwargs):
    """An EXTRUDED lot whose measurements put the quality dimension at
    NONCONFORMING, ready for a disposition. Defaults to concentricity 80.00."""
    if world is None:
        world = setup_baseline(api, **baseline_kwargs)
    lot = create_lot(api, world, planned_length_ft=planned_length_ft)
    overrides = dict(extrusion_overrides or {"measured_min_wall_mils": 24.0})
    advance_lot_to_extruded(api, lot["id"], extrusion_overrides=overrides)
    return world, get_success_data(api.get_production_lot(lot["id"], ENGINEER))


def rework_lot(api, lot_id, rewind_to="STRANDED", reason=None):
    payload = rework_disposition_payload(rewind_to=rewind_to)
    if reason:
        payload["reason"] = reason
    return get_success_data(
        api.disposition_production_lot(lot_id, payload, QE_DISPOSITIONER)
    )


def scrap_lot(api, lot_id, reason=None, headers=QE_DISPOSITIONER):
    payload = scrap_disposition_payload()
    if reason:
        payload["reason"] = reason
    return get_success_data(api.disposition_production_lot(lot_id, payload, headers))


# ===========================================================================
# Tier 3: Reel and shipment lifecycle shortcuts
# ===========================================================================


def setup_loaded_reel(api, world=None, lot=None, load_length_ft=None,
                      reel_overrides=None, occupancy_start_at="2026-08-03T00:00:00Z",
                      **baseline_kwargs):
    """A reel holding a CONFORMING lot, which packages the lot.

    Returns ``(world, lot, reel)``.
    """
    if lot is None:
        world, lot = setup_released_lot(api, world=world, **baseline_kwargs)
    reel = create_reel(api, **(reel_overrides or {}))
    length = load_length_ft if load_length_ft is not None else lot["packaged_length_ft"]
    reel = get_success_data(
        api.load_reel(
            reel["id"],
            load_reel_payload(lot["id"], length, occupancy_start_at=occupancy_start_at),
            CLERK,
        )
    )
    return world, lot, reel


def setup_staged_shipment(api, world=None, lot=None, reel=None,
                          shipped_length_ft=None, shipment_overrides=None,
                          **loaded_reel_kwargs):
    """A STAGED shipment, which charges the reel deposit to the account.

    Returns ``(world, lot, reel, shipment)``.
    """
    if reel is None:
        world, lot, reel = setup_loaded_reel(
            api, world=world, lot=lot, **loaded_reel_kwargs
        )
    length = (
        shipped_length_ft if shipped_length_ft is not None else reel["loaded_length_ft"]
    )
    order_version = current_order_version(api, world["order"]["id"])
    payload = create_shipment_payload(
        world["order"]["id"], lot["id"], reel["id"], length, order_version,
        **(shipment_overrides or {}),
    )
    shipment = get_success_data(api.create_shipment(payload, CLERK))
    return world, lot, reel, shipment


def setup_invoiced_shipment(api, world=None, **staged_kwargs):
    """A shipment carried all the way through invoicing.

    Returns ``(world, lot, reel, shipment)`` with ``shipment`` INVOICED.
    """
    world, lot, reel, shipment = setup_staged_shipment(api, world=world, **staged_kwargs)
    shipment = get_success_data(api.invoice_shipment(shipment["id"], BILLING))
    return world, lot, reel, shipment


def setup_full_lifecycle(api, **baseline_kwargs):
    """Clock through invoice on the canonical LV line, in one call.

    Returns a dict with ``world``, ``lot``, ``reel``, ``shipment`` plus the
    refreshed ``customer`` and ``order`` rows the invoice moved.
    """
    world, lot, reel, shipment = setup_invoiced_shipment(api, **baseline_kwargs)
    return {
        "world": world,
        "lot": lot,
        "reel": reel,
        "shipment": shipment,
        "customer": get_success_data(api.get_customer(world["customer"]["id"], BILLING)),
        "order": get_success_data(api.get_customer_order(world["order"]["id"], BILLING)),
    }


# ===========================================================================
# Tier 4: Accumulation / threshold targeting
# ===========================================================================


def setup_float_window_quotes(api, metal="COPPER", prices=(4.00, 4.05, 4.10),
                              dates=("2026-08-01", "2026-08-02", "2026-08-03")):
    """Post one quote per date so a SHIP_DATE_FLOAT window holds exactly len(prices).

    The float variant averages the settlement prices whose ``effective_date``
    falls inside the trailing window ending at the ship date, and refuses to
    price when the window holds fewer than the declared minimum.
    """
    quotes = []
    for price, date in zip(prices, dates):
        quotes.append(
            create_metal_quote(api, metal=metal, effective_date=date,
                               settlement_price_usd_per_lb=price)
        )
    return quotes


def setup_volatility_history(api, metal="COPPER", prices=None, start_day=1):
    """Post a run of consecutive daily quotes so the volatility window is populated.

    ``prices`` are applied to 2026-08-{start_day..}. The volatility index is
    computed from the trailing window of settlement prices and only becomes
    non-zero once the window holds at least the declared minimum count.
    """
    prices = prices or [4.00, 4.10, 4.20]
    quotes = []
    for offset, price in enumerate(prices):
        date = f"2026-08-{start_day + offset:02d}"
        quotes.append(
            create_metal_quote(api, metal=metal, effective_date=date,
                               settlement_price_usd_per_lb=price)
        )
    return quotes


def setup_rod_lot_sized_for(api, consumed_lbs, **overrides):
    """A heat whose ``purchase_weight_lbs`` is exactly ``consumed_lbs``, so one
    allocation drives ``remaining_lbs`` to 0.00 and the next is refused."""
    return create_rod_lot(api, purchase_weight_lbs=consumed_lbs, **overrides)


def setup_scrap_boundary_world(api, rod_weight_lbs=1000.00, clock=CLOCK_EPOCH):
    """A 10 AWG SKU at 20.0 lbs/kft against a heat of ``rod_weight_lbs``.

    Sized so that 5000 ft of cable is exactly 100.00 lbs — exactly ten percent
    of a 1000.00 lb heat — which is where the scrap-alert threshold sits.
    Returns the world dict, with the SKU released and the heat received.
    """
    world = setup_lv_catalog(
        api,
        clock=clock,
        product_overrides={
            "product_code": "THHN-10-CU",
            "awg_size": "10",
            "conductor_lbs_per_kft": 20.0,
            "insulation_thickness_mils": 30.0,
            "base_target_kft": 60.0,
        },
    )
    world["customer"] = None
    world["order"] = None
    world["rod_lot"] = create_rod_lot(
        api, heat_number="H-88R", purchase_weight_lbs=rod_weight_lbs
    )
    return world


def setup_customer_at_credit_limit(api, credit_limit_usd, **baseline_kwargs):
    """A baseline whose account carries the given limit, for fiscal-ceiling probes."""
    overrides = dict(baseline_kwargs.pop("customer_overrides", None) or {})
    overrides["credit_limit_usd"] = credit_limit_usd
    return setup_baseline(api, customer_overrides=overrides, **baseline_kwargs)


def lower_credit_limit(api, customer_id, credit_limit_usd):
    """Re-run the exposure comparison by moving the limit under the ledger."""
    return get_success_data(
        api.patch_customer(customer_id, {"credit_limit_usd": credit_limit_usd}, BILLING)
    )


# ===========================================================================
# Tier 5: Finalization / terminal state
# ===========================================================================


def setup_returned_reel(api, returned_date, condition="GOOD", return_clock=None,
                       **lifecycle_kwargs):
    """Full lifecycle through the reel coming back, which settles the deposit.

    Returns a dict with ``world``, ``lot``, ``reel``, ``shipment`` and ``reel_return``.
    """
    state = setup_full_lifecycle(api, **lifecycle_kwargs)
    if return_clock:
        set_clock(api, return_clock)
    state["reel_return"] = get_success_data(
        api.create_reel_return(
            state["reel"]["id"],
            create_reel_return_payload(state["shipment"]["id"], returned_date, condition),
            CLERK,
        )
    )
    state["customer"] = get_success_data(
        api.get_customer(state["world"]["customer"]["id"], BILLING)
    )
    state["reel"] = get_success_data(api.get_reel(state["reel"]["id"], CLERK))
    return state


def setup_cancelled_order(api, world=None, planned_length_ft=5000, **baseline_kwargs):
    """An order cancelled while its only lot is still QUEUED.

    The compensating close returns the committed metal to the available bucket
    and shuts the lot down without scrapping it. Returns ``(world, lot, order)``.
    """
    if world is None:
        world = setup_baseline(api, **baseline_kwargs)
    lot = create_lot(api, world, planned_length_ft=planned_length_ft)
    order = get_success_data(
        api.cancel_customer_order(
            world["order"]["id"], BILLING,
            {"reason": "customer released the job to another mill"},
        )
    )
    return world, get_success_data(api.get_production_lot(lot["id"], ENGINEER)), order


def setup_certification_with_lapsed_variation(api, clock=CLOCK_EPOCH):
    """A UL file sitting in VARIATION_NOTICE with its corrective window expired.

    Listed 2026-01-01 on a 90-day interval; a PASS visit on 2026-04-01 activates
    it; a VARIATION visit on 2026-06-01 opens a corrective action due 2026-07-01
    and moves the file to VARIATION_NOTICE; the clock then stands past that date.
    Returns ``(certification, inspections)``.
    """
    set_clock(api, clock)
    cert = get_success_data(
        api.create_listing_certification(
            create_listing_certification_payload(
                initial_listing_date="2026-01-01", inspection_interval_days=90
            ),
            CERT_OFFICER,
        )
    )
    passing = get_success_data(
        api.create_factory_inspection(
            cert["id"],
            create_factory_inspection_payload(
                inspection_date="2026-04-01", inspector_code="INS-1",
                findings_count=0, outcome="PASS",
            ),
            CERT_OFFICER,
        )
    )
    variation = get_success_data(
        api.create_factory_inspection(
            cert["id"],
            create_factory_inspection_payload(
                inspection_date="2026-06-01", inspector_code="INS-2",
                findings_count=3, outcome="VARIATION",
            ),
            CERT_OFFICER,
        )
    )
    cert = get_success_data(api.get_listing_certification(cert["id"], CERT_OFFICER))
    return cert, {"passing": passing, "variation": variation}


def setup_suspended_certification(api, world=None, suspend_inspection_date="2026-08-06",
                                  **baseline_kwargs):
    """Drive a live listing file to SUSPENDED through a failing follow-up visit.

    The suspension is the head of the deepest declared cascade, so this helper
    returns the whole world it was applied to. Returns ``(world, inspection)``.
    """
    if world is None:
        world = setup_baseline(api, **baseline_kwargs)
    inspection = get_success_data(
        api.create_factory_inspection(
            world["certification"]["id"],
            create_factory_inspection_payload(
                inspection_date=suspend_inspection_date, inspector_code="INS-9",
                findings_count=7, outcome="SUSPEND",
            ),
            CERT_OFFICER,
        )
    )
    return world, inspection


# ===========================================================================
# Convenience read helpers
# ===========================================================================


def read_lot(api, lot_id):
    return get_success_data(api.get_production_lot(lot_id, ENGINEER))


def read_rod_lot(api, rod_lot_id):
    return get_success_data(api.get_rod_purchase_lot(rod_lot_id, BUYER))


def read_customer(api, customer_id):
    return get_success_data(api.get_customer(customer_id, BILLING))


def read_order(api, order_id):
    return get_success_data(api.get_customer_order(order_id, BILLING))


def read_reel(api, reel_id):
    return get_success_data(api.get_reel(reel_id, CLERK))


def read_shipment(api, shipment_id):
    return get_success_data(api.get_shipment(shipment_id, CLERK))


def read_certification(api, certification_id):
    return get_success_data(api.get_listing_certification(certification_id, CERT_OFFICER))


def read_compound(api, compound_id):
    return get_success_data(api.get_compound(compound_id, ENGINEER))


def read_product(api, product_id):
    return get_success_data(api.get_catalog_product(product_id, ENGINEER))


def read_own_order_as_customer(api, order_id, customer_id):
    """Ownership-gated read: the Customer role is entity-backed, so the acting
    ``X-User-ID`` must be the account's own id."""
    return get_success_data(
        api.get_customer_order(order_id, make_customer_headers(customer_id))
    )


CANONICAL_MARKING_TEXT = THHN_12_CU_MARKING
CANONICAL_ROD_WEIGHT_LBS = TEST_DEFAULTS["ROD_WEIGHT_LBS"]
