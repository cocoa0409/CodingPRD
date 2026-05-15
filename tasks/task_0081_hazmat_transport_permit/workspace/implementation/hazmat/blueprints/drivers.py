"""The Driver endpoints — three in the scaffold's §1.5 enumeration:

  POST /v1/companies/<company_id>/drivers — operator registers a driver
                                              under their company. The
                                              parent-company-must-be-
                                              APPROVED business-
                                              referential check fires
                                              `ERR_COMPANY_NOT_QUALIFIED`
                                              409. The (company_id,
                                              license_number) natural-
                                              key uniqueness check
                                              within the company fires
                                              `ERR_DUPLICATE_IDENTIFIER`
                                              409 at the business-
                                              constraint priority 520.

  GET  /v1/drivers/<driver_id>            — read-by-id. The three-role
                                              access set (CompanyOperator
                                              with the transitive-tenant
                                              on the driver's
                                              `company_id`, RegulatorOfficer
                                              cross-tenant exempt, Driver
                                              with the self-only-on-the-
                                              driver's-own-id check at
                                              priority 531).

  POST /v1/drivers/<driver_id>/refresh-endorsement — regulator's
                                              endorsement-attestation
                                              endpoint, with the two
                                              mutually-exclusive body
                                              shapes: the
                                              `(endorsement_valid_until,
                                              endorsement_classes)`
                                              attestation pair driving
                                              `NOT_ATTESTED-to-VALID`
                                              and `INVALID-to-VALID`, and
                                              the `(revoke: true,
                                              revoke_reason)` revoke
                                              pair driving the manual
                                              `VALID-to-INVALID` flip.
                                              The body's
                                              `endorsement_valid_until`
                                              must be strictly in the
                                              future, the
                                              `endorsement_classes`
                                              must be a non-empty subset
                                              of the parent company's
                                              `hazard_classes_authorized`,
                                              and the driver's
                                              `current_rolling_points`
                                              must be strictly below the
                                              threshold at the
                                              attestation moment (the
                                              regulatory interlock from
                                              §3.2).

The driver-side cascade chain from a Penalty-insert that pushes the
driver's `current_rolling_points` to at-or-above the threshold is the
rule-4 cascade-A's hops two-and-three: the Penalty-insert side-effect
recomputes the cached `current_rolling_points`, and the threshold-
crossover fires the auto-`VALID → INVALID` flip in the same atomic
transaction. The Penalty-insert handler in the `penalties` blueprint
module is the call site. The corresponding upward arm — the appeal-
uphold-zeroes-the-points-then-the-regulator-attestation-flips-back-to-
VALID two-step chain — is the §3.2 paragraph's "keep-the-regulator-in-
the-loop" convention realized by the absence of an automatic upward
flip in the sweep's per-driver step.

The wall-clock-driven downward auto-flip on the attestation's
`endorsement_valid_until` expiry is fired by the sweep's per-driver
Step 3, which is in the `sweep` module rather than this blueprint.

This blueprint contains the three direct-API endpoints and the helper
that computes the driver's-row cross-aggregate-deferred-cascade-onto-
permits on the manual revoke path (the §3.2 closing paragraph names
this as the symmetric counterpart of the company-revoke's deferred
cascade onto permits — the manual driver-revoke is a regulator's
action whose effect on every ACTIVE permit listing the driver is the
next-verify-compliance-fires-the-SUSPENDED-transition path, with the
implementation here matching the §3.1's cascade-deferred convention).

The Driver row's initial-state-on-create-fields per the §2.4 H3
defaults paragraph: `hazmat_endorsement_status = "NOT_ATTESTED"`,
`endorsement_valid_until = null`, `endorsement_classes = []`,
`current_rolling_points = 0`, the standard four common-fields quartet.
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
from ..clock import current_now, iso_format, iso_now, parse_iso
from ..config import (
    Constants,
    DRIVER_ENDORSEMENT_STATES,
    DRIVER_FULL_NAME_LEN_RANGE,
    DRIVER_LICENSE_CLASS_LEN_RANGE,
    DRIVER_LICENSE_NUMBER_LEN_RANGE,
    DRIVER_REVOKE_REASON_LEN_RANGE,
    UN_HAZARD_CLASS_CODES,
)
from ..envelope import get_json_body, make_object_response
from ..errors import APIError
from ..store import (
    bump_version,
    check_occ,
    find,
    find_driver_by_company_and_license,
    insert,
    stamp_create,
)
from ..validation import (
    require_array,
    require_bool,
    require_int,
    require_iso_datetime,
    require_present,
    require_str,
    validate_hazard_class_array,
    validate_no_whitespace,
)


drivers_bp = Blueprint("drivers", __name__)


def _serialize_driver(row: dict[str, Any]) -> dict[str, Any]:
    """The wire-shape of a Driver row. Pass-through of the on-disk
    fields the §1.1 entity-prose enumerates. The cached
    `current_rolling_points` is the driver's rolling-window sum the
    response surfaces verbatim from the row.
    """
    return dict(row)


# ---------------------------------------------------------------------------
# POST /v1/companies/<company_id>/drivers — operator registers a driver
# ---------------------------------------------------------------------------


@drivers_bp.route("/companies/<company_id>/drivers", methods=["POST"])
def post_create_driver(company_id: str) -> Any:
    """Operator's children-create. The parent-must-be-APPROVED
    business-referential check fires `ERR_COMPANY_NOT_QUALIFIED` 409
    when the parent company's `qualification_status` is not the green-
    light `APPROVED` state. The cross-tenant predicate on the URL
    path's `{company_id}` matching the operator's `X-User-ID` is the
    standard children-creation-tenant-match rule at priority 530.

    The body fields per the §1.5 row for this endpoint:
      - `full_name`: 1-to-120-character free-text legal name.
      - `license_number`: 6-to-32-character no-embedded-whitespace
                          government licence id; per-company unique
                          (the natural-key uniqueness scope is the
                          pair `(company_id, license_number)` — two
                          different companies' drivers may share the
                          same licence string).
      - `license_class`: short class code like `"A2"` or `"B1"`, free
                         string in a sensible length range.
      - `endorsement_classes_requested`: optional array of UN-hazard-
                                          class codes the operator
                                          attests the driver is
                                          qualified for; this is the
                                          operator's-attested wishlist,
                                          and the on-disk
                                          `endorsement_classes` field
                                          is initialized to the empty
                                          array (the regulator's later
                                          attestation overwrites with
                                          the actual verified set).

    The response is the 201 row in `hazmat_endorsement_status =
    "NOT_ATTESTED"` per the initial-state convention of the §1.2
    Driver state-machine's `initial_state`.
    """
    # The parent company must exist and the operator must own it.
    parent = lookup_path_resource(
        "TransportCompany", company_id, "ERR_COMPANY_NOT_FOUND"
    )
    assert_cross_tenant_company_id_match(company_id)

    # The parent-must-be-APPROVED business-referential check.
    if parent.get("qualification_status") != "APPROVED":
        raise APIError(
            "ERR_COMPANY_NOT_QUALIFIED",
            f"Cannot register a driver under a TransportCompany in "
            f"qualification_status "
            f"{parent.get('qualification_status')!r}; the company must be "
            f"'APPROVED'.",
            details={
                "company_id": company_id,
                "current_status": parent.get("qualification_status"),
            },
        )

    body = get_json_body()

    full_name = require_str(
        body, "full_name", length_range=DRIVER_FULL_NAME_LEN_RANGE
    )
    license_number = require_str(
        body, "license_number", length_range=DRIVER_LICENSE_NUMBER_LEN_RANGE
    )
    assert license_number is not None
    validate_no_whitespace(license_number, field="license_number")
    license_class = require_str(
        body, "license_class", length_range=DRIVER_LICENSE_CLASS_LEN_RANGE
    )
    endorsement_classes_requested_raw = require_array(
        body,
        "endorsement_classes_requested",
        element_type=str,
        optional=True,
        no_duplicates=True,
    )
    if endorsement_classes_requested_raw is None:
        endorsement_classes_requested_raw = []
    # The requested-classes array is allowed to be empty per the §1.5
    # row's "may be empty (no attested endorsement yet)" note. The
    # taxonomy-membership check on each entry fires the body-shape
    # `ERR_VALIDATION` 422 on a non-taxonomy value.
    if endorsement_classes_requested_raw:
        validate_hazard_class_array(
            endorsement_classes_requested_raw,
            field="endorsement_classes_requested",
            allow_empty=False,
        )

    # The per-company-scoped uniqueness on the licence number.
    existing = find_driver_by_company_and_license(company_id, license_number)
    if existing is not None:
        raise APIError(
            "ERR_DUPLICATE_IDENTIFIER",
            f"Driver license_number {license_number!r} is already in use "
            f"within company {company_id!r}.",
            details={
                "natural_key": "license_number",
                "scope": "per_company",
                "value": license_number,
                "company_id": company_id,
                "existing_driver_id": existing.get("id"),
            },
        )

    # Build the new row with the initial-state defaults per the §2.4
    # H3 paragraph. The operator's-attested wishlist field is logged
    # out-of-band rather than stored on the row; we keep it on the row
    # under the canonical `endorsement_classes_requested` field name
    # for the audit trail's introspection. The on-disk
    # `endorsement_classes` is the empty array, the regulator-attested
    # standing being unset.
    row: dict[str, Any] = {
        "company_id": company_id,
        "full_name": full_name,
        "license_number": license_number,
        "license_class": license_class,
        "endorsement_classes_requested": list(endorsement_classes_requested_raw),
        "endorsement_classes": [],
        "hazmat_endorsement_status": "NOT_ATTESTED",
        "endorsement_valid_until": None,
        "current_rolling_points": 0,
    }
    stamp_create(row)
    insert("Driver", row)

    return make_object_response(_serialize_driver(row), http_status=201)


# ---------------------------------------------------------------------------
# GET /v1/drivers/<driver_id> — read one
# ---------------------------------------------------------------------------


@drivers_bp.route("/drivers/<driver_id>", methods=["GET"])
def get_driver(driver_id: str) -> Any:
    """The driver-row read. The three-role allow-set is:
      - `CompanyOperator` with the cross-tenant transitive-parent
        rule (the operator's `X-User-ID` equals the driver's
        `company_id`); a non-self-tenant operator gets
        `ERR_CROSS_TENANT_ACCESS` 403.
      - `RegulatorOfficer` (cross-tenant exempt).
      - `Driver` with the self-only-on-the-driver's-own-id check at
        priority 531; a Driver-role's `X-User-ID` that does not equal
        the path's `{driver_id}` is the `ERR_CROSS_TENANT_ACCESS` 403
        with the meaning generalized to "wrong individual identity"
        per the §2.6 paragraph's closing paragraph.

    The existence-tier-priority-300-check fires before the cross-tenant
    tier-priority-530-check per the §2.6 conventions, so a non-existent
    path id is the 404 `ERR_DRIVER_NOT_FOUND` rather than the 403 cross-
    tenant — the rule-5 priority-conflict-B pin.
    """
    row = lookup_path_resource("Driver", driver_id, "ERR_DRIVER_NOT_FOUND")

    role, user_id = current_principal()
    # For the operator and the regulator the standard cross-tenant
    # helper does the right thing. For the Driver-role the self-only
    # variant on the driver's id is the comparison `user_id ==
    # driver_id` per the priority-531 rule.
    if role == "Driver":
        # The driver-self-only-on-the-path-id-equals-the-X-User-ID rule.
        if user_id != driver_id:
            raise APIError(
                "ERR_CROSS_TENANT_ACCESS",
                f"Driver self-only check: requester id {user_id!r} does "
                f"not equal the path id {driver_id!r}.",
                details={
                    "rule": "driver-self-only",
                    "priority": 531,
                    "requester_id": user_id,
                    "path_id": driver_id,
                },
            )
    else:
        # The CompanyOperator-and-RegulatorOfficer cross-tenant cases
        # are handled by the standard helper. The helper's
        # implementation is "regulator-exempt, operator-must-match-the-
        # tenant, driver-handled-above".
        assert_cross_tenant_ownership("Driver", row)

    return make_object_response(_serialize_driver(row), http_status=200)


# ---------------------------------------------------------------------------
# POST /v1/drivers/<driver_id>/refresh-endorsement — regulator's attestation
# ---------------------------------------------------------------------------


@drivers_bp.route("/drivers/<driver_id>/refresh-endorsement", methods=["POST"])
def post_refresh_endorsement(driver_id: str) -> Any:
    """The regulator's endorsement-attestation endpoint, with the two
    mutually-exclusive body shapes the §1.5 row names:

      Shape A (attestation):
        {"endorsement_valid_until": ISO 8601 UTC, strictly future,
         "endorsement_classes": non-empty array of UN hazard-class codes,
                                  subset of the parent company's
                                  authorized list,
         "version"?: integer for OCC}

      Shape B (revoke):
        {"revoke": true,
         "revoke_reason": string 1..500,
         "version"?: integer}

    The cross-shape detection is the standard `xor` of the canonical
    fields: shape A has the (`endorsement_valid_until`,
    `endorsement_classes`) pair without a `revoke` flag; shape B has
    the (`revoke: true`, `revoke_reason`) pair without the attestation
    fields. A body with both, with neither, or with the `revoke` flag
    set to false is the body-shape `ERR_VALIDATION` 422.

    The pre-state allow-set for the attestation shape is
    `{NOT_ATTESTED, INVALID}`; an attestation against a `VALID`-source
    is the generic state error (the regulator's path to refresh an
    already-valid attestation is a no-op-or-update — the scaffold's
    convention is the attestation-against-VALID-source is the generic
    `ERR_INVALID_STATE_TRANSITION` 409, the standard sign that the
    regulator cannot re-attest an already-valid driver without first
    revoking). The pre-state allow-set for the revoke shape is
    `{VALID}`; a revoke on a NOT_ATTESTED-or-INVALID driver is the
    same generic state error.

    The current_rolling_points-below-threshold attestation interlock
    of the §3.2 paragraph's "the regulator may not attest a driver
    whose current rolling total is at or above the threshold" rule is
    realized as a pre-state guard: a driver in `NOT_ATTESTED` or
    `INVALID` whose `current_rolling_points` is at-or-above the
    threshold cannot be attested; the response is
    `ERR_INVALID_STATE_TRANSITION` 409 with the detail-payload naming
    the threshold and the current points.

    The endorsement-classes-subset-of-the-parent-company's-authorized-
    list rule is the body-shape `ERR_VALIDATION` 422 at the catch-all
    body-shape tier. The body's `endorsement_valid_until` strictly-in-
    the-future rule is the same `ERR_VALIDATION` 422 on a non-future
    timestamp (the standard "the attestation's expiry must be in the
    future at the moment of the attestation" rule).

    The handler's successful path writes the canonical exit-state's
    fields per the §1.2 entry's side-effects list: shape A flips the
    status to `VALID` and writes the body's two attestation fields;
    shape B flips the status to `INVALID` and sets the
    `endorsement_valid_until` to the current simulated-clock value (so
    the natural wall-clock-expiry condition is retroactively true,
    matching the §3.2 paragraph's "the wall-clock-expiry rule and the
    manual revoke rule converge"). Both shapes bump the `version` and
    refresh the `updated_at`. The deferred cross-aggregate cascade
    onto every permit whose `authorized_driver_ids` contains the
    driver fires on the next verify-compliance call's snapshot-vs-
    live comparison, per the §3.1's "deferred cascade" convention.
    """
    row = lookup_path_resource("Driver", driver_id, "ERR_DRIVER_NOT_FOUND")
    body = get_json_body()
    constants: Constants = current_app.config["HAZMAT_CONSTANTS"]

    occ = check_occ(row, body)
    if occ is False:
        raise APIError(
            "ERR_VERSION_CONFLICT",
            "OCC version mismatch on the Driver row.",
            details={
                "expected_version": body.get("version"),
                "actual_version": row.get("version"),
            },
        )

    # Determine the body's shape. The shape-A fields are the two
    # attestation fields. The shape-B fields are the revoke flag and
    # the reason. A body with both shapes' fields or neither's is the
    # body-shape error.
    has_attestation_fields = (
        "endorsement_valid_until" in body or "endorsement_classes" in body
    )
    has_revoke_field = "revoke" in body
    if not has_attestation_fields and not has_revoke_field:
        raise APIError(
            "ERR_VALIDATION",
            "The refresh-endorsement body must carry either the "
            "attestation fields ('endorsement_valid_until' and "
            "'endorsement_classes') or the revoke fields "
            "('revoke', 'revoke_reason').",
        )
    if has_attestation_fields and has_revoke_field:
        raise APIError(
            "ERR_VALIDATION",
            "The refresh-endorsement body must not carry both the "
            "attestation fields and the revoke flag; the two body "
            "shapes are mutually exclusive.",
        )

    pre_status = row.get("hazmat_endorsement_status")

    if has_revoke_field:
        # Shape B: the manual revoke. The body must have the `revoke`
        # flag set to the boolean true and the `revoke_reason` string.
        revoke_flag = require_bool(body, "revoke")
        if revoke_flag is not True:
            raise APIError(
                "ERR_VALIDATION",
                "The 'revoke' field, when present, must be the boolean "
                "true.",
                details={"field": "revoke", "value": revoke_flag},
            )
        revoke_reason = require_str(
            body, "revoke_reason", length_range=DRIVER_REVOKE_REASON_LEN_RANGE
        )

        if pre_status != "VALID":
            # The revoke is only legal from VALID per the §1.2 Driver
            # state-machine entry "the revoke-shape body's
            # precondition is `hazmat_endorsement_status == VALID`".
            raise APIError(
                "ERR_INVALID_STATE_TRANSITION",
                f"Cannot revoke a driver in {pre_status!r}; the "
                f"required source state is 'VALID'.",
                details={
                    "current_state": pre_status,
                    "legal_from_states": ["VALID"],
                    "endpoint": "POST /v1/drivers/<driver_id>/refresh-endorsement (revoke shape)",
                },
            )

        # Apply the revoke. The §3.2 paragraph's "the manual-revoke
        # writes the endorsement_valid_until to the current clock so
        # the wall-clock-expiry path's observability is the same" rule
        # is realized by writing the `endorsement_valid_until` to
        # `iso_now()` alongside the status flip.
        row["hazmat_endorsement_status"] = "INVALID"
        row["endorsement_valid_until"] = iso_now()
        # The revoke reason is logged to the audit trail out-of-band
        # per the §3.2 paragraph's wording; we attach it to the on-disk
        # row's `last_revoke_reason` field for introspection.
        row["last_revoke_reason"] = revoke_reason
        bump_version(row)

        # The deferred-cascade onto the permits is the next verify-
        # compliance's drivers-leg flip-to-false observation. No
        # synchronous permit-row touch here.

        return make_object_response(_serialize_driver(row), http_status=200)

    # Shape A: the attestation. The body must have the two attestation
    # fields and may have the optional OCC `version`.
    valid_until_dt = require_iso_datetime(
        body, "endorsement_valid_until"
    )
    assert valid_until_dt is not None  # required on this shape
    # The strict-future rule per the §3.2 paragraph's "must be strictly
    # later than the current logical-clock value".
    now = current_now()
    if valid_until_dt <= now:
        raise APIError(
            "ERR_VALIDATION",
            f"'endorsement_valid_until' must be strictly in the future; "
            f"got {iso_format(valid_until_dt)!r}, now is {iso_format(now)!r}.",
            details={
                "field": "endorsement_valid_until",
                "value": iso_format(valid_until_dt),
                "now": iso_format(now),
            },
        )

    endorsement_classes_raw = require_array(
        body, "endorsement_classes", element_type=str
    )
    assert endorsement_classes_raw is not None
    endorsement_classes = validate_hazard_class_array(
        endorsement_classes_raw, field="endorsement_classes", allow_empty=False
    )
    # The subset-of-the-parent-company's-authorized-list rule.
    parent = find("TransportCompany", row.get("company_id"))
    if parent is None:
        # Defensive — the foreign-key invariant should have prevented
        # this. Map to a 404.
        raise APIError(
            "ERR_COMPANY_NOT_FOUND",
            f"Parent TransportCompany of the driver does not resolve.",
            details={"company_id": row.get("company_id")},
        )
    parent_authorized = set(parent.get("hazard_classes_authorized", []) or [])
    requested = set(endorsement_classes)
    if not requested.issubset(parent_authorized):
        # The hazard-class-subset miss is the body-shape error per the
        # §1.5 row's "endorsement_classes must be a subset of the
        # parent company's hazard_classes_authorized" rule.
        offending = sorted(requested - parent_authorized)
        raise APIError(
            "ERR_VALIDATION",
            f"'endorsement_classes' contains hazard classes "
            f"{offending!r} that are not in the parent company's "
            f"'hazard_classes_authorized' set.",
            details={
                "field": "endorsement_classes",
                "offending": offending,
                "company_authorized": sorted(parent_authorized),
            },
        )

    # The state-allowed-source-set check. The two source states
    # `NOT_ATTESTED` and `INVALID` are the legal pres for the
    # attestation shape per the §1.2 Driver state-machine's
    # NOT_ATTESTED-to-VALID and INVALID-to-VALID transitions; a
    # `VALID` source is the generic state error.
    if pre_status not in ("NOT_ATTESTED", "INVALID"):
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot attest an endorsement for a driver in {pre_status!r}; "
            f"the legal source states are 'NOT_ATTESTED' or 'INVALID'.",
            details={
                "current_state": pre_status,
                "legal_from_states": ["NOT_ATTESTED", "INVALID"],
                "endpoint": "POST /v1/drivers/<driver_id>/refresh-endorsement (attestation shape)",
            },
        )

    # The points-below-threshold attestation interlock from §3.2: the
    # regulator may not attest a driver whose current rolling total is
    # at-or-above the threshold; the natural-decay or appeal-uphold
    # path must first bring the total below.
    if int(row.get("current_rolling_points", 0)) >= constants.threshold_driver_suspension_points:
        raise APIError(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot attest the endorsement: the driver's current "
            f"rolling-points total "
            f"{row.get('current_rolling_points')!r} is at or above the "
            f"suspension threshold "
            f"{constants.threshold_driver_suspension_points!r}.",
            details={
                "current_state": pre_status,
                "current_rolling_points": row.get("current_rolling_points"),
                "threshold": constants.threshold_driver_suspension_points,
                "endpoint": "POST /v1/drivers/<driver_id>/refresh-endorsement (attestation shape)",
            },
        )

    # All checks pass. Apply the attestation. The status flips to
    # `VALID`, the `endorsement_valid_until` and `endorsement_classes`
    # are written to the body's values, the `version` is bumped, the
    # `updated_at` is refreshed.
    row["hazmat_endorsement_status"] = "VALID"
    row["endorsement_valid_until"] = iso_format(valid_until_dt)
    row["endorsement_classes"] = list(endorsement_classes)
    bump_version(row)

    return make_object_response(_serialize_driver(row), http_status=200)
