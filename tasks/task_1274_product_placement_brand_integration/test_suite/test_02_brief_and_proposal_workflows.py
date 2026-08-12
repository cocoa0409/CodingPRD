"""Brief lifecycle and proposal workflow state machines (PRD §3.1, §3.4)."""
from test_helpers import (
    ApiErrorId,
    create_brand,
    create_brief_payload,
    create_episode,
    create_open_brief,
    create_opportunity,
    create_proposal,
    create_series,
    get_brief,
    get_opportunity,
    get_success_data,
    make_brand_rep_headers,
    proposal_decision_payload,
    validate_error,
    validate_success,
)


def test_brief_initial_state_draft(api, admin_headers):
    """PRD §3.1: "A new brief starts in `DRAFT`, and its computed
    `remaining_budget_cents` is initialized to the full `budget_cents`."

    Design: Corner/state_machines/brief_initial_state_draft
    """
    brand = create_brand()
    rep = make_brand_rep_headers(brand["id"])
    resp = api.create_brief(brand["id"], create_brief_payload(budget_cents=1000), rep)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT", f"new brief must be DRAFT, got {data['status']}"


def test_submit_open_brief_returns_invalid_state(api, admin_headers):
    """PRD §3.1: "Submitting the brief moves it from `DRAFT` to `OPEN` and is
    allowed only while the brief is `DRAFT`".
    PRD §2.8 stage 6: "the target entity is in a valid from-state for the
    requested transition (`ERR_INVALID_STATE`, HTTP 409)".

    Design: Corner/state_machines/submit_open_brief_returns_invalid_state
    """
    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=1000)
    version_before = brief["version"]
    rep = make_brand_rep_headers(brand["id"])
    resp = api.submit_brief(brief["id"], rep)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_brief(brief["id"])
    assert after["version"] == version_before, (
        f"version must not change on a rejected transition: {version_before} -> {after['version']}"
    )
    assert after["status"] == "OPEN"


def test_close_brief_with_inflight_proposal_rejected(api, manager_headers):
    """PRD §3.1: "Closing a brief moves it from `OPEN` to `CLOSED` — again only
    for the owning representative — and only when no proposal answering the
    brief is still in flight: there must be no proposal of the brief in
    `DRAFT`, `PRODUCTION_REVIEW`, `NETWORK_REVIEW`, `REVISION_REQUESTED`, or
    `APPROVED`."

    Design: Corner/state_machines/close_brief_with_inflight_proposal_rejected
    """
    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=1_000_000)
    series = create_series()
    episode = create_episode(series["id"])
    opportunity = create_opportunity(episode["id"])
    create_proposal(
        brief["id"],
        opportunity["id"],
        proposed_fee_cents=60_000,
        guaranteed_seconds=10,
        rate_cents_per_second=2000,
    )
    rep = make_brand_rep_headers(brand["id"])
    resp = api.close_brief(brief["id"], rep)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_brief(brief["id"])
    assert after["status"] == "OPEN", f"brief must stay OPEN, got {after['status']}"


def test_network_decision_on_rejected_proposal_rejected(api, manager_headers):
    """PRD §2.8 stage 6: "when the entity sits in a terminal state — a `CLOSED`
    brief, a `REJECTED`, `CONTRACTED`, or `WITHDRAWN` proposal, a `TERMINATED`
    contract, a `RETURNED` or `CANCELLED` shipment, a `DENIED` or `RELEASED`
    clearance, a `WAIVED` credit, an `ACKNOWLEDGED` filing, or a `CONSUMED` or
    `WITHDRAWN` opportunity — the error is `ERR_ALREADY_TERMINAL` (HTTP 409)
    instead."
    PRD §3.4: "a rejection terminates it at `REJECTED`".

    Design: Corner/state_machines/network_decision_on_rejected_proposal_rejected
    """
    from test_helpers import TEST_USERS

    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=1_000_000)
    series = create_series()
    episode = create_episode(series["id"])
    opportunity = create_opportunity(episode["id"])
    proposal = create_proposal(
        brief["id"],
        opportunity["id"],
        proposed_fee_cents=60_000,
        guaranteed_seconds=10,
        rate_cents_per_second=2000,
    )
    proposal = get_success_data(api.submit_proposal(proposal["id"], manager_headers))
    proposal = get_success_data(
        api.production_decision(
            proposal["id"],
            proposal_decision_payload("REJECT"),
            TEST_USERS["production_alt_headers"],
        )
    )
    assert proposal["status"] == "REJECTED", f"precondition: {proposal['status']}"
    resp = api.network_decision(
        proposal["id"],
        proposal_decision_payload("APPROVE"),
        TEST_USERS["network_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_proposal_reject_frees_opportunity(api, manager_headers):
    """PRD §3.4: "advancing it to `APPROVED` on approval, back to
    `REVISION_REQUESTED` on a revision request, or to `REJECTED` on rejection
    — again with the opportunity returning from `PITCHED` to `IDENTIFIED` and
    the budget hold released."
    PRD §3.1: "A `TERMINATED` contract releases its hold, as do `REJECTED` and
    `WITHDRAWN` proposals."

    Design: Corner/state_machines/proposal_reject_frees_opportunity
    """
    from test_helpers import TEST_USERS

    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=1_000_000)
    series = create_series()
    episode = create_episode(series["id"])
    opportunity = create_opportunity(episode["id"])
    proposal = create_proposal(
        brief["id"],
        opportunity["id"],
        proposed_fee_cents=60_000,
        guaranteed_seconds=10,
        rate_cents_per_second=2000,
    )
    proposal = get_success_data(api.submit_proposal(proposal["id"], manager_headers))
    proposal = get_success_data(
        api.production_decision(
            proposal["id"],
            proposal_decision_payload("APPROVE"),
            TEST_USERS["production_alt_headers"],
        )
    )
    proposal = get_success_data(
        api.network_decision(
            proposal["id"],
            proposal_decision_payload("REJECT"),
            TEST_USERS["network_headers"],
        )
    )
    assert proposal["status"] == "REJECTED", f"got {proposal['status']}"
    opp_after = get_opportunity(opportunity["id"])
    assert opp_after["status"] == "IDENTIFIED", (
        f"opportunity must be freed back to IDENTIFIED, got {opp_after['status']}"
    )
    brief_after = get_brief(brief["id"])
    assert brief_after["remaining_budget_cents"] == 1_000_000, (
        f"rejected proposal must release its hold; got {brief_after['remaining_budget_cents']}"
    )


def test_proposal_on_withdrawn_opportunity_rejected(api, manager_headers):
    """PRD §3.4: "the referenced opportunity must be `IDENTIFIED`
    (`ERR_OPPORTUNITY_UNAVAILABLE`, HTTP 409)".
    PRD §3.2: "The production representative may withdraw an unpitched
    opportunity, moving it from `IDENTIFIED` to `WITHDRAWN`".

    Design: Corner/state_machines/proposal_on_withdrawn_opportunity_rejected
    """
    from test_helpers import TEST_USERS

    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=1_000_000)
    series = create_series()
    episode = create_episode(series["id"])
    opportunity = create_opportunity(episode["id"])
    opportunity = get_success_data(
        api.withdraw_opportunity(opportunity["id"], TEST_USERS["production_headers"])
    )
    assert opportunity["status"] == "WITHDRAWN", f"precondition: {opportunity['status']}"
    resp = api.create_proposal(
        {
            "brief_id": brief["id"],
            "opportunity_id": opportunity["id"],
            "proposed_fee_cents": 60_000,
            "guaranteed_seconds": 10,
            "guaranteed_verbal_mentions": 0,
            "cross_promo_owed_count": 0,
            "rate_cents_per_second": 2000,
        },
        manager_headers,
    )
    validate_error(resp, ApiErrorId.ERR_OPPORTUNITY_UNAVAILABLE)
