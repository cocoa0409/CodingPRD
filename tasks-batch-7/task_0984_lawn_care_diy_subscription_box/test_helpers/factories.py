"""Payload factories — one per creatable resource, input fields only.

Defaults come from the catalog fixtures in constants.py; every factory
accepts **overrides so tests control exactly the fields under study.
"""
from datetime import datetime, timedelta

from .constants import CATALOG_FIXTURES


def catalog_product_payload(sku="FERT-01", **overrides) -> dict:
    """Catalog product payload; defaults to the FERT-01 fixture product."""
    base = dict(CATALOG_FIXTURES.get(sku, CATALOG_FIXTURES["FERT-01"]))
    if sku not in CATALOG_FIXTURES:
        base["sku"] = sku
    base.update(overrides)
    return base


def customer_payload(email="user@x.com", full_name="Test User", climate_zone="COOL",
                     referred_by_code=None, **overrides) -> dict:
    payload = {"email": email, "full_name": full_name, "climate_zone": climate_zone}
    if referred_by_code is not None:
        payload["referred_by_code"] = referred_by_code
    payload.update(overrides)
    return payload


def lawn_payload(customer_id, label="Front", lawn_size_sqm=100,
                 grass_type="COOL_SEASON", region="NE-OH", **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "label": label,
        "lawn_size_sqm": lawn_size_sqm,
        "grass_type": grass_type,
        "region": region,
    }
    payload.update(overrides)
    return payload


def soil_test_payload(lawn_id, **overrides) -> dict:
    payload = {"lawn_id": lawn_id}
    payload.update(overrides)
    return payload


def lab_result_analyzed_payload(ph=6.5, nitrogen_ppm=20, phosphorus_ppm=15,
                                potassium_ppm=80, organic_matter_pct=3.1,
                                **overrides) -> dict:
    payload = {
        "outcome": "ANALYZED",
        "ph": ph,
        "nitrogen_ppm": nitrogen_ppm,
        "phosphorus_ppm": phosphorus_ppm,
        "potassium_ppm": potassium_ppm,
        "organic_matter_pct": organic_matter_pct,
    }
    payload.update(overrides)
    return payload


def lab_result_rejected_payload(rejection_reason="insufficient mass", **overrides) -> dict:
    payload = {"outcome": "REJECTED", "rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


def plan_line(product_sku="FERT-01", qty_units=1, target_month=6) -> dict:
    return {"product_sku": product_sku, "qty_units": qty_units, "target_month": target_month}


def plan_payload(lawn_id, soil_test_id, plan_lines=None, season_year=2026, **overrides) -> dict:
    if plan_lines is None:
        plan_lines = [plan_line()]
    payload = {
        "lawn_id": lawn_id,
        "soil_test_id": soil_test_id,
        "season_year": season_year,
        "plan_lines": plan_lines,
    }
    payload.update(overrides)
    return payload


def subscription_payload(customer_id, plan_id, billing_cycle="MONTHLY",
                         auto_ship=False, next_ship_date=None, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "plan_id": plan_id,
        "billing_cycle": billing_cycle,
        "auto_ship": auto_ship,
    }
    if next_ship_date is not None:
        payload["next_ship_date"] = next_ship_date
    payload.update(overrides)
    return payload


def _plus_days(iso_ts: str, days: int) -> str:
    dt = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ")
    return (dt + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def shipment_line(product_sku="FERT-01", qty_units=1) -> dict:
    return {"product_sku": product_sku, "qty_units": qty_units}


def shipment_payload(subscription_id, lines=None, ship_date="2026-06-03T00:00:00Z",
                     box_kind="SEASONAL", delivery_window_start=None,
                     delivery_window_end=None, window_days=7, **overrides) -> dict:
    if lines is None:
        lines = [shipment_line()]
    if delivery_window_start is None:
        delivery_window_start = ship_date
    if delivery_window_end is None:
        delivery_window_end = _plus_days(delivery_window_start, window_days)
    payload = {
        "subscription_id": subscription_id,
        "box_kind": box_kind,
        "ship_date": ship_date,
        "delivery_window_start": delivery_window_start,
        "delivery_window_end": delivery_window_end,
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def application_payload(subscription_id, shipment_id, product_sku="FERT-01",
                        scheduled_date="2026-06-10", **overrides) -> dict:
    payload = {
        "subscription_id": subscription_id,
        "shipment_id": shipment_id,
        "product_sku": product_sku,
        "scheduled_date": scheduled_date,
    }
    payload.update(overrides)
    return payload


def weather_advisory_payload(region="NE-OH", date="2026-06-10", rain_probability=0.10,
                             wind_kph=5, temp_high_c=20, **overrides) -> dict:
    payload = {
        "region": region,
        "date": date,
        "rain_probability": rain_probability,
        "wind_kph": wind_kph,
        "temp_high_c": temp_high_c,
    }
    payload.update(overrides)
    return payload


def add_on_payload(subscription_id, add_on_sku="PEST-01", qty_units=1, **overrides) -> dict:
    payload = {
        "subscription_id": subscription_id,
        "add_on_sku": add_on_sku,
        "qty_units": qty_units,
    }
    payload.update(overrides)
    return payload


def claim_payload(subscription_id, shipment_id, claim_reason="OTHER",
                  evidence_url=None, **overrides) -> dict:
    payload = {
        "subscription_id": subscription_id,
        "shipment_id": shipment_id,
        "claim_reason": claim_reason,
    }
    if evidence_url is not None:
        payload["evidence_url"] = evidence_url
    payload.update(overrides)
    return payload


def ledger_adjustment_payload(customer_id, amount_cents, note="promo", **overrides) -> dict:
    payload = {"customer_id": customer_id, "amount_cents": amount_cents}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload
