"""The Penalty endpoints — three in the scaffold's §1.5 enumeration:

  POST /v1/penalties                  — regulator's manual penalty-
                                          create. The body's
                                          `(subject_type, subject_id)`
                                          pair names the polymorphic
                                          subject; the optional
                                          `trip_id` carries the
                                          trip-context for an in-trip
                                          off-line observation. The
                                          existence walk on the
                                          subject-id resolves to the
                                          per-subject-kind row in the
                                          right table; the optional
                                          trip-id is the standard
                                          existence-tier check. The
                                          `points_value` is the
                                          integer in the inclusive
                                          range `[1, 50]` per the §2.4
                                          paragraph on the manual-
                                          penalty body's-`points_value`
                                          bounds. The `observed_at`
                                          ISO-8601 datetime must be at-
                                          or-before the current
                                          logical-clock value (the
                                          standard "no future-dated
                                          observations" rule from §2.9).
                                          The `reason_note` is the
                                          required 1-to-500-character
                                          audit-cause string.

                                          The cascade on a `DRIVER`
                                          subject mirrors the GPS-
                                          auto-penalty's same-transaction
                                          cascade: the new
                                          `current_rolling_points`
                                          recompute on the Driver row's
                                          cached field, and the
                                          threshold-crossover-driven
                                          `VALID -> INVALID`
                                          hazmat-endorsement-status
                                          auto-flip in the same atomic
                                          transaction. The `COMPANY`
                                          and `VEHICLE` subject paths
                                          insert the Penalty row but
                                          do not drive any automatic
                                          downstream state-machine
                                          transition per the §2.8
                                          paragraph's "the `COMPANY`
                                          and `VEHICLE` subject types
                                          are recorded in the same
                                          Penalty table for the audit
                                          trail but do not drive any
                                          automatic state transition on
                                          their subject's home
                                          aggregate" reservation rule.

                                          The deferred cross-aggregate
                                          cascade onto the permits
                                          whose `authorized_driver_ids`
                                          contains the just-touched
                                          driver is the same depth-three-
                                          from-the-manual-penalty
                                          chain (penalty-insert,
                                          driver-cache-and-status flip,
                                          next-verify-compliance-on-
                                          each-affected-permit fires
                                          the SUSPENDED transition).

  POST /v1/penalties/<penalty_id>/uphold — the regulator's appeal-
                                          uphold compensating action.
                                          Flips the row's
                                          `void_status` from `ACTIVE`
                                          to `UPHELD`, sets the
                                          `upheld_at` and the
                                          `upheld_by` fields, prepends
                                          the body's `uphold_reason` to
                                          the existing `reason_note`
                                          under the canonical
                                          "UPHELD-ON-APPEAL: ..."
                                          marker per the §2.4 paragraph.
                                          The closed-right 30-day
                                          appeal-window from the
                                          penalty's `observed_at`
                                          fires
                                          `ERR_APPEAL_WINDOW_CLOSED`
                                          409 on a duration that
                                          strictly exceeds the
                                          constant. The
                                          source-state-must-be-ACTIVE
                                          rule fires the standard
                                          generic state error on an
                                          already-upheld row.

                                          The cascade on a DRIVER-
                                          subject uphold is the same-
                                          transaction recompute of the
                                          driver's
                                          `current_rolling_points`
                                          (the upheld row's contribution
                                          is now zero per the §2.11
                                          paragraph's invariant), with
                                          the §3.8's
                                          keep-the-regulator-in-the-
                                          loop convention forbidding
                                          the automatic upward
                                          `INVALID -> VALID` flip — the
                                          driver remains in the
                                          status's-cause-removed-but-
                                          the-attestation-not-yet-
                                          refreshed limbo until the
                                          regulator separately calls the
                                          refresh-endorsement
                                          endpoint.

  GET  /v1/drivers/<driver_id>/penalty-summary — the driver's-side
                                          aggregated digest of the
                                          rolling-points-and-permits-
                                          standing. The §3.8 paragraph
                                          names the canonical shape of
                                          the response: the
                                          `current_rolling_points`
                                          integer recomputed at the
                                          read moment, the
                                          `threshold` constant the
                                          consumer compares against,
                                          the `hazmat_endorsement_status`
                                          enum, the lists of active-
                                          and-upheld penalties in the
                                          rolling window, and the
                                          `permits_currently_listing_this_driver`
                                          array with the per-permit
                                          snapshot-and-live flag pair
                                          for the dual-variant axis
                                          observation.

The three-role allow-set on the penalty-summary endpoint matches the
driver-row-read endpoint's three-role-and-the-self-only-driver-cell
RBAC matrix entry; the cross-tenant predicate for the operator is the
transitive-tenant on the driver's `company_id`, for the regulator it
is the cross-tenant exemption, and for the driver-role it is the
self-only-on-the-path-id rule at priority 531.

The §2.11 closing paragraph's points-axis conservation invariant is
the "create-then-uphold pair on the same penalty within the rolling
window leaves the rolling total at the pre-create value" identity. The
implementation realizes this by the standard from-scratch-recompute on
the cached `current_rolling_points` field after each penalty-create
and each uphold: the function's filter on the row's `void_status ==
"ACTIVE"` predicate excludes the just-upheld row, so the algebraic
cancellation is exact.

The PRD §2.4 closing paragraph's "the on-disk `reason_note` after a
successful uphold encodes both the original and the appeal-resolution
text" rule is realized by the prepend pattern: the new note's
canonical prefix is `"UPHELD-ON-APPEAL: <uphold_reason>; ORIGINAL: "`
followed by the prior `reason_note` value. The pre-uphold
`reason_note` is preserved verbatim after the marker so the audit-
trail can read both.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import Blueprint, current_app

from ..auth import (
    assert_cross_tenant_ownership,
    current_principal,
    lookup_path_resource,
)
from ..calculations import (
    driver_penalty_point_rolling_total,
    driver_threshold_crossed,
)
from ..clock import current_now, iso_format, iso_now, parse_iso
from ..config import (
    Constants,
    PENALTY_POINTS_VALUE_RANGE,
    PENALTY_REASON_NOTE_LEN_RANGE,
    PENALTY_SUBJECT_TYPES,
    PENALTY_UPHOLD_REASON_LEN_RANGE,
)
from ..envelope import get_json_body, make_object_response
from ..errors import APIError, ENTITY_TO_NOT_FOUND
from ..store import (
    STATE_LOCK,
    bump_version,
    find,
    list_all,
    stamp_create_event,
    table,
)
from ..validation import (
    require_enum,
    require_int,
    require_iso_datetime,
    require_str,
)


penalties_bp = Blueprint("penalties", __name__)


_SUBJECT_TYPE_TO_ENTITY: dict[str, str] = {
    "DRIVER": "Driver",
    "COMPANY": "TransportCompany",
    "VEHICLE": "Vehicle",
}


def _serialize_penalty(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)


# ---------------------------------------------------------------------------
# POST /v1/penalties — regulator's manual penalty issuance
# ---------------------------------------------------------------------------


@penalties_bp.route("/penalties", methods=["POST"])
def post_create_penalty() -> Any:
    """The regulator's manual penalty-issuance endpoint. The body
    carries the polymorphic-subject pair, the integer points value,
    the observed-at timestamp, the audit reason note, and the optional
    trip-context id. The existence walk on the subject-id-and-the-
    optional-trip-id is the per-entity-kind not-found at the existence
    tier (the per-kind error id is `ERR_DRIVER_NOT_FOUND`,
    `ERR_COMPANY_NOT_FOUND`, or `ERR_VEHICLE_NOT_FOUND` on the subject
    id's table-lookup miss; the `ERR_TRIP_NOT_FOUND` 404 on the
    optional trip-id's miss).

    The DRIVER-subject path drives the cascade onto the driver's
    cached `current_rolling_points` and the threshold-crossover-driven
    `hazmat_endorsement_status` auto-flip from `VALID` to `INVALID`
    in the same transaction. The COMPANY and VEHICLE subject paths
    insert the row without the driver-side cascade.

    The §2.10 paragraph's "a manual-penalty's body has no `version`
    field" rule (the manual-penalty is a creation, the create-
    endpoints carry no OCC) is reflected by the handler not consulting
    the OCC check.

    The `observed_at`-at-or-before-now rule is the standard no-future-
    dated-observation check from §2.9; a future-dated `observed_at` is
    the body-shape `ERR_VALIDATION` 422.
    """
    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]
    role, regulator_id = current_principal()

    subject_type = require_enum(
        body, "subject_type", allowed=PENALTY_SUBJECT_TYPES
    )
    assert subject_type is not None
    subject_id = require_str(body, "subject_id", length_range=(1, 256))
    points_value = require_int(
        body, "points_value", range_inclusive=PENALTY_POINTS_VALUE_RANGE
    )
    assert points_value is not None
    observed_at_dt = require_iso_datetime(body, "observed_at")
    assert observed_at_dt is not None
    reason_note = require_str(
        body, "reason_note", length_range=PENALTY_REASON_NOTE_LEN_RANGE
    )
    trip_id = require_str(body, "trip_id", length_range=(1, 256), optional=True)

    now = current_now()
    if observed_at_dt > now:
        raise APIError(
            "ERR_VALIDATION",
            f"'observed_at' must be at or before the current logical-"
            f"clock value; got {iso_format(observed_at_dt)!r}, now is "
            f"{iso_format(now)!r}.",
            details={
                "field": "observed_at",
                "value": iso_format(observed_at_dt),
                "now": iso_format(now),
            },
        )

    # The subject-id existence walk on the appropriate entity table.
    subject_entity_name = _SUBJECT_TYPE_TO_ENTITY[subject_type]
    subject_row = find(subject_entity_name, subject_id)
    if subject_row is None:
        not_found_id = ENTITY_TO_NOT_FOUND[subject_entity_name]
        raise APIError(
            not_found_id,
            f"Subject {subject_entity_name} {subject_id!r} does not "
            "resolve.",
            details={
                "subject_type": subject_type,
                "subject_id": subject_id,
                "entity": subject_entity_name,
            },
        )

    # The optional trip-id existence.
    if trip_id is not None:
        trip_row = find("Trip", trip_id)
        if trip_row is None:
            raise APIError(
                "ERR_TRIP_NOT_FOUND",
                f"Trip {trip_id!r} (the optional trip-context) does not "
                "resolve.",
                details={"trip_id": trip_id},
            )

    # Build the new Penalty row.
    row: dict[str, Any] = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "points_value": int(points_value),
        "source": "MANUAL_REGULATOR",
        "source_gps_report_id": None,
        "trip_id": trip_id,  # None if absent
        "observed_at": iso_format(observed_at_dt),
        "void_status": "ACTIVE",
        "upheld_at": None,
        "upheld_by": None,
        "reason_note": reason_note,
    }
    stamp_create_event(row)

    # The atomic insert-and-cascade transaction.
    with STATE_LOCK:
        table("Penalty")[row["id"]] = row

        cascade_summary: dict[str, Any] = {
            "subject_type": subject_type,
            "subject_id": subject_id,
        }

        if subject_type == "DRIVER":
            # The driver-side cascade: cache recompute and the
            # threshold-crossover-driven status auto-flip. The
            # standard from-scratch-recompute uses the
            # `driver_penalty_point_rolling_total` function so the
            # cache equals the live-mode value exactly. The
            # observation moment for the cache is the current
            # simulated-clock value (the cache's freshness convention
            # is "the value equals the function evaluated at the
            # current clock" per the §2.11 paragraph).
            driver = subject_row  # alias
            new_total = driver_penalty_point_rolling_total(
                driver["id"], now, constants
            )
            driver["current_rolling_points"] = int(new_total)
            bump_version(driver)
            status_flip: str | None = None
            if (
                driver.get("hazmat_endorsement_status") == "VALID"
                and driver_threshold_crossed(new_total, constants)
            ):
                driver["hazmat_endorsement_status"] = "INVALID"
                bump_version(driver)
                status_flip = "VALID_TO_INVALID"

            # The list of permits whose `authorized_driver_ids`
            # contains this driver — they'll be cascaded on the next
            # verify-compliance per the §3.8 paragraph's deferred-
            # cascade-on-the-permit-side rule. We surface the affected-
            # permit-ids on the response's `cascade_summary` for the
            # test layer's introspection of the pending cascade.
            affected_permit_ids = [
                p["id"]
                for p in table("Permit").values()
                if driver["id"] in (p.get("authorized_driver_ids") or [])
                and p.get("lifecycle_status") in ("ACTIVE", "SUSPENDED")
            ]
            cascade_summary["driver_current_rolling_points"] = int(new_total)
            cascade_summary["driver_hazmat_endorsement_status"] = driver.get(
                "hazmat_endorsement_status"
            )
            cascade_summary["driver_status_flip"] = status_flip
            cascade_summary["pending_cascade_permit_ids"] = affected_permit_ids
        else:
            # COMPANY-or-VEHICLE subject: no automatic cascade per the
            # §2.8 paragraph's "the company and vehicle subject types'
            # totals do not drive automatic state transitions" rule.
            cascade_summary["note"] = (
                f"Subject type {subject_type} does not drive an automatic "
                f"downstream state transition; the row is appended for the "
                "audit trail only."
            )

    response_data = _serialize_penalty(row)
    response_data["cascade_summary"] = cascade_summary
    return make_object_response(response_data, http_status=201)


# ---------------------------------------------------------------------------
# POST /v1/penalties/<penalty_id>/uphold — regulator's appeal-uphold
# ---------------------------------------------------------------------------


@penalties_bp.route("/penalties/<penalty_id>/uphold", methods=["POST"])
def post_penalty_uphold(penalty_id: str) -> Any:
    """The regulator's appeal-adjudication action. The closed-right
    30-day window from the penalty's `observed_at` is the
    `ERR_APPEAL_WINDOW_CLOSED` 409 boundary at priority 513 — a
    duration `now - observed_at` strictly greater than
    `APPEAL_WINDOW_DAYS` is the rejection, the boundary value at
    exactly the window is the last in-window moment per the §2.9
    paragraph's "the appeal-uphold duration is closed-right" rule.

    The source-state-must-be-ACTIVE pre-state check is the standard
    same-state guard, with the
    already-upheld case the generic
    `ERR_INVALID_STATE_TRANSITION` 409 (the action is non-idempotent
    on its source-state — a second uphold on the same row is the
    generic state error since the row is already in the terminal
    UPHELD state per the §1.2 Penalty state-machine's
    `terminal_states: [UPHELD]` entry).

    The body's required `uphold_reason` 1-to-500-character free-text
    string is prepended to the row's `reason_note` field under the
    canonical "UPHELD-ON-APPEAL" marker per the §2.4 paragraph's
    "the on-disk `reason_note` after a successful uphold encodes
    both the original and the appeal-resolution text" rule.

    The cascade on a DRIVER-subject uphold is the cache-recompute
    of the subject driver's `current_rolling_points` (the upheld
    row's contribution is now zero) with the keep-regulator-in-the-
    loop convention forbidding an automatic upward
    `INVALID -> VALID` status-flip — the driver's status is left at
    whatever it was, and the regulator must separately call the
    refresh-endorsement endpoint to re-attest.

    The COMPANY-and-VEHICLE-subject-upholds simply flip the
    `void_status` and the three audit fields without a downstream
    cache-or-status effect on the subject's home aggregate.

    The OCC-version-on-the-Penalty-row rule is the §2.10 paragraph's
    "the manual-penalty's body has no version field, but the uphold
    endpoint does accept the optional version" — wait, the §2.10
    paragraph's enumeration of the OCC-eligible endpoints names the
    Penalty's-version-bump-on-uphold the standard implicit-mutation
    side-effect of the create-pass through the cache. Re-reading: the
    §2.10's table-of-OCC-eligible endpoints does NOT include
    `POST /v1/penalties/<penalty_id>/uphold` since the Penalty entity
    is `common_fields: false` and has no on-disk `version` field. The
    uphold endpoint thus does not engage an OCC check on the Penalty-
    side. The handler-side reads the optional body's `version` field
    for symmetry but does not raise on a mismatch since there is no
    canonical `version` to match against on the Penalty row. The
    standard observation is `version` is absent on every Penalty
    row's response, so the test layer's OCC assertion does not target
    this endpoint.
    """
    penalty = lookup_path_resource(
        "Penalty", penalty_id, "ERR_PENALTY_NOT_FOUND"
    )
    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]
    role, regulator_id = current_principal()

    uphold_reason = require_str(
        body, "uphold_reason", length_range=PENALTY_UPHOLD_REASON_LEN_RANGE
    )

    pre_status = penalty.get("void_status")
    if pre_status != "ACTIVE":
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot uphold an appeal on a penalty in `void_status` "
            f"{pre_status!r}; the source state must be 'ACTIVE'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["ACTIVE"],
                "endpoint": "POST /v1/penalties/<penalty_id>/uphold",
            },
        )

    observed_at_str = penalty.get("observed_at")
    if observed_at_str is None:
        # Defensive — every Penalty row has an `observed_at`.
        raise APIError(
            "ERR_VALIDATION",
            "Penalty row has no `observed_at` value — internal "
            "inconsistency.",
            details={"penalty_id": penalty_id},
        )
    observed_at = parse_iso(observed_at_str)
    now = current_now()
    elapsed = now - observed_at
    window = timedelta(days=constants.appeal_window_days)
    if elapsed > window:
        raise APIError(
            "ERR_APPEAL_WINDOW_CLOSED",
            f"The appeal window has closed: {elapsed.days} days have "
            f"elapsed since `observed_at` "
            f"{iso_format(observed_at)!r}, exceeding the closed-right "
            f"{constants.appeal_window_days}-day window.",
            details={
                "observed_at": iso_format(observed_at),
                "now": iso_format(now),
                "elapsed_days": elapsed.total_seconds() / 86400.0,
                "appeal_window_days": constants.appeal_window_days,
            },
        )

    # Apply the uphold's side-effects under the global lock so the
    # driver-side cache recompute is atomic with the row's flip.
    with STATE_LOCK:
        # The canonical reason-note prepend marker.
        prior_reason = penalty.get("reason_note", "") or ""
        new_reason = (
            f"UPHELD-ON-APPEAL: {uphold_reason}; ORIGINAL: {prior_reason}"
        )
        penalty["void_status"] = "UPHELD"
        penalty["upheld_at"] = iso_format(now)
        penalty["upheld_by"] = regulator_id
        penalty["reason_note"] = new_reason

        cascade_summary: dict[str, Any] = {
            "subject_type": penalty.get("subject_type"),
            "subject_id": penalty.get("subject_id"),
        }
        if penalty.get("subject_type") == "DRIVER":
            subject_id = penalty.get("subject_id")
            driver = find("Driver", subject_id) if subject_id else None
            if driver is not None:
                new_total = driver_penalty_point_rolling_total(
                    subject_id, now, constants
                )
                driver["current_rolling_points"] = int(new_total)
                bump_version(driver)
                cascade_summary["driver_current_rolling_points"] = int(new_total)
                cascade_summary["driver_hazmat_endorsement_status"] = driver.get(
                    "hazmat_endorsement_status"
                )
                cascade_summary["driver_status_flip"] = None  # §3.8's
                # "the regulator-attestation is the only path back to
                # VALID" — no automatic upward flip from the uphold.

    response_data = _serialize_penalty(penalty)
    response_data["cascade_summary"] = cascade_summary
    return make_object_response(response_data, http_status=200)


# ---------------------------------------------------------------------------
# GET /v1/drivers/<driver_id>/penalty-summary — driver-side digest
# ---------------------------------------------------------------------------


@penalties_bp.route("/drivers/<driver_id>/penalty-summary", methods=["GET"])
def get_driver_penalty_summary(driver_id: str) -> Any:
    """The driver-and-permit-status digest the §3.8 paragraph names as
    "the canonical driver-side performance view the operator-and-the-
    regulator's audit dashboards and the driver-role's self-read all
    consume". The response's data block carries:

      - The path's `driver_id`, the `as_of` ISO-string of the current
        simulated-clock value, the integer `current_rolling_points`
        computed fresh at the read moment via the canonical function
        (which equals the cached field's value on a consistent cache),
        the integer `threshold` constant the consumer compares the
        rolling-points against, the `hazmat_endorsement_status`
        enum-value, the `endorsement_valid_until` ISO string (or
        null on a `NOT_ATTESTED` driver), the `endorsement_classes`
        array of UN-hazard-class strings.

      - The `active_penalties_in_window` array of per-penalty
        objects (the ones whose `void_status == "ACTIVE"` and whose
        `observed_at` lies in the rolling-window's open-on-the-left-
        closed-on-the-right interval), sorted by `observed_at`
        descending then by `id` descending. Each entry carries the
        Penalty row's `id`, the `points_value`, the `observed_at`,
        the `source` enum value, the optional `trip_id` context, and
        the first-120-characters of the `reason_note` for the
        summary-display.

      - The companion `upheld_penalties_in_window` array of the same
        shape, but for the rows whose `void_status == "UPHELD"` and
        whose `observed_at` is still in the rolling window — these do
        not contribute to the total but are surfaced for the audit-
        trail's-transparency. The sorting convention matches the
        active list.

      - The `permits_currently_listing_this_driver` array of the
        per-permit `(permit_id, lifecycle_status,
        snapshot_endorsement_for_this_driver,
        live_endorsement_for_this_driver)` quadruples, in created_at-
        descending order, with a max length of 50 per the §1.5
        paragraph's "the per-permit-list scope is bounded by the
        cardinality the regulator considers reasonable" cap. The
        snapshot-vs-live disagreement on this driver's per-permit
        flag is the observable dual-variant axis the §2.11
        closing paragraph names.

    The three-role allow-set is the standard `{CompanyOperator,
    RegulatorOfficer, Driver}` with the operator-transitive-tenant on
    the driver's `company_id`, the regulator cross-tenant exempt, and
    the driver-self-only-on-the-path-id rule at priority 531. The
    existence tier fires first per the §2.6's-priority-300-before-
    priority-530 convention.
    """
    driver = lookup_path_resource("Driver", driver_id, "ERR_DRIVER_NOT_FOUND")
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]
    role, user_id = current_principal()

    # The cross-tenant predicate split by role: Driver-self-only,
    # Operator-transitive, Regulator-exempt.
    if role == "Driver":
        if driver_id != user_id:
            raise APIError(
                "ERR_CROSS_TENANT_ACCESS",
                f"Driver self-only check on penalty-summary: requester "
                f"id {user_id!r} is not the path's driver id "
                f"{driver_id!r}.",
                details={
                    "rule": "driver-self-only-on-penalty-summary",
                    "priority": 531,
                    "requester_id": user_id,
                    "path_id": driver_id,
                },
            )
    elif role == "CompanyOperator":
        # The operator-side transitive-tenant: the driver's company
        # equals the operator's id.
        if driver.get("company_id") != user_id:
            raise APIError(
                "ERR_CROSS_TENANT_ACCESS",
                f"Operator id {user_id!r} cannot read the penalty-summary "
                f"of a driver in a different tenant "
                f"({driver.get('company_id')!r}).",
                details={
                    "operator_id": user_id,
                    "driver_company_id": driver.get("company_id"),
                    "driver_id": driver_id,
                },
            )
    # RegulatorOfficer cross-tenant exempt by §2.6.

    now = current_now()
    # The fresh rolling-total computation.
    fresh_total = driver_penalty_point_rolling_total(driver_id, now, constants)
    # Refresh the cache to the fresh value so the read is observably
    # self-consistent with the function output and the next live-mode
    # read sees the same integer. The PRD §2.11 paragraph's "the
    # cached field equals the function evaluated at the current
    # simulated-clock value" freshness invariant.
    if int(driver.get("current_rolling_points", 0)) != int(fresh_total):
        driver["current_rolling_points"] = int(fresh_total)
        bump_version(driver)

    # The two penalty lists. The window's left-edge-exclusive,
    # right-edge-inclusive interval `(now - PENALTY_WINDOW_DAYS, now]`
    # per the §2.9 paragraph. The sort order is `observed_at`
    # descending then `id` descending so the most-recent observations
    # are first.
    window_lower_exclusive = now - timedelta(
        days=constants.penalty_window_days
    )
    active_in_window: list[dict[str, Any]] = []
    upheld_in_window: list[dict[str, Any]] = []
    for p in table("Penalty").values():
        if p.get("subject_type") != "DRIVER":
            continue
        if p.get("subject_id") != driver_id:
            continue
        observed_at_str = p.get("observed_at")
        if observed_at_str is None:
            continue
        observed_at = parse_iso(observed_at_str)
        # Open-on-the-left.
        if observed_at <= window_lower_exclusive:
            continue
        if observed_at > now:
            continue
        # Pick which bucket.
        entry = {
            "id": p.get("id"),
            "points_value": int(p.get("points_value", 0)),
            "observed_at": observed_at_str,
            "source": p.get("source"),
            "trip_id": p.get("trip_id"),
            "reason_note_first_120_chars": (
                (p.get("reason_note") or "")[:120]
            ),
        }
        if p.get("void_status") == "ACTIVE":
            active_in_window.append(entry)
        elif p.get("void_status") == "UPHELD":
            entry["upheld_at"] = p.get("upheld_at")
            entry["upheld_by"] = p.get("upheld_by")
            upheld_in_window.append(entry)

    active_in_window.sort(
        key=lambda e: (e["observed_at"], e["id"]), reverse=True
    )
    upheld_in_window.sort(
        key=lambda e: (e["observed_at"], e["id"]), reverse=True
    )

    # The permits-currently-listing-this-driver array. The §3.8
    # paragraph names the per-permit fields `(permit_id,
    # lifecycle_status, snapshot_endorsement_for_this_driver,
    # live_endorsement_for_this_driver)`. The snapshot flag is the
    # on-disk value of the permit's `snapshot_driver_endorsements`
    # map's entry keyed by this driver-id (`False` if absent). The
    # live flag is the live-mode evaluation of the per-driver
    # conjunction "endorsement-VALID-and-covers-the-term-and-points-
    # below-threshold" against the current state.
    from ..calculations import compute_per_driver_snapshot_flag

    permit_entries: list[dict[str, Any]] = []
    for permit in list_all("Permit"):
        if driver_id not in (permit.get("authorized_driver_ids") or []):
            continue
        # The on-disk per-driver-snapshot value on the permit row.
        snapshot_map = permit.get("snapshot_driver_endorsements") or {}
        snapshot_flag = bool(snapshot_map.get(driver_id, False))
        # The live evaluation against the current driver state and the
        # permit's `valid_until`-end-of-term (or the permit's
        # `valid_from` if `valid_until` is null on an unissued DRAFT
        # permit, in which case the term-cover-check is vacuous and
        # the flag reduces to "the driver is VALID at the moment").
        valid_until_str = permit.get("valid_until") or permit.get("valid_from")
        if valid_until_str is None:
            live_flag = (
                driver.get("hazmat_endorsement_status") == "VALID"
                and int(driver.get("current_rolling_points", 0))
                < constants.threshold_driver_suspension_points
            )
        else:
            term_end = parse_iso(valid_until_str)
            live_flag = compute_per_driver_snapshot_flag(
                driver_id, term_end, constants
            )
        permit_entries.append(
            {
                "permit_id": permit.get("id"),
                "lifecycle_status": permit.get("lifecycle_status"),
                "snapshot_endorsement_for_this_driver": snapshot_flag,
                "live_endorsement_for_this_driver": live_flag,
                "created_at": permit.get("created_at", ""),
            }
        )
    # Sort by `created_at` descending, cap at 50 entries (the §1.5
    # closing-prose's bound on the per-permit-list scope).
    permit_entries.sort(key=lambda e: (e["created_at"], e["permit_id"]), reverse=True)
    permit_entries = permit_entries[:50]
    # Strip the `created_at` sorting helper from the response shape
    # since it is not in the §3.8 named fields.
    for e in permit_entries:
        e.pop("created_at", None)

    response_data: dict[str, Any] = {
        "driver_id": driver_id,
        "as_of": iso_format(now),
        "current_rolling_points": int(fresh_total),
        "threshold": int(constants.threshold_driver_suspension_points),
        "hazmat_endorsement_status": driver.get("hazmat_endorsement_status"),
        "endorsement_valid_until": driver.get("endorsement_valid_until"),
        "endorsement_classes": list(driver.get("endorsement_classes") or []),
        "active_penalties_in_window": active_in_window,
        "upheld_penalties_in_window": upheld_in_window,
        "permits_currently_listing_this_driver": permit_entries,
    }
    return make_object_response(response_data, http_status=200)
