"""
Three lifecycles that do not run in a straight line: the refinish loop that puts
a body back on the bench, the room posture cycle that only a human act can
close, and the two dimensions of a build order that advance side by side.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U

VINE = {
    "option_code": "INL-VINE",
    "option_group": "INLAY",
    "upcharge_cents": 130000,
    "complexity_class": "ARTISAN",
    "lead_time_days": 45,
    "incompatible_option_codes": ["INL-DOT"],
}


def test_condemning_the_finish_sends_the_body_back_to_the_bench(api, chain_a):
    """
    A condemned finish does not strand the instrument: the shop-floor dimension
    steps backwards to assembly, the refinish tally rises and the booth slot is
    handed back, while the commercial dimension is untouched.

    PRD: "Rejection is accepted from `CURING`, `CURE_SUSPENDED` or `BUFFING`,
    moves the run to `REJECTED`, decrements the booth's `occupied_slots`, and
    sends the order from `IN_FINISH` or `FINISH_HELD` back to `IN_ASSEMBLY`
    while incrementing its `refinish_count`."

    Design: Difficulty/non_linear_state_machine/finish_refinish_cycle_returns_order_to_in_assembly
    """
    F.complete_spray(api, chain_a["fr1"])

    run = validate_success(api.reject_finish_run(
        chain_a["fr1"], U.INSPECTOR_HEADERS, {"reason": "ORANGE_PEEL"}))
    assert run["status"] == "REJECTED"

    order = validate_success(
        api.get_build_order(chain_a["bo1"], U.COORDINATOR_HEADERS))
    assert order["build_stage"] == "IN_ASSEMBLY"
    assert order["commercial_status"] == "OPTIONS_LOCKED"
    assert order["refinish_count"] == 1

    booth = validate_success(
        api.get_storage_room(chain_a["fb1"], U.FINISH_TECH_HEADERS))
    assert booth["occupied_slots"] == 0


def test_a_replacement_run_may_be_booked_once_the_first_finish_is_condemned(api, chain_a):
    """
    The loop is genuinely closed rather than a dead end: with the body back in
    assembly a second booking is accepted and drives the instrument into the
    booth again.

    PRD: "That closes the refinish loop — `IN_ASSEMBLY → IN_FINISH →
    IN_ASSEMBLY` — and a replacement run may then be booked."

    Design: Difficulty/non_linear_state_machine/finish_refinish_cycle_returns_order_to_in_assembly
    """
    F.complete_spray(api, chain_a["fr1"])
    F.reject_run(api, chain_a["fr1"], "ORANGE_PEEL")

    order = validate_success(
        api.get_build_order(chain_a["bo1"], U.COORDINATOR_HEADERS))
    replacement = validate_success(api.create_finish_run({
        "build_order_id": chain_a["bo1"], "booth_id": chain_a["fb1"],
        "finish_system": "NITRO", "coat_count": 12,
        "expected_build_order_version": order["version"],
    }, U.FINISH_TECH_HEADERS), 201)
    assert replacement["status"] == "SPRAYING"

    after = validate_success(
        api.get_build_order(chain_a["bo1"], U.COORDINATOR_HEADERS))
    assert after["build_stage"] == "IN_FINISH"
    assert after["refinish_count"] == 1


def a_room_driven_into_quarantine(api):
    """
    A dry store sampled humid, sampled humid again exactly a day later so the
    quarantine timer fires, and then sampled back inside tolerance.
    """
    env = X.build_clock(api)
    X.build_dry_store(api, env)
    F.log_climate_reading(api, env["dry1"], 61.0, 22.0)
    F.set_clock(api, "2026-08-02T00:00:00Z")
    env["clock"] = "2026-08-02T00:00:00Z"
    F.log_climate_reading(api, env["dry1"], 62.0, 22.0)
    F.log_climate_reading(api, env["dry1"], 48.0, 21.0)
    return env


def test_only_a_deliberate_certification_closes_the_room_posture_cycle(api):
    """
    A good sample refreshes the numbers but leaves a quarantined room
    quarantined; the room is only returned to specification when someone
    certifies the recalibrated space.

    PRD: "Escaping quarantine requires a deliberate human act rather than a
    passing good reading: a `PlantAdmin` or a `QualityInspector` certifies the
    recalibrated room, which moves it `QUARANTINED → IN_SPEC` and clears
    `out_of_spec_since`."

    Design: Difficulty/non_linear_state_machine/storage_room_quarantine_then_recertify_cycle
    """
    env = a_room_driven_into_quarantine(api)

    before = validate_success(api.get_storage_room(env["dry1"], U.PLANT_ADMIN_HEADERS))
    assert before["climate_status"] == "QUARANTINED"
    assert before["latest_rh_pct"] == 48.0

    room = validate_success(api.certify_storage_room(env["dry1"], U.PLANT_ADMIN_HEADERS))
    assert room["climate_status"] == "IN_SPEC"
    assert room["out_of_spec_since"] is None
    assert room["latest_rh_pct"] == 48.0
    assert room["latest_temp_c"] == 21.0


def test_the_same_sampling_endpoint_fires_three_different_posture_transitions(api):
    """
    One endpoint drives the whole cycle: the first humid sample marks the room
    out of specification and stamps the clock, and the second humid sample a
    full day later escalates it to quarantine.

    PRD: "From `OUT_OF_SPEC`, a sample that is *still* outside the band, taken
    when a full day or more has elapsed since `out_of_spec_since`, escalates the
    room `OUT_OF_SPEC → QUARANTINED`; the quarantine timer is twenty-four hours
    measured on the logical clock, and the comparison is inclusive at exactly
    twenty-four hours."

    Design: Difficulty/non_linear_state_machine/storage_room_quarantine_then_recertify_cycle
    """
    env = X.build_clock(api)
    X.build_dry_store(api, env)

    first = validate_success(api.create_climate_reading(
        env["dry1"], {"rh_pct": 61.0, "temp_c": 22.0}, U.FINISH_TECH_HEADERS))
    assert first["climate_status"] == "OUT_OF_SPEC"
    assert first["out_of_spec_since"] == "2026-08-01T00:00:00Z"
    assert first["latest_rh_pct"] == 61.0

    F.set_clock(api, "2026-08-02T00:00:00Z")
    F.log_climate_reading(api, env["dry1"], 62.0, 22.0)
    escalated = validate_success(
        api.get_storage_room(env["dry1"], U.PLANT_ADMIN_HEADERS))
    assert escalated["climate_status"] == "QUARANTINED"


def a_confirmed_custom_order_still_in_draft(api):
    """
    A custom order with one approved artisan inlay, confirmed with 200000 cents
    on deposit and never released to the shop floor.
    """
    env = X.build_clock(api)
    env["optA"] = F.create_option(api, dict(VINE))["id"]
    order = F.create_order(api, F.order_payload(
        order_code="ORD-001", model_code="OM45", base_price_cents=480000,
        is_custom_shop=True, artist_tier="ENDORSER", finish_system="NITRO",
        promised_date="2026-10-01T00:00:00Z"), U.COORDINATOR_HEADERS)
    env["bo1"] = order["id"]
    env["sel1"] = F.create_selection(api, env["bo1"], env["optA"],
                                     order["version"], quantity=1,
                                     headers=U.COORDINATOR_HEADERS)["id"]
    F.approve_selection(api, env["sel1"], U.COORDINATOR_2_HEADERS)
    F.confirm_order(api, env["bo1"], 200000, U.COORDINATOR_HEADERS)
    return env


def test_two_commercial_transitions_fire_while_the_shop_floor_has_not_moved(api):
    """
    One row shows a fully negotiated price alongside a build that has not
    started, a pairing that is only possible when the two dimensions are
    genuinely separate machines.

    PRD: "The commercial dimension can advance all the way to `OPTIONS_LOCKED`
    while the build stage is still `DRAFT`; the two interlock at exactly one
    point, described at the end of this subsection."

    Design: Difficulty/non_linear_state_machine/build_stage_and_commercial_status_advance_independently
    """
    env = a_confirmed_custom_order_still_in_draft(api)

    F.lock_options(api, env["bo1"], U.COORDINATOR_HEADERS)

    order = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert order["build_stage"] == "DRAFT"
    assert order["commercial_status"] == "OPTIONS_LOCKED"
    assert order["binding_quote_total_cents"] == 716610
    assert order["deposit_paid_cents"] == 200000
    assert order["deposit_held_cents"] == 200000


def test_releasing_to_the_machine_shop_moves_only_the_physical_dimension(api):
    """
    The single interlock between the dimensions works one way only: releasing
    the order advances the build stage and leaves the negotiated commercial
    state exactly where it stood.

    PRD: "A `Machinist` releases the order to the machine shop, moving
    `build_stage` `DRAFT → COMPONENTS_RELEASED`, and that transition requires
    `commercial_status` to be `OPTIONS_LOCKED` — a price that is still
    negotiable may not consume wood."

    Design: Difficulty/non_linear_state_machine/build_stage_and_commercial_status_advance_independently
    """
    env = a_confirmed_custom_order_still_in_draft(api)
    F.lock_options(api, env["bo1"], U.COORDINATOR_HEADERS)

    released = validate_success(
        api.release_components(env["bo1"], U.MACHINIST_HEADERS))
    assert released["build_stage"] == "COMPONENTS_RELEASED"
    assert released["commercial_status"] == "OPTIONS_LOCKED"
    assert released["binding_quote_total_cents"] == 716610
