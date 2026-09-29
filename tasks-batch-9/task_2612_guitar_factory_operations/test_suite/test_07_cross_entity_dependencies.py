"""
Four gates that read another entity's state rather than their own: the latest
inspection round, the parent lot behind a valid billet, the sibling parts on an
order, and the authorization standing of a repair shop.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def test_a_measured_but_unsigned_round_does_not_earn_a_serial_number(api, order_at_inspection):
    """
    Everything about the round looks approved — a passing verdict and a score
    inside the limit — except the signature, and the signature is what
    serialization actually reads.

    PRD: "The round with the highest `round_number` on that order must be in
    status `SIGNED` with `verdict` of `PASS`, otherwise
    `ERR_INSPECTION_NOT_SIGNED`."

    Design: Difficulty/cross_entity_state_dependency/assign_serial_requires_the_latest_inspection_signed_and_passing
    """
    measured = F.measure_inspection(
        api, order_at_inspection["insp1"], F.measurement_payload(
            action_mm_treble=1.70, action_mm_bass=2.10, relief_mm=0.20,
            intonation_cents_max=4.8), U.LUTHIER_HEADERS)
    assert measured["status"] == "MEASURED"
    assert measured["deviation_score"] == 10.00

    validate_error(api.assign_serial(order_at_inspection["bo1"],
                                     U.COORDINATOR_HEADERS),
                   E.ERR_INSPECTION_NOT_SIGNED, 409)

    order = validate_success(api.get_build_order(
        order_at_inspection["bo1"], U.COORDINATOR_HEADERS))
    assert order["serial_number"] is None
    assert order["build_stage"] == "INSPECTION"
    assert order["commercial_status"] == "OPTIONS_LOCKED"


def test_the_signature_is_the_only_thing_missing_and_supplying_it_mints_the_serial(api, order_at_inspection):
    """
    With the inspector's signature added and nothing else changed, the identical
    serialization request succeeds and carries the commercial side to invoiced.

    PRD: "Only the latest round counts: an earlier passing round does not qualify,
    so a pass followed by a freshly re-opened round blocks serialization until
    that new round is itself signed."

    Design: Difficulty/cross_entity_state_dependency/assign_serial_requires_the_latest_inspection_signed_and_passing
    """
    F.measure_inspection(api, order_at_inspection["insp1"], F.measurement_payload(
        action_mm_treble=1.70, action_mm_bass=2.10, relief_mm=0.20,
        intonation_cents_max=4.8), U.LUTHIER_HEADERS)
    signed = F.sign_inspection(api, order_at_inspection["insp1"],
                               U.INSPECTOR_HEADERS)
    assert signed["status"] == "SIGNED"

    order = validate_success(api.assign_serial(order_at_inspection["bo1"],
                                               U.COORDINATOR_HEADERS))
    assert order["serial_number"] == "OM45-2026-00001"
    assert order["build_stage"] == "SERIALIZED"
    assert order["commercial_status"] == "INVOICED"


def a_lot_cut_down_to_nothing(api):
    """
    A hundred board feet of spruce released and then sawn almost entirely away in
    one ninety-seven-board-foot cut, which leaves the lot depleted while the
    billet itself is perfectly sound.
    """
    env = X.build_clock(api)
    X.build_dry_store(api, env)
    env["spec1"] = F.create_spec(api, F.spec_payload())["id"]
    env["lotA"] = F.create_lot(api, F.lot_payload(
        lot_code="LOT-A", species_code="SITKA_SPRUCE", cites_appendix="NONE",
        board_feet_received=100.00, moisture_content_pct=7.0,
        storage_room_id=env["dry1"]))["id"]
    F.condition_lot(api, env["lotA"])
    version = F.release_lot(api, env["lotA"])["version"]
    env["bltBig"] = F.create_billet(api, env["lotA"], version,
                                   billet_code="BLT-BIG", board_feet=97.00,
                                   grade="AAA")["id"]
    return env


def test_a_sound_billet_cannot_be_machined_once_its_parent_lot_has_run_out(api):
    """
    The billet is available and both compatible with the spec, so the only thing
    wrong is the state of the lot behind it — a lot that was perfectly releasable
    when the cut was booked.

    PRD: "The billet must be in status `AVAILABLE`, or the request is refused with
    `ERR_BILLET_STATE_INVALID`, and the lot it came from must still be
    `RELEASED`, or `ERR_LOT_NOT_RELEASED`."

    Design: Difficulty/cross_entity_state_dependency/component_creation_requires_its_lot_to_be_released_not_merely_cuttable
    """
    env = a_lot_cut_down_to_nothing(api)

    billet = validate_success(api.get_billet(env["bltBig"], U.MACHINIST_HEADERS))
    assert billet["status"] == "AVAILABLE"
    assert billet["grade"] == "AAA"

    validate_error(api.create_component({
        "spec_id": env["spec1"], "billet_id": env["bltBig"],
    }, U.MACHINIST_HEADERS), E.ERR_LOT_NOT_RELEASED, 409)

    components, _ = validate_paginated(
        api.list_components(U.MACHINIST_HEADERS, {"billet_id": env["bltBig"]}))
    assert components == []


def test_the_cut_that_left_under_two_board_feet_depleted_the_lot_in_the_same_request(api):
    """
    The saw booked ninety-seven board feet plus its kerf and left nine hundredths
    standing, which is below the two board feet the plant treats as usable, so the
    lot moved itself out of service as the billet was created.

    PRD: "If the cut leaves the lot with less than two board feet still standing
    in `board_feet_available`, the lot moves `RELEASED → DEPLETED` in the same
    request and no further billets may be sawn from it."

    Design: Difficulty/cross_entity_state_dependency/component_creation_requires_its_lot_to_be_released_not_merely_cuttable
    """
    env = a_lot_cut_down_to_nothing(api)

    lot = validate_success(api.get_tonewood_lot(env["lotA"], U.MACHINIST_HEADERS))
    assert lot["status"] == "DEPLETED"
    assert lot["board_feet_available"] == 0.09
    assert lot["board_feet_kerf_loss"] == 2.91
    assert lot["board_feet_unassigned"] == 97.00


def one_accepted_part_and_one_still_on_the_bench(api, env):
    """
    Saw a second billet off the same lot and open a part against it, leaving the
    order with one accepted body top and one still rough-sawn.
    """
    X.read_lot_version(api, env, key="lot1", version_key="lot_v2")
    env["blt2"] = F.create_billet(api, env["lot1"], env["lot_v2"],
                                  billet_code="BLT-002", board_feet=30.00,
                                  grade="AAA")["id"]
    env["cmp2"] = F.create_component(api, env["spec1"], env["blt2"],
                                     build_order_id=env["bo1"])["id"]
    return env


def test_assembly_will_not_start_while_a_sibling_part_is_still_in_flight(api, chain_b):
    """
    One part is accepted, which satisfies the count that asks for finished work,
    but another is still moving through the shop, and the refusal has to say so
    rather than claim nothing is ready.

    PRD: "At least one part on the order must be in status `ACCEPTED`, otherwise
    the request is refused with `ERR_COMPONENTS_NOT_ACCEPTED`; and no part on the
    order may still be in `ROUGH_SAWN`, `CNC_ROUTED`, `HAND_SHAPED`, `QC_HELD` or
    `REWORK`, otherwise it is refused with `ERR_COMPONENT_IN_FLIGHT`."

    Design: Difficulty/cross_entity_state_dependency/start_assembly_requires_every_component_out_of_flight
    """
    env = one_accepted_part_and_one_still_on_the_bench(api, chain_b)

    validate_error(api.start_assembly(env["bo1"], U.LUTHIER_HEADERS),
                   E.ERR_COMPONENT_IN_FLIGHT, 409)

    order = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert order["build_stage"] == "COMPONENTS_RELEASED"


def test_the_two_halves_of_the_gate_point_in_opposite_directions(api, chain_b):
    """
    The accepted population is not empty and the in-flight population is not
    empty either, so the aggregate that fails is the second one and the
    nothing-is-ready code must not be what comes back.

    PRD: "A part that has already been scrapped is neither accepted nor in flight,
    so it blocks nothing."

    Design: Difficulty/cross_entity_state_dependency/start_assembly_requires_every_component_out_of_flight
    """
    env = one_accepted_part_and_one_still_on_the_bench(api, chain_b)

    accepted, _ = validate_paginated(api.list_components(
        U.MACHINIST_HEADERS, {"build_order_id": env["bo1"], "status": "ACCEPTED"}))
    assert len(accepted) == 1
    rough, _ = validate_paginated(api.list_components(
        U.MACHINIST_HEADERS, {"build_order_id": env["bo1"], "status": "ROUGH_SAWN"}))
    assert len(rough) == 1

    response = api.start_assembly(env["bo1"], U.LUTHIER_HEADERS)
    assert response.status_code == 409
    assert response.json()["data"]["error_id"] != E.ERR_COMPONENTS_NOT_ACCEPTED


def a_serialized_instrument_and_a_suspended_shop(api, env):
    """
    Carry the custom instrument to a minted serial number, then enrol a Tokyo
    repair shop at full-service level and suspend it again for a failed audit.
    """
    version = F.start_assembly(api, env["bo1"])["version"]
    F.log_climate_reading(api, env["fb1"], 50.0, 21.0, U.FINISH_TECH_HEADERS)
    env["fr1"] = F.create_finish_run(api, env["bo1"], env["fb1"], version,
                                     finish_system="NITRO", coat_count=8)["id"]
    F.complete_spray(api, env["fr1"])
    F.set_clock(api, "2026-08-16T00:00:00Z")
    env["clock"] = "2026-08-16T00:00:00Z"
    F.buff_run(api, env["fr1"])
    F.complete_run(api, env["fr1"])
    F.record_fretwork(api, env["bo1"])
    F.record_setup(api, env["bo1"])
    inspection = F.open_inspection(api, env["bo1"], U.LUTHIER_HEADERS)["id"]
    F.measure_inspection(api, inspection, F.measurement_payload(
        action_mm_treble=1.70, action_mm_bass=2.10, relief_mm=0.20,
        intonation_cents_max=4.8), U.LUTHIER_HEADERS)
    F.sign_inspection(api, inspection, U.INSPECTOR_HEADERS)
    env["serial"] = F.assign_serial(api, env["bo1"],
                                    U.COORDINATOR_HEADERS)["serial_number"]
    env["shop1"] = F.create_shop(api, F.shop_payload(
        shop_code="SHOP-1", shop_name="Kanda Strings",
        country_code="JP"), U.SERVICE_MANAGER_HEADERS)["id"]
    F.authorize_shop(api, env["shop1"], "FULL_SERVICE", U.SERVICE_MANAGER_HEADERS)
    F.suspend_shop(api, env["shop1"], U.SERVICE_MANAGER_HEADERS)
    return env


def test_a_suspended_shop_may_not_register_a_warranty(api, chain_c):
    """
    The instrument is serialized and the serial on the request matches it, so the
    only fault is the standing of the shop — a standing it previously held and
    lost.

    PRD: "The registering shop's status must be `AUTHORIZED`, otherwise
    `ERR_SHOP_NOT_AUTHORIZED`; a shop that is still `APPLIED` or has been
    `SUSPENDED` cannot register anything."

    Design: Difficulty/cross_entity_state_dependency/warranty_registration_requires_an_authorized_repair_shop
    """
    env = a_serialized_instrument_and_a_suspended_shop(api, chain_c)
    assert env["serial"] == "OM45-2026-00001"

    shop = validate_success(api.get_repair_shop(env["shop1"], U.SERVICE_MANAGER_HEADERS))
    assert shop["status"] == "SUSPENDED"

    validate_error(api.create_warranty_registration({
        "build_order_id": env["bo1"], "registering_shop_id": env["shop1"],
        "serial_number": "OM45-2026-00001", "owner_email": "owner@example.com",
        "purchase_date": "2026-08-16T00:00:00Z",
    }, U.SERVICE_MANAGER_HEADERS), E.ERR_SHOP_NOT_AUTHORIZED, 409)

    registrations, _ = validate_paginated(api.list_warranty_registrations(
        U.SERVICE_MANAGER_HEADERS, {"build_order_id": env["bo1"]}))
    assert registrations == []


def test_re_authorizing_the_shop_lets_the_identical_registration_through(api, chain_c):
    """
    The blocking state is reversible, so authorizing the shop a second time makes
    the byte-identical request succeed, with the coverage window taken from the
    custom-shop instrument rather than from the shop.

    PRD: "`coverage_months` is sixty when the order's `is_custom_shop` is true and
    twenty-four otherwise."

    Design: Difficulty/cross_entity_state_dependency/warranty_registration_requires_an_authorized_repair_shop
    """
    env = a_serialized_instrument_and_a_suspended_shop(api, chain_c)
    F.authorize_shop(api, env["shop1"], "FULL_SERVICE", U.SERVICE_MANAGER_HEADERS)

    registration = validate_success(api.create_warranty_registration({
        "build_order_id": env["bo1"], "registering_shop_id": env["shop1"],
        "serial_number": "OM45-2026-00001", "owner_email": "owner@example.com",
        "purchase_date": "2026-08-16T00:00:00Z",
    }, U.SERVICE_MANAGER_HEADERS), 201)
    assert registration["status"] == "ACTIVE"
    assert registration["coverage_months"] == 60
    assert registration["coverage_ends_at"] == "2031-08-16T00:00:00Z"
