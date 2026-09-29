"""Two conserved quantities restored by a compensating write: money, then a population count."""
from test_helpers import (
    DEFAULT_DONOR_FUND_POOL_CENTS,
    file_and_approve_claim,
    file_claim,
    get_donor,
    get_recipient,
    get_segment,
    refresh_program,
    reverse_claim,
    setup_committed_paired_loop,
    setup_donated_donor,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


def _committed_donor_ids(env):
    rows, _meta = validate_paginated(
        api_client.list_donor_candidates(
            env["coordinator_headers"],
            params={
                "program_id": env["program_id"],
                "overall_status": "CHAIN_COMMITTED",
            },
        )
    )
    return sorted(row["id"] for row in rows)


def test_reversing_an_approved_claim_restores_the_fund_ledger_with_no_residue():
    """PRD §2.9: "A program's `donor_fund_committed_cents` is the sum of
    `fund_part_cents` over every donor cost claim whose donor belongs to that program
    and whose `status` is `ADJUDICATED`."
    PRD §2.9: "Committed plus remaining always equals the pool, and remaining is
    always between 0 and the pool inclusive, after every adjudication, denial and
    reversal."
    PRD §3.9: "It moves the claim to `REVERSED` — terminal — records the reason,
    decreases the program's `donor_fund_committed_cents` by this claim's
    `fund_part_cents` and recomputes `donor_fund_remaining_cents` so that the ledger
    identity of §2.9 still holds exactly."

    Design: Difficulty/compensating_invariant/donor_fund_ledger_restored_by_claim_reversal
    """
    env = setup_donated_donor()
    program = refresh_program(env)
    assert program["donor_fund_pool_cents"] == DEFAULT_DONOR_FUND_POOL_CENTS
    assert program["donor_fund_committed_cents"] == 0
    assert program["donor_fund_remaining_cents"] == DEFAULT_DONOR_FUND_POOL_CENTS

    claim = file_and_approve_claim(
        env,
        env["donor_one"]["id"],
        claim_type="MEDICAL",
        coverage_source="RECIPIENT_INSURANCE",
        submitted_amount_cents=1000000,
    )
    assert claim["status"] == "ADJUDICATED"
    assert claim["insurance_part_cents"] == 600000, "the per-claim insurance ceiling"
    assert claim["grant_part_cents"] == 0, "a MEDICAL claim is not grant-eligible"
    assert claim["fund_part_cents"] == 400000
    assert claim["adjudicated_reimbursement_cents"] == 1000000
    assert claim["unfunded_cents"] == 0

    committed = refresh_program(env)
    assert committed["donor_fund_committed_cents"] == 400000
    assert committed["donor_fund_remaining_cents"] == 4600000
    assert (
        committed["donor_fund_committed_cents"] + committed["donor_fund_remaining_cents"]
        == committed["donor_fund_pool_cents"]
    )

    reversed_claim = reverse_claim(
        env, claim["id"], reversal_reason_code="DUPLICATE_SUBMISSION"
    )

    assert reversed_claim["status"] == "REVERSED"
    assert reversed_claim["reversal_reason_code"] == "DUPLICATE_SUBMISSION"
    assert reversed_claim["fund_part_cents"] == 400000, "amounts are retained for audit"

    restored = refresh_program(env)
    assert restored["donor_fund_committed_cents"] == 0, (
        "the 400000 fund share is removed, not the 1000000 payout"
    )
    assert restored["donor_fund_remaining_cents"] == DEFAULT_DONOR_FUND_POOL_CENTS
    assert (
        restored["donor_fund_committed_cents"] + restored["donor_fund_remaining_cents"]
        == restored["donor_fund_pool_cents"] == DEFAULT_DONOR_FUND_POOL_CENTS
    )


def test_reversal_also_restores_the_donor_lifetime_headroom_it_had_consumed():
    """PRD §3.9: "The claim's amounts are retained for audit but the claim leaves every
    aggregate: this donor's lifetime consumption and this donor's grant-pool
    consumption both drop by this claim's respective parts, so a later claim for the
    same donor sees the restored headroom."
    PRD §3.9: "Sum `adjudicated_reimbursement_cents` over this donor's claims whose
    `status` is `ADJUDICATED`; the donor's lifetime cap is 1,500,000 cents (fifteen
    thousand dollars), and the headroom is the cap minus that prior total."

    Design: Difficulty/compensating_invariant/donor_fund_ledger_restored_by_claim_reversal
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]
    first = file_and_approve_claim(
        env,
        donor_id,
        claim_type="MEDICAL",
        coverage_source="RECIPIENT_INSURANCE",
        submitted_amount_cents=1000000,
    )
    assert first["adjudicated_reimbursement_cents"] == 1000000
    reverse_claim(env, first["id"], reversal_reason_code="DUPLICATE_SUBMISSION")

    replacement = file_claim(
        env,
        donor_id,
        claim_type="MEDICAL",
        coverage_source="RECIPIENT_INSURANCE",
        submitted_amount_cents=1000000,
    )
    adjudicated = validate_success(
        api_client.adjudicate_claim(
            replacement["id"], {"decision": "APPROVE"}, env["finance_headers"]
        )
    )

    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["adjudicated_reimbursement_cents"] == 1000000, (
        "the reversed claim no longer consumes any of the 1,500,000-cent lifetime cap"
    )
    assert adjudicated["insurance_part_cents"] == 600000
    assert adjudicated["fund_part_cents"] == 400000
    assert adjudicated["unfunded_cents"] == 0

    program = refresh_program(env)
    assert program["donor_fund_committed_cents"] == 400000, (
        "only the live claim is in the sum; the reversed row left it entirely"
    )
    assert program["donor_fund_remaining_cents"] == 4600000


def test_breaking_a_committed_chain_zeroes_the_count_and_releases_both_donors():
    """PRD §2.9: "Summed over all chains of a program, `committed_donor_count` must
    equal the number of that program's donor candidates whose `overall_status` is
    `CHAIN_COMMITTED`."
    PRD §2.9: "Breaking a chain must therefore release every donor it locked and zero
    its `committed_donor_count` in the same request, so the two sides never disagree
    mid-flight."
    PRD §3.6: "Breaking sets the chain to `BROKEN` with the reason recorded, moves
    every non-withdrawn segment whose status is `PLANNED`, `OFFER_SENT` or `ACCEPTED`
    to `WITHDRAWN`, releases every donor of this chain whose `overall_status` is
    `CHAIN_COMMITTED` back to `APPROVED` or `CONDITIONAL_APPROVED` according to that
    donor's stored `final_risk_index`, zeroes `committed_donor_count`, and moves every
    procedure booking of this chain's segments whose status is `ACTIVE` to `CANCELLED`
    with a `cancel_reason_code` of `CHAIN_BROKEN`, decrementing each room's
    `reserved_minutes_total` by that booking's `duration_minutes`."

    Design: Difficulty/compensating_invariant/chain_commitment_count_conserved_on_break
    """
    env = setup_committed_paired_loop()
    assert env["chain"]["committed_donor_count"] == 2
    assert get_donor(env, env["donor_one"]["id"])["final_risk_index"] == 0.0
    assert get_donor(env, env["donor_two"]["id"])["final_risk_index"] == 0.0

    broken = validate_success(
        api_client.break_chain(
            env["chain"]["id"],
            {"break_reason_code": "LOGISTICS_FAILURE"},
            env["coordinator_headers"],
        )
    )

    assert broken["status"] == "BROKEN"
    assert broken["break_reason_code"] == "LOGISTICS_FAILURE"
    assert broken["committed_donor_count"] == 0

    assert get_segment(env, env["segment_one"]["id"])["status"] == "WITHDRAWN"
    assert get_segment(env, env["segment_two"]["id"])["status"] == "WITHDRAWN"

    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "APPROVED", (
        "released per final_risk_index 0.0, not demoted to CONDITIONAL_APPROVED"
    )
    assert get_donor(env, env["donor_two"]["id"])["overall_status"] == "APPROVED"

    assert get_recipient(env, env["recipient_one"]["id"])["listing_status"] == "ACTIVE"
    assert get_recipient(env, env["recipient_two"]["id"])["listing_status"] == "ACTIVE", (
        "recipients return to the waitlist untouched"
    )


def test_the_population_side_of_the_commitment_identity_empties_with_the_count():
    """PRD §2.9: "Summed over all chains of a program, `committed_donor_count` must
    equal the number of that program's donor candidates whose `overall_status` is
    `CHAIN_COMMITTED`."
    PRD §2.9: "A chain's `committed_donor_count` is the number of distinct
    `donor_candidate_id` values across that chain's segments whose status is not
    `WITHDRAWN` and whose own `created_at` is at or before the chain's `committed_at`,
    evaluated only while the chain's status is `COMMITTED` or `EXECUTING`; for every
    other chain status it is 0, including for a chain that has reached `COMPLETED`."

    Design: Difficulty/compensating_invariant/chain_commitment_count_conserved_on_break
    """
    env = setup_committed_paired_loop()
    locked = _committed_donor_ids(env)
    assert locked == sorted([env["donor_one"]["id"], env["donor_two"]["id"]]), (
        "both sides of the identity read 2 before the break"
    )
    assert env["chain"]["committed_donor_count"] == len(locked)

    broken = validate_success(
        api_client.break_chain(
            env["chain"]["id"],
            {"break_reason_code": "LOGISTICS_FAILURE"},
            env["coordinator_headers"],
        )
    )

    assert broken["committed_donor_count"] == 0
    assert _committed_donor_ids(env) == [], (
        "the population side is 0 and matches the summed committed_donor_count of 0"
    )
