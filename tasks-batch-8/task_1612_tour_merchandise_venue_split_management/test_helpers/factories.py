"""Payload factories — one per entity, input fields only.

Optional fields are included only when explicitly provided so tests can
exercise server-side defaults by omission.
"""
from .constants import (
    DEFAULT_CASH_FLOAT_CENTS,
    DEFAULT_FLAT_COMMISSION_BPS,
    DEFAULT_ROYALTY_CONFIG,
    DEFAULT_SHOW_DATE,
)


def create_tour_payload(name="Test Tour", artist_name="Test Artist",
                        standard_rate_bps=None, tier_threshold_cents=None,
                        tier_bonus_bps=None, licensed_flat_per_unit_cents=None,
                        licensed_rate_bps=None, cash_variance_tolerance_cents=None,
                        default_size_curve=None):
    """Royalty config fields are required; the two operational settings are
    optional and omitted unless given (so the server default applies)."""
    payload = {
        "name": name,
        "artist_name": artist_name,
        "standard_rate_bps": (DEFAULT_ROYALTY_CONFIG["standard_rate_bps"]
                              if standard_rate_bps is None else standard_rate_bps),
        "tier_threshold_cents": (DEFAULT_ROYALTY_CONFIG["tier_threshold_cents"]
                                 if tier_threshold_cents is None else tier_threshold_cents),
        "tier_bonus_bps": (DEFAULT_ROYALTY_CONFIG["tier_bonus_bps"]
                           if tier_bonus_bps is None else tier_bonus_bps),
        "licensed_flat_per_unit_cents": (
            DEFAULT_ROYALTY_CONFIG["licensed_flat_per_unit_cents"]
            if licensed_flat_per_unit_cents is None else licensed_flat_per_unit_cents),
        "licensed_rate_bps": (DEFAULT_ROYALTY_CONFIG["licensed_rate_bps"]
                              if licensed_rate_bps is None else licensed_rate_bps),
    }
    if cash_variance_tolerance_cents is not None:
        payload["cash_variance_tolerance_cents"] = cash_variance_tolerance_cents
    if default_size_curve is not None:
        payload["default_size_curve"] = default_size_curve
    return payload


def royalty_config_payload(standard_rate_bps, tier_threshold_cents,
                           tier_bonus_bps, licensed_flat_per_unit_cents,
                           licensed_rate_bps, expected_tour_version):
    return {
        "standard_rate_bps": standard_rate_bps,
        "tier_threshold_cents": tier_threshold_cents,
        "tier_bonus_bps": tier_bonus_bps,
        "licensed_flat_per_unit_cents": licensed_flat_per_unit_cents,
        "licensed_rate_bps": licensed_rate_bps,
        "expected_tour_version": expected_tour_version,
    }


def create_show_payload(tour_id, city="Springfield", venue_name="Test Hall",
                        show_date=DEFAULT_SHOW_DATE, commission_mode="FLAT",
                        flat_commission_bps=DEFAULT_FLAT_COMMISSION_BPS,
                        commission_tiers=None, size_curve=None):
    payload = {
        "tour_id": tour_id,
        "city": city,
        "venue_name": venue_name,
        "show_date": show_date,
        "commission_mode": commission_mode,
    }
    if flat_commission_bps is not None:
        payload["flat_commission_bps"] = flat_commission_bps
    if commission_tiers is not None:
        payload["commission_tiers"] = commission_tiers
    if size_curve is not None:
        payload["size_curve"] = size_curve
    return payload


def create_product_payload(tour_id, sku="SKU-1", name="Product",
                           product_type="REGULAR", royalty_treatment="STANDARD",
                           sized=False, base_price_cents=4000,
                           bundle_components=None, initial_stock_by_size=None):
    if initial_stock_by_size is None:
        initial_stock_by_size = (
            {"OS": 1000} if not sized else {"S": 100, "M": 100, "L": 100, "XL": 100})
    payload = {
        "tour_id": tour_id,
        "sku": sku,
        "name": name,
        "product_type": product_type,
        "royalty_treatment": royalty_treatment,
        "sized": sized,
        "base_price_cents": base_price_cents,
        "initial_stock_by_size": initial_stock_by_size,
    }
    if bundle_components is not None:
        payload["bundle_components"] = bundle_components
    return payload


def create_show_product_payload(show_id, product_id, price_cents):
    return {"show_id": show_id, "product_id": product_id, "price_cents": price_cents}


def reprice_payload(price_cents, expected_show_product_version):
    return {
        "price_cents": price_cents,
        "expected_show_product_version": expected_show_product_version,
    }


def generate_allocations_payload(product_id, total_units):
    return {"product_id": product_id, "total_units": total_units}


def create_seller_payload(tour_id, display_name="Seller A", seller_code="SELLER-A"):
    return {"tour_id": tour_id, "display_name": display_name, "seller_code": seller_code}


def create_seller_session_payload(show_id, seller_id,
                                  cash_float_cents=DEFAULT_CASH_FLOAT_CENTS):
    return {"show_id": show_id, "seller_id": seller_id,
            "cash_float_cents": cash_float_cents}


def count_out_payload(counted_cash_cents):
    return {"counted_cash_cents": counted_cash_cents}


def verify_payload(decision, variance_override=None):
    payload = {"decision": decision}
    if variance_override is not None:
        payload["variance_override"] = variance_override
    return payload


def create_sale_record_payload(session_id, allocation_id, quantity, tender):
    return {
        "session_id": session_id,
        "allocation_id": allocation_id,
        "quantity": quantity,
        "tender": tender,
    }


def void_payload(void_reason=None):
    payload = {}
    if void_reason is not None:
        payload["void_reason"] = void_reason
    return payload


def create_online_order_payload(tour_id, product_id, quantity, size=None):
    payload = {"tour_id": tour_id, "product_id": product_id, "quantity": quantity}
    if size is not None:
        payload["size"] = size
    return payload


def dispute_payload(reason):
    return {"reason": reason}


def closeout_payload(lines, actual_proceeds_cents, handling_fee_cents):
    return {
        "lines": lines,
        "actual_proceeds_cents": actual_proceeds_cents,
        "handling_fee_cents": handling_fee_cents,
    }


def create_shipment_payload(tour_id, origin_type, destination_show_id, lines,
                            origin_show_id=None):
    payload = {
        "tour_id": tour_id,
        "origin_type": origin_type,
        "destination_show_id": destination_show_id,
        "lines": lines,
    }
    if origin_show_id is not None:
        payload["origin_show_id"] = origin_show_id
    return payload
