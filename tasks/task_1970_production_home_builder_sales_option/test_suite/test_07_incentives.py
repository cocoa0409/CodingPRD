"""Incentives and the community budget ledger: auto-approval boundary, the
provisional-keyed cap, decide RBAC, terminal states, and ledger conservation
across approval and revocation (PRD §2.8, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    CANONICAL_INCENTIVE_CAP_CENTS,
    DEFAULT_CLOCK_ISO,
    TEST_USERS,
    api_client,
    assert_budget_conservation,
    assert_instant_equals,
    cancel_agreement,
    create_agreement_payload,
    create_incentive,
    create_lot,
    decide_incentive,
    get_community,
    get_incentive,
    release_lot,
    reserve_lot,
    setup_signed_agreement,
    sign_agreement,
    validate_error,
    validate_success,
)

AGENT = TEST_USERS["sales_agent_headers"]
DIRECTOR = TEST_USERS["sales_director_headers"]


def _get_agreement(agreement_id):
    return validate_success(api_client.get_agreement(agreement_id, AGENT), 200)


def test_auto_approve_at_exact_limit_and_one_cent_above():
    """PRD §3.7: "When the amount is at or below the $3,000 auto-approval limit
    — exactly the limit still qualifies — and the community's remaining budget
    covers the amount and the agreement's cap check passes, the new request
    lands directly in `APPROVED` with `auto_approved` set to true and
    `decided_at` stamped; the community budget is debited, the agreement's
    `incentives_total_cents` grows by the amount, and the agreement's `version`
    increments."
    PRD §3.7: "Any request that fails one of those conditions is instead
    created in `SUBMITTED` with `auto_approved` false and `decided_at` null,
    awaiting a human decision."

    Design: Difficulty/boundary_precision_check/incentive_auto_approve_at_exact_limit
    """
    bundle = setup_signed_agreement()
    agreement_id = bundle["agreement"]["id"]

    at_limit = create_incentive(agreement_id, 300_000)
    assert at_limit["status"] == "APPROVED", "amount == limit auto-approves"
    assert at_limit["auto_approved"] is True

    over_limit = create_incentive(
        agreement_id, 300_001, incentive_type="CLOSING_COST_CREDIT"
    )
    assert over_limit["status"] == "SUBMITTED", "one cent over the limit waits"
    assert over_limit["auto_approved"] is False

    community = get_community(bundle["community"]["id"])
    assert community["incentive_budget_remaining_cents"] == 700_000, (
        "only the auto-approved 300,000 was debited"
    )


def test_auto_approved_request_stamps_decision_and_updates_totals():
    """PRD §3.7: "When the amount is at or below the $3,000 auto-approval limit
    — exactly the limit still qualifies — and the community's remaining budget
    covers the amount and the agreement's cap check passes, the new request
    lands directly in `APPROVED` with `auto_approved` set to true and
    `decided_at` stamped; the community budget is debited, the agreement's
    `incentives_total_cents` grows by the amount, and the agreement's `version`
    increments."
    PRD §3.7: "Any request that fails one of those conditions is instead
    created in `SUBMITTED` with `auto_approved` false and `decided_at` null,
    awaiting a human decision."

    Design: Difficulty/boundary_precision_check/incentive_auto_approve_at_exact_limit
    """
    bundle = setup_signed_agreement()
    agreement_id = bundle["agreement"]["id"]

    at_limit = create_incentive(agreement_id, 300_000)
    assert_instant_equals(
        at_limit["decided_at"], DEFAULT_CLOCK_ISO,
        "auto-approval stamps decided_at at creation",
    )
    over_limit = create_incentive(
        agreement_id, 300_001, incentive_type="CLOSING_COST_CREDIT"
    )
    assert over_limit["decided_at"] is None

    agreement = _get_agreement(agreement_id)
    assert agreement["incentives_total_cents"] == 300_000, (
        "only the APPROVED request counts toward the agreement total"
    )


def test_incentive_cap_computed_from_provisional_not_final():
    """PRD §3.7: "Approval re-runs both money guards in order: first the
    community budget must cover the amount (`incentive_budget_remaining_cents`
    minus `amount_cents` must not go negative, else
    `ERR_INCENTIVE_BUDGET_EXCEEDED`), then the agreement-level cap — the
    agreement's cumulative `incentives_total_cents` plus this amount must not
    exceed six percent of its `provisional_total_cents`, that ceiling rounded
    half up to whole cents (else `ERR_INCENTIVE_CAP_EXCEEDED`)."
    PRD §3.7: "The cap base is always the immutable provisional total fixed at
    signing; it is never re-derived from `final_total_cents`, which would make
    the rule circular."

    Design: Difficulty/combinatorial_formula/incentive_cap_keyed_on_provisional_not_final
    """
    from test_helpers import confirm_selection, create_selection

    bundle = setup_signed_agreement(budget=5_000_000, with_quartz=True)
    agreement_id = bundle["agreement"]["id"]
    buyer_id = bundle["buyer"]["id"]
    # A confirmed 800,000 option makes a final-price-derived cap (6% of
    # 46,041,000 = 2,762,460) differ from the pinned provisional-derived cap
    # (6% of 45,241,000 = 2,714,460).
    selection = create_selection(agreement_id, bundle["quartz"]["id"], buyer_id)
    confirm_selection(selection["id"], buyer_id)
    assert _get_agreement(agreement_id)["provisional_total_cents"] == 45_241_000

    request = create_incentive(agreement_id, 2_720_000)
    assert request["status"] == "SUBMITTED", (
        "over the auto-approval limit, but inside the intake budget"
    )

    resp = api_client.decide_incentive_request(
        request["id"], {"action": "APPROVE"}, DIRECTOR
    )
    # 2,720,000 > 2,714,460 = 6% of provisional 45,241,000 -> cap error, even
    # though it would fit under a final-price-derived cap.
    validate_error(resp, ApiErrorId.ERR_INCENTIVE_CAP_EXCEEDED, 402)

    still = get_incentive(request["id"])
    assert still["status"] == "SUBMITTED", "a rejected decision changes nothing"
    community = get_community(bundle["community"]["id"])
    assert community["incentive_budget_remaining_cents"] == 5_000_000


def test_incentive_approval_at_exact_cap_ceiling_succeeds():
    """PRD §3.7: "Approval re-runs both money guards in order: first the
    community budget must cover the amount (`incentive_budget_remaining_cents`
    minus `amount_cents` must not go negative, else
    `ERR_INCENTIVE_BUDGET_EXCEEDED`), then the agreement-level cap — the
    agreement's cumulative `incentives_total_cents` plus this amount must not
    exceed six percent of its `provisional_total_cents`, that ceiling rounded
    half up to whole cents (else `ERR_INCENTIVE_CAP_EXCEEDED`)."

    Design: Difficulty/combinatorial_formula/incentive_cap_keyed_on_provisional_not_final
    """
    bundle = setup_signed_agreement(budget=5_000_000)
    agreement_id = bundle["agreement"]["id"]

    request = create_incentive(agreement_id, CANONICAL_INCENTIVE_CAP_CENTS)
    assert request["status"] == "SUBMITTED", "2,714,460 is over the auto limit"

    decided = decide_incentive(request["id"], "APPROVE")
    assert decided["status"] == "APPROVED", (
        "cumulative 2,714,460 does not exceed the 2,714,460 ceiling"
    )
    assert decided["auto_approved"] is False

    agreement = _get_agreement(agreement_id)
    assert agreement["incentives_total_cents"] == CANONICAL_INCENTIVE_CAP_CENTS
    community = get_community(bundle["community"]["id"])
    assert community["incentive_budget_remaining_cents"] == (
        5_000_000 - CANONICAL_INCENTIVE_CAP_CENTS
    )


def test_budget_debit_on_approval_and_restore_on_cancel():
    """PRD §2.8: "The ledger is conserved: at every instant, the remaining
    budget plus the sum of approved amounts across the community equals the
    original total."
    PRD §2.8: "Approval debits the ledger at the moment of approval; revocation
    — which happens only as part of agreement cancellation — restores the exact
    approved amount back to the remaining balance."

    Design: Difficulty/compensating_invariant/incentive_budget_conserved_across_approve_and_revoke
    """
    bundle = setup_signed_agreement()
    agreement_id = bundle["agreement"]["id"]

    request = create_incentive(agreement_id, 250_000)
    assert request["status"] == "APPROVED"
    community = get_community(bundle["community"]["id"])
    assert community["incentive_budget_remaining_cents"] == 750_000
    assert_budget_conservation(community, 250_000)

    cancel_agreement(agreement_id, "BUILDER_DEFAULT", AGENT)

    revoked = get_incentive(request["id"])
    assert revoked["status"] == "REVOKED"
    community = get_community(bundle["community"]["id"])
    assert community["incentive_budget_remaining_cents"] == 1_000_000
    assert_budget_conservation(community, 0)
    agreement = _get_agreement(agreement_id)
    assert agreement["incentives_total_cents"] == 0


def test_ledger_conservation_across_two_agreements_and_one_revoke():
    """PRD §2.8: "The ledger is conserved: at every instant, the remaining
    budget plus the sum of approved amounts across the community equals the
    original total."
    PRD §3.7: "When an agreement is cancelled, every `APPROVED` request on it
    moves to `REVOKED`, the exact amount is restored to the community's
    remaining budget, and the agreement's `incentives_total_cents` is reduced
    accordingly."

    Design: Difficulty/compensating_invariant/incentive_budget_conserved_across_approve_and_revoke
    """
    bundle = setup_signed_agreement()
    buyer = bundle["buyer"]
    community_id = bundle["community"]["id"]
    agreement_a_id = bundle["agreement"]["id"]

    # A second signed agreement on a second lot in the same community.
    lot_b = release_lot(
        create_lot(
            community_id, lot_number="L-102", base_price_cents=5_000_000,
            lot_type="STANDARD", view_adjustment_cents=0,
        )["id"]
    )
    reserved_b = reserve_lot(lot_b["id"], buyer["id"])
    payload_b = create_agreement_payload(
        buyer_id=buyer["id"], lot_id=lot_b["id"],
        plan_id=bundle["plan"]["id"], elevation_name="A",
        expected_lot_version=reserved_b["version"],
    )
    agreement_b = validate_success(api_client.create_agreement(payload_b, AGENT), 201)
    sign_agreement(agreement_b["id"], buyer["id"])

    create_incentive(agreement_a_id, 250_000)  # auto-approved
    create_incentive(agreement_b["id"], 100_000)  # auto-approved
    community = get_community(community_id)
    assert community["incentive_budget_remaining_cents"] == 650_000
    assert_budget_conservation(community, 350_000)

    cancel_agreement(agreement_a_id, "BUILDER_DEFAULT", AGENT)
    community = get_community(community_id)
    assert community["incentive_budget_remaining_cents"] == 900_000
    assert_budget_conservation(community, 100_000), (
        "only agreement B's approved incentive still draws on the ledger"
    )
    assert _get_agreement(agreement_b["id"])["incentives_total_cents"] == 100_000


def test_incentive_double_decide_rejected():
    """PRD §3.7: "A `SalesDirector` decides a pending request by submitting an
    `action` of `APPROVE` or `DENY`; the request must be in `SUBMITTED`, else
    `ERR_INCENTIVE_INVALID_STATE`."
    PRD §3.7: "A denial simply stamps `decided_at` and moves the request to
    `DENIED` with no ledger movement; `DENIED` and `REVOKED` are terminal, as
    is `APPROVED` until a cancellation revokes it."

    Design: Corner/state_machines/incentive_double_decide_rejected
    """
    bundle = setup_signed_agreement()
    request = create_incentive(
        bundle["agreement"]["id"], 300_001, incentive_type="PRICE_REDUCTION"
    )
    assert request["status"] == "SUBMITTED"

    denied = decide_incentive(request["id"], "DENY")
    assert denied["status"] == "DENIED"

    resp = api_client.decide_incentive_request(
        request["id"], {"action": "APPROVE"}, DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_INCENTIVE_INVALID_STATE)

    community = get_community(bundle["community"]["id"])
    assert community["incentive_budget_remaining_cents"] == 1_000_000, (
        "a denial never debits the ledger"
    )


def test_sales_agent_cannot_decide_incentive():
    """PRD §2.1: "Even with valid headers, a caller whose role is not authorized
    for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: the decide endpoint's authorized role is "SalesDirector".

    Design: Corner/rbac/sales_agent_cannot_decide_incentive
    """
    bundle = setup_signed_agreement()
    request = create_incentive(bundle["agreement"]["id"], 300_001)

    resp = api_client.decide_incentive_request(
        request["id"], {"action": "APPROVE"}, AGENT
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    still = get_incentive(request["id"])
    assert still["status"] == "SUBMITTED"
    community = get_community(bundle["community"]["id"])
    assert community["incentive_budget_remaining_cents"] == 1_000_000
