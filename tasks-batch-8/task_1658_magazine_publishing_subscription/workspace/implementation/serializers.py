"""Entity serializers: explicit output field whitelists per resource.

Primary resources carry id/created_at/updated_at/version (PRD 2.5).
Ledger-style snapshots (MailingLabel, PostalStatement, DeferredRevenueEntry)
carry only id/created_at -- updated_at and version are absent entirely.
Internal bookkeeping keys are prefixed with "_" and never serialized.
"""

from util import iso


def _dt(value):
    return iso(value) if value is not None else None


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def _ledger(rec):
    return {"id": rec["id"], "created_at": iso(rec["created_at"])}


def ser_publication(p):
    out = _common(p)
    out.update(
        {
            "title": p["title"],
            "issn": p["issn"],
            "frequency": p["frequency"],
            "circulation_model": p["circulation_model"],
            "issues_per_year": p["issues_per_year"],
            "base_cover_price_cents": p["base_cover_price_cents"],
            "deferred_revenue_method": p["deferred_revenue_method"],
            "status": p["status"],
            "flagged_for_audit": p["flagged_for_audit"],
        }
    )
    return out


def ser_issue(i):
    out = _common(i)
    out.update(
        {
            "publication_id": i["publication_id"],
            "issue_number": i["issue_number"],
            "volume_number": i["volume_number"],
            "cover_date": _dt(i["cover_date"]),
            "editorial_close_date": _dt(i["editorial_close_date"]),
            "ad_close_date": _dt(i["ad_close_date"]),
            "ship_to_printer_date": _dt(i["ship_to_printer_date"]),
            "mail_date": _dt(i["mail_date"]),
            "ad_pages_sold": i["ad_pages_sold"],
            "total_pages": i["total_pages"],
            "print_run_override": i["print_run_override"],
            "print_run": i["print_run"],
            "qualified_subscriber_count": i["qualified_subscriber_count"],
            "newsstand_buffer_copies": i["newsstand_buffer_copies"],
            "revenue_recognized_cents": i["revenue_recognized_cents"],
            "status": i["status"],
        }
    )
    return out


def ser_subscriber(s):
    out = _common(s)
    out.update(
        {
            "email": s["email"],
            "full_name": s["full_name"],
            "address_line1": s["address_line1"],
            "address_line2": s["address_line2"],
            "city": s["city"],
            "state_code": s["state_code"],
            "postal_code": s["postal_code"],
            "country_code": s["country_code"],
            "is_deliverable": s["is_deliverable"],
            "circulation_class": s["circulation_class"],
        }
    )
    return out


def ser_subscription(s):
    out = _common(s)
    out.update(
        {
            "subscriber_id": s["subscriber_id"],
            "publication_id": s["publication_id"],
            "start_issue_id": s["start_issue_id"],
            "term_issues": s["term_issues"],
            "price_paid_cents": s["price_paid_cents"],
            "qualification_tier": s["qualification_tier"],
            "payment_method": s["payment_method"],
            "is_gift": s["is_gift"],
            "donor_subscriber_id": s["donor_subscriber_id"],
            "renewal_series_code": s["renewal_series_code"],
            "renewal_effort_number": s["renewal_effort_number"],
            "issues_served": s["issues_served"],
            "issues_remaining": s["issues_remaining"],
            "issues_suspended_count": s["issues_suspended_count"],
            "auto_renew": s["auto_renew"],
            "expire_action": s["expire_action"],
            "status": s["status"],
        }
    )
    return out


def ser_term(t):
    out = _common(t)
    out.update(
        {
            "subscription_id": t["subscription_id"],
            "term_index": t["term_index"],
            "term_start_issue_id": t["term_start_issue_id"],
            "term_end_issue_id": t["term_end_issue_id"],
            "issues_in_term": t["issues_in_term"],
            "gross_amount_cents": t["gross_amount_cents"],
            "deferred_balance_cents": t["deferred_balance_cents"],
            "recognized_balance_cents": t["recognized_balance_cents"],
            "recognition_variant": t["recognition_variant"],
            "status": t["status"],
        }
    )
    return out


def ser_renewal_series(r):
    out = _common(r)
    out.update(
        {
            "publication_id": r["publication_id"],
            "series_code": r["series_code"],
            "effort_offsets_days": r["effort_offsets_days"],
            "effort_pricing_cents": r["effort_pricing_cents"],
            "max_efforts": r["max_efforts"],
            "is_default": r["is_default"],
        }
    )
    return out


def ser_renewal_event(e):
    out = _common(e)
    out.update(
        {
            "subscription_id": e["subscription_id"],
            "series_code": e["series_code"],
            "effort_number": e["effort_number"],
            "sent_at": _dt(e["sent_at"]),
            "offered_price_cents": e["offered_price_cents"],
            "response": e["response"],
            "responded_at": _dt(e["responded_at"]),
        }
    )
    return out


def ser_batch(b):
    out = _common(b)
    out.update(
        {
            "issue_id": b["issue_id"],
            "batch_label": b["batch_label"],
            "postal_class": b["postal_class"],
            "entry_point": b["entry_point"],
            "expected_piece_count": b["expected_piece_count"],
            "total_postage_cents": b["total_postage_cents"],
            "permit_number": b["permit_number"],
            "is_controlled_copy_included": b["is_controlled_copy_included"],
            "status": b["status"],
        }
    )
    return out


def ser_label(lbl):
    out = _ledger(lbl)
    out.update(
        {
            "batch_id": lbl["batch_id"],
            "subscription_id": lbl["subscription_id"],
            "subscriber_id": lbl["subscriber_id"],
            "address_block": lbl["address_block"],
            "postal_code": lbl["postal_code"],
            "is_controlled_copy": lbl["is_controlled_copy"],
            "piece_weight_oz": lbl["piece_weight_oz"],
            "postage_cents": lbl["postage_cents"],
        }
    )
    return out


def ser_postal_statement(ps):
    out = _ledger(ps)
    out.update(
        {
            "batch_id": ps["batch_id"],
            "form_number": ps["form_number"],
            "paid_piece_count": ps["paid_piece_count"],
            "controlled_piece_count": ps["controlled_piece_count"],
            "paid_percentage_bps": ps["paid_percentage_bps"],
            "advertising_percentage_bps": ps["advertising_percentage_bps"],
            "total_postage_cents": ps["total_postage_cents"],
            "filed_at": _dt(ps["filed_at"]),
        }
    )
    return out


def ser_back_issue_order(o):
    out = _common(o)
    out.update(
        {
            "subscriber_id": o["subscriber_id"],
            "issue_id": o["issue_id"],
            "quantity": o["quantity"],
            "unit_price_cents": o["unit_price_cents"],
            "shipping_cents": o["shipping_cents"],
            "total_charged_cents": o["total_charged_cents"],
            "is_recognized_revenue": o["is_recognized_revenue"],
            "status": o["status"],
        }
    )
    return out


def ser_entitlement(e):
    out = _common(e)
    out.update(
        {
            "subscription_id": e["subscription_id"],
            "issue_id": e["issue_id"],
            "access_level": e["access_level"],
            "granted_at": _dt(e["granted_at"]),
            "revoked_at": _dt(e["revoked_at"]),
            "revocation_reason": e["revocation_reason"],
        }
    )
    return out


def ser_revenue_entry(e):
    out = _ledger(e)
    out.update(
        {
            "subscription_term_id": e["subscription_term_id"],
            "issue_id": e["issue_id"],
            "recognized_at": _dt(e["recognized_at"]),
            "amount_cents": e["amount_cents"],
            "variant": e["variant"],
            "entry_type": e["entry_type"],
        }
    )
    return out


def ser_audit(a):
    out = _common(a)
    out.update(
        {
            "publication_id": a["publication_id"],
            "audit_period_start": _dt(a["audit_period_start"]),
            "audit_period_end": _dt(a["audit_period_end"]),
            "total_distribution": a["total_distribution"],
            "paid_distribution": a["paid_distribution"],
            "controlled_distribution": a["controlled_distribution"],
            "paid_percentage_bps": a["paid_percentage_bps"],
            "qualification_result": a["qualification_result"],
            "status": a["status"],
        }
    )
    return out
