"""Lifecycles: declared initial states, the side effects each transition owns, the
transitions that are refused from the wrong status, and the terminal dead ends.
"""

from typing import Any, Dict

from test_helpers import (
    AUDITOR_BOB,
    AUDITOR_DAVE,
    AlertStatus,
    ApiErrorId,
    BasicCategory,
    CapDecision,
    CapItemAction,
    CapItemStatus,
    CapReviewBranch,
    CapReviewOutcome,
    CapStatus,
    ChallengeStatus,
    ChallengeType,
    CoachingStatus,
    CourtStatus,
    CurriculumCode,
    EmploymentStatus,
    EvidenceType,
    InterventionStatus,
    RecordUpdateStatus,
    RemovalReason,
    ReportStatus,
    ResolutionDisposition,
    ReviewAction,
    SafetyFitnessStatus,
    SelectionBand,
    UnitType,
    ViolationStatus,
    assert_credit_pct,
    assert_measure,
    assert_one_decimal,
    assert_two_decimals,
    factories as fac,
    fixtures as fx,
    get_success_data,
    make_auditor_headers,
    make_carrier_analyst_headers,
    make_carrier_safety_manager_headers,
    validate_error,
    validate_success,
)

UD = BasicCategory.UNSAFE_DRIVING


def _driver_violation_scored(api, report_number: str, vin: str) -> Dict[str, Any]:
    """A carrier, an ACTIVE driver, and one SCORED report whose single DRIVER-unit
    violation of weight 5 is attributed to that driver (time-weighted severity 15.0)."""
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
        api, code="392.2S", basic_category=UD, severity_weight=5, driver_attributable=True
    )
    fx.create_threshold(
        api,
        basic_category=UD,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [
            {
                "violation_code_id": code["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            }
        ],
        report_number=report_number,
        vehicle_vin=vin,
        driver_id=driver["id"],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "code": code,
        "report": report,
        "violation": rows[0],
        "manager": make_carrier_safety_manager_headers(carrier["id"]),
        "analyst": make_carrier_analyst_headers(carrier["id"]),
    }


def _vehicle_violations_scored(api, report_number: str, vin: str, count: int = 1):
    """A carrier with one SCORED report carrying `count` weight-5 VEHICLE violations."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(api, code="392.2S", basic_category=UD, severity_weight=5)
    fx.create_threshold(
        api,
        basic_category=UD,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}] * count,
        report_number=report_number,
        vehicle_vin=vin,
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {
        "carrier": carrier,
        "code": code,
        "report": report,
        "violations": rows,
        "analyst": make_carrier_analyst_headers(carrier["id"]),
    }


class TestInitialStates:
    def test_every_workflow_entity_lands_on_its_declared_first_status(self, api):
        """PRD 3.8: "The new record starts with `court_status` `PENDING`,
        `record_update_status` `NOT_APPLIED`, `severity_factor` 1.0 and `superseded`
        false."

        Design: Corner/state_machines/newly_created_entities_start_in_declared_initial_states
        """
        scenario = _driver_violation_scored(api, "OH2026070201", "1FUJA6CK21LK00201")
        carrier_id = scenario["carrier"]["id"]
        violation_id = scenario["violation"]["id"]
        fx.issue_fitness_determination(api, carrier_id, SafetyFitnessStatus.CONDITIONAL)

        challenge = fx.create_draft_challenge(
            api,
            carrier_id,
            scenario["report"]["id"],
            challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
            narrative="Radar log missing.",
            target_violation_id=violation_id,
        )
        assert challenge["status"] == ChallengeStatus.DRAFT
        assert challenge["info_request_count"] == 0
        assert challenge["evidence_count"] == 0
        assert challenge["carrier_id"] == carrier_id
        assert challenge["submitted_at"] is None
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 0

        adjudication = fx.create_adjudication(
            api, violation_id, citation_number="OH-CIT-7781", court_date="2026-09-15T00:00:00Z"
        )
        assert adjudication["court_status"] == CourtStatus.PENDING
        assert adjudication["record_update_status"] == RecordUpdateStatus.NOT_APPLIED
        assert_one_decimal(adjudication["severity_factor"], 1.0)
        assert adjudication["superseded"] is False

        coaching = fx.create_coaching_assignment(
            api,
            carrier_id,
            scenario["driver"]["id"],
            violation_id,
            curriculum_code=CurriculumCode.UNSAFE_DRIVING_101,
            session_start="2026-08-05T14:00:00Z",
            session_end="2026-08-05T16:00:00Z",
        )
        assert coaching["status"] == CoachingStatus.ASSIGNED
        assert coaching["due_at"].startswith("2026-08-19T16:00:00")
        assert coaching["carrier_id"] == carrier_id

        cap = fx.create_cap(api, carrier_id, narrative="Speed management plan.")
        assert cap["status"] == CapStatus.DRAFT
        assert cap["triggering_fitness_status"] == SafetyFitnessStatus.CONDITIONAL
        assert cap["item_count"] == 0
        assert_one_decimal(cap["completion_pct"], 0.0)
        assert cap["superseded_cap_id"] is None

        item = fx.add_cap_item(
            api,
            carrier_id,
            cap["id"],
            basic_category=UD,
            description="Install speed governors on the line-haul tractors",
            target_completion_date="2026-10-01T00:00:00Z",
        )
        assert item["status"] == CapItemStatus.PROPOSED

        rolled = fx.read_cap(api, cap["id"])
        assert rolled["item_count"] == 1
        assert rolled["committed_item_count"] == 0
        assert_one_decimal(rolled["completion_pct"], 0.0)


class TestValidateThenScore:
    def test_validate_writes_no_score_and_score_fires_the_whole_chain(self, api):
        """PRD 3.3: "The basis instant used for the pass is stamped on the report as
        `severity_basis_utc`, and `scored_at` records the logical-clock instant of the
        pass."

        Design: Corner/state_machines/report_validate_then_score_applies_declared_side_effects
        """
        fx.set_clock(api)
        carrier = fx.create_carrier(api)
        code = fx.create_violation_code(api, code="392.2S", basic_category=UD, severity_weight=5)
        fx.create_threshold(
            api,
            basic_category=UD,
            carrier_segment="MEDIUM",
            measure_at_p50=0.5,
            measure_at_p65=1.0,
            measure_at_p80=2.0,
        )
        report, rows = fx.build_validated_report(
            api,
            carrier["id"],
            [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
            report_number="OH2026070202",
            vehicle_vin="1FUJA6CK21LK00202",
            inspection_start="2026-07-01T14:00:00Z",
            inspection_end="2026-07-01T15:00:00Z",
        )

        validated = fx.read_report(api, report["id"])
        assert validated["status"] == ReportStatus.VALIDATED
        assert_one_decimal(validated["total_time_weighted_severity"], 0.0)
        assert validated["scored_at"] is None
        unpinned = fx.read_violation(api, rows[0]["id"])
        assert unpinned["time_weight"] == 0
        assert_one_decimal(unpinned["time_weighted_severity"], 0.0)

        fx.score_report(api, report["id"])

        scored = fx.read_report(api, report["id"])
        assert scored["status"] == ReportStatus.SCORED
        assert scored["severity_basis_utc"].startswith("2026-08-01T00:00:00")
        assert scored["scored_at"].startswith("2026-08-01T00:00:00")
        assert scored["active_violation_count"] == 1
        assert_one_decimal(scored["total_time_weighted_severity"], 15.0)

        violation = fx.read_violation(api, rows[0]["id"])
        assert violation["code_weight_snapshot"] == 5
        assert violation["oos_add_on_snapshot"] == 0
        assert violation["time_weight"] == 3
        assert_one_decimal(violation["time_weighted_severity"], 15.0)
        assert violation["has_stale_code_pin"] is False
        assert violation["basic_category"] == UD

        row = fx.read_basic_score(api, carrier["id"], UD)
        assert row["relevant_inspection_count"] == 1
        assert_one_decimal(row["denominator_value"], 30.0)
        assert_measure(row["provisional_measure"], 0.500)
        assert_measure(row["certified_measure"], 0.500)
        assert_one_decimal(row["percentile"], 50.0)
        assert row["alert_status"] == AlertStatus.MONITOR

        fresh = fx.read_carrier(api, carrier["id"])
        assert fresh["open_alert_count"] == 0
        assert_one_decimal(fresh["max_percentile"], 50.0)
        assert fresh["intervention_status"] == InterventionStatus.NONE
        assert_one_decimal(fresh["iss_pre_credit_value"], 17.5)
        assert_one_decimal(fresh["iss_value"], 17.5)
        assert fresh["selection_band"] == SelectionBand.PASS
        assert fresh["scored_violation_count"] == 1
        assert fresh["unattributed_violation_count"] == 1


class TestCoachingStartThenComplete:
    def test_only_completion_releases_the_open_coaching_ledger(self, api):
        """PRD 3.9: "Completing a session is permitted only from `IN_PROGRESS`, takes an
        `attestation_note` from the safety manager, stamps `completed_at`, moves the
        assignment to `COMPLETED`, and decrements `open_coaching_count` on both the
        carrier and the driver."

        Design: Corner/state_machines/coaching_start_then_complete_decrements_open_counts
        """
        scenario = _driver_violation_scored(api, "OH2026070203", "1FUJA6CK21LK00203")
        carrier_id = scenario["carrier"]["id"]
        driver_id = scenario["driver"]["id"]
        coaching = fx.create_coaching_assignment(
            api,
            carrier_id,
            driver_id,
            scenario["violation"]["id"],
            curriculum_code=CurriculumCode.UNSAFE_DRIVING_101,
            session_start="2026-08-05T14:00:00Z",
            session_end="2026-08-05T16:00:00Z",
        )

        started = get_success_data(api.start_coaching(coaching["id"], scenario["manager"]))
        assert started["status"] == CoachingStatus.IN_PROGRESS
        assert started["started_at"].startswith("2026-08-01T00:00:00")
        assert fx.read_carrier(api, carrier_id)["open_coaching_count"] == 1
        assert fx.read_driver(api, driver_id)["open_coaching_count"] == 1

        note = "Two-hour speed management session delivered and signed."
        done = get_success_data(
            api.complete_coaching(
                coaching["id"], {"attestation_note": note}, scenario["manager"]
            )
        )
        assert done["status"] == CoachingStatus.COMPLETED
        assert done["completed_at"].startswith("2026-08-01T00:00:00")
        assert done["attestation_note"] == note
        assert done["waived_reason"] is None
        assert fx.read_carrier(api, carrier_id)["open_coaching_count"] == 0
        driver = fx.read_driver(api, driver_id)
        assert driver["open_coaching_count"] == 0
        assert driver["coaching_required"] is True


class TestChallengeRejection:
    def test_rejection_restores_the_measure_but_keeps_the_quota_spent(self, api):
        """PRD 3.6: "It recomputes the carrier's `resolved_challenge_count_24mo`, leaving
        `accepted_challenge_count_24mo` unchanged, and increments the challenge's
        `version` by 1."

        Design: Corner/state_machines/challenge_resolve_reject_restores_certified_measure_and_counts
        """
        scenario = _vehicle_violations_scored(api, "OH2026070204", "1FUJA6CK21LK00204")
        carrier_id = scenario["carrier"]["id"]
        violation_id = scenario["violations"][0]["id"]
        challenge = fx.build_submitted_challenge(
            api,
            carrier_id,
            scenario["report"]["id"],
            evidence_type=EvidenceType.PHOTO,
            challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
            narrative="No radar calibration certificate on file.",
            target_violation_id=violation_id,
        )

        assigned = fx.review_challenge(api, challenge["id"], ReviewAction.ASSIGN)
        assert assigned["status"] == ChallengeStatus.UNDER_REVIEW
        assert fx.read_violation(api, violation_id)["under_challenge"] is True
        assert_measure(fx.read_basic_score(api, carrier_id, UD)["certified_measure"], 0.000)

        rejected = fx.review_challenge(
            api,
            challenge["id"],
            ReviewAction.RESOLVE_REJECT,
            review_note="Calibration record produced by the state; violation stands.",
            resolution_disposition=ResolutionDisposition.NOT_SUBSTANTIATED,
        )
        assert rejected["status"] == ChallengeStatus.RESOLVED_REJECTED
        assert rejected["resolution_disposition"] == ResolutionDisposition.NOT_SUBSTANTIATED
        assert rejected["resolved_by_user_id"] == "review_officer_1"
        assert rejected["resolved_at"].startswith("2026-08-01T00:00:00")

        violation = fx.read_violation(api, violation_id)
        assert violation["under_challenge"] is False
        assert violation["status"] == ViolationStatus.ACTIVE

        row = fx.read_basic_score(api, carrier_id, UD)
        assert_one_decimal(row["challenged_time_weighted_severity"], 0.0)
        assert_measure(row["certified_measure"], 0.500)
        assert_one_decimal(row["percentile"], 50.0)
        assert row["alert_status"] == AlertStatus.MONITOR

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["challenge_quota_used"] == 1
        assert carrier["accepted_challenge_count_24mo"] == 0
        assert carrier["resolved_challenge_count_24mo"] == 1
        assert_credit_pct(carrier["data_quality_credit_pct"], 0.0)
        assert_one_decimal(carrier["iss_value"], 17.5)


class TestInvalidReportAndCoachingTransitions:
    def test_scoring_a_received_report_and_completing_an_assigned_session_are_refused(self, api):
        """PRD 3.9: "A start or complete attempted from a status that does not permit it
        is rejected with `ERR_INVALID_COACHING_STATE`."

        Design: Corner/state_machines/invalid_from_state_transitions_on_report_and_coaching_rejected
        """
        scenario = _driver_violation_scored(api, "OH2026070205", "1FUJA6CK21LK00205")
        carrier_id = scenario["carrier"]["id"]
        coaching = fx.create_coaching_assignment(
            api,
            carrier_id,
            scenario["driver"]["id"],
            scenario["violation"]["id"],
            curriculum_code=CurriculumCode.UNSAFE_DRIVING_101,
            session_start="2026-08-05T14:00:00Z",
            session_end="2026-08-05T16:00:00Z",
        )
        second = fx.create_report(
            api,
            carrier_id,
            report_number="OH2026070206",
            vehicle_vin="1FUJA6CK21LK00206",
            inspection_start="2026-07-02T14:00:00Z",
            inspection_end="2026-07-02T15:00:00Z",
        )
        appended = fx.add_violation(
            api, second["id"], scenario["code"]["id"], unit_type=UnitType.VEHICLE
        )

        validate_error(
            api.score_report(second["id"], fx.OFFICER), ApiErrorId.INVALID_REPORT_STATE, 409
        )
        untouched = fx.read_report(api, second["id"])
        assert untouched["status"] == ReportStatus.RECEIVED
        assert_one_decimal(untouched["total_time_weighted_severity"], 0.0)
        assert fx.read_violation(api, appended["id"])["time_weight"] == 0
        assert_one_decimal(
            fx.read_basic_score(api, carrier_id, UD)["total_time_weighted_severity"], 15.0
        )

        validate_error(
            api.complete_coaching(
                coaching["id"], {"attestation_note": "Session delivered."}, scenario["manager"]
            ),
            ApiErrorId.INVALID_COACHING_STATE,
            409,
        )
        assignment = get_success_data(api.get_coaching_assignment(coaching["id"], fx.AUDITOR))
        assert assignment["status"] == CoachingStatus.ASSIGNED
        assert assignment["completed_at"] is None
        assert fx.read_carrier(api, carrier_id)["open_coaching_count"] == 1


class TestInvalidCapAndItemTransitions:
    def test_the_fork_and_the_item_rungs_cannot_be_skipped_from_draft(self, api):
        """PRD 3.10: "An action that does not match the item's current status is rejected
        with `ERR_INVALID_CAP_ITEM_STATE`."

        Design: Corner/state_machines/invalid_from_state_transitions_on_cap_and_items_rejected
        """
        fx.set_clock(api)
        carrier = fx.create_carrier(api)
        carrier_id = carrier["id"]
        fx.issue_fitness_determination(api, carrier_id, SafetyFitnessStatus.CONDITIONAL)
        cap = fx.create_cap(
            api, carrier_id, narrative="Speed management corrective action plan."
        )
        item = fx.add_cap_item(
            api,
            carrier_id,
            cap["id"],
            basic_category=UD,
            description="Install speed governors on the line-haul tractors",
            target_completion_date="2026-10-01T00:00:00Z",
        )

        validate_error(
            api.review_cap(
                cap["id"],
                {
                    "branch": CapReviewBranch.SAFETY,
                    "outcome": CapReviewOutcome.CLEARED,
                    "note": "Looks fine to me.",
                },
                make_auditor_headers(AUDITOR_BOB),
            ),
            ApiErrorId.INVALID_CAP_STATE,
            409,
        )
        assert fx.read_cap(api, cap["id"])["safety_review_outcome"] is None

        validate_error(
            api.decide_cap(
                cap["id"],
                {"decision": CapDecision.ACCEPT, "note": "Approving early."},
                make_auditor_headers(AUDITOR_DAVE),
            ),
            ApiErrorId.INVALID_CAP_STATE,
            409,
        )
        assert fx.read_cap(api, cap["id"])["decision"] is None
        assert (
            fx.read_carrier(api, carrier_id)["safety_fitness_status"]
            == SafetyFitnessStatus.CONDITIONAL
        )

        validate_error(
            api.set_action_item_status(
                item["id"],
                fac.cap_item_status_payload(CapItemAction.VERIFY),
                make_auditor_headers(AUDITOR_BOB),
            ),
            ApiErrorId.INVALID_CAP_ITEM_STATE,
            409,
        )
        validate_error(
            api.set_action_item_status(
                item["id"],
                fac.cap_item_status_payload(CapItemAction.IMPLEMENT),
                make_carrier_safety_manager_headers(carrier_id),
            ),
            ApiErrorId.INVALID_CAP_ITEM_STATE,
            409,
        )

        items = get_success_data(api.list_action_items(cap["id"], fx.AUDITOR))
        assert [row["status"] for row in items] == [CapItemStatus.PROPOSED]
        final = fx.read_cap(api, cap["id"])
        assert final["status"] == CapStatus.DRAFT
        assert final["verified_item_count"] == 0
        assert_one_decimal(final["completion_pct"], 0.0)


class TestRepeatedTriggers:
    def test_transitions_are_not_idempotent_upserts(self, api):
        """PRD 3.6: "`RESOLVED_ACCEPTED`, `RESOLVED_REJECTED` and `WITHDRAWN` are all
        terminal."

        Design: Corner/state_machines/repeated_triggers_on_the_same_resource_rejected
        """
        scenario = _vehicle_violations_scored(api, "OH2026070207", "1FUJA6CK21LK00207")
        carrier_id = scenario["carrier"]["id"]
        report_id = scenario["report"]["id"]
        challenge = fx.create_draft_challenge(
            api,
            carrier_id,
            report_id,
            challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
            narrative="Radar log missing.",
            target_violation_id=scenario["violations"][0]["id"],
        )
        get_success_data(
            api.withdraw_challenge(
                challenge["id"], scenario["analyst"], {"withdraw_note": "Filed in error."}
            )
        )

        validate_error(
            api.validate_report(report_id, fx.OFFICER), ApiErrorId.INVALID_REPORT_STATE, 409
        )
        validate_error(
            api.add_violation(
                report_id,
                fac.create_violation_payload(scenario["code"]["id"]),
                fx.OFFICER,
            ),
            ApiErrorId.INVALID_REPORT_STATE,
            409,
        )
        validate_error(
            api.withdraw_challenge(
                challenge["id"],
                scenario["analyst"],
                {"withdraw_note": "Filed in error, again."},
            ),
            ApiErrorId.INVALID_CHALLENGE_STATE,
            409,
        )

        report = fx.read_report(api, report_id)
        assert report["status"] == ReportStatus.SCORED
        assert report["active_violation_count"] == 1
        assert_one_decimal(report["total_time_weighted_severity"], 15.0)
        assert (
            get_success_data(api.get_data_challenge(challenge["id"], fx.REVIEWER))["status"]
            == ChallengeStatus.WITHDRAWN
        )
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 0
        assert fx.read_violation(api, scenario["violations"][0]["id"])["under_challenge"] is False


class TestAdjudicationDimensionGuards:
    def test_early_apply_and_a_second_court_result_are_both_refused(self, api):
        """PRD 3.8: "The adjudication's current `court_status` must be `PENDING`, else
        `ERR_INVALID_ADJUDICATION_STATE`, and its `superseded` flag must be false, else
        `ERR_ADJUDICATION_SUPERSEDED`."

        Design: Corner/state_machines/adjudication_early_apply_and_second_court_result_rejected
        """
        scenario = _vehicle_violations_scored(api, "OH2026070208", "1FUJA6CK21LK00208")
        violation_id = scenario["violations"][0]["id"]
        adjudication = fx.create_adjudication(
            api, violation_id, citation_number="OH-CIT-7782", court_date="2026-09-15T00:00:00Z"
        )

        validate_error(
            api.apply_to_record(adjudication["id"], fx.REVIEWER),
            ApiErrorId.INVALID_ADJUDICATION_STATE,
            409,
        )
        pending = get_success_data(
            api.get_citation_adjudication(adjudication["id"], fx.OFFICER)
        )
        assert pending["record_update_status"] == RecordUpdateStatus.NOT_APPLIED
        assert pending["applied_at"] is None

        convicted = validate_success(
            api.record_court_result(
                adjudication["id"],
                fac.court_result_payload(
                    CourtStatus.CONVICTED, court_note="Found liable; fine paid."
                ),
                fx.OFFICER,
            ),
            200,
        )
        assert convicted["court_status"] == CourtStatus.CONVICTED
        assert_one_decimal(convicted["severity_factor"], 1.0)
        assert convicted["court_result_recorded_at"].startswith("2026-08-01T00:00:00")
        assert convicted["record_update_status"] == RecordUpdateStatus.NOT_APPLIED

        validate_error(
            api.record_court_result(
                adjudication["id"],
                fac.court_result_payload(
                    CourtStatus.DISMISSED, court_note="Second bite at the apple."
                ),
                fx.OFFICER,
            ),
            ApiErrorId.INVALID_ADJUDICATION_STATE,
            409,
        )
        unchanged = get_success_data(
            api.get_citation_adjudication(adjudication["id"], fx.OFFICER)
        )
        assert unchanged["court_status"] == CourtStatus.CONVICTED
        assert_one_decimal(unchanged["severity_factor"], 1.0)

        violation = fx.read_violation(api, violation_id)
        assert violation["status"] == ViolationStatus.ACTIVE
        assert_one_decimal(violation["time_weighted_severity"], 15.0)


class TestAdjudicationReapplyAndSupersede:
    def test_a_settled_push_and_a_superseded_push_report_different_refusals(self, api):
        """PRD 3.8: "Three preconditions apply: `record_update_status` must still be
        `NOT_APPLIED`, else `ERR_ALREADY_APPLIED_TO_RECORD`; `court_status` must not be
        `PENDING`, else `ERR_INVALID_ADJUDICATION_STATE`; and the linked violation's
        `status` must be `ACTIVE` or `RECODED`, else `ERR_VIOLATION_NOT_ACTIVE`."

        Design: Corner/state_machines/adjudication_reapply_and_superseded_apply_rejected
        """
        scenario = _vehicle_violations_scored(api, "OH2026070209", "1FUJA6CK21LK00209", count=2)
        carrier_id = scenario["carrier"]["id"]
        first_id, second_id = (row["id"] for row in scenario["violations"])

        settled = fx.create_adjudication(
            api, first_id, citation_number="OH-CIT-7783", court_date="2026-09-15T00:00:00Z"
        )
        fx.record_court_result(api, settled["id"], CourtStatus.CONVICTED)
        fx.apply_adjudication(api, settled["id"])

        older = fx.create_adjudication(
            api, second_id, citation_number="OH-CIT-7784", court_date="2026-09-15T00:00:00Z"
        )
        fx.record_court_result(api, older["id"], CourtStatus.CONVICTED)
        newer = fx.create_adjudication(
            api, second_id, citation_number="OH-CIT-7785", court_date="2026-10-20T00:00:00Z"
        )

        validate_error(
            api.apply_to_record(settled["id"], fx.REVIEWER),
            ApiErrorId.ALREADY_APPLIED_TO_RECORD,
            409,
        )
        applied = get_success_data(api.get_citation_adjudication(settled["id"], fx.OFFICER))
        assert applied["record_update_status"] == RecordUpdateStatus.NOT_APPLICABLE
        assert applied["applied_by_user_id"] == "review_officer_1"
        assert applied["superseded"] is False

        validate_error(
            api.apply_to_record(older["id"], fx.REVIEWER),
            ApiErrorId.ADJUDICATION_SUPERSEDED,
            409,
        )
        stale = get_success_data(api.get_citation_adjudication(older["id"], fx.OFFICER))
        assert stale["superseded"] is True
        assert stale["record_update_status"] == RecordUpdateStatus.NOT_APPLIED
        live = get_success_data(api.get_citation_adjudication(newer["id"], fx.OFFICER))
        assert live["superseded"] is False
        assert live["court_status"] == CourtStatus.PENDING

        assert fx.read_violation(api, first_id)["status"] == ViolationStatus.ACTIVE
        assert fx.read_violation(api, second_id)["status"] == ViolationStatus.ACTIVE
        row = fx.read_basic_score(api, carrier_id, UD)
        assert_measure(row["certified_measure"], 1.000)
        assert_one_decimal(row["percentile"], 65.0)
        assert row["alert_status"] == AlertStatus.ALERT


class TestAttributionOnRemovedViolation:
    def test_a_removed_violation_is_out_of_the_attribution_game(self, api):
        """PRD 3.9: "Setting it supplies a `driver_id`; the named driver must be employed
        by the violation's attributed carrier, else `ERR_DRIVER_CARRIER_MISMATCH`, and the
        violation must not already be `REMOVED`, else `ERR_VIOLATION_NOT_ACTIVE`."

        Design: Corner/state_machines/driver_attribution_on_removed_violation_rejected
        """
        scenario = _vehicle_violations_scored(api, "OH2026070210", "1FUJA6CK21LK00210")
        carrier_id = scenario["carrier"]["id"]
        violation_id = scenario["violations"][0]["id"]
        driver = fx.create_driver(
            api,
            carrier_id,
            cdl_number="OH-D-99001",
            full_name="Dana Reyes",
            employment_status=EmploymentStatus.ACTIVE,
        )
        challenge = fx.build_submitted_challenge(
            api,
            carrier_id,
            scenario["report"]["id"],
            evidence_type=EvidenceType.PHOTO,
            challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
            narrative="Officer notes describe a different tractor.",
            target_violation_id=violation_id,
        )
        fx.review_challenge(api, challenge["id"], ReviewAction.ASSIGN)
        fx.review_challenge(
            api,
            challenge["id"],
            ReviewAction.RESOLVE_ACCEPT,
            review_note="Unit photo confirms the violation was misrecorded.",
        )

        validate_error(
            api.attribute_driver(
                violation_id,
                {"driver_id": driver["id"]},
                make_carrier_safety_manager_headers(carrier_id),
            ),
            ApiErrorId.VIOLATION_NOT_ACTIVE,
            409,
        )

        violation = fx.read_violation(api, violation_id)
        assert violation["status"] == ViolationStatus.REMOVED
        assert violation["removal_reason"] == RemovalReason.CHALLENGE_ACCEPTED
        assert violation["driver_id"] is None
        assert_one_decimal(violation["time_weighted_severity"], 0.0)

        resolved = get_success_data(api.get_data_challenge(challenge["id"], fx.REVIEWER))
        assert resolved["status"] == ChallengeStatus.RESOLVED_ACCEPTED
        assert resolved["resolution_disposition"] == ResolutionDisposition.VIOLATION_REMOVED

        released = fx.read_driver(api, driver["id"])
        assert released["attributed_violation_count"] == 0
        assert_two_decimals(released["strict_attribution_score"], 0.00)
        assert released["coaching_required"] is False

        row = fx.read_basic_score(api, carrier_id, UD)
        assert_one_decimal(row["total_time_weighted_severity"], 0.0)
        assert_measure(row["certified_measure"], 0.000)
        assert_one_decimal(fx.read_carrier(api, carrier_id)["iss_value"], 0.0)


class TestDuplicateReportAcceptance:
    def test_the_duplicate_is_rescinded_and_linked_to_the_survivor(self, api):
        """PRD 3.6: "The report's `duplicate_master_report_id` is set to the challenge's
        `duplicate_of_report_id`, marking which report survived."

        Design: Corner/state_machines/duplicate_report_acceptance_rescinds_and_links_master
        """
        fx.set_clock(api)
        carrier = fx.create_carrier(api)
        carrier_id = carrier["id"]
        code = fx.create_violation_code(api, code="392.2S", basic_category=UD, severity_weight=5)
        fx.create_threshold(
            api,
            basic_category=UD,
            carrier_segment="MEDIUM",
            measure_at_p50=0.5,
            measure_at_p65=1.0,
            measure_at_p80=2.0,
        )
        spec = [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}]
        master, master_rows = fx.build_scored_report(
            api,
            carrier_id,
            spec,
            report_number="OH2026070211",
            vehicle_vin="1FUJA6CK21LK00211",
            inspection_start="2026-07-01T14:00:00Z",
            inspection_end="2026-07-01T15:00:00Z",
        )
        duplicate, duplicate_rows = fx.build_scored_report(
            api,
            carrier_id,
            spec,
            report_number="OH2026070212",
            vehicle_vin="1FUJA6CK21LK00211",
            inspection_start="2026-07-02T14:00:00Z",
            inspection_end="2026-07-02T15:00:00Z",
        )
        challenge = fx.build_submitted_challenge(
            api,
            carrier_id,
            duplicate["id"],
            evidence_type=EvidenceType.COURT_DOCUMENT,
            challenge_type=ChallengeType.DUPLICATE_REPORT,
            narrative="Same tractor, same stop, reported twice by two officers.",
            duplicate_of_report_id=master["id"],
        )
        fx.review_challenge(api, challenge["id"], ReviewAction.ASSIGN)

        accepted = fx.review_challenge(
            api,
            challenge["id"],
            ReviewAction.RESOLVE_ACCEPT,
            review_note="Confirmed duplicate of report OH2026070211.",
        )
        assert accepted["status"] == ChallengeStatus.RESOLVED_ACCEPTED
        assert accepted["resolution_disposition"] == ResolutionDisposition.REPORT_RESCINDED

        rescinded = fx.read_report(api, duplicate["id"])
        assert rescinded["status"] == ReportStatus.RESCINDED
        assert rescinded["duplicate_master_report_id"] == master["id"]
        gone = fx.read_violation(api, duplicate_rows[0]["id"])
        assert gone["status"] == ViolationStatus.REMOVED
        assert gone["removal_reason"] == RemovalReason.DUPLICATE_RESCINDED
        assert_one_decimal(gone["time_weighted_severity"], 0.0)
        assert gone["under_challenge"] is False

        assert fx.read_report(api, master["id"])["status"] == ReportStatus.SCORED
        survivor = fx.read_violation(api, master_rows[0]["id"])
        assert survivor["status"] == ViolationStatus.ACTIVE
        assert_one_decimal(survivor["time_weighted_severity"], 15.0)

        row = fx.read_basic_score(api, carrier_id, UD)
        assert_one_decimal(row["total_time_weighted_severity"], 15.0)
        assert row["relevant_inspection_count"] == 1
        assert_one_decimal(row["challenged_time_weighted_severity"], 0.0)
        assert_measure(row["provisional_measure"], 0.500)
        assert_measure(row["certified_measure"], 0.500)
        assert_one_decimal(row["percentile"], 50.0)
        assert row["alert_status"] == AlertStatus.MONITOR

        fresh = fx.read_carrier(api, carrier_id)
        assert fresh["open_alert_count"] == 0
        assert fresh["intervention_status"] == InterventionStatus.NONE
        assert fresh["accepted_challenge_count_24mo"] == 1
        assert fresh["resolved_challenge_count_24mo"] == 1
        assert_one_decimal(fresh["iss_pre_credit_value"], 17.5)
        assert_credit_pct(fresh["data_quality_credit_pct"], 0.0200)
        assert_one_decimal(fresh["iss_value"], 17.2)
        assert fresh["selection_band"] == SelectionBand.PASS
