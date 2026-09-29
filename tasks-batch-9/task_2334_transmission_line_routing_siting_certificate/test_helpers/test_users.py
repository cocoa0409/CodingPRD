"""Pre-built request headers for each acting identity.

Six of the seven roles carry **opaque** identities (PRD §2.1): the ``X-User-ID``
is an operator identifier that is never compared against a row's ``id``, so it
can be a fixed string.  ``Landowner`` is the one **entity-backed** identity —
its ``X-User-ID`` must be the ``id`` of the acting ``Landowner`` row — so
landowner headers must always be built per-row with
:func:`make_landowner_headers`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- Opaque operator identifiers ---------------------------------------------
DEV_NORA = "dev-nora"          # authors studies, draws and publishes routes
DEV_MILO = "dev-milo"          # certifies sufficiency (never the author)
DEV_FILA = "dev-fila"          # files the application (never the study author)
ANALYST_RAY = "analyst-ray"
STAFF_LIN = "staff-lin"
STAFF_PAZ = "staff-paz"
EXAMINER_QUINN = "examiner-quinn"
FED_OWEN = "fed-owen"
MONITOR_ABE = "monitor-abe"

TEST_USERS = {
    "developer": build_user_headers(DEV_NORA, UserRole.DEVELOPER),
    "developer_certifier": build_user_headers(DEV_MILO, UserRole.DEVELOPER),
    "developer_filer": build_user_headers(DEV_FILA, UserRole.DEVELOPER),
    "route_analyst": build_user_headers(ANALYST_RAY, UserRole.ROUTE_ANALYST),
    "commission_staff": build_user_headers(STAFF_LIN, UserRole.COMMISSION_STAFF),
    "commission_staff_alt": build_user_headers(STAFF_PAZ, UserRole.COMMISSION_STAFF),
    "hearing_examiner": build_user_headers(EXAMINER_QUINN, UserRole.HEARING_EXAMINER),
    "federal_permit_officer": build_user_headers(FED_OWEN, UserRole.FEDERAL_PERMIT_OFFICER),
    "compliance_monitor": build_user_headers(MONITOR_ABE, UserRole.COMPLIANCE_MONITOR),
}

DEVELOPER_HEADERS = TEST_USERS["developer"]
DEVELOPER_CERTIFIER_HEADERS = TEST_USERS["developer_certifier"]
DEVELOPER_FILER_HEADERS = TEST_USERS["developer_filer"]
ROUTE_ANALYST_HEADERS = TEST_USERS["route_analyst"]
COMMISSION_STAFF_HEADERS = TEST_USERS["commission_staff"]
COMMISSION_STAFF_ALT_HEADERS = TEST_USERS["commission_staff_alt"]
HEARING_EXAMINER_HEADERS = TEST_USERS["hearing_examiner"]
FEDERAL_PERMIT_OFFICER_HEADERS = TEST_USERS["federal_permit_officer"]
COMPLIANCE_MONITOR_HEADERS = TEST_USERS["compliance_monitor"]


def make_landowner_headers(landowner_id: str) -> dict:
    """Headers for the landowner whose row ``id`` is ``landowner_id``.

    ``Landowner`` is entity-backed, so every ownership-gated write — the
    easement offer response and public comment intake — must be issued with the
    identifier of the landowner row that actually owns the resource.
    """
    return build_user_headers(landowner_id, UserRole.LANDOWNER)


def make_developer_headers(user_id: str) -> dict:
    """Headers for an arbitrary ``Developer`` operator identifier."""
    return build_user_headers(user_id, UserRole.DEVELOPER)


def make_commission_staff_headers(user_id: str) -> dict:
    """Headers for an arbitrary ``CommissionStaff`` operator identifier."""
    return build_user_headers(user_id, UserRole.COMMISSION_STAFF)


def make_hearing_examiner_headers(user_id: str) -> dict:
    """Headers for an arbitrary ``HearingExaminer`` operator identifier."""
    return build_user_headers(user_id, UserRole.HEARING_EXAMINER)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for any (user_id, role) pair, including unknown role names."""
    return build_user_headers(user_id, role)
