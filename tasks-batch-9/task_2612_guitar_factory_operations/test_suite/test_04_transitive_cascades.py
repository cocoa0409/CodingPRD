"""
Three cascades that run several entities deep from a single request: a humid
booth, a condemned lot, and an inspection that fails once too often.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U


def test_a_humid_booth_suspends_the_cure_holds_the_order_and_frees_the_window(api, chain_a):
    """
    One hygrometer sample moves four entities: the booth leaves specification,
    the cure suspends, the order is held, and the future machine window is given
    back.

    PRD: "Fourth, because those orders were held, every station reservation
    belonging to them whose status is `HELD` and whose `starts_at` is strictly in
    the future moves `HELD → RELEASED`, and each affected station has that
    reservation's `duration_minutes` subtracted from `held_minutes` and added to
    `released_minutes`."

    Design: Difficulty/transitive_cascade/climate_excursion_cascades_four_levels_deep
    """
    F.complete_spray(api, chain_a["fr1"])
    res3 = F.create_reservation(api, chain_a["cnc1"], "2026-08-10T08:00:00Z",
                               "2026-08-10T09:00:00Z",
                               build_order_id=chain_a["bo1"])["id"]

    booth = validate_success(api.create_climate_reading(
        chain_a["fb1"], {"rh_pct": 60.0, "temp_c": 22.0}, U.FINISH_TECH_HEADERS))
    assert booth["climate_status"] == "OUT_OF_SPEC"
    assert booth["out_of_spec_since"] == "2026-08-05T09:00:00Z"

    run = validate_success(api.get_finish_run(chain_a["fr1"], U.FINISH_TECH_HEADERS))
    assert run["status"] == "CURE_SUSPENDED"
    assert run["cure_suspend_started_at"] == "2026-08-05T09:00:00Z"

    order = validate_success(
        api.get_build_order(chain_a["bo1"], U.COORDINATOR_HEADERS))
    assert order["build_stage"] == "FINISH_HELD"

    reservation = validate_success(
        api.get_station_reservation(res3, U.MACHINIST_HEADERS))
    assert reservation["status"] == "RELEASED"


def test_the_cascade_gives_back_only_the_window_that_had_not_started(api, chain_a):
    """
    The machine's minute ledger shows the released window leaving the held
    bucket while the window already worked stays counted as consumed, and the
    three buckets still add up to everything ever scheduled.

    PRD: "Reservations already under way or already begun are left alone."

    Design: Difficulty/transitive_cascade/climate_excursion_cascades_four_levels_deep
    """
    F.complete_spray(api, chain_a["fr1"])
    F.create_reservation(api, chain_a["cnc1"], "2026-08-10T08:00:00Z",
                         "2026-08-10T09:00:00Z", build_order_id=chain_a["bo1"])
    F.log_climate_reading(api, chain_a["fb1"], 60.0, 22.0, U.FINISH_TECH_HEADERS)

    station = validate_success(api.get_station(chain_a["cnc1"], U.MACHINIST_HEADERS))
    A.assert_station_minutes(station, total=120, held=0, consumed=60, released=60)
    A.assert_minutes_conserved(station)


def test_condemning_a_lot_impounds_its_billet_holds_its_part_and_stops_the_order(api, chain_b):
    """
    Condemning the wood runs down an entirely different spine: the billet is
    impounded, the part is held for protected species, and the order is stopped
    with the stage it was interrupted at recorded for later restoration.

    PRD: "Because those components were held, every build order that owns at
    least one of them and whose build stage is not `SERIALIZED` or `SCRAPPED`
    records its current build stage in `stage_before_compliance_hold` and moves
    that stage to `COMPLIANCE_HOLD`; again this applies from every non-terminal
    build stage."

    Design: Difficulty/transitive_cascade/lot_rejection_cascades_four_levels_through_a_different_spine
    """
    lot = validate_success(api.reject_tonewood_lot(
        chain_b["lot1"], U.COMPLIANCE_HEADERS, {"reason": "PERMIT_WITHDRAWN"}))
    assert lot["status"] == "REJECTED"
    assert lot["permit_status"] == "INVALID"

    billet = validate_success(api.get_billet(chain_b["blt1"], U.MACHINIST_HEADERS))
    assert billet["status"] == "QUARANTINED"

    component = validate_success(
        api.get_component(chain_b["cmp1"], U.MACHINIST_HEADERS))
    assert component["status"] == "QC_HELD"
    assert component["qc_hold_reason"] == "PROTECTED_SPECIES"

    order = validate_success(
        api.get_build_order(chain_b["bo1"], U.COORDINATOR_HEADERS))
    assert order["build_stage"] == "COMPLIANCE_HOLD"
    assert order["stage_before_compliance_hold"] == "COMPONENTS_RELEASED"


def test_impounding_the_wood_moves_every_remaining_board_foot_into_the_scrapped_bucket(api, chain_b):
    """
    The reserved board feet and the wood still standing uncut both move into the
    scrapped bucket in the same request, so nothing goes missing from the
    delivery that was booked in.

    PRD: "Because the lot became `REJECTED`, every billet cut from it whose
    status is `AVAILABLE` or `RESERVED` moves to `QUARANTINED`, with the lot's
    `board_feet_unassigned` or `board_feet_reserved` bucket decreasing by that
    billet's `board_feet` and `board_feet_scrapped` increasing by the same
    amount; any wood still standing uncut in `board_feet_available` also moves
    into `board_feet_scrapped`."

    Design: Difficulty/transitive_cascade/lot_rejection_cascades_four_levels_through_a_different_spine
    """
    F.reject_lot(api, chain_b["lot1"], "PERMIT_WITHDRAWN")

    lot = validate_success(
        api.get_tonewood_lot(chain_b["lot1"], U.MACHINIST_HEADERS))
    A.assert_lot_ledger(lot, available=0.00, unassigned=0.00, reserved=0.00,
                        consumed=0.00, scrapped=99.10, kerf_loss=0.90)
    A.assert_wood_conserved(lot)


def carry_to_setup(api, env):
    """
    Take the sprayed instrument through its cure to the setup bench: close the
    spray, advance the clock to the moment the cure is ready, buff, complete the
    run, level the frets and record the setup work.
    """
    F.complete_spray(api, env["fr1"])
    F.set_clock(api, "2026-08-22T09:00:00Z")
    env["clock"] = "2026-08-22T09:00:00Z"
    F.buff_run(api, env["fr1"])
    F.complete_run(api, env["fr1"])
    F.record_fretwork(api, env["bo1"])
    F.record_setup(api, env["bo1"])
    return env


def fail_one_round(api, env):
    """
    Open a round as lu-eve, measure a treble action fifteen hundredths of a
    millimetre over specification with the intonation eight tenths of a cent
    over, and have qi-frank sign it.
    """
    round_id = F.open_inspection(api, env["bo1"], U.LUTHIER_HEADERS)["id"]
    F.measure_inspection(api, round_id, F.measurement_payload(
        action_mm_treble=1.75, action_mm_bass=2.10, relief_mm=0.20,
        intonation_cents_max=4.8), U.LUTHIER_HEADERS)
    signed = F.sign_inspection(api, round_id, U.INSPECTOR_HEADERS)
    return round_id, signed


def test_the_first_failed_round_moves_the_stage_and_the_counter_and_nothing_else(api, chain_a):
    """
    One failure is not yet a commercial problem: the instrument goes back to the
    setup bench and the rework tally rises, while the negotiated status and the
    promised date stand exactly where they were.

    PRD: "A round whose score is above 10.00 moves `MEASURED → FAILED` with
    `verdict` set to `FAIL`, and that failure is the root of a three-link
    cascade: the order moves `build_stage` `INSPECTION → SETUP`, its
    `rework_round_count` increases by one, and if that count has reached two or
    more, the commercial dimension escalates — `commercial_status` moves
    `CONFIRMED → AT_RISK` or `OPTIONS_LOCKED → AT_RISK`, `promised_date`
    advances by fourteen days, and `priority_score` is recomputed, which lifts
    the order in the station queue because `AT_RISK` carries its own scheduling
    points."

    Design: Difficulty/transitive_cascade/inspection_failure_cascades_three_levels_into_commercial_risk
    """
    carry_to_setup(api, chain_a)
    _, signed = fail_one_round(api, chain_a)
    assert signed["status"] == "FAILED"
    assert signed["verdict"] == "FAIL"
    assert signed["deviation_score"] == 13.00
    assert signed["round_number"] == 1

    order = validate_success(
        api.get_build_order(chain_a["bo1"], U.COORDINATOR_HEADERS))
    assert order["build_stage"] == "SETUP"
    assert order["rework_round_count"] == 1
    assert order["commercial_status"] == "OPTIONS_LOCKED"
    # Locking already pushed the promise to 2026-08-01 plus sixty days of base
    # lead time plus the vine inlay's forty-five, and one failure moves nothing.
    assert order["promised_date"] == "2026-11-14T00:00:00Z"


def test_the_second_failed_round_reaches_the_commercial_dimension(api, chain_a):
    """
    The second failure crosses the escalation threshold, so the same signature
    now flips the order at risk, slips the promise a fortnight and lifts its
    place in the station queue.

    PRD: "Raising the treble action alone to 1.75 makes that dimension fifteen
    hundredths over, contributing 9000 for a total of 13000, a `deviation_score`
    of 13.00 and a `FAIL`."

    Design: Difficulty/transitive_cascade/inspection_failure_cascades_three_levels_into_commercial_risk
    """
    carry_to_setup(api, chain_a)
    fail_one_round(api, chain_a)
    _, second = fail_one_round(api, chain_a)
    assert second["round_number"] == 2
    assert second["status"] == "FAILED"
    assert second["deviation_score"] == 13.00

    order = validate_success(
        api.get_build_order(chain_a["bo1"], U.COORDINATOR_HEADERS))
    assert order["build_stage"] == "SETUP"
    assert order["rework_round_count"] == 2
    assert order["commercial_status"] == "AT_RISK"
    # The locked promise of 2026-11-14 slips a fortnight, which puts it further
    # than ninety days out, so the urgency term clamps to zero and only the
    # endorser, custom-shop and distress terms remain.
    assert order["promised_date"] == "2026-11-28T00:00:00Z"
    assert order["priority_score"] == 60.00
