"""Limit breach lifecycle: acknowledge fork, SoD remediation, terminal state,
de-escalation gating.

Difficulty instance: breach_acknowledge_fork_remediate_vs_escalate.
Corner instances: remediated_breach_is_terminal,
remediate_while_still_breached_rejected,
deescalation_blocked_while_red_present.
"""
from test_helpers import (
    ApiErrorId,
    USER_OFFICER_1,
    USER_OFFICER_2,
    USER_OFFICER_3,
    assert_limit_breach,
    make_analyst_headers,
    make_board_limit,
    make_committee_headers,
    make_funding_source,
    make_metric,
    make_officer_headers,
    post_reading,
    setup_red_metric_with_limit,
    setup_wholesale_breach,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = make_analyst_headers("ta_1")
OFFICER = make_officer_headers("ro_1")
COMMITTEE = make_committee_headers("lc_1")


class TestBreachFork:
    def test_breach_acknowledge_fork_remediate_vs_escalate(self, api, officer_headers):
        """PRD §3.7: "The breach lifecycle is a fork guarded by segregation of
        duties. A `RiskOfficer` acknowledges an `OPEN` breach, moving it to
        `ACKNOWLEDGED` and recording `acknowledged_by_user_id`. From
        `ACKNOWLEDGED`, a `LiquidityCommittee` member may escalate to
        `ESCALATED`. Remediation closes the loop but re-proves the numbers at
        remediate time: the current value of the breach's subject is
        re-evaluated against the limit — at or below `limit_value` for
        `ABOVE_BREACHES`, at or above it for `BELOW_BREACHES` — and if the
        breach still stands the request fails with `ERR_LIMIT_STILL_BREACHED`.
        From `ACKNOWLEDGED`, either a `RiskOfficer` or a `LiquidityCommittee`
        member may remediate; from `ESCALATED`, remediation is committee-only,
        and a `RiskOfficer` attempting that branch is rejected with
        `ERR_FORBIDDEN`. In both branches, when an `acknowledged_by_user_id` is
        recorded, the remediator's `X-User-ID` must differ from it
        (`ERR_SOD_VIOLATION`)."
        PRD §3.5: "Detection rides along: the evaluation immediately runs
        breach detection against every board limit on `WHOLESALE_RELIANCE_PCT`
        and `TOP_COUNTERPARTY_PCT`, and the response's `breaches_created`
        counts how many new breaches were raised."

        Design: Difficulty/non_linear_state_machine/breach_acknowledge_fork_remediate_vs_escalate
        """
        limit1 = make_board_limit(subject="WHOLESALE_RELIANCE_PCT",
                                  direction="ABOVE_BREACHES", limit_value=4000,
                                  severity="BOARD")
        limit2 = make_board_limit(subject="TOP_COUNTERPARTY_PCT",
                                  direction="ABOVE_BREACHES", limit_value=5000,
                                  severity="REGULATORY")
        make_funding_source(counterparty_name="RetailA", channel="RETAIL_DEPOSIT",
                            balance_cents=6_000_000_000)
        make_funding_source(counterparty_name="W1", channel="WHOLESALE_UNSECURED",
                            balance_cents=4_000_000_000, matures_in_days=20)
        make_funding_source(counterparty_name="W2", channel="BROKERED",
                            balance_cents=1_000_000_000, matures_in_days=15)

        evaluation = validate_success(api.run_funding_evaluation(officer_headers))
        # wholesale 5000/11000 -> 4545 > 4000; top counterparty 6000/11000 -> 5454 > 5000.
        assert evaluation["breaches_created"] == 2, (
            f"both limits breach, got {evaluation['breaches_created']}"
        )

        b1_list, _ = validate_paginated(api.list_limit_breaches(limit1["id"], officer_headers))
        b2_list, _ = validate_paginated(api.list_limit_breaches(limit2["id"], officer_headers))
        b1, b2 = b1_list[0], b2_list[0]

        acknowledger = make_officer_headers(USER_OFFICER_1)
        b1 = validate_success(api.acknowledge_breach(b1["id"], acknowledger))
        b2 = validate_success(api.acknowledge_breach(b2["id"], acknowledger))
        assert b1["acknowledged_by_user_id"] == USER_OFFICER_1
        b2 = validate_success(api.escalate_breach(b2["id"], make_committee_headers("lc_9")))
        assert b2["status"] == "ESCALATED"

        # Dilute: total 15000000000; wholesale 5000/15000 -> 3333 <= 4000;
        # top counterparty 6000/15000 -> 4000 <= 5000. Both subjects are now
        # within their limits.
        make_funding_source(counterparty_name="RetailB", channel="RETAIL_DEPOSIT",
                            balance_cents=4_000_000_000)

        # ACKNOWLEDGED branch: a RiskOfficer other than the acknowledger remediates.
        remediated_b1 = validate_success(api.remediate_breach(
            b1["id"], {"remediation_note": "diluted wholesale share"},
            make_officer_headers(USER_OFFICER_2),
        ))
        assert remediated_b1["status"] == "REMEDIATED"
        assert remediated_b1["remediated_by_user_id"] == USER_OFFICER_2

        # ESCALATED branch: committee-only — a RiskOfficer is rejected.
        resp = api.remediate_breach(
            b2["id"], {"remediation_note": "officer attempt on escalated"},
            make_officer_headers(USER_OFFICER_3),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        remediated_b2 = validate_success(api.remediate_breach(
            b2["id"], {"remediation_note": "committee sign-off"},
            make_committee_headers("lc_1"),
        ))
        assert remediated_b2["status"] == "REMEDIATED"
        assert remediated_b2["remediated_by_user_id"] == "lc_1"

    def test_remediate_by_acknowledger_violates_sod(self, api):
        """PRD §3.7: "In both branches, when an `acknowledged_by_user_id` is
        recorded, the remediator's `X-User-ID` must differ from it
        (`ERR_SOD_VIOLATION`)."
        PRD §3.7: "Remediation closes the loop but re-proves the numbers at
        remediate time: the current value of the breach's subject is
        re-evaluated against the limit — at or below `limit_value` for
        `ABOVE_BREACHES`, at or above it for `BELOW_BREACHES`".

        Design: Difficulty/non_linear_state_machine/breach_acknowledge_fork_remediate_vs_escalate
        """
        _limit, breach = setup_wholesale_breach(acknowledger=USER_OFFICER_1)
        # Dilute so the subject value is back within the limit.
        make_funding_source(counterparty_name="RetailB", channel="RETAIL_DEPOSIT",
                            balance_cents=5_000_000_000)
        resp = api.remediate_breach(
            breach["id"], {"remediation_note": "self-remediation"},
            make_officer_headers(USER_OFFICER_1),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)


class TestBreachTerminal:
    def test_remediated_breach_is_terminal(self, api, committee_headers, officer_headers):
        """PRD §3.7: "From `ACKNOWLEDGED`, either a `RiskOfficer` or a
        `LiquidityCommittee` member may remediate; from `ESCALATED`,
        remediation is committee-only".
        PRD §3.6: "Entering `SEVERE` or `CRISIS` from a strictly lower level
        escalates every `OPEN` breach to `ESCALATED` automatically, leaving its
        `acknowledged_by_user_id` null."
        PRD §3.9: "Every transition in this section is available only from its
        named from-state; invoking one against a playbook or action standing in
        any other status is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/remediated_breach_is_terminal
        """
        metric, limit, breach = setup_red_metric_with_limit()
        assert breach["status"] == "ESCALATED", (
            f"the fresh OPEN breach is auto-escalated on the SEVERE entry, got {breach['status']}"
        )
        # Corrective reading: value 500 <= limit 4000, so the subject is back
        # within the limit at remediate time.
        post_reading(metric["id"], 500, observed_at="2026-08-02T00:00:00Z")

        remediated = validate_success(api.remediate_breach(
            breach["id"], {"remediation_note": "metric back within limit"}, committee_headers,
        ))
        assert remediated["status"] == "REMEDIATED"

        # REMEDIATED is terminal: acknowledge is no longer admissible.
        resp = api.acknowledge_breach(breach["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        final = validate_success(api.get_breach(breach["id"], officer_headers))
        assert final["status"] == "REMEDIATED", (
            f"the failed acknowledge left the state untouched, got {final['status']}"
        )


class TestRemediateRecheck:
    def test_remediate_while_still_breached_rejected(self, api):
        """PRD §3.7: "Remediation closes the loop but re-proves the numbers at
        remediate time: the current value of the breach's subject is
        re-evaluated against the limit — at or below `limit_value` for
        `ABOVE_BREACHES`, at or above it for `BELOW_BREACHES` — and if the
        breach still stands the request fails with `ERR_LIMIT_STILL_BREACHED`."

        Design: Corner/validations/remediate_while_still_breached_rejected
        """
        _limit, breach = setup_wholesale_breach(
            limit_value=4000, retail_cents=6_000_000_000,
            wholesale_sources=(("W1", "WHOLESALE_UNSECURED", 5_000_000_000, 20),),
            acknowledger=USER_OFFICER_1,
        )
        # Funding not diluted: wholesale share stays 4545 > 4000.
        resp = api.remediate_breach(
            breach["id"], {"remediation_note": "premature"},
            make_officer_headers(USER_OFFICER_2),
        )
        validate_error(resp, ApiErrorId.ERR_LIMIT_STILL_BREACHED)


class TestDeescalationBlocked:
    def test_deescalation_blocked_while_red_present(self, api, committee_headers):
        """PRD §3.6: "it additionally requires `red_count` and
        `open_breach_count` both at zero (`ERR_DEESCALATION_BLOCKED`
        otherwise)".
        PRD §3.6: "The raw level is `CRISIS` when at least two metrics are
        red; otherwise `SEVERE` when at least one is red".

        Design: Corner/validations/deescalation_blocked_while_red_present
        """
        m1 = make_metric(code="M1", name="m1")
        m2 = make_metric(code="M2", name="m2")
        post_reading(m1["id"], 6000)  # RED
        post_reading(m2["id"], 6000)  # RED -> red_count 2, posture auto-CRISIS
        # M2 corrected: red_count drops to 1, so raw_level SEVERE < CRISIS.
        post_reading(m2["id"], 500, observed_at="2026-08-02T00:00:00Z")

        resp = api.run_posture_evaluation(committee_headers)
        validate_error(resp, ApiErrorId.ERR_DEESCALATION_BLOCKED)
