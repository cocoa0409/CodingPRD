"""Drought observations, the destock cascade and elected early removal."""

from test_helpers import (
    ApiErrorId,
    assert_drought_reading,
    assert_same_calendar_date,
    create_lot,
    file_drought_reading,
    make_cattle_owner_headers,
    make_grazier_headers,
    make_range_consultant_headers,
    provision_active_contract,
    read_contract,
    read_lot,
    read_pasture,
    setup_north_bench_available,
    setup_north_bench_lot_on_feed,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# The persistence trigger: two consecutive severe readings
# ===========================================================================

def test_a_single_severe_reading_counts_the_run_but_orders_no_destock(api):
    """PRD 3.8: "Taking the pasture's readings from newest `reading_date` backwards —
    with the later-created row first where two share a date, and beginning with the row
    just written — the system counts the unbroken leading run of readings whose
    `drought_index` is at least 3, stopping at the first reading below 3, and stores
    that count on the new row as `consecutive_severe_count`. A run of at least 2 orders
    a destock: one reading at index 3 is weather, two in a row is a drought."
    PRD 3.8: "The new row's `triggered_destock` flag is true only when the pasture's
    `drought_destock_flag` was false before the reading and one of those two conditions
    is met; in that case the pasture's `drought_destock_flag` is set true and the row's
    flag records that this reading is the one that flipped it."

    Design: Difficulty/boundary_precision_check/drought_index_three_triggers_only_on_the_second_consecutive_reading
    """
    world = setup_north_bench_available()

    resp = api.create_drought_reading(
        world.pasture_id,
        {"reading_date": "2026-09-01", "drought_index": 3, "forage_remaining_pct": 45},
        make_range_consultant_headers(world.consultant_id),
    )
    reading = validate_success(resp, 201)
    assert_drought_reading(reading)

    assert reading["consecutive_severe_count"] == 1
    assert reading["triggered_destock"] is False

    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["drought_destock_flag"] is False
    assert pasture["grazing_posture"] == "OPEN"


def test_an_intervening_mild_reading_resets_the_run_before_the_pair_triggers(api):
    """PRD 3.8: "A run of at least 2 orders a destock: one reading at index 3 is
    weather, two in a row is a drought. An intervening reading at index 2 breaks the run
    and the count starts over."
    PRD 3.8: "Setting the flag sets off the destock cascade. The pasture's
    `grazing_posture` becomes `DESTOCK_ORDERED`."

    Design: Difficulty/boundary_precision_check/drought_index_three_triggers_only_on_the_second_consecutive_reading
    """
    world = setup_north_bench_available()

    first = file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-01", drought_index=3, forage_remaining_pct=45,
    )
    second = file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-05", drought_index=2, forage_remaining_pct=40,
    )
    third = file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-10", drought_index=3, forage_remaining_pct=35,
    )
    fourth = file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-14", drought_index=3, forage_remaining_pct=30,
    )

    assert (first["consecutive_severe_count"], first["triggered_destock"]) == (1, False)
    assert (second["consecutive_severe_count"], second["triggered_destock"]) == (0, False)
    assert (third["consecutive_severe_count"], third["triggered_destock"]) == (1, False)
    assert (fourth["consecutive_severe_count"], fourth["triggered_destock"]) == (2, True)

    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["drought_destock_flag"] is True
    assert pasture["grazing_posture"] == "DESTOCK_ORDERED"


# ===========================================================================
# The destock cascade: reading to pasture to contract to lot
# ===========================================================================

def test_the_second_severe_reading_flips_the_pasture_into_destock_ordered(api):
    """PRD 3.8: "The new row's `triggered_destock` flag is true only when the pasture's
    `drought_destock_flag` was false before the reading and one of those two conditions
    is met; in that case the pasture's `drought_destock_flag` is set true and the row's
    flag records that this reading is the one that flipped it."
    PRD 3.8: "Setting the flag sets off the destock cascade. The pasture's
    `grazing_posture` becomes `DESTOCK_ORDERED`."

    Design: Difficulty/transitive_cascade/drought_reading_destock_cascade_reading_to_pasture_to_contract_to_lot
    """
    world = setup_north_bench_lot_on_feed()
    create_lot(
        world.contract_id, world.grazier_id,
        scheduled_head_count=20, scheduled_delivery_date="2026-09-20",
    )
    first = file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-01", drought_index=3, forage_remaining_pct=45,
    )
    assert first["consecutive_severe_count"] == 1
    assert first["triggered_destock"] is False

    resp = api.create_drought_reading(
        world.pasture_id,
        {"reading_date": "2026-09-15", "drought_index": 3, "forage_remaining_pct": 38},
        make_range_consultant_headers(world.consultant_id),
    )
    second = validate_success(resp, 201)

    assert second["consecutive_severe_count"] == 2
    assert second["triggered_destock"] is True

    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["drought_destock_flag"] is True
    assert pasture["grazing_posture"] == "DESTOCK_ORDERED"


def test_the_destock_order_reaches_the_contract_and_both_of_its_lots(api):
    """PRD 3.8: "Every contract on that pasture whose `lifecycle_status` is `ACTIVE`
    moves to `EARLY_REMOVAL_PENDING` with `early_removal_reason` set to `DROUGHT` and
    `early_removal_effective_date` set to the reading's `reading_date` plus the 15-day
    notice period the platform gives owners to arrange trucks; the system cascade moves
    every such contract regardless of whether any cattle are actually on the ground
    under it."
    PRD 3.8: "Every lot on those contracts sitting in `ON_FEED` moves to
    `REMOVAL_SCHEDULED` and takes `scheduled_removal_date` from the contract's effective
    date, and every lot still in `SCHEDULED` is held at `RECEIVING_HELD`."

    Design: Difficulty/transitive_cascade/drought_reading_destock_cascade_reading_to_pasture_to_contract_to_lot
    """
    world = setup_north_bench_lot_on_feed()
    held_lot = create_lot(
        world.contract_id, world.grazier_id,
        scheduled_head_count=20, scheduled_delivery_date="2026-09-20",
    )
    file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-01", drought_index=3, forage_remaining_pct=45,
    )
    file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-15", drought_index=3, forage_remaining_pct=38,
    )

    contract = read_contract(world.contract_id, world.grazier_id)
    assert contract["lifecycle_status"] == "EARLY_REMOVAL_PENDING"
    assert contract["early_removal_reason"] == "DROUGHT"
    assert_same_calendar_date(
        contract["early_removal_effective_date"], "2026-09-30",
        "GrazingContract.early_removal_effective_date",
    )

    on_feed_lot = read_lot(world.lot_id, world.grazier_id)
    assert on_feed_lot["status"] == "REMOVAL_SCHEDULED"
    assert_same_calendar_date(
        on_feed_lot["scheduled_removal_date"], "2026-09-30",
        "CattleLot.scheduled_removal_date",
    )
    assert read_lot(held_lot["id"], world.grazier_id)["status"] == "RECEIVING_HELD"


# ===========================================================================
# The forage floor and the recovery reading
# ===========================================================================

def test_the_twenty_percent_forage_floor_triggers_on_a_single_reading(api):
    """PRD 3.8: "The second condition is severity of forage: a single reading whose
    `forage_remaining_pct` is 20 or less orders a destock on its own, whatever the index
    and whatever the run length. The boundary is exact — 20.00 percent triggers, 20.01
    percent does not."
    PRD 3.8: "Setting the flag sets off the destock cascade. The pasture's
    `grazing_posture` becomes `DESTOCK_ORDERED`."

    Design: Corner/calculations/forage_floor_of_twenty_percent_orders_a_destock_on_one_reading
    """
    world = setup_north_bench_available()

    above = file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-01", drought_index=1, forage_remaining_pct=20.5,
    )
    assert above["consecutive_severe_count"] == 0
    assert above["triggered_destock"] is False
    assert read_pasture(world.pasture_id, world.grazier_id)["drought_destock_flag"] is False

    at_floor = file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-08", drought_index=1, forage_remaining_pct=20,
    )
    assert at_floor["consecutive_severe_count"] == 0
    assert at_floor["triggered_destock"] is True

    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["drought_destock_flag"] is True
    assert pasture["grazing_posture"] == "DESTOCK_ORDERED"


def test_a_recovery_reading_clears_the_flag_but_not_the_removal_order(api):
    """PRD 3.8: "Recovery runs the other way: if the flag is currently true and the new
    reading shows a `drought_index` of 1 or less *and* a `forage_remaining_pct` strictly
    greater than 20, the flag clears."
    PRD 3.8: "A recovery reading unwinds only the posture side: the flag clears, the
    posture returns to `OPEN` if nothing else is holding it down, and `RECEIVING_HELD`
    lots go back to `SCHEDULED`. Contracts already moved to `EARLY_REMOVAL_PENDING` stay
    there — a destock order, once given, is not rescinded by rain."

    Design: Corner/state_machines/drought_recovery_reading_clears_the_flag_and_releases_held_lots
    """
    world = setup_north_bench_available()
    world.contract = provision_active_contract(world, world.pasture_id)
    world.contract_id = world.contract["id"]
    lot = create_lot(
        world.contract_id, world.grazier_id,
        scheduled_head_count=150, scheduled_delivery_date="2026-08-10",
    )
    file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-01", drought_index=4, forage_remaining_pct=30,
    )
    triggering = file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-09-08", drought_index=4, forage_remaining_pct=26,
    )
    assert triggering["triggered_destock"] is True

    recovery = file_drought_reading(
        world.pasture_id, world.consultant_id,
        reading_date="2026-10-05", drought_index=1, forage_remaining_pct=55,
    )
    assert recovery["consecutive_severe_count"] == 0
    assert recovery["triggered_destock"] is False

    pasture = read_pasture(world.pasture_id, world.grazier_id)
    assert pasture["drought_destock_flag"] is False
    assert pasture["grazing_posture"] == "OPEN"
    assert read_lot(lot["id"], world.grazier_id)["status"] == "SCHEDULED"
    assert read_contract(world.contract_id, world.grazier_id)["lifecycle_status"] == (
        "EARLY_REMOVAL_PENDING"
    ), "A destock order once given is not rescinded by rain"

    _, meta = validate_paginated(
        api.list_drought_readings(world.pasture_id, make_grazier_headers(world.grazier_id))
    )
    assert meta["total_count"] == 3


# ===========================================================================
# Elected early removal
# ===========================================================================

def test_an_owner_election_short_of_the_minimum_stay_is_refused(api):
    """PRD 3.8: "An owner-elected removal must respect the minimum stay the owner
    guaranteed: the whole days from the lot's `in_date` to the requested
    `effective_date` must be at least the contract's `min_days`, or the request is
    refused with `ERR_MIN_DAYS_NOT_MET`."

    Design: Corner/validations/owner_elected_removal_before_min_days_returns_min_days_not_met
    """
    world = setup_north_bench_lot_on_feed()

    resp = api.early_removal(
        world.contract_id,
        {"reason": "OWNER_ELECTED", "effective_date": "2026-09-30"},
        make_cattle_owner_headers(world.owner_id),
    )
    validate_error(resp, ApiErrorId.ERR_MIN_DAYS_NOT_MET.value, 422)

    contract = read_contract(world.contract_id, world.grazier_id)
    assert contract["lifecycle_status"] == "ACTIVE"
    assert contract.get("early_removal_reason") is None
    assert read_lot(world.lot_id, world.grazier_id)["status"] == "ON_FEED"


def test_a_grazier_may_not_submit_an_owner_elected_removal(api):
    """PRD 3.8: "The reason must match the acting role: a `CattleOwner` may only submit
    `OWNER_ELECTED` and a `Grazier` may only submit `GRAZIER_ELECTED`, and a mismatch is
    refused with `ERR_EARLY_REMOVAL_NOT_PERMITTED`."
    PRD 3.8: "An owner-elected removal must respect the minimum stay the owner
    guaranteed: the whole days from the lot's `in_date` to the requested
    `effective_date` must be at least the contract's `min_days`, or the request is
    refused with `ERR_MIN_DAYS_NOT_MET`."

    Design: Corner/validations/grazier_submitting_owner_elected_reason_is_not_permitted
    """
    world = setup_north_bench_lot_on_feed()

    resp = api.early_removal(
        world.contract_id,
        {"reason": "OWNER_ELECTED", "effective_date": "2026-10-15"},
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_EARLY_REMOVAL_NOT_PERMITTED.value, 409)

    assert read_contract(world.contract_id, world.grazier_id)["lifecycle_status"] == "ACTIVE"
