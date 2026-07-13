"""Disputes: the review/needs-info cycle, settlement reversal, sale refund/deny."""
from test_helpers import (
    validate_success,
    CANONICAL,
    make_platform_admin_headers,
    assert_proceeds_identity,
    provide_info_payload, resolve_dispute_payload,
    setup_reviewed_sale_dispute, setup_reviewed_settlement_dispute,
)

ADMIN = make_platform_admin_headers()


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / dispute_cycle_review_needs_info
# ---------------------------------------------------------------------------
def test_dispute_returns_to_under_review_after_two_needs_info_cycles(api):
    """PRD §3.8: "The party that raised the dispute — a tenant or a buyer — then
    provides the requested information by supplying a `note`, moving the dispute from
    `NEEDS_INFO` back to `UNDER_REVIEW`, permitted only while it is `NEEDS_INFO`. This
    review-and-information cycle between `UNDER_REVIEW` and `NEEDS_INFO` may repeat any
    number of rounds."

    Design: Difficulty/non_linear_state_machine/dispute_cycle_review_needs_info
    """
    ctx = setup_reviewed_sale_dispute(api)  # dispute UNDER_REVIEW, raised by the buyer
    did = ctx["dispute_id"]
    validate_success(api.request_info_dispute(did, ADMIN))  # -> NEEDS_INFO
    validate_success(api.provide_info_dispute(did, provide_info_payload("round 1"), ctx["buyer_hdr"]))
    validate_success(api.request_info_dispute(did, ADMIN))  # -> NEEDS_INFO
    dispute = validate_success(api.provide_info_dispute(did, provide_info_payload("round 2"), ctx["buyer_hdr"]))
    assert dispute["status"] == "UNDER_REVIEW"


def test_dispute_first_provide_info_reenters_under_review(api):
    """PRD §3.8: "From `UNDER_REVIEW` the admin may request more information, moving
    the dispute to `NEEDS_INFO`, permitted only while it is `UNDER_REVIEW`. The party
    that raised the dispute — a tenant or a buyer — then provides the requested
    information by supplying a `note`, moving the dispute from `NEEDS_INFO` back to
    `UNDER_REVIEW`, permitted only while it is `NEEDS_INFO`."

    Design: Difficulty/non_linear_state_machine/dispute_cycle_review_needs_info
    """
    ctx = setup_reviewed_sale_dispute(api)
    did = ctx["dispute_id"]
    needs_info = validate_success(api.request_info_dispute(did, ADMIN))
    assert needs_info["status"] == "NEEDS_INFO"
    back = validate_success(api.provide_info_dispute(did, provide_info_payload("info"), ctx["buyer_hdr"]))
    assert back["status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / proceeds_identity_settlement_reverse
# ---------------------------------------------------------------------------
def test_upholding_settlement_dispute_reverses_and_debits_tenant_surplus(api):
    """PRD §3.8: "When the subject is a settlement, that settlement moves from
    `FINALIZED` to `REVERSED`: the tenant's `surplus_balance_cents` is reduced by the
    settlement's `surplus_cents`, and the facility's `recovery_balance_cents` is
    reduced by the sum of `lien_recovered_cents`, `facility_fee_cents`, and
    `buyer_premium_cents` — exactly reversing the credits made at finalization, and
    leaving the proceeds identity intact on the reversed record, where
    `gross_proceeds_cents` still equals `lien_recovered_cents` plus `facility_fee_cents`
    plus `surplus_cents`."

    Design: Difficulty/compensating_invariant/proceeds_identity_settlement_reverse
    """
    ctx = setup_reviewed_settlement_dispute(api)
    tenant_before = validate_success(api.get_tenant(ctx["ten"], ADMIN))
    assert tenant_before["surplus_balance_cents"] == CANONICAL["final_surplus_cents"]  # 41000
    validate_success(api.resolve_dispute(ctx["dispute_id"], resolve_dispute_payload("UPHOLD"), ADMIN))
    settlement = validate_success(api.get_settlement(ctx["settlement_id"], ADMIN))
    assert settlement["status"] == "REVERSED"
    tenant_after = validate_success(api.get_tenant(ctx["ten"], ADMIN))
    assert tenant_after["surplus_balance_cents"] == 0


def test_reversed_settlement_preserves_proceeds_identity(api):
    """PRD §3.8: "leaving the proceeds identity intact on the reversed record, where
    `gross_proceeds_cents` still equals `lien_recovered_cents` plus `facility_fee_cents`
    plus `surplus_cents`."

    Design: Difficulty/compensating_invariant/proceeds_identity_settlement_reverse
    """
    ctx = setup_reviewed_settlement_dispute(api)
    validate_success(api.resolve_dispute(ctx["dispute_id"], resolve_dispute_payload("UPHOLD"), ADMIN))
    settlement = validate_success(api.get_settlement(ctx["settlement_id"], ADMIN))
    assert settlement["gross_proceeds_cents"] == CANONICAL["winning_amount_cents"]  # 150000
    assert_proceeds_identity(settlement)


# ---------------------------------------------------------------------------
# Corner: dispute resolution outcomes
# ---------------------------------------------------------------------------
def test_denying_sale_dispute_sets_denied_without_refund(api):
    """PRD §3.8: "a decision to deny sets `resolution` to `DENIED` and moves the
    dispute to `DENIED`."
    PRD §3.8: "A denied dispute performs no financial cascade."

    Design: Corner/state_machines/dispute_resolve_deny_sets_denied_no_side_effects
    """
    ctx = setup_reviewed_sale_dispute(api)  # SALE dispute UNDER_REVIEW against a PAID sale
    dispute = validate_success(api.resolve_dispute(ctx["dispute_id"], resolve_dispute_payload("DENY"), ADMIN))
    assert dispute["status"] == "DENIED"
    assert dispute["resolution"] == "DENIED"
    sale = validate_success(api.get_sale(ctx["sale_id"], ADMIN))
    assert sale["payment_status"] == "PAID"  # unchanged; no refund


def test_upholding_sale_dispute_refunds_payment(api):
    """PRD §3.8: "When the subject is a sale, the sale's `payment_status` moves from
    `PAID` to `REFUNDED`."

    Design: Corner/state_machines/dispute_uphold_sale_refunds_payment
    """
    ctx = setup_reviewed_sale_dispute(api)
    dispute = validate_success(api.resolve_dispute(ctx["dispute_id"], resolve_dispute_payload("UPHOLD"), ADMIN))
    assert dispute["status"] == "UPHELD"
    sale = validate_success(api.get_sale(ctx["sale_id"], ADMIN))
    assert sale["payment_status"] == "REFUNDED"
