"""Entity creation shapes: seeded ledgers, declared defaults, derived and pinned fields."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.api_client import BatteryApiClient
from test_helpers.assertions import (
    assert_close,
    assert_identity_fields,
    assert_single_resource_envelope,
)
from test_helpers.factories import lead_design_payload, plant_payload, production_lot_payload
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_a_new_plant_seeds_every_ledger_and_derives_an_open_posture(
    api: BatteryApiClient, admin_headers
):
    """Registration answers 201 with the lead inventory seeded and every other ledger at zero.

    "`emission_reserved_g`, `emission_consumed_g`, `lead_in_field_kg`, `lead_recycled_kg`,
    `core_deposit_liability_cents` and `formation_energy_charge_cents` all begin at 0.
    `lead_inventory_kg` begins equal to `lead_initial_inventory_kg`, while `lead_mass_variance_kg`
    and `core_lead_variance_kg` begin at 0.000. `emission_utilization_ratio` begins at 0.0000,
    `open_medical_removal_count` at 0, and `compliance_posture` is derived immediately." The row
    also carries "`version`, an integer that starts at 1 on creation and increments by 1 on every
    accepted mutation of that row."

    Design: Corner/entities/plant_creation_initialises_every_ledger_and_derives_open_posture
    """
    validate_success(api.set_clock(C.CLOCK_START, admin_headers), 200)

    response = api.create_plant(plant_payload(), admin_headers)
    plant = validate_success(response, 201)
    assert_single_resource_envelope(response)
    assert_identity_fields(plant)
    assert plant["version"] == 1

    assert_close(plant["lead_initial_inventory_kg"], 10000.000, "lead_initial_inventory_kg", 3)
    assert_close(plant["lead_inventory_kg"], 10000.000, "lead_inventory_kg", 3)
    assert_close(plant["lead_in_field_kg"], 0.000, "lead_in_field_kg", 3)
    assert_close(plant["lead_recycled_kg"], 0.000, "lead_recycled_kg", 3)
    assert_close(plant["lead_mass_variance_kg"], 0.000, "lead_mass_variance_kg", 3)
    assert_close(plant["core_lead_variance_kg"], 0.000, "core_lead_variance_kg", 3)
    assert_close(plant["emission_reserved_g"], 0.00, "emission_reserved_g", 2)
    assert_close(plant["emission_consumed_g"], 0.00, "emission_consumed_g", 2)
    assert_close(plant["emission_utilization_ratio"], 0.0000, "emission_utilization_ratio", 4)
    assert plant["core_deposit_liability_cents"] == 0
    assert plant["formation_energy_charge_cents"] == 0
    assert plant["open_medical_removal_count"] == 0
    assert plant["permit_status"] == "ACTIVE"
    assert plant["compliance_posture"] == C.POSTURE_OPEN


def test_a_drafted_design_applies_both_declared_defaults_and_derives_its_pack_voltage(
    make_world,
):
    """Omitting the two optional flags yields 1.15 and true while the pack voltage is computed.

    "The formation charge factor expresses ampere-hours returned per ampere-hour nominal during
    formation charging; it defaults to 1.15 and must be at least 1.00 and at most 2.00 with two
    decimal places. The retest-tightening flag defaults to true." Alongside that, "A new design
    starts with `approval_state` `DRAFT`, `revision` 1, `approved_revision` null, and both
    `submitted_by_worker_id` and `approved_by_worker_id` null."

    Design: Corner/entities/cell_design_draft_defaults_and_derived_pack_voltage
    """
    world = make_world(with_design=False)

    design = world.draft_design(
        lead_design_payload(formation_charge_factor=None, retest_tightening_enabled=None)
    )

    assert_close(design["formation_charge_factor"], 1.15, "formation_charge_factor", 2)
    assert design["retest_tightening_enabled"] is True
    assert_close(design["nominal_pack_voltage_v"], 24.0, "nominal_pack_voltage_v", 1)
    assert design["approval_state"] == C.DESIGN_DRAFT
    assert design["revision"] == 1
    assert design["approved_revision"] is None
    assert design["submitted_by_worker_id"] is None
    assert design["approved_by_worker_id"] is None


def test_a_lot_pins_the_approved_revision_and_copies_the_design_chemistry(make_world):
    """A design edited once before approval hands the lot a pinned revision of 2.

    "The lot copies the design's `chemistry` into its own `chemistry` field and pins
    `design_revision_pinned` from the design's `approved_revision`, which is what insulates the lot
    from later editorial revisions." The lot itself opens with no plan at all: "`sample_size` and
    `acceptance_number` both null, because no sampling plan exists until one is drawn."

    Design: Corner/entities/production_lot_pins_the_approved_revision_and_copies_chemistry
    """
    world = make_world(with_design=False)
    design = world.draft_design(lead_design_payload())

    edited = validate_success(
        world.api.update_cell_design(
            design["id"], {"nominal_capacity_ah": 465.0, "rated_cycles": 1500}, world.eng_a
        ),
        200,
    )
    assert edited["revision"] == 2
    assert edited["approval_state"] == C.DESIGN_DRAFT

    approved = world.approve_design(design["id"])
    assert approved["approval_state"] == C.DESIGN_APPROVED
    assert approved["approved_revision"] == 2
    assert approved["approved_by_worker_id"] == world.eng_b_id

    lot = validate_success(
        world.api.create_production_lot(
            production_lot_payload(world.plant_id, design["id"], "LOT-A", 9), world.sup_a
        ),
        201,
    )
    assert lot["design_revision_pinned"] == 2
    assert lot["chemistry"] == C.CHEMISTRY_LEAD_ACID
    assert lot["process_state"] == C.LOT_PLANNED
    assert lot["env_hold_status"] == C.ENV_HOLD_CLEAR
    assert lot["hold_reason"] is None
    assert lot["retest_count"] == 0
    assert lot["sampling_plan_revision"] == 0
    assert lot["sample_size"] is None
    assert lot["acceptance_number"] is None
    assert lot["lot_capacity_yield_pct"] is None
    assert lot["released_at"] is None
    assert lot["last_test_recorded_by_worker_id"] is None
    for counter in (
        "completed_test_count",
        "failed_test_count",
        "passed_cycle_life_count",
        "failed_formation_count",
    ):
        assert lot[counter] == 0, f"{counter} should open at 0: {lot[counter]}"


def test_the_worker_roster_pages_over_the_filtered_set_not_the_page(
    api: BatteryApiClient, admin_headers
):
    """Three workers page as 2 then 1, and a filtered read counts only the filtered rows.

    "`total_count` is the number of rows matching the filters before the page window is applied,
    and `has_more` is true exactly when `offset` plus the number of returned rows is strictly less
    than `total_count`." The unfiltered `limit` is the declared default: "`limit` defaults to 10,
    has a minimum accepted value of 1, and a maximum accepted value of 100."

    Design: Corner/entities/worker_listing_paginates_with_total_count_and_has_more
    """
    validate_success(api.set_clock(C.CLOCK_START, admin_headers), 200)
    plant = validate_success(api.create_plant(plant_payload(), admin_headers), 201)
    for name, job_class in (
        ("Ada Engineer", "ENGINEER"),
        ("Cara Supervisor", "PRODUCTION"),
        ("Sam Safety", "SAFETY"),
    ):
        validate_success(
            api.create_worker(
                {
                    "plant_id": plant["id"],
                    "full_name": name,
                    "job_class": job_class,
                    "hire_date": C.WORKER_HIRE_DATE,
                },
                admin_headers,
            ),
            201,
        )

    page_one, meta_one = validate_paginated(
        api.list_workers(admin_headers, {"plant_id": plant["id"], "limit": 2, "offset": 0})
    )
    assert len(page_one) == 2, page_one
    assert meta_one["total_count"] == 3
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api.list_workers(admin_headers, {"plant_id": plant["id"], "limit": 2, "offset": 2})
    )
    assert len(page_two) == 1, page_two
    assert meta_two["total_count"] == 3
    assert meta_two["offset"] == 2
    assert meta_two["has_more"] is False

    filtered, meta_three = validate_paginated(
        api.list_workers(admin_headers, {"plant_id": plant["id"], "job_class": "SAFETY"})
    )
    assert len(filtered) == 1, filtered
    assert filtered[0]["full_name"] == "Sam Safety"
    assert meta_three["total_count"] == 1
    assert meta_three["limit"] == C.PAGINATION_DEFAULT_LIMIT
    assert meta_three["has_more"] is False

    for row in page_one + page_two:
        assert row["removal_status"] == C.REMOVAL_ACTIVE
        assert row["removal_count"] == 0
        assert_close(row["exposure_index"], 0.00, "exposure_index", 2)
        assert row["exposure_index_variant"] == "NONE"
        assert row["last_sample_at"] is None


def test_reading_a_battery_unit_that_was_never_created_is_a_not_found(
    api: BatteryApiClient, admin_headers
):
    """An unknown but well-formed unit id answers the path-existence code, not an empty 200.

    "Formation bays, test chambers and chargers addressed by path id yield
    `ERR_FORMATION_BAY_NOT_FOUND`, `ERR_TEST_CHAMBER_NOT_FOUND` and `ERR_CHARGER_NOT_FOUND`
    respectively" sits in the same tier as the unit code named beside it: "a request naming a unit
    that does not exist fails with `ERR_BATTERY_UNIT_NOT_FOUND` (HTTP 404) before any core-return
    state is inspected."

    Design: Corner/entities/battery_unit_get_with_unknown_id_returns_not_found
    """
    validate_success(api.set_clock(C.CLOCK_START, admin_headers), 200)

    validate_error(
        api.get_battery_unit(UNKNOWN_ID, admin_headers), E.ERR_BATTERY_UNIT_NOT_FOUND
    )

    rows, meta = validate_paginated(api.list_battery_units(admin_headers))
    assert rows == [], rows
    assert meta["total_count"] == 0


def test_a_design_body_omitting_rated_cycles_is_a_schema_failure(make_world):
    """`rated_cycles` carries no default, so leaving it out is refused before anything derives.

    The drafting payload carries "the `rated_cycles` and `warranty_months` (each at least 1)" as
    required fields, and tier 3 covers "Required fields present, no unknown fields, enum members
    recognised, numeric bounds honoured, and every discriminated field obeying its discriminator;
    otherwise `ERR_VALIDATION`."

    Design: Corner/entities/cell_design_missing_required_rated_cycles_is_rejected
    """
    world = make_world(with_design=False)

    validate_error(
        world.api.create_cell_design(
            lead_design_payload(rated_cycles=None), world.eng_a
        ),
        E.ERR_VALIDATION,
    )

    rows, meta = validate_paginated(world.api.list_cell_designs(world.eng_a))
    assert rows == [], rows
    assert meta["total_count"] == 0


def test_an_unrecognised_chemistry_member_fails_the_enum_check_not_the_plate_rule(make_world):
    """A chemistry outside the two declared members never reaches the plate-coherence rule.

    Tier 3 refuses a body whose "enum members recognised" condition fails with `ERR_VALIDATION`,
    and the design's chemistry is declared as "the `chemistry` as either `LEAD_ACID` or
    `LITHIUM_LFP`", so `NICKEL_IRON` is not a member at all.

    Design: Corner/entities/cell_design_invalid_chemistry_enum_is_rejected
    """
    world = make_world(with_design=False)

    validate_error(
        world.api.create_cell_design(
            lead_design_payload("CD-NICKEL-1", chemistry="NICKEL_IRON"), world.eng_a
        ),
        E.ERR_VALIDATION,
    )

    rows, _ = validate_paginated(world.api.list_cell_designs(world.eng_a))
    assert rows == [], rows


def test_an_unknown_cell_design_on_a_lot_body_resolves_before_the_approval_gate(make_world):
    """The body foreign key resolves first, so an unknown design is a 404 not an approval refusal.

    "The body keys that participate are `plant_id`, `cell_design_id`, `lot_id`, `bay_id`,
    `chamber_id`, `assembly_id`, `sizing_request_id` and `supersedes_design_id`; each resolves to
    the not-found code of its own entity type" -- here "a missing design named by either
    `cell_design_id` or `supersedes_design_id` to `ERR_CELL_DESIGN_NOT_FOUND`".

    Design: Corner/entities/lot_creation_with_unknown_cell_design_id_returns_not_found
    """
    world = make_world(with_design=False)

    validate_error(
        world.api.create_production_lot(
            production_lot_payload(world.plant_id, UNKNOWN_ID, "LOT-A", 9), world.sup_a
        ),
        E.ERR_CELL_DESIGN_NOT_FOUND,
    )

    rows, meta = validate_paginated(world.api.list_production_lots(world.sup_a))
    assert rows == [], rows
    assert meta["total_count"] == 0


def test_an_exposure_sample_stamps_its_own_index_variant_and_removal_flag(world: World):
    """The client supplies no derived figure; the sample row carries its own snapshot.

    "The sample row itself is stamped with `resulting_worker_index`, `resulting_variant` and the
    boolean `triggered_removal`, and the worker's `last_sample_at` is set to the latest sampling
    instant." A single 480-minute reading of 20.00 gives a time-weighted average of 20.000, an
    index of 40.00 against the 50 microgram limit, and no removal.

    Design: Corner/entities/exposure_sample_stamps_its_own_derived_index_and_variant
    """
    pat_id = world.add_worker("Pat Paster", "PRODUCTION")

    sample = world.record_air(pat_id, C.CLOCK_START, 20.00, 480)
    assert_close(sample["resulting_worker_index"], 40.00, "resulting_worker_index", 2)
    assert sample["resulting_variant"] == C.VARIANT_AIR
    assert sample["triggered_removal"] is False

    worker = world.read_worker(pat_id)
    assert_close(worker["exposure_index"], 40.00, "exposure_index", 2)
    assert worker["exposure_index_variant"] == C.VARIANT_AIR
    assert worker["removal_status"] == C.REMOVAL_ACTIVE
    assert worker["removal_count"] == 0
    assert worker["last_sample_at"].startswith("2026-09-01T00:00:00")

    plant = world.read_plant()
    assert plant["open_medical_removal_count"] == 0
    assert plant["compliance_posture"] == C.POSTURE_OPEN
