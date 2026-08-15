"""Obligation register versioning, committee reports, and the audit trail."""
import hashlib

from test_helpers import (
    ApiErrorId,
    accept_assessment,
    confirm_gap,
    create_approved_mapping,
    create_assessment,
    create_business_owner,
    create_change,
    create_control,
    create_obligation,
    create_plan,
    create_report_payload,
    create_triaged_change,
    get_register,
    list_gaps_for_assessment,
    make_business_owner_headers,
    make_manager_headers,
    make_officer_headers,
    make_secretary_headers,
    parse_iso,
    set_clock,
    setup_plan,
    start_assessment,
    submit_assessment,
    validate_error,
    validate_paginated,
    validate_success,
    MANAGER_1,
    OFFICER_A,
    SECRETARY_1,
    api_client,
)


class TestRegisterBasics:
    def test_register_singleton_boot_defaults(self, api, officer_a_headers):
        """PRD §3.2: "The ObligationRegister is a singleton: exactly one register
        row exists, auto-created when the server boots with a
        `current_version_number` of 0, a `version` of 1, and a `singleton_note`
        fixed at `SINGLETON`."

        Design: Corner/entities/entity_register_singleton_boot_defaults
        """
        register = validate_success(api.get_obligation_register(officer_a_headers), 200)
        assert register["current_version_number"] == 0
        assert register["version"] == 1
        assert register["singleton_note"] == "SINGLETON"

    def test_register_version_is_immutable_snapshot(self, api, officer_a_headers):
        """PRD §2.5: "Two resources are append-only snapshots and deviate from
        this contract. An ObligationRegisterVersion and an AuditEvent each carry
        only `id` and `created_at`; both `updated_at` and `version` are absent
        from them."
        PRD §3.2: "whose `published_at` is the logical clock at publish".

        Design: Corner/entities/entity_register_version_immutable
        """
        change = create_triaged_change(citation="IM-1")
        create_obligation(change["id"], obligation_code="OBL-IM-1", criticality="LOW")
        register = get_register()
        resp = api.publish_obligation_register(
            {"expected_register_version": register["version"]}, officer_a_headers
        )
        assert resp.status_code == 201, f"Setup failed: {resp.text}"
        data, meta = validate_paginated(api.list_obligation_register_versions(officer_a_headers))
        assert meta["total_count"] == 1
        version = data[0]
        assert version["version_number"] == 1
        assert "updated_at" not in version, "Append-only snapshot carries no updated_at"
        assert "version" not in version, "Append-only snapshot carries no version"
        assert parse_iso(version["published_at"]) == parse_iso("2026-08-01T00:00:00Z")
        for field in ("id", "created_at", "obligation_codes", "obligation_count", "register_checksum"):
            assert field in version, f"Missing field {field}"


class TestRegisterPublishBoundary:
    def test_publish_empty_register_rejected(self, api, officer_a_headers):
        """PRD §3.2: "The publish call must carry `expected_register_version`
        matching the register's current `version` (see §2.7), and at least one
        obligation must be `ACTIVE` at publish time — publishing against an empty
        estate is rejected with `ERR_REGISTER_EMPTY`."

        Design: Difficulty/boundary_precision_check/bp_register_publish_empty_obligation_set
        """
        change = create_triaged_change(citation="BP-2")
        create_obligation(change["id"], obligation_code="OBL-2026-BP2", criticality="LOW", activate=False)
        register = get_register()
        resp = api.publish_obligation_register(
            {"expected_register_version": register["version"]}, officer_a_headers
        )
        validate_error(resp, ApiErrorId.ERR_REGISTER_EMPTY)

    def test_publish_with_one_active_obligation_succeeds(self, api, officer_a_headers):
        """PRD §3.2: "A successful publish creates an ObligationRegisterVersion
        whose `version_number` is the register's current number plus one, so
        versions run sequentially from 1".
        PRD §3.2: "Publishing then advances the register's
        `current_version_number` by one and increments the register's `version`
        by one."

        Design: Difficulty/boundary_precision_check/bp_register_publish_empty_obligation_set
        """
        change = create_triaged_change(citation="BP-2S")
        obl = create_obligation(change["id"], obligation_code="OBL-2026-BP2", criticality="LOW", activate=False)
        register = get_register()
        empty = api.publish_obligation_register(
            {"expected_register_version": register["version"]}, officer_a_headers
        )
        validate_error(empty, ApiErrorId.ERR_REGISTER_EMPTY)

        activate = api.activate_obligation(obl["id"], officer_a_headers)
        assert activate.status_code == 200, f"Setup failed: {activate.text}"
        resp = api.publish_obligation_register(
            {"expected_register_version": register["version"]}, officer_a_headers
        )
        version = validate_success(resp, 201)
        assert version["version_number"] == 1
        assert version["obligation_count"] == 1
        assert version["obligation_codes"] == ["OBL-2026-BP2"]
        assert get_register()["current_version_number"] == 1


class TestRegisterChecksum:
    def test_checksum_over_sorted_codes(self, api, officer_a_headers):
        """PRD §3.2: "whose `obligation_codes` hold the `obligation_code` values
        of every `ACTIVE` obligation, sorted lexicographically in ascending
        byte-wise order — the sort key is always the business code, never the
        entity id".
        PRD §3.2: "Its `register_checksum` is the SHA-256 hex digest of a string
        built from the literal letter v, the version number, a vertical bar, and
        the sorted codes joined by commas, in that order."

        Design: Corner/calculations/calc_register_checksum_sorted_codes
        """
        change = create_triaged_change(citation="RC-1")
        # Create in reverse lexicographic order to prove the sort key.
        create_obligation(change["id"], obligation_code="OBL-Z-9", criticality="LOW")
        create_obligation(change["id"], obligation_code="OBL-A-1", criticality="MEDIUM")
        register = get_register()
        resp = api.publish_obligation_register(
            {"expected_register_version": register["version"]}, officer_a_headers
        )
        version = validate_success(resp, 201)
        assert version["version_number"] == 1
        assert version["obligation_codes"] == ["OBL-A-1", "OBL-Z-9"]
        assert version["obligation_count"] == 2
        expected = hashlib.sha256("v1|OBL-A-1,OBL-Z-9".encode()).hexdigest()
        assert version["register_checksum"] == expected


class TestCommitteeReports:
    def test_report_periods_half_open_adjacency(self, api, secretary_1_headers):
        """PRD §3.9: "The end must lie strictly after the start
        (`ERR_INVALID_REPORT_PERIOD`), and windows of the same committee may
        never overlap — though adjacency, where one window starts exactly as
        another ends, is allowed (`ERR_REPORT_PERIOD_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/rto_report_periods_half_open_adjacency
        """
        api.create_committee_report(
            create_report_payload(
                committee_name="BOARD_RISK_COMMITTEE",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-09-01T00:00:00Z",
            ),
            secretary_1_headers,
        )
        adjacent = api.create_committee_report(
            create_report_payload(
                committee_name="BOARD_RISK_COMMITTEE",
                period_start="2026-09-01T00:00:00Z",
                period_end="2026-10-01T00:00:00Z",
            ),
            secretary_1_headers,
        )
        validate_success(adjacent, 201)
        overlapping = api.create_committee_report(
            create_report_payload(
                committee_name="BOARD_RISK_COMMITTEE",
                period_start="2026-08-15T00:00:00Z",
                period_end="2026-09-15T00:00:00Z",
            ),
            secretary_1_headers,
        )
        validate_error(overlapping, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

    def test_overlap_scoped_per_committee(self, api, secretary_1_headers):
        """PRD §3.9: "windows of the same committee may never overlap — though
        adjacency, where one window starts exactly as another ends, is allowed
        (`ERR_REPORT_PERIOD_OVERLAP`)".

        Design: Difficulty/resource_temporal_overlap/rto_report_periods_half_open_adjacency
        """
        api.create_committee_report(
            create_report_payload(committee_name="BOARD_RISK_COMMITTEE"), secretary_1_headers
        )
        other_committee = api.create_committee_report(
            create_report_payload(committee_name="AUDIT_COMMITTEE"), secretary_1_headers
        )
        validate_success(other_committee, 201)

    def test_zero_length_period_rejected(self, api, secretary_1_headers):
        """PRD §3.9: "The end must lie strictly after the start
        (`ERR_INVALID_REPORT_PERIOD`)".

        Design: Corner/errors/err_invalid_report_period
        """
        resp = api.create_committee_report(
            create_report_payload(
                period_start="2026-08-01T00:00:00Z", period_end="2026-08-01T00:00:00Z"
            ),
            secretary_1_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REPORT_PERIOD)

    def test_report_lifecycle_and_empty_system_metrics(self, api, secretary_1_headers):
        """PRD §3.9: "The report enters as `DRAFT` with `metrics` unset."
        PRD §3.9: "If the three counts sum to zero, the index is exactly 100.0."
        PRD §3.9: "when no assessment was submitted in the window, compliance is
        vacuous and the value is 100.0."
        PRD §3.9: "Presenting (`FINALIZED` → `PRESENTED`) closes the lifecycle".

        Design: Corner/state_machines/sm_report_lifecycle_draft_finalized_present
        """
        resp = api.create_committee_report(
            create_report_payload(committee_name="EXECUTIVE_COMPLIANCE_COMMITTEE"), secretary_1_headers
        )
        report = validate_success(resp, 201)
        assert report["status"] == "DRAFT"
        assert report["metrics"] is None

        finalized = validate_success(api.finalize_committee_report(report["id"], secretary_1_headers), 200)
        assert finalized["status"] == "FINALIZED"
        assert finalized["metrics"]["compliance_index"] == 100.0
        assert finalized["metrics"]["sla_compliance_pct"] == 100.0

        again = api.finalize_committee_report(report["id"], secretary_1_headers)
        validate_error(again, ApiErrorId.ERR_INVALID_STATE)
        presented = validate_success(api.present_committee_report(report["id"], secretary_1_headers), 200)
        assert presented["status"] == "PRESENTED"


class TestComplianceIndexOrder:
    def _index_scenario(self):
        """One IN_EXECUTION plan that will breach, one PENDING_TRIAGE change; the
        covered gap (weight 4 on a never-reviewed control) keeps residual at 30
        so no zero-coverage escalation fires."""
        owner = create_business_owner()
        change = create_triaged_change(
            citation="CI-1", severity_hint="CRITICAL", feed_source="FED_REGISTER", regulator="CFPB"
        )
        obl = create_obligation(change["id"], obligation_code="OBL-2026-010", criticality="CRITICAL")
        ctl = create_control(control_code="CTL-001", title="Never reviewed control")
        create_approved_mapping(obl["id"], ctl["id"], coverage_weight=4)
        ia = create_assessment(change, owner["id"])
        start_assessment(ia["id"], owner["id"])
        submit_assessment(ia["id"], owner["id"], likelihood_score=5, severity_score=5, affected_business_lines=2)
        accept_assessment(ia["id"])
        gap = confirm_gap(list_gaps_for_assessment(ia["id"])[0]["id"])
        owner_headers = make_business_owner_headers(owner["id"])
        plan = create_plan(gap["id"], owner["id"], target="2026-08-10T00:00:00Z", title="Remediation plan")
        api_client.submit_implementation_plan(plan["id"], owner_headers)
        api_client.approve_implementation_plan(plan["id"], make_manager_headers(MANAGER_1))
        begin = api_client.begin_execution_implementation_plan(plan["id"], owner_headers)
        assert begin.status_code == 200, f"Setup failed: {begin.text}"
        # Untriaged change inside the report window.
        create_change(
            citation="CI-2", title="Untriaged change", feed_source="INT_JOURNAL",
            jurisdiction="EU", regulator="EBA", published_at="2026-07-25T00:00:00Z",
            effective_date="2027-01-01T00:00:00Z", severity_hint="LOW",
        )
        set_clock("2026-08-20T00:00:00Z")
        resp = api_client.create_committee_report(
            create_report_payload(), make_secretary_headers(SECRETARY_1)
        )
        return validate_success(resp, 201)

    def test_metrics_counts_and_index(self, api, secretary_1_headers):
        """PRD §3.9: "The `overdue_plan_count` key counts implementation plans not
        yet `VERIFIED` whose `deadline_posture` stands `OVERDUE`;
        `pending_triage_count` counts regulatory changes still `PENDING_TRIAGE`
        that were created before `period_end`; and `open_escalation_count` counts
        escalations standing in `OPEN` or `ACKNOWLEDGED`."
        PRD §3.9: "each share maps to a deduction weight: a share below one fifth
        deducts 10, a share of at least one fifth but below one half deducts 20,
        and a share of one half or more deducts 35. The `compliance_index` is 100
        minus the sum of the three deductions, floored at zero, reported at one
        decimal place."

        Design: Difficulty/combinatorial_formula/cf_compliance_index_evaluation_order
        """
        report = self._index_scenario()
        finalized = validate_success(api.finalize_committee_report(report["id"], secretary_1_headers), 200)
        assert finalized["status"] == "FINALIZED"
        metrics = finalized["metrics"]
        assert metrics["overdue_plan_count"] == 1
        assert metrics["pending_triage_count"] == 1
        assert metrics["open_escalation_count"] == 1
        assert metrics["compliance_index"] == 40.0, "T=3; each share 1/3 -> 20; 100 - 3 x 20 = 40.0"

    def test_finalized_metrics_frozen(self, api, secretary_1_headers):
        """PRD §3.9: "Finalizing the report freezes a five-key metrics snapshot
        computed at the finalize clock and stamps `finalized_at`."
        PRD §3.9: "Presenting (`FINALIZED` → `PRESENTED`) closes the lifecycle,
        and once a report is finalized its frozen metrics never move again."

        Design: Difficulty/combinatorial_formula/cf_compliance_index_evaluation_order
        """
        report = self._index_scenario()
        finalized = validate_success(api.finalize_committee_report(report["id"], secretary_1_headers), 200)
        frozen = dict(finalized["metrics"])
        set_clock("2026-08-25T00:00:00Z")
        reread = validate_success(api.get_committee_report(report["id"], secretary_1_headers), 200)
        assert reread["metrics"] == frozen, "Frozen metrics must not move with the clock"


class TestSlaCompliance:
    def test_sla_pct_mixed_window_clean_index(self, api, secretary_1_headers):
        """PRD §3.4: "`sla_breached` becomes true exactly when the clock at
        submission is strictly after the `due_date`."
        PRD §3.9: "among impact assessments whose `submitted_at` falls inside the
        half-open window, it is the percentage with `sla_breached` false — 100
        times the on-time count divided by the total in-window count, rounded
        half-up to one decimal place".
        PRD §3.9: "If the three counts sum to zero, the index is exactly 100.0."

        Design: Corner/calculations/calc_report_sla_pct_and_clean_index
        """
        owner = create_business_owner()
        change_a = create_triaged_change(citation="SLA-A")
        ia_a = create_assessment(change_a, owner["id"], due_date="2026-08-10T00:00:00Z")
        start_assessment(ia_a["id"], owner["id"])
        submitted_a = submit_assessment(ia_a["id"], owner["id"], likelihood_score=2, severity_score=2)
        assert submitted_a["sla_breached"] is False

        change_b = create_triaged_change(citation="SLA-B")
        ia_b = create_assessment(change_b, owner["id"], due_date="2026-08-05T00:00:00Z")
        start_assessment(ia_b["id"], owner["id"])
        set_clock("2026-08-12T00:00:00Z")
        submitted_b = submit_assessment(ia_b["id"], owner["id"], likelihood_score=2, severity_score=2)
        assert submitted_b["sla_breached"] is True, "Submitted 2026-08-12 > due 2026-08-05"

        resp = api.create_committee_report(
            create_report_payload(committee_name="AUDIT_COMMITTEE"), secretary_1_headers
        )
        report = validate_success(resp, 201)
        finalized = validate_success(api.finalize_committee_report(report["id"], secretary_1_headers), 200)
        assert finalized["metrics"]["sla_compliance_pct"] == 50.0, "1 of 2 in-window submits on time"
        assert finalized["metrics"]["compliance_index"] == 100.0


class TestAuditTrail:
    def test_chain_verifies_in_sequence_order(self, api, admin_1_headers, officer_a_headers, officer_b_headers):
        """PRD §2.9: "An audit event carries a `sequence_number` strictly
        increasing from 1, which defines replay order".
        PRD §2.9: "`prev_event_hash` holds the previous event's `event_hash`,
        with the literal string `GENESIS` standing in for the very first event."
        PRD §2.9: "The response reports `chain_valid` — false the moment any
        recomputed hash diverges from its stored value — together with the number
        of `events_checked`."
        PRD §2.9: "Every mutating call — creations, state transitions, cascade
        effects, clock advances — appends an AuditEvent for the primary mutated
        entity."

        Design: Corner/calculations/calc_audit_chain_verifies_in_sequence_order
        """
        create_business_owner()
        change = create_change(citation="AU-1")
        triage = api.triage_regulatory_change(
            change["id"], {"verdict": "APPLICABLE", "rationale": "r"}, officer_b_headers
        )
        assert triage.status_code == 200, f"Setup failed: {triage.text}"

        events, meta = validate_paginated(
            api.list_audit_events(admin_1_headers, params={"limit": 100})
        )
        assert meta["total_count"] == 3, "Owner create + change create + triage"
        genesis = [e for e in events if e["sequence_number"] == 1]
        assert len(genesis) == 1
        assert genesis[0]["prev_event_hash"] == "GENESIS"
        change_events, meta_c = validate_paginated(
            api.list_audit_events(admin_1_headers, params={"entity_id": change["id"]})
        )
        assert meta_c["total_count"] == 2
        assert all(e["entity_id"] == change["id"] for e in change_events)

        verification = validate_success(api.verify_audit_chain(admin_1_headers), 200)
        assert verification["chain_valid"] is True
        assert verification["events_checked"] == 3
