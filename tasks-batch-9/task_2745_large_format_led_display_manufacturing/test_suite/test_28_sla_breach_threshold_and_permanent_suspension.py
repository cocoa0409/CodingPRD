"""A counter that only grows, and the suspension it triggers only once.

The spare pool can be drained and refilled without limit, but late responses
accumulate against a hard boundary of two, and the reactivation edge reads that
counter as well as the pool. The wall here keeps one spare reserved throughout so
the pool condition is never what moves the contract.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers.api_errors import ERR_CONTRACT_NOT_ACTIVE
from test_helpers.assertions import (
    assert_case_fields,
    assert_contract_fields,
    assert_instant_equals,
    assert_module_fields,
)
from test_helpers.constants import (
    CASE_OPEN,
    CASE_RESPONDED,
    CONTRACT_ACTIVE,
    CONTRACT_SUSPENDED,
    MODULE_CALIBRATED,
    POSTURE_AT_RISK,
    POSTURE_NORMAL,
)
from test_helpers.factories import (
    FP16_STD,
    module_fault_case_payload,
    spare_reservation_payload,
)

#: The FP16-STD family certifies 150.00 kg/sqm and fits two modules per cabinet, so
#: the wall offers two distinct modules to blame.
FP16_REQUIRED_LOAD_KG_PER_SQM = 150.00

#: A GOLD contract answers in eight hours, and a MAJOR case is due in the full
#: contracted hours, so each deadline is exactly eight hours after its report.
GOLD_RESPONSE_HOURS = 8

#: A GOLD holding of 300 basis points over a two-module wall obliges one spare, and
#: exactly one is reserved for the whole file, so the spare disjunct of the
#: suspension rule is false throughout.
GOLD_SPARE_REQUIRED_COUNT = 1

#: Reactivation demands a breach count below two, and the counter only ever grows.
MAX_SLA_BREACHES = 2

#: The first claim is reported an hour after sign-off and answered one millisecond
#: past its deadline — the narrowest possible breach.
FIRST_CASE_REPORTED_AT = "2026-08-05T10:00:00.000Z"
FIRST_RESPONSE_DEADLINE = "2026-08-05T18:00:00.000Z"
ONE_MILLISECOND_LATE = "2026-08-05T18:00:00.001Z"

#: The second claim is reported an hour later still and answered an hour late.
SECOND_CASE_REPORTED_AT = "2026-08-05T19:00:00.000Z"
SECOND_RESPONSE_DEADLINE = "2026-08-06T03:00:00.000Z"
ONE_HOUR_LATE = "2026-08-06T04:00:00.000Z"

FIRST_SYMPTOM = "First fault: slot 1 flickers"
SECOND_SYMPTOM = "Second fault: slot 2 flickers"
THIRD_SYMPTOM = "Third fault while suspended"

#: The spare that is reserved from the start, and the one offered after the
#: suspension in a doomed attempt to lift it.
FIRST_SPARE_NITS = 4850
SECOND_SPARE_NITS = 4820
SPARE_CHROMA = (0.3130, 0.3290)


def _a_live_wall_with_one_spare_and_one_late_answer(plant):
    """A commissioned GOLD wall whose first claim was answered one millisecond late.

    A second calibrated module waits in free stock, unreserved, so a later
    reservation can be offered to the contract once it is suspended.
    """
    scene = plant.reserved_spare_scene(
        model_base=FP16_STD,
        revision_overrides={"structural_load_kg_per_sqm": FP16_REQUIRED_LOAD_KG_PER_SQM},
        spare_brightness=FIRST_SPARE_NITS,
        spare_chroma=SPARE_CHROMA,
    )
    scene.reserve_candidate = plant.calibrated_module(
        scene.model["id"],
        serial_no="S-2",
        measured_brightness_nits=SECOND_SPARE_NITS,
        measured_color_x=SPARE_CHROMA[0],
        measured_color_y=SPARE_CHROMA[1],
    )

    plant.set_clock(FIRST_CASE_REPORTED_AT)
    first_case = plant.open_module_fault_case(
        scene.contract["id"],
        scene.cabinet["id"],
        faulty_module_id=scene.modules[0]["id"],
        symptom=FIRST_SYMPTOM,
    )
    assert first_case["case_state"] == CASE_OPEN
    assert_instant_equals(
        first_case["response_deadline_at"], FIRST_RESPONSE_DEADLINE, "response_deadline_at"
    )

    plant.set_clock(ONE_MILLISECOND_LATE)
    scene.first_case = validate_success(
        plant.api.respond_to_case(first_case["id"], plant.service), 200
    )
    return scene


def _both_deadlines_missed(plant):
    """The same wall, with the second claim also answered after its deadline."""
    scene = _a_live_wall_with_one_spare_and_one_late_answer(plant)

    plant.set_clock(SECOND_CASE_REPORTED_AT)
    second_case = validate_success(
        plant.api.create_service_case(
            module_fault_case_payload(
                scene.contract["id"],
                scene.cabinet["id"],
                scene.modules[1]["id"],
                symptom=SECOND_SYMPTOM,
            ),
            plant.service,
        ),
        201,
    )
    assert_instant_equals(
        second_case["response_deadline_at"], SECOND_RESPONSE_DEADLINE, "response_deadline_at"
    )

    plant.set_clock(ONE_HOUR_LATE)
    scene.second_case = validate_success(
        plant.api.respond_to_case(second_case["id"], plant.service), 200
    )
    return scene


class TestFirstBreachCountsWithoutSuspending:
    """One late answer moves the counter and nothing else."""

    def test_a_millisecond_of_lateness_is_a_breach_that_leaves_the_contract_active(self, plant):
        """The write stamps `responded_at` from the logical clock, moves the case
        `OPEN → RESPONDED`, and sets `response_breached` to true only when
        `responded_at` is **strictly later** than `response_deadline_at` — a response
        landing at exactly the deadline instant is on time. A breach raises the
        contract's `sla_breach_count` by 1, and when that counter reaches 2 the
        contract moves `ACTIVE → SUSPENDED`.

        Design: Corner/cross_cutting_complexity_layers/the_second_late_response_suspends_the_contract_for_good
        """
        scene = _a_live_wall_with_one_spare_and_one_late_answer(plant)

        assert_case_fields(
            scene.first_case, case_state=CASE_RESPONDED, response_breached=True
        )
        assert_instant_equals(scene.first_case["responded_at"], ONE_MILLISECOND_LATE)

        contract = plant.contract(scene.contract["id"])
        assert_contract_fields(
            contract,
            contract_state=CONTRACT_ACTIVE,
            response_hours=GOLD_RESPONSE_HOURS,
            sla_breach_count=1,
            spare_reserved_count=1,
            spare_required_count=GOLD_SPARE_REQUIRED_COUNT,
        )
        assert plant.project(scene.project["id"])["service_posture"] == POSTURE_NORMAL

    def test_a_contract_at_one_breach_still_accepts_new_claims(self, plant):
        """A new contract is created in `contract_state` `PENDING` with
        `spare_reserved_count` at 0, `sla_breach_count` at 0 and `warranty_start_at`
        null. Creation stamps `reported_at` from the logical clock, sets `case_state`
        to `OPEN`, and computes `response_deadline_at` as `reported_at` advanced by the
        contract's `response_hours` multiplied by a severity multiplier: half the
        contracted hours for `CRITICAL`, the full contracted hours for `MAJOR`, and
        double for `MINOR`.

        Design: Corner/cross_cutting_complexity_layers/the_second_late_response_suspends_the_contract_for_good
        """
        scene = _a_live_wall_with_one_spare_and_one_late_answer(plant)

        plant.set_clock(SECOND_CASE_REPORTED_AT)
        second_case = validate_success(
            plant.api.create_service_case(
                module_fault_case_payload(
                    scene.contract["id"],
                    scene.cabinet["id"],
                    scene.modules[1]["id"],
                    symptom=SECOND_SYMPTOM,
                ),
                plant.service,
            ),
            201,
        )

        assert_case_fields(
            second_case,
            case_state=CASE_OPEN,
            faulty_module_id=scene.modules[1]["id"],
            response_breached=False,
        )
        assert_instant_equals(second_case["reported_at"], SECOND_CASE_REPORTED_AT)
        assert_instant_equals(
            second_case["response_deadline_at"],
            SECOND_RESPONSE_DEADLINE,
            "response_deadline_at",
        )
        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_ACTIVE,
            sla_breach_count=1,
        )


class TestSecondBreachSuspendsAndClosesTheIntake:
    """Crossing the boundary freezes the whole warranty pipeline at once."""

    def test_the_second_late_answer_suspends_the_contract_and_flips_the_posture(self, plant):
        """A breach raises the contract's `sla_breach_count` by 1, and when that
        counter reaches 2 the contract moves `ACTIVE → SUSPENDED` and the project's
        `service_posture` becomes `AT_RISK`, which — per §3.8 — freezes every remaining
        case on that contract.

        Design: Corner/cross_cutting_complexity_layers/the_second_late_response_suspends_the_contract_for_good
        """
        scene = _both_deadlines_missed(plant)

        assert_case_fields(
            scene.second_case, case_state=CASE_RESPONDED, response_breached=True
        )
        assert_instant_equals(scene.second_case["responded_at"], ONE_HOUR_LATE)

        suspended = plant.contract(scene.contract["id"])
        assert_contract_fields(
            suspended,
            contract_state=CONTRACT_SUSPENDED,
            sla_breach_count=MAX_SLA_BREACHES,
            spare_reserved_count=1,
            spare_required_count=GOLD_SPARE_REQUIRED_COUNT,
        )
        assert plant.project(scene.project["id"])["service_posture"] == POSTURE_AT_RISK

    def test_the_suspension_closes_the_intake_immediately(self, plant):
        """The governing contract's `contract_state` is `ACTIVE` — otherwise
        `ERR_CONTRACT_NOT_ACTIVE`. This rung guards case opening, response, assessment
        and fulfilment, so a contract still `PENDING` or already `SUSPENDED` freezes
        the entire warranty pipeline.

        Design: Corner/cross_cutting_complexity_layers/the_second_late_response_suspends_the_contract_for_good
        """
        scene = _both_deadlines_missed(plant)

        refused = plant.api.create_service_case(
            module_fault_case_payload(
                scene.contract["id"],
                scene.cabinet["id"],
                scene.modules[0]["id"],
                symptom=THIRD_SYMPTOM,
            ),
            plant.service,
        )

        validate_error(refused, ERR_CONTRACT_NOT_ACTIVE, 409)
        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_SUSPENDED,
            sla_breach_count=MAX_SLA_BREACHES,
        )


class TestRestockingCannotLiftAPermanentSuspension:
    """The reactivation edge reads the counter too, and the counter only grows."""

    def test_a_further_reservation_succeeds_yet_the_contract_stays_suspended(self, plant):
        """If the contract was `SUSPENDED` and the reservation brings
        `spare_reserved_count` up to at least `spare_required_count` while
        `sla_breach_count` is still below 2, the contract moves `SUSPENDED → ACTIVE`,
        and the project's `service_posture` returns to `NORMAL` provided no other
        contract of that project is still `SUSPENDED`.

        Design: Corner/cross_cutting_complexity_layers/the_second_late_response_suspends_the_contract_for_good
        """
        scene = _both_deadlines_missed(plant)
        contract_version = plant.contract(scene.contract["id"])["version"]

        held = validate_success(
            plant.api.reserve_spare(
                scene.contract["id"],
                spare_reservation_payload(
                    contract_version, scene.reserve_candidate["id"]
                ),
                plant.service,
            ),
            201,
        )

        assert held["id"] == scene.reserve_candidate["id"]
        assert_module_fields(
            held,
            module_state=MODULE_CALIBRATED,
            reserved_service_contract_id=scene.contract["id"],
        )
        pinned = plant.contract(scene.contract["id"])
        assert_contract_fields(
            pinned,
            contract_state=CONTRACT_SUSPENDED,
            sla_breach_count=MAX_SLA_BREACHES,
            spare_reserved_count=2,
            spare_required_count=GOLD_SPARE_REQUIRED_COUNT,
        )
        assert plant.project(scene.project["id"])["service_posture"] == POSTURE_AT_RISK

    def test_neither_answered_case_gives_the_breach_back(self, plant):
        """`sla_breach_count`, however, only ever grows, and reactivation requires it
        to be below 2 — so a contract that has breached twice is pinned in `SUSPENDED`
        permanently no matter how many spares are reserved against it.

        Design: Corner/cross_cutting_complexity_layers/the_second_late_response_suspends_the_contract_for_good
        """
        scene = _both_deadlines_missed(plant)
        contract_version = plant.contract(scene.contract["id"])["version"]
        plant.api.reserve_spare(
            scene.contract["id"],
            spare_reservation_payload(contract_version, scene.reserve_candidate["id"]),
            plant.service,
        )

        first = plant.case(scene.first_case["id"])
        second = plant.case(scene.second_case["id"])

        assert_case_fields(first, case_state=CASE_RESPONDED, response_breached=True)
        assert_case_fields(second, case_state=CASE_RESPONDED, response_breached=True)
        assert_contract_fields(
            plant.contract(scene.contract["id"]),
            contract_state=CONTRACT_SUSPENDED,
            sla_breach_count=MAX_SLA_BREACHES,
        )
