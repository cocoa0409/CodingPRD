"""Risk acceptances, expiry sweeps, and cycle approval gating (PRD §3.6, §3.7, §2.7)."""
import pytest

from test_helpers import (
    ANALYST,
    ANALYST_1,
    APPROVER,
    ApiErrorId,
    NON_EXISTENT_UUID,
    approve_acceptance,
    contact_headers,
    create_and_submit_response,
    create_exception_payload,
    get_success_data,
    issue_cycle,
    list_schedule_events,
    open_cycle,
    register_vendor,
    request_risk_acceptance,
    review_artifact_clean,
    score_cycle,
    set_clock,
    setup_remediation_cycle,
    setup_scored_cycle,
    upload_evidence,
    validate_error,
    validate_success,
    yes_answers,
)


def _acceptance(api, cycle_id, acceptance_id):
    rows = get_success_data(api.list_cycle_risk_acceptances(cycle_id, ANALYST))
    for row in rows:
        if row["id"] == acceptance_id:
            return row
    raise AssertionError(f"Acceptance {acceptance_id} not found in cycle {cycle_id}")


def _exception(api, exception_id):
    return get_success_data(api.get_exception(exception_id, ANALYST))


def _open_count(api, cycle_id):
    return get_success_data(api.get_cycle(cycle_id, ANALYST))["open_exception_count"]


def _setup_approved_acceptance(ctx, expires_at):
    """Request + approve an acceptance over ctx's exceptions. Returns it."""
    ra = request_risk_acceptance(ctx, [e["id"] for e in ctx["exceptions"]], expires_at=expires_at)
    return approve_acceptance(ctx, ra["id"])


class TestAcceptanceExpiryCascade:
    def test_expiry_reopens_exceptions_and_journals_schedule(self, api):
        """PRD §3.6: "When the clock passes an `APPROVED` acceptance's `expires_at`,
        the expiry sweep moves it `APPROVED → EXPIRED`: every exception it had closed
        reopens to `OPEN` with `closure_reason` set to `ACCEPTANCE_EXPIRED`; when the
        owning cycle is non-terminal, its `open_exception_count` rises by the number
        of reopened exceptions."
        PRD §3.6: "The vendor's `next_reassessment_due` is pulled forward to the
        current clock plus 30 days whenever the existing date is later — it never
        moves later than its current value — and a `ReassessmentSchedule` event of
        kind `ACCEPTANCE_EXPIRY` is appended with its `reason_ref` pointing at the
        expired acceptance."

        Design: Difficulty/transitive_cascade/acceptance_expiry_reopens_exceptions_and_shifts_schedule
        """
        ctx = setup_remediation_cycle(exception_severities=("MEDIUM",))
        ra = _setup_approved_acceptance(ctx, "2026-08-10T00:00:00Z")
        assert ra["status"] == "APPROVED"
        assert _open_count(api, ctx["cycle"]["id"]) == 0
        set_clock("2026-08-11T00:00:00Z")
        ra_after = _acceptance(api, ctx["cycle"]["id"], ra["id"])
        assert ra_after["status"] == "EXPIRED"
        exception = _exception(api, ctx["exceptions"][0]["id"])
        assert exception["status"] == "OPEN"
        assert exception["closure_reason"] == "ACCEPTANCE_EXPIRED"
        assert _open_count(api, ctx["cycle"]["id"]) == 1
        events = list_schedule_events(ctx["vendor"]["id"], kind="ACCEPTANCE_EXPIRY")
        assert any(e["reason_ref"] == ra["id"] for e in events), (
            "An ACCEPTANCE_EXPIRY event must reference the expired acceptance"
        )

    def test_sweep_fires_strictly_after_expires_at(self, api):
        """PRD §3.6: "When the clock passes an `APPROVED` acceptance's `expires_at`,
        the expiry sweep moves it `APPROVED → EXPIRED`: every exception it had closed
        reopens to `OPEN` with `closure_reason` set to `ACCEPTANCE_EXPIRED`; when the
        owning cycle is non-terminal, its `open_exception_count` rises by the number
        of reopened exceptions."

        At exactly expires_at the clock has not passed; one second later it has.

        Design: Difficulty/transitive_cascade/acceptance_expiry_reopens_exceptions_and_shifts_schedule
        """
        ctx = setup_remediation_cycle(exception_severities=("MEDIUM",))
        ra = _setup_approved_acceptance(ctx, "2026-08-10T00:00:00Z")
        set_clock("2026-08-10T00:00:00Z")
        assert _acceptance(api, ctx["cycle"]["id"], ra["id"])["status"] == "APPROVED"
        assert _exception(api, ctx["exceptions"][0]["id"])["status"] == "CLOSED_ACCEPTED"
        set_clock("2026-08-10T00:00:01Z")
        assert _acceptance(api, ctx["cycle"]["id"], ra["id"])["status"] == "EXPIRED"
        assert _exception(api, ctx["exceptions"][0]["id"])["status"] == "OPEN"


class TestExpiryWindowSemantics:
    def _setup_two_acceptances(self, api):
        ctx = setup_remediation_cycle(exception_severities=("MEDIUM", "MEDIUM"))
        x1, x2 = ctx["exceptions"]
        ra1 = request_risk_acceptance(ctx, [x1["id"]], expires_at="2026-08-20T00:00:00Z")
        ra2 = request_risk_acceptance(ctx, [x2["id"]], expires_at="2026-12-01T00:00:00Z")
        approve_acceptance(ctx, ra1["id"])
        approve_acceptance(ctx, ra2["id"])
        return ctx, x1, x2, ra1, ra2

    def test_sweep_expires_only_the_acceptance_inside_its_window(self, api):
        """PRD §3.6: "When the clock passes an `APPROVED` acceptance's `expires_at`,
        the expiry sweep moves it `APPROVED → EXPIRED`: every exception it had closed
        reopens to `OPEN` with `closure_reason` set to `ACCEPTANCE_EXPIRED`; when the
        owning cycle is non-terminal, its `open_exception_count` rises by the number
        of reopened exceptions."

        With the clock at 2026-08-20T00:00:01Z the acceptance expiring 2026-08-20 is
        swept while the one expiring 2026-12-01 is untouched.

        Design: Difficulty/resource_temporal_overlap/risk_acceptance_expiry_window_vs_clock
        """
        ctx, x1, x2, ra1, ra2 = self._setup_two_acceptances(api)
        assert _open_count(api, ctx["cycle"]["id"]) == 0
        set_clock("2026-08-20T00:00:01Z")
        assert _acceptance(api, ctx["cycle"]["id"], ra1["id"])["status"] == "EXPIRED"
        assert _exception(api, x1["id"])["status"] == "OPEN"
        assert _acceptance(api, ctx["cycle"]["id"], ra2["id"])["status"] == "APPROVED"
        assert _exception(api, x2["id"])["status"] == "CLOSED_ACCEPTED"
        assert _open_count(api, ctx["cycle"]["id"]) == 1

    def test_decision_on_lapsed_acceptance_rejected(self, api):
        """PRD §3.6: "Approval belongs to a `SecurityApprover` who is not the
        requester (§2.8), requires every referenced exception still in `OPEN` or
        `IN_REMEDIATION`, requires `expires_at` still ahead of the clock — a decision
        on an acceptance whose expiry has passed but whose sweep has not yet fired is
        rejected with `ERR_ACCEPTANCE_EXPIRED` (HTTP 422)".

        The sweep only moves APPROVED acceptances, so a REQUESTED acceptance whose
        expiry has lapsed remains decidable in principle and is rejected here.

        Design: Difficulty/resource_temporal_overlap/risk_acceptance_expiry_window_vs_clock
        """
        ctx = setup_remediation_cycle(exception_severities=("MEDIUM",))
        ra = request_risk_acceptance(
            ctx, [ctx["exceptions"][0]["id"]], expires_at="2026-08-05T00:00:00Z"
        )
        set_clock("2026-08-06T00:00:00Z")
        fresh = get_success_data(api.get_cycle(ctx["cycle"]["id"], ANALYST))
        res = api.approve_risk_acceptance(
            ctx["vendor"]["id"], ctx["cycle"]["id"], ra["id"],
            {"expected_cycle_version": fresh["version"]}, APPROVER,
        )
        validate_error(res, ApiErrorId.ERR_ACCEPTANCE_EXPIRED)


class TestCycleApprovalAddendumGate:
    def _setup_approval_ready_with_addendum(self, api):
        """TIER_3 cycle in RISK_ACCEPTANCE_REVIEW with a REQUIRED addendum:
        one HIGH exception accepted away, remediation resolved."""
        ctx = setup_remediation_cycle(tier="TIER_3", exception_severities=("HIGH",))
        ra = _setup_approved_acceptance(ctx, "2027-01-01T00:00:00Z")
        cycle = get_success_data(api.resolve_remediation(ctx["vendor"]["id"], ctx["cycle"]["id"], ANALYST))
        assert cycle["status"] == "RISK_ACCEPTANCE_REVIEW"
        return ctx, ra

    def test_approval_blocked_while_addendum_required(self, api):
        """PRD §3.7: "Approving a cycle in `RISK_ACCEPTANCE_REVIEW` requires
        `open_exception_count` at zero, every risk acceptance for the cycle decided
        into `APPROVED` or `REJECTED`, and no `REQUIRED` or `DRAFTED` contract
        addendum outstanding — only `SIGNED` or `WAIVED` addenda may remain. Open
        residue is rejected with `ERR_OPEN_ITEMS_OUTSTANDING`, an outstanding
        addendum specifically with `ERR_ADDENDUM_OUTSTANDING` (HTTP 422)".

        Design: Difficulty/cross_entity_state_dependency/cycle_approval_gated_by_addendum_state
        """
        ctx, _ra = self._setup_approval_ready_with_addendum(api)
        addenda = get_success_data(api.list_addenda(ctx["vendor"]["id"], ANALYST))
        assert any(a["status"] == "REQUIRED" for a in addenda), "Setup must yield a REQUIRED addendum"
        # PRD §3.7: "The base set grows with strictness: `TIER_1` requires `C_DPA`;
        # `TIER_2` adds `C_BREACH_NOTIFY`; `TIER_3` further adds `C_AUDIT_RIGHT`"
        # and "any `HIGH`-severity finding — regardless of its status — adds
        # `C_REMEDIATION_TIMELINE`".
        required = next(a for a in addenda if a["status"] == "REQUIRED")
        assert required["clause_set"] == sorted(required["clause_set"])
        assert set(required["clause_set"]) == {
            "C_DPA", "C_BREACH_NOTIFY", "C_AUDIT_RIGHT", "C_REMEDIATION_TIMELINE",
        }
        res = api.approve_cycle(ctx["vendor"]["id"], ctx["cycle"]["id"], APPROVER)
        validate_error(res, ApiErrorId.ERR_ADDENDUM_OUTSTANDING)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ANALYST))
        assert cycle["status"] == "RISK_ACCEPTANCE_REVIEW"

    def test_approval_succeeds_once_addendum_waived(self, api):
        """PRD §3.7: "Approval moves the vendor's posture to `CONDITIONAL` when any
        `APPROVED` risk acceptance exists for the cycle, otherwise to `APPROVED`."
        PRD §3.7: "or a `SecurityApprover` waives it from `REQUIRED` with a
        non-empty `waived_reason`, moving it to `WAIVED`."

        Design: Difficulty/cross_entity_state_dependency/cycle_approval_gated_by_addendum_state
        """
        ctx, _ra = self._setup_approval_ready_with_addendum(api)
        addenda = get_success_data(api.list_addenda(ctx["vendor"]["id"], ANALYST))
        addendum = next(a for a in addenda if a["status"] == "REQUIRED")
        waived = validate_success(
            api.waive_addendum(ctx["vendor"]["id"], addendum["id"], {"waived_reason": "contract renegotiated"}, APPROVER),
            200,
        )
        assert waived["status"] == "WAIVED"
        cycle = validate_success(api.approve_cycle(ctx["vendor"]["id"], ctx["cycle"]["id"], APPROVER), 200)
        assert cycle["status"] == "APPROVED"
        vendor = get_success_data(api.get_vendor(ctx["vendor"]["id"], ANALYST))
        assert vendor["posture"] == "CONDITIONAL"


class TestAcceptanceReferentialIntegrity:
    def _second_cycle_with_exception(self, api, ctx):
        """A different vendor whose cycle carries its own exception."""
        vendor2, contact2 = register_vendor()
        cycle2 = open_cycle(vendor2["id"], ctx["template"]["id"])
        cycle2 = issue_cycle(vendor2["id"], cycle2["id"])
        contact2_headers = contact_headers({"contact": contact2})
        create_and_submit_response(vendor2["id"], cycle2["id"], contact2_headers, yes_answers(ctx["template"]))
        score_cycle(vendor2["id"], cycle2["id"])
        artifact = upload_evidence(vendor2["id"], cycle2["id"], contact2_headers)
        review_artifact_clean(vendor2["id"], cycle2["id"], artifact["id"])
        exception2 = get_success_data(
            api.create_exception(
                vendor2["id"], cycle2["id"],
                create_exception_payload(severity="LOW", description="other cycle finding",
                                         evidence_artifact_id=artifact["id"]),
                ANALYST,
            )
        )
        return vendor2, cycle2, exception2

    def test_cross_cycle_exception_reference_rejected(self, api):
        """PRD §2.9: "10. Referential integrity — referenced children must exist,
        belong to the path parent, and sit in the required state; failures yield
        `ERR_REFERENTIAL_INTEGRITY` (422)."
        PRD §3.6: "A `RiskAnalyst` requests one with a non-empty `exception_ids`
        list — every referenced exception must be `OPEN` or `IN_REMEDIATION`".

        Design: Difficulty/priority_pair_validation_conflict/referential_before_score_threshold_on_acceptance_create
        """
        ctx = setup_remediation_cycle(exception_severities=("HIGH",))
        _vendor2, _cycle2, exception2 = self._second_cycle_with_exception(api, ctx)
        res = api.create_risk_acceptance(
            ctx["vendor"]["id"], ctx["cycle"]["id"],
            {"exception_ids": [exception2["id"]], "justification": "j",
             "compensating_controls": ["c"], "expires_at": "2027-01-01T00:00:00Z"},
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)

    def test_nonexistent_exception_reference_rejected(self, api):
        """PRD §2.9: "10. Referential integrity — referenced children must exist,
        belong to the path parent, and sit in the required state; failures yield
        `ERR_REFERENTIAL_INTEGRITY` (422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_before_score_threshold_on_acceptance_create
        """
        ctx = setup_remediation_cycle(exception_severities=("HIGH",))
        res = api.create_risk_acceptance(
            ctx["vendor"]["id"], ctx["cycle"]["id"],
            {"exception_ids": [NON_EXISTENT_UUID], "justification": "j",
             "compensating_controls": ["c"], "expires_at": "2027-01-01T00:00:00Z"},
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


class TestOccAndDeadlineGuards:
    def test_approve_with_stale_cycle_version_rejected(self, api):
        """PRD §2.7: "Approving a risk acceptance requires `expected_cycle_version`,
        carrying the approver's last-observed `version` of the parent cycle. If the
        cycle's `version` has advanced since — for example because a remediation
        verification or an exception closure changed the cycle's open-exception set
        — the approval is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), forcing
        the decision to be remade against the cycle as it actually stands."
        PRD §3.6: "Each new exception opens in `OPEN` status and raises the cycle's
        `open_exception_count` by one, bumping the cycle's `version`."

        Design: Corner/endpoints/occ_risk_acceptance_approve_stale_cycle_version
        """
        ctx = setup_remediation_cycle(exception_severities=("LOW",))
        stale_version = get_success_data(api.get_cycle(ctx["cycle"]["id"], ANALYST))["version"]
        ra = request_risk_acceptance(ctx, [ctx["exceptions"][0]["id"]])
        # A fresh exception on the same cycle advances cycle.version.
        get_success_data(
            api.create_exception(
                ctx["vendor"]["id"], ctx["cycle"]["id"],
                create_exception_payload(source="QUESTIONNAIRE", severity="LOW", description="bump"),
                ANALYST,
            )
        )
        res = api.approve_risk_acceptance(
            ctx["vendor"]["id"], ctx["cycle"]["id"], ra["id"],
            {"expected_cycle_version": stale_version}, APPROVER,
        )
        validate_error(res, ApiErrorId.ERR_STALE_CYCLE_VERSION)

    def test_acceptance_created_with_past_expiry_rejected(self, api):
        """PRD §3.6: "A `RiskAnalyst` requests one with a non-empty `exception_ids`
        list — every referenced exception must be `OPEN` or `IN_REMEDIATION` — plus a
        `justification`, a list of `compensating_controls`, and an `expires_at` that
        must lie in the future, failing which the request is rejected with
        `ERR_DEADLINE_PASSED` (HTTP 422)."

        Design: Corner/validations/risk_acceptance_expired_at_creation_rejected
        """
        ctx = setup_remediation_cycle(exception_severities=("LOW",))
        res = api.create_risk_acceptance(
            ctx["vendor"]["id"], ctx["cycle"]["id"],
            {"exception_ids": [ctx["exceptions"][0]["id"]], "justification": "j",
             "compensating_controls": ["c"], "expires_at": "2026-07-01T00:00:00Z"},
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_DEADLINE_PASSED)
