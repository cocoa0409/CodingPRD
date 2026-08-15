"""Compliance inspections, delinquency sweeps, and their cascades."""
from test_helpers import (
    TEST_USERS,
    assert_inspection_record,
    set_clock,
    setup_approved_application,
    setup_compliant_notice,
    setup_issued_notice,
    setup_obligated_application,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
INSP2 = TEST_USERS["inspector2_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestInspectionRecords:
    def test_inspection_record_is_append_only_shape(self, api):
        """PRD §2.5: "The single exception is `InspectionRecord`, an append-only
        evidentiary row that carries only `id` and `created_at`; both
        `updated_at` and `version` are absent from it."
        PRD §3.3: "producing an immutable `InspectionRecord` stamped with the
        inspector's identity as `inspector_id` and the notice reference as
        `notice_id`"

        Design: Corner/entities/inspection_record_has_no_version
        """
        bundle = setup_issued_notice(parcel_number="P-E10",
                                     segment_code="S-E10-1",
                                     owner_name="Vic Viburnum",
                                     street_address="50 Vib St")
        record = validate_success(api.create_inspection(
            bundle["notice"]["id"], {"result": "PASS"}, INSP2), 201)
        assert_inspection_record(record)
        assert record["result"] == "PASS"
        assert record["inspector_id"] == "insp-2"
        assert record["notice_id"] == bundle["notice"]["id"]

    def test_pass_executes_declared_side_effects(self, api):
        """PRD §3.3: "A passing inspection on a notice in `ISSUED` or
        `DELINQUENT` status — late compliance is accepted any time before city
        repair is scheduled — moves the notice to `COMPLIANT`"
        PRD §3.3: "On passage, each covered defect moves from `UNDER_REPAIR` to
        `VERIFIED`, every segment whose `open_defect_count` thereby reaches zero
        is `RESTORED`, and the parcel's `delinquency_flag` is recomputed."

        Design: Corner/state_machines/inspection_pass_executes_side_effects
        """
        bundle = setup_issued_notice(parcel_number="P-S12",
                                     segment_code="S-S12-1",
                                     owner_name="Kip Karoo",
                                     street_address="62 Karoo St")
        record = validate_success(api.create_inspection(
            bundle["notice"]["id"], {"result": "PASS", "notes": "work accepted"},
            INSP2), 201)
        assert record["notice_id"] == bundle["notice"]["id"]

        notice = validate_success(
            api.get_repair_notice(bundle["notice"]["id"], COORD))
        assert notice["status"] == "COMPLIANT"
        defect = validate_success(api.get_defect(bundle["defect"]["id"], COORD))
        assert defect["status"] == "VERIFIED"
        segment = validate_success(
            api.get_segment(bundle["segment"]["id"], COORD))
        assert segment["status"] == "RESTORED"
        assert segment["open_defect_count"] == 0

    def test_fail_before_deadline_records_only(self, api):
        """PRD §3.3: "a failing inspection recorded while the clock is strictly
        past the deadline tips that notice over directly"
        PRD §3.3: "An `Inspector` records an inspection against a notice with a
        `result` of `PASS` or `FAIL` and optional free-text `notes`, producing
        an immutable `InspectionRecord`"

        Design: Corner/state_machines/inspection_fail_before_deadline_records_only
        """
        bundle = setup_issued_notice(parcel_number="P-S13",
                                     segment_code="S-S13-1",
                                     owner_name="Liv Linden",
                                     street_address="63 Linden St")
        set_clock("2026-08-10T00:00:00Z")
        record = validate_success(api.create_inspection(
            bundle["notice"]["id"], {"result": "FAIL", "notes": "not started"},
            INSP2), 201)
        assert record["result"] == "FAIL"

        notice = validate_success(
            api.get_repair_notice(bundle["notice"]["id"], COORD))
        assert notice["status"] == "ISSUED", \
            "no delinquency while the clock is before the deadline"
        defect = validate_success(api.get_defect(bundle["defect"]["id"], COORD))
        assert defect["status"] == "UNDER_REPAIR"

        validate_success(api.create_inspection(
            bundle["notice"]["id"], {"result": "PASS"}, INSP2), 201)
        records, _ = validate_paginated(
            api.list_inspections(bundle["notice"]["id"], COORD))
        assert len(records) == 2, "append-only log accumulates both records"


class TestDelinquencyCascade:
    def _setup_obligated_past_deadline(self):
        bundle = setup_obligated_application(
            parcel_number="P-900", segment_code="S-900-1",
            owner_name="Jack Juniper", street_address="10 Juniper St",
            defect_type="VERTICAL_SEPARATION", measured_offset_inches=0.75,
            area_sqft=100, estimated_qty_sqft=100)
        set_clock("2026-09-20T00:00:00Z")
        return bundle

    def test_fail_after_deadline_cascades_to_application(self, api):
        """PRD §3.3: "Every cost-share application on the notice in
        `SUBMITTED`, `RETURNED`, `APPROVED`, or `OBLIGATED` status is
        `CANCELLED`; each application cancelled out of `OBLIGATED` also flips
        its `payment_status` from `RESERVED` to `RELEASED`"

        Design: Difficulty/transitive_cascade/inspection_fail_after_deadline_cascade
        """
        bundle = self._setup_obligated_past_deadline()
        validate_success(api.create_inspection(
            bundle["notice"]["id"],
            {"result": "FAIL", "notes": "work not started"}, INSP2), 201)

        notice = validate_success(
            api.get_repair_notice(bundle["notice"]["id"], COORD))
        assert notice["status"] == "DELINQUENT", "link 1: FAIL past deadline"

        app = validate_success(
            api.get_application(bundle["application"]["id"], COORD))
        assert app["review_status"] == "CANCELLED", "link 2: cascade cancels"
        assert app["payment_status"] == "RELEASED"

    def test_fail_after_deadline_releases_cycle_funds(self, api):
        """PRD §3.3: "returns its `provisional_award_cents` to the cycle by
        reducing `committed_cents`; the parcel's `delinquency_flag` turns true;
        and the notice's `version` increments."

        Design: Difficulty/transitive_cascade/inspection_fail_after_deadline_cascade
        """
        bundle = self._setup_obligated_past_deadline()
        validate_success(api.create_inspection(
            bundle["notice"]["id"],
            {"result": "FAIL", "notes": "work not started"}, INSP2), 201)

        cycle = validate_success(
            api.get_program_cycle(bundle["cycle"]["id"], COORD))
        assert cycle["committed_cents"] == 0, \
            "link 3: reservation released back to the cycle"
        assert cycle["available_cents"] == 10_000_000

        parcel = validate_success(api.get_parcel(bundle["parcel"]["id"], COORD))
        assert parcel["delinquency_flag"] is True


class TestDelinquencySweeps:
    def test_sweep_strict_deadline_boundary(self, api):
        """PRD §3.3: "a coordinator-run delinquency sweep advances every
        `ISSUED` notice whose `compliance_deadline` is strictly before the
        logical clock — equality still counts as compliant"

        Design: Corner/cross_cutting_complexity_layers/delinquency_sweep_strict_boundary
        """
        bundle = setup_issued_notice(parcel_number="P-X4",
                                     segment_code="S-X4-1",
                                     owner_name="Leo Locust",
                                     street_address="119 Locust St")
        notice_id = bundle["notice"]["id"]

        set_clock("2026-09-15T00:00:00Z")
        sweep1 = validate_success(api.run_delinquency_sweep(COORD))
        assert sweep1["swept_notice_count"] == 0
        notice = validate_success(api.get_repair_notice(notice_id, COORD))
        assert notice["status"] == "ISSUED", \
            "clock equal to the deadline is still compliant"

        set_clock("2026-09-16T00:00:00Z")
        sweep2 = validate_success(api.run_delinquency_sweep(COORD))
        assert sweep2["swept_notice_count"] == 1
        assert notice_id in sweep2["swept_notice_ids"]
        notice = validate_success(api.get_repair_notice(notice_id, COORD))
        assert notice["status"] == "DELINQUENT"
        parcel = validate_success(api.get_parcel(bundle["parcel"]["id"], COORD))
        assert parcel["delinquency_flag"] is True

    def test_sweep_expires_approved_applications(self, api):
        """PRD §3.6: "The delinquency sweep of §3.3 also expires every
        `APPROVED` application whose `approval_expires_at` is strictly before
        the logical clock, moving it to `EXPIRED` without touching cycle funds,
        since nothing was reserved yet."

        Design: Corner/cross_cutting_complexity_layers/sweep_expires_approved_applications
        """
        bundle = setup_approved_application(
            parcel_number="P-X3", segment_code="S-X3-1",
            owner_name="Kat Katsura", street_address="118 Katsura St",
            defect_type="VERTICAL_SEPARATION", measured_offset_inches=0.75,
            area_sqft=100, estimated_qty_sqft=100)
        setup_compliant_notice(bundle)
        set_clock("2026-10-01T00:00:00Z")

        sweep = validate_success(api.run_delinquency_sweep(COORD))
        assert sweep["swept_notice_count"] == 0, \
            "the COMPLIANT notice is not sweepable"
        assert sweep["expired_application_count"] == 1
        assert bundle["application"]["id"] in sweep["expired_application_ids"]

        app = validate_success(
            api.get_application(bundle["application"]["id"], COORD))
        assert app["review_status"] == "EXPIRED"
