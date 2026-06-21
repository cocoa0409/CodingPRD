"""Difficulty Rule 7 — cross_entity_state_dependency.

(A) Clear-to-close on a PurchaseAgreement depends on the linked
    ClosingDisclosure being ACKNOWLEDGED — if it is only DELIVERED,
    the transition is rejected with ERR_CD_NOT_ACKNOWLEDGED.
(B) Close on a PurchaseAgreement with a 1031 ExchangeAccount depends on
    the ExchangeAccount NOT being FAILED — once the exchange_deadline
    passes and the account flips to FAILED, the close is rejected with
    ERR_INVALID_STATE.
"""
from test_helpers import (
    validate_error,
    validate_success,
    setup_actors,
    setup_ready_for_clear_to_close,
    create_exchange_account,
    identify_exchange_account,
    setup_cleared_to_close,
    queue_disbursement,
    advance_clock,
    api_client,
)


class TestClearToCloseRequiresCdAcknowledged:
    """When the CD is still DELIVERED (clock hasn't crossed
    earliest_consummation_at), clear-to-close is rejected with
    ERR_CD_NOT_ACKNOWLEDGED.
    """

    def test_clear_to_close_returns_cd_not_acknowledged_when_cd_not_acknowledged(self, api):
        """PRD §3.5: "A missing CD acknowledgement raises ``ERR_CD_NOT_ACKNOWLEDGED``; a missing CC&R acknowledgement raises ``ERR_CCR_NOT_ACKNOWLEDGED``; any unlocked wire raises ``ERR_WIRE_NOT_LOCKED``; the title gate failures surface as ``ERR_INVALID_STATE`` (because the agreement's ``UNDER_CONTRACT → CLEARED_TO_CLOSE`` precondition is not met)."

        Design: Difficulty/cross_entity_state_dependency/clear_to_close_depends_on_cd_acknowledged
        """
        ready = setup_ready_for_clear_to_close(
            initial_iso8601="2026-06-01T00:00:00Z",
            skip_clock_advance=True,   # CD stays DELIVERED, never ACKNOWLEDGED
            skip_ack_cd=True,
        )
        res = api.clear_to_close_purchase_agreement(
            ready["agreement_id"], ready["actors"]["co"]
        )
        validate_error(res, "ERR_CD_NOT_ACKNOWLEDGED", expected_status=409)

    def test_clear_to_close_blocked_when_cd_not_acknowledged_returns_409(self, api):
        """PRD §3.5: "Advancing the agreement from ``UNDER_CONTRACT`` to ``CLEARED_TO_CLOSE`` requires all of the following preconditions to hold concurrently: exactly one ``TitleSearch`` exists for the agreement with status ``RESOLVED`` and ``has_material_defect`` of ``false``; exactly one ``TitleInsurancePolicy`` exists in status ``ISSUED`` whose underlying search traces back to the agreement; exactly one ``CCRReview`` exists for the agreement with ``buyer_acknowledged`` of ``true``; exactly one ``ClosingDisclosure`` exists in status ``ACKNOWLEDGED``; the current UTC clock is at or after that disclosure's ``earliest_consummation_at``; and every ``WireInstruction`` belonging to the agreement is in status ``LOCKED``."

        Design: Difficulty/cross_entity_state_dependency/clear_to_close_depends_on_cd_acknowledged
        """
        ready = setup_ready_for_clear_to_close(
            initial_iso8601="2026-06-01T00:00:00Z",
            skip_clock_advance=True,
            skip_ack_cd=True,
        )
        res = api.clear_to_close_purchase_agreement(
            ready["agreement_id"], ready["actors"]["co"]
        )
        assert res.status_code == 409, \
            f"clear-to-close on UNDER_CONTRACT without CD ACKNOWLEDGED must be 409, got {res.status_code}"


class TestCloseRequiresExchangeAccountNotFailed:
    """When the linked ExchangeAccount has flipped to FAILED (clock past
    exchange_deadline), close is rejected with ERR_INVALID_STATE per
    PRD §3.7.
    """

    def _setup_close_ready_then_let_exchange_fail(self, api):
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        exchange = create_exchange_account(
            actors, relinquished_closing_date="2026-06-01T00:00:00Z"
        )
        identify_exchange_account(actors, exchange["id"])
        # Build a fully ready-to-close 1031 agreement with EXCHANGE_FUNDS
        # disbursement matching escrow balance.
        ready = setup_cleared_to_close(
            actors=actors,
            purchase_price_cents=50_000_000,
            earnest_money_required_cents=1_000_000,
            exchange_account_id=exchange["id"],
            scheduled_closing_date="2026-09-15T00:00:00Z",
            extra_wire_party="EXCHANGE_ACCOMMODATOR",
            extra_wire_callback_reference="VC-X7Bb-QI",
        )
        queue_disbursement(
            ready["actors"], ready["escrow_id"], ready["extra_wire_id"],
            purpose="EXCHANGE_FUNDS", amount_cents=1_000_000,
        )
        # Now advance clock past the 180-day exchange_deadline.
        # The clock currently sits at 2026-06-04T00:00:00Z (set + 72h)
        # against a relinquished_closing_date of 2026-06-01T00:00:00Z,
        # so exchange_deadline = 2026-11-28T00:00:00Z. Advance ~178 days +
        # margin to land just past it.
        advance_clock(15_638_400, ready["actors"]["co"])
        # Read the exchange account to drive the lazy FAILED transition.
        validate_success(
            api.get_exchange_account(exchange["id"], ready["actors"]["eo"]),
            expected_status=200,
        )
        return ready, exchange

    def test_exchange_account_flips_failed_after_exchange_deadline(self, api):
        """PRD §3.7: "Two automatic transitions to ``FAILED`` also exist, each evaluated synchronously when the system observes the relevant deadline (typically on a read or a related write). From ``OPEN``, the account flips to ``FAILED`` when the current UTC clock is strictly greater than ``identification_deadline`` and ``replacement_property_identified`` is still ``false`` — no replacement was identified in time. From ``IDENTIFIED``, the account flips to ``FAILED`` when the current UTC clock is strictly greater than ``exchange_deadline`` — the replacement was identified but the closing never happened within 180 days."

        Design: Difficulty/cross_entity_state_dependency/close_depends_on_exchange_account_not_failed
        """
        ready, exchange = self._setup_close_ready_then_let_exchange_fail(api)
        ea = validate_success(
            api.get_exchange_account(exchange["id"], ready["actors"]["eo"]),
            expected_status=200,
        )
        assert ea["status"] == "FAILED", \
            f"exchange must be FAILED after clock > exchange_deadline, got {ea['status']}"

    def test_close_rejected_when_exchange_account_failed(self, api):
        """PRD §3.7: "Inside the close transaction, the system also verifies that the exchange account is in ``OPEN`` or ``IDENTIFIED`` and the clock is at or before ``exchange_deadline``; if not, the close itself is rejected with ``ERR_INVALID_STATE``."

        Design: Difficulty/cross_entity_state_dependency/close_depends_on_exchange_account_not_failed
        """
        ready, _ = self._setup_close_ready_then_let_exchange_fail(api)
        res = api.close_purchase_agreement(
            ready["agreement_id"], ready["actors"]["eo"]
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
