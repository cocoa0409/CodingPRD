"""A journal's read-time metrics at their empty edges, and its conserved fee ledgers."""

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_EPOCH_MS


def test_fresh_journal_metrics_report_zero_counts_and_a_null_median():
    """Every aggregate of an empty journal is 0 or 0.00 except the median, which is null.

    PRD: "When no manuscript of the journal has a decision at all, `median_days_to_first_decision` is null — the one aggregate here that is null rather than 0.00 when empty."

    Design: Difficulty/boundary_precision_check/fresh_journal_metrics_empty_collection_edges
    """
    journal = fx.create_journal()

    metrics = fx.get_journal_metrics(journal["id"])

    a.assert_fields(
        metrics,
        submitted_count=0,
        desk_rejected_count=0,
        published_count=0,
        retracted_count=0,
        reviewers_on_probation_count=0,
    )
    a.assert_score_equals(metrics["acceptance_rate_pct"], 0.00, "acceptance_rate_pct")
    a.assert_score_equals(
        metrics["reviewer_invitation_acceptance_rate_pct"],
        0.00,
        "reviewer_invitation_acceptance_rate_pct",
    )
    assert metrics["median_days_to_first_decision"] is None, (
        "the median is null, not 0.00, when no manuscript has a decision"
    )


def test_fresh_journal_starts_every_derived_quantity_at_zero():
    """The stored ledgers a metrics read passes through begin at zero.

    PRD: "A newly registered journal starts every derived quantity at zero: `manuscript_intake_count`, `published_article_count`, `retracted_article_count`, `apc_receivable_cents` and `apc_waived_cents`."

    Design: Difficulty/boundary_precision_check/fresh_journal_metrics_empty_collection_edges
    """
    journal = fx.create_journal()

    a.assert_fields(
        journal,
        manuscript_intake_count=0,
        published_article_count=0,
        retracted_article_count=0,
    )
    a.assert_journal_ledgers(journal, apc_receivable_cents=0, apc_waived_cents=0)

    metrics = fx.get_journal_metrics(journal["id"])
    a.assert_fields(metrics, apc_receivable_cents=0, apc_waived_cents=0)


def test_acceptance_rate_is_zero_while_the_decided_set_is_empty():
    """One manuscript in flight leaves the decided set empty, so the rate stays 0.00.

    PRD: "`acceptance_rate_pct` divides the accepted set — manuscripts at `IN_PRODUCTION`, `PUBLISHED`, `CORRECTED` or `RETRACTED` — by the decided set — manuscripts at `DESK_REJECTED`, `REJECTED`, `IN_PRODUCTION`, `PUBLISHED`, `CORRECTED` or `RETRACTED` — multiplies by 100 and rounds half up to 2 decimal places, yielding 0.00 when the decided set is empty; a retracted article still counts as accepted in both the numerator and the denominator, because it was accepted."

    Design: Difficulty/boundary_precision_check/fresh_journal_metrics_empty_collection_edges
    """
    world = fx.setup_under_review_manuscript()

    metrics = fx.get_journal_metrics(world["journal"]["id"])

    a.assert_fields(metrics, submitted_count=1, desk_rejected_count=0, published_count=0)
    a.assert_score_equals(metrics["acceptance_rate_pct"], 0.00, "acceptance_rate_pct")
    assert metrics["median_days_to_first_decision"] is None


def test_issuing_an_invoice_raises_the_receivable_ledger():
    """The receivable ledger rises by exactly the invoice's total.

    PRD: "Issuing the invoice raises the journal's `apc_receivable_cents` by the invoice's `total_due_cents` and advances the manuscript's `version` by 1."

    Design: Difficulty/compensating_invariant/journal_apc_receivable_conserved_by_invoice_cancel
    """
    world = fx.setup_issued_invoice_without_production_job()

    a.assert_journal_ledgers(world["journal_before"], apc_receivable_cents=0)
    a.assert_invoice_amounts(world["invoice"], total_due_cents=180000)
    a.assert_journal_ledgers(
        world["journal_while_issued"], apc_receivable_cents=180000, apc_waived_cents=0
    )


def test_cancelling_an_invoice_restores_the_receivable_ledger():
    """Cancellation returns the receivable to its pre-issue value and leaves the waiver ledger alone.

    PRD: "On success the invoice moves `ISSUED → CANCELLED` and the journal's `apc_receivable_cents` falls by `total_due_cents`, restoring the receivable ledger to its pre-issue value, while `apc_waived_cents` is untouched."

    Design: Difficulty/compensating_invariant/journal_apc_receivable_conserved_by_invoice_cancel
    """
    world = fx.setup_issued_invoice_without_production_job()

    fx.cancel_invoice(world["invoice"]["id"])

    invoice = fx.get_invoice(world["invoice"]["id"])
    a.assert_fields(invoice, status="CANCELLED", settled_at=CLOCK_EPOCH_MS)

    journal = fx.get_journal(world["journal"]["id"])
    a.assert_journal_ledgers(journal, apc_receivable_cents=0, apc_waived_cents=0)
    assert fx.get_manuscript(world["manuscript"]["id"])["status"] == "SUBMITTED"
