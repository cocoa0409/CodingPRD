"""What the endpoints themselves have to publish: the two computed reads with their whole
derivation ladder, filtered and paged listings, a field-selective patch, and the two
action endpoints that stamp who acted and what the epoch touched.
"""

from typing import Any, Dict

from test_helpers import (
    AUDITOR_BOB,
    AUDITOR_CAROL,
    AlertStatus,
    BasicCategory,
    ChallengeStatus,
    ChallengeType,
    CoachingStatus,
    CourtStatus,
    CurriculumCode,
    EmploymentStatus,
    EvidenceType,
    RecordUpdateStatus,
    ResolutionDisposition,
    ReviewAction,
    SafetyFitnessStatus,
    SelectionBand,
    UnitType,
    assert_measure,
    assert_one_decimal,
    assert_two_decimals,
    contribution_for,
    factories as fac,
    fixtures as fx,
    get_success_data,
    make_auditor_headers,
    make_carrier_safety_manager_headers,
    validate_paginated,
    validate_success,
)

UD = BasicCategory.UNSAFE_DRIVING
HOS = BasicCategory.HOURS_OF_SERVICE
VM = BasicCategory.VEHICLE_MAINTENANCE
DF = BasicCategory.DRIVER_FITNESS


def _carrier_with_one_out_of_service_violation(api) -> Dict[str, Any]:
    """A single scored out-of-service violation: weight 5 plus a 2-point add-on, pinned at
    time weight 3."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api,
        code="392.2W",
        description="Reckless driving",
        basic_category=UD,
        severity_weight=5,
        oos_add_on=2,
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
        [
            {
                "violation_code_id": code["id"],
                "unit_type": UnitType.VEHICLE,
                "out_of_service": True,
            }
        ],
        report_number="OH2026070413",
        vehicle_vin="1FUJA6CK21LK00416",
        inspection_level=1,
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {"carrier": carrier, "violation": rows[0]}


class TestScreeningRiskRead:
    def test_the_read_publishes_the_whole_ladder_not_just_the_score(self, api):
        """PRD 3.5: "To the raw figure the system adds an out-of-service adder: half a
        point for each of the carrier's out-of-service violations counted in
        `oos_violation_count_24mo`, capped at 10.0 points however many there are."

        Design: Corner/endpoints/screening_risk_read_exposes_contributions_oos_adder_and_credit
        """
        scenario = _carrier_with_one_out_of_service_violation(api)
        carrier_id = scenario["carrier"]["id"]

        violation = fx.read_violation(api, scenario["violation"]["id"])
        assert violation["oos_add_on_snapshot"] == 2
        assert_one_decimal(violation["time_weighted_severity"], 21.0)

        row = fx.read_basic_score(api, carrier_id, UD)
        assert_measure(row["certified_measure"], 0.700)
        assert_one_decimal(row["percentile"], 56.0)

        risk = validate_success(api.get_screening_risk(carrier_id, fx.AUDITOR), 200)
        assert risk["carrier_id"] == carrier_id
        assert_two_decimals(contribution_for(risk, UD), 19.60)
        assert_two_decimals(contribution_for(risk, HOS), 0.00)
        assert_two_decimals(contribution_for(risk, VM), 0.00)
        assert_two_decimals(contribution_for(risk, DF), 0.00)
        assert risk["oos_violation_count_24mo"] == 1
        assert_one_decimal(risk["oos_adder"], 0.5)
        assert_one_decimal(risk["iss_pre_credit_value"], 20.1)
        assert_one_decimal(risk["data_quality_credit_pct"], 0.0)
        assert_one_decimal(risk["iss_value"], 20.1)
        assert risk["selection_band"] == SelectionBand.PASS
        assert risk["not_enough_data_categories"] == []


def _driver_with_one_reduced_citation(api) -> Dict[str, Any]:
    """Two scored driver-unit violations of 15.0 each, one of them reduced in court but
    never pushed to the record."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    driver = fx.create_driver(
        api, carrier["id"], cdl_number="OH-CDL-0001", full_name="Dana Reyes"
    )
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    lesser = fx.create_violation_code(
        api,
        code="392.2L",
        description="Speeding 1 to 5 over the limit",
        basic_category=UD,
        severity_weight=2,
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
        [
            {
                "violation_code_id": code["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            },
            {
                "violation_code_id": code["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            },
        ],
        report_number="OH2026070414",
        vehicle_vin="1FUJA6CK21LK00417",
        driver_id=driver["id"],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    adjudication = fx.create_adjudication(
        api,
        rows[1]["id"],
        citation_number="OH-CIT-9101",
        court_date="2026-07-22T00:00:00Z",
    )
    fx.record_court_result(
        api,
        adjudication["id"],
        CourtStatus.REDUCED,
        reduced_to_violation_code_id=lesser["id"],
        court_note="Amended to a lesser speed.",
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "code": code,
        "violations": rows,
        "adjudication": adjudication,
    }


class TestAttributionSummaryRead:
    def test_the_read_separates_the_strict_exposure_from_the_court_adjusted_one(self, api):
        """PRD 3.9: "`strict_attribution_score` is the sum of `time_weighted_severity`
        over that included set, rounded half up to 2 decimal places; it ignores court
        outcomes entirely, so a citation that was dismissed but not yet pushed to the
        record still counts against the driver."

        Design: Corner/endpoints/attribution_summary_read_reports_strict_and_reduced_factor_scores
        """
        scenario = _driver_with_one_reduced_citation(api)
        driver_id = scenario["driver"]["id"]

        summary = validate_success(
            api.get_attribution_summary(driver_id, fx.AUDITOR), 200
        )
        assert summary["driver_id"] == driver_id
        assert summary["attributed_violation_count"] == 2
        assert_two_decimals(summary["strict_attribution_score"], 30.00)
        assert_two_decimals(summary["adjudicated_attribution_score"], 22.50)
        assert summary["coaching_required"] is True
        assert len(summary["factor_breakdown"]) == 2

        reduced = fx.read_violation(api, scenario["violations"][1]["id"])
        assert reduced["effective_violation_code_id"] == scenario["code"]["id"]
        assert_one_decimal(reduced["time_weighted_severity"], 15.0)
        assert (
            get_success_data(
                api.get_citation_adjudication(scenario["adjudication"]["id"], fx.OFFICER)
            )["record_update_status"]
            == RecordUpdateStatus.NOT_APPLIED
        )


def _three_violations_one_of_them_challenged(api) -> Dict[str, Any]:
    """One scored report holding two unsafe-driving violations and one vehicle-maintenance
    violation, with only the maintenance row under challenge."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    speeding = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    lamp = fx.create_violation_code(
        api,
        code="393.9TS",
        description="Inoperative tail lamp",
        basic_category=VM,
        severity_weight=2,
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
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [
            {"violation_code_id": speeding["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": speeding["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": lamp["id"], "unit_type": UnitType.VEHICLE},
        ],
        report_number="OH2026070415",
        vehicle_vin="1FUJA6CK21LK00418",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    challenge = fx.create_draft_challenge(
        api,
        carrier["id"],
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="Tail lamp was operative at the scene.",
        target_violation_id=rows[2]["id"],
    )
    fx.add_evidence(
        api,
        carrier["id"],
        challenge["id"],
        evidence_type=EvidenceType.PHOTO,
        document_uri="s3://evidence/ch/lamp.jpg",
        description="Photo of the illuminated lamp.",
    )
    fx.submit_challenge(api, carrier["id"], challenge["id"])
    return {"carrier": carrier, "report": report, "violations": rows}


class TestViolationListing:
    def test_filters_narrow_the_total_and_paging_walks_the_set_once(self, api):
        """PRD 3.2: "Violations are readable with filters on `report_id`,
        `violation_code_id`, `effective_violation_code_id`, `driver_id`,
        `attributed_carrier_id`, `status`, `basic_category`, `under_challenge` and
        `out_of_service`"

        Design: Corner/endpoints/violation_list_filters_and_pagination_interact_correctly
        """
        scenario = _three_violations_one_of_them_challenged(api)
        report_id = scenario["report"]["id"]
        first, second, third = (row["id"] for row in scenario["violations"])

        rows, meta = validate_paginated(
            api.list_violations(fx.AUDITOR, {"report_id": report_id})
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(rows) == 3

        rows, meta = validate_paginated(
            api.list_violations(
                fx.AUDITOR, {"report_id": report_id, "basic_category": UD}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first, second}

        rows, meta = validate_paginated(
            api.list_violations(
                fx.AUDITOR, {"report_id": report_id, "under_challenge": "true"}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == third
        assert rows[0]["under_challenge"] is True

        page_one, meta_one = validate_paginated(
            api.list_violations(
                fx.AUDITOR, {"report_id": report_id, "limit": 2, "offset": 0}
            )
        )
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert len(page_one) == 2

        page_two, meta_two = validate_paginated(
            api.list_violations(
                fx.AUDITOR, {"report_id": report_id, "limit": 2, "offset": 2}
            )
        )
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert len(page_two) == 1

        walked = [row["id"] for row in page_one] + [row["id"] for row in page_two]
        assert len(set(walked)) == 3
        assert set(walked) == {first, second, third}


def _two_active_drivers(api) -> Dict[str, Any]:
    """Two freshly registered drivers of one carrier, both ACTIVE at version 1."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    first = fx.create_driver(
        api, carrier["id"], cdl_number="OH-CDL-0001", full_name="Dana Reyes"
    )
    second = fx.create_driver(
        api, carrier["id"], cdl_number="OH-CDL-0002", full_name="Marco Bell"
    )
    return {
        "carrier": carrier,
        "first": first,
        "second": second,
        "manager": make_carrier_safety_manager_headers(carrier["id"]),
    }


class TestDriverPatch:
    def test_a_patch_touches_only_what_it_names_and_bumps_the_version_once(self, api):
        """PRD 2.5: "a counter that starts at 1 on creation and increments by exactly 1 on
        every mutation of the record." A safety manager "may later revise a driver's
        `full_name` or `employment_status`".

        Design: Corner/endpoints/driver_patch_updates_only_the_supplied_fields
        """
        scenario = _two_active_drivers(api)
        driver_id = scenario["first"]["id"]
        base_version = scenario["first"]["version"]
        manager = scenario["manager"]

        terminated = validate_success(
            api.patch_driver(
                driver_id, {"employment_status": EmploymentStatus.TERMINATED}, manager
            ),
            200,
        )
        assert terminated["employment_status"] == EmploymentStatus.TERMINATED
        assert terminated["full_name"] == "Dana Reyes"
        assert terminated["cdl_number"] == "OH-CDL-0001"
        assert terminated["version"] == base_version + 1

        rows, meta = validate_paginated(
            api.list_drivers(
                fx.AUDITOR,
                {
                    "carrier_id": scenario["carrier"]["id"],
                    "employment_status": EmploymentStatus.ACTIVE,
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == scenario["second"]["id"]

        renamed = validate_success(
            api.patch_driver(
                driver_id,
                {
                    "full_name": "Dana Reyes-Okafor",
                    "employment_status": EmploymentStatus.ACTIVE,
                },
                manager,
            ),
            200,
        )
        assert renamed["full_name"] == "Dana Reyes-Okafor"
        assert renamed["employment_status"] == EmploymentStatus.ACTIVE
        assert renamed["version"] == base_version + 2
        assert fx.read_driver(api, scenario["second"]["id"])["version"] == 1


class TestFitnessDetermination:
    def test_the_second_determination_replaces_the_first_determining_auditor(self, api):
        """PRD 3.1: "It writes `safety_fitness_status` from the supplied `determination`,
        sets `fitness_determined_at` to the current logical clock, records the acting
        `X-User-ID` as `fitness_determined_by_user_id`, and increments the carrier's
        `version` by 1."

        Design: Corner/endpoints/fitness_determination_records_the_determining_auditor
        """
        fx.set_clock(api)
        carrier = fx.create_carrier(api)
        carrier_id = carrier["id"]
        base_version = carrier["version"]
        assert carrier["safety_fitness_status"] == SafetyFitnessStatus.UNRATED
        assert carrier["fitness_determined_by_user_id"] is None

        conditional = validate_success(
            api.issue_fitness_determination(
                carrier_id,
                {
                    "determination": SafetyFitnessStatus.CONDITIONAL,
                    "basis_note": "Compliance review found HOS recordkeeping deficiencies.",
                },
                make_auditor_headers(AUDITOR_BOB),
            ),
            200,
        )
        assert conditional["safety_fitness_status"] == SafetyFitnessStatus.CONDITIONAL
        assert conditional["fitness_determined_by_user_id"] == AUDITOR_BOB
        assert conditional["fitness_determined_at"].startswith("2026-08-01T00:00:00")
        assert conditional["version"] == base_version + 1

        unsatisfactory = validate_success(
            api.issue_fitness_determination(
                carrier_id,
                {
                    "determination": SafetyFitnessStatus.UNSATISFACTORY,
                    "basis_note": "Follow-up review found unresolved brake defects.",
                },
                make_auditor_headers(AUDITOR_CAROL),
            ),
            200,
        )
        assert (
            unsatisfactory["safety_fitness_status"] == SafetyFitnessStatus.UNSATISFACTORY
        )
        assert unsatisfactory["fitness_determined_by_user_id"] == AUDITOR_CAROL
        assert unsatisfactory["version"] == base_version + 2
        assert_one_decimal(unsatisfactory["iss_value"], 0.0)


def _one_pending_request_and_one_dated_session(api) -> Dict[str, Any]:
    """A carrier holding an unanswered information request due 2026-08-31 and a coaching
    session due 2026-08-19, both ready to be swept by a September epoch."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    driver = fx.create_driver(
        api, carrier["id"], cdl_number="OH-CDL-0001", full_name="Dana Reyes"
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
        [
            {
                "violation_code_id": code["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            }
        ],
        report_number="OH2026070416",
        vehicle_vin="1FUJA6CK21LK00419",
        driver_id=driver["id"],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    coaching = fx.create_coaching_assignment(
        api,
        carrier["id"],
        driver["id"],
        rows[0]["id"],
        curriculum_code=CurriculumCode.UNSAFE_DRIVING_101,
        session_start="2026-08-05T14:00:00Z",
        session_end="2026-08-05T16:00:00Z",
    )
    challenge = fx.create_draft_challenge(
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
        challenge["id"],
        evidence_type=EvidenceType.COURT_DOCUMENT,
        document_uri="s3://evidence/ch/notes.pdf",
        description="Inspector notes without a speed measurement.",
    )
    fx.submit_challenge(api, carrier["id"], challenge["id"])
    fx.review_challenge(api, challenge["id"], ReviewAction.ASSIGN)
    fx.review_challenge(
        api,
        challenge["id"],
        ReviewAction.REQUEST_INFO,
        review_note="Send the ELD extract.",
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "violation": rows[0],
        "coaching": coaching,
        "challenge": challenge,
    }


class TestScoringRunCheckpoint:
    def test_one_epoch_reports_each_sweep_in_its_own_counter(self, api):
        """PRD 3.11: "`carriers_scored` is the number of carriers whose score rows the run
        rewrote, `scores_updated` is the number of score rows written,
        `challenges_expired` is the number of `INFO_REQUESTED` challenges the run
        auto-rejected, `coaching_marked_overdue` is the number of assignments the run
        flipped to `OVERDUE`, and `coaching_waived` is the number of assignments the run
        waived for `SCORE_BELOW_TRIGGER`."

        Design: Corner/endpoints/scoring_run_checkpoint_reports_expiry_overdue_and_quota_rederivation
        """
        scenario = _one_pending_request_and_one_dated_session(api)
        carrier_id = scenario["carrier"]["id"]

        assert scenario["coaching"]["due_at"].startswith("2026-08-19T16:00:00")
        assert_measure(
            fx.read_basic_score(api, carrier_id, UD)["certified_measure"], 0.000
        )
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 1

        fx.set_clock(api, "2026-09-01T00:00:00Z")
        run = validate_success(
            api.create_scoring_run(
                fac.create_scoring_run_payload(note="Monthly sweep."), fx.AUDITOR
            ),
            201,
        )
        assert run["snapshot_utc"].startswith("2026-09-01T00:00:00")
        assert run["challenges_expired"] == 1
        assert run["coaching_marked_overdue"] == 1
        assert run["coaching_waived"] == 0
        assert run["carriers_scored"] == 1

        expired = get_success_data(
            api.get_data_challenge(scenario["challenge"]["id"], fx.REVIEWER)
        )
        assert expired["status"] == ChallengeStatus.RESOLVED_REJECTED
        assert (
            expired["resolution_disposition"] == ResolutionDisposition.EXPIRED_NO_RESPONSE
        )
        assert expired["resolved_by_user_id"] is None

        overdue = get_success_data(
            api.get_coaching_assignment(scenario["coaching"]["id"], fx.AUDITOR)
        )
        assert overdue["status"] == CoachingStatus.OVERDUE
        assert overdue["overdue_marked_run_id"] == run["id"]

        violation = fx.read_violation(api, scenario["violation"]["id"])
        assert violation["under_challenge"] is False
        assert violation["time_weight"] == 3

        row = fx.read_basic_score(api, carrier_id, UD)
        assert_measure(row["certified_measure"], 0.500)
        assert_one_decimal(row["percentile"], 50.0)
        assert row["alert_status"] == AlertStatus.MONITOR

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["challenge_quota_used"] == 0
        assert carrier["resolved_challenge_count_24mo"] == 1
        assert carrier["accepted_challenge_count_24mo"] == 0
        assert_one_decimal(carrier["iss_value"], 17.5)
        assert carrier["open_coaching_count"] == 1
