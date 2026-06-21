"""Public JSON serializers for each entity.

Full entities carry id/created_at/updated_at/version. TransactionLineItem and
AuditLogEntry carry only id/created_at (PRD §2.4).
"""
import db


def _full_meta(r):
    return {
        "id": r["id"],
        "created_at": db.iso(r["created_at"]),
        "updated_at": db.iso(r["updated_at"]),
        "version": r["version"],
    }


def _light_meta(r):
    return {"id": r["id"], "created_at": db.iso(r["created_at"])}


def jurisdiction(r):
    out = _full_meta(r)
    out.update({
        "state_code": r["state_code"],
        "sourcing_rule": r["sourcing_rule"],
        "state_rate": r["state_rate"],
        "local_rate": r["local_rate"],
        "reduced_rate": r["reduced_rate"],
        "economic_nexus_sales_threshold": r["economic_nexus_sales_threshold"],
        "economic_nexus_txn_threshold": r["economic_nexus_txn_threshold"],
        "combined_rate": r["combined_rate"],
    })
    return out


def product_category(r):
    out = _full_meta(r)
    out.update({
        "jurisdiction_id": r["jurisdiction_id"],
        "category_code": r["category_code"],
        "taxability": r["taxability"],
    })
    return out


def seller(r):
    out = _full_meta(r)
    out.update({
        "legal_name": r["legal_name"],
        "origin_state_code": r["origin_state_code"],
        "status": r["status"],
    })
    return out


def nexus_profile(r):
    out = _full_meta(r)
    out.update({
        "seller_id": r["seller_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "cumulative_taxable_sales": r["cumulative_taxable_sales"],
        "cumulative_txn_count": r["cumulative_txn_count"],
        "nexus_status": r["nexus_status"],
        "registered_at": db.iso(r["registered_at"]) if r["registered_at"] else None,
    })
    return out


def exemption_certificate(r):
    out = _full_meta(r)
    out.update({
        "seller_id": r["seller_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "customer_ref": r["customer_ref"],
        "exempt_category_code": r["exempt_category_code"],
        "valid_from": db.iso(r["valid_from"]),
        "valid_to": db.iso(r["valid_to"]),
        "status": r["status"],
    })
    return out


def marketplace_facilitator(r):
    out = _full_meta(r)
    out.update({
        "name": r["name"],
        "collecting_state_codes": list(r["collecting_state_codes"]),
    })
    return out


def transaction(r):
    out = _full_meta(r)
    out.update({
        "seller_id": r["seller_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "facilitator_id": r["facilitator_id"],
        "customer_ref": r["customer_ref"],
        "customer_exempt_requested": r["customer_exempt_requested"],
        "sourcing_used": r["sourcing_used"],
        "applied_rate": r["applied_rate"],
        "taxable_subtotal": r["taxable_subtotal"],
        "tax_collected": r["tax_collected"],
        "remittance_responsibility": r["remittance_responsibility"],
        "settlement_status": r["settlement_status"],
        "audit_status": r["audit_status"],
        "tax_return_id": r["tax_return_id"],
    })
    return out


def line_item(r):
    out = _light_meta(r)
    out.update({
        "transaction_id": r["transaction_id"],
        "category_code": r["category_code"],
        "quantity": r["quantity"],
        "unit_price": r["unit_price"],
        "line_taxability": r["line_taxability"],
        "line_tax": r["line_tax"],
    })
    return out


def use_tax_accrual(r):
    out = _full_meta(r)
    out.update({
        "seller_id": r["seller_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "purchase_amount": r["purchase_amount"],
        "accrued_use_tax": r["accrued_use_tax"],
        "status": r["status"],
        "tax_return_id": r["tax_return_id"],
    })
    return out


def tax_return(r):
    out = _full_meta(r)
    out.update({
        "seller_id": r["seller_id"],
        "jurisdiction_id": r["jurisdiction_id"],
        "period_start": db.iso(r["period_start"]),
        "period_end": db.iso(r["period_end"]),
        "prepared_by": r["prepared_by"],
        "approved_by": r["approved_by"],
        "tax_due": r["tax_due"],
        "status": r["status"],
    })
    return out


def remittance_payment(r):
    out = _full_meta(r)
    out.update({
        "tax_return_id": r["tax_return_id"],
        "amount": r["amount"],
        "status": r["status"],
    })
    return out


def audit_log_entry(r):
    out = _light_meta(r)
    out.update({
        "seller_id": r["seller_id"],
        "subject_entity": r["subject_entity"],
        "subject_id": r["subject_id"],
        "action": r["action"],
        "actor_role": r["actor_role"],
        "actor_id": r["actor_id"],
    })
    return out
