"""
The shape of the ground truth: production blocks, the append-only water
register, and the field-packed lot record that traces back to both.

These tests exercise the declared field sets, the derived-not-supplied fields
and the body-validation tier that guards them, all against PRD sections 2.2,
2.3, 2.4, 2.7, 3.1, 3.2, 3.3 and 3.6.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers import test_users as u


def test_block_registration_returns_every_declared_field_and_starts_restricted(api):
    """
    A newly registered block answers 201 with the whole unusable starting row.

    PRD 3.1: "On registration its `water_sample_count` is 0, its `water_geomean_mpn` and `last_sample_date` carry no value, its `water_status` is `NO_SAMPLES`, its `manual_quarantine_active` flag is false with `quarantined_by_user_id` and `quarantine_reason_code` both empty, and its `food_safety_posture` is `RESTRICTED`."

    PRD 2.4: "Ten of the eleven resource families additionally carry a full audit triple: `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with exactly three fractional digits, and `version`, an integer that begins at 1 when the resource is created and is incremented by exactly 1 on every mutation of that resource."

    Design: Corner/entities/block_create_returns_every_declared_field_and_starts_restricted
    """
    payload = f.block_payload(
        name="BLK-E1",
        variety="STRAWBERRY",
        acres=12.50,
        planting_year=2023,
        irrigation_source_code="WELL-E1",
    )
    response = api.create_block(payload, u.HARVEST_MANAGER)
    block = validate_success(response, 201)
    a.assert_object_response(response)
    a.assert_audit_triple(block, "block")

    assert block["name"] == "BLK-E1"
    a.assert_status(block, "variety", "STRAWBERRY")
    a.assert_pounds(block["acres"], 12.50, "block.acres")
    assert block["planting_year"] == 2023
    assert block["irrigation_source_code"] == "WELL-E1"

    assert block["water_sample_count"] == 0
    a.assert_unset(block, "water_geomean_mpn", "block")
    a.assert_unset(block, "last_sample_date", "block")
    a.assert_status(block, "water_status", "NO_SAMPLES")
    assert block["manual_quarantine_active"] is False
    a.assert_unset(block, "quarantined_by_user_id", "block")
    a.assert_unset(block, "quarantine_reason_code", "block")
    a.assert_status(block, "food_safety_posture", "RESTRICTED")
    assert block["version"] == 1


def test_block_read_returns_the_stored_row_with_recomputed_water_fields(api):
    """
    One passing sample makes a block PROVISIONAL and therefore CLEARED, and the
    single-block read shows the recomputation.

    PRD 3.1: "Otherwise, if fewer than three samples are in the window, the status is `PROVISIONAL`, because one or two readings are not enough evidence of compliance."

    PRD 3.1 on posture: "Otherwise, if `water_status` is `PROVISIONAL` or `COMPLIANT`, the posture is `CLEARED`."

    Design: Corner/entities/block_get_returns_the_stored_row_with_its_recomputed_water_fields
    """
    block = x.register_block(
        api,
        name="BLK-E2",
        variety="STRAWBERRY",
        acres=9.00,
        planting_year=2021,
        irrigation_source_code="WELL-E2",
    )
    x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )

    response = api.get_block(block["id"], u.PACKHOUSE_OPERATOR)
    stored = validate_success(response, 200)
    a.assert_object_response(response)

    assert stored["id"] == block["id"]
    assert stored["name"] == "BLK-E2"
    assert stored["water_sample_count"] == 1
    a.assert_geomean(stored["water_geomean_mpn"], 40.0)
    assert stored["last_sample_date"] == "2026-07-20"
    a.assert_status(stored, "water_status", "PROVISIONAL")
    a.assert_status(stored, "food_safety_posture", "CLEARED")
    assert stored["manual_quarantine_active"] is False
    assert stored["version"] == 2


def test_blocks_list_filters_by_variety_and_reports_pagination_fields(api):
    """
    The block list narrows to one variety and reports the pre-pagination count.

    PRD 2.11: "Blocks may be filtered by `variety`, by `food_safety_posture` or by `water_status`."

    PRD 2.3: "The `meta` object of a list response carries four pagination fields: `limit` and `offset` echoing the effective values used for the page, `total_count` giving the number of records that match the filter before pagination is applied, and `has_more` reporting whether any matching record remains beyond the current page."

    Design: Corner/entities/blocks_list_filters_by_variety_and_reports_pagination_fields
    """
    first = x.register_block(api, name="BLK-E3A", variety="STRAWBERRY")
    second = x.register_block(api, name="BLK-E3B", variety="STRAWBERRY")
    third = x.register_block(api, name="BLK-E3C", variety="BLUEBERRY")

    response = api.list_blocks(u.SALES_MANAGER, {"variety": "STRAWBERRY"})
    rows, meta = validate_paginated(response)
    a.assert_array_response(response)
    a.assert_page_meta(
        meta,
        expected_total=2,
        expected_limit=10,
        expected_offset=0,
        expected_has_more=False,
    )

    returned = a.ids_of(rows)
    assert first["id"] in returned
    assert second["id"] in returned
    assert third["id"] not in returned


def test_crew_recruitment_without_supervisor_user_id_is_invalid_request(api):
    """
    A crew body missing the required `supervisor_user_id` is a body-shape
    failure, and nothing is persisted.

    PRD 2.7 rule 10: "On every write endpoint, every field the endpoint declares as required is present and of the declared JSON type, otherwise `ERR_INVALID_REQUEST`."

    PRD 3.2: "The request carries a crew `name` of 1 to 80 characters, a `labor_program` of either `DOMESTIC` or `H2A`, a `supervisor_user_id` of 1 to 64 characters naming the operator who will own this crew's tallies, a contracted `planned_head_count` between 1 and 60, and the engagement dates `contract_start_date` and `contract_end_date`, the latter on or after the former."

    Design: Corner/entities/crew_create_missing_supervisor_user_id_returns_invalid_request
    """
    payload = {
        "name": "CREW-E4",
        "labor_program": "DOMESTIC",
        "planned_head_count": 4,
        "contract_start_date": "2026-07-01",
        "contract_end_date": "2026-09-30",
    }
    response = api.create_crew(payload, u.HARVEST_MANAGER)
    validate_error(response, e.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(api.list_crews(u.HARVEST_MANAGER))
    a.assert_page_meta(meta, expected_total=0)


def test_picker_registration_without_hygiene_training_leaves_expiry_unset(api):
    """
    Omitting `hygiene_training_on` is legitimate for an untrained worker: the
    expiry stays unset while the crew still advances to STAFFED.

    PRD 3.2: "Two things are derived at registration: the picker's `labor_program` is copied from the parent crew, and `hygiene_training_expires_on` is set to `hygiene_training_on` plus 365 days — one year of validity — remaining unset while `hygiene_training_on` is unset."

    PRD 3.2: "Registering a picker recomputes the crew's `picker_count` and increments the crew's `version` by 1, and when that count moves from zero to one the crew advances `RECRUITING → STAFFED`."

    Design: Corner/entities/picker_create_omitting_hygiene_training_on_applies_null_default
    """
    crew = x.recruit_crew(
        api,
        name="CREW-E5",
        labor_program="H2A",
        supervisor_user_id=u.SUP_1,
        planned_head_count=2,
    )

    response = api.create_picker(
        {"crew_id": crew["id"], "full_name": "Untrained Worker"},
        u.CREW_SUPERVISOR,
    )
    picker = validate_success(response, 201)
    a.assert_audit_triple(picker, "picker")

    a.assert_unset(picker, "hygiene_training_on", "picker")
    a.assert_unset(picker, "hygiene_training_expires_on", "picker")
    a.assert_status(picker, "labor_program", "H2A")
    assert picker["total_clamshells_lifetime"] == 0
    a.assert_hours(picker["total_hours_lifetime"], 0.00, "picker.total_hours_lifetime")
    a.assert_rate(picker["avg_lbs_per_hour"], 0.00, "picker.avg_lbs_per_hour")

    stored_crew = x.read_crew(api, crew["id"])
    assert stored_crew["picker_count"] == 1
    a.assert_status(stored_crew, "status", "STAFFED")
    assert stored_crew["support_plan_complete"] is False
    a.assert_unset(stored_crew, "housing_unit_code", "crew")
    assert stored_crew["beds_confirmed"] == 0


def test_fruit_lot_derives_net_packed_lbs_and_traceability_code(api):
    """
    A packed lot computes its own pounds and its own traceability code, and
    pushes the pounds back onto its window.

    PRD 3.6: "The lot's `net_packed_lbs` is `clamshell_count` multiplied by `clamshell_net_weight_lbs`, rounded half up to two decimals, and its `available_lbs` starts equal to that figure."

    PRD 3.6: "The sequence is one greater than the number of lots that already share the same `block_id`, `pick_date` and `grade`, counted in `created_at` ascending order, so the day's second grade-A lot off the same block is `-002`."

    Design: Corner/entities/fruit_lot_computed_fields_derive_net_packed_lbs_and_traceability_code
    """
    block = x.register_block(
        api,
        name="BLK-CF1",
        variety="STRAWBERRY",
        acres=7.00,
        planting_year=2022,
        irrigation_source_code="WELL-CF1",
    )
    crew = x.recruit_crew(api, name="CREW-CF1")
    window = x.plan_window(
        api,
        block["id"],
        crew["id"],
        start_at="2026-08-03T06:00:00Z",
        end_at="2026-08-03T18:00:00Z",
        forecast_brix=8.5,
        planned_volume_lbs=150.00,
        piece_rate_cents_per_clamshell=45,
        clamshell_net_weight_lbs=0.75,
    )

    response = api.create_fruit_lot(
        f.fruit_lot_payload(
            window["id"],
            block["id"],
            variety="STRAWBERRY",
            grade="B",
            clamshell_count=47,
            clamshell_net_weight_lbs=0.75,
            pick_date="2026-08-03",
            pack_completed_at="2026-08-03T09:00:00Z",
            field_pulp_temp_f=66.0,
        ),
        u.PACKHOUSE_OPERATOR,
    )
    lot = validate_success(response, 201)
    a.assert_audit_triple(lot, "lot")

    a.assert_pounds(lot["net_packed_lbs"], 35.25, "lot.net_packed_lbs")
    a.assert_pounds(lot["available_lbs"], 35.25, "lot.available_lbs")
    a.assert_pounds(lot["allocated_lbs"], 0.00, "lot.allocated_lbs")
    a.assert_pounds(lot["repack_out_lbs"], 0.00, "lot.repack_out_lbs")
    a.assert_pounds(lot["cull_lbs"], 0.00, "lot.cull_lbs")
    a.assert_pounds(lot["optical_reject_lbs"], 0.00, "lot.optical_reject_lbs")
    assert lot["traceability_code"] == "BLK-CF1-20260803-B-001"
    a.assert_status(lot, "variety", "STRAWBERRY")
    a.assert_status(lot, "cold_chain_status", "PACKED")
    a.assert_status(lot, "disposition_status", "UNCOMMITTED")
    assert lot["food_safety_hold"] is False
    a.assert_unset(lot, "source_lot_id", "lot")
    a.assert_unset(lot, "cooling_tunnel_id", "lot")
    a.assert_unset(lot, "forecast_shelf_life_days", "lot")
    a.assert_unset(lot, "verified_shelf_life_days", "lot")
    a.assert_unset(lot, "shelf_life_expires_on", "lot")

    stored_window = x.read_window(api, window["id"])
    a.assert_pounds(stored_window["packed_lbs"], 35.25, "window.packed_lbs")


def test_block_registration_ignores_client_supplied_posture_and_counters(api):
    """
    Derived food-safety fields, the water counters, `version` and `id` are all
    server-owned; supplying them in the body changes nothing.

    PRD 3.1: "A block's `food_safety_posture` is recomputed at the end of every call that stores a water sample for it or toggles its manual hold, and it is never accepted as an input."

    PRD 2.4: "Every resource the API creates is identified by an `id`, which is a server-minted UUID carrying no type prefix and never supplied by the client."

    Design: Corner/entities/block_create_with_client_supplied_posture_and_counters_input_ignored
    """
    payload = f.block_payload(
        name="BLK-E7",
        variety="STRAWBERRY",
        acres=10.00,
        planting_year=2022,
        irrigation_source_code="WELL-E7",
        food_safety_posture="CLEARED",
        water_status="COMPLIANT",
        manual_quarantine_active=True,
        water_sample_count=9,
        version=99,
        id="client-supplied-id",
    )
    block = validate_success(api.create_block(payload, u.HARVEST_MANAGER), 201)

    a.assert_status(block, "food_safety_posture", "RESTRICTED")
    a.assert_status(block, "water_status", "NO_SAMPLES")
    assert block["manual_quarantine_active"] is False
    assert block["water_sample_count"] == 0
    assert block["version"] == 1
    assert block["id"] != "client-supplied-id"
    a.assert_identifier(block["id"], "block.id")


def test_block_registration_with_undeclared_variety_is_invalid_enum(api):
    """
    A variety outside the four declared members is an enumeration failure.

    PRD 2.7 rule 11: "Enum-typed body fields carry a declared value — `variety` is one of `STRAWBERRY`, `BLUEBERRY`, `RASPBERRY` or `BLACKBERRY`; `labor_program` is `DOMESTIC` or `H2A`; `grade` is `A`, `B` or `CULL` — otherwise `ERR_INVALID_ENUM`; this applies to block registration, crew recruitment, fruit-lot creation and buyer-commitment registration."

    Design: Corner/entities/block_create_with_undeclared_variety_returns_invalid_enum
    """
    response = api.create_block(
        f.block_payload(name="BLK-E8", variety="GOOSEBERRY"), u.HARVEST_MANAGER
    )
    validate_error(response, e.ERR_INVALID_ENUM, 400)

    _, meta = validate_paginated(api.list_blocks(u.HARVEST_MANAGER))
    a.assert_page_meta(meta, expected_total=0)


def test_water_sample_with_zero_mpn_is_out_of_range(api):
    """
    A most-probable-number of 0 sits below the declared floor of 1, so the
    sample is refused and the block's register stays empty.

    PRD 3.1: "A `FoodSafetyOfficer` records one agricultural-water sample at a time, supplying the `block_id` of the block whose irrigation source was drawn, the `sample_date` on which it was drawn as a calendar date, and `generic_ecoli_mpn`, the generic *E. coli* most-probable-number per 100 mL, which must be at least 1 and no more than 100000."

    PRD 2.7 rule 12: "Numeric body fields respect their declared ranges, otherwise `ERR_VALUE_OUT_OF_RANGE`, on every write endpoint: `acres` greater than zero; `generic_ecoli_mpn` at least 1; `hours_worked` greater than zero and at most 16.00; `clamshells_filled` and `culled_clamshells` each zero or greater; `piece_rate_cents_per_clamshell` at least 1; `clamshell_net_weight_lbs` greater than zero; `clamshell_count` at least 1; `pallet_slots` at least 1; `slot_capacity` at least 1; `allocated_lbs` greater than zero; `volume_commitment_lbs` greater than zero; `price_cents_per_lb` at least 1; `shelf_life_guarantee_days` at least 1; `planned_head_count` at least 1; and `vehicle_seats` and `beds_confirmed` each zero or greater."

    Design: Corner/entities/water_test_create_with_zero_mpn_returns_value_out_of_range
    """
    block = x.register_block(api, name="BLK-E9")

    response = api.create_water_test(
        f.water_test_payload(
            block["id"], sample_date="2026-07-25", generic_ecoli_mpn=0
        ),
        u.FOOD_SAFETY_OFFICER,
    )
    validate_error(response, e.ERR_VALUE_OUT_OF_RANGE, 400)

    stored = x.read_block(api, block["id"])
    assert stored["water_sample_count"] == 0
    a.assert_status(stored, "water_status", "NO_SAMPLES")
    assert stored["version"] == 1


def test_harvest_window_with_end_before_start_is_invalid_date_range(api):
    """
    A window whose `end_at` precedes its `start_at` is a paired-instant
    ordering failure, reported before any scheduling rule runs.

    PRD 2.7 rule 14: "Paired instants and dates inside one body are correctly ordered, otherwise `ERR_INVALID_DATE_RANGE`: `end_at` strictly after `start_at` on window planning; `period_end_date` on or after `period_start_date` on payroll-run creation; `window_end_date` on or after `window_start_date` on commitment registration; `planned_cool_end_at` strictly after `cool_start_at` when cooling starts; and `contract_end_date` on or after `contract_start_date` on crew recruitment."

    Design: Corner/entities/harvest_window_create_with_end_before_start_returns_invalid_date_range
    """
    block = x.register_block(api, name="BLK-E10")
    crew = x.recruit_crew(api, name="CREW-E10")

    response = api.create_harvest_window(
        f.harvest_window_payload(
            block["id"],
            crew["id"],
            start_at="2026-08-03T18:00:00Z",
            end_at="2026-08-03T06:00:00Z",
        ),
        u.HARVEST_MANAGER,
    )
    validate_error(response, e.ERR_INVALID_DATE_RANGE, 400)

    _, meta = x.list_windows(api, block_id=block["id"])
    a.assert_page_meta(meta, expected_total=0)


def test_water_sample_read_carries_no_version_or_updated_at(api):
    """
    The water register is append-only, so a sample read back carries the audit
    pair only — no `updated_at` and no `version`.

    PRD 2.4: "A water sample carries only `id` and `created_at`."

    PRD 2.4: "It has no `updated_at` and no `version` field at all, there is no update endpoint and no delete endpoint for it, and a sample once recorded can never be edited out of the rolling window that determines a block's compliance."

    Design: Corner/entities/water_test_is_append_only_and_carries_no_version_field
    """
    block = x.register_block(api, name="BLK-E11", variety="BLUEBERRY")
    sample = x.record_water_sample(
        api, block["id"], sample_date="2026-07-20", generic_ecoli_mpn=40
    )

    response = api.get_water_test(sample["id"], u.HARVEST_MANAGER)
    stored = validate_success(response, 200)
    a.assert_object_response(response)
    a.assert_water_register_shape(stored)

    assert stored["block_id"] == block["id"]
    assert stored["sample_date"] == "2026-07-20"
    assert stored["generic_ecoli_mpn"] == 40
    assert stored["single_sample_exceedance"] is False
    a.assert_status(stored, "resulting_water_status", "PROVISIONAL")
    assert stored["recorded_by_user_id"] == u.FSO_1


def test_water_sample_against_unknown_block_is_not_found(api):
    """
    A body `block_id` that resolves to nothing is a 404 on the water-sample
    write, and the surviving block's register is untouched.

    PRD 2.7 rule 16: "A body `block_id` resolves to a `Block` (`ERR_BLOCK_NOT_FOUND`) on water-sample recording, window planning and fruit-lot creation."

    Design: Corner/entities/water_test_create_with_unknown_block_id_returns_not_found
    """
    block = x.register_block(api, name="BLK-E12", variety="RASPBERRY")

    response = api.create_water_test(
        f.water_test_payload(
            NON_EXISTENT_UUID, sample_date="2026-07-25", generic_ecoli_mpn=40
        ),
        u.FOOD_SAFETY_OFFICER,
    )
    validate_error(response, e.ERR_BLOCK_NOT_FOUND, 404)

    _, meta = validate_paginated(
        api.list_water_tests(u.FOOD_SAFETY_OFFICER, {"block_id": block["id"]})
    )
    a.assert_page_meta(meta, expected_total=0)
