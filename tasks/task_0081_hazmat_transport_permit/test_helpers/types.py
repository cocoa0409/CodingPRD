"""Domain types for the hazmat-transport-permit API.

Status enums for the six state-bearing entities, the auxiliary discriminator
enums (penalty sources, abort reasons, sweep causes, transition_fired values,
vehicle types, hazard-class taxonomy strings, inspection outcomes), the four
role-name strings, and TypedDicts for the entity-shape contracts the response
envelope's `data` field carries.

Append-only entities (VehicleInspection, GPSReport, Penalty) carry only `id`
and `created_at` in their common-fields set, so their TypedDicts deliberately
omit the `updated_at` and `version` fields the six mutable entities carry.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

# ─── Role names ──────────────────────────────────────────────────────────

ROLE_COMPANY_OPERATOR = "CompanyOperator"
ROLE_REGULATOR_OFFICER = "RegulatorOfficer"
ROLE_DRIVER = "Driver"
ROLE_TEST_HARNESS = "TestHarness"


class UserRole(str, Enum):
    """The four canonical role-name strings the auth-tier recognizes."""

    COMPANY_OPERATOR = ROLE_COMPANY_OPERATOR
    REGULATOR_OFFICER = ROLE_REGULATOR_OFFICER
    DRIVER = ROLE_DRIVER
    TEST_HARNESS = ROLE_TEST_HARNESS


# ─── State-machine enums for the six stateful entities ──────────────────


class CompanyQualificationStatus(str, Enum):
    """TransportCompany.qualification_status — the four-state cycle."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


class RouteApprovalStatus(str, Enum):
    """TransportRoute.approval_status — the four-state cycle with the
    REJECTED→DRAFT internal-collapse on the operator's reapply."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DriverEndorsementStatus(str, Enum):
    """Driver.hazmat_endorsement_status — the three-state cycle.

    The NOT_ATTESTED initial state, the in-force VALID state attested by the
    regulator's refresh-endorsement, and the INVALID state the wall-clock
    expiry / points-threshold cross / regulator-manual-revoke flips to.
    """

    NOT_ATTESTED = "NOT_ATTESTED"
    VALID = "VALID"
    INVALID = "INVALID"


class PermitLifecycleStatus(str, Enum):
    """Permit.lifecycle_status — the five-state posture-driven aggregate.

    DRAFT is the operator's application state; ACTIVE is the post-issue
    in-force state; SUSPENDED is the cyclically-reachable
    grounding-leg-failed state; EXPIRED and VOIDED are the two terminal
    absorbing states (wall-clock-elapsed and regulator-clerical-reversed
    respectively).
    """

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class TripStatus(str, Enum):
    """Trip.trip_status — the four-state fork-from-IN_TRANSIT machine.

    The PLANNED initial state, the IN_TRANSIT in-flight state, and the two
    terminal states COMPLETED (clean arrival) and ABORTED (operator's
    explicit abort or the cascade-abort from a permit-expiry-or-void).
    """

    PLANNED = "PLANNED"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class PenaltyVoidStatus(str, Enum):
    """Penalty.void_status — the two-state ACTIVE→UPHELD linear machine.

    The UPHELD terminal state is the regulator's appeal-uphold-success
    discriminator; UPHELD penalties are excluded from the rolling-points
    sum on the driver per the disciplinary-points conservation invariant.
    """

    ACTIVE = "ACTIVE"
    UPHELD = "UPHELD"


# ─── Auxiliary discriminator enums ──────────────────────────────────────


class InspectionOutcome(str, Enum):
    """VehicleInspection.outcome — the three values driving the
    vehicle-leg of the permit-validity AND-chain.  Only `PASSED` counts as
    compliant; `CONDITIONAL` and `FAILED` are both treated as a failing
    vehicle leg.  A `FAILED` outcome forces the inspection's `valid_until`
    equal to `inspected_at` for the zero-forward-validity certificate."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    CONDITIONAL = "CONDITIONAL"


class VehicleType(str, Enum):
    """Vehicle.vehicle_type — the descriptive class enum.  Not load-bearing
    for any compliance rule; appears in the read response and is filterable
    in the regulator's out-of-band audit views."""

    TANKER_LIQUID = "TANKER_LIQUID"
    TANKER_GAS = "TANKER_GAS"
    BOX_DRY_BULK = "BOX_DRY_BULK"
    FLATBED_PACKAGED = "FLATBED_PACKAGED"
    OTHER = "OTHER"


class PenaltySubjectType(str, Enum):
    """Penalty.subject_type — the polymorphic-subject discriminator.  Only
    the `DRIVER` value drives the automatic suspension cascade; the
    `COMPANY` and `VEHICLE` cases are recorded for the audit trail without
    a state-machine consequence."""

    DRIVER = "DRIVER"
    COMPANY = "COMPANY"
    VEHICLE = "VEHICLE"


class PenaltySource(str, Enum):
    """Penalty.source — the manual-vs-auto origin discriminator.  The two
    auto-flavours are independent; a single GPS sample firing both
    classifier flags inserts two Penalty rows in the same transaction."""

    MANUAL_REGULATOR = "MANUAL_REGULATOR"
    GPS_VIOLATION_SPEED = "GPS_VIOLATION_SPEED"
    GPS_VIOLATION_OFF_ROUTE = "GPS_VIOLATION_OFF_ROUTE"


class AbortReason(str, Enum):
    """Trip.abort_reason — the cause of a terminal-ABORTED trip.

    `OPERATOR_ABORT` is the operator's explicit cancel via the abort
    endpoint.  `PERMIT_EXPIRED_CASCADE` is the cascade-abort fan-out from
    a parent permit's wall-clock-expiry sweep transition.
    `PERMIT_SUSPENDED_CASCADE` is the on-disk discriminator for the
    void-issue's cascade (the enum is reused for the void's cause per the
    scaffold's enum-economy convention).  `GPS_VIOLATION_LIMIT` is the
    reserved-for-future value that no transition in the current rule set
    actually writes.
    """

    OPERATOR_ABORT = "OPERATOR_ABORT"
    PERMIT_SUSPENDED_CASCADE = "PERMIT_SUSPENDED_CASCADE"
    PERMIT_EXPIRED_CASCADE = "PERMIT_EXPIRED_CASCADE"
    GPS_VIOLATION_LIMIT = "GPS_VIOLATION_LIMIT"


class SweepScope(str, Enum):
    """POST /v1/_sweep/run body's `scope` field.  `ALL` covers both the
    permit-side wall-clock-expiry and the driver-side endorsement-expiry
    and rolling-window-fall-off recomputes; the two narrower modes restrict
    the per-row walk to one entity table."""

    ALL = "ALL"
    PERMITS_ONLY = "PERMITS_ONLY"
    DRIVERS_ONLY = "DRIVERS_ONLY"


class SweepPermitCause(str, Enum):
    """sweep response `permit_transitions[].cause` discriminator."""

    WALL_CLOCK_EXPIRY = "WALL_CLOCK_EXPIRY"
    GROUNDING_INVALIDATION = "GROUNDING_INVALIDATION"
    GROUNDING_REVALIDATION = "GROUNDING_REVALIDATION"


class SweepDriverStatusFlip(str, Enum):
    """sweep response `driver_recomputes[].status_flip` discriminator."""

    VALID_TO_INVALID = "VALID_TO_INVALID"


class VerifyComplianceTransitionFired(str, Enum):
    """verify-compliance response `transition_fired` discriminator covering
    the five observable transition labels on the permit aggregate."""

    NO_CHANGE = "NO_CHANGE"
    ACTIVE_TO_SUSPENDED = "ACTIVE_TO_SUSPENDED"
    SUSPENDED_TO_ACTIVE = "SUSPENDED_TO_ACTIVE"
    ACTIVE_TO_EXPIRED = "ACTIVE_TO_EXPIRED"
    SUSPENDED_TO_EXPIRED = "SUSPENDED_TO_EXPIRED"


# ─── Hazard-class taxonomy ──────────────────────────────────────────────

#: The closed set of UN hazardous-materials hazard-class code strings.
#: A class string outside this set on any of the six hazard-class-bearing
#: fields is a body-shape validation failure under the generic
#: ``ERR_VALIDATION``.
HAZARD_CLASSES_UN: List[str] = [
    "1.1", "1.2", "1.3", "1.4", "1.5", "1.6",
    "2.1", "2.2", "2.3",
    "3",
    "4.1", "4.2", "4.3",
    "5.1", "5.2",
    "6.1", "6.2",
    "7",
    "8",
    "9",
]


# ─── Entity TypedDicts ──────────────────────────────────────────────────

# Append-only entities have the bare-minimum (id, created_at) common-fields
# pair and deliberately omit `updated_at` and `version`.  The mutable
# entities carry the full common-fields quartet.


class TransportCompany(TypedDict, total=False):
    """The TransportCompany aggregate root."""

    id: str
    legal_name: str
    registration_number: str
    primary_contact_email: str
    address_line: str
    hazard_classes_authorized: List[str]
    qualification_status: str
    wallet_balance_cents: int
    submitted_at: Optional[str]
    approved_at: Optional[str]
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    """The Driver aggregate child-of-Company."""

    id: str
    company_id: str
    full_name: str
    license_number: str
    license_class: str
    hazmat_endorsement_status: str
    endorsement_classes: List[str]
    endorsement_valid_until: Optional[str]
    current_rolling_points: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    """The Vehicle aggregate child-of-Company."""

    id: str
    company_id: str
    plate_number: str
    vehicle_type: str
    max_payload_kg: int
    hazard_classes_compatible: List[str]
    latest_inspection_id: Optional[str]
    latest_inspection_outcome: Optional[str]
    latest_inspection_valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VehicleInspection(TypedDict, total=False):
    """The VehicleInspection append-only certificate row.  No `updated_at`,
    no `version` — append-only-by-construction per the common-fields-false
    convention of the response-envelope manifest in the scaffold."""

    id: str
    vehicle_id: str
    inspected_at: str
    outcome: str
    valid_until: str
    findings_note: str
    inspector_id: str
    created_at: str


class PolylineWaypoint(TypedDict):
    """A single (lat, lon) WGS-84 waypoint on a route's polyline."""

    lat: float
    lon: float


class TransportRoute(TypedDict, total=False):
    """The TransportRoute aggregate child-of-Company."""

    id: str
    company_id: str
    origin_label: str
    destination_label: str
    polyline: List[Dict[str, float]]
    hazard_classes_supported: List[str]
    approval_status: str
    approved_at: Optional[str]
    approved_by: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalHistoryEntry(TypedDict):
    """One entry in the Permit.renewal_history append-only sub-array."""

    renewed_at: str
    fee_cents: int
    late_penalty_applied: bool
    prior_valid_until: str
    new_valid_until: str


class Permit(TypedDict, total=False):
    """The Permit central aggregate.  Snapshot fields are written by the
    issue handler and refreshed by every subsequent verify-compliance call;
    the live-mode fields on the GET response are computed at read time."""

    id: str
    company_id: str
    route_id: str
    authorized_driver_ids: List[str]
    authorized_vehicle_ids: List[str]
    hazard_classes: List[str]
    valid_from: str
    valid_until: Optional[str]
    lifecycle_status: str
    issued_at: Optional[str]
    issued_by: Optional[str]
    issue_fee_cents: Optional[int]
    last_verified_at: Optional[str]
    snapshot_company_qualified: Optional[bool]
    snapshot_route_approved: Optional[bool]
    snapshot_within_window: Optional[bool]
    snapshot_driver_endorsements: Optional[Dict[str, bool]]
    snapshot_vehicle_inspections: Optional[Dict[str, bool]]
    renewal_history: List[RenewalHistoryEntry]
    voided_at: Optional[str]
    void_refunded_cents: Optional[int]
    # Computed-on-read live-mode fields surfaced by the GET endpoint.
    live_verdict: Optional[bool]
    live_per_leg: Optional[Dict[str, Any]]
    snapshot_overall: Optional[bool]
    # The application-preview embed surfaced on the POST /v1/permits 201.
    application_preview: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict, total=False):
    """The Trip aggregate child-of-Permit."""

    id: str
    permit_id: str
    driver_id: str
    vehicle_id: str
    cargo_description: str
    cargo_hazard_class: str
    cargo_weight_kg: int
    scheduled_departure_at: str
    scheduled_arrival_at: str
    actual_departure_at: Optional[str]
    actual_arrival_at: Optional[str]
    aborted_at: Optional[str]
    abort_reason: Optional[str]
    trip_status: str
    latest_gps_at: Optional[str]
    gps_violation_count: int
    created_at: str
    updated_at: str
    version: int


class GPSReport(TypedDict, total=False):
    """The GPSReport append-only telemetry sample row.  Carries the
    server-computed `off_route_distance_m` and the `auto_penalty_ids` list
    pointing back at the auto-Penalty rows the same transaction wrote."""

    id: str
    trip_id: str
    reported_at: str
    received_at: str
    lat: float
    lon: float
    speed_kph: float
    heading_deg: float
    off_route_distance_m: float
    idempotency_key: Optional[str]
    auto_penalty_ids: List[str]
    created_at: str


class Penalty(TypedDict, total=False):
    """The Penalty append-only disciplinary-ledger row.

    The `void_status` flip from ACTIVE to UPHELD is the one in-place
    mutation the entity admits, paired with the `upheld_at` and `upheld_by`
    fields the appeal-uphold handler writes; the `reason_note` is prepended
    with an `UPHELD-ON-APPEAL: …; ORIGINAL: …` marker on the uphold's
    side-effect per the entity's prose.  No `updated_at`, no `version`
    because the entity is common-fields-false in the strict append-only
    sense, save for the documented one-edge state machine.
    """

    id: str
    subject_type: str
    subject_id: str
    source: str
    source_gps_report_id: Optional[str]
    trip_id: Optional[str]
    points_value: int
    observed_at: str
    reason_note: str
    void_status: str
    upheld_at: Optional[str]
    upheld_by: Optional[str]
    created_at: str


class WalletDeltaSummary(TypedDict, total=False):
    """The wallet-effect sub-object the issue/renew/void response embeds."""

    wallet_debited_cents: Optional[int]
    wallet_credited_cents: Optional[int]
    new_wallet_balance_cents: int


__all__ = [
    "ROLE_COMPANY_OPERATOR",
    "ROLE_REGULATOR_OFFICER",
    "ROLE_DRIVER",
    "ROLE_TEST_HARNESS",
    "UserRole",
    "CompanyQualificationStatus",
    "RouteApprovalStatus",
    "DriverEndorsementStatus",
    "PermitLifecycleStatus",
    "TripStatus",
    "PenaltyVoidStatus",
    "InspectionOutcome",
    "VehicleType",
    "PenaltySubjectType",
    "PenaltySource",
    "AbortReason",
    "SweepScope",
    "SweepPermitCause",
    "SweepDriverStatusFlip",
    "VerifyComplianceTransitionFired",
    "HAZARD_CLASSES_UN",
    "TransportCompany",
    "Driver",
    "Vehicle",
    "VehicleInspection",
    "PolylineWaypoint",
    "TransportRoute",
    "RenewalHistoryEntry",
    "Permit",
    "Trip",
    "GPSReport",
    "Penalty",
    "WalletDeltaSummary",
]
