from util import fmt_dt3


def _dt(rec, field):
    v = getattr(rec, field, None)
    if v is None:
        return None
    raw = rec.raw.get(field)
    return raw if raw is not None else fmt_dt3(v)


def _common(rec):
    return {
        "id": rec.id,
        "created_at": _dt(rec, "created_at"),
        "updated_at": _dt(rec, "updated_at"),
        "version": rec.version,
    }


def ser_customer(r):
    d = _common(r)
    d.update({
        "email": r.email,
        "full_name": r.full_name,
        "climate_zone": r.climate_zone,
        "referral_code": r.referral_code,
        "credit_balance_cents": r.credit_balance_cents,
        "status": r.status,
    })
    return d


def ser_lawn(r):
    d = _common(r)
    d.update({
        "customer_id": r.customer_id,
        "label": r.label,
        "lawn_size_sqm": r.lawn_size_sqm,
        "grass_type": r.grass_type,
        "region": r.region,
        "status": r.status,
    })
    return d


def ser_soil_test(r):
    d = _common(r)
    d.update({
        "lawn_id": r.lawn_id,
        "status": r.status,
        "reship_count": r.reship_count,
        "rejection_reason": r.rejection_reason,
        "ph": r.ph,
        "nitrogen_ppm": r.nitrogen_ppm,
        "phosphorus_ppm": r.phosphorus_ppm,
        "potassium_ppm": r.potassium_ppm,
        "organic_matter_pct": r.organic_matter_pct,
        "analyzed_at": _dt(r, "analyzed_at"),
    })
    return d


def ser_plan(r):
    d = _common(r)
    d.update({
        "lawn_id": r.lawn_id,
        "soil_test_id": r.soil_test_id,
        "season_year": r.season_year,
        "plan_lines": r.plan_lines,
        "status": r.status,
        "provisional_value_cents": r.provisional_value_cents,
        "committed_value_cents": r.committed_value_cents,
        "discount_pct_locked": r.discount_pct_locked,
        "supersedes_plan_id": r.supersedes_plan_id,
        "activated_at": _dt(r, "activated_at"),
    })
    return d


def ser_subscription(r):
    d = _common(r)
    d.update({
        "customer_id": r.customer_id,
        "plan_id": r.plan_id,
        "billing_cycle": r.billing_cycle,
        "auto_ship": r.auto_ship,
        "status": r.status,
        "next_ship_date": _dt(r, "next_ship_date"),
        "skips_used_in_window": r.skips_used_in_window,
        "skip_window_anchor": _dt(r, "skip_window_anchor"),
    })
    return d


def ser_shipment(r):
    d = _common(r)
    d.update({
        "subscription_id": r.subscription_id,
        "box_kind": r.box_kind,
        "fulfillment_status": r.fulfillment_status,
        "billing_status": r.billing_status,
        "ship_date": _dt(r, "ship_date"),
        "delivery_window_start": _dt(r, "delivery_window_start"),
        "delivery_window_end": _dt(r, "delivery_window_end"),
        "lines": r.lines,
        "provisional_charge_cents": r.provisional_charge_cents,
        "final_charge_cents": r.final_charge_cents,
        "delivered_at": _dt(r, "delivered_at"),
        "source_claim_id": r.source_claim_id,
    })
    return d


def ser_application(r):
    d = _common(r)
    d.update({
        "lawn_id": r.lawn_id,
        "subscription_id": r.subscription_id,
        "shipment_id": r.shipment_id,
        "product_sku": r.product_sku,
        "scheduled_date": r.scheduled_date,
        "status": r.status,
        "window_start_date": r.window_start_date,
        "window_end_date": r.window_end_date,
        "snooze_count": r.snooze_count,
        "applied_at": _dt(r, "applied_at"),
    })
    return d


def ser_advisory(r):
    d = _common(r)
    d.update({
        "region": r.region,
        "date": r.date,
        "rain_probability": r.rain_probability,
        "wind_kph": r.wind_kph,
        "temp_high_c": r.temp_high_c,
    })
    return d


def ser_addon(r):
    d = _common(r)
    d.update({
        "subscription_id": r.subscription_id,
        "add_on_sku": r.add_on_sku,
        "qty_units": r.qty_units,
        "status": r.status,
        "quoted_price_cents": r.quoted_price_cents,
        "quote_expires_at": _dt(r, "quote_expires_at"),
        "attached_shipment_id": r.attached_shipment_id,
    })
    return d


def ser_claim(r):
    d = _common(r)
    d.update({
        "subscription_id": r.subscription_id,
        "shipment_id": r.shipment_id,
        "claim_reason": r.claim_reason,
        "evidence_url": r.evidence_url,
        "status": r.status,
        "resolution_type": r.resolution_type,
        "credit_amount_cents": r.credit_amount_cents,
        "filed_at": _dt(r, "filed_at"),
    })
    return d


def ser_referral(r):
    d = _common(r)
    d.update({
        "referrer_customer_id": r.referrer_customer_id,
        "referee_customer_id": r.referee_customer_id,
        "referral_code_used": r.referral_code_used,
        "status": r.status,
        "provisional_credit_cents": r.provisional_credit_cents,
        "qualified_credit_cents": r.qualified_credit_cents,
        "referee_first_invoice_id": r.referee_first_invoice_id,
    })
    return d


def ser_invoice(r):
    d = _common(r)
    d.update({
        "subscription_id": r.subscription_id,
        "shipment_id": r.shipment_id,
        "line_items": r.line_items,
        "subtotal_cents": r.subtotal_cents,
        "credit_applied_cents": r.credit_applied_cents,
        "total_cents": r.total_cents,
        "status": r.status,
        "issued_at": _dt(r, "issued_at"),
    })
    return d


def ser_ledger_entry(r):
    # Append-only record: only id and created_at, no updated_at / version (PRD 2.4).
    return {
        "id": r.id,
        "created_at": _dt(r, "created_at"),
        "customer_id": r.customer_id,
        "entry_type": r.entry_type,
        "amount_cents": r.amount_cents,
        "reference_id": r.reference_id,
        "note": r.note,
    }


def ser_product(r):
    d = _common(r)
    d.update({
        "sku": r.sku,
        "name": r.name,
        "category": r.category,
        "list_price_cents": r.list_price_cents,
        "tier_t1_cents": r.tier_t1_cents,
        "tier_t2_cents": r.tier_t2_cents,
        "tier_t3_cents": r.tier_t3_cents,
        "add_on_flat_price_cents": r.add_on_flat_price_cents,
        "window_start_md": r.window_start_md,
        "window_end_md": r.window_end_md,
        "conflicting_categories": r.conflicting_categories,
        "min_gap_days": r.min_gap_days,
        "active": r.active,
    })
    return d
