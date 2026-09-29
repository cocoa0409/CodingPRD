"""Rejected certificates and a broken payment plan, followed hop by hop."""
from test_helpers import (
    approve_arrangement,
    default_arrangement,
    file_certificate,
    list_adjustments,
    read_arrangement,
    read_assessment,
    read_audit,
    read_certificate,
    read_sample_unit,
    read_taxpayer,
    reopen_fieldwork,
    request_installment_plan,
    review_certificate,
    setup_draft_assessment,
    setup_issued_assessment,
)

SCOPE_START = "2026-01-01"
PRICE_FOR_4762_CENTS = 76_192
SAMPLED_INVOICE_CENTS = 1_000_000
EXEMPT_SALE_CENTS = 800_000
TAX_ON_THE_EXEMPT_SALE = 50_000
COLLECTION_FEE_CENTS = -476


def _certificate_rejected_against_a_sampled_invoice():
    """A drafted notice, fieldwork reopened, and a linked certificate rejected."""
    ctx = setup_draft_assessment(
        sample_unit_specs=[
            {
                "error_class": "NO_ERROR",
                "invoice_amount_cents": SAMPLED_INVOICE_CENTS,
                "exempt_sale_amount_cents": EXEMPT_SALE_CENTS,
            }
        ]
    )
    assert ctx["assessment"]["status"] == "DRAFT"
    reopen_fieldwork(ctx["audit"]["id"])
    ctx["certificate"] = file_certificate(
        ctx["audit"]["id"],
        covered_sale_amount_cents=EXEMPT_SALE_CENTS,
        received_before_sale=False,
        sample_unit_id=ctx["sample_units"][0]["id"],
    )
    assert ctx["certificate"]["status"] == "ON_FILE"
    assert ctx["certificate"]["missing_certificate_tax_cents"] == 0
    ctx["certificate"] = review_certificate(ctx["certificate"]["id"], "REJECTED")
    return ctx


def test_rejecting_a_certificate_prices_the_sale_it_purported_to_exempt():
    """A certificate the seller never held before the sale fails good faith and is priced.

    PRD 3.5: "The computed flag `good_faith_accepted` is true only when all four
    diligence conditions hold together: the certificate was received before the sale,
    the form is complete, a `purchaser_permit_number` is present, and the claimed
    exemption matches the purchaser's business."
    PRD 3.5: "First, the certificate records the `review_note`, takes status
    `REJECTED`, and computes `missing_certificate_tax_cents` as
    `covered_sale_amount_cents` multiplied by 625 basis points, divided by 10,000 and
    rounded half up."

    Design: Difficulty/transitive_cascade/certificate_rejection_four_hop_cascade_stales_the_draft_notice
    """
    ctx = _certificate_rejected_against_a_sampled_invoice()
    certificate = read_certificate(ctx["certificate"]["id"])

    assert certificate["status"] == "REJECTED"
    assert certificate["good_faith_accepted"] is False
    assert certificate["missing_certificate_tax_cents"] == TAX_ON_THE_EXEMPT_SALE

    unit = read_sample_unit(ctx["sample_units"][0]["id"])
    assert unit["error_class"] == "CERTIFICATE_DEFECT"
    assert unit["error_amount_cents"] == TAX_ON_THE_EXEMPT_SALE


def test_the_linked_defect_enters_the_sample_and_not_the_audit_rollup():
    """Routing the tax through the invoice keeps the audit total from double-counting.

    PRD 3.5: "The audit's `certificate_deficiency_cents` is the sum of
    `missing_certificate_tax_cents` over the certificates of that audit whose status
    is `REJECTED` **and** whose `sample_unit_id` is null."
    PRD 3.5: "Third, caused by the second, the audit's `sample_error_rate_bp` can no
    longer be trusted and `projection_status` is set to `STALE`."
    PRD 3.5: "Fourth, caused by the third, every assessment of that audit whose
    `status` is `DRAFT` moves to `DRAFT_STALE`."

    Design: Difficulty/transitive_cascade/certificate_rejection_four_hop_cascade_stales_the_draft_notice
    """
    ctx = _certificate_rejected_against_a_sampled_invoice()

    audit = read_audit(ctx["audit"]["id"])
    assert audit["certificate_deficiency_cents"] == 0
    assert audit["projection_status"] == "STALE"
    assert read_assessment(ctx["assessment"]["id"])["status"] == "DRAFT_STALE"


def _defaulted_installment_plan():
    """An arranged notice of 4,762 cents whose plan the agent declares in default."""
    ctx = setup_issued_assessment(
        purchase_specs=[
            {
                "invoice_date": SCOPE_START,
                "purchase_price_cents": PRICE_FOR_4762_CENTS,
                "asset_class": "CONSUMABLE",
            }
        ]
    )
    assert ctx["assessment"]["balance_due_cents"] == 4_762
    assert read_taxpayer(ctx["taxpayer"]["id"])["compliance_status"] == "COMPLIANT"
    ctx["arrangement"] = request_installment_plan(ctx["assessment"]["id"], 4_762, 1)
    approve_arrangement(ctx["arrangement"]["id"])
    ctx["arrangement"] = default_arrangement(
        ctx["arrangement"]["id"], default_reason="Three consecutive installments missed."
    )
    return ctx


def test_defaulting_a_plan_refers_the_notice_and_charges_the_statutory_fee():
    """The fee is a negative credit, so the balance goes up rather than down.

    PRD 3.9: "Second, caused by the first, the assessment's `collection_status` moves
    to `REFERRED` and a `SYSTEM` `COLLECTION_FEE` adjustment is posted for the
    negative of `balance_due_cents` multiplied by 1,000 basis points, divided by
    10,000 and rounded half up."
    PRD 3.7: "The `amount_cents` is a signed credit against `total_due_cents`:
    positive for `PENALTY_ABATEMENT`, `PAYMENT`, `APPEAL_REDUCTION`,
    `ASSESSMENT_VACATED` and `OIC_WRITEOFF`, and negative for `COLLECTION_FEE`, which
    is a charge and therefore raises the balance rather than lowering it."

    Design: Difficulty/transitive_cascade/arrangement_default_three_hop_cascade_adds_collection_fee
    """
    ctx = _defaulted_installment_plan()

    assert read_arrangement(ctx["arrangement"]["id"])["status"] == "DEFAULTED"

    rows = list_adjustments(assessment_id=ctx["assessment"]["id"])
    assert len(rows) == 1
    assert rows[0]["kind"] == "COLLECTION_FEE"
    assert rows[0]["source"] == "SYSTEM"
    assert rows[0]["status"] == "POSTED"
    # Ten percent of the 4,762-cent balance, charged rather than credited.
    assert rows[0]["amount_cents"] == COLLECTION_FEE_CENTS

    after = read_assessment(ctx["assessment"]["id"])
    assert after["collection_status"] == "REFERRED"
    assert after["total_adjustments_cents"] == COLLECTION_FEE_CENTS
    assert after["total_due_cents"] == 4_762
    assert after["balance_due_cents"] == 5_238


def test_defaulting_a_plan_marks_the_permit_holder_delinquent():
    """The last hop reaches the taxpayer, and the money identity still balances.

    PRD 3.9: "Third, caused by the second, the taxpayer's `compliance_status` becomes
    `DELINQUENT`."
    PRD 3.7: "The conserved-money invariant closes the system: after every mutation,
    `balance_due_cents` plus `total_adjustments_cents` plus `amount_paid_cents` equals
    `total_due_cents`."

    Design: Difficulty/transitive_cascade/arrangement_default_three_hop_cascade_adds_collection_fee
    """
    ctx = _defaulted_installment_plan()

    assert read_taxpayer(ctx["taxpayer"]["id"])["compliance_status"] == "DELINQUENT"

    after = read_assessment(ctx["assessment"]["id"])
    assert (
        after["balance_due_cents"]
        + after["total_adjustments_cents"]
        + after["amount_paid_cents"]
        == after["total_due_cents"]
    )
