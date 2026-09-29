"""Reconciliation penalties, the settlement cascade and the compensating reopen."""

from test_helpers import (
    add_line,
    assert_money_equal,
    assert_posture,
    assert_statement_status,
    assert_total_count,
    assert_unremitted_ledger,
    create_escrow_account,
    create_policy_file,
    create_statement,
    ids_of,
    issue_policy,
    reconcile_statement,
    read_agency,
    reopen_statement,
    set_clock,
    settle_statement,
    submit_statement,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OFFICER


class TestReconciliationPenalties:
    """The filing fee is strict on its boundary and the penalty rides on top of it."""

    def test_late_filing_fee_and_unreported_penalty_total_seventy_five_thousand(
        self, api, env
    ):
        """Three reported policies, one hidden 500,000 policy, filed on 2026-08-20.

        PRD: "A late-filing fee of two hundred fifty dollars — 25,000 cents — applies
        when the calendar date of `submitted_at` falls strictly after the fifteenth day
        following `period_end`; a filing landing exactly on that fifteenth day carries no
        fee, because the comparison is strict."

        Design: Corner/calculations/constants_applied_late_filing_fee_plus_unreported_penalty_totals_seventy_five_thousand
        """
        reported_files = []
        for _ in range(3):
            policy_file = create_policy_file(
                api, env, closing_date="2026-07-20", gross_premium_cents=33_333
            )
            issue_policy(api, env, policy_file["id"])
            reported_files.append(policy_file)
        hidden = create_policy_file(
            api, env, closing_date="2026-07-20", gross_premium_cents=500_000
        )
        issue_policy(api, env, hidden["id"])

        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        for policy_file in reported_files:
            add_line(api, env, statement["id"], policy_file["id"], 33_333)
        set_clock(api, "2026-08-20T00:00:00Z")
        submitted = submit_statement(api, env, statement["id"])
        assert_money_equal(
            submitted["reported_gross_premium_cents"],
            99_999,
            "reported_gross_premium_cents",
        )

        reconciled = reconcile_statement(api, statement["id"])

        assert_statement_status(reconciled, "RECONCILED")
        assert_money_equal(
            reconciled["expected_gross_premium_cents"],
            599_999,
            "expected_gross_premium_cents",
        )
        assert_money_equal(reconciled["variance_cents"], 500_000, "variance_cents")
        assert reconciled["unreported_policy_count"] == 1, (
            "exactly one expected policy carries no line, so unreported_policy_count "
            f"must be 1, got {reconciled['unreported_policy_count']}"
        )
        assert_money_equal(
            reconciled["unreported_premium_cents"],
            500_000,
            "unreported_premium_cents",
        )
        assert_money_equal(
            reconciled["late_fee_cents"],
            75_000,
            "late_fee_cents (25,000 filing fee plus a 50,000 unreported penalty)",
        )
        assert_money_equal(
            reconciled["underwriter_share_cents"],
            20_001,
            "underwriter_share_cents",
        )

        agency = read_agency(api, env.agency_id)
        assert agency["unreported_policy_count"] == 1, (
            "the agency mirrors the statement's count, so it must read 1, got "
            f"{agency['unreported_policy_count']}"
        )
        assert_posture(agency, "OPEN")

    def test_filing_exactly_on_the_fifteenth_day_carries_no_fee(self, api, env):
        """A July period filed at 2026-08-15 sits on the boundary, so the fee stays 0.

        PRD: "A late-filing fee of two hundred fifty dollars — 25,000 cents — applies
        when the calendar date of `submitted_at` falls strictly after the fifteenth day
        following `period_end`; a filing landing exactly on that fifteenth day carries no
        fee, because the comparison is strict."

        Design: Difficulty/boundary_precision_check/reconciliation_at_exact_grace_boundary_yields_zero_fee_and_zero_unreported
        """
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        for _ in range(2):
            policy_file = create_policy_file(
                api, env, closing_date="2026-07-20", gross_premium_cents=1_000_000
            )
            issued = issue_policy(api, env, policy_file["id"])
            assert issued["issuance_elapsed_days"] == 12, (
                "2026-07-20 to 2026-08-01 is 12 whole days, got "
                f"{issued['issuance_elapsed_days']}"
            )
            add_line(api, env, statement["id"], policy_file["id"], 1_000_000)

        set_clock(api, "2026-08-15T00:00:00Z")
        submit_statement(api, env, statement["id"])
        reconciled = reconcile_statement(api, statement["id"])

        assert_money_equal(reconciled["late_fee_cents"], 0, "late_fee_cents")
        assert_money_equal(
            reconciled["expected_gross_premium_cents"],
            2_000_000,
            "expected_gross_premium_cents",
        )
        assert_money_equal(reconciled["variance_cents"], 0, "variance_cents")
        assert reconciled["reconciled_at"] is not None, (
            "reconciled_at is stamped with the clock instant, but it is null"
        )

    def test_a_fully_reported_period_leaves_both_unreported_outputs_at_zero(
        self, api, env
    ):
        """With every expected policy on a line the penalty component is 0 as well.

        PRD: "Where every expected policy does appear on a line,
        `unreported_policy_count` and `unreported_premium_cents` are both 0 and the
        penalty component is 0 as well."

        Design: Difficulty/boundary_precision_check/reconciliation_at_exact_grace_boundary_yields_zero_fee_and_zero_unreported
        """
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        for _ in range(2):
            policy_file = create_policy_file(
                api, env, closing_date="2026-07-20", gross_premium_cents=1_000_000
            )
            issue_policy(api, env, policy_file["id"])
            add_line(api, env, statement["id"], policy_file["id"], 1_000_000)

        set_clock(api, "2026-08-15T00:00:00Z")
        submit_statement(api, env, statement["id"])
        reconciled = reconcile_statement(api, statement["id"])

        assert reconciled["unreported_policy_count"] == 0, (
            "no expected policy is missing a line, so unreported_policy_count must be "
            f"0, got {reconciled['unreported_policy_count']}"
        )
        assert_money_equal(
            reconciled["unreported_premium_cents"], 0, "unreported_premium_cents"
        )
        assert_money_equal(reconciled["late_fee_cents"], 0, "late_fee_cents")
        assert_money_equal(
            reconciled["underwriter_share_cents"], 400_000, "underwriter_share_cents"
        )
        assert_money_equal(
            reconciled["agency_retention_cents"], 1_600_000, "agency_retention_cents"
        )

        agency = read_agency(api, env.agency_id)
        assert agency["unreported_policy_count"] == 0, (
            "the agency mirrors a clean statement, so its count must be 0, got "
            f"{agency['unreported_policy_count']}"
        )
        assert_posture(agency, "OPEN")


class TestSettlementCascade:
    """CASCADE-C: settlement remits the reported files and unwinds the ledger."""

    def test_settlement_remits_the_reported_policies_and_clears_the_ledger(
        self, api, env
    ):
        """Three 20,000,000 policies settle for 12,000,000 and leave nothing unremitted.

        PRD: "Hop 2 fires because the statement became `SETTLED`: every referenced policy
        whose `remittance_status` is `REPORTED` moves to `REMITTED`, while `DISPUTED`
        policies are left exactly where they are."

        Design: Difficulty/transitive_cascade/cascade_c_settlement_remits_policies_clears_ledger_and_relaxes_posture
        """
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        policy_ids = []
        for closing_date in ("2026-07-05", "2026-07-12", "2026-07-20"):
            policy_file = create_policy_file(
                api, env, closing_date=closing_date, gross_premium_cents=20_000_000
            )
            issue_policy(api, env, policy_file["id"])
            add_line(api, env, statement["id"], policy_file["id"], 20_000_000)
            policy_ids.append(policy_file["id"])
        assert_unremitted_ledger(read_agency(api, env.agency_id), 60_000_000)

        submit_statement(api, env, statement["id"])
        reconciled = reconcile_statement(api, statement["id"])
        assert_money_equal(reconciled["variance_cents"], 0, "variance_cents")
        assert_money_equal(reconciled["late_fee_cents"], 0, "late_fee_cents")
        assert_money_equal(
            reconciled["underwriter_share_cents"], 12_000_000, "underwriter_share_cents"
        )

        settled = settle_statement(api, statement["id"], 12_000_000)

        assert_statement_status(settled, "SETTLED")
        assert_money_equal(
            settled["settled_amount_cents"], 12_000_000, "settled_amount_cents"
        )
        assert settled["settled_at"] is not None, (
            "settled_at is stamped with the clock instant, but it is null"
        )

        remitted, meta = validate_paginated(
            api.list_policy_files(
                OFFICER,
                params={"agency_id": env.agency_id, "remittance_status": "REMITTED"},
            )
        )
        assert_total_count(meta, 3)
        assert sorted(ids_of(remitted)) == sorted(policy_ids), (
            "all three reported files must have moved to REMITTED, got "
            f"{sorted(ids_of(remitted))}"
        )
        assert_unremitted_ledger(read_agency(api, env.agency_id), 0)

    def test_settlement_relaxes_the_posture_and_leaves_an_open_account_open(
        self, api, env
    ):
        """The ledger drop returns the agency to `OPEN`; the account was never restricted.

        PRD: "Hop 5 fires when that recomputation leaves `FROZEN` or `RESTRICTED` and
        lands on `OPEN`: every escrow account of the agency whose `status` is
        `RESTRICTED` moves back to `OPEN`."

        Design: Difficulty/transitive_cascade/cascade_c_settlement_remits_policies_clears_ledger_and_relaxes_posture
        """
        account = create_escrow_account(api, env)
        assert account["status"] == "OPEN", (
            f"a new escrow account opens in OPEN, got {account['status']}"
        )

        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        for closing_date in ("2026-07-05", "2026-07-12", "2026-07-20"):
            policy_file = create_policy_file(
                api, env, closing_date=closing_date, gross_premium_cents=20_000_000
            )
            issue_policy(api, env, policy_file["id"])
            add_line(api, env, statement["id"], policy_file["id"], 20_000_000)
        restricted = read_agency(api, env.agency_id)
        assert_unremitted_ledger(restricted, 60_000_000)
        assert_posture(restricted, "RESTRICTED")

        submit_statement(api, env, statement["id"])
        reconcile_statement(api, statement["id"])
        settle_statement(api, statement["id"], 12_000_000)

        relaxed = read_agency(api, env.agency_id)
        assert_posture(relaxed, "OPEN")
        assert relaxed["unreported_policy_count"] == 0, (
            "every expected policy was reported, so the count must be 0, got "
            f"{relaxed['unreported_policy_count']}"
        )
        after = validate_success(api.get_escrow_account(account["id"], OFFICER))
        assert after["status"] == "OPEN", (
            "the account was never RESTRICTED, so the conditional hop is a no-op and it "
            f"must still read OPEN, got {after['status']}"
        )


class TestStatementReopen:
    """The compensating action restores the ledger to its exact pre-settlement value."""

    def test_reopen_restores_the_unremitted_ledger_exactly(self, api, env):
        """60,000,000 unremitted, settled to 0, and reopened back to exactly 60,000,000.

        PRD: "From `SETTLED` back to `DRAFT`: `settled_at`, `reconciled_at` and
        `submitted_at` are all reset to null; `expected_gross_premium_cents`,
        `variance_cents`, `unreported_policy_count`, `unreported_premium_cents` and
        `late_fee_cents` are all reset to 0; every referenced policy whose
        `remittance_status` is `REMITTED` moves back to `REPORTED` and every one that is
        `DISPUTED` moves back to `UNREPORTED`; the agency's `unremitted_premium_cents` is
        recomputed, restoring it to exactly its pre-settlement value; the agency's
        `unreported_policy_count` is recomputed from that agency's most recently
        reconciled statement, becoming 0 when no statement of the agency remains
        reconciled; `oversight_posture` is recomputed; and `Agency.version` is
        incremented by 1."

        Design: Difficulty/compensating_invariant/unremitted_premium_ledger_restored_exactly_by_statement_reopen
        """
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        for closing_date in ("2026-07-05", "2026-07-12"):
            policy_file = create_policy_file(
                api, env, closing_date=closing_date, gross_premium_cents=30_000_000
            )
            issue_policy(api, env, policy_file["id"])
            add_line(api, env, statement["id"], policy_file["id"], 30_000_000)
        assert_unremitted_ledger(read_agency(api, env.agency_id), 60_000_000)

        submit_statement(api, env, statement["id"])
        reconciled = reconcile_statement(api, statement["id"])
        assert_money_equal(reconciled["late_fee_cents"], 0, "late_fee_cents")
        assert_money_equal(
            reconciled["underwriter_share_cents"], 12_000_000, "underwriter_share_cents"
        )
        settle_statement(api, statement["id"], 12_000_000)
        assert_unremitted_ledger(read_agency(api, env.agency_id), 0)

        reopened = reopen_statement(
            api, statement["id"], reopen_reason="Premium restated by the underwriter"
        )

        assert_statement_status(reopened, "DRAFT")
        assert reopened["reopen_count"] == 1, (
            f"the first reopen sets reopen_count to 1, got {reopened['reopen_count']}"
        )
        assert reopened["reopen_reason"] == "Premium restated by the underwriter", (
            f"the supplied reason must be persisted, got {reopened['reopen_reason']!r}"
        )
        assert reopened["settled_at"] is None, (
            f"settled_at must be reset to null, got {reopened['settled_at']!r}"
        )
        assert reopened["reconciled_at"] is None, (
            f"reconciled_at must be reset to null, got {reopened['reconciled_at']!r}"
        )
        assert reopened["submitted_at"] is None, (
            f"submitted_at must be reset to null, got {reopened['submitted_at']!r}"
        )
        assert_money_equal(
            reopened["expected_gross_premium_cents"],
            0,
            "expected_gross_premium_cents after reopen",
        )
        assert_money_equal(
            reopened["late_fee_cents"], 0, "late_fee_cents after reopen"
        )
        assert_unremitted_ledger(read_agency(api, env.agency_id), 60_000_000)

    def test_reopen_returns_the_files_to_reported_and_the_posture_to_restricted(
        self, api, env
    ):
        """The remitted files fall back to `REPORTED` and the restored ledger restricts.

        PRD: "Otherwise, the posture is `RESTRICTED` when any one of six conditions
        holds: `appointment_status` is `PENDING_REVIEW`; `financial_review_status` is
        anything other than `ACCEPTED`; `escrow_standing` is `WATCH`;
        `open_critical_finding_count` is at least 1; `unreported_policy_count` is at
        least 3; or `unremitted_premium_cents` is strictly greater than five hundred
        thousand dollars, that is, greater than 50,000,000 cents."

        Design: Difficulty/compensating_invariant/unremitted_premium_ledger_restored_exactly_by_statement_reopen
        """
        statement = create_statement(api, env, "2026-07-01", "2026-07-31")
        policy_ids = []
        for closing_date in ("2026-07-05", "2026-07-12"):
            policy_file = create_policy_file(
                api, env, closing_date=closing_date, gross_premium_cents=30_000_000
            )
            issue_policy(api, env, policy_file["id"])
            add_line(api, env, statement["id"], policy_file["id"], 30_000_000)
            policy_ids.append(policy_file["id"])
        assert_posture(read_agency(api, env.agency_id), "RESTRICTED")

        submit_statement(api, env, statement["id"])
        reconcile_statement(api, statement["id"])
        settle_statement(api, statement["id"], 12_000_000)
        assert_posture(read_agency(api, env.agency_id), "OPEN")

        reopen_statement(
            api, statement["id"], reopen_reason="Premium restated by the underwriter"
        )

        reported, meta = validate_paginated(
            api.list_policy_files(
                OFFICER,
                params={"agency_id": env.agency_id, "remittance_status": "REPORTED"},
            )
        )
        assert_total_count(meta, 2)
        assert sorted(ids_of(reported)) == sorted(policy_ids), (
            "both files must step back from REMITTED to REPORTED, got "
            f"{sorted(ids_of(reported))}"
        )
        agency = read_agency(api, env.agency_id)
        assert_unremitted_ledger(agency, 60_000_000)
        assert_posture(agency, "RESTRICTED")
        _remitted, remitted_meta = validate_paginated(
            api.list_policy_files(
                OFFICER,
                params={"agency_id": env.agency_id, "remittance_status": "REMITTED"},
            )
        )
        assert_total_count(remitted_meta, 0)
