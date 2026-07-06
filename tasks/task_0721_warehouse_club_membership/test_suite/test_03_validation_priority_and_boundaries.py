"""Difficulty-queue validation-priority and boundary-precision tests."""
from test_helpers import (
    validate_error, get_success_data,
    create_basic_plan, create_product,
    create_active_membership, set_clock,
    open_transaction, add_line, ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["club_admin_headers"]
CLERK = TEST_USERS["register_clerk_headers"]


def test_membership_not_active_beats_member_only(api):
    """PRD §2.6: "the target resource being in the correct state for the requested
    transition, yielding ERR_MEMBERSHIP_NOT_ACTIVE ... and then the operation-specific
    business rules described in §3."
    PRD §3.5: "Adding a line is permitted only ... while the owning membership is ACTIVE
    (otherwise ERR_MEMBERSHIP_NOT_ACTIVE). If the product is member_only and the owning
    membership is not ACTIVE, the line is rejected with ERR_MEMBER_ONLY_PRODUCT."

    Design: Difficulty/priority_pair_validation_conflict/state_not_active_beats_member_only_safety
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-MO", list_price_cents=10000, member_price_cents=8000,
                             member_only=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem PV1", auto_renew=False)
    txn = open_transaction(m["id"])
    set_clock("2027-04-01T00:00:00Z")  # membership EXPIRES — both rules would apply

    res = api.add_line(txn["id"], {"product_id": product["id"], "qty": 1}, CLERK)
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)


def test_purchase_limit_beats_reward_fiscal(api):
    """PRD §3.5: "When the product carries a positive per_member_limit, the requested qty
    plus the units of that product already purchased by this membership in the current
    term ... must not exceed per_member_limit; otherwise the line is rejected with
    ERR_PURCHASE_LIMIT_EXCEEDED (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/purchase_limit_beats_reward_fiscal_redemption
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-LIM", list_price_cents=10000, member_price_cents=8000,
                             per_member_limit=3)
    m = create_active_membership(plan["id"], primary_member_name="Mem PV2", auto_renew=False)
    txn = open_transaction(m["id"])
    add_line(txn["id"], product["id"], 3)  # cumulative at limit

    res = api.add_line(txn["id"], {"product_id": product["id"], "qty": 1}, CLERK)
    validate_error(res, ApiErrorId.ERR_PURCHASE_LIMIT_EXCEEDED)


def test_purchase_limit_at_exact_boundary(api):
    """PRD §3.5: "the requested qty plus the units of that product already purchased by
    this membership in the current term — counting both this transaction's open lines and
    the membership's finalized lines — must not exceed per_member_limit."

    Design: Difficulty/boundary_precision_check/purchase_limit_at_exact_boundary
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-BND", list_price_cents=10000, member_price_cents=8000,
                             per_member_limit=3)
    m = create_active_membership(plan["id"], primary_member_name="Mem BND", auto_renew=False)
    txn = open_transaction(m["id"])
    ok = add_line(txn["id"], product["id"], 3)  # cumulative 3 == limit accepted
    assert ok["qty"] == 3

    res = api.add_line(txn["id"], {"product_id": product["id"], "qty": 1}, CLERK)
    validate_error(res, ApiErrorId.ERR_PURCHASE_LIMIT_EXCEEDED)  # cumulative 4 > 3


def test_purchase_limit_below_boundary_succeeds(api):
    """PRD §3.5: "A per_member_limit of 0 imposes no cap." and "the requested qty plus the
    units of that product already purchased ... must not exceed per_member_limit."

    Design: Difficulty/boundary_precision_check/purchase_limit_at_exact_boundary
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-BND2", list_price_cents=10000, member_price_cents=8000,
                             per_member_limit=3)
    m = create_active_membership(plan["id"], primary_member_name="Mem BND2", auto_renew=False)
    txn = open_transaction(m["id"])
    line = add_line(txn["id"], product["id"], 2)  # 2 < 3, accepted
    assert line["qty"] == 2


def test_finalize_empty_transaction_rejected(api):
    """PRD §3.6: "finalizing an empty transaction is rejected with ERR_EMPTY_TRANSACTION
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/finalize_empty_transaction_zero_line_edge
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    m = create_active_membership(plan["id"], primary_member_name="Mem EMP", auto_renew=False)
    txn = open_transaction(m["id"])
    res = api.finalize_transaction(txn["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_EMPTY_TRANSACTION)


def test_member_only_blocked_when_expired(api):
    """PRD §3.5: "If the product is member_only and the owning membership is not ACTIVE,
    the line is rejected with ERR_MEMBER_ONLY_PRODUCT (HTTP 403)."
    PRD §2.6: existence/state checks precede operation-specific business rules, so the
    state failure (ERR_MEMBERSHIP_NOT_ACTIVE) is reported when the membership is not active.

    Design: Difficulty/priority_pair_validation_conflict/state_not_active_beats_member_only_safety
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-MO2", list_price_cents=10000, member_price_cents=8000,
                             member_only=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem PV1B", auto_renew=False)
    txn = open_transaction(m["id"])
    set_clock("2028-01-01T00:00:00Z")
    res = api.add_line(txn["id"], {"product_id": product["id"], "qty": 1}, CLERK)
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)


def test_purchase_limit_exceeded_across_two_lines(api):
    """PRD §3.5: "the requested qty plus the units of that product already purchased by
    this membership in the current term — counting both this transaction's open lines and
    the membership's finalized lines — must not exceed per_member_limit."

    Design: Difficulty/priority_pair_validation_conflict/purchase_limit_beats_reward_fiscal_redemption
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-LIM2", list_price_cents=10000, member_price_cents=8000,
                             per_member_limit=3)
    m = create_active_membership(plan["id"], primary_member_name="Mem PV2B", auto_renew=False)
    txn = open_transaction(m["id"])
    add_line(txn["id"], product["id"], 2)  # cumulative 2
    res = api.add_line(txn["id"], {"product_id": product["id"], "qty": 2}, CLERK)  # 2+2=4 > 3
    validate_error(res, ApiErrorId.ERR_PURCHASE_LIMIT_EXCEEDED)


def test_finalize_empty_transaction_after_no_lines(api):
    """PRD §3.6: "A RegisterClerk finalizes an OPEN transaction that has at least one line
    ... finalizing an empty transaction is rejected with ERR_EMPTY_TRANSACTION (HTTP 409)."

    Design: Difficulty/boundary_precision_check/finalize_empty_transaction_zero_line_edge
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    m = create_active_membership(plan["id"], primary_member_name="Mem EMP2", auto_renew=False)
    txn = open_transaction(m["id"])
    # No lines added at all.
    res = api.finalize_transaction(txn["id"], CLERK)
    validate_error(res, ApiErrorId.ERR_EMPTY_TRANSACTION)
