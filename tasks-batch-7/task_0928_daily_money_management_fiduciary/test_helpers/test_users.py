"""Pre-built role headers for every role in the PRD.

Five of the seven roles carry an opaque operator identifier that the server
never compares against any row's ``id``; the shared constants below are the
canonical form for those. Two roles - ``Client`` and ``FamilyRecipient`` -
carry an identifier that MUST equal the acting row's ``id``, so those get
per-instance builders and no usable shared constant.

Every distinct principal in this file has a distinct ``X-User-ID``. That
matters most for the segregation-of-duties rung, where the preparer and the
approver must be different natural persons.
"""

from prd_bench_local_runner.testing import build_user_headers

# --- opaque operator identifiers ------------------------------------------
ADMIN_USER_ID = "u-admin"
MANAGER_USER_ID = "u-mgr"
MANAGER_ALT_USER_ID = "u-mgr2"
SPECIALIST_USER_ID = "u-spec"
SPECIALIST_ALT_USER_ID = "u-spec2"
COMPLIANCE_USER_ID = "u-comp"
COMPLIANCE_ALT_USER_ID = "u-comp2"
CARE_1_USER_ID = "u-care1"
CARE_2_USER_ID = "u-care2"
CARE_3_USER_ID = "u-care3"
CARE_4_USER_ID = "u-care4"

TEST_USERS = {
    # PlatformAdmin: opaque.
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    # FiduciaryManager: opaque. The default second approver.
    "fiduciary_manager_headers": build_user_headers(MANAGER_USER_ID, "FiduciaryManager"),
    "fiduciary_manager_alt_headers": build_user_headers(
        MANAGER_ALT_USER_ID, "FiduciaryManager"
    ),
    # BillPaySpecialist: opaque. The default preparer.
    "bill_pay_specialist_headers": build_user_headers(
        SPECIALIST_USER_ID, "BillPaySpecialist"
    ),
    "bill_pay_specialist_alt_headers": build_user_headers(
        SPECIALIST_ALT_USER_ID, "BillPaySpecialist"
    ),
    # ComplianceOfficer: opaque. The default adjudicator / alternate approver.
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_USER_ID, "ComplianceOfficer"
    ),
    "compliance_officer_alt_headers": build_user_headers(
        COMPLIANCE_ALT_USER_ID, "ComplianceOfficer"
    ),
    # CareCoordinator: opaque care-team member identifiers.
    "care_coordinator_headers": build_user_headers(CARE_1_USER_ID, "CareCoordinator"),
    "care_coordinator_2_headers": build_user_headers(CARE_2_USER_ID, "CareCoordinator"),
    "care_coordinator_3_headers": build_user_headers(CARE_3_USER_ID, "CareCoordinator"),
    "care_coordinator_4_headers": build_user_headers(CARE_4_USER_ID, "CareCoordinator"),
}


# --- per-instance builders -------------------------------------------------


def make_platform_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    """PlatformAdmin headers under an explicit operator identifier."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_fiduciary_manager_headers(user_id: str = MANAGER_USER_ID) -> dict:
    """FiduciaryManager headers under an explicit operator identifier.

    Used by the segregation-of-duties tests, where the same natural person who
    prepared a payment tries to approve it while wearing the manager's hat.
    """
    return build_user_headers(user_id, "FiduciaryManager")


def make_bill_pay_specialist_headers(user_id: str = SPECIALIST_USER_ID) -> dict:
    """BillPaySpecialist headers under an explicit operator identifier."""
    return build_user_headers(user_id, "BillPaySpecialist")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_USER_ID) -> dict:
    """ComplianceOfficer headers under an explicit operator identifier."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_care_coordinator_headers(user_id: str) -> dict:
    """CareCoordinator headers for one care-team member identifier.

    The identifier is compared against a coordination request's
    ``assigned_member_user_id`` on an acknowledgement, so pass the same string
    the request was assigned to.
    """
    return build_user_headers(user_id, "CareCoordinator")


def make_client_headers(client_id: str) -> dict:
    """Client headers. ``X-User-ID`` MUST be the acting Client row's ``id``."""
    return build_user_headers(client_id, "Client")


def make_family_recipient_headers(recipient_id: str) -> dict:
    """FamilyRecipient headers. ``X-User-ID`` MUST be the acting
    FamilyRecipient row's ``id``."""
    return build_user_headers(recipient_id, "FamilyRecipient")


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
