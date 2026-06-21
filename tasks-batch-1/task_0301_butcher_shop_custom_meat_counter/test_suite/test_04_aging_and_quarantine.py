"""Dry-aging and the food-safety quarantine cascade: the temp-excursion depth-3
cascade, aging-day boundary, locker aggregate capacity, cross-entity draw/lot
dependency, and the release compensation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_cut_type,
    create_locker,
    create_customer,
    receive_lot,
    start_aging,
    set_clock,
    setup_aging_lot,
    setup_quarantined_locker_with_held_lot,
    place_and_confirm_order,
    ensure_pricing_policy,
    create_temp_reading_payload,
    ApiErrorId,
    TEST_USERS,
)

MGR = TEST_USERS["shift_manager_headers"]
CLERK = TEST_USERS["counter_clerk_headers"]
BUTCHER = TEST_USERS["butcher_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


# ===========================================================================
# Difficulty: transitive_cascade / temp_excursion_quarantine_holds_aging_lot_blocks_completion
# ===========================================================================
def test_temp_excursion_quarantines_and_holds_lot(api):
    """PRD §3.3: "It drives the locker `OPERATIONAL → QUARANTINED`, sets the
    locker's `last_excursion_at` to that reading's `reading_at`, and sets the
    reading's `triggered_quarantine` to true."
    PRD §3.3: "every `InventoryLot` whose `locker_id` is this locker and whose
    `lot_status` is `AGING` is transitioned `AGING → ON_HOLD` in the same operation".

    Design: Difficulty/transitive_cascade/temp_excursion_quarantine_holds_aging_lot_blocks_completion
    """
    base = setup_aging_lot(locker_overrides={"name": "LOCKER-A", "capacity_g": 20000},
                           received_weight_g=5000, aging_target_days=7)
    reading = validate_success(
        api.create_temp_reading(base["locker"]["id"],
                                create_temp_reading_payload(temp_c=9.5,
                                                            reading_at="2026-06-02T00:00:00Z"),
                                SAFETY),
        expected_status=201,
    )
    assert reading["triggered_quarantine"] is True
    locker = get_success_data(api.get_locker(base["locker"]["id"], MGR))
    assert locker["locker_status"] == "QUARANTINED"
    lot = get_success_data(api.get_inventory_lot(base["lot"]["id"], BUTCHER))
    assert lot["lot_status"] == "ON_HOLD"


def test_complete_aging_on_quarantined_locker_rejected(api):
    """PRD §3.2: "The lot's locker must be `OPERATIONAL` — completing aging on a
    lot whose locker is quarantined is rejected with `ERR_LOCKER_QUARANTINED`
    (HTTP 409)."

    After the excursion holds the lot, complete-aging at/after target days is still
    rejected because the locker is quarantined.

    Design: Difficulty/transitive_cascade/temp_excursion_quarantine_holds_aging_lot_blocks_completion
    """
    held = setup_quarantined_locker_with_held_lot(
        locker_overrides={"name": "LOCKER-A2", "capacity_g": 20000},
        received_weight_g=5000, aging_target_days=7,
        excursion_temp_c=9.5, reading_at="2026-06-02T00:00:00Z",
        aging_started_iso="2026-06-01T00:00:00Z",
    )
    set_clock("2026-06-08T00:00:00Z")  # 7 days elapsed
    resp = api.complete_aging(held["lot"]["id"], BUTCHER)
    validate_error(resp, ApiErrorId.ERR_LOCKER_QUARANTINED.value)


# ===========================================================================
# Difficulty: boundary_precision_check / aging_completion_day_boundary
# ===========================================================================
def test_aging_completes_at_exact_target_day(api):
    """PRD §3.2: "the number of whole days between `aging_started_at` and the
    current clock must be at least the lot's `aging_target_days`".
    PRD §3.2: "On success the server clears the lot's `locker_id`".

    Started 06-01, target 7, clock 06-08 (exactly 7 days) -> completes, locker
    cleared, lot AVAILABLE.

    Design: Difficulty/boundary_precision_check/aging_completion_day_boundary
    """
    setup_aging_lot(cut_overrides={"code": "DRY_RIBEYE"},
                    locker_overrides={"name": "LOCKER-C", "capacity_g": 20000},
                    received_weight_g=5000, aging_target_days=7,
                    aging_started_iso="2026-06-01T00:00:00Z")
    # The fixture set the clock to the start instant; advance to exactly target.
    aging = api.list_inventory_lots(BUTCHER, params={"lot_status": "AGING"}).json()["data"]
    lot_id = aging[0]["id"]
    set_clock("2026-06-08T00:00:00Z")
    completed = validate_success(api.complete_aging(lot_id, BUTCHER))
    assert completed["lot_status"] == "AVAILABLE"
    assert completed["locker_id"] is None


def test_aging_one_day_short_rejected(api):
    """PRD §3.2: "if too little time has passed the request is rejected with
    `ERR_AGING_NOT_COMPLETE` (HTTP 409)."

    Started 06-01, target 7, clock 06-07 (6 days < 7) -> ERR_AGING_NOT_COMPLETE.

    Design: Difficulty/boundary_precision_check/aging_completion_day_boundary
    """
    setup_aging_lot(cut_overrides={"code": "DRY_RIBEYE"},
                    locker_overrides={"name": "LOCKER-C2", "capacity_g": 20000},
                    received_weight_g=5000, aging_target_days=7,
                    aging_started_iso="2026-06-01T00:00:00Z")
    aging = api.list_inventory_lots(BUTCHER, params={"lot_status": "AGING"}).json()["data"]
    lot_id = aging[0]["id"]
    set_clock("2026-06-07T00:00:00Z")
    resp = api.complete_aging(lot_id, BUTCHER)
    validate_error(resp, ApiErrorId.ERR_AGING_NOT_COMPLETE.value)


# ===========================================================================
# Difficulty: resource_temporal_overlap / locker_capacity_aggregate_buffer_overlap
# ===========================================================================
def test_locker_capacity_aggregate_overflow_rejected(api):
    """PRD §3.2: "the locker's current `occupied_g` plus the lot's
    `received_weight_g` must be less than or equal to the locker's `capacity_g` ...
    If that capacity check fails, the request is rejected with
    `ERR_LOCKER_OVER_CAPACITY` (HTTP 409)."

    Locker cap 10000, occupied 6000 (one AGING lot); a second 5000g lot -> 11000 >
    10000 -> rejected.

    Design: Difficulty/resource_temporal_overlap/locker_capacity_aggregate_buffer_overlap
    """
    cut = create_cut_type(code="DRY_RIBEYE", species="BEEF",
                          base_price_cents_per_kg=6000, requires_dry_age=True)
    locker = create_locker(name="LOCKER-F", capacity_g=10000)
    lot_a = receive_lot(cut["id"], received_weight_g=6000, aging_target_days=7)
    start_aging(lot_a["id"], locker["id"])
    lot_b = receive_lot(cut["id"], received_weight_g=5000, aging_target_days=7)
    resp = api.start_aging(lot_b["id"], {"locker_id": locker["id"]}, BUTCHER)
    validate_error(resp, ApiErrorId.ERR_LOCKER_OVER_CAPACITY.value)


def test_locker_capacity_inclusive_at_equality(api):
    """PRD §3.2: "a check that is inclusive at equality, so a lot that exactly
    fills the remaining space is accepted."
    PRD §3.2: "On success the server sets the lot's `locker_id` to the target
    locker ... and recomputes the locker's `occupied_g` by adding the lot's
    `received_weight_g`."

    Locker cap 10000, occupied 6000; a 4000g lot -> 10000 == 10000 -> accepted,
    occupied_g becomes 10000.

    Design: Difficulty/resource_temporal_overlap/locker_capacity_aggregate_buffer_overlap
    """
    cut = create_cut_type(code="DRY_RIBEYE", species="BEEF",
                          base_price_cents_per_kg=6000, requires_dry_age=True)
    locker = create_locker(name="LOCKER-F2", capacity_g=10000)
    lot_a = receive_lot(cut["id"], received_weight_g=6000, aging_target_days=7)
    start_aging(lot_a["id"], locker["id"])
    lot_b = receive_lot(cut["id"], received_weight_g=4000, aging_target_days=7)
    aged = validate_success(api.start_aging(lot_b["id"], {"locker_id": locker["id"]}, BUTCHER))
    assert aged["lot_status"] == "AGING"
    locker_after = get_success_data(api.get_locker(locker["id"], MGR))
    assert locker_after["occupied_g"] == 10000


# ===========================================================================
# Difficulty: cross_entity_state_dependency / orderline_draw_requires_lot_available
# ===========================================================================
def test_draw_against_aging_lot_rejected(api):
    """PRD §3.5: "the lot must be `AVAILABLE` — drawing from a lot that is
    `AGING`, `ON_HOLD`, `DEPLETED`, or `DISCARDED` is rejected with
    `ERR_LOT_NOT_AVAILABLE` (HTTP 409)".

    An OrderLine draw against an AGING lot is rejected -> the line's valid
    transition depends on the lot's state.

    Design: Difficulty/cross_entity_state_dependency/orderline_draw_requires_lot_available
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="DRY_RIBEYE", species="BEEF",
                          base_price_cents_per_kg=6000, requires_dry_age=True)
    locker = create_locker(name="LOCKER-D", capacity_g=20000)
    cust = create_customer(full_name="Quinn Cross", phone="555-0011")
    lot = receive_lot(cut["id"], received_weight_g=1000, aging_target_days=7)
    aged = start_aging(lot["id"], locker["id"])
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 500)])
    resp = api.draw_line(
        line_ids[0],
        {"drawn_lot_id": lot["id"], "catch_weight_g": 500,
         "expected_inventory_lot_version": aged["version"]},
        BUTCHER,
    )
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_AVAILABLE.value)


def test_draw_against_available_lot_succeeds(api):
    """PRD §3.5: "the lot must be `AVAILABLE`" and on a successful draw "records the
    line's `catch_weight_g` and `drawn_lot_id`, computes the line's
    `final_line_cents` by the final variant".

    The same draw against an AVAILABLE (never-aged) lot succeeds, confirming the
    rejection above is driven specifically by the lot's non-AVAILABLE state.

    Design: Difficulty/cross_entity_state_dependency/orderline_draw_requires_lot_available
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="DRY_RIBEYE", species="BEEF",
                          base_price_cents_per_kg=6000, requires_dry_age=True)
    cust = create_customer(full_name="Quinn Available", phone="555-0021")
    lot = receive_lot(cut["id"], received_weight_g=1000)
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 500)])
    drawn = validate_success(
        api.draw_line(line_ids[0],
                      {"drawn_lot_id": lot["id"], "catch_weight_g": 500,
                       "expected_inventory_lot_version": lot["version"]}, BUTCHER)
    )
    assert drawn["line_status"] == "DRAWN"
    assert drawn["drawn_lot_id"] == lot["id"]


# ===========================================================================
# Corner: state_machines / locker_release_resumes_held_lots
# ===========================================================================
def test_release_locker_resumes_held_lots(api):
    """PRD §3.3: "On success the locker transitions `QUARANTINED → OPERATIONAL`,
    its `version` is incremented by one, and the release cascades to its contents:
    every `InventoryLot` whose `locker_id` is this locker and whose `lot_status` is
    `ON_HOLD` is transitioned `ON_HOLD → AGING`."

    Design: Corner/state_machines/locker_release_resumes_held_lots
    """
    held = setup_quarantined_locker_with_held_lot(
        cut_overrides={"code": "DRY_RIBEYE"},
        locker_overrides={"name": "LOCKER-REL", "capacity_g": 20000},
        received_weight_g=5000, aging_target_days=7,
        excursion_temp_c=10.0, reading_at="2026-06-02T00:00:00Z",
    )
    locker = held["locker"]
    released = validate_success(
        api.release_locker(locker["id"],
                           {"expected_dry_age_locker_version": locker["version"]}, MGR)
    )
    assert released["locker_status"] == "OPERATIONAL"
    lot_after = get_success_data(api.get_inventory_lot(held["lot"]["id"], BUTCHER))
    assert lot_after["lot_status"] == "AGING"


# ===========================================================================
# Corner: validations / aging_not_complete_before_target_days
# ===========================================================================
def test_aging_not_complete_before_target(api):
    """PRD §3.2: "if too little time has passed the request is rejected with
    `ERR_AGING_NOT_COMPLETE` (HTTP 409)."

    Started 06-01, target 7, clock 06-07 (6 days) -> ERR_AGING_NOT_COMPLETE.

    Design: Corner/validations/aging_not_complete_before_target_days
    """
    setup_aging_lot(cut_overrides={"code": "DRY_RIBEYE"},
                    locker_overrides={"name": "LOCKER-EARLY", "capacity_g": 20000},
                    received_weight_g=5000, aging_target_days=7,
                    aging_started_iso="2026-06-01T00:00:00Z")
    aging = api.list_inventory_lots(BUTCHER, params={"lot_status": "AGING"}).json()["data"]
    set_clock("2026-06-07T00:00:00Z")
    resp = api.complete_aging(aging[0]["id"], BUTCHER)
    validate_error(resp, ApiErrorId.ERR_AGING_NOT_COMPLETE.value)


# ===========================================================================
# Corner: entities / tempreading_immutable_no_version_field
# ===========================================================================
def test_temp_reading_in_band_no_version_field(api):
    """PRD §2.4: "a `TempReading` has only `id` and `created_at` among the system
    fields."
    PRD §3.3: "The server computes `in_band`, which is true exactly when the
    measured temperature is greater than or equal to the locker's `min_temp_c` and
    less than or equal to its `max_temp_c`".

    An in-band reading (2.0 within [0,4]) has in_band true, triggered_quarantine
    false, and carries no version/updated_at.

    Design: Corner/entities/tempreading_immutable_no_version_field
    """
    locker = create_locker(name="LOCKER-IMM", capacity_g=10000)
    reading = validate_success(
        api.create_temp_reading(locker["id"],
                                create_temp_reading_payload(temp_c=2.0,
                                                            reading_at="2026-06-02T00:00:00Z"),
                                SAFETY),
        expected_status=201,
    )
    assert reading["in_band"] is True
    assert reading["triggered_quarantine"] is False
    assert "version" not in reading, "TempReading must not carry a version field"
    assert "updated_at" not in reading, "TempReading must not carry updated_at"
