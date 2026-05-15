"""The GPSReport endpoints — two in the scaffold's §1.5 enumeration:

  POST /v1/trips/<trip_id>/gps-reports — the operator's fleet-tracking
                                          back-end pushes a position-and-
                                          speed sample for an
                                          in-progress trip. The handler
                                          walks the §2.7 priority-tier
                                          chain: existence on the trip-
                                          id, cross-tenant on the trip's
                                          transitive-parent company, the
                                          optional Idempotency-Key
                                          slot lookup at priority 550
                                          (replay on body-hash match,
                                          409 `ERR_IDEMPOTENCY_KEY_REUSED`
                                          on body-hash mismatch), the
                                          body-shape validation on the
                                          four-field position-and-time-
                                          and-speed quartet, the
                                          in-window check at the
                                          safety-tier priority 509
                                          firing `ERR_GPS_OUT_OF_WINDOW`,
                                          the strict-greater-than
                                          monotonicity check at priority
                                          512 firing
                                          `ERR_GPS_OUT_OF_ORDER`, the
                                          parent-permit-active gate at
                                          the safety-tier-priority-515
                                          firing
                                          `ERR_PERMIT_NOT_ACTIVE` on a
                                          SUSPENDED parent, the
                                          gps_violation_classification
                                          calculation that computes the
                                          two boolean violation flags
                                          and the off-route distance,
                                          the atomic insert of the
                                          GPSReport row and the zero-
                                          one-or-two auto-Penalty rows,
                                          the cascade onto the
                                          subject driver's
                                          `current_rolling_points`
                                          cache and the threshold-
                                          crossover-driven
                                          `VALID -> INVALID`
                                          hazmat-endorsement-status
                                          auto-flip in the same
                                          transaction, and the parent
                                          Trip's `latest_gps_at`
                                          cursor-advance and
                                          `gps_violation_count`
                                          increment.

  GET  /v1/trips/<trip_id>/gps-reports — the paginated read of the
                                          trip's GPS-stream, sorted
                                          ascending by `reported_at`
                                          and tie-broken ascending by
                                          `id` so the stream reads
                                          chronologically. The optional
                                          `violation_only` boolean query
                                          filter narrows to reports
                                          whose `auto_penalty_ids` array
                                          is non-empty per the §3.7
                                          paragraph's "the violation-
                                          only filter selects the
                                          reports that triggered at
                                          least one auto-Penalty" rule.

The PRD §2.10 H3 paragraph's idempotency-key contract is the slot-
keyed-by-the-`(trip_id, key)`-pair scheme implemented in the
`idempotency` module. The replay-on-body-hash-match returns the
original 201 response payload with the `meta.replayed = True` flag
on the response envelope's meta block; the body-hash-mismatch fires
the dedicated `ERR_IDEMPOTENCY_KEY_REUSED` 409 error.

The PRD §3.8 paragraph names the priority-509-before-512-before-515
internal sub-ordering of the safety-tier checks on this endpoint — the
in-window check (`ERR_GPS_OUT_OF_WINDOW`) fires before the
monotonicity check (`ERR_GPS_OUT_OF_ORDER`) and the parent-active gate
fires after both. The rule-5 priority-conflict-C pin is the
within-tier integer-priority disambiguation between the window-out
and the order-out cases.

The cascade chain on a successful insert is the rule-4 cascade-A's
depth-four chain documented in the §3.2 closing paragraph: the
GPSReport insert (hop 1), the auto-Penalty inserts (hop 2, one or two
rows depending on the per-flavour violation flags), the subject
Driver's `current_rolling_points` cache recompute and the threshold-
crossover-driven `hazmat_endorsement_status` auto-flip in the same
transaction (hop 3), and the deferred cross-aggregate cascade onto the
permits whose `authorized_driver_ids` contains the just-flipped driver
that fires `ACTIVE -> SUSPENDED` on the next verify-compliance pass
(hop 4, fired through the sweep or an explicit verify-compliance
call rather than synchronously here).

The body-shape rules on the four fields are the standard range checks
from `validation`: `lat` in `[-90, 90]`, `lon` in `[-180, 180]`,
`speed_kph` nonnegative, `heading_deg` in `[0, 360]`. The `reported_at`
ISO 8601 millisecond-precision parse-and-monotonicity check is the
combination of `parse_iso` and the trip's `latest_gps_at` strict-
greater-than comparison.

The list endpoint's sort-order deviation from the §2.3 H3 default of
ascending-by-`created_at` is the §2.3 paragraph's "the GPS-report list
sorts by `reported_at` ascending then by `id` ascending so the stream
reads chronologically" rule. The `violation_only` query parameter is
the boolean-typed filter that the standard query-string convention
recognizes as the strings `"true"`/`"false"` (case-insensitive); a
non-boolean string is the body-shape catch-all
`ERR_VALIDATION` 422.

The cross-tenant predicate on the operator side is the trip-to-
permit-to-company transitive chain the §2.6 paragraph names. The
RegulatorOfficer is cross-tenant exempt on the read endpoint. The
Driver-role has no GPS access at all per the §1.7 matrix's column-
default-deny on the GPS endpoints, on the §1.7-closing-paragraph's
"the driver's window into their own performance is the penalty-
summary digest, not the raw GPS stream" data-minimization choice.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Blueprint, current_app, request

from ..auth import (
    assert_cross_tenant_ownership,
    current_principal,
    lookup_path_resource,
)
from ..calculations import (
    driver_penalty_point_rolling_total,
    driver_threshold_crossed,
    gps_violation_classification,
)
from ..clock import current_now, iso_format, iso_now, parse_iso
from ..config import (
    AUTO_PENALTY_REASON_OFF_ROUTE,
    AUTO_PENALTY_REASON_SPEED,
    Constants,
    HEADER_IDEMPOTENCY_KEY,
)
from ..envelope import (
    get_json_body,
    get_optional_idempotency_key,
    make_array_response,
    make_object_response,
    parse_pagination_query,
)
from ..errors import APIError
from ..idempotency import hash_body, lookup_slot, write_slot
from ..store import (
    STATE_LOCK,
    bump_version,
    find,
    list_all,
    paginate,
    stamp_create_event,
    table,
)
from ..validation import (
    require_iso_datetime,
    require_number,
    require_str,
    validate_heading_deg,
    validate_idempotency_key_header,
    validate_lat_lon,
)


gps_bp = Blueprint("gps", __name__)


def _serialize_gps(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def _serialize_penalty(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)


@gps_bp.route("/trips/<trip_id>/gps-reports", methods=["POST"])
def post_gps_report(trip_id: str) -> Any:
    """The GPS-ingest endpoint. The handler-side walk is the §2.7
    priority-ordered tier chain with the §3.8's intra-tier-509-then-
    512-then-515 sub-ordering on the safety-tier's three GPS-specific
    checks.

    The optional `Idempotency-Key` header opens the per-trip slot's
    lookup. The slot's stored body-hash and the request body's hash
    are compared; an equal pair is the standard replay path (the
    cached response payload is returned with the `meta.replayed =
    True` flag), an unequal pair is the dedicated
    `ERR_IDEMPOTENCY_KEY_REUSED` 409 error.

    The §1.4 §1.2.1 concurrency_rule on the same-`reported_at` race —
    two concurrent ingests on the same trip with the same
    `reported_at` value and different bodies/keys — is serialized by
    the global `STATE_LOCK` plus the strict-greater-than monotonicity
    check on the trip's `latest_gps_at` cursor. The first-arrival's
    insert sets the cursor to its own `reported_at`; the second-
    arrival's monotonicity-check sees its `reported_at` equal to the
    cursor and rejects with `ERR_GPS_OUT_OF_ORDER` 409 per the §2.10
    paragraph's race-resolution rule 2.
    """
    trip = lookup_path_resource("Trip", trip_id, "ERR_TRIP_NOT_FOUND")
    # The cross-tenant predicate on the trip's transitive-parent
    # (the trip's parent permit's `company_id`). The matrix-tier's
    # allow-set for this endpoint is the singleton CompanyOperator,
    # caught by the auth middleware's RBAC check on the non-operator
    # roles.
    assert_cross_tenant_ownership("Trip", trip)

    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]

    # The optional Idempotency-Key header.
    raw_idem_key = get_optional_idempotency_key()
    idem_key = validate_idempotency_key_header(raw_idem_key)

    # The body-shape validation on the four position-and-time-and-
    # speed fields plus the optional heading.
    reported_at_dt = require_iso_datetime(body, "reported_at")
    assert reported_at_dt is not None
    lat = require_number(body, "lat", range_inclusive=(-90.0, 90.0))
    lon = require_number(body, "lon", range_inclusive=(-180.0, 180.0))
    assert lat is not None and lon is not None
    validate_lat_lon(lat, lon)
    speed_kph = require_number(body, "speed_kph", nonnegative=True)
    assert speed_kph is not None
    heading_deg = require_number(
        body, "heading_deg", range_inclusive=(0.0, 360.0), optional=True
    )
    if heading_deg is None:
        heading_deg = 0.0
    else:
        validate_heading_deg(float(heading_deg))

    # The idempotency-slot lookup. If the key is present and the slot
    # is full, we either replay the original 201 (body-hash match) or
    # reject (body-hash mismatch). The hash is computed against the
    # body's canonical JSON serialization, which is identity-stable
    # under key-ordering-and-whitespace differences in the request.
    if idem_key is not None:
        body_hash = hash_body(body)
        slot = lookup_slot(trip_id, idem_key)
        if slot is not None:
            stored_hash, stored_payload, stored_status = slot
            if stored_hash == body_hash:
                # Replay-on-match. The response is the original
                # payload with the standard envelope's meta block
                # gaining the `replayed: true` flag the §2.10
                # paragraph names.
                return make_object_response(
                    stored_payload,
                    http_status=stored_status,
                    extra_meta={"replayed": True},
                )
            # Different body, same key — the rejection.
            raise APIError(
                "ERR_IDEMPOTENCY_KEY_REUSED",
                f"Idempotency-Key {idem_key!r} on trip {trip_id!r} is "
                f"already in use with a different request body.",
                details={
                    "trip_id": trip_id,
                    "idempotency_key": idem_key,
                    "observed_body_hash": body_hash,
                    "cached_body_hash": stored_hash,
                },
            )

    # The in-window check at the safety-tier priority 509. The trip's
    # in-flight interval is `[actual_departure_at, min(actual_arrival_at,
    # aborted_at, now())]` (closed on the left at the actual departure,
    # closed on the right at the appropriate terminal-or-now boundary).
    # A still-PLANNED trip has a null `actual_departure_at` so the
    # interval is the empty set and any GPS sample is out-of-window.
    # A terminal-COMPLETED or terminal-ABORTED trip has its right edge
    # at the recorded terminal-timestamp; a sample whose `reported_at`
    # exceeds the terminal-timestamp is out-of-window.
    actual_departure_at_str = trip.get("actual_departure_at")
    if actual_departure_at_str is None:
        raise APIError(
            "ERR_GPS_OUT_OF_WINDOW",
            "Trip is still in PLANNED state — no in-flight window exists "
            f"for accepting a GPS sample on it.",
            details={
                "trip_id": trip_id,
                "trip_status": trip.get("trip_status"),
            },
        )
    actual_departure_at = parse_iso(actual_departure_at_str)
    if reported_at_dt < actual_departure_at:
        raise APIError(
            "ERR_GPS_OUT_OF_WINDOW",
            f"Sample's `reported_at` {iso_format(reported_at_dt)!r} is "
            f"before the trip's `actual_departure_at` "
            f"{iso_format(actual_departure_at)!r}.",
            details={
                "trip_id": trip_id,
                "reported_at": iso_format(reported_at_dt),
                "actual_departure_at": iso_format(actual_departure_at),
            },
        )
    now = current_now()
    # The terminal-right-edge candidates.
    terminal_candidates: list[datetime] = []
    aa_str = trip.get("actual_arrival_at")
    if aa_str is not None:
        terminal_candidates.append(parse_iso(aa_str))
    ab_str = trip.get("aborted_at")
    if ab_str is not None:
        terminal_candidates.append(parse_iso(ab_str))
    # On an in-flight (IN_TRANSIT) trip with neither terminal-timestamp
    # set, the right edge is the current logical-clock value.
    if not terminal_candidates:
        right_edge = now
    else:
        right_edge = min(terminal_candidates)
    # The closed-right boundary on the in-window interval. The §3.8
    # paragraph's wording is "the in-window interval is
    # `[actual_departure_at, min(actual_arrival_at, aborted_at,
    # now())]`" with the right-edge inclusive — so the sample whose
    # `reported_at == right_edge` exactly is in-window. The
    # strict-greater-than rejection fires on the strictly-past case.
    if reported_at_dt > right_edge:
        raise APIError(
            "ERR_GPS_OUT_OF_WINDOW",
            f"Sample's `reported_at` {iso_format(reported_at_dt)!r} is "
            f"past the trip's in-flight right-edge "
            f"{iso_format(right_edge)!r}.",
            details={
                "trip_id": trip_id,
                "reported_at": iso_format(reported_at_dt),
                "in_flight_right_edge": iso_format(right_edge),
                "actual_arrival_at": aa_str,
                "aborted_at": ab_str,
                "now": iso_format(now),
                "trip_status": trip.get("trip_status"),
            },
        )

    # The strict-greater-than monotonicity check at priority 512.
    latest_gps_at_str = trip.get("latest_gps_at")
    latest_gps_at = (
        parse_iso(latest_gps_at_str) if latest_gps_at_str else None
    )
    if latest_gps_at is not None and reported_at_dt <= latest_gps_at:
        raise APIError(
            "ERR_GPS_OUT_OF_ORDER",
            f"Sample's `reported_at` {iso_format(reported_at_dt)!r} is "
            f"not strictly greater than the trip's `latest_gps_at` "
            f"cursor of {iso_format(latest_gps_at)!r}.",
            details={
                "trip_id": trip_id,
                "reported_at": iso_format(reported_at_dt),
                "latest_gps_at": iso_format(latest_gps_at),
                "rule": "strict-greater-than monotonicity "
                "(rule-8-overlap-B closed-on-prior-edge interval-"
                "semantics).",
            },
        )

    # The parent-permit-active gate at priority 515. The §3.8 paragraph
    # names the precedence as "the parent-permit-active gate fires
    # after the in-window and monotonicity checks", so the EXPIRED-
    # and-VOIDED-cascaded-aborts cases are caught earlier by the
    # window-check (the trip's `aborted_at` set on the cascade-abort
    # gives the in-window right edge a value, and the `reported_at`
    # past that right-edge is the window error). The
    # `ERR_PERMIT_NOT_ACTIVE` here fires solely on the live-suspension
    # case where the permit is SUSPENDED but the trip itself is still
    # in-flight IN_TRANSIT and the in-window check passes.
    permit = find("Permit", trip.get("permit_id"))
    if permit is None:
        # Defensive — the foreign-key invariant should hold. We map
        # to the canonical not-found.
        raise APIError(
            "ERR_PERMIT_NOT_FOUND",
            "Parent permit of the trip does not resolve.",
            details={"trip_id": trip_id, "permit_id": trip.get("permit_id")},
        )
    permit_status = permit.get("lifecycle_status")
    if permit_status != "ACTIVE":
        raise APIError(
            "ERR_PERMIT_NOT_ACTIVE",
            f"Parent permit's `lifecycle_status` is {permit_status!r}, "
            "not 'ACTIVE'; the gps-ingest path is gated on a fully-"
            "active permit.",
            details={
                "trip_id": trip_id,
                "permit_id": permit["id"],
                "lifecycle_status": permit_status,
                "priority": 515,
            },
        )

    # The gps_violation_classification computation.
    route = find("TransportRoute", permit.get("route_id"))
    if route is None:
        raise APIError(
            "ERR_ROUTE_NOT_FOUND",
            "Parent permit's route does not resolve.",
            details={
                "permit_id": permit["id"],
                "route_id": permit.get("route_id"),
            },
        )
    route_polyline = route.get("polyline") or []
    classification = gps_violation_classification(
        gps_report={
            "speed_kph": float(speed_kph),
            "lat": float(lat),
            "lon": float(lon),
        },
        route_polyline=list(route_polyline),
        constants=constants,
    )

    # Build the new GPSReport row.
    gps_row: dict[str, Any] = {
        "trip_id": trip_id,
        "reported_at": iso_format(reported_at_dt),
        "received_at": iso_format(now),
        "lat": float(lat),
        "lon": float(lon),
        "speed_kph": float(speed_kph),
        "heading_deg": float(heading_deg),
        "off_route_distance_m": float(classification["off_route_distance_m"]),
        "idempotency_key": idem_key,
        "auto_penalty_ids": [],  # to be filled in the same transaction
    }
    stamp_create_event(gps_row)

    # The atomic write-and-cascade transaction. Everything from the
    # GPS-row insert through the auto-Penalty inserts, the driver-
    # cache-recompute, the threshold-crossover-driven-status-flip, and
    # the parent-Trip's `latest_gps_at`-and-`gps_violation_count`
    # bumps happens under the single global lock so the post-commit
    # observability is "the new row exists, the auto-penalties exist,
    # the cursor has advanced, the count has incremented, the
    # driver's cache reflects the new total, the driver's status
    # reflects the threshold-crossover, the parent Trip's `version`
    # has bumped".
    with STATE_LOCK:
        # Insert the GPSReport row.
        table("GPSReport")[gps_row["id"]] = gps_row

        # Compute the auto-Penalty rows. The two violation flavours
        # are independent; a single sample may fire zero, one, or two.
        auto_penalty_ids: list[str] = []
        driver_id = trip.get("driver_id")
        driver = find("Driver", driver_id) if driver_id else None

        def _create_auto_penalty(
            source_enum: str, points: int, reason_text: str
        ) -> str:
            new_pen: dict[str, Any] = {
                "subject_type": "DRIVER",
                "subject_id": driver_id,
                "points_value": int(points),
                "source": source_enum,
                "source_gps_report_id": gps_row["id"],
                "trip_id": trip_id,
                "observed_at": iso_format(reported_at_dt),
                "void_status": "ACTIVE",
                "upheld_at": None,
                "upheld_by": None,
                "reason_note": reason_text,
            }
            stamp_create_event(new_pen)
            table("Penalty")[new_pen["id"]] = new_pen
            return new_pen["id"]

        if classification["speed_violated"]:
            pid = _create_auto_penalty(
                "GPS_VIOLATION_SPEED",
                int(classification["speed_points_value"]),
                AUTO_PENALTY_REASON_SPEED,
            )
            auto_penalty_ids.append(pid)
        if classification["off_route_violation"]:
            pid = _create_auto_penalty(
                "GPS_VIOLATION_OFF_ROUTE",
                int(classification["off_route_points_value"]),
                AUTO_PENALTY_REASON_OFF_ROUTE,
            )
            auto_penalty_ids.append(pid)

        gps_row["auto_penalty_ids"] = auto_penalty_ids

        # The cascade onto the subject driver's cached
        # `current_rolling_points` and the threshold-crossover-driven
        # status auto-flip. The rolling-points recompute uses the
        # canonical function so the cache value is the exact integer
        # the live-mode evaluation would return.
        driver_status_flip: str | None = None
        if driver is not None and auto_penalty_ids:
            new_total = driver_penalty_point_rolling_total(
                driver_id, now, constants
            )
            driver["current_rolling_points"] = new_total
            bump_version(driver)
            if (
                driver.get("hazmat_endorsement_status") == "VALID"
                and driver_threshold_crossed(new_total, constants)
            ):
                driver["hazmat_endorsement_status"] = "INVALID"
                bump_version(driver)
                driver_status_flip = "VALID_TO_INVALID"

        # The parent Trip's derived-fields update.
        trip["latest_gps_at"] = iso_format(reported_at_dt)
        trip["gps_violation_count"] = int(trip.get("gps_violation_count", 0)) + len(auto_penalty_ids)
        bump_version(trip)

    # The response payload. The §3.8 paragraph names the
    # `cascade_summary` sub-object with the driver's post-cascade
    # `current_rolling_points` and `hazmat_endorsement_status` for the
    # test layer's same-transaction assertion. We embed it on the
    # response.
    response_data = _serialize_gps(gps_row)
    response_data["auto_penalty_ids"] = list(auto_penalty_ids)
    response_data["classification"] = {
        "speed_violated": bool(classification["speed_violated"]),
        "off_route_violation": bool(classification["off_route_violation"]),
        "off_route_distance_m": float(classification["off_route_distance_m"]),
        "speed_points_value": int(classification["speed_points_value"]),
        "off_route_points_value": int(classification["off_route_points_value"]),
    }
    cascade_summary: dict[str, Any] = {
        "auto_penalty_count": len(auto_penalty_ids),
        "auto_penalty_ids": list(auto_penalty_ids),
    }
    if driver is not None:
        cascade_summary["driver_id"] = driver["id"]
        cascade_summary["driver_current_rolling_points"] = int(
            driver.get("current_rolling_points", 0)
        )
        cascade_summary["driver_hazmat_endorsement_status"] = driver.get(
            "hazmat_endorsement_status"
        )
        cascade_summary["driver_status_flip"] = driver_status_flip
    response_data["cascade_summary"] = cascade_summary
    response_data["trip_latest_gps_at"] = trip["latest_gps_at"]
    response_data["trip_gps_violation_count"] = int(trip["gps_violation_count"])

    # Write the idempotency-slot if the key was provided. The stored
    # payload is the response's `data` block — the next replay of the
    # same key-and-body returns this object verbatim under the
    # idempotency contract.
    if idem_key is not None:
        write_slot(
            trip_id=trip_id,
            key=idem_key,
            body_hash=hash_body(body),
            response_payload=response_data,
            http_status=201,
        )

    return make_object_response(response_data, http_status=201)


@gps_bp.route("/trips/<trip_id>/gps-reports", methods=["GET"])
def list_gps_reports(trip_id: str) -> Any:
    """The paginated GPS-stream read. The sort-order deviation is
    ascending by `reported_at` then ascending by `id` so the stream
    reads chronologically. The optional `violation_only` boolean query
    parameter narrows to reports whose `auto_penalty_ids` array is
    non-empty.

    The cross-tenant predicate via the trip-to-permit-to-company
    transitive chain. The Driver-and-TestHarness roles have no access
    per the matrix.
    """
    trip = lookup_path_resource("Trip", trip_id, "ERR_TRIP_NOT_FOUND")
    assert_cross_tenant_ownership("Trip", trip)

    limit, offset = parse_pagination_query()
    raw_vo = request.args.get("violation_only")
    if raw_vo is None:
        violation_only = False
    else:
        lower = raw_vo.strip().lower()
        if lower == "true":
            violation_only = True
        elif lower == "false":
            violation_only = False
        else:
            raise APIError(
                "ERR_VALIDATION",
                f"'violation_only' query parameter must be 'true' or "
                f"'false'; got {raw_vo!r}.",
                details={"field": "violation_only", "value": raw_vo},
            )

    rows = [
        r
        for r in list_all("GPSReport")
        if r.get("trip_id") == trip_id
        and (not violation_only or len(r.get("auto_penalty_ids") or []) > 0)
    ]
    rows.sort(key=lambda r: (r.get("reported_at", ""), r.get("id", "")))

    page, total, has_more = paginate(rows, limit, offset)
    payload = [_serialize_gps(r) for r in page]
    return make_array_response(
        payload, limit=limit, offset=offset, total_count=total, has_more=has_more
    )
