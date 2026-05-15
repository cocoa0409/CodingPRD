"""The Trip endpoints — five in the scaffold's §1.5 enumeration:

  POST /v1/permits/<permit_id>/trips     — operator schedules a trip
                                            under an ACTIVE permit. The
                                            cross-permit vehicle-
                                            calendar overlap check at
                                            priority 521 fires
                                            `ERR_VEHICLE_DOUBLE_BOOKED`
                                            on a half-open-interval
                                            overlap on the same
                                            vehicle. The scheduled-
                                            window-vs-permit-validity-
                                            window check at priority
                                            522 fires
                                            `ERR_OUTSIDE_VALIDITY_WINDOW`
                                            on a scheduled window that
                                            does not lie entirely
                                            inside the permit's
                                            `[valid_from, valid_until]`
                                            interval (the closed-on-
                                            the-arrival-edge convention
                                            on the right side per the
                                            §2.9 paragraph's
                                            scheduled-arrival-edge
                                            asymmetry-vs-the-wall-clock
                                            -live-comparison note).

  GET  /v1/trips/<trip_id>               — the trip-row read. The
                                            three-role access set
                                            (CompanyOperator with the
                                            transitive-tenant via the
                                            parent permit's company,
                                            RegulatorOfficer cross-
                                            tenant exempt, Driver with
                                            the self-only-on-the-trip's-
                                            driver_id-equals-the-Driver's-
                                            X-User-ID rule the §1.7
                                            matrix's driver-deviation-
                                            cell pins).

  POST /v1/trips/<trip_id>/depart        — operator's `PLANNED ->
                                            IN_TRANSIT` transition.
                                            Requires the parent permit
                                            to be in `lifecycle_status =
                                            "ACTIVE"` at the depart-
                                            time per the §3.7
                                            paragraph's "the depart
                                            re-checks the parent's-
                                            active-state gate" rule
                                            firing `ERR_PERMIT_NOT_ACTIVE`
                                            409 on a non-ACTIVE parent.

  POST /v1/trips/<trip_id>/arrive        — operator's `IN_TRANSIT ->
                                            COMPLETED` transition. The
                                            parent-state predicate is
                                            permissive — a SUSPENDED
                                            parent permit's in-flight
                                            trip is allowed to arrive
                                            per the §3.7's "the
                                            suspension gates the GPS-
                                            stream but allows the
                                            wind-down attestation" rule.
                                            The EXPIRED-and-VOIDED
                                            parent cases have already
                                            cascaded-aborted the trip
                                            so the same-row `trip_status
                                            == IN_TRANSIT` check fails
                                            first.

  POST /v1/trips/<trip_id>/abort         — operator's `PLANNED ->
                                            ABORTED` or `IN_TRANSIT ->
                                            ABORTED` transition with
                                            the discriminator value
                                            `abort_reason =
                                            "OPERATOR_ABORT"`. The
                                            body's required `reason_note`
                                            is the 1-to-500-character
                                            audit-cause string. The
                                            cascade-from-permit-
                                            transition aborts are
                                            server-internal arcs in the
                                            sweep-and-the-void-issue
                                            handlers rather than
                                            client-initiated through
                                            this endpoint.

The vehicle-double-booking interval semantics is the half-open right-
exclusive `[scheduled_departure_at, scheduled_arrival_at)` from the
§2.9 conventions table; two trips whose boundary timestamps touch (one
ends exactly when the other starts) do not overlap under the half-open
rule. The scope of the check is cross-permit — the conflict-walker
iterates over every Trip row in the system whose `vehicle_id` matches
the new trip's, regardless of the row's parent permit, per the §3.7
paragraph's "the vehicle is the physical asset and cannot be in two
places at the same wall-clock instant".

The trip-vs-permit window-membership check on the scheduled window's
edges against the parent permit's `[valid_from, valid_until]` is the
closed-on-the-right convention on the arrival-edge (the scheduled
arrival may touch the permit's `valid_until` exactly even though the
wall-clock-vs-`valid_until` live-comparison is strict-less-than) per
the §2.9's "the scheduled-arrival-vs-the-permit-right-edge is the
closed-right exception" deliberate-asymmetry pin.

The PRD's §3.7 paragraph names the priority-conflict-A scenario:
"a trip-creation request whose parent permit is SUSPENDED and whose
body-named route or driver or vehicle simultaneously has a non-green
state returns `ERR_PERMIT_NOT_ACTIVE` for the parent-state cause, not
the more-specific grounding-entity error" — this is the rule-5
priority-conflict-A's Tier-4-versus-Tier-5b winner. The
implementation realizes this by checking the parent-state predicate
before the body's-driver-endorsement-or-vehicle-inspection-or-route-
approval checks at the safety/referential business-rule tier.

The cascade-from-permit-transition arcs into the trip's terminal
`ABORTED` state are fired by the sweep's wall-clock-expiry handler
in `sweep.py` (the `PERMIT_EXPIRED_CASCADE` reason) and by the void-
issue handler in `permits.py` (the `PERMIT_SUSPENDED_CASCADE` reason
per the §2.8 enum-economy reuse). The operator's abort endpoint in
this blueprint sets `abort_reason = "OPERATOR_ABORT"`, the third
canonical reason-discriminator value. The fourth declared-but-
unused-in-the-current-scaffold reason `GPS_VIOLATION_LIMIT` exists
in the enum for forward compatibility per the §2.8 paragraph.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Blueprint, current_app

from ..auth import (
    assert_cross_tenant_ownership,
    current_principal,
    lookup_path_resource,
)
from ..clock import current_now, iso_format, iso_now, parse_iso
from ..config import (
    Constants,
    GENERIC_REASON_NOTE_LEN_RANGE,
    OPTIONAL_NOTE_LEN_RANGE,
    ARRIVE_DELIVERY_ATTESTATION_LEN_RANGE,
    TRIP_CARGO_DESCRIPTION_LEN_RANGE,
    UN_HAZARD_CLASS_CODES,
)
from ..envelope import get_json_body, make_object_response
from ..errors import APIError
from ..store import (
    STATE_LOCK,
    bump_version,
    check_occ,
    find,
    insert,
    stamp_create,
    table,
)
from ..validation import (
    require_array,
    require_enum,
    require_int,
    require_iso_datetime,
    require_present,
    require_str,
)


trips_bp = Blueprint("trips", __name__)


def _serialize_trip(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def _intervals_overlap_half_open(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    """The half-open-right-exclusive interval-overlap predicate. Two
    intervals `[a_start, a_end)` and `[b_start, b_end)` overlap iff
    `a_start < b_end` AND `b_start < a_end`. The boundary case where
    `a_end == b_start` (one trip's arrival is the other's departure)
    is the non-overlap case — the strict-less-than on both sides of
    the conjunction excludes the touching-boundary pair from the
    overlap, matching the §2.9 paragraph's "the half-open-and-touching-
    boundary-admitted convention" of the vehicle-calendar's interval
    semantics.
    """
    return a_start < b_end and b_start < a_end


def _check_vehicle_no_double_booking(
    vehicle_id: str,
    scheduled_departure_at: datetime,
    scheduled_arrival_at: datetime,
    exclude_trip_id: str | None = None,
) -> None:
    """The cross-permit vehicle-calendar conflict-walk. Iterates the
    Trip table for every row whose `vehicle_id` matches and whose
    `(scheduled_departure_at, scheduled_arrival_at)` half-open interval
    overlaps the candidate's. The conflict-walker is over the closed-
    set of Trip rows that are not yet terminal-ABORTED — the §3.7
    paragraph's "an aborted trip is no longer occupying the vehicle's
    calendar" reading is one defensible interpretation; the alternative
    "the schedule is the schedule regardless of the actual outcome"
    reading is the other. The PRD §3.7's closing paragraph's "the
    check does not consider the trip's `actual_departure_at` or
    `actual_arrival_at` — only the scheduled times" pin reads as the
    scheduling-time-only check, so an aborted trip's schedule still
    occupies the calendar from the spec's perspective. The
    implementation follows that strict reading: the conflict-walk
    includes the terminal-COMPLETED-and-ABORTED rows because their
    scheduled windows are still recorded on the calendar.

    On a conflict the function raises `ERR_VEHICLE_DOUBLE_BOOKED` 409
    at the business-temporal-constraint priority 521. The exclude-trip-
    id argument lets a hypothetical reschedule endpoint exclude the
    current row from its own self-conflict (the scaffold has no
    reschedule endpoint, so the argument is always None in practice).
    """
    for other in table("Trip").values():
        if other.get("vehicle_id") != vehicle_id:
            continue
        if exclude_trip_id is not None and other.get("id") == exclude_trip_id:
            continue
        other_dep_str = other.get("scheduled_departure_at")
        other_arr_str = other.get("scheduled_arrival_at")
        if other_dep_str is None or other_arr_str is None:
            continue
        other_dep = parse_iso(other_dep_str)
        other_arr = parse_iso(other_arr_str)
        if _intervals_overlap_half_open(
            scheduled_departure_at, scheduled_arrival_at, other_dep, other_arr
        ):
            raise APIError(
                "ERR_VEHICLE_DOUBLE_BOOKED",
                f"Vehicle {vehicle_id!r}'s calendar already has a trip "
                f"{other.get('id')!r} whose half-open schedule "
                f"`[{iso_format(other_dep)}, {iso_format(other_arr)})` "
                f"overlaps the candidate's "
                f"`[{iso_format(scheduled_departure_at)}, "
                f"{iso_format(scheduled_arrival_at)})`.",
                details={
                    "vehicle_id": vehicle_id,
                    "conflicting_trip_id": other.get("id"),
                    "conflicting_permit_id": other.get("permit_id"),
                    "candidate_window": [
                        iso_format(scheduled_departure_at),
                        iso_format(scheduled_arrival_at),
                    ],
                    "conflicting_window": [
                        iso_format(other_dep),
                        iso_format(other_arr),
                    ],
                },
            )


# ---------------------------------------------------------------------------
# POST /v1/permits/<permit_id>/trips — schedule a trip
# ---------------------------------------------------------------------------


@trips_bp.route("/permits/<permit_id>/trips", methods=["POST"])
def post_create_trip(permit_id: str) -> Any:
    """The trip-creation endpoint. The PRD §3.7 paragraph names the
    full validation chain in priority-ordered tiers. The implementation
    walks them in the same order so the §2.7's-priority-numbering's-
    lowest-wins rule's observable outcome matches the spec's table.

    The body's-foreign-keys (the `driver_id` and the `vehicle_id`) are
    existence-checked at the existence tier, with the cross-tenant-as-
    not-found semantic from §2.6's closing paragraph on body-foreign-
    key references.

    The `cargo_hazard_class` field is the single-class string drawn
    from the permit's `hazard_classes` authorized array — the body-
    shape validation walks the §2.8 UN-hazard-class taxonomy
    membership first, then the within-permit-authorization check.

    The `cargo_weight_kg` field is the integer in the inclusive 0-to-
    `vehicle.max_payload_kg` range; the negative or over-capacity case
    is the body-shape `ERR_VALIDATION` 422 from the §2.4 paragraph's
    closing free-text-and-range-bounds note.

    The two scheduled timestamps' relative ordering — `scheduled_departure_at
    < scheduled_arrival_at` strictly — is the body-shape rule; the
    `scheduled_departure_at > now()` strictly is the no-back-dated-
    trip rule per the §2.9's `scheduled-departure-not-in-the-past`
    paragraph; the window-membership check against the parent permit's
    `[valid_from, valid_until]` with the closed-on-the-arrival-edge
    convention is the priority-522 `ERR_OUTSIDE_VALIDITY_WINDOW` 409
    check.

    The cross-permit vehicle-double-booking check at priority 521
    iterates the global Trip table for every row with the same
    `vehicle_id` and a half-open-overlapping scheduled window per the
    rule-8 overlap-A interval-semantics. The boundary-touching case
    (one trip's arrival equals another's departure exactly) is the
    non-conflict case under the half-open semantics.

    The driver-endorsement-live-check at priority 510 fires
    `ERR_DRIVER_ENDORSEMENT_INVALID` 409 when the body's `driver_id`,
    even though on the permit's authorized list, has flipped to a
    non-VALID state since the permit's issue. The symmetric vehicle-
    inspection-live-check at priority 511 fires the
    `ERR_VEHICLE_INSPECTION_LAPSED` 409 on the analogous failure on
    the vehicle's latest-inspection cover-the-trip-end-or-not predicate.

    The parent-permit-active gate at the state tier with priority 400
    is the cross-aggregate "the parent permit's `lifecycle_status` is
    `ACTIVE` at the trip-create moment" check firing
    `ERR_PERMIT_NOT_ACTIVE` 409 on any non-ACTIVE parent. This is the
    rule-5 priority-conflict-A's tier-4-beats-tier-5-business-
    referential pin: a parent-permit-SUSPENDED-and-route-not-approved
    pair returns the permit-not-active error rather than the
    route-not-approved error because the Tier-4 priority-400 fires
    earlier than the Tier-5 priority-525.

    The standard order in the handler-body below: auth (the
    middleware), existence on the path-id, cross-tenant on the parent
    permit, parent-state (Tier-4-ERR_PERMIT_NOT_ACTIVE), body-shape on
    the fields, existence-on-body-foreign-keys (driver and vehicle ids
    on the per-tenant-cross-tenant-as-not-found semantic), within-
    permit-authorization-membership-on-the-driver-and-vehicle-ids
    (this is a body-shape rule, with the catch-all `ERR_VALIDATION`
    422 message naming which of the permit's arrays the value is
    missing from), the cargo-hazard-class-membership-in-the-permit's-
    hazard-classes (also catch-all 422), the cargo-vs-vehicle-payload
    range check, the depart-arrive-ordering and the both-in-the-
    permit-window check (the latter the priority-522 dedicated
    `ERR_OUTSIDE_VALIDITY_WINDOW`), the vehicle-double-booking conflict-
    walk (priority-521 dedicated `ERR_VEHICLE_DOUBLE_BOOKED`), the
    per-driver-endorsement-live and the per-vehicle-inspection-live
    checks (priorities 510 and 511). The OCC contract is not engaged
    on a creation endpoint since the to-be-created row has no prior
    `version` to compare against.
    """
    permit = lookup_path_resource("Permit", permit_id, "ERR_PERMIT_NOT_FOUND")
    # The cross-tenant check on the parent permit's `company_id`.
    assert_cross_tenant_ownership("Permit", permit)

    # The parent-permit-active gate at the state tier with priority
    # 400. The §1.5 endpoint table's `ordered_error_table` lists the
    # `ERR_PERMIT_NOT_ACTIVE` 409 error id for this check; the
    # §3.7 paragraph names the priority-conflict-A pin.
    pre_permit_status = permit.get("lifecycle_status")
    if pre_permit_status != "ACTIVE":
        raise APIError(
            "ERR_PERMIT_NOT_ACTIVE",
            f"Parent Permit is in `lifecycle_status` "
            f"{pre_permit_status!r}, not 'ACTIVE'.",
            details={
                "permit_id": permit_id,
                "lifecycle_status": pre_permit_status,
                "required": "ACTIVE",
                "rule": "rule-5-priority-conflict-A "
                "(Tier-4 state beats Tier-5 business-referential).",
            },
        )

    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]
    role, operator_id = current_principal()

    # The body-foreign-keys' existence at the existence tier with the
    # cross-tenant-as-not-found semantic from §2.6.
    driver_id = require_str(body, "driver_id", length_range=(1, 256))
    vehicle_id = require_str(body, "vehicle_id", length_range=(1, 256))
    cargo_description = require_str(
        body,
        "cargo_description",
        length_range=TRIP_CARGO_DESCRIPTION_LEN_RANGE,
    )
    cargo_hazard_class = require_enum(
        body, "cargo_hazard_class", allowed=UN_HAZARD_CLASS_CODES
    )
    cargo_weight_kg = require_int(body, "cargo_weight_kg", nonnegative=True)
    scheduled_departure_dt = require_iso_datetime(body, "scheduled_departure_at")
    assert scheduled_departure_dt is not None
    scheduled_arrival_dt = require_iso_datetime(body, "scheduled_arrival_at")
    assert scheduled_arrival_dt is not None

    # The existence walks on the body-foreign-keys' tenant-scoped resolutions.
    driver = find("Driver", driver_id)
    if driver is None or driver.get("company_id") != operator_id:
        raise APIError(
            "ERR_DRIVER_NOT_FOUND",
            f"Driver {driver_id!r} does not resolve in the operator's "
            f"tenant universe.",
            details={"driver_id": driver_id, "operator_tenant": operator_id},
        )
    vehicle = find("Vehicle", vehicle_id)
    if vehicle is None or vehicle.get("company_id") != operator_id:
        raise APIError(
            "ERR_VEHICLE_NOT_FOUND",
            f"Vehicle {vehicle_id!r} does not resolve in the operator's "
            f"tenant universe.",
            details={"vehicle_id": vehicle_id, "operator_tenant": operator_id},
        )

    # The within-permit-authorization-arrays membership.
    if driver_id not in (permit.get("authorized_driver_ids") or []):
        raise APIError(
            "ERR_VALIDATION",
            f"The `driver_id` {driver_id!r} is not in the permit's "
            f"`authorized_driver_ids` list.",
            details={
                "field": "driver_id",
                "value": driver_id,
                "allowed_set": list(permit.get("authorized_driver_ids") or []),
            },
        )
    if vehicle_id not in (permit.get("authorized_vehicle_ids") or []):
        raise APIError(
            "ERR_VALIDATION",
            f"The `vehicle_id` {vehicle_id!r} is not in the permit's "
            f"`authorized_vehicle_ids` list.",
            details={
                "field": "vehicle_id",
                "value": vehicle_id,
                "allowed_set": list(permit.get("authorized_vehicle_ids") or []),
            },
        )
    if cargo_hazard_class not in (permit.get("hazard_classes") or []):
        raise APIError(
            "ERR_VALIDATION",
            f"The `cargo_hazard_class` {cargo_hazard_class!r} is not in "
            "the permit's authorized `hazard_classes` list.",
            details={
                "field": "cargo_hazard_class",
                "value": cargo_hazard_class,
                "allowed_set": list(permit.get("hazard_classes") or []),
            },
        )

    # The cargo-vs-vehicle-payload range check.
    max_payload = int(vehicle.get("max_payload_kg") or 0)
    assert cargo_weight_kg is not None
    if cargo_weight_kg > max_payload:
        raise APIError(
            "ERR_VALIDATION",
            f"The `cargo_weight_kg` {cargo_weight_kg} exceeds the "
            f"vehicle's `max_payload_kg` of {max_payload}.",
            details={
                "field": "cargo_weight_kg",
                "value": cargo_weight_kg,
                "vehicle_max_payload_kg": max_payload,
            },
        )

    # The cargo-hazard-class-vs-vehicle-compatibility check.
    vehicle_compatible = set(vehicle.get("hazard_classes_compatible") or [])
    if cargo_hazard_class not in vehicle_compatible:
        raise APIError(
            "ERR_VALIDATION",
            f"The cargo's hazard class {cargo_hazard_class!r} is not in "
            "the vehicle's `hazard_classes_compatible` set.",
            details={
                "field": "cargo_hazard_class",
                "value": cargo_hazard_class,
                "vehicle_compatible": sorted(vehicle_compatible),
            },
        )
    # The cargo-hazard-class-vs-driver-endorsement-classes check.
    driver_endorsed = set(driver.get("endorsement_classes") or [])
    if cargo_hazard_class not in driver_endorsed:
        raise APIError(
            "ERR_VALIDATION",
            f"The cargo's hazard class {cargo_hazard_class!r} is not in "
            "the driver's regulator-attested `endorsement_classes` set.",
            details={
                "field": "cargo_hazard_class",
                "value": cargo_hazard_class,
                "driver_endorsed": sorted(driver_endorsed),
            },
        )

    # The temporal-shape rules: departure is strictly future; arrival
    # is strictly after departure; the schedule lies within the
    # permit's `[valid_from, valid_until]` interval (closed-on-the-
    # right per the §2.9 paragraph's "the scheduled-arrival-can-touch-
    # the-permit's-right-edge" asymmetry).
    now = current_now()
    if scheduled_departure_dt <= now:
        raise APIError(
            "ERR_VALIDATION",
            f"The `scheduled_departure_at` {iso_format(scheduled_departure_dt)!r} "
            f"must be strictly after the current logical-clock value "
            f"{iso_format(now)!r}.",
            details={
                "field": "scheduled_departure_at",
                "value": iso_format(scheduled_departure_dt),
                "now": iso_format(now),
            },
        )
    if scheduled_arrival_dt <= scheduled_departure_dt:
        raise APIError(
            "ERR_VALIDATION",
            f"The `scheduled_arrival_at` "
            f"{iso_format(scheduled_arrival_dt)!r} must be strictly "
            f"after the `scheduled_departure_at` "
            f"{iso_format(scheduled_departure_dt)!r}.",
            details={
                "field": "scheduled_arrival_at",
                "value": iso_format(scheduled_arrival_dt),
                "scheduled_departure_at": iso_format(scheduled_departure_dt),
            },
        )

    valid_from_str = permit.get("valid_from")
    valid_until_str = permit.get("valid_until")
    if valid_from_str is None or valid_until_str is None:
        # An ACTIVE permit always has both valid_from and valid_until
        # set per the issue-step's-side-effects; defensive guard.
        raise APIError(
            "ERR_VALIDATION",
            "Parent Permit is in ACTIVE but its `valid_from` or "
            "`valid_until` is null — internal inconsistency.",
            details={
                "valid_from": valid_from_str,
                "valid_until": valid_until_str,
            },
        )
    valid_from = parse_iso(valid_from_str)
    valid_until = parse_iso(valid_until_str)
    # The scheduled departure must be at-or-after the permit's
    # valid_from (closed-left on the left edge), and the scheduled
    # arrival must be at-or-before the permit's valid_until (closed-
    # right on the right edge, the §2.9 paragraph's "the scheduled-
    # arrival can touch the permit's expiry-edge" deliberate-asymmetry
    # pin against the wall-clock-vs-`valid_until`-live-strict-less-than
    # convention).
    if scheduled_departure_dt < valid_from or scheduled_arrival_dt > valid_until:
        raise APIError(
            "ERR_OUTSIDE_VALIDITY_WINDOW",
            f"The trip's scheduled window "
            f"`[{iso_format(scheduled_departure_dt)}, "
            f"{iso_format(scheduled_arrival_dt)}]` lies outside the "
            f"permit's `[valid_from, valid_until]` window "
            f"`[{iso_format(valid_from)}, {iso_format(valid_until)}]`.",
            details={
                "trip_window": [
                    iso_format(scheduled_departure_dt),
                    iso_format(scheduled_arrival_dt),
                ],
                "permit_window": [
                    iso_format(valid_from),
                    iso_format(valid_until),
                ],
            },
        )

    # The cross-permit vehicle-calendar conflict walk (priority 521).
    _check_vehicle_no_double_booking(
        vehicle_id, scheduled_departure_dt, scheduled_arrival_dt
    )

    # The driver-endorsement-live check (priority 510). The endorsement
    # must be VALID at the trip-create moment regardless of whether
    # the driver is on the permit's-authorized-array.
    if driver.get("hazmat_endorsement_status") != "VALID":
        raise APIError(
            "ERR_DRIVER_ENDORSEMENT_INVALID",
            f"Driver {driver_id!r}'s `hazmat_endorsement_status` is "
            f"{driver.get('hazmat_endorsement_status')!r}, not 'VALID'.",
            details={
                "driver_id": driver_id,
                "current_status": driver.get("hazmat_endorsement_status"),
                "scheduled_arrival_at": iso_format(scheduled_arrival_dt),
            },
        )
    # The endorsement must cover the scheduled arrival.
    eu_str = driver.get("endorsement_valid_until")
    if eu_str is None or parse_iso(eu_str) < scheduled_arrival_dt:
        raise APIError(
            "ERR_DRIVER_ENDORSEMENT_INVALID",
            f"Driver {driver_id!r}'s `endorsement_valid_until` "
            f"{eu_str!r} does not cover the trip's scheduled arrival "
            f"{iso_format(scheduled_arrival_dt)!r}.",
            details={
                "driver_id": driver_id,
                "endorsement_valid_until": eu_str,
                "scheduled_arrival_at": iso_format(scheduled_arrival_dt),
            },
        )
    # The points-below-threshold check.
    if int(driver.get("current_rolling_points", 0)) >= constants.threshold_driver_suspension_points:
        raise APIError(
            "ERR_DRIVER_ENDORSEMENT_INVALID",
            f"Driver {driver_id!r}'s `current_rolling_points` "
            f"{driver.get('current_rolling_points')!r} is at or above "
            f"the suspension threshold "
            f"{constants.threshold_driver_suspension_points}.",
            details={
                "driver_id": driver_id,
                "current_rolling_points": driver.get("current_rolling_points"),
                "threshold": constants.threshold_driver_suspension_points,
            },
        )

    # The vehicle-inspection-live check (priority 511). The latest
    # inspection's outcome must be PASSED and its valid_until must
    # cover the scheduled arrival per the §3.7 paragraph's "the
    # vehicle's `latest_inspection_valid_until >= trip.scheduled_arrival_at`
    # rule".
    if vehicle.get("latest_inspection_outcome") != "PASSED":
        raise APIError(
            "ERR_VEHICLE_INSPECTION_LAPSED",
            f"Vehicle {vehicle_id!r}'s `latest_inspection_outcome` is "
            f"{vehicle.get('latest_inspection_outcome')!r}, not 'PASSED'.",
            details={
                "vehicle_id": vehicle_id,
                "latest_inspection_outcome": vehicle.get("latest_inspection_outcome"),
            },
        )
    vu_str = vehicle.get("latest_inspection_valid_until")
    if vu_str is None or parse_iso(vu_str) < scheduled_arrival_dt:
        raise APIError(
            "ERR_VEHICLE_INSPECTION_LAPSED",
            f"Vehicle {vehicle_id!r}'s `latest_inspection_valid_until` "
            f"{vu_str!r} does not cover the trip's scheduled arrival "
            f"{iso_format(scheduled_arrival_dt)!r}.",
            details={
                "vehicle_id": vehicle_id,
                "latest_inspection_valid_until": vu_str,
                "scheduled_arrival_at": iso_format(scheduled_arrival_dt),
            },
        )

    # All checks pass. Build the new Trip row in PLANNED.
    row: dict[str, Any] = {
        "permit_id": permit_id,
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "cargo_description": cargo_description,
        "cargo_hazard_class": cargo_hazard_class,
        "cargo_weight_kg": int(cargo_weight_kg),
        "scheduled_departure_at": iso_format(scheduled_departure_dt),
        "scheduled_arrival_at": iso_format(scheduled_arrival_dt),
        "trip_status": "PLANNED",
        "actual_departure_at": None,
        "actual_arrival_at": None,
        "aborted_at": None,
        "abort_reason": None,
        "latest_gps_at": None,
        "gps_violation_count": 0,
    }
    stamp_create(row)
    insert("Trip", row)

    return make_object_response(_serialize_trip(row), http_status=201)


# ---------------------------------------------------------------------------
# GET /v1/trips/<trip_id> — read one
# ---------------------------------------------------------------------------


@trips_bp.route("/trips/<trip_id>", methods=["GET"])
def get_trip(trip_id: str) -> Any:
    """The trip-row read. The §1.7 matrix's allow-set is
    `{CompanyOperator, RegulatorOfficer, Driver}` (the TestHarness
    column is the default-deny). The cross-tenant predicate is the
    standard transitive-tenant rule for the CompanyOperator (the
    trip's parent permit's `company_id` matches the operator's id);
    the Driver-role's self-only-on-the-trip's-driver_id-field rule
    is the priority-531 driver-self-only variant of the cross-tenant
    predicate; the RegulatorOfficer is cross-tenant exempt.

    The not-found case at the existence tier fires before the cross-
    tenant predicate (rule-5 priority-conflict-B convention).
    """
    row = lookup_path_resource("Trip", trip_id, "ERR_TRIP_NOT_FOUND")
    role, user_id = current_principal()
    if role == "Driver":
        # The driver-self-only-on-the-trip's-driver_id rule.
        if row.get("driver_id") != user_id:
            raise APIError(
                "ERR_CROSS_TENANT_ACCESS",
                f"Driver self-only check on trip-read: requester id "
                f"{user_id!r} is not the trip's `driver_id` "
                f"{row.get('driver_id')!r}.",
                details={
                    "rule": "driver-self-only-on-trip",
                    "priority": 531,
                    "requester_id": user_id,
                    "trip_driver_id": row.get("driver_id"),
                },
            )
    else:
        # Operator-transitive-tenant or regulator-exempt. The helper's
        # `resolve_owning_tenant` walks the trip → permit → company
        # chain.
        assert_cross_tenant_ownership("Trip", row)

    return make_object_response(_serialize_trip(row), http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/trips/<trip_id>/depart — PLANNED → IN_TRANSIT
# ---------------------------------------------------------------------------


@trips_bp.route("/trips/<trip_id>/depart", methods=["POST"])
def post_trip_depart(trip_id: str) -> Any:
    """Operator dispatches the trip. The §3.7 paragraph's "the depart
    re-checks the parent-permit-active gate" rule is the cross-
    aggregate state precondition: the trip's parent permit's
    `lifecycle_status` must be `ACTIVE` at the depart-call moment;
    a SUSPENDED-or-EXPIRED-or-VOIDED parent is the dedicated
    `ERR_PERMIT_NOT_ACTIVE` 409 (with the EXPIRED-and-VOIDED cases in
    practice unreachable because their cascade has flipped the trip's
    own status to ABORTED so the same-row trip-status check fails
    first). The same-row pre-state must be `PLANNED` (the generic
    `ERR_INVALID_STATE_TRANSITION` 409 on a non-PLANNED source).

    The §3.7 paragraph's priority-conflict-A pin is that the parent-
    state-check fires before the same-row-state-check: a still-
    PLANNED trip whose parent permit is SUSPENDED receives
    `ERR_PERMIT_NOT_ACTIVE` rather than the generic state error. The
    implementation realizes this by the order of the two state-tier
    checks below — the parent-state-check is the first state-tier
    rejection point.

    Body: optional OCC `version` and optional 0-to-500-character
    `depart_note`. The handler's successful side-effect is
    `actual_departure_at = now()`, `trip_status = IN_TRANSIT`, the
    `version` bump and the `updated_at` refresh.
    """
    trip = lookup_path_resource("Trip", trip_id, "ERR_TRIP_NOT_FOUND")
    # The cross-tenant predicate via the trip's transitive-parent.
    assert_cross_tenant_ownership("Trip", trip)

    body = get_json_body()
    occ = check_occ(trip, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on the Trip during depart.",
            details={
                "expected_version": body.get("version"),
                "actual_version": trip.get("version"),
            },
        )
    require_str(
        body, "depart_note", length_range=OPTIONAL_NOTE_LEN_RANGE, optional=True
    )

    # The parent-permit-active gate fires before the same-row state
    # gate per the rule-5 priority-conflict-A pin.
    permit = find("Permit", trip.get("permit_id"))
    if permit is None:
        raise APIError(
            "ERR_PERMIT_NOT_FOUND",
            "Parent Permit of the trip does not resolve — internal "
            "inconsistency.",
            details={"trip_id": trip_id, "permit_id": trip.get("permit_id")},
        )
    parent_status = permit.get("lifecycle_status")
    if parent_status != "ACTIVE":
        raise APIError(
            "ERR_PERMIT_NOT_ACTIVE",
            f"Parent permit's `lifecycle_status` is {parent_status!r}, "
            "not 'ACTIVE'; the trip cannot depart.",
            details={
                "trip_id": trip_id,
                "permit_id": permit["id"],
                "permit_lifecycle_status": parent_status,
                "rule": "rule-5-priority-conflict-A (parent-state-precedes-"
                "same-row-state).",
            },
        )

    # The same-row state gate.
    pre_status = trip.get("trip_status")
    if pre_status != "PLANNED":
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot depart a trip in `trip_status` {pre_status!r}; the "
            "required source state is 'PLANNED'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["PLANNED"],
                "endpoint": "POST /v1/trips/<trip_id>/depart",
            },
        )

    now = current_now()
    trip["actual_departure_at"] = iso_format(now)
    trip["trip_status"] = "IN_TRANSIT"
    bump_version(trip)

    return make_object_response(_serialize_trip(trip), http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/trips/<trip_id>/arrive — IN_TRANSIT → COMPLETED
# ---------------------------------------------------------------------------


@trips_bp.route("/trips/<trip_id>/arrive", methods=["POST"])
def post_trip_arrive(trip_id: str) -> Any:
    """The arrive action's parent-state predicate is the permissive
    "ACTIVE or SUSPENDED" set per the §3.7 paragraph: a transient
    mid-trip suspension does not prevent the operator from attesting
    the cargo's arrival once it is delivered. The EXPIRED-and-VOIDED
    parent cases are unreachable through this endpoint because the
    parent-permit's-terminal-transitions' synchronous trip-cascade has
    already flipped the trip's own status to ABORTED, so the same-row
    state-check `trip_status == IN_TRANSIT` rejects with
    `ERR_INVALID_STATE_TRANSITION` 409 first.

    The handler does not enforce a parent-state-permissive check
    because the §3.7's "the parent-state-check on the arrive
    endpoint is `lifecycle_status in {ACTIVE, SUSPENDED}`" rule is
    structurally implied: a parent in EXPIRED-or-VOIDED has already
    cascaded the trip to ABORTED so the same-row check fails first;
    a parent in ACTIVE-or-SUSPENDED admits the arrive without an
    explicit dedicated error on the parent-side. The only state-tier
    rejection on this endpoint is the generic `ERR_INVALID_STATE_TRANSITION`
    on a non-IN_TRANSIT same-row source.

    Body: optional `version`, optional `arrive_note` 0-500 chars, optional
    `delivery_attestation` 0-1000 chars. The successful side-effects:
    `actual_arrival_at = now()`, `trip_status = COMPLETED`, the
    `version` bump and `updated_at` refresh.

    Post-arrive, the trip's in-flight window's right edge is the
    `actual_arrival_at` value, which the gps-ingest's in-window check
    reads as the upper bound of the closed-closed interval. Any
    subsequent GPS sample whose `reported_at` is past the
    `actual_arrival_at` is the `ERR_GPS_OUT_OF_WINDOW` 409 case.
    """
    trip = lookup_path_resource("Trip", trip_id, "ERR_TRIP_NOT_FOUND")
    assert_cross_tenant_ownership("Trip", trip)

    body = get_json_body()
    occ = check_occ(trip, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on the Trip during arrive.",
            details={
                "expected_version": body.get("version"),
                "actual_version": trip.get("version"),
            },
        )
    require_str(
        body, "arrive_note", length_range=OPTIONAL_NOTE_LEN_RANGE, optional=True
    )
    require_str(
        body,
        "delivery_attestation",
        length_range=ARRIVE_DELIVERY_ATTESTATION_LEN_RANGE,
        optional=True,
    )

    pre_status = trip.get("trip_status")
    if pre_status != "IN_TRANSIT":
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot arrive a trip in `trip_status` {pre_status!r}; the "
            "required source state is 'IN_TRANSIT'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["IN_TRANSIT"],
                "endpoint": "POST /v1/trips/<trip_id>/arrive",
            },
        )

    now = current_now()
    trip["actual_arrival_at"] = iso_format(now)
    trip["trip_status"] = "COMPLETED"
    bump_version(trip)

    return make_object_response(_serialize_trip(trip), http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/trips/<trip_id>/abort — PLANNED-or-IN_TRANSIT → ABORTED
# ---------------------------------------------------------------------------


@trips_bp.route("/trips/<trip_id>/abort", methods=["POST"])
def post_trip_abort(trip_id: str) -> Any:
    """The operator-initiated abort. The source-state allow-set is
    `{PLANNED, IN_TRANSIT}` — the standard pre-departure-cancel and
    the in-flight-abort branches both fire `trip_status = ABORTED`
    with `abort_reason = "OPERATOR_ABORT"`. A terminal-COMPLETED-or-
    already-ABORTED trip is the generic
    `ERR_INVALID_STATE_TRANSITION` 409.

    The body's required `reason_note` is the 1-to-500-character audit-
    cause string the §3.7 paragraph names. The optional `version`
    engages the OCC.

    The cascade-from-permit-transition variants are server-internal
    arcs in the sweep-and-the-void-issue handlers and carry the
    discriminator values `PERMIT_EXPIRED_CASCADE` and
    `PERMIT_SUSPENDED_CASCADE` respectively; the operator's direct
    abort sets the third reason value `OPERATOR_ABORT` only. The
    fourth declared-unused-in-this-scaffold reason
    `GPS_VIOLATION_LIMIT` is the §2.8 paragraph's forward-compat
    enum slot, never written by any transition in the current rule
    set.
    """
    trip = lookup_path_resource("Trip", trip_id, "ERR_TRIP_NOT_FOUND")
    assert_cross_tenant_ownership("Trip", trip)

    body = get_json_body()
    occ = check_occ(trip, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on the Trip during abort.",
            details={
                "expected_version": body.get("version"),
                "actual_version": trip.get("version"),
            },
        )
    reason_note = require_str(
        body, "reason_note", length_range=GENERIC_REASON_NOTE_LEN_RANGE
    )

    pre_status = trip.get("trip_status")
    if pre_status not in ("PLANNED", "IN_TRANSIT"):
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot abort a trip in `trip_status` {pre_status!r}; the "
            f"legal source states are 'PLANNED' or 'IN_TRANSIT'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["PLANNED", "IN_TRANSIT"],
                "endpoint": "POST /v1/trips/<trip_id>/abort",
            },
        )

    now = current_now()
    trip["aborted_at"] = iso_format(now)
    trip["abort_reason"] = "OPERATOR_ABORT"
    trip["trip_status"] = "ABORTED"
    trip.setdefault("abort_reason_note", reason_note)
    bump_version(trip)

    return make_object_response(_serialize_trip(trip), http_status=200)
