"""Composite setup helpers for the scenic-shop PRD.

The harness re-launches the server before every test, so every fixture builds
preconditions from scratch using PRD-declared endpoints only.
"""
from typing import Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    STD_BUILD_START_AT,
    STD_CONTACT_EMAIL,
    STD_COMPANY_NAME,
    STD_LOAD_IN_AT,
    STD_SHOW_TITLE,
    STD_STRIKE_AT,
    STD_VENUE,
)
from .factories import (
    create_bid_payload,
    create_client_payload,
    create_design_package_payload,
    create_shop_payload,
)
from .test_users import TEST_USERS, make_client_pm_headers

ADMIN = TEST_USERS["shop_admin_headers"]
EST = TEST_USERS["estimator_headers"]
FOREMAN = TEST_USERS["shop_foreman_headers"]
FOREMAN_9 = TEST_USERS["shop_foreman_other_headers"]
ENGINEER = TEST_USERS["staff_engineer_headers"]
ENGINEER_1 = TEST_USERS["staff_engineer_preparer_headers"]
PAINT = TEST_USERS["paint_charge_headers"]
TC = TEST_USERS["transport_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: shop / client / package / bid primitives
# ---------------------------------------------------------------------------
def setup_shop(**overrides) -> dict:
    resp = api_client.create_shop(create_shop_payload(**overrides), ADMIN)
    return get_success_data(resp)


def setup_client(shop_id: str, credit_limit_cents: int = 100000000, **overrides) -> dict:
    payload = create_client_payload(
        shop_id=shop_id,
        company_name=overrides.pop("company_name", STD_COMPANY_NAME),
        contact_email=overrides.pop("contact_email", STD_CONTACT_EMAIL),
        credit_limit_cents=credit_limit_cents,
        **overrides,
    )
    return get_success_data(api_client.create_client(payload, ADMIN))


def setup_design_package(
    client_id: str,
    show_title: str = STD_SHOW_TITLE,
    load_in_at: str = STD_LOAD_IN_AT,
    strike_at: str = STD_STRIKE_AT,
    venue: str = STD_VENUE,
) -> dict:
    payload = create_design_package_payload(
        client_id=client_id,
        show_title=show_title,
        venue=venue,
        load_in_at=load_in_at,
        strike_at=strike_at,
    )
    return get_success_data(
        api_client.create_design_package(payload, make_client_pm_headers(client_id))
    )


def setup_basic_scenario(
    shop_overrides: Optional[dict] = None,
    credit_limit_cents: int = 100000000,
    show_title: str = STD_SHOW_TITLE,
    load_in_at: str = STD_LOAD_IN_AT,
    strike_at: str = STD_STRIKE_AT,
) -> Tuple[dict, dict, dict]:
    """Shop + client + first design package. Returns (shop, client, package)."""
    shop = setup_shop(**(shop_overrides or {}))
    client = setup_client(shop["id"], credit_limit_cents=credit_limit_cents)
    pkg = setup_design_package(
        client["id"], show_title=show_title, load_in_at=load_in_at, strike_at=strike_at,
    )
    return shop, client, pkg


def setup_second_package(
    client_id: str, show_title: str = "Macbeth", load_in_at: str = "2026-10-24T00:00:00Z",
    strike_at: str = "2026-11-07T00:00:00Z", venue: str = "Lyric Theatre",
) -> dict:
    return setup_design_package(
        client_id, show_title=show_title, load_in_at=load_in_at,
        strike_at=strike_at, venue=venue,
    )


def create_rom_bid(
    client_id: str,
    package_id: str,
    estimated_crew_hours: int = 100,
    has_automation_scope: bool = False,
    bays_required: int = 1,
    validity_days: int = 30,
    floor_area_sqft: int = 100,
    complexity_class: str = "A_SIMPLE",
    build_start_at: str = STD_BUILD_START_AT,
) -> dict:
    payload = create_bid_payload(
        client_id=client_id,
        design_package_id=package_id,
        pricing_variant="ROM",
        has_automation_scope=has_automation_scope,
        bays_required=bays_required,
        build_start_at=build_start_at,
        validity_days=validity_days,
        floor_area_sqft=floor_area_sqft,
        complexity_class=complexity_class,
        estimated_crew_hours=estimated_crew_hours,
    )
    return get_success_data(api_client.create_bid(payload, EST))


def submit_bid(bid_id: str) -> dict:
    return get_success_data(api_client.submit_bid(bid_id, EST))


def accept_bid(bid_id: str, client_id: str) -> dict:
    return get_success_data(api_client.accept_bid(bid_id, make_client_pm_headers(client_id)))


# ---------------------------------------------------------------------------
# Tier 2: accepted bid -> Production spawned
# ---------------------------------------------------------------------------
def setup_accepted_production(
    estimated_crew_hours: int = 100,
    has_automation_scope: bool = False,
    bays_required: int = 1,
    credit_limit_cents: int = 100000000,
    shop_overrides: Optional[dict] = None,
    load_in_at: str = STD_LOAD_IN_AT,
    strike_at: str = STD_STRIKE_AT,
    validity_days: int = 30,
    floor_area_sqft: int = 100,
    complexity_class: str = "A_SIMPLE",
) -> Tuple[dict, dict, dict, dict, dict]:
    """Shop + client + package + ROM bid -> submit -> accept.

    Returns (shop, client, package, bid, production).
    """
    shop, client, pkg = setup_basic_scenario(
        shop_overrides=shop_overrides,
        credit_limit_cents=credit_limit_cents,
        load_in_at=load_in_at,
        strike_at=strike_at,
    )
    bid = create_rom_bid(
        client["id"], pkg["id"],
        estimated_crew_hours=estimated_crew_hours,
        has_automation_scope=has_automation_scope,
        bays_required=bays_required,
        validity_days=validity_days,
        floor_area_sqft=floor_area_sqft,
        complexity_class=complexity_class,
    )
    submit_bid(bid["id"])
    accepted = accept_bid(bid["id"], client["id"])
    prod_id = accepted["production_id"]
    production = get_success_data(api_client.get_production(prod_id, EST))
    return shop, client, pkg, accepted, production


# ---------------------------------------------------------------------------
# Tier 3: in-build production (review approved + bay reserved + start-build)
# ---------------------------------------------------------------------------
def setup_in_build_production(
    estimated_crew_hours: int = 100,
    bays_required: int = 1,
    credit_limit_cents: int = 100000000,
    bay_window: Tuple[str, str] = ("2026-09-01T00:00:00Z", "2026-09-26T00:00:00Z"),
    shop_overrides: Optional[dict] = None,
    load_in_at: str = STD_LOAD_IN_AT,
    strike_at: str = STD_STRIKE_AT,
) -> Tuple[dict, dict, dict, dict, dict, dict, dict]:
    """Drives a production to IN_BUILD with one APPROVED STRUCTURAL review
    and one ACTIVE bay reservation.

    Returns (shop, client, package, bid, production, review, reservation).
    """
    shop, client, pkg, bid, production = setup_accepted_production(
        estimated_crew_hours=estimated_crew_hours,
        bays_required=bays_required,
        credit_limit_cents=credit_limit_cents,
        shop_overrides=shop_overrides,
        load_in_at=load_in_at,
        strike_at=strike_at,
    )
    review = get_success_data(api_client.create_engineering_review(
        {
            "production_id": production["id"],
            "scope": "STRUCTURAL",
            "design_load_lb": 4000,
            "member_capacity_lb": 6000,
        },
        FOREMAN,
    ))
    get_success_data(api_client.approve_engineering_review(review["id"], ENGINEER))
    reservation = get_success_data(api_client.create_bay_reservation(
        {
            "production_id": production["id"],
            "bay_slot": 1,
            "window_start": bay_window[0],
            "window_end": bay_window[1],
        },
        FOREMAN,
    ))
    get_success_data(api_client.start_build(production["id"], FOREMAN))
    production = get_success_data(api_client.get_production(production["id"], EST))
    return shop, client, pkg, bid, production, review, reservation


# ---------------------------------------------------------------------------
# Tier 4: built / loaded-in / struck shortcuts
# ---------------------------------------------------------------------------
def drive_to_built(
    shop: dict, client: dict, production: dict,
    add_finish_sample: bool = True,
) -> dict:
    """From IN_BUILD: optional approved finish sample + complete-build."""
    if add_finish_sample:
        sample = get_success_data(api_client.create_finish_sample(
            {
                "production_id": production["id"],
                "finish_code": "SCUFF_BRICK_RED",
                "texture_ref": "tex_v1",
            },
            PAINT,
        ))
        get_success_data(api_client.approve_finish_sample(
            sample["id"], make_client_pm_headers(client["id"]),
        ))
    get_success_data(api_client.complete_build(production["id"], FOREMAN))
    return get_success_data(api_client.get_production(production["id"], EST))


def drive_to_loaded_in(shop: dict, client: dict, production: dict) -> Tuple[dict, dict]:
    """From IN_BUILD: build, plan transport, confirm, load in.

    Returns (production_in_LOADED_IN, transport_plan_EXECUTED).
    """
    production = drive_to_built(shop, client, production, add_finish_sample=True)
    plan = get_success_data(api_client.create_transport_plan(
        {
            "production_id": production["id"],
            "truck_count": 2,
            "install_crew_hours": 16,
            "depart_at": "2026-09-11T00:00:00Z",
            "arrive_at": "2026-09-12T00:00:00Z",
        },
        TC,
    ))
    get_success_data(api_client.confirm_transport_plan(plan["id"], TC))
    get_success_data(api_client.load_in(production["id"], TC))
    production = get_success_data(api_client.get_production(production["id"], EST))
    plan = get_success_data(api_client.get_transport_plan(plan["id"], TC))
    return production, plan


def drive_to_struck(
    shop: dict, client: dict, production: dict, reclaim_lines: Optional[list] = None,
) -> dict:
    """From IN_BUILD: full drive through LOADED_IN then STRUCK."""
    production, _plan = drive_to_loaded_in(shop, client, production)
    get_success_data(api_client.strike(
        production["id"], {"reclaim_lines": reclaim_lines or []}, FOREMAN,
    ))
    return get_success_data(api_client.get_production(production["id"], EST))


def setup_in_build(
    estimated_crew_hours: int = 100,
    credit_limit_cents: int = 100000000,
    shop_overrides: Optional[dict] = None,
) -> Tuple[dict, dict, dict, dict, dict, dict, dict]:
    """Alias of setup_in_build_production for brevity inside test bodies."""
    return setup_in_build_production(
        estimated_crew_hours=estimated_crew_hours,
        credit_limit_cents=credit_limit_cents,
        shop_overrides=shop_overrides,
    )


# ---------------------------------------------------------------------------
# Tier 5: change-order helpers
# ---------------------------------------------------------------------------
def supersede_package_to_revision_2(client_id: str, show_title: str = STD_SHOW_TITLE) -> dict:
    """Re-upload the same (client_id, show_title) pair so the package advances
    to drawing_revision 2 (the prior package becomes SUPERSEDED)."""
    return setup_design_package(client_id, show_title=show_title)


def create_change_order_on_production(
    production_id: str,
    new_drawing_revision: int,
    delta_materials_cents: int,
    delta_labor_hours: int,
    delta_load_in_days: int,
) -> dict:
    """Read the current production version, then create the change order
    (per PRD §2.8 the create is OCC-gated on the production's version)."""
    prod = get_success_data(api_client.get_production(production_id, EST))
    payload = {
        "production_id": production_id,
        "expected_production_version": prod["version"],
        "new_drawing_revision": new_drawing_revision,
        "delta_materials_cents": delta_materials_cents,
        "delta_labor_hours": delta_labor_hours,
        "delta_load_in_days": delta_load_in_days,
    }
    return get_success_data(api_client.create_change_order(payload, EST))


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))
