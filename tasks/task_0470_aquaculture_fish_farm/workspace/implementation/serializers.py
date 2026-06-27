"""Output shaping. Each serializer projects a stored record into the public
representation, stripping internal bookkeeping keys (those prefixed with '_').

PRD §2.4: most resources expose id, created_at, updated_at, version plus their
domain fields. StockingEvent / FeedLog / WaterQualityReading expose only id and
created_at (no updated_at, no version)."""


def _base(rec, with_version=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if with_version:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def species_out(rec):
    out = _base(rec)
    out.update({
        "common_name": rec["common_name"],
        "code": rec["code"],
        "target_market_weight_g": rec["target_market_weight_g"],
        "base_daily_growth_g": rec["base_daily_growth_g"],
        "default_processing_yield_pct": rec["default_processing_yield_pct"],
        "min_water_temp_c": rec["min_water_temp_c"],
        "max_water_temp_c": rec["max_water_temp_c"],
    })
    return out


def tank_out(rec):
    out = _base(rec)
    out.update({
        "name": rec["name"],
        "kind": rec["kind"],
        "volume_liters": rec["volume_liters"],
        "max_biomass_kg": rec["max_biomass_kg"],
        "posture": rec["posture"],
        "posture_override": rec["posture_override"],
        "current_biomass_kg": rec["current_biomass_kg"],
    })
    return out


def broodstock_out(rec):
    out = _base(rec)
    out.update({
        "species_id": rec["species_id"],
        "spawned_at": rec["spawned_at"],
        "fingerling_count": rec["fingerling_count"],
        "allocated_count": rec["allocated_count"],
        "status": rec["status"],
    })
    return out


def cohort_out(rec):
    out = _base(rec)
    out.update({
        "label": rec["label"],
        "species_id": rec["species_id"],
        "current_tank_id": rec["current_tank_id"],
        "origin_broodstock_id": rec["origin_broodstock_id"],
        "parent_cohort_id": rec["parent_cohort_id"],
        "fish_count": rec["fish_count"],
        "stocked_avg_weight_g": rec["stocked_avg_weight_g"],
        "stocked_at": rec["stocked_at"],
        "cumulative_feed_kg": rec["cumulative_feed_kg"],
        "estimated_biomass_kg": rec["estimated_biomass_kg"],
        "lifecycle_status": rec["lifecycle_status"],
        "health_status": rec["health_status"],
        "operational_status": rec["operational_status"],
        "withdrawal_until": rec["withdrawal_until"],
    })
    return out


def stocking_event_out(rec):
    out = _base(rec, with_version=False)
    out.update({
        "cohort_id": rec["cohort_id"],
        "tank_id": rec["tank_id"],
        "fish_count": rec["fish_count"],
        "stocked_at": rec["stocked_at"],
        "expected_harvest_at": rec["expected_harvest_at"],
    })
    return out


def feed_log_out(rec):
    out = _base(rec, with_version=False)
    out.update({
        "cohort_id": rec["cohort_id"],
        "fed_at": rec["fed_at"],
        "amount_kg": rec["amount_kg"],
        "feed_type": rec["feed_type"],
    })
    return out


def water_reading_out(rec):
    out = _base(rec, with_version=False)
    out.update({
        "tank_id": rec["tank_id"],
        "measured_at": rec["measured_at"],
        "dissolved_oxygen_mg_l": rec["dissolved_oxygen_mg_l"],
        "ammonia_mg_l": rec["ammonia_mg_l"],
        "water_temp_c": rec["water_temp_c"],
        "severity": rec["severity"],
    })
    return out


def grading_event_out(rec):
    out = _base(rec)
    out.update({
        "source_cohort_id": rec["source_cohort_id"],
        "planned_splits": rec["planned_splits"],
        "status": rec["status"],
        "child_cohort_ids": rec["child_cohort_ids"],
    })
    return out


def health_treatment_out(rec):
    out = _base(rec)
    out.update({
        "cohort_id": rec["cohort_id"],
        "tank_id": rec["tank_id"],
        "medication": rec["medication"],
        "started_at": rec["started_at"],
        "duration_days": rec["duration_days"],
        "withdrawal_days": rec["withdrawal_days"],
        "treatment_end_at": rec["treatment_end_at"],
        "withdrawal_end_at": rec["withdrawal_end_at"],
        "status": rec["status"],
    })
    return out


def harvest_order_out(rec):
    out = _base(rec)
    out.update({
        "cohort_id": rec["cohort_id"],
        "planned_fish_count": rec["planned_fish_count"],
        "scheduled_at": rec["scheduled_at"],
        "harvested_fish_count": rec["harvested_fish_count"],
        "harvested_live_weight_kg": rec["harvested_live_weight_kg"],
        "status": rec["status"],
    })
    return out


def processing_batch_out(rec):
    out = _base(rec)
    out.update({
        "harvest_order_id": rec["harvest_order_id"],
        "input_live_weight_kg": rec["input_live_weight_kg"],
        "estimated_yield_kg": rec["estimated_yield_kg"],
        "actual_processed_weight_kg": rec["actual_processed_weight_kg"],
        "status": rec["status"],
    })
    return out


def product_lot_out(rec):
    out = _base(rec)
    out.update({
        "processing_batch_id": rec["processing_batch_id"],
        "species_id": rec["species_id"],
        "total_weight_kg": rec["total_weight_kg"],
        "reserved_weight_kg": rec["reserved_weight_kg"],
        "available_weight_kg": rec["available_weight_kg"],
        "shipped_weight_kg": rec["shipped_weight_kg"],
        "price_per_kg": rec["price_per_kg"],
        "status": rec["status"],
    })
    return out


def sales_order_out(rec):
    out = _base(rec)
    out.update({
        "customer_name": rec["customer_name"],
        "discount_tier": rec["discount_tier"],
        "order_total": rec["order_total"],
        "status": rec["status"],
    })
    return out


def sales_order_line_out(rec):
    out = _base(rec)
    out.update({
        "sales_order_id": rec["sales_order_id"],
        "product_lot_id": rec["product_lot_id"],
        "weight_kg": rec["weight_kg"],
        "line_subtotal": rec["line_subtotal"],
    })
    return out
