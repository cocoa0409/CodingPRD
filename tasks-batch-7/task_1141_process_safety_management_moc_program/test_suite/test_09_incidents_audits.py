"""Incident feedback into PHA, audit findings/corrective actions, audit windows."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    classify,
    create_audit_payload,
    drive_audit_to_reported,
    drive_incident_to_findings_submitted,
    get_audit,
    get_moc,
    get_pha_study,
    get_unit,
    list_audit_findings,
    list_unit_action_items,
    make_auditor_headers,
    make_investigator_headers,
    make_requester_headers,
    new_audit,
    new_draft_moc,
    new_incident,
    new_manual_item,
    new_personnel,
    new_unit,
    set_clock,
    setup_unit_with_study,
    submit,
    validate_error,
    validate_success,
    verify_item,
    work_item_to_submitted,
)

MANAGER = TEST_USERS["manager_headers"]


def _cascade_scenario():
    """Unit with study (validated 2026-01-15); one overdue-able manual P1 item;
    one MAJOR_NC finding with corrective item; one HIGH incident at
    FINDINGS_SUBMITTED (zero findings); clock advanced to 2026-05-03."""
    unit, study = setup_unit_with_study(validated_at="2026-01-15")
    req = new_personnel("Req", "E-REQ")
    inv = new_personnel("Inv", "E-INV")
    aud = new_personnel("Aud", "E-AUD")
    new_manual_item(unit["id"], req["id"], priority="P1", due_in_days=1, title="old")
    audit = new_audit(unit["id"], aud["id"])
    drive_audit_to_reported(audit, [{"title": "f", "severity": "MAJOR_NC", "assignee_id": req["id"]}])
    incident = new_incident(unit["id"], inv["id"], severity_class="HIGH", occurred_at="2026-04-20")
    drive_incident_to_findings_submitted(incident, findings=[])
    set_clock("2026-05-03T00:00:00Z")
    return unit, study, req, incident


class TestIncidentCloseCascade:
    def test_incident_close_cascade_mutates_study_and_index(self, api):
        """PRD §3.7: "When `feeds_pha` is true and the unit's study stands in
        `CURRENT`, `DUE_SOON`, or `OVERDUE`, closure forces the study into
        `REVALIDATION_REQUIRED` and spawns a `P1` action item with `source_type`
        `PHA_REVALIDATION` sourced to the study, assigned to the investigation's
        `investigator_id`, due thirty days after the clock date; the unit index
        shifts accordingly".
        PRD §2.10: "fifteen points per overdue open action item, plus twenty-five
        if the study is overdue, plus twenty if a revalidation is required, plus
        ten per open high-severity incident, plus five per open major
        nonconformance" — here 15 (overdue manual) + 20 (forced study) + 5
        (MAJOR_NC) = 40.

        Design: Difficulty/transitive_cascade/incident_close_forces_pha_posture_cascade
        """
        unit, study, req, incident = _cascade_scenario()
        assert get_unit(unit["id"])["process_safety_index"] == 30  # 15 + 5 + 10 pre-close

        validate_success(api.close_incident(incident["id"], MANAGER), 200)

        assert get_pha_study(study["id"])["status"] == "REVALIDATION_REQUIRED"
        unit_after = get_unit(unit["id"])
        assert unit_after["open_action_count"] == 3, (
            "manual + corrective + spawned PHA_REVALIDATION item"
        )
        assert unit_after["process_safety_index"] == 40, (
            f"15 overdue + 20 forced + 5 MAJOR_NC must be 40, got {unit_after['process_safety_index']}"
        )
        assert unit_after["psm_posture"] == "RESTRICTED"

    def test_posture_flip_blocks_new_submit(self, api):
        """PRD §3.3: "the unit's posture must be neither `RESTRICTED`
        (`ERR_UNIT_POSTURE_RESTRICTED`) nor `FROZEN` (`ERR_UNIT_POSTURE_FROZEN`)"
        at submission — the cascade flips the unit to RESTRICTED, so a MOC
        classified afterwards cannot be submitted.

        Design: Difficulty/transitive_cascade/incident_close_forces_pha_posture_cascade
        """
        unit, study, req, incident = _cascade_scenario()
        # Gate open before the cascade: index 30 (NORMAL), study CURRENT.
        moc_a = new_draft_moc(unit["id"], req["id"], title="A")
        classify(moc_a["id"], change_class="PERMANENT", severity=1, likelihood=1)
        submitted = submit(moc_a["id"], req["id"])
        assert submitted["status"] == "TECHNICAL_REVIEW"

        validate_success(api.close_incident(incident["id"], MANAGER), 200)
        assert get_unit(unit["id"])["psm_posture"] == "RESTRICTED"

        moc_b = new_draft_moc(unit["id"], req["id"], title="B")
        classify(moc_b["id"], change_class="PERMANENT", severity=1, likelihood=1)
        resp = api.submit_moc(moc_b["id"], make_requester_headers(req["id"]))
        validate_error(resp, ApiErrorId.ERR_UNIT_POSTURE_RESTRICTED.value)
        assert get_moc(moc_b["id"])["status"] == "CLASSIFIED"


class TestIncidentStateMachine:
    def test_incident_submit_findings_before_rca_returns_invalid_state(self, api):
        """PRD §3.7: the investigator "begins root-cause analysis from `OPEN`
        (`ERR_INCIDENT_INVALID_STATE`), moving to `ROOT_CAUSE_ANALYSIS`, and later
        submits findings from that state" — submitting findings directly from
        OPEN is a state error and spawns nothing.

        Design: Corner/state_machines/incident_submit_findings_before_rca_returns_invalid_state
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        inv = new_personnel("Inv", "E-INV")
        req = new_personnel("Req", "E-REQ")
        incident = new_incident(unit["id"], inv["id"], severity_class="MINOR",
                                occurred_at="2026-04-20")

        resp = api.submit_findings(incident["id"],
                                   {"findings": [{"title": "f", "priority": "P3",
                                                  "assignee_id": req["id"]}]},
                                   make_investigator_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INCIDENT_INVALID_STATE.value)
        assert list_unit_action_items(unit["id"]) == []


class TestAuditReporting:
    def test_audit_report_spawns_findings_and_corrective_items(self, api):
        """PRD §3.8: "For each element the system creates an **AuditFinding**
        (bound by `audit_id`) that is created in `OPEN` and immediately moved to
        `ACTION_ASSIGNED` within the same request, spawns a corrective action item
        in `OPEN` with `source_type` `AUDIT` sourced to the finding and priority
        mapped from severity — `MAJOR_NC` to `P1`, `MINOR_NC` to `P2`,
        `OBSERVATION` to `P3` — and sets the finding's `corrective_action_id` to
        the spawned item. The audit's `open_finding_count` is set to the number of
        findings reported, the unit's `open_action_count` grows by the same
        amount, the index is recomputed, and the audit lands in `REPORTED`."

        Design: Corner/endpoints/audit_report_spawns_findings_and_corrective_items
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        aud = new_personnel("Aud", "E-AUD")
        req = new_personnel("Req", "E-REQ")
        audit = new_audit(unit["id"], aud["id"])
        validate_success(api.begin_audit_fieldwork(audit["id"], make_auditor_headers(aud["id"])), 200)

        reported = validate_success(api.report_audit(audit["id"], {"findings": [
            {"title": "f1", "severity": "MAJOR_NC", "assignee_id": req["id"]},
            {"title": "f2", "severity": "MINOR_NC", "assignee_id": req["id"]},
            {"title": "f3", "severity": "OBSERVATION", "assignee_id": req["id"]},
        ]}, make_auditor_headers(aud["id"])), 200)
        assert reported["status"] == "REPORTED"
        assert reported["open_finding_count"] == 3

        findings = list_audit_findings(audit["id"])
        assert len(findings) == 3
        expected_priority = {"f1": "P1", "f2": "P2", "f3": "P3"}
        for finding in findings:
            assert finding["status"] == "ACTION_ASSIGNED"
            assert finding["corrective_action_id"], "corrective_action_id must be set"
            corrective = validate_success(api.get_action_item(finding["corrective_action_id"], MANAGER))
            assert corrective["source_type"] == "AUDIT"
            assert corrective["source_id"] == finding["id"]
            assert corrective["priority"] == expected_priority[finding["title"]], (
                f"severity-to-priority mapping failed for {finding['title']}"
            )
        assert get_unit(unit["id"])["open_action_count"] == 3


class TestAuditCloseGate:
    def _reported_audit_with_one_finding(self):
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        aud = new_personnel("Aud", "E-AUD")
        req = new_personnel("Req", "E-REQ")
        audit = new_audit(unit["id"], aud["id"])
        drive_audit_to_reported(audit, [{"title": "f", "severity": "MINOR_NC",
                                         "assignee_id": req["id"]}])
        corrective_id = list_audit_findings(audit["id"])[0]["corrective_action_id"]
        finding_id = list_audit_findings(audit["id"])[0]["id"]
        return unit, req, audit, finding_id, corrective_id

    def test_audit_close_blocked_until_findings_closed(self, api):
        """PRD §3.8: "A `PsmManager` closes the audit from `REPORTED`
        (`ERR_AUDIT_INVALID_STATE` otherwise) only when `open_finding_count` has
        reached zero (`ERR_AUDIT_OPEN_FINDINGS`), landing it in `CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/audit_close_requires_corrective_closure
        """
        unit, req, audit, finding_id, corrective_id = self._reported_audit_with_one_finding()
        assert get_audit(audit["id"])["open_finding_count"] == 1

        resp = api.close_audit(audit["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_AUDIT_OPEN_FINDINGS.value)
        assert get_audit(audit["id"])["status"] == "REPORTED"

    def test_audit_close_succeeds_after_corrective_verified(self, api):
        """PRD §3.8: "When a corrective action item is verified closed, its
        finding moves from `ACTION_ASSIGNED` to `CLOSED` and the audit's
        `open_finding_count` decrements" — after which the close gate of PRD §3.8
        ("only when `open_finding_count` has reached zero") opens.

        Design: Difficulty/cross_entity_state_dependency/audit_close_requires_corrective_closure
        """
        unit, req, audit, finding_id, corrective_id = self._reported_audit_with_one_finding()

        work_item_to_submitted(corrective_id, req["id"], file_ref="s3://ev/fix.pdf")
        verify_item(corrective_id)

        findings = {f["id"]: f for f in list_audit_findings(audit["id"])}
        assert findings[finding_id]["status"] == "CLOSED", (
            "verifying the corrective item must bubble up to CLOSED on the finding"
        )
        assert get_audit(audit["id"])["open_finding_count"] == 0

        closed = validate_success(api.close_audit(audit["id"], MANAGER), 200)
        assert closed["status"] == "CLOSED"


class TestAuditWindowBuffer:
    def test_audit_window_buffered_gap_allows_clear_window(self, api):
        """PRD §3.8: "the new window must stand at least fourteen days clear of
        every other audit in `SCHEDULED`, `FIELDWORK`, or `REPORTED` on the same
        unit — a window that comes within fourteen days of a neighbor on either
        side is rejected with `ERR_AUDIT_WINDOW_CONFLICT`." Starting 2026-08-20
        leaves fourteen clear days after the neighbor ending 2026-08-05.

        Design: Difficulty/resource_temporal_overlap/audit_window_buffered_gap
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        aud = new_personnel("Aud", "E-AUD")
        new_audit(unit["id"], aud["id"], window_start="2026-08-01", window_end="2026-08-05",
                  title="AU1")
        created = validate_success(api.create_audit(
            unit["id"],
            create_audit_payload(aud["id"], title="AU2",
                                 field_window_start="2026-08-20", field_window_end="2026-08-25"),
            MANAGER), 201)
        assert created["status"] == "SCHEDULED"

    def test_audit_window_buffered_gap_rejects_inside_buffer(self, api):
        """PRD §3.8: "a window that comes within fourteen days of a neighbor on
        either side is rejected with `ERR_AUDIT_WINDOW_CONFLICT`" — starting
        2026-08-19 leaves only thirteen clear days after the neighbor ending
        2026-08-05.

        Design: Difficulty/resource_temporal_overlap/audit_window_buffered_gap
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        aud = new_personnel("Aud", "E-AUD")
        new_audit(unit["id"], aud["id"], window_start="2026-08-01", window_end="2026-08-05",
                  title="AU1")
        resp = api.create_audit(
            unit["id"],
            create_audit_payload(aud["id"], title="AU3",
                                 field_window_start="2026-08-19", field_window_end="2026-08-22"),
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_CONFLICT.value)
