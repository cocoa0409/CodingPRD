"""The VehicleInspection endpoints — two in the scaffold's §1.5
enumeration:

  POST /v1/vehicles/<vehicle_id>/inspections — regulator appends an
                                                  inspection certificate
                                                  on the named vehicle.
                                                  The append is append-
                                                  only — the row is
                                                  immutable post-insert,
                                                  with corrections being
                                                  fresh inspections of
                                                  later `inspected_at`
                                                  that supersede the
                                                  previous "latest"
                                                  pointer on the parent
                                                  Vehicle row. The
                                                  cascade side-effect of
                                                  the insert is the
                                                  refresh of the parent
                                                  Vehicle row's three
                                                  derived
                                                  `latest_inspection_*`
                                                  fields when the new
                                                  inspection's
                                                  `inspected_at` is the
                                                  largest in the
                                                  vehicle's history,
                                                  with the lexicographic-
                                                  larger-id tie-break on
                                                  exact-equal-timestamp
                                                  pairs.

  GET  /v1/vehicles/<vehicle_id>/inspections — list the vehicle's
                                                  inspection history,
                                                  sorted by `inspected_at`
                                                  descending and ties
                                                  broken by `id`
                                                  descending so the head
                                                  of the list is the
                                                  same as the parent
                                                  Vehicle row's
                                                  `latest_inspection_id`
                                                  pointer. The optional
                                                  `outcome` query filter
                                                  narrows by the enum
                                                  value.

The PRD §3.3 paragraph names the body's-required-fields-on-the-append:
  - `inspected_at`: ISO 8601 UTC, must be at-or-before the current
    simulated-clock value (a future-dated inspection is the
    body-shape `ERR_VALIDATION` 422).
  - `outcome`: one of the three enum values `PASSED`, `FAILED`,
    `CONDITIONAL` from the §2.8 inspection-outcomes taxonomy.
  - `findings_note`: an optional 0-to-2000-character inspector's prose
    note for the audit trail.
  - `inspector_id`: an optional regulator-side opaque-string override
    of the audit's recorded inspector identity; the default is the
    request's `X-User-ID` (the regulator's opaque officer-string).

The server-set fields on the new row are the `id` and the `created_at`
from the append-only stamp helper, the `vehicle_id` derived from the
URL path, the `inspector_id` from the body's override or the request's
`X-User-Role` header's id, and the `valid_until` computed as
`inspected_at + INSPECTION_VALIDITY_DAYS` for a `PASSED` outcome (the
180-day standard from the §2.8 paragraph) or as the same instant as
`inspected_at` for a `FAILED` outcome (the zero-validity convention).
A `CONDITIONAL` outcome's `valid_until` is the same
`inspected_at + INSPECTION_VALIDITY_DAYS` as the `PASSED` case but
the permit-validity AND-chain's vehicle-leg treats `CONDITIONAL` as
non-compliant — only `PASSED` counts as compliant — so the
`valid_until` field is the nominal-validity-window-on-a-conditional-
certificate-which-doesn't-licence-hazmat-transit case.

The parent Vehicle row's `latest_inspection_*` pointer refresh's
tie-break rule for two inspections with the exact-same `inspected_at`
is "the lexicographically larger `id` wins" — a UUID-string-lex
comparison the standard implementation handles by the new row's
freshly-minted UUID's string comparison against the existing latest's
UUID-string. The §1.1 Vehicle entity's `latest_inspection_id`-field's
prose pins this tie-break direction.

The list endpoint's sort order deviates from the §2.3 H3 default
ascending-by-`created_at`: the inspection list is sorted by
`inspected_at` descending and then by `id` descending, so the head of
the response is the same row the parent Vehicle's `latest_inspection_*`
pointer chain names. The §2.3 paragraph names the inspection-list's
deviation explicitly. The `outcome` query filter is a comma-separated
subset of the three enum values, with an out-of-enum value the
body-shape `ERR_VALIDATION` 422 from the query-parsing helper.

The cross-tenant predicate on the operator's-side list-read is the
transitive-parent rule: the parent Vehicle's `company_id` must equal
the operator's `X-User-ID`. The regulator is cross-tenant exempt; the
driver and the test-harness roles have no access (their RBAC matrix
cells are the default-deny). The append endpoint is regulator-only,
the audit-integrity convention from §3.3.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import Blueprint, current_app, request

from ..auth import (
    assert_cross_tenant_ownership,
    current_principal,
    lookup_path_resource,
)
from ..clock import current_now, iso_format, iso_now, parse_iso
from ..config import (
    Constants,
    INSPECTION_FINDINGS_NOTE_LEN_RANGE,
    INSPECTION_OUTCOMES,
)
from ..envelope import (
    get_json_body,
    make_array_response,
    make_object_response,
    parse_pagination_query,
)
from ..errors import APIError
from ..store import (
    STATE_LOCK,
    bump_version,
    list_all,
    paginate,
    stamp_create_event,
    table,
)
from ..validation import (
    parse_comma_filter_query,
    require_enum,
    require_iso_datetime,
    require_str,
)


inspections_bp = Blueprint("inspections", __name__)


def _serialize_inspection(row: dict[str, Any]) -> dict[str, Any]:
    """Wire-shape of the append-only VehicleInspection event row."""
    return dict(row)


def _refresh_vehicle_latest_pointer(vehicle: dict[str, Any]) -> None:
    """Walk the vehicle's inspection history to refresh the three
    derived "latest inspection" pointer fields. The "latest" rule is
    the largest `inspected_at` timestamp across the history, with the
    tie-break being the lexicographically-larger `id` per the §1.1
    Vehicle entity-prose. The helper is called by the append handler
    after the new row has been inserted into the table; the helper's
    job is to compute the new pointer values from the post-insert
    state and write them to the parent Vehicle row, then bump the
    parent's `version` and refresh its `updated_at`.

    The §2.10 H3 paragraph's "the parent Vehicle row's `version` bumps
    on the inspection-append's atomic side-effect" rule is realized
    here.
    """
    vehicle_id = vehicle["id"]
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]
    # Walk every inspection on the vehicle and pick the canonical
    # latest. The `id` tie-break direction (larger-lex-wins) is
    # consistent with the list endpoint's sort-direction-on-the-
    # ascending-id tie-break.
    candidate: dict[str, Any] | None = None
    for ins in table("VehicleInspection").values():
        if ins.get("vehicle_id") != vehicle_id:
            continue
        if candidate is None:
            candidate = ins
            continue
        ts_new = ins.get("inspected_at", "")
        ts_cur = candidate.get("inspected_at", "")
        if ts_new > ts_cur:
            candidate = ins
        elif ts_new == ts_cur:
            # Lex-larger id wins on the tie.
            if ins.get("id", "") > candidate.get("id", ""):
                candidate = ins

    if candidate is None:
        # No inspections — the pointers are null.
        vehicle["latest_inspection_id"] = None
        vehicle["latest_inspection_outcome"] = None
        vehicle["latest_inspection_valid_until"] = None
    else:
        vehicle["latest_inspection_id"] = candidate.get("id")
        vehicle["latest_inspection_outcome"] = candidate.get("outcome")
        vehicle["latest_inspection_valid_until"] = candidate.get("valid_until")

    bump_version(vehicle)


@inspections_bp.route("/vehicles/<vehicle_id>/inspections", methods=["POST"])
def post_create_inspection(vehicle_id: str) -> Any:
    """Append an inspection certificate. The regulator-only RBAC cell.
    The body's `inspected_at`-not-in-the-future rule and the
    `outcome`-enum-membership rule are the standard body-shape checks.
    The `valid_until` field is computed server-side from the
    `inspected_at` plus the `INSPECTION_VALIDITY_DAYS` constant (for
    `PASSED`, the canonical 180-day forward validity; for `FAILED`,
    the zero-forward-validity instant-equal-to-`inspected_at` value;
    for `CONDITIONAL`, the same nominal-180-day-window the PASSED
    case uses, with the permit-validity AND-chain's vehicle-leg
    treating CONDITIONAL as non-compliant despite the non-zero
    nominal-window).

    The cascade side-effect refreshes the parent Vehicle row's three
    derived `latest_inspection_*` pointer fields. The atomic-pair
    write (new inspection row inserted into the
    `VehicleInspection` table and the parent Vehicle's pointer
    fields refreshed) is under the global `STATE_LOCK` so the
    observability of "the new inspection exists and the parent's
    pointer points at it" is atomic from a concurrent reader's
    perspective.
    """
    vehicle = lookup_path_resource("Vehicle", vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]

    inspected_at_dt = require_iso_datetime(body, "inspected_at")
    assert inspected_at_dt is not None
    outcome = require_enum(body, "outcome", allowed=INSPECTION_OUTCOMES)
    findings_note = require_str(
        body,
        "findings_note",
        length_range=INSPECTION_FINDINGS_NOTE_LEN_RANGE,
        optional=True,
    )
    if findings_note is None:
        findings_note = ""
    # The optional inspector_id-override field. If absent we default
    # to the regulator's request `X-User-Role`-paired `X-User-ID` which
    # is the regulator's opaque officer-id string per the §2.1
    # opaque-identity rule.
    role, requester_user_id = current_principal()
    inspector_id_override = require_str(
        body, "inspector_id", length_range=(1, 256), optional=True
    )
    inspector_id = inspector_id_override or requester_user_id

    # The `inspected_at`-at-or-before-now rule.
    now = current_now()
    if inspected_at_dt > now:
        raise APIError(
            "ERR_VALIDATION",
            f"'inspected_at' must be at or before the current logical-"
            f"clock value; got {iso_format(inspected_at_dt)!r}, now is "
            f"{iso_format(now)!r}.",
            details={
                "field": "inspected_at",
                "value": iso_format(inspected_at_dt),
                "now": iso_format(now),
            },
        )

    # The `valid_until` computation per the outcome.
    if outcome == "FAILED":
        valid_until_dt = inspected_at_dt
    else:
        # PASSED or CONDITIONAL: the standard
        # `inspected_at + INSPECTION_VALIDITY_DAYS` validity end.
        valid_until_dt = inspected_at_dt + timedelta(
            days=constants.inspection_validity_days
        )

    row: dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "inspector_id": inspector_id,
        "inspected_at": iso_format(inspected_at_dt),
        "outcome": outcome,
        "valid_until": iso_format(valid_until_dt),
        "findings_note": findings_note,
    }
    stamp_create_event(row)

    # Atomic insert-and-parent-pointer-refresh under the global lock
    # so the post-commit observability is "the new inspection exists
    # and the parent's `latest_inspection_*` fields reflect it (or the
    # latest-by-timestamp invariant if a later-timestamp existing
    # inspection still wins the tie-break)".
    with STATE_LOCK:
        table("VehicleInspection")[row["id"]] = row
        _refresh_vehicle_latest_pointer(vehicle)

    # The response is the inspection row plus a small parent-vehicle
    # summary the §1.5 row's `response_payload_schema` names. We embed
    # the parent's three derived pointer fields' post-refresh values
    # in a `parent_vehicle_pointers` sub-object so the test layer can
    # assert against the atomic-pair-write's outcome without a
    # separate parent-fetch.
    response_data: dict[str, Any] = dict(row)
    response_data["parent_vehicle_pointers"] = {
        "vehicle_id": vehicle["id"],
        "latest_inspection_id": vehicle.get("latest_inspection_id"),
        "latest_inspection_outcome": vehicle.get("latest_inspection_outcome"),
        "latest_inspection_valid_until": vehicle.get(
            "latest_inspection_valid_until"
        ),
        "vehicle_version": vehicle.get("version"),
    }

    return make_object_response(response_data, http_status=201)


@inspections_bp.route("/vehicles/<vehicle_id>/inspections", methods=["GET"])
def list_inspections(vehicle_id: str) -> Any:
    """List the vehicle's inspection history. The sort-order deviation
    from the global default is the `inspected_at`-descending,
    `id`-descending order so the head of the response is the row the
    parent Vehicle's `latest_inspection_id` pointer names. The
    pagination contract is the standard `(limit, offset)` pair from
    `parse_pagination_query`. The optional `outcome` query filter is
    a comma-separated subset of the three-value
    `INSPECTION_OUTCOMES` enum, with an out-of-enum value the
    body-shape `ERR_VALIDATION` 422 from the query-parser helper.

    The cross-tenant predicate is the transitive-parent rule against
    the vehicle's `company_id`. The existence-tier-on-the-vehicle-path-
    parameter fires before the cross-tenant per the §2.6 priority
    ordering.

    The HTTP status is 200; the response is the standard array
    envelope with the four pagination meta fields.
    """
    vehicle = lookup_path_resource(
        "Vehicle", vehicle_id, "ERR_VEHICLE_NOT_FOUND"
    )
    assert_cross_tenant_ownership("Vehicle", vehicle)

    limit, offset = parse_pagination_query()
    outcome_filter_raw = request.args.get("outcome")
    outcome_filter = parse_comma_filter_query(
        outcome_filter_raw, allowed=INSPECTION_OUTCOMES, field_name="outcome"
    )

    rows = [
        ins
        for ins in list_all("VehicleInspection")
        if ins.get("vehicle_id") == vehicle_id
        and (outcome_filter is None or ins.get("outcome") in outcome_filter)
    ]
    # Sort `inspected_at` descending, then `id` descending — the
    # head-of-the-list is the parent's `latest_inspection_id` row.
    rows.sort(
        key=lambda r: (r.get("inspected_at", ""), r.get("id", "")),
        reverse=True,
    )

    page, total, has_more = paginate(rows, limit, offset)
    payload = [_serialize_inspection(r) for r in page]
    return make_array_response(
        payload, limit=limit, offset=offset, total_count=total, has_more=has_more
    )
