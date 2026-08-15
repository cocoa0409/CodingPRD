"""Issues: repeat-finding detection, dual-variant risk scoring, overdue
escalation, OCC on issue filing, and role-vs-state ordering (PRD §2.7, §2.9,
§3.5, §3.8)."""
from test_helpers import (
    BOARD,
    RAM,
    ApiErrorId,
    assert_issue,
    begin_fieldwork,
    create_agency,
    create_examination,
    create_first_day_item,
    create_meeting,
    create_officer,
    create_reviewer,
    deliver_findings,
    file_issue,
    finalize_meeting,
    get_exam,
    get_issue,
    issue_first_day_letter,
    make_remediation_owner_headers,
    set_logical_clock,
    setup_closed_issue_for_repeat_lineage,
    setup_exam_findings_delivered,
    setup_exam_first_day_issued,
    setup_exam_remediation,
    setup_issue_closed,
    validate_error,
    validate_paginated,
    validate_success,
    waive_item,
)


def _setup_closed_and_overdue_pair(api):
    """One exam carrying a CLOSED HIGH issue and an OVERDUE MODERATE issue.

    Forward score: MODERATE 5,000 + min(10 days * 25, 5,000) = 5,250.
    Historical score: HIGH 7,500 + MODERATE 5,000 = 12,500.
    """
    ctx = setup_issue_closed(
        agency_overrides={"agency_code": "OCC", "repeat_finding_multiplier_bp": 20000},
        exam_overrides={
            "exam_cycle_code": "2026-Q3-SAFETY", "exam_type": "SAFETY_SOUNDNESS",
            "scheduled_start_date": "2026-07-06T00:00:00Z",
            "scheduled_end_date": "2026-07-31T00:00:00Z",
        },
        issue_overrides={
            "issue_ref": "MRA-2026-01", "classification": "MRA",
            "severity": "HIGH", "due_date": "2026-08-01T00:00:00Z",
        },
    )
    issue_b = file_issue(
        ctx["exam"]["id"], issue_ref="MRA-2026-02", classification="MRA",
        severity="MODERATE", due_date="2026-08-04T00:00:00Z")
    set_logical_clock("2026-08-14T00:00:00Z")
    ctx["issue_b"] = issue_b
    return ctx


class TestDualVariantRiskScoring:
    def test_forward_looking_excludes_closed_and_adds_overdue_surcharge(self, api):
        """PRD §3.5: "Every issue in the scoring set contributes a base severity
        weight in basis points: `LOW` contributes 2,500, `MODERATE` 5,000,
        `HIGH` 7,500, and `CRITICAL` 10,000."
        PRD §3.5: "The forward-looking variant — the one stored on the
        examination and snapshotted into board reports while the examination is
        in `REMEDIATION` or any earlier stage — sums contributions over issues
        standing `OPEN`, `REMEDIATION_PLANNED`, `IN_PROGRESS`, `OVERDUE`, or
        `VALIDATION_SUBMITTED`, deliberately excluding `CLOSED` issues, and adds
        a per-issue surcharge for each `OVERDUE` issue of 25 basis points per
        whole day overdue, the surcharge capped at 5,000 basis points per
        issue."

        Issue A (HIGH) is CLOSED and drops out of the forward set; issue B
        (MODERATE) stands OVERDUE 10 whole days, adding 250 bp of surcharge:
        5,000 + 250 = 5,250.

        Design: Difficulty/dual_variant_calc/repeat_finding_risk_forward_vs_historical_variants
        """
        ctx = _setup_closed_and_overdue_pair(api)
        assert get_issue(ctx["issue_b"]["id"])["status"] == "OVERDUE"
        exam = get_exam(ctx["exam"]["id"])
        assert exam["repeat_finding_risk_score_bp"] == 5250, (
            "forward-looking: 5,000 base + min(10*25, 5,000) surcharge; "
            "CLOSED issue excluded"
        )

    def test_historical_includes_closed_and_omits_surcharge(self, api):
        """PRD §3.5: "The historical variant — used by the cross-exam trend read
        of §3.9 — sums only issues standing `CLOSED`, `OVERDUE`, or
        `VALIDATION_SUBMITTED`, capturing resolved exposure, and adds no overdue
        surcharge: a closed issue contributes its final-severity base, with the
        repeat multiplier where applicable, and nothing more."
        PRD §3.9: "The historical variant of the risk score is exposed per
        examination as `historical_risk_bp` together with the
        `contributing_issue_ids` that fed it."

        Historical set = {CLOSED HIGH 7,500, OVERDUE MODERATE 5,000} with no
        surcharge: 12,500 — demonstrably different from the forward value.

        Design: Difficulty/dual_variant_calc/repeat_finding_risk_forward_vs_historical_variants
        """
        ctx = _setup_closed_and_overdue_pair(api)
        history = validate_success(
            api.get_risk_history(ctx["exam"]["id"], RAM))
        assert history["historical_risk_bp"] == 12500
        assert set(history["contributing_issue_ids"]) == {
            ctx["issue"]["id"], ctx["issue_b"]["id"],
        }
        exam = get_exam(ctx["exam"]["id"])
        assert exam["repeat_finding_risk_score_bp"] != history["historical_risk_bp"]


def _setup_multi_input_scoring(api):
    """Exam carrying a CRITICAL fresh issue (9 days overdue) and a MODERATE
    repeat issue (5 days overdue) under a 3.0x repeat multiplier agency.

    C: 10,000 + 9*25 = 10,225.  D: 5,000 * 30,000/10,000 + 5*25 = 15,125.
    Forward total: 25,350.
    """
    agency = create_agency(
        agency_code="FDIC", escalation_threshold_days=30,
        repeat_finding_multiplier_bp=30000)
    exam = create_examination(
        agency["id"], exam_cycle_code="X", exam_type="IT",
        scheduled_start_date="2026-07-06T00:00:00Z",
        scheduled_end_date="2026-07-10T00:00:00Z")
    item = create_first_day_item(exam["id"], due_date="2026-07-15T00:00:00Z")
    issue_first_day_letter(exam["id"])
    waive_item(item["id"])
    begin_fieldwork(exam["id"])
    meeting = create_meeting(exam["id"], meeting_date="2026-07-08T10:00:00Z")
    finalize_meeting(meeting["id"])
    deliver_findings(exam["id"])

    officer = create_officer()
    reviewer = create_reviewer(certification_level="L3")

    # Repeat lineage: a CLOSED issue with the same normalized stem on a prior
    # examination of the same agency.
    setup_closed_issue_for_repeat_lineage(
        agency["id"], "MRA-LEGACY", officer["id"], reviewer["id"])

    issue_c = file_issue(
        exam["id"], issue_ref="MRIA-1", classification="MRIA",
        severity="CRITICAL", due_date="2026-08-05T00:00:00Z")
    issue_d = file_issue(
        exam["id"], issue_ref="MRA-LEGACY-R1", classification="MRA",
        severity="MODERATE", due_date="2026-08-09T00:00:00Z")
    set_logical_clock("2026-08-14T00:00:00Z")
    return {"agency": agency, "exam": exam, "issue_c": issue_c, "issue_d": issue_d}


class TestMultiInputTieredScoring:
    def test_repeat_multiplier_and_overdue_surcharge_compose(self, api):
        """PRD §3.5: "Every issue in the scoring set contributes a base severity
        weight in basis points: `LOW` contributes 2,500, `MODERATE` 5,000,
        `HIGH` 7,500, and `CRITICAL` 10,000. When the issue's
        `is_repeat_finding` flag is true, that base is multiplied by the
        agency's `repeat_finding_multiplier_bp` divided by 10,000, with the
        product rounded half up to a whole basis point before it enters the
        sum."
        PRD §3.5: "The forward-looking variant — the one stored on the
        examination and snapshotted into board reports while the examination is
        in `REMEDIATION` or any earlier stage — sums contributions over issues
        standing `OPEN`, `REMEDIATION_PLANNED`, `IN_PROGRESS`, `OVERDUE`, or
        `VALIDATION_SUBMITTED`, deliberately excluding `CLOSED` issues, and adds
        a per-issue surcharge for each `OVERDUE` issue of 25 basis points per
        whole day overdue, the surcharge capped at 5,000 basis points per
        issue."

        C contributes 10,000 + min(9*25, 5,000) = 10,225; D contributes
        round-half-up(5,000 * 30,000 / 10,000) + min(5*25, 5,000) = 15,125;
        the examination score is 25,350 bp.

        Design: Difficulty/combinatorial_formula/repeat_finding_risk_multi_input_tiered_scoring
        """
        ctx = _setup_multi_input_scoring(api)
        assert get_issue(ctx["issue_c"]["id"])["status"] == "OVERDUE"
        assert get_issue(ctx["issue_d"]["id"])["status"] == "OVERDUE"
        exam = get_exam(ctx["exam"]["id"])
        assert exam["repeat_finding_risk_score_bp"] == 25350, (
            "10,225 (CRITICAL + 9 days) + 15,125 (repeat MODERATE + 5 days)"
        )

    def test_repeat_finding_detected_via_normalized_ref_stem(self, api):
        """PRD §3.5: "The `issue_ref` is normalized by stripping whitespace,
        uppercasing, and dropping any trailing revision suffix of the form "-R"
        followed by digits — so MRA-2026-07-R2 normalizes to MRA-2026-07. The
        new issue's `is_repeat_finding` is true if and only if there exists a
        different, already `CLOSED` issue, on any examination belonging to the
        same agency as the new issue's examination, whose normalized reference
        equals the new issue's normalized reference and whose `closed_at` falls
        strictly before the new issue's `created_at`."

        Filing MRA-LEGACY-R1 after MRA-LEGACY closed under the same agency sets
        is_repeat_finding on the new issue.

        Design: Difficulty/combinatorial_formula/repeat_finding_risk_multi_input_tiered_scoring
        """
        ctx = _setup_multi_input_scoring(api)
        issue_d = get_issue(ctx["issue_d"]["id"])
        assert_issue(issue_d)
        assert issue_d["is_repeat_finding"] is True
        issue_c = get_issue(ctx["issue_c"]["id"])
        assert issue_c["is_repeat_finding"] is False


class TestOverdueEscalationThreshold:
    def test_frozen_at_exactly_threshold_days_overdue(self, api):
        """PRD §3.8: "When the clock advances past an issue's `due_date` while
        the issue still stands `OPEN`, `REMEDIATION_PLANNED`, or `IN_PROGRESS`,
        the issue transitions automatically to `OVERDUE`"
        PRD §3.8: "if the issue's `is_repeat_finding` is true, or if the whole
        days it has been overdue have reached the agency's
        `escalation_threshold_days` — a span exactly equal to the threshold
        qualifies — the issue's `escalated_to_board` flag is set true and stays
        set even if work later resumes."
        PRD §3.8: "The examination is `FROZEN` when the overdue-item count
        reaches three (exactly three qualifies) or when the longest
        issue-overdue stretch reaches the escalation threshold"

        The issue's due date 2026-07-15 sits exactly 30 whole days behind the
        logical clock 2026-08-14; the agency threshold is 30, and a span exactly
        equal to the threshold qualifies.

        Design: Corner/calculations/posture_frozen_at_exactly_threshold_days_overdue_issue
        """
        ctx = setup_exam_remediation(
            agency_overrides={"agency_code": "TH", "escalation_threshold_days": 30},
            exam_overrides={
                "exam_cycle_code": "TH",
                "scheduled_start_date": "2026-06-01T00:00:00Z",
                "scheduled_end_date": "2026-06-05T00:00:00Z",
            },
            item_due_date="2026-06-10T00:00:00Z",
            issue_overrides={"issue_ref": "MRA-TH", "due_date": "2026-07-15T00:00:00Z"},
        )
        set_logical_clock("2026-08-14T00:00:00Z")
        issue = get_issue(ctx["issue"]["id"])
        assert issue["status"] == "OVERDUE"
        assert issue["escalated_to_board"] is True, (
            "30 days overdue reaches the threshold of 30 (inclusive)"
        )
        exam = get_exam(ctx["exam"]["id"])
        assert exam["posture"] == "FROZEN"


class TestIssueFilingOCC:
    def test_stale_examination_version_rejected_on_issue_create(self, api):
        """PRD §2.7: "filing an issue against an examination
        (`POST /regulatory-exams/examinations/{id}/issues`) requires the request
        to carry `expected_examination_version`, the examination `version` the
        client last observed"
        PRD §2.7: "In all three cases the expected-version field is
        non-optional, and a mismatch with the parent entity's current `version`
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        The first filing advances the examination version; the second filing
        carries the now-stale observed version.

        Design: Corner/endpoints/occ_stale_version_on_issue_create
        """
        ctx = setup_exam_findings_delivered()
        observed_v = get_exam(ctx["exam"]["id"])["version"]
        first = file_issue(ctx["exam"]["id"], issue_ref="MRA-OC-1")
        assert_issue(first)
        resp = api.create_issue(
            ctx["exam"]["id"],
            {
                "issue_ref": "MRA-OC-2", "classification": "MRA",
                "severity": "HIGH", "due_date": "2026-09-01T00:00:00Z",
                "expected_examination_version": observed_v,
            },
            RAM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_issues_listed_per_examination(self, api):
        """PRD §4: "| GET | /regulatory-exams/examinations/{id}/issues | List issues for an examination | All roles |"

        Design: Corner/endpoints/reverse_reachability_fk_list_issues_by_exam
        """
        ctx = setup_exam_remediation()
        data, meta = validate_paginated(
            api.list_issues(ctx["exam"]["id"], RAM))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == ctx["issue"]["id"]


class TestAuthBeatsStateOrdering:
    def test_unauthorized_role_close_on_scheduled_exam(self, api):
        """PRD §2.9: "When several checks could apply to one request, the server
        evaluates them in a single fixed order, and the first failing check
        determines the error response."
        PRD §2.9: "2. **Authorization.** The caller's role is permitted on this
        endpoint per §4 — otherwise `ERR_UNAUTHORIZED` (HTTP 403). Applies to
        every endpoint."
        PRD §2.9: "4. **State-machine preconditions.** The target resource's
        current state permits the requested transition — otherwise
        `ERR_INVALID_STATE` (HTTP 409). Applies to all action endpoints."

        A RemediationOwner calling /close on a SCHEDULED exam fails both the
        role check and the state precondition; authorization fires first.

        Design: Difficulty/priority_pair_validation_conflict/auth_beats_state_conflict_on_closed_exam_action
        """
        agency = create_agency(agency_code="CFPB2")
        exam = create_examination(agency["id"], exam_cycle_code="T",
                                  exam_type="TRUST")
        officer = create_officer()
        owner_headers = make_remediation_owner_headers(officer["id"])
        resp = api.close_examination(exam["id"], owner_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_unauthorized_role_begin_fieldwork_with_pending_item(self, api):
        """PRD §2.9: "When several checks could apply to one request, the server
        evaluates them in a single fixed order, and the first failing check
        determines the error response."
        PRD §4: "| POST | /regulatory-exams/examinations/{id}/begin-fieldwork | Begin fieldwork (FIRST_DAY_ISSUED → FIELDWORK) | RegulatoryAffairsManager |"

        A BoardReporter calling begin-fieldwork on a FIRST_DAY_ISSUED exam with
        a still-PENDING item is rejected for the role, not the state.

        Design: Difficulty/priority_pair_validation_conflict/auth_beats_state_conflict_on_closed_exam_action
        """
        ctx = setup_exam_first_day_issued()
        resp = api.begin_fieldwork(ctx["exam"]["id"], BOARD)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
