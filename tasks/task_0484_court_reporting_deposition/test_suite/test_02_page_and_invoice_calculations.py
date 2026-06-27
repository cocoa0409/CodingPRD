"""Page-rate, exhibit, and invoice-total calculations: the pinned tier ->
multiplier -> flat-fee order, the >50 marginal-tier boundary, the DAILY
multiplier, confidential-included exhibit aggregation, and total reconciliation.

The provisional quote uses estimated_pages; the frozen page_subtotal uses
final_pages set at certification (PRD §3.11).
"""
from test_helpers import (
    validate_success,
    assert_invoice_reconciles,
    setup_certified_transcript,
    setup_delivered_transcript,
    setup_adjourned_reporter_job,
    order_transcript,
    create_invoice,
    issue_invoice,
    setup_issued_invoice,
    make_attorney_headers,
    make_billing_clerk_headers,
)

BILLING = make_billing_clerk_headers()


def test_page_charge_provisional_quote_from_estimated_pages(api):
    """PRD §3.11: "Both use the same logic; they differ only in the page count fed
    in — the quote uses the order's `estimated_pages`, while the final charge uses
    the `final_pages` set at certification." STATE_CA EXPEDITE_14 certified,
    estimated_pages=40: tier1 40*325=13000, *1.25=16250, +2500=18750.

    Design: Difficulty/dual_variant_calc/page_charge_provisional_quote_vs_final_billed_on_transcript
    """
    sc, _ = setup_certified_transcript(
        jurisdiction="STATE_CA", turnaround_tier="EXPEDITE_14",
        certified_copy=True, estimated_pages=40, final_pages=60)
    quote = validate_success(api.get_transcript_quote(sc.transcript_order_id, BILLING))
    assert quote["provisional_page_cents"] == 18750, (
        f"CA EXPEDITE_14 cert est=40 quote should be 18750, got "
        f"{quote['provisional_page_cents']}")


def test_page_charge_final_billed_from_final_pages(api):
    """PRD §3.11: "the final charge uses the `final_pages` set at certification."
    PRD §3.14: "The `page_subtotal_cents` is the §3.11 page charge computed from
    the transcript's `final_pages`." STATE_CA EXPEDITE_14 certified, final_pages=60:
    tier1 50*325=16250, tier2 10*round(325*0.90=292.5->293)=2930, sum=19180,
    *1.25=23975, +2500=26475.

    Design: Difficulty/dual_variant_calc/page_charge_provisional_quote_vs_final_billed_on_transcript
    """
    sc, inv = setup_issued_invoice(
        jurisdiction="STATE_CA", turnaround_tier="EXPEDITE_14",
        certified_copy=True, final_pages=60, estimated_pages=40)
    assert inv["page_subtotal_cents"] == 26475, (
        f"CA EXPEDITE_14 cert final=60 page_subtotal should be 26475, got "
        f"{inv['page_subtotal_cents']}")
    to = validate_success(api.get_transcript_order(sc.transcript_order_id, BILLING))
    assert to["final_pages"] == 60, f"final_pages should be 60, got {to['final_pages']}"


def test_page_charge_tier_multiplier_flat_order_pinned(api):
    """PRD §3.11: "The per-tier marginal rate is rounded to a whole cent **before**
    it is multiplied by that tier's page count, and the three tier products are
    then summed to form the page base." PRD §3.11: "The expedite multiplier is
    applied **after** the tier sum... Last, and only if the order is a certified
    copy, a flat certification fee of 2500 cents is **added after** the multiplier
    (it is not multiplied by the expedite factor)." STATE_CA 200 pages EXPEDITE_7
    certified: 50*325 + 100*293 + 50*260 = 58550; *1.50=87825; +2500=90325.

    Design: Difficulty/combinatorial_formula/page_charge_tiered_then_multiplier_then_flat_mode_c
    """
    sc, inv = setup_issued_invoice(
        jurisdiction="STATE_CA", turnaround_tier="EXPEDITE_7",
        certified_copy=True, final_pages=200, estimated_pages=200)
    assert inv["page_subtotal_cents"] == 90325, (
        f"CA 200p EXPEDITE_7 cert page_subtotal should be 90325, got "
        f"{inv['page_subtotal_cents']}")


def test_page_tier_boundary_51_pages_crosses_into_tier2(api):
    """PRD §3.11: "the second tier covers the count of pages above 50 up to 150
    (zero if there are 50 or fewer)." PRD §3.11: "Pages 51 through 150 are charged
    at the base rate reduced by ten percent — that is, the base rate multiplied by
    0.90 and rounded half up to a whole cent, applied per page in that band."
    STATE_TX 51 STANDARD certified: 50*300 + 1*round(300*0.90=270)=15270; *1.0;
    +2500=17770.

    Design: Difficulty/boundary_precision_check/page_tier_boundary_50_vs_51_on_invoice_issue
    """
    sc, inv = setup_issued_invoice(
        jurisdiction="STATE_TX", turnaround_tier="STANDARD",
        certified_copy=True, final_pages=51, estimated_pages=51)
    assert inv["page_subtotal_cents"] == 17770, (
        f"TX 51p STANDARD cert page_subtotal should be 17770, got "
        f"{inv['page_subtotal_cents']}")


def test_page_tier_boundary_50_pages_tier1_only(api):
    """PRD §3.11: "The first 50 pages are charged at the full base rate." PRD
    §3.11: "the first tier covers up to 50 pages, the second tier covers the count
    of pages above 50 up to 150 (zero if there are 50 or fewer)." STATE_TX exactly
    50 STANDARD certified: 50*300=15000; *1.0; +2500=17500 (no tier-2 page).

    Design: Corner/calculations/page_charge_tier_boundary_50_pages_tier1_only
    """
    sc, inv = setup_issued_invoice(
        jurisdiction="STATE_TX", turnaround_tier="STANDARD",
        certified_copy=True, final_pages=50, estimated_pages=50)
    assert inv["page_subtotal_cents"] == 17500, (
        f"TX 50p STANDARD cert page_subtotal should be 17500, got "
        f"{inv['page_subtotal_cents']}")


def test_page_charge_daily_multiplier_applied(api):
    """PRD §3.11: "multiply the summed page base by the multiplier for the order's
    turnaround tier — 1.00 for `STANDARD`, 1.25 for `EXPEDITE_14`, 1.50 for
    `EXPEDITE_7`, 2.00 for `EXPEDITE_3`, and 3.00 for `DAILY`." STATE_CA 30 pages
    DAILY certified: round(30*325*3.00)=29250; +2500=31750.

    Design: Corner/calculations/page_charge_daily_tier_multiplier_applied
    """
    sc, inv = setup_issued_invoice(
        jurisdiction="STATE_CA", turnaround_tier="DAILY",
        certified_copy=True, final_pages=30, estimated_pages=30)
    assert inv["page_subtotal_cents"] == 31750, (
        f"CA 30p DAILY cert page_subtotal should be 31750, got "
        f"{inv['page_subtotal_cents']}")


def test_quote_read_uses_estimated_pages_endpoint(api):
    """PRD §3.12: "The provisional quote read returns two figures for a transcript
    order: a `provisional_page_cents` computed by the §3.11 logic from
    `estimated_pages`, and an `exhibit_cents` reflecting the exhibit charge
    described in §3.13." STATE_CA EXPEDITE_14 certified estimated_pages=40 returns
    provisional_page_cents==18750.

    Design: Corner/endpoints/transcript_quote_computed_read_uses_estimated_pages
    """
    sc = setup_adjourned_reporter_job(jurisdiction="STATE_CA")
    order_transcript(sc, turnaround_tier="EXPEDITE_14", certified_copy=True,
                     estimated_pages=40)
    quote = validate_success(api.get_transcript_quote(
        sc.transcript_order_id, make_attorney_headers(sc.attorney_id)))
    assert quote["provisional_page_cents"] == 18750, (
        f"CA EXPEDITE_14 cert est=40 quote should be 18750, got "
        f"{quote['provisional_page_cents']}")


def test_exhibit_charge_sums_all_pages_confidential_included(api):
    """PRD §3.13: "Sum the `page_count` across **all** exhibits attached to the
    transcript order — there is no status filter and, importantly, confidential
    exhibits are included in this billing total even though they are withheld from
    the default e-delivery bundle — and multiply that total page count by the
    exhibit per-page rate of 75 cents in a single multiplication with no
    intermediate rounding." Exhibits 12 (public) + 8 (confidential) => 20*75=1500.

    Design: Corner/calculations/exhibit_charge_sums_all_pages_confidential_included
    """
    sc, inv = setup_issued_invoice(
        jurisdiction="STATE_NY", turnaround_tier="STANDARD",
        certified_copy=True, final_pages=40, estimated_pages=40,
        exhibits=[("Exhibit 1", 12, False), ("Exhibit 2", 8, True)])
    assert inv["exhibit_subtotal_cents"] == 1500, (
        f"(12+8)*75 exhibit_subtotal should be 1500, got {inv['exhibit_subtotal_cents']}")
    assert inv["total_cents"] == 40000, (
        f"NY 40p cert + 2h@10000 + 1500 exhibit total should be 40000, got "
        f"{inv['total_cents']}")


def test_invoice_total_reconciles_from_three_subtotals(api):
    """PRD §3.14: "The reconciled `total_cents` is the plain sum of the three
    already-rounded subtotals — appearance plus page plus exhibit — with no
    further rounding." NY 40p STANDARD certified, reporter 2h @10000, exhibits
    12+8: appearance 20000, page 18500, exhibit 1500, total 40000.

    Design: Corner/cross_cutting_complexity_layers/derived_invoice_total_reconciles_from_subtotals
    """
    sc, inv = setup_issued_invoice(
        jurisdiction="STATE_NY", turnaround_tier="STANDARD",
        certified_copy=True, final_pages=40, estimated_pages=40,
        hourly_appearance_cents=10000,
        exhibits=[("Exhibit 1", 12, False), ("Exhibit 2", 8, True)])
    assert inv["appearance_subtotal_cents"] == 20000, (
        f"appearance_subtotal should be 20000, got {inv['appearance_subtotal_cents']}")
    assert inv["page_subtotal_cents"] == 18500, (
        f"page_subtotal should be 18500, got {inv['page_subtotal_cents']}")
    assert inv["exhibit_subtotal_cents"] == 1500, (
        f"exhibit_subtotal should be 1500, got {inv['exhibit_subtotal_cents']}")
    assert inv["total_cents"] == 40000, (
        f"total should be 40000, got {inv['total_cents']}")
    assert_invoice_reconciles(inv)
