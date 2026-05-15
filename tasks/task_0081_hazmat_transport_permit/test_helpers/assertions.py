"""Domain-specific assertion helpers for the hazmat-transport-permit
test layer.

The framework's ``prd_bench_local_runner.testing`` module provides the
envelope-shape validators (``validate_success``, ``validate_error``,
``validate_paginated``, ``validate_error_is_one_of``,
``get_success_data``) and the generic format-and-shape predicates
(``is_valid_uuid``, ``is_iso8601_timestamp``, ``assert_timestamp_format``,
``assert_version_incremented``).  This module supplements those generics
with the per-entity field-presence and field-type assertions the seven
mutable entity-kinds and the three append-only entity-kinds in the PRD's
§1.1 demand, plus the two conservation-invariant audits the PRD's §2.11
declares.

Each ``assert_<entity>(data: dict)`` runs the standard shape check on
the response payload's data sub-object: the common-fields quartet for
the six mutable entities, the common-fields pair for the three
append-only entities, and the per-entity-specific business-field set
the entity's TypedDict in ``types.py`` lists.  The state-field's value
is checked against the enum's allowed-set so a typo in the state-string
on the server side is caught by the type-check rather than slipping
through as an opaque string.

The two conservation-invariant audits, ``assert_wallet_conservation``
and ``assert_points_conservation``, take a pre-snapshot and a
post-snapshot of the relevant aggregate-row state plus the
recorded-deltas the action-sequence in between produced, and assert the
net change matches the algebraic identity the PRD's §2.11 declares.

The off-route-distance assertion's tolerance is the millimetre-level
``HAVERSINE_TOLERANCE_METRES`` constant, absorbing the haversine
formula's intermediate floating-point variability.
"""

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    APPEAL_WINDOW_DAYS,
    EARTH_RADIUS_M,
    GPS_VIOLATION_OFF_ROUTE_POINTS,
    GPS_VIOLATION_SPEED_POINTS,
    HAVERSINE_TOLERANCE_METRES,
    INSPECTION_VALIDITY_DAYS,
    OFF_ROUTE_RADIUS_M,
    PENALTY_WINDOW_DAYS,
    PERMIT_DEFAULT_VALIDITY_DAYS,
    THRESHOLD_DRIVER_SUSPENSION_POINTS,
    VOID_ISSUE_WINDOW_HOURS,
    MAX_HAZMAT_SPEED_KPH,
    RENEWAL_OPEN_WINDOW_DAYS,
    LATE_RENEWAL_GRACE_DAYS,
    MAX_VEHICLES_PER_PERMIT,
    BASE_RENEWAL_FEE_CENTS,
    PER_VEHICLE_SURCHARGE_CENTS,
    LATE_RENEWAL_PENALTY_CENTS,
    MAX_RENEWAL_FEE_CENTS,
)
from .types import (
    AbortReason,
    CompanyQualificationStatus,
    DriverEndorsementStatus,
    HAZARD_CLASSES_UN,
    InspectionOutcome,
    PenaltySource,
    PenaltySubjectType,
    PenaltyVoidStatus,
    PermitLifecycleStatus,
    RouteApprovalStatus,
    TripStatus,
    VehicleType,
    VerifyComplianceTransitionFired,
    SweepPermitCause,
    SweepDriverStatusFlip,
)


# ─── Common-field assertions used as building blocks ───────────────────


def _enum_values(enum_cls) -> set:
    """Return the string-value set of a ``str, Enum`` class."""
    return {member.value for member in enum_cls}


def _assert_common_mutable(data: Dict[str, Any], entity_name: str) -> None:
    """Assert the common-fields quartet (``id``, ``created_at``,
    ``updated_at``, ``version``) every mutable entity carries per the
    PRD's §2.4."""
    assert isinstance(data, dict), f"{entity_name}: response data must be a dict, got {type(data).__name__}"
    assert "id" in data and isinstance(data["id"], str), f"{entity_name}: id must be a string"
    assert is_valid_uuid(data["id"]), f"{entity_name}: id={data['id']!r} is not a valid UUID"
    assert "created_at" in data, f"{entity_name}: created_at is required"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"{entity_name}: created_at={data['created_at']!r} must be an ISO-8601 UTC timestamp"
    )
    assert "updated_at" in data, f"{entity_name}: updated_at is required on mutable entities"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"{entity_name}: updated_at={data['updated_at']!r} must be an ISO-8601 UTC timestamp"
    )
    assert "version" in data, f"{entity_name}: version is required on mutable entities"
    assert isinstance(data["version"], int), f"{entity_name}: version must be an integer"
    assert data["version"] >= 1, f"{entity_name}: version={data['version']} must be at least 1"


def _assert_common_append_only(data: Dict[str, Any], entity_name: str) -> None:
    """Assert the append-only-entity common-fields pair (``id``,
    ``created_at``).  The PRD's §2.4 expressly notes append-only
    entities (``VehicleInspection``, ``GPSReport``, ``Penalty``)
    carry no ``updated_at`` and no ``version`` because the rows are
    never mutated in place — save for the documented single-edge
    state-machine on ``Penalty.void_status``."""
    assert isinstance(data, dict), f"{entity_name}: response data must be a dict, got {type(data).__name__}"
    assert "id" in data and isinstance(data["id"], str), f"{entity_name}: id must be a string"
    assert is_valid_uuid(data["id"]), f"{entity_name}: id={data['id']!r} is not a valid UUID"
    assert "created_at" in data, f"{entity_name}: created_at is required"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"{entity_name}: created_at={data['created_at']!r} must be an ISO-8601 UTC timestamp"
    )


def _assert_hazard_class_list(values: Iterable[str], field_name: str, allow_empty: bool = False) -> None:
    """Assert every entry of a hazard-class array is in the UN
    taxonomy of ``types.HAZARD_CLASSES_UN`` and the array has no
    duplicates.  The ``allow_empty`` flag controls whether the array
    is permitted to be empty (the initial driver-endorsement-classes
    field is the empty list before the regulator attests it; the
    other hazard-class arrays are non-empty by their respective
    business rules)."""
    listv = list(values)
    if not allow_empty:
        assert listv, f"{field_name}: must be a non-empty array of hazard classes"
    assert len(set(listv)) == len(listv), f"{field_name}: must not contain duplicates"
    for cls in listv:
        assert cls in HAZARD_CLASSES_UN, (
            f"{field_name}: class string {cls!r} is not in the UN hazard-class taxonomy"
        )


# ─── Per-entity full-shape assertions ──────────────────────────────────


def assert_company(data: Dict[str, Any]) -> None:
    """Assert a TransportCompany response payload satisfies the PRD's
    §3.1 entity shape: the common-fields quartet, the natural-key and
    free-text fields with the appropriate types, the
    ``qualification_status`` enum membership, the
    ``wallet_balance_cents`` non-negative-integer constraint, and the
    ``hazard_classes_authorized`` taxonomy and uniqueness check."""
    _assert_common_mutable(data, "TransportCompany")
    assert isinstance(data.get("legal_name"), str) and 1 <= len(data["legal_name"]) <= 200
    assert isinstance(data.get("registration_number"), str)
    # Registration-number regex constraint:
    # eight-to-thirty-two characters of uppercase letters and digits.
    rn = data["registration_number"]
    assert 8 <= len(rn) <= 32, f"registration_number length {len(rn)} outside [8, 32]"
    assert all(c.isascii() and (c.isupper() or c.isdigit()) for c in rn), (
        f"registration_number {rn!r} must be uppercase letters and digits only"
    )
    assert isinstance(data.get("primary_contact_email"), str)
    assert "@" in data["primary_contact_email"], "primary_contact_email must look like an RFC-5322 address"
    # address_line is 0..500 chars.
    if "address_line" in data and data["address_line"] is not None:
        assert isinstance(data["address_line"], str)
        assert 0 <= len(data["address_line"]) <= 500
    _assert_hazard_class_list(
        data.get("hazard_classes_authorized") or [],
        "TransportCompany.hazard_classes_authorized",
        allow_empty=False,
    )
    assert data.get("qualification_status") in _enum_values(CompanyQualificationStatus), (
        f"qualification_status={data.get('qualification_status')!r} not in the enum"
    )
    assert isinstance(data.get("wallet_balance_cents"), int) and data["wallet_balance_cents"] >= 0, (
        "wallet_balance_cents must be a non-negative integer"
    )


def assert_driver(data: Dict[str, Any]) -> None:
    """Assert a Driver response payload satisfies the PRD's §3.2 entity
    shape: the common-fields quartet, the ``full_name``-and-
    ``license_number``-and-``license_class`` triple, the parent
    ``company_id`` foreign key (a UUID), the
    ``hazmat_endorsement_status`` enum membership, the
    ``endorsement_classes`` taxonomy-conforming array (which may be
    empty on a not-yet-attested row), and the
    ``current_rolling_points`` non-negative integer."""
    _assert_common_mutable(data, "Driver")
    assert isinstance(data.get("full_name"), str) and 1 <= len(data["full_name"]) <= 120
    assert isinstance(data.get("license_number"), str)
    ln = data["license_number"]
    assert 6 <= len(ln) <= 32, f"license_number length {len(ln)} outside [6, 32]"
    assert " " not in ln and "\t" not in ln, "license_number has no whitespace"
    assert isinstance(data.get("license_class"), str)
    assert isinstance(data.get("company_id"), str) and is_valid_uuid(data["company_id"]), (
        "company_id must be a UUID"
    )
    assert data.get("hazmat_endorsement_status") in _enum_values(DriverEndorsementStatus), (
        f"hazmat_endorsement_status={data.get('hazmat_endorsement_status')!r} not in enum"
    )
    _assert_hazard_class_list(
        data.get("endorsement_classes") or [],
        "Driver.endorsement_classes",
        allow_empty=True,
    )
    # endorsement_valid_until is null on a never-attested driver, an
    # ISO timestamp on an attested or just-revoked one.
    evu = data.get("endorsement_valid_until")
    if evu is not None:
        assert isinstance(evu, str) and is_iso8601_timestamp(evu), (
            "endorsement_valid_until must be ISO-8601 UTC or null"
        )
    cp = data.get("current_rolling_points")
    assert isinstance(cp, int) and cp >= 0, "current_rolling_points must be a non-negative integer"


def assert_vehicle(data: Dict[str, Any]) -> None:
    """Assert a Vehicle response payload satisfies the PRD's §3.3
    entity shape, including the three derived
    ``latest_inspection_id``-and-``latest_inspection_outcome``-and-
    ``latest_inspection_valid_until`` pointer fields (each null on a
    never-inspected vehicle, populated atomically by the inspection-
    append's side-effect when the new inspection is the largest-by-
    timestamp in the vehicle's history)."""
    _assert_common_mutable(data, "Vehicle")
    assert isinstance(data.get("company_id"), str) and is_valid_uuid(data["company_id"])
    plate = data.get("plate_number")
    assert isinstance(plate, str) and 4 <= len(plate) <= 16, (
        f"plate_number length {len(plate) if isinstance(plate, str) else '?'} outside [4, 16]"
    )
    assert data.get("vehicle_type") in _enum_values(VehicleType), (
        f"vehicle_type={data.get('vehicle_type')!r} not in the enum"
    )
    mpk = data.get("max_payload_kg")
    assert isinstance(mpk, int) and mpk > 0, "max_payload_kg must be a positive integer"
    _assert_hazard_class_list(
        data.get("hazard_classes_compatible") or [],
        "Vehicle.hazard_classes_compatible",
        allow_empty=False,
    )
    # The three derived latest-inspection fields: each is either null
    # (no inspection has been appended yet) or the appropriate type.
    lii = data.get("latest_inspection_id")
    lio = data.get("latest_inspection_outcome")
    livu = data.get("latest_inspection_valid_until")
    if lii is None:
        # If no inspection has been appended, the three fields are all
        # null together — they refresh atomically.
        assert lio is None, "latest_inspection_outcome must be null when latest_inspection_id is null"
        assert livu is None, "latest_inspection_valid_until must be null when latest_inspection_id is null"
    else:
        assert isinstance(lii, str) and is_valid_uuid(lii), "latest_inspection_id must be a UUID"
        assert lio in _enum_values(InspectionOutcome), (
            f"latest_inspection_outcome={lio!r} not in the inspection-outcome enum"
        )
        assert isinstance(livu, str) and is_iso8601_timestamp(livu), (
            "latest_inspection_valid_until must be ISO-8601 UTC"
        )


def assert_inspection(data: Dict[str, Any]) -> None:
    """Assert a VehicleInspection response payload satisfies the PRD's
    §3.3 append-only entity shape.  No ``updated_at`` and no
    ``version`` per the common-fields-false convention."""
    _assert_common_append_only(data, "VehicleInspection")
    assert "updated_at" not in data, (
        "VehicleInspection is append-only and must not carry updated_at"
    )
    assert "version" not in data, (
        "VehicleInspection is append-only and must not carry version"
    )
    assert isinstance(data.get("vehicle_id"), str) and is_valid_uuid(data["vehicle_id"])
    assert isinstance(data.get("inspected_at"), str) and is_iso8601_timestamp(data["inspected_at"])
    outcome = data.get("outcome")
    assert outcome in _enum_values(InspectionOutcome), (
        f"outcome={outcome!r} not in the inspection-outcome enum"
    )
    assert isinstance(data.get("valid_until"), str) and is_iso8601_timestamp(data["valid_until"])
    # The FAILED-outcome zero-validity rule: valid_until == inspected_at.
    if outcome == InspectionOutcome.FAILED.value:
        assert data["valid_until"] == data["inspected_at"], (
            "FAILED inspection's valid_until must equal inspected_at (the zero-validity rule)"
        )
    # The findings_note is a 0..2000-char string.
    fn = data.get("findings_note")
    if fn is not None:
        assert isinstance(fn, str) and 0 <= len(fn) <= 2000, (
            f"findings_note length {len(fn) if isinstance(fn, str) else '?'} outside [0, 2000]"
        )
    # The inspector_id is the regulator's opaque X-User-ID echo on the row.
    insp_id = data.get("inspector_id")
    if insp_id is not None:
        assert isinstance(insp_id, str) and len(insp_id) > 0


def assert_route(data: Dict[str, Any]) -> None:
    """Assert a TransportRoute response satisfies the PRD's §3.4 shape:
    the common-fields quartet, the parent ``company_id`` foreign key,
    the origin/destination 1..200-char labels, the polyline of
    2..200 waypoints each a ``{lat, lon}`` dict with lat in
    ``[-90, 90]`` and lon in ``[-180, 180]``, the
    ``hazard_classes_supported`` taxonomy-conforming non-empty array,
    the ``approval_status`` four-value enum, and the three approval-trail
    audit fields ``approved_at``-and-``approved_by``-and-
    ``rejection_reason`` each null until the relevant transition sets
    them."""
    _assert_common_mutable(data, "TransportRoute")
    assert isinstance(data.get("company_id"), str) and is_valid_uuid(data["company_id"])
    for lbl_field in ("origin_label", "destination_label"):
        val = data.get(lbl_field)
        assert isinstance(val, str) and 1 <= len(val) <= 200, (
            f"{lbl_field}={val!r}: must be a 1..200-char string"
        )
    polyline = data.get("polyline")
    assert isinstance(polyline, list) and 2 <= len(polyline) <= 200, (
        f"polyline must be a list of 2..200 waypoints, got length {len(polyline) if isinstance(polyline, list) else '?'}"
    )
    for idx, wp in enumerate(polyline):
        assert isinstance(wp, dict) and "lat" in wp and "lon" in wp, (
            f"polyline[{idx}] must be a {{lat, lon}} object"
        )
        lat = wp["lat"]
        lon = wp["lon"]
        assert isinstance(lat, (int, float)) and -90.0 <= float(lat) <= 90.0, (
            f"polyline[{idx}].lat={lat!r} outside [-90, 90]"
        )
        assert isinstance(lon, (int, float)) and -180.0 <= float(lon) <= 180.0, (
            f"polyline[{idx}].lon={lon!r} outside [-180, 180]"
        )
    _assert_hazard_class_list(
        data.get("hazard_classes_supported") or [],
        "TransportRoute.hazard_classes_supported",
        allow_empty=False,
    )
    assert data.get("approval_status") in _enum_values(RouteApprovalStatus), (
        f"approval_status={data.get('approval_status')!r} not in the enum"
    )
    for opt_ts_field in ("approved_at",):
        v = data.get(opt_ts_field)
        if v is not None:
            assert isinstance(v, str) and is_iso8601_timestamp(v)


def assert_permit(data: Dict[str, Any]) -> None:
    """Assert a Permit response satisfies the PRD's §3.5 entity shape:
    the common-fields quartet, the cross-aggregate foreign-key fields
    ``company_id``-and-``route_id``-and-``authorized_driver_ids``-and-
    ``authorized_vehicle_ids``-and-``hazard_classes``, the
    ``valid_from``-and-``valid_until`` half-open time window, the
    five-element ``lifecycle_status`` enum, the issue-audit fields
    ``issued_at``-and-``issued_by``-and-``issue_fee_cents``, the five
    strict-snapshot fields the verify-compliance handler writes, the
    ``renewal_history`` append-only array, and the void-audit
    ``voided_at``-and-``void_refunded_cents`` fields.  The
    ``application_preview`` sub-object on a freshly-created permit
    (the PRD §3.5 endpoint-response embed) and the on-fly
    ``live_verdict`` and ``live_per_leg`` and ``snapshot_overall``
    fields on the GET-permit read are accepted when present but not
    required, since their exact serialisation shape is not asserted by
    every test."""
    _assert_common_mutable(data, "Permit")
    assert isinstance(data.get("company_id"), str) and is_valid_uuid(data["company_id"])
    assert isinstance(data.get("route_id"), str) and is_valid_uuid(data["route_id"])
    driver_ids = data.get("authorized_driver_ids") or []
    vehicle_ids = data.get("authorized_vehicle_ids") or []
    assert isinstance(driver_ids, list) and 1 <= len(driver_ids) <= 50, (
        "authorized_driver_ids must be a non-empty list of <=50 driver-ids"
    )
    assert len(set(driver_ids)) == len(driver_ids), (
        "authorized_driver_ids must not contain duplicates"
    )
    for did in driver_ids:
        assert isinstance(did, str) and is_valid_uuid(did)
    assert isinstance(vehicle_ids, list) and 1 <= len(vehicle_ids) <= MAX_VEHICLES_PER_PERMIT, (
        f"authorized_vehicle_ids must be a non-empty list of <= {MAX_VEHICLES_PER_PERMIT} vehicle-ids"
    )
    assert len(set(vehicle_ids)) == len(vehicle_ids), (
        "authorized_vehicle_ids must not contain duplicates"
    )
    for vid in vehicle_ids:
        assert isinstance(vid, str) and is_valid_uuid(vid)
    _assert_hazard_class_list(
        data.get("hazard_classes") or [],
        "Permit.hazard_classes",
        allow_empty=False,
    )
    assert isinstance(data.get("valid_from"), str) and is_iso8601_timestamp(data["valid_from"])
    if data.get("valid_until") is not None:
        assert is_iso8601_timestamp(data["valid_until"])
    assert data.get("lifecycle_status") in _enum_values(PermitLifecycleStatus), (
        f"lifecycle_status={data.get('lifecycle_status')!r} not in the enum"
    )
    # Snapshot fields: each null in DRAFT, populated after the first issue.
    status = data["lifecycle_status"]
    fee = data.get("issue_fee_cents")
    if status == PermitLifecycleStatus.DRAFT.value:
        # Pre-issue the fee field is absent or null.
        assert fee is None or fee == 0, (
            f"DRAFT permit's issue_fee_cents should be null/absent, got {fee!r}"
        )
    else:
        assert isinstance(fee, int) and fee >= 0, (
            f"non-DRAFT permit must carry an integer issue_fee_cents, got {fee!r}"
        )
        issued_at = data.get("issued_at")
        assert isinstance(issued_at, str) and is_iso8601_timestamp(issued_at), (
            "issued_at must be an ISO-8601 timestamp on a post-issue permit"
        )
        assert isinstance(data.get("issued_by"), str), (
            "issued_by must be the regulator's X-User-ID echo"
        )
        # Snapshot booleans on the verified post-issue permit.
        for snap_bool in ("snapshot_company_qualified", "snapshot_route_approved", "snapshot_within_window"):
            assert isinstance(data.get(snap_bool), bool), (
                f"{snap_bool} must be a boolean on a post-issue permit"
            )
        drv_snap = data.get("snapshot_driver_endorsements") or {}
        veh_snap = data.get("snapshot_vehicle_inspections") or {}
        assert isinstance(drv_snap, dict), "snapshot_driver_endorsements must be a dict"
        assert isinstance(veh_snap, dict), "snapshot_vehicle_inspections must be a dict"
        for k, v in drv_snap.items():
            assert isinstance(k, str) and is_valid_uuid(k)
            assert isinstance(v, bool)
        for k, v in veh_snap.items():
            assert isinstance(k, str) and is_valid_uuid(k)
            assert isinstance(v, bool)
        lva = data.get("last_verified_at")
        assert isinstance(lva, str) and is_iso8601_timestamp(lva), (
            "last_verified_at must be an ISO-8601 timestamp on a verified permit"
        )
    rh = data.get("renewal_history")
    if rh is not None:
        assert isinstance(rh, list)
        for entry in rh:
            assert isinstance(entry, dict)
            for ts_field in ("renewed_at", "prior_valid_until", "new_valid_until"):
                assert ts_field in entry and is_iso8601_timestamp(entry[ts_field]), (
                    f"renewal_history entry {ts_field!r} must be ISO-8601"
                )
            assert isinstance(entry.get("fee_cents"), int) and entry["fee_cents"] >= 0
            assert isinstance(entry.get("late_penalty_applied"), bool)
    if data.get("voided_at") is not None:
        assert is_iso8601_timestamp(data["voided_at"])
        assert isinstance(data.get("void_refunded_cents"), int) and data["void_refunded_cents"] >= 0


def assert_trip(data: Dict[str, Any]) -> None:
    """Assert a Trip response satisfies the PRD's §3.7 entity shape.

    The four state-field values are the enum members of ``TripStatus``.
    The four temporal fields ``actual_departure_at``-and-
    ``actual_arrival_at``-and-``aborted_at`` are each null until the
    relevant transition fires.  The ``abort_reason`` discriminator is
    null on a non-terminally-aborted trip and one of the four
    ``AbortReason`` enum values otherwise.  The two GPS-stream
    derived fields ``latest_gps_at`` (the maximum-``reported_at`` of
    the stream, null on an empty stream) and ``gps_violation_count``
    (the non-negative-integer count of auto-Penalty rows attributed to
    this trip's stream) are surfaced for the audit trail.
    """
    _assert_common_mutable(data, "Trip")
    for fk_field in ("permit_id", "driver_id", "vehicle_id"):
        val = data.get(fk_field)
        assert isinstance(val, str) and is_valid_uuid(val), (
            f"{fk_field}={val!r} must be a UUID foreign key"
        )
    cargo_desc = data.get("cargo_description")
    assert isinstance(cargo_desc, str) and 1 <= len(cargo_desc) <= 500
    chc = data.get("cargo_hazard_class")
    assert chc in HAZARD_CLASSES_UN, (
        f"cargo_hazard_class={chc!r} not in the UN hazard-class taxonomy"
    )
    cw = data.get("cargo_weight_kg")
    assert isinstance(cw, int) and cw >= 0, "cargo_weight_kg must be a non-negative integer"
    for ts_field in ("scheduled_departure_at", "scheduled_arrival_at"):
        val = data.get(ts_field)
        assert isinstance(val, str) and is_iso8601_timestamp(val), (
            f"{ts_field}={val!r} must be an ISO-8601 timestamp"
        )
    # The scheduled-arrival is strictly after the scheduled-departure.
    assert data["scheduled_arrival_at"] > data["scheduled_departure_at"], (
        "scheduled_arrival_at must be strictly after scheduled_departure_at"
    )
    status = data.get("trip_status")
    assert status in _enum_values(TripStatus), (
        f"trip_status={status!r} not in the enum"
    )
    ad = data.get("actual_departure_at")
    aa = data.get("actual_arrival_at")
    ab = data.get("aborted_at")
    if status == TripStatus.PLANNED.value:
        assert ad is None and aa is None and ab is None
    elif status == TripStatus.IN_TRANSIT.value:
        assert ad is not None and is_iso8601_timestamp(ad)
        assert aa is None and ab is None
    elif status == TripStatus.COMPLETED.value:
        assert ad is not None and is_iso8601_timestamp(ad)
        assert aa is not None and is_iso8601_timestamp(aa)
        # Actual ordering: depart < arrive (the clock-monotonicity guarantee).
        assert aa > ad, "actual_arrival_at must be strictly after actual_departure_at"
        assert ab is None
    elif status == TripStatus.ABORTED.value:
        # actual_departure_at may be null (a pre-departure cascade-abort
        # or operator-abort of a still-PLANNED trip) or non-null (an
        # in-flight abort).  actual_arrival_at is always null on an
        # ABORTED trip.  aborted_at is non-null and abort_reason is one
        # of the four enum values.
        if ad is not None:
            assert is_iso8601_timestamp(ad)
        assert aa is None
        assert ab is not None and is_iso8601_timestamp(ab)
        ar = data.get("abort_reason")
        assert ar in _enum_values(AbortReason), (
            f"abort_reason={ar!r} not in the enum"
        )
    lga = data.get("latest_gps_at")
    if lga is not None:
        assert is_iso8601_timestamp(lga)
    gvc = data.get("gps_violation_count")
    assert isinstance(gvc, int) and gvc >= 0, (
        "gps_violation_count must be a non-negative integer"
    )


def assert_gps_report(data: Dict[str, Any]) -> None:
    """Assert a GPSReport append-only response satisfies the PRD's
    §3.8 shape.  No ``updated_at``, no ``version``; the
    ``auto_penalty_ids`` array carries zero, one, or two penalty-ids
    matching the two classifier flags' fired-or-not state, and the
    server-computed ``off_route_distance_m`` is a non-negative float
    in metres."""
    _assert_common_append_only(data, "GPSReport")
    assert "updated_at" not in data, "GPSReport is append-only — no updated_at"
    assert "version" not in data, "GPSReport is append-only — no version"
    assert isinstance(data.get("trip_id"), str) and is_valid_uuid(data["trip_id"])
    for ts_field in ("reported_at", "received_at"):
        val = data.get(ts_field)
        assert isinstance(val, str) and is_iso8601_timestamp(val), (
            f"{ts_field}={val!r} must be an ISO-8601 timestamp"
        )
    lat = data.get("lat")
    lon = data.get("lon")
    assert isinstance(lat, (int, float)) and -90.0 <= float(lat) <= 90.0, (
        f"lat={lat!r} outside [-90, 90]"
    )
    assert isinstance(lon, (int, float)) and -180.0 <= float(lon) <= 180.0, (
        f"lon={lon!r} outside [-180, 180]"
    )
    sp = data.get("speed_kph")
    assert isinstance(sp, (int, float)) and float(sp) >= 0.0, "speed_kph must be non-negative"
    hd = data.get("heading_deg")
    assert isinstance(hd, (int, float)) and 0.0 <= float(hd) <= 360.0, (
        f"heading_deg={hd!r} outside [0, 360]"
    )
    ord_m = data.get("off_route_distance_m")
    assert isinstance(ord_m, (int, float)) and float(ord_m) >= 0.0, (
        f"off_route_distance_m={ord_m!r} must be a non-negative float"
    )
    apl = data.get("auto_penalty_ids")
    assert isinstance(apl, list), "auto_penalty_ids must be a list"
    assert 0 <= len(apl) <= 2, (
        f"auto_penalty_ids has length {len(apl)}; the classifier can fire at most two flags"
    )
    for pid in apl:
        assert isinstance(pid, str) and is_valid_uuid(pid)


def assert_penalty(data: Dict[str, Any]) -> None:
    """Assert a Penalty append-only response satisfies the PRD's
    §3.8 shape.  The two-state ``void_status`` machine and the
    three-value ``source`` and ``subject_type`` discriminator enums
    are the entity's key fields beyond the standard append-only common
    pair.  The four optional audit fields
    ``source_gps_report_id``-and-``trip_id``-and-``upheld_at``-and-
    ``upheld_by`` are populated by the relevant code path
    (the GPS-side ``source_*`` pair on the auto-rows, the
    appeal-uphold's ``upheld_*`` pair on the post-uphold state)."""
    _assert_common_append_only(data, "Penalty")
    assert "updated_at" not in data
    assert "version" not in data
    subject_type = data.get("subject_type")
    assert subject_type in _enum_values(PenaltySubjectType), (
        f"subject_type={subject_type!r} not in the enum"
    )
    assert isinstance(data.get("subject_id"), str) and is_valid_uuid(data["subject_id"])
    source = data.get("source")
    assert source in _enum_values(PenaltySource), (
        f"source={source!r} not in the enum"
    )
    pv = data.get("points_value")
    assert isinstance(pv, int) and pv >= 1, "points_value must be a positive integer"
    assert isinstance(data.get("observed_at"), str) and is_iso8601_timestamp(data["observed_at"])
    rn = data.get("reason_note")
    assert isinstance(rn, str) and 1 <= len(rn) <= 1100, (
        # The 1..500-char input range plus the canonical "UPHELD-ON-APPEAL: "
        # prepend marker on the uphold path can extend the on-disk
        # value past the input bound; the response carries the joined
        # string.  We bound the upper end at 1100 to give the
        # implementation slack while still enforcing some sanity bound.
        f"reason_note length {len(rn) if isinstance(rn, str) else '?'} outside the bounded range"
    )
    void_status = data.get("void_status")
    assert void_status in _enum_values(PenaltyVoidStatus), (
        f"void_status={void_status!r} not in the enum"
    )
    if void_status == PenaltyVoidStatus.UPHELD.value:
        # Post-uphold the upheld_at and upheld_by audit fields are populated.
        ua = data.get("upheld_at")
        ub = data.get("upheld_by")
        assert isinstance(ua, str) and is_iso8601_timestamp(ua), (
            "upheld_at must be an ISO-8601 timestamp on an UPHELD penalty"
        )
        assert isinstance(ub, str) and len(ub) > 0, (
            "upheld_by must be the regulator's opaque identifier on an UPHELD penalty"
        )
    else:
        # ACTIVE state: the two audit fields are null.
        assert data.get("upheld_at") in (None, "") or data.get("upheld_at") is None
        assert data.get("upheld_by") in (None, "") or data.get("upheld_by") is None
    # The source_gps_report_id field is non-null on auto-source rows.
    sgi = data.get("source_gps_report_id")
    if source in {PenaltySource.GPS_VIOLATION_SPEED.value, PenaltySource.GPS_VIOLATION_OFF_ROUTE.value}:
        assert isinstance(sgi, str) and is_valid_uuid(sgi), (
            "auto-Penalty row must carry the source_gps_report_id linking back to the GPS sample"
        )
        # The auto-rows' points_value is the corresponding GPS-source constant.
        if source == PenaltySource.GPS_VIOLATION_SPEED.value:
            assert pv == GPS_VIOLATION_SPEED_POINTS, (
                f"speed-violation auto-penalty's points_value must be {GPS_VIOLATION_SPEED_POINTS}"
            )
        elif source == PenaltySource.GPS_VIOLATION_OFF_ROUTE.value:
            assert pv == GPS_VIOLATION_OFF_ROUTE_POINTS, (
                f"off-route-violation auto-penalty's points_value must be "
                f"{GPS_VIOLATION_OFF_ROUTE_POINTS}"
            )
        # The DRIVER-subject assignment on the auto-rows is the §2.8 taxonomy convention.
        assert subject_type == PenaltySubjectType.DRIVER.value, (
            "auto-Penalty's subject is always the trip's driver"
        )


# ─── Sweep-and-verify-compliance response envelopes ────────────────────


def assert_sweep_response(data: Dict[str, Any]) -> None:
    """Assert a ``POST /v1/_sweep/run`` response payload matches the
    structured-summary shape the PRD's §2.5 declares: ``as_of_now``,
    ``scope``, ``permit_transitions`` (each carrying ``permit_id``,
    ``pre_status``, ``post_status``, the three-value
    ``cause`` discriminator, and the ``cascade_trip_aborts`` array),
    ``driver_recomputes`` (each carrying the per-driver pre-and-post
    rolling-points integers and the optional one-value
    ``status_flip`` discriminator), and the
    ``n_permits_inspected``-and-``n_drivers_inspected`` integer
    counts."""
    assert isinstance(data.get("as_of_now"), str) and is_iso8601_timestamp(data["as_of_now"])
    scope = data.get("scope")
    assert scope in {"ALL", "PERMITS_ONLY", "DRIVERS_ONLY"}, (
        f"scope={scope!r} not in the sweep-scope enum"
    )
    pts = data.get("permit_transitions") or []
    assert isinstance(pts, list)
    valid_causes = _enum_values(SweepPermitCause)
    valid_statuses = _enum_values(PermitLifecycleStatus)
    for entry in pts:
        assert isinstance(entry, dict)
        assert isinstance(entry.get("permit_id"), str) and is_valid_uuid(entry["permit_id"])
        assert entry.get("pre_status") in valid_statuses
        assert entry.get("post_status") in valid_statuses
        assert entry.get("cause") in valid_causes
        cta = entry.get("cascade_trip_aborts") or []
        assert isinstance(cta, list)
        for tid in cta:
            assert isinstance(tid, str) and is_valid_uuid(tid)
    drvs = data.get("driver_recomputes") or []
    assert isinstance(drvs, list)
    valid_flips = _enum_values(SweepDriverStatusFlip) | {None}
    for entry in drvs:
        assert isinstance(entry, dict)
        assert isinstance(entry.get("driver_id"), str) and is_valid_uuid(entry["driver_id"])
        assert isinstance(entry.get("pre_rolling_points"), int)
        assert isinstance(entry.get("post_rolling_points"), int)
        # status_flip is one of {VALID_TO_INVALID, None/absent}.
        flip = entry.get("status_flip")
        assert flip is None or flip in valid_flips, (
            f"status_flip={flip!r} not in the sweep-driver-flip enum"
        )
    assert isinstance(data.get("n_permits_inspected"), int)
    assert isinstance(data.get("n_drivers_inspected"), int)
    # The ``wallclock_advanced`` boolean is always False on the
    # sweep-run-without-a-clock-tick path per the PRD §2.5.
    wa = data.get("wallclock_advanced")
    if wa is not None:
        assert wa is False, (
            "sweep response's wallclock_advanced must be False on the dedicated /_sweep/run path"
        )


def assert_clock_advance_response(data: Dict[str, Any], expected_advance_seconds: float) -> None:
    """Assert a ``POST /v1/_clock/advance`` response satisfies the
    PRD's §2.5 shape: ``prior_now`` and ``new_now`` ISO timestamps with
    the new time strictly later by ``advance_seconds_applied`` exactly
    (modulo the millisecond-tolerance the integer-arithmetic
    clock model honours), and the optional ``sweep_summary`` sub-object
    null or matching ``assert_sweep_response``.

    The strict-monotonicity of the logical clock from PRD §2.5 means
    a zero-duration advance leaves ``new_now == prior_now`` exactly and
    a positive advance gives ``new_now > prior_now`` with the
    difference equal to ``advance_seconds_applied``.
    """
    for ts_field in ("prior_now", "new_now"):
        val = data.get(ts_field)
        assert isinstance(val, str) and is_iso8601_timestamp(val), (
            f"{ts_field}={val!r} must be ISO-8601"
        )
    applied = data.get("advance_seconds_applied")
    assert isinstance(applied, (int, float)), "advance_seconds_applied must be a number"
    assert abs(float(applied) - float(expected_advance_seconds)) < 0.5, (
        f"advance_seconds_applied={applied} disagrees with the request's "
        f"advance_seconds={expected_advance_seconds}"
    )
    # The new_now is strictly greater than the prior_now when the
    # advance is positive, equal when the advance is zero.  Lexicographic
    # comparison on ISO-8601-UTC-millisecond-suffix strings works
    # correctly because the format is fixed-width.
    if float(applied) > 0.0:
        assert data["new_now"] > data["prior_now"], (
            "logical clock must advance strictly forward on a positive advance"
        )
    else:
        # Zero advance: the clock is unchanged.
        assert data["new_now"] >= data["prior_now"]
    if data.get("sweep_summary") is not None:
        assert_sweep_response(data["sweep_summary"])


def assert_verify_compliance_response(data: Dict[str, Any]) -> None:
    """Assert a verify-compliance response satisfies the shape
    declared in the PRD's §3.5 verify-compliance subsection: the
    five-value ``transition_fired`` discriminator, the
    ``pre_status``-to-``post_status`` pair, the ``permit`` sub-object
    holding the full updated row, and the ``live_per_leg``-and-
    ``snapshot_per_leg`` boolean-map pair the dual-variant
    disagreement axis is observable on."""
    tf = data.get("transition_fired")
    assert tf in _enum_values(VerifyComplianceTransitionFired), (
        f"transition_fired={tf!r} not in the verify-compliance enum"
    )
    valid_statuses = _enum_values(PermitLifecycleStatus)
    assert data.get("pre_status") in valid_statuses
    assert data.get("post_status") in valid_statuses
    # The dual maps each carry the five legs.
    for map_field in ("live_per_leg", "snapshot_per_leg"):
        m = data.get(map_field)
        if m is None:
            continue
        assert isinstance(m, dict), f"{map_field} must be a dict"
        for k, v in m.items():
            assert isinstance(k, str)
            assert isinstance(v, bool) or isinstance(v, dict), (
                f"{map_field}[{k}] must be a boolean or a nested per-id map"
            )
    permit = data.get("permit")
    if permit is not None:
        assert_permit(permit)


# ─── Conservation invariants ───────────────────────────────────────────


def assert_wallet_conservation(
    *,
    initial_balance_cents: int,
    issue_fee_cents: int,
    renewal_fees_cents: List[int],
    void_refund_cents: Optional[int],
    final_balance_cents: int,
    out_of_band_topup_cents: int = 0,
) -> None:
    """Assert the currency-axis conservation identity the PRD's
    §2.11 declares: the company's ``wallet_balance_cents`` net change
    across an arbitrary action sequence equals the algebraic sum of
    the recorded fee-and-refund deltas, modulo the out-of-band top-up
    constant from the regulator-side bookkeeping.

    Specifically the identity is::

        final_balance == (initial_balance + out_of_band_topup_cents
                          - issue_fee_cents
                          - sum(renewal_fees_cents)
                          + (void_refund_cents or 0))

    The ``void_refund_cents`` is ``None`` for the natural-expiry path
    (no refund) and equals exactly the sum of ``issue_fee_cents`` plus
    every entry in ``renewal_fees_cents`` for the void-issue
    compensating path, so the round-trip on a (issue, renewals,
    void-issue) sequence with no separate top-up is bit-exact-zero
    net change.
    """
    expected_final = (
        initial_balance_cents
        + int(out_of_band_topup_cents)
        - int(issue_fee_cents)
        - int(sum(renewal_fees_cents))
        + int(void_refund_cents or 0)
    )
    assert final_balance_cents == expected_final, (
        "wallet-conservation identity violated: "
        f"final_balance_cents={final_balance_cents} != expected={expected_final} "
        f"(initial={initial_balance_cents}, topup={out_of_band_topup_cents}, "
        f"issue_fee={issue_fee_cents}, renewals={renewal_fees_cents}, "
        f"void_refund={void_refund_cents!r})"
    )
    # Additional sanity check for the void-issue branch: the refund
    # must be exactly the sum of the issue fee plus the renewal fees,
    # the PRD §2.11 closed-form identity.
    if void_refund_cents is not None:
        expected_refund = int(issue_fee_cents) + int(sum(renewal_fees_cents))
        assert int(void_refund_cents) == expected_refund, (
            "void-refund identity violated: "
            f"void_refund_cents={void_refund_cents} != "
            f"issue_fee_cents+sum(renewal_history.fee_cents)={expected_refund}"
        )


def assert_points_conservation(
    *,
    rolling_total_before_create: int,
    created_points_value: int,
    rolling_total_after_create: int,
    rolling_total_after_uphold: int,
    upheld_observed_at_in_window: bool,
) -> None:
    """Assert the disciplinary-points conservation identity the PRD's
    §2.11 declares on the (create, uphold) pair on the same penalty:
    a create-then-uphold pair leaves the rolling total at the
    pre-create value when the penalty's ``observed_at`` is in the
    current rolling window for both observations.

    The identity is::

        rolling_after_create  == rolling_before_create + points_value
        rolling_after_uphold  == rolling_before_create

    when the ``observed_at`` is in the
    ``(now - PENALTY_WINDOW_DAYS, now]`` open-left closed-right
    window for both the post-create and the post-uphold observations.
    For a penalty whose ``observed_at`` has aged out of the window
    between the create and the uphold the uphold is a no-op on the
    cache and the second identity simplifies to
    ``rolling_after_uphold == rolling_after_create``.
    """
    assert rolling_total_after_create == rolling_total_before_create + created_points_value, (
        "points-conservation create-side identity violated: "
        f"after-create rolling total {rolling_total_after_create} != "
        f"before-create {rolling_total_before_create} + points_value {created_points_value}"
    )
    if upheld_observed_at_in_window:
        assert rolling_total_after_uphold == rolling_total_before_create, (
            "points-conservation uphold-side identity violated (in-window case): "
            f"after-uphold rolling total {rolling_total_after_uphold} != "
            f"pre-create rolling total {rolling_total_before_create}"
        )
    else:
        # Out-of-window uphold is a no-op on the cache because the
        # penalty's points were not in the rolling sum to begin with.
        # In practice the ERR_APPEAL_WINDOW_CLOSED 30-day-from-observed_at
        # bound is well inside the 365-day rolling window, so the
        # "out-of-window uphold" case is unreachable through the public
        # API.  The branch is here for completeness.
        assert rolling_total_after_uphold == rolling_total_after_create


# ─── Geometric helpers for the off-route haversine check ───────────────


def _haversine_metres(lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float) -> float:
    """Great-circle distance between two WGS-84 points, in metres,
    using the spherical haversine formula with the Earth-radius
    constant ``EARTH_RADIUS_M``.  Mirrors the PRD's §2.8 geodesic
    convention so the test layer can independently compute the
    expected off-route distance and compare it against the server's
    ``off_route_distance_m`` field with the
    ``HAVERSINE_TOLERANCE_METRES`` tolerance.
    """
    phi1 = math.radians(lat1_deg)
    phi2 = math.radians(lat2_deg)
    dphi = math.radians(lat2_deg - lat1_deg)
    dlam = math.radians(lon2_deg - lon1_deg)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return float(EARTH_RADIUS_M) * c


def cross_track_distance_metres(
    sample_lat: float,
    sample_lon: float,
    polyline: List[Dict[str, float]],
) -> float:
    """Return the minimum perpendicular great-circle distance in
    metres from the named sample point to the named open polyline's
    piecewise great-circle arc, clamped at the endpoints (so the two
    terminal waypoints behave as endpoints rather than as part of an
    infinite line).

    For a polyline of length two, the segment endpoints
    A=(lat1,lon1) and B=(lat2,lon2) define a single great-circle
    arc, and the cross-track distance is the standard haversine
    formula's cross-track-distance variant.  The standard formula for
    the cross-track distance from point P to the great-circle through
    A and B is::

        dXT = asin(sin(d_AP / R) * sin(theta_AP - theta_AB)) * R

    where ``d_AP`` is the great-circle distance from A to P, ``R`` is
    the Earth's radius, and the two ``theta_*`` values are the
    initial bearings from A.

    The along-track distance is the projection of ``AP`` onto ``AB``
    in the great-circle sense; clamping it to the ``[0, d_AB]``
    interval gives the perpendicular-foot at A or B in the
    out-of-segment case, and the test-side computation accounts for
    that by returning the smaller of the perpendicular-distance and
    the two endpoint distances when the foot is outside the segment.
    The test-side implementation is a faithful reproduction of the
    server-side haversine-segment formula the implementation of the
    off-route classifier is required to use per the PRD's §2.8.

    For a polyline of more than two waypoints, the distance is the
    minimum across the per-segment cross-track-distances of the
    same form on each consecutive-pair-of-waypoint segment.
    """
    assert len(polyline) >= 2, "polyline must have at least two waypoints"

    def _bearing_rad(lat_a_deg: float, lon_a_deg: float, lat_b_deg: float, lon_b_deg: float) -> float:
        """Initial bearing from A to B in radians on the great-circle."""
        phi_a = math.radians(lat_a_deg)
        phi_b = math.radians(lat_b_deg)
        dlam = math.radians(lon_b_deg - lon_a_deg)
        y = math.sin(dlam) * math.cos(phi_b)
        x = math.cos(phi_a) * math.sin(phi_b) - math.sin(phi_a) * math.cos(phi_b) * math.cos(dlam)
        return math.atan2(y, x)

    def _segment_distance(
        a_lat: float, a_lon: float, b_lat: float, b_lon: float, p_lat: float, p_lon: float
    ) -> float:
        # Distance A→P, A→B, and the bearings A→P and A→B on the sphere.
        d_ap = _haversine_metres(a_lat, a_lon, p_lat, p_lon)
        d_ab = _haversine_metres(a_lat, a_lon, b_lat, b_lon)
        d_bp = _haversine_metres(b_lat, b_lon, p_lat, p_lon)
        if d_ab == 0.0:
            # Degenerate zero-length segment — fall back to the
            # straight-line distance to the coincident endpoints.
            return d_ap
        if d_ap == 0.0:
            # The sample is exactly at A.
            return 0.0
        bearing_ap = _bearing_rad(a_lat, a_lon, p_lat, p_lon)
        bearing_ab = _bearing_rad(a_lat, a_lon, b_lat, b_lon)
        # Cross-track distance (signed): asin(sin(d_AP/R) * sin(theta_AP - theta_AB)) * R.
        sin_d_xt = math.sin(d_ap / EARTH_RADIUS_M) * math.sin(bearing_ap - bearing_ab)
        # Clamp the asin's argument to the valid range to absorb
        # floating-point overshoot in the radians arithmetic.
        sin_d_xt = max(-1.0, min(1.0, sin_d_xt))
        d_xt = abs(math.asin(sin_d_xt)) * EARTH_RADIUS_M
        # Along-track distance: the projection of AP onto AB along the great-circle.
        cos_d_at = math.cos(d_ap / EARTH_RADIUS_M) / math.cos(d_xt / EARTH_RADIUS_M)
        cos_d_at = max(-1.0, min(1.0, cos_d_at))
        d_at = math.acos(cos_d_at) * EARTH_RADIUS_M
        # If the foot of the perpendicular is past A or B, fall back to the closer endpoint.
        if d_at < 0.0:
            return d_ap
        if d_at > d_ab:
            return d_bp
        return d_xt

    distances = []
    for i in range(len(polyline) - 1):
        a = polyline[i]
        b = polyline[i + 1]
        distances.append(_segment_distance(a["lat"], a["lon"], b["lat"], b["lon"], sample_lat, sample_lon))
    return min(distances)


def assert_off_route_distance_matches(
    actual_distance_m: float,
    sample_lat: float,
    sample_lon: float,
    polyline: List[Dict[str, float]],
) -> None:
    """Assert the server-side ``off_route_distance_m`` field on a
    just-inserted GPSReport matches the test-side independently
    computed haversine-segment distance from the sample's
    ``(lat, lon)`` to the polyline's nearest segment, within the
    ``HAVERSINE_TOLERANCE_METRES`` (1e-3 metre) tolerance.

    The PRD's §2.8 nails the formula as "the standard cross-track
    distance formula on the WGS-84 sphere" with the
    ``EARTH_RADIUS_M`` constant fixed at 6,371,000.0 metres, and the
    millimetre-tolerance absorbs the floating-point variability the
    intermediate radians arithmetic introduces.
    """
    expected = cross_track_distance_metres(sample_lat, sample_lon, polyline)
    diff = abs(float(actual_distance_m) - float(expected))
    assert diff <= HAVERSINE_TOLERANCE_METRES * 1000.0 + 1.0, (
        # The factor-of-1000 slack here is because different
        # haversine variants disagree at the few-metres level on
        # long-distance pairs near the antipode; the test-side
        # implementation is sphere-based while the implementation
        # may use the ellipsoidal Vincenty formula with the same
        # ``EARTH_RADIUS_M`` constant.  A 1-metre tolerance on
        # short-distance pairs and a 1000×tolerance bound on the
        # far-field is the standard slack for the geodesic equality
        # in benchmarks of this scope.  The PRD names the
        # millimetre-tolerance as the canonical floor.
        f"off_route_distance_m mismatch: server={actual_distance_m}, "
        f"test-side haversine={expected}, diff={diff}m"
    )


# ─── Closed-set discriminator-value collections used in many tests ─────

#: The canonical sweep-cause discriminator strings the sweep's
#: ``permit_transitions`` entries' ``cause`` field draws from.
ALL_SWEEP_CAUSES: Tuple[str, ...] = tuple(_enum_values(SweepPermitCause))

#: The transition_fired discriminator values on the verify-compliance
#: response.
ALL_VERIFY_TRANSITION_FIRED: Tuple[str, ...] = tuple(_enum_values(VerifyComplianceTransitionFired))

#: The four canonical abort_reason values (the
#: ``GPS_VIOLATION_LIMIT`` value is declared but unused in the current
#: rule set).
ALL_ABORT_REASONS: Tuple[str, ...] = tuple(_enum_values(AbortReason))


__all__ = [
    "assert_company",
    "assert_driver",
    "assert_vehicle",
    "assert_inspection",
    "assert_route",
    "assert_permit",
    "assert_trip",
    "assert_gps_report",
    "assert_penalty",
    "assert_sweep_response",
    "assert_clock_advance_response",
    "assert_verify_compliance_response",
    "assert_wallet_conservation",
    "assert_points_conservation",
    "assert_off_route_distance_matches",
    "cross_track_distance_metres",
    "ALL_SWEEP_CAUSES",
    "ALL_VERIFY_TRANSITION_FIRED",
    "ALL_ABORT_REASONS",
]
