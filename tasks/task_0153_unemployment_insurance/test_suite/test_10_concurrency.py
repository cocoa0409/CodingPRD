"""Concurrency guarantees — PRD §3.8.

Tests scenarios PRD explicitly nails down with a specific error_id.
For pairs where PRD only commits to first-writer-wins without naming
the loser's error_id, we use assert_exactly_one_succeeds.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    apply_extension_payload,
    create_appeal_payload,
    create_weekly_certification_payload,
    date_to_iso,
    make_claimant_headers,
    n_work_search_entries,
    next_certifiable_saturday,
    repay_overpayment_payload,
    run_race,
    setup_active_pandemic_extension,
    setup_claim_with_n_approved_certs,
    setup_filed_appeal_on_denied_claim,
    setup_outstanding_overpayment,
    validate_error,
    create_eligible_claim,
    create_denied_claim,
    file_appeal,
)


class TestDuplicateWeekRace:

    def test_two_simultaneous_same_week_certifications_serialize(self, api):
        """PRD §3.8: "Two weekly certifications submitted simultaneously
        with the same week_ending_date on the same claim_id serialize
        on the unique (claim_id, week_ending_date) constraint; the
        first writer wins and the second is rejected with
        ERR_DUPLICATE_WEEK."
        """
        bundle = create_eligible_claim()
        claim, cm = bundle["claim"], bundle["claimant"]
        sat = next_certifiable_saturday(claim)
        headers = make_claimant_headers(cm["id"])
        payload = create_weekly_certification_payload(
            week_ending_date=date_to_iso(sat),
        )
        results = run_race(
            lambda: api.create_weekly_certification(
                claim["id"], dict(payload), headers,
            ),
            lambda: api.create_weekly_certification(
                claim["id"], dict(payload), headers,
            ),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        # Loser's specific error_id is named in PRD §3.8.
        loser = outcome["failures"][0]
        body = loser.json()
        err = body.get("data", {}).get("error_id")
        assert err == ApiErrorId.ERR_DUPLICATE_WEEK.value, (
            f"PRD §3.8 names ERR_DUPLICATE_WEEK as the loser; got {err}"
        )


class TestAppealUniquenessRace:

    def test_two_simultaneous_appeals_on_same_subject(self, api):
        """PRD §3.8: "Two appeals filed simultaneously on the same
        (subject_type, subject_id) pair serialize on the appeals
        uniqueness constraint; the loser receives
        ERR_APPEAL_ALREADY_FILED."
        """
        bundle = create_denied_claim()
        claim, cm = bundle["claim"], bundle["claimant"]
        headers = make_claimant_headers(cm["id"])
        payload = create_appeal_payload(
            claim_id=claim["id"],
            subject_type="MONETARY_DETERMINATION",
            subject_id=claim["id"],
            assigned_appeal_officer_id="appeal-officer-0001",
        )
        results = run_race(
            lambda: api.create_appeal(dict(payload), headers),
            lambda: api.create_appeal(dict(payload), headers),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        err = loser.json().get("data", {}).get("error_id")
        assert err == ApiErrorId.ERR_APPEAL_ALREADY_FILED.value, (
            f"PRD §3.8 names ERR_APPEAL_ALREADY_FILED as the loser; "
            f"got {err}"
        )


class TestRepayBalanceRace:

    def test_two_repayments_summing_above_balance(self, api):
        """PRD §3.8: "Two simultaneous repayments to the same
        Overpayment whose sum exceeds the current balance_cents
        serialize on a row-level lock; the writer whose post-decrement
        balance would fall below zero is rejected with
        ERR_REPAY_EXCEEDS_BALANCE."

        For the loser to observe ERR_REPAY_EXCEEDS_BALANCE (priority 14
        per §2.10) rather than ERR_INVALID_STATE (priority 5), the
        Overpayment must remain in OUTSTANDING after the winner commits.
        We therefore choose per-request amounts that are individually
        valid (<= current balance) but whose SUM exceeds balance; the
        winner leaves a non-zero residual balance so the OP stays
        OUTSTANDING, and the loser's request fails on the per-request
        balance guard rather than the state check.
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        cm = bundle["claimant"]
        headers = make_claimant_headers(cm["id"])
        balance = op["balance_cents"]
        # Each repayment is strictly more than half the balance and
        # strictly less than the full balance. Each is valid in
        # isolation; their sum exceeds balance, and the winner's
        # decrement leaves a non-zero residual so the OP is still
        # OUTSTANDING when the loser arrives.
        amount = (balance // 2) + 1
        assert 0 < amount < balance
        assert 2 * amount > balance
        results = run_race(
            lambda: api.repay_overpayment(
                op["id"], repay_overpayment_payload(amount), headers,
            ),
            lambda: api.repay_overpayment(
                op["id"], repay_overpayment_payload(amount), headers,
            ),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        err = loser.json().get("data", {}).get("error_id")
        assert err == ApiErrorId.ERR_REPAY_EXCEEDS_BALANCE.value, (
            f"PRD §3.8 names ERR_REPAY_EXCEEDS_BALANCE as the loser; "
            f"got {err}"
        )


class TestExtensionRace:

    def test_two_simultaneous_apply_extension(self, api):
        """PRD §3.8: "Two apply-extension requests on the same EXHAUSTED
        claim serialize on the extension_id immutability rule; the
        first writer wins and the second is rejected with
        ERR_EXTENSION_ALREADY_APPLIED."
        """
        ext = setup_active_pandemic_extension()
        bundle = setup_claim_with_n_approved_certs(
            n_approvals=13,
            max_weeks_target=13,
        )
        from test_helpers import get_claim
        claim = get_claim(bundle["claim"]["id"])
        if claim["status"] != "EXHAUSTED":
            pytest.skip(
                "could not drive claim into EXHAUSTED; PRD min-weeks "
                "clamp prevents accelerating exhaustion"
            )
        headers = make_claimant_headers(bundle["claimant"]["id"])
        payload = apply_extension_payload(ext["id"])
        results = run_race(
            lambda: api.apply_extension(claim["id"], dict(payload), headers),
            lambda: api.apply_extension(claim["id"], dict(payload), headers),
        )
        outcome = assert_race_outcome(
            results, expected_successes=1, expected_failures=1,
        )
        loser = outcome["failures"][0]
        err = loser.json().get("data", {}).get("error_id")
        assert err == ApiErrorId.ERR_EXTENSION_ALREADY_APPLIED.value, (
            f"PRD §3.8 names ERR_EXTENSION_ALREADY_APPLIED as the loser; "
            f"got {err}"
        )
