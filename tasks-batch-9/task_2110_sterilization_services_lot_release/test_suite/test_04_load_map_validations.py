"""Validation rules guarding the load map, the readiness sign-off, the dwell
start and the dosimetry close."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    build_cycle_scenario,
    create_chamber,
    create_cycle,
    create_cycle_payload,
    create_load_position_payload,
    create_lot,
    fetch_indicator,
    create_recipe,
    get_cycle,
    get_lot,
    get_permit,
    get_qualification,
    get_recipe,
    operator,
    place_indicator,
    record_dose_audit,
    record_reading,
    remove_load_position,
    setup_reference_data,
    start_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["regulatory_admin_headers"]

BI_RECIPE = {
    "required_min_zone_dosimeters": 1,
    "required_routine_dosimeters": 1,
    "required_biological_indicators": 1,
}


def test_duplicate_position_index_on_the_same_cycle_is_rejected():
    """PRD 3.5: "No existing position on the cycle may already hold the
    requested `position_index`, on pain of `ERR_DUPLICATE_POSITION_INDEX`."

    Design: Corner/validations/corner_duplicate_position_index_on_one_cycle_rejected
    """
    env = build_cycle_scenario(
        stage="loading",
        lot_overrides={"total_pallet_count": 4},
        pallet_count=2,
        place_indicators=False,
    )
    version = get_cycle(env["cycle"]["id"])["version"]

    response = api_client.create_load_position(
        env["cycle"]["id"],
        create_load_position_payload(
            env["lot"]["id"], version, position_index=1, zone="INTERIOR", pallet_count=2
        ),
        operator(),
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_POSITION_INDEX)
    assert get_cycle(env["cycle"]["id"])["loaded_pallet_count"] == 2
    lot = get_lot(env["lot"]["id"])
    assert lot["staged_pallet_count"] == 2
    assert lot["available_pallet_count"] == 2


def test_cumulative_dose_ceiling_blocks_a_second_placement():
    """PRD 3.5: "Finally the lot's lifetime dose headroom must survive the
    placement: the lot's `cumulative_dose_kgy` plus the recipe's
    `target_dose_kgy`, rounded half up to two decimal places, must be no
    greater than the product's `max_cumulative_dose_kgy`, and a breach is
    refused with `ERR_CUMULATIVE_DOSE_EXCEEDED`."

    Design: Corner/validations/corner_cumulative_dose_ceiling_blocks_load_position
    """
    env = build_cycle_scenario(
        stage="closed",
        product_overrides={"product_code": "PC", "max_cumulative_dose_kgy": 45.0},
        lot_overrides={"total_pallet_count": 4},
        pallet_count=2,
    )
    assert get_lot(env["lot"]["id"])["cumulative_dose_kgy"] == pytest.approx(
        30.00, abs=0.001
    )
    second = create_cycle(
        env["chamber"]["id"],
        env["recipe"]["id"],
        cycle_code="C-B",
        scheduled_start_at="2026-08-12T00:00:00Z",
        scheduled_end_at="2026-08-12T06:00:00Z",
    )

    response = api_client.create_load_position(
        second["id"],
        create_load_position_payload(env["lot"]["id"], second["version"], pallet_count=2),
        operator(),
    )

    validate_error(response, ApiErrorId.ERR_CUMULATIVE_DOSE_EXCEEDED)
    after = get_cycle(second["id"])
    assert after["status"] == "PLANNED"
    assert after["loaded_pallet_count"] == 0


def test_cycle_recipe_modality_must_match_the_chamber_modality():
    """PRD 3.4: "Scheduling is refused if the chamber is `DECOMMISSIONED`
    (`ERR_CHAMBER_UNAVAILABLE`), if the recipe is still `DRAFT`
    (`ERR_RECIPE_NOT_APPROVED`), if the recipe's `modality` differs from the
    chamber's `modality` (`ERR_MODALITY_MISMATCH`), or if the `cycle_code` is
    already taken (`ERR_DUPLICATE_CODE`)."

    Design: Corner/validations/corner_recipe_modality_must_match_chamber_modality
    """
    env = setup_reference_data(qualify=False)
    eto_recipe = create_recipe("ETO", recipe_code="RE")

    response = api_client.create_cycle(
        create_cycle_payload(env["chamber"]["id"], eto_recipe["id"]), operator()
    )

    validate_error(response, ApiErrorId.ERR_MODALITY_MISMATCH)
    _, meta = validate_paginated(
        api_client.list_cycles(operator(), params={"chamber_id": env["chamber"]["id"]})
    )
    assert meta["total_count"] == 0


def test_chamber_modality_must_be_contracted_by_the_lot_owner():
    """PRD 3.5: "The chamber's `modality` must appear in the owning customer's
    `contracted_modalities`, and a modality the customer never contracted for
    is refused with `ERR_MODALITY_MISMATCH`."

    Design: Corner/validations/corner_chamber_modality_must_be_contracted_by_the_customer
    """
    env = setup_reference_data(
        modality="ETO",
        customer_overrides={"account_code": "GAMMA-ONLY", "contracted_modalities": ["GAMMA"]},
    )
    lot = create_lot(env["customer"]["id"], env["product"]["id"])
    cycle = create_cycle(
        env["chamber"]["id"], env["recipe"]["id"], raw_eto_charge_kg=100.0
    )

    response = api_client.create_load_position(
        cycle["id"],
        create_load_position_payload(lot["id"], cycle["version"], pallet_count=2),
        operator(),
    )

    validate_error(response, ApiErrorId.ERR_MODALITY_MISMATCH)
    assert get_cycle(cycle["id"])["status"] == "PLANNED"
    assert get_lot(lot["id"])["status"] == "RECEIVED"


def test_a_draft_recipe_cannot_back_a_cycle():
    """PRD 3.3: "Recipes open in `status` `DRAFT`; only a `RegulatoryAdmin` may
    advance one `DRAFT → APPROVED`, and only an `APPROVED` recipe may back a
    cycle — scheduling against a draft is refused with
    `ERR_RECIPE_NOT_APPROVED`."

    Design: Corner/validations/corner_draft_recipe_cannot_back_a_cycle
    """
    env = setup_reference_data(qualify=False)
    draft = create_recipe("GAMMA", approved=False, recipe_code="RG-DRAFT")

    response = api_client.create_cycle(
        create_cycle_payload(env["chamber"]["id"], draft["id"]), operator()
    )

    validate_error(response, ApiErrorId.ERR_RECIPE_NOT_APPROVED)
    assert get_recipe(draft["id"])["status"] == "DRAFT"


def test_readiness_sign_off_on_an_empty_load_map_is_rejected():
    """PRD 3.6: "First, the cycle must hold at least one load position; a
    `PLANNED` cycle necessarily holds none, so it always fails here with
    `ERR_LOAD_MAP_EMPTY` and never reaches `READY`."
    PRD 3.5: "a cycle left with no positions at all goes `LOADING → PLANNED`
    with `loaded_pallet_count` at 0 and `load_density_g_per_cm3` at 0.0000."

    Design: Corner/validations/corner_ready_with_empty_load_map_rejected
    """
    env = build_cycle_scenario(stage="loading", place_indicators=False)
    remove_load_position(env["cycle"]["id"], env["position"]["id"])
    assert get_cycle(env["cycle"]["id"])["status"] == "PLANNED"

    response = api_client.ready_cycle(env["cycle"]["id"], operator())

    validate_error(response, ApiErrorId.ERR_LOAD_MAP_EMPTY)
    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "PLANNED"
    assert cycle["loaded_pallet_count"] == 0
    assert cycle["load_density_g_per_cm3"] == pytest.approx(0.0, abs=1e-9)


def test_readiness_sign_off_without_the_required_biological_indicator_is_rejected():
    """PRD 3.6: "Second, the indicator census must be satisfied: counted across
    every load position of the cycle, the number of `DOSIMETER` indicators
    whose `placement_zone` is `MIN_DOSE` must be at least the recipe's
    `required_min_zone_dosimeters`, the number of `DOSIMETER` indicators whose
    `placement_zone` is `ROUTINE` must be at least `required_routine_dosimeters`,
    and the number of `BIOLOGICAL` indicators must be at least
    `required_biological_indicators`; any shortfall is refused with
    `ERR_INDICATOR_PLACEMENT_INCOMPLETE`."

    Design: Corner/validations/corner_ready_with_missing_biological_indicator_rejected
    """
    env = build_cycle_scenario(
        stage="loading", recipe_overrides=BI_RECIPE, place_indicators=False
    )
    place_indicator(
        env["position"]["id"], indicator_type="DOSIMETER", placement_zone="MIN_DOSE",
        serial_code="D-MIN",
    )
    place_indicator(
        env["position"]["id"], indicator_type="DOSIMETER", placement_zone="ROUTINE",
        serial_code="D-RT",
    )

    response = api_client.ready_cycle(env["cycle"]["id"], operator())

    validate_error(response, ApiErrorId.ERR_INDICATOR_PLACEMENT_INCOMPLETE)
    assert get_cycle(env["cycle"]["id"])["status"] == "LOADING"
    _, meta = validate_paginated(
        api_client.list_indicators(env["position"]["id"], operator())
    )
    assert meta["total_count"] == 2


def test_dosimetry_close_with_an_unread_indicator_is_rejected():
    """PRD 3.7: "Closing dosimetry is the analyst's terminal act on a cycle and
    requires the cycle to be in `DOSIMETRY_REVIEW` with every indicator on it —
    dosimeters and biological indicators alike — at `reading_status` `READ`;
    any unread indicator refuses the close with `ERR_DOSIMETRY_INCOMPLETE`."

    Design: Corner/validations/corner_dosimetry_close_with_an_unread_indicator_rejected
    """
    env = build_cycle_scenario(stage="completed")
    record_reading(env["indicators"]["min_zone"][0]["id"], measured_dose_kgy=28.50)
    assert get_cycle(env["cycle"]["id"])["status"] == "DOSIMETRY_REVIEW"

    response = api_client.dosimetry_close(
        env["cycle"]["id"], TEST_USERS["dosimetry_analyst_headers"]
    )

    validate_error(response, ApiErrorId.ERR_DOSIMETRY_INCOMPLETE)
    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "DOSIMETRY_REVIEW"
    assert cycle["delivered_dose_kgy"] is None
    assert get_lot(env["lot"]["id"])["status"] == "PROCESSED"


def test_permit_allowance_rejects_an_excess_charge_and_accepts_an_exact_landing():
    """PRD 3.6: "**Step three** is the allowance gate: if the prospective
    figure is strictly greater than the permit's `annual_allowance_kg` the
    start is refused with `ERR_PERMIT_ALLOWANCE_EXCEEDED`, while landing
    exactly on the allowance is accepted."
    PRD 3.6: "If the commit leaves `consumed_kg_ytd` at or above
    `annual_allowance_kg`, the permit moves `ACTIVE → SUSPENDED` on the spot,
    and every subsequent start beneath it is refused with
    `ERR_PERMIT_NOT_ACTIVE` until an abort or an administrator restores it."

    Design: Corner/validations/corner_permit_allowance_boundary_exact_equality_accepted_excess_rejected
    """
    env_a = build_cycle_scenario(
        stage="ready",
        modality="ETO",
        permit_overrides={"annual_allowance_kg": 50.0},
        lot_overrides={"lot_code": "L-A"},
        cycle_overrides={"cycle_code": "C-A", "raw_eto_charge_kg": 1200.0},
    )
    start_cycle(env_a["cycle"]["id"])
    assert get_permit(env_a["permit"]["id"])["consumed_kg_ytd"] == pytest.approx(
        48.000, abs=1e-6
    )

    chamber_b = create_chamber(env_a["permit"]["id"], "ETO", chamber_code="CH-E2")
    env_b = build_cycle_scenario(
        stage="ready",
        modality="ETO",
        env=dict(env_a, chamber=chamber_b),
        lot_overrides={"lot_code": "L-B"},
        cycle_overrides={
            "cycle_code": "C-B",
            "scheduled_start_at": "2026-08-11T07:00:00Z",
            "scheduled_end_at": "2026-08-11T13:00:00Z",
            "raw_eto_charge_kg": 100.0,
        },
    )
    chamber_c = create_chamber(env_a["permit"]["id"], "ETO", chamber_code="CH-E3")
    env_c = build_cycle_scenario(
        stage="ready",
        modality="ETO",
        env=dict(env_a, chamber=chamber_c),
        lot_overrides={"lot_code": "L-C"},
        cycle_overrides={
            "cycle_code": "C-C",
            "scheduled_start_at": "2026-08-11T14:00:00Z",
            "scheduled_end_at": "2026-08-11T20:00:00Z",
            "raw_eto_charge_kg": 50.0,
        },
    )

    rejected = api_client.start_cycle(env_b["cycle"]["id"], operator())
    validate_error(rejected, ApiErrorId.ERR_PERMIT_ALLOWANCE_EXCEEDED)
    blocked = get_cycle(env_b["cycle"]["id"])
    assert blocked["status"] == "READY"
    assert blocked["abated_eto_kg"] == pytest.approx(0.0, abs=1e-9)

    accepted = start_cycle(env_c["cycle"]["id"])
    assert accepted["abated_eto_kg"] == pytest.approx(2.000, abs=1e-6)
    assert accepted["emission_fee_usd"] == pytest.approx(24.00, abs=0.001)
    assert accepted["status"] == "RUNNING"

    permit = get_permit(env_a["permit"]["id"])
    assert permit["consumed_kg_ytd"] == pytest.approx(50.000, abs=1e-6)
    assert permit["total_emission_fee_usd"] == pytest.approx(600.00, abs=0.001)
    assert permit["status"] == "SUSPENDED"


def test_an_unschedulable_lot_cannot_be_placed():
    """PRD 3.5: "The lot's `schedulable` flag must be true, failing which the
    write is refused with `ERR_LOT_NOT_SCHEDULABLE`."
    PRD 3.3: "`CONDITIONAL → REVOKED` fires when a `CONDITIONAL_PASS` pushes
    `consecutive_conditional_count` to 2 or more — reachable from `CONDITIONAL`
    and from `AUDIT_DUE` alike — nulling `next_audit_due_at` and, as a further
    consequence, clearing `schedulable` on every lot of that product whose
    `status` is `RECEIVED` or `STAGED`."

    Design: Corner/validations/corner_unschedulable_lot_cannot_be_loaded
    """
    env = setup_reference_data(qualify=False, clock="2026-08-20T00:00:00Z")
    lot = create_lot(env["customer"]["id"], env["product"]["id"])
    record_dose_audit(
        env["qualification"]["id"], performed_at="2026-08-20T00:00:00Z", positives=1
    )
    record_dose_audit(
        env["qualification"]["id"], performed_at="2026-09-19T00:00:00Z", positives=1
    )
    qualification = get_qualification(env["qualification"]["id"])
    assert qualification["status"] == "REVOKED"
    assert qualification["consecutive_conditional_count"] == 2
    assert get_lot(lot["id"])["schedulable"] is False
    cycle = create_cycle(
        env["chamber"]["id"],
        env["recipe"]["id"],
        scheduled_start_at="2026-09-20T00:00:00Z",
        scheduled_end_at="2026-09-20T06:00:00Z",
    )

    response = api_client.create_load_position(
        cycle["id"],
        create_load_position_payload(lot["id"], cycle["version"], pallet_count=2),
        operator(),
    )

    validate_error(response, ApiErrorId.ERR_LOT_NOT_SCHEDULABLE)
    assert get_cycle(cycle["id"])["loaded_pallet_count"] == 0


def test_chamber_pallet_capacity_is_cumulative_across_the_load_map():
    """PRD 3.5: "The cycle's `loaded_pallet_count` plus the requested
    `pallet_count` must not exceed the chamber's `pallet_capacity`, and the
    requested `pallet_count` must not exceed the lot's
    `available_pallet_count`; either breach is refused with
    `ERR_CHAMBER_CAPACITY_EXCEEDED`."

    Design: Corner/validations/corner_chamber_pallet_capacity_exceeded
    """
    env = build_cycle_scenario(
        stage="loading",
        chamber_overrides={"pallet_capacity": 3},
        lot_overrides={"total_pallet_count": 4},
        pallet_count=2,
        place_indicators=False,
    )
    version = get_cycle(env["cycle"]["id"])["version"]

    rejected = api_client.create_load_position(
        env["cycle"]["id"],
        create_load_position_payload(
            env["lot"]["id"], version, position_index=2, zone="INTERIOR", pallet_count=2
        ),
        operator(),
    )
    validate_error(rejected, ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED)

    accepted = validate_success(
        api_client.create_load_position(
            env["cycle"]["id"],
            create_load_position_payload(
                env["lot"]["id"], version, position_index=2, zone="INTERIOR", pallet_count=1
            ),
            operator(),
        ),
        201,
    )

    assert accepted["pallet_count"] == 1
    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["loaded_pallet_count"] == 3
    assert cycle["load_density_g_per_cm3"] == pytest.approx(0.1000, abs=1e-9)
    lot = get_lot(env["lot"]["id"])
    assert lot["staged_pallet_count"] == 3
    assert lot["available_pallet_count"] == 1


def test_rereading_an_indicator_outside_a_deviation_is_rejected():
    """PRD 3.7: "Recording a reading against an indicator that is already
    `READ` is normally refused with `ERR_INDICATOR_ALREADY_READ` — with one
    deliberate exception."

    Design: Corner/validations/corner_indicator_reread_outside_deviation_rejected
    """
    env = build_cycle_scenario(stage="completed")
    indicator = env["indicators"]["min_zone"][0]
    record_reading(indicator["id"], measured_dose_kgy=28.50)
    assert get_cycle(env["cycle"]["id"])["status"] == "DOSIMETRY_REVIEW"

    response = api_client.record_reading(
        indicator["id"],
        {"measured_dose_kgy": 31.00},
        TEST_USERS["dosimetry_analyst_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INDICATOR_ALREADY_READ)
    stored = fetch_indicator(env["position"]["id"], indicator["id"])
    assert stored["measured_dose_kgy"] == pytest.approx(28.50, abs=0.001)
    assert get_cycle(env["cycle"]["id"])["status"] == "DOSIMETRY_REVIEW"


def test_path_existence_is_checked_before_the_state_precondition():
    """PRD 2.7: "Every identifier in the URL is resolved left to right, and
    each resource type raises its own 404: `ERR_CUSTOMER_NOT_FOUND` for a
    customer segment, `ERR_PRODUCT_NOT_FOUND` for a product,
    `ERR_PERMIT_NOT_FOUND` for an emission permit, `ERR_CHAMBER_NOT_FOUND` for
    a chamber, `ERR_RECIPE_NOT_FOUND` for a cycle recipe,
    `ERR_QUALIFICATION_NOT_FOUND` for a qualification, `ERR_LOT_NOT_FOUND` for
    a lot, `ERR_CYCLE_NOT_FOUND` for a cycle"
    PRD 2.7: "Requests are screened in a strictly ascending order of checks,
    and the **first** check that fails determines the error returned. This
    ordering is part of the contract: a request that violates three rules must
    surface the earliest one."

    Design: Corner/validations/corner_path_existence_outranks_state_precondition
    """
    response = api_client.complete_cycle(NON_EXISTENT_UUID, operator())

    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_FOUND)
