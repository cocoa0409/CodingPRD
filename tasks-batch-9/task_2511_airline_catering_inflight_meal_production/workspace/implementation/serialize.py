"""Entity output shapes.

Internal bookkeeping keys (prefixed with an underscore) never leak.  HaccpCheck
carries only id and created_at; every other entity also carries updated_at and
version (PRD 2.5).
"""

from decimal import Decimal

import db
from services import calc, cascade


def _num(value):
    """Render a Decimal money-free ratio as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def _pick(row, names):
    return {name: row.get(name) for name in names}


# ---------------------------------------------------------------------------

AIRLINE_FIELDS = (
    "name",
    "iata_code",
    "waste_regime",
    "special_meal_cutoff_minutes",
    "cost_cap_per_pax_cents",
    "late_delivery_grace_minutes",
    "status",
)


def airline(row):
    out = _common(row)
    out.update(_pick(row, AIRLINE_FIELDS))
    out["unused_recovery_rate_pct"] = _num(row["unused_recovery_rate_pct"])
    out["spec_deviation_tolerance_pct"] = _num(row["spec_deviation_tolerance_pct"])
    out["open_finding_count"] = cascade.open_finding_count(row["id"])
    out["penalty_accrued_cents"] = cascade.penalty_accrued_cents(row["id"])
    return out


SPEC_FIELDS = (
    "airline_id",
    "spec_code",
    "cabin",
    "meal_code",
    "storage_class",
    "portion_grams",
    "gross_weight_grams",
    "unit_cost_cents",
    "shelf_life_hours",
    "required_haccp_steps",
    "status",
)


def meal_specification(row):
    out = _common(row)
    out.update(_pick(row, SPEC_FIELDS))
    out["load_factor_pct"] = _num(row["load_factor_pct"])
    return out


FLIGHT_FIELDS = (
    "airline_id",
    "flight_number",
    "service_date",
    "std_utc",
    "tail_number",
    "station_code",
    "pax_first",
    "pax_business",
    "pax_economy",
    "delay_minutes",
    "counts_locked_at",
    "status",
    "production_hold",
    "units_planned_provisional",
    "units_planned",
)


def flight(row):
    from timeutil import fmt_ms

    out = _common(row)
    out.update(_pick(row, FLIGHT_FIELDS))
    out["total_pax"] = calc.total_pax(row)
    out["revised_std_utc"] = fmt_ms(calc.revised_std(row))
    out["special_meal_cutoff_utc"] = fmt_ms(calc.special_meal_cutoff(row))
    produced = calc.units_produced(row["id"])
    loaded = calc.units_loaded(row["id"])
    out["units_produced"] = produced
    out["units_loaded"] = loaded
    out["units_scrapped"] = calc.units_scrapped(row["id"])
    out["unit_balance"] = produced - loaded
    out["cost_per_pax_cents"] = 0 if loaded == 0 else calc.cost_per_pax_cents(row)
    return out


ORDER_FIELDS = (
    "flight_id",
    "meal_specification_id",
    "substitute_meal_specification_id",
    "passenger_ref",
    "seat_number",
    "cabin",
    "requested_at",
    "status",
)


def special_meal_order(row):
    out = _common(row)
    out.update(_pick(row, ORDER_FIELDS))
    return out


BATCH_FIELDS = (
    "flight_id",
    "meal_specification_id",
    "store_zone",
    "planned_qty",
    "produced_qty",
    "scrapped_qty",
    "production_status",
    "haccp_rework_rounds",
    "release_deadline_utc",
    "released_at",
    "released_by_user_id",
    "is_overflow",
)


def production_batch(row):
    out = _common(row)
    out.update(_pick(row, BATCH_FIELDS))
    out["haccp_risk_score"] = _num(calc.risk_score(row))
    return out


CHECK_FIELDS = (
    "production_batch_id",
    "step_code",
    "measured_at_utc",
    "verdict",
    "sequence_no",
    "recorded_by_user_id",
)


def haccp_check(row):
    out = {"id": row["id"], "created_at": row["created_at"]}
    out.update(_pick(row, CHECK_FIELDS))
    out["measured_temp_c"] = _num(row["measured_temp_c"])
    return out


CART_FIELDS = (
    "flight_id",
    "cart_code",
    "cart_type",
    "storage_class",
    "capacity_units",
    "galley_position",
    "build_status",
    "seal_status",
    "seal_number",
    "seal_count",
    "sealed_by_user_id",
)


def cart(row):
    out = _common(row)
    out.update(_pick(row, CART_FIELDS))
    out["loaded_units"] = calc.cart_loaded_units(row["id"])
    return out


ITEM_FIELDS = (
    "cart_id",
    "production_batch_id",
    "qty_units",
    "meal_code",
    "status",
    "voided_at",
)


def cart_item(row):
    out = _common(row)
    out.update(_pick(row, ITEM_FIELDS))
    return out


MANIFEST_FIELDS = (
    "flight_id",
    "manifest_number",
    "status",
    "cart_seal_snapshot",
    "total_units",
    "issued_at",
    "issued_by_user_id",
    "amendment_count",
)


def loading_manifest(row):
    out = _common(row)
    out.update(_pick(row, MANIFEST_FIELDS))
    return out


TRUCK_FIELDS = ("station_code", "registration", "buffer_minutes", "status")


def truck(row):
    out = _common(row)
    out.update(_pick(row, TRUCK_FIELDS))
    return out


STAND_FIELDS = ("station_code", "stand_code", "max_concurrent_runs", "status")


def stand(row):
    out = _common(row)
    out.update(_pick(row, STAND_FIELDS))
    return out


RUN_FIELDS = (
    "loading_manifest_id",
    "truck_id",
    "stand_id",
    "recovery_of_run_id",
    "window_start_utc",
    "window_end_utc",
    "status",
    "dispatched_at_utc",
    "arrived_at_utc",
    "delivered_at_utc",
    "lateness_minutes",
    "penalty_cents",
    "miss_reason",
)


def delivery_run(row):
    out = _common(row)
    out.update(_pick(row, RUN_FIELDS))
    return out


UPLIFT_FIELDS = (
    "flight_id",
    "lines",
    "uplifted_units",
    "consumed_units",
    "returned_units",
    "unused_units",
    "gross_cost_cents",
    "net_cost_cents",
    "handling_fee_cents",
    "late_penalty_cents",
    "billing_total_cents",
    "cost_per_pax_cents",
    "seal_mismatch_count",
    "status",
)


def uplift_record(row):
    out = _common(row)
    out.update(_pick(row, UPLIFT_FIELDS))
    out["spec_deviation_pct"] = _num(row["spec_deviation_pct"])
    return out


WASTE_FIELDS = (
    "uplift_record_id",
    "regime",
    "disposal_method",
    "seal_number",
    "sealed_weight_grams",
    "status",
    "rejection_reason",
)


def waste_manifest(row):
    out = _common(row)
    out.update(_pick(row, WASTE_FIELDS))
    return out


FINDING_FIELDS = (
    "airline_id",
    "flight_id",
    "finding_type",
    "severity",
    "penalty_cents",
    "status",
    "source",
    "evidence_ref",
)


def audit_finding(row):
    out = _common(row)
    out.update(_pick(row, FINDING_FIELDS))
    return out


SERIALIZERS = {
    "airlines": airline,
    "meal_specifications": meal_specification,
    "flights": flight,
    "special_meal_orders": special_meal_order,
    "production_batches": production_batch,
    "haccp_checks": haccp_check,
    "carts": cart,
    "cart_items": cart_item,
    "loading_manifests": loading_manifest,
    "trucks": truck,
    "stands": stand,
    "delivery_runs": delivery_run,
    "uplift_records": uplift_record,
    "waste_manifests": waste_manifest,
    "audit_findings": audit_finding,
}


def many(collection, rows):
    fn = SERIALIZERS[collection]
    return [fn(row) for row in rows]


def one(collection, row):
    return SERIALIZERS[collection](row)


__all__ = ["many", "one", "SERIALIZERS", "db"]
