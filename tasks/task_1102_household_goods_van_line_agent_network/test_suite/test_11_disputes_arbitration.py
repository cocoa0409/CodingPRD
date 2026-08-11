"""Disputes and the arbitration program (PRD 3.9, 3.8, 2.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    file_claim,
    get_statement_for_order,
    make_arbitrator_headers,
    make_claims_adjuster_headers,
    make_van_line_admin_headers,
    set_clock,
    setup_delivered_order,
    setup_docketed_dispute,
    validate_error,
    get_success_data,
)

ADMIN = TEST_USERS["van_line_admin_headers"]


# ---------------------------------------------------------------------------
# Arbitration decide cascade on a claim dispute
# ---------------------------------------------------------------------------
def test_arbitration_decide_forces_claim_acceptance(api):
    """PRD section 3.9: "The decision records `decided_by_user_id`, computes
    `fee_allocated_to` as just described, and moves the dispute to `DECIDED` with
    its `version` bumped, then cascades according to the subject: for a claim
    dispute, the referenced claim moves to `ACCEPTED` with `settled_amount_cents`
    set to the award and `offered_by_user_id` set to the arbitrator's identifier,
    firing the same chargeback and quality-score cascades as a negotiated
    acceptance; for a revenue dispute, the award is added to the statement's
    `chargeback_total_cents` as a cascade adjustment."
    PRD section 3.9: "The filing fee is allocated by comparing the award to the
    amount in controversy using exact integer cross-multiplication, never
    floating-point division: the fee falls to `RESPONDENT` when five times the
    award is at least four times the amount in controversy — an award of exactly
    eighty percent included; it falls to `FILER` when five times the award is at
    most one times the amount in controversy — an award of exactly twenty percent
    included; and in every other case the fee is `SPLIT`."
    PRD section 3.9: "Escalation moves the dispute to `ARBITRATION_DOCKETED`,
    stamps `escalated_at`, and sets `filing_fee_cents` to the program's fixed
    filing fee of 25000 cents."

    Design: Difficulty/transitive_cascade/arbitration_decide_claim_chargeback_quality_cascade
    """
    ctx = setup_docketed_dispute(
        pricing_mode="BINDING", mileage=900,
        tariff_overrides={"mileage_bands": [{"min_miles": 0, "max_miles": 999999, "rate_multiplier": 1.0}]},
        claim_kwargs={"claimed_amount_cents": 250000, "claimed_item_weight_lbs": 200},
        offer_amount_cents=12000,
        subject_amount_cents=12000,
    )
    dispute = ctx["dispute"]
    assert dispute["filing_fee_cents"] == 25000, "fixed filing fee attaches at escalation"

    decided = get_success_data(
        api.decide_dispute(dispute["id"], {"decision_amount_cents": 10000}, make_arbitrator_headers("arb-1"))
    )
    assert decided["status"] == "DECIDED"
    # 10000 * 5 >= 12000 * 4 -> the 80% boundary is inclusive.
    assert decided["fee_allocated_to"] == "RESPONDENT"
    assert decided["decided_by_user_id"] == "arb-1"

    claim = get_success_data(api.get_claim(ctx["claim"]["id"], ADMIN))
    assert claim["status"] == "ACCEPTED", "hop 1: the claim is forced to ACCEPTED at decide"
    assert claim["settled_amount_cents"] == 10000
    assert claim["offered_by_user_id"] == "arb-1"


def test_arbitration_decide_cascades_chargeback_quality_and_pay_closes(api):
    """PRD section 3.9: "Accepting the offer sets `settled_amount_cents` to the
    current `offer_amount_cents`, moves the claim to `ACCEPTED`, and fires two
    cascades: the order's revenue statement adds the settled amount to its
    `chargeback_total_cents` (statement `version` bumped), and the `HAULING`
    agent's `quality_score` is recomputed per §2.9 from the new chargeback total
    (agent `version` bumped)."
    PRD section 2.9: "An agent's `quality_score` starts at 100 and is recomputed
    whenever the order's statement accumulates chargebacks: the new score is one
    hundred minus the number of complete ten-thousand-cent blocks contained in the
    statement's cumulative `chargeback_total_cents` (that is, the chargeback total
    divided by ten thousand and rounded down to a whole number), and it never
    falls below zero."
    PRD section 3.9: "Payment moves the claim from `ACCEPTED` to the terminal
    `PAID` and, as a cascade, closes every dispute referencing this claim that is
    still `OPENED`, `RESPONSE_FILED`, `ARBITRATION_DOCKETED`, or `DECIDED`."

    Design: Difficulty/transitive_cascade/arbitration_decide_claim_chargeback_quality_cascade
    """
    ctx = setup_docketed_dispute(
        pricing_mode="BINDING", mileage=900,
        tariff_overrides={"mileage_bands": [{"min_miles": 0, "max_miles": 999999, "rate_multiplier": 1.0}]},
        claim_kwargs={"claimed_amount_cents": 250000, "claimed_item_weight_lbs": 200},
        offer_amount_cents=12000,
        subject_amount_cents=12000,
    )
    get_success_data(
        api.decide_dispute(ctx["dispute"]["id"], {"decision_amount_cents": 10000}, make_arbitrator_headers("arb-1"))
    )

    statement = get_success_data(api.get_revenue_statement(ctx["statement"]["id"], ADMIN))
    assert statement["chargeback_total_cents"] == 10000, "hop 2: caused by the claim mutation"

    haul_agent = get_success_data(api.get_agent(ctx["hauling_agent"]["id"], ADMIN))
    # max(0, 100 - floor(10000 / 10000)) == 99
    assert haul_agent["quality_score"] == 99, (
        f"one complete ten-thousand-cent block costs one point, got {haul_agent['quality_score']}"
    )

    # offered_by_user_id is now the arbitrator; a different operator pays.
    paid = get_success_data(
        api.pay_claim(ctx["claim"]["id"], make_van_line_admin_headers("vl-admin-1"))
    )
    assert paid["status"] == "PAID"
    dispute_after = get_success_data(api.get_dispute(ctx["dispute"]["id"], ADMIN))
    assert dispute_after["status"] == "CLOSED", "the pay cascade closes the arbitration record"


# ---------------------------------------------------------------------------
# Fee allocation thresholds on revenue disputes
# ---------------------------------------------------------------------------
def _setup_final_statement(api):
    ctx = setup_delivered_order(
        pricing_mode="NON_BINDING", estimated_weight_lbs=8000, actual_weight_lbs=9600
    )
    statement = ctx["statement"]
    get_success_data(api.finalize_revenue_statement(statement["id"], ADMIN))
    return ctx, statement


def _run_revenue_dispute(api, ctx, statement_id, decision_cents, responder_clock, escalate_clock):
    dispute = get_success_data(
        api.create_dispute(
            {"revenue_statement_id": statement_id, "subject_amount_cents": 100000},
            ctx["hauling_h"],
        )
    )
    set_clock(responder_clock)
    get_success_data(
        api.respond_dispute(dispute["id"], {}, make_van_line_admin_headers("vl-admin-9"))
    )
    set_clock(escalate_clock)
    get_success_data(api.escalate_dispute(dispute["id"], ctx["hauling_h"]))
    decided = get_success_data(
        api.decide_dispute(dispute["id"], {"decision_amount_cents": decision_cents}, make_arbitrator_headers("arb-1"))
    )
    return dispute["id"], decided


def test_arbitration_fee_allocation_thresholds(api):
    """PRD section 3.9: "The filing fee is allocated by comparing the award to the
    amount in controversy using exact integer cross-multiplication, never
    floating-point division: the fee falls to `RESPONDENT` when five times the
    award is at least four times the amount in controversy — an award of exactly
    eighty percent included; it falls to `FILER` when five times the award is at
    most one times the amount in controversy — an award of exactly twenty percent
    included; and in every other case the fee is `SPLIT`."
    PRD section 3.9: "The decision records `decided_by_user_id`, computes
    `fee_allocated_to` as just described, and moves the dispute to `DECIDED` with
    its `version` bumped, then cascades according to the subject: for a claim
    dispute, the referenced claim moves to `ACCEPTED` with `settled_amount_cents`
    set to the award and `offered_by_user_id` set to the arbitrator's identifier,
    firing the same chargeback and quality-score cascades as a negotiated
    acceptance; for a revenue dispute, the award is added to the statement's
    `chargeback_total_cents` as a cascade adjustment."
    PRD section 3.9: "Escalation moves the dispute to `ARBITRATION_DOCKETED`,
    stamps `escalated_at`, and sets `filing_fee_cents` to the program's fixed
    filing fee of 25000 cents."
    PRD section 3.9: "A `VanLineAdmin` may close a `DECIDED` dispute; for a claim
    dispute the referenced claim must already be `PAID` (otherwise
    `ERR_CLAIM_NOT_PAID`), while a revenue dispute carries no additional
    condition."

    Design: Corner/calculations/arbitration_fee_allocation_thresholds
    """
    ctx, statement = _setup_final_statement(api)

    # 80000 * 5 >= 100000 * 4 -> RESPONDENT at exactly 80%.
    d1_id, d1 = _run_revenue_dispute(
        api, ctx, statement["id"], 80000, "2026-06-10T10:00:00Z", "2026-06-24T10:00:00Z"
    )
    assert d1["fee_allocated_to"] == "RESPONDENT"
    assert d1["filing_fee_cents"] == 25000
    get_success_data(api.close_dispute(d1_id, ADMIN))

    # 20000 * 5 <= 100000 * 1 -> FILER at exactly 20%.
    _d2_id, d2 = _run_revenue_dispute(
        api, ctx, statement["id"], 20000, "2026-06-24T10:00:00Z", "2026-07-08T10:00:00Z"
    )
    assert d2["fee_allocated_to"] == "FILER"
    assert d2["filing_fee_cents"] == 25000

    after = get_success_data(api.get_revenue_statement(statement["id"], ADMIN))
    assert after["chargeback_total_cents"] == 100000, (
        f"both revenue awards accumulate (80000 + 20000), got {after['chargeback_total_cents']}"
    )


# ---------------------------------------------------------------------------
# Dispute subject discipline
# ---------------------------------------------------------------------------
def test_dispute_subject_xor_and_state_gates(api):
    """PRD section 3.9: "When negotiation stalls, either side's next step is a
    dispute. A customer or any agent-role operator may open one, with a payload
    naming exactly one subject — a `claim_id` or a `revenue_statement_id`, never
    both and never neither (violations are `ERR_DISPUTE_SUBJECT_INVALID`, HTTP
    422) — and a `subject_amount_cents` of at least 1. The subject must be in a
    disputable state: a claim subject must be `DISPUTED` with at least one
    rejected round behind it (`round_count` of 1 or more), and a statement subject
    must be `FINAL` — filing against a statement that is not `FINAL` is rejected
    with `ERR_STATEMENT_NOT_FINAL`, and a subject failing these state requirements
    is `ERR_DISPUTE_SUBJECT_INVALID`."

    Design: Corner/validations/dispute_subject_xor_and_state_gates
    """
    ctx = setup_delivered_order(
        pricing_mode="BINDING", mileage=900,
        tariff_overrides={"mileage_bands": [{"min_miles": 0, "max_miles": 999999, "rate_multiplier": 1.0}]},
    )
    statement = ctx["statement"]  # PROVISIONAL at delivery.
    claim = file_claim(ctx, claimed_amount_cents=50000, claimed_item_weight_lbs=100)

    both = api.create_dispute(
        {
            "claim_id": claim["id"],
            "revenue_statement_id": statement["id"],
            "subject_amount_cents": 10000,
        },
        ctx["cust_h"],
    )
    validate_error(both, ApiErrorId.ERR_DISPUTE_SUBJECT_INVALID)

    not_disputed = api.create_dispute(
        {"claim_id": claim["id"], "subject_amount_cents": 10000}, ctx["cust_h"]
    )
    validate_error(not_disputed, ApiErrorId.ERR_DISPUTE_SUBJECT_INVALID)

    not_final = api.create_dispute(
        {"revenue_statement_id": statement["id"], "subject_amount_cents": 10000},
        ctx["hauling_h"],
    )
    validate_error(not_final, ApiErrorId.ERR_STATEMENT_NOT_FINAL)


# ---------------------------------------------------------------------------
# Segregation of duties on arbitration decide
# ---------------------------------------------------------------------------
def test_segregation_of_duties_arbitration_decide(api):
    """PRD section 3.9: "An `Arbitrator` decides a docketed dispute under the
    second segregation-of-duties rule: the decider's `X-User-ID` must differ from
    `responded_by_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`), so the
    operator who filed the van line's response can never arbitrate the same
    dispute."

    Design: Corner/rbac/segregation_of_duties_arbitration_decide
    """
    ctx = setup_docketed_dispute(
        responder_id="vl-admin-9",
        pricing_mode="BINDING", mileage=900,
        tariff_overrides={"mileage_bands": [{"min_miles": 0, "max_miles": 999999, "rate_multiplier": 1.0}]},
        claim_kwargs={"claimed_amount_cents": 250000, "claimed_item_weight_lbs": 200},
        offer_amount_cents=12000,
        subject_amount_cents=12000,
    )
    dispute = ctx["dispute"]

    resp = api.decide_dispute(
        dispute["id"], {"decision_amount_cents": 10000}, make_arbitrator_headers("vl-admin-9")
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    decided = get_success_data(
        api.decide_dispute(dispute["id"], {"decision_amount_cents": 10000}, make_arbitrator_headers("arb-1"))
    )
    assert decided["status"] == "DECIDED"
    claim = get_success_data(api.get_claim(ctx["claim"]["id"], ADMIN))
    assert claim["status"] == "ACCEPTED"
    assert claim["settled_amount_cents"] == 10000
