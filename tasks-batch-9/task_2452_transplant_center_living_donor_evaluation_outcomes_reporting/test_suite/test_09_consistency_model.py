"""Every cross-aggregate consequence is visible in the response that caused it."""
from test_helpers import (
    add_operating_room,
    book_theatre,
    create_outcome_review,
    file_claim,
    get_chain,
    refresh_program,
    setup_validated_paired_loop,
    setup_donated_donor,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client


def test_the_adjudication_response_already_carries_the_recomputed_ledger():
    """PRD §3.9: "An approval first checks the donor's lifetime headroom."
    PRD §3.9: "The insurance bucket has a per-claim ceiling of 600,000 cents (six thousand
    dollars), but only when the claim's `coverage_source` is `RECIPIENT_INSURANCE`; for any
    other coverage source the insurance headroom is zero, so a claim filed against the
    program fund never touches insurance even where a ceiling would have existed."
    PRD §3.9: "The grant bucket is only open to claims whose `claim_type` is `TRAVEL` or
    `LOST_WAGES`; for a `MEDICAL` claim the grant headroom is zero."
    PRD §2.9: "A program's `donor_fund_committed_cents` is the sum of `fund_part_cents`
    over every donor cost claim whose donor belongs to that program and whose `status` is
    `ADJUDICATED`."
    PRD §2.9: "Committed plus remaining always equals the pool, and remaining is always
    between 0 and the pool inclusive, after every adjudication, denial and reversal."
    PRD §3.9: "Claims are listed through their donor, filtered on `claim_type` and
    `status`, with `limit` and `offset`, and the listing exposes each claim's
    estimated-versus-adjudicated split."

    Design: Corner/consistency_model/adjudication_response_already_carries_the_recomputed_ledger
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]
    opening = refresh_program(env)
    assert opening["donor_fund_pool_cents"] == 5000000
    assert opening["donor_fund_committed_cents"] == 0
    assert opening["donor_fund_remaining_cents"] == 5000000
    claim = file_claim(
        env,
        donor_id,
        claim_type="MEDICAL",
        coverage_source="PROGRAM_FUND",
        submitted_amount_cents=900000,
    )
    assert claim["estimated_reimbursement_cents"] == 900000

    adjudicated = validate_success(
        api_client.adjudicate_claim(
            claim["id"], {"decision": "APPROVE"}, env["finance_headers"]
        )
    )

    assert adjudicated["status"] == "ADJUDICATED"
    assert adjudicated["fund_part_cents"] == 900000
    assert adjudicated["insurance_part_cents"] == 0
    assert adjudicated["grant_part_cents"] == 0
    assert adjudicated["adjudicated_reimbursement_cents"] == 900000
    assert adjudicated["unfunded_cents"] == 0

    program = validate_success(
        api_client.get_program(env["program_id"], env["finance_headers"])
    )
    assert program["donor_fund_committed_cents"] == 900000, "no second write was needed"
    assert program["donor_fund_remaining_cents"] == 4100000
    assert (
        program["donor_fund_committed_cents"] + program["donor_fund_remaining_cents"]
        == program["donor_fund_pool_cents"]
    )

    _rows, meta = validate_paginated(
        api_client.list_donor_cost_claims(
            donor_id, env["coordinator_headers"], params={"status": "ADJUDICATED"}
        )
    )
    assert meta["total_count"] == 1


def test_the_finalization_response_already_shows_the_frozen_posture_and_suspended_chain():
    """PRD §3.8: "On success `status` becomes `FINALIZED` — terminal — and `finalized_at`
    is stamped with the current logical clock."
    PRD §3.8: "The cascade then runs in three further hops: because the review is now
    finalized, the program's `compliance_posture` is re-derived, where a `FLAGGED` level
    drives `FROZEN` and a `WATCH` level drives `RESTRICTED`; because the posture entered
    `FROZEN`, every chain of the program whose status is `DRAFT` or `VALIDATED` moves to
    `SUSPENDED`; and because those chains are suspended, each of their `OFFER_SENT` segments
    reverts to `PLANNED` with the offer fields cleared and every `ACTIVE` procedure booking
    of *any* of their segments moves to `CANCELLED` with a `cancel_reason_code` of
    `POSTURE_FROZEN`, decrementing each room's `reserved_minutes_total`."
    PRD §3.8: "`expected_survivor_count` is `cohort_size` multiplied by
    `expected_survival_rate_used`, rounded half up to two decimal places."
    PRD §3.8: "Otherwise `oe_ratio` is `observed_survivor_count` divided by
    `expected_survivor_count`, rounded half up to **four** decimal places, and `flag_level`
    is `FLAGGED` when `oe_ratio` is strictly below 0.85, `WATCH` when it is strictly below
    0.95 but not below 0.85, and `NONE` otherwise."
    PRD §3.8: "A new review's `status` is `DRAFT` and `finalized_at` is null; a draft
    review does not yet affect the program's posture at all."
    PRD §3.5: "Chains are listed with optional `program_id`, `chain_type` and `status`
    filters plus `limit` and `offset`, and read individually to expose `version`,
    `segment_count`, `is_closed_loop`, `total_planned_cit_minutes` and
    `committed_donor_count`."

    Design: Corner/consistency_model/finalization_response_already_shows_the_frozen_posture_and_suspended_chain
    """
    env = setup_validated_paired_loop()
    assert env["clock"] == "2026-08-08T00:00:00Z"
    room = add_operating_room(env, "OR-1")
    booking = book_theatre(
        env,
        room["id"],
        env["segment_one"]["id"],
        "DONOR_RECOVERY",
        "2026-08-09T06:00:00Z",
        "2026-08-09T10:00:00Z",
    )
    assert booking["duration_minutes"] == 240
    review = create_outcome_review(env, cohort_size=25, observed_survivor_count=16)
    assert review["status"] == "DRAFT"
    assert review["expected_survivor_count"] == 20.0
    assert refresh_program(env)["compliance_posture"] == "OPEN", "a draft does not bite"

    finalized = validate_success(
        api_client.finalize_outcome_review(review["id"], env["quality_headers"])
    )

    assert finalized["status"] == "FINALIZED"
    assert finalized["finalized_at"].startswith("2026-08-08T00:00:00")
    assert finalized["oe_ratio"] == 0.8
    assert finalized["flag_level"] == "FLAGGED"
    assert finalized["requires_improvement_plan"] is True

    assert refresh_program(env)["compliance_posture"] == "FROZEN"
    assert get_chain(env, env["chain"]["id"])["status"] == "SUSPENDED"

    cancelled = validate_success(
        api_client.get_procedure_booking(booking["id"], env["coordinator_headers"])
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason_code"] == "POSTURE_FROZEN"

    rooms = validate_success(
        api_client.list_program_operating_rooms(env["program_id"], env["admin_headers"])
    )
    assert rooms[0]["reserved_minutes_total"] == 0, "the ledger was decremented"

    _chains, meta = validate_paginated(
        api_client.list_exchange_chains(
            env["coordinator_headers"],
            params={"program_id": env["program_id"], "status": "SUSPENDED"},
        )
    )
    assert meta["total_count"] == 1
