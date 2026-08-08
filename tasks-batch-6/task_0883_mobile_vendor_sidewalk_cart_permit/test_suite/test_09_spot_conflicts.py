"""Direct spot-assignment conflict rules: spatial spacing boundary, half-open time
overlap, zone capacity, and zone-version OCC (Difficulty: boundary_precision_check,
resource_temporal_overlap; Corner: errors, cross_cutting)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS,
    create_spot_assignment_payload,
)
from test_helpers import fixtures as fx

PO = TEST_USERS["permit_officer_headers"]


def _assign(api, permit_id, spot_id, start, end, version):
    return api.create_spot_assignment(
        permit_id, create_spot_assignment_payload(spot_id, start, end, version), PO)


# --------------------------------------------------------------------------- #
# boundary_precision_check / spacing_boundary_equal_allowed_below_rejected
# --------------------------------------------------------------------------- #
def test_spacing_equal_to_buffer_allowed(api):
    """PRD §3.5: "a spacing violation across the zone: the request is rejected with
    ERR_SPACING_VIOLATION if any active assignment in the same zone occupies a
    position whose distance from the requested spot — the absolute difference of their
    position_feet — is strictly less than the zone's spacing_min_feet ... a distance
    exactly equal to the buffer is permitted."

    Design: Difficulty/boundary_precision_check/spacing_boundary_equal_allowed_below_rejected
    """
    ctx = fx.setup_issued_permit(spot_positions=[100, 120], spacing_min_feet=20, capacity_slots=5)
    permit, zone = ctx["permit"], ctx["zone"]
    s100, s120 = ctx["spots"]
    get_success_data(_assign(api, permit["id"], s100["id"],
                             "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z", zone["version"]))
    # distance |120-100| == 20 == spacing_min_feet -> permitted.
    res = _assign(api, permit["id"], s120["id"],
                  "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z", fx.zone_version(zone["id"]))
    created = validate_success(res, 201)
    assert created["status"] == "ACTIVE"


def test_spacing_below_buffer_rejected(api):
    """PRD §3.5: "the request is rejected with ERR_SPACING_VIOLATION if any active
    assignment in the same zone occupies a position whose distance from the requested
    spot — the absolute difference of their position_feet — is strictly less than the
    zone's spacing_min_feet"

    Design: Difficulty/boundary_precision_check/spacing_boundary_equal_allowed_below_rejected
    """
    ctx = fx.setup_issued_permit(spot_positions=[100, 119], spacing_min_feet=20, capacity_slots=5)
    permit, zone = ctx["permit"], ctx["zone"]
    s100, s119 = ctx["spots"]
    get_success_data(_assign(api, permit["id"], s100["id"],
                             "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z", zone["version"]))
    # distance |119-100| == 19 < 20 -> rejected.
    res = _assign(api, permit["id"], s119["id"],
                  "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z", fx.zone_version(zone["id"]))
    validate_error(res, "ERR_SPACING_VIOLATION", expected_status=409)


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / spot_time_overlap_half_open
# --------------------------------------------------------------------------- #
def test_adjacent_time_window_touching_boundary_allowed(api):
    """PRD §3.5: "two half-open windows overlap when the new start_at is before the
    existing end_at and the existing start_at is before the new end_at; two windows
    that merely touch at a boundary do not conflict."

    Design: Difficulty/resource_temporal_overlap/spot_time_overlap_half_open
    """
    ctx = fx.setup_issued_permit(spot_positions=[100], capacity_slots=5)
    permit, zone, spot = ctx["permit"], ctx["zone"], ctx["spots"][0]
    get_success_data(_assign(api, permit["id"], spot["id"],
                             "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z", zone["version"]))
    # new window starts exactly at the prior window's end_at -> allowed.
    res = _assign(api, permit["id"], spot["id"],
                  "2026-06-01T12:00:00Z", "2026-06-01T15:00:00Z", fx.zone_version(zone["id"]))
    created = validate_success(res, 201)
    assert created["status"] == "ACTIVE"


def test_overlapping_time_window_rejected(api):
    """PRD §3.5: "a time conflict on the same spot: the request is rejected with
    ERR_SPOT_TIME_CONFLICT if any active assignment on that same spot_id overlaps the
    requested window, where two half-open windows overlap when the new start_at is
    before the existing end_at and the existing start_at is before the new end_at"

    Design: Difficulty/resource_temporal_overlap/spot_time_overlap_half_open
    """
    ctx = fx.setup_issued_permit(spot_positions=[100], capacity_slots=5)
    permit, zone, spot = ctx["permit"], ctx["zone"], ctx["spots"][0]
    get_success_data(_assign(api, permit["id"], spot["id"],
                             "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z", zone["version"]))
    # [11:00,13:00) genuinely overlaps [09:00,12:00).
    res = _assign(api, permit["id"], spot["id"],
                  "2026-06-01T11:00:00Z", "2026-06-01T13:00:00Z", fx.zone_version(zone["id"]))
    validate_error(res, "ERR_SPOT_TIME_CONFLICT", expected_status=409)


# --------------------------------------------------------------------------- #
# Corner errors: zone_capacity_full_rejected
# --------------------------------------------------------------------------- #
def test_assignment_rejected_when_zone_at_capacity(api):
    """PRD §3.5: "zone availability: if the zone's available_slots is at or below zero
    the request is rejected with ERR_ZONE_CAPACITY_FULL"

    Design: Corner/errors/zone_capacity_full_rejected
    """
    ctx = fx.setup_issued_permit(spot_positions=[100, 400], capacity_slots=1, spacing_min_feet=20)
    permit, zone = ctx["permit"], ctx["zone"]
    s100, s400 = ctx["spots"]
    get_success_data(_assign(api, permit["id"], s100["id"],
                             "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z", zone["version"]))
    # zone capacity 1 now full; a second (spacing-clear, time-clear) assignment fails.
    res = _assign(api, permit["id"], s400["id"],
                  "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z", fx.zone_version(zone["id"]))
    validate_error(res, "ERR_ZONE_CAPACITY_FULL", expected_status=409)


# --------------------------------------------------------------------------- #
# Corner cross_cutting: occ_stale_zone_version_conflict
# --------------------------------------------------------------------------- #
def test_stale_zone_version_rejected(api):
    """PRD §2.8: "If expected_zone_version does not equal the zone's current version —
    because another assignment has legitimately consumed or freed a slot since the
    client last read the zone — the request is rejected with ERR_STALE_VERSION (HTTP
    412) and no assignment is created."

    Design: Corner/cross_cutting/occ_stale_zone_version_conflict
    """
    ctx = fx.setup_issued_permit(spot_positions=[100, 400], capacity_slots=5)
    permit, zone = ctx["permit"], ctx["zone"]
    s100, s400 = ctx["spots"]
    stale_version = zone["version"]  # observed before any assignment
    first = _assign(api, permit["id"], s100["id"],
                    "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z", stale_version)
    validate_success(first, 201)  # this advances Zone.version
    # second create still carrying the now-stale version.
    res = _assign(api, permit["id"], s400["id"],
                  "2026-06-01T09:00:00Z", "2026-06-01T17:00:00Z", stale_version)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
