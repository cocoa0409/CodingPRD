"""Wire representations. Journal records deliberately omit updated_at/version."""
import clock


def _common(record):
    return {
        "id": record["id"],
        "created_at": clock.fmt(record["created_at"]),
        "updated_at": clock.fmt(record["updated_at"]),
        "version": record["version"],
    }


def _journal(record):
    return {
        "id": record["id"],
        "created_at": clock.fmt(record["created_at"]),
    }


def store(rec):
    out = _common(rec)
    out.update({
        "brand_code": rec["brand_code"],
        "name": rec["name"],
        "timezone_offset_minutes": rec["timezone_offset_minutes"],
        "base_prep_minutes": rec["base_prep_minutes"],
        "prep_capacity_per_bucket": rec["prep_capacity_per_bucket"],
        "pos_retry_limit": rec["pos_retry_limit"],
        "tablet_backlog_threshold": rec["tablet_backlog_threshold"],
        "active_menu_version_id": rec["active_menu_version_id"],
        "throttle_state": rec["throttle_state"],
        "open_order_count": rec["open_order_count"],
        "reserved_prep_slots": rec["reserved_prep_slots"],
        "tablet_backlog_count": rec["tablet_backlog_count"],
        "last_published_at": clock.fmt(rec["last_published_at"]),
    })
    return out


def hour_window(rec):
    out = _journal(rec)
    out.update({
        "store_id": rec["store_id"],
        "day_of_week": rec["day_of_week"],
        "opens_at_minute": rec["opens_at_minute"],
        "closes_at_minute": rec["closes_at_minute"],
        "window_minutes": rec["window_minutes"],
    })
    return out


def channel(rec):
    out = _common(rec)
    out.update({
        "code": rec["code"],
        "name": rec["name"],
        "channel_type": rec["channel_type"],
        "markup_bps": rec["markup_bps"],
        "rounding_mode": rec["rounding_mode"],
        "service_fee_cents": rec["service_fee_cents"],
        "commission_bps": rec["commission_bps"],
        "settlement_mode": rec["settlement_mode"],
        "eighty_six_policy": rec["eighty_six_policy"],
        "throttle_policy": rec["throttle_policy"],
        "adjustment_review_mode": rec["adjustment_review_mode"],
        "accepts_delivery": rec["accepts_delivery"],
        "listing_count": rec["listing_count"],
    })
    return out


def menu_version(rec):
    out = _common(rec)
    out.update({
        "brand_code": rec["brand_code"],
        "version_label": rec["version_label"],
        "state": rec["state"],
        "item_count": rec["item_count"],
        "published_store_count": rec["published_store_count"],
        "published_at": clock.fmt(rec["published_at"]),
        "superseded_at": clock.fmt(rec["superseded_at"]),
    })
    return out


def menu_item(rec):
    out = _common(rec)
    out.update({
        "menu_version_id": rec["menu_version_id"],
        "sku": rec["sku"],
        "name": rec["name"],
        "base_price_cents": rec["base_price_cents"],
        "tax_bps": rec["tax_bps"],
        "is_delivery_eligible": rec["is_delivery_eligible"],
    })
    return out


def listing(rec):
    out = _common(rec)
    out.update({
        "store_id": rec["store_id"],
        "channel_id": rec["channel_id"],
        "menu_item_id": rec["menu_item_id"],
        "sku": rec["sku"],
        "base_price_cents": rec["base_price_cents"],
        "price_cents": rec["price_cents"],
        "suppressed": rec["suppressed"],
        "eighty_sixed": rec["eighty_sixed"],
        "availability_state": rec["availability_state"],
    })
    return out


def availability_event(rec):
    out = _journal(rec)
    out.update({
        "store_id": rec["store_id"],
        "menu_item_id": rec["menu_item_id"],
        "actor_channel_id": rec["actor_channel_id"],
        "event_type": rec["event_type"],
        "effective_at": clock.fmt(rec["effective_at"]),
        "propagated_listing_count": rec["propagated_listing_count"],
        "skipped_listing_count": rec["skipped_listing_count"],
        "held_order_count": rec["held_order_count"],
    })
    return out


def order(rec):
    out = _common(rec)
    out.update({
        "store_id": rec["store_id"],
        "channel_id": rec["channel_id"],
        "menu_version_id": rec["menu_version_id"],
        "remittance_statement_id": rec["remittance_statement_id"],
        "external_ref": rec["external_ref"],
        "fulfillment_mode": rec["fulfillment_mode"],
        "tip_cents": rec["tip_cents"],
        "subtotal_cents": rec["subtotal_cents"],
        "markup_cents": rec["markup_cents"],
        "tax_cents": rec["tax_cents"],
        "service_fee_cents": rec["service_fee_cents"],
        "commission_cents": rec["commission_cents"],
        "channel_collected_cents": rec["channel_collected_cents"],
        "brand_net_cents": rec["brand_net_cents"],
        "refunded_total_cents": rec["refunded_total_cents"],
        "bucket_index": rec["bucket_index"],
        "promised_ready_at": clock.fmt(rec["promised_ready_at"]),
        "injection_status": rec["injection_status"],
        "injection_attempt_count": rec["injection_attempt_count"],
        "fulfillment_status": rec["fulfillment_status"],
        "settlement_status": rec["settlement_status"],
    })
    return out


def order_line(rec):
    out = _journal(rec)
    out.update({
        "order_id": rec["order_id"],
        "sku": rec["sku"],
        "quantity": rec["quantity"],
        "base_price_cents": rec["base_price_cents"],
        "unit_price_cents": rec["unit_price_cents"],
        "tax_bps": rec["tax_bps"],
        "line_subtotal_cents": rec["line_subtotal_cents"],
        "line_tax_cents": rec["line_tax_cents"],
    })
    return out


def injection_attempt(rec):
    out = _journal(rec)
    out.update({
        "order_id": rec["order_id"],
        "attempt_number": rec["attempt_number"],
        "pos_result_code": rec["pos_result_code"],
        "outcome": rec["outcome"],
        "attempted_at": clock.fmt(rec["attempted_at"]),
    })
    return out


def courier_network(rec):
    out = _common(rec)
    out.update({
        "code": rec["code"],
        "name": rec["name"],
        "network_type": rec["network_type"],
        "priority_rank": rec["priority_rank"],
        "per_delivery_fee_cents": rec["per_delivery_fee_cents"],
        "handoff_sla_seconds": rec["handoff_sla_seconds"],
        "dispatch_buffer_seconds": rec["dispatch_buffer_seconds"],
        "max_concurrent_assignments": rec["max_concurrent_assignments"],
        "is_active": rec["is_active"],
        "open_assignment_count": rec["open_assignment_count"],
        "penalty_accrued_cents": rec["penalty_accrued_cents"],
    })
    return out


def assignment(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "courier_network_id": rec["courier_network_id"],
        "state": rec["state"],
        "offered_at": clock.fmt(rec["offered_at"]),
        "accepted_at": clock.fmt(rec["accepted_at"]),
        "handoff_deadline_at": clock.fmt(rec["handoff_deadline_at"]),
        "occupancy_until": clock.fmt(rec["occupancy_until"]),
        "handoff_at": clock.fmt(rec["handoff_at"]),
        "delivered_at": clock.fmt(rec["delivered_at"]),
        "handoff_lateness_seconds": rec["handoff_lateness_seconds"],
        "handoff_penalty_cents": rec["handoff_penalty_cents"],
        "sla_breached": rec["sla_breached"],
        "delivery_fee_cents": rec["delivery_fee_cents"],
    })
    return out


def adjustment(rec):
    out = _common(rec)
    out.update({
        "order_id": rec["order_id"],
        "channel_id": rec["channel_id"],
        "remittance_statement_id": rec["remittance_statement_id"],
        "adjustment_type": rec["adjustment_type"],
        "amount_cents": rec["amount_cents"],
        "reason_code": rec["reason_code"],
        "state": rec["state"],
        "revision_round": rec["revision_round"],
        "commission_relief_cents": rec["commission_relief_cents"],
        "proposed_by_user_id": rec["proposed_by_user_id"],
        "accepted_at": clock.fmt(rec["accepted_at"]),
        "reversed_at": clock.fmt(rec["reversed_at"]),
    })
    return out


def statement(rec):
    out = _common(rec)
    out.update({
        "channel_id": rec["channel_id"],
        "period_start": clock.fmt(rec["period_start"]),
        "period_end": clock.fmt(rec["period_end"]),
        "state": rec["state"],
        "order_count": rec["order_count"],
        "gross_sales_cents": rec["gross_sales_cents"],
        "adjustment_total_cents": rec["adjustment_total_cents"],
        "tier_base_cents": rec["tier_base_cents"],
        "tier": rec["tier"],
        "commission_cents": rec["commission_cents"],
        "rebate_cents": rec["rebate_cents"],
        "net_payable_cents": rec["net_payable_cents"],
        "open_adjustment_count": rec["open_adjustment_count"],
        "reconciled_by_user_id": rec["reconciled_by_user_id"],
        "settled_at": clock.fmt(rec["settled_at"]),
    })
    return out
