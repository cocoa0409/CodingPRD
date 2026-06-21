"""Resource -> public-JSON projections.

Internal records carry bookkeeping fields prefixed with `_` (e.g. parsed
datetimes, sequence keys) that must never appear in API output. Each serializer
emits exactly the fields the scaffold §1.1 entity declares, in a stable shape.
"""


def _common(rec, with_version=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if "updated_at" in rec:
        out["updated_at"] = rec["updated_at"]
    if with_version and "version" in rec:
        out["version"] = rec["version"]
    return out


def catalog_item_view(rec):
    out = _common(rec)
    for f in ("sku", "name", "category", "total_units", "daily_rate_cents",
              "multi_day_discount_pct", "deposit_per_unit_cents",
              "requires_cleaning", "cleaning_fee_cents", "requires_coi", "status"):
        out[f] = rec[f]
    return out


def customer_view(rec):
    out = _common(rec)
    for f in ("email", "full_name", "phone", "account_credit_cents"):
        out[f] = rec[f]
    return out


def venue_view(rec, coi_status):
    out = _common(rec)
    for f in ("customer_id", "name", "address", "delivery_zone"):
        out[f] = rec[f]
    out["coi_status"] = coi_status
    return out


def certificate_view(rec):
    out = _common(rec)
    for f in ("venue_id", "carrier_name", "coverage_start", "coverage_end",
              "coverage_amount_cents", "status"):
        out[f] = rec[f]
    return out


def order_view(rec):
    out = _common(rec)
    for f in ("customer_id", "venue_id", "fulfillment", "event_start", "event_end",
              "rental_days", "booking_status", "settlement_status",
              "rental_subtotal_cents", "delivery_fee_cents", "cleaning_fee_total_cents",
              "deposit_total_cents", "grand_total_cents", "weather_cancellable"):
        out[f] = rec[f]
    return out


def line_view(rec):
    out = _common(rec)
    for f in ("order_id", "item_id", "quantity", "line_rental_cents",
              "line_deposit_cents", "line_cleaning_cents",
              "reserved_window_start", "reserved_window_end", "status"):
        out[f] = rec[f]
    return out


def run_view(rec):
    out = _common(rec)
    for f in ("order_id", "leg", "crew_id", "window_start", "window_end",
              "status", "attempt_count"):
        out[f] = rec[f]
    return out


def crew_view(rec):
    out = _common(rec)
    for f in ("name", "turnaround_minutes"):
        out[f] = rec[f]
    return out


def ledger_view(rec):
    # DepositLedgerEntry: leaner record, only id + created_at (no version/updated_at).
    return {
        "id": rec["id"],
        "order_id": rec["order_id"],
        "kind": rec["kind"],
        "amount_cents": rec["amount_cents"],
        "reason": rec["reason"],
        "created_at": rec["created_at"],
    }


def weather_event_view(rec):
    return {
        "id": rec["id"],
        "delivery_zone": rec["delivery_zone"],
        "severity": rec["severity"],
        "effective_date": rec["effective_date"],
        "created_at": rec["created_at"],
    }
