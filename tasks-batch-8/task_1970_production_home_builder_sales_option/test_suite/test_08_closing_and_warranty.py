"""Closing: the milestone gate, the provisional-vs-final price pair, terminal
lockdown, and warranty enrollment/acknowledgement (PRD §3.8, §3.9)."""
from test_helpers import (
    ApiErrorId,
    CANONICAL_PROVISIONAL_TOTAL_CENTS,
    DEFAULT_CLOCK_ISO,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    close_agreement,
    complete_milestones_in_order,
    confirm_selection,
    create_incentive,
    create_selection,
    get_lot,
    make_buyer_headers,
    setup_cleared_agreement,
    setup_closed_agreement,
    setup_signed_agreement,
    clear_all_pending_contingencies,
    validate_error,
    validate_success,
)

AGENT = TEST_USERS["sales_agent_headers"]


def _get_agreement(agreement_id):
    return validate_success(api_client.get_agreement(agreement_id, AGENT), 200)


def test_close_blocked_until_all_milestones_complete():
    """PRD §3.9: "Closing is a `SalesAgent` act with two hard preconditions: the
    agreement must be in `CONTINGENCIES_CLEARED` (else
    `ERR_AGREEMENT_INVALID_STATE`), and all five of its construction milestones
    must be `COMPLETE` (else `ERR_CLOSE_BLOCKED`)."
    PRD §3.9: "At close the final price crystallizes: `final_total_cents` is
    the immutable `provisional_total_cents` plus `options_total_cents` plus
    `change_fees_total_cents` minus `incentives_total_cents` — identical inputs
    priced at signing would give a different number than at close once options
    and incentives exist, which is exactly why the two totals are computed at
    different moments."
    PRD §3.9: "Warranty enrollment happens in the same motion:
    `warranty_status` moves from `NONE` to `ENROLLED`, `warranty_term_months`
    is set to the standard 12-month term, and `warranty_enrolled_at` is stamped
    with the closing instant."

    Design: Difficulty/cross_entity_state_dependency/close_blocked_until_all_milestones_complete
    """
    bundle = setup_cleared_agreement()
    agreement = bundle["agreement"]
    assert agreement["status"] == "CONTINGENCIES_CLEARED"

    blocked = api_client.close_agreement(agreement["id"], AGENT)
    validate_error(blocked, ApiErrorId.ERR_CLOSE_BLOCKED)

    complete_milestones_in_order(agreement["id"], 5)
    closed = validate_success(api_client.close_agreement(agreement["id"], AGENT), 200)
    assert closed["status"] == "CLOSED"
    assert closed["final_total_cents"] == CANONICAL_PROVISIONAL_TOTAL_CENTS, (
        "no options, fees, or incentives: final equals provisional 45,241,000"
    )
    assert closed["warranty_status"] == "ENROLLED"
    assert closed["warranty_term_months"] == 12
    assert_instant_equals(
        closed["warranty_enrolled_at"], DEFAULT_CLOCK_ISO, "closing instant"
    )

    lot = get_lot(bundle["lot"]["id"])
    assert lot["status"] == "CLOSED"


def test_close_blocked_with_four_of_five_milestones_complete():
    """PRD §3.9: "Closing is a `SalesAgent` act with two hard preconditions: the
    agreement must be in `CONTINGENCIES_CLEARED` (else
    `ERR_AGREEMENT_INVALID_STATE`), and all five of its construction milestones
    must be `COMPLETE` (else `ERR_CLOSE_BLOCKED`)."

    Design: Difficulty/cross_entity_state_dependency/close_blocked_until_all_milestones_complete
    """
    bundle = setup_cleared_agreement()
    agreement_id = bundle["agreement"]["id"]

    complete_milestones_in_order(agreement_id, 4)
    blocked = api_client.close_agreement(agreement_id, AGENT)
    validate_error(blocked, ApiErrorId.ERR_CLOSE_BLOCKED)
    assert _get_agreement(agreement_id)["status"] == "CONTINGENCIES_CLEARED", (
        "a blocked close changes nothing"
    )

    complete_milestones_in_order(agreement_id, 1)
    closed = validate_success(api_client.close_agreement(agreement_id, AGENT), 200)
    assert closed["status"] == "CLOSED"


def test_close_computes_final_total_distinct_from_provisional():
    """PRD §3.9: "At close the final price crystallizes: `final_total_cents` is
    the immutable `provisional_total_cents` plus `options_total_cents` plus
    `change_fees_total_cents` minus `incentives_total_cents` — identical inputs
    priced at signing would give a different number than at close once options
    and incentives exist, which is exactly why the two totals are computed at
    different moments."
    PRD §3.9: "Warranty enrollment happens in the same motion:
    `warranty_status` moves from `NONE` to `ENROLLED`, `warranty_term_months`
    is set to the standard 12-month term, and `warranty_enrolled_at` is stamped
    with the closing instant."

    Design: Difficulty/dual_variant_calc/agreement_price_provisional_vs_final_at_close
    """
    bundle = setup_signed_agreement(with_quartz=True)
    agreement_id = bundle["agreement"]["id"]
    buyer_id = bundle["buyer"]["id"]

    selection = create_selection(agreement_id, bundle["quartz"]["id"], buyer_id)
    confirm_selection(selection["id"], buyer_id)  # options_total 800,000
    incentive = create_incentive(agreement_id, 200_000)  # auto-APPROVED
    assert incentive["status"] == "APPROVED"

    agreement = clear_all_pending_contingencies(agreement_id)
    assert agreement["status"] == "CONTINGENCIES_CLEARED"
    complete_milestones_in_order(agreement_id, 5)

    closed = close_agreement(agreement_id)
    assert closed["status"] == "CLOSED"
    assert closed["provisional_total_cents"] == 45_241_000, (
        "9,991,000 + 35,000,000 + 250,000, frozen at signing"
    )
    assert closed["options_total_cents"] == 800_000
    assert closed["change_fees_total_cents"] == 0
    assert closed["incentives_total_cents"] == 200_000
    # 45,241,000 + 800,000 + 0 - 200,000 = 45,841,000: the final variant
    # diverges from the provisional by exactly the post-signing accruals.
    assert closed["final_total_cents"] == 45_841_000
    assert closed["warranty_status"] == "ENROLLED"
    assert closed["warranty_term_months"] == 12

    lot = get_lot(bundle["lot"]["id"])
    assert lot["status"] == "CLOSED"


def test_provisional_total_frozen_while_accruals_accumulate():
    """PRD §3.3: "The `provisional_total_cents` is fixed at that moment as the
    sum of the three snapshots and never changes afterwards."
    PRD §3.9: "At close the final price crystallizes: `final_total_cents` is
    the immutable `provisional_total_cents` plus `options_total_cents` plus
    `change_fees_total_cents` minus `incentives_total_cents` — identical inputs
    priced at signing would give a different number than at close once options
    and incentives exist, which is exactly why the two totals are computed at
    different moments."

    Design: Difficulty/dual_variant_calc/agreement_price_provisional_vs_final_at_close
    """
    bundle = setup_signed_agreement(with_quartz=True)
    agreement_id = bundle["agreement"]["id"]
    buyer_id = bundle["buyer"]["id"]

    selection = create_selection(agreement_id, bundle["quartz"]["id"], buyer_id)
    confirm_selection(selection["id"], buyer_id)
    create_incentive(agreement_id, 200_000)

    mid = _get_agreement(agreement_id)
    assert mid["provisional_total_cents"] == 45_241_000, (
        "options and incentives accrue without touching the provisional total"
    )
    assert mid["options_total_cents"] == 800_000
    assert mid["incentives_total_cents"] == 200_000
    assert mid["final_total_cents"] is None, (
        "the final price crystallizes only at close"
    )

    clear_all_pending_contingencies(agreement_id)
    complete_milestones_in_order(agreement_id, 5)
    closed = close_agreement(agreement_id)
    assert closed["final_total_cents"] == 45_841_000
    assert closed["provisional_total_cents"] == 45_241_000


def test_cancel_closed_agreement_returns_invalid_state():
    """PRD §3.8: "An agreement in `DRAFT`, `PENDING_CONTINGENCIES`, or
    `CONTINGENCIES_CLEARED` may be cancelled by the owning `Buyer` or by a
    `SalesAgent` (a buyer cancelling someone else's contract is rejected with
    `ERR_NOT_RESOURCE_OWNER`; any other status is rejected with
    `ERR_AGREEMENT_INVALID_STATE`)."
    PRD §3.8: "A cancelled agreement is terminal; `CLOSED` and `CANCELLED` are
    the two terminal agreement states."

    Design: Corner/state_machines/cancel_closed_agreement_returns_invalid_state
    """
    bundle = setup_closed_agreement()
    agreement = bundle["agreement"]
    assert agreement["status"] == "CLOSED"

    resp = api_client.cancel_agreement(
        agreement["id"], {"reason": "BUYER_DEFAULT"},
        make_buyer_headers(bundle["buyer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)

    after = _get_agreement(agreement["id"])
    assert after["status"] == "CLOSED"
    assert after["warranty_status"] == "ENROLLED"
    assert after["final_total_cents"] == CANONICAL_PROVISIONAL_TOTAL_CENTS


def test_warranty_acknowledge_flow_and_replay_rejected():
    """PRD §3.9: "The owning buyer acknowledges the enrolled warranty, moving
    `warranty_status` from `ENROLLED` to `ACKNOWLEDGED`; the agreement must be
    `CLOSED` with the warranty still `ENROLLED` (else
    `ERR_AGREEMENT_INVALID_STATE`), and the caller must own the agreement (else
    `ERR_NOT_RESOURCE_OWNER`)."
    PRD §3.9: "This is a self-transition on the contract dimension — the
    agreement's `status` stays `CLOSED` — restricted to the warranty dimension
    alone, and it increments the agreement's `version` like any other
    mutation."

    Design: Corner/state_machines/warranty_acknowledge_flow_and_replay_rejected
    """
    bundle = setup_closed_agreement()
    agreement = bundle["agreement"]
    buyer_headers = make_buyer_headers(bundle["buyer"]["id"])
    assert agreement["warranty_status"] == "ENROLLED"

    acknowledged = validate_success(
        api_client.acknowledge_warranty(agreement["id"], buyer_headers), 200
    )
    assert acknowledged["warranty_status"] == "ACKNOWLEDGED"
    assert acknowledged["status"] == "CLOSED", "contract status stays CLOSED"

    replay = api_client.acknowledge_warranty(agreement["id"], buyer_headers)
    validate_error(replay, ApiErrorId.ERR_AGREEMENT_INVALID_STATE)
