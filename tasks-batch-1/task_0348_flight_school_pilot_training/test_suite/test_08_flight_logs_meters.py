"""Flight-log posting claims: the strict meter-inequality boundary, the meter
continuity check, conservation of the aircraft Hobbs ledger, the void path, and
the enrollment hours rollup.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error,
    DISPATCHER,
    ApiErrorId,
    setup_dispatched_booking, setup_drafted_flight_log,
    create_draft_flight_log, get_flight_log, get_aircraft, get_enrollment, get_booking,
    create_booking,
    make_instructor_headers,
)


def test_post_flight_log_zero_duration_meter_rejected(api):
    """PRD §3.4: "The meter readings must be sane: `hobbs_end` must be strictly
    greater than `hobbs_start` and `tach_end` strictly greater than `tach_start`, or
    the post is rejected with `ERR_INVALID_METER_READING` (HTTP 400)."

    Design: Difficulty/boundary_precision_check/meter_zero_duration_flight_log_post_rejected
    """
    ctx = setup_dispatched_booking(deposit_cents=100000, lesson_type="DUAL",
                                   aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    instr_id = ctx["instructor"]["id"]
    # hobbs_end == hobbs_start (delta 0) violates the strict-inequality rule.
    fl = create_draft_flight_log(ctx["booking"]["id"], instr_id, 100.0, 100.0, 200.0, 200.0, 1)
    validate_error(api.post_flight_log(fl["id"], make_instructor_headers(instr_id)),
                   ApiErrorId.ERR_INVALID_METER_READING.value)
    assert get_flight_log(fl["id"])["status"] == "DRAFT"


def test_post_flight_log_minimal_positive_delta_accepted(api):
    """PRD §3.4: "`hobbs_end` must be strictly greater than `hobbs_start` and
    `tach_end` strictly greater than `tach_start`, or the post is rejected with
    `ERR_INVALID_METER_READING` (HTTP 400)."

    Design: Difficulty/boundary_precision_check/meter_zero_duration_flight_log_post_rejected
    """
    ctx = setup_dispatched_booking(deposit_cents=100000, lesson_type="DUAL",
                                   aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    instr_id = ctx["instructor"]["id"]
    # Strictly positive deltas (just above zero) satisfy the rule and post succeeds.
    fl = create_draft_flight_log(ctx["booking"]["id"], instr_id, 100.0, 100.1, 200.0, 200.1, 1)
    posted = validate_success(api.post_flight_log(fl["id"], make_instructor_headers(instr_id)))
    assert posted["status"] == "POSTED"


def test_post_flight_log_meter_discontinuity_rejected(api):
    """PRD §3.4: "The readings must also be continuous with the aircraft's live
    meters: `hobbs_start` must equal the aircraft's `current_hobbs` and `tach_start`
    must equal its `current_tach`, or the post is rejected with
    `ERR_METER_DISCONTINUITY`."

    Design: Corner/calculations/meter_discontinuity_post_rejected
    """
    ctx = setup_dispatched_booking(deposit_cents=100000, lesson_type="DUAL",
                                   aircraft_overrides={"rental_rate_cents_per_hour": 15000})
    instr_id = ctx["instructor"]["id"]
    # current_hobbs is 100.0; start at 105.0 leaves a gap.
    fl = create_draft_flight_log(ctx["booking"]["id"], instr_id, 105.0, 106.7, 200.0, 201.4, 1)
    validate_error(api.post_flight_log(fl["id"], make_instructor_headers(instr_id)),
                   ApiErrorId.ERR_METER_DISCONTINUITY.value)
    assert get_aircraft(ctx["aircraft"]["id"])["current_hobbs"] == 100.0
    assert get_flight_log(fl["id"])["status"] == "DRAFT"


def test_post_advances_hobbs_meter_by_exact_delta(api):
    """PRD §3.4: "It advances the aircraft's live meters, setting `current_hobbs` to
    `hobbs_end` and `current_tach` to `tach_end`, which increments the aircraft's
    `version` by one."
    PRD §3.4: "At any time the aircraft's `current_hobbs` equals its `initial_hobbs`
    plus the sum, over all of that aircraft's `POSTED` flight logs taken in
    chronological order of `created_at` ascending ... of each log's `hobbs_end` minus
    `hobbs_start`."

    Design: Difficulty/compensating_invariant/hobbs_meter_conservation_post_advances_exactly
    """
    base = setup_drafted_flight_log(
        deposit_cents=100000, lesson_type="DUAL",
        aircraft_overrides={"rental_rate_cents_per_hour": 15000, "billing_basis": "HOBBS",
                            "initial_hobbs": 100.0, "initial_tach": 200.0},
        hobbs_start=100.0, hobbs_end=101.7, tach_start=200.0, tach_end=201.4,
    )
    instr_id = base["instructor"]["id"]
    posted = get_success_data(api.post_flight_log(base["flight_log"]["id"], make_instructor_headers(instr_id)))
    assert posted["status"] == "POSTED"
    assert posted["billed_hours"] == 1.7
    aircraft = get_aircraft(base["aircraft"]["id"])
    assert aircraft["current_hobbs"] == 101.7   # 100.0 + (101.7 - 100.0)
    assert aircraft["current_tach"] == 201.4


def test_hobbs_conservation_across_two_posted_flights(api):
    """PRD §3.4: "At any time the aircraft's `current_hobbs` equals its
    `initial_hobbs` plus the sum, over all of that aircraft's `POSTED` flight logs
    taken in chronological order of `created_at` ascending (ties broken by
    `created_at` ascending), of each log's `hobbs_end` minus `hobbs_start`."

    Design: Difficulty/compensating_invariant/hobbs_meter_conservation_post_advances_exactly
    """
    # First flight: 100.0 -> 101.7 (delta 1.7).
    base = setup_drafted_flight_log(
        deposit_cents=200000, lesson_type="DUAL",
        aircraft_overrides={"rental_rate_cents_per_hour": 15000, "billing_basis": "HOBBS",
                            "initial_hobbs": 100.0, "initial_tach": 200.0},
        hobbs_start=100.0, hobbs_end=101.7, tach_start=200.0, tach_end=201.4,
    )
    instr_id = base["instructor"]["id"]
    get_success_data(api.post_flight_log(base["flight_log"]["id"], make_instructor_headers(instr_id)))
    assert get_aircraft(base["aircraft"]["id"])["current_hobbs"] == 101.7

    # Build a second dispatched booking against the same active enrollment + aircraft,
    # continuing from the live meters (101.7 / 201.4).
    bk2 = create_booking(
        base["enrollment"]["id"], base["aircraft"]["id"], "DUAL", 2.0,
        window=("2026-07-05T14:00:00.000Z", "2026-07-05T16:00:00.000Z"),
        instructor_id=base["instructor"]["id"],
    )
    api.confirm_booking(bk2["id"], DISPATCHER)
    api.dispatch_booking(bk2["id"], DISPATCHER)
    fl2 = create_draft_flight_log(bk2["id"], instr_id, 101.7, 103.0, 201.4, 202.5, 1)
    get_success_data(api.post_flight_log(fl2["id"], make_instructor_headers(instr_id)))
    # 100.0 + (101.7-100.0) + (103.0-101.7) == 103.0.
    assert get_aircraft(base["aircraft"]["id"])["current_hobbs"] == 103.0


def test_void_draft_flight_log_leaves_meters_untouched(api):
    """PRD §3.4: "A draft that is no longer wanted can instead be voided by a
    `Dispatcher`, moving it from `DRAFT` to `VOID`; the log must be `DRAFT`,
    otherwise `ERR_FLIGHT_LOG_NOT_DRAFT`. A `VOID` or `DRAFT` log contributes
    nothing to meters or hours."

    Design: Corner/endpoints/void_draft_flight_log_succeeds
    """
    base = setup_drafted_flight_log(
        deposit_cents=100000, lesson_type="DUAL",
        aircraft_overrides={"rental_rate_cents_per_hour": 15000, "initial_hobbs": 100.0, "initial_tach": 200.0},
        hobbs_start=100.0, hobbs_end=101.7, tach_start=200.0, tach_end=201.4,
    )
    voided = validate_success(api.void_flight_log(base["flight_log"]["id"], DISPATCHER))
    assert voided["status"] == "VOID"
    assert get_aircraft(base["aircraft"]["id"])["current_hobbs"] == 100.0


def test_post_rolls_dual_hours_into_enrollment(api):
    """PRD §3.4: "It rolls the flight's `billed_hours` into the enrollment — into
    `logged_dual_hours` when the booking's `lesson_type` is `DUAL`, or into
    `logged_solo_hours` when it is `SOLO`. And it cascades the underlying booking
    from `DISPATCHED` to `COMPLETED`."

    Design: Corner/state_machines/enrollment_hours_rollup_after_post
    """
    base = setup_drafted_flight_log(
        deposit_cents=100000, lesson_type="DUAL",
        aircraft_overrides={"rental_rate_cents_per_hour": 15000, "initial_hobbs": 100.0, "initial_tach": 200.0},
        hobbs_start=100.0, hobbs_end=101.7, tach_start=200.0, tach_end=201.4,
    )
    instr_id = base["instructor"]["id"]
    get_success_data(api.post_flight_log(base["flight_log"]["id"], make_instructor_headers(instr_id)))
    enr = get_enrollment(base["enrollment"]["id"])
    assert enr["logged_dual_hours"] == 1.7
    assert enr["logged_solo_hours"] == 0
    assert get_booking(base["booking"]["id"])["status"] == "COMPLETED"
