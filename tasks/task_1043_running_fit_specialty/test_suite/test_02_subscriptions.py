"""Subscription lifecycle: the ACTIVE<->PAST_DUE cycle and invalid-state transitions."""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_member_headers,
    fixtures as fx,
)
import test_helpers.factories as f

SM = TEST_USERS["store_manager_headers"]


def test_subscription_failed_renewal_moves_active_to_past_due(api):
    """PRD §3.2: "A `payment_outcome` of `FAILED` moves an `ACTIVE` subscription to
    `PAST_DUE`; while `PAST_DUE`, the member loses their club gear and training
    discounts, so subsequent order and fitting pricing recomputes with the
    subscription's gear/training contribution treated as zero."

    Design: Difficulty/non_linear_state_machine/subscription_cycle_active_pastdue_active
    """
    member = fx.new_member(api)
    hdr = make_member_headers(member["id"])
    sub = fx.new_subscription(api, member["id"], member["version"], tier="CLUB_BASIC")
    get_success_data(api.activate_subscription(sub["id"], hdr))
    updated = get_success_data(api.renew_subscription(sub["id"], f.renew_payload("FAILED"), SM))
    assert updated["status"] == "PAST_DUE"


def test_subscription_cycles_back_to_active_on_succeeded_renewal(api):
    """PRD §3.2: "A `payment_outcome` of `SUCCEEDED` on a `PAST_DUE` subscription
    reactivates it to `ACTIVE`, advances `current_period_end` by a further 30 days,
    and resets `fittings_used_this_period` to 0. This `ACTIVE` ⇄ `PAST_DUE` cycle
    may repeat."

    Design: Difficulty/non_linear_state_machine/subscription_cycle_active_pastdue_active
    """
    member = fx.new_member(api)
    hdr = make_member_headers(member["id"])
    sub = fx.new_subscription(api, member["id"], member["version"], tier="CLUB_BASIC")
    get_success_data(api.activate_subscription(sub["id"], hdr))
    get_success_data(api.renew_subscription(sub["id"], f.renew_payload("FAILED"), SM))
    reactivated = get_success_data(api.renew_subscription(sub["id"], f.renew_payload("SUCCEEDED"), SM))
    assert reactivated["status"] == "ACTIVE"


def test_activate_already_active_subscription_rejected(api):
    """PRD §3.2: "Attempting to activate a subscription that is not `PENDING` is an
    invalid transition and is rejected with `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/activate_already_active_subscription_returns_invalid_state
    """
    member = fx.new_member(api)
    hdr = make_member_headers(member["id"])
    sub = fx.new_subscription(api, member["id"], member["version"], tier="CLUB_BASIC")
    get_success_data(api.activate_subscription(sub["id"], hdr))
    resp = api.activate_subscription(sub["id"], hdr)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
