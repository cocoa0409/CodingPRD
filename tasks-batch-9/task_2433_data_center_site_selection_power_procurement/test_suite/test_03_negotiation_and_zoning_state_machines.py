"""Cyclic and counter-bounded state machines: negotiation rounds and zoning dockets."""

from test_helpers import (
    CHAIR_USER_ID,
    EXPECTED_CONDITIONS_ESCROW_USD,
    EXPECTED_MITIGATION_COST_USD,
    NEGOTIATOR_USER_ID,
    TEST_USERS,
    add_objection,
    api_client,
    assert_money,
    assert_status,
    create_authority_round_payload,
    create_zoning_decision_payload,
    decide_zoning,
    file_authority_round,
    file_company_round,
    file_zoning,
    list_site_negotiations,
    make_chair_headers,
    open_negotiation,
    setup_draft_site,
    sign_negotiation,
    validate_error,
    validate_success,
)


def _read_negotiation(site_id, negotiation_id):
    """Re-read a negotiation through the nested listing on its own site, which is the
    only read channel the contract offers for a negotiation."""
    listing = list_site_negotiations(site_id)
    for item in listing["data"]:
        if item["id"] == negotiation_id:
            return item
    raise AssertionError(f"negotiation {negotiation_id} is not listed under its site")


def _negotiation_after_four_rounds():
    """A STATE negotiation walked COMPANY, AUTHORITY, COMPANY, AUTHORITY, which
    leaves it expecting the company again."""
    env = setup_draft_site()
    negotiation = open_negotiation(env["site"]["id"], "STATE")
    file_company_round(negotiation["id"])
    file_authority_round(negotiation["id"])
    file_company_round(negotiation["id"])
    fourth = file_authority_round(negotiation["id"])
    return env, negotiation, fourth


def _docket_with_five_objections():
    """A 55/62 dBA docket offering FULL_ENCLOSURE, with three noise and two water
    objections, so the demanded tier settles at BERM_AND_SCREENING."""
    env = setup_draft_site()
    docket = file_zoning(env["site"]["id"], visual_mitigation_tier="FULL_ENCLOSURE")
    for reference in ("CMT-001", "CMT-002", "CMT-003"):
        add_objection(docket["id"], objection_type="NOISE", commenter_reference=reference)
    for reference in ("CMT-004", "CMT-005"):
        add_objection(docket["id"], objection_type="WATER", commenter_reference=reference)
    return env, docket


def test_negotiation_ping_pongs_between_the_two_pending_states_each_round():
    """Four rounds traverse only two non-terminal states: the opening company offer
    moves the negotiation to `AUTHORITY_COUNTER_PENDING`, the counter to
    `COMPANY_OFFER_PENDING`, and rounds three and four repeat the pair. `round_count`
    therefore reaches 4 while the negotiation has never held more than two distinct
    statuses, and `last_party` always names the side that just acted.

    PRD §3.7: "The opening company round drives the negotiation from `DRAFT` to `AUTHORITY_COUNTER_PENDING`, and that first round additionally requires the referenced site to be in `DRAFT` or `SCREENED` status."
    PRD §3.7: "The authority's counter then drives it from `AUTHORITY_COUNTER_PENDING` to `COMPANY_OFFER_PENDING`, and a further company round drives it back from `COMPANY_OFFER_PENDING` to `AUTHORITY_COUNTER_PENDING`, so the pair of states cycles once per round pair for as long as the two sides keep talking."
    PRD §3.7: "Every round, from either party, overwrites all five standing terms with that round's proposal, increments `round_count` by one, records `last_party` as the submitting party, flips `status` to the other party's pending state, recomputes all four money figures from the new terms, and increments the negotiation's `version` by one."

    Design: Difficulty/non_linear_state_machine/incentive_negotiation_party_alternation_cycle
    """
    env = setup_draft_site()
    negotiation = open_negotiation(env["site"]["id"], "STATE")

    first = file_company_round(negotiation["id"])
    assert_status(first, "AUTHORITY_COUNTER_PENDING", "after round 1")
    assert first["round_count"] == 1
    assert first["last_party"] == "COMPANY"

    second = file_authority_round(negotiation["id"])
    assert_status(second, "COMPANY_OFFER_PENDING", "after round 2")
    assert second["round_count"] == 2
    assert second["last_party"] == "AUTHORITY"

    third = file_company_round(negotiation["id"])
    assert_status(third, "AUTHORITY_COUNTER_PENDING", "after round 3")
    assert third["round_count"] == 3
    assert third["last_party"] == "COMPANY"

    fourth = file_authority_round(negotiation["id"])
    assert_status(fourth, "COMPANY_OFFER_PENDING", "after round 4")
    assert fourth["round_count"] == 4
    assert fourth["last_party"] == "AUTHORITY"


def test_each_round_reprices_the_money_from_that_rounds_own_terms():
    """Because every round overwrites all five standing terms, the money after round
    four reflects the authority's leaner package — 800 million of capital in the
    5.50 percent band at a 0.75 exemption, a five-year abatement at 0.60, and a jobs
    commitment of 60 that pulls the harsher 0.60 clawback share — rather than the far
    larger figures the company's rounds produced.

    PRD §3.7: "Every round, from either party, overwrites all five standing terms with that round's proposal, increments `round_count` by one, records `last_party` as the submitting party, flips `status` to the other party's pending state, recomputes all four money figures from the new terms, and increments the negotiation's `version` by one."
    PRD §3.7: "Only this negotiation's own standing terms enter that computation; a sibling negotiation on the same site never contributes."
    PRD §3.7: "Fourth, `npv_incentive_usd` is the sales-tax benefit plus the abatement present value, rounded to 2 decimal places, and `clawback_exposure_usd` is that total multiplied by a clawback share, rounded to 2 decimal places — where the share is the gentler 0.40 when the company has committed to at least 100 permanent jobs and the harsher 0.60 when it has committed to fewer."

    Design: Difficulty/non_linear_state_machine/incentive_negotiation_party_alternation_cycle
    """
    _env, _negotiation, fourth = _negotiation_after_four_rounds()

    assert_money(fourth["sales_tax_benefit_usd"], 20460000.00, "sales_tax_benefit_usd")
    assert_money(fourth["abatement_npv_usd"], 37639812.47, "abatement_npv_usd")
    assert_money(fourth["npv_incentive_usd"], 58099812.47, "npv_incentive_usd")
    assert_money(fourth["clawback_exposure_usd"], 34859887.48, "clawback_exposure_usd")


def test_authority_cannot_answer_its_own_counter_offer():
    """After four rounds the table waits on the company, so a fifth authority round is
    the wrong party for the status and is refused. The refusal is inert: `round_count`
    stays at 4 and the standing money figures are exactly those the fourth round wrote.

    PRD §3.7: "A `COMPANY` round is expected while the negotiation is in `DRAFT` or in `COMPANY_OFFER_PENDING`, and an `AUTHORITY` round is expected while it is in `AUTHORITY_COUNTER_PENDING`; a round whose declared party is not the party the status expects is rejected with `ERR_WRONG_NEGOTIATION_PARTY`, and a round filed from any other status — from `SIGNED` or `RATIFIED` — is rejected with `ERR_NEGOTIATION_INVALID_STATE`."
    PRD §2.11: "**Negotiation turn** — the round's `submitted_by_party` is the party the status expects, on `POST /incentive-negotiations/{id}/rounds`; otherwise `ERR_WRONG_NEGOTIATION_PARTY`."

    Design: Difficulty/non_linear_state_machine/incentive_negotiation_party_alternation_cycle
    """
    env, negotiation, _fourth = _negotiation_after_four_rounds()

    response = api_client.create_negotiation_round(
        negotiation["id"],
        create_authority_round_payload(
            sales_tax_exemption_pct=0.70, abatement_pct=0.55
        ),
        TEST_USERS["authority_headers"],
    )

    validate_error(response, "ERR_WRONG_NEGOTIATION_PARTY", 409)

    refreshed = _read_negotiation(env["site"]["id"], negotiation["id"])
    assert refreshed["round_count"] == 4
    assert_status(refreshed, "COMPANY_OFFER_PENDING", "negotiation")
    assert_money(
        refreshed["npv_incentive_usd"], 58099812.47, "npv_incentive_usd after refusal"
    )


def test_continuance_self_loops_in_place_up_to_its_budget_of_two():
    """The first continuance carries the docket out of `SUBMITTED` into `CONTINUED`;
    the second continues an already-continued docket, self-looping on the same state
    while the counter climbs to 2. Each continuance re-derives the demanded tier and
    the money that follows it, which the five recorded objections and the 7.0 dBA
    excess pin at `BERM_AND_SCREENING`.

    PRD §3.6: "A **continuance** carries the docket from `SUBMITTED` to `CONTINUED`, and a docket already in `CONTINUED` may be continued again, self-looping in place."
    PRD §3.6: "Both routes increment `continuance_count` by one, re-derive the `required_mitigation_tier`, the `mitigation_cost_usd` and the `conditions_escrow_usd`, and recompute the owning site's `site_capital_commitment_usd`."

    Design: Difficulty/non_linear_state_machine/zoning_continuance_self_loop_then_approval_fork
    """
    _env, docket = _docket_with_five_objections()

    first = decide_zoning(
        docket["id"], outcome="CONTINUED", decision_note="Continued for traffic study."
    )
    assert_status(first, "CONTINUED", "after the first continuance")
    assert first["continuance_count"] == 1

    second = decide_zoning(
        docket["id"],
        outcome="CONTINUED",
        decision_note="Continued for acoustic modelling review.",
    )
    assert_status(second, "CONTINUED", "after the second continuance")
    assert second["continuance_count"] == 2
    assert second["required_mitigation_tier"] == "BERM_AND_SCREENING"
    assert_money(
        second["mitigation_cost_usd"], EXPECTED_MITIGATION_COST_USD, "mitigation_cost_usd"
    )
    assert_money(
        second["conditions_escrow_usd"],
        EXPECTED_CONDITIONS_ESCROW_USD,
        "conditions_escrow_usd",
    )


def test_third_continuance_is_refused_and_the_same_endpoint_then_approves():
    """A third continuance exhausts the budget and is refused without incrementing the
    counter, leaving the docket in `CONTINUED`. The very same decide endpoint then takes
    the approval fork from `CONTINUED`, and that route has identical effects to
    approving straight from `SUBMITTED`: the demanded `BERM_AND_SCREENING` tier is
    priced at 2975000.00 and escrowed at 446250.00.

    PRD §3.6: "Either route requires that `continuance_count` is still strictly below 2 continuances; the third continuance request is refused with `ERR_ZONING_CONTINUANCE_EXHAUSTED`."
    PRD §3.6: "An **approval with conditions** carries the docket from `SUBMITTED` to `APPROVED_WITH_CONDITIONS`, or equally from `CONTINUED` to `APPROVED_WITH_CONDITIONS` after one or two continuances, and the two routes have identical effects."
    PRD §3.6: "Approval has one gate: the applicant's offered mitigation must rank at least as high as the tier the analysis demands, where the ranking places `NONE` lowest, then `BERM`, then `BERM_AND_SCREENING`, then `FULL_ENCLOSURE` highest."

    Design: Difficulty/non_linear_state_machine/zoning_continuance_self_loop_then_approval_fork
    """
    _env, docket = _docket_with_five_objections()
    decide_zoning(
        docket["id"], outcome="CONTINUED", decision_note="Continued for traffic study."
    )
    decide_zoning(
        docket["id"],
        outcome="CONTINUED",
        decision_note="Continued for acoustic modelling review.",
    )

    refused = api_client.decide_zoning_application(
        docket["id"],
        create_zoning_decision_payload(
            outcome="CONTINUED", decision_note="Third continuance requested."
        ),
        TEST_USERS["authority_headers"],
    )
    validate_error(refused, "ERR_ZONING_CONTINUANCE_EXHAUSTED", 409)

    approved = decide_zoning(
        docket["id"],
        outcome="APPROVED_WITH_CONDITIONS",
        decision_note="Approved with enclosure conditions.",
    )

    assert_status(approved, "APPROVED_WITH_CONDITIONS", "zoning docket")
    assert approved["continuance_count"] == 2
    assert approved["required_mitigation_tier"] == "BERM_AND_SCREENING"
    assert_money(
        approved["mitigation_cost_usd"],
        EXPECTED_MITIGATION_COST_USD,
        "mitigation_cost_usd",
    )
    assert_money(
        approved["conditions_escrow_usd"],
        EXPECTED_CONDITIONS_ESCROW_USD,
        "conditions_escrow_usd",
    )


def test_ratification_is_blocked_while_the_site_docket_is_merely_submitted():
    """The term sheet is properly `SIGNED` and the chair is not the signer, yet
    ratification is still refused because a third entity — the site's zoning docket,
    joined only through `site_id` — has not reached `APPROVED_WITH_CONDITIONS`. The
    negotiation is unmoved: it stays `SIGNED` with no ratifier stamped.

    PRD §3.7: "It requires the negotiation to be in `SIGNED` — otherwise `ERR_NEGOTIATION_INVALID_STATE` — that the acting operator is not the operator who signed, otherwise `ERR_SEGREGATION_OF_DUTIES`, and that the site's zoning docket has already reached `APPROVED_WITH_CONDITIONS`, otherwise `ERR_ZONING_NOT_APPROVED`."
    PRD §3.6: "A freshly filed docket sits at `status` `SUBMITTED` with `continuance_count` of 0 and `objection_count` of 0, and its acoustic and mitigation figures are already computed from the noise inputs on the assumption of zero objections."

    Design: Difficulty/cross_entity_state_dependency/negotiation_ratify_requires_zoning_approved
    """
    env = setup_draft_site()
    file_zoning(env["site"]["id"], visual_mitigation_tier="FULL_ENCLOSURE")
    negotiation = open_negotiation(env["site"]["id"], "STATE")
    file_company_round(negotiation["id"])
    file_authority_round(negotiation["id"])
    sign_negotiation(negotiation["id"])

    response = api_client.ratify_incentive_negotiation(
        negotiation["id"], make_chair_headers()
    )

    validate_error(response, "ERR_ZONING_NOT_APPROVED", 409)

    refreshed = _read_negotiation(env["site"]["id"], negotiation["id"])
    assert_status(refreshed, "SIGNED", "negotiation")
    assert refreshed["ratified_by_user_id"] is None


def test_ratification_succeeds_once_the_board_approves_and_stamps_both_actors():
    """Approving the docket cures the only unmet condition, and the identical ratify
    call then carries the negotiation `SIGNED` to `RATIFIED`. Both halves of the
    two-person decision are visible on the row afterwards: the negotiator who signed
    and the chair who ratified are recorded as distinct operators.

    PRD §3.7: "Ratification belongs to the `CapitalCommitteeChair` and moves the negotiation `SIGNED` to `RATIFIED`, stamping `ratified_by_user_id`."
    PRD §3.7: "Signature moves the negotiation `COMPANY_OFFER_PENDING` to `SIGNED` and stamps the acting operator as `signed_by_user_id`, which becomes the comparand for the duty separation at ratification."

    Design: Difficulty/cross_entity_state_dependency/negotiation_ratify_requires_zoning_approved
    """
    env = setup_draft_site()
    docket = file_zoning(env["site"]["id"], visual_mitigation_tier="FULL_ENCLOSURE")
    negotiation = open_negotiation(env["site"]["id"], "STATE")
    file_company_round(negotiation["id"])
    file_authority_round(negotiation["id"])
    sign_negotiation(negotiation["id"])
    decide_zoning(
        docket["id"],
        outcome="APPROVED_WITH_CONDITIONS",
        decision_note="Approved with enclosure conditions.",
    )

    ratified = validate_success(
        api_client.ratify_incentive_negotiation(negotiation["id"], make_chair_headers())
    )
    assert ratified["status"] == "RATIFIED"

    refreshed = _read_negotiation(env["site"]["id"], negotiation["id"])
    assert_status(refreshed, "RATIFIED", "negotiation")
    assert refreshed["ratified_by_user_id"] == CHAIR_USER_ID
    assert refreshed["signed_by_user_id"] == NEGOTIATOR_USER_ID
