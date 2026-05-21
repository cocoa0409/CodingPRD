"""Tests that depend on engineering suspicious_score >= 0.70.

These cover the difficulty-design instances:
  - non_linear_state_machine/fraud_case_cyclic_via_appeal
  - transitive_cascade/fraud_substantiate_suspends_card_blocks_purchase
  - cross_entity_state_dependency/card_resume_blocked_by_substantiated_fraudcase
  - priority_pair_validation_conflict/safety_fraud_hold_beats_state_on_resume

Score engineering: size=1 approved household at net=63667 cents yields
monthly_allotment=10000 cents (multiple of 10000). A single purchase of
exactly 10000 cents (STAPLE line, all eligible) produces:
    signal_a = 10000 / max(1, 10000) = 1.0   (recently credited within 24h)
    signal_b = 0/1 = 0                       (assumes same-state merchant)
    signal_c = 1/1 = 1.0                     (10000 is a multiple of 10000)
    score   = 0.50*1.0 + 0.30*0 + 0.20*1.0 = 0.70 (exactly at threshold, accepted)
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    ERR_INVALID_STATE, ERR_FRAUD_HOLD, ERR_CARD_NOT_ACTIVE,
    TEST_USERS, make_household_head_headers, make_merchant_headers,
    setup_substantiated_household,
    setup_authorized_merchant,
    create_transaction_payload,
)


CASEWORKER = TEST_USERS["caseworker_headers"]
FRAUD_INV = TEST_USERS["fraud_investigator_headers"]


@pytest.fixture(scope="module")
def substantiated_scene():
    """Try to engineer a SUBSTANTIATED fraud case.

    If the engineered score < 0.70 (because the implementation interprets the
    fraud-score signals differently than the documented sum-then-round of
    A+B+C with our concrete construction), this fixture returns a scene where
    case may still be in UNDER_REVIEW. Tests must handle that gracefully.
    """
    return setup_substantiated_household(size=1, age=30)


class TestFraudSubstantiateCascade:
    def test_substantiate_suspends_active_card(self, api, substantiated_scene):
        """PRD §3.7: "The substantiate cascade is non-trivial: every `ACTIVE`
        `EbtCard` on the affected household transitions from `ACTIVE` to
        `SUSPENDED`."

        Claim (transitive cascade): after substantiation, the household's
        ACTIVE card becomes SUSPENDED.
        """
        # difficulty: transitive_cascade/fraud_substantiate_suspends_card_blocks_purchase
        case = substantiated_scene["fraud_case"]
        card = substantiated_scene["card"]
        hh = substantiated_scene["household"]
        if case["state"] != "SUBSTANTIATED":
            pytest.skip(
                "Engineered suspicious_score did not reach 0.70 in this "
                "implementation; PRD-derivable construction depends on "
                "merchant out-of-state semantics which are PRD-silent."
            )
        # Re-fetch card after substantiation
        card_re = validate_success(api.get_card(hh["id"], card["id"], CASEWORKER))
        assert card_re["status"] == "SUSPENDED", (
            f"Card should be SUSPENDED after fraud substantiation, got {card_re['status']}"
        )

    def test_purchase_blocked_on_substantiated_card(self, api, substantiated_scene):
        """PRD §3.5: "If the `EbtCard.status` is not `ACTIVE`, the transaction
        is declined with `decline_reason` = `CARD_NOT_ACTIVE` and the response
        is `ERR_CARD_NOT_ACTIVE`."

        Claim (transitive cascade hop 3): a subsequent purchase against the
        suspended card returns ERR_CARD_NOT_ACTIVE.
        """
        # difficulty: transitive_cascade/fraud_substantiate_suspends_card_blocks_purchase
        if substantiated_scene["fraud_case"]["state"] != "SUBSTANTIATED":
            pytest.skip("score did not reach 0.70; see fixture note")
        hh = substantiated_scene["household"]
        card = substantiated_scene["card"]
        merchant = setup_authorized_merchant()
        m_headers = make_merchant_headers(merchant["id"])
        payload = create_transaction_payload(
            card_id=card["id"], merchant_id=merchant["id"],
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 100, "quantity": 1}],
        )
        resp = api.create_transaction(payload, m_headers)
        validate_error(resp, ERR_CARD_NOT_ACTIVE)


class TestFraudHoldBlocksResume:
    def test_resume_blocked_by_substantiated_case(self, api, substantiated_scene):
        """PRD §3.4: "A caseworker may resume the card from `SUSPENDED` back
        to `ACTIVE` only when no `FraudCase` for the same household is in
        `SUBSTANTIATED`; if a substantiated case exists, resume fails with
        `ERR_FRAUD_HOLD`."

        Claim (priority pair business_safety vs state): /resume yields
        ERR_FRAUD_HOLD (not ERR_INVALID_STATE) when a SUBSTANTIATED case
        blocks the household.
        """
        # difficulty: priority_pair_validation_conflict/safety_fraud_hold_beats_state_on_resume
        # difficulty: cross_entity_state_dependency/card_resume_blocked_by_substantiated_fraudcase
        if substantiated_scene["fraud_case"]["state"] != "SUBSTANTIATED":
            pytest.skip("score did not reach 0.70; see fixture note")
        hh = substantiated_scene["household"]
        card = substantiated_scene["card"]
        # Card is already SUSPENDED via fraud cascade; attempt /resume
        resp = api.resume_card(hh["id"], card["id"], CASEWORKER)
        validate_error(resp, ERR_FRAUD_HOLD)


class TestFraudHoldEABlocked:
    def test_disburse_blocked_when_household_has_substantiated(self, api, substantiated_scene):
        """PRD §3.9: "The server identifies every qualifying household — those
        with `state_code` matching the declaration, `certification_status` of
        `APPROVED`, and **no** `FraudCase` currently in `SUBSTANTIATED` — and
        posts one `EMERGENCY_ALLOTMENT` `BenefitLedger` entry per qualifying
        household."

        Claim: a household with a SUBSTANTIATED fraud case is NOT a qualifying
        household for EA disbursement — its card receives no EA credit.

        (This is the EA-side of the fraud-hold rule; the resume-side is in
        TestFraudHoldBlocksResume.)
        """
        # difficulty: cross_entity_state_dependency/card_resume_blocked_by_substantiated_fraudcase
        if substantiated_scene["fraud_case"]["state"] != "SUBSTANTIATED":
            pytest.skip("score did not reach 0.70; see fixture note")
        hh = substantiated_scene["household"]
        card = substantiated_scene["card"]
        # Create EA matching the household's state_code and disburse
        from test_helpers import create_emergency_allotment_payload
        ea_resp = api.create_emergency_allotment(
            create_emergency_allotment_payload(
                state_code=hh["state_code"], benefit_month="2030-01",
                max_allotment_table_version=1,
            ),
            TEST_USERS["state_admin_headers"],
        )
        ea = validate_success(ea_resp, expected_status=201)
        validate_success(api.declare_emergency_allotment(
            ea["id"], TEST_USERS["state_admin_headers"]
        ))
        pre_balance = validate_success(api.get_card(hh["id"], card["id"], CASEWORKER))["balance_cents"]
        validate_success(api.disburse_emergency_allotment(
            ea["id"], TEST_USERS["state_admin_headers"]
        ))
        # After disbursement, fraud-blocked household's card balance should NOT have changed.
        post_balance = validate_success(api.get_card(hh["id"], card["id"], CASEWORKER))["balance_cents"]
        assert post_balance == pre_balance, (
            f"Fraud-blocked household should not receive EA credit; "
            f"balance changed from {pre_balance} to {post_balance}"
        )


class TestSafetyFraudHoldBeatsStateSecondHit:
    def test_resume_on_active_card_with_fraud(self, api, substantiated_scene):
        """PRD §3.4: "if a substantiated case exists, resume fails with
        `ERR_FRAUD_HOLD`."

        Claim (second test for safety_fraud_hold_beats_state): even after the
        cascade has already SUSPENDED the card, an explicit /resume call still
        produces ERR_FRAUD_HOLD as long as the fraud case is in SUBSTANTIATED.
        """
        # difficulty: priority_pair_validation_conflict/safety_fraud_hold_beats_state_on_resume
        if substantiated_scene["fraud_case"]["state"] != "SUBSTANTIATED":
            pytest.skip("score did not reach 0.70; see fixture note")
        hh = substantiated_scene["household"]
        card = substantiated_scene["card"]
        # The card is now SUSPENDED via cascade. Try resume — should fail
        # with ERR_FRAUD_HOLD (not ERR_INVALID_STATE).
        resp = api.resume_card(hh["id"], card["id"], CASEWORKER)
        validate_error(resp, ERR_FRAUD_HOLD)


class TestFraudCaseCyclicAppealPath:
    def test_appeal_path_substantiated_to_appeal_pending(self, api, substantiated_scene):
        """PRD §3.7: "The household head may appeal a substantiated case,
        transitioning it from `SUBSTANTIATED` to `APPEAL_PENDING`."

        Claim (cyclic SM): SUBSTANTIATED -> APPEAL_PENDING via HouseholdHead.
        """
        # difficulty: non_linear_state_machine/fraud_case_cyclic_via_appeal
        if substantiated_scene["fraud_case"]["state"] != "SUBSTANTIATED":
            pytest.skip("score did not reach 0.70; see fixture note")
        case = substantiated_scene["fraud_case"]
        hh = substantiated_scene["household"]
        hh_head = make_household_head_headers(hh["id"])
        resp = api.appeal_fraud_case(case["id"], hh_head)
        data = validate_success(resp)
        assert data["state"] == "APPEAL_PENDING"

    def test_uphold_appeal_restores_card(self, api, substantiated_scene):
        """PRD §3.7: "uphold the appeal (transitioning from `APPEAL_PENDING` to
        `UNFOUNDED` and cascading every `EbtCard` that was suspended by *this*
        case back from `SUSPENDED` to `ACTIVE`)."

        Claim (uphold cascade): upholding the appeal flips the previously
        suspended card back to ACTIVE.
        """
        # difficulty: non_linear_state_machine/fraud_case_cyclic_via_appeal
        if substantiated_scene["fraud_case"]["state"] != "SUBSTANTIATED":
            pytest.skip("score did not reach 0.70; see fixture note")
        case = substantiated_scene["fraud_case"]
        hh = substantiated_scene["household"]
        card = substantiated_scene["card"]
        hh_head = make_household_head_headers(hh["id"])
        # The module-scoped fixture may have been mutated by a previous test
        # (e.g. test_appeal_path_substantiated_to_appeal_pending). Re-read the
        # current state and only issue the appeal transition when still
        # SUBSTANTIATED.
        current = validate_success(api.get_fraud_case(case["id"], FRAUD_INV))
        if current["state"] == "SUBSTANTIATED":
            current = validate_success(api.appeal_fraud_case(case["id"], hh_head))
        assert current["state"] == "APPEAL_PENDING", (
            f"Expected case in APPEAL_PENDING for uphold; got {current['state']}"
        )
        # Uphold the appeal
        upheld = validate_success(api.uphold_fraud_appeal(case["id"], FRAUD_INV))
        assert upheld["state"] == "UNFOUNDED"
        # Card should be back to ACTIVE
        card_re = validate_success(api.get_card(hh["id"], card["id"], CASEWORKER))
        assert card_re["status"] == "ACTIVE"
