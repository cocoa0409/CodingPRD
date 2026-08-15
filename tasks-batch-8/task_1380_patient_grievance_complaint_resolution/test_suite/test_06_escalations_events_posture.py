"""Quality/risk escalation fork-join, adjudication cascades, reportable
events and their filing deadlines, and unit posture restoration."""
from test_helpers import (
    ApiErrorId,
    assign_investigator,
    classify_case,
    create_case,
    create_escalation,
    create_reportable_event_payload,
    create_staff,
    create_unit,
    get_success_data,
    make_director_headers,
    make_qro_headers,
    set_clock,
    setup_escalation_at_reviews_complete,
    setup_letter_in_review,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


class TestEscalationForkJoin:
    def _setup_both_track_in_review(self, api):
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("Surgery 2", "SURGICAL")
        q1 = create_staff("Quinn One", ["QRO"])
        q2 = create_staff("Quinn Two", ["QRO"])
        case = create_case(unit["id"], patient_ref="P-5003",
                           received_at="2026-08-03T09:00:00.000Z", channel="LETTER",
                           description="Surgical consent concern",
                           grievance_category="CARE_QUALITY")
        esc = create_escalation(case["id"], q1["id"], "CARE_CONCERN", "BOTH")
        get_success_data(api.triage_escalation(
            esc["id"], {"review_track": "BOTH"}, make_qro_headers(q1["id"])))
        mid = get_success_data(api.complete_escalation_review(
            esc["id"], {"review_branch": "COMPLIANCE"}, make_qro_headers(q1["id"])))
        return case, esc, q1, q2, mid

    def test_premature_adjudication_rejected_before_join(self, api):
        """PRD §3.6: "Adjudication is the terminal act, open to a
        `QualityRiskOfficer` once the escalation stands `REVIEWS_COMPLETE`
        (`ERR_ESCALATION_INVALID_STATE` before that)." and "The join rule
        advances the escalation to `REVIEWS_COMPLETE` exactly when the track's
        required branches are done: a `COMPLIANCE` track completes when the
        compliance flag is set, a `SAFETY` track when the safety flag is set,
        and `BOTH` only when both flags stand."

        Design: Difficulty/non_linear_state_machine/escalation_fork_join_requires_both_reviews
        """
        _case, esc, _q1, q2, mid = self._setup_both_track_in_review(api)
        assert mid["status"] == "IN_REVIEW", (
            "track BOTH: one branch done, the join has not fired")
        assert mid["compliance_review_done"] is True

        resp = api.adjudicate_escalation(
            esc["id"], {"outcome": "SUBSTANTIATED"}, make_qro_headers(q2["id"]))
        validate_error(resp, ApiErrorId.ERR_ESCALATION_INVALID_STATE)

    def test_join_fires_when_both_branches_done_then_adjudicate(self, api):
        """PRD §3.6: "The join rule advances the escalation to
        `REVIEWS_COMPLETE` exactly when the track's required branches are done:
        a `COMPLIANCE` track completes when the compliance flag is set, a
        `SAFETY` track when the safety flag is set, and `BOTH` only when both
        flags stand." and "The payload's `outcome` selects between a
        substantiated and an unsubstantiated finding, and an optional
        `outcome_note` records the rationale."

        Design: Difficulty/non_linear_state_machine/escalation_fork_join_requires_both_reviews
        """
        _case, esc, q1, q2, _mid = self._setup_both_track_in_review(api)
        joined = get_success_data(api.complete_escalation_review(
            esc["id"], {"review_branch": "SAFETY"}, make_qro_headers(q1["id"])))
        assert joined["status"] == "REVIEWS_COMPLETE", (
            "join fires only when BOTH branches are done")

        final = validate_success(api.adjudicate_escalation(
            esc["id"], {"outcome": "SUBSTANTIATED",
                        "outcome_note": "Both reviews concur"},
            make_qro_headers(q2["id"])))
        assert final["status"] == "ADJUDICATED_SUBSTANTIATED"

    def test_sod_escalation_self_adjudicate(self, api):
        """PRD §3.6: "The segregation rule of §2.10 applies: the adjudicator
        must differ from `filed_by_id`, except when the filer is 'system'
        (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/validations/sod_escalation_self_adjudicate
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("Surgery", "SURGICAL")
        q1 = create_staff("Quinn One", ["QRO"])
        case = create_case(unit["id"], patient_ref="P-0305",
                           received_at="2026-08-03T09:00:00.000Z", channel="LETTER",
                           description="Consent concern",
                           grievance_category="CARE_QUALITY")
        esc = setup_escalation_at_reviews_complete(case["id"], q1["id"],
                                                   "CARE_CONCERN", "COMPLIANCE")
        assert esc["status"] == "REVIEWS_COMPLETE"
        resp = api.adjudicate_escalation(
            esc["id"], {"outcome": "UNSUBSTANTIATED"}, make_qro_headers(q1["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestSubstantiatedEscalationCascade:
    def _setup_and_adjudicate(self, api):
        """STANDARD grievance (received 2026-08-01T09:00:00Z, due
        2026-08-31T09:00:00Z) sitting ASSIGNED while past due; CARE_CONCERN
        escalation driven to REVIEWS_COMPLETE, then adjudicated SUBSTANTIATED
        by a second officer at 2026-09-10T12:00:00Z."""
        set_clock("2026-08-01T10:00:00.000Z")
        unit = create_unit("Oncology", "INPATIENT")
        inv = create_staff("Ivy Investigator", ["INVESTIGATOR"])
        director = create_staff("Dana Director", ["DIRECTOR"])
        q1 = create_staff("Quinn One", ["QRO"])
        q2 = create_staff("Quinn Two", ["QRO"])
        case = create_case(unit["id"], patient_ref="P-6002",
                           received_at="2026-08-01T09:00:00.000Z", channel="EMAIL",
                           description="Chemo scheduling failure",
                           grievance_category="CARE_QUALITY")
        classify_case(case["id"], "GRIEVANCE")
        assign_investigator(case["id"], director["id"], inv["id"])
        set_clock("2026-09-10T12:00:00.000Z")
        esc = setup_escalation_at_reviews_complete(case["id"], q1["id"],
                                                   "CARE_CONCERN", "COMPLIANCE")
        adjudicated = validate_success(api.adjudicate_escalation(
            esc["id"], {"outcome": "SUBSTANTIATED",
                        "outcome_note": "Care concern confirmed"},
            make_qro_headers(q2["id"])))
        return unit, case, esc, q2, adjudicated

    def test_adjudication_sets_cosign_and_breach_without_expedite(self, api):
        """PRD §3.6: "A substantiated one — `ADJUDICATED_SUBSTANTIATED` — fires
        a three-link cascade. First, the case's `requires_qro_cosign` is
        recomputed and becomes true. Second, the regulatory dues are expedited:
        when seven calendar days after `adjudicated_at` falls earlier than the
        current `response_due_calendar_at`, the calendar due is pulled in to
        that earlier instant, and the business due is likewise pulled in to
        seven business days after `adjudicated_at` when that is earlier. Third,
        when the recomputed calendar due already lies in the past and the case
        is unresolved, the case's regulatory clock reads `RESPONSE_BREACH`"

        Design: Difficulty/transitive_cascade/substantiated_escalation_breach_autoevent_cascade
        """
        _unit, case, _esc, q2, adjudicated = self._setup_and_adjudicate(api)
        assert adjudicated["status"] == "ADJUDICATED_SUBSTANTIATED"
        assert adjudicated["adjudicated_at"] == "2026-09-10T12:00:00.000Z"

        case_after = get_success_data(api.get_case(case["id"],
                                                   make_qro_headers(q2["id"])))
        assert case_after["requires_qro_cosign"] is True, (
            "cosign recomputed from the substantiated escalation")
        timeline = get_success_data(api.get_case_timeline(
            case["id"], make_qro_headers(q2["id"])))
        assert timeline["response_due_calendar_at"] == "2026-08-31T09:00:00.000Z", (
            "expedite candidate 2026-09-17T12:00:00Z is later than the current "
            "due, so the due is unchanged")
        assert timeline["regulatory_clock_status"] == "RESPONSE_BREACH", (
            "the due already lies in the past and the case is unresolved")

    def test_substantiation_auto_creates_reportable_event(self, api):
        """PRD §3.6: "Third, when the recomputed calendar due already lies in
        the past and the case is unresolved, the case's regulatory clock reads
        `RESPONSE_BREACH` and the system files a reportable event on the case —
        `trigger_reason` `SUBSTANTIATED_CARE_CONCERN`, `escalation_id` pointing
        at this escalation, status `PENDING_FILING`, and a filing deadline five
        business days after `adjudicated_at` (§3.7)."

        Design: Difficulty/transitive_cascade/substantiated_escalation_breach_autoevent_cascade
        """
        _unit, case, esc, q2, _adjudicated = self._setup_and_adjudicate(api)
        events, _ = validate_paginated(api.list_reportable_events(
            make_qro_headers(q2["id"]), params={"case_id": case["id"]}))
        assert len(events) == 1
        event = events[0]
        assert event["status"] == "PENDING_FILING"
        assert event["trigger_reason"] == "SUBSTANTIATED_CARE_CONCERN"
        assert event["escalation_id"] == esc["id"]
        assert event["filing_deadline_at"] == "2026-09-17T12:00:00.000Z", (
            "five business days after 2026-09-10T12:00:00Z: Sep 11,14,15,16,17")


class TestLetterApprovalEscalationGate:
    def _setup_letter_blocked_by_escalation(self, api):
        base = setup_letter_in_review(
            unit_name="Cardiology", unit_category="INPATIENT", patient_ref="P-9001",
            description="Consent process concern", grievance_category="CARE_QUALITY")
        q1 = create_staff("Quinn One", ["QRO"])
        q2 = create_staff("Quinn Two", ["QRO"])
        esc = create_escalation(base.case["id"], q1["id"], "CARE_CONCERN",
                                "COMPLIANCE")
        return base, esc, q1, q2

    def test_letter_approval_blocked_while_escalation_open(self, api):
        """PRD §3.4: "and no escalation for the case may stand in `FILED`,
        `IN_REVIEW`, or `REVIEWS_COMPLETE`
        (`ERR_OPEN_ESCALATION_BLOCKS_APPROVAL`)."

        Design: Difficulty/cross_entity_state_dependency/letter_approval_gated_by_open_escalation
        """
        base, esc, _q1, _q2 = self._setup_letter_blocked_by_escalation(api)
        assert esc["status"] == "FILED"
        resp = api.approve_letter(base.letter["id"],
                                  make_director_headers(base.director["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_ESCALATION_BLOCKS_APPROVAL)

    def test_letter_approval_freed_by_terminal_adjudication(self, api):
        """PRD §3.4: "and no escalation for the case may stand in `FILED`,
        `IN_REVIEW`, or `REVIEWS_COMPLETE`
        (`ERR_OPEN_ESCALATION_BLOCKS_APPROVAL`). Approval stamps
        `approved_by_id`, moves the letter to `APPROVED`, and the case
        `RESPONSE_REVIEW` → `PENDING_CLOSURE`."

        Design: Difficulty/cross_entity_state_dependency/letter_approval_gated_by_open_escalation
        """
        base, esc, q1, q2 = self._setup_letter_blocked_by_escalation(api)
        get_success_data(api.triage_escalation(
            esc["id"], {"review_track": "COMPLIANCE"}, make_qro_headers(q1["id"])))
        get_success_data(api.complete_escalation_review(
            esc["id"], {"review_branch": "COMPLIANCE"}, make_qro_headers(q1["id"])))
        terminal = validate_success(api.adjudicate_escalation(
            esc["id"], {"outcome": "UNSUBSTANTIATED",
                        "outcome_note": "No care defect found"},
            make_qro_headers(q2["id"])))
        assert terminal["status"] == "ADJUDICATED_UNSUBSTANTIATED"

        approved = validate_success(api.approve_letter(
            base.letter["id"], make_director_headers(base.director["id"])))
        assert approved["status"] == "APPROVED", (
            "the gate clears once the escalation reaches a terminal adjudication")


class TestReportableEvents:
    def test_event_escalation_from_wrong_case_rejected(self, api):
        """PRD §3.7: "An `escalation_id` reference is required for every
        trigger except `ALLEGED_ABUSE`; when supplied, the referenced
        escalation must belong to the case named in the path and must stand
        `ADJUDICATED_SUBSTANTIATED` — violations are rejected with
        `ERR_CROSS_REFERENCE_MISMATCH`."

        Design: Corner/validations/event_escalation_from_wrong_case_rejected
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("Surgery", "SURGICAL")
        q1 = create_staff("Quinn Risk", ["QRO"])
        c1 = create_case(unit["id"], patient_ref="P-0310",
                         received_at="2026-08-03T09:00:00.000Z",
                         description="Case one", grievance_category="CARE_QUALITY")
        c2 = create_case(unit["id"], patient_ref="P-0311", channel="EMAIL",
                         received_at="2026-08-03T09:00:00.000Z",
                         description="Case two", grievance_category="CARE_QUALITY")
        esc = create_escalation(c1["id"], q1["id"], "CARE_CONCERN", "COMPLIANCE")

        resp = api.create_reportable_event(
            c2["id"],
            create_reportable_event_payload(
                authority_code="STATE_HEALTH_DEPT",
                trigger_reason="SUBSTANTIATED_CARE_CONCERN",
                escalation_id=esc["id"]),
            make_qro_headers(q1["id"]))
        validate_error(resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH)

    def test_event_trigger_abuse_flag_mismatch_rejected(self, api):
        """PRD §3.7: "An `ALLEGED_ABUSE` event is supported only on a case
        whose `alleged_abuse_flag` is set; otherwise the registration fails
        with `ERR_EVENT_TRIGGER_NOT_SUPPORTED`."

        Design: Corner/validations/event_trigger_abuse_flag_mismatch_rejected
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("Peds", "INPATIENT")
        q1 = create_staff("Quinn Risk", ["QRO"])
        case = create_case(unit["id"], patient_ref="P-0312",
                           received_at="2026-08-03T09:00:00.000Z",
                           description="Ordinary concern", grievance_category="OTHER")
        resp = api.create_reportable_event(
            case["id"],
            create_reportable_event_payload(authority_code="STATE_HEALTH_DEPT",
                                            trigger_reason="ALLEGED_ABUSE"),
            make_qro_headers(q1["id"]))
        validate_error(resp, ApiErrorId.ERR_EVENT_TRIGGER_NOT_SUPPORTED)

    def test_filing_deadline_abuse_48h_boundary(self, api):
        """PRD §3.7: "an alleged-abuse event must be filed within exactly
        forty-eight hours of creation with no calendar adjustment, while any
        other trigger allows five business days on the §2.8 arithmetic." and
        "Filing on or before the deadline — equality counts as on time — moves
        the event to `FILED` with `filed_at` stamped and `late_filing` false.
        Filing even one second later moves it to `LATE_FILED` instead:
        `filed_at` is stamped, `late_filing` reads true, and the late filing
        cascades onto the unit. The unit's `late_filed_event_count` rises by
        one; a unit in `STANDARD` posture flips to `RESTRICTED`"

        Design: Corner/calculations/filing_deadline_abuse_48h_boundary
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("Peds", "INPATIENT")
        q1 = create_staff("Quinn Risk", ["QRO"])
        case = create_case(unit["id"], patient_ref="P-0205",
                           received_at="2026-08-03T09:00:00.000Z", channel="IN_PERSON",
                           description="Alleged rough handling",
                           grievance_category="RIGHTS_ABUSE",
                           alleged_abuse_flag=True)
        qro = make_qro_headers(q1["id"])
        e1 = validate_success(api.create_reportable_event(
            case["id"], create_reportable_event_payload(
                authority_code="STATE_HEALTH_DEPT", trigger_reason="ALLEGED_ABUSE"),
            qro), expected_status=201)
        e2 = validate_success(api.create_reportable_event(
            case["id"], create_reportable_event_payload(
                authority_code="CMS_REGIONAL", trigger_reason="ALLEGED_ABUSE"),
            qro), expected_status=201)
        assert e1["filing_deadline_at"] == "2026-08-05T10:00:00.000Z", (
            "created_at + exactly 48 hours")

        set_clock("2026-08-05T10:00:00.000Z")
        on_time = validate_success(api.file_reportable_event(e1["id"], qro))
        assert on_time["status"] == "FILED"
        assert on_time["late_filing"] is False, (
            "filing exactly at the deadline is on time")

        set_clock("2026-08-05T10:00:01.000Z")
        late = validate_success(api.file_reportable_event(e2["id"], qro))
        assert late["status"] == "LATE_FILED"
        assert late["late_filing"] is True, "one second past the deadline"

        unit_after = get_success_data(api.get_unit(unit["id"], qro))
        assert unit_after["posture"] == "RESTRICTED"
        assert unit_after["late_filed_event_count"] == 1

    def test_unit_restore_blocked_by_unacknowledged_late_event(self, api):
        """PRD §3.7: "Restoration is earned, not declared: moving the unit back
        to `STANDARD` is blocked with `ERR_UNIT_HAS_UNRESOLVED_LATE_EVENTS`
        until every late-filed event on the unit's cases has been
        acknowledged." and "Acknowledgment belongs to the `ComplianceAuditor`,
        who records the authority's confirmation — optionally carrying an
        `authority_reference` — moving the event from `FILED` or `LATE_FILED`
        to `ACKNOWLEDGED`."

        Design: Corner/validations/unit_restore_blocked_by_unacknowledged_late_event
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("Peds", "INPATIENT")
        q1 = create_staff("Quinn Risk", ["QRO"])
        director = create_staff("Dana Director", ["DIRECTOR"])
        case = create_case(unit["id"], patient_ref="P-0321",
                           received_at="2026-08-03T09:00:00.000Z", channel="IN_PERSON",
                           description="Alleged rough handling",
                           grievance_category="RIGHTS_ABUSE",
                           alleged_abuse_flag=True)
        qro = make_qro_headers(q1["id"])
        event = validate_success(api.create_reportable_event(
            case["id"], create_reportable_event_payload(
                authority_code="STATE_HEALTH_DEPT", trigger_reason="ALLEGED_ABUSE"),
            qro), expected_status=201)
        set_clock("2026-08-05T10:00:01.000Z")
        late = validate_success(api.file_reportable_event(event["id"], qro))
        assert late["status"] == "LATE_FILED"

        blocked = api.patch_unit(unit["id"], {"posture": "STANDARD"},
                                 make_director_headers(director["id"]))
        validate_error(blocked, ApiErrorId.ERR_UNIT_HAS_UNRESOLVED_LATE_EVENTS)

        acked = validate_success(api.acknowledge_reportable_event(
            event["id"], {"authority_reference": "SD-2026-114"}, AUDITOR))
        assert acked["status"] == "ACKNOWLEDGED"
        restored = validate_success(api.patch_unit(
            unit["id"], {"posture": "STANDARD"},
            make_director_headers(director["id"])))
        assert restored["posture"] == "STANDARD"
