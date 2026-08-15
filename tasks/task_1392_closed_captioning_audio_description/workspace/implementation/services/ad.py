"""ad_gap_coverage and studio_booking_window (PRD §3.5).

Coverage rounding order is pinned: per-gap utilization rounded half-up to one
decimal place first, then the mean of those utilizations rounded half-up to
one decimal place. Studio bookings use CLOSED intervals with a mandatory
30-minute turnover gap.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import DB
from errors import ApiError, ERR_VALIDATION
from util import is_int

COVERAGE_MIN_PCT = Decimal("35.0")
COVERAGE_MAX_PCT = Decimal("85.0")
STUDIO_TURNOVER_MIN = 30


def validate_gaps(gaps):
    """gaps: [{start_ms, end_ms}], end_ms > start_ms, non-overlapping, ascending."""
    if not isinstance(gaps, list):
        raise ApiError(ERR_VALIDATION, 400, "Field 'gaps' must be an array")
    prev_end = None
    for g in gaps:
        if not isinstance(g, dict) or not is_int(g.get("start_ms")) or not is_int(g.get("end_ms")):
            raise ApiError(ERR_VALIDATION, 400, "Each gap requires integer start_ms and end_ms")
        if g["end_ms"] <= g["start_ms"]:
            raise ApiError(ERR_VALIDATION, 400, "Each gap requires end_ms > start_ms")
        if prev_end is not None and g["start_ms"] < prev_end:
            raise ApiError(ERR_VALIDATION, 400, "Gaps must be non-overlapping and ascending")
        prev_end = g["end_ms"]
    return gaps


def validate_segments(segments, gaps):
    """segments: [{gap_index, duration_ms, text}]; duration_ms > 0 and no longer
    than the referenced gap."""
    if not isinstance(segments, list):
        raise ApiError(ERR_VALIDATION, 400, "Field 'segments' must be an array")
    for s in segments:
        if not isinstance(s, dict) or not is_int(s.get("gap_index")):
            raise ApiError(ERR_VALIDATION, 400, "Each segment requires an integer gap_index")
        gi = s["gap_index"]
        if gi < 0 or gi >= len(gaps):
            raise ApiError(ERR_VALIDATION, 400, "Segment gap_index does not reference a gap")
        duration_ms = s.get("duration_ms")
        if not is_int(duration_ms) or duration_ms <= 0:
            raise ApiError(ERR_VALIDATION, 400, "Segment duration_ms must be an integer > 0")
        gap = gaps[gi]
        if duration_ms > gap["end_ms"] - gap["start_ms"]:
            raise ApiError(ERR_VALIDATION, 400, "Segment duration_ms exceeds its gap length")
        if "text" not in s or not isinstance(s["text"], str):
            raise ApiError(ERR_VALIDATION, 400, "Each segment requires text")
    return segments


def compute_gap_coverage(gaps, segments):
    """Per-gap utilization (HALF_UP, 1 dp) then mean (HALF_UP, 1 dp)."""
    utils = []
    for s in segments:
        gap = gaps[s["gap_index"]]
        gap_len = Decimal(gap["end_ms"] - gap["start_ms"])
        u = (Decimal(s["duration_ms"]) / gap_len * Decimal(100)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        utils.append(u)
    mean = sum(utils) / Decimal(len(utils))
    return mean.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def studio_conflict(studio_id, candidate_track_id, ns, ne):
    """Closed-interval geometry with a mandatory 30-minute turnover gap. A
    track re-booking itself never conflicts with its own prior booking. Only
    OTHER AD tracks in RECORDING or MIX_QC with a booking present count."""
    buffer = timedelta(minutes=STUDIO_TURNOVER_MIN)
    for other in DB.ad_tracks.values():
        if other["id"] == candidate_track_id:
            continue
        if other["ad_status"] not in ("RECORDING", "MIX_QC"):
            continue
        if other["studio_id"] != studio_id:
            continue
        es, ee = other["record_start_at"], other["record_end_at"]
        if es is None or ee is None:
            continue
        # Back-to-back allowed only when >= 30 minutes separate the bookings.
        if ne + buffer <= es or ns >= ee + buffer:
            continue
        return True
    return False
