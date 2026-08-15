"""Payload factories — one per entity, input fields only (PRD §3 narratives)."""

DEFAULTS = {
    "DISTRIBUTOR_NAME": "Dairy Dist",
    "CREDIT_TERMS_DAYS": 7,
    "ROUTE_NAME": "Route 1",
    "SERVICE_WEEKDAYS": ["MON"],
    "DRIVER_NAME": "Dan Driver",
    "CDL_CLASS": "A",
    "STORE_NAME": "Store 1",
    "CREDIT_LIMIT_CENTS": 100000000,
    "PRODUCT_NAME": "Whole Milk Gal",
    "UNITS_PER_CASE": 1,
    "SHELF_LIFE_DAYS": 14,
    "LIST_PRICE_CENTS": 250,
    "TRUCK_PLATE": "TK-1",
    "CASE_CAPACITY": 1000,
    "SERVICE_DATE": "2026-08-10",
    "PRICING_MONTH": "2026-08",
    "ASKING_PRICE_CENTS": 5000000,
}


def create_distributor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DISTRIBUTOR_NAME"],
        "license_number": "LIC-1",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(distributor_id, route_code, **overrides) -> dict:
    defaults = {
        "distributor_id": distributor_id,
        "route_code": route_code,
        "name": DEFAULTS["ROUTE_NAME"],
        "service_weekdays": list(DEFAULTS["SERVICE_WEEKDAYS"]),
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(distributor_id, **overrides) -> dict:
    defaults = {
        "distributor_id": distributor_id,
        "name": DEFAULTS["DRIVER_NAME"],
        "cdl_class": DEFAULTS["CDL_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(route_id, store_code, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "store_code": store_code,
        "name": DEFAULTS["STORE_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(sku, **overrides) -> dict:
    defaults = {
        "sku": sku,
        "name": DEFAULTS["PRODUCT_NAME"],
        "units_per_case": DEFAULTS["UNITS_PER_CASE"],
        "shelf_life_days": DEFAULTS["SHELF_LIFE_DAYS"],
        "regulated": False,
    }
    defaults.update(overrides)
    return defaults


def create_standing_par_payload(product_id, expected_store_version, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "expected_store_version": expected_store_version,
    }
    defaults.update(overrides)
    return defaults


def create_pricing_period_payload(month=DEFAULTS["PRICING_MONTH"], **overrides) -> dict:
    defaults = {"month": month}
    defaults.update(overrides)
    return defaults


def create_announcement_payload(
    kind,
    expected_pricing_period_version,
    class_i_base_cents_per_cwt=2000,
    processor_assessment_cents_per_cwt=35,
    hauling_cents_per_cwt=60,
    diesel_index_cents=299,
    **overrides,
) -> dict:
    defaults = {
        "kind": kind,
        "class_i_base_cents_per_cwt": class_i_base_cents_per_cwt,
        "processor_assessment_cents_per_cwt": processor_assessment_cents_per_cwt,
        "hauling_cents_per_cwt": hauling_cents_per_cwt,
        "diesel_index_cents": diesel_index_cents,
        "expected_pricing_period_version": expected_pricing_period_version,
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(route_id, driver_id, service_date=None, **overrides) -> dict:
    service_date = service_date or DEFAULTS["SERVICE_DATE"]
    defaults = {
        "route_id": route_id,
        "driver_id": driver_id,
        "service_date": service_date,
        "truck_plate": DEFAULTS["TRUCK_PLATE"],
        "case_capacity": DEFAULTS["CASE_CAPACITY"],
        "planned_depart_at": f"{service_date}T05:00:00Z",
        "planned_return_at": f"{service_date}T13:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(store_id, trip_id, lines, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "trip_id": trip_id,
        "lines": lines,
        "delivery_window_start": "2026-08-10T08:00:00Z",
        "delivery_window_end": "2026-08-10T08:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def order_line(product_id, quantity_units) -> dict:
    return {"product_id": product_id, "quantity_units": quantity_units}


def delivered_line(product_id, delivered_units, scanned_code_date) -> dict:
    return {
        "product_id": product_id,
        "delivered_units": delivered_units,
        "scanned_code_date": scanned_code_date,
    }


def create_temperature_reading_payload(recorded_at, temp_tenths_f, zone) -> dict:
    return {
        "recorded_at": recorded_at,
        "temp_tenths_f": temp_tenths_f,
        "zone": zone,
    }


def create_return_payload(
    order_id, store_id, pickup_trip_id, product_id, quantity_units,
    reason_code, scanned_code_date, **overrides,
) -> dict:
    defaults = {
        "order_id": order_id,
        "store_id": store_id,
        "pickup_trip_id": pickup_trip_id,
        "product_id": product_id,
        "quantity_units": quantity_units,
        "reason_code": reason_code,
        "scanned_code_date": scanned_code_date,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents) -> dict:
    return {"amount_cents": amount_cents}


def create_crate_transaction_payload(kind, crate_count, **overrides) -> dict:
    defaults = {"kind": kind, "crate_count": crate_count}
    defaults.update(overrides)
    return defaults


def create_listing_payload(route_id, **overrides) -> dict:
    defaults = {
        "route_id": route_id,
        "asking_price_cents": DEFAULTS["ASKING_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(buyer_distributor_id, offer_price_cents) -> dict:
    return {
        "buyer_distributor_id": buyer_distributor_id,
        "offer_price_cents": offer_price_cents,
    }


def create_store_patch_payload(expected_store_version, **fields) -> dict:
    payload = {"expected_store_version": expected_store_version}
    payload.update(fields)
    return payload
