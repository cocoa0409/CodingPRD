"""Auth identities.

Five of the six roles carry an opaque ``X-User-ID``: any stable string
identifies the operator, and the value only matters where a rule compares the
acting user id against the user id that performed a previous step.  The sixth
role, ``Subject``, is entity-backed: its ``X-User-ID`` must be the id of the
DataSubject row that owns the target resource, so subject headers can only be
built once the row exists.

Because duty-separation rules compare the approving user id against the
submitting/drafting/creating user id, every operator role exposes at least two
distinct ids: a primary actor and an independent second actor.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_APPROVER,
    ROLE_HR_ADMINISTRATOR,
    ROLE_PRIVACY_OFFICER,
    ROLE_SUBJECT,
    ROLE_SYSTEM_OPERATOR,
    ROLE_VENDOR_MANAGER,
)

# --- opaque user ids -------------------------------------------------
SYSTEM_OPERATOR_USER_ID = "so-1"

PRIVACY_OFFICER_USER_ID = "po-1"
PRIVACY_OFFICER_ALT_USER_ID = "po-2"

COMPLIANCE_APPROVER_USER_ID = "ca-1"
COMPLIANCE_APPROVER_ALT_USER_ID = "ca-9"

VENDOR_MANAGER_USER_ID = "vm-1"
VENDOR_MANAGER_ALT_USER_ID = "vm-2"

HR_ADMIN_USER_ID = "hr-1"
HR_ADMIN_ALT_USER_ID = "hr-2"

# A single operator identity deliberately reused across two roles, for the
# duty-separation rules that compare the acting user id, not the acting role.
DUAL_HAT_USER_ID = "u-dual"

# --- ready-made header dicts ----------------------------------------
SYSTEM_OPERATOR = build_user_headers(SYSTEM_OPERATOR_USER_ID, ROLE_SYSTEM_OPERATOR)

PRIVACY_OFFICER = build_user_headers(PRIVACY_OFFICER_USER_ID, ROLE_PRIVACY_OFFICER)
PRIVACY_OFFICER_ALT = build_user_headers(PRIVACY_OFFICER_ALT_USER_ID, ROLE_PRIVACY_OFFICER)

COMPLIANCE_APPROVER = build_user_headers(COMPLIANCE_APPROVER_USER_ID, ROLE_COMPLIANCE_APPROVER)
COMPLIANCE_APPROVER_ALT = build_user_headers(
    COMPLIANCE_APPROVER_ALT_USER_ID, ROLE_COMPLIANCE_APPROVER
)

VENDOR_MANAGER = build_user_headers(VENDOR_MANAGER_USER_ID, ROLE_VENDOR_MANAGER)
VENDOR_MANAGER_ALT = build_user_headers(VENDOR_MANAGER_ALT_USER_ID, ROLE_VENDOR_MANAGER)

HR_ADMIN = build_user_headers(HR_ADMIN_USER_ID, ROLE_HR_ADMINISTRATOR)
HR_ADMIN_ALT = build_user_headers(HR_ADMIN_ALT_USER_ID, ROLE_HR_ADMINISTRATOR)

# The same human wearing two hats: same user id, two different roles.
DUAL_HAT_AS_PRIVACY_OFFICER = build_user_headers(DUAL_HAT_USER_ID, ROLE_PRIVACY_OFFICER)
DUAL_HAT_AS_COMPLIANCE_APPROVER = build_user_headers(DUAL_HAT_USER_ID, ROLE_COMPLIANCE_APPROVER)
DUAL_HAT_AS_VENDOR_MANAGER = build_user_headers(DUAL_HAT_USER_ID, ROLE_VENDOR_MANAGER)


# --- per-instance identity builders ---------------------------------
def make_subject_headers(subject_id: str) -> Dict[str, str]:
    """Headers for the data subject who owns ``subject_id``.

    The Subject role is identified by the DataSubject row it acts on, so the
    real row id must be threaded through as ``X-User-ID``.
    """
    return build_user_headers(subject_id, ROLE_SUBJECT)


def make_privacy_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PRIVACY_OFFICER)


def make_compliance_approver_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLIANCE_APPROVER)


def make_vendor_manager_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_VENDOR_MANAGER)


def make_hr_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_HR_ADMINISTRATOR)


def make_system_operator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SYSTEM_OPERATOR)


# Headers missing the auth pair entirely.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": PRIVACY_OFFICER_USER_ID,
    "Content-Type": "application/json",
}
MISSING_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-Role": ROLE_PRIVACY_OFFICER,
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers("x-1", "DataProtectionOfficer")
