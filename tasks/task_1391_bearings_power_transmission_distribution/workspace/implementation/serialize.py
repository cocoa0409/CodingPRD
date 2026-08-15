"""Entity serializers — whitelist exactly the scaffold fields; internal
fields are underscore-prefixed and never leak. Datetimes rendered with 3
fractional digits; derived fields computed at read time."""

import domain
from helpers import render_dt

DT_FIELDS = {
    "Product": ["last_price_change_at"],
    "CustomerContract": ["effective_from", "effective_to"],
    "PriceFileVersion": ["effective_at"],
    "SalesOrder": ["priced_at"],
    "OrderLine": ["factory_ordered_at", "shipped_at"],
    "StockReservation": ["expires_at"],
    "ConsignmentConsumption": ["reported_at"],
    "ReturnAuthorization": ["approved_at"],
}

FIELDS = {
    "Product": ["sku", "description", "family", "list_price_cents",
                "last_price_change_at", "superseded_by_id", "status"],
    "InterchangeRecord": ["competitor_part_number", "product_id", "interchange_class",
                          "min_shaft_diameter_mm", "max_shaft_diameter_mm",
                          "requires_engineering_review"],
    "CustomerAccount": ["name", "credit_limit_cents", "credit_status", "status"],
    "CustomerContract": ["customer_id", "family", "price_basis", "discount_pct",
                         "fixed_unit_price_cents", "lag_protection_days",
                         "effective_from", "effective_to", "status"],
    "Branch": ["code", "timezone_offset_hours", "business_open_hour",
               "business_close_hour", "expedite_cutoff_hour",
               "after_hours_fee_cents", "status"],
    "BranchStock": ["branch_id", "product_id", "on_hand_qty",
                    "factory_lead_time_days", "reorder_point"],
    "PriceFileVersion": ["product_id", "new_list_price_cents", "effective_at",
                         "published_by", "status"],
    "SalesOrder": ["customer_id", "branch_id", "price_variant", "fulfillment_status",
                   "billing_status", "subtotal_cents", "expedite_fees_cents",
                   "total_cents", "paid_cents", "priced_at"],
    "OrderLine": ["order_id", "product_id", "qty", "expedite_tier",
                  "unit_price_cents", "price_protection_applied",
                  "expedite_fee_cents", "line_total_cents", "factory_ordered_at",
                  "shipped_at", "sourcing_status"],
    "StockReservation": ["order_line_id", "branch_stock_id", "qty", "expires_at",
                         "status"],
    "CallOut": ["branch_id", "customer_id", "product_id", "qty",
                "call_out_fee_cents", "parts_amount_cents", "total_charge_cents",
                "responder_id", "preempted_reservation_ids", "status"],
    "ConsignmentAgreement": ["customer_id", "branch_id", "product_id",
                             "consigned_qty", "pinned_unit_price_cents",
                             "billing_variant", "status"],
    "ConsignmentConsumption": ["agreement_id", "qty", "reported_at",
                               "unit_price_cents", "billed_amount_cents",
                               "offset_applied_cents", "status"],
    "WarrantyClaim": ["product_id", "order_line_id", "consumption_id", "filed_by",
                      "failure_mode", "operating_hours", "qty", "verdict",
                      "verdict_by", "coverage_pct", "credit_amount_cents", "status"],
    "ReturnAuthorization": ["customer_id", "product_id", "branch_id", "qty",
                            "condition", "original_unit_price_cents", "requested_by",
                            "approved_by", "eligible_credit_cents",
                            "write_down_cents", "offset_applied_cents",
                            "credit_memo_cents", "received_qty", "approved_at",
                            "status"],
    "ServiceShop": ["name", "capabilities", "region", "labor_rate_cents", "status"],
    "ServiceReferral": ["warranty_claim_id", "service_shop_id", "region",
                        "quoted_amount_cents", "referral_fee_cents",
                        "declined_shop_ids", "status"],
}


def serialize(kind, rec):
    out = {"id": rec["id"]}
    for f in FIELDS[kind]:
        v = rec.get(f)
        if f in DT_FIELDS.get(kind, []):
            v = render_dt(v)
        out[f] = v
    # derived fields
    if kind == "CustomerAccount":
        out["open_receivables_cents"] = domain.open_receivables(rec["id"])
    elif kind == "BranchStock":
        rq = domain.reserved_qty(rec)
        out["reserved_qty"] = rq
        out["available_qty"] = rec["on_hand_qty"] - rq
    elif kind == "ConsignmentAgreement":
        cq = domain.consumed_qty(rec)
        out["consumed_qty"] = cq
        out["remaining_qty"] = rec["consigned_qty"] - cq
    # common fields
    out["created_at"] = render_dt(rec["created_at"])
    if kind != "InterchangeRecord":
        out["updated_at"] = render_dt(rec["updated_at"])
        out["version"] = rec["version"]
    return out


def serialize_list(kind, recs):
    return [serialize(kind, r) for r in recs]
