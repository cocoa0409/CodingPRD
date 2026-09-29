"""Composite setup helpers.

The runner restarts the API server before every test, so each test begins
against an empty database and must build all of its state through the public
endpoints.  These helpers are the shared vocabulary for doing that: single-step
wrappers that assert success and return the resource, plus composites that walk
the chain from jurisdiction registration to a released order.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_WORKING_DAY
from .factories import (
    accept_quote_payload,
    connection_component_payload,
    create_accessory_kit_payload,
    create_builder_payload,
    create_configuration_payload,
    create_design_payload,
    create_drawing_package_payload,
    create_jurisdiction_payload,
    create_production_line_payload,
    create_production_lot_payload,
    create_quote_payload,
    create_shipment_load_payload,
    loading_criteria_payload,
    member_component_payload,
    release_payload,
    set_clock_payload,
)
from .test_users import (
    ENGINEERING_MANAGER_USER_ID,
    ENGINEER_USER_ID,
    SEALING_ENGINEER_USER_ID,
    TEST_USERS,
    make_builder_headers,
    make_engineer_headers,
    make_engineering_manager_headers,
    make_sealing_engineer_headers,
)

#: The two accessory kits used wherever a priced building carries kits: their
#: extended price feeds ``accessory_cost_cents`` and their extended weight feeds
#: both freight tonnage and the order's shippable pounds.
STANDARD_KITS = [
    {
        "kit_type": "OVERHEAD_DOOR",
        "quantity": 2,
        "unit_price_cents": 385075,
        "unit_weight_lbs": 640.5,
        "erection_stage": "TRIM_ACCESSORY",
    },
    {
        "kit_type": "VENTILATION",
        "quantity": 3,
        "unit_price_cents": 129933,
        "unit_weight_lbs": 88.25,
        "erection_stage": "ROOF_PANEL",
    },
]

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
MANAGER = TEST_USERS["engineering_manager_headers"]
SEALER = TEST_USERS["sealing_engineer_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


# ------------------------------------------------------------ single-step steps --
def set_clock(to_iso8601: str = CLOCK_WORKING_DAY) -> dict:
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def create_jurisdiction(**overrides) -> dict:
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides), ADMIN),
        expected_status=201,
    )


def publish_loading_criteria(jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.publish_loading_criteria(
            jurisdiction_id, loading_criteria_payload(**overrides), ADMIN
        )
    )


def create_builder(jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_builder(
            create_builder_payload(jurisdiction_id, **overrides), ADMIN
        ),
        expected_status=201,
    )


def authorize_builder(builder_id: str) -> dict:
    return get_success_data(api_client.authorize_builder(builder_id, ADMIN))


def suspend_builder(builder_id: str) -> dict:
    return get_success_data(api_client.suspend_builder(builder_id, ADMIN))


def create_authorized_builder(jurisdiction_id: str, **overrides) -> dict:
    """Onboard a builder and take it through to ``AUTHORIZED``."""
    builder = create_builder(jurisdiction_id, **overrides)
    return authorize_builder(builder["id"])


def create_configuration(builder_id: str, jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_configuration(
            create_configuration_payload(builder_id, jurisdiction_id, **overrides), SALES
        ),
        expected_status=201,
    )


def lock_configuration(configuration_id: str) -> dict:
    return get_success_data(api_client.lock_configuration(configuration_id, SALES))


def create_locked_configuration(
    builder_id: str, jurisdiction_id: str, **overrides
) -> dict:
    configuration = create_configuration(builder_id, jurisdiction_id, **overrides)
    return lock_configuration(configuration["id"])


def add_accessory_kit(configuration_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_accessory_kit(
            configuration_id, create_accessory_kit_payload(**overrides), SALES
        ),
        expected_status=201,
    )


def create_quote(builder_id: str, configuration_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_quote(
            create_quote_payload(builder_id, configuration_id, **overrides), SALES
        ),
        expected_status=201,
    )


def issue_quote(quote_id: str) -> dict:
    return get_success_data(api_client.issue_quote(quote_id, SALES))


def accept_quote(quote_id: str, builder_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.accept_quote(
            quote_id, accept_quote_payload(**overrides), make_builder_headers(builder_id)
        ),
        expected_status=201,
    )


def create_design(
    configuration_id: str, expected_configuration_version: int, **overrides
) -> dict:
    return get_success_data(
        api_client.create_design(
            create_design_payload(
                configuration_id, expected_configuration_version, **overrides
            ),
            ENGINEER,
        ),
        expected_status=201,
    )


def add_member_component(design_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_design_component(
            design_id, member_component_payload(**overrides), ENGINEER
        ),
        expected_status=201,
    )


def add_connection_component(design_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_design_component(
            design_id, connection_component_payload(**overrides), ENGINEER
        ),
        expected_status=201,
    )


def submit_design(design_id: str, user_id: str = ENGINEER_USER_ID) -> dict:
    return get_success_data(
        api_client.submit_design(design_id, make_engineer_headers(user_id))
    )


def review_design(
    design_id: str,
    decision: str = "APPROVE",
    user_id: str = ENGINEERING_MANAGER_USER_ID,
) -> dict:
    return get_success_data(
        api_client.review_design(
            design_id, {"decision": decision}, make_engineering_manager_headers(user_id)
        )
    )


def revise_design(design_id: str) -> dict:
    return get_success_data(api_client.revise_design(design_id, ENGINEER))


def create_drawing_package(design_id: str, jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_drawing_package(
            create_drawing_package_payload(design_id, jurisdiction_id, **overrides),
            SEALER,
        ),
        expected_status=201,
    )


def seal_drawing_package(package_id: str, user_id: str = SEALING_ENGINEER_USER_ID) -> dict:
    return get_success_data(
        api_client.seal_drawing_package(package_id, make_sealing_engineer_headers(user_id))
    )


def create_production_line(**overrides) -> dict:
    return get_success_data(
        api_client.create_production_line(
            create_production_line_payload(**overrides), ADMIN
        ),
        expected_status=201,
    )


def get_order(order_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_order(order_id, headers or PLANNER))


def get_jurisdiction(jurisdiction_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_jurisdiction(jurisdiction_id, headers or ADMIN))


def get_quote(quote_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_quote(quote_id, headers or SALES))


def get_production_line(line_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_production_line(line_id, headers or PLANNER))


def get_production_lot(lot_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_production_lot(lot_id, headers or PLANNER))


def get_shipment_load(load_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_shipment_load(load_id, headers or LOGISTICS))


def get_erection_sequence(order_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_erection_sequence(order_id, headers or LOGISTICS))


def list_design_components(design_id: str, headers: Optional[dict] = None) -> list:
    return get_success_data(
        api_client.list_design_components(design_id, headers or ENGINEER)
    )


def get_builder(builder_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_builder(builder_id, headers or ADMIN))


def get_design(design_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_design(design_id, headers or ENGINEER))


def get_configuration(configuration_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_configuration(configuration_id, headers or SALES)
    )


def get_drawing_package(package_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_drawing_package(package_id, headers or SEALER)
    )


def release_order(order_id: str, expected_order_version: Optional[int] = None) -> dict:
    """Release an order, reading its current version first when none is given."""
    if expected_order_version is None:
        expected_order_version = get_order(order_id)["version"]
    return get_success_data(
        api_client.release_order_to_fabrication(
            order_id, release_payload(expected_order_version), PLANNER
        )
    )


def cancel_order_release(
    order_id: str, expected_order_version: Optional[int] = None
) -> dict:
    if expected_order_version is None:
        expected_order_version = get_order(order_id)["version"]
    return get_success_data(
        api_client.cancel_order_release(
            order_id, release_payload(expected_order_version), PLANNER
        )
    )


def schedule_lot(order_id: str, line_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_production_lot(
            create_production_lot_payload(order_id, line_id, **overrides), PLANNER
        ),
        expected_status=201,
    )


def complete_lot(lot_id: str) -> dict:
    return get_success_data(api_client.complete_production_lot(lot_id, PLANNER))


def cancel_lot(lot_id: str) -> dict:
    return get_success_data(api_client.cancel_production_lot(lot_id, PLANNER))


def plan_load(
    order_id: str, expected_order_version: Optional[int] = None, **overrides
) -> dict:
    if expected_order_version is None:
        expected_order_version = get_order(order_id)["version"]
    return get_success_data(
        api_client.create_shipment_load(
            create_shipment_load_payload(order_id, expected_order_version, **overrides),
            LOGISTICS,
        ),
        expected_status=201,
    )


def dispatch_load(load_id: str) -> dict:
    return get_success_data(api_client.dispatch_shipment_load(load_id, LOGISTICS))


def cancel_load(load_id: str) -> dict:
    return get_success_data(api_client.cancel_shipment_load(load_id, LOGISTICS))


# ------------------------------------------------------------ bills of material --
def minimal_bom() -> List[Dict]:
    """One primary frame member plus the knee and base details a seal requires."""
    return [
        member_component_payload(),
        connection_component_payload(mark="K-1", connection_type="KNEE",
                                     capacity_moment_kip_ft=1100),
        connection_component_payload(
            mark="B-1",
            connection_type="BASE",
            capacity_moment_kip_ft=900,
            erection_stage="ANCHORAGE",
        ),
    ]


def anchored_bom() -> List[Dict]:
    """The minimal bill plus an anchor package, so two erection stages exist."""
    return [
        member_component_payload(),
        member_component_payload(
            mark="AB-1",
            component_class="ANCHOR_PACKAGE",
            member_type="ANCHOR_BOLT",
            erection_stage="ANCHORAGE",
            quantity=10,
            length_ft=1.5,
            weight_per_ft=2.2,
        ),
        connection_component_payload(mark="K-1", connection_type="KNEE",
                                     capacity_moment_kip_ft=1100),
        connection_component_payload(
            mark="B-1",
            connection_type="BASE",
            capacity_moment_kip_ft=900,
            erection_stage="ANCHORAGE",
        ),
    ]


def two_frame_marks_bom() -> List[Dict]:
    """Two primary frame marks plus an anchor package and both details."""
    return [
        member_component_payload(),
        member_component_payload(
            mark="C-2", member_type="RAFTER", quantity=2, length_ft=50, weight_per_ft=22
        ),
        member_component_payload(
            mark="AB-1",
            component_class="ANCHOR_PACKAGE",
            member_type="ANCHOR_BOLT",
            erection_stage="ANCHORAGE",
            quantity=10,
            length_ft=1.5,
            weight_per_ft=2.2,
        ),
        connection_component_payload(mark="K-1", connection_type="KNEE",
                                     capacity_moment_kip_ft=1100),
        connection_component_payload(
            mark="B-1",
            connection_type="BASE",
            capacity_moment_kip_ft=900,
            erection_stage="ANCHORAGE",
        ),
    ]


def full_bom() -> List[Dict]:
    """A nine-line detailed bill spanning every component class."""
    return [
        member_component_payload(mark="C-1", member_type="COLUMN", quantity=10,
                                length_ft=24.5, weight_per_ft=62.35),
        member_component_payload(mark="R-1", member_type="RAFTER", quantity=10,
                                length_ft=51.25, weight_per_ft=48.7),
        member_component_payload(mark="C-2", member_type="COLUMN", quantity=2,
                                length_ft=24.5, weight_per_ft=45.15),
        member_component_payload(
            mark="P-1",
            component_class="SECONDARY_MEMBER",
            member_type="PURLIN",
            erection_stage="SECONDARY_FRAME",
            quantity=40,
            length_ft=25.083,
            weight_per_ft=3.375,
        ),
        member_component_payload(
            mark="G-1",
            component_class="SECONDARY_MEMBER",
            member_type="GIRT",
            erection_stage="SECONDARY_FRAME",
            quantity=16,
            length_ft=24.5,
            weight_per_ft=2.605,
        ),
        member_component_payload(
            mark="PB-1",
            component_class="PANEL_BUNDLE",
            member_type="PANEL",
            erection_stage="ROOF_PANEL",
            quantity=4,
            length_ft=51.25,
            weight_per_ft=1.45,
        ),
        member_component_payload(
            mark="PB-2",
            component_class="PANEL_BUNDLE",
            member_type="PANEL",
            erection_stage="WALL_PANEL",
            quantity=4,
            length_ft=24.0,
            weight_per_ft=1.45,
        ),
        member_component_payload(
            mark="AB-1",
            component_class="ANCHOR_PACKAGE",
            member_type="ANCHOR_BOLT",
            erection_stage="ANCHORAGE",
            quantity=10,
            length_ft=1.5,
            weight_per_ft=2.2,
        ),
        connection_component_payload(mark="K-1", connection_type="KNEE",
                                     capacity_moment_kip_ft=1100),
        connection_component_payload(
            mark="B-1",
            connection_type="BASE",
            capacity_moment_kip_ft=900,
            erection_stage="ANCHORAGE",
        ),
    ]


def append_components(design_id: str, components: List[Dict]) -> List[Dict]:
    """Append a bill of material one component at a time, in list order."""
    rows = []
    for payload in components:
        rows.append(
            get_success_data(
                api_client.create_design_component(design_id, payload, ENGINEER),
                expected_status=201,
            )
        )
    return rows


# --------------------------------------------------------------- composites --
def chain_authorized_builder(
    clock: str = CLOCK_WORKING_DAY,
    jurisdiction_overrides: Optional[dict] = None,
    builder_overrides: Optional[dict] = None,
) -> dict:
    """Clock, one jurisdiction and one AUTHORIZED builder in its territory."""
    set_clock(clock)
    jurisdiction = create_jurisdiction(**(jurisdiction_overrides or {}))
    builder = create_authorized_builder(
        jurisdiction["id"], **(builder_overrides or {})
    )
    return {"jurisdiction": jurisdiction, "builder": builder}


def chain_locked_configuration(
    clock: str = CLOCK_WORKING_DAY,
    jurisdiction_overrides: Optional[dict] = None,
    builder_overrides: Optional[dict] = None,
    configuration_overrides: Optional[dict] = None,
    kits: Optional[List[Dict]] = None,
) -> dict:
    """Adds a LOCKED building configuration to :func:`chain_authorized_builder`.

    Any ``kits`` are attached before the lock, in list order, so their extended
    price and weight are already on the configuration when it is priced.
    """
    chain = chain_authorized_builder(clock, jurisdiction_overrides, builder_overrides)
    configuration = create_configuration(
        chain["builder"]["id"],
        chain["jurisdiction"]["id"],
        **(configuration_overrides or {}),
    )
    chain["kits"] = [
        add_accessory_kit(configuration["id"], **kit) for kit in (kits or [])
    ]
    chain["configuration"] = lock_configuration(configuration["id"])
    return chain


def chain_accepted_order(
    clock: str = CLOCK_WORKING_DAY,
    jurisdiction_overrides: Optional[dict] = None,
    builder_overrides: Optional[dict] = None,
    configuration_overrides: Optional[dict] = None,
    quote_overrides: Optional[dict] = None,
    accept_overrides: Optional[dict] = None,
    kits: Optional[List[Dict]] = None,
) -> dict:
    """Adds a quote, its issue and its acceptance, minting one order."""
    chain = chain_locked_configuration(
        clock,
        jurisdiction_overrides,
        builder_overrides,
        configuration_overrides,
        kits=kits,
    )
    quote = create_quote(
        chain["builder"]["id"], chain["configuration"]["id"], **(quote_overrides or {})
    )
    issue_quote(quote["id"])
    order = accept_quote(
        quote["id"], chain["builder"]["id"], **(accept_overrides or {})
    )
    chain["quote"] = get_success_data(api_client.get_quote(quote["id"], SALES))
    chain["order"] = order
    return chain


def chain_approved_design(
    chain: dict,
    components: Optional[List[Dict]] = None,
    design_variant: str = "ASD",
) -> dict:
    """Open a design on the chain's configuration, detail it and approve it."""
    configuration = get_configuration(chain["configuration"]["id"])
    design = create_design(
        configuration["id"], configuration["version"], design_variant=design_variant
    )
    append_components(design["id"], components if components is not None else minimal_bom())
    submit_design(design["id"])
    chain["design"] = review_design(design["id"], "APPROVE")
    return chain


def chain_sealed_order(
    clock: str = CLOCK_WORKING_DAY,
    jurisdiction_overrides: Optional[dict] = None,
    builder_overrides: Optional[dict] = None,
    configuration_overrides: Optional[dict] = None,
    quote_overrides: Optional[dict] = None,
    accept_overrides: Optional[dict] = None,
    components: Optional[List[Dict]] = None,
    design_variant: str = "ASD",
    package_overrides: Optional[dict] = None,
    kits: Optional[List[Dict]] = None,
) -> dict:
    """Everything up to and including a SEALED permit set, leaving ENG_SEALED."""
    chain = chain_accepted_order(
        clock,
        jurisdiction_overrides,
        builder_overrides,
        configuration_overrides,
        quote_overrides,
        accept_overrides,
        kits=kits,
    )
    chain_approved_design(chain, components, design_variant)
    package = create_drawing_package(
        chain["design"]["id"], chain["jurisdiction"]["id"], **(package_overrides or {})
    )
    chain["package"] = seal_drawing_package(package["id"])
    chain["order"] = get_order(chain["order"]["id"])
    return chain


def chain_released_order(**kwargs) -> dict:
    """A sealed order taken through release to fabrication."""
    chain = chain_sealed_order(**kwargs)
    chain["order"] = release_order(chain["order"]["id"], chain["order"]["version"])
    return chain
