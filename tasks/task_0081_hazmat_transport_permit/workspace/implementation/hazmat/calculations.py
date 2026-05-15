"""The four named calculations the scaffold's §1.3 declares and the PRD's
§2.11 and §3 narrate.

  1. `permit_validity_check(permit, world, mode)` — the five-leg boolean
     AND-chain over the permit's grounding-entity state, in either the
     snapshot mode (reading the on-disk `snapshot_*` fields) or the live
     mode (re-evaluating each leg against the current grounding-entity
     state). The pinned evaluation order is: company → drivers (sorted
     ascending by id) → vehicles (sorted ascending by id) → route →
     time-window. The function returns the tuple `(overall_bool,
     per_leg_dict)` where the `per_leg_dict` carries the five booleans
     in the keys `company_ok`, `drivers_ok`, `vehicles_ok`, `route_ok`,
     `time_ok`.

  2. `driver_penalty_point_rolling_total(driver_id, asof_dt, constants)`
     — the integer sum over the points-values of the non-UPHELD Penalty
     rows whose subject is the named driver and whose `observed_at` is
     in the open-on-the-left, closed-on-the-right rolling window
     `(asof_dt - PENALTY_WINDOW_DAYS, asof_dt]`. The threshold-check
     comparison against `THRESHOLD_DRIVER_SUSPENSION_POINTS` uses the
     inclusive-greater-than-or-equal predicate so the exact-threshold
     value is the just-suspended state.

  3. `annual_renewal_fee(now_dt, vehicle_count, valid_until_at_call_time,
     constants)` — the integer-cents fee output of the four-stage
     pinned-order formula: base plus per-vehicle surcharge, conditional
     late-add when the call lands in the inner late-grace window, the
     saturating cap, and the round-then-cap ordering for any future
     fractional-cent intermediate. The current integer-cents arithmetic
     does not exercise the rounding step in practice, but the order is
     pinned for forward compatibility per the Quality-Checklist's-
     "multi-step-rounding-order-must-be-pinned" item.

  4. `gps_violation_classification(gps_report_dict, route_polyline,
     constants)` — the per-GPS-sample classifier that returns the two
     boolean flags `speed_violated` and `off_route_violation` (and the
     computed `off_route_distance_m` float for the audit). The speed
     check is the strict-greater-than `speed_kph > MAX_HAZMAT_SPEED_KPH`;
     the off-route check is the strict-greater-than `off_route_distance_m
     > OFF_ROUTE_RADIUS_M` against the haversine-on-segments
     perpendicular distance using the WGS-84 mean Earth radius of
     6_371_000.0 meters from the `EARTH_RADIUS_M` constant.

The haversine helper computes the cross-track distance from a point to a
piecewise polyline, clamping each per-segment along-track parameter to
the inclusive `[0, 1]` range so the per-segment endpoint case is the
great-circle distance to the segment's endpoint rather than the
infinite-line's perpendicular foot. The minimum across all per-segment
distances is the polyline-distance. The standard millimeter-level
tolerance the test layer absorbs on the haversine floating-point
arithmetic is 1e-3 meters per the PRD §2.8's GPS-stream-contractual-
constants paragraph.

The PRD's prose uses the exact field names this module references —
`hazmat_endorsement_status`, `endorsement_valid_until`,
`current_rolling_points`, `latest_inspection_outcome`,
`latest_inspection_valid_until`, `qualification_status`, `approval_status`,
`lifecycle_status`, `valid_from`, `valid_until`, `authorized_driver_ids`,
`authorized_vehicle_ids`, the `snapshot_*` map and scalar fields — so a
fixture-side test's name-of-field matches the implementation-side's
field-name without coordination.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from .clock import current_now, parse_iso
from .config import Constants
from .store import find, table


# ---------------------------------------------------------------------------
# Calculation 1 — permit_validity_check
# ---------------------------------------------------------------------------


def permit_validity_check(
    permit: dict[str, Any],
    mode: str,
    constants: Constants,
    now_override: datetime | None = None,
) -> tuple[bool, dict[str, bool]]:
    """The five-leg boolean conjunction over the permit's grounding-entity
    state. The pinned evaluation order is the PRD §2.11's "company, then
    drivers in ascending-by-id order, then vehicles in ascending-by-id
    order, then route, then time-window" sequence so the snapshot-write
    is deterministic under concurrent grounding-entity writes.

    `mode` is the string `"snapshot"` (read the on-disk `snapshot_*` fields
    on the permit row directly) or `"live"` (cross-aggregate read of each
    grounding entity's current state at the moment of the call). The
    `now_override` argument is used by the sweep-and-the-verify-compliance
    paths to anchor the time-window check at a specific instant rather
    than the current simulated-clock value; the standard call passes None
    and the function reads `current_now()` itself.

    Returns the pair `(overall, per_leg)` where `overall` is the boolean
    AND of the five `per_leg` values, and `per_leg` is a dict with the
    keys `company_ok`, `drivers_ok`, `vehicles_ok`, `route_ok`, `time_ok`,
    matching the field-names the verify-compliance response's
    `live_per_leg` and the permit-read's `live_per_leg` and
    `snapshot_overall` companion fields use.
    """
    if mode not in ("snapshot", "live"):
        raise ValueError(f"mode must be 'snapshot' or 'live'; got {mode!r}")

    now = now_override if now_override is not None else current_now()

    if mode == "snapshot":
        # The strict-snapshot mode reads the on-disk `snapshot_*` fields
        # verbatim and does no cross-aggregate read. The snapshot is the
        # forensic-audit answer "what was the permit's validity verdict
        # at the last verify-compliance call?".
        company_ok = bool(permit.get("snapshot_company_qualified", False))
        driver_map: dict[str, bool] = permit.get("snapshot_driver_endorsements", {}) or {}
        # Sort the driver ids ascending so the conjunction's evaluation
        # order is deterministic. The conjunction's value is invariant
        # under ordering, but the per-leg-map's iteration order is
        # observable on the response's `snapshot_per_leg` field's
        # display side. We don't fold the per-driver map into the
        # `drivers_ok` scalar's intermediate booleans here; the test
        # layer reads the per-driver map directly from the permit row's
        # field.
        sorted_driver_ids = sorted(permit.get("authorized_driver_ids", []))
        drivers_ok = all(
            bool(driver_map.get(did, False)) for did in sorted_driver_ids
        )
        vehicle_map: dict[str, bool] = permit.get("snapshot_vehicle_inspections", {}) or {}
        sorted_vehicle_ids = sorted(permit.get("authorized_vehicle_ids", []))
        vehicles_ok = all(
            bool(vehicle_map.get(vid, False)) for vid in sorted_vehicle_ids
        )
        route_ok = bool(permit.get("snapshot_route_approved", False))
        time_ok = bool(permit.get("snapshot_within_window", False))
        overall = (
            company_ok and drivers_ok and vehicles_ok and route_ok and time_ok
        )
        return overall, {
            "company_ok": company_ok,
            "drivers_ok": drivers_ok,
            "vehicles_ok": vehicles_ok,
            "route_ok": route_ok,
            "time_ok": time_ok,
        }

    # The live mode: re-evaluate each leg against the current grounding-
    # entity state. The cross-aggregate reads walk the in-memory store
    # for the company row, each driver row in ascending-id order, each
    # vehicle row in ascending-id order, and the route row. The time-
    # window leg uses the half-open right-exclusive interval
    # `[valid_from, valid_until)` of the §2.9 conventions table.
    threshold = constants.threshold_driver_suspension_points

    # 1) Company leg.
    company = find("TransportCompany", permit.get("company_id"))
    company_ok = bool(
        company is not None
        and company.get("qualification_status") == "APPROVED"
    )

    # 2) Drivers leg — the conjunction over each authorized driver's
    # three sub-checks: endorsement is in force, endorsement covers the
    # permit's `valid_until` term, and the driver's rolling-points total
    # is strictly below the threshold. The per-driver booleans are
    # written into the response's `live_per_driver` map by the caller
    # (the verify-compliance handler) when the caller wants the per-
    # driver breakdown; this function returns the aggregated AND-over-
    # all-drivers as the `drivers_ok` flag.
    sorted_driver_ids = sorted(permit.get("authorized_driver_ids", []))
    valid_until_str = permit.get("valid_until")
    permit_valid_until = (
        parse_iso(valid_until_str) if valid_until_str else None
    )
    drivers_ok = True
    for did in sorted_driver_ids:
        d = find("Driver", did)
        if d is None:
            drivers_ok = False
            continue
        endorsement_in_force = d.get("hazmat_endorsement_status") == "VALID"
        endorsement_valid_until_str = d.get("endorsement_valid_until")
        if endorsement_valid_until_str is None or permit_valid_until is None:
            endorsement_covers_term = False
        else:
            endorsement_valid_until = parse_iso(endorsement_valid_until_str)
            endorsement_covers_term = (
                endorsement_valid_until >= permit_valid_until
            )
        points_below_threshold = (
            int(d.get("current_rolling_points", 0)) < threshold
        )
        leg = (
            endorsement_in_force
            and endorsement_covers_term
            and points_below_threshold
        )
        if not leg:
            drivers_ok = False

    # 3) Vehicles leg — the per-vehicle "latest inspection PASSED AND
    # its `valid_until` covers the permit's `valid_until`" conjunction.
    sorted_vehicle_ids = sorted(permit.get("authorized_vehicle_ids", []))
    vehicles_ok = True
    for vid in sorted_vehicle_ids:
        v = find("Vehicle", vid)
        if v is None:
            vehicles_ok = False
            continue
        outcome = v.get("latest_inspection_outcome")
        valid_until_v_str = v.get("latest_inspection_valid_until")
        if outcome != "PASSED":
            vehicles_ok = False
            continue
        if valid_until_v_str is None or permit_valid_until is None:
            vehicles_ok = False
            continue
        valid_until_v = parse_iso(valid_until_v_str)
        if valid_until_v < permit_valid_until:
            vehicles_ok = False

    # 4) Route leg.
    route = find("TransportRoute", permit.get("route_id"))
    route_ok = bool(
        route is not None and route.get("approval_status") == "APPROVED"
    )

    # 5) Time-window leg — the half-open right-exclusive interval
    # `[valid_from, valid_until)`. The §2.9 paragraph's "the moment
    # `now() == valid_until` is the expired moment, not the last-active
    # moment" rule is realized by the strict-less-than against the right
    # edge.
    valid_from_str = permit.get("valid_from")
    if (
        valid_from_str is None
        or valid_until_str is None
    ):
        time_ok = False
    else:
        valid_from = parse_iso(valid_from_str)
        valid_until = parse_iso(valid_until_str)
        time_ok = valid_from <= now < valid_until

    overall = company_ok and drivers_ok and vehicles_ok and route_ok and time_ok
    return overall, {
        "company_ok": company_ok,
        "drivers_ok": drivers_ok,
        "vehicles_ok": vehicles_ok,
        "route_ok": route_ok,
        "time_ok": time_ok,
    }


def compute_per_driver_snapshot_flag(
    driver_id: str, permit_valid_until: datetime, constants: Constants
) -> bool:
    """The boolean the per-driver entry in the permit's
    `snapshot_driver_endorsements` map carries: the conjunction "the
    driver's `hazmat_endorsement_status` is `VALID` AND the driver's
    `endorsement_valid_until` is at or after the permit's `valid_until`
    AND the driver's `current_rolling_points` is strictly below the
    threshold". This is the per-driver leg of the drivers-conjunction
    of `permit_validity_check`'s live mode, evaluated against a single
    driver-id, used by the verify-compliance and the issue handlers'
    snapshot-write side-effects.
    """
    d = find("Driver", driver_id)
    if d is None:
        return False
    if d.get("hazmat_endorsement_status") != "VALID":
        return False
    eu_str = d.get("endorsement_valid_until")
    if eu_str is None:
        return False
    eu = parse_iso(eu_str)
    if eu < permit_valid_until:
        return False
    points = int(d.get("current_rolling_points", 0))
    if points >= constants.threshold_driver_suspension_points:
        return False
    return True


def compute_per_vehicle_snapshot_flag(
    vehicle_id: str, permit_valid_until: datetime
) -> bool:
    """The boolean the per-vehicle entry in the permit's
    `snapshot_vehicle_inspections` map carries: "the vehicle's
    `latest_inspection_outcome` is `PASSED` AND
    `latest_inspection_valid_until` is at or after the permit's
    `valid_until`".
    """
    v = find("Vehicle", vehicle_id)
    if v is None:
        return False
    if v.get("latest_inspection_outcome") != "PASSED":
        return False
    vu_str = v.get("latest_inspection_valid_until")
    if vu_str is None:
        return False
    vu = parse_iso(vu_str)
    return vu >= permit_valid_until


# ---------------------------------------------------------------------------
# Calculation 2 — driver_penalty_point_rolling_total
# ---------------------------------------------------------------------------


def driver_penalty_point_rolling_total(
    driver_id: str,
    asof_dt: datetime,
    constants: Constants,
) -> int:
    """The integer rolling-total over the points-values of the non-UPHELD
    Penalty rows whose subject is the named driver and whose
    `observed_at` lies in the open-on-the-left, closed-on-the-right
    interval `(asof_dt - PENALTY_WINDOW_DAYS, asof_dt]`. The standard
    convention of the §2.9 conventions table.

    The function walks the entire Penalty table linearly, filtering on
    the `(subject_type == "DRIVER", subject_id == driver_id,
    void_status == "ACTIVE")` predicate triple and on the time-window
    membership. The integer sum of the matching rows' `points_value`
    field is the return.

    The threshold predicate against `THRESHOLD_DRIVER_SUSPENSION_POINTS`
    uses the inclusive-greater-than-or-equal — at the exact-threshold
    value the driver is in the suspended-bound state. The
    `crosses_threshold` helper below evaluates that predicate against
    the function's output and the constant.
    """
    window_lower_exclusive = asof_dt - timedelta(
        days=constants.penalty_window_days
    )

    total = 0
    for p in table("Penalty").values():
        if p.get("subject_type") != "DRIVER":
            continue
        if p.get("subject_id") != driver_id:
            continue
        if p.get("void_status") != "ACTIVE":
            # Upheld penalties don't count — the §2.11 conservation
            # invariant B's "the rolling total is the sum over the
            # non-UPHELD rows" pin.
            continue
        observed_at_str = p.get("observed_at")
        if observed_at_str is None:
            continue
        observed_at = parse_iso(observed_at_str)
        # Open on the left, closed on the right.
        if observed_at <= window_lower_exclusive:
            continue
        if observed_at > asof_dt:
            # Future-dated penalty, which the validation tier rejects at
            # insert time anyway; defensive filter.
            continue
        total += int(p.get("points_value", 0))
    return total


def driver_threshold_crossed(total: int, constants: Constants) -> bool:
    """The PRD §2.8's "at exactly the threshold the driver is in the
    suspended-bound state" inclusive-greater-than-or-equal predicate.
    """
    return total >= constants.threshold_driver_suspension_points


# ---------------------------------------------------------------------------
# Calculation 3 — annual_renewal_fee
# ---------------------------------------------------------------------------


def annual_renewal_fee(
    now_dt: datetime,
    vehicle_count: int,
    valid_until_at_call_time: datetime | None,
    constants: Constants,
) -> tuple[int, bool]:
    """The four-stage formula's output as the pair `(fee_cents, is_late)`.
    Stage 1 is the integer-cents subtotal `BASE + vehicle_count *
    PER_VEHICLE_SURCHARGE`. Stage 2 is the conditional add of
    `LATE_RENEWAL_PENALTY_CENTS` when the call's `now_dt` lies in the
    closed-left-and-open-right inner late-grace window
    `[valid_until - LATE_RENEWAL_GRACE_DAYS, valid_until)`; if
    `valid_until_at_call_time` is None (the issue-step's first-time call,
    where the term has not yet been pinned and the late-flag is
    definitionally false), the late-add is skipped. Stage 3 is the
    saturating cap at `MAX_RENEWAL_FEE_CENTS` via `min(subtotal, cap)`.
    Stage 4 is the rounding pin (no-op in the integer-cents-only
    arithmetic the current rules use).

    The boundary semantics of the late-grace inner window is the closed-
    left, open-right interval from the PRD §2.11's "the boundary at
    `now == valid_until - LATE_RENEWAL_GRACE_DAYS` is the first late
    moment (the late penalty fires at the exact boundary)" rule. The
    right edge at `now == valid_until` is the after-expiry case which
    the outer-renewal-window check at the validation tier has already
    rejected with `ERR_RENEWAL_AFTER_EXPIRY` 409 before the formula
    evaluates, so the right edge of the late-grace window is
    structurally unreachable in practice but is open-right in the
    formula's predicate for consistency.

    The boundary semantics is straightforward for the test layer's
    "the late surcharge fires at exactly the inner-window's left edge"
    assertion.
    """
    if vehicle_count < 1:
        # The caller's body-shape tier should have caught the empty-
        # vehicle-list case via the ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE
        # cardinality bound; defensive guard.
        raise ValueError(
            "vehicle_count must be at least 1 for the fee formula"
        )

    # Stage 1: base plus per-vehicle surcharge.
    subtotal_cents = (
        constants.base_renewal_fee_cents
        + vehicle_count * constants.per_vehicle_surcharge_cents
    )

    # Stage 2: conditional late-add. On the issue-step the
    # `valid_until_at_call_time` argument is None and the late-flag is
    # forced false.
    is_late = False
    if valid_until_at_call_time is not None:
        late_grace_lower_inclusive = valid_until_at_call_time - timedelta(
            days=constants.late_renewal_grace_days
        )
        # Closed-left at `late_grace_lower_inclusive`, open-right at
        # `valid_until_at_call_time`. The "the boundary at exactly the
        # lower edge fires the late surcharge" rule is realized by the
        # `>=` on the lower edge.
        if (
            now_dt >= late_grace_lower_inclusive
            and now_dt < valid_until_at_call_time
        ):
            is_late = True

    if is_late:
        subtotal_cents += constants.late_renewal_penalty_cents

    # Stage 3: the saturating cap. The cap-after-the-late-add ordering
    # is the §2.11's "round-then-cap" sub-clause of the rounding-order
    # pin. The "the late surcharge may be partially absorbed by the cap"
    # behaviour is the deliberate non-linear interaction the rule-2-mode-
    # a clause from the scaffold's complexity-profile prose names.
    fee_cents = min(subtotal_cents, constants.max_renewal_fee_cents)

    # Stage 4: rounding-no-op on the integer arithmetic. The §2.11's
    # closing paragraph names the rounding rule "round-half-up at the
    # multiplicative step before the cap" but the current integer-only
    # input set doesn't introduce a fractional cent. The output is the
    # integer fee in cents.

    return fee_cents, is_late


# ---------------------------------------------------------------------------
# Calculation 4 — gps_violation_classification
# ---------------------------------------------------------------------------


def haversine_distance_to_polyline(
    lat_deg: float,
    lon_deg: float,
    polyline: list[dict[str, float]],
    earth_radius_m: float,
) -> float:
    """The minimum great-circle (haversine-formula) perpendicular distance
    in meters from the point `(lat_deg, lon_deg)` (WGS-84 decimal degrees)
    to the polyline's piecewise great-circle segments. The polyline is
    the list of waypoint objects `{"lat": float, "lon": float}` in
    degrees. The Earth-radius constant is the input parameter (the
    canonical WGS-84 mean radius is 6,371,000.0 meters per the §2.8
    paragraph).

    The algorithm walks each consecutive pair of waypoints `(w_i,
    w_{i+1})` and computes the cross-track distance from the point to
    the great-circle through the two waypoints, clamped to the along-
    track range `[0, segment_length]` so the per-segment endpoint case
    is the great-circle distance to the segment's endpoint rather than
    the infinite-great-circle's signed perpendicular. The minimum
    across all segments is the polyline distance.

    The standard formula references are:
      - The haversine formula computes the great-circle angular distance
        between two points `(lat_1, lon_1)` and `(lat_2, lon_2)` on a
        sphere of radius `R`:
            a = sin^2(Δφ/2) + cos(φ1) cos(φ2) sin^2(Δλ/2)
            d = 2 R asin(sqrt(a))
        where φ is the latitude in radians, λ is the longitude in
        radians, Δφ = φ_2 - φ_1, Δλ = λ_2 - λ_1.
      - The cross-track-distance formula gives the perpendicular distance
        from a third point P to the great circle through two waypoints
        A and B:
            d_xt = R asin( sin(d_AP / R) sin(θ_AP - θ_AB) )
        where `d_AP` is the great-circle distance from A to P, `θ_AP`
        is the initial bearing from A to P, `θ_AB` is the initial
        bearing from A to B. The absolute value is the unsigned
        perpendicular distance.
      - The along-track-distance formula gives the signed projection of
        P onto the AB great circle, measured from A:
            d_at = R acos( cos(d_AP / R) / cos(d_xt / R) )
        with the sign matching the bearing difference.

    For the polyline-distance-to-the-segment-not-the-infinite-line case,
    we clamp the along-track to the inclusive `[0, d_AB]` range — if
    the foot of the perpendicular from P to the AB great circle lands
    before A or after B, the per-segment distance is the great-circle
    distance from P to the nearer endpoint. The minimum across all
    segments of the polyline is the function's return.

    Edge case: a zero-length segment (two consecutive waypoints with
    the same `(lat, lon)`) makes the formulas singular (the bearing
    from A to B is undefined). The handler is the standard "treat a
    zero-length segment as the single-point endpoint" rule: the per-
    segment distance is the great-circle distance from P to the
    coincident endpoint. The numerical guard `if d_AB < 1e-12` detects
    the zero-length case.
    """
    if not polyline:
        # An empty polyline is the degenerate case — return +infinity so
        # any radius-comparison comes out as "off-route" for the
        # well-defined fail-closed behaviour. The validation tier
        # rejects the empty-polyline body shape, so this case is not
        # hit on the canonical request path.
        return float("inf")

    lat_rad = math.radians(lat_deg)
    lon_rad = math.radians(lon_deg)

    min_distance_m = float("inf")

    def angular_distance(
        lat1_r: float, lon1_r: float, lat2_r: float, lon2_r: float
    ) -> float:
        """The angular distance (in radians on the unit sphere) between
        two points, computed via the haversine formula. The conversion
        to meters is the multiplication by the Earth radius.
        """
        dlat = lat2_r - lat1_r
        dlon = lon2_r - lon1_r
        a = (
            math.sin(dlat / 2.0) ** 2
            + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2.0) ** 2
        )
        # Clamp for the numerical-safety on the asin of a sqrt that may
        # marginally exceed 1.0 due to float-rounding.
        a = max(0.0, min(1.0, a))
        c = 2.0 * math.asin(math.sqrt(a))
        return c

    def bearing_rad(
        lat1_r: float, lon1_r: float, lat2_r: float, lon2_r: float
    ) -> float:
        """The initial bearing in radians (the great-circle's angle from
        true north at the starting point), normalized to the `(-π, π]`
        range. The formula is the standard `atan2(sin(Δλ) cos(φ2),
        cos(φ1) sin(φ2) - sin(φ1) cos(φ2) cos(Δλ))`.
        """
        dlon = lon2_r - lon1_r
        y = math.sin(dlon) * math.cos(lat2_r)
        x = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(
            lat2_r
        ) * math.cos(dlon)
        return math.atan2(y, x)

    # Walk the polyline's consecutive-pair segments.
    n = len(polyline)
    if n == 1:
        wp = polyline[0]
        a_lat_r = math.radians(float(wp["lat"]))
        a_lon_r = math.radians(float(wp["lon"]))
        d_ang = angular_distance(a_lat_r, a_lon_r, lat_rad, lon_rad)
        return d_ang * earth_radius_m

    for i in range(n - 1):
        a = polyline[i]
        b = polyline[i + 1]
        a_lat_r = math.radians(float(a["lat"]))
        a_lon_r = math.radians(float(a["lon"]))
        b_lat_r = math.radians(float(b["lat"]))
        b_lon_r = math.radians(float(b["lon"]))

        # The segment's length on the unit sphere.
        d_ab_ang = angular_distance(a_lat_r, a_lon_r, b_lat_r, b_lon_r)
        if d_ab_ang < 1e-12:
            # Zero-length segment — the per-segment distance is the
            # great-circle distance from P to the single-point endpoint.
            d_endpoint = angular_distance(
                a_lat_r, a_lon_r, lat_rad, lon_rad
            )
            cand = d_endpoint * earth_radius_m
            if cand < min_distance_m:
                min_distance_m = cand
            continue

        # The great-circle distance from A to P.
        d_ap_ang = angular_distance(a_lat_r, a_lon_r, lat_rad, lon_rad)
        if d_ap_ang < 1e-15:
            # P coincides with A — the per-segment distance is zero.
            return 0.0

        # The bearing difference between the AP great circle and the AB
        # great circle. The signed angular cross-track distance is
        # `asin(sin(d_ap) * sin(theta_ap - theta_ab))`, and the unsigned
        # cross-track distance in radians is its absolute value.
        theta_ap = bearing_rad(a_lat_r, a_lon_r, lat_rad, lon_rad)
        theta_ab = bearing_rad(a_lat_r, a_lon_r, b_lat_r, b_lon_r)
        delta_theta = theta_ap - theta_ab
        sin_dxt = math.sin(d_ap_ang) * math.sin(delta_theta)
        sin_dxt = max(-1.0, min(1.0, sin_dxt))
        d_xt_ang = math.asin(sin_dxt)
        d_xt_abs = abs(d_xt_ang)

        # The along-track distance: the signed great-circle distance from
        # A to the foot of the perpendicular from P. The formula is
        # `acos(cos(d_ap) / cos(d_xt))`, with the sign matching the
        # direction of the perpendicular's foot from A along the AB
        # great circle. We compute the signed along-track via the
        # signed great-circle position relative to A in the AB direction.
        cos_d_ap = math.cos(d_ap_ang)
        cos_d_xt = math.cos(d_xt_abs)
        if abs(cos_d_xt) < 1e-15:
            # Degenerate — the cross-track is a quarter-circle, which
            # only happens for antipodal-ish geometry that the test
            # layer doesn't exercise. Fall back to the endpoint-distance
            # heuristic.
            d_at_ang = d_ap_ang
            # The sign is from the bearing-difference's sign.
            if math.cos(delta_theta) < 0:
                d_at_ang = -d_at_ang
        else:
            ratio = cos_d_ap / cos_d_xt
            ratio = max(-1.0, min(1.0, ratio))
            d_at_ang_unsigned = math.acos(ratio)
            # Sign: positive if the foot lands in the same hemisphere as
            # B from A's perspective (the standard bearing-difference's
            # cosine sign).
            sign = 1.0 if math.cos(delta_theta) >= 0 else -1.0
            d_at_ang = sign * d_at_ang_unsigned

        # Clamp the along-track to the segment's range. If the foot is
        # before A or after B, the segment's nearest point is the
        # appropriate endpoint and the per-segment distance is the
        # great-circle distance from P to that endpoint.
        if d_at_ang < 0:
            per_segment_ang = d_ap_ang
        elif d_at_ang > d_ab_ang:
            d_bp_ang = angular_distance(
                b_lat_r, b_lon_r, lat_rad, lon_rad
            )
            per_segment_ang = d_bp_ang
        else:
            per_segment_ang = d_xt_abs

        per_segment_m = per_segment_ang * earth_radius_m
        if per_segment_m < min_distance_m:
            min_distance_m = per_segment_m

    return min_distance_m


def gps_violation_classification(
    gps_report: dict[str, Any],
    route_polyline: list[dict[str, float]],
    constants: Constants,
) -> dict[str, Any]:
    """The per-sample classifier returning the violation flags and the
    auto-Penalty points-values. The return dict's keys are
    `speed_violated` (bool), `off_route_violation` (bool),
    `off_route_distance_m` (float, the computed haversine-segment
    distance for the audit trail's storage on the GPSReport row's
    `off_route_distance_m` field), `speed_points_value` (the integer
    points-value for the speed-violation auto-Penalty, the constant
    `GPS_VIOLATION_SPEED_POINTS`, or zero on the no-speed-violation
    case), and `off_route_points_value` (the integer points-value for
    the off-route-violation auto-Penalty, the constant
    `GPS_VIOLATION_OFF_ROUTE_POINTS`, or zero on the no-off-route case).

    Both comparison predicates are strict-greater-than per the §2.8
    paragraph's "the boundary value is not a violation" pin. The boundary
    on the speed-limit at `speed_kph == MAX_HAZMAT_SPEED_KPH` is the
    clean case; the boundary on the distance at `off_route_distance_m
    == OFF_ROUTE_RADIUS_M` is the on-the-corridor-edge case, also clean.

    The float-arithmetic-imprecision on the haversine's intermediate
    trigonometry is absorbed by the test layer's stated 1e-3-meter
    tolerance per the PRD §2.8 prose, so the comparisons are direct-
    float-comparison-without-epsilon on this implementation's side.
    """
    speed_kph = float(gps_report.get("speed_kph", 0.0))
    speed_violated = speed_kph > constants.max_hazmat_speed_kph

    lat = float(gps_report.get("lat", 0.0))
    lon = float(gps_report.get("lon", 0.0))
    off_route_distance_m = haversine_distance_to_polyline(
        lat, lon, route_polyline, constants.earth_radius_m
    )
    off_route_violation = off_route_distance_m > constants.off_route_radius_m

    return {
        "speed_violated": bool(speed_violated),
        "off_route_violation": bool(off_route_violation),
        "off_route_distance_m": float(off_route_distance_m),
        "speed_points_value": (
            int(constants.gps_violation_speed_points)
            if speed_violated
            else 0
        ),
        "off_route_points_value": (
            int(constants.gps_violation_off_route_points)
            if off_route_violation
            else 0
        ),
    }
