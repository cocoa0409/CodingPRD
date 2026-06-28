"""Validation precedence (state-before-fiscal, existence-before-capacity) and
boundary precision (allocation pool >= boundary, empty-buylist count==0 edge).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_customer, create_open_event, create_registration,
    create_release_product, create_requested_pre_order, create_allocated_pre_order,
    create_pre_order_payload, set_clock,
    create_buylist_submission_payload,
    ApiErrorId, TEST_USERS, make_customer_headers, MISSING_UUID,
)

SM = TEST_USERS["store_manager_headers"]


# ─── priority_pair_validation_conflict (difficulty) ─────────────────────────────
def test_pay_on_withdrawn_returns_state_not_fiscal(api):
    """PRD §3.4: "Paying a registration is a customer action that moves
    `payment_status` from `UNPAID` to `PAID`. It is rejected if the registration's
    check-in status is already `WITHDRAWN` (`ERR_INVALID_STATE`), and the customer's
    `store_credit_balance_cents` must be at least the registration's
    `quoted_fee_cents`, otherwise it fails with `ERR_INSUFFICIENT_STORE_CREDIT`."
    PRD §2.9: "authentication, then authorization, then existence, then state
    (including the banned check for check-in), then request well-formedness, then
    quantity and grade bounds, then the domain-specific business constraints."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Broke Cust", "broke@x.com")  # 0 store credit
    ev = create_open_event(title="Conflict Event", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=8,
                           entry_fee_cents=2000)
    reg = create_registration(ev, cust)
    cust_h = make_customer_headers(cust["id"])
    validate_success(api.withdraw_registration(reg["id"], cust_h), 200)
    # WITHDRAWN + 0 credit: state precedes the fiscal check
    res = api.pay_registration(reg["id"], cust_h)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_register_nonexistent_customer_returns_not_found_before_capacity(api):
    """PRD §2.4: "the system validates the identifiers left to right and rejects the
    request with `ERR_NOT_FOUND` (HTTP 404) ... Foreign-key references supplied in a
    request body are validated the same way: every referenced resource must exist,
    or the request fails with `ERR_NOT_FOUND`."
    PRD §2.9: "then existence, then state ... then the domain-specific business
    constraints."

    Design: Difficulty/priority_pair_validation_conflict/capacity_beats_quantity_validation
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Seat Taker", "seat@x.com")
    ev = create_open_event(title="Tiny Event", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=1,
                           entry_fee_cents=1000)
    create_registration(ev, cust)  # fills the single seat
    # A register call naming a non-existent customer: existence beats capacity.
    res = api.create_registration(
        {"event_id": ev["id"], "customer_id": MISSING_UUID},
        make_customer_headers(MISSING_UUID))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


# ─── boundary_precision_check (difficulty) ──────────────────────────────────────
def test_allocation_at_pool_boundary_rejected(api):
    """PRD §3.3: "Allocation must not push the release's `quantity_allocated` plus
    this pre-order's `requested_quantity` past the `allocation_pool`; exceeding it
    fails with `ERR_ALLOCATION_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/allocation_exact_pool_boundary
    """
    ca = create_customer("Alloc A", "aa@x.com", credit_cents=5000)
    cb = create_customer("Alloc B", "ab@x.com", credit_cents=5000)
    rp = create_release_product(title="Scarce Box", allocation_pool=5,
                                unit_price_cents=1000, deposit_required_cents=500)
    # First allocation of qty 3 succeeds (0+3<=5), advancing quantity_allocated to 3.
    po_a, rp_after = create_allocated_pre_order(ca, rp, requested_quantity=3,
                                                deposit_paid_cents=500)
    assert rp_after["quantity_allocated"] == 3
    # Second pre-order qty 3: 3+3=6 > 5 → rejected.
    po_b = create_requested_pre_order(cb, rp, requested_quantity=3, deposit_paid_cents=500)
    res = api.allocate_pre_order(
        po_b["id"], {"expected_release_product_version": rp_after["version"]}, SM)
    validate_error(res, ApiErrorId.ERR_ALLOCATION_EXCEEDED)
    rp_final = validate_success(api.get_release_product(rp["id"], SM), 200)
    assert rp_final["quantity_allocated"] == 3


def test_submit_empty_buylist_rejected(api):
    """PRD §3.2: "Submitting the draft moves it from `DRAFT` to `SUBMITTED`, but only
    if at least one line exists — an empty submission is rejected with
    `ERR_EMPTY_BUYLIST`"

    Design: Difficulty/boundary_precision_check/empty_buylist_zero_lines_boundary
    """
    cust = create_customer("Empty Seller", "empty@x.com")
    cust_h = make_customer_headers(cust["id"])
    sub = get_success_data(api.create_buylist_submission(
        create_buylist_submission_payload(cust["id"], "CASH"), cust_h))
    res = api.submit_buylist(sub["id"], cust_h)
    validate_error(res, ApiErrorId.ERR_EMPTY_BUYLIST)
