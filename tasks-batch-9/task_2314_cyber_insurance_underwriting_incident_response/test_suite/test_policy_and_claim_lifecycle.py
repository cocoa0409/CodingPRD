"""Two state machines that do not walk in a straight line.

The policy carries two independent status dimensions (PRD §3.5), and the
proof-of-loss negotiation on a claim is a bounded cycle (PRD §3.8).
"""
from test_helpers import ADJUSTER_2_HEADERS, ADJUSTER_HEADERS, UNDERWRITER_HEADERS
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import assert_instant, assert_money, data_of, get_rows


ATTEST_77_50 = {
    "MFA_PRIVILEGED": "FULL",
    "OFFLINE_BACKUPS": "FULL",
    "EDR_COVERAGE": "PARTIAL",
    "EMAIL_FILTERING": "PARTIAL",
    "INCIDENT_RESPONSE_PLAN": "PARTIAL",
}


# ==========================================================================
# lifecycle_status and limit_status move on different triggers
# ==========================================================================
def _bitwise_policy_exhausted_by_one_payment(api):
    """A 250,000 aggregate policy whose single accepted proof consumes the whole tower."""
    chain = X.bound_policy(
        api,
        account_spec=C.ACCOUNT_BITWISE,
        attestations=ATTEST_77_50,
        requested_aggregate_limit_usd=250000,
        requested_retention_usd=0,
        dependent_bi_definition="BROAD_SYSTEM_FAILURE",
        coverage_sections=list(C.SMALL_TOWER),
        findings=[],
    )
    assert_money(chain["policy"]["premium_usd"], 7500.00, "premium_usd")

    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-01T00:00:00Z",
        outage_start_at="2026-09-01T00:00:00Z",
        outage_end_at="2026-09-05T16:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=250000,
    )
    proof = X.file_proof(
        api,
        claim["id"],
        claimed_bi_loss_usd=400000,
        trailing_12m_revenue_usd=43800000,
        prior_year_same_period_revenue_usd=1200000,
        prior_year_same_period_hours=200,
        gross_profit_margin_pct=0.8,
        extra_expense_usd=0,
        mitigation_savings_usd=0,
    )
    accepted = data_of(api.accept_proof_of_loss(proof["id"], ADJUSTER_2_HEADERS))
    return chain, claim, accepted


def test_limit_status_reaches_exhausted_while_lifecycle_status_stays_inforce(api):
    """A 400000.00 indemnity against a 250,000 aggregate exhausts capacity, not the contract.

    PRD §3.5: "`limit_status` describes the erosion of aggregate capacity and moves
    between `INTACT`, `PARTIALLY_ERODED`, and `EXHAUSTED` purely as a function of
    payment activity; it has no terminal state and can travel in both directions."
    The unplaceable remainder lands on the claim rather than being dropped.

    Design: Difficulty/non_linear_state_machine/policy_lifecycle_and_limit_dimensions_move_independently
    """
    chain, claim, accepted = _bitwise_policy_exhausted_by_one_payment(api)

    assert_money(accepted["assessed_indemnity_usd"], 400000.00, "assessed_indemnity_usd")

    policy = X.read_policy(api, chain["policy"]["id"])
    assert policy["lifecycle_status"] == "INFORCE", policy["lifecycle_status"]
    assert policy["limit_status"] == "EXHAUSTED", policy["limit_status"]
    assert_money(policy["aggregate_limit_remaining_usd"], 0.00, "aggregate_limit_remaining_usd")

    settled = X.read_claim(api, claim["id"])
    assert settled["status"] == "SETTLED", settled["status"]
    assert_money(settled["paid_total_usd"], 250000.00, "paid_total_usd")
    assert_money(settled["unallocated_loss_usd"], 150000.00, "unallocated_loss_usd")


def test_cancellation_moves_lifecycle_only_and_leaves_the_settled_claim_alone(api):
    """Cancelling an exhausted policy stamps cancelled_at and touches nothing else.

    PRD §3.6: "Claims that have already reached `PROOF_REVIEW` or gone beyond it —
    `INFO_REQUESTED`, `APPROVED_FOR_PAYMENT`, `SETTLED`, `DENIED` — are left entirely
    untouched, because the indemnity determination on those files is already under
    way." The erosion dimension is unaffected by the contractual one.

    Design: Difficulty/non_linear_state_machine/policy_lifecycle_and_limit_dimensions_move_independently
    """
    chain, claim, _accepted = _bitwise_policy_exhausted_by_one_payment(api)

    cancelled = data_of(
        api.cancel_policy(
            chain["policy"]["id"],
            F.cancel_policy_payload("INSURED_REQUEST"),
            UNDERWRITER_HEADERS,
        )
    )

    assert cancelled["lifecycle_status"] == "CANCELLED", cancelled["lifecycle_status"]
    assert cancelled["cancellation_reason"] == "INSURED_REQUEST", cancelled["cancellation_reason"]
    assert_instant(cancelled["cancelled_at"], "2026-09-10T00:00:00Z", "cancelled_at")
    assert cancelled["limit_status"] == "EXHAUSTED", cancelled["limit_status"]

    settled = X.read_claim(api, claim["id"])
    assert settled["status"] == "SETTLED", settled["status"]
    assert_money(settled["paid_total_usd"], 250000.00, "paid_total_usd")
    assert_money(settled["reserved_amount_usd"], 0.00, "reserved_amount_usd")


# ==========================================================================
# The bounded proof-review negotiation
# ==========================================================================
PROOF_FINANCIALS = {
    "claimed_bi_loss_usd": 250000,
    "trailing_12m_revenue_usd": 43800000,
    "prior_year_same_period_revenue_usd": 1200000,
    "prior_year_same_period_hours": 200,
    "gross_profit_margin_pct": 0.62,
    "extra_expense_usd": 60000,
    "mitigation_savings_usd": 20000,
}


def _claim_at_second_review_round(api):
    """Two information requests already issued and a third proof under review."""
    chain = X.bound_policy(
        api,
        account_spec=C.ACCOUNT_AURORA,
        attestations=C.ATTEST_95,
        requested_aggregate_limit_usd=5000000,
        requested_retention_usd=250000,
        coverage_sections=list(C.STANDARD_TOWER),
        findings=[F.scan_finding("EMAIL_FILTERING", "HIGH", "PARTIAL")],
    )
    X.set_clock(api, "2026-09-10T00:00:00Z")
    claim = X.confirmed_claim(
        api,
        chain["policy"]["id"],
        incident_type="RANSOMWARE",
        incident_discovered_at="2026-09-05T00:00:00Z",
        outage_start_at="2026-09-05T00:00:00Z",
        outage_end_at="2026-09-08T00:00:00Z",
        covered_section_keys=["FIRST_PARTY_RESPONSE", "BUSINESS_INTERRUPTION"],
        initial_reserve_usd=250000,
    )
    first = X.file_proof(api, claim["id"], **PROOF_FINANCIALS)
    X.request_info(api, first["id"], "Provide audited monthly revenue schedules.")
    second = X.file_proof(api, claim["id"], **PROOF_FINANCIALS)
    X.request_info(api, second["id"], "Revenue schedules still unsigned.")
    third = X.file_proof(api, claim["id"], **PROOF_FINANCIALS)
    return claim, [first, second, third]


def test_third_information_request_denies_the_claim_for_insufficient_proof(api):
    """With proof_review_round already at 2 the request is not granted; the claim is denied.

    PRD §3.8: "When `proof_review_round` already stands at 2 before the request, the
    round is not granted; instead the proof moves to `SUPERSEDED`, the claim moves
    from `PROOF_REVIEW` to `DENIED` with `denial_reason` recorded as
    `PROOF_INSUFFICIENT` and `reserved_amount_usd` zeroed to 0.00, every vendor
    engagement of the claim in `AUTHORIZED` or `ACTIVE` moves to `TERMINATED` with
    each affected firm's `active_engagement_count` decremented, and the claim's
    `version` is incremented by 1."

    Design: Difficulty/non_linear_state_machine/claim_proof_review_cycle_terminates_at_max_rounds
    """
    claim, proofs = _claim_at_second_review_round(api)
    before = X.read_claim(api, claim["id"])
    assert before["status"] == "PROOF_REVIEW", before["status"]
    assert before["proof_review_round"] == 2, before["proof_review_round"]

    X.request_info(api, proofs[2]["id"], "Third submission still lacks the margin workpapers.")

    after = X.read_claim(api, claim["id"])
    assert after["status"] == "DENIED", after["status"]
    assert after["denial_reason"] == "PROOF_INSUFFICIENT", after["denial_reason"]
    assert after["proof_review_round"] == 2, after["proof_review_round"]
    assert_money(after["reserved_amount_usd"], 0.00, "reserved_amount_usd")


def test_every_proof_of_the_denied_claim_ends_superseded_with_no_payment(api):
    """All three filings terminate in SUPERSEDED and nothing ever posts.

    PRD §3.8: "The proof is created in `UNDER_REVIEW`, and any earlier proof of the
    same claim sitting in `UNDER_REVIEW` or `INFO_REQUESTED` is moved to
    `SUPERSEDED` with its `version` incremented by 1 — a claim never has two live
    proofs."

    Design: Difficulty/non_linear_state_machine/claim_proof_review_cycle_terminates_at_max_rounds
    """
    claim, proofs = _claim_at_second_review_round(api)

    X.request_info(api, proofs[2]["id"], "Third submission still lacks the margin workpapers.")

    rows = get_rows(
        api.list_proofs_of_loss(ADJUSTER_HEADERS, params={"incident_claim_id": claim["id"]})
    )
    assert len(rows) == 3, rows
    for row in rows:
        assert row["status"] == "SUPERSEDED", row

    assert X.list_payments_for_claim(api, claim["id"]) == []
