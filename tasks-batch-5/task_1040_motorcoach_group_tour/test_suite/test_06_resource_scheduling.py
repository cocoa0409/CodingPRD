"""Resource assignment: overlap semantics, DOT boundary, and OCC on departure version."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_tour_product, create_coach, create_driver, create_guide,
    create_departure, get_departure, current_version,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


# ---------------------------------------------------------------------------
# Coach overlap: closed interval + 1-day turnaround buffer
# ---------------------------------------------------------------------------

def _coach_overlap_setup(api):
    """Coach assigned to Dep1 [08-01,08-05]; Dep2 [08-06,08-08] created. Returns (dep2, coach)."""
    tp = create_tour_product(duration_days=5)
    coach = create_coach(code="C10", seat_capacity=10)
    dep1 = create_departure(tp["id"], name="Ovl Dep1", start_date="2026-08-01",
                            end_date="2026-08-05", itinerary_days=f.itinerary(6, service_date="2026-08-01"))
    fx.assign_resource(dep1["id"], "COACH", coach["id"])
    dep2 = create_departure(tp["id"], name="Ovl Dep2", start_date="2026-08-06",
                            end_date="2026-08-08", itinerary_days=f.itinerary(6, service_date="2026-08-06"))
    return dep2, coach


def test_coach_overlap_within_turnaround_buffer_rejected(api, ops_headers):
    """PRD §2.10: "if one departure's occupied window ends on day D, another departure
    holding the same coach may not begin until day D+2 or later; a start on D+1 (only one
    day's gap) still conflicts. If the padded windows overlap, the assignment is rejected
    with ERR_COACH_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/coach_overlap_closed_interval_with_turnaround_buffer
    """
    dep2, coach = _coach_overlap_setup(api)
    version = current_version(dep2["id"])
    resp = api.assign_departure(dep2["id"], {
        "resource_kind": "COACH", "coach_id": coach["id"],
        "expected_departure_version": version,
    }, ops_headers)
    validate_error(resp, ApiErrorId.ERR_COACH_OVERLAP.value)


def test_coach_overlap_rejection_leaves_dep_coach_unset(api, ops_headers):
    """PRD §2.10: "If the padded windows overlap, the assignment is rejected with
    ERR_COACH_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/coach_overlap_closed_interval_with_turnaround_buffer
    """
    dep2, coach = _coach_overlap_setup(api)
    version = current_version(dep2["id"])
    api.assign_departure(dep2["id"], {
        "resource_kind": "COACH", "coach_id": coach["id"],
        "expected_departure_version": version,
    }, ops_headers)
    refreshed = get_departure(dep2["id"])
    assert refreshed["coach_id"] is None, \
        f"rejected coach assign must leave coach_id null, got {refreshed['coach_id']}"


# ---------------------------------------------------------------------------
# Guide overlap: half-open [start, end) — exact adjacency is allowed
# ---------------------------------------------------------------------------

def _guide_adjacency_setup(api):
    """Guide assigned to Dep1 [08-01,08-05]; Dep2 [08-05,08-07] created. Returns (dep2, guide)."""
    tp = create_tour_product(duration_days=5)
    guide = create_guide(name="Grace")
    dep1 = create_departure(tp["id"], name="Ovl2 Dep1", start_date="2026-08-01",
                            end_date="2026-08-05", itinerary_days=f.itinerary(6, service_date="2026-08-01"))
    fx.assign_resource(dep1["id"], "GUIDE", guide["id"])
    dep2 = create_departure(tp["id"], name="Ovl2 Dep2", start_date="2026-08-05",
                            end_date="2026-08-07", itinerary_days=f.itinerary(6, service_date="2026-08-05"))
    return dep2, guide


def test_guide_end_to_start_adjacency_allowed(api, ops_headers):
    """PRD §2.10: "For a guide, the overlap test is half-open: a guide's occupancy runs
    from the start_date inclusive up to but not including the end_date. Two departures
    whose spans meet exactly end-to-start do not conflict for a guide."

    Design: Difficulty/resource_temporal_overlap/guide_overlap_half_open_adjacency_allowed
    """
    dep2, guide = _guide_adjacency_setup(api)
    updated = fx.assign_resource(dep2["id"], "GUIDE", guide["id"])
    assert updated["guide_id"] == guide["id"], \
        f"end-to-start adjacency should assign, got guide_id {updated['guide_id']}"


# ---------------------------------------------------------------------------
# DOT boundary: exactly 10.0 hours is allowed; 11 is rejected
# ---------------------------------------------------------------------------

def test_dot_hours_exactly_ten_allowed(api, ops_headers):
    """PRD §2.10: "no single itinerary day may schedule more than ten planned driving hours.
    If any itinerary day's planned_drive_hours exceeds ten, the assignment is rejected with
    ERR_DOT_HOURS_EXCEEDED."

    Design: Difficulty/boundary_precision_check/dot_hours_boundary_exactly_10_allowed
    """
    tp = create_tour_product(duration_days=2)
    driver = create_driver(name="Del", license_no="CDL10")
    dep = create_departure(tp["id"], start_date="2026-10-20", end_date="2026-10-21",
                           itinerary_days=f.itinerary(10, service_date="2026-10-20"))
    fx.publish_departure(dep["id"])
    updated = fx.assign_resource(dep["id"], "DRIVER", driver["id"])
    assert updated["driver_id"] == driver["id"], \
        f"exactly-10h day must pass DOT check, got driver_id {updated['driver_id']}"
    refreshed = validate_success(api.get_driver(driver["id"], ops_headers))
    assert refreshed["status"] == "ASSIGNED"


def test_dot_hours_above_ten_rejected(api, ops_headers):
    """PRD §2.10: "no single itinerary day may schedule more than ten planned driving hours.
    If any itinerary day's planned_drive_hours exceeds ten, the assignment is rejected with
    ERR_DOT_HOURS_EXCEEDED."

    Design: Difficulty/boundary_precision_check/dot_hours_boundary_exactly_10_allowed
    """
    tp = create_tour_product(duration_days=2)
    driver = create_driver(name="Del", license_no="CDL11")
    dep = create_departure(tp["id"], start_date="2026-10-20", end_date="2026-10-21",
                           itinerary_days=f.itinerary(11, service_date="2026-10-20"))
    fx.publish_departure(dep["id"])
    version = current_version(dep["id"])
    resp = api.assign_departure(dep["id"], {
        "resource_kind": "DRIVER", "driver_id": driver["id"],
        "expected_departure_version": version,
    }, ops_headers)
    validate_error(resp, ApiErrorId.ERR_DOT_HOURS_EXCEEDED.value)


# ---------------------------------------------------------------------------
# OCC on departure version (corner)
# ---------------------------------------------------------------------------

def test_assign_with_stale_departure_version_rejected(api, ops_headers):
    """PRD §2.6: "If that value does not match the departure's current version at the
    moment the request is processed, the assignment is rejected with
    ERR_STALE_DEPARTURE_VERSION and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/corner_assign_stale_departure_version_returns_412
    """
    tp = create_tour_product(duration_days=2)
    coach = create_coach(code="OccC", seat_capacity=10)
    driver = create_driver(name="OccDrv", license_no="CDLO")
    dep = create_departure(tp["id"], start_date="2026-08-01", end_date="2026-08-02",
                           itinerary_days=f.itinerary(6, service_date="2026-08-01"))
    dv0 = dep["version"]
    # First assign advances the departure version.
    fx.assign_resource(dep["id"], "COACH", coach["id"])
    # Second assign carrying the pre-assign (now stale) version is rejected.
    resp = api.assign_departure(dep["id"], {
        "resource_kind": "DRIVER", "driver_id": driver["id"],
        "expected_departure_version": dv0,
    }, ops_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_DEPARTURE_VERSION.value)


def test_driver_overlap_actual_conflict_rejected(api, ops_headers):
    """PRD §2.10: "a driver may not be assigned if any other non-CANCELLED departure that
    holds the same driver has dates that overlap this departure's date span, treating both
    the first and last service dates as inclusive; a conflict yields ERR_DRIVER_OVERLAP."

    Design: Corner/cross_cutting_complexity_layers/corner_driver_overlap_on_assign_returns_409
    """
    tp = create_tour_product(duration_days=5)
    driver = create_driver(name="DoDrv", license_no="CDLD")
    dep1 = create_departure(tp["id"], name="Do Dep1", start_date="2026-08-01",
                            end_date="2026-08-05", itinerary_days=f.itinerary(6, service_date="2026-08-01"))
    fx.assign_resource(dep1["id"], "DRIVER", driver["id"])
    dep2 = create_departure(tp["id"], name="Do Dep2", start_date="2026-08-03",
                            end_date="2026-08-06", itinerary_days=f.itinerary(6, service_date="2026-08-03"))
    version = current_version(dep2["id"])
    resp = api.assign_departure(dep2["id"], {
        "resource_kind": "DRIVER", "driver_id": driver["id"],
        "expected_departure_version": version,
    }, ops_headers)
    validate_error(resp, ApiErrorId.ERR_DRIVER_OVERLAP.value)


def test_guide_half_open_actual_overlap_rejected(api, ops_headers):
    """PRD §2.10: "Any genuine half-open overlap with another non-CANCELLED departure
    holding the same guide is rejected with ERR_GUIDE_OVERLAP."

    Design: Corner/cross_cutting_complexity_layers/corner_guide_overlap_actual_conflict_returns_409
    """
    tp = create_tour_product(duration_days=5)
    guide = create_guide(name="GoGid")
    dep1 = create_departure(tp["id"], name="Go Dep1", start_date="2026-08-01",
                            end_date="2026-08-05", itinerary_days=f.itinerary(6, service_date="2026-08-01"))
    fx.assign_resource(dep1["id"], "GUIDE", guide["id"])
    # Dep2 starts 08-04 < 08-05, a genuine half-open overlap.
    dep2 = create_departure(tp["id"], name="Go Dep2", start_date="2026-08-04",
                            end_date="2026-08-07", itinerary_days=f.itinerary(6, service_date="2026-08-04"))
    version = current_version(dep2["id"])
    resp = api.assign_departure(dep2["id"], {
        "resource_kind": "GUIDE", "guide_id": guide["id"],
        "expected_departure_version": version,
    }, ops_headers)
    validate_error(resp, ApiErrorId.ERR_GUIDE_OVERLAP.value)
