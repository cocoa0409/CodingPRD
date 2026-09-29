"""The two-branch participation fork: the pinned review-load computation, the
divergent per-branch side effects, the budget that bounds them and the
compensations that give the minutes back.
"""
from test_helpers import (
    ADMIN, COUNSEL, ApiErrorId, adjust_exposure, assert_participation,
    assert_review_minutes_identity, business_justification_payload,
    clear_legally, create_approved_association, create_participation_payload,
    create_trained_employee, decide_association, justify_business,
    legal_clearance_payload, make_business_lead_headers, make_counsel_headers,
    nominate_participation, read_business_unit, read_participation,
    register_business_unit, reinstate_participation, set_clock,
    submit_participation, terminate_participation, termination_payload,
    validate_error, validate_paginated, validate_success,
)


def _pending_participation(approval_tier="TIER_1_LOW", competitor_density_pct=0,
                           bu_overrides=None, association=None,
                           purpose="Standards drafting delegate", trained=None,
                           unit=None):
    """Unit + trained SALES delegate + approved association + APPROVAL_PENDING."""
    unit = unit or register_business_unit(**(bu_overrides or {}))
    trained = trained or create_trained_employee(unit["id"], role_category="SALES")
    association = association or create_approved_association(
        approval_tier=approval_tier, competitor_density_pct=competitor_density_pct)
    participation = nominate_participation(
        unit["id"], association["id"], trained["employee"]["id"], purpose)
    submit_participation(participation["id"], unit["id"])
    return {"unit": unit, "trained": trained, "association": association,
            "participation": participation}


def test_review_load_surcharge_is_keyed_on_the_step_one_base_alone(api):
    """PRD §3.4: "**Step one** takes a base of 30 minutes, adds the
    association's tier surcharge — 0 minutes for `TIER_1_LOW`, 20 minutes for
    `TIER_2_MEDIUM`, 45 minutes for `TIER_3_HIGH` — and then adds 5 minutes for
    each 25-percentage-point step of competitor density, where the number of
    steps is the association's `competitor_density_pct` divided by 25 and
    rounded **up** to a whole number."
    PRD §3.4: "Take a `TIER_3_HIGH` association at 100 percent competitor
    density: the base is 30 plus 45 plus four density steps of 5 minutes each,
    giving 95; the pinned order selects the surcharge for 95, which is 15, and
    the review load is 110 minutes."
    PRD §3.4: "The alternative reading — re-selecting the surcharge from the
    110-minute total and converging on 125 — is forbidden. Implementations must
    produce 110."

    Design: Difficulty/combinatorial_formula/participation_review_load_pinned_evaluation_order
    """
    set_clock()
    bundle = _pending_participation("TIER_3_HIGH", 100,
                                    purpose="Standards committee observer")

    data = validate_success(api.decide_legal_clearance(
        bundle["participation"]["id"],
        legal_clearance_payload("CLEARED", "Observer only, no pricing agenda items"),
        COUNSEL))

    assert_participation(data)
    assert data["review_load_minutes"] == 110, (
        "the surcharge tier reads the 95-minute base, never the running total")
    assert data["review_minutes_reserved"] == 110


def test_cleared_legal_branch_reserves_the_load_against_the_unit_budget(api):
    """PRD §3.4: "A `decision` of `CLEARED` computes the counsel review load,
    freezes it onto `review_load_minutes`, sets `review_minutes_reserved` to
    that same figure, adds the reservation to the unit's
    `review_minutes_consumed`, increments the unit's `version` by 1, sets
    `legal_cleared` to true, and records the acting counsel's `X-User-ID` into
    `legal_cleared_by_user_id`."
    PRD §3.4: "Whichever branch lands first moves `APPROVAL_PENDING →
    PARTIALLY_APPROVED` and applies only its own branch-specific effects."

    Design: Difficulty/combinatorial_formula/participation_review_load_pinned_evaluation_order
    """
    set_clock()
    bundle = _pending_participation("TIER_3_HIGH", 100)

    data = validate_success(api.decide_legal_clearance(
        bundle["participation"]["id"],
        legal_clearance_payload("CLEARED", "Observer only"), COUNSEL))

    assert data["status"] == "PARTIALLY_APPROVED"
    assert data["legal_cleared"] is True
    assert data["business_justified"] is False
    unit = read_business_unit(bundle["unit"]["id"])
    assert unit["review_minutes_consumed"] == 110
    assert_review_minutes_identity(unit, [read_participation(data["id"])])


def test_business_branch_landing_first_reserves_no_counsel_minutes(api):
    """PRD §3.4: "The **business branch** is the lead's. It carries a
    `justification`, records it into `business_justification`, and sets
    `business_justified` to true. This branch reserves **no** counsel minutes at
    all and leaves `review_load_minutes` sitting at 0 if it arrives first."

    Design: Difficulty/non_linear_state_machine/participation_fork_join_divergent_branch_side_effects
    """
    set_clock()
    bundle = _pending_participation("TIER_2_MEDIUM", 25,
                                    purpose="Technical committee delegate")

    data = validate_success(api.record_business_justification(
        bundle["participation"]["id"],
        business_justification_payload(
            "Only forum where the new bonding standard is drafted"),
        make_business_lead_headers(bundle["unit"]["id"])))

    assert data["status"] == "PARTIALLY_APPROVED"
    assert data["business_justified"] is True
    assert data["legal_cleared"] is False
    assert data["review_load_minutes"] == 0
    assert read_business_unit(bundle["unit"]["id"])["review_minutes_consumed"] == 0


def test_legal_branch_landing_second_completes_the_join_into_active(api):
    """PRD §3.4: "Whichever lands second moves `PARTIALLY_APPROVED → ACTIVE`,
    applying its own effects first and then joining: with `legal_cleared` and
    `business_justified` both true, the participation becomes `ACTIVE`."
    PRD §3.4: "That last field is the segregation-of-duties key that will later
    bar this same counsel from reviewing the participation's minutes."

    Design: Difficulty/non_linear_state_machine/participation_fork_join_divergent_branch_side_effects
    """
    set_clock()
    bundle = _pending_participation("TIER_2_MEDIUM", 25,
                                    purpose="Technical committee delegate")
    justify_business(bundle["participation"]["id"], bundle["unit"]["id"],
                     "Only forum where the new bonding standard is drafted")

    data = validate_success(api.decide_legal_clearance(
        bundle["participation"]["id"],
        legal_clearance_payload("CLEARED", "Agenda pre-cleared; no commercial items"),
        make_counsel_headers("counsel-7")))

    assert data["status"] == "ACTIVE"
    assert data["review_load_minutes"] == 55
    assert data["review_minutes_reserved"] == 55
    assert data["legal_cleared_by_user_id"] == "counsel-7"
    assert read_business_unit(bundle["unit"]["id"])["review_minutes_consumed"] == 55


def test_zero_competitor_density_contributes_no_density_step(api):
    """PRD §3.4: "A density of exactly 0 contributes exactly 0 steps; any
    density above 0 and up to and including 25 contributes exactly 1 step; a
    density of exactly 25 contributes 1 step and not 2."
    PRD §3.4: "**Step two** selects an escalation surcharge keyed on the
    step-one base **alone**: 0 minutes when the base is below 60, 15 minutes
    when the base is at least 60 and below 100, and 30 minutes when the base is
    at least 100."

    Design: Difficulty/boundary_precision_check/zero_competitor_density_contributes_zero_review_steps
    """
    set_clock()
    bundle = _pending_participation("TIER_1_LOW", 0, purpose="Zero density delegate")

    data = validate_success(api.decide_legal_clearance(
        bundle["participation"]["id"],
        legal_clearance_payload("CLEARED", "No competitor members"), COUNSEL))

    assert data["review_load_minutes"] == 30, "30 base, no tier surcharge, no steps"
    assert data["status"] == "PARTIALLY_APPROVED"
    assert read_business_unit(bundle["unit"]["id"])["review_minutes_consumed"] == 30


def test_density_of_exactly_twenty_five_contributes_one_step_not_two(api):
    """PRD §3.4: "A density of exactly 0 contributes exactly 0 steps; any
    density above 0 and up to and including 25 contributes exactly 1 step; a
    density of exactly 25 contributes 1 step and not 2."
    PRD §3.4: "**Step three** adds the two together to give
    `review_load_minutes`."

    Design: Difficulty/boundary_precision_check/zero_competitor_density_contributes_zero_review_steps
    """
    set_clock()
    unit = register_business_unit()
    trained = create_trained_employee(unit["id"], role_category="SALES")

    zero = _pending_participation("TIER_1_LOW", 0, unit=unit, trained=trained,
                                  purpose="Zero density delegate")
    quarter = _pending_participation("TIER_1_LOW", 25, unit=unit, trained=trained,
                                     purpose="Quarter density delegate")

    zero_cleared = clear_legally(zero["participation"]["id"])
    quarter_cleared = clear_legally(quarter["participation"]["id"])

    assert zero_cleared["review_load_minutes"] == 30
    assert quarter_cleared["review_load_minutes"] == 35, (
        "a density of exactly 25 is one step of 5 minutes, not two")
    assert zero_cleared["status"] == "PARTIALLY_APPROVED"
    assert quarter_cleared["status"] == "PARTIALLY_APPROVED"
    assert read_business_unit(unit["id"])["review_minutes_consumed"] == 65


def test_terminating_an_active_participation_releases_its_reservation(api):
    """PRD §3.4: "Its compensating effect is to release the reservation: the
    unit's `review_minutes_consumed` is reduced by the participation's
    `review_minutes_reserved`, that field is reset to 0, and the unit's
    `version` increments by 1."
    PRD §3.4: "Termination, available to the business lead and to counsel alike
    and carrying a `reason`, is legal from `DRAFT`, `APPROVAL_PENDING`,
    `PARTIALLY_APPROVED`, `ACTIVE`, `SUSPENDED` and `UNDER_REVIEW`, and lands on
    the terminal `TERMINATED`."

    Design: Difficulty/compensating_invariant/participation_termination_restores_review_minutes_exactly
    """
    set_clock()
    unit = register_business_unit()
    trained = create_trained_employee(unit["id"], role_category="SALES")
    p55 = _pending_participation("TIER_2_MEDIUM", 25, unit=unit, trained=trained,
                                 purpose="Technical committee delegate")
    clear_legally(p55["participation"]["id"], notes="Agenda pre-cleared")
    justify_business(p55["participation"]["id"], unit["id"])
    p110 = _pending_participation("TIER_3_HIGH", 100, unit=unit, trained=trained,
                                  purpose="Standards committee observer")
    clear_legally(p110["participation"]["id"], notes="Observer only")
    justify_business(p110["participation"]["id"], unit["id"])

    assert read_business_unit(unit["id"])["review_minutes_consumed"] == 165

    data = validate_success(api.terminate_participation(
        p55["participation"]["id"],
        termination_payload("Forum merged into the European council"),
        make_business_lead_headers(unit["id"])))

    assert data["status"] == "TERMINATED"
    assert data["review_minutes_reserved"] == 0
    assert data["review_load_minutes"] == 55, "the computed load is retained"
    assert read_business_unit(unit["id"])["review_minutes_consumed"] == 110


def test_sibling_participation_keeps_its_reservation_through_a_termination(api):
    """PRD §3.1: "The consumed-minutes figure is the sum of
    `review_minutes_reserved` across the unit's participations whose status is
    `PARTIALLY_APPROVED`, `ACTIVE`, `SUSPENDED` or `UNDER_REVIEW`."
    PRD §3.4: "Its compensating effect is to release the reservation: the unit's
    `review_minutes_consumed` is reduced by the participation's
    `review_minutes_reserved`, that field is reset to 0, and the unit's
    `version` increments by 1."

    Design: Difficulty/compensating_invariant/participation_termination_restores_review_minutes_exactly
    """
    set_clock()
    unit = register_business_unit()
    trained = create_trained_employee(unit["id"], role_category="SALES")
    p55 = _pending_participation("TIER_2_MEDIUM", 25, unit=unit, trained=trained,
                                 purpose="Technical committee delegate")
    clear_legally(p55["participation"]["id"], notes="Agenda pre-cleared")
    justify_business(p55["participation"]["id"], unit["id"])
    p110 = _pending_participation("TIER_3_HIGH", 100, unit=unit, trained=trained,
                                  purpose="Standards committee observer")
    clear_legally(p110["participation"]["id"], notes="Observer only")
    justify_business(p110["participation"]["id"], unit["id"])

    terminate_participation(p55["participation"]["id"], unit["id"])

    survivor = read_participation(p110["participation"]["id"])
    assert survivor["status"] == "ACTIVE"
    assert survivor["review_minutes_reserved"] == 110

    stored_unit = read_business_unit(unit["id"])
    assert_review_minutes_identity(
        stored_unit,
        [read_participation(p55["participation"]["id"]), survivor])


def test_legal_clearance_beyond_the_review_minutes_budget_is_refused(api):
    """PRD §3.4: "Only if the unit's `review_minutes_consumed` plus that
    computed load stays within `review_minutes_budget` does the clearance
    proceed; otherwise it is refused with `ERR_REVIEW_MINUTES_EXCEEDED` and
    nothing at all is reserved."
    PRD §2.7: "**Review-minute budget.** The unit's `review_minutes_consumed`
    plus the review load this clearance would reserve is no greater than the
    unit's `review_minutes_budget` — otherwise `ERR_REVIEW_MINUTES_EXCEEDED`,
    HTTP 422."

    Design: Corner/validations/legal_clearance_exceeding_review_minutes_budget_is_refused
    """
    set_clock()
    unit = register_business_unit(name="Tight Budget Unit", market_code="EU-TB",
                                  review_minutes_budget=100)
    trained = create_trained_employee(unit["id"], role_category="SALES")
    p55 = _pending_participation("TIER_2_MEDIUM", 25, unit=unit, trained=trained,
                                 purpose="Technical committee delegate")
    clear_legally(p55["participation"]["id"], notes="Agenda pre-cleared")
    p110 = _pending_participation("TIER_3_HIGH", 100, unit=unit, trained=trained,
                                  purpose="Standards committee observer")

    resp = api.decide_legal_clearance(
        p110["participation"]["id"],
        legal_clearance_payload("CLEARED", "Observer only"), COUNSEL)

    validate_error(resp, ApiErrorId.ERR_REVIEW_MINUTES_EXCEEDED.value)
    assert resp.status_code == 422

    refused = read_participation(p110["participation"]["id"])
    assert refused["status"] == "APPROVAL_PENDING"
    assert refused["review_load_minutes"] == 0, "nothing at all is reserved"
    assert read_business_unit(unit["id"])["review_minutes_consumed"] == 55


def test_duplicate_live_participation_triple_is_refused_until_terminated(api):
    """PRD §3.4: "Nomination is refused if the unit's posture is `FROZEN`,
    refused if it is merely `RESTRICTED`, refused if the association is not
    `APPROVED`, refused when a `SALES` or `PRICING` delegate's training is not
    current, and refused with `ERR_DUPLICATE_PARTICIPATION` when the unit
    already holds a participation with the same association and the same
    delegate in any status other than `REJECTED` or `TERMINATED`."
    PRD §3.4: "Terminating a draft frees that combination for a fresh
    nomination."

    Design: Corner/validations/duplicate_live_participation_triple_is_refused
    """
    set_clock()
    unit = register_business_unit()
    trained = create_trained_employee(unit["id"], role_category="SALES")
    association = create_approved_association(
        approval_tier="TIER_2_MEDIUM", competitor_density_pct=25)
    first = nominate_participation(unit["id"], association["id"],
                                   trained["employee"]["id"],
                                   "Technical committee delegate")

    duplicate = api.create_participation(
        create_participation_payload(unit["id"], association["id"],
                                     trained["employee"]["id"],
                                     "Duplicate nomination"),
        make_business_lead_headers(unit["id"]))
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_PARTICIPATION.value)
    assert duplicate.status_code == 409

    terminated = terminate_participation(first["id"], unit["id"],
                                         "Nomination withdrawn")
    assert terminated["status"] == "TERMINATED"

    renomination = validate_success(api.create_participation(
        create_participation_payload(unit["id"], association["id"],
                                     trained["employee"]["id"],
                                     "Re-nomination after withdrawal"),
        make_business_lead_headers(unit["id"])), 201)
    assert renomination["status"] == "DRAFT"
    assert read_business_unit(unit["id"])["review_minutes_consumed"] == 0


def test_prohibiting_an_approved_association_terminates_its_live_participations(api):
    """PRD §3.4: "Prohibiting an association that had already been approved is
    the destructive case: every participation for that association whose status
    is `PARTIALLY_APPROVED`, `ACTIVE`, `SUSPENDED` or `UNDER_REVIEW` is driven
    to `TERMINATED`, processed in `created_at` ascending order, and each of
    those terminations releases its reserved review minutes back to its own
    business unit's budget."
    PRD §3.4: "A decision of `PROHIBITED` moves either `PROPOSED → PROHIBITED`
    or `APPROVED → PROHIBITED`, and `PROHIBITED` is terminal."

    Design: Corner/state_machines/association_prohibition_terminates_live_participations_and_releases_minutes
    """
    set_clock()
    bundle = _pending_participation("TIER_2_MEDIUM", 25,
                                    purpose="Technical committee delegate")
    clear_legally(bundle["participation"]["id"], notes="Agenda pre-cleared")
    justify_business(bundle["participation"]["id"], bundle["unit"]["id"],
                     "Only forum where the new bonding standard is drafted")
    assert read_business_unit(bundle["unit"]["id"])["review_minutes_consumed"] == 55

    association = decide_association(bundle["association"]["id"], "PROHIBITED")

    assert association["status"] == "PROHIBITED"
    participation = read_participation(bundle["participation"]["id"])
    assert participation["status"] == "TERMINATED"
    assert participation["review_minutes_reserved"] == 0
    assert read_business_unit(bundle["unit"]["id"])["review_minutes_consumed"] == 0


def test_thawed_unit_needs_an_explicit_reinstatement_to_return_to_active(api):
    """PRD §2.8: "Neither thaw auto-reinstates a suspended participation.
    Reinstatement is an explicit act by counsel."
    PRD §2.8: "Suspension does **not** release the participation's reserved
    review minutes — the reservation is held through the freeze."
    PRD §3.4: "Counsel reinstates from either: `SUSPENDED → ACTIVE` requires the
    unit no longer to be `FROZEN` and requires both `legal_cleared` and
    `business_justified` to be true, while `UNDER_REVIEW → ACTIVE` requires the
    unit no longer to be `FROZEN` and requires that no attendance of that
    participation is still sitting in `FLAGGED`."

    Design: Corner/state_machines/participation_reinstatement_from_suspended_returns_it_to_active
    """
    set_clock()
    bundle = _pending_participation(
        "TIER_1_LOW", 0,
        bu_overrides={"name": "Industrial Coatings EMEA", "market_code": "EU-COAT",
                      "exposure_budget_points": 200})
    clear_legally(bundle["participation"]["id"])
    justify_business(bundle["participation"]["id"], bundle["unit"]["id"])
    unit_id = bundle["unit"]["id"]

    adjust_exposure(unit_id, 90, "Interim loading pending an internal investigation")
    assert read_business_unit(unit_id)["posture"] == "FROZEN"
    assert read_participation(bundle["participation"]["id"])["status"] == "SUSPENDED"

    adjust_exposure(unit_id, -90, "Investigation closed with no findings")
    thawed = read_business_unit(unit_id)
    assert thawed["exposure_points"] == 0.00
    assert thawed["posture"] == "OPEN"
    assert read_participation(bundle["participation"]["id"])["status"] == "SUSPENDED", (
        "thawing never auto-reinstates a suspended participation")

    reinstated = reinstate_participation(bundle["participation"]["id"])
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["review_minutes_reserved"] == 30
    assert read_business_unit(unit_id)["review_minutes_consumed"] == 30
