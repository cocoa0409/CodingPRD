"""Charge-session scheduling gates: referential, temporal, fiscal, concurrency.

Difficulty (queue A): temporal-vs-fiscal precedence, capacity boundary, charger
buffered half-open conflict, vehicle closed-interval conflict.
Corner (queue B): connector/power referential errors, capacity over-by-one,
session-create OCC stale version.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    fm_headers, op_headers,
)
import test_helpers.factories as fac
import test_helpers.fixtures as fx


def _schedule(api, depot_id, charger_id, vehicle_id, version, **ov):
    return api.create_session(
        fac.create_session_payload(depot_id, charger_id, vehicle_id, version, **ov), op_headers()
    )


# ---------------------------------------------------------------------------
# Difficulty: temporal outranks fiscal
# ---------------------------------------------------------------------------

def _temporal_fiscal_setup(api):
    """Depot max_load 200; existing session E on C1 [10:00,12:00) power 150.
    A new same-charger request [10:30,11:30) power 100 both overlaps E AND would
    push reserved to 250 (>200)."""
    depot = fx.new_depot(api, max_load_kw=200, contracted_capacity_kw=200)
    c1 = fx.new_charger(api, depot["id"], name="C1", max_power_kw=150)
    va = fx.new_vehicle(api, depot["id"], vin="VA", current_soc_pct=20)
    vb = fx.new_vehicle(api, depot["id"], vin="VB", current_soc_pct=20)
    fx.schedule_session(api, depot["id"], c1["id"], va["id"], fx.depot_version(api, depot["id"]),
                        scheduled_start="2026-05-10T10:00:00Z", scheduled_end="2026-05-10T12:00:00Z",
                        target_soc_pct=50, power_kw=150)
    return depot, c1, vb


def test_schedule_temporal_conflict_beats_fiscal_capacity(api):
    """PRD §3.3: "The **fiscal** capacity gate runs only after the temporal
    checks pass: the depot's current `reserved_load_kw` plus the new session's
    `power_kw` must be no greater than the depot's `max_load_kw`, or the request
    is rejected with `ERR_DEPOT_CAPACITY_EXCEEDED` (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/schedule_temporal_beats_fiscal
    """
    depot, c1, vb = _temporal_fiscal_setup(api)
    resp = _schedule(api, depot["id"], c1["id"], vb["id"], fx.depot_version(api, depot["id"]),
                     scheduled_start="2026-05-10T10:30:00Z", scheduled_end="2026-05-10T11:30:00Z",
                     target_soc_pct=50, power_kw=100)
    validate_error(resp, ApiErrorId.ERR_CHARGER_TIME_CONFLICT.value)


def test_schedule_temporal_conflict_leaves_reserved_load_unchanged(api):
    """PRD §2.8: "at any moment `reserved_load_kw` equals the summed `power_kw`
    of the depot's `SCHEDULED` and `ACTIVE` sessions."

    Design: Difficulty/priority_pair_validation_conflict/schedule_temporal_beats_fiscal
    """
    depot, c1, vb = _temporal_fiscal_setup(api)
    _schedule(api, depot["id"], c1["id"], vb["id"], fx.depot_version(api, depot["id"]),
              scheduled_start="2026-05-10T10:30:00Z", scheduled_end="2026-05-10T11:30:00Z",
              target_soc_pct=50, power_kw=100)
    after = fx.get_depot(api, depot["id"])
    assert after["reserved_load_kw"] == 150, f"rejected session must not reserve; got {after['reserved_load_kw']}"


# ---------------------------------------------------------------------------
# Difficulty: capacity at the inclusive max_load boundary
# ---------------------------------------------------------------------------

def test_schedule_capacity_exactly_at_max_load_succeeds(api):
    """PRD §3.3: "the depot's current `reserved_load_kw` plus the new session's
    `power_kw` must be no greater than the depot's `max_load_kw`, or the request
    is rejected with `ERR_DEPOT_CAPACITY_EXCEEDED` (HTTP 409); the boundary is
    inclusive, so reserving exactly up to the limit is allowed."

    Design: Difficulty/boundary_precision_check/schedule_capacity_at_max_load_boundary
    """
    depot = fx.new_depot(api, max_load_kw=500, contracted_capacity_kw=500)
    ca = fx.new_charger(api, depot["id"], name="CA", max_power_kw=500)
    cb = fx.new_charger(api, depot["id"], name="CB", max_power_kw=500)
    va = fx.new_vehicle(api, depot["id"], vin="VA", current_soc_pct=20)
    vb = fx.new_vehicle(api, depot["id"], vin="VB", current_soc_pct=20)
    fx.schedule_session(api, depot["id"], ca["id"], va["id"], fx.depot_version(api, depot["id"]),
                        scheduled_start="2026-05-10T10:00:00Z", scheduled_end="2026-05-10T12:00:00Z",
                        target_soc_pct=50, power_kw=400)
    resp = _schedule(api, depot["id"], cb["id"], vb["id"], fx.depot_version(api, depot["id"]),
                     scheduled_start="2026-05-10T10:00:00Z", scheduled_end="2026-05-10T12:00:00Z",
                     target_soc_pct=50, power_kw=100)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
    assert fx.get_depot(api, depot["id"])["reserved_load_kw"] == 500


def test_schedule_capacity_boundary_different_split_succeeds(api):
    """PRD §3.3: "the depot's current `reserved_load_kw` plus the new session's
    `power_kw` must be no greater than the depot's `max_load_kw`, or the request
    is rejected with `ERR_DEPOT_CAPACITY_EXCEEDED` (HTTP 409); the boundary is
    inclusive, so reserving exactly up to the limit is allowed."

    Design: Difficulty/boundary_precision_check/schedule_capacity_at_max_load_boundary
    """
    depot = fx.new_depot(api, max_load_kw=500, contracted_capacity_kw=500)
    ca = fx.new_charger(api, depot["id"], name="CA", max_power_kw=500)
    cb = fx.new_charger(api, depot["id"], name="CB", max_power_kw=500)
    va = fx.new_vehicle(api, depot["id"], vin="VA", current_soc_pct=20)
    vb = fx.new_vehicle(api, depot["id"], vin="VB", current_soc_pct=20)
    fx.schedule_session(api, depot["id"], ca["id"], va["id"], fx.depot_version(api, depot["id"]),
                        scheduled_start="2026-05-10T10:00:00Z", scheduled_end="2026-05-10T12:00:00Z",
                        target_soc_pct=50, power_kw=300)
    resp = _schedule(api, depot["id"], cb["id"], vb["id"], fx.depot_version(api, depot["id"]),
                     scheduled_start="2026-05-10T10:00:00Z", scheduled_end="2026-05-10T12:00:00Z",
                     target_soc_pct=50, power_kw=200)
    assert validate_success(resp, 201)["status"] == "SCHEDULED"
    assert fx.get_depot(api, depot["id"])["reserved_load_kw"] == 500


# ---------------------------------------------------------------------------
# Difficulty: charger buffered half-open conflict
# ---------------------------------------------------------------------------

def _charger_buffer_setup(api):
    depot = fx.new_depot(api)
    c1 = fx.new_charger(api, depot["id"], name="C1", max_power_kw=150)
    va = fx.new_vehicle(api, depot["id"], vin="VA", current_soc_pct=20)
    vb = fx.new_vehicle(api, depot["id"], vin="VB", current_soc_pct=20)
    fx.schedule_session(api, depot["id"], c1["id"], va["id"], fx.depot_version(api, depot["id"]),
                        scheduled_start="2026-05-10T10:00:00Z", scheduled_end="2026-05-10T11:00:00Z",
                        target_soc_pct=50, power_kw=50)
    return depot, c1, vb


def test_schedule_charger_gap_below_buffer_conflicts(api):
    """PRD §3.3: "the request is rejected with `ERR_CHARGER_TIME_CONFLICT` if
    that window overlaps any existing session's window expanded by the buffer on
    both sides — that is, the existing window from 30 minutes before its
    `scheduled_start` up to 30 minutes after its `scheduled_end`."

    Design: Difficulty/resource_temporal_overlap/charger_buffered_halfopen_conflict
    """
    depot, c1, vb = _charger_buffer_setup(api)
    resp = _schedule(api, depot["id"], c1["id"], vb["id"], fx.depot_version(api, depot["id"]),
                     scheduled_start="2026-05-10T11:15:00Z", scheduled_end="2026-05-10T12:00:00Z",
                     target_soc_pct=50, power_kw=50)
    validate_error(resp, ApiErrorId.ERR_CHARGER_TIME_CONFLICT.value)


def test_schedule_charger_gap_exactly_buffer_allowed(api):
    """PRD §3.3: "Two windows separated by a gap of exactly 30 minutes do not
    conflict, because the buffer gap is allowed to be met exactly."

    Design: Difficulty/resource_temporal_overlap/charger_buffered_halfopen_conflict
    """
    depot, c1, vb = _charger_buffer_setup(api)
    resp = _schedule(api, depot["id"], c1["id"], vb["id"], fx.depot_version(api, depot["id"]),
                     scheduled_start="2026-05-10T11:30:00Z", scheduled_end="2026-05-10T12:00:00Z",
                     target_soc_pct=50, power_kw=50)
    assert validate_success(resp, 201)["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: vehicle closed-interval conflict
# ---------------------------------------------------------------------------

def _vehicle_closed_setup(api):
    depot = fx.new_depot(api)
    ca = fx.new_charger(api, depot["id"], name="CA", max_power_kw=150)
    cb = fx.new_charger(api, depot["id"], name="CB", max_power_kw=150)
    va = fx.new_vehicle(api, depot["id"], vin="VA", current_soc_pct=20)
    fx.schedule_session(api, depot["id"], ca["id"], va["id"], fx.depot_version(api, depot["id"]),
                        scheduled_start="2026-05-10T10:00:00Z", scheduled_end="2026-05-10T11:00:00Z",
                        target_soc_pct=50, power_kw=50)
    return depot, cb, va


def test_schedule_vehicle_touching_boundary_conflicts(api):
    """PRD §3.3: "the request is rejected with `ERR_VEHICLE_TIME_CONFLICT` if the
    new session's `scheduled_start` is at or before an existing session's
    `scheduled_end` and that existing session's `scheduled_start` is at or before
    the new session's `scheduled_end`. Because the vehicle intervals are closed,
    two windows that merely touch at a shared boundary instant do collide".

    Design: Difficulty/resource_temporal_overlap/vehicle_closed_interval_conflict
    """
    depot, cb, va = _vehicle_closed_setup(api)
    resp = _schedule(api, depot["id"], cb["id"], va["id"], fx.depot_version(api, depot["id"]),
                     scheduled_start="2026-05-10T11:00:00Z", scheduled_end="2026-05-10T12:00:00Z",
                     target_soc_pct=50, power_kw=50)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_TIME_CONFLICT.value)


def test_schedule_vehicle_non_touching_gap_allowed(api):
    """PRD §3.3: "the request is rejected with `ERR_VEHICLE_TIME_CONFLICT` if the
    new session's `scheduled_start` is at or before an existing session's
    `scheduled_end` and that existing session's `scheduled_start` is at or before
    the new session's `scheduled_end`."

    Design: Difficulty/resource_temporal_overlap/vehicle_closed_interval_conflict
    """
    depot, cb, va = _vehicle_closed_setup(api)
    resp = _schedule(api, depot["id"], cb["id"], va["id"], fx.depot_version(api, depot["id"]),
                     scheduled_start="2026-05-10T11:01:00Z", scheduled_end="2026-05-10T12:00:00Z",
                     target_soc_pct=50, power_kw=50)
    assert validate_success(resp, 201)["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner: referential + fiscal + OCC single-rule violations
# ---------------------------------------------------------------------------

def test_schedule_connector_mismatch_returns_incompatible(api):
    """PRD §3.3: "the charger's `connector_type` must equal the vehicle's
    `connector_type`, or the request is rejected with
    `ERR_CONNECTOR_INCOMPATIBLE`".

    Design: Corner/validations/schedule_connector_mismatch_returns_incompatible
    """
    depot = fx.new_depot(api)
    charger = fx.new_charger(api, depot["id"], connector_type="CCS", max_power_kw=150)
    vehicle = fx.new_vehicle(api, depot["id"], connector_type="CHADEMO", current_soc_pct=40)
    resp = _schedule(api, depot["id"], charger["id"], vehicle["id"], fx.depot_version(api, depot["id"]),
                     target_soc_pct=80, power_kw=100)
    validate_error(resp, ApiErrorId.ERR_CONNECTOR_INCOMPATIBLE.value)


def test_schedule_power_exceeds_charger_returns_error(api):
    """PRD §3.3: "the requested `power_kw` must be no greater than the charger's
    `max_power_kw`, or the request is rejected with `ERR_POWER_EXCEEDS_CHARGER`."

    Design: Corner/validations/schedule_power_exceeds_charger_returns_error
    """
    depot = fx.new_depot(api, max_load_kw=1000)
    charger = fx.new_charger(api, depot["id"], connector_type="CCS", max_power_kw=150)
    vehicle = fx.new_vehicle(api, depot["id"], connector_type="CCS", current_soc_pct=40)
    resp = _schedule(api, depot["id"], charger["id"], vehicle["id"], fx.depot_version(api, depot["id"]),
                     target_soc_pct=80, power_kw=200)
    validate_error(resp, ApiErrorId.ERR_POWER_EXCEEDS_CHARGER.value)


def test_schedule_capacity_over_by_one_returns_exceeded(api):
    """PRD §3.3: "the depot's current `reserved_load_kw` plus the new session's
    `power_kw` must be no greater than the depot's `max_load_kw`, or the request
    is rejected with `ERR_DEPOT_CAPACITY_EXCEEDED` (HTTP 409)".

    Design: Corner/validations/schedule_capacity_over_by_one_returns_exceeded
    """
    depot = fx.new_depot(api, max_load_kw=500, contracted_capacity_kw=500)
    ca = fx.new_charger(api, depot["id"], name="CA", max_power_kw=500)
    cb = fx.new_charger(api, depot["id"], name="CB", max_power_kw=500)
    va = fx.new_vehicle(api, depot["id"], vin="VA", current_soc_pct=20)
    vb = fx.new_vehicle(api, depot["id"], vin="VB", current_soc_pct=20)
    fx.schedule_session(api, depot["id"], ca["id"], va["id"], fx.depot_version(api, depot["id"]),
                        scheduled_start="2026-05-10T10:00:00Z", scheduled_end="2026-05-10T12:00:00Z",
                        target_soc_pct=50, power_kw=400)
    resp = _schedule(api, depot["id"], cb["id"], vb["id"], fx.depot_version(api, depot["id"]),
                     scheduled_start="2026-05-10T10:00:00Z", scheduled_end="2026-05-10T12:00:00Z",
                     target_soc_pct=50, power_kw=101)
    validate_error(resp, ApiErrorId.ERR_DEPOT_CAPACITY_EXCEEDED.value)


def test_schedule_stale_depot_version_returns_stale(api):
    """PRD §2.9: "If the supplied `expected_depot_version` does not match the
    depot's current `version`, the write is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/session_create_stale_depot_version_returns_stale
    """
    depot = fx.new_depot(api, max_load_kw=1000)
    stale_version = depot["version"]  # version 1, captured before any session
    ca = fx.new_charger(api, depot["id"], name="CA", max_power_kw=150)
    cb = fx.new_charger(api, depot["id"], name="CB", max_power_kw=150)
    va = fx.new_vehicle(api, depot["id"], vin="VA", current_soc_pct=20)
    vb = fx.new_vehicle(api, depot["id"], vin="VB", current_soc_pct=20)
    # Session A advances Depot.version to 2.
    fx.schedule_session(api, depot["id"], ca["id"], va["id"], stale_version,
                        scheduled_start="2026-05-10T10:00:00Z", scheduled_end="2026-05-10T11:00:00Z",
                        target_soc_pct=50, power_kw=50)
    # Session B still carries the stale version 1.
    resp = _schedule(api, depot["id"], cb["id"], vb["id"], stale_version,
                     scheduled_start="2026-05-10T12:00:00Z", scheduled_end="2026-05-10T13:00:00Z",
                     target_soc_pct=50, power_kw=50)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
