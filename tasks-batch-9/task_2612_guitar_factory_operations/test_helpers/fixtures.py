"""
Composite state builders and the pytest fixtures that expose them.

The runner relaunches the service against an empty database before every single
test, so every precondition has to be rebuilt from scratch through the
documented endpoints. The builders below assemble the compositions this domain
keeps needing — a received lot, a released lot, a routed part, an order carried
to assembly, an order standing at inspection, a shipment awaiting documents —
so an individual test only has to describe what is unusual about its own
scenario.

Every builder takes and returns one mutable environment dict, so layers compose
in any order:

    env = build_released_lot(api)
    env = build_billet(api, env)

Environment keys, once the corresponding layer has run:

    clock, dry1, br1, fb1, cnc1, hs1, spec1,
    lot1, lot_v1, lot2, lot2_v1, blt1, blt2, cmp1, cmp2,
    optA, optD, optG, bo1, bo_v1, bo_v3, sel1, res1, res2, fr1, insp1,
    shopA, shopB, shp1

Nothing here asserts a rule under test: a failure inside a builder means the
precondition could not be established, not that a rule is wrong.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from . import constants as C
from . import factories as F
from . import test_users as U
from .api_client import ApiClient
from .types import JsonDict


# ---------------------------------------------------------------------------
# Tier 0 — the plant itself
# ---------------------------------------------------------------------------
def build_clock(api: ApiClient, env: JsonDict = None,
                clock: str = C.CLOCK_DEFAULT) -> JsonDict:
    """Pin the logical shop clock, which every date-bearing rule reads."""
    env = env if env is not None else {}
    F.set_clock(api, clock)
    env["clock"] = clock
    return env


def build_dry_store(api: ApiClient, env: JsonDict) -> JsonDict:
    env["dry1"] = F.create_room(api, dict(C.DRY_STORE_1))["id"]
    return env


def build_build_room(api: ApiClient, env: JsonDict) -> JsonDict:
    env["br1"] = F.create_room(api, dict(C.BUILD_ROOM_1))["id"]
    return env


def build_booth(api: ApiClient, env: JsonDict, roomy: bool = False) -> JsonDict:
    """
    Register the finish booth. The narrow booth holds a single chemistry slot;
    the roomy one holds four, which is what lets a capacity test isolate the
    chemistry rule from the capacity rule.
    """
    payload = dict(C.FINISH_BOOTH_ROOMY if roomy else C.FINISH_BOOTH_1)
    env["fb1"] = F.create_room(api, payload)["id"]
    return env


def build_stations(api: ApiClient, env: JsonDict) -> JsonDict:
    env["cnc1"] = F.create_station(api, env["br1"], dict(C.CNC_STATION))["id"]
    env["hs1"] = F.create_station(api, env["br1"], dict(C.HAND_SHAPING_STATION))["id"]
    return env


def build_spec(api: ApiClient, env: JsonDict) -> JsonDict:
    env["spec1"] = F.create_spec(api, dict(C.SPEC_TOP_OM))["id"]
    return env


def build_machine_shop(api: ApiClient, env: JsonDict = None,
                       clock: str = C.CLOCK_DEFAULT,
                       booth: bool = True, roomy_booth: bool = False) -> JsonDict:
    """Clock, dry store, build room, optional finish booth, both stations, one spec."""
    env = build_clock(api, env, clock)
    build_dry_store(api, env)
    build_build_room(api, env)
    if booth:
        build_booth(api, env, roomy=roomy_booth)
    build_stations(api, env)
    build_spec(api, env)
    return env


# ---------------------------------------------------------------------------
# Tier 1 — wood
# ---------------------------------------------------------------------------
def build_lot(api: ApiClient, env: JsonDict, key: str = "lot1", **overrides) -> JsonDict:
    """Book a delivery into the dry store."""
    payload = F.lot_payload(storage_room_id=env["dry1"], **overrides)
    env[key] = F.create_lot(api, payload)["id"]
    return env


def build_dried_lot(api: ApiClient, env: JsonDict, key: str = "lot1",
                    moisture: float = 7.0) -> JsonDict:
    """Log a moisture reading that puts the lot inside the conditioning band."""
    F.log_moisture_reading(api, env[key], moisture)
    return env


def build_released_lot(api: ApiClient, env: JsonDict = None,
                       key: str = "lot1", version_key: str = "lot_v1",
                       clock: str = C.CLOCK_DEFAULT, **overrides) -> JsonDict:
    """
    A lot dried to 7.0 percent, conditioned and released, so it may be sawn.
    The version the release produced is captured, because sawing has to echo it.

    A protected-species delivery lands on the permit hold instead, so the permit
    is attested by co-alice first — that stamp is what the export segregation
    check later reads.
    """
    if env is None:
        env = build_clock(api, None, clock)
        build_dry_store(api, env)
    build_lot(api, env, key, **overrides)
    if overrides.get("cites_appendix", "NONE") != "NONE":
        F.attest_permit(api, env[key], "CITES-II-4471", U.COMPLIANCE_HEADERS)
    build_dried_lot(api, env, key)
    F.condition_lot(api, env[key])
    env[version_key] = F.release_lot(api, env[key])["version"]
    return env


def build_billet(api: ApiClient, env: JsonDict, key: str = "blt1",
                 lot_key: str = "lot1", version_key: str = "lot_v1",
                 billet_code: str = "BLT-001", board_feet: float = 30.00,
                 grade: str = "AAA") -> JsonDict:
    """Saw a billet off the released lot."""
    env[key] = F.create_billet(api, env[lot_key], env[version_key],
                               billet_code=billet_code, board_feet=board_feet,
                               grade=grade)["id"]
    return env


# ---------------------------------------------------------------------------
# Tier 2 — orders, options and parts
# ---------------------------------------------------------------------------
def build_vine_option(api: ApiClient, env: JsonDict) -> JsonDict:
    env["optA"] = F.create_option(api, dict(C.OPTION_VINE_INLAY))["id"]
    return env


def build_custom_order(api: ApiClient, env: JsonDict, **overrides) -> JsonDict:
    """
    An ENDORSER custom-shop order at a base price of 480000 cents, opened by
    csc-bob, whose opening version is captured for the option-selection guard.
    """
    payload = F.order_payload(is_custom_shop=True, artist_tier="ENDORSER",
                              finish_system="NITRO", **overrides)
    order = F.create_order(api, payload, U.COORDINATOR_HEADERS)
    env["bo1"] = order["id"]
    env["bo_v1"] = order["version"]
    env["order"] = order
    return env


def build_approved_vine_selection(api: ApiClient, env: JsonDict) -> JsonDict:
    """
    Configure the vine inlay as csc-bob and have csc-dana approve it, because
    the approver may not be the coordinator who configured the row.
    """
    env["sel1"] = F.create_selection(api, env["bo1"], env["optA"], env["bo_v1"],
                                     quantity=1,
                                     headers=U.COORDINATOR_HEADERS)["id"]
    F.approve_selection(api, env["sel1"], U.COORDINATOR_2_HEADERS)
    return env


def build_locked_order(api: ApiClient, env: JsonDict, deposit_cents: int) -> JsonDict:
    """Confirm the order with a deposit and freeze the configuration."""
    F.confirm_order(api, env["bo1"], deposit_cents, U.COORDINATOR_HEADERS)
    F.lock_options(api, env["bo1"], U.COORDINATOR_HEADERS)
    return env


def build_component_accepted(api: ApiClient, env: JsonDict,
                             component_key: str = "cmp1",
                             billet_key: str = "blt1",
                             order_key: str = "bo1",
                             res_a: str = "res1", res_b: str = "res2",
                             cnc_starts: str = "2026-08-02T08:00:00Z",
                             cnc_ends: str = "2026-08-02T09:00:00Z",
                             hs_starts: str = "2026-08-02T10:00:00Z",
                             hs_ends: str = "2026-08-02T11:00:00Z") -> JsonDict:
    """
    Open a part against the spec and the billet, route it on the CNC station,
    hand-shape it on the hand-shaping station and accept it at quality control.
    """
    env[component_key] = F.create_component(api, env["spec1"], env[billet_key],
                                            env[order_key])["id"]
    env[res_a] = F.create_reservation(api, env["cnc1"], cnc_starts, cnc_ends,
                                      build_order_id=env[order_key],
                                      component_id=env[component_key])["id"]
    F.route_component(api, env[component_key], env[res_a], 2.90)
    env[res_b] = F.create_reservation(api, env["hs1"], hs_starts, hs_ends,
                                      build_order_id=env[order_key],
                                      component_id=env[component_key],
                                      headers=U.LUTHIER_HEADERS)["id"]
    F.hand_shape_component(api, env[component_key], env[res_b], 2.90)
    F.qc_component(api, env[component_key], "ACCEPT")
    return env


# ---------------------------------------------------------------------------
# The four difficulty setup chains
# ---------------------------------------------------------------------------
def build_chain_b(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    The protected-species spine: an APPENDIX_II rosewood lot attested by
    co-alice, released, sawn into BLT-001; an ENDORSER custom order carrying an
    approved vine inlay, confirmed at 200000 cents and locked; and one accepted
    BODY_TOP part, leaving the order at build stage COMPONENTS_RELEASED.
    """
    env = build_machine_shop(api, env)
    build_released_lot(api, env, species_code="EAST_INDIAN_ROSEWOOD",
                       cites_appendix="APPENDIX_II")
    build_billet(api, env)
    build_vine_option(api, env)
    build_custom_order(api, env)
    build_approved_vine_selection(api, env)
    build_locked_order(api, env, 200000)
    F.release_components(api, env["bo1"])
    build_component_accepted(api, env)
    return env


def build_chain_c(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    Chain B with the deposit set to 88619 cents — exactly ten percent of the
    886185-cent provisional total — so the settlement threshold on export
    release can be missed without the deposit ever being short at confirmation.
    """
    env = build_machine_shop(api, env)
    build_released_lot(api, env, species_code="EAST_INDIAN_ROSEWOOD",
                       cites_appendix="APPENDIX_II")
    build_billet(api, env)
    build_vine_option(api, env)
    build_custom_order(api, env)
    build_approved_vine_selection(api, env)
    build_locked_order(api, env, 88619)
    F.release_components(api, env["bo1"])
    build_component_accepted(api, env)
    return env


def build_chain_a(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    Chain B carried into the booth: assembly started, a twelve-coat NITRO run
    booked in FB-1, the booth sampled at 52.0 percent and 27.0 degrees, and the
    clock advanced to 2026-08-05T09:00:00Z ready for the spray to be closed.
    """
    env = build_chain_b(api, env)
    env["bo_v3"] = F.start_assembly(api, env["bo1"])["version"]
    env["fr1"] = F.create_finish_run(api, env["bo1"], env["fb1"], env["bo_v3"],
                                     finish_system="NITRO", coat_count=12)["id"]
    F.log_climate_reading(api, env["fb1"], 52.0, 27.0, U.FINISH_TECH_HEADERS)
    F.set_clock(api, "2026-08-05T09:00:00Z")
    env["clock"] = "2026-08-05T09:00:00Z"
    return env


def build_chain_two_orders(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    Two instruments in flight from one rosewood lot: ORD-001, a NITRO custom
    build already spraying in FB-1 from 2026-08-02T12:00:00Z, and ORD-002, a
    POLY standard build standing at IN_ASSEMBLY with its own accepted part.
    """
    env = build_machine_shop(api, env)
    build_released_lot(api, env, species_code="EAST_INDIAN_ROSEWOOD",
                       cites_appendix="APPENDIX_II")
    build_billet(api, env)
    read_lot_version(api, env, key="lot1", version_key="lot_v2")
    build_billet(api, env, key="blt2", version_key="lot_v2",
                 billet_code="BLT-002", board_feet=30.00)
    build_vine_option(api, env)
    build_custom_order(api, env)
    build_approved_vine_selection(api, env)
    build_locked_order(api, env, 200000)
    F.release_components(api, env["bo1"])
    build_component_accepted(api, env)
    env["bo1_v3"] = F.start_assembly(api, env["bo1"])["version"]

    order2 = F.create_order(api, F.order_payload(
        order_code="ORD-002", model_code="D28", base_price_cents=400000,
        is_custom_shop=False, artist_tier="NONE", finish_system="POLY",
        promised_date="2026-11-01T00:00:00Z"), U.COORDINATOR_HEADERS)
    env["bo2"] = order2["id"]
    F.confirm_order(api, env["bo2"], 200000, U.COORDINATOR_HEADERS)
    F.lock_options(api, env["bo2"], U.COORDINATOR_HEADERS)
    F.release_components(api, env["bo2"])
    build_component_accepted(api, env, component_key="cmp2", billet_key="blt2",
                             order_key="bo2", res_a="res3", res_b="res4",
                             cnc_starts="2026-08-03T08:00:00Z",
                             cnc_ends="2026-08-03T09:00:00Z",
                             hs_starts="2026-08-03T10:00:00Z",
                             hs_ends="2026-08-03T11:00:00Z")
    env["bo2_v3"] = F.start_assembly(api, env["bo2"])["version"]

    F.set_clock(api, "2026-08-02T12:00:00Z")
    env["clock"] = "2026-08-02T12:00:00Z"
    F.log_climate_reading(api, env["fb1"], 50.0, 21.0, U.FINISH_TECH_HEADERS)
    env["fr1"] = F.create_finish_run(api, env["bo1"], env["fb1"], env["bo1_v3"],
                                     finish_system="NITRO", coat_count=8)["id"]
    return env


# ---------------------------------------------------------------------------
# Small readers, for the versions a later write has to echo back
# ---------------------------------------------------------------------------
def read_lot_version(api: ApiClient, env: JsonDict, key: str = "lot1",
                     version_key: str = "lot_v2") -> JsonDict:
    """Re-read the lot so a second cut can quote the version the first one left."""
    env[version_key] = validate_success(
        api.get_tonewood_lot(env[key], U.MACHINIST_HEADERS))["version"]
    return env


def read_order_version(api: ApiClient, env: JsonDict, key: str = "bo1",
                       version_key: str = "bo_v2") -> JsonDict:
    """Re-read the order so the next configuration call can quote its version."""
    env[version_key] = validate_success(
        api.get_build_order(env[key], U.COORDINATOR_HEADERS))["version"]
    return env


# ---------------------------------------------------------------------------
# Wood compositions
# ---------------------------------------------------------------------------
def build_lot_received(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """One SITKA_SPRUCE delivery of 100.00 board feet at 12.0 percent in DRY-1."""
    env = build_clock(api, env)
    build_dry_store(api, env)
    build_lot(api, env)
    return env


def build_four_lots(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    Three spruce deliveries and one maple one, so a species filter and a page
    window can be shown to compose rather than shadow each other.
    """
    env = build_lot_received(api, env)
    build_lot(api, env, "lot2", lot_code="LOT-002", species_code="SITKA_SPRUCE",
              board_feet_received=80.00, moisture_content_pct=11.0)
    build_lot(api, env, "lot3", lot_code="LOT-003", species_code="SITKA_SPRUCE",
              board_feet_received=60.00, moisture_content_pct=10.0)
    build_lot(api, env, "lot4", lot_code="LOT-004", species_code="HARD_MAPLE",
              board_feet_received=40.00, moisture_content_pct=9.0)
    return env


def build_lot_permit_hold(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    A Brazilian rosewood delivery of 40.00 board feet, which the protected
    species fork parks on the permit hold with the permit still outstanding.
    """
    env = build_clock(api, env)
    build_dry_store(api, env)
    build_lot(api, env, "lotB", lot_code="LOT-BRW",
              species_code="BRAZILIAN_ROSEWOOD", cites_appendix="APPENDIX_II",
              board_feet_received=40.00, moisture_content_pct=7.0)
    return env


def build_two_lots_one_conditioned(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    DRY-1 holding a conditioned spruce lot and a still-untouched maple one, so a
    room-wide event can be shown to reach only the conditioned child.
    """
    env = build_lot_received(api, env)
    build_dried_lot(api, env, "lot1")
    F.condition_lot(api, env["lot1"])
    build_lot(api, env, "lot2", lot_code="LOT-002", species_code="HARD_MAPLE",
              board_feet_received=60.00, moisture_content_pct=9.0)
    return env


def build_lot_rejected(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """A spruce delivery already refused for grain runout."""
    env = build_lot_received(api, env)
    F.reject_lot(api, env["lot1"], "grain runout")
    return env


def build_lot_after_big_cut(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    A released 100.00 board-foot lot with a single 68.00 board-foot billet
    already sawn from it, which leaves 29.96 board feet on hand.
    """
    env = build_released_lot(api, env)
    build_billet(api, env, board_feet=68.00)
    read_lot_version(api, env)
    return env


def build_comp_routed(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    A body top routed on the CNC station from BLT-001 with no order attached,
    which is legal because the order edge on a part is optional.
    """
    env = build_machine_shop(api, env, booth=False)
    build_released_lot(api, env)
    build_billet(api, env)
    env["cmp1"] = F.create_component(api, env["spec1"], env["blt1"])["id"]
    env["res1"] = F.create_reservation(api, env["cnc1"], "2026-08-02T08:00:00Z",
                                       "2026-08-02T09:00:00Z",
                                       component_id=env["cmp1"])["id"]
    F.route_component(api, env["cmp1"], env["res1"], 2.90)
    return env


# ---------------------------------------------------------------------------
# Station compositions
# ---------------------------------------------------------------------------
def build_one_cnc_station(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """One build room carrying a single CNC router."""
    env = build_clock(api, env)
    build_build_room(api, env)
    env["cnc1"] = F.create_station(api, env["br1"], dict(C.CNC_STATION))["id"]
    return env


def build_two_confirmed_orders_on_cnc1(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    Two confirmed instruments each holding one window on CNC-1: BO-1, a
    signature custom build promised for 2026-10-01, and BO-2, a plain build
    promised much sooner for 2026-08-20.
    """
    env = build_one_cnc_station(api, env)
    env["optD"] = F.create_option(api, dict(C.OPTION_DOT_INLAY))["id"]
    order1 = F.create_order(api, F.order_payload(
        order_code="BO-1", model_code="OM45", base_price_cents=300000,
        promised_date="2026-10-01T00:00:00Z", is_custom_shop=True,
        artist_tier="SIGNATURE", finish_system="NITRO"), U.COORDINATOR_HEADERS)
    env["bo1"] = order1["id"]
    env["bo1_v1"] = order1["version"]
    env["selD"] = F.create_selection(api, env["bo1"], env["optD"], env["bo1_v1"],
                                     headers=U.COORDINATOR_3_HEADERS)["id"]
    F.approve_selection(api, env["selD"], U.COORDINATOR_4_HEADERS)
    F.confirm_order(api, env["bo1"], 35010, U.COORDINATOR_HEADERS)

    order2 = F.create_order(api, F.order_payload(
        order_code="BO-2", model_code="D28", base_price_cents=300000,
        promised_date="2026-08-20T00:00:00Z", is_custom_shop=False,
        artist_tier="NONE", finish_system="NITRO"), U.COORDINATOR_HEADERS)
    env["bo2"] = order2["id"]
    F.confirm_order(api, env["bo2"], 30000, U.COORDINATOR_HEADERS)

    env["resA"] = F.create_reservation(api, env["cnc1"], "2026-08-03T08:00:00Z",
                                       "2026-08-03T09:00:00Z",
                                       build_order_id=env["bo1"])["id"]
    env["resB"] = F.create_reservation(api, env["cnc1"], "2026-08-04T08:00:00Z",
                                       "2026-08-04T09:00:00Z",
                                       build_order_id=env["bo2"])["id"]
    return env


# ---------------------------------------------------------------------------
# Order and quote compositions
# ---------------------------------------------------------------------------
def build_order_two_options(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    A plain OM45 order at 300000 cents carrying a dot inlay and gold hardware,
    both still awaiting approval, so the provisional total has two live lines.
    """
    env = build_clock(api, env)
    env["optD"] = F.create_option(api, dict(C.OPTION_DOT_INLAY))["id"]
    env["optG"] = F.create_option(api, dict(C.OPTION_GOLD_HARDWARE))["id"]
    order = F.create_order(api, F.order_payload(
        order_code="ORD-STD", model_code="OM45", base_price_cents=300000,
        promised_date="2026-11-01T00:00:00Z", is_custom_shop=False,
        artist_tier="NONE", finish_system="NITRO"), U.COORDINATOR_HEADERS)
    env["bo1"] = order["id"]
    env["bo_v1"] = order["version"]
    env["selD"] = F.create_selection(api, env["bo1"], env["optD"], env["bo_v1"],
                                     headers=U.COORDINATOR_3_HEADERS)["id"]
    read_order_version(api, env, "bo1", "bo_v2")
    env["selG"] = F.create_selection(api, env["bo1"], env["optG"], env["bo_v2"],
                                     headers=U.COORDINATOR_3_HEADERS)["id"]
    return env


def build_order_with_vine(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    A quoted custom order carrying a live vine inlay selection, with the dot
    inlay the vine excludes also sitting in the catalog.
    """
    env = build_clock(api, env)
    env["optV"] = F.create_option(api, dict(C.OPTION_VINE_INLAY))["id"]
    env["optD"] = F.create_option(api, dict(C.OPTION_DOT_INLAY))["id"]
    order = F.create_order(api, F.order_payload(
        order_code="ORD-CS", model_code="OM45", base_price_cents=480000,
        promised_date="2026-11-01T00:00:00Z", is_custom_shop=True,
        artist_tier="ENDORSER", finish_system="NITRO"), U.COORDINATOR_HEADERS)
    env["boCS"] = order["id"]
    env["boCS_v1"] = order["version"]
    env["selV"] = F.create_selection(api, env["boCS"], env["optV"],
                                     env["boCS_v1"],
                                     headers=U.COORDINATOR_HEADERS)["id"]
    env["boCS_v2"] = validate_success(
        api.get_build_order(env["boCS"], U.COORDINATOR_HEADERS))["version"]
    return env


def build_two_orders_custom_and_standard(api: ApiClient,
                                         env: JsonDict = None) -> JsonDict:
    """
    Two quoted orders at 480000 cents for an endorsing artist — one a custom
    shop build, one not — and neither carrying any option at all.
    """
    env = build_clock(api, env)
    env["boCS"] = F.create_order(api, F.order_payload(
        order_code="ORD-CS", model_code="OM45", base_price_cents=480000,
        promised_date="2026-11-01T00:00:00Z", is_custom_shop=True,
        artist_tier="ENDORSER", finish_system="NITRO"),
        U.COORDINATOR_HEADERS)["id"]
    env["boSTD"] = F.create_order(api, F.order_payload(
        order_code="ORD-STD", model_code="OM45", base_price_cents=480000,
        promised_date="2026-11-01T00:00:00Z", is_custom_shop=False,
        artist_tier="ENDORSER", finish_system="NITRO"),
        U.COORDINATOR_HEADERS)["id"]
    return env


def build_standard_order_to_assembly(api: ApiClient, env: JsonDict,
                                     order_code: str = "ORD-STD") -> JsonDict:
    """
    A plain NITRO OM45 order at 300000 cents confirmed with a 100000-cent
    deposit and walked through one accepted body top into assembly.
    """
    order = F.create_order(api, F.order_payload(
        order_code=order_code, model_code="OM45", base_price_cents=300000,
        promised_date="2026-11-01T00:00:00Z", is_custom_shop=False,
        artist_tier="NONE", finish_system="NITRO"), U.COORDINATOR_HEADERS)
    env["bo1"] = order["id"]
    env["bo_v1"] = order["version"]
    F.confirm_order(api, env["bo1"], 100000, U.COORDINATOR_HEADERS)
    F.lock_options(api, env["bo1"], U.COORDINATOR_HEADERS)
    F.release_components(api, env["bo1"])
    build_component_accepted(api, env)
    env["bo_v3"] = F.start_assembly(api, env["bo1"])["version"]
    return env


def build_order_in_assembly(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    A plain NITRO OM45 order standing in assembly, with a dry store, a build
    room and a four-slot finish booth all registered and the booth already
    sampled at 50.0 percent and 21.0 degrees.
    """
    env = build_machine_shop(api, env, roomy_booth=True)
    build_released_lot(api, env)
    build_billet(api, env)
    build_standard_order_to_assembly(api, env)
    F.log_climate_reading(api, env["fb1"], 50.0, 21.0, U.FINISH_TECH_HEADERS)
    return env


def build_order_at_inspection(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    The same plain order carried the whole way to the inspection bench: sprayed
    and cured in FB-1, buffed after the clock reaches 2026-08-16, fretted, set
    up, and holding one open inspection round opened by luthier lu-eve.
    """
    env = build_order_in_assembly(api, env)
    env["fr1"] = F.create_finish_run(api, env["bo1"], env["fb1"], env["bo_v3"],
                                     finish_system="NITRO", coat_count=8)["id"]
    F.complete_spray(api, env["fr1"])
    F.set_clock(api, "2026-08-16T00:00:00Z")
    env["clock"] = "2026-08-16T00:00:00Z"
    F.buff_run(api, env["fr1"])
    F.complete_run(api, env["fr1"])
    F.record_fretwork(api, env["bo1"])
    F.record_setup(api, env["bo1"])
    env["insp1"] = F.open_inspection(api, env["bo1"], U.LUTHIER_HEADERS)["id"]
    return env


def build_order_two_components_released(api: ApiClient,
                                        env: JsonDict = None) -> JsonDict:
    """
    An order at components-released with two rough-sawn body tops cut from two
    separate spruce lots, and a held CNC-1 window waiting for the second part.
    """
    env = build_clock(api, env)
    build_dry_store(api, env)
    build_build_room(api, env)
    env["cnc1"] = F.create_station(api, env["br1"], dict(C.CNC_STATION))["id"]
    build_spec(api, env)
    build_released_lot(api, env, key="lot1", version_key="lot1_v1")
    build_billet(api, env, key="blt1", lot_key="lot1", version_key="lot1_v1")
    build_released_lot(api, env, key="lot2", version_key="lot2_v1",
                       lot_code="LOT-002")
    build_billet(api, env, key="blt2", lot_key="lot2", version_key="lot2_v1",
                 billet_code="BLT-002")
    order = F.create_order(api, F.order_payload(
        order_code="ORD-STD", model_code="OM45", base_price_cents=300000,
        promised_date="2026-11-01T00:00:00Z", is_custom_shop=False,
        artist_tier="NONE", finish_system="NITRO"), U.COORDINATOR_HEADERS)
    env["bo1"] = order["id"]
    F.confirm_order(api, env["bo1"], 100000, U.COORDINATOR_HEADERS)
    F.lock_options(api, env["bo1"], U.COORDINATOR_HEADERS)
    F.release_components(api, env["bo1"])
    env["cmp1"] = F.create_component(api, env["spec1"], env["blt1"],
                                     env["bo1"])["id"]
    env["cmp2"] = F.create_component(api, env["spec1"], env["blt2"],
                                     env["bo1"])["id"]
    env["res2"] = F.create_reservation(api, env["cnc1"], "2026-08-02T08:00:00Z",
                                       "2026-08-02T09:00:00Z",
                                       build_order_id=env["bo1"],
                                       component_id=env["cmp2"])["id"]
    return env


# ---------------------------------------------------------------------------
# Service network and export compositions
# ---------------------------------------------------------------------------
def build_two_authorized_shops(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    Two authorized repair shops: SHP-A in Japan cleared for full service and
    SHP-B in the United States cleared for warranty work only.
    """
    env = build_clock(api, env)
    env["shopA"] = F.create_shop(api, F.shop_payload(
        shop_code="SHP-A", shop_name="Kanto Fret Works", country_code="JP"))["id"]
    F.authorize_shop(api, env["shopA"], "FULL_SERVICE")
    env["shopB"] = F.create_shop(api, F.shop_payload(
        shop_code="SHP-B", shop_name="Bay Guitar Service", country_code="US"))["id"]
    F.authorize_shop(api, env["shopB"], "WARRANTY_ONLY")
    return env


def build_shipment_docs_pending(api: ApiClient, env: JsonDict = None) -> JsonDict:
    """
    A never-assembled order with its options locked and an export shipment to
    Japan awaiting documents; no protected wood contributes, so no permit is
    demanded.
    """
    env = build_clock(api, env)
    env["optD"] = F.create_option(api, dict(C.OPTION_DOT_INLAY))["id"]
    order = F.create_order(api, F.order_payload(
        order_code="ORD-EX", model_code="D28", base_price_cents=300000,
        promised_date="2026-11-01T00:00:00Z", is_custom_shop=False,
        artist_tier="NONE", finish_system="NITRO"), U.COORDINATOR_HEADERS)
    env["boX"] = order["id"]
    env["boX_v1"] = order["version"]
    env["selX"] = F.create_selection(api, env["boX"], env["optD"],
                                     env["boX_v1"],
                                     headers=U.COORDINATOR_3_HEADERS)["id"]
    F.approve_selection(api, env["selX"], U.COORDINATOR_4_HEADERS)
    F.confirm_order(api, env["boX"], 31621, U.COORDINATOR_HEADERS)
    F.lock_options(api, env["boX"], U.COORDINATOR_HEADERS)
    env["shp1"] = F.create_shipment(api, env["boX"], "JP")["id"]
    return env


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client bound to the service under test."""
    return ApiClient()


@pytest.fixture
def clock(api: ApiClient) -> JsonDict:
    return build_clock(api)


@pytest.fixture
def machine_shop(api: ApiClient) -> JsonDict:
    return build_machine_shop(api)


@pytest.fixture
def lot_received(api: ApiClient) -> JsonDict:
    return build_lot_received(api)


@pytest.fixture
def four_lots(api: ApiClient) -> JsonDict:
    return build_four_lots(api)


@pytest.fixture
def lot_released(api: ApiClient) -> JsonDict:
    return build_released_lot(api)


@pytest.fixture
def lot_permit_hold(api: ApiClient) -> JsonDict:
    return build_lot_permit_hold(api)


@pytest.fixture
def lot_rejected(api: ApiClient) -> JsonDict:
    return build_lot_rejected(api)


@pytest.fixture
def lot_after_big_cut(api: ApiClient) -> JsonDict:
    return build_lot_after_big_cut(api)


@pytest.fixture
def two_lots_one_conditioned(api: ApiClient) -> JsonDict:
    return build_two_lots_one_conditioned(api)


@pytest.fixture
def comp_routed(api: ApiClient) -> JsonDict:
    return build_comp_routed(api)


@pytest.fixture
def one_cnc_station(api: ApiClient) -> JsonDict:
    return build_one_cnc_station(api)


@pytest.fixture
def two_confirmed_orders_on_cnc1(api: ApiClient) -> JsonDict:
    return build_two_confirmed_orders_on_cnc1(api)


@pytest.fixture
def order_two_options(api: ApiClient) -> JsonDict:
    return build_order_two_options(api)


@pytest.fixture
def order_with_vine(api: ApiClient) -> JsonDict:
    return build_order_with_vine(api)


@pytest.fixture
def two_orders_custom_and_standard(api: ApiClient) -> JsonDict:
    return build_two_orders_custom_and_standard(api)


@pytest.fixture
def order_in_assembly(api: ApiClient) -> JsonDict:
    return build_order_in_assembly(api)


@pytest.fixture
def order_at_inspection(api: ApiClient) -> JsonDict:
    return build_order_at_inspection(api)


@pytest.fixture
def order_two_components_released(api: ApiClient) -> JsonDict:
    return build_order_two_components_released(api)


@pytest.fixture
def two_authorized_shops(api: ApiClient) -> JsonDict:
    return build_two_authorized_shops(api)


@pytest.fixture
def shipment_docs_pending(api: ApiClient) -> JsonDict:
    return build_shipment_docs_pending(api)


@pytest.fixture
def chain_a(api: ApiClient) -> JsonDict:
    return build_chain_a(api)


@pytest.fixture
def chain_b(api: ApiClient) -> JsonDict:
    return build_chain_b(api)


@pytest.fixture
def chain_c(api: ApiClient) -> JsonDict:
    return build_chain_c(api)


@pytest.fixture
def chain_two_orders(api: ApiClient) -> JsonDict:
    return build_chain_two_orders(api)
