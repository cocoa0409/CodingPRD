"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import TEST_DEFAULTS

_seq = [0]


def _next(prefix: str) -> str:
    _seq[0] += 1
    return f"{prefix}-{_seq[0]:04d}"


def create_rights_asset_payload(**overrides) -> dict:
    defaults = {
        "asset_code": _next("ASSET"),
        "competition_name": "Test League",
        "season_label": "2026",
        "season_start_date": TEST_DEFAULTS["SEASON_START"],
        "season_end_date": TEST_DEFAULTS["SEASON_END"],
        "total_package_pool": 5,
        "guaranteed_rating_basis_points": TEST_DEFAULTS["GUARANTEED_RATING_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_broadcaster_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _next("Broadcaster"),
        "home_territory": "US",
        "platform_classes": ["LINEAR_TV"],
        "credit_rating": "INVESTMENT_GRADE",
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(asset_id: str, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "package_code": _next("PKG"),
        "territory_code": "US",
        "platform_class": "LINEAR_TV",
        "window_start": TEST_DEFAULTS["SEASON_START"],
        "window_end": TEST_DEFAULTS["SEASON_END"],
        "exclusivity_class": "EXCLUSIVE",
        "minimum_bid_cents": 1000000,
        "games_committed": 5,
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(bidder_id: str, **overrides) -> dict:
    defaults = {
        "bidder_id": bidder_id,
        "offered_fee_cents": 1000000,
        "upfront_pct": 0.1,
        "escalator_rate_pct": 0.0,
        "minimum_growth_pct": 0.0,
        "fee_cap_cents": 2000000,
        "production_commitment_games": 5,
        "audience_commitment_pct": 0.5,
        "exclusivity_request": "MATCH_PACKAGE",
    }
    defaults.update(overrides)
    return defaults


def execute_deal_payload(expected_deal_version: int, **overrides) -> dict:
    defaults = {
        "expected_deal_version": expected_deal_version,
        "term_start": TEST_DEFAULTS["TERM_START"],
        "term_end": TEST_DEFAULTS["TERM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_milestone_payload(**overrides) -> dict:
    defaults = {
        "season_index": 1,
        "sequence_in_season": 1,
        "due_date": TEST_DEFAULTS["DUE_DATE"],
        "milestone_weight": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_production_obligation_payload(**overrides) -> dict:
    defaults = {"season_index": 1}
    defaults.update(overrides)
    return defaults


def create_broadcast_event_payload(obligation_id: str, **overrides) -> dict:
    defaults = {
        "obligation_id": obligation_id,
        "event_code": _next("EV"),
        "scheduled_kickoff_utc": "2026-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_audience_measurement_payload(broadcast_event_id: str, **overrides) -> dict:
    defaults = {
        "broadcast_event_id": broadcast_event_id,
        "reporting_period_end": "2026-03-31T23:59:59Z",
        "rating_basis_points": 1000,
        "source": "PANEL",
    }
    defaults.update(overrides)
    return defaults


def create_sublicense_request_payload(**overrides) -> dict:
    defaults = {
        "sublicensee_name": _next("Sub"),
        "sublicensee_territory": "US",
        "sublicensee_platform_class": "LINEAR_TV",
        "requested_window_start": "2026-03-01T00:00:00Z",
        "requested_window_end": "2026-04-01T00:00:00Z",
        "proposed_fee_cents": 100000,
        "league_share_pct": 0.15,
    }
    defaults.update(overrides)
    return defaults


def create_blackout_window_payload(asset_id: str, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "territory_code": "US",
        "platform_class": "LINEAR_TV",
        "blackout_start": "2026-03-15T00:00:00Z",
        "blackout_end": "2026-03-15T23:59:59Z",
        "applies_to_sublicense_only": True,
        "reason": "Stadium attendance protection",
    }
    defaults.update(overrides)
    return defaults


def create_renewal_offer_payload(offeror_broadcaster_id: str, **overrides) -> dict:
    defaults = {
        "offer_source": "INCUMBENT_BROADCASTER",
        "offeror_broadcaster_id": offeror_broadcaster_id,
        "offered_fee_cents": 2000000,
        "escalator_rate_pct": 0.05,
    }
    defaults.update(overrides)
    return defaults
