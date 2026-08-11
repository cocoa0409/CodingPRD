"""Instrument registration, the two status axes, pitch assessment and the tuning cycle."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_date_equals,
    assert_instrument,
    instrument_payload,
    make_move_coordinator_headers,
    new_client,
    new_instrument,
    new_location,
    read_instrument,
    run_daily_sweep,
    set_clock,
    setup_client_with_instrument,
    setup_instrument_with_dispatched_move_job,
    setup_order,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]
COORDINATOR = TEST_USERS["move_coordinator_headers"]


def test_instrument_read_with_unresolvable_id_is_not_found(api):
    """PRD 2.8: "**Instrument existence.** An `instrument_id` that does not resolve
    yields `ERR_INSTRUMENT_NOT_FOUND` (404)."

    Design: Corner/entities/instrument_get_with_unknown_id_returns_not_found
    """
    response = api.get_instrument("00000000-0000-4000-8000-000000000000", MANAGER)
    validate_error(response, ApiErrorId.ERR_INSTRUMENT_NOT_FOUND.value)


def test_duplicate_serial_number_is_refused(api):
    """PRD 2.8: "**Serial uniqueness.** `serial_number` must be unique across all
    instruments. Otherwise `ERR_DUPLICATE_SERIAL_NUMBER` (409). Applies to instrument
    creation."
    PRD 3.2: "A duplicate `serial_number` is refused with
    `ERR_DUPLICATE_SERIAL_NUMBER`, and a location owned by a different client is refused
    with `ERR_OWNERSHIP_MISMATCH`."

    Design: Corner/entities/instrument_duplicate_serial_number_rejected
    """
    base = setup_client_with_instrument()
    client, location = base["client"], base["location"]
    serial = base["instrument"]["serial_number"]

    response = api.create_instrument(
        instrument_payload(
            client["id"], location["id"], serial_number=serial,
            instrument_class="CONSOLE",
        ),
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_SERIAL_NUMBER.value)

    rows, _ = validate_paginated(
        api.list_instruments(MANAGER, params={"client_id": client["id"]})
    )
    assert len(rows) == 1, "the rejected create must not have added a second instrument"


def test_instrument_sited_at_another_clients_address_is_refused(api):
    """PRD 2.8: "**Address ownership.** On every operation that pairs a location with an
    instrument, the location's owning client must equal the instrument's owning client;
    additionally, an appointment's `location_id` must equal the instrument's
    `current_location_id`. Otherwise `ERR_OWNERSHIP_MISMATCH` (409)."
    PRD 3.2: "An instrument is registered against a `client_id` and a
    `current_location_id` that must belong to that same client, with a `make`, a
    `model`, a `serial_number` unique across every instrument in the system, an
    `instrument_class` of `UPRIGHT`, `CONSOLE`, `BABY_GRAND`, `GRAND` or
    `CONCERT_GRAND`, and a `usage_tier` of `HOME`, `STUDIO`, `INSTITUTIONAL` or
    `PERFORMANCE`."

    Design: Corner/entities/instrument_at_another_clients_location_returns_ownership_mismatch
    """
    owner_one = new_client()
    owner_two = new_client()
    other_address = new_location(owner_two["id"], label="Two Home")

    response = api.create_instrument(
        instrument_payload(owner_one["id"], other_address["id"], make="Kawai"), MANAGER
    )
    validate_error(response, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)


def test_instrument_create_with_unresolvable_location_is_not_found(api):
    """PRD 2.8: "**Location existence.** A `location_id`, `origin_location_id`,
    `destination_location_id` or `current_location_id` that does not resolve yields
    `ERR_LOCATION_NOT_FOUND` (404)."
    PRD 2.4: "Nested paths are validated left to right."

    Design: Corner/errors/instrument_create_with_unknown_location_returns_location_not_found
    """
    client = new_client()
    response = api.create_instrument(
        instrument_payload(client["id"], "00000000-0000-4000-8000-000000000002"), MANAGER
    )
    validate_error(response, ApiErrorId.ERR_LOCATION_NOT_FOUND.value)


def test_instrument_listing_paginates_with_total_count_and_has_more(api):
    """PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more`; `total_count` counts the rows matching the filters
    before pagination is applied, and `has_more` is true when rows remain beyond the
    returned page."

    Design: Corner/entities/instrument_list_is_paginated_with_total_count_and_has_more
    """
    base = setup_client_with_instrument()
    client, location = base["client"], base["location"]
    new_instrument(client["id"], location["id"], instrument_class="CONSOLE")
    new_instrument(client["id"], location["id"], instrument_class="GRAND")

    first_page, meta = validate_paginated(
        api.list_instruments(
            MANAGER, params={"client_id": client["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    second_page, meta2 = validate_paginated(
        api.list_instruments(
            MANAGER, params={"client_id": client["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert meta2["has_more"] is False


def test_pitch_assessment_against_the_wrong_reference_is_refused(api):
    """PRD 3.3: "The reference must equal the instrument's `target_pitch_hz`
    **exactly**; a technician who measured against a different standard is refused with
    `ERR_PITCH_REFERENCE_MISMATCH`, because a deviation measured against the wrong
    reference is not a deviation at all."
    PRD 2.8: "No state change is committed before the ladder completes, with exactly
    three deliberate exceptions described in §2.9."

    Design: Corner/validations/pitch_assessment_with_wrong_reference_pitch_is_rejected
    """
    base = setup_client_with_instrument(
        instrument_class="GRAND", usage_tier="PERFORMANCE", target_pitch_hz=442.0
    )
    instrument = base["instrument"]

    response = api.create_pitch_assessment(
        instrument["id"],
        {"reference_pitch_hz": 440.0, "measured_deviation_cents": 4.0},
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_PITCH_REFERENCE_MISMATCH.value)

    after = read_instrument(instrument["id"])
    assert after["pitch_deviation_cents"] is None
    assert after["pitch_raise_tier"] is None
    assert after["version"] == 1, "a rejected assessment writes nothing"


def test_overdue_recall_bumps_the_effective_pitch_tier(api):
    """PRD 3.3: "If the instrument has an outstanding tuning recall whose overdue
    banding has reached `OVERDUE_T2` or `LAPSED_TIER`, the tier is bumped up by one
    band, capped at `TIER_3`; otherwise it is not bumped at all."
    PRD 3.3: "Above 5.0 and up to and including 15.0 is `TIER_1`."
    PRD 3.4: "The `overdue_tier` bands that figure: 0 days is `ON_TIME`; 1 through 30
    days is `OVERDUE_T1`; 31 through 90 days is `OVERDUE_T2`; and 91 days or more is
    `LAPSED_TIER`."
    PRD 3.3: "The assessment also writes `planned_visit_count`, the number of visits a
    tuning needs at the effective tier: 1 visit at `TIER_0`, 1 at `TIER_1`, 1 at
    `TIER_2`, and 2 at `TIER_3`."

    Design: Corner/calculations/pitch_tier_overdue_bump_raises_the_effective_tier
    """
    base = setup_client_with_instrument(climate_controlled=False)
    instrument = base["instrument"]
    recall = validate_success(
        api.create_tuning_recall(
            {"instrument_id": instrument["id"], "cycle_start_date": "2026-01-15"},
            MANAGER,
        ),
        201,
    )
    set_clock("2026-07-05T00:00:00Z")
    run_daily_sweep()

    recalls, _ = validate_paginated(api.list_tuning_recalls(instrument["id"], MANAGER))
    governing = next(r for r in recalls if r["id"] == recall["id"])
    assert governing["days_overdue"] == 35
    assert governing["overdue_tier"] == "OVERDUE_T2"

    # PRD 4: "Creating a new resource answers 201 Created and returns the new
    # resource; every other successful operation answers 200 OK and returns the
    # affected resource."  The PRD declares no PitchAssessment entity -- 3.3
    # specifies the operation purely as writes onto the instrument's own fields
    # ("it is written verbatim into `pitch_deviation_cents`", "Every assessment
    # bumps the instrument's `version` by 1"), so the affected resource is the
    # instrument and the operation answers 200.
    validate_success(
        api.create_pitch_assessment(
            instrument["id"],
            {"reference_pitch_hz": 440.0, "measured_deviation_cents": -10.0},
            MANAGER,
        ),
        200,
    )

    after = read_instrument(instrument["id"])
    assert_instrument(after)
    assert after["pitch_deviation_cents"] == -10.0
    assert after["raw_pitch_tier"] == "TIER_1"
    assert after["pitch_raise_tier"] == "TIER_2", "the OVERDUE_T2 recall bumps one band"
    assert after["planned_visit_count"] == 1


def test_pitch_tier_conflict_keeps_the_already_committed_pitch_fields(api):
    """PRD 2.9: "At rung 46, recording a pitch assessment that would change the
    effective tier of an instrument with an in-flight `TUNE` order:
    `pitch_deviation_cents`, `raw_pitch_tier`, `pitch_raise_tier`,
    `planned_visit_count`, `updated_at` and `version` have **already** been written from
    the classification calculation. The response is `ERR_PITCH_TIER_CONFLICT` (409) and
    those pitch fields are **not** rolled back."
    PRD 3.3: "Above 15.0 and up to and including 35.0 is `TIER_2`."

    Design: Corner/endpoints/pitch_assessment_conflict_keeps_the_committed_pitch_fields
    """
    ctx = setup_order(
        service_type="TUNE", instrument_class="GRAND", deviation=2.0, condition=None,
        certification_level="APPRENTICE", start=True,
    )
    instrument = read_instrument(ctx["instrument"]["id"])
    version_before = instrument["version"]

    response = api.create_pitch_assessment(
        instrument["id"],
        {"reference_pitch_hz": 440.0, "measured_deviation_cents": 20.0},
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_PITCH_TIER_CONFLICT.value)

    after = read_instrument(instrument["id"])
    assert after["pitch_deviation_cents"] == 20.0, "the measurement is a fact of record"
    assert after["raw_pitch_tier"] == "TIER_2"
    assert after["pitch_raise_tier"] == "TIER_2"
    assert after["version"] == version_before + 1

    order = validate_success(api.get_service_order(ctx["order"]["id"], MANAGER))
    assert order["status"] == "IN_PROGRESS"
    assert order["estimated_minutes"] == 78, "the order's visit plan is untouched"


def test_tuning_cycle_interval_clamps_at_the_thirty_day_floor(api):
    """PRD 3.4: "First, a base interval is read off the `usage_tier`: 182 days for a
    `HOME` instrument, 120 for `STUDIO`, 91 for `INSTITUTIONAL`, and 45 for a
    `PERFORMANCE` instrument that is played hard and expected back roughly every six
    weeks."
    PRD 3.4: "The result is finally raised to a floor of 30 days, so no instrument is
    ever put on a cycle shorter than a month."
    PRD 3.4: "The floor of the product is taken **before** the class adjustment is
    added, and the 30-day minimum is applied **last**."
    PRD 3.4: "That figure is written both to the instrument's
    `tuning_cycle_interval_days` and, as a snapshot that never moves afterwards, to the
    recall's own `interval_days`."

    Design: Corner/calculations/tuning_cycle_interval_clamps_at_the_thirty_day_floor
    """
    base = setup_client_with_instrument(
        instrument_class="CONCERT_GRAND", usage_tier="PERFORMANCE",
        climate_controlled=False,
    )
    instrument = base["instrument"]

    recall = validate_success(
        api.create_tuning_recall(
            {"instrument_id": instrument["id"], "cycle_start_date": "2026-01-15"},
            MANAGER,
        ),
        201,
    )

    assert recall["interval_days"] == 30, (
        "floor(45 * 0.75) = 33, minus 21 for a CONCERT_GRAND = 12, raised to the 30 floor"
    )
    assert_date_equals(recall["due_date"], "2026-02-14", "TuningRecall.due_date")
    assert recall["status"] == "PENDING"
    assert recall["overdue_tier"] == "ON_TIME"
    assert read_instrument(instrument["id"])["tuning_cycle_interval_days"] == 30


def test_second_notify_on_a_notified_recall_is_invalid_state(api):
    """PRD 3.4: "A `ShopManager` marks the client notified, which moves it to
    `NOTIFIED`, stamps `notified_at` from the logical clock and bumps the recall's
    `version` by 1; this requires the instrument owner's client `status` to be `ACTIVE`."
    PRD 2.8: "**Edge exists.** The requested transition must exist as an edge from the
    resource's current state in its own machine. Otherwise `ERR_INVALID_STATE` (409)."
    PRD 3.4: "The recall's `due_date` is the `cycle_start_date` advanced by
    `interval_days` calendar days, honouring month lengths and leap days."

    Design: Corner/state_machines/tuning_recall_notify_twice_returns_invalid_state
    """
    base = setup_client_with_instrument(climate_controlled=False)
    instrument = base["instrument"]
    recall = validate_success(
        api.create_tuning_recall(
            {"instrument_id": instrument["id"], "cycle_start_date": "2026-01-15"},
            MANAGER,
        ),
        201,
    )
    validate_success(api.notify_tuning_recall(recall["id"], MANAGER))

    response = api.notify_tuning_recall(recall["id"], MANAGER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    recalls, _ = validate_paginated(api.list_tuning_recalls(instrument["id"], MANAGER))
    current = next(r for r in recalls if r["id"] == recall["id"])
    assert current["status"] == "NOTIFIED"
    assert current["interval_days"] == 136, "floor(182 * 0.75) with a 0 UPRIGHT adjustment"
    assert_date_equals(current["due_date"], "2026-05-31", "TuningRecall.due_date")


def test_custody_transitions_leave_the_condition_axis_untouched(api):
    """PRD 3.2: "Each instrument carries **two independent status axes** that advance on
    their own triggers while constraining one another."
    PRD 3.2: "Moving from `AT_CLIENT_SITE` into `IN_TRANSIT` is the pivotal edge: when
    `authorizing_move_job_id` is supplied it must name a move job for this instrument in
    status `DISPATCHED`, and that job advances `DISPATCHED → IN_TRANSIT`; when it is
    **omitted**, `unauthorized_move_flag` is set to true and Cascade A fires, voiding
    the instrument's warranties as described in §2.11."
    PRD 3.2: "From `IN_TRANSIT` the instrument reaches either `IN_SHOP` or
    `AT_CLIENT_SITE`; on both of those edges, when a job is quoted, the job advances
    `IN_TRANSIT → DELIVERED` and the instrument's `current_location_id` is set to that
    job's `destination_location_id`."

    Design: Difficulty/non_linear_state_machine/instrument_condition_and_custody_axes_advance_independently
    """
    ctx = setup_instrument_with_dispatched_move_job()
    instrument, job = ctx["instrument"], ctx["move_job"]
    assert instrument["condition_status"] == "SERVICEABLE"

    in_transit = validate_success(
        api.create_custody_transition(
            instrument["id"],
            {"to_custody_status": "IN_TRANSIT", "authorizing_move_job_id": job["id"]},
            COORDINATOR,
        )
    )
    assert in_transit["custody_status"] == "IN_TRANSIT"
    assert in_transit["condition_status"] == "SERVICEABLE"
    assert in_transit["unauthorized_move_flag"] is False, "the move was authorised"

    in_shop = validate_success(
        api.create_custody_transition(
            instrument["id"],
            {"to_custody_status": "IN_SHOP", "authorizing_move_job_id": job["id"]},
            COORDINATOR,
        )
    )
    assert in_shop["custody_status"] == "IN_SHOP"
    assert in_shop["condition_status"] == "SERVICEABLE"
    assert in_shop["current_location_id"] == ctx["shop_location"]["id"]

    delivered = validate_success(api.get_move_job(job["id"], MANAGER))
    assert delivered["status"] == "DELIVERED"


def test_condition_transition_leaves_the_custody_axis_untouched(api):
    """PRD 3.2: "Each instrument carries **two independent status axes** that advance on
    their own triggers while constraining one another."
    PRD 3.2: "Four of its edges are technician-driven and share one precondition — the
    instrument's `custody_status` must be `AT_CLIENT_SITE`, `IN_SHOP` or
    `SHOWROOM_FLOOR` — and each bumps the instrument's `version` by 1:
    `NEEDS_ASSESSMENT → NEEDS_REGULATION`, `NEEDS_ASSESSMENT → REBUILD_REQUIRED`,
    `SERVICEABLE → NEEDS_REGULATION`, and the re-entry edge `RESTORED → NEEDS_REGULATION`
    that makes the axis cyclic."

    Design: Difficulty/non_linear_state_machine/instrument_condition_and_custody_axes_advance_independently
    """
    ctx = setup_instrument_with_dispatched_move_job()
    instrument, job = ctx["instrument"], ctx["move_job"]
    coordinator = make_move_coordinator_headers("coord-axes-1")

    validate_success(
        api.create_custody_transition(
            instrument["id"],
            {"to_custody_status": "IN_TRANSIT", "authorizing_move_job_id": job["id"]},
            coordinator,
        )
    )
    validate_success(
        api.create_custody_transition(
            instrument["id"],
            {"to_custody_status": "IN_SHOP", "authorizing_move_job_id": job["id"]},
            coordinator,
        )
    )
    before = read_instrument(instrument["id"])

    after = validate_success(
        api.create_condition_transition(
            instrument["id"],
            {
                "to_condition_status": "NEEDS_REGULATION",
                "note": "action found tight after transport",
            },
            MANAGER,
        )
    )
    assert after["condition_status"] == "NEEDS_REGULATION"
    assert after["custody_status"] == "IN_SHOP", "the condition edge moves no custody"
    assert after["version"] == before["version"] + 1
