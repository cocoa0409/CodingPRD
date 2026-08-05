"""Finalize cascade (report → fee invoice → client ledger) and fee-ledger conservation.

Translates queue A (transitive_cascade finalize chain, compensating fee-ledger invariant)
and queue B (fixed-fee invoice, pay-already-paid idempotency) instances.
"""
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS, fixtures

SM = TEST_USERS["study_manager_headers"]

# 3-component PERCENT-2500 study: estimated_tax_benefit 4408908 → fee round(0.25*4408908)=1102227.
PERCENT_COMPS = [
    ("5yr", "FIVE_YEAR", 10000000),
    ("15yr", "FIFTEEN_YEAR", 20000000),
    ("39yr", "THIRTY_NINE_YEAR", 70000000),
]
PERCENT_SCOPE = {"fee_type": "PERCENT", "fee_percent_bps": 2500}


def _submitted_percent_study(api):
    ctx = fixtures.setup_cost_seg_engineering(api, marginal_tax_rate=0.21,
                                              scope_overrides=PERCENT_SCOPE, with_reviewer=True)
    fixtures.add_allocated_components(api, ctx, PERCENT_COMPS)
    fixtures.submit(api, ctx)
    return ctx


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/finalize_report_fee_client_chain
# ---------------------------------------------------------------------------
def test_finalize_cascades_report_fee_and_client_ledger(api):
    """PRD §3.5: "First, the study's report moves from DRAFT to ISSUED and its issued_at is
    stamped from the logical clock. Second, the newly issued report triggers creation of a
    FeeInvoice against the study in status ISSUED ... for a PERCENT fee it is the study's
    fee_percent_bps divided by 10,000, multiplied by the study's estimated_tax_benefit_cents,
    rounded to whole cents. Third, the issued invoice's amount_cents is added to the owning
    client's outstanding_fee_cents."

    Design: Difficulty/transitive_cascade/finalize_report_fee_client_chain
    """
    ctx = _submitted_percent_study(api)
    study = validate_success(api.finalize_study(ctx["study_id"], ctx["rev_headers"]), 200)
    assert study["status"] == "FINALIZED"

    report = fixtures.only_report(api, ctx)
    assert report["status"] == "ISSUED"

    invoice = fixtures.first_fee_invoice(api, ctx)
    assert invoice is not None
    assert invoice["status"] == "ISSUED"
    assert invoice["amount_cents"] == 1102227

    client = validate_success(api.get_client(ctx["client_id"], SM), 200)
    assert client["outstanding_fee_cents"] == 1102227


def test_finalize_moves_client_ledger_from_zero_to_fee(api):
    """PRD §3.5: "Third, the issued invoice's `amount_cents` is added to the owning client's
    `outstanding_fee_cents`."
    PRD §3.1: "A new client starts in `status` `ONBOARDING` with `outstanding_fee_cents` at 0."

    Isolates cascade link 3: the ledger reads 0 before finalize and 1102227 after.

    Design: Difficulty/transitive_cascade/finalize_report_fee_client_chain
    """
    ctx = _submitted_percent_study(api)
    before = validate_success(api.get_client(ctx["client_id"], SM), 200)
    assert before["outstanding_fee_cents"] == 0
    fixtures.finalize(api, ctx)
    after = validate_success(api.get_client(ctx["client_id"], SM), 200)
    assert after["outstanding_fee_cents"] == 1102227


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/fee_ledger_conserved_on_issue_then_void
# ---------------------------------------------------------------------------
def test_void_invoice_returns_client_ledger_to_zero(api):
    """PRD §3.7: "a StudyManager may void an issued invoice ... moving its status from ISSUED
    to VOID and likewise subtracting its amount_cents from the client's outstanding_fee_cents
    as a compensating reversal of the finalize cascade."

    Finalize adds 1102227; voiding subtracts it, returning the ledger to 0.

    Design: Difficulty/compensating_invariant/fee_ledger_conserved_on_issue_then_void
    """
    ctx = _submitted_percent_study(api)
    fixtures.finalize(api, ctx)
    invoice = fixtures.first_fee_invoice(api, ctx)
    assert validate_success(api.get_client(ctx["client_id"], SM), 200)["outstanding_fee_cents"] == 1102227
    get_success_data(api.void_fee_invoice(invoice["id"], SM))
    client = validate_success(api.get_client(ctx["client_id"], SM), 200)
    assert client["outstanding_fee_cents"] == 0


def test_pay_invoice_returns_client_ledger_to_zero(api):
    """PRD §3.7: "A StudyManager settles an issued invoice by paying it, moving its status from
    ISSUED to PAID and subtracting its amount_cents from the client's outstanding_fee_cents."

    Paying the invoice is the other settlement path for the same conserved quantity: the
    ledger returns to 0.

    Design: Difficulty/compensating_invariant/fee_ledger_conserved_on_issue_then_void
    """
    ctx = _submitted_percent_study(api)
    fixtures.finalize(api, ctx)
    invoice = fixtures.first_fee_invoice(api, ctx)
    get_success_data(api.pay_fee_invoice(invoice["id"], SM))
    client = validate_success(api.get_client(ctx["client_id"], SM), 200)
    assert client["outstanding_fee_cents"] == 0


# ---------------------------------------------------------------------------
# Corner/calculations/study_fee_fixed_amount_used_verbatim
# ---------------------------------------------------------------------------
def test_fixed_fee_invoice_uses_flat_amount(api):
    """PRD §3.5: "for a `FIXED` fee the amount is the study's `fee_fixed_amount_cents`, and for
    a `PERCENT` fee it is the study's `fee_percent_bps` divided by 10,000, multiplied by the
    study's `estimated_tax_benefit_cents`, rounded to whole cents."
    PRD §3.5: "whose `fee_basis` copies the study's `fee_type`".

    Design: Corner/calculations/study_fee_fixed_amount_used_verbatim
    """
    ctx = fixtures.setup_cost_seg_finalized(
        api, scope_overrides={"fee_type": "FIXED", "fee_fixed_amount_cents": 500000},
        comps=[("5yr", "FIVE_YEAR", 10000000)])
    invoice = fixtures.first_fee_invoice(api, ctx)
    assert invoice["amount_cents"] == 500000
    assert invoice["fee_basis"] == "FIXED"


# ---------------------------------------------------------------------------
# Corner/state_machines/pay_already_paid_invoice_returns_invalid_state
# ---------------------------------------------------------------------------
def test_pay_already_paid_invoice_rejected(api):
    """PRD §3.7: "A StudyManager settles an issued invoice by paying it, moving its status from
    ISSUED to PAID and subtracting its amount_cents from the client's outstanding_fee_cents."
    PRD §2.1: "then whether the target resource is in a state from which the requested
    transition is legal (ERR_INVALID_STATE)."

    A PAID invoice is no longer ISSUED, so a second pay is an illegal transition; the ledger
    must not be double-decremented.

    Design: Corner/state_machines/pay_already_paid_invoice_returns_invalid_state
    """
    ctx = fixtures.setup_cost_seg_finalized(
        api, scope_overrides={"fee_type": "FIXED", "fee_fixed_amount_cents": 500000},
        comps=[("5yr", "FIVE_YEAR", 10000000)])
    invoice = fixtures.first_fee_invoice(api, ctx)
    get_success_data(api.pay_fee_invoice(invoice["id"], SM))
    resp = api.pay_fee_invoice(invoice["id"], SM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    client = validate_success(api.get_client(ctx["client_id"], SM), 200)
    assert client["outstanding_fee_cents"] == 0
