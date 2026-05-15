"""Named-constant catalogue.

The PRD's §2.11 closing paragraph and the §2.8 GPS-stream-constants paragraph
together enumerate the named symbols the calculations and the time-window
guards read. The eight scaffold-pinned regulatory-regime constants carry
specific numeric values the PRD's prose hard-codes — the 365-day rolling
penalty-points window, the 30-day appeal-window-after-`observed_at`, the
60-day pre-expiry renewal-open window, the 24-hour post-issue void-grace
window, the 180-day inspection-validity window, the zero-day endorsement-
renewal grace cushion, the WGS-84 mean Earth radius of 6,371,000.0 meters for
the haversine formula, and the "annual" 365-day permit term length — and these
are module-level immutable constants in this file with no environment-variable
override path, on the principle that the values are intrinsic to the regulatory
domain rather than deployment-configurable.

The eleven deployment-configurable named-constant symbols — the integer
suspension-threshold, the four cents-denominated fee-formula tariff integers
plus the saturating-fee-cap, the per-permit vehicle-list cardinality cap, the
late-renewal-grace days inside the renewal-open window, the float GPS speed
limit in km/h, the float off-route radius in meters, and the two integer
points-values for the speed and the off-route GPS-violation auto-penalties —
are read at startup from environment variables of the same names with sensible
canonical defaults baked in as fallbacks. The test harness's between-test
fixture-setup wires the environment-variables that the test-fixtures'
assertion-arithmetic anchors against, and the defaults are the policy-canonical
values a reasonable regulator would set so the implementation works as a
standalone container outside the test harness as well.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Section 1 — Scaffold-pinned, PRD-§2.11-baked-in, regulatory-regime intrinsic
# constants. These have no environment-variable override path because their
# values are the regulatory-domain's named figures-of-record rather than
# deployment knobs.
# ---------------------------------------------------------------------------

# The PRD §2.11 names the rolling-penalty window as "the 12-month rolling
# window" and "the 365-day rolling window" interchangeably; this is the trailing
# duration in days of the rolling sum that the driver's `current_rolling_points`
# field tracks (the open-on-the-left, closed-on-the-right interval ending at the
# current logical-clock value, the §2.9 conventions table entry for the
# rolling-points axis).
PENALTY_WINDOW_DAYS: int = int(os.environ.get("PENALTY_WINDOW_DAYS", "365"))

# The PRD §2.11 names "the 30-day appeal window measured from `observed_at`"
# as the closed-right duration during which a regulator's appeal-uphold action
# on a penalty is admissible. A duration of `now() - observed_at` strictly
# greater than this constant produces ERR_APPEAL_WINDOW_CLOSED.
APPEAL_WINDOW_DAYS: int = int(os.environ.get("APPEAL_WINDOW_DAYS", "30"))

# The PRD §2.11 names "the 60-day pre-expiry renewal-open window" as the
# outer-window's width-in-days that the renewal endpoint accepts a request in.
# The closed-left boundary at the moment `now() == valid_until -
# RENEWAL_OPEN_WINDOW_DAYS` is the just-opened renewal moment; an arrival
# strictly earlier is `ERR_RENEWAL_TOO_EARLY` 409.
RENEWAL_OPEN_WINDOW_DAYS: int = int(
    os.environ.get("RENEWAL_OPEN_WINDOW_DAYS", "60")
)

# The PRD §2.11 names "the 24-hour void-issue window measured from `issued_at`"
# as the closed-right duration after the permit's issuance during which the
# regulator may fire the clerical-error-reversal void-issue action. A duration
# of `now() - issued_at` strictly greater is `ERR_VOID_WINDOW_CLOSED` 409.
VOID_ISSUE_WINDOW_HOURS: int = int(
    os.environ.get("VOID_ISSUE_WINDOW_HOURS", "24")
)

# The PRD §2.8 inspection-outcomes paragraph and the §2.11 closing paragraph
# pin the inspection-validity duration as 180 days. The new VehicleInspection's
# `valid_until` field on a PASSED outcome is `inspected_at +
# INSPECTION_VALIDITY_DAYS`; on a FAILED outcome the field is forced equal to
# the inspection's `inspected_at` itself for zero forward validity.
INSPECTION_VALIDITY_DAYS: int = int(
    os.environ.get("INSPECTION_VALIDITY_DAYS", "180")
)

# The PRD §2.11 names the endorsement-renewal-grace as "zero days for the hard
# cutoff convention on the driver's endorsement-expiry", contrasting with the
# permit's late-grace-window's non-zero width. A driver's `VALID → INVALID`
# auto-flip on the sweep fires at the exact instant `now() >=
# driver.endorsement_valid_until`, with no cushion past the stored end.
ENDORSEMENT_RENEWAL_GRACE_DAYS: int = int(
    os.environ.get("ENDORSEMENT_RENEWAL_GRACE_DAYS", "0")
)

# The WGS-84 mean Earth radius in meters, fed into the haversine-segment
# perpendicular-distance computation that the gps_violation_classification
# off-route check evaluates. The PRD §2.8 and the scaffold's calculation 4
# both name the canonical value 6,371,000.0 meters.
EARTH_RADIUS_M: float = float(os.environ.get("EARTH_RADIUS_M", "6371000.0"))

# The PRD §2.11's "annual" permit-term-length convention pins the default at
# 365 days, with the renewal-step extending `valid_until` by exactly this
# constant amount measured forward from the prior `valid_until` so the term-end
# stride is exact across an on-time-renewals chain and the late-renewal
# carries the surcharge as the only price of lateness while keeping the
# stride invariant.
PERMIT_DEFAULT_VALIDITY_DAYS: int = int(
    os.environ.get("PERMIT_DEFAULT_VALIDITY_DAYS", "365")
)


# ---------------------------------------------------------------------------
# Section 2 — Deployment-configured constants. These have the same
# environment-variable name as their symbol name, parsed at startup with the
# canonical defaults baked in as fallback when the env-var is unset.
# ---------------------------------------------------------------------------

# Default canonical values follow the policy-sensible-number convention. The
# test fixtures override these at container start by passing env-vars to the
# docker-run command per the test-harness's standard wire-the-numerics
# convention.
_DEFAULT_THRESHOLD_DRIVER_SUSPENSION_POINTS = 12
_DEFAULT_MAX_VEHICLES_PER_PERMIT = 20
_DEFAULT_LATE_RENEWAL_GRACE_DAYS = 14
_DEFAULT_MAX_HAZMAT_SPEED_KPH = 80.0
_DEFAULT_OFF_ROUTE_RADIUS_M = 500.0
_DEFAULT_BASE_RENEWAL_FEE_CENTS = 50000  # $500.00 base
_DEFAULT_PER_VEHICLE_SURCHARGE_CENTS = 5000  # $50.00 per vehicle
_DEFAULT_LATE_RENEWAL_PENALTY_CENTS = 25000  # $250.00 late add-on
_DEFAULT_MAX_RENEWAL_FEE_CENTS = 1000000  # $10,000.00 saturating cap
_DEFAULT_GPS_VIOLATION_SPEED_POINTS = 3
_DEFAULT_GPS_VIOLATION_OFF_ROUTE_POINTS = 4

# The maximum-single-advance bound on the `_clock/advance` endpoint, in
# seconds. The PRD §2.5's clock-advance prose names "on the order of a century
# of seconds" as the upper bound. The scaffold's clock-constants table
# nominally pins this in seconds.
_DEFAULT_CLOCK_ADVANCE_MAX_SECONDS = 100 * 365 * 24 * 3600


@dataclass(frozen=True)
class Constants:
    """The bundled deployment-configured constants and the regulatory-pinned
    ones. The deployment loader writes the read-from-environment values into
    the dataclass instance once at startup and the rest of the application
    reads the values by attribute access. The dataclass is `frozen=True` so
    no mid-run mutation can race the test-harness's exit-time consistency
    audit on the value table.

    The eleven deployment-configurable fields are the first eleven attributes
    below; the eight scaffold-pinned regulatory-regime constants are also
    accessible on the same instance for ergonomic single-source reads from
    the handlers' code.
    """

    # The eleven deployment-configurable constants the test-harness env-vars
    # override (with the canonical defaults baked in here as the fallback).
    threshold_driver_suspension_points: int
    max_vehicles_per_permit: int
    late_renewal_grace_days: int
    max_hazmat_speed_kph: float
    off_route_radius_m: float
    base_renewal_fee_cents: int
    per_vehicle_surcharge_cents: int
    late_renewal_penalty_cents: int
    max_renewal_fee_cents: int
    gps_violation_speed_points: int
    gps_violation_off_route_points: int

    # The eight regulatory-pinned constants (mirrored here from the module-
    # level constants above for the dataclass-attribute-access ergonomics).
    penalty_window_days: int
    appeal_window_days: int
    renewal_open_window_days: int
    void_issue_window_hours: int
    inspection_validity_days: int
    endorsement_renewal_grace_days: int
    earth_radius_m: float
    permit_default_validity_days: int

    # The clock-advance upper-bound on the test-mode `_clock/advance` endpoint.
    clock_advance_max_seconds: int


def load_config() -> Constants:
    """Read the eleven deployment-configurable constants from the environment
    and bundle them with the eight regulatory-pinned constants into the
    `Constants` dataclass instance the rest of the application sees as the
    deployment's configuration view.

    The integer-and-float parsing uses the standard `int()` and `float()`
    constructors against the env-var-string-or-the-canonical-default-string
    fallback. A malformed env-var value (e.g., `int("not_a_number")`) raises
    `ValueError` at startup, which is the canonical fail-fast behavior — the
    container's process exits before it reaches the bind-and-listen state and
    the test-harness's docker-compose-up's readiness probe times out, which is
    the deterministic-startup-failure signal.
    """
    return Constants(
        threshold_driver_suspension_points=int(
            os.environ.get(
                "THRESHOLD_DRIVER_SUSPENSION_POINTS",
                str(_DEFAULT_THRESHOLD_DRIVER_SUSPENSION_POINTS),
            )
        ),
        max_vehicles_per_permit=int(
            os.environ.get(
                "MAX_VEHICLES_PER_PERMIT", str(_DEFAULT_MAX_VEHICLES_PER_PERMIT)
            )
        ),
        late_renewal_grace_days=int(
            os.environ.get(
                "LATE_RENEWAL_GRACE_DAYS", str(_DEFAULT_LATE_RENEWAL_GRACE_DAYS)
            )
        ),
        max_hazmat_speed_kph=float(
            os.environ.get(
                "MAX_HAZMAT_SPEED_KPH", str(_DEFAULT_MAX_HAZMAT_SPEED_KPH)
            )
        ),
        off_route_radius_m=float(
            os.environ.get(
                "OFF_ROUTE_RADIUS_M", str(_DEFAULT_OFF_ROUTE_RADIUS_M)
            )
        ),
        base_renewal_fee_cents=int(
            os.environ.get(
                "BASE_RENEWAL_FEE_CENTS", str(_DEFAULT_BASE_RENEWAL_FEE_CENTS)
            )
        ),
        per_vehicle_surcharge_cents=int(
            os.environ.get(
                "PER_VEHICLE_SURCHARGE_CENTS",
                str(_DEFAULT_PER_VEHICLE_SURCHARGE_CENTS),
            )
        ),
        late_renewal_penalty_cents=int(
            os.environ.get(
                "LATE_RENEWAL_PENALTY_CENTS",
                str(_DEFAULT_LATE_RENEWAL_PENALTY_CENTS),
            )
        ),
        max_renewal_fee_cents=int(
            os.environ.get(
                "MAX_RENEWAL_FEE_CENTS", str(_DEFAULT_MAX_RENEWAL_FEE_CENTS)
            )
        ),
        gps_violation_speed_points=int(
            os.environ.get(
                "GPS_VIOLATION_SPEED_POINTS",
                str(_DEFAULT_GPS_VIOLATION_SPEED_POINTS),
            )
        ),
        gps_violation_off_route_points=int(
            os.environ.get(
                "GPS_VIOLATION_OFF_ROUTE_POINTS",
                str(_DEFAULT_GPS_VIOLATION_OFF_ROUTE_POINTS),
            )
        ),
        penalty_window_days=PENALTY_WINDOW_DAYS,
        appeal_window_days=APPEAL_WINDOW_DAYS,
        renewal_open_window_days=RENEWAL_OPEN_WINDOW_DAYS,
        void_issue_window_hours=VOID_ISSUE_WINDOW_HOURS,
        inspection_validity_days=INSPECTION_VALIDITY_DAYS,
        endorsement_renewal_grace_days=ENDORSEMENT_RENEWAL_GRACE_DAYS,
        earth_radius_m=EARTH_RADIUS_M,
        permit_default_validity_days=PERMIT_DEFAULT_VALIDITY_DAYS,
        clock_advance_max_seconds=int(
            os.environ.get(
                "CLOCK_ADVANCE_MAX_SECONDS",
                str(_DEFAULT_CLOCK_ADVANCE_MAX_SECONDS),
            )
        ),
    )


# The canonical UN-hazard-class taxonomy from PRD §2.8. The values are the
# bytes-exact strings the API accepts on the hazard-class array fields of the
# company, the route, the driver-endorsement, the vehicle-compatibility, the
# permit-authorization, and the trip-cargo-class field. A value outside this
# set on any of those request bodies is the catch-all body-shape
# `ERR_VALIDATION` 422.
UN_HAZARD_CLASS_CODES: frozenset[str] = frozenset(
    {
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "1.5",
        "1.6",
        "2.1",
        "2.2",
        "2.3",
        "3",
        "4.1",
        "4.2",
        "4.3",
        "5.1",
        "5.2",
        "6.1",
        "6.2",
        "7",
        "8",
        "9",
    }
)

VEHICLE_TYPES: frozenset[str] = frozenset(
    {
        "TANKER_LIQUID",
        "TANKER_GAS",
        "BOX_DRY_BULK",
        "FLATBED_PACKAGED",
        "OTHER",
    }
)

INSPECTION_OUTCOMES: frozenset[str] = frozenset(
    {"PASSED", "FAILED", "CONDITIONAL"}
)

PENALTY_SUBJECT_TYPES: frozenset[str] = frozenset(
    {"DRIVER", "COMPANY", "VEHICLE"}
)

PENALTY_SOURCES: frozenset[str] = frozenset(
    {"MANUAL_REGULATOR", "GPS_VIOLATION_SPEED", "GPS_VIOLATION_OFF_ROUTE"}
)

COMPANY_QUALIFICATION_STATES: frozenset[str] = frozenset(
    {"DRAFT", "SUBMITTED", "APPROVED", "REVOKED"}
)

ROUTE_APPROVAL_STATES: frozenset[str] = frozenset(
    {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED"}
)

DRIVER_ENDORSEMENT_STATES: frozenset[str] = frozenset(
    {"NOT_ATTESTED", "VALID", "INVALID"}
)

PERMIT_LIFECYCLE_STATES: frozenset[str] = frozenset(
    {"DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "VOIDED"}
)

TRIP_STATES: frozenset[str] = frozenset(
    {"PLANNED", "IN_TRANSIT", "COMPLETED", "ABORTED"}
)

PENALTY_VOID_STATES: frozenset[str] = frozenset({"ACTIVE", "UPHELD"})

ABORT_REASONS: frozenset[str] = frozenset(
    {
        "OPERATOR_ABORT",
        "PERMIT_SUSPENDED_CASCADE",
        "PERMIT_EXPIRED_CASCADE",
        "GPS_VIOLATION_LIMIT",
    }
)

CANONICAL_ROLES: frozenset[str] = frozenset(
    {"CompanyOperator", "RegulatorOfficer", "Driver", "TestHarness"}
)

# The two header names the auth middleware reads, exactly as the PRD §2.1's
# H3 paragraph names them (without the optional `X-Request-ID` echo header,
# which we generate server-side on every response per §2.2's envelope contract).
HEADER_USER_ID: str = "X-User-ID"
HEADER_USER_ROLE: str = "X-User-Role"

# The idempotency-key header name the gps-report ingest endpoint reads. The
# PRD §2.10 idempotency-contract paragraph names the header as `Idempotency-Key`
# with the standard HTTP-header-case (the client sends `Idempotency-Key:
# <opaque string>` and the server's case-insensitive header lookup matches).
HEADER_IDEMPOTENCY_KEY: str = "Idempotency-Key"

# Idempotency-Key length bounds from the PRD §2.10 and §2.8 prose. A header
# value outside this length range is a body-shape `ERR_VALIDATION` 422.
IDEMPOTENCY_KEY_MIN_LEN: int = 8
IDEMPOTENCY_KEY_MAX_LEN: int = 128

# Pagination contract from the PRD §2.3 prose: default limit 10, allowed range
# [1, 100] inclusive on `limit`, and the non-negative integer convention on
# `offset` with a default of 0. The four pagination fields' names in the
# response envelope's `meta` block are `limit`, `offset`, `total_count`, and
# `has_more`, mirroring the scaffold's `pagination_fields` list.
PAGINATION_LIMIT_DEFAULT: int = 10
PAGINATION_LIMIT_MIN: int = 1
PAGINATION_LIMIT_MAX: int = 100
PAGINATION_OFFSET_DEFAULT: int = 0

# The canonical-auto-penalty reason-note strings the PRD §2.4 closing paragraph
# names for the two GPS-auto-Penalty kinds. The test layer asserts these exact
# prefix strings on the auto-Penalty rows' `reason_note` field.
AUTO_PENALTY_REASON_SPEED: str = "Auto: speed exceeded the hazmat speed limit"
AUTO_PENALTY_REASON_OFF_ROUTE: str = "Auto: off-route beyond the permitted corridor"

# Driver-list cardinality bound on the permit's `authorized_driver_ids` array
# per the PRD §2.4 cross-entity-references paragraph: an explicit constant of
# 50 as the upper bound, with the lower bound 1 (non-empty). The vehicle-list
# upper bound is the configurable `MAX_VEHICLES_PER_PERMIT` constant above.
PERMIT_DRIVER_LIST_MAX: int = int(
    os.environ.get("PERMIT_DRIVER_LIST_MAX", "50")
)
PERMIT_DRIVER_LIST_MIN: int = 1
PERMIT_VEHICLE_LIST_MIN: int = 1

# Length bounds on the free-text fields the PRD §2.4's "free-text fields are
# bounded in length" closing paragraph names. The bounds are pairs of
# (min_inclusive, max_inclusive) integers; the bound is checked at the
# body-shape catch-all `ERR_VALIDATION` 422 tier.
LEGAL_NAME_LEN_RANGE: tuple[int, int] = (1, 200)
ADDRESS_LINE_LEN_RANGE: tuple[int, int] = (0, 500)
DRIVER_FULL_NAME_LEN_RANGE: tuple[int, int] = (1, 120)
DRIVER_LICENSE_NUMBER_LEN_RANGE: tuple[int, int] = (6, 32)
DRIVER_LICENSE_CLASS_LEN_RANGE: tuple[int, int] = (1, 16)
VEHICLE_PLATE_NUMBER_LEN_RANGE: tuple[int, int] = (4, 16)
ROUTE_LABEL_LEN_RANGE: tuple[int, int] = (1, 200)
INSPECTION_FINDINGS_NOTE_LEN_RANGE: tuple[int, int] = (0, 2000)
PENALTY_REASON_NOTE_LEN_RANGE: tuple[int, int] = (1, 500)
PENALTY_UPHOLD_REASON_LEN_RANGE: tuple[int, int] = (1, 500)
PENALTY_POINTS_VALUE_RANGE: tuple[int, int] = (1, 50)  # manual penalty range
GENERIC_REASON_NOTE_LEN_RANGE: tuple[int, int] = (1, 500)  # void, revoke, abort
OPTIONAL_NOTE_LEN_RANGE: tuple[int, int] = (0, 500)  # issue_note, approve_note, etc.
ARRIVE_DELIVERY_ATTESTATION_LEN_RANGE: tuple[int, int] = (0, 1000)
ROUTE_REJECTION_REASON_LEN_RANGE: tuple[int, int] = (1, 500)
DRIVER_REVOKE_REASON_LEN_RANGE: tuple[int, int] = (1, 500)
TRIP_CARGO_DESCRIPTION_LEN_RANGE: tuple[int, int] = (1, 500)

# Polyline waypoint-count bounds per the PRD §2.8 paragraph on the route's
# polyline: an inclusive 2-to-200 integer range on the array length.
POLYLINE_WAYPOINT_COUNT_RANGE: tuple[int, int] = (2, 200)

# Latitude and longitude inclusive degree ranges (WGS-84 standard).
LAT_RANGE: tuple[float, float] = (-90.0, 90.0)
LON_RANGE: tuple[float, float] = (-180.0, 180.0)
HEADING_RANGE: tuple[float, float] = (0.0, 360.0)

# Registration-number regex pattern per the PRD §2.4 and the scaffold's §1.1
# TransportCompany.registration_number field-prose: an 8-to-32 character string
# of uppercase Latin letters and digits.
REGISTRATION_NUMBER_REGEX: str = r"^[A-Z0-9]{8,32}$"

# Email-syntax regex — a permissive RFC-5322-syntactic pattern. The PRD §2.4
# names the check as "RFC 5322 syntactic" without specifying the exact regex,
# and the scaffold's prose calls it a "syntactic check only" so we apply a
# relaxed `local-part@domain` pattern that the standard regulatory-form-input
# emails satisfy.
EMAIL_SYNTAX_REGEX: str = (
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)
