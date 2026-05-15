"""The TransportRoute endpoints — five in the scaffold's §1.5
enumeration: create-under-company, get-by-id, submit, approve, reject.

The state-machine is the four-state DRAFT-SUBMITTED-APPROVED-REJECTED
machine the §1.2 entry names, with the cycle-closing internal arc
REJECTED-to-DRAFT inside the submit handler (the external-observable
transition from REJECTED-source to SUBMITTED-result in one call, the
same internal-collapse-bookkeeping-step pattern as the company's
REVOKED-to-DRAFT-to-SUBMITTED cycle in §3.1).

The two-time-point hazard-class-subset check the §3.4 paragraph names
as "the route's `hazard_classes_supported` array must be a subset of
the parent company's `hazard_classes_authorized` at both the submit
moment and the approve moment" is enforced on both the submit endpoint
(at submission time) and the approve endpoint (re-checked against the
company's possibly-narrower current authorized list). The failure on
either time point is the body-shape `ERR_VALIDATION` 422 with the
response message naming which class is the offender and at which
time point.

The standard system-set audit-trail fields on a route row are
`approved_at`, `approved_by`, and `rejection_reason`. The first two
are written on a successful approve; the third is written on a
successful reject and cleared on the next submit (the cycle's
"the rejection reason is wiped on the re-submit" rule from §1.2).

The body shapes:

  POST /v1/companies/<company_id>/routes:
    {
      "origin_label": string 1..200,
      "destination_label": string 1..200,
      "polyline": array of {"lat": float in [-90, 90], "lon": float in
                            [-180, 180]} objects, length 2..200,
      "hazard_classes_supported": non-empty no-duplicates array of UN
                                  hazard-class codes, subset of the
                                  parent company's
                                  `hazard_classes_authorized`.
    }

  POST /v1/routes/<route_id>/submit:
    {"version"?: integer for OCC}

  POST /v1/routes/<route_id>/approve:
    {"version"?: integer, "approval_note"?: string 0..500}

  POST /v1/routes/<route_id>/reject:
    {"rejection_reason": string 1..500, "version"?: integer}

There is no PATCH endpoint for editing a route in DRAFT — the operator
who wants to change the route's payload posts a fresh route. The
§3.4 paragraph's "the scaffold's keep-the-endpoint-surface-small
convention" reasoning.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app

from ..auth import (
    assert_cross_tenant_company_id_match,
    assert_cross_tenant_ownership,
    current_principal,
    lookup_path_resource,
)
from ..clock import iso_now
from ..config import (
    OPTIONAL_NOTE_LEN_RANGE,
    ROUTE_APPROVAL_STATES,
    ROUTE_LABEL_LEN_RANGE,
    ROUTE_REJECTION_REASON_LEN_RANGE,
)
from ..envelope import get_json_body, make_object_response
from ..errors import APIError
from ..store import (
    bump_version,
    check_occ,
    find,
    insert,
    stamp_create,
)
from ..validation import (
    require_array,
    require_str,
    validate_hazard_class_array,
    validate_polyline,
)


routes_bp = Blueprint("routes", __name__)


def _serialize_route(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def _check_hazard_classes_subset_of_company(
    hazard_classes: list[str], company_id: str, field_name: str
) -> None:
    """The two-time-point check from §3.4: the route's
    `hazard_classes_supported` (or the to-be-validated body's-`hazard_classes`-
    on-permit-creation) array must be a subset of the parent company's
    current `hazard_classes_authorized` set. A miss is the body-shape
    `ERR_VALIDATION` 422 with the offending classes listed in the
    detail payload.
    """
    company = find("TransportCompany", company_id)
    if company is None:
        raise APIError(
            "ERR_COMPANY_NOT_FOUND",
            f"Parent TransportCompany {company_id!r} does not resolve.",
            details={"company_id": company_id},
        )
    company_authorized = set(company.get("hazard_classes_authorized", []) or [])
    requested = set(hazard_classes)
    if not requested.issubset(company_authorized):
        offending = sorted(requested - company_authorized)
        raise APIError(
            "ERR_VALIDATION",
            f"Field {field_name!r} contains hazard classes {offending!r} "
            f"that are not in the parent company's "
            f"'hazard_classes_authorized' set.",
            details={
                "field": field_name,
                "offending": offending,
                "company_id": company_id,
                "company_authorized": sorted(company_authorized),
            },
        )


# ---------------------------------------------------------------------------
# POST /v1/companies/<company_id>/routes — operator creates a route
# ---------------------------------------------------------------------------


@routes_bp.route("/companies/<company_id>/routes", methods=["POST"])
def post_create_route(company_id: str) -> Any:
    """Operator's children-create-under-company for the route. The
    parent-must-be-APPROVED rule, the cross-tenant rule on the URL
    path's company id, the body's per-field shape-and-range checks
    on `origin_label`, `destination_label`, the `polyline` waypoint
    array, and the `hazard_classes_supported` taxonomy-membership-and-
    subset-of-the-parent-company's-authorized-list check.
    """
    parent = lookup_path_resource(
        "TransportCompany", company_id, "ERR_COMPANY_NOT_FOUND"
    )
    assert_cross_tenant_company_id_match(company_id)
    if parent.get("qualification_status") != "APPROVED":
        raise APIError(
            "ERR_COMPANY_NOT_QUALIFIED",
            f"Cannot file a route under a company in "
            f"{parent.get('qualification_status')!r}; the company must "
            f"be 'APPROVED'.",
            details={
                "company_id": company_id,
                "current_status": parent.get("qualification_status"),
            },
        )

    body = get_json_body()

    origin_label = require_str(
        body, "origin_label", length_range=ROUTE_LABEL_LEN_RANGE
    )
    destination_label = require_str(
        body, "destination_label", length_range=ROUTE_LABEL_LEN_RANGE
    )
    polyline_raw = require_array(body, "polyline", element_type=dict)
    assert polyline_raw is not None
    polyline = validate_polyline(polyline_raw, field="polyline")
    hazard_classes_supported_raw = require_array(
        body, "hazard_classes_supported", element_type=str
    )
    assert hazard_classes_supported_raw is not None
    hazard_classes_supported = validate_hazard_class_array(
        hazard_classes_supported_raw,
        field="hazard_classes_supported",
        allow_empty=False,
    )

    # The two-time-point subset check at the submit-time (this
    # creation acts as the source-of-truth-on-the-route's-supported-
    # classes at the moment of the operator's filing — the route is
    # created in DRAFT and the operator's subsequent submit will be
    # the second time-point of the check against the then-current
    # company authorized list, and the regulator's approve will be the
    # third time-point per the §3.4 prose's "the hazard-class
    # consistency is checked at every transition that pivots on it").
    _check_hazard_classes_subset_of_company(
        hazard_classes_supported, company_id, "hazard_classes_supported"
    )

    row: dict[str, Any] = {
        "company_id": company_id,
        "origin_label": origin_label,
        "destination_label": destination_label,
        "polyline": polyline,
        "hazard_classes_supported": list(hazard_classes_supported),
        "approval_status": "DRAFT",
        "approved_at": None,
        "approved_by": None,
        "rejection_reason": None,
    }
    stamp_create(row)
    insert("TransportRoute", row)

    return make_object_response(_serialize_route(row), http_status=201)


# ---------------------------------------------------------------------------
# GET /v1/routes/<route_id> — read one
# ---------------------------------------------------------------------------


@routes_bp.route("/routes/<route_id>", methods=["GET"])
def get_route(route_id: str) -> Any:
    """Read a TransportRoute row. The standard cross-tenant predicate
    on the route's `company_id` field for the operator side, with the
    regulator-cross-tenant-exemption.
    """
    row = lookup_path_resource(
        "TransportRoute", route_id, "ERR_ROUTE_NOT_FOUND"
    )
    assert_cross_tenant_ownership("TransportRoute", row)
    return make_object_response(_serialize_route(row), http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/routes/<route_id>/submit — operator submits (or resubmits after
# rejection — the internal-collapse cycle's entry).
# ---------------------------------------------------------------------------


@routes_bp.route("/routes/<route_id>/submit", methods=["POST"])
def post_route_submit(route_id: str) -> Any:
    """The operator's `DRAFT → SUBMITTED` or
    `REJECTED → DRAFT → SUBMITTED` cycle's submit-action. The body
    carries the optional OCC `version` integer. The two-time-point
    subset check re-fires against the parent company's current
    `hazard_classes_authorized` (which may have narrowed since the
    create), with a non-subset entry the body-shape `ERR_VALIDATION` 422.

    The handler's successful side-effects: the `approval_status` flips
    to `SUBMITTED`, the previous `rejection_reason` is cleared
    (in the REJECTED-source case from the cycle's internal-collapse),
    the `version` is bumped, the `updated_at` is refreshed.

    The polyline-min-length re-check is a no-op since the polyline is
    immutable (no PATCH endpoint), but the §1.2 entry lists it as a
    precondition for the at-rest invariant's continued validity.
    """
    row = lookup_path_resource(
        "TransportRoute", route_id, "ERR_ROUTE_NOT_FOUND"
    )
    # The cross-tenant rule on the transitive-parent company. The
    # operator's `X-User-ID` must equal the route's `company_id`.
    assert_cross_tenant_ownership("TransportRoute", row)

    body = get_json_body()
    occ = check_occ(row, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on the TransportRoute.",
            details={
                "expected_version": body.get("version"),
                "actual_version": row.get("version"),
            },
        )

    pre_status = row.get("approval_status")
    if pre_status not in ("DRAFT", "REJECTED"):
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot submit a route in {pre_status!r}; the legal source "
            f"states are 'DRAFT' or 'REJECTED'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["DRAFT", "REJECTED"],
                "endpoint": "POST /v1/routes/<route_id>/submit",
            },
        )

    # Polyline-min-length-and-well-formedness invariant. The polyline
    # is immutable post-create, so this is a defensive re-check.
    polyline = row.get("polyline") or []
    if not isinstance(polyline, list) or len(polyline) < 2:
        raise APIError(
            "ERR_VALIDATION",
            "Route's stored polyline has fewer than 2 waypoints, "
            "violating the polyline-shape invariant.",
            details={"field": "polyline", "length": len(polyline)},
        )

    # Two-time-point hazard-class subset re-check against the parent
    # company's current authorized list. A class on the route's
    # `hazard_classes_supported` no longer in the company's current
    # `hazard_classes_authorized` (because the regulator revoked it
    # out-of-band) is the body-shape `ERR_VALIDATION` 422.
    hazard_classes_supported = list(row.get("hazard_classes_supported", []))
    _check_hazard_classes_subset_of_company(
        hazard_classes_supported,
        row.get("company_id"),
        "hazard_classes_supported",
    )

    # The successful transition's side-effects.
    row["approval_status"] = "SUBMITTED"
    # Clear the prior cycle's rejection_reason on the re-submit per
    # the §1.2 entry's "the rejection_reason is wiped on the new
    # submit's transit through DRAFT" rule.
    row["rejection_reason"] = None
    bump_version(row)

    return make_object_response(_serialize_route(row), http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/routes/<route_id>/approve — regulator's approve
# ---------------------------------------------------------------------------


@routes_bp.route("/routes/<route_id>/approve", methods=["POST"])
def post_route_approve(route_id: str) -> Any:
    """The regulator's `SUBMITTED → APPROVED` transition. The body's
    optional `version` engages the OCC and the optional `approval_note`
    is a 0-to-500-character audit string. The two-time-point hazard-
    class subset re-check fires against the parent company's current
    `hazard_classes_authorized` (which may have narrowed in the
    submit-to-approve gap per the §3.4's "the regulator's approve-time
    re-check is against the company's then-current authorized list"
    rule). A failure is `ERR_VALIDATION` 422.

    The handler's successful side-effects: the `approval_status` flips
    to `APPROVED`, the `approved_at` is set to the current simulated-
    clock value, the `approved_by` is set to the regulator's `X-User-ID`
    opaque-officer-string, the `rejection_reason` field (which carries
    a stale value from a prior cycle if any) is cleared, the `version`
    is bumped, the `updated_at` is refreshed.

    The cross-tenant exemption: the regulator-role is cross-tenant
    exempt; the RBAC matrix has only `RegulatorOfficer` in the allow-
    set for this endpoint, so a non-regulator hits the auth tier's
    `ERR_ROLE_NOT_PERMITTED` 403 from the matrix-check rather than
    reaching this handler.
    """
    row = lookup_path_resource(
        "TransportRoute", route_id, "ERR_ROUTE_NOT_FOUND"
    )
    body = get_json_body()
    occ = check_occ(row, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on the TransportRoute.",
            details={
                "expected_version": body.get("version"),
                "actual_version": row.get("version"),
            },
        )
    require_str(
        body, "approval_note", length_range=OPTIONAL_NOTE_LEN_RANGE, optional=True
    )

    pre_status = row.get("approval_status")
    if pre_status != "SUBMITTED":
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot approve a route in {pre_status!r}; the required "
            f"source state is 'SUBMITTED'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["SUBMITTED"],
                "endpoint": "POST /v1/routes/<route_id>/approve",
            },
        )

    # Re-check the hazard-class subset against the parent's current
    # authorized list.
    hazard_classes_supported = list(row.get("hazard_classes_supported", []))
    _check_hazard_classes_subset_of_company(
        hazard_classes_supported,
        row.get("company_id"),
        "hazard_classes_supported",
    )

    role, regulator_user_id = current_principal()
    row["approval_status"] = "APPROVED"
    row["approved_at"] = iso_now()
    row["approved_by"] = regulator_user_id
    row["rejection_reason"] = None
    bump_version(row)

    # The deferred-cross-aggregate-cascade onto every previously-
    # SUSPENDED permit whose `route_id` is this route's id and whose
    # other validity legs hold is the §3.5's "the next verify-
    # compliance observes the live route-leg now true and fires the
    # SUSPENDED-to-ACTIVE reinstate" rule, not synchronous here.

    return make_object_response(_serialize_route(row), http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/routes/<route_id>/reject — regulator's reject
# ---------------------------------------------------------------------------


@routes_bp.route("/routes/<route_id>/reject", methods=["POST"])
def post_route_reject(route_id: str) -> Any:
    """The regulator's `SUBMITTED → REJECTED` transition. The body's
    required `rejection_reason` 1-to-500-character free-text string is
    stored on the row's `rejection_reason` field for the operator's
    read-back. The optional OCC `version` field engages the standard
    check. The `approval_status` flips to `REJECTED`, the
    `rejection_reason` is the body's value, the `version` is bumped,
    the `updated_at` is refreshed.

    The `approved_at` and `approved_by` fields are left at their prior
    values (which are typically null on a first-ever-rejection on a
    never-approved row, or carry the prior approval's audit values
    on the unreachable-in-the-scaffold's-state-graph
    APPROVED-to-SUBMITTED-to-REJECTED case — the scaffold's prose
    notes the APPROVED state has no outgoing transition in the modeled
    API surface so the "reject after a prior approval" path is
    unreachable through the API but the field-preservation behaviour
    is the documented one).
    """
    row = lookup_path_resource(
        "TransportRoute", route_id, "ERR_ROUTE_NOT_FOUND"
    )
    body = get_json_body()
    occ = check_occ(row, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on the TransportRoute.",
            details={
                "expected_version": body.get("version"),
                "actual_version": row.get("version"),
            },
        )

    rejection_reason = require_str(
        body,
        "rejection_reason",
        length_range=ROUTE_REJECTION_REASON_LEN_RANGE,
    )

    pre_status = row.get("approval_status")
    if pre_status != "SUBMITTED":
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot reject a route in {pre_status!r}; the required "
            f"source state is 'SUBMITTED'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["SUBMITTED"],
                "endpoint": "POST /v1/routes/<route_id>/reject",
            },
        )

    row["approval_status"] = "REJECTED"
    row["rejection_reason"] = rejection_reason
    bump_version(row)

    return make_object_response(_serialize_route(row), http_status=200)
