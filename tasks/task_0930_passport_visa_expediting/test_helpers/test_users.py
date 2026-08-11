"""Pre-built role headers for every role in the PRD.

Five of the six roles carry an opaque operator identity: the server records
the ``X-User-ID`` value for attribution but never compares it to any row's
``id``. The sixth, ``Traveler``, is identity-bound: its ``X-User-ID`` is the
``id`` of the acting ``Applicant`` row, so ownership-gated calls must use the
per-instance builder below with a real applicant id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identities. Safe as shared constants: nothing compares them
# to a stored row.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
    # Two distinct CaseManager identities, because submission requires the
    # acting operator to differ from the order's quoted_by_user_id.
    "case_manager_headers": build_user_headers("cm-quote", "CaseManager"),
    "case_manager_quote_headers": build_user_headers("cm-quote", "CaseManager"),
    "case_manager_review_headers": build_user_headers("cm-review", "CaseManager"),
    "case_manager_submit_headers": build_user_headers("cm-submit", "CaseManager"),
    "case_manager_split_headers": build_user_headers("cm-split", "CaseManager"),
    "courier_ops_headers": build_user_headers("co-1", "CourierOps"),
    "agency_liaison_headers": build_user_headers("al-1", "AgencyLiaison"),
    "compliance_officer_headers": build_user_headers("co-audit", "ComplianceOfficer"),
    # Placeholder Traveler identity for calls that are not ownership-gated
    # (or where the denial itself is the subject under test).
    "traveler_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000001", "Traveler"
    ),
}

# Operator identifiers, spelled once so assertions can compare against them.
QUOTING_USER_ID = "cm-quote"
REVIEWING_USER_ID = "cm-review"
SUBMITTING_USER_ID = "cm-submit"
SPLITTING_USER_ID = "cm-split"
COURIER_USER_ID = "co-1"
AGENCY_USER_ID = "al-1"
COMPLIANCE_USER_ID = "co-audit"

# A request carrying no role header at all.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_traveler_headers(applicant_id: str) -> dict:
    """For Traveler, whose X-User-ID is the id of the acting Applicant row.

    Pass the real applicant id whenever the call is ownership-gated.
    """
    return build_user_headers(applicant_id, "Traveler")


def make_case_manager_headers(user_id: str) -> dict:
    """A CaseManager acting under a specific operator identifier."""
    return build_user_headers(user_id, "CaseManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    """A ComplianceOfficer acting under a specific operator identifier."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_agency_liaison_headers(user_id: str) -> dict:
    """An AgencyLiaison acting under a specific operator identifier."""
    return build_user_headers(user_id, "AgencyLiaison")


def make_courier_ops_headers(user_id: str) -> dict:
    """A CourierOps operator acting under a specific operator identifier."""
    return build_user_headers(user_id, "CourierOps")
