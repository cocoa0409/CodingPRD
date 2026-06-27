"""Transitive cancellation cascades, the transfer-disburse repayment bubble, and
the compensating denormalized counters (open_return_count, assigned_open_returns).
"""
from test_helpers import (
    validate_success, api_client,
    create_client, create_return, create_refund_advance, create_refund_transfer,
    create_approved_advance, setup_return_in_docs_pending,
    setup_accepted_return_with_disbursed_advance_and_pending_transfer,
    TEST_USERS,
)

OM = TEST_USERS["office_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
BO = TEST_USERS["bank_officer_headers"]


# ─── Queue A: transitive_cascade / return_cancel_cascades_advance_then_transfer

def test_cancel_return_cascades_advance_then_transfer(api):
    """PRD §3.5: "Any RefundAdvance on the return whose status is REQUESTED or
    APPROVED is moved to CANCELLED; and that advance cancellation in turn moves
    the linked RefundTransfer to CANCELLED when that transfer is in
    PENDING_FUNDING."

    Design: Difficulty/transitive_cascade/return_cancel_cascades_advance_then_transfer_depth3
    """
    office = validate_success(api_client.create_office(
        {"name": "Cascade Office", "efin": "666777", "state_code": "AZ",
         "bank_product_enabled": True}, OM), 201)
    client = create_client(office["id"], full_name="Cas Cal", ssn_last4="1212", risk_band="LOW")
    ret = create_return(office["id"], client["id"], tax_year=2025, expected_refund_cents=500000)
    adv = create_approved_advance(ret["id"], 100000)
    rt = create_refund_transfer(ret["id"])

    cancelled = validate_success(api.transition_return(
        ret["id"], {"to": "CANCELLED"}, TEST_USERS["tax_preparer_headers"]), 200)
    assert cancelled["status"] == "CANCELLED"

    adv_after = validate_success(api.get_refund_advance(adv["id"], BO), 200)
    assert adv_after["status"] == "CANCELLED", "approved advance must cascade to CANCELLED"
    rt_after = validate_success(api.get_refund_transfer(rt["id"], BO), 200)
    assert rt_after["status"] == "CANCELLED", "pending transfer must cascade to CANCELLED via the advance"


# ─── Queue A: transitive_cascade / transfer_disburse_cascades_advance_repaid ─

def test_transfer_disburse_cascades_advance_to_repaid(api):
    """PRD §3.8: "when the linked RefundTransfer transitions from PENDING_FUNDING
    to DISBURSED, the waterfall's advance-repayment bucket take becomes the
    advance's repaid_cents and the advance moves from DISBURSED to REPAID."

    Design: Difficulty/transitive_cascade/transfer_disburse_cascades_advance_repaid_depth2
    """
    ctx, rt, adv = setup_accepted_return_with_disbursed_advance_and_pending_transfer(
        advance_cents=60000)
    rt_v = rt["version"]
    disbursed = validate_success(api.disburse_refund_transfer(
        rt["id"], {"disbursed_refund_cents": 500000, "expected_refundtransfer_version": rt_v}, BO), 200)
    assert disbursed["status"] == "DISBURSED"

    adv_after = validate_success(api.get_refund_advance(adv["id"], BO), 200)
    assert adv_after["status"] == "REPAID", "disbursed advance must cascade to REPAID"
    assert adv_after["repaid_cents"] == 60000, f"repaid_cents should be 60000, got {adv_after['repaid_cents']}"


def test_transfer_disburse_net_with_full_coverage(api):
    """PRD §3.7: "After all four buckets, whatever remains is
    net_to_taxpayer_cents."

    Design: Difficulty/transitive_cascade/transfer_disburse_cascades_advance_repaid_depth2
    """
    ctx, rt, adv = setup_accepted_return_with_disbursed_advance_and_pending_transfer(
        advance_cents=60000)
    rt_v = rt["version"]
    disbursed = validate_success(api.disburse_refund_transfer(
        rt["id"], {"disbursed_refund_cents": 500000, "expected_refundtransfer_version": rt_v}, BO), 200)
    # 500000 - (bank 3995 + prep 15000 + audit 0 + advance 60000) = 421005.
    assert disbursed["net_to_taxpayer_cents"] == 421005, \
        f"net should be 421005, got {disbursed['net_to_taxpayer_cents']}"


# ─── Queue A: compensating_invariant / office_open_return_count_create_then_cancel

def test_open_return_count_create_then_cancel_restores(api):
    """PRD §2.9: "Opening a return increments the office's open_return_count by
    one"
    PRD §2.9: "cancelling a return recomputes both so the cancelled return
    leaves the count (the office count falls by one, and the preparer count
    falls by one when a preparer had been assigned)."

    Design: Difficulty/compensating_invariant/office_open_return_count_create_then_cancel
    """
    office = validate_success(api_client.create_office(
        {"name": "Inv1 Office", "efin": "171717", "state_code": "KS"}, OM), 201)
    client = create_client(office["id"], full_name="In Cli", ssn_last4="2525")

    ret = create_return(office["id"], client["id"], tax_year=2025)
    after_create = validate_success(api.get_office(office["id"], OM), 200)
    assert after_create["open_return_count"] == 1, \
        f"open_return_count should be 1 after open, got {after_create['open_return_count']}"

    validate_success(api.transition_return(
        ret["id"], {"to": "CANCELLED"}, TEST_USERS["tax_preparer_headers"]), 200)
    after_cancel = validate_success(api.get_office(office["id"], OM), 200)
    assert after_cancel["open_return_count"] == 0, \
        f"open_return_count should return to 0 after cancel, got {after_cancel['open_return_count']}"


# ─── Queue A: compensating_invariant / preparer_assigned_open_returns_assign_then_cancel

def test_assigned_open_returns_assign_then_cancel_restores(api):
    """PRD §2.9: "assigning a preparer increments that preparer's
    assigned_open_returns by one"
    PRD §2.9: "cancelling a return recomputes both so the cancelled return
    leaves the count (the office count falls by one, and the preparer count
    falls by one when a preparer had been assigned)."

    Design: Difficulty/compensating_invariant/preparer_assigned_open_returns_assign_then_cancel
    """
    # Return in DOCS_PENDING already has a preparer assigned by the fixture, so
    # observe assigned_open_returns == 1, then cancel and confirm it returns to 0.
    ctx = setup_return_in_docs_pending(return_overrides={"complexity_band": "SIMPLE"})
    prep_id = ctx["preparer"]["id"]
    after_assign = validate_success(api.get_preparer(prep_id, OM), 200)
    assert after_assign["assigned_open_returns"] == 1, \
        f"assigned_open_returns should be 1 after assign, got {after_assign['assigned_open_returns']}"

    validate_success(api.transition_return(
        ctx["return"]["id"], {"to": "CANCELLED"}, ctx["prep_headers"]), 200)
    after_cancel = validate_success(api.get_preparer(prep_id, OM), 200)
    assert after_cancel["assigned_open_returns"] == 0, \
        f"assigned_open_returns should return to 0 after cancel, got {after_cancel['assigned_open_returns']}"
