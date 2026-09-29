"""Rejections that need a real database behind them: per-type payload completeness,
type-specific evidence, cross-entity gates, uniqueness scopes and the two time windows.
"""

from typing import Any, Dict

from test_helpers import (
    AUDITOR_BOB,
    AUDITOR_CAROL,
    AUDITOR_DAVE,
    AlertStatus,
    AmendmentType,
    ApiErrorId,
    BasicCategory,
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
    ReportStatus,
    ResolutionDisposition,
    ReviewAction,
    SafetyFitnessStatus,
    SelectionBand,
    SelectionSource,
    UnitType,
    ViolationStatus,
    assert_measure,
    assert_one_decimal,
    factories as fac,
    fixtures as fx,
    get_success_data,
    make_auditor_headers,
    make_carrier_analyst_headers,
    make_carrier_safety_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UD = BasicCategory.UNSAFE_DRIVING
HOS = BasicCategory.HOURS_OF_SERVICE
VM = BasicCategory.VEHICLE_MAINTENANCE


def _two_scored_reports_of_one_carrier(api) -> Dict[str, Any]:
    """Two SCORED reports of the same carrier on different vehicles, one violation each,
    plus an alternative violation code an assertion could name."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    alternative = fx.create_violation_code(
        api,
        code="392.2C",
        description="Failure to obey traffic control device",
        basic_category=UD,
        severity_weight=5,
    )
    fx.create_threshold(
        api,
        basic_category=UD,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    first, first_rows = fx.build_scored_report(
        api,
        carrier["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026070401",
        vehicle_vin="1FUJA6CK21LK00401",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    second, second_rows = fx.build_scored_report(
        api,
        carrier["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026070402",
        vehicle_vin="1FUJA6CK21LK00402",
        inspection_start="2026-07-02T14:00:00Z",
        inspection_end="2026-07-02T15:00:00Z",
    )
    return {
        "carrier": carrier,
        "code": code,
        "alternative": alternative,
        "first": first,
        "first_violation": first_rows[0],
        "second": second,
        "second_violation": second_rows[0],
        "analyst": make_carrier_analyst_headers(carrier["id"]),
    }


class TestChallengePayloadCompleteness:
    def test_each_challenge_type_polices_its_own_conditional_fields(self, api):
        """PRD 3.6: "A missing conditional field, or an `asserted_correct_carrier_id`
        equal to the filing carrier, is rejected with
        `ERR_CHALLENGE_PAYLOAD_INCOMPLETE`; a `target_violation_id` that does not belong
        to the named `report_id` is rejected with `ERR_CHALLENGE_TARGET_MISMATCH`."

        Design: Corner/validations/challenge_payload_and_target_defects_rejected
        """
        scenario = _two_scored_reports_of_one_carrier(api)
        carrier_id = scenario["carrier"]["id"]
        report_id = scenario["first"]["id"]
        analyst = scenario["analyst"]

        def file(**overrides):
            return api.create_data_challenge(
                fac.create_data_challenge_payload(report_id, **overrides), analyst
            )

        probes = [
            (
                file(challenge_type=ChallengeType.WRONG_CARRIER, narrative="Not our truck."),
                ApiErrorId.CHALLENGE_PAYLOAD_INCOMPLETE,
            ),
            (
                file(
                    challenge_type=ChallengeType.WRONG_CARRIER,
                    narrative="Not our truck.",
                    asserted_correct_carrier_id=carrier_id,
                ),
                ApiErrorId.CHALLENGE_PAYLOAD_INCOMPLETE,
            ),
            (
                file(
                    challenge_type=ChallengeType.INCORRECT_VIOLATION_CODE,
                    narrative="Wrong code cited.",
                    target_violation_id=scenario["first_violation"]["id"],
                ),
                ApiErrorId.CHALLENGE_PAYLOAD_INCOMPLETE,
            ),
            (
                file(
                    challenge_type=ChallengeType.INCORRECT_VIOLATION_CODE,
                    narrative="Wrong code cited.",
                    target_violation_id=scenario["second_violation"]["id"],
                    asserted_correct_violation_code_id=scenario["alternative"]["id"],
                ),
                ApiErrorId.CHALLENGE_TARGET_MISMATCH,
            ),
            (
                file(
                    challenge_type=ChallengeType.DUPLICATE_REPORT,
                    narrative="Already reported.",
                    duplicate_of_report_id=scenario["second"]["id"],
                ),
                ApiErrorId.DUPLICATE_TARGET_INVALID,
            ),
            (
                file(
                    challenge_type=ChallengeType.DUPLICATE_REPORT,
                    narrative="Already reported.",
                    duplicate_of_report_id=report_id,
                ),
                ApiErrorId.DUPLICATE_TARGET_INVALID,
            ),
        ]
        for response, error_id in probes:
            validate_error(response, error_id)

        accepted = validate_success(
            file(
                challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
                narrative="No evidence of the violation.",
                target_violation_id=scenario["first_violation"]["id"],
            ),
            201,
        )
        assert accepted["status"] == ChallengeStatus.DRAFT
        assert accepted["carrier_id"] == carrier_id
        assert accepted["evidence_count"] == 0
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 0
        assert (
            fx.read_violation(api, scenario["first_violation"]["id"])["under_challenge"]
            is False
        )


def _two_wrong_carrier_drafts(api) -> Dict[str, Any]:
    """Two DRAFT WRONG_CARRIER challenges on one report: the first evidenced only by a
    photo, the second by a bill of lading."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    other = fx.create_carrier(
        api,
        dot_number="1000002",
        legal_name="Scioto Logistics Inc",
        average_power_units=20,
        annual_vmt=1600000,
    )
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
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
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026070403",
        vehicle_vin="1FUJA6CK21LK00403",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    first = fx.create_draft_challenge(
        api,
        carrier["id"],
        report["id"],
        challenge_type=ChallengeType.WRONG_CARRIER,
        narrative="Truck was leased to Scioto that week.",
        asserted_correct_carrier_id=other["id"],
    )
    fx.add_evidence(
        api,
        carrier["id"],
        first["id"],
        evidence_type=EvidenceType.PHOTO,
        document_uri="s3://evidence/cha/photo.jpg",
        description="Photo of the tractor door decal.",
    )
    second = fx.create_draft_challenge(
        api,
        carrier["id"],
        report["id"],
        challenge_type=ChallengeType.WRONG_CARRIER,
        narrative="Second filing on the same report.",
        asserted_correct_carrier_id=other["id"],
    )
    fx.add_evidence(
        api,
        carrier["id"],
        second["id"],
        evidence_type=EvidenceType.BILL_OF_LADING,
        document_uri="s3://evidence/chb/bol.pdf",
        description="Bill of lading naming Scioto.",
    )
    return {
        "carrier": carrier,
        "other": other,
        "report": report,
        "violation": rows[0],
        "first": first,
        "second": second,
        "analyst": make_carrier_analyst_headers(carrier["id"]),
    }


class TestEvidenceSufficiencyAndOpenChallengeUniqueness:
    def test_the_type_decides_which_documents_count_and_who_may_still_file(self, api):
        """PRD 3.6: "a `WRONG_CARRIER` challenge needs at least one evidence row whose
        `evidence_type` is `BILL_OF_LADING` or `LEASE_AGREEMENT`" — and afterwards "No
        other challenge sharing the same combination of `report_id`, `challenge_type` and
        `target_violation_id` may already be in `SUBMITTED`, `UNDER_REVIEW` or
        `INFO_REQUESTED`, else `ERR_DUPLICATE_OPEN_CHALLENGE`."

        Design: Corner/validations/evidence_type_and_duplicate_open_challenge_rejected
        """
        scenario = _two_wrong_carrier_drafts(api)
        carrier_id = scenario["carrier"]["id"]
        analyst = scenario["analyst"]

        refused = api.submit_challenge(scenario["first"]["id"], analyst)
        validate_error(refused, ApiErrorId.EVIDENCE_REQUIRED, 422)
        held = get_success_data(
            api.get_data_challenge(scenario["first"]["id"], fx.REVIEWER)
        )
        assert held["status"] == ChallengeStatus.DRAFT
        assert held["evidence_count"] == 1

        lease = fx.add_evidence(
            api,
            carrier_id,
            scenario["first"]["id"],
            evidence_type=EvidenceType.LEASE_AGREEMENT,
            document_uri="s3://evidence/cha/lease.pdf",
            description="Executed lease for the tractor.",
        )
        assert lease["submitted_round"] == 0
        assert (
            get_success_data(
                api.get_data_challenge(scenario["first"]["id"], fx.REVIEWER)
            )["evidence_count"]
            == 2
        )

        validate_success(api.submit_challenge(scenario["first"]["id"], analyst), 200)
        assert (
            get_success_data(
                api.get_data_challenge(scenario["first"]["id"], fx.REVIEWER)
            )["status"]
            == ChallengeStatus.SUBMITTED
        )
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 1
        assert fx.read_violation(api, scenario["violation"]["id"])["under_challenge"] is True

        blocked = api.submit_challenge(scenario["second"]["id"], analyst)
        validate_error(blocked, ApiErrorId.DUPLICATE_OPEN_CHALLENGE, 409)
        assert (
            get_success_data(
                api.get_data_challenge(scenario["second"]["id"], fx.REVIEWER)
            )["status"]
            == ChallengeStatus.DRAFT
        )
        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["challenge_quota_used"] == 1
        assert carrier["challenge_quota_limit"] == 3


def _out_of_service_violation_under_review(api) -> Dict[str, Any]:
    """An out-of-service brake violation whose removal challenge is UNDER_REVIEW."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api,
        code="396.3A1",
        description="Brakes out of adjustment",
        basic_category=VM,
        severity_weight=4,
        oos_add_on=2,
    )
    fx.create_threshold(
        api,
        basic_category=VM,
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
                "unit_type": UnitType.VEHICLE,
                "out_of_service": True,
            }
        ],
        report_number="OH2026070404",
        vehicle_vin="1FUJA6CK21LK00404",
        inspection_level=1,
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    challenge = fx.create_draft_challenge(
        api,
        carrier["id"],
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="Brake measurement was never recorded.",
        target_violation_id=rows[0]["id"],
    )
    fx.add_evidence(
        api,
        carrier["id"],
        challenge["id"],
        evidence_type=EvidenceType.COURT_DOCUMENT,
        document_uri="s3://evidence/ch/inspector-notes.pdf",
        description="Inspector notes without a brake measurement.",
    )
    fx.submit_challenge(api, carrier["id"], challenge["id"])
    fx.review_challenge(
        api,
        challenge["id"],
        ReviewAction.ASSIGN,
        review_note="Opening review of the brake violation.",
    )
    return {"carrier": carrier, "violation": rows[0], "challenge": challenge}


class TestOutOfServiceRemovalNeedsACourtOutcome:
    def test_only_a_court_finding_unlocks_the_acceptance(self, api):
        """PRD 3.6: "For a `VIOLATION_NOT_SUPPORTED` or `INCORRECT_VIOLATION_CODE`
        challenge whose target violation carries an `out_of_service` flag of true, a
        non-superseded `CitationAdjudication` on that violation must already show a
        `court_status` of `DISMISSED` or `NOT_GUILTY`; without one, the acceptance is
        refused with `ERR_OOS_REMOVAL_REQUIRES_ADJUDICATION`."

        Design: Corner/validations/oos_violation_removal_without_adjudication_rejected
        """
        scenario = _out_of_service_violation_under_review(api)
        carrier_id = scenario["carrier"]["id"]
        violation_id = scenario["violation"]["id"]

        premature = api.review_challenge(
            scenario["challenge"]["id"],
            fac.review_payload(
                ReviewAction.RESOLVE_ACCEPT,
                review_note="Accepting without a court outcome.",
            ),
            fx.REVIEWER,
        )
        validate_error(premature, ApiErrorId.OOS_REMOVAL_REQUIRES_ADJUDICATION, 422)
        assert (
            get_success_data(
                api.get_data_challenge(scenario["challenge"]["id"], fx.REVIEWER)
            )["status"]
            == ChallengeStatus.UNDER_REVIEW
        )
        standing = fx.read_violation(api, violation_id)
        assert standing["status"] == ViolationStatus.ACTIVE
        assert standing["out_of_service"] is True
        assert_one_decimal(standing["time_weighted_severity"], 18.0)

        adjudication = fx.create_adjudication(
            api,
            violation_id,
            citation_number="OH-CIT-8801",
            court_date="2026-07-25T00:00:00Z",
        )
        settled = fx.record_court_result(
            api,
            adjudication["id"],
            CourtStatus.NOT_GUILTY,
            court_note="Found not guilty at trial.",
        )
        assert settled["court_status"] == CourtStatus.NOT_GUILTY
        assert settled["superseded"] is False

        accepted = fx.review_challenge(
            api,
            scenario["challenge"]["id"],
            ReviewAction.RESOLVE_ACCEPT,
            review_note="Accepting on the not-guilty finding.",
        )
        assert accepted["status"] == ChallengeStatus.RESOLVED_ACCEPTED
        assert (
            accepted["resolution_disposition"] == ResolutionDisposition.VIOLATION_REMOVED
        )

        removed = fx.read_violation(api, violation_id)
        assert removed["status"] == ViolationStatus.REMOVED
        assert removed["under_challenge"] is False
        assert_one_decimal(
            fx.read_basic_score(api, carrier_id, VM)["total_time_weighted_severity"], 0.0
        )
        assert fx.read_carrier(api, carrier_id)["oos_violation_count_24mo"] == 0


def _driver_roster_and_a_received_report(api) -> Dict[str, Any]:
    """Two carriers, three drivers, and a RECEIVED report holding one unattributed
    driver-unit violation plus one violation whose code forbids coaching."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    other = fx.create_carrier(
        api,
        dot_number="1000002",
        legal_name="Scioto Logistics Inc",
        average_power_units=20,
        annual_vmt=1600000,
    )
    driver = fx.create_driver(
        api, carrier["id"], cdl_number="OH-CDL-0001", full_name="Dana Reyes"
    )
    colleague = fx.create_driver(
        api, carrier["id"], cdl_number="OH-CDL-0002", full_name="Marco Bell"
    )
    outsider = fx.create_driver(
        api, other["id"], cdl_number="OH-CDL-0003", full_name="Priya Nair"
    )
    coachable = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=UD,
        severity_weight=5,
        driver_attributable=True,
    )
    exempt = fx.create_violation_code(
        api,
        code="393.9TS",
        description="Inoperative tail lamp",
        basic_category=VM,
        severity_weight=2,
        driver_attributable=False,
    )
    for category in (UD, VM):
        fx.create_threshold(
            api,
            basic_category=category,
            carrier_segment="MEDIUM",
            measure_at_p50=0.5,
            measure_at_p65=1.0,
            measure_at_p80=2.0,
        )
    report = fx.create_report(
        api,
        carrier["id"],
        report_number="OH2026070405",
        vehicle_vin="1FUJA6CK21LK00405",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    driver_row = fx.add_violation(
        api, report["id"], coachable["id"], unit_type=UnitType.DRIVER
    )
    vehicle_row = fx.add_violation(
        api, report["id"], exempt["id"], unit_type=UnitType.VEHICLE
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "colleague": colleague,
        "outsider": outsider,
        "report": report,
        "driver_violation": driver_row,
        "vehicle_violation": vehicle_row,
        "manager": make_carrier_safety_manager_headers(carrier["id"]),
    }


class TestAttributionAndCoachingEligibility:
    def test_four_separate_gates_guard_attribution_and_coaching(self, api):
        """PRD 3.2: "every violation of the report whose `unit_type` is `DRIVER` must have
        a non-empty `driver_id` either on the violation itself or on the report, and a
        report failing that test is rejected with `ERR_DRIVER_ATTRIBUTION_MISSING`."

        Design: Corner/validations/driver_attribution_and_coaching_eligibility_defects_rejected
        """
        scenario = _driver_roster_and_a_received_report(api)
        carrier_id = scenario["carrier"]["id"]
        report_id = scenario["report"]["id"]
        driver_id = scenario["driver"]["id"]
        manager = scenario["manager"]

        incomplete = api.validate_report(report_id, fx.OFFICER)
        validate_error(incomplete, ApiErrorId.DRIVER_ATTRIBUTION_MISSING, 422)
        assert fx.read_report(api, report_id)["status"] == ReportStatus.RECEIVED

        foreign = api.attribute_driver(
            scenario["driver_violation"]["id"],
            {"driver_id": scenario["outsider"]["id"]},
            manager,
        )
        validate_error(foreign, ApiErrorId.DRIVER_CARRIER_MISMATCH, 422)
        assert (
            fx.read_violation(api, scenario["driver_violation"]["id"])["driver_id"] is None
        )

        for violation in (scenario["driver_violation"], scenario["vehicle_violation"]):
            attributed = fx.attribute_driver(
                api, carrier_id, violation["id"], driver_id
            )
            assert attributed["driver_id"] == driver_id

        assert fx.validate_report(api, report_id)["status"] == ReportStatus.VALIDATED
        assert fx.score_report(api, report_id)["status"] == ReportStatus.SCORED

        wrong_driver = api.create_coaching_assignment(
            fac.create_coaching_assignment_payload(
                scenario["colleague"]["id"],
                scenario["driver_violation"]["id"],
                curriculum_code=CurriculumCode.UNSAFE_DRIVING_101,
                session_start="2026-08-05T14:00:00Z",
                session_end="2026-08-05T16:00:00Z",
            ),
            manager,
        )
        validate_error(
            wrong_driver, ApiErrorId.VIOLATION_NOT_ATTRIBUTED_TO_DRIVER, 422
        )

        exempt_code = api.create_coaching_assignment(
            fac.create_coaching_assignment_payload(
                driver_id,
                scenario["vehicle_violation"]["id"],
                curriculum_code=CurriculumCode.PRETRIP_INSPECTION,
                session_start="2026-08-05T14:00:00Z",
                session_end="2026-08-05T16:00:00Z",
            ),
            manager,
        )
        validate_error(exempt_code, ApiErrorId.CODE_NOT_DRIVER_ATTRIBUTABLE, 422)

        assignment = validate_success(
            api.create_coaching_assignment(
                fac.create_coaching_assignment_payload(
                    driver_id,
                    scenario["driver_violation"]["id"],
                    curriculum_code=CurriculumCode.UNSAFE_DRIVING_101,
                    session_start="2026-08-05T14:00:00Z",
                    session_end="2026-08-05T16:00:00Z",
                ),
                manager,
            ),
            201,
        )
        assert assignment["status"] == CoachingStatus.ASSIGNED
        assert fx.read_driver(api, driver_id)["coaching_required"] is True
        assert fx.read_carrier(api, carrier_id)["open_coaching_count"] == 1


def _validated_report_without_a_matching_threshold(api) -> Dict[str, Any]:
    """A VALIDATED unsafe-driving report whose carrier segment has no unsafe-driving
    reference row, though two other rows exist."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    fx.create_threshold(
        api,
        basic_category=UD,
        carrier_segment="SMALL",
        measure_at_p50=2.0,
        measure_at_p65=4.0,
        measure_at_p80=6.0,
    )
    fx.create_threshold(
        api,
        basic_category=VM,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    report, rows = fx.build_validated_report(
        api,
        carrier["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026070406",
        vehicle_vin="1FUJA6CK21LK00406",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {"carrier": carrier, "report": report, "violation": rows[0]}


class TestScoringNeedsTheMatchingReferenceRow:
    def test_the_requirement_follows_the_categories_actually_present(self, api):
        """PRD 3.3: "One precondition guards the whole pass: for every behaviour category
        that holds at least one includable violation of the attributed carrier, a threshold
        reference row must be selectable, and if none is, the pass is rejected with
        `ERR_THRESHOLD_NOT_CONFIGURED`."

        Design: Corner/validations/scoring_without_a_configured_threshold_rejected
        """
        scenario = _validated_report_without_a_matching_threshold(api)
        carrier_id = scenario["carrier"]["id"]
        report_id = scenario["report"]["id"]

        refused = api.score_report(report_id, fx.OFFICER)
        validate_error(refused, ApiErrorId.THRESHOLD_NOT_CONFIGURED, 409)
        assert fx.read_report(api, report_id)["status"] == ReportStatus.VALIDATED
        waiting = fx.read_violation(api, scenario["violation"]["id"])
        assert waiting["time_weight"] == 0
        assert_one_decimal(waiting["time_weighted_severity"], 0.0)

        threshold = fx.create_threshold(
            api,
            basic_category=UD,
            carrier_segment="MEDIUM",
            measure_at_p50=0.5,
            measure_at_p65=1.0,
            measure_at_p80=2.0,
        )
        assert threshold["carrier_segment"] == "MEDIUM"
        assert_one_decimal(threshold["monitor_percentile"], 50.0)
        assert_one_decimal(threshold["intervention_percentile"], 65.0)

        assert fx.score_report(api, report_id)["status"] == ReportStatus.SCORED
        row = fx.read_basic_score(api, carrier_id, UD)
        assert row["threshold_id"] == threshold["id"]
        assert_measure(row["certified_measure"], 0.500)
        assert_one_decimal(row["percentile"], 50.0)
        assert row["alert_status"] == AlertStatus.MONITOR
        assert_one_decimal(fx.read_carrier(api, carrier_id)["iss_value"], 17.5)


class TestAmendmentPayloadCompleteness:
    def test_each_amendment_type_polices_its_own_correction_field(self, api):
        """PRD 3.7: "A missing conditional field, or a `CARRIER_REATTRIBUTION` that names
        the carrier the report already scores against, is
        `ERR_AMENDMENT_PAYLOAD_INCOMPLETE`. A `target_violation_id` that does not belong
        to the amended report is `ERR_AMENDMENT_TARGET_MISMATCH`."

        Design: Corner/validations/amendment_payload_and_target_defects_rejected
        """
        scenario = _two_scored_reports_of_one_carrier(api)
        carrier_id = scenario["carrier"]["id"]
        report_id = scenario["first"]["id"]
        version = fx.current_version(api, "report", report_id)

        def amend(**overrides):
            return api.create_amendment(
                report_id,
                fac.create_amendment_payload(
                    expected_report_version=version, **overrides
                ),
                fx.OFFICER,
            )

        probes = [
            (
                amend(
                    amendment_type=AmendmentType.VIOLATION_CODE_CORRECTION,
                    rationale="Wrong code keyed at roadside.",
                    target_violation_id=scenario["first_violation"]["id"],
                ),
                ApiErrorId.AMENDMENT_PAYLOAD_INCOMPLETE,
            ),
            (
                amend(
                    amendment_type=AmendmentType.CARRIER_REATTRIBUTION,
                    rationale="Reattributing to the same carrier.",
                    corrected_carrier_id=carrier_id,
                ),
                ApiErrorId.AMENDMENT_PAYLOAD_INCOMPLETE,
            ),
            (
                amend(
                    amendment_type=AmendmentType.DRIVER_ATTRIBUTION_CORRECTION,
                    rationale="Driver was misidentified.",
                ),
                ApiErrorId.AMENDMENT_PAYLOAD_INCOMPLETE,
            ),
            (
                amend(
                    amendment_type=AmendmentType.VIOLATION_REMOVAL,
                    rationale="Removing a violation recorded on the wrong report.",
                    target_violation_id=scenario["second_violation"]["id"],
                ),
                ApiErrorId.AMENDMENT_TARGET_MISMATCH,
            ),
        ]
        for response, error_id in probes:
            validate_error(response, error_id, 422)

        report = fx.read_report(api, report_id)
        assert report["version"] == version
        assert report["status"] == ReportStatus.SCORED
        _, meta = validate_paginated(
            api.list_report_amendments(fx.OFFICER, {"report_id": report_id})
        )
        assert meta["total_count"] == 0

        untouched = fx.read_violation(api, scenario["first_violation"]["id"])
        assert untouched["effective_violation_code_id"] == scenario["code"]["id"]
        assert (
            fx.read_violation(api, scenario["second_violation"]["id"])["status"]
            == ViolationStatus.ACTIVE
        )


def _one_of_everything_unique(api) -> Dict[str, Any]:
    """A registered carrier, a second carrier, a published code, a driver and a report —
    each holding the identifier a repeat will collide with."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    other = fx.create_carrier(
        api,
        dot_number="1000002",
        legal_name="Scioto Logistics Inc",
        average_power_units=20,
        annual_vmt=1600000,
    )
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    driver = fx.create_driver(
        api, carrier["id"], cdl_number="OH-CDL-0001", full_name="Dana Reyes"
    )
    report = fx.create_report(
        api,
        carrier["id"],
        report_number="OH2026070409",
        vehicle_vin="1FUJA6CK21LK00409",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {
        "carrier": carrier,
        "other": other,
        "code": code,
        "driver": driver,
        "report": report,
    }


class TestUniquenessScopes:
    def test_the_cdl_index_is_carrier_scoped_while_the_others_are_global(self, api):
        """PRD 3.1: "A `CarrierSafetyManager` registers one with a `carrier_id`, a
        `cdl_number` that must be unique within that employing carrier (a repeat within the
        carrier is `ERR_DUPLICATE_CDL`)"

        Design: Corner/validations/uniqueness_conflicts_rejected
        """
        scenario = _one_of_everything_unique(api)
        carrier_id = scenario["carrier"]["id"]
        other_id = scenario["other"]["id"]

        probes = [
            (
                api.create_carrier(
                    fac.create_carrier_payload(
                        dot_number=scenario["carrier"]["dot_number"],
                        legal_name="Buckeye Freight Holdings",
                        average_power_units=5,
                        annual_vmt=200000,
                    ),
                    fx.AUDITOR,
                ),
                ApiErrorId.DUPLICATE_DOT_NUMBER,
            ),
            (
                api.create_violation_code(
                    fac.create_violation_code_payload(
                        code="392.2S",
                        description="Duplicate speeding code",
                        severity_weight=3,
                    ),
                    fx.AUDITOR,
                ),
                ApiErrorId.DUPLICATE_VIOLATION_CODE,
            ),
            (
                api.create_inspection_report(
                    fac.create_inspection_report_payload(
                        carrier_id,
                        report_number="OH2026070409",
                        vehicle_vin="1FUJA6CK21LK00410",
                        inspection_start="2026-07-05T14:00:00Z",
                        inspection_end="2026-07-05T15:00:00Z",
                    ),
                    fx.OFFICER,
                ),
                ApiErrorId.DUPLICATE_REPORT_NUMBER,
            ),
            (
                api.create_driver(
                    fac.create_driver_payload(
                        carrier_id,
                        cdl_number="OH-CDL-0001",
                        full_name="Dana Reyes Jr",
                    ),
                    make_carrier_safety_manager_headers(carrier_id),
                ),
                ApiErrorId.DUPLICATE_CDL,
            ),
        ]
        for response, error_id in probes:
            validate_error(response, error_id, 409)

        namesake = validate_success(
            api.create_driver(
                fac.create_driver_payload(
                    other_id,
                    cdl_number="OH-CDL-0001",
                    full_name="Unrelated Namesake",
                ),
                make_carrier_safety_manager_headers(other_id),
            ),
            201,
        )
        assert namesake["carrier_id"] == other_id
        assert namesake["cdl_number"] == "OH-CDL-0001"
        assert namesake["employment_status"] == EmploymentStatus.ACTIVE


def _one_screened_carrier_and_one_clean_carrier(api) -> Dict[str, Any]:
    """One carrier driven to a screening value of exactly 50.0, and one never scored."""
    fx.set_clock(api)
    screened = fx.create_carrier(api)
    clean = fx.create_carrier(
        api,
        dot_number="1000002",
        legal_name="Scioto Logistics Inc",
        average_power_units=20,
        annual_vmt=1600000,
    )
    hours = fx.create_violation_code(
        api,
        code="395.3A1",
        description="11 hour driving limit exceeded",
        basic_category=HOS,
        severity_weight=5,
    )
    maintenance = fx.create_violation_code(
        api,
        code="393.9TS",
        description="Inoperative tail lamp",
        basic_category=VM,
        severity_weight=2,
    )
    fx.create_threshold(
        api,
        basic_category=HOS,
        carrier_segment="MEDIUM",
        measure_at_p50=0.1,
        measure_at_p65=0.2,
        measure_at_p80=0.4,
    )
    fx.create_threshold(
        api,
        basic_category=VM,
        carrier_segment="MEDIUM",
        measure_at_p50=2.0,
        measure_at_p65=4.0,
        measure_at_p80=6.0,
    )
    fx.build_scored_report(
        api,
        screened["id"],
        [
            {"violation_code_id": hours["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": maintenance["id"], "unit_type": UnitType.VEHICLE},
        ],
        report_number="OH2026070410",
        vehicle_vin="1FUJA6CK21LK00411",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {"screened": screened, "clean": clean}


class TestScreeningSelectionConsistency:
    def test_an_iss_screening_report_needs_a_carrier_the_screener_would_flag(self, api):
        """PRD 3.2: "A report claiming `ISS_SCREENING` as its `selection_source` asserts
        that the screening system flagged this carrier, so the attributed carrier's
        `selection_band` must currently be `OPTIONAL` or `INSPECT`. If it is `PASS`, the
        assertion contradicts the screening data and the ingestion is rejected with
        `ERR_SCREENING_SELECTION_INCONSISTENT`."

        Design: Corner/validations/iss_screening_selection_on_a_pass_band_carrier_rejected
        """
        scenario = _one_screened_carrier_and_one_clean_carrier(api)
        screened_id = scenario["screened"]["id"]
        clean_id = scenario["clean"]["id"]

        clean_risk = fx.read_screening_risk(api, clean_id)
        assert_one_decimal(clean_risk["iss_value"], 0.0)
        assert clean_risk["selection_band"] == SelectionBand.PASS
        screened_risk = fx.read_screening_risk(api, screened_id)
        assert_one_decimal(screened_risk["iss_value"], 50.0)
        assert screened_risk["selection_band"] == SelectionBand.OPTIONAL

        refused = api.create_inspection_report(
            fac.create_inspection_report_payload(
                clean_id,
                report_number="OH2026080101",
                inspection_level=3,
                vehicle_vin="1FUJA6CK21LK00412",
                inspection_start="2026-08-01T09:00:00Z",
                inspection_end="2026-08-01T10:00:00Z",
                selection_source=SelectionSource.ISS_SCREENING,
            ),
            fx.OFFICER,
        )
        validate_error(refused, ApiErrorId.SCREENING_SELECTION_INCONSISTENT, 422)

        accepted = validate_success(
            api.create_inspection_report(
                fac.create_inspection_report_payload(
                    screened_id,
                    report_number="OH2026080102",
                    inspection_level=3,
                    vehicle_vin="1FUJA6CK21LK00413",
                    inspection_start="2026-08-01T09:00:00Z",
                    inspection_end="2026-08-01T10:00:00Z",
                    selection_source=SelectionSource.ISS_SCREENING,
                ),
                fx.OFFICER,
            ),
            201,
        )
        assert accepted["status"] == ReportStatus.RECEIVED
        assert accepted["selection_source"] == SelectionSource.ISS_SCREENING
        assert accepted["selection_band_at_selection"] == SelectionBand.OPTIONAL
        assert_one_decimal(accepted["iss_value_at_selection"], 50.0)


def _violation_with_a_pending_citation(api) -> Dict[str, Any]:
    """A scored violation already carrying one PENDING citation."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    fx.create_threshold(
        api,
        basic_category=UD,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    _, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026070411",
        vehicle_vin="1FUJA6CK21LK00414",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    first = fx.create_adjudication(
        api,
        rows[0]["id"],
        citation_number="OH-CIT-9001",
        court_date="2026-07-20T00:00:00Z",
    )
    return {"carrier": carrier, "violation": rows[0], "first": first}


class TestOnePendingCitationPerViolation:
    def test_a_second_citation_waits_for_the_first_court_result(self, api):
        """PRD 3.8: "A violation may carry at most one non-superseded adjudication whose
        `court_status` is `PENDING`, and a second attempt is rejected with
        `ERR_ADJUDICATION_PENDING_EXISTS`."

        Design: Corner/validations/second_pending_adjudication_on_one_violation_rejected
        """
        scenario = _violation_with_a_pending_citation(api)
        violation_id = scenario["violation"]["id"]
        version = fx.current_version(api, "violation", violation_id)

        blocked = api.create_citation_adjudication(
            fac.create_citation_adjudication_payload(
                violation_id,
                version,
                citation_number="OH-CIT-9002",
                court_date="2026-07-27T00:00:00Z",
            ),
            fx.OFFICER,
        )
        validate_error(blocked, ApiErrorId.ADJUDICATION_PENDING_EXISTS, 409)

        first = get_success_data(
            api.get_citation_adjudication(scenario["first"]["id"], fx.OFFICER)
        )
        assert first["court_status"] == CourtStatus.PENDING
        assert first["superseded"] is False
        assert fx.read_violation(api, violation_id)["version"] == version

        settled = fx.record_court_result(
            api,
            scenario["first"]["id"],
            CourtStatus.CONVICTED,
            court_note="Convicted as charged.",
        )
        assert settled["court_status"] == CourtStatus.CONVICTED

        second = validate_success(
            api.create_citation_adjudication(
                fac.create_citation_adjudication_payload(
                    violation_id,
                    fx.current_version(api, "violation", violation_id),
                    citation_number="OH-CIT-9002",
                    court_date="2026-07-27T00:00:00Z",
                ),
                fx.OFFICER,
            ),
            201,
        )
        assert second["court_status"] == CourtStatus.PENDING
        assert second["superseded"] is False
        assert (
            get_success_data(
                api.get_citation_adjudication(scenario["first"]["id"], fx.OFFICER)
            )["superseded"]
            is True
        )

        violation = fx.read_violation(api, violation_id)
        assert violation["status"] == ViolationStatus.ACTIVE
        assert_one_decimal(violation["time_weighted_severity"], 15.0)


def _empty_draft_plan(api) -> Dict[str, Any]:
    """A conditionally rated carrier holding one DRAFT plan with no action items."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    determined = fx.issue_fitness_determination(
        api,
        carrier["id"],
        SafetyFitnessStatus.CONDITIONAL,
        auditor_id=AUDITOR_BOB,
        basis_note="Compliance review found recordkeeping deficiencies.",
    )
    assert determined["safety_fitness_status"] == SafetyFitnessStatus.CONDITIONAL
    plan = fx.create_cap(
        api, carrier["id"], narrative="Plan to correct HOS recordkeeping."
    )
    return {
        "carrier": carrier,
        "plan": plan,
        "analyst": make_carrier_analyst_headers(carrier["id"]),
        "manager": make_carrier_safety_manager_headers(carrier["id"]),
    }


class TestCapSubmissionAndReviewConflicts:
    def test_the_plan_polices_its_items_its_siblings_and_its_branches(self, api):
        """PRD 3.10: "Two gates apply beyond the fitness-status check: `item_count` must
        be at least 1, and `committed_item_count` must equal `item_count`, so every
        surviving item is committed; a shortfall is `ERR_CAP_ITEMS_INCOMPLETE`."

        Design: Corner/validations/cap_submission_and_review_conflicts_rejected
        """
        scenario = _empty_draft_plan(api)
        carrier_id = scenario["carrier"]["id"]
        plan_id = scenario["plan"]["id"]

        empty = api.submit_cap(plan_id, scenario["manager"])
        validate_error(empty, ApiErrorId.CAP_ITEMS_INCOMPLETE, 422)
        assert fx.read_cap(api, plan_id)["status"] == CapStatus.DRAFT

        item = validate_success(
            api.add_action_item(
                plan_id,
                fac.create_cap_action_item_payload(
                    basic_category=HOS,
                    description="Retrain dispatch on ELD edits.",
                    target_completion_date="2026-10-01T00:00:00Z",
                ),
                scenario["analyst"],
            ),
            201,
        )
        assert item["status"] == CapItemStatus.PROPOSED
        proposed = fx.read_cap(api, plan_id)
        assert proposed["item_count"] == 1
        assert proposed["committed_item_count"] == 0

        uncommitted = api.submit_cap(plan_id, scenario["manager"])
        validate_error(uncommitted, ApiErrorId.CAP_ITEMS_INCOMPLETE, 422)

        committed = fx.set_item_status(
            api,
            item["id"],
            CapItemAction.COMMIT,
            scenario["analyst"],
            note="Committing the retraining item.",
        )
        assert committed["status"] == CapItemStatus.COMMITTED
        assert fx.read_cap(api, plan_id)["committed_item_count"] == 1

        submitted = get_success_data(api.submit_cap(plan_id, scenario["manager"]))
        assert submitted["status"] == CapStatus.SUBMITTED

        competing = api.create_corrective_action_plan(
            fac.create_cap_payload(
                carrier_id,
                fx.current_version(api, "carrier", carrier_id),
                narrative="A competing second plan.",
            ),
            scenario["analyst"],
        )
        validate_error(competing, ApiErrorId.ACTIVE_CAP_EXISTS, 409)

        reviewed = get_success_data(
            api.review_cap(
                plan_id,
                {
                    "branch": CapReviewBranch.SAFETY,
                    "outcome": CapReviewOutcome.CLEARED,
                    "note": "Safety branch cleared.",
                },
                make_auditor_headers(AUDITOR_CAROL),
            )
        )
        assert reviewed["status"] == CapStatus.IN_REVIEW
        assert reviewed["safety_review_outcome"] == CapReviewOutcome.CLEARED
        assert reviewed["safety_review_user_id"] == AUDITOR_CAROL
        assert reviewed["data_review_outcome"] is None

        repeat = api.review_cap(
            plan_id,
            {
                "branch": CapReviewBranch.SAFETY,
                "outcome": CapReviewOutcome.CLEARED,
                "note": "Second safety sign-off by a different auditor.",
            },
            make_auditor_headers(AUDITOR_DAVE),
        )
        validate_error(repeat, ApiErrorId.REVIEW_BRANCH_ALREADY_RECORDED, 409)
        final = fx.read_cap(api, plan_id)
        assert final["safety_review_user_id"] == AUDITOR_CAROL
        assert final["status"] == CapStatus.IN_REVIEW


def _two_challenges_awaiting_information(api) -> Dict[str, Any]:
    """Two challenges on one report, both in INFO_REQUESTED with a 30-day deadline and a
    round-one document already uploaded."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    alternative = fx.create_violation_code(
        api,
        code="392.2C",
        description="Failure to obey traffic control device",
        basic_category=UD,
        severity_weight=5,
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
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026070412",
        vehicle_vin="1FUJA6CK21LK00415",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    first = fx.create_draft_challenge(
        api,
        carrier["id"],
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="No radar reading was recorded.",
        target_violation_id=rows[0]["id"],
    )
    fx.add_evidence(
        api,
        carrier["id"],
        first["id"],
        evidence_type=EvidenceType.COURT_DOCUMENT,
        document_uri="s3://evidence/cha/notes.pdf",
        description="Inspector notes with no speed measurement.",
    )
    fx.submit_challenge(api, carrier["id"], first["id"])
    fx.review_challenge(api, first["id"], ReviewAction.ASSIGN)
    fx.review_challenge(
        api,
        first["id"],
        ReviewAction.REQUEST_INFO,
        review_note="Send the ELD extract for that shift.",
    )
    fx.add_evidence(
        api,
        carrier["id"],
        first["id"],
        evidence_type=EvidenceType.ELD_RECORD,
        document_uri="s3://evidence/cha/eld-round1.csv",
        description="ELD extract for the shift in question.",
    )
    second = fx.create_draft_challenge(
        api,
        carrier["id"],
        report["id"],
        challenge_type=ChallengeType.INCORRECT_VIOLATION_CODE,
        narrative="The cited code should be 392.2C.",
        target_violation_id=rows[0]["id"],
        asserted_correct_violation_code_id=alternative["id"],
    )
    fx.add_evidence(
        api,
        carrier["id"],
        second["id"],
        evidence_type=EvidenceType.PHOTO,
        document_uri="s3://evidence/chb/sign.jpg",
        description="Photo of the traffic control device.",
    )
    fx.submit_challenge(api, carrier["id"], second["id"])
    fx.review_challenge(api, second["id"], ReviewAction.ASSIGN)
    fx.review_challenge(
        api,
        second["id"],
        ReviewAction.REQUEST_INFO,
        review_note="Send the citation image.",
    )
    fx.add_evidence(
        api,
        carrier["id"],
        second["id"],
        evidence_type=EvidenceType.PHOTO,
        document_uri="s3://evidence/chb/citation-round1.jpg",
        description="Photograph of the issued citation.",
    )
    return {
        "carrier": carrier,
        "violation": rows[0],
        "first": first,
        "second": second,
        "analyst": make_carrier_analyst_headers(carrier["id"]),
    }


class TestInformationResponseWindow:
    def test_the_deadline_instant_is_still_inside_the_window(self, api):
        """PRD 3.6: "The current logical clock must be at or before the challenge's
        `info_response_deadline`, else `ERR_INFO_RESPONSE_WINDOW_CLOSED`."

        Design: Corner/validations/info_response_at_the_deadline_passes_and_one_second_late_rejected
        """
        scenario = _two_challenges_awaiting_information(api)
        carrier_id = scenario["carrier"]["id"]
        analyst = scenario["analyst"]

        opened = get_success_data(
            api.get_data_challenge(scenario["first"]["id"], fx.REVIEWER)
        )
        assert opened["info_response_deadline"].startswith("2026-08-31T00:00:00")
        assert opened["info_request_count"] == 1
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 2

        fx.set_clock(api, "2026-08-31T00:00:00Z")
        validate_success(api.submit_challenge(scenario["first"]["id"], analyst), 200)
        answered = get_success_data(
            api.get_data_challenge(scenario["first"]["id"], fx.REVIEWER)
        )
        assert answered["status"] == ChallengeStatus.SUBMITTED
        assert answered["info_request_count"] == 1
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 2

        fx.set_clock(api, "2026-09-01T00:00:00Z")
        late = api.submit_challenge(scenario["second"]["id"], analyst)
        validate_error(late, ApiErrorId.INFO_RESPONSE_WINDOW_CLOSED, 422)
        stuck = get_success_data(
            api.get_data_challenge(scenario["second"]["id"], fx.REVIEWER)
        )
        assert stuck["status"] == ChallengeStatus.INFO_REQUESTED
        assert stuck["resolution_disposition"] is None
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 2
        assert fx.read_violation(api, scenario["violation"]["id"])["under_challenge"] is True


def _one_completed_run(api) -> Dict[str, Any]:
    """A carrier and one completed scoring run at the default epoch."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    run = fx.run_scoring(api, note="Baseline run.")
    return {"carrier": carrier, "run": run}


class TestScoringEpochMayNotRegress:
    def test_a_repeat_at_the_same_instant_is_allowed_but_an_earlier_one_is_not(self, api):
        """PRD 3.11: "Epochs may not go backwards: a run whose `snapshot_utc` would fall
        earlier than the most recent run's `snapshot_utc` is rejected with
        `ERR_SCORING_RUN_SNAPSHOT_REGRESSION`."

        Design: Corner/validations/scoring_run_with_an_earlier_snapshot_rejected
        """
        scenario = _one_completed_run(api)
        assert scenario["run"]["snapshot_utc"].startswith("2026-08-01T00:00:00")

        rewound = fx.set_clock(api, "2026-07-31T00:00:00Z")
        assert rewound["current_utc"].startswith("2026-07-31T00:00:00")
        assert rewound["previous_utc"].startswith("2026-08-01T00:00:00")

        refused = api.create_scoring_run(
            fac.create_scoring_run_payload(note="Run attempted with a rewound clock."),
            fx.AUDITOR,
        )
        validate_error(refused, ApiErrorId.SCORING_RUN_SNAPSHOT_REGRESSION, 409)

        restored = fx.set_clock(api, "2026-08-01T00:00:00Z")
        assert restored["current_utc"].startswith("2026-08-01T00:00:00")

        repeat = validate_success(
            api.create_scoring_run(
                fac.create_scoring_run_payload(note="Re-run at the same snapshot."),
                fx.AUDITOR,
            ),
            201,
        )
        assert repeat["snapshot_utc"].startswith("2026-08-01T00:00:00")
        assert repeat["carriers_scored"] == 1
        assert repeat["challenges_expired"] == 0
        assert repeat["coaching_marked_overdue"] == 0
        assert repeat["coaching_waived"] == 0
        assert (
            get_success_data(api.get_scoring_run(scenario["run"]["id"], fx.AUDITOR))[
                "snapshot_utc"
            ].startswith("2026-08-01T00:00:00")
        )
