"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "MACHINE_NAME": "Barrel-A",
    "MIX_PAR_OZ": 1000,
    "FLAVOR_NAME": "Tart",
    "PRICE_PER_OZ_CENTS": 55,
    "COST_PER_OZ_CENTS": 20,
    "TOPPING_NAME": "Mochi",
    "SURCHARGE_CENTS": 30,
    "INITIAL_UNITS": 50,
    "MEMBER_NAME": "Ada",
    "BUSINESS_DATE": "2026-03-01",
    "RESOURCE_NAME": "Cart-1",
    "GUEST_COUNT": 10,
}


def create_machine_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["MACHINE_NAME"],
        "mix_par_oz": DEFAULTS["MIX_PAR_OZ"],
    }
    payload.update(overrides)
    return payload


def create_flavor_payload(machine_id, **overrides) -> dict:
    payload = {
        "machine_id": machine_id,
        "name": DEFAULTS["FLAVOR_NAME"],
        "price_per_oz_cents": DEFAULTS["PRICE_PER_OZ_CENTS"],
        "cost_per_oz_cents": DEFAULTS["COST_PER_OZ_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_topping_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["TOPPING_NAME"],
        "surcharge_cents": DEFAULTS["SURCHARGE_CENTS"],
        "initial_units": DEFAULTS["INITIAL_UNITS"],
    }
    payload.update(overrides)
    return payload


def create_promotion_payload(**overrides) -> dict:
    payload = {
        "name": "Promo10",
        "discount_pct": 0.10,
        "starts_at": "2026-03-01T00:00:00Z",
        "ends_at": "2026-03-02T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_loyalty_payload(**overrides) -> dict:
    payload = {"member_name": DEFAULTS["MEMBER_NAME"]}
    payload.update(overrides)
    return payload


def create_ticket_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def add_line_payload(flavor_id, gross_weight_oz, **overrides) -> dict:
    payload = {
        "flavor_id": flavor_id,
        "gross_weight_oz": gross_weight_oz,
    }
    payload.update(overrides)
    return payload


def create_waste_event_payload(**overrides) -> dict:
    payload = {"reason": "MELT"}
    payload.update(overrides)
    return payload


def create_maintenance_window_payload(machine_id, window_start, window_end,
                                      expected_machine_version, **overrides) -> dict:
    payload = {
        "machine_id": machine_id,
        "window_start": window_start,
        "window_end": window_end,
        "expected_machine_version": expected_machine_version,
    }
    payload.update(overrides)
    return payload


def create_catering_resource_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["RESOURCE_NAME"]}
    payload.update(overrides)
    return payload


def create_catering_order_payload(resource_id, line_items, **overrides) -> dict:
    payload = {
        "resource_id": resource_id,
        "event_start": "2026-03-10T10:00:00Z",
        "event_end": "2026-03-10T12:00:00Z",
        "guest_count": DEFAULTS["GUEST_COUNT"],
        "line_items": line_items,
    }
    payload.update(overrides)
    return payload


def create_reconciliation_payload(**overrides) -> dict:
    payload = {"business_date": DEFAULTS["BUSINESS_DATE"]}
    payload.update(overrides)
    return payload


def post_adjustment_payload(amount_cents, expected_daily_reconciliation_version,
                            reason="adjustment", **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "reason": reason,
        "expected_daily_reconciliation_version": expected_daily_reconciliation_version,
    }
    payload.update(overrides)
    return payload
