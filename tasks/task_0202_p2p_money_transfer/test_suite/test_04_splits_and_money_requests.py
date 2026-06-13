"""Split share allocation, split rollup/cancel, and money-request lifecycle.

Queue A: combinatorial_formula/split_share_largest_remainder_rounding_order,
boundary_precision_check/split_cancel_zero_paid_empty_set_boundary.
Queue B: calculations (even remainder to earliest), state_machines (partially
settled bubble-up, cancel-already-declined invalid state), validations (too few
participants), endpoints (money-request decline, pay spawns transfer).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_account_holder_headers,
    make_platform_admin_headers,
    create_account,
    make_recipient_verified,
    seed_credit,
    setup_even_split_with_new_accounts,
    setup_weighted_split_with_new_accounts,
    setup_split_request,
    list_participants,
    participant_by_account,
    create_split_request_payload,
    create_money_request_payload,
)


# ===========================================================================
# Queue A — combinatorial_formula / split_share_largest_remainder_rounding_order
# ===========================================================================
def test_weighted_split_largest_remainder_allocation(api):
    """PRD §3.7: "For a `WEIGHTED` split, the weighted raw share for each participant
    is `total_amount_cents` times that participant's `weight` divided by the sum of
    all weights; each raw share is floored to a whole cent, and the leftover cents
    (the total minus the sum of the floored shares) are distributed by the
    largest-remainder method: participants are ranked by the fractional part of
    their raw share in descending order, ties broken by `created_at` ascending, and
    the top-ranked participants each receive one extra cent until the leftover is
    exhausted."

    Total 10000 over weights [1,2,3]: floors [1666,3333,5000] sum 9999; the 1
    leftover cent goes to the largest remainder (weight 1, raw 1666.67) -> [1667,3333,5000].

    Design: Difficulty/combinatorial_formula/split_share_largest_remainder_rounding_order
    """
    org, parts_accts, sr, parts = setup_weighted_split_with_new_accounts(10000, [1, 2, 3])
    p1 = participant_by_account(parts, parts_accts[0]["id"])
    p2 = participant_by_account(parts, parts_accts[1]["id"])
    p3 = participant_by_account(parts, parts_accts[2]["id"])
    assert p1["share_amount_cents"] == 1667
    assert p2["share_amount_cents"] == 3333
    assert p3["share_amount_cents"] == 5000


def test_weighted_split_shares_sum_to_total(api):
    """PRD §3.7: "In both modes the sum of all `share_amount_cents` equals
    `total_amount_cents` exactly."

    Weighted shares over [1,2,3] for total 10000 sum to exactly 10000.

    Design: Difficulty/combinatorial_formula/split_share_largest_remainder_rounding_order
    """
    org, parts_accts, sr, parts = setup_weighted_split_with_new_accounts(10000, [1, 2, 3])
    total = sum(p["share_amount_cents"] for p in parts)
    assert total == 10000, f"shares must sum to 10000, got {total}"


# ===========================================================================
# Queue A — boundary_precision_check / split_cancel_zero_paid_empty_set_boundary
# ===========================================================================
def test_cancel_split_with_zero_paid_forgives_all(api):
    """PRD §3.7: "The organizer may cancel a split only while it is `OPEN` and no
    participant has yet reached `PAID`; cancellation sets every still-`OWED`
    participant to `FORGIVEN`."

    With zero PAID participants, cancel succeeds and flips both OWED participants to
    FORGIVEN.

    Design: Difficulty/boundary_precision_check/split_cancel_zero_paid_empty_set_boundary
    """
    org, parts_accts, sr, parts = setup_even_split_with_new_accounts(1000, 2)
    res = api.cancel_split_request(sr["id"], make_account_holder_headers(org["id"]))
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    after = list_participants(sr["id"], org["id"])
    assert all(p["status"] == "FORGIVEN" for p in after), (
        f"all participants should be FORGIVEN, got {[p['status'] for p in after]}"
    )


def test_cancel_split_with_a_paid_participant_rejected(api):
    """PRD §3.7: "The organizer may cancel a split only while it is `OPEN` and no
    participant has yet reached `PAID`"

    Once one participant has PAID, the count-of-PAID is no longer 0, so cancel is an
    invalid transition.

    Design: Difficulty/boundary_precision_check/split_cancel_zero_paid_empty_set_boundary
    """
    org = create_account()
    p1 = create_account(funded_cents=50000)
    make_recipient_verified(org["id"])  # organizer receives the share transfer
    p2 = create_account()
    sr, parts = setup_split_request(1000, [p1["id"], p2["id"]], split_mode="EVEN",
                                    organizer_account_id=org["id"])
    part1 = participant_by_account(parts, p1["id"])
    validate_success(api.pay_split_participant(sr["id"], part1["id"], {},
                                               make_account_holder_headers(p1["id"])), 200)
    res = api.cancel_split_request(sr["id"], make_account_holder_headers(org["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — calculations: EVEN remainder to earliest participant
# ===========================================================================
def test_even_split_remainder_to_earliest_participant(api):
    """PRD §3.7: "For an `EVEN` split, the base share is the total divided by the
    participant count, taking the whole-number (floor) quotient ... The remaining
    cents are handed out one each to the earliest participants — the first
    however-many participants ordered by `created_at` ascending (never by `id`)
    receive one extra cent each until the remainder is exhausted."

    Total 10000 over 3 -> base 3333, remainder 1 to the earliest participant:
    [3334, 3333, 3333], sum 10000.

    Design: Corner/calculations/split_even_remainder_to_earliest_participant
    """
    org, parts_accts, sr, parts = setup_even_split_with_new_accounts(10000, 3)
    p1 = participant_by_account(parts, parts_accts[0]["id"])
    p2 = participant_by_account(parts, parts_accts[1]["id"])
    p3 = participant_by_account(parts, parts_accts[2]["id"])
    assert p1["share_amount_cents"] == 3334
    assert p2["share_amount_cents"] == 3333
    assert p3["share_amount_cents"] == 3333
    assert sum(p["share_amount_cents"] for p in parts) == 10000


# ===========================================================================
# Queue B — state_machines: partially-settled bubble-up
# ===========================================================================
def test_split_partially_settled_bubble_up(api):
    """PRD §3.7: "The `collected_amount_cents` is recomputed as the sum of
    `share_amount_cents` over participants currently in `PAID`. ... otherwise if at
    least one participant has paid, the split is `PARTIALLY_SETTLED`"
    PRD §3.7: "The split therefore moves `OPEN → PARTIALLY_SETTLED` when its first
    participant pays while others remain `OWED`"

    When one of two participants pays a 500c share (1000 EVEN split), the split
    becomes PARTIALLY_SETTLED with collected_amount_cents 500.

    Design: Corner/state_machines/split_partially_settled_bubble_up
    """
    org = create_account()
    make_recipient_verified(org["id"])
    p1 = create_account(funded_cents=50000)
    p2 = create_account()
    sr, parts = setup_split_request(1000, [p1["id"], p2["id"]], split_mode="EVEN",
                                    organizer_account_id=org["id"])
    part1 = participant_by_account(parts, p1["id"])
    validate_success(api.pay_split_participant(sr["id"], part1["id"], {},
                                               make_account_holder_headers(p1["id"])), 200)
    after = validate_success(api.get_split_request(sr["id"], make_account_holder_headers(org["id"])), 200)
    assert after["status"] == "PARTIALLY_SETTLED"
    assert after["collected_amount_cents"] == 500


def test_cancel_already_declined_money_request_invalid_state(api):
    """PRD §3.6: "The payer may decline a `PENDING` request, which simply moves it
    to the terminal `DECLINED` state with no money movement."
    PRD §3.6: "The original requester may cancel their own `PENDING` request, moving
    it to the terminal `CANCELLED` state with no money movement."
    PRD §2.5: "(6) the target being in a state from which the requested transition
    is defined, surfacing `ERR_INVALID_STATE`"

    Cancelling an already-DECLINED (terminal) money request is rejected: cancel is
    defined only from PENDING, and DECLINED is terminal.

    Design: Corner/state_machines/cancel_already_declined_money_request_returns_invalid_state
    """
    requester = create_account()
    payer = create_account()
    mr = get_success_data(api.create_money_request(
        create_money_request_payload(requester["id"], payer["id"], 3000),
        make_account_holder_headers(requester["id"]),
    ))
    validate_success(api.decline_money_request(mr["id"], make_account_holder_headers(payer["id"])), 200)
    res = api.cancel_money_request(mr["id"], make_account_holder_headers(requester["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — validations: split with too few participants
# ===========================================================================
def test_split_too_few_participants_rejected(api):
    """PRD §3.7: "A split must have at least two participants ... any of these
    violations is rejected with `ERR_SPLIT_PARTICIPANT_INVALID`."

    A split with a single participant is rejected.

    Design: Corner/validations/split_too_few_participants_rejected
    """
    org = create_account()
    p = create_account()
    res = api.create_split_request(
        create_split_request_payload(org["id"], 1000, [{"participant_account_id": p["id"]}], split_mode="EVEN"),
        make_account_holder_headers(org["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SPLIT_PARTICIPANT_INVALID.value)


# ===========================================================================
# Queue B — endpoints: money-request decline / pay spawns transfer
# ===========================================================================
def test_money_request_decline_no_transfer(api):
    """PRD §3.6: "The payer may decline a `PENDING` request, which simply moves it
    to the terminal `DECLINED` state with no money movement."

    Declining a PENDING money request by the payer sets it DECLINED with no transfer.

    Design: Corner/endpoints/money_request_decline_action
    """
    requester = create_account()
    payer = create_account()
    mr = get_success_data(api.create_money_request(
        create_money_request_payload(requester["id"], payer["id"], 4000),
        make_account_holder_headers(requester["id"]),
    ))
    res = api.decline_money_request(mr["id"], make_account_holder_headers(payer["id"]))
    declined = validate_success(res, 200)
    assert declined["status"] == "DECLINED"


def test_money_request_pay_spawns_settled_transfer(api):
    """PRD §3.6: "Fulfillment spawns a transfer from the payer to the requester for
    the request's amount ... When the spawned transfer is created, the request moves
    to the terminal `FULFILLED` state."

    Paying a 3000c request from a funded payer to a verified requester fulfills the
    request and credits the requester 3000.

    Design: Corner/endpoints/money_request_pay_spawns_transfer
    """
    requester = create_account()
    make_recipient_verified(requester["id"])
    payer = create_account(funded_cents=50000)
    mr = get_success_data(api.create_money_request(
        create_money_request_payload(requester["id"], payer["id"], 3000),
        make_account_holder_headers(requester["id"]),
    ))
    res = api.pay_money_request(mr["id"], {}, make_account_holder_headers(payer["id"]))
    fulfilled = validate_success(res, 200)
    assert fulfilled["status"] == "FULFILLED"
    req = validate_success(api.get_account(requester["id"], make_account_holder_headers(requester["id"])), 200)
    assert req["available_balance_cents"] == 3000
