"""The Permit endpoints — seven in the scaffold's §1.5 enumeration:

  POST /v1/permits                                 — operator files the
                                                       application; the
                                                       new row is in
                                                       `lifecycle_status =
                                                       "DRAFT"` and the
                                                       response embeds a
                                                       non-stored
                                                       `application_preview`
                                                       sub-object with
                                                       the application-
                                                       moment validity-
                                                       leg booleans.

  GET  /v1/permits/<permit_id>                     — read-one; the
                                                       response embeds
                                                       the on-disk
                                                       snapshot fields
                                                       verbatim and the
                                                       separately-
                                                       computed live-
                                                       verdict fields
                                                       (the snapshot-
                                                       and-live dual-
                                                       variant axis the
                                                       §2.11 paragraph
                                                       names).

  GET  /v1/permits                                 — paginated list,
                                                       sorted
                                                       `created_at`-
                                                       descending then
                                                       `id`-descending
                                                       per the §2.3
                                                       sort-deviation
                                                       note. The
                                                       optional
                                                       `company_id`
                                                       filter the
                                                       regulator may use
                                                       freely; the
                                                       operator's
                                                       explicit-`company_id`
                                                       must equal its
                                                       own `X-User-ID`.
                                                       The optional
                                                       `lifecycle_status`
                                                       comma-list filter.

  POST /v1/permits/<permit_id>/issue               — regulator's
                                                       `DRAFT → ACTIVE`
                                                       atomic write-and-
                                                       debit transaction:
                                                       compute the fee
                                                       via
                                                       `annual_renewal_fee(is_late=false)`,
                                                       debit the parent
                                                       company's wallet,
                                                       write `valid_until
                                                       = valid_from +
                                                       PERMIT_DEFAULT_VALIDITY_DAYS`,
                                                       write the
                                                       strict-snapshot
                                                       all-true values,
                                                       set
                                                       `issued_at`,
                                                       `issued_by`,
                                                       `issue_fee_cents`,
                                                       `last_verified_at`,
                                                       and the
                                                       `lifecycle_status`
                                                       to `ACTIVE`. The
                                                       fiscal-tier check
                                                       fires
                                                       `ERR_INSUFFICIENT_WALLET_BALANCE`
                                                       402 on a short
                                                       wallet, after the
                                                       safety-and-
                                                       referential
                                                       checks have all
                                                       passed.

  POST /v1/permits/<permit_id>/verify-compliance   — regulator's
                                                       periodic
                                                       compliance audit
                                                       that runs the
                                                       five-leg live
                                                       recompute,
                                                       compares against
                                                       the on-disk
                                                       snapshot's
                                                       conjunction, and
                                                       decides the
                                                       `ACTIVE ↔ SUSPENDED`
                                                       transition or
                                                       the wall-clock-
                                                       driven
                                                       `→ EXPIRED`
                                                       transition. The
                                                       response carries
                                                       the
                                                       `transition_fired`
                                                       discriminator
                                                       string per the
                                                       §3.5 paragraph.
                                                       The OCC-on-the-
                                                       permit-row
                                                       contention race
                                                       is the concurrency_rule
                                                       4 entry of the
                                                       §1.2.1 block.

  POST /v1/permits/<permit_id>/renew               — operator's annual
                                                       renewal. The
                                                       outer-renewal-
                                                       window check
                                                       (the closed-left,
                                                       open-right
                                                       `[valid_until -
                                                       RENEWAL_OPEN_WINDOW_DAYS,
                                                       valid_until)`
                                                       interval) at
                                                       priorities 541
                                                       and 542. The
                                                       inner late-grace
                                                       window's
                                                       `is_late` flag
                                                       drives the
                                                       formula's
                                                       conditional add.
                                                       The optional body
                                                       fields
                                                       `authorized_driver_ids`,
                                                       `authorized_vehicle_ids`,
                                                       and
                                                       `hazard_classes`
                                                       atomically
                                                       replace the
                                                       on-row arrays
                                                       when present.
                                                       The `valid_until`
                                                       is extended by
                                                       `PERMIT_DEFAULT_VALIDITY_DAYS`
                                                       measured forward
                                                       from the prior
                                                       `valid_until`
                                                       (the §2.11's
                                                       "the new term-
                                                       end is one term-
                                                       length ahead of
                                                       the prior, not of
                                                       now()" stride
                                                       rule). The
                                                       fee-cents goes
                                                       to a fresh
                                                       `renewal_history`
                                                       entry; the
                                                       wallet is debited
                                                       atomically; the
                                                       snapshot fields
                                                       are refreshed
                                                       (the renewal
                                                       embeds a verify-
                                                       compliance pass).

  POST /v1/permits/<permit_id>/void-issue          — regulator's 24-hour
                                                       clerical-error
                                                       reversal. The
                                                       refund amount is
                                                       the literal sum
                                                       `issue_fee_cents +
                                                       sum(renewal_history[*].fee_cents)`,
                                                       which by the
                                                       §2.11 conservation
                                                       invariant equals
                                                       the exact integer
                                                       that has flowed
                                                       out of the wallet
                                                       across the issue-
                                                       and-renewals
                                                       sequence. The
                                                       wallet is credited
                                                       by that amount in
                                                       the same
                                                       transaction that
                                                       flips
                                                       `lifecycle_status`
                                                       to the terminal
                                                       `VOIDED` and
                                                       sets the on-row
                                                       `voided_at` and
                                                       `void_refunded_cents`
                                                       fields. The 24-
                                                       hour window from
                                                       `issued_at` is the
                                                       closed-right
                                                       duration check at
                                                       priority 514's
                                                       `ERR_VOID_WINDOW_CLOSED`
                                                       409 error. The
                                                       cascade onto open
                                                       child trips
                                                       aborts each with
                                                       `abort_reason =
                                                       "PERMIT_SUSPENDED_CASCADE"`
                                                       (the enum-economy
                                                       reuse of the
                                                       suspension-cascade
                                                       value for the
                                                       void-cascade per
                                                       the §2.8 abort-
                                                       reason taxonomy's
                                                       prose).

The validation precedence per the §2.7 priority tier-walk's hierarchy
is realized by the order the handler-code below performs the checks:
auth-tier and existence-tier (in `auth.py`'s middleware and
`lookup_path_resource`), then the same-row-state-tier check at
priority 400, then the cross-entity-state-tier-from-the-grounding-
entities (the company-qualified at 526, the route-approved at 525,
the per-driver-endorsement-and-coverage at 510, the per-vehicle-
inspection-and-coverage at 511) on the issue and the renewal paths,
then the cardinality-and-hazard-class business constraints at 523 and
524, then the fiscal-tier wallet-balance check at 540, then the OCC
version match at 560, then the body-shape catch-all at 590.

The cross-tenant predicate on the operator-side endpoints (POST
/permits, the GET-by-id, the renewal) is the permit's `company_id`
matching the operator's `X-User-ID`, with the existence-tier-fires-
first precedence per the §2.6's rule-5 priority-conflict-B convention.
The regulator-side endpoints (issue, verify-compliance, void-issue)
are cross-tenant exempt.

The OCC contract of §2.10 is the standard "optional `version` field
in the body engages the check; absence opts out". The per-permit-row
version-bump on every successful mutating action of the seven on this
aggregate is the canonical "this row has been touched" signal a
concurrent retry of the same action observes via the now-bumped
version.

The §1.2.1 concurrency_rules entries on the permit row are the
verify-compliance-vs-verify-compliance race (rule 4) and the
renew-vs-void-issue race (rule 5), both serialized on the row's
`version` field with the OCC contract's `ERR_VERSION_CONFLICT` 409
on the loser.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from flask import Blueprint, current_app, request

from ..auth import (
    assert_cross_tenant_ownership,
    current_principal,
    lookup_path_resource,
)
from ..calculations import (
    annual_renewal_fee,
    permit_validity_check,
)
from ..clock import current_now, iso_format, iso_now, parse_iso
from ..config import (
    Constants,
    GENERIC_REASON_NOTE_LEN_RANGE,
    OPTIONAL_NOTE_LEN_RANGE,
    PERMIT_DRIVER_LIST_MAX,
    PERMIT_DRIVER_LIST_MIN,
    PERMIT_LIFECYCLE_STATES,
    PERMIT_VEHICLE_LIST_MIN,
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
    check_occ,
    find,
    insert,
    list_all,
    paginate,
    stamp_create,
    table,
)
from ..sweep import _abort_open_trips_of_permit, _write_snapshot_fields
from ..validation import (
    parse_comma_filter_query,
    require_array,
    require_int,
    require_iso_datetime,
    require_present,
    require_str,
    validate_hazard_class_array,
)


permits_bp = Blueprint("permits", __name__)


def _serialize_permit(row: dict[str, Any]) -> dict[str, Any]:
    """Wire-shape of the Permit row. The dict's keys mirror the §1.1
    Permit-entity field list verbatim. The wallet-side debit-credit
    sub-object the issue-and-renew-and-void-issue responses embed as a
    transient is built by the per-handler code.
    """
    return dict(row)


def _validate_authorized_lists_existence_and_tenancy(
    driver_ids: list[str],
    vehicle_ids: list[str],
    operator_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve every driver-id and vehicle-id on the body's
    authorized-lists, walking the existence-tier first (a missing id is
    the per-entity-kind `ERR_<ENTITY>_NOT_FOUND` 404 with the leftmost-
    missing id winning per the §2.7 paragraph's left-to-right walk
    rule), then the cross-aggregate-tenant rule (a driver or vehicle
    whose owning `company_id` is not the operator's tenant gets the
    same per-entity `ERR_<ENTITY>_NOT_FOUND` 404 per the §2.6 closing
    paragraph's "from the operator's perspective the other-tenant's
    rows are not part of the operator's universe and therefore are
    not-found in their view" convention — i.e., the cross-tenant
    foreign-key reference on the body is reported as the existence-
    tier 404 rather than the cross-tenant-tier 403).

    Returns the pair `(driver_rows, vehicle_rows)` of resolved row
    dicts in the same order as the input id-arrays. The handler-side
    code then iterates the per-row state-and-validity checks (the
    per-driver hazmat-endorsement-VALID-and-covers-the-term-and-points-
    below-threshold conjunction, the per-vehicle latest-inspection-
    PASSED-and-covers-the-term conjunction).
    """
    driver_rows: list[dict[str, Any]] = []
    for did in driver_ids:
        d = find("Driver", did)
        if d is None or d.get("company_id") != operator_id:
            raise APIError(
                "ERR_DRIVER_NOT_FOUND",
                f"Driver {did!r} does not resolve in the operator's "
                f"tenant universe.",
                details={
                    "driver_id": did,
                    "operator_tenant": operator_id,
                },
            )
        driver_rows.append(d)
    vehicle_rows: list[dict[str, Any]] = []
    for vid in vehicle_ids:
        v = find("Vehicle", vid)
        if v is None or v.get("company_id") != operator_id:
            raise APIError(
                "ERR_VEHICLE_NOT_FOUND",
                f"Vehicle {vid!r} does not resolve in the operator's "
                f"tenant universe.",
                details={
                    "vehicle_id": vid,
                    "operator_tenant": operator_id,
                },
            )
        vehicle_rows.append(v)
    return driver_rows, vehicle_rows


def _check_per_driver_validity_for_term(
    drivers: list[dict[str, Any]],
    term_end_dt: datetime,
    constants: Constants,
    *,
    error_id: str = "ERR_DRIVER_ENDORSEMENT_INVALID",
) -> None:
    """For each driver on the list, check the conjunction
    "hazmat_endorsement_status is VALID AND endorsement_valid_until is
    at or after the term-end datetime AND current_rolling_points is
    strictly below the threshold". A failing driver is the immediate
    `ERR_DRIVER_ENDORSEMENT_INVALID` 409 at the safety-tier priority
    510 with the offending driver-id and the cause-of-the-fail in the
    detail-payload.
    """
    for d in drivers:
        did = d["id"]
        if d.get("hazmat_endorsement_status") != "VALID":
            raise APIError(
                error_id,
                f"Driver {did!r}'s `hazmat_endorsement_status` is "
                f"{d.get('hazmat_endorsement_status')!r}; the permit's "
                f"drivers-leg requires every named driver to be 'VALID'.",
                details={
                    "driver_id": did,
                    "current_status": d.get("hazmat_endorsement_status"),
                    "cause": "endorsement_not_valid",
                },
            )
        eu_str = d.get("endorsement_valid_until")
        if eu_str is None:
            raise APIError(
                error_id,
                f"Driver {did!r} has no `endorsement_valid_until` value; "
                f"the permit's drivers-leg requires the endorsement to "
                f"cover the whole permit term.",
                details={
                    "driver_id": did,
                    "cause": "endorsement_valid_until_is_null",
                },
            )
        eu = parse_iso(eu_str)
        if eu < term_end_dt:
            raise APIError(
                error_id,
                f"Driver {did!r}'s endorsement expires at "
                f"{iso_format(eu)!r}, which is before the permit's would-"
                f"be term-end {iso_format(term_end_dt)!r}.",
                details={
                    "driver_id": did,
                    "endorsement_valid_until": iso_format(eu),
                    "permit_term_end": iso_format(term_end_dt),
                    "cause": "endorsement_does_not_cover_term",
                },
            )
        points = int(d.get("current_rolling_points", 0))
        if points >= constants.threshold_driver_suspension_points:
            raise APIError(
                error_id,
                f"Driver {did!r}'s `current_rolling_points` is {points}, "
                f"at or above the suspension threshold of "
                f"{constants.threshold_driver_suspension_points}.",
                details={
                    "driver_id": did,
                    "current_rolling_points": points,
                    "threshold": constants.threshold_driver_suspension_points,
                    "cause": "points_at_or_above_threshold",
                },
            )


def _check_per_vehicle_validity_for_term(
    vehicles: list[dict[str, Any]],
    term_end_dt: datetime,
    *,
    error_id: str = "ERR_VEHICLE_INSPECTION_LAPSED",
) -> None:
    """For each vehicle on the list, check the conjunction
    "latest_inspection_outcome == 'PASSED' AND
    latest_inspection_valid_until >= term_end". The
    `latest_inspection_valid_until == null` case (no inspection has
    ever been appended on the vehicle) is also the failing case. The
    failing-vehicle's row-id and cause are in the detail-payload of the
    raised `ERR_VEHICLE_INSPECTION_LAPSED` 409 at the priority-511
    safety-tier check.
    """
    for v in vehicles:
        vid = v["id"]
        outcome = v.get("latest_inspection_outcome")
        if outcome != "PASSED":
            raise APIError(
                error_id,
                f"Vehicle {vid!r}'s latest inspection outcome is "
                f"{outcome!r}; the permit's vehicles-leg requires every "
                f"named vehicle's most-recent inspection to be 'PASSED'.",
                details={
                    "vehicle_id": vid,
                    "latest_inspection_outcome": outcome,
                    "cause": "inspection_not_passed_or_missing",
                },
            )
        vu_str = v.get("latest_inspection_valid_until")
        if vu_str is None:
            raise APIError(
                error_id,
                f"Vehicle {vid!r} has no `latest_inspection_valid_until` "
                f"value; the inspection's validity must cover the "
                f"permit's term-end.",
                details={
                    "vehicle_id": vid,
                    "cause": "no_inspection_valid_until",
                },
            )
        vu = parse_iso(vu_str)
        if vu < term_end_dt:
            raise APIError(
                error_id,
                f"Vehicle {vid!r}'s latest-inspection `valid_until` is "
                f"{iso_format(vu)!r}, before the permit's would-be "
                f"`valid_until` of {iso_format(term_end_dt)!r}.",
                details={
                    "vehicle_id": vid,
                    "latest_inspection_valid_until": iso_format(vu),
                    "permit_term_end": iso_format(term_end_dt),
                    "cause": "inspection_does_not_cover_term",
                },
            )


def _check_hazard_classes_subset_of_intersection(
    hazard_classes: list[str], company_id: str, route_id: str
) -> None:
    """The permit's `hazard_classes` body field's non-empty-subset-of-
    the-intersection rule per the §1.5 permit-create body-schema's
    "non-empty subset of the intersection
    `company.hazard_classes_authorized ∩ route.hazard_classes_supported`"
    rule. The check fires on POST /permits and on the issue-step's
    re-check (the time-of-check-vs-time-of-use gap may have narrowed
    the intersection in between, in which case the `ERR_VALIDATION`
    422 catch-all fires at the issue with the same field name).
    """
    company = find("TransportCompany", company_id)
    if company is None:
        raise APIError(
            "ERR_COMPANY_NOT_FOUND",
            f"Parent TransportCompany {company_id!r} does not resolve.",
            details={"company_id": company_id},
        )
    route = find("TransportRoute", route_id)
    if route is None:
        raise APIError(
            "ERR_ROUTE_NOT_FOUND",
            f"Route {route_id!r} does not resolve.",
            details={"route_id": route_id},
        )
    company_authorized = set(company.get("hazard_classes_authorized", []) or [])
    route_supported = set(route.get("hazard_classes_supported", []) or [])
    intersection = company_authorized & route_supported
    requested = set(hazard_classes)
    if not requested:
        raise APIError(
            "ERR_VALIDATION",
            "Permit 'hazard_classes' must be a non-empty array.",
            details={"field": "hazard_classes"},
        )
    if not requested.issubset(intersection):
        offending = sorted(requested - intersection)
        raise APIError(
            "ERR_VALIDATION",
            f"Permit 'hazard_classes' contains entries "
            f"{offending!r} not in the intersection of the company's "
            f"authorized hazard-classes and the route's supported "
            f"hazard-classes.",
            details={
                "field": "hazard_classes",
                "offending": offending,
                "intersection": sorted(intersection),
                "company_authorized": sorted(company_authorized),
                "route_supported": sorted(route_supported),
            },
        )


# ---------------------------------------------------------------------------
# POST /v1/permits — operator's permit application
# ---------------------------------------------------------------------------


@permits_bp.route("/permits", methods=["POST"])
def post_create_permit_application() -> Any:
    """The operator files a permit application. The new row's
    `lifecycle_status` is `DRAFT`. The body's foreign-key references
    on `route_id`, `authorized_driver_ids`, and `authorized_vehicle_ids`
    are walked at the existence tier with the cross-tenant-as-not-
    found semantic, the cardinality-bounds rules at the business-
    constraint tier (the vehicle-list-cardinality firing the dedicated
    `ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE` 422 at priority 523, the
    driver-list cardinality the generic `ERR_VALIDATION` 422), the
    hazard-class-subset-of-the-company-and-route-intersection rule
    (`ERR_VALIDATION` 422 at priority 524), and the cross-entity-state
    preconditions (`ERR_COMPANY_NOT_QUALIFIED` 409 on the operator's
    own company at priority 526, `ERR_ROUTE_NOT_APPROVED` 409 on the
    named route at priority 525, the per-driver and per-vehicle live
    validity checks at priorities 510 and 511). The `valid_from`-not-
    in-the-past body-shape rule rounds out the validation.

    The successful response embeds the standard envelope's `data`
    object with the new Permit row and an additional non-stored
    `application_preview` sub-object carrying the validity-leg booleans
    the §1.5 row's `response_payload_schema` paragraph names. The
    HTTP status is 201.
    """
    body = get_json_body()
    role, operator_id = current_principal()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]

    # The operator's-own company must be APPROVED. The operator's
    # X-User-ID equals the operator's-own company id; we read the row.
    operator_company = find("TransportCompany", operator_id)
    if operator_company is None:
        # The auth-tier's entity-backed-id resolution should have
        # caught this. Defensive guard.
        raise APIError(
            "ERR_UNAUTHENTICATED",
            f"Operator's X-User-ID {operator_id!r} does not resolve to "
            "a TransportCompany row.",
        )
    if operator_company.get("qualification_status") != "APPROVED":
        raise APIError(
            "ERR_COMPANY_NOT_QUALIFIED",
            f"The operator's own TransportCompany is in "
            f"{operator_company.get('qualification_status')!r}; only an "
            "APPROVED company may file a permit application.",
            details={
                "company_id": operator_id,
                "current_status": operator_company.get("qualification_status"),
            },
        )

    # The body's foreign-key references and the four required fields.
    route_id = require_str(body, "route_id", length_range=(1, 256))
    authorized_driver_ids_raw = require_array(
        body,
        "authorized_driver_ids",
        element_type=str,
        length_range=(PERMIT_DRIVER_LIST_MIN, PERMIT_DRIVER_LIST_MAX),
        no_duplicates=True,
    )
    assert authorized_driver_ids_raw is not None
    authorized_vehicle_ids_raw = require_array(
        body,
        "authorized_vehicle_ids",
        element_type=str,
        length_range=(PERMIT_VEHICLE_LIST_MIN, constants.max_vehicles_per_permit),
        no_duplicates=True,
        error_id_for_length="ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE",
    )
    assert authorized_vehicle_ids_raw is not None
    hazard_classes_raw = require_array(
        body,
        "hazard_classes",
        element_type=str,
        no_duplicates=True,
    )
    assert hazard_classes_raw is not None
    hazard_classes = validate_hazard_class_array(
        hazard_classes_raw, field="hazard_classes", allow_empty=False
    )
    valid_from_dt = require_iso_datetime(body, "valid_from")
    assert valid_from_dt is not None
    now = current_now()
    if valid_from_dt < now:
        raise APIError(
            "ERR_VALIDATION",
            f"'valid_from' is in the past: {iso_format(valid_from_dt)!r} "
            f"vs now() = {iso_format(now)!r}.",
            details={
                "field": "valid_from",
                "value": iso_format(valid_from_dt),
                "now": iso_format(now),
            },
        )

    # The body-foreign-key existence walk on the three id-arrays. The
    # leftmost-unresolvable id wins per the §2.7 paragraph's "the
    # body-foreign-key existence check walks the body-field-declaration
    # order with the leftmost-unresolvable-id winning" convention. The
    # route is the first body-foreign-key, then the drivers, then the
    # vehicles in their array-index order.
    route = find("TransportRoute", route_id)
    if route is None or route.get("company_id") != operator_id:
        # The cross-tenant-as-not-found convention.
        raise APIError(
            "ERR_ROUTE_NOT_FOUND",
            f"Route {route_id!r} does not resolve in the operator's "
            "tenant universe.",
            details={
                "route_id": route_id,
                "operator_tenant": operator_id,
            },
        )

    driver_rows, vehicle_rows = _validate_authorized_lists_existence_and_tenancy(
        list(authorized_driver_ids_raw),
        list(authorized_vehicle_ids_raw),
        operator_id,
    )

    # The route-approved state-tier check at priority 525.
    if route.get("approval_status") != "APPROVED":
        raise APIError(
            "ERR_ROUTE_NOT_APPROVED",
            f"Route {route_id!r}'s `approval_status` is "
            f"{route.get('approval_status')!r}; the permit-application "
            "requires the route to be 'APPROVED'.",
            details={
                "route_id": route_id,
                "current_status": route.get("approval_status"),
            },
        )

    # The hazard-class-subset-of-the-intersection check.
    _check_hazard_classes_subset_of_intersection(
        hazard_classes, operator_id, route_id
    )

    # Compute the would-be `valid_until` for the per-driver-and-per-
    # vehicle term-coverage checks. The would-be `valid_until` is
    # `valid_from + PERMIT_DEFAULT_VALIDITY_DAYS` per the §1.2's
    # DRAFT-to-ACTIVE side-effect "set valid_until = valid_from +
    # PERMIT_DEFAULT_VALIDITY_DAYS" rule, but the on-disk row's
    # `valid_until` stays null until the issue step writes it; the
    # application-step's preview checks the would-be value against the
    # grounding-entity validity windows so the operator gets early
    # feedback on a would-be-not-coverable term.
    would_be_valid_until = valid_from_dt + timedelta(
        days=constants.permit_default_validity_days
    )

    # Per-driver and per-vehicle validity-coverage checks.
    _check_per_driver_validity_for_term(driver_rows, would_be_valid_until, constants)
    _check_per_vehicle_validity_for_term(vehicle_rows, would_be_valid_until)

    # All checks pass. Build the new Permit row in DRAFT. The four
    # common-fields quartet's `version` starts at 1. The standard
    # initial-state fields the §2.4 H3 paragraph names: every snapshot
    # field is null, the `valid_until`-is-null on the unissued permit,
    # the `issued_at`-and-`issued_by`-are-null, the `issue_fee_cents`-is-
    # null, the `last_verified_at`-is-null, the `renewal_history` is
    # the empty array, the `voided_at`-and-`void_refunded_cents` are
    # null.
    row: dict[str, Any] = {
        "company_id": operator_id,
        "route_id": route_id,
        "authorized_driver_ids": list(authorized_driver_ids_raw),
        "authorized_vehicle_ids": list(authorized_vehicle_ids_raw),
        "hazard_classes": list(hazard_classes),
        "valid_from": iso_format(valid_from_dt),
        "valid_until": None,
        "lifecycle_status": "DRAFT",
        "issued_at": None,
        "issued_by": None,
        "issue_fee_cents": None,
        "last_verified_at": None,
        "snapshot_company_qualified": None,
        "snapshot_driver_endorsements": {},
        "snapshot_vehicle_inspections": {},
        "snapshot_route_approved": None,
        "snapshot_within_window": None,
        "renewal_history": [],
        "voided_at": None,
        "void_refunded_cents": None,
    }
    stamp_create(row)
    insert("Permit", row)

    # The non-stored `application_preview` sub-object the §1.5
    # response_payload_schema's prose names. The preview's five-leg
    # booleans use the live-mode recompute against the current
    # grounding-entity state at the moment of the create-call. The
    # `live_within_window` flag here is the comparison `valid_from <=
    # now() < would_be_valid_until`, which equals `False` on the
    # typical operator-set-valid_from-in-the-near-future case (where
    # now() < valid_from) and `True` on the valid-from-is-now-or-in-
    # the-past case. The on-disk snapshot fields are still all null
    # because no verify-compliance has fired; the response's preview
    # is the operator's information-only view.
    live_company_qualified = (
        operator_company.get("qualification_status") == "APPROVED"
    )
    live_route_approved = route.get("approval_status") == "APPROVED"
    # Per-driver-and-per-vehicle preview booleans.
    live_driver_endorsements = {
        d["id"]: (
            d.get("hazmat_endorsement_status") == "VALID"
            and d.get("endorsement_valid_until") is not None
            and parse_iso(d["endorsement_valid_until"]) >= would_be_valid_until
            and int(d.get("current_rolling_points", 0))
            < constants.threshold_driver_suspension_points
        )
        for d in driver_rows
    }
    live_vehicle_inspections = {
        v["id"]: (
            v.get("latest_inspection_outcome") == "PASSED"
            and v.get("latest_inspection_valid_until") is not None
            and parse_iso(v["latest_inspection_valid_until"]) >= would_be_valid_until
        )
        for v in vehicle_rows
    }
    live_within_window = valid_from_dt <= now < would_be_valid_until
    live_overall = (
        live_company_qualified
        and live_route_approved
        and all(live_driver_endorsements.values())
        and all(live_vehicle_inspections.values())
        and live_within_window
    )

    response_body = _serialize_permit(row)
    response_body["application_preview"] = {
        "live_company_qualified": live_company_qualified,
        "live_driver_endorsements": live_driver_endorsements,
        "live_vehicle_inspections": live_vehicle_inspections,
        "live_route_approved": live_route_approved,
        "live_within_window": live_within_window,
        "live_overall": live_overall,
        "would_be_valid_until": iso_format(would_be_valid_until),
    }

    return make_object_response(response_body, http_status=201)


# ---------------------------------------------------------------------------
# GET /v1/permits/<permit_id> — read one
# ---------------------------------------------------------------------------


@permits_bp.route("/permits/<permit_id>", methods=["GET"])
def get_permit(permit_id: str) -> Any:
    """Read a permit, with the on-disk snapshot fields and the
    separately-computed live-mode verdict embedded in the response.
    The §3.5's "the read endpoint surfaces both the snapshot and the
    live verdict so the disagreement between the two is observable
    without firing a state transition" pin is realized by this
    handler.

    The cross-tenant predicate fires after the existence tier per the
    §2.6's-priority-300-before-priority-530 convention. The Driver-and-
    TestHarness roles' default-deny RBAC cells are caught by the
    auth tier's matrix-lookup so this handler is only reached by the
    CompanyOperator-or-RegulatorOfficer pair.
    """
    row = lookup_path_resource("Permit", permit_id, "ERR_PERMIT_NOT_FOUND")
    assert_cross_tenant_ownership("Permit", row)

    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]
    # Compute the live-mode verdict at the read moment without writing
    # it back to the row.
    live_overall, live_per_leg = permit_validity_check(
        row, mode="live", constants=constants
    )
    snapshot_overall, _snapshot_per_leg = permit_validity_check(
        row, mode="snapshot", constants=constants
    )

    response = _serialize_permit(row)
    response["live_verdict"] = bool(live_overall)
    response["live_per_leg"] = {
        "live_company_qualified": bool(live_per_leg["company_ok"]),
        "live_drivers_ok": bool(live_per_leg["drivers_ok"]),
        "live_vehicles_ok": bool(live_per_leg["vehicles_ok"]),
        "live_route_approved": bool(live_per_leg["route_ok"]),
        "live_within_window": bool(live_per_leg["time_ok"]),
    }
    response["snapshot_overall"] = bool(snapshot_overall)

    return make_object_response(response, http_status=200)


# ---------------------------------------------------------------------------
# GET /v1/permits — list, paginated
# ---------------------------------------------------------------------------


@permits_bp.route("/permits", methods=["GET"])
def list_permits() -> Any:
    """The paginated list of permits. The sort-order deviation per the
    §2.3 paragraph's permit-list note: `created_at` descending then
    `id` descending so the head of the page is the most-recently-
    filed application. The two optional filters are the
    `lifecycle_status` comma-list (subset of the five-state enum) and
    the `company_id` filter the operator may only set to its own
    `X-User-ID` (a mismatched explicit `company_id` returns
    `ERR_CROSS_TENANT_ACCESS` 403 per the §2.6's closing paragraph's
    "the operator's explicit-but-mismatched company_id is the cross-
    tenant 403" rule). The regulator may pass any value.

    The standard pagination's `limit`-default-10-and-range-1-to-100
    rule from the `parse_pagination_query` helper.
    """
    limit, offset = parse_pagination_query()
    role, user_id = current_principal()

    raw_lifecycle = request.args.get("lifecycle_status")
    lifecycle_filter = parse_comma_filter_query(
        raw_lifecycle,
        allowed=PERMIT_LIFECYCLE_STATES,
        field_name="lifecycle_status",
    )

    raw_company_id = request.args.get("company_id")
    explicit_company_id_filter: str | None = None
    if raw_company_id is not None:
        explicit_company_id_filter = raw_company_id.strip() or None
    if role == "CompanyOperator":
        if (
            explicit_company_id_filter is not None
            and explicit_company_id_filter != user_id
        ):
            raise APIError(
                "ERR_CROSS_TENANT_ACCESS",
                f"Operator {user_id!r} cannot list permits of another "
                f"tenant {explicit_company_id_filter!r}.",
                details={
                    "operator_id": user_id,
                    "requested_company_id": explicit_company_id_filter,
                },
            )
        effective_company_filter: str | None = user_id  # implicit self
    else:
        effective_company_filter = explicit_company_id_filter

    rows = []
    for r in list_all("Permit"):
        if effective_company_filter is not None and r.get("company_id") != effective_company_filter:
            continue
        if lifecycle_filter is not None and r.get("lifecycle_status") not in lifecycle_filter:
            continue
        rows.append(r)
    rows.sort(
        key=lambda r: (r.get("created_at", ""), r.get("id", "")), reverse=True
    )

    page, total, has_more = paginate(rows, limit, offset)
    payload = [_serialize_permit(r) for r in page]
    return make_array_response(
        payload, limit=limit, offset=offset, total_count=total, has_more=has_more
    )


# ---------------------------------------------------------------------------
# POST /v1/permits/<permit_id>/issue — regulator's DRAFT → ACTIVE
# ---------------------------------------------------------------------------


@permits_bp.route("/permits/<permit_id>/issue", methods=["POST"])
def post_permit_issue(permit_id: str) -> Any:
    """The atomic write-and-debit transaction of the issue: compute
    the fee via the `annual_renewal_fee` formula with `is_late=False`
    (the issue is by definition not a renewal so the late-flag is
    forced false), debit the parent company's wallet by the fee in
    cents, write the on-row `issue_fee_cents` field, write the
    `valid_until = valid_from + PERMIT_DEFAULT_VALIDITY_DAYS` and the
    `issued_at = now()` and the `issued_by = regulator's X-User-ID`,
    write the five strict-snapshot fields with the all-true values
    (the issue's preconditions guarantee every leg is currently green,
    so the snapshot is the all-pass initial state), set
    `last_verified_at = now()`, flip `lifecycle_status` to `ACTIVE`,
    bump the row's `version` and refresh the `updated_at`.

    The response embeds the canonical permit row plus the wallet-
    ledger sub-object `{wallet_debited_cents, new_wallet_balance_cents}`
    the §1.5's `response_payload_schema` names for the test layer's
    atomicity assertion on the wallet-side delta.

    The validation tier walks the priority-100-through-priority-540
    sequence: auth, RBAC, existence, the same-row-state-must-be-DRAFT,
    the cross-entity-state checks on the company and the route, the
    per-driver-endorsement and per-vehicle-inspection checks against
    the would-be `valid_until`, the hazard-class-subset-of-intersection
    re-check (the second time-point of the §3.4 prose), the
    cardinality-and-vehicle-list bounds (the dedicated
    `ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE` 422 if the bounds were
    violated post-application — which the create-step already checked,
    so this is defensive), the fiscal-tier wallet-balance check at
    priority 540 firing `ERR_INSUFFICIENT_WALLET_BALANCE` 402 on a
    short wallet, the OCC check at priority 560.

    The PRD §3.5's "the wallet check is the last line of defense at
    issue time, fired only after all the regulatory checks pass" rule
    is the integer-priority ordering's natural consequence: the
    fiscal-tier-540 is the highest integer priority in the Tier-5
    business-rule tier and so fires after all the safety-and-
    referential-priority-510-through-526 checks. The rule-5 priority-
    conflict-D pin "the state-tier 400 beats the fiscal-tier 540" is
    realized by the state-check firing earlier in the handler's
    code-order than the wallet check.
    """
    permit = lookup_path_resource("Permit", permit_id, "ERR_PERMIT_NOT_FOUND")
    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]

    role, regulator_user_id = current_principal()
    # The regulator is cross-tenant-exempt; no cross-tenant check here.
    # The RBAC matrix's allow-set for this endpoint is the singleton
    # `{RegulatorOfficer}`, so the auth middleware has already rejected
    # any other role.

    # The OCC check.
    occ = check_occ(permit, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on the Permit.",
            details={
                "expected_version": body.get("version"),
                "actual_version": permit.get("version"),
            },
        )
    # The optional issue_note for the audit trail.
    require_str(
        body, "issue_note", length_range=OPTIONAL_NOTE_LEN_RANGE, optional=True
    )

    # The state precondition.
    pre_status = permit.get("lifecycle_status")
    if pre_status != "DRAFT":
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot issue a permit in {pre_status!r}; the required "
            f"source state is 'DRAFT'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["DRAFT"],
                "endpoint": "POST /v1/permits/<permit_id>/issue",
            },
        )

    # The cross-entity-state recheck at the issue moment per the §3.5
    # "the issue-step's check fires the same five-leg conjunction as
    # the application-time check, against the moment-of-issue
    # grounding-entity state, since the entities may have changed in
    # the application-to-issue gap" rule.
    company = find("TransportCompany", permit.get("company_id"))
    if company is None or company.get("qualification_status") != "APPROVED":
        raise APIError(
            "ERR_COMPANY_NOT_QUALIFIED",
            f"Parent TransportCompany's qualification_status is not "
            f"'APPROVED' at issue time.",
            details={
                "company_id": permit.get("company_id"),
                "current_status": (
                    company.get("qualification_status") if company else None
                ),
            },
        )
    route = find("TransportRoute", permit.get("route_id"))
    if route is None or route.get("approval_status") != "APPROVED":
        raise APIError(
            "ERR_ROUTE_NOT_APPROVED",
            f"Route's approval_status is not 'APPROVED' at issue time.",
            details={
                "route_id": permit.get("route_id"),
                "current_status": route.get("approval_status") if route else None,
            },
        )

    # The would-be `valid_until` for the term-coverage checks.
    valid_from_str = permit.get("valid_from")
    if valid_from_str is None:
        raise APIError(
            "ERR_VALIDATION",
            "Permit has no `valid_from` value at issue time.",
            details={"field": "valid_from"},
        )
    valid_from = parse_iso(valid_from_str)
    new_valid_until = valid_from + timedelta(
        days=constants.permit_default_validity_days
    )

    # The hazard-class-subset re-check.
    _check_hazard_classes_subset_of_intersection(
        list(permit.get("hazard_classes", [])),
        permit.get("company_id"),
        permit.get("route_id"),
    )

    # The vehicle-list cardinality bound re-check (the body's create-
    # time cardinality was checked then; the issue-step has the same
    # cardinality bound applying to the now-fixed authorized-vehicle
    # list).
    vehicle_count = len(permit.get("authorized_vehicle_ids", []) or [])
    if not (
        PERMIT_VEHICLE_LIST_MIN <= vehicle_count <= constants.max_vehicles_per_permit
    ):
        raise APIError(
            "ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE",
            f"Permit's `authorized_vehicle_ids` cardinality {vehicle_count} "
            f"is outside the inclusive range "
            f"[{PERMIT_VEHICLE_LIST_MIN}, {constants.max_vehicles_per_permit}].",
            details={
                "field": "authorized_vehicle_ids",
                "length": vehicle_count,
                "min_length": PERMIT_VEHICLE_LIST_MIN,
                "max_length": constants.max_vehicles_per_permit,
            },
        )

    # The per-driver and per-vehicle live validity-coverage checks
    # against the would-be `valid_until`.
    driver_rows = [
        find("Driver", did) for did in permit.get("authorized_driver_ids", [])
    ]
    for i, d in enumerate(driver_rows):
        if d is None:
            raise APIError(
                "ERR_DRIVER_NOT_FOUND",
                f"Driver id at index {i} no longer resolves at issue time.",
                details={
                    "driver_id": permit.get("authorized_driver_ids", [])[i],
                    "index": i,
                },
            )
    vehicle_rows = [
        find("Vehicle", vid) for vid in permit.get("authorized_vehicle_ids", [])
    ]
    for i, v in enumerate(vehicle_rows):
        if v is None:
            raise APIError(
                "ERR_VEHICLE_NOT_FOUND",
                f"Vehicle id at index {i} no longer resolves at issue time.",
                details={
                    "vehicle_id": permit.get("authorized_vehicle_ids", [])[i],
                    "index": i,
                },
            )
    # Filter the None-rejection above.
    driver_rows_nn = [d for d in driver_rows if d is not None]
    vehicle_rows_nn = [v for v in vehicle_rows if v is not None]
    _check_per_driver_validity_for_term(driver_rows_nn, new_valid_until, constants)
    _check_per_vehicle_validity_for_term(vehicle_rows_nn, new_valid_until)

    # Compute the fee at the issue moment with `is_late=False`. The
    # `valid_until_at_call_time=None` argument is the formula's-side
    # "this is the issue path, the late-window concept doesn't apply"
    # signal that forces the `is_late` to false.
    now = current_now()
    fee_cents, is_late = annual_renewal_fee(
        now_dt=now,
        vehicle_count=vehicle_count,
        valid_until_at_call_time=None,  # forces is_late=False
        constants=constants,
    )
    # `is_late` should be False on the issue path; the assertion is a
    # defensive railing.
    assert is_late is False

    # The fiscal-tier wallet-balance check at priority 540.
    wallet_balance = int(company.get("wallet_balance_cents", 0))
    if wallet_balance < fee_cents:
        raise APIError(
            "ERR_INSUFFICIENT_WALLET_BALANCE",
            f"Parent company's wallet balance {wallet_balance} is less "
            f"than the computed issue fee of {fee_cents} cents.",
            details={
                "company_id": permit.get("company_id"),
                "wallet_balance_cents": wallet_balance,
                "fee_cents": fee_cents,
                "shortfall_cents": fee_cents - wallet_balance,
            },
        )

    # The atomic write-and-debit transaction under the global lock.
    with STATE_LOCK:
        # Debit the wallet.
        company["wallet_balance_cents"] = wallet_balance - fee_cents
        bump_version(company)

        # Write the permit's post-issue fields.
        permit["valid_until"] = iso_format(new_valid_until)
        permit["issue_fee_cents"] = int(fee_cents)
        permit["issued_at"] = iso_format(now)
        permit["issued_by"] = regulator_user_id
        permit["last_verified_at"] = iso_format(now)
        permit["lifecycle_status"] = "ACTIVE"
        # The strict-snapshot fields are all-true at the issue moment
        # because the per-leg checks just passed; the helper from the
        # sweep module writes the snapshot map from the live values.
        _write_snapshot_fields(permit, constants, now)
        bump_version(permit)

    # The response embeds the canonical permit row and the wallet-
    # delta sub-object.
    response = _serialize_permit(permit)
    response["wallet_ledger_entry"] = {
        "wallet_debited_cents": int(fee_cents),
        "new_wallet_balance_cents": int(company["wallet_balance_cents"]),
        "is_late": False,
    }
    return make_object_response(response, http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/permits/<permit_id>/verify-compliance — regulator's audit
# ---------------------------------------------------------------------------


@permits_bp.route("/permits/<permit_id>/verify-compliance", methods=["POST"])
def post_permit_verify_compliance(permit_id: str) -> Any:
    """The regulator's verify-compliance action. Computes the five-leg
    live recompute, compares against the on-disk snapshot's
    conjunction, and decides the post-state per the §3.5 transition
    decision table:

      - If the wall-clock has crossed `valid_until` (the half-open
        right-exclusive convention), the post-state is the terminal
        `EXPIRED` and the trip-cascade fan-out aborts every open
        child trip with `abort_reason = "PERMIT_EXPIRED_CASCADE"`.
        The cause-discriminator on the response is "WALL_CLOCK_EXPIRY",
        and the `transition_fired` value is
        `"ACTIVE_TO_EXPIRED"` or `"SUSPENDED_TO_EXPIRED"` per the pre-
        state.

      - Otherwise the live verdict is computed. If `pre_state =
        ACTIVE` and `live = False`, the post-state is `SUSPENDED`
        and the `transition_fired` is `"ACTIVE_TO_SUSPENDED"`. If
        `pre_state = SUSPENDED` and `live = True`, the post-state is
        `ACTIVE` and the `transition_fired` is
        `"SUSPENDED_TO_ACTIVE"`. Otherwise the state is unchanged and
        the `transition_fired` is `"NO_CHANGE"`.

      - In every branch the on-disk snapshot fields are rewritten to
        the live values and `last_verified_at` is set to the current
        clock value; the row's `version` bumps.

    The response carries the standard envelope's success-shape with
    the canonical fields named in the scaffold-§1.5's
    `response_payload_schema`: the permit row, the pre_status and
    post_status, the transition_fired discriminator, the live_per_leg
    boolean map keyed by the five canonical leg names, and the
    snapshot_per_leg pre-write values for the test layer's comparison.

    The pre-state allow-set is `{ACTIVE, SUSPENDED}`; the DRAFT case
    is the generic `ERR_INVALID_STATE_TRANSITION` 409 (a DRAFT permit
    has no snapshot to verify against — the issue step is the first
    write of the snapshot), the EXPIRED-and-VOIDED terminal cases are
    the same generic error.

    The concurrency-rules §1.2.1 entry on the verify-compliance
    same-row race serializes on the permit's `version` field; the
    OCC contract's `ERR_VERSION_CONFLICT` 409 fires on the loser.
    """
    permit = lookup_path_resource("Permit", permit_id, "ERR_PERMIT_NOT_FOUND")
    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]

    occ = check_occ(permit, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on the Permit during verify-compliance.",
            details={
                "expected_version": body.get("version"),
                "actual_version": permit.get("version"),
            },
        )
    require_str(
        body, "note", length_range=OPTIONAL_NOTE_LEN_RANGE, optional=True
    )

    pre_status = permit.get("lifecycle_status")
    if pre_status not in ("ACTIVE", "SUSPENDED"):
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot verify-compliance on a permit in {pre_status!r}; "
            f"the legal source states are 'ACTIVE' and 'SUSPENDED'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["ACTIVE", "SUSPENDED"],
                "endpoint": "POST /v1/permits/<permit_id>/verify-compliance",
            },
        )

    now = current_now()

    # The snapshot-before-the-write, captured for the response's
    # `snapshot_per_leg` field.
    snapshot_overall_pre, snapshot_per_leg_pre = permit_validity_check(
        permit, mode="snapshot", constants=constants, now_override=now
    )

    # The wall-clock-expiry-first check: if `now >= valid_until` the
    # post-state is the terminal EXPIRED and the trip-cascade fires.
    valid_until_str = permit.get("valid_until")
    valid_until = parse_iso(valid_until_str) if valid_until_str else None

    transition_fired: str = "NO_CHANGE"
    post_status: str = pre_status
    cascade_trip_aborts: list[str] = []

    with STATE_LOCK:
        if valid_until is not None and now >= valid_until:
            # Wall-clock-expiry. The trip-cascade fan-out fires.
            cascade_trip_aborts = _abort_open_trips_of_permit(
                permit_id, "PERMIT_EXPIRED_CASCADE", now
            )
            permit["lifecycle_status"] = "EXPIRED"
            permit["snapshot_within_window"] = False
            permit["last_verified_at"] = iso_format(now)
            post_status = "EXPIRED"
            transition_fired = (
                "ACTIVE_TO_EXPIRED"
                if pre_status == "ACTIVE"
                else "SUSPENDED_TO_EXPIRED"
            )
            bump_version(permit)
        else:
            # The standard live-vs-snapshot decision.
            live_overall, live_per_leg = permit_validity_check(
                permit, mode="live", constants=constants, now_override=now
            )
            if pre_status == "ACTIVE" and not live_overall:
                permit["lifecycle_status"] = "SUSPENDED"
                post_status = "SUSPENDED"
                transition_fired = "ACTIVE_TO_SUSPENDED"
            elif pre_status == "SUSPENDED" and live_overall:
                permit["lifecycle_status"] = "ACTIVE"
                post_status = "ACTIVE"
                transition_fired = "SUSPENDED_TO_ACTIVE"
            else:
                transition_fired = "NO_CHANGE"

            # Refresh the snapshot fields to the live values regardless
            # of whether a transition fired — the snapshot is the
            # canonical "the verify-compliance has run as of `now`"
            # record.
            _write_snapshot_fields(permit, constants, now)
            permit["last_verified_at"] = iso_format(now)
            bump_version(permit)

    # Recompute the live verdict on the now-written snapshot for the
    # response's `live_per_leg` field (the post-write snapshot equals
    # the live verdict by construction of `_write_snapshot_fields`).
    live_overall_post, live_per_leg_post = permit_validity_check(
        permit, mode="live", constants=constants, now_override=now
    )

    response_body = {
        "permit": _serialize_permit(permit),
        "pre_status": pre_status,
        "post_status": post_status,
        "transition_fired": transition_fired,
        "live_per_leg": {
            "live_company_qualified": bool(live_per_leg_post["company_ok"]),
            "live_drivers_ok": bool(live_per_leg_post["drivers_ok"]),
            "live_vehicles_ok": bool(live_per_leg_post["vehicles_ok"]),
            "live_route_approved": bool(live_per_leg_post["route_ok"]),
            "live_within_window": bool(live_per_leg_post["time_ok"]),
        },
        "snapshot_per_leg": {
            "snapshot_company_qualified": bool(snapshot_per_leg_pre["company_ok"]),
            "snapshot_drivers_ok": bool(snapshot_per_leg_pre["drivers_ok"]),
            "snapshot_vehicles_ok": bool(snapshot_per_leg_pre["vehicles_ok"]),
            "snapshot_route_approved": bool(snapshot_per_leg_pre["route_ok"]),
            "snapshot_within_window": bool(snapshot_per_leg_pre["time_ok"]),
        },
        "snapshot_overall_pre": bool(snapshot_overall_pre),
        "cascade_trip_aborts": cascade_trip_aborts,
    }
    return make_object_response(response_body, http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/permits/<permit_id>/renew — operator's annual renewal
# ---------------------------------------------------------------------------


@permits_bp.route("/permits/<permit_id>/renew", methods=["POST"])
def post_permit_renew(permit_id: str) -> Any:
    """The operator's annual renewal action. The two-edge renewal-
    window-check is the §2.7's priority-541 and -542 pair:
    `now < valid_until - RENEWAL_OPEN_WINDOW_DAYS` is
    `ERR_RENEWAL_TOO_EARLY` 409, and `now >= valid_until` is
    `ERR_RENEWAL_AFTER_EXPIRY` 409. The inner-late-grace window's
    `is_late` flag drives the formula's-conditional-add per §2.11.

    The body's optional `authorized_driver_ids`, `authorized_vehicle_ids`,
    and `hazard_classes` arrays atomically replace the on-row arrays
    when present (the §3.6 paragraph's "the replacement is total, not
    a merge" rule), with the same per-driver and per-vehicle term-
    coverage checks against the new would-be `valid_until = prior
    valid_until + PERMIT_DEFAULT_VALIDITY_DAYS`. The
    `hazard_classes`-subset-of-the-company-route-intersection rule
    fires the body-shape `ERR_VALIDATION` 422 on a miss.

    The wallet-debit-and-the-renewal-history-append happens in one
    atomic transaction under the global lock so the wallet-balance-
    vs-the-renewal-history-sum conservation identity of §2.11 holds
    across the action.

    The pre-state must be ACTIVE; SUSPENDED, EXPIRED, and VOIDED are
    different rejection cases per the §3.6 closing paragraph:
    SUSPENDED-and-DRAFT-and-VOIDED give the generic
    `ERR_INVALID_STATE_TRANSITION` 409, and the EXPIRED case maps to
    the specific `ERR_RENEWAL_AFTER_EXPIRY` 409 because the cause is
    the wall-clock-expiry that the renewal-handler's embedded wall-
    clock-check picks up before the state-check would name. The
    implementation's check order is: state-must-be-ACTIVE (generic
    state error on a DRAFT-SUSPENDED-or-VOIDED source), wall-clock-
    expiry check (ERR_RENEWAL_AFTER_EXPIRY on `now >= valid_until`
    even when the on-disk status is ACTIVE because the sweep has not
    yet flipped it), the outer-renewal-too-early check, the body's
    optional-list-replacement validations, the cross-entity-state
    re-checks on the company and route, the per-driver and per-
    vehicle term-coverage re-checks, the hazard-classes re-check, the
    fee computation, the fiscal-tier wallet-balance check, and the
    OCC version match.
    """
    permit = lookup_path_resource("Permit", permit_id, "ERR_PERMIT_NOT_FOUND")
    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]
    role, operator_id = current_principal()

    # The cross-tenant check: the operator's `X-User-ID` must equal
    # the permit's `company_id`.
    assert_cross_tenant_ownership("Permit", permit)

    # The OCC check.
    occ = check_occ(permit, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on the Permit during renewal.",
            details={
                "expected_version": body.get("version"),
                "actual_version": permit.get("version"),
            },
        )

    # The optional `renew_note`.
    require_str(
        body, "renew_note", length_range=OPTIONAL_NOTE_LEN_RANGE, optional=True
    )

    pre_status = permit.get("lifecycle_status")

    # The wall-clock-expiry-check fires before the state-allow-set
    # check in the §3.6 paragraph's "the renewal handler maps the
    # EXPIRED case onto the specific ERR_RENEWAL_AFTER_EXPIRY rather
    # than the generic state error" rule. The handler observes the
    # current wall clock first.
    now = current_now()
    valid_until_str = permit.get("valid_until")
    if valid_until_str is None:
        # The permit has no `valid_until` — it has never been issued
        # (so it's in DRAFT) or there's a defensive inconsistency.
        # The pre-state check below catches the DRAFT case as the
        # generic state error.
        valid_until = None
    else:
        valid_until = parse_iso(valid_until_str)

    if pre_status == "EXPIRED" or (
        pre_status in ("ACTIVE", "SUSPENDED") and valid_until is not None and now >= valid_until
    ):
        # The permit has crossed its expiry — either the on-disk
        # status is already EXPIRED (the sweep has run) or the wall
        # clock is past `valid_until` even though the on-disk status
        # is still ACTIVE-or-SUSPENDED (the sweep has not yet run).
        # The dedicated cause-error is `ERR_RENEWAL_AFTER_EXPIRY`.
        raise APIError(
            "ERR_RENEWAL_AFTER_EXPIRY",
            f"Permit has reached or passed its `valid_until` at the "
            f"renewal moment; the term has ended.",
            details={
                "permit_id": permit_id,
                "valid_until": valid_until_str,
                "now": iso_format(now),
                "lifecycle_status": pre_status,
            },
        )

    if pre_status != "ACTIVE":
        # The remaining non-ACTIVE cases (DRAFT, SUSPENDED, VOIDED).
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot renew a permit in {pre_status!r}; the required "
            "source state is 'ACTIVE'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["ACTIVE"],
                "endpoint": "POST /v1/permits/<permit_id>/renew",
            },
        )

    # We are guaranteed at this point: pre_status == "ACTIVE" and
    # now < valid_until. The renewal-window's left-edge check is the
    # outer-too-early predicate.
    assert valid_until is not None
    open_window_start = valid_until - timedelta(
        days=constants.renewal_open_window_days
    )
    if now < open_window_start:
        raise APIError(
            "ERR_RENEWAL_TOO_EARLY",
            f"The renewal window opens at "
            f"{iso_format(open_window_start)!r} (which is "
            f"{constants.renewal_open_window_days} days before "
            f"`valid_until` = {iso_format(valid_until)!r}); the current "
            f"clock value {iso_format(now)!r} is strictly earlier.",
            details={
                "now": iso_format(now),
                "renewal_window_opens_at": iso_format(open_window_start),
                "valid_until": iso_format(valid_until),
                "renewal_open_window_days": constants.renewal_open_window_days,
            },
        )

    # Body's optional new authorized arrays. The total-replacement
    # semantics means a present body field is the full new array, a
    # missing one keeps the prior. The cardinality and uniqueness
    # checks fire on the present-body's-array.
    new_driver_ids_raw = require_array(
        body,
        "authorized_driver_ids",
        element_type=str,
        optional=True,
        length_range=(PERMIT_DRIVER_LIST_MIN, PERMIT_DRIVER_LIST_MAX),
        no_duplicates=True,
    )
    new_vehicle_ids_raw = require_array(
        body,
        "authorized_vehicle_ids",
        element_type=str,
        optional=True,
        length_range=(PERMIT_VEHICLE_LIST_MIN, constants.max_vehicles_per_permit),
        no_duplicates=True,
        error_id_for_length="ERR_PERMIT_VEHICLE_COUNT_OUT_OF_RANGE",
    )
    new_hazard_classes_raw = require_array(
        body,
        "hazard_classes",
        element_type=str,
        optional=True,
        no_duplicates=True,
    )

    effective_driver_ids = (
        list(new_driver_ids_raw)
        if new_driver_ids_raw is not None
        else list(permit.get("authorized_driver_ids", []))
    )
    effective_vehicle_ids = (
        list(new_vehicle_ids_raw)
        if new_vehicle_ids_raw is not None
        else list(permit.get("authorized_vehicle_ids", []))
    )
    effective_hazard_classes = (
        list(
            validate_hazard_class_array(
                new_hazard_classes_raw, field="hazard_classes"
            )
        )
        if new_hazard_classes_raw is not None
        else list(permit.get("hazard_classes", []))
    )

    # The new would-be `valid_until` = prior `valid_until` +
    # PERMIT_DEFAULT_VALIDITY_DAYS per the §3.6 paragraph's "the term-
    # end is anchored to the previous term-end, not the renewal-call
    # moment" stride rule.
    new_valid_until = valid_until + timedelta(
        days=constants.permit_default_validity_days
    )

    # The body's-foreign-key existence walks if the new arrays are
    # present. The cross-tenant-as-not-found rule applies the same as
    # the application step.
    if new_driver_ids_raw is not None or new_vehicle_ids_raw is not None:
        driver_rows, vehicle_rows = _validate_authorized_lists_existence_and_tenancy(
            effective_driver_ids, effective_vehicle_ids, operator_id
        )
    else:
        # Both arrays unchanged — re-read the existing rows for the
        # validity check. The existence is guaranteed since the
        # original issue passed the check, but a delete-driver-or-
        # vehicle action would invalidate the reference; the scaffold
        # has no such delete endpoint so the resolution is always
        # successful in practice.
        driver_rows = []
        for did in effective_driver_ids:
            d = find("Driver", did)
            if d is None:
                raise APIError(
                    "ERR_DRIVER_NOT_FOUND",
                    f"Driver {did!r} from the permit's existing "
                    f"`authorized_driver_ids` no longer resolves.",
                    details={"driver_id": did},
                )
            driver_rows.append(d)
        vehicle_rows = []
        for vid in effective_vehicle_ids:
            v = find("Vehicle", vid)
            if v is None:
                raise APIError(
                    "ERR_VEHICLE_NOT_FOUND",
                    f"Vehicle {vid!r} from the permit's existing "
                    f"`authorized_vehicle_ids` no longer resolves.",
                    details={"vehicle_id": vid},
                )
            vehicle_rows.append(v)

    # The cross-entity-state re-checks against the new would-be term.
    company = find("TransportCompany", permit.get("company_id"))
    if company is None or company.get("qualification_status") != "APPROVED":
        raise APIError(
            "ERR_COMPANY_NOT_QUALIFIED",
            "The parent TransportCompany's qualification_status is not "
            "'APPROVED' at the renewal moment.",
            details={
                "company_id": permit.get("company_id"),
                "current_status": (
                    company.get("qualification_status") if company else None
                ),
            },
        )
    route = find("TransportRoute", permit.get("route_id"))
    if route is None or route.get("approval_status") != "APPROVED":
        raise APIError(
            "ERR_ROUTE_NOT_APPROVED",
            "The route's approval_status is not 'APPROVED' at the "
            "renewal moment.",
            details={
                "route_id": permit.get("route_id"),
                "current_status": route.get("approval_status") if route else None,
            },
        )

    # The hazard-classes-subset-of-the-intersection check.
    _check_hazard_classes_subset_of_intersection(
        effective_hazard_classes,
        permit.get("company_id"),
        permit.get("route_id"),
    )

    # The per-driver and per-vehicle term-coverage checks against the
    # new would-be `valid_until`.
    _check_per_driver_validity_for_term(driver_rows, new_valid_until, constants)
    _check_per_vehicle_validity_for_term(vehicle_rows, new_valid_until)

    # Compute the renewal fee.
    fee_cents, is_late = annual_renewal_fee(
        now_dt=now,
        vehicle_count=len(effective_vehicle_ids),
        valid_until_at_call_time=valid_until,
        constants=constants,
    )

    # The fiscal-tier wallet-balance check.
    wallet_balance = int(company.get("wallet_balance_cents", 0))
    if wallet_balance < fee_cents:
        raise APIError(
            "ERR_INSUFFICIENT_WALLET_BALANCE",
            f"Parent company's wallet balance {wallet_balance} cents is "
            f"less than the renewal fee {fee_cents} cents.",
            details={
                "company_id": permit.get("company_id"),
                "wallet_balance_cents": wallet_balance,
                "fee_cents": int(fee_cents),
                "is_late": bool(is_late),
                "shortfall_cents": fee_cents - wallet_balance,
            },
        )

    # The atomic write-and-debit-and-history-append transaction.
    with STATE_LOCK:
        company["wallet_balance_cents"] = wallet_balance - fee_cents
        bump_version(company)

        renewal_entry = {
            "renewed_at": iso_format(now),
            "fee_cents": int(fee_cents),
            "late_penalty_applied": bool(is_late),
            "prior_valid_until": iso_format(valid_until),
            "new_valid_until": iso_format(new_valid_until),
        }
        history = list(permit.get("renewal_history", []) or [])
        history.append(renewal_entry)
        permit["renewal_history"] = history

        # The optional authorized-arrays replacement.
        if new_driver_ids_raw is not None:
            permit["authorized_driver_ids"] = effective_driver_ids
        if new_vehicle_ids_raw is not None:
            permit["authorized_vehicle_ids"] = effective_vehicle_ids
        if new_hazard_classes_raw is not None:
            permit["hazard_classes"] = effective_hazard_classes

        # The term extension.
        permit["valid_until"] = iso_format(new_valid_until)

        # The embedded verify-compliance pass refreshes the snapshot
        # fields against the new authorized lists and the new term.
        _write_snapshot_fields(permit, constants, now)
        permit["last_verified_at"] = iso_format(now)

        # The lifecycle_status stays ACTIVE on a renewal (the
        # §3.6 paragraph names "the renewal does not change the state-
        # machine state because the permit was and remains active —
        # only the term's right edge moves and the fee meter ticks").
        bump_version(permit)

    response = _serialize_permit(permit)
    response["wallet_ledger_entry"] = {
        "wallet_debited_cents": int(fee_cents),
        "new_wallet_balance_cents": int(company["wallet_balance_cents"]),
        "is_late": bool(is_late),
        "renewal_history_entry": renewal_entry,
    }
    return make_object_response(response, http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/permits/<permit_id>/void-issue — regulator's clerical-error reversal
# ---------------------------------------------------------------------------


@permits_bp.route("/permits/<permit_id>/void-issue", methods=["POST"])
def post_permit_void_issue(permit_id: str) -> Any:
    """The regulator's clerical-error reversal of the issue. Gated to
    the 24-hour closed-right duration window from the permit's
    `issued_at` per the §3.6 closing paragraph. The refund amount is
    the literal sum `issue_fee_cents + sum(renewal_history[*].fee_cents)`
    per the §2.11 conservation invariant on the wallet axis. The
    wallet is credited and the on-row fields `voided_at` and
    `void_refunded_cents` are written, and the cascade onto the
    permit's open child trips fires synchronously with the
    `abort_reason = "PERMIT_SUSPENDED_CASCADE"` enum-economy-reuse
    value per the §2.8 abort-reason taxonomy.

    The pre-state must be `ACTIVE`; the SUSPENDED-and-DRAFT-and-
    EXPIRED-and-VOIDED cases get the generic state error. The body's
    required `reason_note` is the 1-to-500-character free-text audit
    cause; the optional `version` engages the OCC.

    The §1.2.1 concurrency-rules entry on the renew-vs-void-issue
    race serializes on the permit row's `version` field via the OCC
    contract, with the loser getting `ERR_VERSION_CONFLICT` 409.
    """
    permit = lookup_path_resource("Permit", permit_id, "ERR_PERMIT_NOT_FOUND")
    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]

    occ = check_occ(permit, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on the Permit during void-issue.",
            details={
                "expected_version": body.get("version"),
                "actual_version": permit.get("version"),
            },
        )

    reason_note = require_str(
        body, "reason_note", length_range=GENERIC_REASON_NOTE_LEN_RANGE
    )

    pre_status = permit.get("lifecycle_status")
    if pre_status != "ACTIVE":
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot void-issue a permit in {pre_status!r}; the "
            f"required source state is 'ACTIVE'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["ACTIVE"],
                "endpoint": "POST /v1/permits/<permit_id>/void-issue",
            },
        )

    issued_at_str = permit.get("issued_at")
    if issued_at_str is None:
        # An ACTIVE permit must have a non-null `issued_at` per the
        # issue-step's side-effects; defensive guard.
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            "Permit is ACTIVE but has no `issued_at` value, an "
            "internal inconsistency.",
            details={"permit_id": permit_id},
        )
    issued_at = parse_iso(issued_at_str)
    now = current_now()
    elapsed = now - issued_at
    window = timedelta(hours=constants.void_issue_window_hours)
    # Closed-right convention on the duration: the boundary moment
    # `elapsed == window` is the last in-window moment; strictly larger
    # is out-of-window.
    if elapsed > window:
        raise APIError(
            "ERR_VOID_WINDOW_CLOSED",
            f"The void-issue window has closed: {elapsed.total_seconds()/3600.0:.6f} hours "
            f"have elapsed since `issued_at` "
            f"{iso_format(issued_at)!r}, exceeding the "
            f"{constants.void_issue_window_hours}-hour window.",
            details={
                "issued_at": iso_format(issued_at),
                "now": iso_format(now),
                "elapsed_hours": elapsed.total_seconds() / 3600.0,
                "window_hours": constants.void_issue_window_hours,
            },
        )

    # The refund-amount computation per the conservation invariant.
    issue_fee = int(permit.get("issue_fee_cents") or 0)
    renewal_sum = sum(
        int(e.get("fee_cents", 0))
        for e in (permit.get("renewal_history") or [])
    )
    refund_cents = issue_fee + renewal_sum

    # The atomic wallet-credit-and-state-flip-and-trip-cascade.
    company = find("TransportCompany", permit.get("company_id"))
    if company is None:
        raise APIError(
            "ERR_COMPANY_NOT_FOUND",
            "Parent TransportCompany of the voided permit does not "
            "resolve.",
            details={"company_id": permit.get("company_id")},
        )

    with STATE_LOCK:
        company["wallet_balance_cents"] = int(
            company.get("wallet_balance_cents", 0)
        ) + refund_cents
        bump_version(company)

        permit["lifecycle_status"] = "VOIDED"
        permit["voided_at"] = iso_format(now)
        permit["void_refunded_cents"] = int(refund_cents)
        permit.setdefault("void_reason_note", reason_note)
        bump_version(permit)

        # Cascade-abort the open child trips with the enum-economy-
        # reused discriminator value `PERMIT_SUSPENDED_CASCADE` per
        # the §2.8 abort-reason taxonomy's "the on-disk discriminator
        # for the void-cascade case is the suspended-cascade value to
        # keep the four-value enum compact" rule.
        cascade_trip_aborts = _abort_open_trips_of_permit(
            permit_id, "PERMIT_SUSPENDED_CASCADE", now
        )

    response = _serialize_permit(permit)
    response["wallet_ledger_entry"] = {
        "wallet_credited_cents": int(refund_cents),
        "new_wallet_balance_cents": int(company["wallet_balance_cents"]),
        "issue_fee_component": int(issue_fee),
        "renewal_sum_component": int(renewal_sum),
    }
    response["cascade_summary"] = {
        "aborted_trip_ids": cascade_trip_aborts,
        "abort_reason": "PERMIT_SUSPENDED_CASCADE",
        "aborted_at": iso_format(now),
    }
    return make_object_response(response, http_status=200)
