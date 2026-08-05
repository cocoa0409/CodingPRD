"""Pre-built role headers for every role in the PRD (§2.1).

Seven of the eight roles carry an opaque identity: the accompanying
``X-User-ID`` is an operator identifier the server records for provenance but
never compares against any entity's ``id``.  The eighth role, ``Patient``, is
entity-backed — its ``X-User-ID`` must be the ``id`` of the acting ``Patient``
record, so a per-instance builder is mandatory for it and any test that reads
through the patient's own identity MUST use ``make_patient_headers()``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the seven opaque roles.  Because these identities are
# never compared against an entity id, the same constant is safe everywhere the
# specific operator identity does not itself carry meaning.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_admin_headers": build_user_headers("admin-1", "ProgramAdmin"),
    "admitting_physician_headers": build_user_headers("phys-1", "AdmittingPhysician"),
    "field_nurse_headers": build_user_headers("rn-1", "FieldNurse"),
    "community_paramedic_headers": build_user_headers("medic-1", "CommunityParamedic"),
    "pharmacy_authorizer_headers": build_user_headers("pharm-9", "PharmacyAuthorizer"),
    "logistics_coordinator_headers": build_user_headers(
        "log-1", "LogisticsCoordinator"
    ),
    "billing_analyst_headers": build_user_headers("bill-1", "BillingAnalyst"),
}


# ─── Per-instance builders ─────────────────────────────────────────────────

def make_program_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "ProgramAdmin")


def make_admitting_physician_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "AdmittingPhysician")


def make_field_nurse_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "FieldNurse")


def make_community_paramedic_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "CommunityParamedic")


def make_pharmacy_authorizer_headers(user_id: str) -> Dict[str, str]:
    """The segregation-of-duties counterpart: pass the authorizing operator's
    own identifier, which must differ from a controlled order's
    ``requested_by_user_id``."""
    return build_user_headers(user_id, "PharmacyAuthorizer")


def make_logistics_coordinator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_billing_analyst_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "BillingAnalyst")


def make_patient_headers(patient_id: str) -> Dict[str, str]:
    """For the Patient role, whose ``X-User-ID`` is the acting Patient's ``id``.

    Always pass the real ``Patient.id``; a placeholder string would never match
    any persisted patient and every ownership check would reject the call.
    """
    return build_user_headers(patient_id, "Patient")


# Convenience aliases used throughout the suite.
PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]
ADMITTING_PHYSICIAN = TEST_USERS["admitting_physician_headers"]
FIELD_NURSE = TEST_USERS["field_nurse_headers"]
COMMUNITY_PARAMEDIC = TEST_USERS["community_paramedic_headers"]
PHARMACY_AUTHORIZER = TEST_USERS["pharmacy_authorizer_headers"]
LOGISTICS_COORDINATOR = TEST_USERS["logistics_coordinator_headers"]
BILLING_ANALYST = TEST_USERS["billing_analyst_headers"]

NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
