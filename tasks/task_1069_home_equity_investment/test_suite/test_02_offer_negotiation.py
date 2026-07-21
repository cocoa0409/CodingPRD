"""Offer presentation, the investment LTV cap, the counter/represent cycle, the
accept funding cascade, and fund-capital reconciliation.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_homeowner_headers,
    create_homeowner_payload,
    fixtures,
)

ANALYST = TEST_USERS["analyst_headers"]


# --------------------------------------------------------------------------
# dual_variant_calc: offer_max_investment provisional (AVM) vs final (APPRAISAL)
# --------------------------------------------------------------------------
def test_offer_rejected_on_avm_basis_investment_cap(api):
    """PRD §3.4: "the maximum permitted investment is thirty percent of the
    basis valuation's valued_amount_cents, floored to whole cents, and if
    investment_amount_cents exceeds that maximum the presentation is rejected
    with ERR_INVESTMENT_EXCEEDS_LTV_CAP."

    Design: Difficulty/dual_variant_calc/offer_max_investment_provisional_vs_final
    """
    ctx = fixtures.setup_approved_with_dual_basis(api)
    resp = api.create_offer(
        ctx["application"]["id"],
        {
            "valuation_id": ctx["avm_valuation"]["id"],
            "investment_amount_cents": 25000000,
            "option_percentage": 0.25, "risk_adjustment_pct": 0.10,
            "term_months": 120, "capped_annual_rate": 0.19,
            "expires_at": "2027-01-01T00:00:00Z",
        },
        ANALYST,
    )
    validate_error(resp, "ERR_INVESTMENT_EXCEEDS_LTV_CAP", 422)


def test_offer_accepted_on_appraisal_basis_investment_cap(api):
    """PRD §3.4: "Because this cap is computed from the chosen basis, an amount
    that is valid against a provisional AVM basis can be rejected against an
    appraisal basis whose valued_amount_cents differs, and vice versa — the same
    investment_amount_cents yields a different ceiling on each basis."

    Design: Difficulty/dual_variant_calc/offer_max_investment_provisional_vs_final
    """
    ctx = fixtures.setup_approved_with_dual_basis(api)
    offer = validate_success(api.create_offer(
        ctx["application"]["id"],
        {
            "valuation_id": ctx["appraisal_valuation"]["id"],
            "investment_amount_cents": 25000000,
            "option_percentage": 0.25, "risk_adjustment_pct": 0.10,
            "term_months": 120, "capped_annual_rate": 0.19,
            "expires_at": "2027-01-01T00:00:00Z",
        },
        ANALYST,
    ), 201)
    assert offer["status"] == "PRESENTED"
    assert offer["investment_amount_cents"] == 25000000


# --------------------------------------------------------------------------
# non_linear_state_machine: offer counter -> represent cycle
# --------------------------------------------------------------------------
def test_counter_moves_offer_to_countered_with_notes(api):
    """PRD §3.4: "Countering moves the offer to COUNTERED, records the
    homeowner's counter_notes rationale, and likewise releases the reserved
    amount — a COUNTERED offer holds no capital."

    Design: Difficulty/non_linear_state_machine/offer_counter_represent_cycle
    """
    ctx = fixtures.setup_presented_offer(api)
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    countered = validate_success(
        api.counter_offer(ctx["offer"]["id"], {"counter_notes": "offer too low"}, ho)
    )
    assert countered["status"] == "COUNTERED"
    assert countered["counter_notes"] == "offer too low"


def test_represent_returns_countered_offer_to_presented(api):
    """PRD §3.4: "From COUNTERED, the analyst may re-present revised terms,
    moving the offer back to PRESENTED in a loop; the re-presentation may
    overwrite any of investment_amount_cents, option_percentage,
    risk_adjustment_pct, term_months, capped_annual_rate, and expires_at".

    Design: Difficulty/non_linear_state_machine/offer_counter_represent_cycle
    """
    ctx = fixtures.setup_presented_offer(api)
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    get_success_data(api.counter_offer(ctx["offer"]["id"], {"counter_notes": "offer too low"}, ho))
    represented = validate_success(
        api.represent_offer(ctx["offer"]["id"], {"investment_amount_cents": 9000000}, ANALYST)
    )
    assert represented["status"] == "PRESENTED"
    assert represented["investment_amount_cents"] == 9000000


# --------------------------------------------------------------------------
# transitive_cascade: accept -> fund application -> decline siblings
# --------------------------------------------------------------------------
def test_accept_funds_offer_and_application(api):
    """PRD §3.5: "In one atomic step the accepted offer moves to ACCEPTED; the
    parent application moves from OFFERED to FUNDED; and every sibling offer of
    that application still in PRESENTED is moved to DECLINED, releasing the
    capital each was holding."

    Design: Difficulty/transitive_cascade/offer_accept_supersede_depth2
    """
    ctx = fixtures.setup_approved_application(api)
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    offer1 = fixtures.present_offer(api, ctx["application"]["id"], ctx["valuation"]["id"])
    fixtures.present_offer(api, ctx["application"]["id"], ctx["valuation"]["id"],
                           option_percentage=0.20, capped_annual_rate=0.18)
    accepted = validate_success(api.accept_offer(offer1["id"], ho))
    assert accepted["status"] == "ACCEPTED"
    application = validate_success(api.get_application(ctx["application"]["id"], ANALYST))
    assert application["status"] == "FUNDED"


def test_accept_declines_sibling_presented_offers(api):
    """PRD §3.5: "In one atomic step the accepted offer moves to ACCEPTED; the
    parent application moves from OFFERED to FUNDED; and every sibling offer of
    that application still in PRESENTED is moved to DECLINED, releasing the
    capital each was holding."

    Design: Difficulty/transitive_cascade/offer_accept_supersede_depth2
    """
    ctx = fixtures.setup_approved_application(api)
    ho = make_homeowner_headers(ctx["homeowner"]["id"])
    offer1 = fixtures.present_offer(api, ctx["application"]["id"], ctx["valuation"]["id"])
    offer2 = fixtures.present_offer(api, ctx["application"]["id"], ctx["valuation"]["id"],
                                    option_percentage=0.20, capped_annual_rate=0.18)
    get_success_data(api.accept_offer(offer1["id"], ho))
    sibling = validate_success(api.get_offer(offer2["id"], ANALYST))
    assert sibling["status"] == "DECLINED"


# --------------------------------------------------------------------------
# cross_entity_state_dependency: offer basis must be COMPLETED
# --------------------------------------------------------------------------
def test_present_offer_on_pending_valuation_rejected(api):
    """PRD §3.4: "Presenting an offer also requires that the chosen basis
    valuation actually be COMPLETED; presenting against a non-completed
    valuation is rejected with ERR_VALUATION_NOT_COMPLETED."

    Design: Difficulty/cross_entity_state_dependency/offer_present_requires_valuation_completed
    """
    ctx = fixtures.setup_approved_application(api)
    pending = fixtures.create_appraisal_valuation(api, ctx["application"]["id"])
    resp = api.create_offer(
        ctx["application"]["id"],
        {
            "valuation_id": pending["id"], "investment_amount_cents": 10000000,
            "option_percentage": 0.25, "risk_adjustment_pct": 0.10,
            "term_months": 120, "capped_annual_rate": 0.19,
            "expires_at": "2027-01-01T00:00:00Z",
        },
        ANALYST,
    )
    validate_error(resp, "ERR_VALUATION_NOT_COMPLETED", 409)


def test_present_offer_on_completed_valuation_succeeds(api):
    """PRD §3.4: "Presenting an offer also requires that the chosen basis
    valuation actually be COMPLETED; presenting against a non-completed
    valuation is rejected with ERR_VALUATION_NOT_COMPLETED."

    Design: Difficulty/cross_entity_state_dependency/offer_present_requires_valuation_completed
    """
    ctx = fixtures.setup_approved_application(api)
    offer = validate_success(api.create_offer(
        ctx["application"]["id"],
        {
            "valuation_id": ctx["valuation"]["id"], "investment_amount_cents": 10000000,
            "option_percentage": 0.25, "risk_adjustment_pct": 0.10,
            "term_months": 120, "capped_annual_rate": 0.19,
            "expires_at": "2027-01-01T00:00:00Z",
        },
        ANALYST,
    ), 201)
    assert offer["status"] == "PRESENTED"


# --------------------------------------------------------------------------
# compensating_invariant: present then withdraw conserves fund capital
# --------------------------------------------------------------------------
def test_withdraw_offer_releases_committed_capital(api):
    """PRD §3.4: "the analyst may withdraw a still-presented offer to the
    terminal WITHDRAWN state, which also releases its reserved amount from
    committed capital."

    Design: Difficulty/compensating_invariant/fund_capital_conserved_present_then_withdraw
    """
    ctx = fixtures.setup_presented_offer(api)
    get_success_data(api.withdraw_offer(ctx["offer"]["id"], ANALYST))
    fund = validate_success(api.get_fund(ctx["fund"]["id"], ANALYST))
    assert fund["committed_capital_cents"] == 0


def test_withdraw_offer_restores_available_capital(api):
    """PRD §2.6: "Available capital is the fund's total_capital_cents minus its
    committed_capital_cents. These two figures are recomputed on every offer or
    agreement mutation — presentation, counter, re-presentation, decline,
    withdrawal, acceptance, settlement finalization, and default — and the
    invariant that committed plus available always equals total capital holds
    after each."

    Design: Difficulty/compensating_invariant/fund_capital_conserved_present_then_withdraw
    """
    ctx = fixtures.setup_presented_offer(api)
    get_success_data(api.withdraw_offer(ctx["offer"]["id"], ANALYST))
    fund = validate_success(api.get_fund(ctx["fund"]["id"], ANALYST))
    assert fund["available_capital_cents"] == 50000000
    assert fund["committed_capital_cents"] + fund["available_capital_cents"] == fund["total_capital_cents"]


# --------------------------------------------------------------------------
# Queue-B corner instances
# --------------------------------------------------------------------------
def test_accept_offer_by_other_homeowner_forbidden(api):
    """PRD §2.1: "A homeowner-owned mutation performed by a different homeowner
    is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/validations/offer_accept_by_other_homeowner_forbidden
    """
    ctx = fixtures.setup_presented_offer(api)
    other = get_success_data(api.create_homeowner(create_homeowner_payload(), ANALYST))
    validate_error(
        api.accept_offer(ctx["offer"]["id"], make_homeowner_headers(other["id"])),
        "ERR_NOT_RESOURCE_OWNER", 403,
    )


def test_present_offer_over_available_capital_rejected(api):
    """PRD §3.4: "an offer cannot reserve more than the fund currently holds
    available — if investment_amount_cents exceeds the fund's
    available_capital_cents the presentation is rejected with
    ERR_INSUFFICIENT_FUND_CAPITAL".

    Design: Corner/validations/offer_present_insufficient_fund_capital_returns_422
    """
    ctx = fixtures.setup_approved_application(
        api, fund_total_cents=10000000, valued_amount_cents=40000000,
        requested_investment_cents=10000001, existing_mortgage_balance_cents=0,
    )
    resp = api.create_offer(
        ctx["application"]["id"],
        {
            "valuation_id": ctx["valuation"]["id"], "investment_amount_cents": 10000001,
            "option_percentage": 0.25, "risk_adjustment_pct": 0.10,
            "term_months": 120, "capped_annual_rate": 0.19,
            "expires_at": "2027-01-01T00:00:00Z",
        },
        ANALYST,
    )
    validate_error(resp, "ERR_INSUFFICIENT_FUND_CAPITAL", 422)


def test_accept_expired_offer_rejected(api):
    """PRD §3.4: "acceptance is refused with ERR_OFFER_EXPIRED if the logical
    clock is at or after the offer's expires_at".

    Design: Corner/state_machines/offer_accept_after_expiry_returns_offer_expired
    """
    ctx = fixtures.setup_presented_offer(api, offer_overrides={"expires_at": "2026-06-15T00:00:00Z"})
    validate_error(
        api.accept_offer(ctx["offer"]["id"], make_homeowner_headers(ctx["homeowner"]["id"])),
        "ERR_OFFER_EXPIRED", 409,
    )


def test_accept_already_accepted_offer_is_invalid_state(api):
    """PRD §2.8: "(6) whether the target resource is in a state from which the
    requested transition is defined, yielding ERR_INVALID_STATE".

    Design: Corner/state_machines/offer_accept_twice_returns_invalid_state
    """
    ctx = fixtures.setup_funded_agreement(api)
    validate_error(
        api.accept_offer(ctx["offer"]["id"], make_homeowner_headers(ctx["homeowner"]["id"])),
        "ERR_INVALID_STATE", 409,
    )


def test_present_offer_reserves_capital_immediately(api):
    """PRD §3.4: "presenting an offer reserves that amount by adding it into the
    fund's committed capital."

    Design: Corner/consistency_model/offer_present_committed_capital_immediate
    """
    ctx = fixtures.setup_presented_offer(api)
    fund = validate_success(api.get_fund(ctx["fund"]["id"], ANALYST))
    assert fund["committed_capital_cents"] == 10000000
    assert fund["available_capital_cents"] == 40000000
