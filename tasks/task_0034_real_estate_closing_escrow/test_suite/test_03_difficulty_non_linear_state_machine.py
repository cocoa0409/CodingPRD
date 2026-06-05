"""Difficulty Rule 3 — non_linear_state_machine.

(A) ClosingDisclosure has a fork from DELIVERED: REISSUED (material-change
    branch) re-stamps issued_at and earliest_consummation_at; the other
    branch (ACKNOWLEDGED on or after the 72-hour mark) freezes the row.
(B) PurchaseAgreement has TWO terminate transitions: one from ACTIVE
    (refunds PENDING deposits), one from UNDER_CONTRACT (refunds CONFIRMED
    deposits, gated on has_material_defect=true).
"""
from test_helpers import (
    validate_success,
    setup_actors,
    setup_delivered_cd,
    setup_active_agreement,
    create_deposit,
    create_wire,
    verify_and_lock_wire,
    advance_clock,
    api_client,
    reissue_closing_disclosure_payload,
    terminate_purchase_agreement_payload,
)


class TestClosingDisclosureReissueBranch:
    """From DELIVERED, a material-change reissue re-stamps issued_at and
    restarts the 72-hour clock.
    """

    def test_reissue_with_material_apr_change_advances_to_reissued(self, api):
        """PRD §3.4: "A delivered CD may be reissued if a material change occurs to the loan terms."
        PRD §3.4: "the absolute difference between the request's ``cd_apr_bps`` and the current ``cd_apr_bps`` is at least 12 basis points (so an absolute delta of 12 bps is material; an absolute delta of 11 bps is not), or the request's ``cd_product_type`` differs from the current value, or ``cd_prepayment_penalty`` changes specifically from ``false`` to ``true``."
        PRD §3.4: "When the change is material, the supplied fields are written, the disclosure advances from ``DELIVERED`` to ``REISSUED``, ``issued_at`` is re-stamped to the current UTC clock, and ``earliest_consummation_at`` is recomputed as the new ``issued_at`` plus 72 hours — restarting the three-day clock from scratch."

        Design: Difficulty/non_linear_state_machine/closing_disclosure_branch_reissue_then_acknowledge
        """
        scenario = setup_delivered_cd(initial_iso8601="2026-06-01T00:00:00Z", cd_apr_bps=600)
        # Advance clock 24h then reissue with a 15-bps APR change (material).
        advance_clock(86400, scenario["actors"]["co"])
        res = api.reissue_closing_disclosure(
            scenario["cd_id"],
            reissue_closing_disclosure_payload(cd_apr_bps=615),
            scenario["actors"]["eo"],
        )
        cd = validate_success(res, expected_status=200)
        assert cd["status"] == "REISSUED", \
            f"material-change reissue must advance to REISSUED, got {cd['status']}"
        assert cd["cd_apr_bps"] == 615, \
            f"cd_apr_bps must be rewritten to the request value, got {cd['cd_apr_bps']}"

    def test_reissue_restamps_issued_at_and_earliest_consummation_at(self, api):
        """PRD §3.4: "When the change is material, the supplied fields are written, the disclosure advances from ``DELIVERED`` to ``REISSUED``, ``issued_at`` is re-stamped to the current UTC clock, and ``earliest_consummation_at`` is recomputed as the new ``issued_at`` plus 72 hours — restarting the three-day clock from scratch."

        Design: Difficulty/non_linear_state_machine/closing_disclosure_branch_reissue_then_acknowledge
        """
        scenario = setup_delivered_cd(initial_iso8601="2026-06-01T00:00:00Z", cd_apr_bps=600)
        advance_clock(86400, scenario["actors"]["co"])  # → 2026-06-02T00:00:00Z
        res = api.reissue_closing_disclosure(
            scenario["cd_id"],
            reissue_closing_disclosure_payload(cd_apr_bps=615),
            scenario["actors"]["eo"],
        )
        cd = validate_success(res, expected_status=200)
        assert cd["issued_at"].startswith("2026-06-02T00:00:00"), \
            f"issued_at must be re-stamped to current UTC (2026-06-02T00:00:00Z), got {cd['issued_at']}"
        assert cd["earliest_consummation_at"].startswith("2026-06-05T00:00:00"), \
            f"earliest_consummation_at must be new issued_at + 72h (2026-06-05T00:00:00Z), got {cd['earliest_consummation_at']}"


class TestPurchaseAgreementTerminateFromActive:
    """From ACTIVE, terminate refunds PENDING deposits and closes the escrow.
    """

    def test_terminate_from_active_marks_agreement_terminated(self, api):
        """PRD §3.6: "A purchase agreement may be terminated by an ``EscrowOfficer`` from one of two from-states, advancing it to the terminal ``TERMINATED`` status."
        PRD §3.6: "From ``ACTIVE`` (i.e., before the agreement has reached ``UNDER_CONTRACT``), termination requires only that the request body's ``terminated_reason`` is non-empty."

        Design: Difficulty/non_linear_state_machine/purchase_agreement_branching_terminate_from_two_states
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(
            actors=actors, earnest_money_required_cents=1_000_000
        )
        agreement = base["agreement"]
        deposit = create_deposit(actors, base["escrow"]["id"], amount_cents=500_000)
        # Locked BUYER wire required for refund routing per PRD §3.6.
        buyer_wire = create_wire(
            actors, agreement["id"], party="BUYER",
            beneficiary_account_last4="1111",
        )
        verify_and_lock_wire(
            actors, buyer_wire["id"],
            verifier_user_id=actors["eo_id"],
            voice_callback_reference="VC-A1B",
            verify_as="eo",
        )
        res = api.terminate_purchase_agreement(
            agreement["id"],
            terminate_purchase_agreement_payload(
                terminated_reason="Buyer financing fell through."
            ),
            actors["eo"],
        )
        agr_after = validate_success(res, expected_status=200)
        assert agr_after["status"] == "TERMINATED", \
            f"ACTIVE→TERMINATED transition expected, got {agr_after['status']}"
        assert agr_after["terminated_reason"] == "Buyer financing fell through."

    def test_terminate_from_active_refunds_pending_deposit(self, api):
        """PRD §3.6: "The compensating action flips every ``PENDING`` earnest money deposit on the agreement's escrow to ``REFUNDED``, transitions the escrow from ``OPEN`` to ``CLOSED``, sets ``terminated_reason`` on the agreement, and bumps both the escrow's and the agreement's ``version`` by one each."

        Design: Difficulty/non_linear_state_machine/purchase_agreement_branching_terminate_from_two_states
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(
            actors=actors, earnest_money_required_cents=1_000_000
        )
        agreement = base["agreement"]
        deposit = create_deposit(actors, base["escrow"]["id"], amount_cents=500_000)
        buyer_wire = create_wire(
            actors, agreement["id"], party="BUYER",
            beneficiary_account_last4="1112",
        )
        verify_and_lock_wire(
            actors, buyer_wire["id"],
            verifier_user_id=actors["eo_id"],
            voice_callback_reference="VC-A1B2",
            verify_as="eo",
        )
        validate_success(
            api.terminate_purchase_agreement(
                agreement["id"],
                terminate_purchase_agreement_payload(terminated_reason="Off."),
                actors["eo"],
            ),
            expected_status=200,
        )
        emd_after = validate_success(
            api.get_earnest_money_deposit(deposit["id"], actors["eo"]),
            expected_status=200,
        )
        assert emd_after["status"] == "REFUNDED", \
            f"PENDING deposit must flip to REFUNDED on terminate from ACTIVE, got {emd_after['status']}"
