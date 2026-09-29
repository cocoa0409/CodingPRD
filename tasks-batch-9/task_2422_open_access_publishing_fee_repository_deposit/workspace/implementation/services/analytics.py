"""annual_spend_and_negotiation_analytics (PRD 3.9)."""
from db import db
from services.determination import effective_determination
from util import (
    dec,
    fiscal_year_window,
    parse_iso_date,
    round_half_up,
    round_half_up_places,
)

TA_ROUTES = ("TA_FULL", "TA_CAPPED")


def annual_spend(fiscal_year, basis, publisher_id=None):
    fy_from, fy_to = fiscal_year_window(fiscal_year)

    # ---- allocation ledger
    total_committed_cents = 0
    total_disbursed_cents = 0
    for allocation in db.allocations.values():
        fund = db.funds.get(allocation["fund_id"])
        if fund is None or fund["fiscal_year"] != fiscal_year:
            continue
        if allocation["status"] == "ENCUMBERED":
            total_committed_cents += allocation["amount_cents"]
        elif allocation["status"] == "DISBURSED":
            total_disbursed_cents += allocation["amount_cents"]
    if basis == "ENCUMBRANCE":
        total_allocated_cents = total_committed_cents + total_disbursed_cents
    else:
        total_allocated_cents = total_disbursed_cents

    # ---- invoice ledger
    paid = []
    for invoice in db.invoices.values():
        if invoice["status"] != "PAID":
            continue
        invoice_date = parse_iso_date(invoice["invoice_date"])
        if invoice_date < fy_from or invoice_date > fy_to:
            continue
        if publisher_id is not None and invoice["publisher_id"] != publisher_id:
            continue
        paid.append(invoice)
    paid_invoice_count = len(paid)
    if paid_invoice_count == 0:
        avg_paid_net_cents = 0
    else:
        avg_paid_net_cents = round_half_up(
            dec(sum(i["net_cents"] or 0 for i in paid)) / dec(paid_invoice_count)
        )

    # ---- determination ledger
    ta_articles_covered = 0
    ta_savings_cents = 0
    hybrid_article_count = 0
    fully_oa_article_count = 0
    for article in db.articles.values():
        accepted = parse_iso_date(article["accepted_on"])
        if accepted is None or accepted < fy_from or accepted > fy_to:
            continue
        determination = effective_determination(article["id"])
        if determination is None:
            continue
        if determination["route"] in TA_ROUTES:
            ta_articles_covered += 1
            ta_savings_cents += (
                determination["list_base_cents"]
                - determination["covered_amount_cents"]
                - determination["author_share_cents"]
            )
        journal = db.journals.get(article["journal_id"])
        if journal is not None:
            if journal["oa_model"] == "HYBRID":
                hybrid_article_count += 1
            elif journal["oa_model"] == "FULLY_OA":
                fully_oa_article_count += 1

    # ---- top publisher by paid net spend
    net_by_publisher = {}
    for invoice in paid:
        net_by_publisher[invoice["publisher_id"]] = (
            net_by_publisher.get(invoice["publisher_id"], 0) + (invoice["net_cents"] or 0)
        )
    top_publisher_code = None
    if net_by_publisher:
        ranked = sorted(
            net_by_publisher.items(),
            key=lambda pair: (
                -pair[1],
                db.publishers[pair[0]]["publisher_code"] if pair[0] in db.publishers else "",
            ),
        )
        winner_id = ranked[0][0]
        publisher = db.publishers.get(winner_id)
        top_publisher_code = publisher["publisher_code"] if publisher else None

    ratio = round_half_up_places(
        dec(ta_savings_cents) / dec(max(1, total_disbursed_cents)), 4
    )

    return {
        "fiscal_year": fiscal_year,
        "basis": basis,
        "total_allocated_cents": total_allocated_cents,
        "total_committed_cents": total_committed_cents,
        "total_disbursed_cents": total_disbursed_cents,
        "paid_invoice_count": paid_invoice_count,
        "avg_paid_net_cents": avg_paid_net_cents,
        "ta_articles_covered": ta_articles_covered,
        "ta_savings_cents": ta_savings_cents,
        "hybrid_article_count": hybrid_article_count,
        "fully_oa_article_count": fully_oa_article_count,
        "top_publisher_code": top_publisher_code,
        "negotiation_leverage_ratio": float(ratio),
    }
