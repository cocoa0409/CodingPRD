"""Single writes whose consequences travel several records deep.

A failed soak reaches the run, the cabinet, the project, the booked visit and the
chamber; a warranty swap reaches the case, two modules, the contract and the
project's posture; a sign-off reaches the visit, the project and every pending
contract.
"""

from test_helpers.assertions import (
    assert_2dp,
    assert_cabinet_fields,
    assert_case_fields,
    assert_chamber_fields,
    assert_contract_fields,
    assert_instant_equals,
    assert_module_fields,
    assert_project_fields,
    assert_run_fields,
    assert_visit_fields,
)
from test_helpers.constants import (
    CABINET_MOUNTED,
    CABINET_QUARANTINED,
    CASE_FULFILLED,
    CONTRACT_ACTIVE,
    CONTRACT_SUSPENDED,
    ENGINEERING_APPROVED,
    MODULE_INSTALLED,
    MODULE_RETURNED,
    POSTURE_AT_RISK,
    POSTURE_NORMAL,
    PRODUCTION_BLOCKED,
    PRODUCTION_COMMISSIONED,
    PROJECT_BLOCKED_ABORT_REASON,
    RUN_FAILED,
    SOAK_WINDOW_END,
    VISIT_ABORTED,
    VISIT_INSTANT,
    VISIT_SIGNED_OFF,
    VISIT_WINDOW_END,
    VISIT_WINDOW_START,
)

#: One dead pixel on the module plus one revealed by the soak is two dead pixels
#: in 1024, which is 1953.13 ppm and twice the FP10-IN ceiling of 976.56.
FAILING_PPM = 1953.13

#: One dead pixel in a 1024 pixel cabinet.
PASSING_PPM = 976.56


def _soaking_cabinet_with_a_booked_visit(plant):
    """A populated cabinet mid-soak whose project already has a crew booked."""
    scene = plant.populated_cabinet_scene()
    chamber = plant.register_chamber()
    crew = plant.register_crew()
    run = plant.schedule_run(scene.cabinet["id"], chamber["id"], slots_required=2)
    visit = plant.book_visit(scene.project["id"], crew["id"])
    plant.set_clock(SOAK_WINDOW_END)
    scene.chamber = plant.chamber(chamber["id"])
    scene.crew = plant.crew(crew["id"])
    scene.run = run
    scene.visit = visit
    return scene


def _approved_claim_over_a_reserved_spare(plant):
    """A commissioned wall whose one brightness claim is approved and ready to swap."""
    scene = plant.warranty_case_scene()
    plant.assess(
        scene.case["id"],
        decision="APPROVE",
        assessment_basis="PRO_RATA_REMAINING_TERM",
    )
    return scene


def _calibrated_visit_with_a_pending_contract(plant):
    """A mounted wall, a SILVER contract still PENDING, and a crew on site."""
    scene = plant.mounted_project_scene()
    contract = plant.sell_contract(scene.project["id"], tier="SILVER", spare_pct_bp=200)
    visit = plant.book_visit(
        scene.project["id"],
        scene.crew["id"],
        window_start=VISIT_WINDOW_START,
        window_end=VISIT_WINDOW_END,
    )
    plant.set_clock(VISIT_INSTANT)
    plant.arrive(visit["id"], scene.crew["id"])
    plant.calibrate_on_site(visit["id"], scene.crew["id"])
    scene.contract = contract
    scene.visit = visit
    return scene


class TestBurnInFailureCascade:
    """One failing verdict quarantines a cabinet and unwinds the wall around it."""

    def test_the_failing_verdict_quarantines_the_cabinet_without_a_baseline(self, plant):
        """Second, the cabinet moves `BURN_IN → QUARANTINED` and its
        `baseline_uniformity_score` is left null — a failed cabinet never
        acquires a baseline.

        Design: Difficulty/transitive_cascade/burn_in_failure_cascades_cabinet_project_visit
        """
        scene = _soaking_cabinet_with_a_booked_visit(plant)

        run = plant.complete_run(
            scene.run["id"],
            new_dead_pixel_count=1,
            measured_brightness_nits=4900,
            measured_uniformity_pct=95.00,
        )

        assert_run_fields(run, run_state=RUN_FAILED, new_dead_pixel_count=1)
        assert_2dp(run["cabinet_dead_pixel_ppm"], FAILING_PPM, "cabinet_dead_pixel_ppm")
        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(cabinet, cabinet_state=CABINET_QUARANTINED)
        assert_2dp(cabinet["dead_pixel_ppm"], FAILING_PPM, "dead_pixel_ppm")
        assert cabinet["baseline_uniformity_score"] is None

    def test_the_quarantine_blocks_the_project_and_aborts_its_visits(self, plant):
        """Fourth, every commissioning visit of that project whose `visit_state`
        is `SCHEDULED`, `ON_SITE` or `CALIBRATED` is moved to `ABORTED` with
        `abort_reason` set to the exact string `PROJECT_BLOCKED`, and each such
        abort decrements the crew's `scheduled_visit_count`, releasing the window
        for another booking.

        Design: Difficulty/transitive_cascade/burn_in_failure_cascades_cabinet_project_visit
        """
        scene = _soaking_cabinet_with_a_booked_visit(plant)

        plant.complete_run(scene.run["id"], new_dead_pixel_count=1)

        assert_project_fields(
            plant.project(scene.project["id"]),
            production_state=PRODUCTION_BLOCKED,
            quarantined_cabinet_count=1,
            qa_passed_cabinet_count=0,
            mounted_cabinet_count=0,
        )
        assert_visit_fields(
            plant.visit(scene.visit["id"]),
            visit_state=VISIT_ABORTED,
            abort_reason=PROJECT_BLOCKED_ABORT_REASON,
        )
        assert plant.crew(scene.crew["id"])["scheduled_visit_count"] == 0

    def test_the_verdict_releases_the_chamber_and_leaves_module_states_alone(self, plant):
        """Either outcome stores the three measurements, records
        `completed_by_user_id` as the acting `X-User-ID`, recomputes the
        cabinet's dead-pixel density with the new count folded in, and snapshots
        that figure onto the run as `cabinet_dead_pixel_ppm`, rounded to 2
        decimal places, and releases the chamber: the run's `slots_required` is
        subtracted from the chamber's `reserved_slot_total` and 1 from its
        `scheduled_run_count`.

        Design: Difficulty/transitive_cascade/burn_in_failure_cascades_cabinet_project_visit
        """
        scene = _soaking_cabinet_with_a_booked_visit(plant)
        assert_chamber_fields(scene.chamber, reserved_slot_total=2, scheduled_run_count=1)

        plant.complete_run(scene.run["id"], new_dead_pixel_count=1)

        assert_chamber_fields(
            plant.chamber(scene.chamber["id"]),
            reserved_slot_total=0,
            scheduled_run_count=0,
        )
        assert_module_fields(
            plant.module(scene.modules[0]["id"]), module_state=MODULE_INSTALLED
        )


class TestWarrantyFulfilmentCascade:
    """A swap flips two modules in opposite directions and depletes the pool."""

    def test_the_swap_returns_the_faulty_module_and_installs_the_spare(self, plant):
        """Second, the module pinned as `resolved_faulty_module_id` moves
        `INSTALLED → RETURNED` and gives up its `slot_index` while **retaining**
        its `cabinet_id` for traceability, and the replacement module moves
        `CALIBRATED → INSTALLED` into that vacated `slot_index`, with
        `replaces_module_id` set to the outgoing module's id — the
        self-referential chain that lets an auditor walk a slot's whole
        replacement history — and its `reserved_service_contract_id` cleared,
        since a module in service is no longer a spare.

        Design: Difficulty/transitive_cascade/warranty_fulfilment_cascades_module_contract_project
        """
        scene = _approved_claim_over_a_reserved_spare(plant)
        faulty = scene.modules[0]

        fulfilled = plant.fulfil(
            scene.case["id"], scene.cabinet["id"], scene.spare["id"]
        )

        assert_case_fields(
            fulfilled,
            case_state=CASE_FULFILLED,
            replacement_module_id=scene.spare["id"],
        )
        assert_module_fields(
            plant.module(faulty["id"]),
            module_state=MODULE_RETURNED,
            slot_index=None,
            cabinet_id=scene.cabinet["id"],
        )
        assert_module_fields(
            plant.module(scene.spare["id"]),
            module_state=MODULE_INSTALLED,
            slot_index=1,
            replaces_module_id=faulty["id"],
            reserved_service_contract_id=None,
        )

    def test_the_depleted_pool_suspends_the_contract_and_flags_the_project(self, plant):
        """Third, the contract's `spare_reserved_count` drops by 1, and when that
        leaves the pool below `spare_required_count` the contract moves
        `ACTIVE → SUSPENDED`.

        Design: Difficulty/transitive_cascade/warranty_fulfilment_cascades_module_contract_project
        """
        scene = _approved_claim_over_a_reserved_spare(plant)
        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_ACTIVE,
            spare_reserved_count=1,
            spare_required_count=1,
        )

        plant.fulfil(scene.case["id"], scene.cabinet["id"], scene.spare["id"])

        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_SUSPENDED,
            spare_reserved_count=0,
            spare_required_count=1,
        )
        assert_project_fields(
            plant.project(scene.project["id"]), service_posture=POSTURE_AT_RISK
        )

    def test_the_service_cascade_never_touches_the_production_dimension(self, plant):
        """Along the way the cabinet's `total_dead_pixel_count`,
        `dead_pixel_ppm` and `as_built_uniformity_score` are recomputed over its
        new module set while `baseline_uniformity_score` and
        `baseline_module_ids` are left exactly as burn-in froze them, and version
        increments land on the cabinet, the case and both modules.

        Design: Difficulty/transitive_cascade/warranty_fulfilment_cascades_module_contract_project
        """
        scene = _approved_claim_over_a_reserved_spare(plant)

        plant.fulfil(scene.case["id"], scene.cabinet["id"], scene.spare["id"])

        cabinet = plant.cabinet(scene.cabinet["id"])
        assert_cabinet_fields(
            cabinet,
            cabinet_state=CABINET_MOUNTED,
            installed_module_count=1,
            occupied_slot_indexes=[1],
            total_dead_pixel_count=1,
        )
        assert_2dp(cabinet["dead_pixel_ppm"], PASSING_PPM, "dead_pixel_ppm")
        assert cabinet["as_built_uniformity_score"] is None, (
            "a single-module cabinet has too few modules to score"
        )
        assert_project_fields(
            plant.project(scene.project["id"]),
            production_state=PRODUCTION_COMMISSIONED,
        )


class TestSignOffCascade:
    """Handover closes the visit, commissions the wall and starts the warranty."""

    def test_sign_off_commissions_the_wall_and_releases_the_crew(self, plant):
        """The write then stamps `signed_off_at` from the logical clock and moves
        the visit `CALIBRATED → SIGNED_OFF`; moves the project
        `INSTALLED → COMMISSIONED`; activates the warranty by moving **every**
        service contract of that project whose `contract_state` is `PENDING` to
        `ACTIVE`, setting each one's `warranty_start_at` to the same
        `signed_off_at` instant and incrementing each contract's `version`; and
        decrements the crew's `scheduled_visit_count`, releasing the crew.

        Design: Difficulty/transitive_cascade/sign_off_cascades_project_commissioned_contract_active
        """
        scene = _calibrated_visit_with_a_pending_contract(plant)

        signed_off = plant.sign_off(scene.visit["id"], scene.crew["id"])

        assert_visit_fields(signed_off, visit_state=VISIT_SIGNED_OFF)
        assert_instant_equals(signed_off["signed_off_at"], VISIT_INSTANT, "signed_off_at")
        assert_instant_equals(signed_off["arrived_at"], VISIT_INSTANT, "arrived_at")
        assert_project_fields(
            plant.project(scene.project["id"]),
            engineering_state=ENGINEERING_APPROVED,
            production_state=PRODUCTION_COMMISSIONED,
            service_posture=POSTURE_NORMAL,
        )
        assert plant.crew(scene.crew["id"])["scheduled_visit_count"] == 0

    def test_sign_off_activates_the_pending_contract_and_starts_the_warranty(self, plant):
        """`response_hours` is derived, never supplied: two full days, that is 48
        hours, for `BRONZE`; one full day, that is 24 hours, for `SILVER`; and 8
        hours for `GOLD`.

        Design: Difficulty/transitive_cascade/sign_off_cascades_project_commissioned_contract_active
        """
        scene = _calibrated_visit_with_a_pending_contract(plant)

        plant.sign_off(scene.visit["id"], scene.crew["id"])

        contract = plant.contract(scene.contract["id"])
        assert_contract_fields(
            contract,
            contract_state=CONTRACT_ACTIVE,
            tier="SILVER",
            response_hours=24,
            spare_required_count=1,
            spare_reserved_count=0,
        )
        assert_instant_equals(
            contract["warranty_start_at"], VISIT_INSTANT, "warranty_start_at"
        )
