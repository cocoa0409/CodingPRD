"""Named-constant catalogue for the hazmat-transport-permit test layer.

The values mirror the ``constants_numeric_values`` block at the top of the
benchmark's difficulty-design file: every symbol on this list is the literal
integer or float the implementation's configuration loader is required to
honour for the test layer's boundary-precision assertions to land on the
expected outputs.  The PRD's §2.8 names the same symbols by name, and the
PRD's §2.11 catalogue of "the full named-constant catalogue" enumerates the
same set in prose.  The test files import the symbols from this module by
name rather than embedding bare numeric literals, so a deployment that pins
a different value for any symbol can be retargeted by editing this single
module.

Three convenience derived constants — ``LATE_RENEWAL_GRACE_SECONDS``, the
default seed-data company wallet float, and the test-canonical hazard-class
pair — are at the bottom of the file.
"""

from typing import Final, List

# ─── Time-window length constants (durations) ───────────────────────────

#: A permit's natural term in days from `valid_from` to `valid_until`.
PERMIT_DEFAULT_VALIDITY_DAYS: Final[int] = 365

#: The number of days before `valid_until` at which the renewal endpoint
#: opens.  Closed-left convention: ``now == valid_until -
#: RENEWAL_OPEN_WINDOW_DAYS`` is the first in-window moment.
RENEWAL_OPEN_WINDOW_DAYS: Final[int] = 60

#: The inner-window-width inside the outer renewal-window beyond which the
#: ``LATE_RENEWAL_PENALTY_CENTS`` surcharge applies.  Closed-left convention
#: on the inner window's left edge ``valid_until - LATE_RENEWAL_GRACE_DAYS``.
LATE_RENEWAL_GRACE_DAYS: Final[int] = 30

#: The maximum number of hours after a permit's ``issued_at`` during which
#: the void-issue clerical-error reversal is admissible.  Closed-right on
#: the duration: ``now - issued_at == VOID_ISSUE_WINDOW_HOURS`` is the last
#: in-window moment.  The scaffold's intended value is 24 hours.
VOID_ISSUE_WINDOW_HOURS: Final[int] = 24

#: The maximum number of days after a penalty's ``observed_at`` during
#: which the appeal-uphold action is admissible.  Closed-right on the
#: duration.  The scaffold's intended value is 30 days.
APPEAL_WINDOW_DAYS: Final[int] = 30

#: The trailing-edge length of the rolling-window over which the
#: ``driver_penalty_point_rolling_total`` calculation sums the non-UPHELD
#: penalty rows whose ``observed_at`` is in the open-left-closed-right
#: interval ``(now - PENALTY_WINDOW_DAYS, now]``.  Aliased in the PRD
#: prose as "the 365-day rolling window" and "the 12-month rolling
#: window".
PENALTY_WINDOW_DAYS: Final[int] = 365

#: A VehicleInspection's forward-validity-end is ``inspected_at +
#: INSPECTION_VALIDITY_DAYS`` for a ``PASSED`` outcome and the
#: zero-forward value ``inspected_at`` for a ``FAILED`` outcome.  The
#: scaffold pins the value at 180 days.
INSPECTION_VALIDITY_DAYS: Final[int] = 180

#: The grace-window after a driver's ``endorsement_valid_until`` during
#: which the wall-clock-expiry flip to ``INVALID`` is deferred.  The
#: scaffold pins this at zero days — the hard-cutoff at the exact
#: ``endorsement_valid_until`` moment, in deliberate contrast to the
#: permit's 30-day late-grace window.
ENDORSEMENT_RENEWAL_GRACE_DAYS: Final[int] = 0


# ─── Numeric thresholds and bounds ─────────────────────────────────────

#: The integer-valued rolling-points threshold at and above which the
#: driver's hazmat endorsement automatically flips to ``INVALID``.  The
#: predicate is inclusive-greater-than-or-equal: a rolling total of
#: exactly the threshold is the just-suspended state, one below is the
#: last-clean state.  The deployment's pinned value is 12.
THRESHOLD_DRIVER_SUSPENSION_POINTS: Final[int] = 12

#: The strict upper bound in kilometres-per-hour above which a GPS
#: sample's ``speed_kph`` fires the speed-violation auto-penalty.  The
#: comparison is strict-greater-than: a sample exactly at the limit is
#: not a violation.  The deployment's pinned value is 80.0 kph.
MAX_HAZMAT_SPEED_KPH: Final[float] = 80.0

#: The strict upper bound in metres on the perpendicular great-circle
#: distance from a GPS sample's ``(lat, lon)`` to the parent route's
#: polyline.  A sample with a strictly-larger computed
#: ``off_route_distance_m`` is the off-route violation.  The
#: deployment's pinned value is 500.0 metres.
OFF_ROUTE_RADIUS_M: Final[float] = 500.0

#: The inclusive upper bound on the ``authorized_vehicle_ids`` array's
#: cardinality on a permit application.  The lower bound is the constant
#: 1.  A violation produces the dedicated ``ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE``
#: 422 error at the priority-523 business-constraint check.
MAX_VEHICLES_PER_PERMIT: Final[int] = 20

#: The inclusive upper bound on the ``authorized_driver_ids`` array's
#: cardinality on a permit application.  The lower bound is the constant
#: 1.  A violation falls under the generic ``ERR_VALIDATION`` 422
#: catch-all because the driver-count is not a fee input.
MAX_DRIVERS_PER_PERMIT: Final[int] = 50

#: The WGS-84 mean Earth radius in metres, fed into the haversine-segment
#: perpendicular-distance computation used by the off-route classifier.
EARTH_RADIUS_M: Final[float] = 6371000.0


# ─── Fee-formula constants (integer cents) ──────────────────────────────

#: The flat base in cents on the permit-issue and the permit-renew fee.
BASE_RENEWAL_FEE_CENTS: Final[int] = 500_000

#: The additive surcharge in cents per vehicle on the permit's
#: ``authorized_vehicle_ids`` list, summed into the first stage's
#: subtotal.
PER_VEHICLE_SURCHARGE_CENTS: Final[int] = 30_000

#: The conditional add-on in cents for renewals whose arrival time is in
#: the closed-left-open-right late-grace inner-window
#: ``[valid_until - LATE_RENEWAL_GRACE_DAYS, valid_until)``.
LATE_RENEWAL_PENALTY_CENTS: Final[int] = 200_000

#: The saturating ceiling in cents on the post-late-add fee.  The cap
#: applies after the late-add, swallowing a late surcharge that pushes
#: the subtotal above the ceiling.
MAX_RENEWAL_FEE_CENTS: Final[int] = 5_000_000


# ─── GPS-auto-penalty point-value constants ─────────────────────────────

#: Points-value the speed-violation auto-Penalty row carries on its
#: ``points_value`` field.
GPS_VIOLATION_SPEED_POINTS: Final[int] = 3

#: Points-value the off-route-violation auto-Penalty row carries.
GPS_VIOLATION_OFF_ROUTE_POINTS: Final[int] = 4


# ─── Idempotency-Key header length bounds ───────────────────────────────

#: The inclusive lower bound on the ``Idempotency-Key`` request-header's
#: string length.  An out-of-range header value is rejected with the
#: generic body-shape ``ERR_VALIDATION`` 422.
IDEMPOTENCY_KEY_MIN_CHARS: Final[int] = 8

#: The inclusive upper bound on the same header's string length.
IDEMPOTENCY_KEY_MAX_CHARS: Final[int] = 128


# ─── Manual-penalty body bounds ─────────────────────────────────────────

#: Inclusive lower bound on a manual penalty's ``points_value``.
MANUAL_PENALTY_POINTS_MIN: Final[int] = 1

#: Inclusive upper bound on a manual penalty's ``points_value``.
MANUAL_PENALTY_POINTS_MAX: Final[int] = 50


# ─── Test-mode clock-advance bound ──────────────────────────────────────

#: The deployment-configured upper bound in seconds on a single
#: ``POST /v1/_clock/advance``'s ``advance_seconds`` payload.  The
#: scaffold pins this at 100 years' worth of seconds (3,155,760,000) to
#: bound the year-9999 datetime overflow while admitting the year-long
#: permit-term-expiry tests.
CLOCK_ADVANCE_MAX_SECONDS: Final[int] = 3_155_760_000


# ─── Seed-data conventions for the test layer ───────────────────────────

#: The TransportCompany row's initial ``wallet_balance_cents`` immediately
#: after the company-create endpoint mints the row.  The scaffold pins
#: the value at zero — the operator must top up the wallet through the
#: regulator-side out-of-band channel before any fee-paying action.  The
#: test layer's wallet-topup convention is the ``api_client.admin_wallet_topup``
#: affordance documented in ``test_helpers/api_client.py``.
INITIAL_WALLET_BALANCE_CENTS: Final[int] = 0

#: A generous wallet-balance value the test fixtures top a freshly-minted
#: company up to, comfortably exceeding the worst-case fee a 20-vehicle
#: late-grace renewal would cost (the cap is 5,000,000 cents, so 100 ×
#: the cap is well over the cap-saturating mark).
TEST_WALLET_TOPUP_CENTS: Final[int] = 500_000_000

#: The pagination-default page size the system's list endpoints honour
#: when the client's ``limit`` query parameter is absent.  Mirrors the
#: PRD's §2.3 prose ("the default is 10").
DEFAULT_PAGE_LIMIT: Final[int] = 10

#: The pagination-maximum-acceptable page-size value.  A ``limit`` above
#: this hard ceiling is rejected with ``ERR_VALIDATION`` 422.
MAX_PAGE_LIMIT: Final[int] = 100

#: The canonical pair of test-side hazard-class strings the fixture
#: factories use as a non-empty default.  Both values are in the
#: ``HAZARD_CLASSES_UN`` taxonomy of ``test_helpers.types``.  Class "3"
#: is "flammable liquid"; class "8" is "corrosives".  Tests that exercise
#: the hazard-class-subset rule narrow or widen this pair as needed.
CANONICAL_HAZARD_CLASSES: Final[List[str]] = ["3", "8"]

#: The single-class default a Trip's ``cargo_hazard_class`` field carries
#: in the standard fixture chain.  Drawn from ``CANONICAL_HAZARD_CLASSES``.
CANONICAL_CARGO_HAZARD_CLASS: Final[str] = "3"

#: A short Beijing-to-Tianjin straight-line polyline (two waypoints).
#: The lat/lon pairs are inside the WGS-84 ranges declared in §2.8 of the
#: PRD and the haversine-on-segments distance from any waypoint to itself
#: is exactly zero metres.  The corridor's half-width is
#: ``OFF_ROUTE_RADIUS_M``.
CANONICAL_POLYLINE: Final[List[dict]] = [
    {"lat": 39.9042, "lon": 116.4074},  # near Tian'anmen, Beijing
    {"lat": 39.1422, "lon": 117.2056},  # central Tianjin
]

#: A canonical on-route GPS sample's lat/lon pair: the first waypoint of
#: ``CANONICAL_POLYLINE``.  A sample with this position has a computed
#: perpendicular distance to the polyline of zero, well inside the
#: corridor's ``OFF_ROUTE_RADIUS_M`` half-width.
CANONICAL_ON_ROUTE_LAT: Final[float] = 39.9042
CANONICAL_ON_ROUTE_LON: Final[float] = 116.4074

#: A canonical far-off-route GPS sample's lat/lon pair: a point in the
#: South China Sea, thousands of kilometres from the Beijing-Tianjin
#: corridor.  Its perpendicular distance to the polyline is far greater
#: than ``OFF_ROUTE_RADIUS_M`` and so fires the off-route-violation flag
#: on the GPS classifier.
CANONICAL_OFF_ROUTE_LAT: Final[float] = 16.5000
CANONICAL_OFF_ROUTE_LON: Final[float] = 114.5000

#: The half-open right-exclusive boundary-tolerance in milliseconds the
#: integer-arithmetic time comparisons absorb on the clock-advance edges.
#: A test that advances by exactly N seconds expects the new clock to be
#: exactly the prior clock plus N seconds, with no rounding slack — the
#: scaffold's clock is the deterministic logical clock the test harness
#: drives.  Float comparisons on the wall-clock axis use this tolerance
#: as the absolute-difference upper bound in seconds.
CLOCK_FLOAT_TOLERANCE_SECONDS: Final[float] = 1e-3

#: The haversine-formula's accumulated-floating-point error tolerance in
#: metres on the off-route-distance assertion.  The PRD's §2.8 names the
#: same convention as "a millimetre-level tolerance of 1e-3 metres".
HAVERSINE_TOLERANCE_METRES: Final[float] = 1e-3

#: Aggregate dict bundling every named constant for the convenience of
#: the assertions module's domain-invariant checkers and the test files'
#: log lines.  The keys are the constant names verbatim.
CONSTANTS: Final[dict] = {
    "PERMIT_DEFAULT_VALIDITY_DAYS":      PERMIT_DEFAULT_VALIDITY_DAYS,
    "RENEWAL_OPEN_WINDOW_DAYS":          RENEWAL_OPEN_WINDOW_DAYS,
    "LATE_RENEWAL_GRACE_DAYS":           LATE_RENEWAL_GRACE_DAYS,
    "VOID_ISSUE_WINDOW_HOURS":           VOID_ISSUE_WINDOW_HOURS,
    "APPEAL_WINDOW_DAYS":                APPEAL_WINDOW_DAYS,
    "PENALTY_WINDOW_DAYS":               PENALTY_WINDOW_DAYS,
    "INSPECTION_VALIDITY_DAYS":          INSPECTION_VALIDITY_DAYS,
    "ENDORSEMENT_RENEWAL_GRACE_DAYS":    ENDORSEMENT_RENEWAL_GRACE_DAYS,
    "THRESHOLD_DRIVER_SUSPENSION_POINTS": THRESHOLD_DRIVER_SUSPENSION_POINTS,
    "MAX_HAZMAT_SPEED_KPH":              MAX_HAZMAT_SPEED_KPH,
    "OFF_ROUTE_RADIUS_M":                OFF_ROUTE_RADIUS_M,
    "MAX_VEHICLES_PER_PERMIT":           MAX_VEHICLES_PER_PERMIT,
    "MAX_DRIVERS_PER_PERMIT":            MAX_DRIVERS_PER_PERMIT,
    "EARTH_RADIUS_M":                    EARTH_RADIUS_M,
    "BASE_RENEWAL_FEE_CENTS":            BASE_RENEWAL_FEE_CENTS,
    "PER_VEHICLE_SURCHARGE_CENTS":       PER_VEHICLE_SURCHARGE_CENTS,
    "LATE_RENEWAL_PENALTY_CENTS":        LATE_RENEWAL_PENALTY_CENTS,
    "MAX_RENEWAL_FEE_CENTS":             MAX_RENEWAL_FEE_CENTS,
    "GPS_VIOLATION_SPEED_POINTS":        GPS_VIOLATION_SPEED_POINTS,
    "GPS_VIOLATION_OFF_ROUTE_POINTS":    GPS_VIOLATION_OFF_ROUTE_POINTS,
    "IDEMPOTENCY_KEY_MIN_CHARS":         IDEMPOTENCY_KEY_MIN_CHARS,
    "IDEMPOTENCY_KEY_MAX_CHARS":         IDEMPOTENCY_KEY_MAX_CHARS,
    "MANUAL_PENALTY_POINTS_MIN":         MANUAL_PENALTY_POINTS_MIN,
    "MANUAL_PENALTY_POINTS_MAX":         MANUAL_PENALTY_POINTS_MAX,
    "CLOCK_ADVANCE_MAX_SECONDS":         CLOCK_ADVANCE_MAX_SECONDS,
    "INITIAL_WALLET_BALANCE_CENTS":      INITIAL_WALLET_BALANCE_CENTS,
    "TEST_WALLET_TOPUP_CENTS":           TEST_WALLET_TOPUP_CENTS,
    "DEFAULT_PAGE_LIMIT":                DEFAULT_PAGE_LIMIT,
    "MAX_PAGE_LIMIT":                    MAX_PAGE_LIMIT,
}


__all__ = [
    "PERMIT_DEFAULT_VALIDITY_DAYS",
    "RENEWAL_OPEN_WINDOW_DAYS",
    "LATE_RENEWAL_GRACE_DAYS",
    "VOID_ISSUE_WINDOW_HOURS",
    "APPEAL_WINDOW_DAYS",
    "PENALTY_WINDOW_DAYS",
    "INSPECTION_VALIDITY_DAYS",
    "ENDORSEMENT_RENEWAL_GRACE_DAYS",
    "THRESHOLD_DRIVER_SUSPENSION_POINTS",
    "MAX_HAZMAT_SPEED_KPH",
    "OFF_ROUTE_RADIUS_M",
    "MAX_VEHICLES_PER_PERMIT",
    "MAX_DRIVERS_PER_PERMIT",
    "EARTH_RADIUS_M",
    "BASE_RENEWAL_FEE_CENTS",
    "PER_VEHICLE_SURCHARGE_CENTS",
    "LATE_RENEWAL_PENALTY_CENTS",
    "MAX_RENEWAL_FEE_CENTS",
    "GPS_VIOLATION_SPEED_POINTS",
    "GPS_VIOLATION_OFF_ROUTE_POINTS",
    "IDEMPOTENCY_KEY_MIN_CHARS",
    "IDEMPOTENCY_KEY_MAX_CHARS",
    "MANUAL_PENALTY_POINTS_MIN",
    "MANUAL_PENALTY_POINTS_MAX",
    "CLOCK_ADVANCE_MAX_SECONDS",
    "INITIAL_WALLET_BALANCE_CENTS",
    "TEST_WALLET_TOPUP_CENTS",
    "DEFAULT_PAGE_LIMIT",
    "MAX_PAGE_LIMIT",
    "CANONICAL_HAZARD_CLASSES",
    "CANONICAL_CARGO_HAZARD_CLASS",
    "CANONICAL_POLYLINE",
    "CANONICAL_ON_ROUTE_LAT",
    "CANONICAL_ON_ROUTE_LON",
    "CANONICAL_OFF_ROUTE_LAT",
    "CANONICAL_OFF_ROUTE_LON",
    "CLOCK_FLOAT_TOLERANCE_SECONDS",
    "HAVERSINE_TOLERANCE_METRES",
    "CONSTANTS",
]
