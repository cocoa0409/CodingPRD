"""Fraud scoring, the cyclic case machine and the substantiation cascade."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    attach_receipt,
    create_active_program,
    create_dealer_claimant,
    create_published_offer,
    deny_claim,
    entries_of_type,
    list_ledger,
    make_dealer_headers,
    open_claim,
    open_case_under_investigation,
    open_fraud_case,
    read_claim,
    read_claimant,
    read_fraud_case,
    read_payout,
    read_program,
    set_clock,
    setup_pending_payout,
    transition_fraud_case,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
PROCESSOR = TEST_USERS["claims_processor_headers"]
FRAUD = TEST_USERS["fraud_analyst_headers"]
TWO_UNITS = [{"sku": "TOOLS-A", "quantity": 2, "unit_price_cents": 1000}]


def test_substantiating_a_case_straight_from_open_is_an_invalid_transition(api):
    """PRD §3.7: "From `UNDER_INVESTIGATION` the case may reach either of its two
    terminal states, `SUBSTANTIATED` or `CLEARED`. Any destination requested from a
    state that does not declare it is refused with `ERR_INVALID_TRANSITION`
    (HTTP 409)."

    Design: Corner/state_machines/fraud_case_open_to_substantiated_shortcut_is_rejected
    """
    claimant = create_dealer_claimant(legal_name="Jump Dealer", email="jp@jp.example")
    case = open_fraud_case(claimant["id"], opened_reason="TIP_LINE")

    resp = api.transition_fraud_case(case["id"], {"to_status": "SUBSTANTIATED"}, FRAUD)
    validate_error(resp, ApiErrorId.ERR_INVALID_TRANSITION.value)

    stored = read_fraud_case(case["id"])
    assert stored["status"] == "OPEN"
    assert stored["final_score"] is None
    assert read_claimant(claimant["id"])["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# The investigated score diverges by branch
# --------------------------------------------------------------------------- #

def _two_denied_claimants():
    """Two dealer claimants, each with exactly one DENIED claim."""
    set_clock("2026-07-10T00:00:00Z")
    program = create_active_program(name="Risk Program", budget_total_cents=100000000)
    offer = create_published_offer(program["id"], name="Risk Offer")

    result = {"program": program, "offer": offer}
    for label, legal_name, email in (
        ("a", "Alpha Dealer", "a@alpha.example"),
        ("b", "Beta Dealer", "b@beta.example"),
    ):
        claimant = create_dealer_claimant(legal_name=legal_name, email=email)
        claim = open_claim(offer["id"], claimant)
        attach_receipt(
            claim["id"],
            claimant,
            serial_number=f"SN-{label.upper()}-1",
            purchase_date="2026-06-15T00:00:00Z",
            lines=TWO_UNITS,
        )
        validate_success(
            api_client.submit_claim(claim["id"], make_dealer_headers(claimant["id"]))
        )
        validate_success(api_client.review_claim(claim["id"], PROCESSOR))
        deny_claim(claim["id"], reason_code="ILLEGIBLE_RECEIPT")
        result[f"claimant_{label}"] = claimant
        result[f"claim_{label}"] = claim
    return result


def test_substantiated_branch_multiplies_the_score_at_open(api):
    """PRD §3.7: "On the `SUBSTANTIATED` branch, multiply `heuristic_score_at_open`
    by 1.5, round the product half up to a whole number of points, and take the
    lesser of that and 100."
    PRD §3.7: "Take the claimant's `denied_claim_count` — the number of its claims
    currently sitting in `DENIED` — and weight it at 15 points each."

    Design: Difficulty/dual_variant_calc/fraud_score_substantiated_vs_cleared_diverges_on_claimant
    """
    ctx = _two_denied_claimants()
    case = open_case_under_investigation(
        ctx["claimant_a"]["id"], opened_reason="MANUAL_AUDIT"
    )
    assert case["heuristic_score_at_open"] == 15

    terminal = transition_fraud_case(case["id"], "SUBSTANTIATED")
    assert terminal["status"] == "SUBSTANTIATED"
    assert terminal["final_score"] == 23

    claimant = read_claimant(ctx["claimant_a"]["id"])
    assert claimant["fraud_score"] == 23
    assert claimant["status"] == "BLOCKED"


def test_cleared_branch_subtracts_the_clearance_credit(api):
    """PRD §3.7: "On the `CLEARED` branch, subtract 30 points from
    `heuristic_score_at_open` and take the greater of that and 0. In both branches
    the resulting `final_score` is also copied onto the claimant's `fraud_score`."
    PRD §3.7: "An analyst-opened case starts in `OPEN` with `opened_by` of
    `ANALYST` and has its `heuristic_score_at_open` stamped from the real-time
    heuristic evaluated at that moment."

    Design: Difficulty/dual_variant_calc/fraud_score_substantiated_vs_cleared_diverges_on_claimant
    """
    ctx = _two_denied_claimants()
    case = open_case_under_investigation(
        ctx["claimant_b"]["id"], opened_reason="MANUAL_AUDIT"
    )
    assert case["heuristic_score_at_open"] == 15
    assert case["opened_by"] == "ANALYST"

    terminal = transition_fraud_case(case["id"], "CLEARED")
    assert terminal["status"] == "CLEARED"
    assert terminal["final_score"] == 0

    claimant = read_claimant(ctx["claimant_b"]["id"])
    assert claimant["fraud_score"] == 0
    assert claimant["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# The unbounded investigation cycle
# --------------------------------------------------------------------------- #

def _cycled_case():
    claimant = create_dealer_claimant(legal_name="Cycle Dealer", email="c@cyc.example")
    case = open_fraud_case(claimant["id"], opened_reason="TIP_LINE")
    transition_fraud_case(case["id"], "UNDER_INVESTIGATION")
    transition_fraud_case(case["id"], "PENDING_INFO", note="await invoices")
    transition_fraud_case(case["id"], "UNDER_INVESTIGATION")
    transition_fraud_case(case["id"], "PENDING_INFO", note="await bank letter")
    transition_fraud_case(case["id"], "UNDER_INVESTIGATION")
    return claimant, case


def test_each_pending_info_hop_increments_the_info_request_count(api):
    """PRD §3.7: "From `UNDER_INVESTIGATION` it may move to `PENDING_INFO`, which
    increments `info_request_count` by one; from `PENDING_INFO` it may return to
    `UNDER_INVESTIGATION`, and this `UNDER_INVESTIGATION → PENDING_INFO →
    UNDER_INVESTIGATION` cycle is unbounded."

    Design: Difficulty/non_linear_state_machine/fraud_case_investigation_pending_info_cycle_repeats
    """
    _, case = _cycled_case()
    stored = read_fraud_case(case["id"])
    assert stored["status"] == "UNDER_INVESTIGATION"
    assert stored["info_request_count"] == 2


def test_a_twice_cycled_case_still_terminates_cleared(api):
    """PRD §3.7: "From `UNDER_INVESTIGATION` the case may reach either of its two
    terminal states, `SUBSTANTIATED` or `CLEARED`."
    PRD §3.7: "On the `CLEARED` branch, subtract 30 points from
    `heuristic_score_at_open` and take the greater of that and 0."

    Design: Difficulty/non_linear_state_machine/fraud_case_investigation_pending_info_cycle_repeats
    """
    claimant, case = _cycled_case()
    terminal = transition_fraud_case(case["id"], "CLEARED")

    assert terminal["status"] == "CLEARED"
    assert terminal["info_request_count"] == 2
    assert terminal["heuristic_score_at_open"] == 0
    assert terminal["final_score"] == 0
    assert read_claimant(claimant["id"])["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Substantiation fans out three hops deep
# --------------------------------------------------------------------------- #

def _approved_claim_with_pending_payout():
    ctx = setup_pending_payout(
        method="CHECK",
        program_overrides={"name": "Fraud Cascade Program"},
        budget_total_cents=1000000,
        offer_overrides={"name": "Fraud Cascade Offer"},
        claimant_overrides={"legal_name": "Suspect Dealer", "email": "s@suspect.example"},
        serial_number="SN-FRD-1",
    )
    ctx["case"] = open_case_under_investigation(
        ctx["claimant"]["id"], opened_reason="SERIAL_FARMING", claim_id=ctx["claim"]["id"]
    )
    return ctx


def test_substantiation_blocks_the_claimant_and_revokes_the_unpaid_claim(api):
    """PRD §3.7: "As hop one, the claimant moves `ACTIVE → BLOCKED`."
    PRD §3.7: "Also as hop two, every claim of that claimant in `APPROVED` whose
    payment state is `NONE` or `SCHEDULED` moves `APPROVED → REVOKED`, and each
    such revocation decrements its offer's `active_claim_count` by one."

    Design: Difficulty/transitive_cascade/substantiate_blocks_claimant_revokes_claim_releases_commitment
    """
    ctx = _approved_claim_with_pending_payout()
    transition_fraud_case(ctx["case"]["id"], "SUBSTANTIATED")

    assert read_claimant(ctx["claimant"]["id"])["status"] == "BLOCKED"
    claim = read_claim(ctx["claim"]["id"])
    assert claim["adjudication_status"] == "REVOKED"
    assert claim["payment_status"] == "NONE"
    assert read_payout(ctx["payout"]["id"])["status"] == "VOIDED"


def test_revocation_releases_the_commitment_through_the_ledger(api):
    """PRD §3.7: "As hop three, each revoked claim appends a ledger row of type
    `RELEASE` whose `amount_cents` equals that claim's `final_rebate_cents`,
    lowering the program's `committed_cents`; and any payout of that claim in
    `PENDING` or `REISSUE_PENDING` moves to `VOIDED` with the claim's payment state
    reset to `NONE`."

    Design: Difficulty/transitive_cascade/substantiate_blocks_claimant_revokes_claim_releases_commitment
    """
    ctx = _approved_claim_with_pending_payout()
    transition_fraud_case(ctx["case"]["id"], "SUBSTANTIATED")

    releases = entries_of_type(
        list_ledger(program_id=ctx["program"]["id"], entry_type="RELEASE"), "RELEASE"
    )
    assert len(releases) == 1
    assert releases[0]["amount_cents"] == 1600

    program = read_program(ctx["program"]["id"])
    assert program["committed_cents"] == 0
    assert program["available_cents"] == 1000000
