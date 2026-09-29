"""The concurrency guards and the listing contract, exercised where the version that goes
stale was bumped by somebody else's action -- a second determination, the scoring pass
itself, a safety manager's attribution -- plus filters re-evaluated against live rows.
"""

from typing import Any, Dict

from test_helpers import (
    AUDITOR_BOB,
    AlertStatus,
    AmendmentType,
    ApiErrorId,
    BasicCategory,
    CapStatus,
    CarrierSegment,
    CourtStatus,
    RecordUpdateStatus,
    ReportStatus,
    SafetyFitnessStatus,
    SelectionBand,
    UnitType,
    ViolationStatus,
    assert_measure,
    assert_one_decimal,
    factories as fac,
    fixtures as fx,
    make_carrier_analyst_headers,
    make_carrier_safety_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UD = BasicCategory.UNSAFE_DRIVING
HOS = BasicCategory.HOURS_OF_SERVICE


def _carrier_determined_twice(api) -> Dict[str, Any]:
    """A carrier whose fitness was determined CONDITIONAL and then UNSATISFACTORY, so the
    version an analyst read after the first determination is one behind."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    fx.issue_fitness_determination(
        api,
        carrier["id"],
        SafetyFitnessStatus.CONDITIONAL,
        auditor_id=AUDITOR_BOB,
        basis_note="Compliance review found HOS recordkeeping deficiencies.",
    )
    stale_version = fx.current_version(api, "carrier", carrier["id"])
    fx.issue_fitness_determination(
        api,
        carrier["id"],
        SafetyFitnessStatus.UNSATISFACTORY,
        auditor_id=AUDITOR_BOB,
        basis_note="Follow-up review downgraded the carrier.",
    )
    fresh_version = fx.current_version(api, "carrier", carrier["id"])
    return {
        "carrier": carrier,
        "stale_version": stale_version,
        "fresh_version": fresh_version,
    }


class TestStaleCarrierVersionOnPlanCreation:
    def test_a_second_determination_invalidates_the_analysts_carrier_view(self, api):
        """PRD 2.6: "Creating a `CorrectiveActionPlan` requires `expected_carrier_version`
        in the request body, carrying the client's last observed `version` of the target
        `Carrier`. If that value does not equal the carrier's current `version`, the create
        is rejected with `ERR_STALE_CARRIER_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/stale_carrier_version_on_cap_create_rejected
        """
        scenario = _carrier_determined_twice(api)
        carrier_id = scenario["carrier"]["id"]
        analyst = make_carrier_analyst_headers(carrier_id)

        assert scenario["carrier"]["version"] == 1
        assert scenario["stale_version"] == 2
        assert scenario["fresh_version"] == 3
        assert (
            fx.read_carrier(api, carrier_id)["safety_fitness_status"]
            == SafetyFitnessStatus.UNSATISFACTORY
        )

        refused = api.create_corrective_action_plan(
            fac.create_cap_payload(
                carrier_id,
                scenario["stale_version"],
                narrative="Plan written against the pre-downgrade carrier view.",
            ),
            analyst,
        )
        validate_error(refused, ApiErrorId.STALE_CARRIER_VERSION, 412)
        _, plan_meta = validate_paginated(api.list_corrective_action_plans(fx.AUDITOR))
        assert plan_meta["total_count"] == 0
        assert fx.current_version(api, "carrier", carrier_id) == 3

        plan = validate_success(
            api.create_corrective_action_plan(
                fac.create_cap_payload(
                    carrier_id,
                    scenario["fresh_version"],
                    narrative="Plan written against the current carrier view.",
                ),
                analyst,
            ),
            201,
        )
        assert plan["status"] == CapStatus.DRAFT
        assert plan["triggering_fitness_status"] == SafetyFitnessStatus.UNSATISFACTORY
        assert plan["item_count"] == 0
        assert_one_decimal(plan["completion_pct"], 0.0)
        assert plan["superseded_cap_id"] is None


def _scored_report_read_before_it_was_scored(api) -> Dict[str, Any]:
    """A report whose version was observed while it was still VALIDATED, then scored --
    scoring being a write of its own."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    light = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    heavier = fx.create_violation_code(
        api,
        code="392.2C",
        description="Failure to obey traffic control device",
        basic_category=UD,
        severity_weight=8,
    )
    fx.create_threshold(api, basic_category=UD, carrier_segment=CarrierSegment.MEDIUM)
    report, rows = fx.build_validated_report(
        api,
        carrier["id"],
        [{"violation_code_id": light["id"], "unit_type": UnitType.VEHICLE}],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    validated_version = fx.current_version(api, "report", report["id"])
    fx.score_report(api, report["id"])
    scored_version = fx.current_version(api, "report", report["id"])
    return {
        "carrier": carrier,
        "light": light,
        "heavier": heavier,
        "report": report,
        "violation": rows[0],
        "validated_version": validated_version,
        "scored_version": scored_version,
    }


class TestStaleReportVersionOnAmendment:
    def test_scoring_is_a_write_so_the_pre_score_version_no_longer_files(self, api):
        """PRD 2.6: "Filing a `ReportAmendment` requires `expected_report_version` in the
        request body, carrying the client's last observed `version` of the target
        `InspectionReport`. If that value does not equal the report's current `version`,
        the amendment is rejected with `ERR_STALE_REPORT_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/stale_report_version_on_amendment_rejected
        """
        scenario = _scored_report_read_before_it_was_scored(api)
        report_id = scenario["report"]["id"]
        violation_id = scenario["violation"]["id"]
        carrier_id = scenario["carrier"]["id"]

        assert scenario["scored_version"] == scenario["validated_version"] + 1
        assert fx.read_report(api, report_id)["status"] == ReportStatus.SCORED
        before = fx.read_basic_score(api, carrier_id, UD)
        assert_measure(before["certified_measure"], 0.500)
        assert_one_decimal(before["percentile"], 50.0)
        assert before["alert_status"] == AlertStatus.MONITOR

        correction = {
            "amendment_type": AmendmentType.VIOLATION_CODE_CORRECTION,
            "rationale": "Officer recorded the wrong control-device code.",
            "target_violation_id": violation_id,
            "corrected_violation_code_id": scenario["heavier"]["id"],
        }
        refused = api.create_amendment(
            report_id,
            fac.create_amendment_payload(
                expected_report_version=scenario["validated_version"], **correction
            ),
            fx.OFFICER,
        )
        validate_error(refused, ApiErrorId.STALE_REPORT_VERSION, 412)
        held = fx.read_report(api, report_id)
        assert held["status"] == ReportStatus.SCORED
        assert held["version"] == scenario["scored_version"]
        untouched = fx.read_violation(api, violation_id)
        assert untouched["effective_violation_code_id"] == scenario["light"]["id"]
        assert untouched["status"] == ViolationStatus.ACTIVE
        _, amendment_meta = validate_paginated(
            api.list_report_amendments(fx.AUDITOR, {"report_id": report_id})
        )
        assert amendment_meta["total_count"] == 0

        amendment = validate_success(
            api.create_amendment(
                report_id,
                fac.create_amendment_payload(
                    expected_report_version=scenario["scored_version"], **correction
                ),
                fx.OFFICER,
            ),
            201,
        )
        assert amendment["report_version_before"] == scenario["scored_version"]
        assert amendment["report_version_after"] == scenario["scored_version"] + 1

        amended = fx.read_report(api, report_id)
        assert amended["status"] == ReportStatus.AMENDED
        assert amended["version"] == scenario["scored_version"] + 1
        recoded = fx.read_violation(api, violation_id)
        assert recoded["effective_violation_code_id"] == scenario["heavier"]["id"]
        assert recoded["status"] == ViolationStatus.RECODED

        after = fx.read_basic_score(api, carrier_id, UD)
        assert after["relevant_inspection_count"] == 0
        assert_measure(after["certified_measure"], 0.000)
        assert after["percentile"] is None
        assert after["alert_status"] == AlertStatus.NOT_ENOUGH_DATA
        carrier = fx.read_carrier(api, carrier_id)
        assert_one_decimal(carrier["iss_value"], 0.0)
        assert carrier["selection_band"] == SelectionBand.PASS


def _violation_attributed_after_the_officer_read_it(api) -> Dict[str, Any]:
    """A scored driver violation whose version was bumped by the carrier's own safety
    manager attributing it to a driver."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api,
        code="395.8",
        description="False report of driver record of duty status",
        basic_category=HOS,
        severity_weight=5,
        driver_attributable=True,
    )
    fx.create_threshold(api, basic_category=HOS, carrier_segment=CarrierSegment.MEDIUM)
    driver = fx.create_driver(
        api, carrier["id"], cdl_number="OH-D-77104", full_name="Marcus Webb"
    )
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.DRIVER}],
        # PRD 3.2: a DRIVER-unit violation satisfies the validation gate through a
        # driver_id on the report; the violation itself stays unattributed so the
        # safety manager's later attribution is what bumps its version.
        driver_id=driver["id"],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    violation_id = rows[0]["id"]
    stale_version = fx.current_version(api, "violation", violation_id)
    fx.attribute_driver(api, carrier["id"], violation_id, driver["id"])
    fresh_version = fx.current_version(api, "violation", violation_id)
    return {
        "carrier": carrier,
        "driver": driver,
        "report": report,
        "violation_id": violation_id,
        "stale_version": stale_version,
        "fresh_version": fresh_version,
    }


class TestStaleViolationVersionOnAdjudication:
    def test_an_attribution_by_another_party_blocks_the_citation_filing(self, api):
        """PRD 2.6: "Creating a `CitationAdjudication` requires
        `expected_violation_version` in the request body, carrying the client's last
        observed `version` of the target `Violation`. If that value does not equal the
        violation's current `version`, the create is rejected with
        `ERR_STALE_VIOLATION_VERSION` and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/stale_violation_version_on_adjudication_rejected
        """
        scenario = _violation_attributed_after_the_officer_read_it(api)
        violation_id = scenario["violation_id"]

        assert scenario["fresh_version"] == scenario["stale_version"] + 1
        attributed = fx.read_violation(api, violation_id)
        assert attributed["driver_id"] == scenario["driver"]["id"]
        assert_one_decimal(attributed["time_weighted_severity"], 15.0)

        refused = api.create_citation_adjudication(
            fac.create_citation_adjudication_payload(
                violation_id,
                scenario["stale_version"],
                citation_number="OH-CIT-2026-4471",
                court_date="2026-09-15T00:00:00Z",
            ),
            fx.OFFICER,
        )
        validate_error(refused, ApiErrorId.STALE_VIOLATION_VERSION, 412)
        _, meta = validate_paginated(
            api.list_citation_adjudications(fx.AUDITOR, {"violation_id": violation_id})
        )
        assert meta["total_count"] == 0
        assert (
            fx.current_version(api, "violation", violation_id)
            == scenario["fresh_version"]
        )

        adjudication = validate_success(
            api.create_citation_adjudication(
                fac.create_citation_adjudication_payload(
                    violation_id,
                    scenario["fresh_version"],
                    citation_number="OH-CIT-2026-4471",
                    court_date="2026-09-15T00:00:00Z",
                ),
                fx.OFFICER,
            ),
            201,
        )
        assert adjudication["court_status"] == CourtStatus.PENDING
        assert adjudication["record_update_status"] == RecordUpdateStatus.NOT_APPLIED
        assert_one_decimal(adjudication["severity_factor"], 1.0)
        assert adjudication["superseded"] is False

        after = fx.read_violation(api, violation_id)
        assert after["version"] == scenario["fresh_version"] + 1
        assert_one_decimal(after["time_weighted_severity"], 15.0)


class TestVersionAdvancesOncePerWrite:
    def test_body_less_transitions_bump_the_version_and_reads_never_do(self, api):
        """PRD 2.5: "**`version`** (integer): a counter that starts at 1 on creation and
        increments by exactly 1 on every mutation of the record."

        Design: Corner/cross_cutting_complexity_layers/version_increments_by_one_on_every_write
        """
        fx.set_clock(api)
        code = fx.create_violation_code(
            api, code="392.2S", basic_category=UD, severity_weight=5
        )
        fx.create_threshold(api, basic_category=UD, carrier_segment=CarrierSegment.MEDIUM)
        assert code["version"] == 1

        carrier = fx.create_carrier(api)
        assert carrier["version"] == 1
        fx.issue_fitness_determination(
            api,
            carrier["id"],
            SafetyFitnessStatus.CONDITIONAL,
            auditor_id=AUDITOR_BOB,
            basis_note="Compliance review finding.",
        )
        assert fx.current_version(api, "carrier", carrier["id"]) == 2

        driver = fx.create_driver(
            api, carrier["id"], cdl_number="OH-D-77105", full_name="Dana Ruiz"
        )
        assert driver["version"] == 1
        renamed = validate_success(
            api.patch_driver(
                driver["id"],
                {"full_name": "Dana Ruiz-Perez"},
                make_carrier_safety_manager_headers(carrier["id"]),
            ),
            200,
        )
        assert renamed["version"] == 2
        assert renamed["full_name"] == "Dana Ruiz-Perez"

        revised = validate_success(
            api.patch_violation_code(
                code["id"],
                {"description": "Speeding 15 mph or more over the posted limit"},
                fx.AUDITOR,
            ),
            200,
        )
        assert revised["version"] == code["version"] + 1

        report = fx.create_report(
            api,
            carrier["id"],
            inspection_start="2026-07-01T14:00:00Z",
            inspection_end="2026-07-01T15:00:00Z",
        )
        assert report["version"] == 1
        assert report["status"] == ReportStatus.RECEIVED
        violation = fx.add_violation(
            api, report["id"], code["id"], unit_type=UnitType.VEHICLE
        )
        assert violation["version"] == 1

        # PRD 3.3: "Appending recomputes the report's `active_violation_count` and
        # increments the report's `version` by 1." — so the append above already
        # carried the report from 1 to 2 before either transition ran.
        validated = fx.validate_report(api, report["id"])
        assert validated["version"] == 3
        assert validated["status"] == ReportStatus.VALIDATED
        scored = fx.score_report(api, report["id"])
        assert scored["version"] == 4
        assert scored["status"] == ReportStatus.SCORED

        after_read = fx.read_report(api, report["id"])
        assert after_read["version"] == 4
        row = fx.read_basic_score(api, carrier["id"], UD)
        assert_measure(row["certified_measure"], 0.500)
        assert_one_decimal(row["percentile"], 50.0)


def _three_received_reports(api) -> Dict[str, Any]:
    """Three RECEIVED reports on one carrier, each with its own inspection window."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    windows = [
        ("2026-07-01T08:00:00Z", "2026-07-01T09:00:00Z"),
        ("2026-07-02T08:00:00Z", "2026-07-02T09:00:00Z"),
        ("2026-07-03T08:00:00Z", "2026-07-03T09:30:00Z"),
    ]
    reports = [
        fx.create_report(
            api, carrier["id"], inspection_start=start, inspection_end=end
        )
        for start, end in windows
    ]
    return {"carrier": carrier, "reports": reports}


class TestFilteredPagesUnderMutation:
    def test_validating_one_report_moves_it_between_filtered_result_sets(self, api):
        """PRD 2.4: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` is the number of rows matching
        the filters before pagination is applied and `has_more` indicates whether rows
        remain beyond the current window."

        Design: Corner/cross_cutting_complexity_layers/report_filters_and_offset_pages_stay_consistent_under_mutation
        """
        scenario = _three_received_reports(api)
        carrier_id = scenario["carrier"]["id"]
        all_ids = {report["id"] for report in scenario["reports"]}
        moved_id = scenario["reports"][1]["id"]

        first_page, first_meta = validate_paginated(
            api.list_inspection_reports(
                fx.AUDITOR,
                {"status": ReportStatus.RECEIVED, "limit": 2, "offset": 0},
            )
        )
        assert first_meta["total_count"] == 3
        assert len(first_page) == 2
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_inspection_reports(
                fx.AUDITOR,
                {"status": ReportStatus.RECEIVED, "limit": 2, "offset": 2},
            )
        )
        assert second_meta["total_count"] == 3
        assert len(second_page) == 1
        assert second_meta["has_more"] is False
        paged_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
        assert len(paged_ids) == len(set(paged_ids))
        assert set(paged_ids) == all_ids

        validated = fx.validate_report(api, moved_id)
        assert validated["status"] == ReportStatus.VALIDATED

        remaining, remaining_meta = validate_paginated(
            api.list_inspection_reports(
                fx.AUDITOR,
                {"status": ReportStatus.RECEIVED, "limit": 2, "offset": 0},
            )
        )
        assert remaining_meta["total_count"] == 2
        assert len(remaining) == 2
        assert remaining_meta["has_more"] is False
        assert moved_id not in {row["id"] for row in remaining}

        empty, empty_meta = validate_paginated(
            api.list_inspection_reports(
                fx.AUDITOR,
                {"status": ReportStatus.RECEIVED, "limit": 2, "offset": 2},
            )
        )
        assert empty_meta["total_count"] == 2
        assert len(empty) == 0
        assert empty_meta["has_more"] is False

        promoted, promoted_meta = validate_paginated(
            api.list_inspection_reports(
                fx.AUDITOR, {"status": ReportStatus.VALIDATED}
            )
        )
        assert promoted_meta["total_count"] == 1
        assert promoted[0]["id"] == moved_id

        everything, everything_meta = validate_paginated(
            api.list_inspection_reports(
                fx.AUDITOR,
                {"attributed_carrier_id": carrier_id, "limit": 100, "offset": 0},
            )
        )
        assert everything_meta["total_count"] == 3
        assert len(everything) == 3
        assert everything_meta["has_more"] is False
        assert {row["id"] for row in everything} == all_ids
