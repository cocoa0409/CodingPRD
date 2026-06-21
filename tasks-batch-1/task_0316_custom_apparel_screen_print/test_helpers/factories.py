"""Payload factories — one per entity, input fields only."""


def create_shop_payload(**overrides) -> dict:
    defaults = {"name": "Ink Co"}
    defaults.update(overrides)
    return defaults


def create_customer_payload(shop_id, **overrides) -> dict:
    defaults = {"shop_id": shop_id, "name": "Acme", "email": "a@x.com"}
    defaults.update(overrides)
    return defaults


def create_decoration_method_payload(shop_id, method_type="SCREEN_PRINT", **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "method_type": method_type,
        "name": "Plastisol" if method_type == "SCREEN_PRINT" else "Tajima",
    }
    defaults.update(overrides)
    return defaults


def create_garment_style_payload(shop_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "sku_code": "GIL-5000",
        "name": "Tee",
        "blank_cost_cents": 350,
        "available_colors": ["BLACK"],
        "available_sizes": ["L"],
    }
    defaults.update(overrides)
    return defaults


def create_blank_sku_payload(color="BLACK", size="L", total_stock_qty=200, **overrides) -> dict:
    defaults = {"color": color, "size": size, "total_stock_qty": total_stock_qty}
    defaults.update(overrides)
    return defaults


def restock_payload(add_qty, **overrides) -> dict:
    defaults = {"add_qty": add_qty}
    defaults.update(overrides)
    return defaults


def create_press_payload(shop_id, **overrides) -> dict:
    defaults = {"shop_id": shop_id, "name": "P1"}
    defaults.update(overrides)
    return defaults


def create_embroidery_station_payload(shop_id, **overrides) -> dict:
    defaults = {"shop_id": shop_id, "name": "S1"}
    defaults.update(overrides)
    return defaults


def create_order_payload(shop_id, customer_id, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "customer_id": customer_id,
        "requested_ship_date": "2026-06-20T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(garment_style_id, decoration_method_id, size_run, **overrides) -> dict:
    defaults = {
        "garment_style_id": garment_style_id,
        "decoration_method_id": decoration_method_id,
        "color": "BLACK",
        "num_locations": 1,
        "num_colors": 1,
        "size_run": size_run,
    }
    defaults.update(overrides)
    return defaults


def create_art_proof_payload(title="Front", art_hash="h1", **overrides) -> dict:
    defaults = {"title": title, "art_hash": art_hash}
    defaults.update(overrides)
    return defaults


def approve_proof_payload(expected_order_version, **overrides) -> dict:
    defaults = {"expected_order_version": expected_order_version}
    defaults.update(overrides)
    return defaults


def create_production_run_payload(window_start, window_end, **overrides) -> dict:
    defaults = {"window_start": window_start, "window_end": window_end}
    defaults.update(overrides)
    return defaults


def complete_run_payload(good_units, spoiled_units, **overrides) -> dict:
    defaults = {"good_units": good_units, "spoiled_units": spoiled_units}
    defaults.update(overrides)
    return defaults


def set_clock_payload(shop_id, to_iso8601, **overrides) -> dict:
    defaults = {"shop_id": shop_id, "to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
