"""Difficulty Rule 5 — priority_pair_validation_conflict.

When two validations would both fail, the higher-priority error is the
one surfaced. We test two pairs:
  (A) state (priority 5) vs business_fiscal (priority 20) on close.
  (B) business_safety/ERR_WIRE_NOT_LOCKED (priority 9) vs
      business_constraint/ERR_EXCHANGE_ROUTING_REQUIRED (priority 17)
      on disbursement queue.
"""
from test_helpers import (
    validate_error,
    setup_actors,
    setup_active_agreement,
    setup_locked_wire,
    create_exchange_account,
    create_wire,
    create_disbursement_payload,
    setup_under_contract_agreement,
    queue_disbursement,
    api_client,
)


class TestStateOutranksBusinessFiscalOnClose:
    """An agreement still in UNDER_CONTRACT (not CLEARED_TO_CLOSE) AND with
    insufficient escrow balance fails BOTH the state precondition (priority
    5) and the fiscal sufficiency check (priority 20). Per PRD §2.10 the
    state error fires first.
    """

    def _setup_under_contract_with_insufficient_balance(self):
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_under_contract_agreement(
            actors=actors,
            purchase_price_cents=50_000_000,
            earnest_money_required_cents=1_000_000,
        )
        # Lock a SELLER wire and queue a disbursement far larger than the
        # escrow's balance_cents (1_000_000) so both gates would fail.
        seller_wire = setup_locked_wire(
            base["actors"], base["agreement_id"], party="SELLER",
            voice_callback_reference="VC-P5",
        )
        queue_disbursement(
            base["actors"], base["escrow_id"], seller_wire["id"],
            purpose="SELLER_PROCEEDS", amount_cents=100_000_000,
        )
        return base

    def test_close_from_under_contract_returns_invalid_state(self, api):
        """PRD §2.10: "State preconditions are next: the from-state check against the relevant state machine (raising ``ERR_INVALID_STATE``), then the optimistic-concurrency checks of §2.7 (raising ``ERR_STALE_AGREEMENT_VERSION`` or ``ERR_STALE_TITLE_SEARCH_VERSION``), then the three-day disclosure wait (raising ``ERR_CD_THREE_DAY_NOT_ELAPSED``), then the wire segregation-of-duties check (raising ``ERR_WIRE_SOD_VIOLATION``)."
        PRD §2.10: "Business-safety and compliance checks rank above business-referential checks, and both rank above business-temporal, business-constraint, and business-fiscal checks."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_close_returns_invalid_state
        """
        base = self._setup_under_contract_with_insufficient_balance()
        res = api.close_purchase_agreement(base["agreement_id"], base["actors"]["eo"])
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_close_from_under_contract_does_not_return_insufficient_funds(self, api):
        """PRD §2.10: "State preconditions are next: the from-state check against the relevant state machine (raising ``ERR_INVALID_STATE``), then the optimistic-concurrency checks of §2.7 (raising ``ERR_STALE_AGREEMENT_VERSION`` or ``ERR_STALE_TITLE_SEARCH_VERSION``), then the three-day disclosure wait (raising ``ERR_CD_THREE_DAY_NOT_ELAPSED``), then the wire segregation-of-duties check (raising ``ERR_WIRE_SOD_VIOLATION``)."
        PRD §2.10: "Business-safety and compliance checks rank above business-referential checks, and both rank above business-temporal, business-constraint, and business-fiscal checks."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_close_returns_invalid_state
        """
        base = self._setup_under_contract_with_insufficient_balance()
        res = api.close_purchase_agreement(base["agreement_id"], base["actors"]["eo"])
        body = res.json()
        # The higher-priority state precondition must shadow the fiscal check.
        assert body["data"]["error_id"] != "ERR_INSUFFICIENT_ESCROW_FUNDS", \
            f"state precondition (priority 5) must outrank fiscal sufficiency (priority 20); got {body['data']['error_id']}"


class TestBusinessSafetyOutranksBusinessConstraintOnDisbursementQueue:
    """A disbursement that violates BOTH:
      * priority 9 (business_safety / ERR_WIRE_NOT_LOCKED — wire is not LOCKED)
      * priority 17 (business_constraint / ERR_EXCHANGE_ROUTING_REQUIRED —
        SELLER_PROCEEDS against a 1031 agreement)
    Per PRD §2.10 the business-safety wire-lock check fires first.
    """

    def _setup_unlocked_wire_on_exchange_agreement(self):
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        exchange = create_exchange_account(actors)
        base = setup_active_agreement(
            actors=actors,
            purchase_price_cents=50_000_000,
            exchange_account_id=exchange["id"],
        )
        # Create a SELLER wire but leave it in PROVIDED (do not verify, do not lock)
        seller_wire = create_wire(
            actors, base["agreement"]["id"], party="SELLER",
            beneficiary_account_last4="0003",
        )
        return actors, base, seller_wire

    def test_unlocked_seller_wire_on_1031_returns_wire_not_locked(self, api):
        """PRD §2.10: "The wire-not-locked checks (``ERR_WIRE_NOT_LOCKED`` on a queued disbursement, ``ERR_WIRE_NOT_LOCKED`` on clear-to-close, ``ERR_BUYER_WIRE_NOT_LOCKED`` on terminate), and the reissue-not-material check (``ERR_CD_REISSUE_NOT_MATERIAL``) all fall under business-safety."
        PRD §2.10: "Business-safety and compliance checks rank above business-referential checks, and both rank above business-temporal, business-constraint, and business-fiscal checks."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_disbursement_returns_wire_not_locked
        """
        actors, base, seller_wire = self._setup_unlocked_wire_on_exchange_agreement()
        res = api.create_disbursement(
            create_disbursement_payload(
                escrow_account_id=base["escrow"]["id"],
                wire_instruction_id=seller_wire["id"],
                purpose="SELLER_PROCEEDS",
                amount_cents=40_000_000,
            ),
            actors["eo"],
        )
        validate_error(res, "ERR_WIRE_NOT_LOCKED", expected_status=409)

    def test_unlocked_seller_wire_on_1031_does_not_return_exchange_routing(self, api):
        """PRD §2.10: "The wire-not-locked checks (``ERR_WIRE_NOT_LOCKED`` on a queued disbursement, ``ERR_WIRE_NOT_LOCKED`` on clear-to-close, ``ERR_BUYER_WIRE_NOT_LOCKED`` on terminate), and the reissue-not-material check (``ERR_CD_REISSUE_NOT_MATERIAL``) all fall under business-safety."
        PRD §2.10: "Business-safety and compliance checks rank above business-referential checks, and both rank above business-temporal, business-constraint, and business-fiscal checks."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_disbursement_returns_wire_not_locked
        """
        actors, base, seller_wire = self._setup_unlocked_wire_on_exchange_agreement()
        res = api.create_disbursement(
            create_disbursement_payload(
                escrow_account_id=base["escrow"]["id"],
                wire_instruction_id=seller_wire["id"],
                purpose="SELLER_PROCEEDS",
                amount_cents=40_000_000,
            ),
            actors["eo"],
        )
        body = res.json()
        assert body["data"]["error_id"] != "ERR_EXCHANGE_ROUTING_REQUIRED", \
            f"business-safety wire-not-locked must shadow business-constraint exchange-routing; got {body['data']['error_id']}"
