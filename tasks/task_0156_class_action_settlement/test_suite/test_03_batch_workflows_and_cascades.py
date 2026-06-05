"""Distribution batch branching (post vs void), the close-claims and
batch-reverse cascades, and the post/reverse compensating invariants on the
ledger and on the validated-claim count.

Queue A (Difficulty): non_linear_state_machine (batch fork), transitive_cascade,
compensating_invariant.
"""
from test_helpers import (
    get_success_data,
    validate_paginated,
    fixtures,
)
from test_helpers.api_client import api_client

ADMIN = fixtures.ADMIN
ADMINISTRATOR = fixtures.ADMINISTRATOR
REVIEWER = fixtures.REVIEWER
CONTROLLER = fixtures.CONTROLLER


# ─── non_linear_state_machine: batch_computed_forks_post_vs_void ─────────────
def test_void_computed_batch_cancels_payments_no_ledger_impact():
    """PRD §3.6: "Alternatively, the controller voids a `COMPUTED` batch. Voiding is the divergent sibling of posting: it cancels every planned payment in the batch (each `PLANNED` payment becomes `CANCELLED`), sets the batch to the terminal `VOID`, and increments the batch's version — with no ledger impact, no claim transition, and no tax forms."

    Design: Difficulty/non_linear_state_machine/batch_computed_forks_post_vs_void
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA",
        gross_fund_cents=50000,
        members=[{"email": "m@x.com", "full_name": "M", "claimed_loss_cents": 50000, "recognized_loss_cents": 50000}],
    )
    batch_id = ctx["batch"]["id"]
    result = get_success_data(api_client.void_batch(batch_id, CONTROLLER))
    assert result["status"] == "VOID"

    payments, _ = validate_paginated(api_client.list_batch_payments(batch_id, CONTROLLER))
    assert len(payments) == 1
    assert payments[0]["status"] == "CANCELLED"


def test_void_leaves_claim_validated_and_allocation_zero():
    """PRD §3.6: "Voiding is the divergent sibling of posting: it cancels every planned payment in the batch (each `PLANNED` payment becomes `CANCELLED`), sets the batch to the terminal `VOID`, and increments the batch's version — with no ledger impact, no claim transition, and no tax forms."

    Design: Difficulty/non_linear_state_machine/batch_computed_forks_post_vs_void
    """
    ctx = fixtures.setup_computed_batch(
        distribution_method="PRO_RATA",
        gross_fund_cents=50000,
        members=[{"email": "m@x.com", "full_name": "M", "claimed_loss_cents": 50000, "recognized_loss_cents": 50000}],
    )
    s_id = ctx["settlement"]["id"]
    claim_id = ctx["claims"][0]["id"]
    get_success_data(api_client.void_batch(ctx["batch"]["id"], CONTROLLER))

    claim = get_success_data(api_client.get_claim(claim_id, CONTROLLER))
    assert claim["status"] == "VALIDATED"
    settlement = get_success_data(api_client.get_settlement(s_id, ADMIN))
    assert settlement["allocated_cents"] == 0


# ─── transitive_cascade: close_claims_expire_deficiency_reject_claim_demote_member_depth3 ─
def test_close_claims_expires_deficiency_rejects_claim_demotes_member():
    """PRD §3.1: "Closing the claims window sweeps the deficiency backlog: for every still-open deficiency whose own cure window has elapsed (its `cure_deadline` at or before now), the deficiency is expired and its claim is driven to `REJECTED` through the rejection cascade described in §3.4."
    PRD §3.4: "Rejection expires every open deficiency child (each `OPEN` deficiency becomes `EXPIRED`), resets the claim's `open_deficiency_count` to 0, increments the claim's version, and bubbles up to the member: if the claimant has no remaining non-rejected claim, the member falls from `PARTICIPATING` back to `NOTIFIED`."

    Design: Difficulty/transitive_cascade/close_claims_expire_deficiency_reject_claim_demote_member_depth3
    """
    fixtures.set_clock("2026-01-05T00:00:00Z")
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-02-01T00:00:00Z",
        objection_deadline="2026-01-20T00:00:00Z",
        cy_pres_floor_cents=0,
        case_caption="In re Cascade",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)
    get_success_data(api_client.open_claims(s_id, ADMIN))
    claim = fixtures.file_claim(s_id, member["id"], claimed_loss_cents=5000)
    get_success_data(api_client.raise_deficiency(
        claim["id"], {"reason_code": "MISSING_PROOF", "cure_deadline": "2026-01-15T00:00:00Z"}, REVIEWER))
    fixtures.set_clock("2026-02-01T00:00:00Z")

    get_success_data(api_client.close_claims(s_id, ADMIN))

    defs, _ = validate_paginated(api_client.list_deficiencies(claim["id"], REVIEWER))
    assert len(defs) == 1
    assert defs[0]["status"] == "EXPIRED"
    refreshed_claim = get_success_data(api_client.get_claim(claim["id"], CONTROLLER))
    assert refreshed_claim["status"] == "REJECTED"
    refreshed_member = get_success_data(api_client.get_class_member(member["id"], ADMINISTRATOR))
    assert refreshed_member["status"] == "NOTIFIED"


def test_close_claims_rejected_claim_zeroes_open_deficiency_count():
    """PRD §3.4: "Rejection expires every open deficiency child (each `OPEN` deficiency becomes `EXPIRED`), resets the claim's `open_deficiency_count` to 0, increments the claim's version, and bubbles up to the member: if the claimant has no remaining non-rejected claim, the member falls from `PARTICIPATING` back to `NOTIFIED`."

    Design: Difficulty/transitive_cascade/close_claims_expire_deficiency_reject_claim_demote_member_depth3
    """
    fixtures.set_clock("2026-01-05T00:00:00Z")
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-02-01T00:00:00Z",
        objection_deadline="2026-01-20T00:00:00Z",
        cy_pres_floor_cents=0,
        case_caption="In re CascadeCount",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)
    get_success_data(api_client.open_claims(s_id, ADMIN))
    claim = fixtures.file_claim(s_id, member["id"], claimed_loss_cents=5000)
    get_success_data(api_client.raise_deficiency(
        claim["id"], {"reason_code": "MISSING_PROOF", "cure_deadline": "2026-01-15T00:00:00Z"}, REVIEWER))
    fixtures.set_clock("2026-02-01T00:00:00Z")
    get_success_data(api_client.close_claims(s_id, ADMIN))

    refreshed_claim = get_success_data(api_client.get_claim(claim["id"], CONTROLLER))
    assert refreshed_claim["status"] == "REJECTED"
    assert refreshed_claim["open_deficiency_count"] == 0


# ─── transitive_cascade: batch_reverse_reverses_payment_reverts_claim_depth2 ─
def test_reverse_batch_reverts_payment_and_claim():
    """PRD §3.7: "Reversal is the compensating mirror of posting: every committed payment in the batch moves to `REVERSED`; each paid claim reverts from `PAID` back to `VALIDATED` with its `paid_amount_cents` reset to 0; one positive `PAYMENT_REVERSAL_CREDIT` ledger entry of `amount_cents` is appended per payment; the settlement's `allocated_cents` is decreased by the batch's posted total; every tax form referencing a payment in the batch is voided; and both the batch's version and the settlement's version are incremented."

    Design: Difficulty/transitive_cascade/batch_reverse_reverses_payment_reverts_claim_depth2
    """
    ctx = fixtures.setup_single_claim_posted(gross_fund_cents=50000)
    s_id = ctx["settlement"]["id"]
    batch_id = ctx["batch"]["id"]
    claim_id = ctx["claims"][0]["id"]
    get_success_data(api_client.reverse_batch(batch_id, CONTROLLER))

    payments, _ = validate_paginated(api_client.list_batch_payments(batch_id, CONTROLLER))
    assert len(payments) == 1
    assert payments[0]["status"] == "REVERSED"
    claim = get_success_data(api_client.get_claim(claim_id, CONTROLLER))
    assert claim["status"] == "VALIDATED"
    assert claim["paid_amount_cents"] == 0


def test_reverse_batch_decrements_allocated_cents():
    """PRD §3.7: "the settlement's `allocated_cents` is decreased by the batch's posted total; every tax form referencing a payment in the batch is voided; and both the batch's version and the settlement's version are incremented."

    Design: Difficulty/transitive_cascade/batch_reverse_reverses_payment_reverts_claim_depth2
    """
    ctx = fixtures.setup_single_claim_posted(gross_fund_cents=50000)
    s_id = ctx["settlement"]["id"]
    assert ctx["settlement"]["allocated_cents"] == 50000
    get_success_data(api_client.reverse_batch(ctx["batch"]["id"], CONTROLLER))

    settlement = get_success_data(api_client.get_settlement(s_id, ADMIN))
    assert settlement["allocated_cents"] == 0


# ─── compensating_invariant: post_then_reverse_conserves_ledger_balance ──────
def test_post_then_reverse_restores_ledger_balance():
    """PRD §2.7: "one negative `PAYMENT_DEBIT` per committed payment; one positive `PAYMENT_REVERSAL_CREDIT` per reversed payment"
    PRD §2.7: "A read-only balance endpoint computes this sum on demand — summing the signed `amount_cents` of every `LedgerEntry` for the settlement, with no entry excluded — and returns it alongside the fund's `net_distributable_cents`, `allocated_cents`, and `residual_cents`."

    Design: Difficulty/compensating_invariant/post_then_reverse_conserves_ledger_balance
    """
    ctx = fixtures.setup_single_claim_posted(gross_fund_cents=50000)
    s_id = ctx["settlement"]["id"]
    # post brought balance to 0 (FUND_OPEN +50000, PAYMENT_DEBIT -50000)
    get_success_data(api_client.reverse_batch(ctx["batch"]["id"], CONTROLLER))

    bal = get_success_data(api_client.get_ledger_balance(s_id, CONTROLLER))
    assert bal["balance_cents"] == 50000
    settlement = get_success_data(api_client.get_settlement(s_id, ADMIN))
    assert settlement["allocated_cents"] == 0


def test_post_then_reverse_ledger_entries_sum_to_net():
    """PRD §2.7: "summing the signed `amount_cents` of every `LedgerEntry` for the settlement, with no entry excluded"

    Design: Difficulty/compensating_invariant/post_then_reverse_conserves_ledger_balance
    """
    ctx = fixtures.setup_single_claim_posted(gross_fund_cents=50000)
    s_id = ctx["settlement"]["id"]
    get_success_data(api_client.reverse_batch(ctx["batch"]["id"], CONTROLLER))

    entries, _ = validate_paginated(api_client.list_ledger_entries(s_id, CONTROLLER))
    assert sum(e["amount_cents"] for e in entries) == 50000


# ─── compensating_invariant: post_then_reverse_conserves_validated_claim_count ─
def test_post_then_reverse_restores_validated_claim():
    """PRD §3.7: "each paid claim reverts from `PAID` back to `VALIDATED` with its `paid_amount_cents` reset to 0"

    Design: Difficulty/compensating_invariant/post_then_reverse_conserves_validated_claim_count
    """
    ctx = fixtures.setup_single_claim_posted(gross_fund_cents=50000)
    s_id = ctx["settlement"]["id"]
    claim_id = ctx["claims"][0]["id"]
    get_success_data(api_client.reverse_batch(ctx["batch"]["id"], CONTROLLER))

    claim = get_success_data(api_client.get_claim(claim_id, CONTROLLER))
    assert claim["status"] == "VALIDATED"
    assert claim["paid_amount_cents"] == 0


def test_post_then_reverse_validated_claim_count_back_to_one():
    """PRD §3.6: "Computation runs the allocation over the **eligible claims**: every claim of this settlement that is `VALIDATED`, has a `paid_amount_cents` of 0, and whose owning member is `PARTICIPATING`."

    Design: Difficulty/compensating_invariant/post_then_reverse_conserves_validated_claim_count
    """
    ctx = fixtures.setup_single_claim_posted(gross_fund_cents=50000)
    s_id = ctx["settlement"]["id"]
    get_success_data(api_client.reverse_batch(ctx["batch"]["id"], CONTROLLER))

    # PRD §4 authorizes FundController (not SettlementAdmin) for GET /claims.
    claims, _ = validate_paginated(
        api_client.list_claims(CONTROLLER, params={"settlement_id": s_id, "status": "VALIDATED"})
    )
    assert len(claims) == 1
