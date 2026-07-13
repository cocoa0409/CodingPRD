"""Payload factories — one per writable entity, input fields only.

Field names are exact to the PRD. Only source: input fields appear here.
"""

DEFAULTS = {
    "MUNICIPALITY_NAME": "City A",
    "MILL_NAME": "Mill 1",
    "SORT_LINE_NAME": "Line 1",
    "HAULER": "H1",
    "REVENUE_SHARE_PCT": 0.50,
    "RATED_TPH": 10,
    "COMMODITY": "OCC",
}


def create_municipality_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["MUNICIPALITY_NAME"],
        "revenue_share_pct": DEFAULTS["REVENUE_SHARE_PCT"],
    }
    payload.update(overrides)
    return payload


def create_mill_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["MILL_NAME"],
        "commodity_focus": DEFAULTS["COMMODITY"],
        "freight_rate_cents_per_ton": 0,
    }
    payload.update(overrides)
    return payload


def create_commodity_index_payload(**overrides) -> dict:
    payload = {
        "commodity": DEFAULTS["COMMODITY"],
        "price_cents_per_ton": 8000,
        "effective_start": "2026-03-01T00:00:00Z",
        "effective_end": "2026-04-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_sort_line_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SORT_LINE_NAME"],
        "rated_tph": DEFAULTS["RATED_TPH"],
    }
    payload.update(overrides)
    return payload


def create_downtime_event_payload(**overrides) -> dict:
    payload = {
        "sort_line_id": None,
        "start_at": "2026-03-01T08:00:00Z",
        "end_at": "2026-03-01T10:00:00Z",
        "reason": "jam",
    }
    payload.update(overrides)
    return payload


def create_inbound_load_payload(**overrides) -> dict:
    payload = {
        "source_municipality_id": None,
        "sort_line_id": None,
        "hauler": DEFAULTS["HAULER"],
        "gross_tons": 22,
        "tare_tons": 2,
    }
    payload.update(overrides)
    return payload


def audit_load_payload(**overrides) -> dict:
    payload = {
        "sampled_contamination_pct": 3.0,
        "audited_composition": [{"commodity": "OCC", "pct": 99}],
    }
    payload.update(overrides)
    return payload


def close_load_payload(**overrides) -> dict:
    payload = {"residual_tons": 0}
    payload.update(overrides)
    return payload


def create_bale_payload(**overrides) -> dict:
    payload = {
        "source_load_id": None,
        "commodity": DEFAULTS["COMMODITY"],
        "net_tons": 10,
        "moisture_pct": 0,
        "quality_grade": "A",
    }
    payload.update(overrides)
    return payload


def create_mill_shipment_payload(**overrides) -> dict:
    payload = {
        "mill_id": None,
        "commodity": DEFAULTS["COMMODITY"],
        "freight_cost_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_municipal_statement_payload(**overrides) -> dict:
    payload = {
        "municipality_id": None,
        "period_start": "2026-03-01T00:00:00Z",
        "period_end": "2026-04-01T00:00:00Z",
        "expected_municipality_version": 1,
    }
    payload.update(overrides)
    return payload
