"""Identity headers for the four roles.

Three of the four roles carry an opaque operator identifier in ``X-User-ID``
that the server records but never resolves against an entity row, so a fixed
constant is fine for them. The fourth, ``CarrierAdmin``, is different: its
``X-User-ID`` is the ``id`` of the acting ``Carrier``, and ownership checks
compare a resource's carrier reference to it. There is therefore no shared
``CarrierAdmin`` identity — build one per carrier with
``make_carrier_admin_headers``.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole


# Opaque operator identifiers. Distinct spellings so that a segregation-of-duties
# rule comparing two acting users has something to distinguish.
MILEAGE_ANALYST_1 = "analyst-1"
MILEAGE_ANALYST_2 = "analyst-2"
TAX_PREPARER_1 = "preparer-1"
TAX_PREPARER_2 = "preparer-2"
COMPLIANCE_OFFICER_1 = "officer-1"
COMPLIANCE_OFFICER_2 = "officer-2"


def make_carrier_admin_headers(carrier_id: str) -> Dict[str, str]:
    """Headers for a ``CarrierAdmin`` acting as the carrier with this ``id``."""
    return build_user_headers(carrier_id, UserRole.CARRIER_ADMIN.value)


def make_mileage_analyst_headers(user_id: str = MILEAGE_ANALYST_1) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.MILEAGE_ANALYST.value)


def make_tax_preparer_headers(user_id: str = TAX_PREPARER_1) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.TAX_PREPARER.value)


def make_compliance_officer_headers(
    user_id: str = COMPLIANCE_OFFICER_1,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for tests that need an arbitrary user/role pairing."""
    return build_user_headers(user_id, role)


# Ready-made headers for the roles whose identifier is opaque.
ANALYST_1_HEADERS = make_mileage_analyst_headers(MILEAGE_ANALYST_1)
ANALYST_2_HEADERS = make_mileage_analyst_headers(MILEAGE_ANALYST_2)
PREPARER_1_HEADERS = make_tax_preparer_headers(TAX_PREPARER_1)
PREPARER_2_HEADERS = make_tax_preparer_headers(TAX_PREPARER_2)
OFFICER_1_HEADERS = make_compliance_officer_headers(COMPLIANCE_OFFICER_1)
OFFICER_2_HEADERS = make_compliance_officer_headers(COMPLIANCE_OFFICER_2)

# Every role may call every read endpoint; this list drives the shared-read tests.
ALL_ROLE_READ_HEADERS = [
    ("MileageAnalyst", ANALYST_1_HEADERS),
    ("TaxPreparer", PREPARER_1_HEADERS),
    ("ComplianceOfficer", OFFICER_1_HEADERS),
]
