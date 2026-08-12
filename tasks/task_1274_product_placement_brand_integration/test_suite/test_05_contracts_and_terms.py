"""Contract formation, terms amendment, activation gating, and OCC (PRD §2.7,
§3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    amend_terms_payload,
    create_brand,
    create_episode,
    create_open_brief,
    create_opportunity,
    create_proposal,
    create_revision_payload,
    create_series,
    get_brief,
    get_contract,
    get_success_data,
    proposal_decision_payload,
    setup_approved_proposal,
    setup_pending_contract,
    setup_settled_contract,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
PROD_DECIDER = TEST_USERS["production_alt_headers"]
NETWORK = TEST_USERS["network_headers"]


def test_activation_requires_episode_locked(api):
    """PRD §3.5: "Activation is the signature step and is guarded by two
    prerequisites, evaluated in this order: the contract's episode must be
    `LOCKED` (`ERR_EPISODE_NOT_LOCKED`, HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/activation_requires_episode_locked
    """
    # Build the approved chain WITHOUT locking the episode.
    ctx = setup_approved_proposal()
    contract = get_success_data(
        api.create_contract_from_proposal(ctx["proposal"]["id"], MANAGER)
    )
    resp = api.activate_contract(contract["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_LOCKED)

    from test_helpers import PROD_CREATOR

    get_success_data(api.lock_episode(ctx["episode"]["id"], PROD_CREATOR))
    contract = get_success_data(api.activate_contract(contract["id"], MANAGER))
    assert contract["status"] == "ACTIVE", (
        f"after locking the same transition is legal; got {contract['status']}"
    )


def test_activation_blocked_then_succeeds_after_lock(api):
    """PRD §3.5: "Activation moves the contract from `PENDING_SIGNATURE` to
    `ACTIVE`, sets its `outstanding_balance_cents` to the full
    `base_fee_cents`".

    Design: Difficulty/cross_entity_state_dependency/activation_requires_episode_locked
    """
    ctx = setup_approved_proposal()
    contract = get_success_data(
        api.create_contract_from_proposal(ctx["proposal"]["id"], MANAGER)
    )
    resp = api.activate_contract(contract["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_LOCKED)

    from test_helpers import PROD_CREATOR

    get_success_data(api.lock_episode(ctx["episode"]["id"], PROD_CREATOR))
    contract = get_success_data(api.activate_contract(contract["id"], MANAGER))
    assert contract["status"] == "ACTIVE"
    assert contract["outstanding_balance_cents"] == contract["base_fee_cents"], (
        "activation sets outstanding_balance_cents to the full base_fee_cents"
    )


def test_activate_without_clearance_rejected(api):
    """PRD §3.5: "a `GRANTED` clearance must exist for this episode covering
    the brand behind the contract's proposal's brief — matched through the
    copied category (`ERR_CLEARANCE_REQUIRED`, HTTP 409)".

    Design: Corner/validations/activate_without_clearance_rejected
    """
    ctx = setup_approved_proposal(with_clearance=False)
    from test_helpers import PROD_CREATOR

    get_success_data(api.lock_episode(ctx["episode"]["id"], PROD_CREATOR))
    contract = get_success_data(
        api.create_contract_from_proposal(ctx["proposal"]["id"], MANAGER)
    )
    resp = api.activate_contract(contract["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_REQUIRED)


def test_proposal_revision_stale_version_rejected(api):
    """PRD §2.7: "Submitting revised terms for a proposal requires
    `expected_proposal_version`, matched against the `IntegrationProposal`'s
    current `version`." PRD §2.7: "if the presented value does not match the
    entity's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/proposal_revision_stale_version_rejected
    """
    # Build a proposal in REVISION_REQUESTED.
    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=1_000_000)
    series = create_series()
    episode = create_episode(series["id"])
    opportunity = create_opportunity(episode["id"])
    proposal = create_proposal(brief["id"], opportunity["id"])
    proposal = get_success_data(api.submit_proposal(proposal["id"], MANAGER))
    proposal = get_success_data(
        api.production_decision(
            proposal["id"], proposal_decision_payload("REQUEST_REVISION"), PROD_DECIDER
        )
    )
    current_version = proposal["version"]

    resp = api.submit_revision(
        proposal["id"],
        create_revision_payload(current_version - 1),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    ok = get_success_data(
        api.submit_revision(
            proposal["id"], create_revision_payload(current_version), MANAGER
        )
    )
    assert ok["status"] == "PRODUCTION_REVIEW", (
        f"revision with the current version must succeed; got {ok['status']}"
    )


def test_contract_terms_stale_version_rejected(api):
    """PRD §2.7: "Amending the base fee of a contract requires
    `expected_contract_version`, matched against the `IntegrationContract`'s
    current `version`." PRD §2.7: "if the presented value does not match the
    entity's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/contract_terms_stale_version_rejected
    """
    ctx = setup_pending_contract(lock_episode=False)
    contract = ctx["contract"]
    current_version = contract["version"]

    resp = api.amend_contract_terms(
        contract["id"],
        amend_terms_payload(800_000, current_version - 1),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    after = get_contract(contract["id"])
    assert after["base_fee_cents"] == contract["base_fee_cents"], (
        f"stale amendment must not change base_fee_cents; got {after['base_fee_cents']}"
    )


def test_version_increments_on_each_mutation(api):
    """PRD §2.4: "The `version` is an integer that the server increments by
    exactly 1 on every mutation of the resource, including every state
    transition and every field update".

    Design: Corner/cross_cutting/version_increments_on_each_mutation
    """
    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=1_000_000)
    series = create_series()
    episode = create_episode(series["id"])
    opportunity = create_opportunity(episode["id"])

    proposal = get_success_data(
        api.create_proposal(
            {
                "brief_id": brief["id"],
                "opportunity_id": opportunity["id"],
                "proposed_fee_cents": 60_000,
                "guaranteed_seconds": 10,
                "guaranteed_verbal_mentions": 0,
                "cross_promo_owed_count": 0,
                "rate_cents_per_second": 2000,
            },
            MANAGER,
        )
    )
    assert proposal["version"] == 1, f"create -> v1, got {proposal['version']}"
    proposal = get_success_data(api.submit_proposal(proposal["id"], MANAGER))
    assert proposal["version"] == 2, f"submit -> v2, got {proposal['version']}"
    proposal = get_success_data(
        api.production_decision(
            proposal["id"], proposal_decision_payload("APPROVE"), PROD_DECIDER
        )
    )
    assert proposal["version"] == 3, f"production decision -> v3, got {proposal['version']}"


def test_proposal_revision_cycle_returns_to_production_review(api):
    """PRD §3.4: "The new terms replace the old outright, `terms_revision`
    increments by 1, the proposal moves back to `PRODUCTION_REVIEW`". PRD
    §3.4: "The `PRODUCTION_REVIEW` → `REVISION_REQUESTED` → `PRODUCTION_REVIEW`
    cycle is the negotiation round loop and may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_returns_to_production_review
    """
    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=1_000_000)
    series = create_series()
    episode = create_episode(series["id"])
    opportunity = create_opportunity(episode["id"])
    proposal = create_proposal(brief["id"], opportunity["id"])
    proposal = get_success_data(api.submit_proposal(proposal["id"], MANAGER))
    proposal = get_success_data(
        api.production_decision(
            proposal["id"],
            proposal_decision_payload("REQUEST_REVISION", note="fee too high"),
            PROD_DECIDER,
        )
    )
    version_at_revision = proposal["version"]

    revised = get_success_data(
        api.submit_revision(
            proposal["id"],
            create_revision_payload(
                version_at_revision,
                proposed_fee_cents=900_000,
            ),
            MANAGER,
        )
    )
    assert revised["status"] == "PRODUCTION_REVIEW", (
        f"cycle must return to PRODUCTION_REVIEW, got {revised['status']}"
    )
    assert revised["terms_revision"] == 2, (
        f"terms_revision must increment 1 -> 2, got {revised['terms_revision']}"
    )
    assert revised["version"] == version_at_revision + 1, (
        f"version increments on the revision: {revised['version']} != {version_at_revision + 1}"
    )
    assert revised["proposed_fee_cents"] == 900_000, (
        f"new terms replace the old outright; got {revised['proposed_fee_cents']}"
    )


def test_proposal_revision_cycle_replaces_terms_and_recomputes_budget(api):
    """PRD §3.4: "The new terms replace the old outright, `terms_revision`
    increments by 1, the proposal moves back to `PRODUCTION_REVIEW`, and the
    brief's remaining budget is recomputed against the new fee."

    Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_returns_to_production_review
    """
    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=1_000_000)
    series = create_series()
    episode = create_episode(series["id"])
    opportunity = create_opportunity(episode["id"])
    proposal = create_proposal(brief["id"], opportunity["id"])  # fee 1_000_000
    proposal = get_success_data(api.submit_proposal(proposal["id"], MANAGER))
    proposal = get_success_data(
        api.production_decision(
            proposal["id"], proposal_decision_payload("REQUEST_REVISION"), PROD_DECIDER
        )
    )
    revised = get_success_data(
        api.submit_revision(
            proposal["id"],
            create_revision_payload(proposal["version"], proposed_fee_cents=900_000),
            MANAGER,
        )
    )
    assert revised["terms_revision"] == 2
    brief_after = get_brief(brief["id"])
    assert brief_after["remaining_budget_cents"] == 100_000, (
        f"remaining budget recomputed against the new fee: 1000000 - 900000 = 100000, "
        f"got {brief_after['remaining_budget_cents']}"
    )


def test_contract_terms_amend_recomputes_provisional(api):
    """PRD §3.5: "A successful amendment updates `base_fee_cents`, recomputes
    `provisional_value_cents`, recomputes the brief's remaining budget, and
    increments the contract's `version` by 1."
    PRD §3.5: "the projected shortfall is the larger of zero and the contract's
    `guaranteed_seconds` minus the opportunity's `estimated_exposure_seconds`;
    that shortfall is multiplied by the contract's `rate_cents_per_second` and
    by one and a half, the product is rounded half-up to whole cents, and the
    result is subtracted from `base_fee_cents`."

    Design: Corner/endpoints/contract_terms_amend_recomputes_provisional
    """
    ctx = setup_pending_contract(
        lock_episode=False,
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        estimated_exposure_seconds=25,
        rate_cents_per_second=2000,
    )
    contract = ctx["contract"]
    resp = api.amend_contract_terms(
        contract["id"],
        amend_terms_payload(800_000, contract["version"]),
        MANAGER,
    )
    amended = validate_success(resp)
    assert amended["base_fee_cents"] == 800_000, f"got {amended['base_fee_cents']}"
    # provisional = 800000 - round_half_up((30 - 25) * 2000 * 1.5) = 800000 - 15000
    assert amended["provisional_value_cents"] == 785_000, (
        f"provisional must be recomputed to 785000, got {amended['provisional_value_cents']}"
    )
    assert amended["version"] == contract["version"] + 1, (
        f"version increments on amendment: {amended['version']} != {contract['version'] + 1}"
    )
    brief_after = get_brief(ctx["brief"]["id"])
    assert brief_after["remaining_budget_cents"] == 200_000, (
        f"hold carried at the amended fee: 1000000 - 800000 = 200000, got {brief_after['remaining_budget_cents']}"
    )


def test_terminal_state_beats_budget_on_terms_amend(api):
    """PRD §2.8: "Every request is validated against an ordered pipeline; the
    first stage that fails determines the response, so an earlier failure
    always masks any later failure that would also have applied." PRD §2.8
    stage 6: "State validity: the target entity is in a valid from-state for
    the requested transition (`ERR_INVALID_STATE`, HTTP 409)" — the amendment
    is legal only "While the contract remains `PENDING_SIGNATURE`" (PRD §3.5),
    so a settled contract fails the stage-6 state check before the stage-11
    fiscal ceiling is ever reached.

    Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_budget_on_terms_amend
    """
    ctx = setup_settled_contract(
        budget_cents=1_000_000,
        proposed_fee_cents=1_000_000,
        guaranteed_seconds=30,
        guaranteed_verbal_mentions=2,
        estimated_exposure_seconds=30,
        measured_segments_seconds=[30],
        measured_verbal_mentions=2,
    )
    contract = ctx["contract"]
    assert contract["status"] == "SETTLED", f"precondition: {contract['status']}"
    resp = api.amend_contract_terms(
        contract["id"],
        amend_terms_payload(5_000_000, contract["version"]),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_contract(contract["id"])
    assert after["base_fee_cents"] == 1_000_000, (
        f"base_fee_cents unchanged; got {after['base_fee_cents']}"
    )


def test_terminal_state_beats_budget_on_terms_amend_terminated(api):
    """PRD §2.8: "the first stage that fails determines the response, so an
    earlier failure always masks any later failure that would also have
    applied." PRD §2.8 stage 6: "when the entity sits in a terminal state — a
    `CLOSED` brief, a `REJECTED`, `CONTRACTED`, or `WITHDRAWN` proposal, a
    `TERMINATED` contract, a `RETURNED` or `CANCELLED` shipment, a `DENIED` or
    `RELEASED` clearance, a `WAIVED` credit, an `ACKNOWLEDGED` filing, or a
    `CONSUMED` or `WITHDRAWN` opportunity — the error is `ERR_ALREADY_TERMINAL`
    (HTTP 409) instead" — and stage 6 precedes the fiscal stage 11
    (`ERR_BUDGET_EXCEEDED`).

    Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_budget_on_terms_amend
    """
    ctx = setup_pending_contract(lock_episode=False)
    contract = ctx["contract"]
    get_success_data(api.terminate_contract(contract["id"], MANAGER))
    terminated = get_contract(contract["id"])
    assert terminated["status"] == "TERMINATED", f"precondition: {terminated['status']}"

    resp = api.amend_contract_terms(
        contract["id"],
        amend_terms_payload(5_000_000, terminated["version"]),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
    after = get_contract(contract["id"])
    assert after["base_fee_cents"] == 1_000_000, (
        f"base_fee_cents unchanged; got {after['base_fee_cents']}"
    )
