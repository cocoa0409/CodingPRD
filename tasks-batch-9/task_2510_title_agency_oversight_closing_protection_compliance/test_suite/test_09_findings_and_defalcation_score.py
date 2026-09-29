"""The defalcation score, its two scoping variants and the adverse-closure cascade."""

from test_helpers import (
    assert_escrow_standing,
    assert_money_equal,
    assert_posture,
    assert_total_count,
    audit_findings,
    clear_finding,
    close_audit,
    create_audit,
    create_escrow_account,
    create_finding,
    escalate_finding,
    post_snapshot,
    read_agency,
    request_letter,
    review_audit,
    set_clock,
    submit_audit,
    submit_remediation,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AUDITOR, OFFICER


def _build_adverse_history(api, env):
    """Two escalated audits — one dated 2025-01-10, one dated 2026-07-05 — plus a spare
    account with no audit at all. Returns the second audit and that spare account."""
    set_clock(api, "2025-01-10T00:00:00Z")
    old_account = create_escrow_account(api, env)
    post_snapshot(
        api,
        env,
        old_account["id"],
        trial_balance_cents=4_000_000,
        snapshot_as_of="2025-01-10",
    )
    old_audit = create_audit(api, env, old_account["id"], as_of_date="2025-01-10")
    submit_audit(api, old_audit["id"])
    old_finding = audit_findings(api, old_audit["id"])[0]
    review_audit(api, old_audit["id"])
    escalate_finding(api, old_finding["id"], disposition_note="Trust shortfall confirmed")
    close_audit(api, old_audit["id"], "CLOSED_ADVERSE", note="Adverse closure 2025")

    set_clock(api, "2026-08-01T00:00:00Z")
    recent_account = create_escrow_account(api, env)
    post_snapshot(
        api,
        env,
        recent_account["id"],
        trial_balance_cents=8_000_000,
        snapshot_as_of="2026-07-05",
    )
    recent_audit = create_audit(api, env, recent_account["id"], as_of_date="2026-07-05")
    submit_audit(api, recent_audit["id"])
    recent_finding = audit_findings(api, recent_audit["id"])[0]
    review_audit(api, recent_audit["id"])
    escalate_finding(api, recent_finding["id"], disposition_note="Variance unexplained")
    spare_account = create_escrow_account(api, env)
    return recent_audit, recent_finding, spare_account


class TestDefalcationScoreVariants:
    """One history, two scopes: the closure window and the lifetime sweep disagree."""

    def test_closure_scores_the_rolling_window_and_drops_the_old_audit(self, api, env):
        """The 2025 audit falls outside 365 days, leaving 12 plus 8 and `COMPLIANT`.

        PRD: "When an escrow audit closure recomputes the score — either `CLOSED_CLEAN`
        or `CLOSED_ADVERSE` — the rolling-window variant applies: in scope are only rows
        dated on or after the logical clock's current date minus 365 days, where a finding
        is dated by its parent audit's `as_of_date`, an audit by its own `as_of_date`, and
        a claim by its `notice_date`."

        Design: Difficulty/dual_variant_calc/defalcation_score_rolling_window_versus_lifetime_uncleared
        """
        recent_audit, recent_finding, _spare = _build_adverse_history(api, env)
        assert recent_finding["severity"] == "HIGH", (
            "a 2,000,000 exposure sits above 1,000,000 and at most 5,000,000, so the "
            f"severity is HIGH, got {recent_finding['severity']}"
        )

        closed = close_audit(
            api, recent_audit["id"], "CLOSED_ADVERSE", note="Adverse closure 2026"
        )

        assert closed["status"] == "CLOSED_ADVERSE", (
            f"the audit must close adverse, got {closed['status']}"
        )
        agency = read_agency(api, env.agency_id)
        assert_money_equal(
            agency["defalcation_score"],
            20,
            "defalcation_score under the rolling window (12 for one high finding plus 8 "
            "for one adverse closure)",
        )
        assert_escrow_standing(agency, "COMPLIANT")

    def test_audit_creation_scores_the_lifetime_history_and_keeps_the_old_finding(
        self, api, env
    ):
        """The same history scores 53 and stands `WATCH` when a new audit is opened.

        PRD: "When an actor-initiated audit creation recomputes the score — of either
        `audit_type` — the lifetime variant applies instead: there is no date window at
        all and the agency's entire history is in scope, but findings whose `status` is
        `CLEARED` are excluded."

        Design: Difficulty/dual_variant_calc/defalcation_score_rolling_window_versus_lifetime_uncleared
        """
        recent_audit, _recent_finding, spare_account = _build_adverse_history(api, env)
        close_audit(
            api, recent_audit["id"], "CLOSED_ADVERSE", note="Adverse closure 2026"
        )
        after_closure = read_agency(api, env.agency_id)
        assert_money_equal(
            after_closure["defalcation_score"], 20, "defalcation_score after closure"
        )

        create_audit(api, env, spare_account["id"], as_of_date="2026-08-01")

        agency = read_agency(api, env.agency_id)
        assert_money_equal(
            agency["defalcation_score"],
            53,
            "defalcation_score under the lifetime variant (25 for one uncleared critical "
            "finding, 12 for one high finding and 16 for two adverse closures)",
        )
        assert_escrow_standing(agency, "WATCH")
        assert_posture(agency, "RESTRICTED")
        assert agency["defalcation_score"] != after_closure["defalcation_score"], (
            "the two variants must disagree on identical history, but both read "
            f"{agency['defalcation_score']}"
        )


class TestScoreThreshold:
    """The standing ladder compares with `>=`, so exactly 60 is the risk band."""

    def test_five_cleared_high_findings_land_on_exactly_sixty(self, api, env):
        """Clearances do not reduce the window score, so 5 times 12 flips the standing.

        PRD: "From the score, `escrow_standing` follows directly: `DEFALCATION_RISK` when
        the score is at least 60, otherwise `WATCH` when it is at least 30, and otherwise
        `COMPLIANT`."

        Design: Corner/calculations/threshold_defalcation_score_at_exactly_sixty_flips_standing_to_defalcation_risk
        """
        account = create_escrow_account(api, env)
        post_snapshot(api, env, account["id"])
        audit = create_audit(api, env, account["id"])
        submitted = submit_audit(api, audit["id"])
        assert_money_equal(
            submitted["reconciliation_variance_cents"], 0, "reconciliation_variance_cents"
        )
        assert submitted["open_finding_count"] == 0, (
            "a perfectly reconciled account raises no auto-finding, got "
            f"{submitted['open_finding_count']}"
        )

        findings = [
            create_finding(api, audit["id"], "NEGATIVE_FILE_BALANCE", 250_000)
            for _ in range(5)
        ]
        for finding in findings:
            assert finding["severity"] == "HIGH", (
                "NEGATIVE_FILE_BALANCE is HIGH by code, got "
                f"{finding['severity']}"
            )
            assert finding["is_repeat"] is False, (
                "all five share one parent audit, so none is a repeat, got "
                f"{finding['is_repeat']!r}"
            )
            submit_remediation(api, env, finding["id"])
            clear_finding(
                api,
                finding["id"],
                cleared_amount_cents=250_000,
                disposition_note="File balance funded",
            )
        review_audit(api, audit["id"])
        before_close = validate_success(api.get_escrow_audit(audit["id"], AUDITOR))
        assert before_close["risk_tier"] == "LOW", (
            f"every finding is CLEARED, so the tier is LOW, got {before_close['risk_tier']}"
        )

        closed = close_audit(
            api, audit["id"], "CLOSED_CLEAN", note="All five file balances funded"
        )

        assert closed["status"] == "CLOSED_CLEAN", (
            f"the audit must close clean, got {closed['status']}"
        )
        agency = read_agency(api, env.agency_id)
        assert_money_equal(
            agency["defalcation_score"],
            60,
            "defalcation_score (five high findings at 12 apiece, uncapped and unreduced "
            "by the clearances)",
        )
        assert_escrow_standing(agency, "DEFALCATION_RISK")
        assert_posture(agency, "FROZEN")
        assert agency["open_critical_finding_count"] == 0, (
            "the freeze comes from the standing, not from a critical finding, so the "
            f"critical counter must be 0, got {agency['open_critical_finding_count']}"
        )


class TestAdverseClosureCascade:
    """CASCADE-A runs five hops out of one adverse closure."""

    def _freeze_setup(self, api, env):
        letter = request_letter(api, env, requested_coverage_cents=30_000_000)
        assert letter["status"] == "REQUESTED", (
            "the letter is requested while the posture is still OPEN, so it must land on "
            f"REQUESTED, got {letter['status']}"
        )
        account = create_escrow_account(api, env)
        post_snapshot(api, env, account["id"], trial_balance_cents=4_000_000)
        audit = create_audit(api, env, account["id"])
        submit_audit(api, audit["id"])
        variance_finding = audit_findings(api, audit["id"])[0]
        assert variance_finding["severity"] == "CRITICAL", (
            "a 6,000,000 variance exposure is CRITICAL, got "
            f"{variance_finding['severity']}"
        )
        for _ in range(2):
            commingling = create_finding(api, audit["id"], "COMMINGLING", 1_000_000)
            assert commingling["severity"] == "CRITICAL", (
                "COMMINGLING is always CRITICAL, got "
                f"{commingling['severity']}"
            )
        review_audit(api, audit["id"])
        escalate_finding(
            api, variance_finding["id"], disposition_note="Trust shortfall confirmed"
        )
        return letter, account, audit

    def test_adverse_closure_scores_eighty_three_and_freezes_the_agency(self, api, env):
        """Three critical findings plus the closure reach 83, which is past 60.

        PRD: "Hop 2 fires because that recomputed score reached at least 60: the agency's
        `escrow_standing` becomes `DEFALCATION_RISK`."

        Design: Difficulty/transitive_cascade/cascade_a_adverse_closure_freezes_agency_declines_letter_and_spawns_successor
        """
        _letter, _account, audit = self._freeze_setup(api, env)

        closed = close_audit(
            api,
            audit["id"],
            "CLOSED_ADVERSE",
            note="Trust shortfall and commingling confirmed",
        )

        assert closed["status"] == "CLOSED_ADVERSE", (
            f"hop 1 must set the audit to CLOSED_ADVERSE, got {closed['status']}"
        )
        assert closed["closed_by_user_id"] == "officer-1", (
            f"closed_by_user_id must record the closer, got {closed['closed_by_user_id']!r}"
        )
        agency = read_agency(api, env.agency_id)
        assert_money_equal(
            agency["defalcation_score"],
            83,
            "defalcation_score (25 for each of three critical findings plus 8 for one "
            "adverse closure)",
        )
        assert_escrow_standing(agency, "DEFALCATION_RISK")
        assert_posture(agency, "FROZEN")

    def test_the_freeze_restricts_the_account_declines_the_letter_and_spawns_a_successor(
        self, api, env
    ):
        """Hops 4 and 5: the account, the letter and the auto-created audit.

        PRD: "Hop 4 fires because the posture became `FROZEN`: every escrow account of the
        agency whose `status` is `OPEN` moves to `RESTRICTED`, and every closing protection
        letter of the agency whose `status` is `REQUESTED` or `REFERRED` moves to
        `DECLINED`, both sets processed in ascending `created_at` order and the letters
        carrying `SYSTEM` as their `decided_by_user_id`."

        Design: Difficulty/transitive_cascade/cascade_a_adverse_closure_freezes_agency_declines_letter_and_spawns_successor
        """
        letter, account, audit = self._freeze_setup(api, env)

        close_audit(
            api,
            audit["id"],
            "CLOSED_ADVERSE",
            note="Trust shortfall and commingling confirmed",
        )

        frozen_account = validate_success(api.get_escrow_account(account["id"], OFFICER))
        assert frozen_account["status"] == "RESTRICTED", (
            f"the open account must move to RESTRICTED, got {frozen_account['status']}"
        )
        declined_letter = validate_success(api.get_letter(letter["id"], OFFICER))
        assert declined_letter["status"] == "DECLINED", (
            f"the outstanding letter must move to DECLINED, got {declined_letter['status']}"
        )
        assert declined_letter["decided_by_user_id"] == "SYSTEM", (
            "the cascade decides the letter, so the decider must be SYSTEM, got "
            f"{declined_letter['decided_by_user_id']!r}"
        )

        successors, meta = validate_paginated(
            api.list_escrow_audits(
                OFFICER, params={"follow_up_of_audit_id": audit["id"]}
            )
        )
        assert_total_count(meta, 1)
        successor = successors[0]
        assert successor["audit_type"] == "SURPRISE", (
            f"the successor audit must be a SURPRISE audit, got {successor['audit_type']}"
        )
        assert successor["status"] == "DRAFT", (
            f"the successor audit must open in DRAFT, got {successor['status']}"
        )
        assert successor["conducted_by_user_id"] == "SYSTEM", (
            "the successor audit is system-created, got "
            f"{successor['conducted_by_user_id']!r}"
        )
        assert successor["escrow_account_id"] == account["id"], (
            "the successor audit targets the same account, got "
            f"{successor['escrow_account_id']}"
        )
        agency = read_agency(api, env.agency_id)
        assert_money_equal(
            agency["defalcation_score"],
            83,
            "defalcation_score after the successor audit was auto-created",
        )
        assert_escrow_standing(agency, "DEFALCATION_RISK")
