"""SCOBY lineage and vitality, vessel sanitation, and vessel occupancy."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_same_instant,
    assert_scoby_culture,
    build_ready_batch,
    create_batch_payload,
    create_scoby_culture_payload,
    new_culture,
    new_lineage,
    new_recipe,
    new_sanitized_vessel,
    new_vessel,
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


# --------------------------------------------------------------------------
# Culture lineage and the vitality score
# --------------------------------------------------------------------------
def test_founder_and_daughter_generations_and_vitality_are_derived(api):
    """PRD 3.2: "When `parent_culture_id` is omitted the new culture is a **founder**
    and its `generation_number` is 1. When `parent_culture_id` is supplied, the parent
    must exist and its `state` must be `ACTIVE`, and the daughter's
    `generation_number` is the parent's plus 1."
    PRD 3.2: "Start from 100. Subtract 6 for each pitch counted in `pitch_count`.
    Subtract 4 for each generation beyond the first, that is, for `generation_number`
    minus 1."

    Design: Corner/entities/scoby_generation_number_and_vitality_are_computed_not_supplied
    """
    founder = validate_success(
        api.create_scoby_culture(create_scoby_culture_payload("Founder"), OPERATOR), 201
    )
    daughter = validate_success(
        api.create_scoby_culture(
            create_scoby_culture_payload("Daughter", parent_culture_id=founder["id"]), OPERATOR
        ),
        201,
    )

    assert_scoby_culture(founder)
    assert_scoby_culture(daughter)
    assert founder["generation_number"] == 1
    assert founder["vitality_score"] == 100
    assert daughter["generation_number"] == 2
    assert daughter["vitality_score"] == 96, "one generation beyond the first costs 4 points"
    assert daughter["parent_culture_id"] == founder["id"]

    rows, meta = validate_paginated(api.list_scoby_culture_daughters(founder["id"], OPERATOR))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [daughter["id"]]


def test_a_single_pitch_costs_the_culture_exactly_six_vitality_points(api):
    """PRD 3.2: "Start from 100. Subtract 6 for each pitch counted in `pitch_count`.
    Subtract 4 for each generation beyond the first, that is, for `generation_number`
    minus 1."
    PRD 3.2: "Each accepted pitch increments `pitch_count` by 1, recomputes
    `vitality_score` on the new count, and bumps the culture's `version` by 1; the
    culture stays in `ACTIVE`, which is why this is a self-loop rather than a
    transition."

    Design: Corner/calculations/scoby_vitality_falls_exactly_six_points_per_pitch
    """
    recipe = new_recipe(api)
    founder = new_culture(api, "Mother W")
    daughter = new_culture(api, "Daughter W", parent_culture_id=founder["id"])
    vessel = new_sanitized_vessel(api, code="FV-24", capacity_liters=500.0)

    batch = pitch_batch(
        api, recipe["id"], daughter["id"], vessel["id"], batch_code="B-24001",
        pitched_liters=400.0, planned_f2_days=3,
    )

    after = read_culture(api, daughter["id"])
    assert after["vitality_score"] == 90, "96 less the 6-point pitch penalty is exactly 90"
    assert after["pitch_count"] == 1
    assert after["state"] == "ACTIVE"

    mother = read_culture(api, founder["id"])
    assert mother["vitality_score"] == 100, "the mother is untouched by a daughter's pitch"
    assert mother["pitch_count"] == 0
    assert batch["ferment_stage"] == "F1_ACTIVE"


def test_a_passed_reverification_resets_the_pitch_count_and_lifts_vitality(api):
    """PRD 3.2: "On `PASS` the culture returns `REVERIFICATION_PENDING → ACTIVE`,
    `reverification_count` is incremented by 1, `pitch_count` is reset to 0 **before**
    the score is recomputed, and `last_reverified_at` is stamped with the logical
    clock."
    PRD 3.2: "Clamp the result into the closed range 0 through 100, so a computed
    value below 0 becomes 0 and a value above 100 becomes 100."

    Design: Corner/state_machines/a_passed_reverification_resets_the_pitch_count_and_lifts_vitality
    """
    recipe = new_recipe(api)
    founder = new_culture(api, "Mother AL")
    daughter = new_culture(api, "Daughter AL", parent_culture_id=founder["id"])
    vessel = new_sanitized_vessel(api, code="FV-43", capacity_liters=500.0)
    pitch_batch(
        api, recipe["id"], daughter["id"], vessel["id"], batch_code="B-43001",
        pitched_liters=400.0, planned_f2_days=3,
    )
    validate_success(api.reverify_scoby_culture(daughter["id"], QA))

    result = validate_success(
        api.reverify_result_scoby_culture(daughter["id"], {"outcome": "PASS"}, QA)
    )

    assert result["state"] == "ACTIVE"
    assert result["pitch_count"] == 0
    assert result["reverification_count"] == 1
    assert_same_instant(
        result["last_reverified_at"], "2026-05-01T00:00:00.000Z", "last_reverified_at"
    )
    assert result["vitality_score"] == 100, "100 - 0 - 4 + 15 = 111, clamped to 100"
    assert result["retire_reason"] is None


def test_a_failed_reverification_contaminates_the_culture_and_nonconforms_its_batch(api):
    """PRD 3.2: "On `FAIL` the culture moves `REVERIFICATION_PENDING → CONTAMINATED`,
    `retire_reason` is set to `CONTAMINATION`, and a two-hop cascade fires: every
    batch of that culture whose `ferment_stage` is `F1_ACTIVE`, `F2_ACTIVE` or
    `READY_TO_PACKAGE` has its `qa_disposition` set to `NONCONFORMING`, and every
    packaging run in `DRAFT`, `SOURCED` or `IN_PROGRESS` that draws on one of those
    batches is driven to `ABORTED` with its drawn liters returned."

    Design: Corner/state_machines/reverification_failure_contaminates_the_culture_and_nonconforms_its_inflight_batch
    """
    recipe = new_recipe(api)
    culture = new_culture(api, "Mother U")
    vessel = new_sanitized_vessel(api, code="FV-22", capacity_liters=500.0)
    batch = pitch_batch(
        api, recipe["id"], culture["id"], vessel["id"], batch_code="B-22001",
        pitched_liters=400.0, planned_f2_days=3,
    )
    validate_success(api.reverify_scoby_culture(culture["id"], QA))

    result = validate_success(
        api.reverify_result_scoby_culture(culture["id"], {"outcome": "FAIL"}, QA)
    )

    assert result["state"] == "CONTAMINATED"
    assert result["retire_reason"] == "CONTAMINATION"

    after = read_batch(api, batch["id"])
    assert after["qa_disposition"] == "NONCONFORMING"
    assert after["ferment_stage"] == "F1_ACTIVE", "the process axis is untouched by the cascade"
    assert read_vessel(api, vessel["id"])["state"] == "OCCUPIED"


def test_a_daughter_at_generation_eight_is_refused_outright(api):
    """PRD 3.2: "Lineage depth is capped at 7: a daughter whose `generation_number`
    would come out at 8 or more is refused outright with `ERR_SCOBY_GENERATION_CAP`."

    Design: Corner/state_machines/an_eighth_generation_daughter_is_refused_at_the_lineage_cap
    """
    lineage = new_lineage(api, 7)
    seventh = lineage[-1]

    response = api.create_scoby_culture(
        create_scoby_culture_payload("G8", parent_culture_id=seventh["id"]), OPERATOR
    )
    validate_error(response, ApiErrorId.ERR_SCOBY_GENERATION_CAP.value, 422)

    after = read_culture(api, seventh["id"])
    assert after["generation_number"] == 7
    assert after["state"] == "ACTIVE"
    assert after["vitality_score"] == 76, "100 less 4 points for each of six generations"


def test_a_retired_culture_can_never_be_pitched_again(api):
    """PRD 3.2: "`RETIRED` and `CONTAMINATED` are both terminal — a culture in either
    state can never be pitched, reverified or retired again."
    PRD 2.8: "(7) the culture's `state` is `ACTIVE`, else `ERR_INVALID_STATE`"

    Design: Corner/state_machines/a_retired_culture_cannot_be_pitched_again
    """
    recipe = new_recipe(api)
    culture = new_culture(api, "Mother T")
    vessel = new_sanitized_vessel(api, code="FV-21", capacity_liters=500.0)
    validate_success(
        api.retire_scoby_culture(culture["id"], {"retire_reason": "OPERATOR"}, OPERATOR)
    )

    response = api.create_batch(
        create_batch_payload(
            recipe["id"], culture["id"], vessel["id"], batch_code="B-21001",
            pitched_liters=400.0, planned_f2_days=3,
        ),
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    after = read_culture(api, culture["id"])
    assert after["state"] == "RETIRED"
    assert after["retire_reason"] == "OPERATOR"
    assert after["pitch_count"] == 0, "a refused pitch consumes nothing from the culture"
    assert read_vessel(api, vessel["id"])["state"] == "SANITIZED"


def test_a_culture_below_the_vitality_floor_refuses_the_pitch_and_stays_active(api):
    """PRD 3.2: "The floor is 40. A culture whose `vitality_score` is at or above 40
    may be pitched; strictly below 40 the pitch is refused with
    `ERR_SCOBY_VITALITY_TOO_LOW`. There is deliberately no automatic retirement at
    that floor — a worn-out culture stays `ACTIVE` and simply refuses every further
    pitch, and an operator must retire it explicitly."

    Design: Corner/errors/a_worn_out_culture_is_refused_at_the_vitality_floor_and_stays_active
    """
    recipe = new_recipe(api)
    lineage = new_lineage(api, 6)
    worn = lineage[-1]

    pitched = []
    for index in range(1, 8):
        vessel = new_sanitized_vessel(api, code=f"FV-5{index}", capacity_liters=500.0)
        pitched.append(
            pitch_batch(
                api, recipe["id"], worn["id"], vessel["id"], batch_code=f"B-5{index}",
                pitched_liters=100.0, planned_f2_days=3,
            )
        )

    before_retire = read_culture(api, worn["id"])
    assert before_retire["pitch_count"] == 7
    assert before_retire["vitality_score"] == 38, "100 - 42 for pitches - 20 for generations"
    assert before_retire["state"] == "ACTIVE"

    spare = new_sanitized_vessel(api, code="FV-58", capacity_liters=500.0)
    response = api.create_batch(
        create_batch_payload(
            recipe["id"], worn["id"], spare["id"], batch_code="B-58",
            pitched_liters=100.0, planned_f2_days=3,
        ),
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_SCOBY_VITALITY_TOO_LOW.value, 422)
    assert read_vessel(api, spare["id"])["state"] == "SANITIZED"

    # PRD 3.2: manual retirement lands "only when no batch of that culture is
    # currently in `ferment_stage` `F1_ACTIVE` or `F2_ACTIVE`".  Write off the
    # seven pitches first -- PRD 3.5: "A batch may be dumped from `F1_ACTIVE`".
    for batch in pitched:
        validate_success(api.dump_batch(batch["id"], {"reason": "VITALITY"}, OPERATOR))

    retired = validate_success(
        api.retire_scoby_culture(worn["id"], {"retire_reason": "VITALITY"}, OPERATOR)
    )
    assert retired["state"] == "RETIRED"
    assert retired["retire_reason"] == "VITALITY"


# --------------------------------------------------------------------------
# Vessels: registration, sanitation, versioning
# --------------------------------------------------------------------------
def test_registering_a_vessel_without_its_capacity_is_a_validation_error(api):
    """PRD 2.9: "Every field the endpoint declares as required is present and of the
    declared type, on every endpoint — otherwise `ERR_VALIDATION` (400)."
    PRD 3.3: "A fermentation vessel is registered with a stencilled `code` and a
    nominal `capacity_liters`, and it enters the world in `state` `DIRTY`."

    Design: Corner/entities/vessel_create_missing_required_capacity_returns_validation
    """
    response = api.create_vessel({"code": "FV-MISSING"}, OPERATOR)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)


def test_completing_cip_on_an_already_sanitized_vessel_is_refused(api):
    """PRD 2.9: "A `Vessel` has `state` `SANITIZED` for a pitch, is in `DIRTY` or
    `SANITIZED` for a CIP start, and is `CIP_IN_PROGRESS` for a CIP completion —
    otherwise `ERR_VESSEL_UNAVAILABLE`."
    PRD 2.4: "A server-wide logical clock governs every window, expiry, hold period
    and age calculation, and before it is ever set it reads exactly
    `2026-05-01T00:00:00Z`."

    Design: Corner/state_machines/cip_complete_from_sanitized_is_an_invalid_transition
    """
    vessel = new_sanitized_vessel(api, code="FV-19", capacity_liters=400.0)

    response = api.cip_complete_vessel(vessel["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_VESSEL_UNAVAILABLE.value, 409)

    after = read_vessel(api, vessel["id"])
    assert after["state"] == "SANITIZED"
    assert_same_instant(
        after["cip_completed_at"], "2026-05-01T00:00:00.000Z", "cip_completed_at"
    )


def test_each_mutating_call_bumps_the_version_by_exactly_one_and_reads_do_not(api):
    """PRD 2.4: "Seventeen of the eighteen resource families also carry `updated_at`,
    refreshed on every mutation, and `version`, an integer that starts at 1 on
    creation and increases by exactly 1 on every mutation of that row."
    PRD 3.3: "Starting a clean-in-place cycle is accepted from `DIRTY` and also from
    `SANITIZED`; either way the vessel moves to `CIP_IN_PROGRESS`, `cip_started_at` is
    stamped with the logical clock and `cip_completed_at` is cleared to null."

    Design: Corner/cross_cutting_complexity_layers/entity_version_increments_by_one_on_every_mutation
    """
    vessel = new_vessel(api, code="FV-32", capacity_liters=250.0)
    assert vessel["version"] == 1

    started = validate_success(api.cip_start_vessel(vessel["id"], OPERATOR))
    assert started["version"] == 2
    assert started["state"] == "CIP_IN_PROGRESS"

    completed = validate_success(api.cip_complete_vessel(vessel["id"], OPERATOR))
    assert completed["version"] == 3
    assert completed["state"] == "SANITIZED"

    after_read = read_vessel(api, vessel["id"])
    assert after_read["version"] == 3, "a read is not a mutation and must not bump version"


# --------------------------------------------------------------------------
# Pitching against the vessel
# --------------------------------------------------------------------------
def test_pitching_into_a_dirty_vessel_is_refused(api):
    """PRD 2.8: "(10) the vessel's `state` is `SANITIZED`, else
    `ERR_VESSEL_UNAVAILABLE`"
    PRD 3.3: "A fermentation vessel is registered with a stencilled `code` and a
    nominal `capacity_liters`, and it enters the world in `state` `DIRTY`."

    Design: Difficulty/cross_entity_state_dependency/pitching_into_a_vessel_that_was_never_sanitised_is_refused
    """
    recipe = new_recipe(api)
    culture = new_culture(api, "Mother L")
    vessel = new_vessel(api, code="FV-12", capacity_liters=500.0)

    response = api.create_batch(
        create_batch_payload(
            recipe["id"], culture["id"], vessel["id"], batch_code="B-12001",
            pitched_liters=400.0, planned_f2_days=3,
        ),
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_VESSEL_UNAVAILABLE.value, 409)

    after = read_vessel(api, vessel["id"])
    assert after["state"] == "DIRTY"
    assert after["current_batch_id"] is None


def test_a_refused_pitch_leaves_the_culture_pitch_count_and_vitality_untouched(api):
    """PRD 3.2: "Each accepted pitch increments `pitch_count` by 1, recomputes
    `vitality_score` on the new count, and bumps the culture's `version` by 1; the
    culture stays in `ACTIVE`, which is why this is a self-loop rather than a
    transition."
    PRD 2.8: "(10) the vessel's `state` is `SANITIZED`, else
    `ERR_VESSEL_UNAVAILABLE`"

    Design: Difficulty/cross_entity_state_dependency/pitching_into_a_vessel_that_was_never_sanitised_is_refused
    """
    recipe = new_recipe(api)
    culture = new_culture(api, "Mother L")
    vessel = new_vessel(api, code="FV-12", capacity_liters=500.0)

    response = api.create_batch(
        create_batch_payload(
            recipe["id"], culture["id"], vessel["id"], batch_code="B-12001",
            pitched_liters=400.0, planned_f2_days=3,
        ),
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_VESSEL_UNAVAILABLE.value, 409)

    after = read_culture(api, culture["id"])
    assert after["pitch_count"] == 0, "a refused pitch is not counted against the culture"
    assert after["vitality_score"] == 100

    rows, meta = validate_paginated(
        api.list_batches(OPERATOR, params={"vessel_id": vessel["id"]})
    )
    assert meta["total_count"] == 0 and rows == [], "no batch row is created by a refused pitch"


def test_an_expired_cip_window_is_answered_before_the_capacity_rung(api):
    """PRD 2.8: "| `ERR_VESSEL_CIP_EXPIRED` vs `ERR_VESSEL_CAPACITY_EXCEEDED` |
    `ERR_VESSEL_CIP_EXPIRED` | pitching a batch | Sanitation is a safety rung and
    outranks the capacity constraint. |"
    PRD 2.8: "(11) the logical clock is at or before `cip_completed_at` plus 72 hours,
    else `ERR_VESSEL_CIP_EXPIRED`"

    Design: Difficulty/priority_pair_validation_conflict/cip_expiry_beats_vessel_capacity_on_pitch
    """
    recipe = new_recipe(api, name="Small Batch Yuzu")
    culture = new_culture(api, "Mother J")
    vessel = new_sanitized_vessel(api, code="FV-10", capacity_liters=100.0)
    set_clock(api, "2026-05-05T00:00:00.000Z")

    response = api.create_batch(
        create_batch_payload(
            recipe["id"], culture["id"], vessel["id"], batch_code="B-10001",
            pitched_liters=95.0, planned_f2_days=3,
        ),
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_VESSEL_CIP_EXPIRED.value, 422)
    assert response.json()["data"]["error_id"] != "ERR_VESSEL_CAPACITY_EXCEEDED"


def test_the_pitch_refused_for_cip_expiry_leaves_no_occupancy_behind(api):
    """PRD 2.8: "(11) the logical clock is at or before `cip_completed_at` plus 72
    hours, else `ERR_VESSEL_CIP_EXPIRED`"
    PRD 3.3: "Occupancy is an interval, not a flag. When a batch is pitched into a
    vessel the vessel moves `SANITIZED → OCCUPIED`, `current_batch_id` mirrors the new
    batch, `occupancy_start_at` takes the batch's pitch instant as an **inclusive**
    start, and `occupancy_end_at` takes the batch's own computed occupancy end as an
    **exclusive** end."

    Design: Difficulty/priority_pair_validation_conflict/cip_expiry_beats_vessel_capacity_on_pitch
    """
    recipe = new_recipe(api, name="Small Batch Yuzu")
    culture = new_culture(api, "Mother J")
    vessel = new_sanitized_vessel(api, code="FV-10", capacity_liters=100.0)
    set_clock(api, "2026-05-05T00:00:00.000Z")

    response = api.create_batch(
        create_batch_payload(
            recipe["id"], culture["id"], vessel["id"], batch_code="B-10001",
            pitched_liters=95.0, planned_f2_days=3,
        ),
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_VESSEL_CIP_EXPIRED.value, 422)

    after = read_vessel(api, vessel["id"])
    assert after["state"] == "SANITIZED"
    assert after["current_batch_id"] is None
    assert read_culture(api, culture["id"])["pitch_count"] == 0

    rows, meta = validate_paginated(
        api.list_batches(OPERATOR, params={"vessel_id": vessel["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


def test_a_backdated_pitch_overlapping_the_retained_occupancy_is_refused(api):
    """PRD 3.3: "The interval the new batch wants, running from its `pitched_at` up to
    but excluding its `occupancy_end_at`, must not intersect the interval the vessel
    has retained. Both intervals are half-open, so a new pitch whose `pitched_at`
    falls exactly on the retained `occupancy_end_at` **is** accepted; any genuine
    overlap is refused with `ERR_VESSEL_UNAVAILABLE`."
    PRD 3.3: "When the batch later completes secondary fermentation, or is dumped, the
    vessel returns `OCCUPIED → DIRTY` and `current_batch_id` is cleared to null — but
    `occupancy_start_at` and `occupancy_end_at` are **retained**."

    Design: Difficulty/resource_temporal_overlap/vessel_occupancy_is_half_open_so_a_backdated_overlap_fails_but_an_abutting_pitch_passes
    """
    built = build_ready_batch(api, vessel_code="FV-14", batch_code="B-14001", culture_label="Mother N")
    vessel_id = built["vessel"]["id"]
    validate_success(api.cip_start_vessel(vessel_id, OPERATOR))
    validate_success(api.cip_complete_vessel(vessel_id, OPERATOR))

    response = api.create_batch(
        create_batch_payload(
            built["recipe"]["id"], built["culture"]["id"], vessel_id,
            batch_code="B-14002", pitched_liters=300.0, planned_f2_days=3,
            pitched_at="2026-05-08T00:00:00.000Z",
        ),
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_VESSEL_UNAVAILABLE.value, 409)

    after = read_vessel(api, vessel_id)
    assert after["state"] == "SANITIZED", "the refused pitch leaves the vessel free"
    assert after["current_batch_id"] is None
    assert read_culture(api, built["culture"]["id"])["pitch_count"] == 1


def test_a_pitch_starting_exactly_at_the_retained_occupancy_end_is_accepted(api):
    """PRD 3.3: "Both intervals are half-open, so a new pitch whose `pitched_at` falls
    exactly on the retained `occupancy_end_at` **is** accepted; any genuine overlap is
    refused with `ERR_VESSEL_UNAVAILABLE`."
    PRD 3.4: "`occupancy_end_at` is computed as `pitched_at` plus the recipe's
    `planned_f1_days` and this batch's `planned_f2_days`, added as whole days."

    Design: Difficulty/resource_temporal_overlap/vessel_occupancy_is_half_open_so_a_backdated_overlap_fails_but_an_abutting_pitch_passes
    """
    built = build_ready_batch(api, vessel_code="FV-14", batch_code="B-14001", culture_label="Mother N")
    vessel_id = built["vessel"]["id"]
    validate_success(api.cip_start_vessel(vessel_id, OPERATOR))
    validate_success(api.cip_complete_vessel(vessel_id, OPERATOR))
    set_clock(api, "2026-05-10T00:00:00.000Z")

    created = validate_success(
        api.create_batch(
            create_batch_payload(
                built["recipe"]["id"], built["culture"]["id"], vessel_id,
                batch_code="B-14003", pitched_liters=300.0, planned_f2_days=3,
                pitched_at="2026-05-10T00:00:00.000Z",
            ),
            OPERATOR,
        ),
        201,
    )

    assert_same_instant(created["pitched_at"], "2026-05-10T00:00:00.000Z", "pitched_at")
    assert_same_instant(
        created["occupancy_end_at"], "2026-05-19T00:00:00.000Z", "occupancy_end_at"
    )
    assert created["ferment_stage"] == "F1_ACTIVE"

    vessel = read_vessel(api, vessel_id)
    assert vessel["state"] == "OCCUPIED"
    assert vessel["current_batch_id"] == created["id"]
    assert read_culture(api, built["culture"]["id"])["pitch_count"] == 2
