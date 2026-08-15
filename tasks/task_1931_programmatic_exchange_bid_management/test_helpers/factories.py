"""Payload factories — one per entity, input fields only."""
from .constants import (
    BATCH_PERIOD_END,
    BATCH_PERIOD_START,
    DEFAULT_DAILY_CAP_MICROS,
    DEFAULT_MAX_QPS,
    FLIGHT_END,
    FLIGHT_START,
)


def create_publisher_payload(name="Pub", domain="p.com", payment_terms=None,
                             **overrides):
    payload = {"name": name, "domain": domain}
    if payment_terms is not None:
        payload["payment_terms"] = payment_terms
    payload.update(overrides)
    return payload


def create_demand_partner_payload(name="DP", seat_id="seat-1",
                                  max_qps=DEFAULT_MAX_QPS,
                                  daily_cap_micros=DEFAULT_DAILY_CAP_MICROS,
                                  **overrides):
    payload = {
        "name": name,
        "seat_id": seat_id,
        "max_qps": max_qps,
        "daily_cap_micros": daily_cap_micros,
    }
    payload.update(overrides)
    return payload


def create_package_payload(name="Pkg", ad_format="DISPLAY",
                           category_tags=("IAB1",),
                           base_floor_cpm_micros=500000, **overrides):
    payload = {
        "name": name,
        "ad_format": ad_format,
        "category_tags": list(category_tags),
        "base_floor_cpm_micros": base_floor_cpm_micros,
    }
    payload.update(overrides)
    return payload


def create_seasonal_window_payload(package_id, name="W",
                                   start_date="2026-11-20",
                                   end_date="2026-11-30",
                                   multiplier_bps=15000, **overrides):
    payload = {
        "package_id": package_id,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "multiplier_bps": multiplier_bps,
    }
    payload.update(overrides)
    return payload


def create_deal_payload(package_id, demand_partner_id,
                        deal_type="PMP_STANDARD", auction_type="FIRST_PRICE",
                        floor_cpm_micros=500000, start_at=FLIGHT_START,
                        end_at=FLIGHT_END, committed_impressions=None,
                        **overrides):
    payload = {
        "package_id": package_id,
        "demand_partner_id": demand_partner_id,
        "deal_type": deal_type,
        "auction_type": auction_type,
        "floor_cpm_micros": floor_cpm_micros,
        "start_at": start_at,
        "end_at": end_at,
    }
    if committed_impressions is not None:
        payload["committed_impressions"] = committed_impressions
    payload.update(overrides)
    return payload


def create_supply_chain_node_payload(package_id, seller_domain="ssp1.com",
                                     fee_bps=1000, parent_node_id=None,
                                     **overrides):
    payload = {
        "package_id": package_id,
        "seller_domain": seller_domain,
        "fee_bps": fee_bps,
    }
    if parent_node_id is not None:
        payload["parent_node_id"] = parent_node_id
    payload.update(overrides)
    return payload


def create_blocklist_entry_payload(scope="EXCHANGE",
                                   rule_type="ADVERTISER_DOMAIN",
                                   value="evil.com", publisher_id=None,
                                   deal_id=None, **overrides):
    payload = {"scope": scope, "rule_type": rule_type, "value": value}
    if publisher_id is not None:
        payload["publisher_id"] = publisher_id
    if deal_id is not None:
        payload["deal_id"] = deal_id
    payload.update(overrides)
    return payload


def make_bid(bid_cpm_micros=1_000_000, impression_count=1000,
             creative_domain="a.com"):
    return {
        "bid_cpm_micros": bid_cpm_micros,
        "impression_count": impression_count,
        "creative_domain": creative_domain,
    }


def execute_auction_payload(publisher_id, bids):
    return {"publisher_id": publisher_id, "bids": list(bids)}


def create_reconciliation_report_payload(deal_id, period_start="2026-08-01",
                                         period_end="2026-08-02", **overrides):
    payload = {
        "deal_id": deal_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def resolve_report_payload(resolution_type, adjustment_micros=None):
    payload = {"resolution_type": resolution_type}
    if adjustment_micros is not None:
        payload["adjustment_micros"] = adjustment_micros
    return payload


def create_payout_batch_payload(period_start=BATCH_PERIOD_START,
                                period_end=BATCH_PERIOD_END, **overrides):
    payload = {"period_start": period_start, "period_end": period_end}
    payload.update(overrides)
    return payload


def write_off_payload(write_off_reason="unrecoverable"):
    return {"write_off_reason": write_off_reason}
