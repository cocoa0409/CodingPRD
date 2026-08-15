"""Inspection findings: remediation loop, adjudication, branch risk score,
and posture escalation (PRD §3.2).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_finding,
    adjudicate_finding,
    assert_branch_risk_invariants,
    create_finding_payload,
    get_branch,
    make_branch,
    make_registered_rep_headers,
    make_rep,
    remediate_finding,
    schedule_and_start_inspection,
    set_clock,
    setup_in_progress_inspection,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
PRINCIPAL_A = TEST_USERS["principal_a_headers"]
ANY = TEST_USERS["any_headers"]


# ─── finding state guards ─────────────────────────────

def test_adjudicate_open_finding_rejected(api, any_headers):
    """PRD §3.2: "A principal then adjudicates a `REMEDIATION_SUBMITTED`
    finding with a `decision` of `VERIFY` or `REOPEN`; adjudicating from any
    other state is likewise `ERR_FINDING_INVALID_STATE`."

    Design: Corner/state_machines/adjudicate_open_finding_rejected
    """
    _branch, inspection = setup_in_progress_inspection(region="W")
    finding = add_finding(inspection["id"], severity="LOW", description="x")
    res = api.adjudicate_finding(finding["id"], {"decision": "VERIFY"}, PRINCIPAL_A)
    validate_error(res, ApiErrorId.ERR_FINDING_INVALID_STATE)
    still_open = validate_success(api.get_finding(finding["id"], any_headers), 200)
    assert still_open["status"] == "OPEN"


def test_remediate_verified_finding_rejected(api, any_headers):
    """PRD §3.2: "An analyst may submit remediation on a finding in `OPEN` or
    `OVERDUE`, moving it to `REMEDIATION_SUBMITTED` and recording the
    payload's `remediation_note`; invoking remediation from any other state
    is rejected with `ERR_FINDING_INVALID_STATE`." VERIFIED_CLOSED is
    terminal, so remediation there is rejected.

    Design: Corner/errors/finding_state_error_on_remediate_verified
    """
    _branch, inspection = setup_in_progress_inspection(region="W")
    finding = add_finding(inspection["id"], severity="LOW", description="x")
    remediate_finding(finding["id"], note="done")
    closed = adjudicate_finding(finding["id"], "VERIFY")
    assert closed["status"] == "VERIFIED_CLOSED"

    res = api.remediate_finding(
        finding["id"], {"remediation_note": "again"}, ANALYST
    )
    validate_error(res, ApiErrorId.ERR_FINDING_INVALID_STATE)


def test_remediate_overdue_finding_allowed(api, any_headers):
    """PRD §2.5: "Any InspectionFinding in `OPEN` whose `due_date` is earlier
    than the new clock date transitions to `OVERDUE`." PRD §3.2: "An analyst
    may submit remediation on a finding in `OPEN` or `OVERDUE`" — late
    remediation remains permitted.

    Design: Corner/state_machines/remediate_overdue_finding_allowed
    """
    branch = make_branch(region="S")
    inspection = schedule_and_start_inspection(branch["id"], scheduled_date="2026-08-02")
    finding = add_finding(
        inspection["id"], severity="MEDIUM", due_date="2026-08-05",
        description="late one",
    )
    set_clock("2026-08-06T00:00:01Z")
    swept = validate_success(api.get_finding(finding["id"], any_headers), 200)
    assert swept["status"] == "OVERDUE"

    remediated = remediate_finding(finding["id"], note="late fix")
    assert remediated["status"] == "REMEDIATION_SUBMITTED"


# ─── RBAC: finding creation ───────────────────────────

def test_role_forbidden_for_finding_create(api, any_headers):
    """PRD §2.1: "If the caller's role is not permitted for the target
    endpoint — or an entity-backed ownership check fails — the request is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." Findings are an analyst
    function; a RegisteredRep cannot record them.

    Design: Corner/rbac/role_forbidden_for_finding_create
    """
    branch, inspection = setup_in_progress_inspection(region="N")
    rep = make_rep(branch["id"], crd_number="950001", full_name="RB Rep")
    res = api.create_finding(
        create_finding_payload(inspection["id"], severity="LOW",
                               description="rep attempt"),
        make_registered_rep_headers(rep["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ─── remediation revision loop ────────────────────────

class TestFindingRemediationCycle:
    def test_reopen_returns_to_open_and_counts(self, api, any_headers):
        """PRD §3.2: "Reopening returns the finding to `OPEN`, increments its
        `reopen_count` by one, records the payload's `rejection_reason` in
        `adjudication_note`, and recomputes the branch score as the finding
        re-enters the scored set — the exact compensation of the remediation
        transition."

        Design: Difficulty/non_linear_state_machine/nonlinear_finding_remediation_cycle
        """
        _branch, inspection = setup_in_progress_inspection(region="S")
        finding = add_finding(inspection["id"], severity="MEDIUM",
                              description="consent file")
        remediate_finding(finding["id"], note="retrained staff")

        reopened = adjudicate_finding(
            finding["id"], "REOPEN", rejection_reason="evidence incomplete"
        )
        assert reopened["status"] == "OPEN"
        assert reopened["reopen_count"] == 1
        assert reopened.get("adjudication_note") == "evidence incomplete"

    def test_revision_loop_completes_to_verified_closed(self, api, any_headers):
        """PRD §3.2: "Remediation is an analyst act with an unlimited
        revision loop." and "Verification moves the finding to
        `VERIFIED_CLOSED`, stamps `verified_by` with the principal's
        identifier, and decrements the inspection's `open_findings_count` by
        one." One full loop (remediate → reopen → remediate → verify) ends
        with reopen_count exactly 1.

        Design: Difficulty/non_linear_state_machine/nonlinear_finding_remediation_cycle
        """
        _branch, inspection = setup_in_progress_inspection(region="S")
        finding = add_finding(inspection["id"], severity="MEDIUM",
                              description="consent file")
        remediate_finding(finding["id"], note="retrained staff")
        adjudicate_finding(finding["id"], "REOPEN",
                           rejection_reason="evidence incomplete")
        remediate_finding(finding["id"], note="second submission")
        verified = adjudicate_finding(finding["id"], "VERIFY")

        assert verified["status"] == "VERIFIED_CLOSED"
        assert verified["reopen_count"] == 1
        assert verified.get("verified_by") == "principal-a"
        insp_after = validate_success(
            api.get_inspection(inspection["id"], any_headers), 200
        )
        assert insp_after["open_findings_count"] == 0


# ─── branch risk score ────────────────────────────────

class TestBranchRiskScoreWeighted:
    def test_weighted_sum_of_scored_findings(self, api, any_headers):
        """PRD §3.2: "The branch `risk_score` weighs only findings in the
        scored statuses `OPEN` and `OVERDUE`: fifteen points for each scored
        `HIGH` finding, five for each scored `MEDIUM`, and two for each
        scored `LOW`, plus a flat twenty points whenever the branch's
        `sd_rep_count` is at least one, with the total capped at 100."
        1 HIGH + 1 MEDIUM + 2 LOW with no SD reps scores 15 + 5 + 4 = 24.

        Design: Difficulty/combinatorial_formula/combo_branch_risk_score_weighted
        """
        branch, inspection = setup_in_progress_inspection(region="W")
        add_finding(inspection["id"], severity="HIGH", description="books gap")
        add_finding(inspection["id"], severity="MEDIUM", description="late review")
        add_finding(inspection["id"], severity="LOW", description="filing")
        add_finding(inspection["id"], severity="LOW", description="signage")

        branch_after = get_branch(branch["id"])
        assert branch_after["risk_score"] == 24
        assert_branch_risk_invariants(branch_after)

    def test_single_high_finding_does_not_escalate_posture(self, api, any_headers):
        """PRD §3.2: "When any single inspection of the branch accumulates
        two or more `HIGH` findings in the counting statuses — a count of
        exactly one does not trigger — the branch's `posture` becomes
        `REMEDIATION_REQUIRED`". With only one HIGH finding the posture stays
        NORMAL.

        Design: Difficulty/combinatorial_formula/combo_branch_risk_score_weighted
        """
        branch, inspection = setup_in_progress_inspection(region="W")
        add_finding(inspection["id"], severity="HIGH", description="books gap")
        add_finding(inspection["id"], severity="MEDIUM", description="late review")
        add_finding(inspection["id"], severity="LOW", description="filing")
        add_finding(inspection["id"], severity="LOW", description="signage")

        branch_after = get_branch(branch["id"])
        assert branch_after["posture"] == "NORMAL"
        assert branch_after["high_severity_open_count"] == 1


# ─── remediation/reopen risk conservation ─────────────

class TestOpenFindingsScoreConservation:
    def test_remediate_removes_finding_from_scored_set(self, api, any_headers):
        """PRD §3.2: "The branch `risk_score` weighs only findings in the
        scored statuses `OPEN` and `OVERDUE`" and remediation moves a finding
        to `REMEDIATION_SUBMITTED`, so "the branch `risk_score` is
        recomputed". One HIGH (15) + one LOW (2) scores 17; remediating the
        HIGH leaves only the LOW scored: 2.

        Design: Difficulty/compensating_invariant/invariant_open_findings_conservation
        """
        branch, inspection = setup_in_progress_inspection(region="S")
        high = add_finding(inspection["id"], severity="HIGH", description="hf")
        add_finding(inspection["id"], severity="LOW", description="lf")
        assert get_branch(branch["id"])["risk_score"] == 17

        remediate_finding(high["id"], note="fixed")
        mid = get_branch(branch["id"])
        assert mid["risk_score"] == 2

    def test_reopen_restores_score_exactly(self, api, any_headers):
        """PRD §3.2: "Reopening returns the finding to `OPEN`, increments its
        `reopen_count` by one, records the payload's `rejection_reason` in
        `adjudication_note`, and recomputes the branch score as the finding
        re-enters the scored set — the exact compensation of the remediation
        transition." The forward (17 → 2) plus compensating (2 → 17) pair
        leaves the branch score unchanged.

        Design: Difficulty/compensating_invariant/invariant_open_findings_conservation
        """
        branch, inspection = setup_in_progress_inspection(region="S")
        high = add_finding(inspection["id"], severity="HIGH", description="hf")
        add_finding(inspection["id"], severity="LOW", description="lf")

        remediate_finding(high["id"], note="fixed")
        assert get_branch(branch["id"])["risk_score"] == 2
        adjudicate_finding(high["id"], "REOPEN", rejection_reason="not sufficient")

        restored = get_branch(branch["id"])
        assert restored["risk_score"] == 17


# ─── posture escalation cascade ───────────────────────

class TestHighFindingPostureEscalation:
    def test_second_high_finding_flips_posture_and_pulls_in_due_date(
        self, api, any_headers
    ):
        """PRD §3.2: "When any single inspection of the branch accumulates
        two or more `HIGH` findings in the counting statuses — a count of
        exactly one does not trigger — the branch's `posture` becomes
        `REMEDIATION_REQUIRED`, and its `next_inspection_due_date` is pulled
        in to the earlier of its current value and the current clock date
        plus 90 days." min(2027-08-01, 2026-08-01 + 90 days) = 2026-10-30.

        Design: Difficulty/transitive_cascade/cascade_high_finding_posture_escalation
        """
        branch, inspection = setup_in_progress_inspection(region="E")
        assert get_branch(branch["id"])["next_inspection_due_date"] == "2027-08-01"

        add_finding(inspection["id"], severity="HIGH", description="high one")
        add_finding(inspection["id"], severity="HIGH", description="high two")

        branch_after = get_branch(branch["id"])
        assert branch_after["posture"] == "REMEDIATION_REQUIRED"
        assert branch_after["next_inspection_due_date"] == "2026-10-30"

    def test_second_high_finding_scores_thirty_and_counts_two(
        self, api, any_headers
    ):
        """PRD §3.2: "fifteen points for each scored `HIGH` finding" — two
        open HIGH findings score 30 — and "Recording a finding increments the
        inspection's `open_findings_count` — and `high_severity_open_count`
        when the severity is `HIGH` — and immediately recomputes the branch's
        counts, `risk_score`, and `posture`."

        Design: Difficulty/transitive_cascade/cascade_high_finding_posture_escalation
        """
        branch, inspection = setup_in_progress_inspection(region="E")
        add_finding(inspection["id"], severity="HIGH", description="high one")
        add_finding(inspection["id"], severity="HIGH", description="high two")

        branch_after = get_branch(branch["id"])
        assert branch_after["risk_score"] == 30
        assert branch_after["high_severity_open_count"] == 2
        assert branch_after["open_findings_count"] == 2
