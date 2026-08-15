"""Feed order lifecycle: validation quota accounting, SUBMITTED branching,
state guards, VCPR cross-entity dependency, ship-time acknowledgment gate,
and OCC on validate (PRD §2.7, §2.8, §3.2, §3.5, §3.6, §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_order_chain, setup_validated_order, setup_vfd_chain,
    setup_mill_with_ack, submit_order, validate_order, fresh_vfd,
    get_withdrawal_plan_for_order, set_clock,
    make_veterinarian_headers, make_feed_mill_operator_headers,
    make_producer_headers,
)

INSPECTOR = TEST_USERS["inspector_headers"]


# ─── Difficulty: vfd_remaining_quota_forward_vs_settled ───

def test_validate_debits_vfd_remaining_quota(api):
    """PRD §2.8: "Its `remaining_animal_count` is derived as
    `authorized_animal_count` minus the sum of `animal_count` across every
    `FeedOrder` bound to this VFD whose status is `VALIDATED`, `SHIPPED`, or
    `DELIVERED`. The deduction happens when an order transitions into `VALIDATED`."
    PRD §3.5: "if the VFD was in `ISSUED`, it transitions to `PARTIALLY_USED` on
    this first validation"

    Design: Difficulty/dual_variant_calc/vfd_remaining_quota_forward_vs_settled
    """
    chain = setup_order_chain(
        vfd_overrides={"authorized_animal_count": 50},
        order_overrides={"animal_count": 20},
    )
    validated = validate_order(chain["mill"], chain["order"], chain["vfd"]["id"])
    assert validated["status"] == "VALIDATED"

    vfd_after = fresh_vfd(chain["vfd"]["id"])
    assert vfd_after["remaining_animal_count"] == 30, (
        f"Expected remaining 30 (50 - 20), got {vfd_after['remaining_animal_count']}"
    )
    assert vfd_after["status"] == "PARTIALLY_USED"


def test_cancel_validated_order_returns_quota(api):
    """PRD §2.8: "A compensating return happens when an order leaves `VALIDATED`
    for `CANCELLED` — whether by explicit cancellation, by a shipment being
    returned, by a shipment being rejected at receipt, or by a VFD-driven cascade —
    at which point the order's `animal_count` is added back into
    `remaining_animal_count` and the VFD's `version` is incremented."

    Design: Difficulty/dual_variant_calc/vfd_remaining_quota_forward_vs_settled
    """
    chain = setup_order_chain(
        vfd_overrides={"authorized_animal_count": 50},
        order_overrides={"animal_count": 20},
    )
    validate_order(chain["mill"], chain["order"], chain["vfd"]["id"])
    assert fresh_vfd(chain["vfd"]["id"])["remaining_animal_count"] == 30

    cancelled = validate_success(
        api.cancel_feed_order(
            chain["order"]["id"], make_producer_headers(chain["producer"]["id"])
        ), 200,
    )
    assert cancelled["status"] == "CANCELLED"
    vfd_after = fresh_vfd(chain["vfd"]["id"])
    assert vfd_after["remaining_animal_count"] == 50, (
        f"Expected remaining restored to 50, got {vfd_after['remaining_animal_count']}"
    )


# ─── Difficulty: feed_order_branching_reject_vs_validate ───

def test_reject_branch_leaves_quota_and_creates_no_plan(api):
    """PRD §3.5: "A mill may instead reject an order that is still in `SUBMITTED`
    by supplying a `rejection_reason`; the order transitions to `REJECTED` with the
    reason recorded."
    PRD §3.11: "Withdrawal plans are listed per feed order — the list contains zero
    or one entry, because a plan exists only after validation."

    Design: Difficulty/non_linear_state_machine/feed_order_branching_reject_vs_validate
    """
    chain = setup_order_chain(
        vfd_overrides={"authorized_animal_count": 30},
        order_overrides={"animal_count": 10},
    )
    rejected = validate_success(api.reject_feed_order(
        chain["order"]["id"], {"rejection_reason": "bad label"},
        make_feed_mill_operator_headers(chain["mill"]["id"]),
    ), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected.get("rejection_reason") == "bad label"

    vfd_after = fresh_vfd(chain["vfd"]["id"])
    assert vfd_after["remaining_animal_count"] == 30, (
        "Rejection must not debit the VFD quota (deduction happens on VALIDATED)"
    )
    plans = get_success_data(
        api.list_order_withdrawal_plans(chain["order"]["id"], INSPECTOR))
    assert plans == [], "A rejected order has no withdrawal plan"


def test_validate_branch_debits_quota_and_creates_plan(api):
    """PRD §3.5: "When validation succeeds, several effects fire together. The
    order transitions from `SUBMITTED` to `VALIDATED`. A `WithdrawalPlan` is
    created in `PROVISIONAL` status with `withdrawal_window_hours` copied from the
    linked drug's `withdrawal_hours` at this moment. ... The VFD's
    `remaining_animal_count` is decremented by the order's `animal_count`"

    Design: Difficulty/non_linear_state_machine/feed_order_branching_reject_vs_validate
    """
    chain = setup_order_chain(
        vfd_overrides={"authorized_animal_count": 30},
        order_overrides={"animal_count": 5},
    )
    # Rejected sibling order must not affect this branch.
    sibling = submit_order(chain["mill"], chain["vfd"], chain["producer"], animal_count=10)
    validate_success(api.reject_feed_order(
        sibling["id"], {"rejection_reason": "bad label"},
        make_feed_mill_operator_headers(chain["mill"]["id"]),
    ), 200)

    validated = validate_order(chain["mill"], chain["order"], chain["vfd"]["id"])
    assert validated["status"] == "VALIDATED"

    vfd_after = fresh_vfd(chain["vfd"]["id"])
    assert vfd_after["remaining_animal_count"] == 25, (
        f"Expected remaining 25 (30 - 5; rejected sibling did not debit), "
        f"got {vfd_after['remaining_animal_count']}"
    )
    plan = get_withdrawal_plan_for_order(chain["order"]["id"])
    assert plan["status"] == "PROVISIONAL"


# ─── Difficulty: state_vs_safety_vfd_expired_and_extra_label ───

def test_validate_rejected_order_returns_invalid_state(api):
    """PRD §3.5: "When validation succeeds, several effects fire together. The
    order transitions from `SUBMITTED` to `VALIDATED`." A `REJECTED` order has
    left `SUBMITTED`, so validation is a state-guard violation rejected with
    `ERR_INVALID_STATE` (HTTP 409, PRD §5).

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_vfd_expired_and_extra_label
    """
    chain = setup_order_chain()
    validate_success(api.reject_feed_order(
        chain["order"]["id"], {"rejection_reason": "rejected already"},
        make_feed_mill_operator_headers(chain["mill"]["id"]),
    ), 200)

    res = api.validate_feed_order(
        chain["order"]["id"],
        {"expected_vfd_authorization_version": fresh_vfd(chain["vfd"]["id"])["version"]},
        make_feed_mill_operator_headers(chain["mill"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_validate_cancelled_order_returns_invalid_state(api):
    """PRD §3.5: "When validation succeeds, several effects fire together. The
    order transitions from `SUBMITTED` to `VALIDATED`."
    PRD §3.7: "Cancelling a `SUBMITTED` order moves it to `CANCELLED` with no
    further effect." A `CANCELLED` order cannot later be validated; the state
    guard rejects with `ERR_INVALID_STATE` (HTTP 409, PRD §5).

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_vfd_expired_and_extra_label
    """
    chain = setup_order_chain()
    validate_success(
        api.cancel_feed_order(
            chain["order"]["id"], make_producer_headers(chain["producer"]["id"])
        ), 200,
    )

    res = api.validate_feed_order(
        chain["order"]["id"],
        {"expected_vfd_authorization_version": fresh_vfd(chain["vfd"]["id"])["version"]},
        make_feed_mill_operator_headers(chain["mill"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# ─── Difficulty: feedorder_validate_requires_vcpr_active ───

def test_validate_with_expired_vcpr_rejected(api):
    """PRD §3.5: "Eighth, an `ACTIVE` VCPR must cover the pair of the VFD's
    veterinarian and the VFD's producer at validation time (otherwise
    `ERR_VCPR_NOT_VERIFIED`)."
    PRD §3.2: "When the logical clock reaches `expires_on`, the VCPR transitions
    automatically from `ACTIVE` to `EXPIRED` with no further side effects."

    Setup note: the VCPR is lapsed by the clock (not revoked), so per §3.2 the
    VFD is untouched and the VCPR check is the only failing precondition.

    Design: Difficulty/cross_entity_state_dependency/feedorder_validate_requires_vcpr_active
    """
    chain = setup_order_chain(vcpr_expires_on="2026-08-15T00:00:00Z")
    # VCPR expires 2026-08-15; the VFD's own expiration (2026-10-01) stays ahead.
    set_clock("2026-08-16T00:00:00Z")

    res = api.validate_feed_order(
        chain["order"]["id"],
        {"expected_vfd_authorization_version": fresh_vfd(chain["vfd"]["id"])["version"]},
        make_feed_mill_operator_headers(chain["mill"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_VCPR_NOT_VERIFIED, expected_status=422)
    order_after = validate_success(api.get_feed_order(chain["order"]["id"], INSPECTOR), 200)
    assert order_after["status"] == "SUBMITTED"


def test_vcpr_revocation_cascades_vfd_expiry_and_order_cancellation(api):
    """PRD §3.2: "Revoking a VCPR cascades: every `VfdAuthorization` in `ISSUED`
    or `PARTIALLY_USED` status that was issued by this veterinarian for this
    producer transitions to `EXPIRED`, and the per-VFD side effects described in
    §3.4 fire for each one."
    PRD §3.4: "every `FeedOrder` for this VFD currently in `SUBMITTED` or
    `VALIDATED` transitions to `CANCELLED` with its `rejection_reason` set to the
    string `VFD_EXPIRED`"

    Design: Difficulty/cross_entity_state_dependency/feedorder_validate_requires_vcpr_active
    """
    chain = setup_order_chain()
    revoked = validate_success(api.revoke_vcp_verification(
        chain["vcpr"]["id"], {"revocation_reason": "VCPR lapsed"},
        make_veterinarian_headers(chain["vet"]["id"]),
    ), 200)
    assert revoked["status"] == "REVOKED"

    vfd_after = fresh_vfd(chain["vfd"]["id"])
    assert vfd_after["status"] == "EXPIRED", (
        f"VCPR revocation must cascade the VFD to EXPIRED, got {vfd_after['status']}"
    )
    order_after = validate_success(api.get_feed_order(chain["order"]["id"], INSPECTOR), 200)
    assert order_after["status"] == "CANCELLED"
    assert order_after.get("rejection_reason") == "VFD_EXPIRED"


# ─── Difficulty: feedorder_ship_requires_distributor_ack ───

def test_ship_without_distributor_ack_rejected(api):
    """PRD §3.6: "it requires a `DistributorAcknowledgment` in `ACKNOWLEDGED`
    status to exist covering this mill and this VFD's drug (otherwise
    `ERR_ACK_MISSING`, HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/feedorder_ship_requires_distributor_ack
    """
    chain = setup_validated_order(with_ack=False)
    res = api.ship_feed_order(
        chain["order"]["id"], {"tons_shipped": 1},
        make_feed_mill_operator_headers(chain["mill"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_ACK_MISSING, expected_status=422)
    order_after = validate_success(api.get_feed_order(chain["order"]["id"], INSPECTOR), 200)
    assert order_after["status"] == "VALIDATED"


def test_ship_with_distributor_ack_succeeds(api):
    """PRD §3.6: "On success, the order transitions from `VALIDATED` to `SHIPPED`
    and a `FeedShipment` is created in `IN_TRANSIT` status with `shipped_at` set
    to the current logical time."

    Design: Difficulty/cross_entity_state_dependency/feedorder_ship_requires_distributor_ack
    """
    chain = setup_validated_order(with_ack=True)
    shipment = validate_success(api.ship_feed_order(
        chain["order"]["id"], {"tons_shipped": 1},
        make_feed_mill_operator_headers(chain["mill"]["id"]),
    ), 200)
    assert shipment["status"] == "IN_TRANSIT"
    assert shipment["feed_order_id"] == chain["order"]["id"]
    assert shipment.get("shipped_at")

    order_after = validate_success(api.get_feed_order(chain["order"]["id"], INSPECTOR), 200)
    assert order_after["status"] == "SHIPPED"


# ─── Difficulty: vfd_quota_conserved_across_validate_cancel ───

def test_quota_conserved_after_validate(api):
    """PRD §2.8: "Its `remaining_animal_count` is derived as
    `authorized_animal_count` minus the sum of `animal_count` across every
    `FeedOrder` bound to this VFD whose status is `VALIDATED`, `SHIPPED`, or
    `DELIVERED`."
    PRD §3.5: "The mill's `pending_order_count` increments by one."

    Design: Difficulty/compensating_invariant/vfd_quota_conserved_across_validate_cancel
    """
    chain = setup_order_chain(
        vfd_overrides={"authorized_animal_count": 50},
        order_overrides={"animal_count": 15},
    )
    validate_order(chain["mill"], chain["order"], chain["vfd"]["id"])

    vfd_after = fresh_vfd(chain["vfd"]["id"])
    assert vfd_after["remaining_animal_count"] == 35, (
        f"Expected 35 (50 - 15), got {vfd_after['remaining_animal_count']}"
    )
    mill_after = validate_success(api.get_feed_mill(chain["mill"]["id"], INSPECTOR), 200)
    assert mill_after["pending_order_count"] == 1


def test_quota_conserved_after_validate_then_cancel(api):
    """PRD §2.8: "A compensating return happens when an order leaves `VALIDATED`
    for `CANCELLED` — whether by explicit cancellation, by a shipment being
    returned, by a shipment being rejected at receipt, or by a VFD-driven cascade —
    at which point the order's `animal_count` is added back into
    `remaining_animal_count` and the VFD's `version` is incremented."
    PRD §3.7: "Cancelling a `VALIDATED` order fires the compensating return: the
    VFD's `remaining_animal_count` is incremented by the order's `animal_count`,
    the VFD's `version` increments, the mill's `pending_order_count` decrements by
    one, and the order's `WithdrawalPlan` is left behind in `PROVISIONAL` status
    as an orphan kept for audit."

    Design: Difficulty/compensating_invariant/vfd_quota_conserved_across_validate_cancel
    """
    chain = setup_order_chain(
        vfd_overrides={"authorized_animal_count": 50},
        order_overrides={"animal_count": 15},
    )
    validate_order(chain["mill"], chain["order"], chain["vfd"]["id"])
    validate_success(
        api.cancel_feed_order(
            chain["order"]["id"], make_producer_headers(chain["producer"]["id"])
        ), 200,
    )

    vfd_after = fresh_vfd(chain["vfd"]["id"])
    assert vfd_after["remaining_animal_count"] == 50, (
        f"Compensating return must restore 50, got {vfd_after['remaining_animal_count']}"
    )
    mill_after = validate_success(api.get_feed_mill(chain["mill"]["id"], INSPECTOR), 200)
    assert mill_after["pending_order_count"] == 0


# ─── Corner: optimistic_concurrency_stale_validate_version ───

def test_validate_with_stale_vfd_version_rejected(api):
    """PRD §2.7: "Validating a feed order is the other: the validation request
    must carry `expected_vfd_authorization_version` matching the VFD's current
    `version`, and a mismatch — which signals that another order validation has
    just debited the VFD's `remaining_animal_count` — is likewise rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_validate_version
    """
    chain = setup_order_chain(
        vfd_overrides={"authorized_animal_count": 50},
        order_overrides={"animal_count": 10},
    )
    original_version = chain["vfd"]["version"]
    order2 = submit_order(chain["mill"], chain["vfd"], chain["producer"], animal_count=10)

    # First validation succeeds and advances the VFD version (PRD §3.5).
    validate_order(chain["mill"], chain["order"], chain["vfd"]["id"],
                   expected_version=original_version)

    res = api.validate_feed_order(
        order2["id"],
        {"expected_vfd_authorization_version": original_version},
        make_feed_mill_operator_headers(chain["mill"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    order2_after = validate_success(api.get_feed_order(order2["id"], INSPECTOR), 200)
    assert order2_after["status"] == "SUBMITTED"
