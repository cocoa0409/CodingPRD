"""The Vehicle endpoints — two in the scaffold's §1.5 enumeration:

  POST /v1/companies/<company_id>/vehicles — operator registers a
                                                vehicle. The parent-
                                                must-be-APPROVED rule
                                                (`ERR_COMPANY_NOT_QUALIFIED`
                                                409). The system-wide
                                                unique `plate_number`
                                                check
                                                (`ERR_DUPLICATE_IDENTIFIER`
                                                409 at priority 520).

  GET  /v1/vehicles/<vehicle_id>            — read-one. The cross-tenant
                                                ownership-by-the-vehicle's
                                                `company_id` rule. The
                                                response includes the
                                                three derived "latest
                                                inspection" pointer
                                                fields the inspection-
                                                append handler atomically
                                                refreshes.

The vehicle entity is read-only post-creation — there is no PATCH or
DELETE endpoint in the scaffold's surface. The dynamic state of the
vehicle is the VehicleInspection append-only log handled in the
adjacent `inspections.py` blueprint, with the parent Vehicle row's
three derived `latest_inspection_*` fields atomically refreshed on
each append.

The PRD §3.3 paragraph names the canonical fields the body carries:
the 4-to-16-character `plate_number` with the system-wide uniqueness
scope on the natural key, the `vehicle_type` enum drawn from the §2.8
five-value vehicle-class taxonomy, the strictly-positive integer
`max_payload_kg` of the manufacturer-rated cargo capacity, and the
non-empty no-duplicates `hazard_classes_compatible` array of UN
hazard-class codes that the vehicle's construction certifies it can
carry.

The system-set fields on the fresh row are the three derived
"latest-inspection" pointers null (until the first inspection-append
fires the side-effect), plus the standard four common-fields quartet
with `version = 1`.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint

from ..auth import (
    assert_cross_tenant_company_id_match,
    assert_cross_tenant_ownership,
    lookup_path_resource,
)
from ..config import VEHICLE_PLATE_NUMBER_LEN_RANGE, VEHICLE_TYPES
from ..envelope import get_json_body, make_object_response
from ..errors import APIError
from ..store import (
    find_by_unique_field,
    insert,
    stamp_create,
)
from ..validation import (
    require_array,
    require_int,
    require_str,
    validate_hazard_class_array,
    validate_vehicle_type,
)


vehicles_bp = Blueprint("vehicles", __name__)


def _serialize_vehicle(row: dict[str, Any]) -> dict[str, Any]:
    """The wire-shape of a Vehicle row, pass-through of the on-disk
    fields. The three derived `latest_inspection_*` pointer fields are
    included in the response so the client sees the vehicle's current
    inspection-coverage standing without a separate inspection-list
    fetch.
    """
    return dict(row)


@vehicles_bp.route("/companies/<company_id>/vehicles", methods=["POST"])
def post_create_vehicle(company_id: str) -> Any:
    """Operator's children-create-under-company. The parent-must-be-
    APPROVED rule fires `ERR_COMPANY_NOT_QUALIFIED` 409. The system-
    wide unique `plate_number` rule fires `ERR_DUPLICATE_IDENTIFIER`
    409. The body's field-shape rules are the standard length-and-
    range checks from `validation`.
    """
    parent = lookup_path_resource(
        "TransportCompany", company_id, "ERR_COMPANY_NOT_FOUND"
    )
    assert_cross_tenant_company_id_match(company_id)
    if parent.get("qualification_status") != "APPROVED":
        raise APIError(
            "ERR_COMPANY_NOT_QUALIFIED",
            f"Cannot register a vehicle under a TransportCompany in "
            f"{parent.get('qualification_status')!r}; the company must be "
            f"'APPROVED'.",
            details={
                "company_id": company_id,
                "current_status": parent.get("qualification_status"),
            },
        )

    body = get_json_body()

    plate_number = require_str(
        body, "plate_number", length_range=VEHICLE_PLATE_NUMBER_LEN_RANGE
    )
    assert plate_number is not None
    vehicle_type = require_str(body, "vehicle_type", length_range=(1, 64))
    assert vehicle_type is not None
    validate_vehicle_type(vehicle_type)
    max_payload_kg = require_int(body, "max_payload_kg", positive=True)
    hazard_classes_compatible_raw = require_array(
        body, "hazard_classes_compatible", element_type=str
    )
    assert hazard_classes_compatible_raw is not None
    hazard_classes_compatible = validate_hazard_class_array(
        hazard_classes_compatible_raw, field="hazard_classes_compatible"
    )

    # System-wide uniqueness on the plate.
    existing = find_by_unique_field("Vehicle", "plate_number", plate_number)
    if existing is not None:
        raise APIError(
            "ERR_DUPLICATE_IDENTIFIER",
            f"Vehicle plate_number {plate_number!r} is already in use.",
            details={
                "natural_key": "plate_number",
                "scope": "system_wide",
                "value": plate_number,
                "existing_vehicle_id": existing.get("id"),
                "existing_owning_company": existing.get("company_id"),
            },
        )

    row: dict[str, Any] = {
        "company_id": company_id,
        "plate_number": plate_number,
        "vehicle_type": vehicle_type,
        "max_payload_kg": max_payload_kg,
        "hazard_classes_compatible": list(hazard_classes_compatible),
        # The three derived "latest inspection" pointer fields, null
        # until the first inspection-append's side-effect refreshes
        # them.
        "latest_inspection_id": None,
        "latest_inspection_outcome": None,
        "latest_inspection_valid_until": None,
    }
    stamp_create(row)
    insert("Vehicle", row)

    return make_object_response(_serialize_vehicle(row), http_status=201)


@vehicles_bp.route("/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id: str) -> Any:
    """The vehicle-row read. The standard cross-tenant rule on the
    vehicle's `company_id` field. The existence tier fires before
    cross-tenant per the §2.6 priority-300-before-priority-530
    convention.
    """
    row = lookup_path_resource("Vehicle", vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    assert_cross_tenant_ownership("Vehicle", row)
    return make_object_response(_serialize_vehicle(row), http_status=200)
