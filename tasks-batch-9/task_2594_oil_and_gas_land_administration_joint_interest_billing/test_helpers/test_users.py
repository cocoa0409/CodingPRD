"""Pre-built request headers for every role named in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Stable user identifiers. The joint interest accountant identifier is what a
# draft statement records as prepared_by_user_id; the audit reviewer identifier
# is what a resolution records as resolved_by_user_id, and the two must differ
# so that the reviewer is never the preparer of the bill under dispute.
LAND_ADMIN_USER_ID = "u-land-1"
JIB_ACCOUNTANT_USER_ID = "u-jib-1"
AUDIT_REVIEWER_USER_ID = "u-audit-1"
SECOND_AUDIT_REVIEWER_USER_ID = "u-audit-2"
COMPLIANCE_OFFICER_USER_ID = "u-compliance-1"
PARTNER_REP_FALLBACK_USER_ID = "u-partner-1"

# Shared constants. Safe for the four roles whose identity is opaque, and for
# tests that never exercise ownership of a subject resource.
TEST_USERS = {
    "land_administrator_headers": build_user_headers(
        LAND_ADMIN_USER_ID, "LandAdministrator"
    ),
    "joint_interest_accountant_headers": build_user_headers(
        JIB_ACCOUNTANT_USER_ID, "JointInterestAccountant"
    ),
    "audit_reviewer_headers": build_user_headers(
        AUDIT_REVIEWER_USER_ID, "AuditReviewer"
    ),
    "second_audit_reviewer_headers": build_user_headers(
        SECOND_AUDIT_REVIEWER_USER_ID, "AuditReviewer"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    # A partner representative acts as the interest owner named by X-User-ID, so
    # this shared constant is only a fallback for calls that are not gated on
    # ownership of the subject resource.
    "partner_representative_headers": build_user_headers(
        PARTNER_REP_FALLBACK_USER_ID, "PartnerRepresentative"
    ),
}


def make_land_administrator_headers(user_id: str = LAND_ADMIN_USER_ID) -> dict:
    """Headers for a LandAdministrator acting as `user_id`."""
    return build_user_headers(user_id, "LandAdministrator")


def make_joint_interest_accountant_headers(
    user_id: str = JIB_ACCOUNTANT_USER_ID,
) -> dict:
    """Headers for a JointInterestAccountant acting as `user_id`.

    Pass a specific identifier when a test needs the statement's
    prepared_by_user_id to be a chosen value.
    """
    return build_user_headers(user_id, "JointInterestAccountant")


def make_audit_reviewer_headers(user_id: str = AUDIT_REVIEWER_USER_ID) -> dict:
    """Headers for an AuditReviewer acting as `user_id`.

    Pass the preparer's identifier to exercise the segregation-of-duties bar.
    """
    return build_user_headers(user_id, "AuditReviewer")


def make_compliance_officer_headers(
    user_id: str = COMPLIANCE_OFFICER_USER_ID,
) -> dict:
    """Headers for a ComplianceOfficer acting as `user_id`."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_partner_representative_headers(owner_id: str) -> dict:
    """Headers for a PartnerRepresentative acting as the interest owner
    identified by `owner_id`.

    A partner representative's X-User-ID is the interest owner id it acts as, so
    every ownership-gated call must pass the real InterestOwner id here.
    """
    return build_user_headers(owner_id, "PartnerRepresentative")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary user identifier and role string."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = LAND_ADMIN_USER_ID) -> dict:
    """Headers carrying a user identifier but no role header at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "LandAdministrator") -> dict:
    """Headers carrying a role but no user identifier at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
