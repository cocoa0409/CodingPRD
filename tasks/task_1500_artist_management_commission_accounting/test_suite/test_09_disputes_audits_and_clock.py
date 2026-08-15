"""Disputes, amendments, audit rights, cost allocation boundaries, and the
logical clock (fixed default, monotonicity, and the full sweep)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_team_member,
    advance_clock,
    begin_audit,
    create_option,
    create_opportunity,
    create_and_verify_event,
    demand_audit,
    generate_and_issue_statement,
    generate_statement,
    get_success_data,
    issue_audit_findings,
    issue_statement,
    open_dispute,
    refresh_agreement,
    reopen_audit,
    resolve_dispute,
    setup_artist_team,
    setup_issued_statement_with_event,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["firm_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _setup_issued_170000(api, stage_name="Loop Act"):
    """Artist + VERIFIED event 200000 swept onto an issued ACCRUAL Q1 statement
    (net_payable 170000, dispute window open at the default clock)."""
    sc = setup_artist_team(stage_name=stage_name)
    statement, event = setup_issued_statement_with_event(sc)
    assert statement["net_payable_cents"] == 170000
    return sc, statement, event


class TestDisputeAmendCycle:
    def _setup_upheld_dispute(self, api):
        sc, statement, _event = _setup_issued_170000(api)
        dispute = open_dispute(sc, statement["id"], reason="COMMISSION_RATE",
                               claimed_amount_cents=5000)
        get_success_data(api.start_review_dispute(dispute["id"], sc["bm_headers"]))
        resolve_dispute(sc, dispute["id"], outcome="UPHELD",
                        awarded_amount_cents=5000, resolution_note="rate misapplied")
        return sc, statement, dispute

    def test_amend_appends_adjustment_and_reissues(self, api):
        """PRD: "For each upheld dispute the amendment appends an `ADJUSTMENT`
        line whose amount is the dispute's `awarded_amount_cents` and whose
        reference is the dispute; `revision_number` increments by one."
        PRD: "Totals then re-run over the amended line set — the pinned
        `rate_snapshot` lines are untouched — so `adjustment_total_cents`,
        `net_payable_cents`, `disbursed_cents`, and `carry_out_cents` recompute"

        Design: Difficulty/non_linear_state_machine/statement_issue_dispute_amend_cycle
        """
        sc, statement, dispute = self._setup_upheld_dispute(api)
        amended = validate_success(api.amend_statement(statement["id"],
                                                       sc["bm_headers"]))
        assert amended["status"] == "ISSUED", (
            "Full ISSUED -> DISPUTED -> ISSUED cycle via amendment"
        )
        assert amended["revision_number"] == 2
        assert amended["adjustment_total_cents"] == 5000
        assert amended["net_payable_cents"] == 175000
        assert amended["disbursed_cents"] == 175000
        assert amended["carry_out_cents"] == 0

        lines, meta = validate_paginated(
            api.list_statement_lines(statement["id"], sc["bm_headers"]))
        adjustments = [l for l in lines if l["line_type"] == "ADJUSTMENT"]
        assert len(adjustments) == 1
        assert adjustments[0]["amount_cents"] == 5000
        assert adjustments[0]["ref_id"] == dispute["id"]

    def test_amend_resets_dispute_window(self, api):
        """PRD: "Finally, `issued_at` and `dispute_window_ends_at` reset, opening
        a fresh thirty-day dispute window on the revised statement."

        Design: Difficulty/non_linear_state_machine/statement_issue_dispute_amend_cycle
        """
        sc, statement, _dispute = self._setup_upheld_dispute(api)
        amended = validate_success(api.amend_statement(statement["id"],
                                                       sc["bm_headers"]))
        assert amended["issued_at"] is not None
        assert amended["dispute_window_ends_at"] is not None
        # Both stamps come from the fixed default clock; the window is 30 days.
        assert amended["issued_at"].startswith("2026-08-01T00:00:00")
        assert amended["dispute_window_ends_at"].startswith("2026-08-31T00:00:00")


class TestAuditCostAllocationBoundary:
    def _setup_two_statement_audits(self, api):
        """Two issued ACCRUAL statements each pinning net_payable 400000
        (PUBLISHING 2500bps over gross 533334), each with an IN_PROGRESS audit."""
        sc = setup_artist_team(stage_name="Ratio Act", primary_genre="folk",
                                   income_types=("PUBLISHING",))
        statements = []
        for gross_date, period in (("2026-02-05", ("2026-01-01", "2026-03-31")),
                                   ("2026-05-05", ("2026-04-01", "2026-06-30"))):
            create_and_verify_event(sc, gross_amount_cents=533334,
                                    recognition_date=gross_date,
                                    income_type="PUBLISHING", source_name="PRO")
            st = generate_and_issue_statement(sc, period[0], period[1], "ACCRUAL")
            assert st["net_payable_cents"] == 400000, "533334 - 133334 pinned"
            statements.append(st)
        audits = []
        for st in statements:
            audit = demand_audit(sc, st["id"])
            begin_audit(audit["id"])
            audits.append(audit)
        return sc, audits

    def test_ratio_exactly_five_percent_firm_bears(self, api):
        """PRD: "`cost_bearer` is `FIRM` when the ratio reaches five percent —
        compared as an exact rational, so the boundary reads: underpayment times
        100 is at least base times 5 — or when the underpayment reaches 2500000
        cents ($25,000), and `ARTIST` otherwise."

        Design: Difficulty/boundary_precision_check/audit_underpayment_ratio_five_percent
        """
        _sc, audits = self._setup_two_statement_audits(api)
        issued = issue_audit_findings(audits[0]["id"],
                                      findings_underpayment_cents=20000,
                                      audit_cost_cents=90000)
        assert issued["cost_bearer"] == "FIRM", (
            "20000/400000 is exactly 0.05 and the comparison is >= "
            "(20000*100 >= 400000*5)"
        )
        assert issued["status"] == "FINDINGS_ISSUED"

    def test_ratio_just_below_artist_bears(self, api):
        """PRD: "`cost_bearer` is `FIRM` when the ratio reaches five percent —
        compared as an exact rational, so the boundary reads: underpayment times
        100 is at least base times 5 — or when the underpayment reaches 2500000
        cents ($25,000), and `ARTIST` otherwise."

        Design: Difficulty/boundary_precision_check/audit_underpayment_ratio_five_percent
        """
        _sc, audits = self._setup_two_statement_audits(api)
        issued = issue_audit_findings(audits[1]["id"],
                                      findings_underpayment_cents=19999,
                                      audit_cost_cents=90000)
        assert issued["cost_bearer"] == "ARTIST", (
            "19999/400000 < 0.05 and 19999 is below the 2500000 floor"
        )
        assert issued["status"] == "FINDINGS_ISSUED"


class TestDisputeLifecycle:
    def test_dispute_withdraw_reverts_statement_to_issued(self, api):
        """PRD: "The artist may withdraw a dispute from `OPEN` or
        `UNDER_REVIEW`; when no other active dispute remains on the statement,
        the statement reverts from `DISPUTED` back to `ISSUED`."

        Design: Corner/state_machines/dispute_withdraw_reverts_statement_to_issued
        """
        sc, statement, _event = _setup_issued_170000(api, "Rev Act")
        dispute = open_dispute(sc, statement["id"], reason="EXPENSE_UNAUTHORIZED",
                               claimed_amount_cents=1000)
        mid = get_success_data(api.get_statement(statement["id"], sc["bm_headers"]))
        assert mid["status"] == "DISPUTED"

        withdrawn = validate_success(api.withdraw_dispute(dispute["id"],
                                                          sc["artist_headers"]))
        assert withdrawn["status"] == "WITHDRAWN"
        reverted = get_success_data(api.get_statement(statement["id"],
                                                      sc["bm_headers"]))
        assert reverted["status"] == "ISSUED"
        assert reverted["net_payable_cents"] == 170000, "Totals unchanged by the loop"

    def test_dispute_after_window_closed(self, api):
        """PRD: "an `ACKNOWLEDGED` or `FINALIZED` statement means the dispute
        window has closed (`ERR_DISPUTE_WINDOW_CLOSED`)"
        PRD: "Because deemed acceptance fires the moment the window lapses, an
        `ISSUED` statement always has an open dispute window"

        Design: Corner/validations/dispute_after_window_closed
        """
        sc = setup_artist_team(stage_name="Late Act", with_agent=False)
        statement = generate_and_issue_statement(sc, "2026-06-01", "2026-06-30",
                                                 "ACCRUAL")
        advance_clock("2026-09-15T00:00:00Z")
        acknowledged = get_success_data(api.get_statement(statement["id"],
                                                          sc["bm_headers"]))
        assert acknowledged["status"] == "ACKNOWLEDGED", (
            "The 2026-09-15 sweep deemed it accepted"
        )

        resp = api.create_dispute(
            {"artist_id": sc["artist"]["id"], "statement_id": statement["id"],
             "reason": "OTHER", "claimed_amount_cents": 1000},
            sc["artist_headers"])
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)

    def test_second_dispute_on_same_statement_rejected(self, api):
        """PRD: "a `DISPUTED` statement means another dispute is already active
        (`ERR_DISPUTE_ALREADY_ACTIVE`)"

        Design: Corner/validations/second_dispute_on_same_statement_rejected
        """
        sc = setup_artist_team(stage_name="Dup Act", with_agent=False)
        statement = generate_and_issue_statement(sc, "2026-06-01", "2026-06-30",
                                                 "ACCRUAL")
        first = open_dispute(sc, statement["id"], reason="OTHER",
                             claimed_amount_cents=1000)

        resp = api.create_dispute(
            {"artist_id": sc["artist"]["id"], "statement_id": statement["id"],
             "reason": "COMMISSION_RATE", "claimed_amount_cents": 2000},
            sc["artist_headers"])
        validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_ACTIVE)

        first_after = validate_success(api.get_dispute(first["id"], ADMIN))
        assert first_after["status"] == "OPEN"
        statement_after = get_success_data(api.get_statement(statement["id"],
                                                             sc["bm_headers"]))
        assert statement_after["status"] == "DISPUTED"

    def test_amend_blocked_until_disputes_resolved(self, api):
        """PRD: "A `BusinessManager` amends a `DISPUTED` statement only when every
        dispute on it has reached `RESOLVED_UPHELD`, `RESOLVED_REJECTED`, or
        `WITHDRAWN` — any dispute still open, under review, or escalated blocks
        the amendment with `ERR_DISPUTE_NOT_RESOLVED`."

        Design: Corner/validations/amend_blocked_until_disputes_resolved
        """
        sc = setup_artist_team(stage_name="Amend Act", with_agent=False)
        statement = generate_and_issue_statement(sc, "2026-06-01", "2026-06-30",
                                                 "ACCRUAL")
        open_dispute(sc, statement["id"], reason="OTHER", claimed_amount_cents=1000)

        resp = api.amend_statement(statement["id"], sc["bm_headers"])
        validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_RESOLVED)

        after = get_success_data(api.get_statement(statement["id"], sc["bm_headers"]))
        assert after["status"] == "DISPUTED"
        assert after["revision_number"] == 1


class TestAuditLifecycle:
    def _setup_issued_empty(self, api, stage_name):
        sc = setup_artist_team(stage_name=stage_name, with_agent=False)
        statement = generate_and_issue_statement(sc, "2026-06-01", "2026-06-30",
                                                 "ACCRUAL")
        return sc, statement

    def test_second_audit_on_same_statement_rejected(self, api):
        """PRD: "no other audit on the same statement may be open — any audit not
        yet `CLOSED` blocks a new one with `ERR_AUDIT_ALREADY_ACTIVE`."

        Design: Corner/validations/second_audit_on_same_statement_rejected
        """
        sc, statement = self._setup_issued_empty(api, "Audit Act")
        audit = demand_audit(sc, statement["id"])
        begin_audit(audit["id"])

        resp = api.create_audit(
            {"artist_id": sc["artist"]["id"],
             "scope_statement_id": statement["id"]},
            sc["artist_headers"])
        validate_error(resp, ApiErrorId.ERR_AUDIT_ALREADY_ACTIVE)

        after = validate_success(api.get_audit(audit["id"], ADMIN))
        assert after["status"] == "IN_PROGRESS"

    def test_audit_reopen_limit_two(self, api):
        """PRD: "The artist may object: reopening moves `FINDINGS_ISSUED →
        IN_PROGRESS` and adds one to `reopen_count`, which is capped at 2 — a
        third attempt fails with `ERR_AUDIT_REOPEN_LIMIT`."

        Design: Corner/validations/audit_reopen_limit_two
        """
        sc, statement = self._setup_issued_empty(api, "Reopen Act")
        audit = demand_audit(sc, statement["id"])
        begin_audit(audit["id"])
        for _ in range(2):
            issue_audit_findings(audit["id"], findings_underpayment_cents=0,
                                 audit_cost_cents=10000)
            reopened = reopen_audit(sc, audit["id"])
        assert reopened["reopen_count"] == 2
        issue_audit_findings(audit["id"], findings_underpayment_cents=0,
                             audit_cost_cents=10000)

        resp = api.reopen_audit(audit["id"], sc["artist_headers"])
        validate_error(resp, ApiErrorId.ERR_AUDIT_REOPEN_LIMIT)

        after = validate_success(api.get_audit(audit["id"], ADMIN))
        assert after["reopen_count"] == 2
        assert after["status"] == "FINDINGS_ISSUED"

    def test_audit_window_365_days_inclusive(self, api):
        """PRD: "its `issued_at` must lie within the trailing 365 days of the
        clock, inclusive (`ERR_AUDIT_WINDOW_CLOSED`)"

        Design: Corner/validations/audit_window_365_days_inclusive
        """
        sc, statement = self._setup_issued_empty(api, "Win Act")
        advance_clock("2027-08-01T00:00:00Z")  # exactly 365 days after issuance

        audit = demand_audit(sc, statement["id"])
        begin_audit(audit["id"])
        issue_audit_findings(audit["id"], findings_underpayment_cents=0,
                             audit_cost_cents=0)
        closed = validate_success(api.close_audit(audit["id"], AUDITOR))
        assert closed["status"] == "CLOSED", (
            "Audit at issued+365d succeeds: the boundary is inclusive"
        )

        advance_clock("2027-08-02T00:00:00Z")
        resp = api.create_audit(
            {"artist_id": sc["artist"]["id"],
             "scope_statement_id": statement["id"]},
            sc["artist_headers"])
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_CLOSED)


class TestLogicalClock:
    def test_clock_sweep_fires_all_time_transitions_with_counts(self, api):
        """PRD: "Advancing the clock runs a sweep that applies every time-driven
        transition due at the new instant."
        PRD: "The sweep response reports per-category counts under the keys
        `agreements_expired`, `agreements_sunset`, `agreements_closed`,
        `options_lapsed`, `opportunities_expired`, `statements_acknowledged`, and
        `team_members_ended`."

        Design: Corner/endpoints/clock_sweep_fires_all_time_transitions_with_counts
        """
        sc = setup_artist_team(stage_name="Sweep Act",
                                   term_start="2026-01-01", term_end="2026-07-31")
        # Bound the BM's assignment to 2026-08-05; the agent stays open-ended.
        bounded_bm = add_team_member(sc["artist"]["id"], "BUSINESS_MANAGER",
                                     "BM Sw", window_end="2026-08-05")
        option = create_option(
            sc, window=("2026-07-01T00:00:00Z", "2026-08-15T00:00:00Z"))
        opp = create_opportunity(sc, offer_expiry_date="2026-08-10")
        statement = generate_and_issue_statement(sc, "2026-06-01", "2026-06-30",
                                                 "ACCRUAL")

        counts = advance_clock("2026-09-15T00:00:00Z")
        assert counts["agreements_expired"] == 1
        assert counts["agreements_sunset"] == 1
        assert counts["agreements_closed"] == 0
        assert counts["options_lapsed"] == 1
        assert counts["opportunities_expired"] == 1
        assert counts["statements_acknowledged"] == 1
        assert counts["team_members_ended"] == 1

        agreement = refresh_agreement(sc)
        assert agreement["status"] == "SUNSET", (
            "sunset_months 12 > 0, so EXPIRED moves to SUNSET, not CLOSED"
        )
        assert agreement["sunset_start_date"] == "2026-08-01"
        assert agreement["sunset_end_date"] == "2027-07-31", (
            "2026-08-01 + 12 months - 1 day"
        )
        assert validate_success(api.get_option(option["id"], ADMIN))["status"] == "LAPSED"
        assert validate_success(
            api.get_opportunity(opp["id"], ADMIN))["status"] == "EXPIRED"
        assert get_success_data(
            api.get_statement(statement["id"], sc["bm_headers"]))["status"] == (
                "ACKNOWLEDGED")
        assert validate_success(
            api.get_team_member(bounded_bm["id"], ADMIN))["status"] == "ENDED"
        assert validate_success(
            api.get_team_member(sc["agent"]["id"], ADMIN))["status"] == "ACTIVE"

    def test_clock_default_is_fixed_and_monotonic(self, api):
        """PRD: "At startup the clock reads exactly 2026-08-01T00:00:00Z."
        PRD: "A `FirmAdmin` advances it through the clock-driving capability by
        supplying `to_iso8601`, which must be at or after the current logical
        time; a regression is rejected with `ERR_INVALID_REQUEST`."
        PRD: "`issued_at` is stamped from the clock, `dispute_window_ends_at`
        opens thirty days later"

        Design: Corner/cross_cutting_layers/clock_default_is_fixed_and_monotonic
        """
        sc = setup_artist_team(stage_name="Time Act", with_agent=False)
        statement = generate_and_issue_statement(sc, "2026-06-01", "2026-06-30",
                                                 "ACCRUAL")
        assert statement["issued_at"].startswith("2026-08-01T00:00:00"), (
            "The fixed startup default, never wall-clock time"
        )
        assert statement["dispute_window_ends_at"].startswith("2026-08-31T00:00:00")

        advance_clock("2026-09-01T00:00:00Z")
        resp = api.set_clock("2026-08-15T00:00:00Z", ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_deemed_acceptance_after_dispute_window(self, api):
        """PRD: "`ISSUED` statements whose dispute window has lapsed with no
        active dispute move to `ACKNOWLEDGED` (deemed acceptance)."
        PRD: "The sweep response reports per-category counts under the keys
        `agreements_expired`, `agreements_sunset`, `agreements_closed`,
        `options_lapsed`, `opportunities_expired`, `statements_acknowledged`, and
        `team_members_ended`."

        Design: Corner/state_machines/deemed_acceptance_after_dispute_window
        """
        sc = setup_artist_team(stage_name="Deem Act", with_agent=False)
        statement = generate_and_issue_statement(sc, "2026-06-01", "2026-06-30",
                                                 "ACCRUAL")
        assert statement["status"] == "ISSUED"

        counts = advance_clock("2026-09-01T00:00:00Z")
        assert counts["statements_acknowledged"] == 1
        after = get_success_data(api.get_statement(statement["id"],
                                                   sc["bm_headers"]))
        assert after["status"] == "ACKNOWLEDGED", (
            "Deemed acceptance: no artist action occurred"
        )
