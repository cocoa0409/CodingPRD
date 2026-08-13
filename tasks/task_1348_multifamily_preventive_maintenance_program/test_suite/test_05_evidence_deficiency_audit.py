"""Evidence capture, deficiency recording/waiver, and completion audits."""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    api_client,
    create_property, create_building, create_unit, create_asset,
    create_template, create_plan, create_batch, add_visit, publish_batch,
    set_clock, start_visit, record_evidence, record_deficiency,
    setup_property_scaffold, setup_in_progress_visit, setup_completed_visit,
    create_deficiency_payload,
    make_technician_headers, make_auditor_headers,
    get_asset,
)

TEST_PM = TEST_USERS["property_manager_headers"]


class TestEvidenceRecordedBySystemStamped:
    def test_recorded_by_stamped_from_caller_user_id(self, api):
        """PRD §3.4: "Each row stamps `recorded_by` with the recording
        technician's `X-User-ID`."

        Design: Corner/entities/evidence_recorded_by_system_stamped
        """
        ctx = setup_in_progress_visit(requires_evidence=True, estimated_labor_minutes=15,
                                      frequency_days=30)
        resp = api.create_evidence(
            ctx["visit"]["id"],
            {"evidence_type": "FILTER_REPLACEMENT", "serial_or_lot": "LOT-123"},
            make_technician_headers("tech-1"),
        )
        evidence = validate_success(resp, expected_status=201)
        assert evidence["recorded_by"] == "tech-1", (
            f"recorded_by must be system-stamped from X-User-ID, got {evidence['recorded_by']}"
        )


class TestDeficiencyAssetMismatch:
    """Two units (101, 102) each with an HVAC asset; the visit in progress
    services unit 101's asset a1."""

    def _setup(self):
        prop = create_property()
        building = create_building(prop["id"])
        unit1 = create_unit(building["id"], unit_number="101", occupancy_status="VACANT")
        unit2 = create_unit(building["id"], unit_number="102", occupancy_status="VACANT")
        asset1 = create_asset(unit1["id"], component_type="HVAC")
        asset2 = create_asset(unit2["id"], component_type="HVAC")
        template = create_template(prop["id"], component_type="HVAC")
        plan = create_plan(prop["id"], adopt=True)
        batch = create_batch(prop["id"], window_start="2026-08-02T08:00:00Z",
                             window_end="2026-08-02T18:00:00Z")
        visit = add_visit(batch["id"], unit1["id"], template["id"], asset1["id"],
                          plan["id"], scheduled_start="2026-08-02T09:00:00Z")
        publish_batch(batch["id"])
        set_clock("2026-08-02T09:00:00Z")
        start_visit(visit["id"], technician_id="tech-1")
        return visit, asset1, asset2

    def test_deficiency_naming_other_asset_rejected(self, api):
        """PRD §3.5: "the technician records a deficiency naming the `asset_id`
        observed, which must equal the visit's own `asset_id` or the request
        fails with `ERR_DEFICIENCY_ASSET_MISMATCH`".

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_safety_on_deficiency
        """
        visit, _asset1, asset2 = self._setup()
        resp = api.create_deficiency(
            visit["id"],
            create_deficiency_payload(asset2["id"], severity="LOW",
                                      description="Wrong asset reference"),
            make_technician_headers("tech-1"),
        )
        validate_error(resp, ApiErrorId.ERR_DEFICIENCY_ASSET_MISMATCH)

    def test_deficiency_naming_visit_asset_created_recorded(self, api):
        """PRD §3.5: "A new deficiency is `RECORDED`, its `work_order_id` null".

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_safety_on_deficiency
        """
        visit, asset1, _asset2 = self._setup()
        resp = api.create_deficiency(
            visit["id"],
            create_deficiency_payload(asset1["id"], severity="LOW", description="Cosmetic"),
            make_technician_headers("tech-1"),
        )
        deficiency = validate_success(resp, expected_status=201)
        assert deficiency["status"] == "RECORDED"
        assert deficiency["work_order_id"] is None


class TestDeficiencyWaiveRules:
    def _setup_two_deficiencies(self):
        ctx = setup_in_progress_visit(
            component_type="APPLIANCE", estimated_labor_minutes=20,
            warranty_months=12, replacement_cost_cents=100000,
        )
        d_low = record_deficiency(ctx["visit"]["id"], ctx["asset"]["id"],
                                  technician_id="tech-1", severity="LOW",
                                  description="Cosmetic scratch")
        d_emg = record_deficiency(ctx["visit"]["id"], ctx["asset"]["id"],
                                  technician_id="tech-1", severity="EMERGENCY",
                                  description="Gas smell")
        return ctx, d_low, d_emg

    def test_emergency_deficiency_not_waivable(self, api):
        """PRD §3.5: "a deficiency in `RECORDED` or `TRIAGED` may be waived — but
        never one whose `severity` is `EMERGENCY` (`ERR_EMERGENCY_NOT_WAIVABLE`)".

        Design: Corner/state_machines/deficiency_waive_terminal_and_emergency_blocked
        """
        _ctx, _d_low, d_emg = self._setup_two_deficiencies()
        resp = api.waive_deficiency(d_emg["id"], TEST_PM)
        validate_error(resp, ApiErrorId.ERR_EMERGENCY_NOT_WAIVABLE)

    def test_low_deficiency_waived_terminally(self, api):
        """PRD §3.5: "a waived deficiency rests terminally in `WAIVED`."

        Design: Corner/state_machines/deficiency_waive_terminal_and_emergency_blocked
        """
        _ctx, d_low, _d_emg = self._setup_two_deficiencies()
        resp = api.waive_deficiency(d_low["id"], TEST_PM)
        deficiency = validate_success(resp)
        assert deficiency["status"] == "WAIVED"


class TestSegregationOfDutiesOnAudit:
    def test_same_user_audit_rejected_and_independent_audit_passes(self, api):
        """PRD §3.6: "The server stamps `auditor_id` from the caller's `X-User-ID`
        and `audited_at` from the logical clock, and enforces segregation of
        duties: an auditor whose `X-User-ID` equals the visit's `technician_id`
        is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_on_audit
        """
        ctx = setup_completed_visit(occupancy="OCCUPIED", actual_minutes=30, condition_score=4)
        resp = api.create_audit(ctx["visit"]["id"], {"outcome": "PASS"},
                                make_auditor_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        audit = validate_success(
            api.create_audit(ctx["visit"]["id"], {"outcome": "PASS"}, make_auditor_headers("aud-1")),
            expected_status=201,
        )
        assert audit["outcome"] == "PASS"
        assert audit["auditor_id"] == "aud-1"


class TestAuditFailCascadesToAssetCompliance:
    def _setup_completed(self):
        return setup_completed_visit(occupancy="OCCUPIED", actual_minutes=30, condition_score=4)

    def test_fail_audit_drops_asset_to_non_compliant(self, api):
        """PRD §3.6: "A `FAIL` outcome drops the serviced asset's
        `compliance_status` to `NON_COMPLIANT` regardless of where the due-date
        mapping would otherwise place it." and "The server stamps `auditor_id`
        from the caller's `X-User-ID` and `audited_at` from the logical clock".

        Design: Difficulty/transitive_cascade/audit_fail_cascades_to_asset_compliance
        """
        ctx = self._setup_completed()
        asset_before = get_asset(ctx["asset"]["id"])
        assert asset_before["compliance_status"] == "COMPLIANT"

        audit = validate_success(
            api.create_audit(ctx["visit"]["id"],
                             {"outcome": "FAIL", "fail_reason": "Filter not actually replaced"},
                             make_auditor_headers("aud-7")),
            expected_status=201,
        )
        assert audit["auditor_id"] == "aud-7"
        assert audit["audited_at"].startswith("2026-08-02T09:00"), (
            f"audited_at must be stamped from the logical clock, got {audit['audited_at']}"
        )

        asset_after = get_asset(ctx["asset"]["id"])
        assert asset_after["compliance_status"] == "NON_COMPLIANT", (
            f"expected NON_COMPLIANT after FAIL audit, got {asset_after['compliance_status']}"
        )

    def test_audit_readable_as_zero_or_one_array_and_second_audit_rejected(self, api):
        """PRD §3.6: "Reading a visit's audit returns an array of zero or one
        entries." and "because exactly one audit may exist per visit, a second
        audit on the same visit also fails with `ERR_INVALID_STATE`".

        Design: Difficulty/transitive_cascade/audit_fail_cascades_to_asset_compliance
        """
        ctx = self._setup_completed()
        validate_success(
            api.create_audit(ctx["visit"]["id"],
                             {"outcome": "FAIL", "fail_reason": "Filter not actually replaced"},
                             make_auditor_headers("aud-7")),
            expected_status=201,
        )
        audits, _meta = validate_paginated(api.get_audit(ctx["visit"]["id"], TEST_PM))
        assert len(audits) == 1, f"expected exactly one audit row, got {audits}"
        assert audits[0]["outcome"] == "FAIL"
        assert audits[0]["fail_reason"] == "Filter not actually replaced"

        resp = api.create_audit(ctx["visit"]["id"], {"outcome": "PASS"},
                                make_auditor_headers("aud-2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
