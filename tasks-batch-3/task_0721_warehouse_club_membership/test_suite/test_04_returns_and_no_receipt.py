"""Returns: no-receipt lookup window (difficulty) plus corner-queue return claims."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_basic_plan, create_product,
    create_active_membership, set_clock,
    create_finalized_transaction, create_receipted_return,
    create_no_receipt_return, approve_return, ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["club_admin_headers"]
CLERK = TEST_USERS["register_clerk_headers"]
SVC = TEST_USERS["service_desk_headers"]


def test_no_receipt_lookup_denied_past_window(api):
    """PRD §3.7: "measuring whole days as the floor of the elapsed time between the current
    clock instant and the transaction's finalized_at_utc, that age must be at most 90 days
    (inclusive)."
    PRD §3.7: "If no transaction qualifies within the 90-day window, the lookup_mode is
    DENIED and creation is rejected with ERR_NO_RECEIPT_LOOKUP_DENIED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/no_receipt_lookup_window_inclusive_boundary
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-NRW", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="Mem NRW", auto_renew=False)
    create_finalized_transaction(m["id"], product["id"], 1)  # finalized at 2026-03-01
    set_clock("2026-06-15T00:00:00Z")  # > 90 days later

    res = api.create_return({"membership_id": m["id"], "product_id": product["id"], "qty": 1}, SVC)
    validate_error(res, ApiErrorId.ERR_NO_RECEIPT_LOOKUP_DENIED)


def test_no_receipt_lookup_allowed_within_window(api):
    """PRD §3.7: "The return is allowed only when the membership has at least one FINALIZED
    transaction containing the product whose finalization is recent enough ... that age must
    be at most 90 days (inclusive). Among the qualifying transactions, the most recent one
    ... sets the return's lookup_mode to NO_RECEIPT_LOOKUP."

    Design: Difficulty/resource_temporal_overlap/no_receipt_lookup_window_inclusive_boundary
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-NRW2", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="Mem NRW2", auto_renew=False)
    create_finalized_transaction(m["id"], product["id"], 1)
    set_clock("2026-04-01T00:00:00Z")  # 31 days, within window

    res = api.create_return({"membership_id": m["id"], "product_id": product["id"], "qty": 1}, SVC)
    data = validate_success(res, 201)
    assert data["lookup_mode"] == "NO_RECEIPT_LOOKUP"


# --------------------------------------------------------------------------
# Corner queue
# --------------------------------------------------------------------------
def test_reject_pending_return_zero_refund(api):
    """PRD §3.7: "Rejecting a return sets its refund_cents and reward_reversal_cents to 0,
    writes no ledger entries, and moves it to REJECTED."

    Design: Corner/state_machines/reject_pending_return_zero_refund
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-REJ", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="Rej Mem", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 1)
    ret = create_receipted_return(m["id"], txn["id"], product["id"], 1)
    res = api.reject_return(ret["id"], SVC)
    data = validate_success(res, 200)
    assert data["status"] == "REJECTED"
    assert data["refund_cents"] == 0


def test_approve_already_approved_return_rejected(api):
    """PRD §3.7: "A return is resolved by a ServiceDeskClerk who approves or rejects it
    while it is PENDING; acting on a non-PENDING return is rejected with
    ERR_RETURN_NOT_PENDING."

    Design: Corner/state_machines/approve_already_approved_return_rejected
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-APPR2", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="Appr2 Mem", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 1)
    ret = create_receipted_return(m["id"], txn["id"], product["id"], 1)
    approve_return(ret["id"])
    res = api.approve_return(ret["id"], SVC)
    validate_error(res, ApiErrorId.ERR_RETURN_NOT_PENDING)


def test_no_receipt_refund_uses_current_member_price(api):
    """PRD §3.7: "A no-receipt approval instead refunds at the current member price — the
    product's member_price_cents times qty, reflecting the lowest-price policy — and claws
    back no reward, so its reward_reversal_cents is 0."

    Design: Corner/calculations/no_receipt_refund_uses_current_member_price
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-NRREF", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="NRRef Mem", auto_renew=False)
    create_finalized_transaction(m["id"], product["id"], 1)
    set_clock("2026-04-01T00:00:00Z")
    ret = create_no_receipt_return(m["id"], product["id"], 1)
    approved = approve_return(ret["id"])
    assert approved["lookup_mode"] == "NO_RECEIPT_LOOKUP"
    assert approved["refund_cents"] == 8000  # member_price * qty
    assert approved["reward_reversal_cents"] == 0


def test_receipted_return_qty_exceeds_purchased_at_create(api):
    """PRD §3.7: "When transaction_id is provided, the return is receipted; the original
    line's already-returned units plus the requested qty must not exceed the original
    line's purchased qty, or creation is rejected with ERR_RETURN_QTY_EXCEEDS_PURCHASED
    (HTTP 409)."

    Design: Corner/validations/receipted_return_qty_exceeds_purchased_at_create
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-RQEX", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="RQEx Mem", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 2)
    res = api.create_return({"membership_id": m["id"], "product_id": product["id"],
                             "qty": 3, "transaction_id": txn["id"]}, SVC)
    validate_error(res, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_PURCHASED)
