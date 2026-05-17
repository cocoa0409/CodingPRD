"""Concurrency: pinned race outcomes — PRD §3.3, §3.5.

Coverage targets:
- Two /pay on the same APPROVED claim: exactly one wins; loser sees
  ERR_INVALID_STATE.
- Two /pay across separate claims sharing a plan year whose sum
  exceeds available_balance: exactly one wins; the loser is rejected
  with ERR_INSUFFICIENT_BALANCE.
- Two /contributions whose individual amounts fit but together
  exceed the cap: exactly one is accepted.
- Two POST /ops-runs with the same (kind, as_of_date): exactly one
  recorded; second rejected with ERR_DUPLICATE_OPS_RUN.

The PRD pins each race outcome explicitly, so the asserted loser
error_ids are warranted.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_contribution_payload,
    create_ops_run_payload,
    iso_datetime_utc,
    make_adjudicator_headers,
    post_contribution,
    run_race,
    setup_approved_claim,
    setup_active_plan_year,
    validate_error,
)


# ===========================================================================
# Pay race on same claim — PRD §3.5
# ===========================================================================
class TestPayRaceSameClaim:

    def test_two_pays_on_same_approved_claim_first_wins(self, api):
        """PRD §3.5: "When two adjudicators race to pay the same
        APPROVED claim, exactly one transitions Claim.status from
        APPROVED to PAID; the loser observes Claim.status no longer
        APPROVED and is rejected with ERR_INVALID_STATE."

        Claim: race two /pay calls on the same APPROVED claim — one
        succeeds, the other returns ERR_INVALID_STATE.
        """
        holder, acct, py, qe, claim = setup_approved_claim(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=200_000, claim_cents=20_000,
        )
        # Two distinct adjudicator headers — neither equals the
        # submitter, so SoD does not pre-empt.
        h1 = make_adjudicator_headers("pay-race-1")
        h2 = make_adjudicator_headers("pay-race-2")
        results = run_race(
            lambda: api.pay_claim(claim["id"], h1),
            lambda: api.pay_claim(claim["id"], h2),
        )
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        # The loser MUST be ERR_INVALID_STATE per PRD §3.5.
        loser = outcomes["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == (
            ApiErrorId.ERR_INVALID_STATE.value
        ), (
            f"loser error_id expected ERR_INVALID_STATE, got "
            f"{body['data'].get('error_id')!r}"
        )


# ===========================================================================
# Pay race overdrawing plan year balance — PRD §3.5
# ===========================================================================
class TestPayRaceBalance:

    def test_two_pays_exceeding_balance_only_one_wins(self, api):
        """PRD §3.5: "When two pays race against two different APPROVED
        claims sharing one plan year and each fits the balance
        individually but the sum would overdraw, serialization runs
        against PlanYear.version and the balance check is evaluated
        against the post-write counters; at most one succeeds and
        the second is rejected with ERR_INSUFFICIENT_BALANCE."

        Claim: build two APPROVED claims at $60 each against a plan
        year funded with only $100; race their /pay calls. At most
        one succeeds; if one fails, it returns ERR_INSUFFICIENT_BALANCE.
        """
        from test_helpers import (
            approve_claim,
            create_claim,
            seed_qualified_expense,
            setup_funded_plan_year,
            submit_claim,
        )
        holder, acct, py = setup_funded_plan_year(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE",
            contribution_cents=10_000,  # $100
        )
        qe = seed_qualified_expense(
            category="MEDICAL",
            eligible_account_types=["HSA"],
            requires_dependent=False,
        )
        c1 = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2025, 6, 15),
            expense_code=qe["code"], amount_cents=6_000,
        )
        c2 = create_claim(
            account_holder=holder, account=acct,
            service_date=iso_datetime_utc(2025, 6, 16),
            expense_code=qe["code"], amount_cents=6_000,
        )
        submit_claim(c1["id"], account_holder=holder)
        submit_claim(c2["id"], account_holder=holder)
        approve_claim(c1["id"])
        approve_claim(c2["id"])
        h1 = make_adjudicator_headers("bal-race-1")
        h2 = make_adjudicator_headers("bal-race-2")
        results = run_race(
            lambda: api.pay_claim(c1["id"], h1),
            lambda: api.pay_claim(c2["id"], h2),
        )
        # Exactly one succeeds; the other gets
        # ERR_INSUFFICIENT_BALANCE per PRD §3.5.
        outcomes = assert_race_outcome(results, 1, 1)
        loser = outcomes["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == (
            ApiErrorId.ERR_INSUFFICIENT_BALANCE.value
        ), (
            f"loser error_id expected ERR_INSUFFICIENT_BALANCE, got "
            f"{body['data'].get('error_id')!r}"
        )


# ===========================================================================
# Contribution cap race — PRD §3.3
# ===========================================================================
class TestContributionCapRace:

    def test_two_contributions_exceeding_cap_only_one_wins(
        self, api, plan_admin_headers,
    ):
        """PRD §3.3: "When two contributions race to post against the
        same plan year and each fits the cap individually but together
        exceed contribution_cap_cents + catch_up_cap_cents, the system
        serializes them against PlanYear.version and evaluates each
        cap check against the post-write counters. Exactly one
        succeeds; the loser is rejected with
        ERR_CONTRIBUTION_CAP_EXCEEDED."

        Claim: HEALTH_FSA cap = 320_000. Two contributions of 200_000
        each both individually fit but together exceed the cap.
        Exactly one succeeds; the loser is
        ERR_CONTRIBUTION_CAP_EXCEEDED.
        """
        _, _, py = setup_active_plan_year(
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="NONE", calendar_year=2025,
        )
        payload1 = create_contribution_payload(
            amount_cents=200_000, source="PAYROLL",
        )
        payload2 = create_contribution_payload(
            amount_cents=200_000, source="DIRECT",
        )
        results = run_race(
            lambda: api.create_contribution(
                py["id"], payload1, plan_admin_headers,
            ),
            lambda: api.create_contribution(
                py["id"], payload2, plan_admin_headers,
            ),
        )
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == (
            ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value
        ), (
            f"loser error_id expected ERR_CONTRIBUTION_CAP_EXCEEDED, "
            f"got {body['data'].get('error_id')!r}"
        )


# ===========================================================================
# Duplicate ops-runs race — PRD §3.7
# ===========================================================================
class TestOpsRunRace:

    def test_two_ops_runs_same_kind_and_date_only_one_wins(
        self, api, plan_admin_headers,
    ):
        """PRD §3.7: "Two concurrent ops runs with the same kind and
        as_of_date are serialized on the uniqueness of the pair;
        exactly one is recorded and the second is rejected with
        ERR_DUPLICATE_OPS_RUN."

        Claim: race two POST /ops-runs with identical (kind,
        as_of_date) — one succeeds, the other gets
        ERR_DUPLICATE_OPS_RUN.
        """
        advance_clock_to(iso_datetime_utc(2026, 6, 1))
        payload = create_ops_run_payload(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        results = run_race(
            lambda: api.create_ops_run(payload, plan_admin_headers),
            lambda: api.create_ops_run(payload, plan_admin_headers),
        )
        outcomes = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcomes["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == (
            ApiErrorId.ERR_DUPLICATE_OPS_RUN.value
        ), (
            f"loser error_id expected ERR_DUPLICATE_OPS_RUN, got "
            f"{body['data'].get('error_id')!r}"
        )
