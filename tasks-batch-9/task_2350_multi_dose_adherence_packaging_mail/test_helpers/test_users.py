"""Caller identities: one header set per role, plus builders for explicit identities.

Every request carries ``X-User-ID`` and ``X-User-Role``. Several controls in this
domain are keyed on identity rather than role — the technician who packed a roll
may not image or verify it — so the builders below accept an explicit user id and
the bench identities ``tech-01``, ``tech-02``, ``tech-03`` and ``rph-01`` are
provided as named constants.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

__all__ = [
    "TEST_USERS",
    "PLATFORM_ADMIN_ID",
    "PHARMACY_OPS_ID",
    "PHARMACIST_ID",
    "PHARMACIST_ID_2",
    "TECHNICIAN_ID",
    "TECHNICIAN_ID_2",
    "TECHNICIAN_ID_3",
    "PRESCRIBER_ID",
    "PRESCRIBER_ID_2",
    "admin_headers",
    "ops_headers",
    "pharmacist_headers",
    "technician_headers",
    "prescriber_headers",
    "patient_headers",
    "headers_for_role",
    "unauthenticated_headers",
]

PLATFORM_ADMIN_ID = "admin-01"
PHARMACY_OPS_ID = "ops-01"
PHARMACIST_ID = "rph-01"
PHARMACIST_ID_2 = "rph-02"
TECHNICIAN_ID = "tech-01"
TECHNICIAN_ID_2 = "tech-02"
TECHNICIAN_ID_3 = "tech-03"
PRESCRIBER_ID = "prescriber-01"
PRESCRIBER_ID_2 = "prescriber-02"


def admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> Dict[str, str]:
    """Headers for a ``PlatformAdmin`` caller."""
    return build_user_headers(user_id, "PlatformAdmin")


def ops_headers(user_id: str = PHARMACY_OPS_ID) -> Dict[str, str]:
    """Headers for a ``PharmacyOperations`` caller."""
    return build_user_headers(user_id, "PharmacyOperations")


def pharmacist_headers(user_id: str = PHARMACIST_ID) -> Dict[str, str]:
    """Headers for a ``VerifyingPharmacist`` caller."""
    return build_user_headers(user_id, "VerifyingPharmacist")


def technician_headers(user_id: str = TECHNICIAN_ID) -> Dict[str, str]:
    """Headers for a ``PackagingTechnician`` caller."""
    return build_user_headers(user_id, "PackagingTechnician")


def prescriber_headers(user_id: str = PRESCRIBER_ID) -> Dict[str, str]:
    """Headers for a ``Prescriber`` caller."""
    return build_user_headers(user_id, "Prescriber")


def patient_headers(patient_id: str) -> Dict[str, str]:
    """Headers for a ``Patient`` caller.

    The patient's own identifier is the ``X-User-ID``, because patient ownership is
    resolved by comparing that header against the row's patient.
    """
    return build_user_headers(patient_id, "Patient")


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role and identity."""
    return build_user_headers(user_id, role)


def unauthenticated_headers() -> Dict[str, str]:
    """Headers with neither identity nor role."""
    return {"Content-Type": "application/json"}


TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin_headers": admin_headers(),
    "ops_headers": ops_headers(),
    "pharmacist_headers": pharmacist_headers(),
    "pharmacist_2_headers": pharmacist_headers(PHARMACIST_ID_2),
    "technician_headers": technician_headers(),
    "technician_2_headers": technician_headers(TECHNICIAN_ID_2),
    "technician_3_headers": technician_headers(TECHNICIAN_ID_3),
    "prescriber_headers": prescriber_headers(),
    "prescriber_2_headers": prescriber_headers(PRESCRIBER_ID_2),
}
