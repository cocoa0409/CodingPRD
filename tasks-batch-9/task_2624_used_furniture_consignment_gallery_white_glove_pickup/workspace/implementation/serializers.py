"""Row -> JSON projections. Every computed field is recomputed at read time."""

import services
import store


def _common(row):
    return {
        "id": row["id"],
        "created_at": store.iso(row["created_at"]),
        "updated_at": store.iso(row["updated_at"]),
        "version": row["version"],
    }


def _immutable(row):
    return {"id": row["id"], "created_at": store.iso(row["created_at"])}


def _dt(value):
    return store.iso(value) if value is not None else None


def consignor(row):
    out = {
        "display_name": row["display_name"],
        "email": row["email"],
        "address_line": row["address_line"],
        "floor_number": row["floor_number"],
        "has_elevator": row["has_elevator"],
        "payout_method": row["payout_method"],
        "status": row["status"],
        "unclaimed_balance_cents": services.unclaimed_balance_cents(row["id"]),
        "lifetime_credits_cents": services.lifetime_credits_cents(row["id"]),
        "last_activity_at": _dt(row["last_activity_at"]),
        "escheat_state": row["escheat_state"],
    }
    out.update(_common(row))
    return out


def buyer(row):
    out = {
        "display_name": row["display_name"],
        "email": row["email"],
        "address_line": row["address_line"],
        "floor_number": row["floor_number"],
        "has_elevator": row["has_elevator"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def price_schedule(row):
    out = {
        "name": row["name"],
        "unsold_trigger_day": row["unsold_trigger_day"],
        "election_window_days": row["election_window_days"],
        "step_count": services.step_count(row["id"]),
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def price_schedule_step(row):
    out = {
        "schedule_id": row["schedule_id"],
        "sequence": row["sequence"],
        "start_day_offset": row["start_day_offset"],
        "markdown_pct": row["markdown_pct"],
        "min_price_cents": row["min_price_cents"],
    }
    out.update(_immutable(row))
    return out


def agreement(row):
    out = {
        "consignor_id": row["consignor_id"],
        "price_schedule_id": row["price_schedule_id"],
        "term_days": row["term_days"],
        "status": row["status"],
        "effective_at": _dt(row["effective_at"]),
        "expires_at": _dt(row["expires_at"]),
        "approved_by_user_id": row["approved_by_user_id"],
        "item_count": len(services.items_of_agreement(row["id"])),
    }
    out.update(_common(row))
    return out


def item(row):
    out = {
        "consignor_id": row["consignor_id"],
        "agreement_id": row["agreement_id"],
        "parent_lot_item_id": row["parent_lot_item_id"],
        "pickup_job_id": row["pickup_job_id"],
        "placement_zone_id": row["placement_zone_id"],
        "title": row["title"],
        "category": row["category"],
        "declared_value_cents": row["declared_value_cents"],
        "photo_count": row["photo_count"],
        "volume_cuft": row["volume_cuft"],
        "footprint_sqft": row["footprint_sqft"],
        "photo_surface_score": row["photo_surface_score"],
        "photo_structure_score": row["photo_structure_score"],
        "photo_completeness_score": row["photo_completeness_score"],
        "photo_score": row["photo_score"],
        "provisional_condition_grade": row["provisional_condition_grade"],
        "provisional_list_price_cents": row["provisional_list_price_cents"],
        "condition_grade": row["condition_grade"],
        "list_price_cents": row["list_price_cents"],
        "current_price_cents": row["current_price_cents"],
        "markdown_sequence": row["markdown_sequence"],
        "lifecycle_state": row["lifecycle_state"],
        "inventory_state": row["inventory_state"],
        "tag_code": row["tag_code"],
        "listed_at": _dt(row["listed_at"]),
        "days_on_floor": services.days_on_floor(row),
        "election_round": row["election_round"],
        "election_deadline_at": _dt(row["election_deadline_at"]),
        "disposition_election": row["disposition_election"],
        "unsold_trigger_day_effective": services.unsold_trigger_day_effective(row),
        "clearance_relocation_pending": row["clearance_relocation_pending"],
        "lot_component_count": services.lot_component_count(row),
        "lot_ready": services.lot_ready(row),
        "screened_by_user_id": row["screened_by_user_id"],
        "received_by_user_id": row["received_by_user_id"],
    }
    out.update(_common(row))
    return out


def truck(row):
    out = {
        "name": row["name"],
        "capacity_volume_cuft": row["capacity_volume_cuft"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def crew(row):
    out = {
        "name": row["name"],
        "max_concurrent_jobs": row["max_concurrent_jobs"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def zone(row):
    occupied = services.zone_occupied_sqft(row["id"])
    out = {
        "name": row["name"],
        "zone_type": row["zone_type"],
        "capacity_sqft": row["capacity_sqft"],
        "occupied_sqft": occupied,
        "utilization_state": services.zone_utilization(row),
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def pickup_job(row):
    out = {
        "consignor_id": row["consignor_id"],
        "truck_id": row["truck_id"],
        "window_start": _dt(row["window_start"]),
        "window_end": _dt(row["window_end"]),
        "crew_size": row["crew_size"],
        "item_count": services.job_item_count(row["id"]),
        "total_volume_cuft": services.job_total_volume(row["id"]),
        "declared_stair_flights": row["declared_stair_flights"],
        "declared_elevator": row["declared_elevator"],
        "quoted_surcharge_cents": row["quoted_surcharge_cents"],
        "actual_stair_flights": row["actual_stair_flights"],
        "actual_elevator_used": row["actual_elevator_used"],
        "actual_crew_size": row["actual_crew_size"],
        "final_surcharge_cents": row["final_surcharge_cents"],
        "surcharge_variance_cents": row["surcharge_variance_cents"],
        "status": row["status"],
        "scheduled_by_user_id": row["scheduled_by_user_id"],
    }
    out.update(_common(row))
    return out


def sale(row):
    out = {
        "item_id": row["item_id"],
        "buyer_id": row["buyer_id"],
        "sale_price_cents": row["sale_price_cents"],
        "markdown_sequence_at_sale": row["markdown_sequence_at_sale"],
        "split_pct_applied": row["split_pct_applied"],
        "consignor_share_cents": row["consignor_share_cents"],
        "gallery_share_cents": row["gallery_share_cents"],
        "refund_cents": row["refund_cents"],
        "status": row["status"],
        "sold_at": _dt(row["sold_at"]),
        "reversed_at": _dt(row["reversed_at"]),
        "sold_by_user_id": row["sold_by_user_id"],
    }
    out.update(_common(row))
    return out


def delivery_order(row):
    out = {
        "sale_id": row["sale_id"],
        "crew_id": row["crew_id"],
        "window_start": _dt(row["window_start"]),
        "window_end": _dt(row["window_end"]),
        "stair_flights": row["stair_flights"],
        "elevator_used": row["elevator_used"],
        "delivery_fee_cents": row["delivery_fee_cents"],
        "status": row["status"],
        "outcome_recorded_at": _dt(row["outcome_recorded_at"]),
        "claim_window_ends_at": _dt(row["claim_window_ends_at"]),
        "scheduled_by_user_id": row["scheduled_by_user_id"],
    }
    out.update(_common(row))
    return out


def damage_claim(row):
    out = {
        "delivery_order_id": row["delivery_order_id"],
        "claim_amount_cents": row["claim_amount_cents"],
        "description": row["description"],
        "status": row["status"],
        "resubmission_count": row["resubmission_count"],
        "fault_party": row["fault_party"],
        "adjudicated_amount_cents": row["adjudicated_amount_cents"],
        "gallery_absorbed_cents": row["gallery_absorbed_cents"],
        "consignor_debited_cents": row["consignor_debited_cents"],
        "info_request_note": row["info_request_note"],
        "adjudicated_by_user_id": row["adjudicated_by_user_id"],
    }
    out.update(_common(row))
    return out


def shrinkage_audit(row):
    out = {
        "floor_zone_id": row["floor_zone_id"],
        "counted_item_ids": list(row["counted_item_ids"]),
        "expected_item_count": row["expected_item_count"],
        "counted_item_count": row["counted_item_count"],
        "variance_count": row["variance_count"],
        "missing_item_ids": list(row["missing_item_ids"]),
        "write_off_total_cents": row["write_off_total_cents"],
        "status": row["status"],
        "counted_by_user_id": row["counted_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
    }
    out.update(_common(row))
    return out


def ledger_entry(row):
    out = {
        "consignor_id": row["consignor_id"],
        "item_id": row["item_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "withholding_cents": row["withholding_cents"],
        "processing_fee_cents": row["processing_fee_cents"],
        "net_payout_cents": row["net_payout_cents"],
        "balance_after_cents": row["balance_after_cents"],
        "memo": row["memo"],
        "effective_at": _dt(row["effective_at"]),
    }
    out.update(_immutable(row))
    return out


def many(fn, rows):
    return [fn(row) for row in rows]
