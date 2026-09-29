"""Pre-built role headers for every role in the PRD.

Three roles carry an opaque operator identifier that the server records but
never compares to an entity id, so a shared constant is the canonical form for
them. Two roles are identity bound: a ``TalentRepresentative``'s user id is the
acting talent's id and an ``EstateRepresentative``'s user id is the acting
estate authority's id, so any ownership-gated call must be made with the
per-instance builder below rather than with a shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    COMPLIANCE_OFFICER_ONE,
    COMPLIANCE_OFFICER_TWO,
    LICENSEE_ONE,
    LICENSEE_TWO,
    RIGHTS_ADMIN_ONE,
    RIGHTS_ADMIN_TWO,
)

TEST_USERS = {
    # Opaque operator identifiers — canonical form for these three roles.
    "rights_administrator_headers": build_user_headers(
        RIGHTS_ADMIN_ONE, "RightsAdministrator"
    ),
    "second_rights_administrator_headers": build_user_headers(
        RIGHTS_ADMIN_TWO, "RightsAdministrator"
    ),
    "licensee_producer_headers": build_user_headers(LICENSEE_ONE, "LicenseeProducer"),
    "other_licensee_producer_headers": build_user_headers(
        LICENSEE_TWO, "LicenseeProducer"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_ONE, "ComplianceOfficer"
    ),
    "second_compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_TWO, "ComplianceOfficer"
    ),
    # Identity-bound roles — fallback for tests that never reach an ownership
    # check (missing header shape, unknown resource, role denial).
    "talent_representative_headers": build_user_headers(
        "test-talent-representative", "TalentRepresentative"
    ),
    "estate_representative_headers": build_user_headers(
        "test-estate-representative", "EstateRepresentative"
    ),
}


def make_talent_representative_headers(talent_id: str) -> dict:
    """Headers for the representative of one talent. Pass the talent's own id."""
    return build_user_headers(talent_id, "TalentRepresentative")


def make_estate_representative_headers(estate_authority_id: str) -> dict:
    """Headers for one estate. Pass the verified estate authority's own id."""
    return build_user_headers(estate_authority_id, "EstateRepresentative")


def make_rights_administrator_headers(user_id: str) -> dict:
    """Headers for a named clearance-office operator."""
    return build_user_headers(user_id, "RightsAdministrator")


def make_licensee_producer_headers(user_id: str) -> dict:
    """Headers for a named licensee operator."""
    return build_user_headers(user_id, "LicenseeProducer")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Headers for a named compliance operator."""
    return build_user_headers(user_id, "ComplianceOfficer")
