"""Findings: remediation deadlines, escalation boundaries, closure and reopen
(PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    complete_engagement,
    create_finding,
    create_model,
    create_model_with_approved_doc,
    create_approved_model_with_metric,
    get_model,
    open_engagement,
    record_breach_run,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

OWNER_A = TEST_USERS["model_owner_a_headers"]
OFFICER = TEST_USERS["risk_officer_headers"]
VALIDATOR = TEST_USERS["model_validator_headers"]


class TestFindingCreation:
    def test_finding_creation_sets_source_validation(self, api):
        """PRD §3.6: "A manually raised finding is stamped with `source` `VALIDATION`
        and the raiser's `X-User-ID` as `raised_by_user_id`, and starts in `OPEN`. (A
        second origin, the monitoring cascade of §3.7, stamps `source` `MONITORING` and
        the literal string 'system' as `raised_by_user_id`.)"

        Design: Corner/entities/finding_creation_sets_source_validation
        """
        model = create_model(name="Find M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        finding = validate_success(
            api.create_finding(model["id"], {"severity": "LOW", "title": "manual finding"}, VALIDATOR),
            expected_status=201,
        )
        assert finding["source"] == "VALIDATION"
        assert finding["raised_by_user_id"] == "u_val"
        assert finding["status"] == "OPEN"
        assert finding.get("escalated_at") is None
        assert finding.get("closed_at") is None


class TestFindingDeadlines:
    def test_finding_deadlines_on_tier1_model(self, api):
        """PRD §3.6: "The computation starts from a base allowance by severity —
        ninety days for `LOW`, sixty for `MEDIUM`, thirty for `HIGH`, fourteen days
        (two weeks) for `CRITICAL` — then multiplies that base by a tier factor: one
        times for a `TIER_1` model, one and a half times for `TIER_2`, and double for
        `TIER_3`, with the product rounded half-up to a whole number of days."
        PRD §3.6: "The deadline is the finding's `created_at` plus that many days."

        TIER_1 model (HIGH/SINGLE_DESK/100 -> 70) at the 2026-08-01 default clock:
        CRITICAL -> round(14*1.0) = 14 days -> 2026-08-15; HIGH -> 30 days ->
        2026-08-31.

        Design: Difficulty/combinatorial_formula/finding_deadline_severity_tier_source_clamp
        """
        model = create_model(name="Deadline T1", declared_complexity="HIGH", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        assert model["risk_tier"] == "TIER_1"
        f_crit = validate_success(
            api.create_finding(model["id"], {"severity": "CRITICAL", "title": "CRIT on T1"}, OFFICER),
            expected_status=201,
        )
        assert_instant_equal(f_crit["remediation_due_at"], "2026-08-15T00:00:00Z",
                             "CRITICAL on TIER_1")
        f_high = validate_success(
            api.create_finding(model["id"], {"severity": "HIGH", "title": "HIGH on T1"}, OFFICER),
            expected_status=201,
        )
        assert_instant_equal(f_high["remediation_due_at"], "2026-08-31T00:00:00Z", "HIGH on TIER_1")

    def test_finding_deadlines_on_tier2_model(self, api):
        """PRD §3.6: "The computation starts from a base allowance by severity —
        ninety days for `LOW`, sixty for `MEDIUM`, thirty for `HIGH`, fourteen days
        (two weeks) for `CRITICAL` — then multiplies that base by a tier factor: one
        times for a `TIER_1` model, one and a half times for `TIER_2`, and double for
        `TIER_3`, with the product rounded half-up to a whole number of days."

        TIER_2 model (MEDIUM/SINGLE_DESK/100 -> 50): MEDIUM -> round(60*1.5) = 90 days
        -> 2026-10-30; LOW -> round(90*1.5) = 135 days -> 2026-12-14.

        Design: Difficulty/combinatorial_formula/finding_deadline_severity_tier_source_clamp
        """
        model = create_model(name="Deadline T2", declared_complexity="MEDIUM", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        assert model["risk_tier"] == "TIER_2"
        f_med = validate_success(
            api.create_finding(model["id"], {"severity": "MEDIUM", "title": "MED on T2"}, OFFICER),
            expected_status=201,
        )
        assert_instant_equal(f_med["remediation_due_at"], "2026-10-30T00:00:00Z", "MEDIUM on TIER_2")
        f_low = validate_success(
            api.create_finding(model["id"], {"severity": "LOW", "title": "LOW on T2"}, OFFICER),
            expected_status=201,
        )
        assert_instant_equal(f_low["remediation_due_at"], "2026-12-14T00:00:00Z", "LOW on TIER_2")

    def test_finding_deadline_monitoring_deduction_and_min_clamp(self, api):
        """PRD §3.6: "When the finding's `source` is `MONITORING`, five days are then
        deducted as an urgency adjustment."
        PRD §3.7: "when `consecutive_breach_count` reaches exactly three, the system
        auto-raises a finding on the metric's model — severity `HIGH`, `source`
        `MONITORING`, `raised_by_user_id` the literal string 'system', and a `title` of
        the form "AUTO: 3 consecutive breaches on " followed by the metric's
        `metric_name`."

        Auto-raised HIGH MONITORING finding on a TIER_1 model, created at the
        2026-08-01 default clock: round(30*1.0) - 5 = 25 days -> 2026-08-26.

        Design: Corner/calculations/finding_deadline_monitoring_deduction_and_min_clamp
        """
        model, metric, _ctx = create_approved_model_with_metric(
            name="MonDed M", declared_complexity="HIGH", usage_scope="SINGLE_DESK", exposure_amount=100,
            assessed_complexity="HIGH",
        )
        record_breach_run(metric["id"], [0.30, 0.31, 0.32])
        findings, _ = validate_paginated(api.list_findings(model["id"], OFFICER))
        assert len(findings) == 1
        auto = findings[0]
        assert auto["source"] == "MONITORING"
        assert auto["severity"] == "HIGH"
        assert auto["raised_by_user_id"] == "system"
        assert auto["title"] == "AUTO: 3 consecutive breaches on psi"
        assert_instant_equal(auto["remediation_due_at"], "2026-08-26T00:00:00Z",
                             "auto-finding deadline")

    def test_finding_deadline_tier_pinned_at_creation(self, api):
        """PRD §3.6: "Two pinning rules make deadlines stable: the tier used is the
        owning model's `risk_tier` at the moment of creation, evaluated before the new
        finding itself is counted into the model's findings penalty, so a finding never
        shifts the tier that sets its own deadline; and later tier changes never move
        an existing deadline."

        LOW finding on a TIER_3 model (30): round(90*2.0) = 180 days -> 2027-01-28. A
        later CRITICAL finding flips the model to 41 / TIER_2 without moving the first
        finding's deadline.

        Design: Corner/calculations/finding_deadline_tier_pinned_at_creation
        """
        model = create_model(name="PinTier M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        f1 = validate_success(
            api.create_finding(model["id"], {"severity": "LOW", "title": "early finding"}, OFFICER),
            expected_status=201,
        )
        assert_instant_equal(f1["remediation_due_at"], "2027-01-28T00:00:00Z",
                             "tier pinned TIER_3 at creation")
        create_finding(model["id"], severity="CRITICAL", title="tier flipper")
        assert get_model(model["id"])["risk_tier"] == "TIER_2", "30 + 1 + 10 = 41"
        findings, _ = validate_paginated(api.list_findings(model["id"], OFFICER))
        by_id = {f["id"]: f for f in findings}
        assert_instant_equal(by_id[f1["id"]]["remediation_due_at"], "2027-01-28T00:00:00Z",
                             "later tier change does not move existing deadlines")


class TestFindingEscalationBoundaries:
    def test_clock_sweep_overdue_boundary_exactness(self, api):
        """PRD §3.6: "When a sweep finds an `OPEN` finding whose `remediation_due_at`
        is strictly in the past, the finding becomes `OVERDUE` — at exactly the due
        instant it is not yet overdue. When a sweep finds an `OVERDUE` finding whose
        deadline plus a grace of seven days is strictly in the past, the finding
        becomes `ESCALATED` and `escalated_at` is stamped — at exactly the deadline
        plus seven days it is not yet escalated."

        CRITICAL on a TIER_1 model at 2026-08-01: due 2026-08-15, escalation once now
        is past 2026-08-22.

        Design: Corner/cross_cutting_complexity_layers/clock_sweep_overdue_boundary_exactness
        """
        model = create_model(name="Sweep M", declared_complexity="HIGH", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        finding = create_finding(model["id"], severity="CRITICAL", title="sweep boundary")

        def status_now():
            findings, _ = validate_paginated(api.list_findings(model["id"], OFFICER))
            return findings[0]["status"]

        set_clock("2026-08-15T00:00:00Z")
        assert status_now() == "OPEN", "at exactly due_at the finding is NOT overdue"
        set_clock("2026-08-15T00:00:01Z")
        assert status_now() == "OVERDUE", "one second past the due instant"
        set_clock("2026-08-22T00:00:00Z")
        assert status_now() == "OVERDUE", "at exactly due + 7d the finding is NOT yet escalated"
        set_clock("2026-08-22T00:00:01Z")
        assert status_now() == "ESCALATED", "one second past the grace boundary"


class TestFindingCloseReopen:
    def test_finding_close_from_closed_returns_not_closable(self, api):
        """PRD §3.6: "Closing a finding is a `ModelRiskOfficer` action available from
        `OPEN`, `OVERDUE`, or `ESCALATED`; closing one already `CLOSED` fails with
        `ERR_FINDING_NOT_CLOSABLE`."

        Design: Corner/state_machines/finding_close_from_closed_returns_not_closable
        """
        model = create_model(name="Close M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        finding = create_finding(model["id"], severity="LOW", title="double close")
        validate_success(api.close_finding(model["id"], finding["id"], OFFICER))
        err = validate_error(api.close_finding(model["id"], finding["id"], OFFICER),
                             ApiErrorId.ERR_FINDING_NOT_CLOSABLE)
        assert err["error_id"] == "ERR_FINDING_NOT_CLOSABLE"
        assert get_model(model["id"])["open_findings_count"] == 0

    def test_finding_reopen_from_open_returns_not_open(self, api):
        """PRD §3.6: "Reopening — a `ModelRiskOfficer` action allowed only from
        `CLOSED`, else `ERR_FINDING_NOT_OPEN`".

        Design: Corner/state_machines/finding_reopen_from_open_returns_not_open
        """
        model = create_model(name="ReopF M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        finding = create_finding(model["id"], severity="LOW", title="bad reopen")
        err = validate_error(api.reopen_finding(model["id"], finding["id"], OFFICER),
                             ApiErrorId.ERR_FINDING_NOT_OPEN)
        assert err["error_id"] == "ERR_FINDING_NOT_OPEN"

    def test_low_finding_close_skips_retest_gate(self, api):
        """PRD §3.6: "For `HIGH` and `CRITICAL` findings, closure additionally requires
        retest evidence: a `COMPLETED` validation engagement on the same model whose
        `completed_at` is after the finding's `created_at`, failing with
        `ERR_RETEST_REQUIRED` when none exists."

        The gate is conditional on severity: a MEDIUM finding closes with no
        engagements at all.

        Design: Corner/validations/low_finding_close_skips_retest_gate
        """
        model = create_model(name="CondGate M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        finding = create_finding(model["id"], severity="MEDIUM", title="no retest needed")
        closed = validate_success(api.close_finding(model["id"], finding["id"], OFFICER))
        assert closed["status"] == "CLOSED"

    def test_high_finding_close_requires_later_completed_retest(self, api):
        """PRD §3.6: "For `HIGH` and `CRITICAL` findings, closure additionally requires
        retest evidence: a `COMPLETED` validation engagement on the same model whose
        `completed_at` is after the finding's `created_at`, failing with
        `ERR_RETEST_REQUIRED` when none exists."

        The only COMPLETED engagement finished at 2026-08-01, before the finding's
        created_at 2026-08-02, so the close is rejected.

        Design: Corner/validations/high_finding_close_requires_later_completed_retest
        """
        model, _doc = create_model_with_approved_doc(name="Retest M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        eng = open_engagement(model["id"])
        complete_engagement(eng["id"], outcome="EFFECTIVE", assessed_complexity="LOW")
        set_clock("2026-08-02T00:00:00Z")
        finding = create_finding(model["id"], severity="HIGH", title="needs retest")
        err = validate_error(api.close_finding(model["id"], finding["id"], OFFICER),
                             ApiErrorId.ERR_RETEST_REQUIRED)
        assert err["error_id"] == "ERR_RETEST_REQUIRED"
        findings, _ = validate_paginated(api.list_findings(model["id"], OFFICER))
        assert findings[0]["status"] == "OPEN"

    def test_high_finding_close_succeeds_with_later_retest(self, api):
        """PRD §3.6: "For `HIGH` and `CRITICAL` findings, closure additionally requires
        retest evidence: a `COMPLETED` validation engagement on the same model whose
        `completed_at` is after the finding's `created_at`, failing with
        `ERR_RETEST_REQUIRED` when none exists."
        PRD §3.6: "Closure stamps `closed_at`, decrements `open_findings_count` by one,
        recomputes `risk_score` and `risk_tier` with the penalty reduced, and refreshes
        `validation_due_at` if the tier changed."

        Finding created at 2026-08-02; retest engagement completed at 2026-08-03; the
        close succeeds.

        Design: Corner/validations/high_finding_close_succeeds_with_later_retest
        """
        model, _doc = create_model_with_approved_doc(name="RetestOK M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        set_clock("2026-08-02T00:00:00Z")
        finding = create_finding(model["id"], severity="HIGH", title="will retest")
        eng = open_engagement(model["id"], period_start="2026-08-02T00:00:00Z",
                              period_end="2026-08-03T00:00:00Z", scope_outcomes_analysis=False)
        set_clock("2026-08-03T00:00:00Z")
        complete_engagement(eng["id"], outcome="EFFECTIVE_WITH_FINDINGS", assessed_complexity="LOW")
        closed = validate_success(api.close_finding(model["id"], finding["id"], OFFICER))
        assert closed["status"] == "CLOSED"
        assert_instant_equal(closed["closed_at"], "2026-08-03T00:00:00Z", "closed_at")
        assert get_model(model["id"])["open_findings_count"] == 0


class TestCloseReopenInvariant:
    def test_close_then_reopen_restores_count_and_score(self, api):
        """PRD §3.6: "Closure stamps `closed_at`, decrements `open_findings_count` by
        one, recomputes `risk_score` and `risk_tier` with the penalty reduced, and
        refreshes `validation_due_at` if the tier changed."
        PRD §3.6: "The model's `open_findings_count` is incremented, `risk_score` and
        `risk_tier` are recomputed with the penalty restored, and `validation_due_at`
        is refreshed if the tier changed."

        LOW/SINGLE_DESK/100 -> 30; MEDIUM finding -> 32; close -> 0 findings / 30;
        reopen -> exactly the pre-close values (1 finding / 32) again.

        Design: Difficulty/compensating_invariant/close_reopen_restores_open_findings_count
        """
        model, _doc = create_model_with_approved_doc(name="Invariant M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        finding = create_finding(model["id"], severity="MEDIUM", title="invariant finding")
        assert get_model(model["id"])["risk_score"] == 32

        validate_success(api.close_finding(model["id"], finding["id"], OFFICER))
        mid = get_model(model["id"])
        assert mid["open_findings_count"] == 0
        assert mid["risk_score"] == 30

        validate_success(api.reopen_finding(model["id"], finding["id"], OFFICER))
        after = get_model(model["id"])
        assert after["open_findings_count"] == 1, "exactly the pre-close value (conserved)"
        assert after["risk_score"] == 32, "exactly the pre-close score"

    def test_reopen_preserves_original_deadline_and_clears_closed_at(self, api):
        """PRD §3.6: "Reopening — a `ModelRiskOfficer` action allowed only from
        `CLOSED`, else `ERR_FINDING_NOT_OPEN` — returns the finding to `OPEN`, clears
        `closed_at` back to unset, and leaves `remediation_due_at` unchanged: the
        original deadline is preserved, not extended."

        Design: Difficulty/compensating_invariant/close_reopen_restores_open_findings_count
        """
        model, _doc = create_model_with_approved_doc(name="Invariant M", declared_complexity="LOW",
                                                     usage_scope="SINGLE_DESK", exposure_amount=100)
        finding = create_finding(model["id"], severity="MEDIUM", title="invariant finding")
        original_due = finding["remediation_due_at"]
        closed = validate_success(api.close_finding(model["id"], finding["id"], OFFICER))
        assert closed.get("closed_at") is not None
        reopened = validate_success(api.reopen_finding(model["id"], finding["id"], OFFICER))
        assert reopened["status"] == "OPEN"
        assert reopened.get("closed_at") is None, "closed_at cleared back to unset"
        assert_instant_equal(reopened["remediation_due_at"], original_due,
                             "reopen preserves the original deadline")


class TestFindingListing:
    def test_findings_list_filters_by_status_and_severity(self, api):
        """PRD §3.6: "The findings list of a model can be filtered by `status` and by
        `severity`."

        Design: Corner/endpoints/findings_list_filters_by_status_and_severity
        """
        model = create_model(name="Filt M", declared_complexity="LOW", usage_scope="SINGLE_DESK",
                             exposure_amount=100)
        create_finding(model["id"], severity="CRITICAL", title="crit open")
        low = create_finding(model["id"], severity="LOW", title="low closed")
        validate_success(api.close_finding(model["id"], low["id"], OFFICER))

        open_rows, _ = validate_paginated(api.list_findings(model["id"], OFFICER, params={"status": "OPEN"}))
        assert len(open_rows) == 1 and open_rows[0]["severity"] == "CRITICAL"
        crit_rows, _ = validate_paginated(
            api.list_findings(model["id"], OFFICER, params={"severity": "CRITICAL"})
        )
        assert len(crit_rows) == 1
        all_rows, meta = validate_paginated(api.list_findings(model["id"], OFFICER))
        assert len(all_rows) == 2
