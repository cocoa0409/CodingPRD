"""Serialized shapes (PRD 2.11).

Every response body returns the full row: no partial projections, no
field-selection parameters, no hidden fields.  Every entity carries ``id``,
``created_at``, ``updated_at`` and ``version`` in addition to the fields named
below -- except ``InvoiceLine``, which carries only ``id`` and ``created_at``
and must NOT emit ``updated_at`` or ``version``.
"""

FIELDS = {
    "barns": ["name", "zone", "served_weekdays", "access_open_minute",
              "access_close_minute", "blackout_dates"],
    "clients": ["display_name", "home_barn_id", "billing_standing",
                "deposit_balance_cents", "credit_balance_cents",
                "completed_visit_count", "no_show_count_rolling", "tax_exempt"],
    "horses": ["client_id", "barn_id", "name", "routine_cycle_weeks",
               "requires_sedation", "shoe_size_code", "lifecycle_status",
               "hold_status", "active_prescription_id", "next_due_on",
               "last_completed_on"],
    "limb_states": ["horse_id", "limb", "shoeing_state", "current_sku_code",
                    "last_serviced_on", "consecutive_reset_count"],
    "farriers": ["display_name", "certification_level", "cert_expires_on", "status"],
    "shoe_skus": ["sku_code", "size_code", "material", "price_cents_per_pair"],
    "inventory_buckets": ["location_kind", "farrier_id", "sku_id", "on_hand_pairs",
                          "available_pairs", "reserved_pairs", "replenishment_flag"],
    "stock_transfers": ["sku_id", "from_bucket_id", "to_bucket_id",
                        "quantity_pairs", "status"],
    "shoe_reservations": ["appointment_id", "sku_id", "bucket_id", "pairs", "status"],
    "rate_cards": ["label", "effective_from", "supersedes_rate_card_id",
                   "price_trim_cents", "price_reset_cents", "price_new_shoes_cents",
                   "price_corrective_cents", "price_glue_on_cents", "pad_price_cents",
                   "trip_fee_zone_a_cents", "trip_fee_zone_b_cents",
                   "trip_fee_zone_c_cents", "status"],
    "routes": ["farrier_id", "route_date", "status", "committed_units",
               "committed_minutes", "stop_count"],
    "route_stops": ["route_id", "barn_id", "sequence_index", "planned_start_minute",
                    "status", "travel_minutes", "service_minutes", "end_minute",
                    "trip_fee_cents", "billable_horse_count"],
    "appointments": ["horse_id", "route_stop_id", "origin_appointment_id",
                     "rate_card_id", "scheduled_date", "visit_kind",
                     "warranty_reason", "cycle_source", "status", "billing_status",
                     "vet_present", "service_units", "service_minutes",
                     "estimated_total_cents", "cancellation_fee_cents",
                     "trip_fee_share_cents", "completed_on"],
    "service_lines": ["appointment_id", "limb_state_id", "prescription_id", "sku_id",
                      "limb", "service_type", "with_pad", "status", "labor_cents"],
    "lameness_cases": ["horse_id", "reported_on", "severity", "status", "hold_applied"],
    "vet_prescriptions": ["lameness_case_id", "horse_id", "issued_on", "expires_on",
                          "limb_scope", "prescribed_cycle_weeks", "status"],
    "invoices": ["appointment_id", "client_id", "rate_card_id", "status", "issued_on",
                 "labor_subtotal_cents", "product_subtotal_cents",
                 "multi_horse_discount_cents", "loyalty_discount_cents",
                 "loyalty_discount_labor_cents", "loyalty_discount_product_cents",
                 "labor_net_cents", "trip_fee_share_cents", "fee_cents",
                 "taxable_product_base_cents", "tax_cents", "total_cents",
                 "paid_cents", "balance_cents"],
    "invoice_lines": ["invoice_id", "line_kind", "description", "limb", "service_type",
                      "sku_code", "quantity", "unit_amount_cents", "amount_cents",
                      "taxable"],
    "reminders": ["appointment_id", "offset_days", "due_on", "status", "sent_on"],
}

# InvoiceLine is immutable once written: it carries neither updated_at nor version.
UNVERSIONED_TABLES = ("invoice_lines",)


def serialize(row):
    table = row["_table"]
    out = {"id": row["id"], "created_at": row["created_at"]}
    if table not in UNVERSIONED_TABLES:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    for field in FIELDS[table]:
        value = row.get(field)
        if isinstance(value, list):
            value = list(value)
        out[field] = value
    return out


def serialize_many(rows):
    return [serialize(r) for r in rows]
