"""RBAC corners: the exclusive operations, the shared reads, and both duty splits.

The role gate, the acting-worker gate and the job-class gate are three
independent axes, and these tests keep them apart: the same endpoint succeeds
for its own role and answers `ERR_ROLE_NOT_PERMITTED` for every other one, and
the two segregation rules key on stored worker identifiers rather than on roles.
"""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.api_client import BatteryApiClient
from test_helpers.assertions import assert_assembly_axes, assert_close
from test_helpers.factories import (
    abort_payload,
    air_sample_payload,
    assembly_payload,
    charger_payload,
    disposition_payload,
    env_hold_payload,
    lead_design_payload,
    plant_payload,
    production_lot_payload,
    review_action_payload,
    sizing_request_payload,
    torque_verification_payload,
    watering_log_payload,
    worker_payload,
)
from test_helpers.fixtures import World
from test_helpers.test_users import make_headers

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

GHOST_WORKER = "11111111-1111-1111-1111-111111111111"
GHOST_PLANT = "22222222-2222-2222-2222-222222222222"
GHOST_DESIGN = "33333333-3333-3333-3333-333333333333"
GHOST_LOT = "44444444-4444-4444-4444-444444444444"
GHOST_ASSEMBLY = "55555555-5555-5555-5555-555555555555"
GHOST_RUN = "66666666-6666-6666-6666-666666666666"
GHOST_UNIT = "77777777-7777-7777-7777-777777777777"


def test_each_role_performs_its_own_exclusive_operation_in_one_session(
    world: World, fleet_headers, warranty_headers
):
    """Seven roles, seven operations that only they may call, all succeeding side by side.

    "Authorisation is exactly as listed here: a role absent from an endpoint's row is refused with
    `ERR_ROLE_NOT_PERMITTED`, and the behavioural contract for each endpoint is the section of §3
    that describes it." For the four entity-backed roles the identifier is resolved as well: "When
    `X-User-Role` is `DesignEngineer`, `ProductionSupervisor`, `QualityInspector`, or
    `SafetyOfficer`, `X-User-ID` is the `id` of the acting `Worker` row". The job-class gate is a
    property of that worker and it names the actor, never the subject: it "Applies to exactly three
    operations: `POST /cell-designs/{id}/review-actions` when the action is `APPROVE` (requires
    `ENGINEER`), `POST /workers/{id}/exposure-samples` (requires `SAFETY`), and `POST
    /production-lots/{id}/disposition` when the action is `RELEASE` (requires `QUALITY`)."

    Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operation
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-R", 9)
    assembly = world.add_assembly(lot["id"], "ASM-R1")

    second_plant = validate_success(
        world.api.create_plant(
            plant_payload(
                name="Second Works",
                site_code="PLTSEC",
                licensed_chemistries=[C.CHEMISTRY_LEAD_ACID],
                monthly_lead_emission_permit_g=50000.00,
                peak_tariff_cents_per_kwh=30.00,
                offpeak_tariff_cents_per_kwh=18.00,
                lead_initial_inventory_kg=5000.000,
            ),
            world.admin,
        ),
        201,
    )
    assert second_plant["site_code"] == "PLTSEC"

    drafted = validate_success(
        world.api.create_cell_design(
            lead_design_payload(
                "CD-LEAD-330",
                plate_type=C.PLATE_FLAT_PASTED,
                nominal_capacity_ah=330.0,
                rated_cycles=1200,
                warranty_months=36,
                pack_weight_kg=700.0,
                lead_content_kg=220.000,
                formation_charge_factor=1.40,
                list_price_cents=400000,
            ),
            world.eng_a,
        ),
        201,
    )
    assert drafted["approval_state"] == C.DESIGN_DRAFT
    assert drafted["revision"] == 1

    second_lot = validate_success(
        world.api.create_production_lot(
            production_lot_payload(world.plant_id, world.design_id, "LOT-R2", 12),
            world.sup_a,
        ),
        201,
    )
    assert second_lot["process_state"] == C.LOT_PLANNED

    torqued = validate_success(
        world.api.record_verification(
            assembly["id"], torque_verification_payload(20.0, 12), world.qa_a
        ),
        200,
    )
    assert_assembly_axes(
        torqued,
        torque_status=C.AXIS_PASS,
        insulation_status=C.AXIS_PENDING,
        certification_status=C.CERT_PENDING,
    )

    sample = validate_success(
        world.api.create_exposure_sample(
            world.sup_a_id,
            air_sample_payload("2026-08-31T16:00:00Z", 12.0, 480),
            world.saf_a,
        ),
        201,
    )
    assert_close(sample["resulting_worker_index"], 24.00, "resulting_worker_index", 2)
    assert sample["resulting_variant"] == C.VARIANT_AIR
    assert sample["triggered_removal"] is False

    charger = validate_success(
        world.api.create_charger(charger_payload("CH-R1", output_amps=50.0), fleet_headers),
        201,
    )
    assert charger["charger_status"] == "AVAILABLE"

    units, unit_meta = validate_paginated(
        world.api.list_battery_units(warranty_headers, {"limit": 50, "offset": 0})
    )
    assert units == [], units
    assert unit_meta["total_count"] == 0


def test_the_lot_list_is_shared_by_six_roles_and_denied_to_the_seventh(
    world: World, fleet_headers, warranty_headers
):
    """The same collection read is identical for six roles, refused for the one absent from its row.

    "**Tier 2 -- authorisation.** The acting role appears in the addressed endpoint's authorised-role
    list; otherwise `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint." The list is per endpoint
    rather than per entity: "Authorisation is exactly as listed here: a role absent from an
    endpoint's row is refused with `ERR_ROLE_NOT_PERMITTED`, and the behavioural contract for each
    endpoint is the section of §3 that describes it." `GET /production-lots` names six roles and
    omits `FleetEngineer`, while `GET /plants/{id}` names all seven.

    Design: Corner/rbac/shared_reads_are_permitted_to_their_whole_role_list_and_denied_outside_it
    """
    lot = world.lot_in_state(C.LOT_PLANNED, "LOT-R", 9)
    params = {"plant_id": world.plant_id, "limit": 50, "offset": 0}

    permitted = [
        world.admin,
        world.sup_a,
        world.qa_a,
        world.saf_a,
        world.eng_a,
        warranty_headers,
    ]
    seen = []
    for headers in permitted:
        rows, meta = validate_paginated(world.api.list_production_lots(headers, params))
        assert meta["total_count"] == 1, rows
        assert [row["id"] for row in rows] == [lot["id"]]
        seen.append(rows[0])
    for row in seen[1:]:
        assert row == seen[0], f"a shared read must not vary by role: {row} != {seen[0]}"

    validate_error(
        world.api.list_production_lots(fleet_headers, params), E.ERR_ROLE_NOT_PERMITTED
    )

    for headers in (fleet_headers, warranty_headers):
        plant = validate_success(world.api.get_plant(world.plant_id, headers), 200)
        assert plant["id"] == world.plant_id
        assert plant["site_code"] == C.PLANT_SITE_CODE


def test_thirteen_exclusive_writes_are_denied_before_any_id_is_resolved(
    api: BatteryApiClient, admin_headers, fleet_headers, warranty_headers
):
    """Every path id, body key and acting identifier is unresolvable, and the answer is still 403.

    "When several checks would fail on the same request, exactly one error is returned: the one
    belonging to the **lowest-numbered tier** below that fails." Tier 2 is the role gate -- "The
    acting role appears in the addressed endpoint's authorised-role list; otherwise
    `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint." -- and it sits above payload schema
    (tier 3), acting-worker existence (tier 4) and "**Tier 7 -- path identifier existence,**
    validated left to right". Privilege is not a ladder either: `POST /chargers` names only
    `FleetEngineer`, so even a `PlantAdmin` is refused there.

    Design: Corner/rbac/exclusive_operations_are_denied_to_every_other_role
    """
    validate_success(api.set_clock(C.CLOCK_START, admin_headers), 200)
    supervisor = make_headers(C.ROLE_PRODUCTION_SUPERVISOR, GHOST_WORKER)
    engineer = make_headers(C.ROLE_DESIGN_ENGINEER, GHOST_WORKER)
    inspector = make_headers(C.ROLE_QUALITY_INSPECTOR, GHOST_WORKER)
    officer = make_headers(C.ROLE_SAFETY_OFFICER, GHOST_WORKER)

    attempts = [
        api.create_plant(
            plant_payload(name="Rogue Works", site_code="PLTROGUE"), supervisor
        ),
        api.create_worker(
            worker_payload(GHOST_PLANT, "Rogue Hire", "ENGINEER"), engineer
        ),
        api.create_cell_design(lead_design_payload("CD-ROGUE"), fleet_headers),
        api.create_production_lot(
            production_lot_payload(GHOST_PLANT, GHOST_DESIGN, "LOT-ROGUE", 9), inspector
        ),
        api.env_hold_lot(
            GHOST_LOT, env_hold_payload("HOLD", C.HOLD_REASON_OPERATOR), supervisor
        ),
        api.create_battery_assembly(
            assembly_payload(GHOST_LOT, "ASM-ROGUE"), warranty_headers
        ),
        api.record_verification(
            GHOST_ASSEMBLY, torque_verification_payload(20.0, 12), supervisor
        ),
        api.create_exposure_sample(
            GHOST_WORKER, air_sample_payload("2026-08-31T16:00:00Z", 12.0, 480), inspector
        ),
        api.abort_formation_run(
            GHOST_RUN, abort_payload(abort_reason="not my call"), inspector
        ),
        api.create_charger(charger_payload("CH-ROGUE", output_amps=50.0), admin_headers),
        api.create_sizing_request(
            sizing_request_payload(GHOST_PLANT, application_name="Rogue Fleet"),
            warranty_headers,
        ),
        api.create_maintenance_log(
            GHOST_UNIT, watering_log_payload("2026-08-31T00:00:00Z"), supervisor
        ),
        api.set_plant_permit(GHOST_PLANT, {"permit_status": "SUSPENDED"}, officer),
    ]
    assert len(attempts) == 13
    for response in attempts:
        validate_error(response, E.ERR_ROLE_NOT_PERMITTED)

    plants, plant_meta = validate_paginated(api.list_plants(admin_headers))
    assert plants == [], plants
    assert plant_meta["total_count"] == 0
    workers, worker_meta = validate_paginated(api.list_workers(admin_headers))
    assert workers == [], workers
    assert worker_meta["total_count"] == 0
    chargers, charger_meta = validate_paginated(api.list_chargers(fleet_headers))
    assert chargers == [], chargers
    assert charger_meta["total_count"] == 0


def test_the_review_bar_follows_the_submitter_across_a_revision_loop(make_world):
    """Ada is barred, then Ben is barred, because SUBMIT overwrites the identifier being compared.

    "A cell design records `submitted_by_worker_id` when it is submitted for review; the engineer who
    approves it, and the engineer who requests changes on it, must both be someone else." The guard
    covers both verdicts -- "`ERR_SEGREGATION_OF_DUTIES` (HTTP 409) guards `POST
    /cell-designs/{id}/review-actions` when the action is `APPROVE` or `REQUEST_CHANGES`" -- and it
    sits below the class gate, since "Approving a cell design requires the acting worker's
    `job_class` to be `ENGINEER`" is tier 6 while segregation is tier 13. The reopening edit is the
    `CHANGES_REQUESTED` to `DRAFT` edge and `APPROVE` "copies the current `revision` into
    `approved_revision`".

    Design: Corner/rbac/design_review_segregation_of_duties_tracks_the_current_submitter
    """
    world = make_world(with_design=False)
    design = world.draft_design(lead_design_payload("CD-SOD"))
    submitted = validate_success(
        world.api.review_cell_design(
            design["id"], review_action_payload("SUBMIT"), world.eng_a
        ),
        200,
    )
    assert submitted["submitted_by_worker_id"] == world.eng_a_id

    validate_error(
        world.api.review_cell_design(
            design["id"], review_action_payload("APPROVE"), world.eng_a
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(
        world.api.review_cell_design(
            design["id"],
            review_action_payload(
                "REQUEST_CHANGES", review_comment="my own second thoughts"
            ),
            world.eng_a,
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(
        world.api.review_cell_design(
            design["id"],
            review_action_payload("APPROVE"),
            make_headers(C.ROLE_DESIGN_ENGINEER, world.sup_a_id),
        ),
        E.ERR_ACTOR_JOB_CLASS_MISMATCH,
    )

    changes = validate_success(
        world.api.review_cell_design(
            design["id"],
            review_action_payload("REQUEST_CHANGES", review_comment="raise the rated cycles"),
            world.eng_b,
        ),
        200,
    )
    assert changes["approval_state"] == C.DESIGN_CHANGES_REQUESTED
    assert changes["revision"] == 1
    assert changes["submitted_by_worker_id"] == world.eng_a_id

    edited = validate_success(
        world.api.update_cell_design(
            design["id"], {"nominal_capacity_ah": 470.0}, world.eng_a
        ),
        200,
    )
    assert edited["revision"] == 2
    assert edited["approval_state"] == C.DESIGN_DRAFT
    assert edited["submitted_by_worker_id"] == world.eng_a_id

    resubmitted = validate_success(
        world.api.review_cell_design(
            design["id"], review_action_payload("SUBMIT"), world.eng_b
        ),
        200,
    )
    assert resubmitted["approval_state"] == C.DESIGN_UNDER_REVIEW
    assert resubmitted["submitted_by_worker_id"] == world.eng_b_id

    validate_error(
        world.api.review_cell_design(
            design["id"], review_action_payload("APPROVE"), world.eng_b
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
    )

    approved = validate_success(
        world.api.review_cell_design(
            design["id"], review_action_payload("APPROVE"), world.eng_a
        ),
        200,
    )
    assert approved["approval_state"] == C.DESIGN_APPROVED
    assert approved["approved_by_worker_id"] == world.eng_a_id
    assert approved["approved_revision"] == 2
    assert approved["revision"] == 2

    validate_error(
        world.api.create_exposure_sample(
            world.sup_a_id,
            air_sample_payload("2026-08-31T16:00:00Z", 12.0, 480),
            make_headers(C.ROLE_SAFETY_OFFICER, world.eng_a_id),
        ),
        E.ERR_ACTOR_JOB_CLASS_MISMATCH,
    )
    assert world.read_worker(world.sup_a_id)["last_sample_at"] is None


def test_only_the_recorder_of_the_last_result_is_barred_from_releasing_the_lot(
    world: World,
):
    """Dana records two results and still releases; Eli records the third and is refused.

    "A production lot records `last_test_recorded_by_worker_id` each time a capacity-test result is
    recorded inside the lot's current sampling window; the inspector who releases the lot must be
    someone other than that person." The field is written by the other endpoint -- "`recorded_by_worker_id`
    is set to the acting worker and copied onto the lot's `last_test_recorded_by_worker_id`, which is
    what the release segregation-of-duties rule later reads" -- and at release "the acting worker's
    `job_class` must be `QUALITY` (`ERR_ACTOR_JOB_CLASS_MISMATCH`) and the acting worker must not be
    the one recorded in `last_test_recorded_by_worker_id` (`ERR_SEGREGATION_OF_DUTIES`)". The summary
    cannot see that: "It never reports the two actor-dependent gates, `ERR_ACTOR_JOB_CLASS_MISMATCH`
    and `ERR_SEGREGATION_OF_DUTIES`". A release "stamps `released_at` from the logical clock,
    recomputes and thereby freezes `lot_capacity_yield_pct` over the current window".

    Design: Corner/rbac/lot_release_is_refused_to_the_inspector_who_recorded_the_last_test
    """
    world.add_second_inspector()
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-S", 9)
    assembly = world.certify_assembly(lot["id"], "ASM-S1")
    planned = world.draw_plan(lot["id"])
    assert planned["sample_size"] == 3
    assert planned["acceptance_number"] == 0
    chamber_id = world.add_chamber()

    t1 = world.schedule_test(
        assembly["id"], chamber_id, "2026-09-03T08:00:00Z", "2026-09-03T10:00:00Z"
    )
    t2 = world.schedule_test(
        assembly["id"], chamber_id, "2026-09-03T10:00:00Z", "2026-09-03T12:00:00Z"
    )
    t3 = world.schedule_test(
        assembly["id"],
        chamber_id,
        "2026-09-03T12:00:00Z",
        "2026-09-03T14:00:00Z",
        test_type=C.TEST_TYPE_CYCLE_LIFE,
    )
    world.set_clock("2026-09-03T14:00:00Z")
    world.record_capacity(t1["id"], 441.8, headers=world.qa_a)
    world.record_capacity(t2["id"], 442.1, headers=world.qa_a)
    last = world.record_cycle_life(t3["id"], 372.0, 1350, headers=world.qa_b)
    assert last["recorded_by_worker_id"] == world.qa_b_id
    assert world.read_lot(lot["id"])["last_test_recorded_by_worker_id"] == world.qa_b_id

    summary = validate_success(
        world.api.get_quality_summary(lot["id"], world.qa_a), 200
    )
    assert summary["sample_size"] == 3
    assert summary["acceptance_number"] == 0
    assert summary["sampling_plan_revision"] == 1
    assert summary["completed_test_count"] == 3
    assert summary["failed_test_count"] == 0
    assert summary["passed_cycle_life_count"] == 1
    assert_close(summary["lot_capacity_yield_pct"], 90.03, "lot_capacity_yield_pct", 2)
    assert summary["release_blocked_by"] == "NONE"

    validate_error(
        world.api.disposition_lot(
            lot["id"],
            disposition_payload(C.DISPOSITION_RELEASE, "independent release"),
            world.qa_b,
        ),
        E.ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(
        world.api.disposition_lot(
            lot["id"],
            disposition_payload(C.DISPOSITION_RELEASE, "supervisor signing off"),
            make_headers(C.ROLE_QUALITY_INSPECTOR, world.sup_a_id),
        ),
        E.ERR_ACTOR_JOB_CLASS_MISMATCH,
    )
    assert world.read_lot(lot["id"])["process_state"] == C.LOT_TESTING

    released = validate_success(
        world.api.disposition_lot(
            lot["id"],
            disposition_payload(C.DISPOSITION_RELEASE, "acceptance met"),
            world.qa_a,
        ),
        200,
    )
    assert released["process_state"] == C.LOT_RELEASED
    assert released["released_at"].startswith("2026-09-03T14:00:00")
    assert_close(released["lot_capacity_yield_pct"], 90.03, "lot_capacity_yield_pct", 2)

    validate_error(
        world.api.disposition_lot(
            lot["id"],
            disposition_payload(C.DISPOSITION_QUARANTINE, "second thoughts"),
            world.qa_a,
        ),
        E.ERR_LOT_STATE_INVALID,
    )

    after = world.read_lot(lot["id"])
    assert after["process_state"] == C.LOT_RELEASED
    assert_close(after["lot_capacity_yield_pct"], 90.03, "lot_capacity_yield_pct", 2)
