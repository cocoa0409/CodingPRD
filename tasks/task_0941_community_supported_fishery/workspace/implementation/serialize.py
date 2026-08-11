"""Resource projections.

Every instant goes through clock.render_instant (PRD 2.4) and every pound or
temperature quantity through money.to_number.  Serialisation always happens
after store.commit(), so a projection never shows a stale version.
"""
from decimal import Decimal

import clock
from money import to_number

DATETIME_FIELDS = {
    "created_at", "updated_at", "start_date", "end_date", "true_up_run_at",
    "opens_at", "closes_at", "landed_at", "species_open_date",
    "species_close_date", "scheduled_at", "recorded_at", "requested_at",
    "cutoff_at",
}

FIELDS = {
    "Season": ["season_code", "start_date", "end_date", "total_weeks",
               "ambient_band", "offered_species", "landing_commit_lead_hours",
               "status", "shortfall_flag_count", "true_up_run_at"],
    "SharePlan": ["season_id", "plan_code", "share_size", "delivery_frequency",
                  "species_tier", "price_per_delivery_cents", "weight_units",
                  "target_pounds_per_delivery", "min_floor_pounds",
                  "scheduled_delivery_count"],
    "DeliveryZone": ["zone_code", "fee_tier", "transit_hours", "is_serviceable"],
    "PickupHub": ["hub_code", "cooler_slots_default", "grace_minutes"],
    "PickupWindow": ["pickup_hub_id", "season_id", "week_index", "opens_at",
                     "closes_at", "grace_minutes", "cooler_slots_total",
                     "slots_reserved", "slots_occupied", "slots_forfeited",
                     "slots_free", "status"],
    "Member": ["full_name", "email", "allergy_exclusions", "dislikes",
               "never_substitute", "season_no_show_count", "standing",
               "credit_balance_cents"],
    "Subscription": ["member_id", "share_plan_id", "season_id", "pickup_hub_id",
                     "delivery_zone_id", "renewed_from_subscription_id",
                     "fulfillment_mode", "payment_basis", "join_week_index",
                     "lifecycle_status", "billing_status", "commitment_cents",
                     "price_per_delivery_cents", "promised_delivery_count",
                     "delivered_count", "credited_count", "skip_credited_count",
                     "undelivered_count", "member_fault_count", "skip_count",
                     "skip_credit_balance_cents", "paid_cents",
                     "rollover_credit_cents", "expired_credit_cents",
                     "true_up_status", "true_up_amount_cents"],
    "Vessel": ["vessel_name", "permit_number", "home_port", "gear_types",
               "compliance_status", "violation_count"],
    "QuotaLedger": ["vessel_id", "season_id", "species", "management_area",
                    "entitlement_pounds", "committed_pounds", "remaining_pounds",
                    "area_closed", "species_open_date", "species_close_date",
                    "permitted_gears", "area_sensitivity_penalty",
                    "species_stock_adjustment", "status"],
    "Trip": ["vessel_id", "season_id", "quota_ledger_id", "gear_type",
             "management_area", "landed_at", "offload_minutes",
             "sustainability_score", "sustainability_band", "status"],
    "LandingLot": ["trip_id", "species", "landed_pounds_gross",
                   "landed_pounds_net", "discarded_over_quota_pounds",
                   "allocation_week_index", "allocated_pounds_total",
                   "surplus_secondary_pounds", "surplus_donated_pounds",
                   "split_pounds_total", "ex_vessel_price_cents_per_lb",
                   "retail_value_cents_per_lb", "cold_chain_cumulative_minutes",
                   "cold_chain_max_single_minutes", "peak_temp_c",
                   "allocation_variant", "status", "quality_status"],
    "SubLot": ["landing_lot_id", "pickup_hub_id", "delivery_zone_id",
               "destination_type", "pounds", "status"],
    "ShareDelivery": ["subscription_id", "season_id", "landing_lot_id",
                      "sub_lot_id", "pickup_window_id", "week_index",
                      "scheduled_at", "allocated_pounds", "substituted_pounds",
                      "box_pounds", "pack_size", "gel_pack_count",
                      "subtotal_cents", "surcharge_cents", "delivery_fee_cents",
                      "invoice_total_cents", "charged_cents", "credit_cents",
                      "fill_status", "fulfillment_status", "billing_status"],
    "SubstitutionEvent": ["share_delivery_id", "substitute_landing_lot_id",
                          "substitute_species", "substitute_pounds",
                          "shortfall_pounds", "owed_value_cents",
                          "substitute_value_cents", "settlement_variant",
                          "member_credit_cents", "status"],
    "ColdChainEvent": ["landing_lot_id", "sub_lot_id", "custody_leg",
                       "minutes_above_threshold", "peak_temp_c", "recorded_at",
                       "recorded_by_user_id", "breach_type"],
    "SkipRequest": ["subscription_id", "share_delivery_id", "week_index",
                    "requested_at", "cutoff_at", "settlement_variant",
                    "credit_cents", "status"],
    "SettlementStatement": ["trip_id", "landing_lot_id", "vessel_id",
                            "ex_vessel_cents", "premium_cents", "gross_cents",
                            "dock_fee_cents", "ice_handling_cents",
                            "offload_labor_cents", "handling_levy_cents",
                            "deductions_cents", "holdback_cents",
                            "holdback_released_cents", "holdback_forfeited_cents",
                            "offset_cents", "net_payable_cents", "net_paid_cents",
                            "variant", "status"],
    "ShareTransfer": ["from_subscription_id", "to_subscription_id", "season_id",
                      "remaining_delivery_count", "effective_week_index",
                      "transfer_fee_cents", "transferor_refund_cents",
                      "transferee_charge_cents", "settlement_variant", "status"],
    "RecallNotice": ["landing_lot_id", "season_id", "reason",
                     "impacted_sub_lot_count", "impacted_delivery_count",
                     "impacted_member_count", "total_credit_cents", "status"],
}

# PRD 2.4: a cold-chain leg record "carries id and created_at and carries
# neither updated_at nor version".
NO_COMMON = {"ColdChainEvent"}


def _value(name, raw):
    if raw is None:
        return None
    if name in DATETIME_FIELDS:
        return clock.render_instant(raw)
    if isinstance(raw, Decimal):
        return to_number(raw)
    if isinstance(raw, list):
        return list(raw)
    return raw


def project(rec):
    kind = rec["_kind"]
    out = {"id": rec["id"], "created_at": clock.render_instant(rec["created_at"])}
    if kind not in NO_COMMON:
        out["updated_at"] = clock.render_instant(rec["updated_at"])
        out["version"] = rec["version"]
    for name in FIELDS[kind]:
        out[name] = _value(name, rec.get(name))
    return out


def projector(kind):
    def fn(rec):
        return project(rec)
    return fn
