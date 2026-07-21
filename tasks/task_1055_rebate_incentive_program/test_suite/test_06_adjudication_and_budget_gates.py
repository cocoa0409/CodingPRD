"""Adjudication: review, approval under the budget gate, denial and appeal."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjust_budget,
    api_client,
    attach_receipt,
    create_active_program,
    create_dealer_claimant,
    create_published_offer,
    deny_claim,
    list_ledger,
    make_dealer_headers,
    open_claim,
    read_claim,
    read_claimant,
    read_offer,
    read_program,
    set_clock,
    setup_claim_under_review,
    setup_denied_claim,
    setup_submitted_claim,
    validate_receipt,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
PROCESSOR = TEST_USERS["claims_processor_headers"]
BIG_RECEIPT = [{"sku": "TOOLS-A", "quantity": 5, "unit_price_cents": 400000}]
TWO_UNITS = [{"sku": "TOOLS-A", "quantity": 2, "unit_price_cents": 1000}]


def test_approve_directly_from_submitted_is_not_reviewable(api):
    """PRD §3.6: "A review attempt from a state that does not declare the
    transition is refused with `ERR_CLAIM_NOT_REVIEWABLE`, and any adjudication
    action attempted against a claim already resting in `APPROVED`, `REVOKED`,
    `WITHDRAWN` or `VOIDED` is refused with `ERR_CLAIM_ALREADY_TERMINAL`."
    PRD §3.6: "Approval is the moment the program's money is genuinely committed,
    and it carries five preconditions. The claim must be `UNDER_REVIEW`."

    Design: Corner/state_machines/approve_from_submitted_without_review_is_rejected
    """
    ctx = setup_submitted_claim(
        program_overrides={"name": "Skip Review Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Skip Review Offer"},
    )
    resp = api.approve_claim(ctx["claim"]["id"], PROCESSOR)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE.value)

    claim = read_claim(ctx["claim"]["id"])
    assert claim["adjudication_status"] == "SUBMITTED"
    assert claim["final_rebate_cents"] is None
    assert read_program(ctx["program"]["id"])["committed_cents"] == 0


def test_approval_requires_at_least_one_validated_receipt(api):
    """PRD §3.6: "At least one receipt of the claim must have `validated` true,
    else `ERR_NO_VALIDATED_RECEIPT` (HTTP 422)."

    Design: Corner/validations/approve_without_any_validated_receipt_is_rejected
    """
    ctx = setup_claim_under_review(
        validate_receipt_flag=False,
        program_overrides={"name": "Unvalidated Program"},
        budget_total_cents=100000000,
        offer_overrides={"name": "Unvalidated Offer"},
    )
    resp = api.approve_claim(ctx["claim"]["id"], PROCESSOR)
    validate_error(resp, ApiErrorId.ERR_NO_VALIDATED_RECEIPT.value)

    claim = read_claim(ctx["claim"]["id"])
    assert claim["adjudication_status"] == "UNDER_REVIEW"
    assert claim["final_rebate_cents"] is None
    assert read_program(ctx["program"]["id"])["committed_cents"] == 0


def test_appeal_on_day_thirty_one_is_out_of_window(api):
    """PRD §3.6: "the whole days between `denied_at` and the logical clock must be
    at most 30, so an appeal on day 30 is accepted and one on day 31 is refused
    with `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422)"

    Design: Corner/validations/appeal_after_thirty_one_days_is_out_of_window
    """
    ctx = setup_denied_claim(
        program_overrides={"name": "Appeal Window Program"},
        budget_total_cents=100000000,
        offer_overrides={
            "name": "Appeal Window Offer",
            "effective_end_date": "2026-12-01T00:00:00Z",
        },
        lines=TWO_UNITS,
    )
    set_clock("2026-08-10T00:00:00Z")

    resp = api.appeal_claim(
        ctx["claim"]["id"], {"appeal_note": "Proof attached by mail"}, ctx["headers"]
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED.value)

    claim = read_claim(ctx["claim"]["id"])
    assert claim["adjudication_status"] == "DENIED"
    assert claim["appeal_count"] == 0
    assert read_claimant(ctx["claimant"]["id"])["denied_claim_count"] == 1


def test_third_appeal_hits_the_appeal_ceiling(api):
    """PRD §3.6: "and `appeal_count` must be strictly less than 2, so a claim may
    be appealed twice in total and a third attempt is refused with
    `ERR_APPEAL_LIMIT_REACHED` (HTTP 409)."

    Design: Corner/validations/third_appeal_exceeds_the_appeal_limit
    """
    ctx = setup_denied_claim(
        program_overrides={"name": "Appeal Limit Program"},
        budget_total_cents=100000000,
        offer_overrides={
            "name": "Appeal Limit Offer",
            "effective_end_date": "2026-12-01T00:00:00Z",
        },
        lines=TWO_UNITS,
    )
    validate_success(
        api.appeal_claim(ctx["claim"]["id"], {"appeal_note": "First appeal"}, ctx["headers"])
    )
    deny_claim(ctx["claim"]["id"])
    validate_success(
        api.appeal_claim(ctx["claim"]["id"], {"appeal_note": "Second appeal"}, ctx["headers"])
    )
    deny_claim(ctx["claim"]["id"])

    resp = api.appeal_claim(
        ctx["claim"]["id"], {"appeal_note": "Third appeal"}, ctx["headers"]
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value)

    claim = read_claim(ctx["claim"]["id"])
    assert claim["appeal_count"] == 2
    assert claim["adjudication_status"] == "DENIED"


# --------------------------------------------------------------------------- #
# The budget gate at its boundary
# --------------------------------------------------------------------------- #

def _budget_boundary_setup():
    """Two 100000-cent claims in UNDER_REVIEW on a 150000-cent program."""
    set_clock("2026-07-10T00:00:00Z")
    program = create_active_program(name="Boundary Program", budget_total_cents=150000)
    offer = create_published_offer(
        program["id"], name="Boundary Offer", max_rebate_cents_per_claim=200000
    )
    claimant = create_dealer_claimant(legal_name="Boundary Dealer", email="bd@bd.example")
    headers = make_dealer_headers(claimant["id"])

    claims = []
    for index in (1, 2):
        claim = open_claim(offer["id"], claimant)
        receipt = attach_receipt(
            claim["id"], claimant, serial_number=f"SN-BND-{index}", lines=BIG_RECEIPT
        )
        claims.append((claim, receipt))

    for claim, _ in claims:
        validate_success(api_client.submit_claim(claim["id"], headers))
    for claim, _ in claims:
        validate_success(api_client.review_claim(claim["id"], PROCESSOR))
    for _, receipt in claims:
        validate_receipt(receipt["id"])

    validate_success(api_client.approve_claim(claims[0][0]["id"], PROCESSOR))
    return {
        "program": program,
        "offer": offer,
        "claimant": claimant,
        "claim_one": claims[0][0],
        "claim_two": claims[1][0],
    }


def test_approval_is_refused_when_the_final_rebate_exceeds_available_cents(api):
    """PRD §3.6: "And the final valuation of §3.5 must fit inside the program's
    `available_cents`, evaluated with this very claim excluded from
    `pending_provisional_cents` so that the claim's own accrual reserve does not
    block its own approval; a final rebate exceeding the available balance is
    refused with `ERR_BUDGET_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/budget_gate_accepts_final_equal_to_available_and_locks_at_exactly_one
    """
    ctx = _budget_boundary_setup()
    resp = api.approve_claim(ctx["claim_two"]["id"], PROCESSOR)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)

    assert read_claim(ctx["claim_two"]["id"])["adjudication_status"] == "UNDER_REVIEW"
    program = read_program(ctx["program"]["id"])
    assert program["committed_cents"] == 100000
    assert program["pending_provisional_cents"] == 100000
    assert program["reserve_cents"] == 15000
    assert program["available_cents"] == 35000


def test_approval_at_exactly_available_cents_succeeds_and_locks_the_program(api):
    """PRD §3.1: "Whenever a recomputation triggered by a `COMMIT` or
    `BUDGET_ADJUSTMENT` entry leaves an `ACTIVE` program at a `utilization_pct` of
    1.0000 or above — the comparison is at-or-above, not strictly above — the
    program moves `ACTIVE → BUDGET_LOCKED` automatically inside the very request
    that appended the entry."
    PRD §3.1: "The delta is added to `budget_total_cents`, a ledger row of type
    `BUDGET_ADJUSTMENT` is appended, and the budget position is recomputed — which
    may fire either the lock or the unlock transition."

    Design: Difficulty/boundary_precision_check/budget_gate_accepts_final_equal_to_available_and_locks_at_exactly_one
    """
    ctx = _budget_boundary_setup()
    validate_error(
        api.approve_claim(ctx["claim_two"]["id"], PROCESSOR),
        ApiErrorId.ERR_BUDGET_EXCEEDED.value,
    )

    topped_up = adjust_budget(ctx["program"]["id"], 50000, memo="Q3 top-up")
    assert topped_up["budget_total_cents"] == 200000

    approved = validate_success(api.approve_claim(ctx["claim_two"]["id"], PROCESSOR))
    assert approved["final_rebate_cents"] == 100000

    program = read_program(ctx["program"]["id"])
    assert program["committed_cents"] == 200000
    assert float(program["utilization_pct"]) == 1.0
    assert program["status"] == "BUDGET_LOCKED"


# --------------------------------------------------------------------------- #
# State preconditions are evaluated ahead of the fiscal gate
# --------------------------------------------------------------------------- #

def _terminal_claim_on_tight_budget():
    set_clock("2026-07-10T00:00:00Z")
    program = create_active_program(name="Priority Program", budget_total_cents=3000)
    offer = create_published_offer(program["id"], name="Priority Offer")
    claimant = create_dealer_claimant(legal_name="Priority Dealer", email="pri@dealer.example")
    headers = make_dealer_headers(claimant["id"])

    claim = open_claim(offer["id"], claimant)
    receipt = attach_receipt(
        claim["id"],
        claimant,
        serial_number="SN-PRI-1",
        lines=[{"sku": "TOOLS-A", "quantity": 2, "unit_price_cents": 20000}],
    )
    validate_success(api_client.submit_claim(claim["id"], headers))
    validate_success(api_client.review_claim(claim["id"], PROCESSOR))
    validate_receipt(receipt["id"])
    approved = validate_success(api_client.approve_claim(claim["id"], PROCESSOR))
    return {"program": program, "claim": approved}


def test_second_approve_reports_the_terminal_state_not_the_budget_gate(api):
    """PRD §2.8: "9. State preconditions — the target resource must be in a state
    from which the requested transition is declared, else one of
    `ERR_PROGRAM_NOT_ACTIVE`, `ERR_OFFER_NOT_PUBLISHED`, `ERR_CLAIM_NOT_DRAFT`,
    `ERR_CLAIM_NOT_REVIEWABLE`, `ERR_CLAIM_ALREADY_TERMINAL`,
    `ERR_PAYOUT_NOT_RELEASABLE`, `ERR_CARD_NOT_ACTIVE` or `ERR_INVALID_TRANSITION`
    (all HTTP 409)."
    PRD §3.6: "any adjudication action attempted against a claim already resting in
    `APPROVED`, `REVOKED`, `WITHDRAWN` or `VOIDED` is refused with
    `ERR_CLAIM_ALREADY_TERMINAL`."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_budget_check_on_second_approve
    """
    ctx = _terminal_claim_on_tight_budget()
    assert ctx["claim"]["final_rebate_cents"] == 2000

    resp = api.approve_claim(ctx["claim"]["id"], PROCESSOR)
    validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_TERMINAL.value)


def test_failed_second_approve_leaves_the_budget_position_untouched(api):
    """PRD §2.8: "16. Fiscal gates, in this internal order: the budget gate at
    approval (`ERR_BUDGET_EXCEEDED`), the minimum payout floor
    (`ERR_BELOW_MIN_PAYOUT`), then the budget-adjustment floor
    (`ERR_BUDGET_ADJUSTMENT_INVALID`)."
    PRD §3.1: "Fourth, `available_cents` is `budget_total_cents` less
    `committed_cents` less `reserve_cents`."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_budget_check_on_second_approve
    """
    ctx = _terminal_claim_on_tight_budget()
    before = read_program(ctx["program"]["id"])
    assert before["committed_cents"] == 2000
    assert before["available_cents"] == 1000

    api.approve_claim(ctx["claim"]["id"], PROCESSOR)

    after = read_program(ctx["program"]["id"])
    assert after["committed_cents"] == 2000
    assert after["available_cents"] == 1000
    assert len(list_ledger(claim_id=ctx["claim"]["id"], entry_type="COMMIT")) == 1


# --------------------------------------------------------------------------- #
# Approval cascades four hops deep when the program locks
# --------------------------------------------------------------------------- #

def _lock_cascade_setup():
    set_clock("2026-07-10T00:00:00Z")
    program = create_active_program(name="Tight Budget Program", budget_total_cents=100000)
    offer_tools = create_published_offer(
        program["id"], name="Tools Offer", sku_scope="TOOLS", max_rebate_cents_per_claim=200000
    )
    offer_paint = create_published_offer(
        program["id"], name="Paint Offer", sku_scope="PAINT", max_rebate_cents_per_claim=200000
    )
    claimant = create_dealer_claimant(legal_name="Cascade Dealer", email="cas@dealer.example")
    headers = make_dealer_headers(claimant["id"])

    big_claim = open_claim(offer_tools["id"], claimant)
    big_receipt = attach_receipt(
        big_claim["id"], claimant, serial_number="SN-CAS-1", lines=BIG_RECEIPT
    )
    draft_claim = open_claim(offer_paint["id"], claimant)

    validate_success(api_client.submit_claim(big_claim["id"], headers))
    validate_success(api_client.review_claim(big_claim["id"], PROCESSOR))
    validate_receipt(big_receipt["id"])
    return {
        "program": program,
        "offer_tools": offer_tools,
        "offer_paint": offer_paint,
        "big_claim": big_claim,
        "draft_claim": draft_claim,
    }


def test_commit_that_reaches_full_utilization_locks_the_program(api):
    """PRD §3.6: "As the first cascade hop, a ledger row of type `COMMIT` with
    `amount_cents` equal to `final_rebate_cents` is appended, raising the program's
    `committed_cents`."
    PRD §3.1: "Whenever a recomputation triggered by a `COMMIT` or
    `BUDGET_ADJUSTMENT` entry leaves an `ACTIVE` program at a `utilization_pct` of
    1.0000 or above — the comparison is at-or-above, not strictly above — the
    program moves `ACTIVE → BUDGET_LOCKED` automatically inside the very request
    that appended the entry."

    Design: Difficulty/transitive_cascade/approve_commits_budget_locks_program_suspends_offers_voids_draft_claims
    """
    ctx = _lock_cascade_setup()
    approved = validate_success(api.approve_claim(ctx["big_claim"]["id"], PROCESSOR))
    assert approved["final_rebate_cents"] == 100000

    program = read_program(ctx["program"]["id"])
    assert program["committed_cents"] == 100000
    assert float(program["utilization_pct"]) == 1.0
    assert program["status"] == "BUDGET_LOCKED"


def test_budget_lock_suspends_published_offers_and_voids_their_draft_claims(api):
    """PRD §3.1: "That lock cascades: as hop two, every offer of the program
    currently `PUBLISHED` moves `PUBLISHED → SUSPENDED`; as hop three, for each
    offer so suspended, every claim on that offer still in `DRAFT` moves
    `DRAFT → VOIDED`."

    Design: Difficulty/transitive_cascade/approve_commits_budget_locks_program_suspends_offers_voids_draft_claims
    """
    ctx = _lock_cascade_setup()
    validate_success(api.approve_claim(ctx["big_claim"]["id"], PROCESSOR))

    assert read_offer(ctx["offer_tools"]["id"])["status"] == "SUSPENDED"
    assert read_offer(ctx["offer_paint"]["id"])["status"] == "SUSPENDED"
    assert read_claim(ctx["draft_claim"]["id"])["adjudication_status"] == "VOIDED"
