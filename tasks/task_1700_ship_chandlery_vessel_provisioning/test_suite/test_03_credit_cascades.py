"""Transitive cascades (difficulty rule 4): credit-note apply and revoke.

Covers the depth-3 cascade from complaint accept (PRD §3.12/§3.13: complaint ->
auto-created CreditNote -> Invoice mutation -> ShipAgent exposure) and the
depth-2 compensating cascade from credit-note revoke (PRD §3.13).
"""
from test_helpers import (
    FINANCE,
    TEST_USERS,
    api_client,
    get_success_data,
    list_credit_notes,
    make_officer_headers,
    make_qa_headers,
    pay_invoice,
    setup_accepted_credit_note,
)

FINANCE_HEADERS = TEST_USERS["finance_headers"]


def _whisky_kwargs():
    return dict(
        item_overrides=dict(
            sku="WHISKY-09", name="Scotch Whisky 1L", category="BONDED",
            bonded_eligible=True, requires_cold_chain=False,
            base_price_cents=5000, duty_rate_pct=20,
        ),
        lot_overrides=dict(lot_code="BW-9", storage_tier="BONDED_WAREHOUSE",
                           received_qty=500, capacity_qty=0),
        call_overrides=dict(foreign_going=True),
        clear_customs=True,
    )


# ===========================================================================
# transitive_cascade / complaint_accept_depth3_credit_cascade
# ===========================================================================

class TestComplaintAcceptDepth3CreditCascade:
    def test_accept_auto_creates_applied_credit_note(self, api):
        """PRD §3.12: "A successful accept auto-creates exactly one `CreditNote` in
        `APPLIED` status and applies the cascade of §3.13." PRD §3.13:
        "`restocking_fee_cents` is the larger of 500 cents and 5 percent of
        `gross_amount_cents` rounded half-up." 10 rejected units at invoice unit
        price 5,000 => gross 50,000; fee max(500, 2,500) = 2,500; amount
        47,500.

        Design: Difficulty/transitive_cascade/complaint_accept_depth3_credit_cascade
        """
        ctx = setup_accepted_credit_note(
            qty=100, unit_price_cents=5000, rejected_qty=10,
            qa_user_id="qa-lead-1", **_whisky_kwargs(),
        )
        note = ctx["credit_note"]
        assert ctx["complaint"]["status"] == "ACCEPTED"
        assert note["status"] == "APPLIED"
        assert note["amount_cents"] == 47500, (
            f"gross 50000 - restocking max(500, 2500) = 47500; got {note['amount_cents']}"
        )

    def test_cascade_mutates_invoice_and_agent_exposure(self, api):
        """PRD §3.13: "Applying the note increases the invoice's
        `credited_amount_cents` by `amount_cents`, recomputes `outstanding_cents`,
        and may flip the invoice to `CREDITED`". "The agent's exposures recompute
        on every application."

        Duty-free invoice 480,000; credit 47,500 applied: hop 2 — invoice
        credited 47,500, outstanding 432,500, status stays ISSUED (not fully
        credited); hop 3 — agent settled and committed exposure both 432,500.

        Design: Difficulty/transitive_cascade/complaint_accept_depth3_credit_cascade
        """
        ctx = setup_accepted_credit_note(
            qty=100, unit_price_cents=5000, rejected_qty=10,
            qa_user_id="qa-lead-1", **_whisky_kwargs(),
        )
        invoice = get_success_data(api_client.get_invoice(ctx["invoice"]["id"], FINANCE))
        assert invoice["total_cents"] == 480000
        assert invoice["credited_amount_cents"] == 47500
        assert invoice["outstanding_cents"] == 432500
        assert invoice["status"] == "ISSUED", "Partial credit does not flip to CREDITED"

        agent = get_success_data(api_client.get_ship_agent(ctx["agent"]["id"], FINANCE))
        assert agent["settled_exposure_cents"] == 432500
        assert agent["committed_exposure_cents"] == 432500


# ===========================================================================
# transitive_cascade / credit_note_revoke_depth2_reversal_cascade
# ===========================================================================

class TestCreditNoteRevokeDepth2ReversalCascade:
    def test_revoke_flips_note_to_revoked(self, api):
        """PRD §3.13: "A `FinanceController` may later revoke an `APPLIED` note
        (any other state yields `ERR_CREDIT_NOTE_NOT_REVOCABLE`)". "Revocation
        flips the note to `REVOKED`".

        Design: Difficulty/transitive_cascade/credit_note_revoke_depth2_reversal_cascade
        """
        ctx = setup_accepted_credit_note(
            qty=100, unit_price_cents=5000, rejected_qty=10,
            qa_user_id="qa-lead-9",
            **dict(_whisky_kwargs(), item_overrides=dict(
                sku="WHISKY-10", name="Scotch Whisky 1L", category="BONDED",
                bonded_eligible=True, requires_cold_chain=False,
                base_price_cents=5000, duty_rate_pct=20,
            ), lot_overrides=dict(lot_code="BW-10", storage_tier="BONDED_WAREHOUSE",
                                  received_qty=500, capacity_qty=0)),
        )
        note = get_success_data(
            api_client.revoke_credit_note(ctx["credit_note"]["id"], FINANCE)
        )
        assert note["status"] == "REVOKED"

    def test_revoke_restores_invoice_and_agent_exposure(self, api):
        """PRD §3.13: "Revocation flips the note to `REVOKED`, subtracts
        `amount_cents` from the invoice's `credited_amount_cents`, recomputes the
        outstanding balance, and re-derives the invoice status ... with the
        order's payment dimension following and the agent's exposures recomputed
        once more."

        Credit 47,500 applied on invoice 480,000 (outstanding 432,500, agent
        settled 432,500); after revoke: hop 1 — invoice credited 0, outstanding
        480,000 restored; hop 2 — agent settled back to 480,000.

        Design: Difficulty/transitive_cascade/credit_note_revoke_depth2_reversal_cascade
        """
        ctx = setup_accepted_credit_note(
            qty=100, unit_price_cents=5000, rejected_qty=10,
            qa_user_id="qa-lead-9",
            **dict(_whisky_kwargs(), item_overrides=dict(
                sku="WHISKY-10", name="Scotch Whisky 1L", category="BONDED",
                bonded_eligible=True, requires_cold_chain=False,
                base_price_cents=5000, duty_rate_pct=20,
            ), lot_overrides=dict(lot_code="BW-10", storage_tier="BONDED_WAREHOUSE",
                                  received_qty=500, capacity_qty=0)),
        )
        agent_before = get_success_data(api_client.get_ship_agent(ctx["agent"]["id"], FINANCE))
        assert agent_before["settled_exposure_cents"] == 432500

        get_success_data(api_client.revoke_credit_note(ctx["credit_note"]["id"], FINANCE))

        invoice = get_success_data(api_client.get_invoice(ctx["invoice"]["id"], FINANCE))
        assert invoice["credited_amount_cents"] == 0
        assert invoice["outstanding_cents"] == 480000, "Outstanding fully restored"

        agent = get_success_data(api_client.get_ship_agent(ctx["agent"]["id"], FINANCE))
        assert agent["settled_exposure_cents"] == 480000, (
            "Compensating pair (apply then revoke) leaves exposure as before"
        )
