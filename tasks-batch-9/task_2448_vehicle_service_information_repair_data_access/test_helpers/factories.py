"""Payload factories.

Each factory emits only the input fields the endpoint accepts — never a
server-minted identifier, never a computed field, never a status. Keyword
overrides let a caller vary one field without restating the rest.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_ATTESTATION_EXPIRY,
    DEFAULT_CREDENTIAL_EXPIRY,
    DEFAULT_ENTITLEMENT_WINDOW_END,
    DEFAULT_ENTITLEMENT_WINDOW_START,
    DEFAULT_LICENSE_EFFECTIVE_END,
    DEFAULT_LICENSE_EFFECTIVE_START,
    DEFAULT_SESSION_WINDOW_END,
    DEFAULT_SESSION_WINDOW_START,
    LICENSE_MONTHLY_FEE_CENTS,
    LICENSE_PER_VEHICLE_FEE_CENTS,
    LICENSE_SEAT_CAP,
    PARITY_BOUNDARY_DEALER_CENTS,
    PARITY_BOUNDARY_DEALER_SYSTEMS,
    PARITY_BOUNDARY_INDEPENDENT_CENTS,
    PARITY_BOUNDARY_INDEPENDENT_SYSTEMS,
    SYSTEM_AREA_SPECS,
    VIN_PRIMARY,
)
from .types import (
    EntitlementModel,
    JobType,
    LicenseModel,
    PublicationType,
    Region,
    ShopTier,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def system_area_payload(code: str = "POWERTRAIN", **overrides) -> Dict[str, Any]:
    spec = SYSTEM_AREA_SPECS.get(
        code,
        {
            "code": code,
            "name": code.replace("_", " ").title(),
            "requires_calibration_doc": False,
            "requires_security_credential": False,
        },
    )
    return _merge(dict(spec), overrides)


def manufacturer_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "name": "Acme Motors",
            "oem_code": "ACME",
            "region": Region.NA,
            "independent_list_monthly_cents": PARITY_BOUNDARY_INDEPENDENT_CENTS,
            "independent_covered_system_count": PARITY_BOUNDARY_INDEPENDENT_SYSTEMS,
            "oem_dealer_monthly_cents": PARITY_BOUNDARY_DEALER_CENTS,
            "oem_dealer_covered_system_count": PARITY_BOUNDARY_DEALER_SYSTEMS,
        },
        overrides,
    )


def vehicle_model_payload(manufacturer_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "manufacturer_id": manufacturer_id,
            "model_code": "AX7",
            "model_year": 2025,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Licensing
# ---------------------------------------------------------------------------


def license_payload(
    manufacturer_id: str, covered_system_area_ids: List[str], **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "manufacturer_id": manufacturer_id,
            "license_model": LicenseModel.SUBSCRIPTION,
            "monthly_fee_cents": LICENSE_MONTHLY_FEE_CENTS,
            "per_vehicle_fee_cents": LICENSE_PER_VEHICLE_FEE_CENTS,
            "seat_cap": LICENSE_SEAT_CAP,
            "covered_system_area_ids": list(covered_system_area_ids),
            "effective_start": DEFAULT_LICENSE_EFFECTIVE_START,
            "effective_end": DEFAULT_LICENSE_EFFECTIVE_END,
        },
        overrides,
    )


def reason_payload(reason: str) -> Dict[str, Any]:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Shops and credit
# ---------------------------------------------------------------------------


def shop_payload(**overrides) -> Dict[str, Any]:
    return _merge({"name": "Bay Auto", "tier": ShopTier.PRO}, overrides)


def credit_funding_payload(amount_cents: int, **overrides) -> Dict[str, Any]:
    return _merge({"amount_cents": amount_cents, "funding_ref": "FUND-1"}, overrides)


# ---------------------------------------------------------------------------
# Technicians and seats
# ---------------------------------------------------------------------------


def technician_payload(shop_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "shop_id": shop_id,
            "full_name": "Tina Tech",
            "credential_expires_at": DEFAULT_CREDENTIAL_EXPIRY,
        },
        overrides,
    )


def verify_technician_payload(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "identity_document_ref": "DL-77123",
            "credential_expires_at": DEFAULT_CREDENTIAL_EXPIRY,
        },
        overrides,
    )


def seat_assignment_payload(
    entitlement_id: str, technician_id: str, expected_entitlement_version: int, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "entitlement_id": entitlement_id,
            "technician_id": technician_id,
            "expected_entitlement_version": expected_entitlement_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Entitlements
# ---------------------------------------------------------------------------


def entitlement_payload(shop_id: str, license_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "shop_id": shop_id,
            "license_id": license_id,
            "entitlement_model": EntitlementModel.SUBSCRIPTION,
            "seats_total": 3,
            "window_start": DEFAULT_ENTITLEMENT_WINDOW_START,
            "window_end": DEFAULT_ENTITLEMENT_WINDOW_END,
        },
        overrides,
    )


def per_vehicle_entitlement_payload(
    shop_id: str, license_id: str, vin_quota: int = 40, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "shop_id": shop_id,
            "license_id": license_id,
            "entitlement_model": EntitlementModel.PER_VEHICLE,
            "seats_total": 3,
            "vin_quota": vin_quota,
            "window_start": DEFAULT_ENTITLEMENT_WINDOW_START,
            "window_end": DEFAULT_ENTITLEMENT_WINDOW_END,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Diagnostic tools
# ---------------------------------------------------------------------------


def diagnostic_tool_payload(shop_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "shop_id": shop_id,
            "serial_no": "SN-0001",
            "oem_attestation_expires_at": DEFAULT_ATTESTATION_EXPIRY,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Publications
# ---------------------------------------------------------------------------


def publication_payload(
    vehicle_model_id: str, system_area_id: str, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "vehicle_model_id": vehicle_model_id,
            "system_area_id": system_area_id,
            "publication_type": PublicationType.REPAIR_PROCEDURE,
        },
        overrides,
    )


def publication_version_payload(
    expected_publication_version: int,
    source_tsb_ref: str = "TSB-0001",
    calibration_procedure_ref: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source_tsb_ref": source_tsb_ref,
        "expected_publication_version": expected_publication_version,
    }
    if calibration_procedure_ref is not None:
        payload["calibration_procedure_ref"] = calibration_procedure_ref
    return _merge(payload, overrides)


def validate_version_payload(**overrides) -> Dict[str, Any]:
    return _merge({"reviewer_notes": "checked against OEM procedure"}, overrides)


# ---------------------------------------------------------------------------
# Gateway sessions and jobs
# ---------------------------------------------------------------------------


def gateway_session_payload(
    seat_assignment_id: str, diagnostic_tool_id: str, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "seat_assignment_id": seat_assignment_id,
            "diagnostic_tool_id": diagnostic_tool_id,
            "vin": VIN_PRIMARY,
            "window_start": DEFAULT_SESSION_WINDOW_START,
            "window_end": DEFAULT_SESSION_WINDOW_END,
        },
        overrides,
    )


def programming_job_payload(
    session_id: str, pinned_publication_version_id: str, **overrides
) -> Dict[str, Any]:
    return _merge(
        {
            "session_id": session_id,
            "job_type": JobType.MODULE_FLASH,
            "pinned_publication_version_id": pinned_publication_version_id,
        },
        overrides,
    )


def repin_payload(pinned_publication_version_id: str) -> Dict[str, Any]:
    return {"pinned_publication_version_id": pinned_publication_version_id}
