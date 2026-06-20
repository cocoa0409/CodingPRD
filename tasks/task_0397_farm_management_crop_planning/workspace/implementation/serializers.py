"""Serializers: internal record dict -> API output dict.

Each function lists exactly the fields the PRD/SCAFFOLD declares for that
entity, so internal bookkeeping fields (e.g. _seq) never leak.
Common fields (id, created_at, updated_at, version) are included for every
first-class resource (PRD §2.4).
"""

_COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(rec, fields):
    return {f: rec.get(f) for f in fields}


def parcel(rec):
    return _pick(
        rec,
        _COMMON
        + [
            "name",
            "acreage",
            "soil_type",
            "status",
            "reentry_blocked_until",
            "active_crop_plan_count",
        ],
    )


def crop_plan(rec):
    return _pick(
        rec,
        _COMMON
        + [
            "parcel_id",
            "crop",
            "season_year",
            "planned_acres",
            "budget_input_cost",
            "budget_labor_cost",
            "budget_equipment_cost",
            "status",
            "revision_count",
            "planted_acres",
            "harvested_acres",
            "actual_input_cost",
            "actual_labor_cost",
            "actual_equipment_cost",
            "provisional_cost_per_acre",
            "final_cost_per_acre",
            "total_yield_units",
        ],
    )


def input_product(rec):
    return _pick(
        rec,
        _COMMON
        + [
            "name",
            "category",
            "unit",
            "unit_cost",
            "restricted_use",
            "reentry_interval_hours",
            "preharvest_interval_days",
            "max_seasonal_rate_per_acre",
        ],
    )


def input_lot(rec):
    return _pick(
        rec,
        _COMMON
        + [
            "input_product_id",
            "lot_code",
            "quantity_received",
            "quantity_remaining",
            "status",
        ],
    )


def application_record(rec):
    return _pick(
        rec,
        _COMMON
        + [
            "crop_plan_id",
            "input_product_id",
            "applicator_user_id",
            "rate_per_acre",
            "acres_treated",
            "quantity_used",
            "applied_cost",
            "applied_at",
            "status",
            "is_restricted",
            "reentry_clear_at",
        ],
    )


def compliance_record(rec):
    return _pick(
        rec,
        _COMMON
        + [
            "application_record_id",
            "crop_plan_id",
            "applicator_user_id",
            "reentry_interval_hours",
            "preharvest_interval_days",
            "reentry_clear_at",
            "status",
        ],
    )


def planting_event(rec):
    return _pick(
        rec,
        _COMMON
        + [
            "crop_plan_id",
            "input_lot_id",
            "acres_planted",
            "seed_rate_per_acre",
            "seed_units_used",
            "status",
        ],
    )


def harvest_event(rec):
    return _pick(
        rec,
        _COMMON
        + [
            "crop_plan_id",
            "acres_harvested",
            "gross_quantity",
            "moisture_pct",
            "net_quantity",
            "status",
        ],
    )


def harvest_lot(rec):
    return _pick(
        rec,
        _COMMON
        + [
            "harvest_event_id",
            "crop_plan_id",
            "quantity",
            "quantity_committed",
            "quality_status",
            "sale_status",
            "committed_contract_id",
        ],
    )


def sale_contract(rec):
    return _pick(
        rec,
        _COMMON
        + [
            "crop",
            "buyer_name",
            "contracted_quantity",
            "min_quality",
            "price_per_unit",
            "committed_quantity",
            "contract_value",
            "status",
        ],
    )


def equipment_asset(rec):
    return _pick(
        rec,
        _COMMON + ["name", "kind", "hourly_cost", "status", "total_logged_hours"],
    )


def equipment_usage(rec):
    return _pick(
        rec,
        _COMMON
        + [
            "equipment_asset_id",
            "crop_plan_id",
            "window_start",
            "window_end",
            "hours",
            "usage_cost",
            "status",
        ],
    )


def labor_entry(rec):
    return _pick(
        rec,
        _COMMON + ["crop_plan_id", "worker_name", "hours", "hourly_rate", "labor_cost"],
    )


def irrigation_event(rec):
    return _pick(
        rec,
        _COMMON
        + ["parcel_id", "window_start", "window_end", "inches_applied", "status"],
    )


def applicator(rec):
    return _pick(rec, _COMMON + ["full_name", "license_no", "certified"])
