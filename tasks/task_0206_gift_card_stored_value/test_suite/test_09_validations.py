"""Validation rules: auth, fiscal floor/cap, sufficiency, refund/redemption ceiling,
corporate buyer gate, jurisdiction and temporal gates, risk-review gate.

Queue B (Corner) section validations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_program, create_active_card, setup_program_and_active_card,
    setup_card_for_dormancy, setup_quoted_bulk_order, setup_flagged_card,
    draft_redemption, settle_redemption,
    create_program_payload, reload_card_payload,
    make_b2b_buyer_headers,
    TEST_USERS,
)

_STORE = TEST_USERS["store_associate_headers"]
_ADMIN = TEST_USERS["program_admin_headers"]
_FRAUD = TEST_USERS["fraud_analyst_headers"]


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing the role header, or carrying a role string that is not one
    of the recognized roles, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/validations/missing_role_header_returns_unauthenticated
    """
    res = api.create_program(create_program_payload(name="Acme"), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_reload_below_min_rejected(api):
    """PRD §3.3: "The amount must meet the reload_min_cents floor (else ERR_RELOAD_BELOW_MIN)."

    Design: Corner/validations/reload_below_min_rejected
    """
    program, card = setup_program_and_active_card(settled_cents=2000)
    res = api.reload_card(card["id"], reload_card_payload(100), _STORE)
    validate_error(res, "ERR_RELOAD_BELOW_MIN", expected_status=409)


def test_reload_over_balance_cap_rejected(api):
    """PRD §3.3: "the resulting settled_balance_cents must not exceed reload_max_balance_cents
    (else ERR_BALANCE_CAP_EXCEEDED)."

    Design: Corner/validations/reload_over_cap_rejected
    """
    program, card = setup_program_and_active_card(
        settled_cents=98000, reload_max_balance_cents=100000)
    res = api.reload_card(card["id"], reload_card_payload(5000), _STORE)
    validate_error(res, "ERR_BALANCE_CAP_EXCEEDED", expected_status=409)


def test_insufficient_balance_redemption_rejected(api):
    """PRD §3.5: "If, after walking every card, the remaining amount is still above zero, the
    settlement is rejected with ERR_INSUFFICIENT_BALANCE and no leg and no debit are
    persisted."

    Design: Corner/validations/insufficient_balance_redemption_rejected
    """
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    a = create_active_card(program["id"], 3000)
    b = create_active_card(program["id"], 1500)
    c = create_active_card(program["id"], 4000)
    redemption = draft_redemption(program["id"], 9000, [a["id"], b["id"], c["id"]])
    res = settle_redemption(redemption["id"], redemption["version"])
    validate_error(res, "ERR_INSUFFICIENT_BALANCE", expected_status=409)
    a_after = validate_success(api.get_card(a["id"], _STORE), 200)
    assert a_after["settled_balance_cents"] == 3000, "no debit posted on rejection"


def test_refund_exceeds_redemption_rejected(api):
    """PRD §3.6: "when a redemption_id is set, that requested_refund_cents does not exceed that
    referenced redemption's allocated_amount_cents (ERR_REFUND_EXCEEDS_REDEMPTION)."

    Design: Corner/validations/refund_exceeds_redemption_rejected
    """
    program = create_program(reload_min_cents=500, reload_max_balance_cents=100000)
    customer = get_success_data(api.create_customer(
        {"email": "c@x.com", "full_name": "C", "residence_state_code": "FL"}, _ADMIN))
    a = create_active_card(program["id"], 3000, owner_customer_id=customer["id"])
    b = create_active_card(program["id"], 1500, owner_customer_id=customer["id"])
    redemption = draft_redemption(program["id"], 4500, [a["id"], b["id"]],
                                  customer_id=customer["id"])
    get_success_data(settle_redemption(redemption["id"], redemption["version"]))
    # Reload card A so it can in principle accept a large refund credit (isolate the
    # redemption-ceiling check from the balance-cap check).
    get_success_data(api.reload_card(a["id"], reload_card_payload(7000), _STORE))
    refund = get_success_data(api.create_refund(
        {"card_id": a["id"], "requested_refund_cents": 6000, "redemption_id": redemption["id"]},
        _ADMIN))
    res = api.approve_refund(refund["id"], _ADMIN)
    validate_error(res, "ERR_REFUND_EXCEEDS_REDEMPTION", expected_status=409)


def test_bulk_confirm_non_corporate_buyer_rejected(api):
    """PRD §3.2: "an attempt to confirm a bulk order for a non-corporate buyer is rejected
    with ERR_NOT_CORPORATE_BUYER."
    PRD §3.9: "It requires that the buyer's is_corporate is true (ERR_NOT_CORPORATE_BUYER)."

    Design: Corner/validations/bulk_quote_non_corporate_buyer_rejected_on_confirm
    """
    program, buyer, bulk_order = setup_quoted_bulk_order(
        card_count=3, face_value_cents=2500, is_corporate=False)
    res = api.confirm_bulk_order(bulk_order["id"], make_b2b_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_NOT_CORPORATE_BUYER", expected_status=409)


def test_expiration_not_allowed_jurisdiction_rejected(api):
    """PRD §3.8: "If the jurisdiction does not permit expiration (expiration_allowed is
    false), an attempt to expire the card is rejected with ERR_EXPIRATION_NOT_ALLOWED."

    Design: Corner/validations/expiration_not_allowed_jurisdiction_rejected
    """
    program, state_rule, card = setup_card_for_dormancy(
        state_rule_kwargs={"expiration_allowed": False, "dormancy_fee_allowed": False,
                           "breakage_policy": "ESCHEAT", "escheat_rate": 0.60},
        activate_at_iso="2024-01-01T00:00:00Z",
        assess_at_iso="2026-02-01T00:00:00Z",
        settled_cents=4000, state_code="CA")
    res = api.assess_dormancy(card["id"], _ADMIN)
    validate_error(res, "ERR_EXPIRATION_NOT_ALLOWED", expected_status=409)
    after = validate_success(api.get_card(card["id"], _ADMIN), 200)
    assert after["lifecycle_status"] == "ACTIVE"


def test_dormancy_not_due_before_threshold_rejected(api):
    """PRD §3.8: "If a dormancy assessment is requested but the card has not reached the
    threshold, or an ACTIVE waiver covers the current instant, the request is rejected with
    ERR_DORMANCY_NOT_DUE."

    Design: Corner/validations/dormancy_not_due_before_threshold_rejected
    """
    program, state_rule, card = setup_card_for_dormancy(
        state_rule_kwargs={"expiration_allowed": True, "dormancy_fee_allowed": False,
                           "breakage_policy": "RECOGNIZE", "dormancy_threshold_months": 12},
        activate_at_iso="2025-11-01T00:00:00Z",
        assess_at_iso="2026-02-01T00:00:00Z",  # 3 months
        settled_cents=4000)
    res = api.assess_dormancy(card["id"], _ADMIN)
    validate_error(res, "ERR_DORMANCY_NOT_DUE", expected_status=409)


def test_flagged_card_redeem_without_fraud_actor_returns_review(api):
    """PRD §3.5: "any card whose risk_status is FLAGGED is being settled by a FraudAnalyst
    actor — a flagged card settled by anyone else is rejected with ERR_CARD_RISK_REVIEW."

    Design: Corner/validations/flagged_card_redeem_without_fraud_actor_returns_review
    """
    program, card = setup_flagged_card(settled_cents=5000)
    redemption = draft_redemption(program["id"], 1000, [card["id"]])
    res = settle_redemption(redemption["id"], redemption["version"])  # StoreAssociate
    validate_error(res, "ERR_CARD_RISK_REVIEW", expected_status=409)
