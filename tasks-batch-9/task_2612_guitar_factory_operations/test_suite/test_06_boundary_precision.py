"""
Five boundaries, each tested from both sides in one run: a tenth of a percentage
point of moisture, a hundredth of a deviation point, one minute of machine
changeover, one hour of booth hold, and one cent of deposit.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def two_lots_dried_to(api, first_pct, second_pct):
    """
    Two otherwise identical non-protected spruce deliveries in one dry store,
    dried to the two moisture figures given.
    """
    env = X.build_clock(api)
    X.build_dry_store(api, env)
    for key, code, pct in (("lotA", "LOT-A", first_pct), ("lotB", "LOT-B", second_pct)):
        env[key] = F.create_lot(api, F.lot_payload(
            lot_code=code, species_code="SITKA_SPRUCE", cites_appendix="NONE",
            board_feet_received=100.00, moisture_content_pct=12.0,
            storage_room_id=env["dry1"]))["id"]
        F.log_moisture_reading(api, env[key], pct)
    return env


def test_wood_at_exactly_eight_percent_conditions_while_eight_point_one_does_not(api):
    """
    A tenth of a percentage point is the whole difference between two identical
    deliveries: the one sitting exactly on the upper bound acclimatises, the one
    a tenth above it is refused.

    PRD: "It requires the lot's current `moisture_content_pct` to sit inside the
    band from 6.0 to 8.0 percent with **both bounds inclusive** — 6.0 passes, 8.0
    passes, 5.9 and 8.1 are refused with `ERR_MOISTURE_OUT_OF_BAND` — and it
    requires the lot's storage room to be `IN_SPEC` at that moment."

    Design: Difficulty/boundary_precision_check/moisture_band_upper_bound_is_inclusive
    """
    env = two_lots_dried_to(api, 8.0, 8.1)

    accepted = validate_success(
        api.condition_tonewood_lot(env["lotA"], U.WOOD_BUYER_HEADERS))
    assert accepted["status"] == "CONDITIONED"
    assert accepted["moisture_content_pct"] == 8.0

    validate_error(api.condition_tonewood_lot(env["lotB"], U.WOOD_BUYER_HEADERS),
                   E.ERR_MOISTURE_OUT_OF_BAND, 409)
    refused = validate_success(
        api.get_tonewood_lot(env["lotB"], U.WOOD_BUYER_HEADERS))
    assert refused["status"] == "KILN_DRYING"


def test_the_lower_bound_of_the_band_behaves_the_same_way(api):
    """
    The band is inclusive at the bottom as well, so wood read at exactly six
    percent acclimatises while wood a tenth drier is refused with the same code.

    PRD: "A lot's `moisture_content_pct` must sit inside the inclusive band
    before it may be conditioned or released — violation
    `ERR_MOISTURE_OUT_OF_BAND` (409) — and a component accepted at QC must sit
    inside its spec's thickness tolerance, violation
    `ERR_THICKNESS_OUT_OF_TOLERANCE` (409)."

    Design: Difficulty/boundary_precision_check/moisture_band_upper_bound_is_inclusive
    """
    env = two_lots_dried_to(api, 6.0, 5.9)
    assert C.MOISTURE_BAND_MIN_PCT == 6.0

    accepted = validate_success(
        api.condition_tonewood_lot(env["lotA"], U.WOOD_BUYER_HEADERS))
    assert accepted["status"] == "CONDITIONED"

    validate_error(api.condition_tonewood_lot(env["lotB"], U.WOOD_BUYER_HEADERS),
                   E.ERR_MOISTURE_OUT_OF_BAND, 409)


def test_a_guitar_scoring_exactly_ten_passes_its_inspection(api, order_at_inspection):
    """
    The four-term sum lands on exactly the published limit, and the limit is
    inclusive, so the instrument is signed off as passing rather than sent back.

    PRD: "The verdict follows from the score against a threshold of 10.00, with
    the bound inclusive: a `deviation_score` of 10.00 is a `PASS` and 10.01 is a
    `FAIL`."

    Design: Difficulty/boundary_precision_check/deviation_score_exactly_at_pass_score_max_passes
    """
    F.measure_inspection(api, order_at_inspection["insp1"], F.measurement_payload(
        action_mm_treble=1.70, action_mm_bass=2.10, relief_mm=0.20,
        intonation_cents_max=4.8), U.LUTHIER_HEADERS)

    signed = validate_success(api.sign_setup_inspection(
        order_at_inspection["insp1"], U.INSPECTOR_HEADERS))
    assert signed["deviation_score"] == 10.00
    assert signed["verdict"] == "PASS"
    assert signed["status"] == "SIGNED"

    order = validate_success(api.get_build_order(
        order_at_inspection["bo1"], U.COORDINATOR_HEADERS))
    assert order["build_stage"] == "INSPECTION"
    assert order["rework_round_count"] == 0


def test_the_two_dimensions_inside_specification_contribute_nothing_at_all(api, order_at_inspection):
    """
    The bass action and the relief are both better than specification and clamp
    to zero rather than earning credit that could offset the treble action, which
    is what keeps the total on the limit instead of below it.

    PRD: "An inspection reading 1.70, 2.10, 0.20 and 4.8 converts to 170, 210, 20
    and 48 sub-units; the treble action is ten hundredths over its limit and
    contributes 6000, the bass action and the relief are both inside
    specification and clamp to zero, and the intonation is eight tenths of a cent
    over and contributes 4000, for a total of 10000, a `deviation_score` of
    exactly 10.00 and a `PASS`."

    Design: Difficulty/boundary_precision_check/deviation_score_exactly_at_pass_score_max_passes
    """
    measured = F.measure_inspection(
        api, order_at_inspection["insp1"], F.measurement_payload(
            action_mm_treble=1.70, action_mm_bass=2.10, relief_mm=0.20,
            intonation_cents_max=4.8), U.LUTHIER_HEADERS)
    assert measured["status"] == "MEASURED"
    assert measured["deviation_score"] == 10.00
    assert C.PASS_SCORE_MAX == 10.00

    tighter = validate_success(api.get_setup_inspection(
        order_at_inspection["insp1"], U.INSPECTOR_HEADERS))
    assert tighter["action_mm_bass"] == 2.10
    assert tighter["relief_mm"] == 0.20


def test_a_window_one_minute_inside_the_changeover_buffer_collides(api, one_cnc_station):
    """
    The router needs half an hour of re-tooling between jobs, so a booking
    starting one minute short of that buffer is refused while the one starting
    exactly on it is accepted.

    PRD: "A window that begins exactly at an existing reservation's `ends_at`
    plus the changeover minutes does **not** conflict and is accepted."

    Design: Difficulty/boundary_precision_check/station_window_adjacency_exactly_at_changeover_boundary
    """
    F.create_reservation(api, one_cnc_station["cnc1"], "2026-08-02T08:00:00Z",
                         "2026-08-02T09:00:00Z")

    validate_error(api.create_station_reservation({
        "station_id": one_cnc_station["cnc1"],
        "starts_at": "2026-08-02T09:29:00Z", "ends_at": "2026-08-02T10:29:00Z",
    }, U.MACHINIST_HEADERS), E.ERR_STATION_WINDOW_CONFLICT, 409)

    accepted = validate_success(api.create_station_reservation({
        "station_id": one_cnc_station["cnc1"],
        "starts_at": "2026-08-02T09:30:00Z", "ends_at": "2026-08-02T10:30:00Z",
    }, U.MACHINIST_HEADERS), 201)
    assert accepted["status"] == "HELD"
    assert accepted["duration_minutes"] == 60


def test_the_changeover_buffer_widens_the_conflict_test_and_is_never_billed(api, one_cnc_station):
    """
    The half hour of re-tooling only decides whether a booking is legal; the
    machine's ledger still counts the two accepted hours as two hours, not three.

    PRD: "It is also widened symmetrically on both sides by the station's
    `changeover_minutes`, because a router has to be re-tooled between jobs."

    Design: Difficulty/boundary_precision_check/station_window_adjacency_exactly_at_changeover_boundary
    """
    F.create_reservation(api, one_cnc_station["cnc1"], "2026-08-02T08:00:00Z",
                         "2026-08-02T09:00:00Z")
    F.create_reservation(api, one_cnc_station["cnc1"], "2026-08-02T09:30:00Z",
                         "2026-08-02T10:30:00Z")

    station = validate_success(
        api.get_station(one_cnc_station["cnc1"], U.MACHINIST_HEADERS))
    assert station["changeover_minutes"] == 30
    assert station["total_scheduled_minutes"] == 120
    assert station["held_minutes"] == 120


def test_a_booth_hold_that_begins_on_the_previous_hold_s_last_instant_collides(api, chain_two_orders):
    """
    The booth interval is closed at both ends, so a request whose hold starts on
    the very instant the standing hold ends is treated as an overlap — and the
    proof is that the chemistry rule, which only inspects touching holds, fires
    at all.

    PRD: "A hold that begins exactly at an existing hold's `booth_hold_until`
    therefore **does** collide — the opposite of the station rule."

    Design: Difficulty/boundary_precision_check/booth_hold_closed_interval_touching_endpoints_collide
    """
    standing = validate_success(
        api.get_finish_run(chain_two_orders["fr1"], U.FINISH_TECH_HEADERS))
    assert standing["booth_hold_from"] == "2026-08-02T12:00:00Z"
    assert standing["booth_hold_until"] == "2026-08-16T16:00:00Z"

    F.set_clock(api, "2026-08-16T16:00:00Z")
    validate_error(api.create_finish_run({
        "build_order_id": chain_two_orders["bo2"],
        "booth_id": chain_two_orders["fb1"],
        "finish_system": "POLY", "coat_count": 3,
        "expected_build_order_version": chain_two_orders["bo2_v3"],
    }, U.FINISH_TECH_HEADERS), E.ERR_BOOTH_FINISH_INCOMPATIBLE, 409)


def test_an_hour_later_the_same_request_is_accepted(api, chain_two_orders):
    """
    One hour past the standing hold's last instant there is nothing to touch, so
    the identical polyurethane booking opens with its own projection and the
    booth still counts a single occupancy.

    PRD: "A proposed hold conflicts with an existing non-terminal finish run in
    the same booth when the proposed `booth_hold_from` is at or before that run's
    `booth_hold_until` and the proposed `booth_hold_until` is at or after that
    run's `booth_hold_from`."

    Design: Difficulty/boundary_precision_check/booth_hold_closed_interval_touching_endpoints_collide
    """
    F.set_clock(api, "2026-08-16T17:00:00Z")

    created = validate_success(api.create_finish_run({
        "build_order_id": chain_two_orders["bo2"],
        "booth_id": chain_two_orders["fb1"],
        "finish_system": "POLY", "coat_count": 3,
        "expected_build_order_version": chain_two_orders["bo2_v3"],
    }, U.FINISH_TECH_HEADERS), 201)
    assert created["status"] == "SPRAYING"
    assert created["booth_hold_from"] == "2026-08-16T17:00:00Z"
    assert created["booth_hold_until"] == "2026-08-19T21:00:00Z"
    assert created["cure_hours"] is None

    booth = validate_success(
        api.get_storage_room(chain_two_orders["fb1"], U.FINISH_TECH_HEADERS))
    assert booth["occupied_slots"] == 1


def a_quoted_custom_order_at_eight_hundred_eighty_six_thousand(api):
    """
    An endorser custom-shop order at 480000 cents carrying one approved artisan
    vine inlay at 130000 and one master top wood at 95000 still awaiting
    approval, still quoted, whose provisional total is 886185 cents. Both
    statuses sit inside the provisional input set, which is what makes the
    threshold land on an exact half cent.
    """
    env = X.build_clock(api)
    X.build_vine_option(api, env)
    env["optB"] = F.create_option(api, dict(C.OPTION_MASTER_TOP))["id"]
    X.build_custom_order(api, env)
    X.build_approved_vine_selection(api, env)
    X.read_order_version(api, env, "bo1", "bo_v2")
    env["sel2"] = F.create_selection(api, env["bo1"], env["optB"],
                                     env["bo_v2"], quantity=1,
                                     headers=U.COORDINATOR_HEADERS)["id"]
    return env


def test_a_deposit_one_cent_under_the_rounded_up_threshold_is_refused(api):
    """
    The threshold falls on an exact half cent and rounds up, so the deposit one
    cent below it is refused with the payment status and the order stays quoted
    with nothing collected.

    PRD: "The deposit itself must be at least ten percent of the provisional
    total: multiply `provisional_quote_total_cents` by 1000 basis points, divide
    by 10000, round half up, and require `deposit_cents` to be greater than or
    equal to that figure, otherwise `ERR_DEPOSIT_INSUFFICIENT` with HTTP 402."

    Design: Difficulty/boundary_precision_check/confirm_deposit_exactly_at_min_deposit_bp_threshold
    """
    env = a_quoted_custom_order_at_eight_hundred_eighty_six_thousand(api)

    quoted = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert quoted["provisional_quote_total_cents"] == 886185

    validate_error(api.confirm_build_order(env["bo1"], {"deposit_cents": 88618},
                                           U.COORDINATOR_HEADERS),
                   E.ERR_DEPOSIT_INSUFFICIENT, 402)

    after = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert after["commercial_status"] == "QUOTED"
    assert after["deposit_paid_cents"] == 0


def test_a_deposit_exactly_at_the_threshold_confirms_the_order(api):
    """
    One cent more, exactly on the rounded-up minimum, and the order confirms with
    the whole deposit both paid and held.

    PRD: "A successful confirmation adds `deposit_cents` to both
    `deposit_paid_cents` and `deposit_held_cents` and refreshes `priority_score`."

    Design: Difficulty/boundary_precision_check/confirm_deposit_exactly_at_min_deposit_bp_threshold
    """
    env = a_quoted_custom_order_at_eight_hundred_eighty_six_thousand(api)
    assert C.MIN_DEPOSIT_BP == 1000

    confirmed = validate_success(api.confirm_build_order(
        env["bo1"], {"deposit_cents": 88619}, U.COORDINATOR_HEADERS))
    assert confirmed["commercial_status"] == "CONFIRMED"
    assert confirmed["provisional_quote_total_cents"] == 886185
    assert confirmed["deposit_paid_cents"] == 88619
    assert confirmed["deposit_held_cents"] == 88619
