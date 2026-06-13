"""Serializers — project stored entity dicts to API response shapes.

Stored entities already hold their computed/system fields up to date (recomputes
run synchronously in the request that mutates inputs), so serialization is mostly
a field projection. Recall computed counters are returned directly from stored
fields which are kept fresh by the recompute helpers in services.py.
"""


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def product_out(e):
    out = _common(e)
    out.update({
        "sku": e["sku"],
        "name": e["name"],
        "regulator": e["regulator"],
        "unit_list_price_cents": e["unit_list_price_cents"],
        "active_recall_id": e["active_recall_id"],
    })
    return out


def lot_out(e):
    out = _common(e)
    out.update({
        "product_id": e["product_id"],
        "lot_code": e["lot_code"],
        "serial_start": e["serial_start"],
        "serial_end": e["serial_end"],
        "manufactured_units": e["manufactured_units"],
        "quarantine_status": e["quarantine_status"],
    })
    return out


def unit_out(e):
    out = _common(e)
    out.update({
        "lot_id": e["lot_id"],
        "serial_number": e["serial_number"],
        "customer_id": e["customer_id"],
        "sale_price_cents": e["sale_price_cents"],
        "affected": e["affected"],
    })
    return out


def customer_out(e):
    out = _common(e)
    out.update({
        "name": e["name"],
        "contact_channel": e["contact_channel"],
        "contact_address": e["contact_address"],
        "reachable": e["reachable"],
    })
    return out


def recall_out(e):
    out = _common(e)
    out.update({
        "product_id": e["product_id"],
        "reason": e["reason"],
        "hazard_severity": e["hazard_severity"],
        "injury_reported": e["injury_reported"],
        "serial_filter_start": e["serial_filter_start"],
        "serial_filter_end": e["serial_filter_end"],
        "classification": e["classification"],
        "classified_by_user_id": e["classified_by_user_id"],
        "approved_by_user_id": e["approved_by_user_id"],
        "status": e["status"],
        "notification_deadline_hours": e["notification_deadline_hours"],
        "affected_unit_count": e["affected_unit_count"],
        "recovered_unit_count": e["recovered_unit_count"],
        "effectiveness_pct": e["effectiveness_pct"],
        "total_refund_cents": e["total_refund_cents"],
    })
    return out


def affected_lot_out(e):
    # Immutable junction row: only id + created_at (no updated_at, no version).
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "recall_id": e["recall_id"],
        "lot_id": e["lot_id"],
        "unit_count_snapshot": e["unit_count_snapshot"],
    }


def quarantine_hold_out(e):
    out = _common(e)
    out.update({
        "recall_id": e["recall_id"],
        "lot_id": e["lot_id"],
        "reason": e["reason"],
        "status": e["status"],
        "lifted_count": e["lifted_count"],
    })
    return out


def notification_out(e):
    out = _common(e)
    out.update({
        "recall_id": e["recall_id"],
        "customer_id": e["customer_id"],
        "channel": e["channel"],
        "status": e["status"],
        "attempt_count": e["attempt_count"],
    })
    return out


def disposition_out(e):
    out = _common(e)
    out.update({
        "recall_id": e["recall_id"],
        "unit_id": e["unit_id"],
        "disposition_type": e["disposition_type"],
        "logistics_status": e["logistics_status"],
        "financial_status": e["financial_status"],
        "refund_basis": e["refund_basis"],
        "refund_amount_cents": e["refund_amount_cents"],
    })
    return out


def regulatory_report_out(e):
    out = _common(e)
    out.update({
        "recall_id": e["recall_id"],
        "agency": e["agency"],
        "report_kind": e["report_kind"],
        "filed_within_deadline": e["filed_within_deadline"],
        "status": e["status"],
        "signed_by_user_id": e["signed_by_user_id"],
    })
    return out


def effectiveness_check_out(e):
    out = _common(e)
    out.update({
        "recall_id": e["recall_id"],
        "target_pct": e["target_pct"],
        "measured_pct": e["measured_pct"],
        "outcome": e["outcome"],
    })
    return out
