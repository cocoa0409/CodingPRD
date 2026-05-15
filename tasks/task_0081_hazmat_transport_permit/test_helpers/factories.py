"""Payload-factory functions for the hazmat-transport-permit API.

One ``create_X_payload(**overrides)`` per resource-creation endpoint
declared in the PRD's §4 endpoint reference, plus the body-shape
factories for the state-transition action endpoints that carry a
non-trivial body (the company-revoke's ``reason_note``, the driver-
endorsement attestation's two-shape body, the route-reject's
``rejection_reason``, the permit-issue's optional ``note``, the
permit-renew's optional ``authorized_vehicle_ids``-and-driver-list-and-
hazard-class-list trio, the permit-void's required ``reason_note``, the
trip-abort's required ``reason_note``, the GPS-report's
position-and-speed quartet, the manual-penalty's full body, the
appeal-uphold's ``uphold_reason``).

The factories carry the "good baseline" defaults for the input fields the
relevant endpoint accepts on the happy path, applying any overrides the
caller passes via ``**overrides``.  Tests that exercise the
body-shape-validation rejection paths copy the baseline and mutate the
specific field whose value the test is targeting (omitting a required
field, supplying a value of the wrong type, supplying a value outside
the field's numeric range or enum-allowed-set, etc.).

The names that appear in this module are the canonical PRD-exact field
names — ``legal_name`` and ``registration_number`` and the rest — and the
test layer's assertions read the same names back from the response body
so the test suite is field-name-traceable across the
factory-to-response round-trip.
"""

from typing import Any, Dict, List, Optional
from uuid import uuid4

from .constants import (
    CANONICAL_CARGO_HAZARD_CLASS,
    CANONICAL_HAZARD_CLASSES,
    CANONICAL_POLYLINE,
    CANONICAL_ON_ROUTE_LAT,
    CANONICAL_ON_ROUTE_LON,
    MANUAL_PENALTY_POINTS_MAX,
    MANUAL_PENALTY_POINTS_MIN,
    MAX_HAZMAT_SPEED_KPH,
)
from .types import (
    InspectionOutcome,
    PenaltySource,
    PenaltySubjectType,
    VehicleType,
)


# ─── Helper utilities ─────────────────────────────────────────────────


def _random_token(prefix: str, length_digits: int = 8) -> str:
    """A short unique-per-call token suitable for the natural-key
    fields that the duplicate-identifier check on each creation
    endpoint reads.  Each call returns a fresh string so two
    factory-emitted payloads collide on the natural key only when the
    caller explicitly passes the same override.
    """
    suffix = uuid4().hex[:length_digits].upper()
    return f"{prefix}{suffix}"


def _apply_overrides(defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge an overrides dict into the defaults dict, with the
    convention that an override-value of ``None`` removes the key from
    the resulting dict entirely (so a test for the "field omitted
    from the body" body-shape-validation case can express it as
    ``create_X_payload(field_name=None)``).
    """
    out = dict(defaults)
    for key, value in overrides.items():
        if value is None and key in out:
            del out[key]
        else:
            out[key] = value
    return out


# ─── TransportCompany ──────────────────────────────────────────────────


def create_company_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/companies``.

    The natural-key ``registration_number`` is a fresh
    eight-to-thirty-two-uppercase-alphanumeric token per call so the
    duplicate-identifier 409 fires only when the test explicitly passes
    the same value across two creates.

    The ``hazard_classes_authorized`` array defaults to the canonical
    test pair from ``CANONICAL_HAZARD_CLASSES``.  The default
    ``legal_name`` is the role-name-prefixed unique-token so the
    audit-trail string differs across tests for the regulator-side
    log readability.
    """
    defaults: Dict[str, Any] = {
        "legal_name": f"Hazmat Carrier {_random_token('NAME')}",
        "registration_number": _random_token("REG", length_digits=12),
        "primary_contact_email": f"safety+{_random_token('CO').lower()}@example.test",
        "address_line": "123 Industrial Park Road, Some City",
        "hazard_classes_authorized": list(CANONICAL_HAZARD_CLASSES),
    }
    return _apply_overrides(defaults, overrides)


def revoke_company_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/companies/{company_id}/revoke``.

    The ``reason_note`` is the required 1-to-500-character cause-string.
    The optional ``version`` is absent by default so the OCC check is
    opted-out unless the test explicitly passes a value.
    """
    defaults: Dict[str, Any] = {
        "reason_note": "Periodic compliance review found safety issues.",
    }
    return _apply_overrides(defaults, overrides)


def approve_company_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/companies/{company_id}/approve``.

    All fields are optional; the optional ``approval_note`` is the
    regulator-side comment string captured by the audit trail.  The
    default is the empty body ``{}``.
    """
    defaults: Dict[str, Any] = {}
    return _apply_overrides(defaults, overrides)


def submit_company_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/companies/{company_id}/submit``.  Empty by
    default; the optional ``version`` field engages the OCC check if
    the test passes it explicitly."""
    defaults: Dict[str, Any] = {}
    return _apply_overrides(defaults, overrides)


# ─── Driver ────────────────────────────────────────────────────────────


def create_driver_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/companies/{company_id}/drivers``.

    The ``license_number`` is the per-company-unique natural key the
    duplicate-identifier 409 fires on; the per-call random suffix is
    long enough that two factory-emitted bodies do not collide.

    The ``endorsement_classes_requested`` array is the operator's
    asserted hazard-class list; the server-side ``endorsement_classes``
    starts as the empty list and the regulator's refresh-endorsement
    overwrites it to the regulator-verified subset.  The factory's
    default is the canonical test pair.
    """
    defaults: Dict[str, Any] = {
        "full_name": f"Driver {_random_token('NAME', 6)}",
        "license_number": _random_token("LIC", length_digits=10),
        "license_class": "B1",
        "endorsement_classes_requested": list(CANONICAL_HAZARD_CLASSES),
    }
    return _apply_overrides(defaults, overrides)


def driver_attestation_payload(
    endorsement_valid_until: str,
    endorsement_classes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for the attestation-shape of
    ``POST /v1/drivers/{driver_id}/refresh-endorsement``.

    The ``endorsement_valid_until`` ISO-8601 UTC timestamp string must
    be strictly greater than the current logical-clock value (the
    not-in-the-past body-shape rule).  The ``endorsement_classes``
    list is the non-empty regulator-attested hazard-class subset; an
    empty list is rejected with ``ERR_VALIDATION`` 422.  The
    ``revoke`` flag is absent on this shape (it would make the body
    ambiguous between the two mutually-exclusive shapes, which the
    handler rejects with ``ERR_VALIDATION`` 422).
    """
    defaults: Dict[str, Any] = {
        "endorsement_valid_until": endorsement_valid_until,
        "endorsement_classes": list(endorsement_classes) if endorsement_classes else list(CANONICAL_HAZARD_CLASSES),
    }
    return _apply_overrides(defaults, overrides)


def driver_revoke_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for the revoke-shape of the same refresh-endorsement
    endpoint.  The ``revoke: true`` flag and the ``revoke_reason``
    1-to-500-character cause are the two required fields; the
    attestation-shape's two fields are absent.  A body containing both
    shapes' fields or neither's fields is the body-shape
    ``ERR_VALIDATION`` 422 ambiguity case."""
    defaults: Dict[str, Any] = {
        "revoke": True,
        "revoke_reason": "Regulator-initiated revocation for cause.",
    }
    return _apply_overrides(defaults, overrides)


# ─── Vehicle and inspection ────────────────────────────────────────────


def create_vehicle_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/companies/{company_id}/vehicles``.

    The ``plate_number`` is the system-wide-unique natural key
    triggering the ``ERR_DUPLICATE_IDENTIFIER`` 409 on a collision
    (the contrast with the driver's per-company-scoped license-number
    uniqueness).  The ``vehicle_type`` defaults to the
    ``TANKER_LIQUID`` enum value, the descriptive class that the
    canonical test fleet carries.  The ``max_payload_kg`` is a
    strictly-positive integer.  The ``hazard_classes_compatible``
    array is the construction-certified per-vehicle hazard-class
    set the cargo-vs-vehicle compatibility check at trip-create reads.
    """
    defaults: Dict[str, Any] = {
        "plate_number": _random_token("PL", length_digits=6),
        "vehicle_type": VehicleType.TANKER_LIQUID.value,
        "max_payload_kg": 20000,
        "hazard_classes_compatible": list(CANONICAL_HAZARD_CLASSES),
    }
    return _apply_overrides(defaults, overrides)


def create_inspection_payload(inspected_at: str, **overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/vehicles/{vehicle_id}/inspections``.

    The ``inspected_at`` ISO-8601 UTC timestamp must be at-or-before
    the current logical-clock value (a future-dated inspection is the
    catch-all ``ERR_VALIDATION`` 422).  The ``outcome`` defaults to
    ``PASSED`` from the three-value enum.  The optional
    ``findings_note`` is the inspector's prose finding, the optional
    ``inspector_id`` override gives the regulator-side audit value
    (defaults to the request's ``X-User-ID``).
    """
    defaults: Dict[str, Any] = {
        "inspected_at": inspected_at,
        "outcome": InspectionOutcome.PASSED.value,
        "findings_note": "Routine annual hazmat inspection, no findings.",
    }
    return _apply_overrides(defaults, overrides)


# ─── TransportRoute ────────────────────────────────────────────────────


def create_route_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/companies/{company_id}/routes``.

    The polyline is the canonical Beijing-Tianjin two-waypoint default.
    The ``hazard_classes_supported`` array must be a subset of the
    parent company's ``hazard_classes_authorized`` at the moment of the
    operator's submit, and the same check is re-evaluated against the
    company's then-current set at the regulator's approve moment — the
    PRD's §2.9 names this as the "two-time-point hazard-class subset
    re-check".
    """
    defaults: Dict[str, Any] = {
        "origin_label": "Beijing Industrial Park",
        "destination_label": "Tianjin Port Terminal",
        "polyline": [dict(wp) for wp in CANONICAL_POLYLINE],
        "hazard_classes_supported": list(CANONICAL_HAZARD_CLASSES),
    }
    return _apply_overrides(defaults, overrides)


def reject_route_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/routes/{route_id}/reject``.

    The required ``rejection_reason`` 1-to-500-character cause is the
    regulator's stated reason, stored on the row's
    ``rejection_reason`` field for the operator's later reapply.  The
    optional ``version`` opt-in engages the OCC check.
    """
    defaults: Dict[str, Any] = {
        "rejection_reason": "Polyline traverses a restricted urban zone.",
    }
    return _apply_overrides(defaults, overrides)


# ─── Permit ────────────────────────────────────────────────────────────


def create_permit_payload(
    route_id: str,
    authorized_driver_ids: List[str],
    authorized_vehicle_ids: List[str],
    valid_from: str,
    hazard_classes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for ``POST /v1/permits``.

    The four required cross-aggregate references — the ``route_id``
    foreign key, the non-empty ``authorized_driver_ids`` list, the
    non-empty ``authorized_vehicle_ids`` list (whose length is the
    inclusive interval ``[1, MAX_VEHICLES_PER_PERMIT]``), and the
    non-empty ``hazard_classes`` array which must be a subset of the
    intersection of the parent company's and the route's hazard-class
    arrays at the application moment — are positional arguments here.

    The ``valid_from`` ISO-8601 UTC timestamp is the desired start of
    the permit's term; the issue handler writes
    ``valid_until = valid_from + PERMIT_DEFAULT_VALIDITY_DAYS``.  A
    back-dated ``valid_from`` (strictly earlier than the current
    logical-clock value) is the body-shape
    ``ERR_VALIDATION`` 422 case the PRD's §3.5 names.

    The optional ``application_note`` is the operator's free-text
    description of the application's purpose, stored on the audit
    trail without driving any rule.
    """
    if hazard_classes is None:
        hazard_classes = list(CANONICAL_HAZARD_CLASSES)
    defaults: Dict[str, Any] = {
        "route_id": route_id,
        "authorized_driver_ids": list(authorized_driver_ids),
        "authorized_vehicle_ids": list(authorized_vehicle_ids),
        "hazard_classes": list(hazard_classes),
        "valid_from": valid_from,
        "application_note": "Routine application for hazmat transit permit.",
    }
    return _apply_overrides(defaults, overrides)


def issue_permit_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/permits/{permit_id}/issue``.  All fields are
    optional; the convention is to pass either an empty body or just
    the OCC ``version`` integer with an optional ``issue_note``
    audit-trail comment."""
    defaults: Dict[str, Any] = {}
    return _apply_overrides(defaults, overrides)


def verify_compliance_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/permits/{permit_id}/verify-compliance``.

    Like the issue body, an empty body is the standard happy-path
    request shape.  The optional ``version`` integer engages the OCC
    check on the permit row's ``version``; the optional ``note`` is
    the regulator's free-text comment captured in the audit trail."""
    defaults: Dict[str, Any] = {}
    return _apply_overrides(defaults, overrides)


def renew_permit_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/permits/{permit_id}/renew``.

    Each of the four override-controllable optional fields —
    ``authorized_vehicle_ids``, ``authorized_driver_ids``,
    ``hazard_classes``, and ``renew_note`` — is absent from the
    default empty-body shape so the standard renew-without-roster-change
    happy path engages only the wallet-debit and the term-extension
    side-effects.  The optional ``version`` engages the OCC check.
    """
    defaults: Dict[str, Any] = {}
    return _apply_overrides(defaults, overrides)


def void_issue_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/permits/{permit_id}/void-issue``.

    The required ``reason_note`` 1-to-500-character cause is the
    regulator's stated clerical-error description; the optional
    ``version`` engages the OCC.  The wallet-refund amount is the
    server-computed sum of the on-row ``issue_fee_cents`` and the
    sum of the ``renewal_history[*].fee_cents`` entries, so the body
    does not carry a refund-amount input.
    """
    defaults: Dict[str, Any] = {
        "reason_note": "Clerical error in permit issuance — reversing.",
    }
    return _apply_overrides(defaults, overrides)


# ─── Trip ─────────────────────────────────────────────────────────────


def create_trip_payload(
    driver_id: str,
    vehicle_id: str,
    scheduled_departure_at: str,
    scheduled_arrival_at: str,
    cargo_hazard_class: Optional[str] = None,
    cargo_weight_kg: int = 5000,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for ``POST /v1/permits/{permit_id}/trips``.

    The cross-aggregate references ``driver_id`` and ``vehicle_id`` must
    each be a member of the parent permit's ``authorized_driver_ids``
    and ``authorized_vehicle_ids`` lists respectively, and the live
    state of each (driver's ``hazmat_endorsement_status == VALID``,
    vehicle's ``latest_inspection_outcome == PASSED`` with
    ``valid_until`` covering the trip's scheduled arrival) is re-checked
    at the trip-create moment.

    The two scheduled timestamps satisfy the strict-greater-than-now
    rule on ``scheduled_departure_at`` and the strict-less-than-arrival
    rule between the two so the planned duration is positive.  The
    scheduled-window must lie inside the parent permit's
    ``[valid_from, valid_until]`` closed-on-the-arrival-edge interval
    (the deliberate scaffold-internal interval-semantics asymmetry the
    PRD's §2.9 documents — the scheduled-arrival may touch the permit's
    expiry edge exactly).

    The ``cargo_hazard_class`` is the single-class string the cargo
    carries, which must be in the permit's ``hazard_classes``
    authorized array, in the assigned driver's ``endorsement_classes``,
    and in the assigned vehicle's ``hazard_classes_compatible``; the
    ``cargo_weight_kg`` is in ``[0, vehicle.max_payload_kg]``.
    """
    if cargo_hazard_class is None:
        cargo_hazard_class = CANONICAL_CARGO_HAZARD_CLASS
    defaults: Dict[str, Any] = {
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "cargo_description": "Bulk fuel transport — JET-A jet fuel.",
        "cargo_hazard_class": cargo_hazard_class,
        "cargo_weight_kg": int(cargo_weight_kg),
        "scheduled_departure_at": scheduled_departure_at,
        "scheduled_arrival_at": scheduled_arrival_at,
    }
    return _apply_overrides(defaults, overrides)


def depart_trip_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/trips/{trip_id}/depart``.  Empty by
    default; the optional ``version`` engages the OCC check, the
    optional ``depart_note`` adds an audit-trail comment."""
    return _apply_overrides({}, overrides)


def arrive_trip_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/trips/{trip_id}/arrive``.  Empty by
    default; the optional ``arrive_note`` and ``delivery_attestation``
    free-text strings are audit-trail-only.  The handler sets the
    ``actual_arrival_at`` field to the current logical-clock value."""
    return _apply_overrides({}, overrides)


def abort_trip_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/trips/{trip_id}/abort``.

    The required ``reason_note`` 1-to-500-character cause is the
    operator's stated reason for the abort.  The ``abort_reason`` on
    the on-disk row is the enum value ``OPERATOR_ABORT`` for this
    operator-initiated branch of the abort fork; the two cascade
    branches' enum values are written by the server-internal
    parent-permit-transition side-effects, not by this endpoint.
    """
    defaults: Dict[str, Any] = {
        "reason_note": "Operator-initiated abort — cargo unavailable.",
    }
    return _apply_overrides(defaults, overrides)


# ─── GPS-stream ────────────────────────────────────────────────────────


def create_gps_report_payload(
    reported_at: str,
    lat: float = CANONICAL_ON_ROUTE_LAT,
    lon: float = CANONICAL_ON_ROUTE_LON,
    speed_kph: float = 60.0,
    heading_deg: float = 90.0,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for ``POST /v1/trips/{trip_id}/gps-reports``.

    The position-and-time quartet of fields covers the on-board GPS
    unit's wall-clock-from-the-satellite timestamp ``reported_at``,
    the WGS-84-decimal-degree-range ``lat`` and ``lon`` pair, the
    non-negative ``speed_kph`` float, and the diagnostic
    ``heading_deg`` float in the inclusive degree range
    ``[0, 360]``.  The optional ``Idempotency-Key`` HTTP header is
    handled by the ``api_client.create_gps_report`` wrapper rather than
    appearing in the JSON body.

    The default ``speed_kph`` of 60.0 is strictly less than
    ``MAX_HAZMAT_SPEED_KPH`` (80.0), so the speed-violation classifier
    flag is false on the default sample.  The default ``(lat, lon)``
    is exactly the first waypoint of ``CANONICAL_POLYLINE`` so the
    perpendicular distance to the polyline is zero metres and the
    off-route classifier flag is also false.  Tests that want the
    sample to fire one or both violation flags override the relevant
    field — ``speed_kph=MAX_HAZMAT_SPEED_KPH + 1.0`` for the speed
    violation, ``lat=CANONICAL_OFF_ROUTE_LAT, lon=CANONICAL_OFF_ROUTE_LON``
    for the off-route violation.
    """
    # Sanity: the default speed is below the limit so the factory's
    # canonical sample is a clean one.
    assert 0.0 <= speed_kph and speed_kph <= MAX_HAZMAT_SPEED_KPH * 2.0, (
        f"speed_kph={speed_kph} is outside the test-sanity range"
    )
    defaults: Dict[str, Any] = {
        "reported_at": reported_at,
        "lat": float(lat),
        "lon": float(lon),
        "speed_kph": float(speed_kph),
        "heading_deg": float(heading_deg),
    }
    return _apply_overrides(defaults, overrides)


# ─── Penalty ───────────────────────────────────────────────────────────


def create_penalty_payload(
    subject_type: str,
    subject_id: str,
    observed_at: str,
    points_value: int = 5,
    reason_note: str = "Manual penalty issued by regulator on observation.",
    trip_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Body for ``POST /v1/penalties`` — the regulator's manual-penalty
    issuance.

    The ``subject_type`` is one of the three values in the
    ``PenaltySubjectType`` enum; the ``subject_id`` resolves to a row
    in the corresponding entity table (the existence-tier check fires
    ``ERR_DRIVER_NOT_FOUND``, ``ERR_COMPANY_NOT_FOUND``, or
    ``ERR_VEHICLE_NOT_FOUND`` discriminated by the ``subject_type``
    value).  The ``points_value`` integer is in the inclusive range
    ``[MANUAL_PENALTY_POINTS_MIN, MANUAL_PENALTY_POINTS_MAX]``, which
    is ``[1, 50]`` per the PRD's §2.8 manual-penalty-points-range
    constant pair.  The ``observed_at`` ISO-8601 UTC timestamp is the
    wall-clock moment of the underlying observation (which the
    appeal-window's closed-right boundary anchors against, not the
    server-side ``created_at`` insert-moment).

    The optional ``trip_id`` foreign key associates a trip-contextual
    manual penalty with the underlying trip for the audit trail's
    cross-reference; absent ``trip_id`` leaves the on-disk field
    null.  The required ``reason_note`` is the regulator's free-text
    cause string.

    The ``source`` field on the resulting row is the server-set value
    ``MANUAL_REGULATOR`` (the ``PenaltySource`` enum value
    distinguishing manual-from-auto rows); the auto-Penalty rows the
    GPS-ingest side-effect inserts carry the
    ``GPS_VIOLATION_SPEED`` or ``GPS_VIOLATION_OFF_ROUTE`` values
    of the same enum.
    """
    assert subject_type in {
        PenaltySubjectType.DRIVER.value,
        PenaltySubjectType.COMPANY.value,
        PenaltySubjectType.VEHICLE.value,
    }, f"invalid subject_type {subject_type!r}"
    assert MANUAL_PENALTY_POINTS_MIN <= points_value <= MANUAL_PENALTY_POINTS_MAX, (
        f"points_value {points_value} outside the test-sanity range "
        f"[{MANUAL_PENALTY_POINTS_MIN}, {MANUAL_PENALTY_POINTS_MAX}]"
    )
    defaults: Dict[str, Any] = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "points_value": int(points_value),
        "observed_at": observed_at,
        "reason_note": reason_note,
    }
    if trip_id is not None:
        defaults["trip_id"] = trip_id
    return _apply_overrides(defaults, overrides)


def uphold_penalty_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for ``POST /v1/penalties/{penalty_id}/uphold``.

    The required ``uphold_reason`` 1-to-500-character regulator's
    decision-narrative is the audit-trail field the
    ``"UPHELD-ON-APPEAL: "`` prefix-marker on the on-disk
    ``reason_note`` is composed from.  The ``Penalty`` entity has no
    ``version`` field (the common-fields-false append-only convention),
    so the OCC mechanism doesn't apply here — the source-state-must-
    be-``ACTIVE`` guard alone resolves the concurrent-uphold race.
    """
    defaults: Dict[str, Any] = {
        "uphold_reason": "Appeal granted; underlying observation contested.",
    }
    return _apply_overrides(defaults, overrides)


__all__ = [
    "create_company_payload",
    "submit_company_payload",
    "approve_company_payload",
    "revoke_company_payload",
    "create_driver_payload",
    "driver_attestation_payload",
    "driver_revoke_payload",
    "create_vehicle_payload",
    "create_inspection_payload",
    "create_route_payload",
    "reject_route_payload",
    "create_permit_payload",
    "issue_permit_payload",
    "verify_compliance_payload",
    "renew_permit_payload",
    "void_issue_payload",
    "create_trip_payload",
    "depart_trip_payload",
    "arrive_trip_payload",
    "abort_trip_payload",
    "create_gps_report_payload",
    "create_penalty_payload",
    "uphold_penalty_payload",
]
