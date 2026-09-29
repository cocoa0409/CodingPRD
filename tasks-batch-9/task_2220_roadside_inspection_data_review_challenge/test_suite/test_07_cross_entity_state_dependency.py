"""Gates that live on a different entity than the one being transitioned: the parent
report, the driver's employment dimension, and the carrier's fitness dimension.
"""

from typing import Any, Dict

from test_helpers import (
    AUDITOR_ALICE,
    ApiErrorId,
    BasicCategory,
    CapStatus,
    ChallengeStatus,
    ChallengeType,
    CoachingStatus,
    CurriculumCode,
    EmploymentStatus,
    EvidenceType,
    ReportStatus,
    SafetyFitnessStatus,
    UnitType,
    assert_measure,
    assert_one_decimal,
    factories as fac,
    fixtures as fx,
    get_success_data,
    make_carrier_analyst_headers,
    make_carrier_safety_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _draft_challenge_on_a_received_report(api) -> Dict[str, Any]:
    """A complete DRAFT challenge whose report is deliberately left in RECEIVED."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    report = fx.create_report(
        api,
        carrier["id"],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    violation = fx.add_violation(
        api, report["id"], code["id"], unit_type=UnitType.VEHICLE
    )
    challenge = fx.create_draft_challenge(
        api,
        carrier["id"],
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="Narrative does not support the violation.",
        target_violation_id=violation["id"],
    )
    fx.add_evidence(
        api, carrier["id"], challenge["id"], evidence_type=EvidenceType.ELD_RECORD
    )
    return {
        "carrier": carrier,
        "report": report,
        "violation": violation,
        "challenge": challenge,
    }


class TestChallengeSubmitGatedByReportStatus:
    def test_submit_is_refused_while_the_report_is_still_received(self, api):
        """PRD 3.6: "The challenged report must be in `VALIDATED`, `SCORED` or `AMENDED`
        status, else `ERR_INVALID_REPORT_STATE`."

        Design: Difficulty/cross_entity_state_dependency/challenge_submit_requires_report_beyond_received
        """
        scenario = _draft_challenge_on_a_received_report(api)
        carrier_id = scenario["carrier"]["id"]

        response = api.submit_challenge(
            scenario["challenge"]["id"], make_carrier_analyst_headers(carrier_id)
        )
        validate_error(response, ApiErrorId.INVALID_REPORT_STATE, 409)

        challenge = get_success_data(
            api.get_data_challenge(scenario["challenge"]["id"], fx.REVIEWER)
        )
        assert challenge["status"] == ChallengeStatus.DRAFT
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 0
        assert fx.read_violation(api, scenario["violation"]["id"])["under_challenge"] is False

    def test_the_same_submit_succeeds_once_the_report_is_scored(self, api):
        """PRD 3.6: "A successful first submission stamps `submitted_at` with the logical
        clock and `filing_age_days_at_submit` with the number of whole days between the
        report's `inspection_start` and that submit instant, and it increments the
        carrier's `challenge_quota_used` by 1."

        Design: Difficulty/cross_entity_state_dependency/challenge_submit_requires_report_beyond_received
        """
        scenario = _draft_challenge_on_a_received_report(api)
        carrier_id = scenario["carrier"]["id"]
        api.submit_challenge(
            scenario["challenge"]["id"], make_carrier_analyst_headers(carrier_id)
        )

        fx.validate_report(api, scenario["report"]["id"])
        fx.score_report(api, scenario["report"]["id"])
        assert fx.read_report(api, scenario["report"]["id"])["status"] == ReportStatus.SCORED

        validate_success(
            api.submit_challenge(
                scenario["challenge"]["id"], make_carrier_analyst_headers(carrier_id)
            ),
            200,
        )

        challenge = get_success_data(
            api.get_data_challenge(scenario["challenge"]["id"], fx.REVIEWER)
        )
        assert challenge["status"] == ChallengeStatus.SUBMITTED
        assert fx.read_violation(api, scenario["violation"]["id"])["under_challenge"] is True
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 1

        row = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_measure(row["certified_measure"], 0.000)


def _suspended_driver_with_a_coachable_violation(api) -> Dict[str, Any]:
    """A driver over the coaching trigger whose employment has been suspended."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    driver = fx.create_driver(
        api,
        carrier["id"],
        cdl_number="OH-D-99001",
        full_name="Dana Reyes",
        employment_status=EmploymentStatus.ACTIVE,
    )
    code = fx.create_violation_code(
        api,
        code="392.2R",
        description="Reckless driving",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=8,
        driver_attributable=True,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    _, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [
            {
                "violation_code_id": code["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            }
        ],
        driver_id=driver["id"],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    manager = make_carrier_safety_manager_headers(carrier["id"])
    get_success_data(
        api.patch_driver(
            driver["id"],
            {"employment_status": EmploymentStatus.SUSPENDED},
            manager,
        )
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "violation": rows[0],
        "manager": manager,
        "session": {
            "session_start": "2026-08-05T14:00:00Z",
            "session_end": "2026-08-10T16:00:00Z",
        },
    }


class TestCoachingGatedByDriverEmployment:
    def test_a_suspended_driver_cannot_be_coached(self, api):
        """PRD 3.9: "Four eligibility conditions apply: the driver's `employment_status`
        must be `ACTIVE`, else `ERR_DRIVER_NOT_EMPLOYED`; the named violation's
        `driver_id` must equal the assignment's `driver_id`, else
        `ERR_VIOLATION_NOT_ATTRIBUTED_TO_DRIVER`; the violation's report must be in
        `SCORED` status, else `ERR_INVALID_REPORT_STATE`; and the violation's effective
        violation code must have `driver_attributable` set to true, else
        `ERR_CODE_NOT_DRIVER_ATTRIBUTABLE`."

        Design: Difficulty/cross_entity_state_dependency/coaching_assignment_requires_active_driver
        """
        scenario = _suspended_driver_with_a_coachable_violation(api)
        response = api.create_coaching_assignment(
            fac.create_coaching_assignment_payload(
                scenario["driver"]["id"],
                scenario["violation"]["id"],
                curriculum_code=CurriculumCode.UNSAFE_DRIVING_101,
                **scenario["session"],
            ),
            scenario["manager"],
        )
        validate_error(response, ApiErrorId.DRIVER_NOT_EMPLOYED, 422)

        assert fx.read_driver(api, scenario["driver"]["id"])["open_coaching_count"] == 0
        assert fx.read_carrier(api, scenario["carrier"]["id"])["open_coaching_count"] == 0

    def test_reinstating_the_driver_lets_the_identical_call_through(self, api):
        """PRD 3.9: "Creation copies `carrier_id` from the driver, sets `status` to
        `ASSIGNED`, sets `due_at` to `session_end` plus 14 days, and increments
        `open_coaching_count` on both the carrier and the driver."

        Design: Difficulty/cross_entity_state_dependency/coaching_assignment_requires_active_driver
        """
        scenario = _suspended_driver_with_a_coachable_violation(api)
        payload = fac.create_coaching_assignment_payload(
            scenario["driver"]["id"],
            scenario["violation"]["id"],
            curriculum_code=CurriculumCode.UNSAFE_DRIVING_101,
            **scenario["session"],
        )
        api.create_coaching_assignment(payload, scenario["manager"])

        get_success_data(
            api.patch_driver(
                scenario["driver"]["id"],
                {"employment_status": EmploymentStatus.ACTIVE},
                scenario["manager"],
            )
        )
        assert (
            fx.read_driver(api, scenario["driver"]["id"])["employment_status"]
            == EmploymentStatus.ACTIVE
        )

        assignment = validate_success(
            api.create_coaching_assignment(payload, scenario["manager"]), 201
        )
        assert assignment["status"] == CoachingStatus.ASSIGNED
        assert assignment["carrier_id"] == scenario["carrier"]["id"]
        assert assignment["due_at"].startswith("2026-08-24T16:00:00")

        driver = fx.read_driver(api, scenario["driver"]["id"])
        assert driver["open_coaching_count"] == 1
        assert driver["coaching_required"] is True
        assert fx.read_carrier(api, scenario["carrier"]["id"])["open_coaching_count"] == 1


def _unrated_carrier(api) -> Dict[str, Any]:
    """A freshly registered carrier, still UNRATED, with its version observed."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    return {
        "carrier": carrier,
        "version": fx.current_version(api, "carrier", carrier["id"]),
    }


class TestCapCreationGatedByFitnessStatus:
    def test_an_unrated_carrier_owes_no_plan(self, api):
        """PRD 3.10: "Creating a plan for a carrier whose status is `UNRATED` or
        `SATISFACTORY` is rejected with `ERR_CAP_NOT_REQUIRED`, and the same check is
        repeated at submission."

        Design: Difficulty/cross_entity_state_dependency/cap_creation_requires_conditional_or_unsatisfactory_fitness
        """
        scenario = _unrated_carrier(api)
        carrier_id = scenario["carrier"]["id"]

        response = api.create_corrective_action_plan(
            fac.create_cap_payload(
                carrier_id,
                scenario["version"],
                narrative="Voluntary remediation plan.",
            ),
            make_carrier_analyst_headers(carrier_id),
        )
        validate_error(response, ApiErrorId.CAP_NOT_REQUIRED, 422)

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["safety_fitness_status"] == SafetyFitnessStatus.UNRATED
        _, meta = validate_paginated(
            api.list_corrective_action_plans(fx.AUDITOR, {"carrier_id": carrier_id})
        )
        assert meta["total_count"] == 0

    def test_a_conditional_determination_opens_the_door(self, api):
        """PRD 3.10: "The plan starts in `DRAFT` and records
        `triggering_fitness_status`, a snapshot of the carrier's `safety_fitness_status`
        at creation, which is therefore always `CONDITIONAL` or `UNSATISFACTORY`."

        Design: Difficulty/cross_entity_state_dependency/cap_creation_requires_conditional_or_unsatisfactory_fitness
        """
        scenario = _unrated_carrier(api)
        carrier_id = scenario["carrier"]["id"]
        api.create_corrective_action_plan(
            fac.create_cap_payload(carrier_id, scenario["version"]),
            make_carrier_analyst_headers(carrier_id),
        )

        fx.issue_fitness_determination(api, carrier_id, SafetyFitnessStatus.CONDITIONAL)
        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["safety_fitness_status"] == SafetyFitnessStatus.CONDITIONAL
        assert carrier["fitness_determined_at"].startswith("2026-08-01T00:00:00")
        assert carrier["fitness_determined_by_user_id"] == AUDITOR_ALICE
        assert carrier["version"] == scenario["version"] + 1

        cap = fx.create_cap(
            api,
            carrier_id,
            narrative="Remediation plan for the conditional rating.",
        )
        assert cap["status"] == CapStatus.DRAFT
        assert cap["triggering_fitness_status"] == SafetyFitnessStatus.CONDITIONAL
        assert cap["item_count"] == 0
        assert_one_decimal(cap["completion_pct"], 0.0)
        assert cap["superseded_cap_id"] is None
