"""Composite setup helpers.

Every fixture reaches its state through PRD-declared endpoints only, so a test
can start from an empty database and still assert against deep plant state.
Setup calls use get_success_data() so a broken prerequisite reports itself as a
setup failure rather than as a confusing assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CANON, TOW
from .factories import (
    advance_payload,
    chassis_receipt_payload,
    clock_payload,
    complete_inspection_payload,
    component_installation_payload,
    component_lot_payload,
    configuration_payload,
    dealer_payload,
    delivered_unit_payload,
    expand_campaign_payload,
    floor_plan_payload,
    option_item_payload,
    production_line_payload,
    production_slot_payload,
    quality_inspection_payload,
    recall_campaign_payload,
    supplier_payload,
    test_booth_payload,
    unit_order_payload,
    warranty_claim_payload,
)
from .test_users import TEST_USERS, make_dealer_principal_headers

PLANT_ADMIN = TEST_USERS["plant_admin_headers"]
SCHEDULER = TEST_USERS["production_scheduler_headers"]
SUPERVISOR = TEST_USERS["line_supervisor_headers"]
INSPECTOR_1 = TEST_USERS["quality_inspector_headers"]
INSPECTOR_2 = TEST_USERS["quality_inspector_2_headers"]
WARRANTY_1 = TEST_USERS["warranty_admin_headers"]
WARRANTY_2 = TEST_USERS["warranty_admin_2_headers"]
RECALL = TEST_USERS["recall_coordinator_headers"]


# ─── Tier 0: ops and single-row creators ───────────────────────────────────

def advance_clock(current_utc: str) -> dict:
    return get_success_data(api_client.set_clock(clock_payload(current_utc), PLANT_ADMIN))


def run_daily_close() -> dict:
    return get_success_data(api_client.daily_close(PLANT_ADMIN))


def create_supplier(**overrides) -> dict:
    return get_success_data(api_client.create_supplier(supplier_payload(**overrides), PLANT_ADMIN))


def create_floor_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_floor_plan(floor_plan_payload(**overrides), PLANT_ADMIN)
    )


def create_option_item(**overrides) -> dict:
    return get_success_data(
        api_client.create_option_item(option_item_payload(**overrides), PLANT_ADMIN)
    )


def create_dealer(**overrides) -> dict:
    return get_success_data(api_client.create_dealer(dealer_payload(**overrides), PLANT_ADMIN))


def create_production_line(**overrides) -> dict:
    return get_success_data(
        api_client.create_production_line(production_line_payload(**overrides), PLANT_ADMIN)
    )


def create_test_booth(**overrides) -> dict:
    return get_success_data(
        api_client.create_test_booth(test_booth_payload(**overrides), PLANT_ADMIN)
    )


def create_chassis_receipt(supplier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_chassis_receipt(
            chassis_receipt_payload(supplier_id, **overrides), PLANT_ADMIN
        )
    )


def create_component_lot(supplier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_component_lot(
            component_lot_payload(supplier_id, **overrides), PLANT_ADMIN
        )
    )


def inject_delivered_unit(dealer_id: str, floor_plan_id: str, **overrides) -> dict:
    """PRD §3.1 test-driving capability: materialise a shipped coach in one call."""
    return get_success_data(
        api_client.inject_delivered_unit(
            delivered_unit_payload(dealer_id, floor_plan_id, **overrides), PLANT_ADMIN
        )
    )


# ─── Tier 1: order progression ─────────────────────────────────────────────

def create_order(dealer_id: str, floor_plan_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_unit_order(
            unit_order_payload(dealer_id, floor_plan_id, **overrides),
            make_dealer_principal_headers(dealer_id),
        )
    )


def replace_configuration(order_id: str, dealer_id: str, option_ids, **overrides) -> dict:
    return get_success_data(
        api_client.replace_configuration(
            order_id,
            configuration_payload(option_ids, **overrides),
            make_dealer_principal_headers(dealer_id),
        )
    )


def submit_order(order_id: str, dealer_id: str) -> dict:
    return get_success_data(
        api_client.submit_order(order_id, make_dealer_principal_headers(dealer_id))
    )


def create_submitted_order(dealer_id: str, floor_plan_id: str, **overrides) -> dict:
    order = create_order(dealer_id, floor_plan_id, **overrides)
    return submit_order(order["id"], dealer_id)


def reserve_slot(order_id: str, line_id: str, slot_date: str, expected_version: int) -> dict:
    return get_success_data(
        api_client.reserve_production_slot(
            order_id, production_slot_payload(line_id, slot_date, expected_version), SCHEDULER
        )
    )


def match_chassis(order_id: str) -> dict:
    return get_success_data(api_client.match_chassis(order_id, SCHEDULER))


def release_to_line(order_id: str) -> dict:
    return get_success_data(api_client.release_to_line(order_id, SCHEDULER))


def ship_order(order_id: str) -> dict:
    return get_success_data(api_client.ship_order(order_id, SCHEDULER))


def read_order(order_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_unit_order(order_id, headers or PLANT_ADMIN))


def read_dealer(dealer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_dealer(dealer_id, headers or PLANT_ADMIN))


def read_build(build_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_unit_build(build_id, headers or PLANT_ADMIN))


def read_lot(lot_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_component_lot(lot_id, headers or PLANT_ADMIN))


# ─── Tier 1: financing progression ─────────────────────────────────────────

def request_funding(order_id: str, dealer_id: str) -> dict:
    return get_success_data(
        api_client.request_funding(order_id, make_dealer_principal_headers(dealer_id))
    )


def decide_funding(order_id: str, decision: str = "APPROVED", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(api_client.funding_decision(order_id, payload, PLANT_ADMIN))


def fund_order(order_id: str, dealer_id: str) -> dict:
    """Request funding and approve it, leaving the order FLOOR_PLAN_FUNDED."""
    request_funding(order_id, dealer_id)
    return decide_funding(order_id, "APPROVED")


def pay_floor_plan(order_id: str, dealer_id: str, amount_cents: int) -> dict:
    return get_success_data(
        api_client.floor_plan_payment(
            order_id, {"amount_cents": amount_cents}, make_dealer_principal_headers(dealer_id)
        )
    )


# ─── Tier 1: shop-floor progression ────────────────────────────────────────

def advance_build(build_id: str, to_station: str, station_hours_used, headers=None) -> dict:
    return get_success_data(
        api_client.advance_build(
            build_id, advance_payload(to_station, station_hours_used), headers or SUPERVISOR
        )
    )


def walk_build(build_id: str, steps) -> dict:
    """Advance a build through an iterable of (to_station, station_hours_used)."""
    build = None
    for to_station, hours in steps:
        build = advance_build(build_id, to_station, hours)
    return build


def install_pieces(build_id: str, lot_id: str, station: str, quantity: int) -> dict:
    return get_success_data(
        api_client.create_component_installation(
            component_installation_payload(build_id, lot_id, station, quantity), SUPERVISOR
        )
    )


def schedule_pdi(build_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.create_quality_inspection(
            quality_inspection_payload(build_id, "PDI"), headers or INSPECTOR_1
        )
    )


def schedule_booth_inspection(
    build_id: str,
    booth_id: str,
    window_start: str,
    window_end: str,
    inspection_type: str = "WATER_TEST",
    headers=None,
) -> dict:
    return get_success_data(
        api_client.create_quality_inspection(
            quality_inspection_payload(
                build_id,
                inspection_type,
                test_booth_id=booth_id,
                window_start=window_start,
                window_end=window_end,
            ),
            headers or INSPECTOR_1,
        )
    )


def complete_inspection(
    inspection_id: str, defect_points: int, leak_detected: bool, headers=None
) -> dict:
    return get_success_data(
        api_client.complete_inspection(
            inspection_id,
            complete_inspection_payload(defect_points, leak_detected),
            headers or INSPECTOR_1,
        )
    )


# ─── Tier 1: warranty and recall progression ───────────────────────────────

def file_claim(dealer_id: str, build_id: str, claim_type: str = "APPLIANCE", **overrides) -> dict:
    return get_success_data(
        api_client.create_warranty_claim(
            warranty_claim_payload(build_id, claim_type, **overrides),
            make_dealer_principal_headers(dealer_id),
        )
    )


def decide_claim(claim_id: str, decision: str = "APPROVED", headers=None, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(api_client.decide_claim(claim_id, payload, headers or WARRANTY_1))


def draft_campaign(supplier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_recall_campaign(
            recall_campaign_payload(supplier_id, **overrides), RECALL
        )
    )


def open_campaign(campaign_id: str) -> dict:
    return get_success_data(api_client.open_recall_campaign(campaign_id, RECALL))


def expand_campaign(campaign_id: str, additional_lot_codes, expected_version: int) -> dict:
    return get_success_data(
        api_client.expand_recall_campaign(
            campaign_id, expand_campaign_payload(additional_lot_codes, expected_version), RECALL
        )
    )


def draft_and_open_campaign(supplier_id: str, **overrides) -> dict:
    campaign = draft_campaign(supplier_id, **overrides)
    return open_campaign(campaign["id"])


# ─── Tier 2: master-data kits ──────────────────────────────────────────────

def build_tow_kit(
    with_supplier: bool = True,
    with_chassis: bool = True,
    with_booth: bool = True,
    supplier=None,
    floor_plan=None,
    option=None,
    dealer=None,
    line=None,
    booth=None,
    chassis=None,
) -> dict:
    """One towable floor plan, one electrical option, one dealer, one line.

    A STOCK order on the single option costs 41.00 required station hours and
    6620350 provisional cents against this kit.
    """
    kit = {}
    if with_supplier or with_chassis:
        kit["supplier"] = create_supplier(**(supplier or {}))
    kit["floor_plan"] = create_floor_plan(
        **{
            "model_code": TOW["FP_MODEL_CODE"],
            "chassis_class": "TOWABLE",
            "length_ft": TOW["FP_LENGTH_FT"],
            "base_msrp_cents": TOW["FP_BASE_MSRP_CENTS"],
            "base_station_hours": TOW["FP_BASE_STATION_HOURS"],
            "base_dry_weight_lbs": TOW["FP_BASE_DRY_WEIGHT_LBS"],
            "gvwr_lbs": TOW["FP_GVWR_LBS"],
            "required_wheelbase_in": TOW["FP_WHEELBASE_IN"],
            "electrical_service_amps": TOW["FP_AMPS"],
            "fresh_water_capacity_gal": TOW["FP_WATER_GAL"],
            **(floor_plan or {}),
        }
    )
    kit["option"] = create_option_item(
        **{
            "option_code": TOW["OPT_CODE"],
            "category": "ELECTRICAL",
            "install_station": "ROUGH_IN",
            "price_cents": TOW["OPT_PRICE_CENTS"],
            "weight_lbs": 0,
            "added_station_hours": TOW["OPT_STATION_HOURS"],
            "amp_draw": TOW["OPT_AMPS"],
            "water_demand_gal": 0,
            **(option or {}),
        }
    )
    kit["dealer"] = create_dealer(
        **{
            "dealer_code": TOW["DEALER_CODE"],
            "region": TOW["DEALER_REGION"],
            "allocation_share_bp": TOW["DEALER_SHARE_BP"],
            "floor_plan_credit_limit_cents": TOW["DEALER_CREDIT_LIMIT_CENTS"],
            "goodwill_budget_cents": TOW["DEALER_GOODWILL_CENTS"],
            **(dealer or {}),
        }
    )
    kit["line"] = create_production_line(
        **{
            "line_code": TOW["LINE_CODE"],
            "chassis_class_supported": "TOWABLE",
            "daily_station_hour_capacity": TOW["LINE_HOURS"],
            "max_units_per_day": TOW["LINE_UNITS"],
            **(line or {}),
        }
    )
    if with_chassis:
        kit["chassis"] = create_chassis_receipt(
            kit["supplier"]["id"],
            **{
                "chassis_serial": TOW["CHASSIS_SERIAL"],
                "chassis_class": "TOWABLE",
                "gvwr_lbs": TOW["FP_GVWR_LBS"],
                "wheelbase_in": TOW["FP_WHEELBASE_IN"],
                **(chassis or {}),
            },
        )
    if with_booth:
        kit["booth"] = create_test_booth(
            **{
                "booth_code": TOW["BOOTH_CODE"],
                "booth_type": "WATER_TEST",
                "bay_count": 1,
                "turnaround_minutes": 30,
                **(booth or {}),
            }
        )
    return kit


CANON_OPTION_SPECS = [
    {
        "option_code": "OPT-AC2",
        "category": "ELECTRICAL",
        "install_station": "ROOF_SET",
        "price_cents": 385000,
        "weight_lbs": 95,
        "added_station_hours": 2.50,
        "amp_draw": 16,
        "water_demand_gal": 0,
    },
    {
        "option_code": "OPT-WASH",
        "category": "APPLIANCE",
        "install_station": "APPLIANCE_INSTALL",
        "price_cents": 245500,
        "weight_lbs": 180,
        "added_station_hours": 3.00,
        "amp_draw": 12,
        "water_demand_gal": 0,
    },
    {
        "option_code": "OPT-BATT",
        "category": "ELECTRICAL",
        "install_station": "ROUGH_IN",
        "price_cents": 415000,
        "weight_lbs": 130,
        "added_station_hours": 2.00,
        "amp_draw": 0,
        "water_demand_gal": 0,
    },
    {
        "option_code": "OPT-INV",
        "category": "ELECTRICAL",
        "install_station": "ROUGH_IN",
        "price_cents": 165000,
        "weight_lbs": 45,
        "added_station_hours": 1.50,
        "amp_draw": 0,
        "water_demand_gal": 0,
        "requires_option_codes": ["OPT-BATT"],
    },
    {
        "option_code": "OPT-SOLAR",
        "category": "ELECTRICAL",
        "install_station": "ROOF_SET",
        "price_cents": 325000,
        "weight_lbs": 70,
        "added_station_hours": 4.00,
        "amp_draw": 0,
        "water_demand_gal": 0,
        "requires_option_codes": ["OPT-INV"],
    },
]


def build_canon_kit(
    with_chassis: bool = True,
    with_booth: bool = True,
    with_lot: bool = True,
    floor_plan=None,
    dealer=None,
    line=None,
) -> dict:
    """The canonical Class A coach: five options, 71.24 required station hours.

    A STOCK order selecting all five options prices at 16122725 provisional
    cents and finances 14510453 cents of principal.
    """
    kit = {}
    kit["chassis_supplier"] = create_supplier(
        supplier_code="SUP-CH", name="Cascade Chassis Works", component_categories=["CHASSIS"]
    )
    kit["appliance_supplier"] = create_supplier(
        supplier_code="SUP-APP", name="Northline Appliance", component_categories=["APPLIANCE"]
    )
    kit["floor_plan"] = create_floor_plan(
        **{
            "model_code": CANON["FP_MODEL_CODE"],
            "chassis_class": "CLASS_A",
            "length_ft": CANON["FP_LENGTH_FT"],
            "base_msrp_cents": CANON["FP_BASE_MSRP_CENTS"],
            "base_station_hours": CANON["FP_BASE_STATION_HOURS"],
            "base_dry_weight_lbs": CANON["FP_BASE_DRY_WEIGHT_LBS"],
            "gvwr_lbs": CANON["FP_GVWR_LBS"],
            "required_wheelbase_in": CANON["FP_WHEELBASE_IN"],
            "electrical_service_amps": CANON["FP_AMPS"],
            "fresh_water_capacity_gal": CANON["FP_WATER_GAL"],
            **(floor_plan or {}),
        }
    )
    kit["options"] = {}
    for spec in CANON_OPTION_SPECS:
        created = create_option_item(**spec)
        kit["options"][spec["option_code"]] = created
    kit["dealer"] = create_dealer(
        **{
            "dealer_code": CANON["DEALER_CODE"],
            "region": CANON["DEALER_REGION"],
            "allocation_share_bp": CANON["DEALER_SHARE_BP"],
            "floor_plan_credit_limit_cents": CANON["DEALER_CREDIT_LIMIT_CENTS"],
            "goodwill_budget_cents": CANON["DEALER_GOODWILL_CENTS"],
            **(dealer or {}),
        }
    )
    kit["line"] = create_production_line(
        **{
            "line_code": CANON["LINE_CODE"],
            "chassis_class_supported": "CLASS_A",
            "daily_station_hour_capacity": CANON["LINE_HOURS"],
            "max_units_per_day": CANON["LINE_UNITS"],
            **(line or {}),
        }
    )
    if with_booth:
        kit["booth"] = create_test_booth(
            booth_code=CANON["BOOTH_CODE"],
            booth_type="WATER_TEST",
            bay_count=1,
            turnaround_minutes=30,
        )
    if with_chassis:
        kit["chassis"] = create_chassis_receipt(
            kit["chassis_supplier"]["id"],
            chassis_serial=CANON["CHASSIS_SERIAL"],
            chassis_class="CLASS_A",
            gvwr_lbs=CANON["FP_GVWR_LBS"],
            wheelbase_in=CANON["FP_WHEELBASE_IN"],
        )
    if with_lot:
        kit["lot"] = create_component_lot(
            kit["appliance_supplier"]["id"],
            part_number=CANON["LOT_PART_NUMBER"],
            lot_code=CANON["LOT_CODE"],
            category="APPLIANCE",
            quantity_received=CANON["LOT_QUANTITY"],
        )
    return kit


def canon_option_ids(kit: dict) -> list:
    """The five canonical options in the order the dealer selects them."""
    return [
        kit["options"]["OPT-AC2"]["id"],
        kit["options"]["OPT-WASH"]["id"],
        kit["options"]["OPT-SOLAR"]["id"],
        kit["options"]["OPT-INV"]["id"],
        kit["options"]["OPT-BATT"]["id"],
    ]


# ─── Tier 3: kit plus order progression ────────────────────────────────────

def tow_submitted_order(kit=None, order_type: str = "STOCK", with_option: bool = True, **kit_kwargs):
    """TOW kit plus one submitted order. Returns (kit, order)."""
    kit = kit or build_tow_kit(**kit_kwargs)
    option_ids = [kit["option"]["id"]] if with_option else []
    order = create_order(
        kit["dealer"]["id"],
        kit["floor_plan"]["id"],
        order_type=order_type,
        selected_option_ids=option_ids,
    )
    order = submit_order(order["id"], kit["dealer"]["id"])
    return kit, order


def tow_slotted_order(
    kit=None, order_type: str = "STOCK", slot_date: str = "2026-08-05T00:00:00Z", **kit_kwargs
):
    """TOW kit plus a submitted order holding a RESERVED slot. Returns (kit, order, slot)."""
    kit, order = tow_submitted_order(kit=kit, order_type=order_type, **kit_kwargs)
    slot = reserve_slot(order["id"], kit["line"]["id"], slot_date, order["version"])
    return kit, read_order(order["id"]), slot


def tow_released_build(
    kit=None, order_type: str = "STOCK", slot_date: str = "2026-08-05T00:00:00Z", **kit_kwargs
):
    """TOW kit walked to a live build standing at CHASSIS_PREP.

    Returns (kit, order, build).
    """
    kit, order, _slot = tow_slotted_order(
        kit=kit, order_type=order_type, slot_date=slot_date, **kit_kwargs
    )
    match_chassis(order["id"])
    build = release_to_line(order["id"])
    return kit, read_order(order["id"]), build


def tow_build_at_station(
    station: str,
    kit=None,
    order_type: str = "STOCK",
    hours_per_station=6.00,
    slot_date: str = "2026-08-05T00:00:00Z",
    **kit_kwargs,
):
    """Walk a fresh TOW build forward to `station`. Returns (kit, order, build)."""
    kit, order, build = tow_released_build(
        kit=kit, order_type=order_type, slot_date=slot_date, **kit_kwargs
    )
    path = ["SIDEWALL_LAM", "ROOF_SET", "ROUGH_IN", "APPLIANCE_INSTALL", "FINISH"]
    if station != "CHASSIS_PREP":
        for to_station in path[: path.index(station) + 1]:
            build = advance_build(build["id"], to_station, hours_per_station)
    return kit, read_order(order["id"]), read_build(build["id"])


def tow_build_ready_to_ship(
    kit=None,
    order_type: str = "STOCK",
    slot_date: str = "2026-08-05T00:00:00Z",
    water_test_defect_points: int = 3,
    pdi_defect_points: int = 2,
    **kit_kwargs,
):
    """Walk a TOW build all the way to READY_TO_SHIP with both gates passed.

    The walk books 6.00 hours at each of the first five stations, 5.00 at
    WATER_TEST, 3.00 at PDI and 2.00 at READY_TO_SHIP — 40.00 actual hours in
    total, one hour under the 41.00 planned for the single-option coach. The
    water test is signed by one inspector and the pre-delivery inspection by
    another, satisfying the duty split of PRD §2.11.

    Returns (kit, order, build).
    """
    kit, order, build = tow_build_at_station(
        "FINISH", kit=kit, order_type=order_type, slot_date=slot_date, **kit_kwargs
    )
    build = advance_build(build["id"], "WATER_TEST", 5.00)
    water_test = schedule_booth_inspection(
        build["id"],
        kit["booth"]["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        headers=INSPECTOR_1,
    )
    complete_inspection(water_test["id"], water_test_defect_points, False, headers=INSPECTOR_1)
    build = advance_build(build["id"], "PDI", 3.00)
    pdi = schedule_pdi(build["id"], headers=INSPECTOR_2)
    complete_inspection(pdi["id"], pdi_defect_points, False, headers=INSPECTOR_2)
    build = advance_build(build["id"], "READY_TO_SHIP", 2.00)
    return kit, read_order(order["id"]), read_build(build["id"])


def canon_submitted_order(kit=None, order_type: str = "STOCK", **kit_kwargs):
    """CANON kit plus a submitted five-option order. Returns (kit, order)."""
    kit = kit or build_canon_kit(**kit_kwargs)
    order = create_order(
        kit["dealer"]["id"],
        kit["floor_plan"]["id"],
        order_type=order_type,
        selected_option_ids=canon_option_ids(kit),
    )
    order = submit_order(order["id"], kit["dealer"]["id"])
    return kit, order


def canon_released_build(
    kit=None, order_type: str = "STOCK", slot_date: str = "2026-08-05T00:00:00Z", fund: bool = True
):
    """CANON kit walked to a live build at CHASSIS_PREP. Returns (kit, order, build)."""
    kit, order = canon_submitted_order(kit=kit, order_type=order_type)
    if fund:
        fund_order(order["id"], kit["dealer"]["id"])
    order = read_order(order["id"])
    reserve_slot(order["id"], kit["line"]["id"], slot_date, order["version"])
    order = read_order(order["id"])
    match_chassis(order["id"])
    build = release_to_line(order["id"])
    return kit, read_order(order["id"]), build


# ─── Tier 4: delivered units and warranty scenarios ────────────────────────

def delivered_unit_with_dealer(**dealer_overrides):
    """A dealer, a floor plan and one injected delivered coach.

    Returns (dealer, floor_plan, injected) where `injected` is the returned
    UnitBuild standing at SHIPPED.
    """
    floor_plan = create_floor_plan()
    dealer = create_dealer(**dealer_overrides)
    injected = inject_delivered_unit(dealer["id"], floor_plan["id"])
    return dealer, floor_plan, injected


def approved_claim(dealer_id: str, build_id: str, claim_type: str = "APPLIANCE", **overrides):
    """File a claim and approve it with the first warranty administrator."""
    claim = file_claim(dealer_id, build_id, claim_type, **overrides)
    return decide_claim(claim["id"], "APPROVED", headers=WARRANTY_1)


def build_with_installation(lot_quantity: int = 10, install_quantity: int = 2):
    """A TOW build at ROUGH_IN holding one installation from an appliance lot.

    Returns (kit, order, build, lot, installation).
    """
    kit = build_tow_kit()
    appliance_supplier = create_supplier(
        supplier_code="SUP-APP", name="Northline Appliance", component_categories=["APPLIANCE"]
    )
    lot = create_component_lot(
        appliance_supplier["id"],
        part_number="PN-FRIDGE",
        lot_code="L-1",
        category="APPLIANCE",
        quantity_received=lot_quantity,
    )
    kit["appliance_supplier"] = appliance_supplier
    kit, order, build = tow_build_at_station("ROUGH_IN", kit=kit)
    installation = install_pieces(build["id"], lot["id"], "APPLIANCE_INSTALL", install_quantity)
    return kit, order, read_build(build["id"]), read_lot(lot["id"]), installation
