"""
Request-payload factories.

Every factory returns a fully valid payload for the endpoint it names and lets
a caller override any field with a keyword argument, so a test that wants one
boundary value does not have to restate the other seven fields. Passing
``field=None`` is an override to the JSON null; use ``drop=("field",)`` to omit
a key entirely (which is how the required-field refusals are exercised).
"""

from typing import Any, Dict, Iterable, List, Optional

from .constants import (
    BASIS_RAW_GENERATION,
    CURRENT_CBA_VERSION,
    DELIVERY_REALTIME,
    HOLDER_LICENSEE,
    METRIC_TOTAL_DISTANCE,
    REASON_WRONG_CLOCK,
    RIGHTS_CLASS_COMMERCIAL_LICENSE,
    SCOPE_BIOMETRIC_TRACKING,
    SCOPE_POSITIONAL,
    TIER_GOLD,
)


def _finish(payload: Dict[str, Any], overrides: Dict[str, Any], drop: Optional[Iterable[str]]) -> Dict[str, Any]:
    payload.update(overrides)
    for key in drop or ():
        payload.pop(key, None)
    return payload


# ---------------------------------------------------------------------------
# Venues and installations
# ---------------------------------------------------------------------------

def venue_payload(drop: Optional[Iterable[str]] = None, **overrides) -> Dict[str, Any]:
    """POST /venues — a one-rig venue with a 100 mbps pipe and a 200 ms floor."""
    return _finish(
        {
            "name": "Harbor Arena",
            "city": "Harbor",
            "tracking_tech": "HYBRID",
            "required_certified_installations": 1,
            "transport_capacity_mbps": 100,
            "min_achievable_latency_ms": 200,
        },
        overrides,
        drop,
    )


def installation_payload(
    venue_id: str, drop: Optional[Iterable[str]] = None, **overrides
) -> Dict[str, Any]:
    """POST /installations."""
    return _finish(
        {
            "venue_id": venue_id,
            "rig_label": "RIG-A",
            "modality": "UWB_ANCHOR",
        },
        overrides,
        drop,
    )


def calibration_run_payload(
    drop: Optional[Iterable[str]] = None, **overrides
) -> Dict[str, Any]:
    """POST /installations/{id}/calibration-runs — a passing run by default."""
    return _finish(
        {
            "axis_rms_x_mm": 90.0,
            "axis_rms_y_mm": 90.0,
            "axis_rms_z_mm": 90.0,
            "sample_count": 6000,
            "reference_point_count": 16,
        },
        overrides,
        drop,
    )


def uniform_calibration_run_payload(axis_mm: float, **overrides) -> Dict[str, Any]:
    """A calibration run whose three axis errors are equal, so the quadratic
    mean of the three equals that same figure."""
    return calibration_run_payload(
        axis_rms_x_mm=axis_mm,
        axis_rms_y_mm=axis_mm,
        axis_rms_z_mm=axis_mm,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Clubs, players, consent
# ---------------------------------------------------------------------------

def club_payload(drop: Optional[Iterable[str]] = None, **overrides) -> Dict[str, Any]:
    """POST /clubs."""
    return _finish({"name": "Harbor FC", "market_code": "HBR"}, overrides, drop)


def away_club_payload(**overrides) -> Dict[str, Any]:
    return club_payload(name="Summit SC", market_code="SMT", **overrides)


def third_club_payload(**overrides) -> Dict[str, Any]:
    return club_payload(name="Vale United", market_code="VAL", **overrides)


def player_payload(
    club_id: str, drop: Optional[Iterable[str]] = None, **overrides
) -> Dict[str, Any]:
    """POST /players."""
    return _finish(
        {"club_id": club_id, "full_name": "Ada Ruiz", "jersey_number": 9},
        overrides,
        drop,
    )


def consent_record_payload(
    drop: Optional[Iterable[str]] = None, **overrides
) -> Dict[str, Any]:
    """POST /players/{id}/consent-records — biometric scope under the live CBA."""
    return _finish(
        {
            "scope": SCOPE_BIOMETRIC_TRACKING,
            "cba_agreement_version": CURRENT_CBA_VERSION,
            "effective_from_utc": "2026-08-01T00:00:00Z",
            "expires_at_utc": "2026-12-31T00:00:00Z",
        },
        overrides,
        drop,
    )


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------

def game_payload(
    venue_id: str,
    home_club_id: str,
    away_club_id: str,
    drop: Optional[Iterable[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """POST /games — 240 licensable minutes of G1 output."""
    return _finish(
        {
            "venue_id": venue_id,
            "home_club_id": home_club_id,
            "away_club_id": away_club_id,
            "scheduled_start_utc": "2026-08-01T18:00:00Z",
            "tracking_generation": "G1",
            "licensable_minutes": 240,
        },
        overrides,
        drop,
    )


# ---------------------------------------------------------------------------
# Event tags and corrections
# ---------------------------------------------------------------------------

def event_tag_payload(
    game_id: str,
    player_id: str,
    expected_game_version: int,
    drop: Optional[Iterable[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """POST /event-tags."""
    return _finish(
        {
            "game_id": game_id,
            "player_id": player_id,
            "tag_type": "SHOT",
            "clock_ms": 120000,
            "confidence": 0.9,
            "expected_game_version": expected_game_version,
        },
        overrides,
        drop,
    )


def correction_request_payload(
    drop: Optional[Iterable[str]] = None, **overrides
) -> Dict[str, Any]:
    """POST /event-tags/{id}/correction-requests — a WRONG_CLOCK dispute."""
    return _finish(
        {"reason_code": REASON_WRONG_CLOCK, "proposed_clock_ms": 121000},
        overrides,
        drop,
    )


def wrong_player_correction_payload(
    proposed_player_id: str, **overrides
) -> Dict[str, Any]:
    """A WRONG_PLAYER dispute carries proposed_player_id and no clock."""
    payload = {
        "reason_code": "WRONG_PLAYER",
        "proposed_player_id": proposed_player_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Rights windows
# ---------------------------------------------------------------------------

def rights_window_payload(
    holder_id: Optional[str] = None,
    drop: Optional[Iterable[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """POST /games/{id}/rights-windows — a three-hour US commercial licence."""
    payload: Dict[str, Any] = {
        "rights_class": RIGHTS_CLASS_COMMERCIAL_LICENSE,
        "holder_type": HOLDER_LICENSEE,
        "territory": "US",
        "window_start_utc": "2026-08-01T18:00:00Z",
        "window_end_utc": "2026-08-01T21:00:00Z",
        "max_latency_ms": 2000,
        "allowed_scopes": [SCOPE_POSITIONAL],
    }
    if holder_id is not None:
        payload["holder_id"] = holder_id
    return _finish(payload, overrides, drop)


def league_archive_window_payload(
    drop: Optional[Iterable[str]] = None, **overrides
) -> Dict[str, Any]:
    """A LEAGUE_ARCHIVE window draws on the reserve pool and names no holder."""
    payload: Dict[str, Any] = {
        "rights_class": "LEAGUE_ARCHIVE",
        "holder_type": "LEAGUE",
        "territory": "GLOBAL",
        "window_start_utc": "2026-08-02T00:00:00Z",
        "window_end_utc": "2026-08-02T00:36:00Z",
        "max_latency_ms": 5000,
        "allowed_scopes": [SCOPE_POSITIONAL],
    }
    return _finish(payload, overrides, drop)


# ---------------------------------------------------------------------------
# Licensees, feed sessions, usage records
# ---------------------------------------------------------------------------

def licensee_payload(drop: Optional[Iterable[str]] = None, **overrides) -> Dict[str, Any]:
    """POST /licensees — a GOLD broadcaster with 5000 units and no biometrics."""
    return _finish(
        {
            "name": "Northstar Data",
            "licensee_class": "BROADCASTER",
            "tier": TIER_GOLD,
            "granted_units": 5000,
            "biometric_entitled": False,
        },
        overrides,
        drop,
    )


def feed_session_payload(
    game_id: str,
    rights_window_id: str,
    drop: Optional[Iterable[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """POST /feed-sessions — 20 mbps of real-time positional output for 30 min."""
    return _finish(
        {
            "game_id": game_id,
            "rights_window_id": rights_window_id,
            "delivery_mode": DELIVERY_REALTIME,
            "bandwidth_mbps": 20,
            "window_start_utc": "2026-08-01T18:00:00Z",
            "window_end_utc": "2026-08-01T18:30:00Z",
            "requested_latency_ms": 250,
            "scope": [SCOPE_POSITIONAL],
        },
        overrides,
        drop,
    )


def usage_record_payload(
    drop: Optional[Iterable[str]] = None, **overrides
) -> Dict[str, Any]:
    """POST /feed-sessions/{id}/usage-records."""
    return _finish(
        {
            "sampled_at_utc": "2026-08-01T18:05:00Z",
            "bandwidth_mbps": 20,
            "duration_seconds": 300,
            "latency_p95_ms": 240,
        },
        overrides,
        drop,
    )


# ---------------------------------------------------------------------------
# Normalization runs
# ---------------------------------------------------------------------------

def normalization_run_payload(
    segment_values: Optional[List[float]] = None,
    drop: Optional[Iterable[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """POST /games/{id}/normalization-runs."""
    return _finish(
        {
            "basis": BASIS_RAW_GENERATION,
            "metric_code": METRIC_TOTAL_DISTANCE,
            "segment_values": (
                [123.456, 78.912, 45.678, 12.345]
                if segment_values is None
                else segment_values
            ),
        },
        overrides,
        drop,
    )
