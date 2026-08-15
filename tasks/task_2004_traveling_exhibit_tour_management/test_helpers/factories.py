"""Payload factories — one per entity, input fields only."""

import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


DEFAULTS = {
    "TOUR_TITLE": "Traveling Exhibit",
    "DECLARED_VALUE_CENTS": 1_000_000,
    "REFURBISHMENT_GAP_DAYS": 0,
    "BASE_FEE_CENTS": 100_000,
    "SPONSORSHIP_CREDIT_CENTS": 0,
    "CONTENTS_VALUE_CENTS": 100_000,
    "VENUE_CAP_CENTS": 0,
    "PROJECTED_ATTENDANCE": 1000,
    "INSURER_NAME": "Axis Insurance",
    "CARRIER_NAME": "FineArt Freight",
    "INSPECTOR_NAME": "R. Registrar",
}


def create_tour_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["TOUR_TITLE"],
        "exhibit_code": _uniq("EXH") + "-2026",
        "crate_count": 1,
        "declared_value_cents": DEFAULTS["DECLARED_VALUE_CENTS"],
        "refurbishment_gap_days": DEFAULTS["REFURBISHMENT_GAP_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Venue"),
        "city": "Denver",
        "climate_controlled": True,
        "max_gallery_sqm": 500,
        "local_sponsorship_cap_cents": DEFAULTS["VENUE_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_crate_payload(**overrides) -> dict:
    defaults = {
        "crate_label": _uniq("CRATE"),
        "contents_value_cents": DEFAULTS["CONTENTS_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(venue_id, expected_tour_version, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "install_start": "2026-09-01T00:00:00Z",
        "open_date": "2026-09-03T00:00:00Z",
        "close_date": "2026-10-03T00:00:00Z",
        "teardown_end": "2026-10-06T00:00:00Z",
        "projected_attendance": DEFAULTS["PROJECTED_ATTENDANCE"],
        "expected_tour_version": expected_tour_version,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "base_fee_cents": DEFAULTS["BASE_FEE_CENTS"],
        "sponsorship_credit_cents": DEFAULTS["SPONSORSHIP_CREDIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_marketing_kit_payload(**overrides) -> dict:
    defaults = {
        "language_count": 1,
        "sponsor_logo_slots": 0,
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(tour_stop_id, coverage_cents, **overrides) -> dict:
    defaults = {
        "tour_stop_id": tour_stop_id,
        "insurer_name": DEFAULTS["INSURER_NAME"],
        "coverage_cents": coverage_cents,
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(destination_stop_id, crate_ids, **overrides) -> dict:
    defaults = {
        "origin_stop_id": None,
        "destination_stop_id": destination_stop_id,
        "depart_at": "2026-08-20T00:00:00Z",
        "arrive_at": "2026-08-28T00:00:00Z",
        "carrier_name": DEFAULTS["CARRIER_NAME"],
        "crate_ids": crate_ids,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(crate_id, **overrides) -> dict:
    defaults = {
        "crate_id": crate_id,
        "inspector_name": DEFAULTS["INSPECTOR_NAME"],
        "phase": "UNPACK",
        "surface_score": 90,
        "structural_score": 80,
        "seal_intact": True,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(condition_report_id, claimed_amount_cents, line_items, **overrides) -> dict:
    defaults = {
        "condition_report_id": condition_report_id,
        "claimed_amount_cents": claimed_amount_cents,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults
