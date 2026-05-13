"""Geofence polygon validation and point-in-polygon tests.

PRD §3.1: 'A polygon with fewer than 3 or more than 32 vertices, with any
duplicate vertex, or whose edges self-intersect is rejected with
ERR_INVALID_POLYGON.'
"""
from __future__ import annotations

from typing import List, Tuple


def _as_pairs(polygon: List[dict]) -> List[Tuple[float, float]]:
    """Return polygon as list of (lat, lng) tuples (validating shape only)."""
    pairs: List[Tuple[float, float]] = []
    for v in polygon:
        if not isinstance(v, dict):
            raise ValueError("vertex must be an object with lat and lng")
        if "lat" not in v or "lng" not in v:
            raise ValueError("vertex requires lat and lng")
        lat, lng = v["lat"], v["lng"]
        if not isinstance(lat, (int, float)) or isinstance(lat, bool):
            raise ValueError("vertex lat must be a number")
        if not isinstance(lng, (int, float)) or isinstance(lng, bool):
            raise ValueError("vertex lng must be a number")
        pairs.append((float(lat), float(lng)))
    return pairs


def validate_polygon(polygon) -> List[Tuple[float, float]]:
    """Return (lat,lng) pairs or raise ValueError on any structural issue.

    Caller is responsible for translating ValueError to ERR_INVALID_POLYGON.
    """
    if not isinstance(polygon, list):
        raise ValueError("polygon must be an array of vertices")
    if len(polygon) < 3 or len(polygon) > 32:
        raise ValueError("polygon must have between 3 and 32 vertices")
    pairs = _as_pairs(polygon)
    # Reject duplicate vertices (exact match).
    if len(set(pairs)) != len(pairs):
        raise ValueError("polygon must not contain duplicate vertices")
    if _polygon_self_intersects(pairs):
        raise ValueError("polygon edges must not self-intersect")
    return pairs


# ---------------------------------------------------------------------------
# Self-intersection check
# ---------------------------------------------------------------------------
def _segments_intersect(p1, p2, p3, p4) -> bool:
    """Return True iff (p1,p2) and (p3,p4) intersect at a proper interior point."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    # Adjacent segments share a vertex by construction; do not count that as
    # self-intersection.
    if p1 == p3 or p1 == p4 or p2 == p3 or p2 == p4:
        return False
    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)


def _polygon_self_intersects(pairs: List[Tuple[float, float]]) -> bool:
    n = len(pairs)
    edges = [(pairs[i], pairs[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            # Skip adjacent edges (and the wrap-around adjacency).
            if abs(i - j) <= 1 or (i == 0 and j == n - 1):
                continue
            a, b = edges[i]
            c, d = edges[j]
            if _segments_intersect(a, b, c, d):
                return True
    return False


# ---------------------------------------------------------------------------
# Point-in-polygon (ray casting). Vertices are (lat, lng).
# ---------------------------------------------------------------------------
def point_in_polygon(lat: float, lng: float, polygon_vertices: List[dict]) -> bool:
    """Return True iff (lat,lng) lies inside the polygon (boundary counts)."""
    pairs = _as_pairs(polygon_vertices)
    n = len(pairs)
    inside = False
    j = n - 1
    for i in range(n):
        lat_i, lng_i = pairs[i]
        lat_j, lng_j = pairs[j]
        # Boundary detection: treat exact vertex / collinear-edge as inside.
        if (lat_i == lat and lng_i == lng):
            return True
        if ((lng_i > lng) != (lng_j > lng)):
            # Compute intersection latitude of the edge with horizontal ray.
            denom = (lng_j - lng_i) if (lng_j - lng_i) != 0 else 1e-18
            x_intersect = (lat_j - lat_i) * (lng - lng_i) / denom + lat_i
            if lat < x_intersect:
                inside = not inside
        j = i
    return inside
