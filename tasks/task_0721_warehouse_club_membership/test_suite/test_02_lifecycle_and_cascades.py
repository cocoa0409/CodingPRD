"""Difficulty-queue state-machine, cascade and cross-entity-dependency tests."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_basic_plan, create_executive_plan, create_product,
    create_active_membership, create_pending_membership, activate_membership,
    get_membership, get_membership_version, set_clock,
    open_transaction, add_line, finalize_transaction,
    create_finalized_transaction, create_receipted_return,
    find_fee_event, ApiErrorId,
    TEST_USERS, make_member_headers,
)
from test_helpers import api_client as _api

ADMIN = TEST_USERS["club_admin_headers"]
CLERK = TEST_USERS["register_clerk_headers"]
SVC = TEST_USERS["service_desk_headers"]


def test_membership_cyclic_lapse_then_reinstate(api):
    """PRD §3.3: "If auto_renew is false, the membership lapses: it moves from ACTIVE to
    EXPIRED ..."
    PRD §3.2: "A SUCCEEDED payment with purpose RENEWAL against an EXPIRED membership
    reinstates it: the membership returns from EXPIRED to ACTIVE ..."

    Design: Difficulty/non_linear_state_machine/membership_cyclic_renew_reinstate_loop
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    m = create_active_membership(plan["id"], primary_member_name="Mem Cyc", auto_renew=False)
    set_clock("2027-04-01T00:00:00Z")  # past term_end with auto_renew false -> EXPIRED
    assert get_membership(m["id"])["status"] == "EXPIRED"

    res = api.create_payment({"membership_id": m["id"], "purpose": "RENEWAL",
                              "outcome": "SUCCEEDED"}, make_member_headers(m["id"]))
    validate_success(res, 201)
    assert get_membership(m["id"])["status"] == "ACTIVE"


def test_renew_self_loop_keeps_active(api):
    """PRD §3.3: "renews an ACTIVE membership, which is a cyclic transition that keeps the
    membership ACTIVE while rolling its term and resetting the per-term reward cap."

    Design: Difficulty/non_linear_state_machine/membership_cyclic_renew_reinstate_loop
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    m = create_active_membership(plan["id"], primary_member_name="Mem Loop", auto_renew=False)
    ver = get_membership_version(m["id"])
    res = api.renew_membership(m["id"], {"expected_membership_version": ver},
                               make_member_headers(m["id"]))
    data = validate_success(res, 200)
    assert data["status"] == "ACTIVE"
    assert data["version"] == ver + 1


def test_transaction_finalize_creates_accrual(api):
    """PRD §3.6: "The accrued amount is recorded on the transaction's reward_accrued_cents,
    added to the membership's reward_accrued_cents, and written as a RewardLedgerEntry of
    type ACCRUAL with the positive accrued amount, the source_transaction_id set to this
    transaction ..."

    Design: Difficulty/non_linear_state_machine/transaction_branching_finalize_vs_void
    """
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-BR", list_price_cents=10000, member_price_cents=8000,
                             reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem Br", auto_renew=False)
    txn = open_transaction(m["id"])
    add_line(txn["id"], product["id"], 5)
    txn = finalize_transaction(txn["id"])
    assert txn["status"] == "FINALIZED"

    ledger = api.list_reward_ledger(make_member_headers(m["id"]),
                                    params={"source_transaction_id": txn["id"]}).json()["data"]
    accruals = [e for e in ledger if e["entry_type"] == "ACCRUAL"]
    assert len(accruals) == 1
    assert accruals[0]["amount_cents"] == 800


def test_transaction_void_creates_no_ledger(api):
    """PRD §3.6: "A void writes no ledger entries because the transaction was never
    finalized, and its lines remain for audit."

    Design: Difficulty/non_linear_state_machine/transaction_branching_finalize_vs_void
    """
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-BR2", list_price_cents=10000, member_price_cents=8000,
                             reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem Br2", auto_renew=False)
    txn = open_transaction(m["id"])
    add_line(txn["id"], product["id"], 5)
    res = api.void_transaction(txn["id"], CLERK)
    data = validate_success(res, 200)
    assert data["status"] == "VOIDED"

    ledger = api.list_reward_ledger(make_member_headers(m["id"]),
                                    params={"source_transaction_id": txn["id"]}).json()["data"]
    assert len(ledger) == 0


def test_cancel_cascade_revokes_card_and_fees(api):
    """PRD §3.3: "On success the system computes the prorated cancel refund (see §3.7),
    records a FeeEvent of kind CANCEL_REFUND carrying the negative of that refund against
    the current term, writes a RewardLedgerEntry of type EXPIRY zeroing unredeemed reward,
    cascades every ACTIVE household card to REVOKED ..."

    Design: Difficulty/transitive_cascade/cancel_cascade_depth3_fee_ledger_cards
    """
    set_clock("2026-03-01T00:00:00Z")
    # Executive plan + reward-bearing finalized transaction so there is unredeemed
    # reward for cancel's EXPIRY entry to zero. PRD §2.8 ("a REVERSAL, REDEMPTION,
    # and EXPIRY are negative") means a faithful impl writes an EXPIRY entry only when
    # unredeemed reward > 0; on a basic/no-reward membership none would be written.
    # annual_fee 6000 with zero redeemed reward keeps the CANCEL_REFUND at -6000.
    plan = create_executive_plan(annual_fee_cents=6000, reward_rate_bps=200,
                                 reward_cap_cents=100000, max_household_cards=1)
    product = create_product("P-CASC", member_price_cents=8000, reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem Casc", auto_renew=False)
    create_finalized_transaction(m["id"], product["id"], 5)  # accrues unredeemed reward
    card = get_success_data(api.create_household_card(
        {"membership_id": m["id"], "cardholder_name": "Spouse", "card_kind": "INCLUDED"},
        make_member_headers(m["id"])))
    ver = get_membership_version(m["id"])

    res = api.cancel_membership(m["id"], {"expected_membership_version": ver},
                               make_member_headers(m["id"]))
    data = validate_success(res, 200)
    assert data["status"] == "CANCELLED"
    assert get_success_data(api.get_household_card(card["id"],
                            make_member_headers(m["id"])))["status"] == "REVOKED"
    fe = find_fee_event(m["id"], "CANCEL_REFUND")
    assert fe["amount_cents"] == -6000
    ledger = api.list_reward_ledger(make_member_headers(m["id"]),
                                    params={"membership_id": m["id"], "entry_type": "EXPIRY"}).json()["data"]
    assert len([e for e in ledger if e["entry_type"] == "EXPIRY"]) >= 1


def test_return_approve_cascade_reversal_qty_membership(api):
    """PRD §3.7: "The reversal is subtracted from the membership's reward_accrued_cents, a
    RewardLedgerEntry of type REVERSAL carrying the negative reversal is written when the
    reversal is positive, the original line's returned_qty is incremented by the returned
    units, and the membership's reward_accrued_cents is recomputed."

    Design: Difficulty/transitive_cascade/return_approve_cascade_depth3_reversal_qty_membership
    """
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-RET", list_price_cents=10000, member_price_cents=8000,
                             reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem Ret", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 5)  # accrued 800
    ret = create_receipted_return(m["id"], txn["id"], product["id"], 2)
    ret = approve_return_inline(api, ret["id"])

    assert ret["status"] == "APPROVED"
    assert ret["reward_reversal_cents"] == 320  # floor(800*2/5)
    lines = api.list_lines(txn["id"], CLERK).json()["data"]
    target = next(l for l in lines if l["id"] == line["id"])
    assert target["returned_qty"] == 2
    assert get_membership(m["id"])["reward_accrued_cents"] == 480  # 800-320


def approve_return_inline(api, return_id):
    return validate_success(api.approve_return(return_id, SVC), 200)


def test_line_add_requires_membership_active(api):
    """PRD §3.5: "Adding a line is permitted only while the transaction is OPEN (otherwise
    ERR_TRANSACTION_NOT_OPEN) and only while the owning membership is ACTIVE (otherwise
    ERR_MEMBERSHIP_NOT_ACTIVE)."

    Design: Difficulty/cross_entity_state_dependency/line_add_requires_membership_active
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-CE1", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="Mem CE1", auto_renew=False)
    txn = open_transaction(m["id"])
    set_clock("2027-04-01T00:00:00Z")  # membership lapses to EXPIRED

    res = api.add_line(txn["id"], {"product_id": product["id"], "qty": 1}, CLERK)
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)


def test_receipted_return_qty_exceeds_purchased(api):
    """PRD §3.7: "for a receipted return additionally requires that the original
    transaction be FINALIZED and that the line's returned-so-far units plus the return qty
    not exceed the line's qty (again ERR_RETURN_QTY_EXCEEDS_PURCHASED)."

    Design: Difficulty/cross_entity_state_dependency/receipted_return_requires_finalized_transaction
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-CE2", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="Mem CE2", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 2)
    # The recipe allows the qty>purchased to surface either at create or approve. Create
    # with qty 3 (> line qty 2); approval is the trigger but creation may also reject.
    res = api.create_return({"membership_id": m["id"], "product_id": product["id"],
                             "qty": 3, "transaction_id": txn["id"]}, SVC)
    if res.status_code < 400:
        ret = res.json()["data"]
        res = api.approve_return(ret["id"], SVC)
    validate_error(res, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_PURCHASED)


def test_cancel_cascade_zeroes_reward_accrued(api):
    """PRD §3.3: "writes a RewardLedgerEntry of type EXPIRY zeroing unredeemed reward,
    cascades every ACTIVE household card to REVOKED, recomputes fees_paid_cents and
    reward_accrued_cents, and increments the membership version by one."

    Design: Difficulty/transitive_cascade/cancel_cascade_depth3_fee_ledger_cards
    """
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-CASC2", list_price_cents=10000, member_price_cents=8000,
                             reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem Casc2", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 5)  # accrued 800
    assert get_membership(m["id"])["reward_accrued_cents"] == 800
    ver = get_membership_version(m["id"])
    res = api.cancel_membership(m["id"], {"expected_membership_version": ver},
                               make_member_headers(m["id"]))
    validate_success(res, 200)
    assert get_membership(m["id"])["reward_accrued_cents"] == 0


def test_return_approve_writes_reversal_ledger_entry(api):
    """PRD §3.7: "a RewardLedgerEntry of type REVERSAL carrying the negative reversal is
    written when the reversal is positive."

    Design: Difficulty/transitive_cascade/return_approve_cascade_depth3_reversal_qty_membership
    """
    plan = create_executive_plan(annual_fee_cents=12000, reward_rate_bps=200,
                                 reward_cap_cents=100000, addon_fee_cents=6000)
    product = create_product("P-RET2", list_price_cents=10000, member_price_cents=8000,
                             reward_eligible=True)
    m = create_active_membership(plan["id"], primary_member_name="Mem Ret2", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 5)
    ret = create_receipted_return(m["id"], txn["id"], product["id"], 2)
    validate_success(api.approve_return(ret["id"], SVC), 200)
    ledger = api.list_reward_ledger(make_member_headers(m["id"]),
                                    params={"membership_id": m["id"], "entry_type": "REVERSAL"}).json()["data"]
    reversals = [e for e in ledger if e["entry_type"] == "REVERSAL"]
    assert len(reversals) == 1
    assert reversals[0]["amount_cents"] == -320


def test_line_add_on_expired_membership_member_not_active(api):
    """PRD §3.5: "only while the owning membership is ACTIVE (otherwise
    ERR_MEMBERSHIP_NOT_ACTIVE)."

    Design: Difficulty/cross_entity_state_dependency/line_add_requires_membership_active
    """
    set_clock("2026-03-01T00:00:00Z")
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-CE1B", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="Mem CE1B", auto_renew=False)
    txn = open_transaction(m["id"])
    set_clock("2028-01-01T00:00:00Z")
    res = api.add_line(txn["id"], {"product_id": product["id"], "qty": 2}, CLERK)
    validate_error(res, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)


def test_receipted_return_within_purchased_qty_approves(api):
    """PRD §3.7: "for a receipted return additionally requires that the original
    transaction be FINALIZED and that the line's returned-so-far units plus the return qty
    not exceed the line's qty."

    Design: Difficulty/cross_entity_state_dependency/receipted_return_requires_finalized_transaction
    """
    plan = create_basic_plan(annual_fee_cents=6000)
    product = create_product("P-CE2B", list_price_cents=10000, member_price_cents=8000)
    m = create_active_membership(plan["id"], primary_member_name="Mem CE2B", auto_renew=False)
    txn, line = create_finalized_transaction(m["id"], product["id"], 2)
    ret = create_receipted_return(m["id"], txn["id"], product["id"], 2)  # exactly the purchased qty
    approved = validate_success(api.approve_return(ret["id"], SVC), 200)
    assert approved["status"] == "APPROVED"
