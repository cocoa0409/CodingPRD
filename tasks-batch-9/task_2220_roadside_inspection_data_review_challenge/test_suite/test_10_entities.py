"""Entity surface: derived fields on creation, snapshots on read, pagination meta, the
entity-scoped 404 family, required fields, declared defaults, shape rules and the two
append-only audit rows.
"""

from typing import Any, Dict

from test_helpers import (
    AmendmentType,
    ApiErrorId,
    BasicCategory,
    ChallengeType,
    EmploymentStatus,
    EvidenceType,
    InterventionStatus,
    ReportStatus,
    SafetyFitnessStatus,
    SelectionBand,
    UnitType,
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

UNKNOWN_IDS = [f"00000000-0000-4000-8000-{n:012d}" for n in range(1, 14)]


class TestCarrierCreation:
    def test_creation_derives_segment_utilization_and_quota(self, api):
        """PRD 3.1: "The segment additionally fixes `challenge_quota_limit`, the number of
        data challenges the carrier may file in a rolling thirty-day window: one for a
        `SMALL` carrier, three for a `MEDIUM` carrier, six for a `LARGE` one."

        Design: Corner/entities/carrier_creation_computes_segment_utilization_and_quota_limit
        """
        fx.set_clock(api)
        carrier = validate_success(
            api.create_carrier(
                fac.create_carrier_payload(
                    dot_number="1000001",
                    legal_name="Buckeye Freight LLC",
                    average_power_units=20,
                    annual_vmt=1600000,
                ),
                fx.AUDITOR,
            ),
            201,
        )

        assert carrier["dot_number"] == "1000001"
        assert carrier["carrier_segment"] == "MEDIUM"
        assert_one_decimal(carrier["utilization_factor"], 1.5)
        assert carrier["challenge_quota_limit"] == 3
        assert carrier["challenge_quota_used"] == 0
        assert carrier["safety_fitness_status"] == SafetyFitnessStatus.UNRATED
        assert carrier["intervention_status"] == InterventionStatus.NONE
        assert carrier["selection_band"] == SelectionBand.PASS
        assert_one_decimal(carrier["iss_pre_credit_value"], 0.0)
        assert_one_decimal(carrier["iss_value"], 0.0)
        assert carrier["open_alert_count"] == 0
        assert carrier["scored_violation_count"] == 0


class TestInspectionReportRead:
    def test_the_report_read_returns_its_selection_snapshot(self, api):
        """PRD 3.2: "Ingestion writes the report in `RECEIVED` status and takes two
        snapshots of the carrier's screening posture at that moment:
        `iss_value_at_selection` captures the carrier's current screening risk value and
        `selection_band_at_selection` captures its current band, one of `PASS`, `OPTIONAL`
        or `INSPECT`."

        Design: Corner/entities/inspection_report_get_returns_selection_snapshot
        """
        fx.set_clock(api)
        carrier = fx.create_carrier(api)
        created = fx.create_report(
            api,
            carrier["id"],
            report_number="OH2026070101",
            vehicle_vin="1FUJA6CK21LK00101",
        )

        report = get_success_data(api.get_inspection_report(created["id"], fx.AUDITOR))
        assert report["status"] == ReportStatus.RECEIVED
        assert report["attributed_carrier_id"] == carrier["id"]
        assert_one_decimal(report["iss_value_at_selection"], 0.0)
        assert report["selection_band_at_selection"] == SelectionBand.PASS
        assert report["reattributed"] is False
        assert report["original_carrier_id"] is None
        assert report["duplicate_master_report_id"] is None
        assert report["active_violation_count"] == 0
        assert_one_decimal(report["total_time_weighted_severity"], 0.0)
        assert report["scored_at"] is None
        assert report["severity_basis_utc"] is None


class TestViolationCodeListing:
    def test_total_count_ignores_the_page_window(self, api):
        """PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` is the number of rows matching
        the filters before pagination is applied and `has_more` indicates whether rows
        remain beyond the current window."

        Design: Corner/entities/violation_code_list_pagination_reports_total_count_and_has_more
        """
        fx.set_clock(api)
        fx.create_violation_code(
            api, code="392.2S", basic_category=BasicCategory.UNSAFE_DRIVING
        )
        fx.create_violation_code(
            api,
            code="395.3A1",
            description="11 hour driving limit exceeded",
            basic_category=BasicCategory.HOURS_OF_SERVICE,
        )
        fx.create_violation_code(
            api,
            code="393.9TS",
            description="Inoperative tail lamp",
            basic_category=BasicCategory.VEHICLE_MAINTENANCE,
            severity_weight=2,
        )

        first, first_meta = validate_paginated(
            api.list_violation_codes(fx.AUDITOR, {"limit": 2, "offset": 0})
        )
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert len(first) == 2

        last, last_meta = validate_paginated(
            api.list_violation_codes(fx.AUDITOR, {"limit": 2, "offset": 2})
        )
        assert last_meta["total_count"] == 3
        assert last_meta["has_more"] is False
        assert len(last) == 1

        filtered, filtered_meta = validate_paginated(
            api.list_violation_codes(
                fx.AUDITOR, {"basic_category": BasicCategory.UNSAFE_DRIVING}
            )
        )
        assert filtered_meta["total_count"] == 1
        assert filtered_meta["has_more"] is False
        assert filtered[0]["code"] == "392.2S"


class TestNotFoundFamily:
    def test_every_path_family_reports_its_own_not_found(self, api):
        """PRD 2.8: "The reported error is the one belonging to the first identifier that
        fails: `ERR_CARRIER_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`,
        `ERR_VIOLATION_CODE_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
        `ERR_VIOLATION_NOT_FOUND`, `ERR_AMENDMENT_NOT_FOUND`, `ERR_CHALLENGE_NOT_FOUND`,
        `ERR_ADJUDICATION_NOT_FOUND`, `ERR_BASIC_SCORE_NOT_FOUND`,
        `ERR_COACHING_NOT_FOUND`, `ERR_CAP_NOT_FOUND`, `ERR_CAP_ITEM_NOT_FOUND` or
        `ERR_SCORING_RUN_NOT_FOUND`, each at HTTP 404."

        Design: Corner/entities/unknown_path_ids_return_entity_scoped_not_found
        """
        fx.set_clock(api)
        auditor = fx.AUDITOR
        probes = [
            (api.get_carrier(UNKNOWN_IDS[0], auditor), ApiErrorId.CARRIER_NOT_FOUND),
            (api.get_driver(UNKNOWN_IDS[1], auditor), ApiErrorId.DRIVER_NOT_FOUND),
            (
                api.get_violation_code(UNKNOWN_IDS[2], auditor),
                ApiErrorId.VIOLATION_CODE_NOT_FOUND,
            ),
            (
                api.get_inspection_report(UNKNOWN_IDS[3], auditor),
                ApiErrorId.REPORT_NOT_FOUND,
            ),
            (api.get_violation(UNKNOWN_IDS[4], auditor), ApiErrorId.VIOLATION_NOT_FOUND),
            (
                api.get_report_amendment(UNKNOWN_IDS[5], auditor),
                ApiErrorId.AMENDMENT_NOT_FOUND,
            ),
            (
                api.get_data_challenge(UNKNOWN_IDS[6], auditor),
                ApiErrorId.CHALLENGE_NOT_FOUND,
            ),
            (
                api.get_citation_adjudication(UNKNOWN_IDS[7], auditor),
                ApiErrorId.ADJUDICATION_NOT_FOUND,
            ),
            (
                api.get_basic_score(UNKNOWN_IDS[8], auditor),
                ApiErrorId.BASIC_SCORE_NOT_FOUND,
            ),
            (
                api.get_coaching_assignment(UNKNOWN_IDS[9], auditor),
                ApiErrorId.COACHING_NOT_FOUND,
            ),
            (
                api.get_corrective_action_plan(UNKNOWN_IDS[10], auditor),
                ApiErrorId.CAP_NOT_FOUND,
            ),
            (
                api.set_action_item_status(
                    UNKNOWN_IDS[11],
                    fac.cap_item_status_payload(),
                    make_carrier_analyst_headers(UNKNOWN_IDS[0]),
                ),
                ApiErrorId.CAP_ITEM_NOT_FOUND,
            ),
            (
                api.get_scoring_run(UNKNOWN_IDS[12], auditor),
                ApiErrorId.SCORING_RUN_NOT_FOUND,
            ),
        ]
        for response, error_id in probes:
            validate_error(response, error_id, 404)


class TestBodyReferenceResolution:
    def test_unresolved_parents_and_body_keys_report_the_missing_reference(self, api):
        """PRD 2.8: "Every foreign key carried in a request body resolves to an existing
        record, else the corresponding 404 from the same family."

        Design: Corner/entities/child_and_body_foreign_keys_unresolved_return_not_found
        """
        fx.set_clock(api)
        carrier = fx.create_carrier(api)
        code = fx.create_violation_code(api, code="392.2S")
        report = fx.create_report(
            api,
            carrier["id"],
            report_number="OH2026070102",
            vehicle_vin="1FUJA6CK21LK00102",
        )
        analyst = make_carrier_analyst_headers(carrier["id"])

        validate_error(
            api.add_violation(
                UNKNOWN_IDS[3],
                fac.create_violation_payload(code["id"]),
                fx.OFFICER,
            ),
            ApiErrorId.REPORT_NOT_FOUND,
            404,
        )
        validate_error(
            api.add_evidence(
                UNKNOWN_IDS[6],
                fac.create_evidence_payload(evidence_type=EvidenceType.PHOTO),
                analyst,
            ),
            ApiErrorId.CHALLENGE_NOT_FOUND,
            404,
        )
        validate_error(
            api.add_action_item(
                UNKNOWN_IDS[10],
                fac.create_cap_action_item_payload(
                    basic_category=BasicCategory.UNSAFE_DRIVING
                ),
                analyst,
            ),
            ApiErrorId.CAP_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_driver(
                fac.create_driver_payload(UNKNOWN_IDS[0]),
                make_carrier_safety_manager_headers(UNKNOWN_IDS[0]),
            ),
            ApiErrorId.CARRIER_NOT_FOUND,
            404,
        )
        validate_error(
            api.add_violation(
                report["id"],
                fac.create_violation_payload(UNKNOWN_IDS[2]),
                fx.OFFICER,
            ),
            ApiErrorId.VIOLATION_CODE_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_inspection_report(
                fac.create_inspection_report_payload(
                    carrier["id"],
                    report_number="OH2026070103",
                    vehicle_vin="1FUJA6CK21LK00103",
                    inspection_start="2026-07-02T14:00:00Z",
                    inspection_end="2026-07-02T15:00:00Z",
                    driver_id=UNKNOWN_IDS[1],
                ),
                fx.OFFICER,
            ),
            ApiErrorId.DRIVER_NOT_FOUND,
            404,
        )

        assert fx.read_report(api, report["id"])["active_violation_count"] == 0


class TestRequiredFields:
    def test_omitting_a_required_field_creates_nothing(self, api):
        """PRD 2.8: "Required fields present, enum members recognised, numeric ranges
        honoured, ordering constraints satisfied, and conditionally forbidden fields
        absent, else `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/required_fields_missing_on_create_rejected
        """
        fx.set_clock(api)
        carrier = fx.create_carrier(api)
        carrier_id = carrier["id"]

        no_vmt = fac.create_carrier_payload(
            dot_number="1000002",
            legal_name="Maple Leaf Transport",
            average_power_units=25,
        )
        no_vmt.pop("annual_vmt")
        validate_error(
            api.create_carrier(no_vmt, fx.AUDITOR), ApiErrorId.INVALID_REQUEST, 400
        )

        no_cdl = fac.create_driver_payload(carrier_id)
        no_cdl.pop("cdl_number")
        validate_error(
            api.create_driver(
                no_cdl, make_carrier_safety_manager_headers(carrier_id)
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        no_vin = fac.create_inspection_report_payload(
            carrier_id, report_number="OH2026070104"
        )
        no_vin.pop("vehicle_vin")
        validate_error(
            api.create_inspection_report(no_vin, fx.OFFICER),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        _, driver_meta = validate_paginated(
            api.list_drivers(fx.AUDITOR, {"carrier_id": carrier_id})
        )
        assert driver_meta["total_count"] == 0
        _, report_meta = validate_paginated(
            api.list_inspection_reports(
                fx.AUDITOR, {"attributed_carrier_id": carrier_id}
            )
        )
        assert report_meta["total_count"] == 0


class TestDeclaredDefaults:
    def test_omitted_optional_inputs_take_their_declared_defaults(self, api):
        """PRD 3.1: "an optional `oos_add_on` from 0 to 5 that defaults to 2 and is
        applied only when the violation was placed out of service; and an optional
        `driver_attributable` flag defaulting to true, which governs whether the code may
        motivate driver coaching."

        Design: Corner/entities/optional_fields_omitted_apply_declared_defaults
        """
        fx.set_clock(api)
        carrier = fx.create_carrier(api)

        code = fx.create_violation_code(api, code="392.2S")
        assert code["oos_add_on"] == 2
        assert code["driver_attributable"] is True

        driver = fx.create_driver(api, carrier["id"], cdl_number="OH-D-99001")
        assert driver["employment_status"] == EmploymentStatus.ACTIVE
        assert driver["coaching_required"] is False
        assert_one_decimal(driver["strict_attribution_score"], 0.0)

        threshold = fx.create_threshold(
            api, basic_category=BasicCategory.UNSAFE_DRIVING, carrier_segment="MEDIUM"
        )
        assert_one_decimal(threshold["monitor_percentile"], 50.0)
        assert_one_decimal(threshold["intervention_percentile"], 65.0)
        assert_one_decimal(threshold["investigation_percentile"], 85.0)


class TestShapeConstraints:
    def test_each_declared_shape_rule_is_enforced_on_its_own(self, api):
        """PRD 2.8: "This tier covers `inspection_level` between 1 and 6 inclusive,
        `severity_weight` between 1 and 10 inclusive, `oos_add_on` between 0 and 5
        inclusive, `limit` between 1 and 100 inclusive, `offset` not negative,
        `inspection_end` strictly after `inspection_start`, `session_end` strictly after
        `session_start`, `measure_at_p50` strictly less than `measure_at_p65` which is
        strictly less than `measure_at_p80`, `monitor_percentile` strictly less than
        `intervention_percentile` which is no greater than `investigation_percentile`,
        `resolution_disposition` supplied only on a reject review action, and a
        `court_status` that is a legal target for the court dimension."

        Design: Corner/entities/enum_and_range_constraints_rejected
        """
        fx.set_clock(api)
        carrier = fx.create_carrier(api)
        carrier_id = carrier["id"]

        bad_shapes = [
            api.create_inspection_report(
                fac.create_inspection_report_payload(
                    carrier_id, report_number="OH2026070106", inspection_level=7
                ),
                fx.OFFICER,
            ),
            api.create_inspection_report(
                fac.create_inspection_report_payload(
                    carrier_id,
                    report_number="OH2026070107",
                    selection_source="TELEPATHY",
                ),
                fx.OFFICER,
            ),
            api.create_inspection_report(
                fac.create_inspection_report_payload(
                    carrier_id,
                    report_number="OH2026070108",
                    inspection_start="2026-07-01T14:00:00Z",
                    inspection_end="2026-07-01T14:00:00Z",
                ),
                fx.OFFICER,
            ),
            api.create_violation_code(
                fac.create_violation_code_payload(
                    code="392.2X", description="Impossible weight", severity_weight=11
                ),
                fx.AUDITOR,
            ),
            api.list_carriers(fx.AUDITOR, {"limit": 0}),
            api.create_intervention_threshold(
                fac.create_intervention_threshold_payload(
                    measure_at_p50=2.0, measure_at_p65=1.0, measure_at_p80=3.0
                ),
                fx.AUDITOR,
            ),
        ]
        for response in bad_shapes:
            validate_error(response, ApiErrorId.INVALID_REQUEST, 400)

        _, report_meta = validate_paginated(
            api.list_inspection_reports(
                fx.AUDITOR, {"attributed_carrier_id": carrier_id}
            )
        )
        assert report_meta["total_count"] == 0
        _, code_meta = validate_paginated(api.list_violation_codes(fx.AUDITOR))
        assert code_meta["total_count"] == 0
        _, threshold_meta = validate_paginated(
            api.list_intervention_thresholds(fx.AUDITOR)
        )
        assert threshold_meta["total_count"] == 0


def _amended_report_with_evidence(api) -> Dict[str, Any]:
    """A scored report carrying one applied VIOLATION_CODE_CORRECTION amendment and a
    DRAFT challenge holding one evidence row."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    charged = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
    )
    corrected = fx.create_violation_code(
        api,
        code="392.2LS",
        description="Speeding 6 to 10 over the limit",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=3,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [{"violation_code_id": charged["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026070109",
    )
    challenge = fx.create_draft_challenge(
        api,
        carrier["id"],
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="Radar calibration expired.",
        target_violation_id=rows[0]["id"],
    )
    evidence = fx.add_evidence(
        api,
        carrier["id"],
        challenge["id"],
        evidence_type=EvidenceType.PHOTO,
        description="Calibration sticker",
    )
    amendment = get_success_data(
        api.create_amendment(
            report["id"],
            fac.create_amendment_payload(
                expected_report_version=fx.current_version(api, "report", report["id"]),
                amendment_type=AmendmentType.VIOLATION_CODE_CORRECTION,
                rationale="Officer recorded the wrong speed band.",
                target_violation_id=rows[0]["id"],
                corrected_violation_code_id=corrected["id"],
            ),
            fx.OFFICER,
        )
    )
    return {
        "carrier": carrier,
        "corrected": corrected,
        "challenge": challenge,
        "evidence": evidence,
        "amendment": amendment,
    }


class TestAppendOnlyAuditRows:
    def test_amendments_and_evidence_carry_no_version(self, api):
        """PRD 2.5: "Two record types are append-only audit rows and carry only `id` and
        `created_at`: `ReportAmendment` and `ChallengeEvidence`. Neither has an
        `updated_at` field and neither has a `version` field, so neither can be the
        subject of a concurrency check."

        Design: Corner/entities/immutable_children_expose_no_version_and_no_update_endpoint
        """
        scenario = _amended_report_with_evidence(api)

        amendment = get_success_data(
            api.get_report_amendment(scenario["amendment"]["id"], fx.AUDITOR)
        )
        assert "version" not in amendment
        assert (
            amendment["report_version_after"] == amendment["report_version_before"] + 1
        )
        assert amendment["corrected_violation_code_id"] == scenario["corrected"]["id"]
        assert amendment["source_challenge_id"] is None
        assert amendment["amendment_type"] == AmendmentType.VIOLATION_CODE_CORRECTION

        rows, _ = validate_paginated(
            api.list_evidence(scenario["challenge"]["id"], fx.AUDITOR)
        )
        assert len(rows) == 1
        assert rows[0]["id"] == scenario["evidence"]["id"]
        assert "version" not in rows[0]
        assert rows[0]["submitted_round"] == 0
