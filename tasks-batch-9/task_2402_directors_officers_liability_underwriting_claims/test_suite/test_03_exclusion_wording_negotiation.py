"""Negotiating exclusion wording round by round.

The negotiation cycle revisits states it has already occupied, alternates actors
on every hop, and terminates in an impasse that permanently poisons the bind.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    UNDERWRITER,
    assert_exclusion_term,
    counter_exclusion_term_payload,
    find_term,
    make_risk_manager_headers,
    read_exclusion_terms,
    read_quote,
    resolve_term_as_insured,
    setup_offered_quote,
)

PRIOR_ACTS_TERM = {
    "exclusion_type": "PRIOR_ACTS",
    "wording_variant": "RETRO_DATE_FULL_PRIOR_ACTS",
    "premium_impact_pct": 0.10,
}


def _quote_with_open_prior_acts_wording():
    """An OFFERED quote whose mandatory CONDUCT term is already AGREED — so it can
    never mask a later bind failure — and whose PRIOR_ACTS term is open in
    PROPOSED with round_count 1 and last_actor_role Underwriter."""
    scenario = setup_offered_quote(extra_terms=[PRIOR_ACTS_TERM])
    resolve_term_as_insured(
        scenario["conduct_term"]["id"], scenario["insured"]["id"], "AGREE"
    )
    scenario["prior_acts_term"] = scenario["extra_terms"][0]
    return scenario


def test_counter_cycle_returns_the_term_to_a_state_it_already_occupied(api):
    """PRD 3.3: "The insured's `RiskManager` countering an underwriter's
    outstanding proposal moves the term `PROPOSED → COUNTERED`; the `Underwriter`
    countering the insured's outstanding counter moves it `COUNTERED → PROPOSED`,
    and the cycle `PROPOSED → COUNTERED → PROPOSED` may continue from either
    side." A counter "sets `last_actor_role` to the acting role and increments
    `round_count` by 1".

    Design: Difficulty/non_linear_state_machine/exclusion_term_counter_cycle_to_impasse
    """
    scenario = _quote_with_open_prior_acts_wording()
    term_id = scenario["prior_acts_term"]["id"]
    insured_headers = make_risk_manager_headers(scenario["insured"]["id"])

    countered = validate_success(
        api.counter_exclusion_term(
            term_id,
            counter_exclusion_term_payload(wording_variant="NONE", premium_impact_pct=0.00),
            insured_headers,
        ),
        200,
    )
    reproposed = validate_success(
        api.counter_exclusion_term(
            term_id,
            counter_exclusion_term_payload(
                wording_variant="RETRO_DATE_FULL_PRIOR_ACTS", premium_impact_pct=0.10
            ),
            UNDERWRITER,
        ),
        200,
    )

    assert_exclusion_term(countered)
    assert countered["status"] == "COUNTERED"
    assert countered["round_count"] == 2
    assert countered["last_actor_role"] == "RiskManager"
    assert countered["wording_variant"] == "NONE"
    assert countered["version"] == 2

    assert reproposed["status"] == "PROPOSED", (
        "the machine re-enters a state it already occupied"
    )
    assert reproposed["round_count"] == 3
    assert reproposed["last_actor_role"] == "Underwriter"
    assert reproposed["wording_variant"] == "RETRO_DATE_FULL_PRIOR_ACTS"
    assert reproposed["version"] == 3


def test_fourth_round_counter_forces_a_terminal_impasse(api):
    """PRD 3.3: "the acting role must differ from `last_actor_role` — a party may
    not counter or resolve its own outstanding wording — or the attempt is refused
    with `ERR_TERM_ACTOR_SEQUENCE`." "Negotiation is capped at four rounds. While
    incrementing `round_count` would leave it strictly below 4 the term simply
    flips to the other side of the cycle; the counter that would take
    `round_count` to exactly 4 instead drives the term to `IMPASSE`, setting
    `round_count` to 4 and `last_actor_role` to the acting role."

    Design: Difficulty/non_linear_state_machine/exclusion_term_counter_cycle_to_impasse
    """
    scenario = _quote_with_open_prior_acts_wording()
    term_id = scenario["prior_acts_term"]["id"]
    insured_headers = make_risk_manager_headers(scenario["insured"]["id"])

    validate_success(
        api.counter_exclusion_term(
            term_id,
            counter_exclusion_term_payload(wording_variant="NONE", premium_impact_pct=0.00),
            insured_headers,
        ),
        200,
    )
    validate_success(
        api.counter_exclusion_term(
            term_id,
            counter_exclusion_term_payload(
                wording_variant="RETRO_DATE_FULL_PRIOR_ACTS", premium_impact_pct=0.10
            ),
            UNDERWRITER,
        ),
        200,
    )

    # The underwriter countering its own outstanding wording is refused, and the
    # refused call must leave the term exactly where it was.
    validate_error(
        api.counter_exclusion_term(
            term_id,
            counter_exclusion_term_payload(wording_variant="BROAD", premium_impact_pct=0.05),
            UNDERWRITER,
        ),
        ApiErrorId.ERR_TERM_ACTOR_SEQUENCE,
        409,
    )
    unchanged = find_term(read_exclusion_terms(scenario["quote"]["id"]), "PRIOR_ACTS")
    assert unchanged["status"] == "PROPOSED"
    assert unchanged["round_count"] == 3
    assert unchanged["version"] == 3

    impasse = validate_success(
        api.counter_exclusion_term(
            term_id,
            counter_exclusion_term_payload(wording_variant="NONE", premium_impact_pct=0.00),
            insured_headers,
        ),
        200,
    )
    assert impasse["status"] == "IMPASSE", (
        "the same counter trigger that produced COUNTERED and PROPOSED now produces "
        "a terminal state"
    )
    assert impasse["round_count"] == 4
    assert impasse["last_actor_role"] == "RiskManager"
    assert impasse["version"] == 4
    assert impasse["agreed_variant"] is None, (
        "an IMPASSE term never freezes an agreed_variant, so it contributes nothing "
        "to the premium adjustment applied at binding"
    )

    # PRD 2.7: "checks are evaluated in ascending order and the first one violated
    # determines the response." Here the acting Underwriter differs from
    # last_actor_role RiskManager, so the alternation check passes and the term
    # state check is what fires.
    validate_error(
        api.counter_exclusion_term(
            term_id,
            counter_exclusion_term_payload(
                wording_variant="FINAL_ADJUDICATION", premium_impact_pct=-0.05
            ),
            UNDERWRITER,
        ),
        ApiErrorId.ERR_INVALID_TERM_STATE,
        409,
    )


def test_impasse_wording_permanently_blocks_the_bind(api):
    """PRD 3.3: "An `IMPASSE` term is terminal and can never become `AGREED`,
    which means it permanently blocks binding with
    `ERR_UNRESOLVED_EXCLUSION_TERMS`." PRD 3.4: "Every exclusion term on the quote
    must be in `AGREED` or `REJECTED`; a term still `PROPOSED` or `COUNTERED`, or
    stuck in `IMPASSE`, is refused with `ERR_UNRESOLVED_EXCLUSION_TERMS`."

    Design: Difficulty/non_linear_state_machine/exclusion_term_counter_cycle_to_impasse
    """
    scenario = _quote_with_open_prior_acts_wording()
    term_id = scenario["prior_acts_term"]["id"]
    quote_id = scenario["quote"]["id"]
    insured_headers = make_risk_manager_headers(scenario["insured"]["id"])

    for actor, variant, impact in (
        (insured_headers, "NONE", 0.00),
        (UNDERWRITER, "RETRO_DATE_FULL_PRIOR_ACTS", 0.10),
        (insured_headers, "NONE", 0.00),
    ):
        validate_success(
            api.counter_exclusion_term(
                term_id,
                counter_exclusion_term_payload(
                    wording_variant=variant, premium_impact_pct=impact
                ),
                actor,
            ),
            200,
        )
    assert find_term(read_exclusion_terms(quote_id), "PRIOR_ACTS")["status"] == "IMPASSE"

    # The CONDUCT term is AGREED, so the mandatory-conduct-exclusion check cannot
    # mask the wording failure.
    validate_error(
        api.accept_quote(quote_id, insured_headers),
        ApiErrorId.ERR_UNRESOLVED_EXCLUSION_TERMS,
        409,
    )

    assert read_quote(quote_id)["status"] == "OFFERED"
    policies, meta = validate_paginated(
        api.list_policies(UNDERWRITER, params={"quote_id": quote_id})
    )
    assert meta["total_count"] == 0, "no policy and no coverage part was created"
    assert policies == []
