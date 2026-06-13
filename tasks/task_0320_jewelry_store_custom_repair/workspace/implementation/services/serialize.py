"""Serialize internal records into API output (drops internal keys like _seq).

Each function emits exactly the fields declared by the entity in SCAFFOLD §1.1,
plus the system/common fields per PRD §2.4. Append-only records (Payment,
CreditLedgerEntry) expose only id + created_at and the declared input fields.
"""

_COMMON = ("created_at", "updated_at", "version")


def _emit(rec, fields, common=True):
    out = {"id": rec["id"]}
    for f in fields:
        out[f] = rec.get(f)
    if common:
        for c in _COMMON:
            out[c] = rec.get(c)
    else:
        out["created_at"] = rec.get("created_at")
    return out


def customer(rec):
    return _emit(rec, ["full_name", "email", "phone", "store_credit_balance_cents", "status"])


def inventory_item(rec):
    return _emit(rec, ["sku", "title", "metal_karat", "list_price_cents",
                       "latest_appraised_value_cents", "status"])


def workbench(rec):
    return _emit(rec, ["label", "status"])


def appraisal(rec):
    return _emit(rec, ["inventory_item_id", "appraiser_name", "appointment_start",
                       "appointment_end", "market_value_cents", "replacement_factor",
                       "replacement_value_cents", "document_number", "status"])


def custom_order(rec):
    return _emit(rec, ["customer_id", "description", "estimated_materials_cents",
                       "design_fee_cents", "provisional_total_cents", "deposit_required_cents",
                       "deposit_paid_cents", "final_total_cents", "balance_due_cents",
                       "line_items", "revision_count", "status"])


def repair_ticket(rec):
    return _emit(rec, ["customer_id", "inventory_item_id", "repair_kind", "parts_cents",
                       "labor_cents", "rush", "rush_surcharge_cents", "total_cents",
                       "promised_at", "bench_id", "scheduled_start", "scheduled_end",
                       "warranty_claim_id", "status"])


def layaway_plan(rec):
    return _emit(rec, ["customer_id", "inventory_item_id", "item_price_cents",
                       "down_payment_cents", "installment_count", "installment_amount_cents",
                       "paid_to_date_cents", "projected_payoff_cents", "settlement_refund_cents",
                       "restocking_fee_cents", "status"])


def trade_in(rec):
    return _emit(rec, ["customer_id", "metal_karat", "metal_weight_grams",
                       "metal_spot_price_cents_per_gram", "gemstone_value_cents", "condition",
                       "metal_value_cents", "buyback_credit_cents", "credit_ledger_entry_id",
                       "status"])


def special_order(rec):
    return _emit(rec, ["customer_id", "vendor_name", "catalog_ref", "quoted_price_cents",
                       "deposit_required_cents", "deposit_paid_cents",
                       "received_inventory_item_id", "status"])


def payment(rec):
    return _emit(rec, ["target_type", "custom_order_id", "layaway_plan_id",
                       "special_order_id", "amount_cents", "outcome"], common=False)


def warranty_claim(rec):
    return _emit(rec, ["inventory_item_id", "customer_id", "defect_description",
                       "spawned_repair_ticket_id", "status"])


def credit_ledger_entry(rec):
    return _emit(rec, ["customer_id", "direction", "amount_cents", "reason"], common=False)
