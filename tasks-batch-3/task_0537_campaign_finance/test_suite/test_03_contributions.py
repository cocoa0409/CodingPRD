"""Contribution settlement/review dimensions, cascades, conservation, and body validation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_contribution_payload,
    TEST_USERS, make_treasurer_headers,
    set_clock, create_active_committee, add_contribution, get_committee,
)

REGULATOR = TEST_USERS["regulator_headers"]


# --------------------------------------------------------------------------- #
# Parallel settlement x review dimensions
# --------------------------------------------------------------------------- #
def test_flag_touches_only_review_dimension(api):
    """PRD §3.3: "Neither flag nor clear touches the settlement dimension, but each is a
    committee-affecting mutation and increments the committee's version."

    Design: Difficulty/non_linear_state_machine/contribution_parallel_dimensions
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    committee = create_active_committee(api, name="Delta")
    con = add_contribution(api, committee["id"], amount_cents=50000)
    flagged = validate_success(api.flag_contribution(con["id"], REGULATOR))
    assert flagged["settlement_status"] == "RECORDED", "flag must not change settlement"
    assert flagged["review_status"] == "FLAGGED"


def test_deposit_touches_only_settlement_dimension(api):
    """PRD §3.3: "A deposit leaves the committee's total_receipts_cents unchanged ... On the
    review side, an agency auditor flags an unreviewed contribution ... Neither flag nor
    clear touches the settlement dimension." (the settlement transition leaves review as-is)

    Design: Difficulty/non_linear_state_machine/contribution_parallel_dimensions
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    committee = create_active_committee(api, name="Delta2")
    cid = committee["id"]
    con = add_contribution(api, cid, amount_cents=50000)
    validate_success(api.flag_contribution(con["id"], REGULATOR))
    deposited = validate_success(api.deposit_contribution(con["id"], make_treasurer_headers(cid)))
    assert deposited["settlement_status"] == "DEPOSITED"
    assert deposited["review_status"] == "FLAGGED", "deposit must not change the review dimension"


# --------------------------------------------------------------------------- #
# Settlement invalid transitions
# --------------------------------------------------------------------------- #
def test_deposit_already_deposited_contribution_rejected(api):
    """PRD §3.3: "the owning treasurer deposits a recorded contribution, moving
    settlement_status from RECORDED to DEPOSITED; this requires the contribution to be
    RECORDED and is otherwise rejected with ERR_CONTRIBUTION_NOT_RECORDED."

    Design: Corner/state_machines/contribution_deposit_twice_rejected
    """
    committee = create_active_committee(api, name="Ups", committee_type="PAC")
    cid = committee["id"]
    con = add_contribution(api, cid, amount_cents=5000)
    validate_success(api.deposit_contribution(con["id"], make_treasurer_headers(cid)))
    validate_error(api.deposit_contribution(con["id"], make_treasurer_headers(cid)),
                   ApiErrorId.ERR_CONTRIBUTION_NOT_RECORDED.value)


def test_clear_unreviewed_contribution_rejected(api):
    """PRD §3.3: "Flagging requires the review status to be UNREVIEWED and clearing requires
    it to be FLAGGED; a request that does not meet its precondition is rejected with
    ERR_CONTRIBUTION_REVIEW_INVALID."

    Design: Corner/state_machines/contribution_clear_without_flag_rejected
    """
    committee = create_active_committee(api, name="Phi", committee_type="PAC")
    con = add_contribution(api, committee["id"], amount_cents=5000)
    validate_error(api.clear_contribution(con["id"], REGULATOR),
                   ApiErrorId.ERR_CONTRIBUTION_REVIEW_INVALID.value)


# --------------------------------------------------------------------------- #
# Void cascade to receipts / cash-on-hand / solvency
# --------------------------------------------------------------------------- #
def test_void_contribution_recomputes_receipts(api):
    """PRD §3.3: "A void, like a refund, drops the contribution from receipts and cascades
    the same way: receipts recomputed downward, then cash on hand, then solvency, then a
    version increment on the committee."

    Design: Difficulty/transitive_cascade/void_contribution_receipts_cascade
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    committee = create_active_committee(api, name="Eta")
    cid = committee["id"]
    add_contribution(api, cid, contributor_ref="r1", amount_cents=300000)
    con_b = add_contribution(api, cid, contributor_ref="r2", amount_cents=100000)
    validate_success(api.void_contribution(con_b["id"], REGULATOR))
    after = get_committee(api, cid)
    assert after["total_receipts_cents"] == 300000, "voided 100000 must be excluded from receipts"


def test_void_contribution_cascades_to_cash_and_solvency(api):
    """PRD §2.9: "When a contribution is refunded or voided, receipts are recomputed
    downward, then cash on hand is recomputed from the new receipts, then solvency is
    recomputed from the new cash on hand."

    Design: Difficulty/transitive_cascade/void_contribution_receipts_cascade
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    committee = create_active_committee(api, name="Eta2")
    cid = committee["id"]
    add_contribution(api, cid, contributor_ref="r1", amount_cents=300000)
    con_b = add_contribution(api, cid, contributor_ref="r2", amount_cents=100000)
    validate_success(api.void_contribution(con_b["id"], REGULATOR))
    after = get_committee(api, cid)
    assert after["cash_on_hand_cents"] == 300000, "cash on hand recomputed from new receipts"
    assert after["solvency_status"] == "SOLVENT", "solvency recomputed from new cash on hand"


# --------------------------------------------------------------------------- #
# Conservation: create + void returns receipts to pre-create value
# --------------------------------------------------------------------------- #
def test_receipts_after_create_reflects_contribution(api):
    """PRD §2.9: "total_receipts_cents is the sum of amount_cents over the committee's
    contributions whose settlement_status is either RECORDED or DEPOSITED ... it is
    recomputed on every contribution mutation."

    Design: Difficulty/compensating_invariant/contribution_create_void_conserves_receipts
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    committee = create_active_committee(api, name="Mu")
    cid = committee["id"]
    assert get_committee(api, cid)["total_receipts_cents"] == 0
    add_contribution(api, cid, amount_cents=50000)
    assert get_committee(api, cid)["total_receipts_cents"] == 50000


def test_receipts_conserved_after_create_then_void(api):
    """PRD §2.9: "total_receipts_cents is the sum of amount_cents over the committee's
    contributions whose settlement_status is either RECORDED or DEPOSITED (refunded and
    voided contributions are excluded)."

    Design: Difficulty/compensating_invariant/contribution_create_void_conserves_receipts
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    committee = create_active_committee(api, name="Mu2")
    cid = committee["id"]
    before = get_committee(api, cid)["total_receipts_cents"]
    con = add_contribution(api, cid, amount_cents=50000)
    validate_success(api.void_contribution(con["id"], REGULATOR))
    after = get_committee(api, cid)["total_receipts_cents"]
    assert before == 0 and after == 0, "voided contribution must restore receipts to the pre-create value"


# --------------------------------------------------------------------------- #
# Body / ownership validation
# --------------------------------------------------------------------------- #
def test_contribution_zero_amount_rejected(api):
    """PRD §3.2: "The amount must be strictly positive; a zero or negative amount_cents is
    rejected with ERR_INVALID_AMOUNT."

    Design: Corner/validations/contribution_amount_zero_returns_invalid_amount
    """
    committee = create_active_committee(api, name="ZeroCo", committee_type="PAC")
    resp = api.create_contribution(
        committee["id"], create_contribution_payload(amount_cents=0), make_treasurer_headers(committee["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value)


def test_contribution_by_non_owner_treasurer_forbidden(api):
    """PRD §2.1: "an authenticated principal of the correct role who is nevertheless not the
    owner of the target resource is rejected with ERR_FORBIDDEN_OWNER (HTTP 403)."

    Design: Corner/validations/ownership_wrong_treasurer_forbidden
    """
    committee_a = create_active_committee(api, name="OwnerA", committee_type="PAC")
    committee_b = create_active_committee(api, name="OwnerB", committee_type="PAC")
    # acting Treasurer identity is committee B, but the target committee is A
    resp = api.create_contribution(
        committee_a["id"], create_contribution_payload(amount_cents=5000), make_treasurer_headers(committee_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNER.value)
