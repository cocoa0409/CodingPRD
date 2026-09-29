"""Capital projects funded by the CFC and the two-signature capital draw."""

from test_helpers import (
    ADMIN,
    TREASURY,
    TREASURY_2,
    FINANCE_OFFICER_2_USER_ID,
    ApiErrorId,
    UNKNOWN_UUID,
    assert_disbursement,
    assert_trust_conservation,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _funded_project_with_two_draws(api):
    """A trust holding 750,000 cents of capital fund behind a FUNDED 2,000,000 cent project,
    with two draws of 300,000 and 200,000 cents requested by fin-1."""
    scenario = fx.setup_two_receipt_trust(
        api,
        with_obligation=True,
        with_project=True,
        project_overrides={"project_name": "Bus maintenance bay", "budget_cents": 2_000_000},
    )
    project_id = scenario["project"]["id"]
    scenario["draw_ok"] = fx.request_draw(api, project_id, 300_000, TREASURY, "Bay slab pour")
    scenario["draw_no"] = fx.request_draw(api, project_id, 200_000, TREASURY, "Signage")
    return scenario


def test_authorising_a_draw_encumbers_capital_cash(api):
    """PRD §3.8: "On success the draw moves to `AUTHORIZED`, `authorized_by_user_id` is
    stamped from `X-User-ID`, `trust_capital_fund_cents` falls by `amount_cents` while
    `trust_encumbered_cents` rises by the same amount, the project's `encumbered_cents` rises
    by `amount_cents`, and the draw's `version`, the project's `version` and the facility's
    `version` each advance by 1."
    PRD §3.8: "Thereafter `disbursed_cents` is the total `amount_cents` over the project's
    `PAID` draws, `encumbered_cents` is the total `amount_cents` over its `AUTHORIZED` draws,
    `draw_request_count` counts every draw ever created against it, and `rejected_draw_count`
    counts those that reached `REJECTED`."

    Design: Difficulty/non_linear_state_machine/capital_draw_fork_authorize_moves_cash_reject_moves_none
    """
    scenario = _funded_project_with_two_draws(api)

    authorized = validate_success(
        api.authorize_disbursement(scenario["draw_ok"]["id"], TREASURY_2)
    )

    assert_disbursement(authorized)
    assert authorized["status"] == "AUTHORIZED"
    assert authorized["authorized_by_user_id"] == FINANCE_OFFICER_2_USER_ID
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_capital_fund_cents"] == 450_000, (
        "authorisation moves 300,000 cents out of the capital bucket"
    )
    assert facility["trust_encumbered_cents"] == 300_000
    assert facility["trust_disbursed_cents"] == 0
    project = validate_success(api.get_project(scenario["project"]["id"], ADMIN))
    assert project["encumbered_cents"] == 300_000
    assert project["disbursed_cents"] == 0


def test_rejecting_a_draw_moves_no_cash(api):
    """PRD §3.8: "On success the draw moves to the terminal `REJECTED`, the project's
    `rejected_draw_count` rises by 1, not a single trust bucket moves, and the draw's
    `version` and the project's `version` each advance by 1. That absent bucket movement is
    the entire difference between the two branches."
    PRD §3.8: "A created draw opens in `REQUESTED` status with `requested_by_user_id` stamped
    from the caller's `X-User-ID` and `authorized_by_user_id` null, raises the project's
    `draw_request_count` by 1, and advances the project's `version` by 1."

    Design: Difficulty/non_linear_state_machine/capital_draw_fork_authorize_moves_cash_reject_moves_none
    """
    scenario = _funded_project_with_two_draws(api)

    rejected = validate_success(
        api.reject_disbursement(scenario["draw_no"]["id"], TREASURY_2)
    )

    assert rejected["status"] == "REJECTED"
    assert rejected["authorized_by_user_id"] is None, (
        "the money-free branch never stamps an authoriser"
    )
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_capital_fund_cents"] == 750_000, (
        "the rejecting branch touches no trust bucket at all"
    )
    assert facility["trust_encumbered_cents"] == 0
    assert facility["trust_disbursed_cents"] == 0
    project = validate_success(api.get_project(scenario["project"]["id"], ADMIN))
    assert project["rejected_draw_count"] == 1
    assert project["draw_request_count"] == 2
    assert project["encumbered_cents"] == 0


def test_unfunded_project_is_reported_before_a_dry_capital_bucket(api):
    """PRD §3.8: "it requires the project's status to be exactly `FUNDED`, rejecting anything
    else with `ERR_PROJECT_NOT_FUNDED` (HTTP 409); it requires the facility's
    `bond_coverage_status` to be `SATISFIED`, rejecting a deficient covenant with
    `ERR_BOND_COVENANT_DEFICIENT` (HTTP 409); it requires the project's `disbursed_cents` plus
    `encumbered_cents` plus this draw's `amount_cents` to be no greater than `budget_cents`,
    rejecting an overrun with `ERR_PROJECT_BUDGET_EXCEEDED` (HTTP 409); and it requires the
    facility's `trust_capital_fund_cents` to be at least `amount_cents`, rejecting a dry
    bucket with `ERR_CAPITAL_FUND_INSUFFICIENT` (HTTP 409). Those five business checks are
    evaluated in exactly that order."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_12_beats_fiscal_priority_33_on_draw_authorize
    """
    facility = fx.create_facility(api)
    project = fx.create_project(
        api, facility["id"], project_name="Shuttle lane widening", budget_cents=2_000_000
    )
    approved = fx.approve_project(api, project["id"])
    assert approved["status"] == "APPROVED", "no obligation has ever been funded here"
    draw = fx.request_draw(api, project["id"], 500_000, TREASURY, "Mobilisation")

    response = api.authorize_disbursement(draw["id"], TREASURY_2)

    error = validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FUNDED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_CAPITAL_FUND_INSUFFICIENT.value, (
        "the project-status check runs before the capital-fund check"
    )


def test_refused_authorisation_leaves_project_and_trust_untouched(api):
    """PRD §3.8: "it requires the project's status to be exactly `FUNDED`, rejecting anything
    else with `ERR_PROJECT_NOT_FUNDED` (HTTP 409)"
    PRD §3.8: "On success the draw moves to `AUTHORIZED`, `authorized_by_user_id` is stamped
    from `X-User-ID`, `trust_capital_fund_cents` falls by `amount_cents` while
    `trust_encumbered_cents` rises by the same amount, the project's `encumbered_cents` rises
    by `amount_cents`, and the draw's `version`, the project's `version` and the facility's
    `version` each advance by 1."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_12_beats_fiscal_priority_33_on_draw_authorize
    """
    facility = fx.create_facility(api)
    project = fx.create_project(
        api, facility["id"], project_name="Shuttle lane widening", budget_cents=2_000_000
    )
    fx.approve_project(api, project["id"])
    draw = fx.request_draw(api, project["id"], 500_000, TREASURY, "Mobilisation")

    api.authorize_disbursement(draw["id"], TREASURY_2)

    stored_draw = validate_success(api.get_disbursement(draw["id"], ADMIN))
    assert stored_draw["status"] == "REQUESTED"
    refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
    assert refreshed["trust_capital_fund_cents"] == 0
    assert refreshed["trust_encumbered_cents"] == 0
    stored_project = validate_success(api.get_project(project["id"], ADMIN))
    assert stored_project["status"] == "APPROVED"
    assert stored_project["encumbered_cents"] == 0


def test_self_authorisation_is_refused_before_the_fiscal_check(api):
    """PRD §2.10: "On capital draws, the `X-User-ID` captured as `requested_by_user_id` when
    the draw was created may neither authorise nor reject that same draw. Both of those
    actions therefore compare the acting `X-User-ID` against `requested_by_user_id` and reject
    a match with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.8: "It requires the draw to be in `REQUESTED`; it requires the acting `X-User-ID`
    to differ from `requested_by_user_id`, rejecting a self-authorisation with
    `ERR_SEGREGATION_OF_DUTIES`; it requires the project's status to be exactly `FUNDED`,
    rejecting anything else with `ERR_PROJECT_NOT_FUNDED` (HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_9_beats_fiscal_priority_33_on_self_authorized_draw
    """
    scenario = fx.setup_two_receipt_trust(
        api,
        with_obligation=True,
        with_project=True,
        project_overrides={"project_name": "CFC office fit-out", "budget_cents": 2_000_000},
    )
    draw = fx.request_draw(
        api, scenario["project"]["id"], 1_500_000, TREASURY, "Fit-out phase 1"
    )

    response = api.authorize_disbursement(draw["id"], TREASURY)

    error = validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_CAPITAL_FUND_INSUFFICIENT.value, (
        "segregation of duties is decided before the capital bucket is measured"
    )


def test_self_authorised_draw_stays_requested(api):
    """PRD §2.10: "On capital draws, the `X-User-ID` captured as `requested_by_user_id` when
    the draw was created may neither authorise nor reject that same draw. Both of those
    actions therefore compare the acting `X-User-ID` against `requested_by_user_id` and reject
    a match with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.8: "On success the draw moves to `AUTHORIZED`, `authorized_by_user_id` is stamped
    from `X-User-ID`, `trust_capital_fund_cents` falls by `amount_cents` while
    `trust_encumbered_cents` rises by the same amount, the project's `encumbered_cents` rises
    by `amount_cents`, and the draw's `version`, the project's `version` and the facility's
    `version` each advance by 1."

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_9_beats_fiscal_priority_33_on_self_authorized_draw
    """
    scenario = fx.setup_two_receipt_trust(
        api,
        with_obligation=True,
        with_project=True,
        project_overrides={"project_name": "CFC office fit-out", "budget_cents": 2_000_000},
    )
    draw = fx.request_draw(
        api, scenario["project"]["id"], 1_500_000, TREASURY, "Fit-out phase 1"
    )

    api.authorize_disbursement(draw["id"], TREASURY)

    stored = validate_success(api.get_disbursement(draw["id"], ADMIN))
    assert stored["status"] == "REQUESTED"
    assert stored["authorized_by_user_id"] is None
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_capital_fund_cents"] == 750_000
    assert facility["trust_encumbered_cents"] == 0


def test_deficient_covenant_blocks_draw_authorisation(api):
    """PRD §3.8: "it requires the facility's `bond_coverage_status` to be `SATISFIED`,
    rejecting a deficient covenant with `ERR_BOND_COVENANT_DEFICIENT` (HTTP 409)"
    PRD §3.7: "Paying a funded obligation carries it `FUNDED → PAID`, its terminal status:
    `trust_debt_service_funded_cents` falls by `amount_due_cents`, `trust_disbursed_cents`
    rises by the same amount, `bond_coverage_status` is recomputed and may fall back to
    `DEFICIENT` because the funded bucket has just emptied, and the obligation's `version` and
    the facility's `version` each advance by 1."

    Design: Difficulty/cross_entity_state_dependency/draw_authorization_blocked_by_facility_covenant_deficiency
    """
    scenario = fx.setup_single_receipt_trust(
        api, project_name="Overflow lot lighting", project_budget_cents=900_000
    )
    validate_success(api.pay_obligation(scenario["obligation"]["id"], TREASURY))
    draw = fx.request_draw(api, scenario["project"]["id"], 300_000, TREASURY, "Pole bases")

    response = api.authorize_disbursement(draw["id"], TREASURY_2)

    validate_error(response, ApiErrorId.ERR_BOND_COVENANT_DEFICIENT.value, 409)
    stored = validate_success(api.get_disbursement(draw["id"], ADMIN))
    assert stored["status"] == "REQUESTED"
    project = validate_success(api.get_project(scenario["project"]["id"], ADMIN))
    assert project["status"] == "FUNDED", (
        "the project is perfectly fundable; only the facility's covenant blocks the draw"
    )


def test_paid_obligation_leaves_the_covenant_deficient(api):
    """PRD §2.8: "It is recomputed whenever any trust bucket moves: it reads `SATISFIED` when
    the sum of `trust_debt_service_reserve_cents` and `trust_debt_service_funded_cents` is
    greater than or equal to `ds_reserve_requirement_cents`, and `DEFICIENT` otherwise."
    PRD §3.7: "Paying a funded obligation carries it `FUNDED → PAID`, its terminal status:
    `trust_debt_service_funded_cents` falls by `amount_due_cents`, `trust_disbursed_cents`
    rises by the same amount, `bond_coverage_status` is recomputed and may fall back to
    `DEFICIENT` because the funded bucket has just emptied, and the obligation's `version` and
    the facility's `version` each advance by 1."

    Design: Difficulty/cross_entity_state_dependency/draw_authorization_blocked_by_facility_covenant_deficiency
    """
    scenario = fx.setup_single_receipt_trust(
        api, project_name="Overflow lot lighting", project_budget_cents=900_000
    )
    validate_success(api.pay_obligation(scenario["obligation"]["id"], TREASURY))

    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))

    assert facility["bond_coverage_status"] == "DEFICIENT"
    assert facility["trust_debt_service_reserve_cents"] == 200_000
    assert facility["trust_debt_service_funded_cents"] == 0
    assert facility["trust_disbursed_cents"] == 800_000
    assert facility["trust_capital_fund_cents"] == 1_000_000
    assert_trust_conservation(facility)


def test_draw_request_blocked_by_open_predecessor(api):
    """PRD §3.8: "Before the draw is created, the predecessor gate is checked at request time
    as well: when the project's `predecessor_project_id` is non-null and that predecessor is
    not in `CLOSED`, the request is rejected with `ERR_PREDECESSOR_NOT_CLOSED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/draw_request_blocked_by_open_predecessor_project
    """
    facility = fx.create_facility(api)
    predecessor = fx.create_project(
        api, facility["id"], project_name="Phase 1 demolition", budget_cents=1_000_000
    )
    successor = fx.create_project(
        api, facility["id"], project_name="Phase 2 deck build", budget_cents=3_000_000,
        predecessor_project_id=predecessor["id"],
    )

    response = api.create_disbursement(
        f.disbursement_payload(
            successor["id"], 100_000, successor["version"], memo="Deck survey"
        ),
        TREASURY,
    )

    validate_error(response, ApiErrorId.ERR_PREDECESSOR_NOT_CLOSED.value, 409)
    stored_pred = validate_success(api.get_project(predecessor["id"], ADMIN))
    assert stored_pred["status"] == "PROPOSED"


def test_blocked_draw_request_creates_no_disbursement(api):
    """PRD §3.8: "Before the draw is created, the predecessor gate is checked at request time
    as well: when the project's `predecessor_project_id` is non-null and that predecessor is
    not in `CLOSED`, the request is rejected with `ERR_PREDECESSOR_NOT_CLOSED` (HTTP 409)."
    PRD §3.8: "A created draw opens in `REQUESTED` status with `requested_by_user_id` stamped
    from the caller's `X-User-ID` and `authorized_by_user_id` null, raises the project's
    `draw_request_count` by 1, and advances the project's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/draw_request_blocked_by_open_predecessor_project
    """
    facility = fx.create_facility(api)
    predecessor = fx.create_project(
        api, facility["id"], project_name="Phase 1 demolition", budget_cents=1_000_000
    )
    successor = fx.create_project(
        api, facility["id"], project_name="Phase 2 deck build", budget_cents=3_000_000,
        predecessor_project_id=predecessor["id"],
    )

    api.create_disbursement(
        f.disbursement_payload(
            successor["id"], 100_000, successor["version"], memo="Deck survey"
        ),
        TREASURY,
    )

    stored = validate_success(api.get_project(successor["id"], ADMIN))
    assert stored["draw_request_count"] == 0, (
        "a refused request must not raise draw_request_count"
    )
    assert stored["status"] == "PROPOSED"
    _rows, meta = validate_paginated(
        api.list_disbursements(ADMIN, params={"project_id": successor["id"]})
    )
    assert meta["total_count"] == 0


def test_authorise_then_void_restores_the_capital_bucket(api):
    """PRD §3.8: "On success the draw moves to `AUTHORIZED`, `authorized_by_user_id` is
    stamped from `X-User-ID`, `trust_capital_fund_cents` falls by `amount_cents` while
    `trust_encumbered_cents` rises by the same amount, the project's `encumbered_cents` rises
    by `amount_cents`, and the draw's `version`, the project's `version` and the facility's
    `version` each advance by 1."
    PRD §3.8: "Voiding it carries `AUTHORIZED → VOIDED`, also terminal, and is the exact
    compensating action for authorisation: `trust_encumbered_cents` falls by `amount_cents`
    and `trust_capital_fund_cents` rises by the same amount, so the capital bucket returns to
    its pre-authorisation value and the trust's conservation identity is untouched; the
    project's `encumbered_cents` falls by `amount_cents`; and the draw's `version`, the
    project's `version` and the facility's `version` each advance by 1."

    Design: Difficulty/compensating_invariant/cfc_trust_cash_conservation_across_authorize_then_void
    """
    scenario = fx.setup_funded_project_with_requested_draw(api)
    draw_id = scenario["disbursement"]["id"]

    validate_success(api.authorize_disbursement(draw_id, TREASURY_2))
    after_authorize = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert after_authorize["trust_capital_fund_cents"] == 700_000
    assert after_authorize["trust_encumbered_cents"] == 300_000

    voided = validate_success(api.void_disbursement(draw_id, TREASURY_2))

    assert voided["status"] == "VOIDED"
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_capital_fund_cents"] == 1_000_000, (
        "the void returns the capital bucket to its pre-authorisation value"
    )
    assert facility["trust_encumbered_cents"] == 0
    assert facility["trust_disbursed_cents"] == 0
    project = validate_success(api.get_project(scenario["project"]["id"], ADMIN))
    assert project["encumbered_cents"] == 0
    assert project["disbursed_cents"] == 0


def test_trust_conservation_identity_holds_across_authorize_and_void(api):
    """PRD §2.8: "The trust obeys a conservation identity that no operation may break. Every
    cent that enters through a remittance receipt lands in exactly one of the debt-service
    reserve, O&M reserve, capital fund or unallocated buckets; every cent that moves between
    buckets leaves one and enters another in the same request; and only a paid obligation or a
    paid draw removes cents from the trust's live buckets into `trust_disbursed_cents`."
    PRD §2.8: "Separately, `trust_lifetime_received_cents` accumulates every cent the trust
    has ever received and never decreases."

    Design: Difficulty/compensating_invariant/cfc_trust_cash_conservation_across_authorize_then_void
    """
    scenario = fx.setup_funded_project_with_requested_draw(api)
    facility_id = scenario["facility"]["id"]
    draw_id = scenario["disbursement"]["id"]

    before = validate_success(api.get_facility(facility_id, ADMIN))
    assert before["trust_lifetime_received_cents"] == 2_000_000
    assert_trust_conservation(before)

    validate_success(api.authorize_disbursement(draw_id, TREASURY_2))
    after_authorize = validate_success(api.get_facility(facility_id, ADMIN))
    assert after_authorize["trust_lifetime_received_cents"] == 2_000_000
    assert_trust_conservation(after_authorize)

    validate_success(api.void_disbursement(draw_id, TREASURY_2))

    after_void = validate_success(api.get_facility(facility_id, ADMIN))
    assert after_void["trust_lifetime_received_cents"] == 2_000_000, (
        "the lifetime counter never decreases"
    )
    assert_trust_conservation(after_void)


def test_cancelling_a_closed_project_is_rejected(api):
    """PRD §3.8: "Closing a funded project carries it `FUNDED → CLOSED`, its terminal status,
    and requires `encumbered_cents` to be exactly 0; a project with money still tied up in
    authorised draws is rejected with `ERR_PROJECT_HAS_ENCUMBRANCE` (HTTP 409)."
    PRD §3.8: "Cancelling is available from `PROPOSED`, from `APPROVED` and from `FUNDED`,
    landing in the terminal `CANCELLED`; cancelling from `APPROVED` or from `FUNDED` also
    requires `encumbered_cents` to be 0 and otherwise raises `ERR_PROJECT_HAS_ENCUMBRANCE`,
    while cancelling from `PROPOSED` has no encumbrance to check."
    PRD §2.6: "State: the target resource sits in a from-state that the requested transition
    declares, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/cancel_a_closed_capital_project_is_rejected_terminal_lockdown
    """
    scenario = fx.setup_single_receipt_trust(api)
    project_id = scenario["project"]["id"]
    closed = validate_success(api.close_project(project_id, ADMIN))
    assert closed["status"] == "CLOSED"

    response = api.cancel_project(project_id, ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    stored = validate_success(api.get_project(project_id, ADMIN))
    assert stored["status"] == "CLOSED"
    obligation = validate_success(api.get_obligation(scenario["obligation"]["id"], ADMIN))
    assert obligation["status"] == "FUNDED"
    assert obligation["auto_funded"] is True
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["funded_obligation_count"] == 1


def test_closing_a_predecessor_releases_its_successor(api):
    """PRD §3.8: "When any of those three conditions fails, `funding_hold` stays true and the
    project waits in `APPROVED`."
    PRD §3.8: "Closing has a cascade of its own: every project whose `predecessor_project_id`
    names the closing project, and that sits in `APPROVED` with `funding_hold` true, is
    released to `FUNDED` provided the facility's `funded_obligation_count` is at least 1 and
    its `bond_coverage_status` is `SATISFIED`, processed in ascending `created_at` order."

    Design: Corner/state_machines/closing_a_predecessor_project_releases_its_successor_to_funded
    """
    scenario = fx.setup_single_receipt_trust(
        api, project_name="Phase 1 demolition", project_budget_cents=900_000
    )
    predecessor_id = scenario["project"]["id"]
    successor = fx.create_project(
        api, scenario["facility"]["id"], project_name="Phase 2 deck build",
        budget_cents=500_000, predecessor_project_id=predecessor_id,
    )
    successor = fx.approve_project(api, successor["id"])
    assert successor["status"] == "APPROVED", "the open predecessor keeps the gate shut"
    assert successor["funding_hold"] is True

    validate_success(api.close_project(predecessor_id, ADMIN))

    stored_pred = validate_success(api.get_project(predecessor_id, ADMIN))
    assert stored_pred["status"] == "CLOSED"
    stored_succ = validate_success(api.get_project(successor["id"], ADMIN))
    assert stored_succ["status"] == "FUNDED"
    assert stored_succ["funding_hold"] is False
    assert stored_succ["predecessor_project_id"] == predecessor_id


def test_draw_beyond_the_project_budget_is_rejected(api):
    """PRD §3.8: "it requires the project's `disbursed_cents` plus `encumbered_cents` plus
    this draw's `amount_cents` to be no greater than `budget_cents`, rejecting an overrun with
    `ERR_PROJECT_BUDGET_EXCEEDED` (HTTP 409)"

    Design: Corner/validations/draw_exceeding_the_project_budget_is_rejected
    """
    scenario = fx.setup_single_receipt_trust(
        api, project_name="Wayfinding signage", project_budget_cents=200_000
    )
    draw = fx.request_draw(api, scenario["project"]["id"], 300_000, TREASURY, "Signs")

    response = api.authorize_disbursement(draw["id"], TREASURY_2)

    validate_error(response, ApiErrorId.ERR_PROJECT_BUDGET_EXCEEDED.value, 409)
    stored = validate_success(api.get_disbursement(draw["id"], ADMIN))
    assert stored["status"] == "REQUESTED"
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_capital_fund_cents"] == 1_000_000, (
        "the capital bucket could have covered the draw; the budget check fired first"
    )
    assert facility["trust_encumbered_cents"] == 0
    project = validate_success(api.get_project(scenario["project"]["id"], ADMIN))
    assert project["encumbered_cents"] == 0


def test_closing_a_project_with_encumbrance_is_rejected(api):
    """PRD §3.8: "Closing a funded project carries it `FUNDED → CLOSED`, its terminal status,
    and requires `encumbered_cents` to be exactly 0; a project with money still tied up in
    authorised draws is rejected with `ERR_PROJECT_HAS_ENCUMBRANCE` (HTTP 409)."

    Design: Corner/errors/closing_a_project_with_an_authorized_draw_is_rejected
    """
    scenario = fx.setup_funded_project_with_requested_draw(api)
    validate_success(api.authorize_disbursement(scenario["disbursement"]["id"], TREASURY_2))

    response = api.close_project(scenario["project"]["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_PROJECT_HAS_ENCUMBRANCE.value, 409)
    project = validate_success(api.get_project(scenario["project"]["id"], ADMIN))
    assert project["status"] == "FUNDED"
    assert project["encumbered_cents"] == 300_000
    facility = validate_success(api.get_facility(scenario["facility"]["id"], ADMIN))
    assert facility["trust_encumbered_cents"] == 300_000
    assert facility["trust_capital_fund_cents"] == 700_000


def test_project_with_unknown_predecessor_is_rejected(api):
    """PRD §2.5: "`predecessor_project_id`, when supplied, is a reference to another capital
    project and yields `ERR_PROJECT_NOT_FOUND` when it resolves to nothing."

    Design: Corner/entities/capital_project_with_unknown_predecessor_returns_project_not_found
    """
    facility = fx.create_facility(api)

    response = api.create_project(
        f.project_payload(
            facility["id"], project_name="Phase 2 deck build", budget_cents=3_000_000,
            predecessor_project_id=UNKNOWN_UUID,
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)
    _rows, meta = validate_paginated(
        api.list_projects(ADMIN, params={"facility_id": facility["id"]})
    )
    assert meta["total_count"] == 0


def test_facility_admin_cannot_authorize_a_draw(api):
    """PRD §2.1: "A caller whose role is recognised but who is not among the roles authorised
    for the endpoint being called receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "Authorize a draw: REQUESTED -> AUTHORIZED; the requester may not authorize their
    own draw | FinanceOfficer"

    Design: Corner/rbac/facility_admin_cannot_authorize_a_capital_draw
    """
    facility = fx.create_facility(api)
    project = fx.create_project(
        api, facility["id"], project_name="Bus wash bay", budget_cents=500_000
    )
    draw = validate_success(
        api.create_disbursement(
            f.disbursement_payload(project["id"], 100_000, project["version"], memo="Design fee"),
            ADMIN,
        ),
        201,
    )

    response = api.authorize_disbursement(draw["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    stored = validate_success(api.get_disbursement(draw["id"], ADMIN))
    assert stored["status"] == "REQUESTED"
    stored_project = validate_success(api.get_project(project["id"], ADMIN))
    assert stored_project["draw_request_count"] == 1


def test_stale_project_version_blocks_a_second_draw(api):
    """PRD §2.9: "A request creating a capital disbursement must carry
    `expected_project_version`, holding the `version` of the `CapitalProject` named by
    `project_id` as the client last observed it. A mismatch against the project's current
    `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), so a draw is never requested
    against a budget, encumbrance or funding state the client has not observed."

    Design: Corner/cross_cutting_complexity_layers/stale_project_version_on_capital_draw_create_returns_conflict
    """
    facility = fx.create_facility(api)
    project = fx.create_project(
        api, facility["id"], project_name="Bus wash bay", budget_cents=500_000
    )
    stale_version = project["version"]
    validate_success(
        api.create_disbursement(
            f.disbursement_payload(project["id"], 100_000, stale_version, memo="Design fee"),
            TREASURY,
        ),
        201,
    )

    response = api.create_disbursement(
        f.disbursement_payload(project["id"], 50_000, stale_version, memo="Permit fee"),
        TREASURY,
    )

    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)
    stored = validate_success(api.get_project(project["id"], ADMIN))
    assert stored["draw_request_count"] == 1
    _rows, meta = validate_paginated(
        api.list_disbursements(ADMIN, params={"project_id": project["id"]})
    )
    assert meta["total_count"] == 1
