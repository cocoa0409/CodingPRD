"""Commissioning and warranty gates: who may act, when, and in what order.

On site the service checks three separate things — the identity of the crew, the
stage the visit has reached, and where the logical clock stands relative to a
half-open window — and each refusal leaves the visit exactly where it was. The
same discipline governs the warranty desk: a claim cannot be judged before it has
been answered, and a handover cannot be replayed.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_CREW_NOT_ASSIGNED,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_VISIT_STATE,
    ERR_VISIT_WINDOW_NOT_CURRENT,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_case_fields,
    assert_cents,
    assert_contract_fields,
    assert_fields_absent_or_null,
    assert_instant_equals,
    assert_module_fields,
    assert_project_fields,
    assert_version,
    assert_visit_fields,
)
from test_helpers.constants import (
    CASE_DENIED,
    CASE_OPEN,
    CASE_RESPONDED,
    CONTRACT_ACTIVE,
    MODULE_INSTALLED,
    PRODUCTION_COMMISSIONED,
    PRODUCTION_INSTALLED,
    VISIT_CALIBRATED,
    VISIT_INSTANT,
    VISIT_ON_SITE,
    VISIT_SCHEDULED,
    VISIT_SIGNED_OFF,
    VISIT_WINDOW_END,
    VISIT_WINDOW_START,
)
from test_helpers.factories import assess_payload, visit_calibrate_payload
from test_helpers.test_users import make_field_engineer_headers

#: A second NA-W crew that holds no booking of its own.
SECOND_CREW_NAME = "Crew East"

#: One millisecond before the booked window opens.
ONE_MS_BEFORE_VISIT_WINDOW_START = "2026-08-05T07:59:59.999Z"

#: The on-site acceptance measurements, both comfortably above their floors.
ON_SITE_BRIGHTNESS_NITS = 4900
ON_SITE_UNIFORMITY_PCT = 95.00

#: The warranty desk's timeline: a MAJOR claim on a GOLD contract is due in the
#: contracted eight hours.
CASE_REPORTED_AT = "2026-08-05T10:00:00.000Z"
MAJOR_GOLD_RESPONSE_DEADLINE = "2026-08-05T18:00:00.000Z"

#: Two hours after the handover, so a re-stamped instant would be visible.
REPLAY_INSTANT = "2026-08-05T11:00:00.000Z"

DENIAL_REASON = "Impact damage from a forklift, outside warranty scope"


def _mounted_wall_with_a_booked_visit(plant):
    """An INSTALLED wall whose booked crew has not yet arrived on site."""
    scene = plant.mounted_project_scene()
    scene.visit = plant.book_visit(scene.project["id"], scene.crew["id"])
    return scene


class TestArrivalCrewOwnership:
    """Only the booked crew may open the visit, whoever else is on site."""

    def test_an_unbooked_crew_cannot_record_the_arrival(self, plant):
        """When `X-User-Role` is `FieldEngineer`, `X-User-ID` is the `id` of the
        acting `CommissioningCrew`; ownership checks on a commissioning visit
        compare the visit's `commissioning_crew_id` to `X-User-ID`, and a mismatch
        is rejected with `ERR_CREW_NOT_ASSIGNED` (HTTP 403).

        Design: Corner/state_machines/visit_arrive_by_another_crew_rejected
        """
        scene = _mounted_wall_with_a_booked_visit(plant)
        other_crew = plant.register_crew(name=SECOND_CREW_NAME)
        plant.set_clock(VISIT_INSTANT)

        refused = plant.api.arrive_at_visit(
            scene.visit["id"], make_field_engineer_headers(other_crew["id"])
        )

        validate_error(refused, ERR_CREW_NOT_ASSIGNED, 403)
        waiting = plant.visit(scene.visit["id"])
        assert_visit_fields(
            waiting,
            visit_state=VISIT_SCHEDULED,
            commissioning_crew_id=scene.crew["id"],
        )
        assert_fields_absent_or_null(waiting, "arrived_at")
        assert_project_fields(
            plant.project(scene.project["id"]), production_state=PRODUCTION_INSTALLED
        )

        arrived = plant.arrive(scene.visit["id"], scene.crew["id"])

        assert_visit_fields(arrived, visit_state=VISIT_ON_SITE)
        assert_instant_equals(arrived["arrived_at"], VISIT_INSTANT, "arrived_at")
        assert_project_fields(
            plant.project(scene.project["id"]), production_state=PRODUCTION_INSTALLED
        )


class TestArrivalWindowCurrency:
    """The booked window is half-open: its opening instant is in, its end is out."""

    def test_the_window_admits_its_start_and_excludes_its_end(self, plant):
        """The logical clock must lie inside the half-open window, at or after
        `window_start` and strictly before `window_end`, with a clock reading
        exactly at `window_end` counting as outside and refused with
        `ERR_VISIT_WINDOW_NOT_CURRENT`.

        Design: Corner/state_machines/visit_arrive_outside_the_half_open_window_rejected
        """
        scene = _mounted_wall_with_a_booked_visit(plant)
        crew_headers = make_field_engineer_headers(scene.crew["id"])

        plant.set_clock(ONE_MS_BEFORE_VISIT_WINDOW_START)
        too_early = plant.api.arrive_at_visit(scene.visit["id"], crew_headers)
        validate_error(too_early, ERR_VISIT_WINDOW_NOT_CURRENT, 409)

        plant.set_clock(VISIT_WINDOW_END)
        at_the_end = plant.api.arrive_at_visit(scene.visit["id"], crew_headers)
        validate_error(at_the_end, ERR_VISIT_WINDOW_NOT_CURRENT, 409)

        still_scheduled = plant.visit(scene.visit["id"])
        assert_visit_fields(still_scheduled, visit_state=VISIT_SCHEDULED)
        assert_fields_absent_or_null(still_scheduled, "arrived_at")

        plant.set_clock(VISIT_WINDOW_START)
        arrived = plant.arrive(scene.visit["id"], scene.crew["id"])

        assert_visit_fields(arrived, visit_state=VISIT_ON_SITE)
        assert_instant_equals(arrived["arrived_at"], VISIT_WINDOW_START, "arrived_at")


class TestOnSiteCalibrationStageGate:
    """Calibration belongs to a crew that has already arrived."""

    def test_calibration_before_arrival_is_refused_and_stores_nothing(self, plant):
        """The visit's `visit_state` permits the operation: `SCHEDULED` for arrival,
        `ON_SITE` for on-site calibration, `CALIBRATED` for sign-off — otherwise
        `ERR_INVALID_VISIT_STATE`.

        Design: Corner/state_machines/visit_calibrate_before_arrival_rejected
        """
        scene = _mounted_wall_with_a_booked_visit(plant)
        plant.set_clock(VISIT_INSTANT)

        refused = plant.api.calibrate_visit(
            scene.visit["id"],
            visit_calibrate_payload(ON_SITE_BRIGHTNESS_NITS, ON_SITE_UNIFORMITY_PCT),
            make_field_engineer_headers(scene.crew["id"]),
        )

        validate_error(refused, ERR_INVALID_VISIT_STATE, 409)
        waiting = plant.visit(scene.visit["id"])
        assert_visit_fields(
            waiting, visit_state=VISIT_SCHEDULED, measured_brightness_nits=None
        )
        assert_fields_absent_or_null(waiting, "arrived_at", "measured_uniformity_pct")
        assert plant.crew(scene.crew["id"])["scheduled_visit_count"] == 1, (
            "the crew is released only at sign-off or abort"
        )

        on_site = plant.arrive(scene.visit["id"], scene.crew["id"])
        assert_visit_fields(on_site, visit_state=VISIT_ON_SITE)

        calibrated = plant.calibrate_on_site(
            scene.visit["id"],
            scene.crew["id"],
            ON_SITE_BRIGHTNESS_NITS,
            ON_SITE_UNIFORMITY_PCT,
        )

        assert_visit_fields(
            calibrated,
            visit_state=VISIT_CALIBRATED,
            measured_brightness_nits=ON_SITE_BRIGHTNESS_NITS,
        )
        assert_2dp(
            calibrated["measured_uniformity_pct"],
            ON_SITE_UNIFORMITY_PCT,
            "measured_uniformity_pct",
        )
        assert plant.crew(scene.crew["id"])["scheduled_visit_count"] == 1, (
            "the crew is released only at sign-off or abort"
        )


class TestSignOffIsNotReplayable:
    """The commercial handover happens once, at one instant, for one contract."""

    def test_a_second_sign_off_changes_no_stamp_and_no_counter(self, plant):
        """The write then stamps `signed_off_at` from the logical clock and moves the
        visit `CALIBRATED → SIGNED_OFF`; moves the project `INSTALLED → COMMISSIONED`;
        activates the warranty by moving **every** service contract of that project
        whose `contract_state` is `PENDING` to `ACTIVE`, setting each one's
        `warranty_start_at` to the same `signed_off_at` instant and incrementing each
        contract's `version`; and decrements the crew's `scheduled_visit_count`,
        releasing the crew.

        Design: Corner/state_machines/second_sign_off_on_a_signed_off_visit_rejected
        """
        scene = plant.commissioned_scene()
        contract_version_at_activation = scene.contract["version"]
        project_version_at_handover = scene.project["version"]
        plant.set_clock(REPLAY_INSTANT)

        refused = plant.api.sign_off_visit(
            scene.visit["id"], make_field_engineer_headers(scene.crew["id"])
        )

        validate_error(refused, ERR_INVALID_VISIT_STATE, 409)
        visit = plant.visit(scene.visit["id"])
        assert_visit_fields(visit, visit_state=VISIT_SIGNED_OFF)
        assert_instant_equals(visit["signed_off_at"], VISIT_INSTANT, "signed_off_at")
        assert plant.crew(scene.crew["id"])["scheduled_visit_count"] == 0, (
            "the crew is released once, and never below zero"
        )

        contract = plant.contract(scene.contract["id"])
        assert_contract_fields(contract, contract_state=CONTRACT_ACTIVE)
        assert_instant_equals(
            contract["warranty_start_at"], VISIT_INSTANT, "warranty_start_at"
        )
        assert_version(contract, contract_version_at_activation, "contract")

        project = plant.project(scene.project["id"])
        assert_project_fields(project, production_state=PRODUCTION_COMMISSIONED)
        assert_version(project, project_version_at_handover, "project")


class TestWarrantyAssessmentStageGate:
    """A claim is judged only after it has been answered."""

    def test_a_claim_cannot_be_assessed_before_it_has_been_responded_to(self, plant):
        """The case's `case_state` permits the operation: `OPEN` for response,
        `RESPONDED` for assessment, `APPROVED` for fulfilment — otherwise
        `ERR_INVALID_CASE_STATE`.

        Design: Corner/state_machines/case_assess_before_respond_rejected
        """
        scene = plant.commissioned_scene()
        plant.set_clock(CASE_REPORTED_AT)
        case = plant.open_module_fault_case(
            scene.contract["id"], scene.cabinet["id"], scene.modules[0]["id"]
        )

        premature = plant.api.assess_case(
            case["id"],
            assess_payload("APPROVE", assessment_basis="PRO_RATA_REMAINING_TERM"),
            plant.service,
        )

        validate_error(premature, ERR_INVALID_CASE_STATE, 409)
        unjudged = plant.case(case["id"])
        assert_case_fields(
            unjudged,
            case_state=CASE_OPEN,
            assessment_basis=None,
            resolved_faulty_module_id=None,
        )
        assert unjudged.get("credit_cents") in (None, 0), (
            f"an unjudged claim carries no credit, got {unjudged.get('credit_cents')!r}"
        )
        assert_instant_equals(
            unjudged["response_deadline_at"],
            MAJOR_GOLD_RESPONSE_DEADLINE,
            "response_deadline_at",
        )

        responded = plant.respond(case["id"])

        assert_case_fields(responded, case_state=CASE_RESPONDED, response_breached=False)
        assert_instant_equals(responded["responded_at"], CASE_REPORTED_AT, "responded_at")
        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_ACTIVE,
            sla_breach_count=0,
        )

        denied = plant.assess(case["id"], decision="DENY", denial_reason=DENIAL_REASON)

        assert_case_fields(
            denied,
            case_state=CASE_DENIED,
            denial_reason=DENIAL_REASON,
            assessment_basis=None,
            resolved_faulty_module_id=None,
            replacement_module_id=None,
        )
        assert_cents(denied["credit_cents"], 0, "credit_cents")
        assert_module_fields(
            plant.module(scene.modules[0]["id"]), module_state=MODULE_INSTALLED
        )
