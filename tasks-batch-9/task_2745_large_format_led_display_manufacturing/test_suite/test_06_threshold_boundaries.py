"""Values sitting exactly on a declared threshold, and one step either side.

A dead-pixel density byte-equal to its ceiling, a response landing on the very
millisecond of its deadline, and a candidate pool of exactly zero.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_NO_ELIGIBLE_SPARE_MODULE
from test_helpers.assertions import (
    assert_2dp,
    assert_cabinet_fields,
    assert_contract_fields,
    assert_instant_equals,
    assert_module_fields,
    assert_project_fields,
    assert_run_fields,
    assert_version,
)
from test_helpers.constants import (
    CABINET_BURN_IN_PASSED,
    CABINET_QUARANTINED,
    CASE_RESPONDED,
    CONTRACT_ACTIVE,
    MODULE_CALIBRATED,
    MODULE_INSTALLED,
    POSTURE_NORMAL,
    PRODUCTION_BLOCKED,
    RUN_FAILED,
    RUN_PASSED,
    SOAK_WINDOW_END,
    SOAK_WINDOW_START,
)
from test_helpers.factories import next_serial, spare_reservation_payload

#: A GOLD contract answers in 8 hours and a MAJOR case carries the full
#: multiplier, so a claim reported at 09:00 is due at 17:00 the same day.
CLAIM_REPORTED_AT = "2027-02-05T09:00:00.000Z"
CLAIM_DEADLINE = "2027-02-05T17:00:00.000Z"
ONE_MILLISECOND_LATE = "2027-02-05T17:00:00.001Z"

#: One dead pixel in the 1024 pixels of an FP10-IN cabinet is 976.5625 ppm, which
#: rounds to the family's ceiling exactly.
PPM_AT_THE_LIMIT = 976.56
PPM_BELOW_THE_LIMIT = 0.00
PPM_OVER_THE_LIMIT = 1953.13


def _three_cabinet_wall_straddling_the_ppm_limit(plant):
    """A 3x1 wall whose three cabinets carry 0, 1 and 2 dead pixels, all soaking."""
    scene = plant.approved_project_scene(
        project_overrides={"cabinet_grid_cols": 3, "cabinet_grid_rows": 1}
    )
    chamber = plant.register_chamber()
    scene.cabinets = []
    scene.runs = []
    for column, dead in ((1, 0), (2, 1), (3, 2)):
        cabinet = plant.plan_cabinet(scene.project["id"], grid_row=1, grid_col=column)
        module = plant.calibrated_module(
            scene.model["id"],
            dead_pixel_count=dead,
            max_cluster_size=1 if dead else 0,
        )
        plant.install(cabinet["id"], module["id"], 1)
        scene.runs.append(
            plant.schedule_run(
                cabinet["id"],
                chamber["id"],
                window_start=SOAK_WINDOW_START,
                window_end=SOAK_WINDOW_END,
                slots_required=1,
            )
        )
        scene.cabinets.append(plant.cabinet(cabinet["id"]))
    plant.set_clock(SOAK_WINDOW_END)
    scene.chamber = chamber
    return scene


def _two_open_module_fault_claims(plant):
    """A commissioned GOLD wall with two MAJOR claims opened at the same instant."""
    scene = plant.commissioned_scene()
    plant.set_clock(CLAIM_REPORTED_AT)
    scene.case_a = plant.open_module_fault_case(
        scene.contract["id"],
        scene.cabinet["id"],
        scene.modules[0]["id"],
        symptom="Quadrant one is dark",
    )
    scene.case_b = plant.open_module_fault_case(
        scene.contract["id"],
        scene.cabinet["id"],
        scene.modules[0]["id"],
        symptom="Quadrant one still dark",
    )
    return scene


class TestDeadPixelDensityAgainstItsCeiling:
    """The density comparison treats equality with the ceiling as acceptable."""

    def test_a_density_below_the_ceiling_passes(self, plant):
        """The run **passes** when the cabinet's recomputed dead-pixel density is
        at most the family's `dead_pixel_ppm_limit`, **and**
        `measured_brightness_nits` is at least 4800 nits, **and**
        `measured_uniformity_pct` is at least 92.00 percent.

        Design: Difficulty/boundary_precision_check/dead_pixel_ppm_exact_limit_passes
        """
        scene = _three_cabinet_wall_straddling_the_ppm_limit(plant)

        run = plant.complete_run(
            scene.runs[0]["id"],
            new_dead_pixel_count=0,
            measured_brightness_nits=4800,
            measured_uniformity_pct=92.00,
        )

        assert_run_fields(run, run_state=RUN_PASSED)
        cabinet = plant.cabinet(scene.cabinets[0]["id"])
        assert_cabinet_fields(cabinet, cabinet_state=CABINET_BURN_IN_PASSED)
        assert_2dp(cabinet["dead_pixel_ppm"], PPM_BELOW_THE_LIMIT, "dead_pixel_ppm")

    def test_a_density_exactly_at_the_ceiling_still_passes(self, plant):
        """Each comparison treats exact equality with the floor as acceptable.

        Design: Difficulty/boundary_precision_check/dead_pixel_ppm_exact_limit_passes
        """
        scene = _three_cabinet_wall_straddling_the_ppm_limit(plant)

        run = plant.complete_run(scene.runs[1]["id"], new_dead_pixel_count=0)

        assert_run_fields(run, run_state=RUN_PASSED)
        assert_2dp(
            run["cabinet_dead_pixel_ppm"], PPM_AT_THE_LIMIT, "cabinet_dead_pixel_ppm"
        )
        cabinet = plant.cabinet(scene.cabinets[1]["id"])
        assert_cabinet_fields(cabinet, cabinet_state=CABINET_BURN_IN_PASSED)
        assert_2dp(cabinet["dead_pixel_ppm"], PPM_AT_THE_LIMIT, "dead_pixel_ppm")

    def test_one_pixel_past_the_ceiling_quarantines_the_cabinet(self, plant):
        """It **fails** when the density exceeds the limit, or the brightness
        falls below 4800 nits, or the uniformity falls below 92.00 percent.

        Design: Difficulty/boundary_precision_check/dead_pixel_ppm_exact_limit_passes
        """
        scene = _three_cabinet_wall_straddling_the_ppm_limit(plant)

        run = plant.complete_run(scene.runs[2]["id"], new_dead_pixel_count=0)

        assert_run_fields(run, run_state=RUN_FAILED)
        cabinet = plant.cabinet(scene.cabinets[2]["id"])
        assert_cabinet_fields(cabinet, cabinet_state=CABINET_QUARANTINED)
        assert_2dp(cabinet["dead_pixel_ppm"], PPM_OVER_THE_LIMIT, "dead_pixel_ppm")
        project = plant.project(scene.project["id"])
        assert_project_fields(
            project, production_state=PRODUCTION_BLOCKED, quarantined_cabinet_count=1
        )
        assert project["required_data_mbps"] == 6
        assert_2dp(project["data_load_pct"], 0.60, "data_load_pct")


class TestResponseDeadlineBoundary:
    """A response is late only when it lands strictly after the deadline."""

    def test_a_response_on_the_deadline_instant_is_on_time(self, plant):
        """The write stamps `responded_at` from the logical clock, moves the case
        `OPEN → RESPONDED`, and sets `response_breached` to true only when
        `responded_at` is **strictly later** than `response_deadline_at` — a
        response landing at exactly the deadline instant is on time.

        Design: Difficulty/boundary_precision_check/sla_response_exactly_at_deadline_is_not_breached
        """
        scene = _two_open_module_fault_claims(plant)
        assert_instant_equals(
            scene.case_a["response_deadline_at"], CLAIM_DEADLINE, "response_deadline_at"
        )
        assert_instant_equals(
            scene.case_a["reported_at"], CLAIM_REPORTED_AT, "reported_at"
        )

        plant.set_clock(CLAIM_DEADLINE)
        responded = plant.respond(scene.case_a["id"])

        assert responded["case_state"] == CASE_RESPONDED
        assert responded["response_breached"] is False
        assert_instant_equals(responded["responded_at"], CLAIM_DEADLINE, "responded_at")

    def test_a_response_one_millisecond_later_is_a_breach(self, plant):
        """Creation stamps `reported_at` from the logical clock, sets `case_state`
        to `OPEN`, and computes `response_deadline_at` as `reported_at` advanced
        by the contract's `response_hours` multiplied by a severity multiplier:
        half the contracted hours for `CRITICAL`, the full contracted hours for
        `MAJOR`, and double for `MINOR`.

        Design: Difficulty/boundary_precision_check/sla_response_exactly_at_deadline_is_not_breached
        """
        scene = _two_open_module_fault_claims(plant)
        assert_instant_equals(
            scene.case_b["response_deadline_at"], CLAIM_DEADLINE, "response_deadline_at"
        )

        plant.set_clock(ONE_MILLISECOND_LATE)
        responded = plant.respond(scene.case_b["id"])

        assert responded["case_state"] == CASE_RESPONDED
        assert responded["response_breached"] is True
        assert_instant_equals(
            responded["responded_at"], ONE_MILLISECOND_LATE, "responded_at"
        )

    def test_a_single_breach_does_not_suspend_the_contract(self, plant):
        """A breach raises the contract's `sla_breach_count` by 1, and when that
        counter reaches 2 the contract moves `ACTIVE → SUSPENDED` and the
        project's `service_posture` becomes `AT_RISK`, which — per §3.8 — freezes
        every remaining case on that contract.

        Design: Difficulty/boundary_precision_check/sla_response_exactly_at_deadline_is_not_breached
        """
        scene = _two_open_module_fault_claims(plant)

        plant.set_clock(CLAIM_DEADLINE)
        plant.respond(scene.case_a["id"])
        plant.set_clock(ONE_MILLISECOND_LATE)
        plant.respond(scene.case_b["id"])

        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_ACTIVE,
            sla_breach_count=1,
        )
        assert_project_fields(
            plant.project(scene.project["id"]), service_posture=POSTURE_NORMAL
        )


class TestEmptySpareCandidatePool:
    """A server-picked reservation over an empty pool refuses rather than guesses."""

    def test_an_installed_module_is_never_a_candidate(self, plant):
        """If the eligible pool is empty the reservation is refused with
        `ERR_NO_ELIGIBLE_SPARE_MODULE`.

        Design: Difficulty/boundary_precision_check/empty_spare_pool_returns_no_eligible_spare_module
        """
        scene = plant.commissioned_scene()
        contract_version = plant.contract_version(scene.contract["id"])

        response = plant.api.reserve_spare(
            scene.contract["id"],
            spare_reservation_payload(contract_version),
            plant.service,
        )

        validate_error(response, ERR_NO_ELIGIBLE_SPARE_MODULE, 409)
        contract = plant.contract(scene.contract["id"])
        assert_contract_fields(contract, spare_reserved_count=0)
        assert_version(contract, contract_version, "contract")
        assert_module_fields(
            plant.module(scene.modules[0]["id"]),
            module_state=MODULE_INSTALLED,
            reserved_service_contract_id=None,
        )

    def test_one_candidate_appearing_satisfies_the_same_reservation(self, plant):
        """Eligible candidates are modules whose `module_state` is `CALIBRATED`,
        whose `display_model_id` matches the display model pinned by the
        contract's project, and whose `reserved_service_contract_id` is unset —
        modules that are `MANUFACTURED`, `PIXEL_TESTED`, in `REWORK`,
        `INSTALLED`, `RETURNED` or `SCRAPPED` are never candidates.

        Design: Difficulty/boundary_precision_check/empty_spare_pool_returns_no_eligible_spare_module
        """
        scene = plant.commissioned_scene()
        contract_version = plant.contract_version(scene.contract["id"])
        plant.api.reserve_spare(
            scene.contract["id"],
            spare_reservation_payload(contract_version),
            plant.service,
        )
        spare = plant.calibrated_module(
            scene.model["id"],
            serial_no=next_serial("S"),
            measured_brightness_nits=4850,
            measured_color_x=0.3124,
            measured_color_y=0.3287,
        )

        reserved = validate_success(
            plant.api.reserve_spare(
                scene.contract["id"],
                spare_reservation_payload(contract_version),
                plant.service,
            ),
            201,
        )

        assert reserved["id"] == spare["id"]
        assert_module_fields(
            reserved,
            module_state=MODULE_CALIBRATED,
            reserved_service_contract_id=scene.contract["id"],
        )
        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_ACTIVE,
            spare_reserved_count=1,
            spare_required_count=1,
        )
