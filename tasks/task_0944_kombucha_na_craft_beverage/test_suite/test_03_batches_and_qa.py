"""Pitching a batch, the QA log, and the two independent batch axes."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_abv,
    assert_batch,
    assert_liters,
    assert_qa_reading,
    assert_same_instant,
    build_at_risk_batch,
    create_batch_payload,
    create_ingredient_lot_payload,
    create_ingredient_use_payload,
    create_qa_reading_payload,
    new_culture,
    new_ingredient_lot,
    new_recipe,
    new_sanitized_vessel,
    pitch_batch,
    read_batch,
    read_culture,
    read_vessel,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

OPERATOR = TEST_USERS["production_operator_headers"]
QA = TEST_USERS["qa_manager_headers"]


def test_an_undeclared_ingredient_type_is_refused(api):
    """PRD 2.9: "Every enum-typed field carries one of the members declared for it, on
    every endpoint — otherwise `ERR_VALIDATION` (400)."
    PRD 3.4: "A lot carries an `ingredient_type` drawn from `TEA`, `SUGAR`,
    `CULTURE_NUTRIENT`, `JUICE`, `BOTANICAL` and `HOPS`, the supplier's printed
    `supplier_lot_code`, a `received_on_date`, an `expiry_date`, and
    `quantity_received` expressed in the material's native unit — kilograms for
    solids, liters for liquids."

    Design: Corner/entities/ingredient_type_outside_the_declared_enum_is_refused
    """
    payload = create_ingredient_lot_payload(
        ingredient_type="COFFEE", supplier_lot_code="X-1", quantity_received=10.0
    )
    validate_error(
        api.create_ingredient_lot(payload, OPERATOR), ApiErrorId.ERR_VALIDATION.value, 400
    )


def test_a_new_batch_opens_on_f1_active_and_pending_with_a_nine_day_occupancy(api):
    """PRD 3.4: "On success the batch is born with `ferment_stage` `F1_ACTIVE` and
    `qa_disposition` `PENDING`, the two axes it will advance along independently."
    PRD 3.4: "`pitched_at` is stamped, `recipe_version_number_at_pitch` captures the
    recipe's `recipe_version_number` as it stands at that moment, `remaining_liters`
    is set to `pitched_liters` while `drawn_liters` and `loss_liters` both start at 0,
    and `occupancy_end_at` is computed as `pitched_at` plus the recipe's
    `planned_f1_days` and this batch's `planned_f2_days`, added as whole days."

    Design: Corner/state_machines/a_new_batch_starts_in_f1_active_with_a_pending_disposition
    """
    recipe = new_recipe(api, planned_f1_days=6)
    culture = new_culture(api, "Mother S")
    vessel = new_sanitized_vessel(api, code="FV-20", capacity_liters=500.0)

    batch = validate_success(
        api.create_batch(
            create_batch_payload(
                recipe["id"], culture["id"], vessel["id"], batch_code="B-20001",
                pitched_liters=450.0, planned_f2_days=3,
            ),
            OPERATOR,
        ),
        201,
    )

    assert_batch(batch)
    assert batch["ferment_stage"] == "F1_ACTIVE"
    assert batch["qa_disposition"] == "PENDING"
    assert_same_instant(batch["pitched_at"], "2026-05-01T00:00:00.000Z", "pitched_at")
    assert_same_instant(
        batch["occupancy_end_at"], "2026-05-10T00:00:00.000Z", "occupancy_end_at"
    )
    assert_liters(batch["remaining_liters"], 450.0, "remaining_liters at pitch")
    assert batch["flagged_reading_count"] == 0

    assert read_vessel(api, vessel["id"])["state"] == "OCCUPIED"
    culture_after = read_culture(api, culture["id"])
    assert culture_after["pitch_count"] == 1
    assert culture_after["vitality_score"] == 94


def test_the_pitch_response_is_immediately_visible_on_the_vessel_and_the_culture(api):
    """PRD 3.3: "Occupancy is an interval, not a flag. When a batch is pitched into a
    vessel the vessel moves `SANITIZED → OCCUPIED`, `current_batch_id` mirrors the new
    batch, `occupancy_start_at` takes the batch's pitch instant as an **inclusive**
    start, and `occupancy_end_at` takes the batch's own computed occupancy end as an
    **exclusive** end."
    PRD 3.4: "The vessel is occupied and the culture's pitch self-loop fires, so both
    the vessel's `version` and the culture's `version` increase by 1 alongside the
    culture's `pitch_count`."

    Design: Corner/consistency_model/a_pitch_response_already_shows_every_immediate_side_effect
    """
    recipe = new_recipe(api, planned_f1_days=6)
    culture = new_culture(api, "Mother AC")
    vessel = new_sanitized_vessel(api, code="FV-33", capacity_liters=500.0)

    batch = pitch_batch(
        api, recipe["id"], culture["id"], vessel["id"], batch_code="B-33001",
        pitched_liters=400.0, planned_f2_days=3,
    )

    vessel_after = read_vessel(api, vessel["id"])
    assert vessel_after["state"] == "OCCUPIED"
    assert vessel_after["current_batch_id"] == batch["id"]
    assert_same_instant(
        vessel_after["occupancy_start_at"], "2026-05-01T00:00:00.000Z", "occupancy_start_at"
    )
    assert_same_instant(
        vessel_after["occupancy_end_at"], "2026-05-10T00:00:00.000Z", "occupancy_end_at"
    )

    culture_after = read_culture(api, culture["id"])
    assert culture_after["pitch_count"] == 1
    assert culture_after["vitality_score"] == 94
    assert batch["recipe_version_number_at_pitch"] == 1


def test_a_fill_of_exactly_ninety_percent_passes_and_one_liter_more_is_refused(api):
    """PRD 3.4: "A vessel may only be charged to 90 % of its nominal capacity — a
    headspace allowance of 10 % is reserved for the ferment — so `pitched_liters` must
    be at or below `capacity_liters` multiplied by 90 and divided by 100. A fill of
    exactly 90 % is accepted; anything strictly greater is
    `ERR_VESSEL_CAPACITY_EXCEEDED`."

    Design: Corner/errors/vessel_headspace_boundary_admits_exactly_ninety_percent_and_refuses_one_liter_more
    """
    recipe = new_recipe(api, name="Small Batch Yuzu")
    culture = new_culture(api, "Mother AD")
    over = new_sanitized_vessel(api, code="FV-34", capacity_liters=100.0)
    exact = new_sanitized_vessel(api, code="FV-35", capacity_liters=100.0)

    refused = api.create_batch(
        create_batch_payload(
            recipe["id"], culture["id"], over["id"], batch_code="B-34001",
            pitched_liters=91.0, planned_f2_days=3,
        ),
        OPERATOR,
    )
    validate_error(refused, ApiErrorId.ERR_VESSEL_CAPACITY_EXCEEDED.value, 422)

    accepted = validate_success(
        api.create_batch(
            create_batch_payload(
                recipe["id"], culture["id"], exact["id"], batch_code="B-35001",
                pitched_liters=90.0, planned_f2_days=3,
            ),
            OPERATOR,
        ),
        201,
    )

    assert read_vessel(api, over["id"])["state"] == "SANITIZED"
    assert read_vessel(api, exact["id"])["state"] == "OCCUPIED"
    assert_liters(accepted["pitched_liters"], 90.0, "pitched_liters at exactly 90 % of capacity")
    assert read_culture(api, culture["id"])["pitch_count"] == 1


def test_a_qa_reading_carries_no_version_and_no_updated_at(api):
    """PRD 2.4: "The single exception is `QaReading`: a QA reading is an append-only
    observation and is never edited, so a reading carries only `id` and `created_at` —
    it has **no** `updated_at` field and **no** `version` field at all."
    PRD 3.5: "The server stamps `recorded_by_user_id` with the acting `X-User-ID` and
    derives `day_index` as the number of complete days from `pitched_at` to
    `reading_at`, so the pitch instant itself sits at day index 0."

    Design: Corner/entities/qa_reading_is_append_only_and_carries_no_version_field
    """
    recipe = new_recipe(api)
    culture = new_culture(api, "Mother Q")
    vessel = new_sanitized_vessel(api, code="FV-17", capacity_liters=500.0)
    batch = pitch_batch(
        api, recipe["id"], culture["id"], vessel["id"], batch_code="B-17001",
        pitched_liters=400.0, planned_f2_days=3,
    )
    set_clock(api, "2026-05-04T00:00:00.000Z")

    reading = validate_success(
        api.create_qa_reading(
            batch["id"],
            create_qa_reading_payload(
                reading_type="F1", reading_at="2026-05-03T00:00:00.000Z", ph=3.80,
                temperature_c=24.0, brix=6.0, abv_pct=0.10,
            ),
            OPERATOR,
        ),
        201,
    )

    assert_qa_reading(reading)
    assert reading["day_index"] == 2
    assert reading["flagged"] is False

    rows, meta = validate_paginated(api.list_batch_qa_readings(batch["id"], OPERATOR))
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_a_reading_dated_after_the_logical_clock_is_refused(api):
    """PRD 2.9: "On a QA reading, `reading_at` is at or after the batch's `pitched_at`
    and at or before the logical clock — otherwise `ERR_VALIDATION` (400)."

    Design: Corner/validations/a_qa_reading_dated_after_the_clock_is_refused
    """
    recipe = new_recipe(api)
    culture = new_culture(api, "Mother Y")
    vessel = new_sanitized_vessel(api, code="FV-27", capacity_liters=500.0)
    batch = pitch_batch(
        api, recipe["id"], culture["id"], vessel["id"], batch_code="B-27001",
        pitched_liters=400.0, planned_f2_days=3,
    )
    set_clock(api, "2026-05-04T00:00:00.000Z")

    response = api.create_qa_reading(
        batch["id"],
        create_qa_reading_payload(
            reading_type="F1", reading_at="2026-05-20T00:00:00.000Z", ph=3.40,
            temperature_c=24.0, brix=5.0, abv_pct=0.15,
        ),
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    after = read_batch(api, batch["id"])
    assert after["flagged_reading_count"] == 0
    assert after["ph_target_hit_day_index"] is None

    rows, meta = validate_paginated(api.list_batch_qa_readings(batch["id"], OPERATOR))
    assert meta["total_count"] == 0 and rows == []


def test_an_ingredient_lot_expiring_exactly_on_the_buffer_boundary_is_refused(api):
    """PRD 3.4: "The freshness rule is stated deliberately strictly: the lot's
    `expiry_date` must be **strictly after** the logical clock plus 7 whole days. A
    lot expiring exactly on that boundary is refused, and so is one already in
    `status` `EXPIRED`; both answer `ERR_INGREDIENT_EXPIRED`."
    PRD 3.4: "Recording a use raises `quantity_consumed` and lowers
    `quantity_available` accordingly, and moves the lot's status: a draw strictly
    smaller than the remaining availability moves an `AVAILABLE` lot to
    `PARTIALLY_CONSUMED`, while a draw exactly equal to the remaining availability
    moves the lot to `CONSUMED` with `quantity_consumed` equal to `quantity_received`
    and `quantity_available` at 0."

    Design: Corner/validations/ingredient_expiry_buffer_is_strict_on_the_boundary_day
    """
    recipe = new_recipe(api)
    culture = new_culture(api, "Mother Z")
    vessel = new_sanitized_vessel(api, code="FV-28", capacity_liters=500.0)
    batch = pitch_batch(
        api, recipe["id"], culture["id"], vessel["id"], batch_code="B-28001",
        pitched_liters=400.0, planned_f2_days=3,
    )
    edge = new_ingredient_lot(
        api, supplier_lot_code="TEA-EDGE", expiry_date="2026-05-08T00:00:00.000Z",
        quantity_received=20.0,
    )
    fresh = new_ingredient_lot(
        api, supplier_lot_code="TEA-OK", expiry_date="2026-05-09T00:00:00.000Z",
        quantity_received=20.0,
    )

    refused = api.create_ingredient_use(
        batch["id"], create_ingredient_use_payload(edge["id"], 5.0), OPERATOR
    )
    validate_error(refused, ApiErrorId.ERR_INGREDIENT_EXPIRED.value, 422)

    use = validate_success(
        api.create_ingredient_use(
            batch["id"], create_ingredient_use_payload(fresh["id"], 5.0), OPERATOR
        ),
        201,
    )

    edge_after = validate_success(api.get_ingredient_lot(edge["id"], OPERATOR))
    assert_liters(edge_after["quantity_consumed"], 0.0, "the refused lot is untouched")
    assert edge_after["status"] == "AVAILABLE"

    fresh_after = validate_success(api.get_ingredient_lot(fresh["id"], OPERATOR))
    assert_liters(fresh_after["quantity_consumed"], 5.0, "quantity_consumed after the use")
    assert_liters(fresh_after["quantity_available"], 15.0, "quantity_available after the use")
    assert fresh_after["status"] == "PARTIALLY_CONSUMED"
    assert use["voided"] is False


def test_advancing_before_the_ph_target_is_reached_is_refused(api):
    """PRD 3.5: "Advancing to secondary requires `ferment_stage` `F1_ACTIVE`, a
    `qa_disposition` other than `NONCONFORMING`, at least one reading of
    `reading_type` `F1` on the batch, and a non-null `ph_target_hit_day_index` — that
    is, the effective ceiling must actually have been reached inside the
    day-5-to-day-14 window, and a batch that never got there is refused with
    `ERR_PH_WINDOW_MISSED`."

    Design: Corner/errors/advancing_to_f2_before_the_ph_target_is_reached_is_refused
    """
    recipe = new_recipe(api, target_ph_ceiling=3.5)
    culture = new_culture(api, "Mother AE")
    vessel = new_sanitized_vessel(api, code="FV-36", capacity_liters=500.0)
    batch = pitch_batch(
        api, recipe["id"], culture["id"], vessel["id"], batch_code="B-36001",
        pitched_liters=400.0, planned_f2_days=3,
    )
    set_clock(api, "2026-05-05T00:00:00.000Z")
    for reading_at, ph, abv in (
        ("2026-05-03T00:00:00.000Z", 3.80, 0.10),
        ("2026-05-05T00:00:00.000Z", 3.60, 0.14),
    ):
        validate_success(
            api.create_qa_reading(
                batch["id"],
                create_qa_reading_payload(
                    reading_type="F1", reading_at=reading_at, ph=ph,
                    temperature_c=24.0, brix=5.0, abv_pct=abv,
                ),
                OPERATOR,
            ),
            201,
        )

    response = api.advance_batch_to_f2(batch["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_PH_WINDOW_MISSED.value, 422)

    after = read_batch(api, batch["id"])
    assert after["ferment_stage"] == "F1_ACTIVE"
    assert after["qa_disposition"] == "PENDING"
    assert after["ph_target_hit_day_index"] is None
    assert after["flagged_reading_count"] == 0
    assert after["f2_started_at"] is None


def test_dumping_a_batch_writes_off_the_remainder_and_frees_the_vessel(api):
    """PRD 3.5: "A batch may be dumped from `F1_ACTIVE`, from `F2_ACTIVE` or from
    `READY_TO_PACKAGE`, with an optional `reason`. The dump adds the current
    `remaining_liters` to `loss_liters` and sets `remaining_liters` to 0, so the batch
    volume identity still balances, and it frees the vessel when the vessel still
    points at this batch."
    PRD 3.3: "When the batch later completes secondary fermentation, or is dumped, the
    vessel returns `OCCUPIED → DIRTY` and `current_batch_id` is cleared to null — but
    `occupancy_start_at` and `occupancy_end_at` are **retained**."

    Design: Corner/state_machines/dumping_a_batch_writes_off_the_remainder_and_frees_the_vessel
    """
    recipe = new_recipe(api, planned_f1_days=6)
    culture = new_culture(api, "Mother V")
    vessel = new_sanitized_vessel(api, code="FV-23", capacity_liters=500.0)
    batch = pitch_batch(
        api, recipe["id"], culture["id"], vessel["id"], batch_code="B-23001",
        pitched_liters=400.0, planned_f2_days=3,
    )

    dumped = validate_success(
        api.dump_batch(batch["id"], {"reason": "Contamination smell"}, OPERATOR)
    )

    assert dumped["ferment_stage"] == "DUMPED"
    assert_liters(dumped["loss_liters"], 400.0, "loss_liters after the dump")
    assert_liters(dumped["remaining_liters"], 0.0, "remaining_liters after the dump")
    assert_liters(dumped["drawn_liters"], 0.0, "drawn_liters after the dump")
    assert_batch(dumped)

    vessel_after = read_vessel(api, vessel["id"])
    assert vessel_after["state"] == "DIRTY"
    assert vessel_after["current_batch_id"] is None
    assert_same_instant(
        vessel_after["occupancy_end_at"], "2026-05-10T00:00:00.000Z",
        "the freed vessel retains occupancy_end_at",
    )


def test_the_batch_list_narrows_by_vessel_id(api):
    """PRD 3.12: "Batches are listed across the whole plant and can be narrowed by
    `recipe_id`, by `scoby_culture_id`, by `vessel_id`, by `ferment_stage` and by
    `qa_disposition`, so both axes of the parallel state machine are independently
    filterable."

    Design: Corner/endpoints/the_batch_list_filters_by_vessel_id
    """
    recipe = new_recipe(api)
    culture = new_culture(api, "Mother AA")
    v1 = new_sanitized_vessel(api, code="FV-29", capacity_liters=500.0)
    v2 = new_sanitized_vessel(api, code="FV-30", capacity_liters=500.0)
    pitch_batch(
        api, recipe["id"], culture["id"], v1["id"], batch_code="B-29001",
        pitched_liters=400.0, planned_f2_days=3,
    )
    second = pitch_batch(
        api, recipe["id"], culture["id"], v2["id"], batch_code="B-30001",
        pitched_liters=300.0, planned_f2_days=3,
    )

    rows, meta = validate_paginated(api.list_batches(OPERATOR, params={"vessel_id": v2["id"]}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1 and rows[0]["id"] == second["id"]
    assert_liters(rows[0]["pitched_liters"], 300.0, "the filtered row's pitched_liters")

    _, all_meta = validate_paginated(api.list_batches(OPERATOR))
    assert all_meta["total_count"] == 2


# --------------------------------------------------------------------------
# The two batch axes advance independently
# --------------------------------------------------------------------------
def test_the_process_axis_advances_while_the_quality_axis_stays_at_risk(api):
    """PRD 3.5: "A flagged reading with no hard-fail reason present moves the axis to
    `AT_RISK` — from `PENDING` and equally from `CONFORMING` — increments
    `flagged_reading_count` by 1, and records the recording operator's `X-User-ID` in
    `last_flagged_reading_by_user_id`."
    PRD 3.5: "A later clean reading, on its own, never restores `CONFORMING` — the
    human sign-off is the only edge out of `AT_RISK` that does not lead to
    `NONCONFORMING`, and it may be used at most once per batch."
    PRD 3.5: "`TEMP_EXCURSION`, when `temperature_c` is strictly below 20.0 or
    strictly above 30.0. Exactly 20.0 and exactly 30.0 are both inside the band."

    Design: Difficulty/non_linear_state_machine/batch_quality_axis_holds_at_risk_while_the_process_axis_advances
    """
    built = build_at_risk_batch(api)
    batch_id = built["batch"]["id"]

    before = read_batch(api, batch_id)
    assert before["ph_target_hit_day_index"] == 5
    assert before["temp_excursion_count"] == 1
    assert before["flagged_reading_count"] == 1
    assert before["qa_disposition"] == "AT_RISK", (
        "the clean reading recorded after the excursion must not restore CONFORMING"
    )

    advanced = validate_success(api.advance_batch_to_f2(batch_id, OPERATOR))
    assert advanced["ferment_stage"] == "F2_ACTIVE", (
        "the process axis advances even though the quality axis is AT_RISK"
    )
    assert advanced["qa_disposition"] == "AT_RISK"
    assert_abv(advanced["f1_measured_abv_pct"], 0.22, "f1_measured_abv_pct")
    assert_abv(advanced["projected_abv_pct"], 0.45, "projected_abv_pct")


def test_the_corrective_signoff_is_the_only_way_back_and_keeps_the_flag_count(api):
    """PRD 3.5: "A `QaManager` may apply a corrective sign-off, with an optional
    `note`, to a batch whose `qa_disposition` is exactly `AT_RISK`, whose
    `qa_signoff_count` is 0, and whose most recent QA reading has `flagged` false."
    PRD 3.5: "On success the axis moves `AT_RISK → CONFORMING` and `qa_signoff_count`
    becomes 1. `flagged_reading_count` is deliberately **not** decremented."

    Design: Difficulty/non_linear_state_machine/batch_quality_axis_holds_at_risk_while_the_process_axis_advances
    """
    built = build_at_risk_batch(api)
    batch_id = built["batch"]["id"]
    validate_success(api.advance_batch_to_f2(batch_id, OPERATOR))

    signed = validate_success(
        api.qa_signoff_batch(
            batch_id, {"note": "Excursion investigated, product unaffected"}, QA
        )
    )

    assert signed["qa_disposition"] == "CONFORMING"
    assert signed["qa_signoff_count"] == 1
    assert signed["flagged_reading_count"] == 1, (
        "the sign-off deliberately does not decrement flagged_reading_count"
    )
    assert signed["temp_excursion_count"] == 1
    assert signed["ferment_stage"] == "F2_ACTIVE"
