"""Pre-built role headers for every role in the PRD.

Four roles carry an opaque operator identifier that is never compared to any
row's id: ProgramAdmin, IntakeCoordinator, FundingOfficer and
TransportDispatcher.  Two roles are entity-backed and MUST be built per
instance: an ActivityLead's X-User-ID is the acting StaffMember's id and a
CaregiverUser's X-User-ID is the acting Caregiver's id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.
ADMIN_USER_ID = "admin-1"
COORDINATOR_USER_ID = "coord-1"
OFFICER_ONE_USER_ID = "officer-1"
OFFICER_TWO_USER_ID = "officer-2"
DISPATCHER_USER_ID = "dispatch-1"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "intake_coordinator_headers": build_user_headers(COORDINATOR_USER_ID, "IntakeCoordinator"),
    "funding_officer_headers": build_user_headers(OFFICER_ONE_USER_ID, "FundingOfficer"),
    "funding_officer_two_headers": build_user_headers(OFFICER_TWO_USER_ID, "FundingOfficer"),
    "transport_dispatcher_headers": build_user_headers(DISPATCHER_USER_ID, "TransportDispatcher"),
    # Entity-backed roles — these shared constants are ONLY safe for tests that
    # deliberately exercise an unresolvable identity.  Every ownership-gated
    # call must use the per-instance builders below.
    "activity_lead_unknown_headers": build_user_headers(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", "ActivityLead"
    ),
    "caregiver_unknown_headers": build_user_headers(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", "CaregiverUser"
    ),
}


def make_program_admin_headers(user_id=ADMIN_USER_ID):
    return build_user_headers(user_id, "ProgramAdmin")


def make_intake_coordinator_headers(user_id=COORDINATOR_USER_ID):
    return build_user_headers(user_id, "IntakeCoordinator")


def make_funding_officer_headers(user_id=OFFICER_ONE_USER_ID):
    """FundingOfficer is opaque, but its X-User-ID is stamped onto awards as
    awarded_by_user_id / disbursed_by_user_id, so tests control it explicitly."""
    return build_user_headers(user_id, "FundingOfficer")


def make_transport_dispatcher_headers(user_id=DISPATCHER_USER_ID):
    return build_user_headers(user_id, "TransportDispatcher")


def make_activity_lead_headers(staff_member_id):
    """For ActivityLead. Pass the acting StaffMember's own id as X-User-ID."""
    return build_user_headers(staff_member_id, "ActivityLead")


def make_caregiver_headers(caregiver_id):
    """For CaregiverUser. Pass the acting Caregiver's own id as X-User-ID."""
    return build_user_headers(caregiver_id, "CaregiverUser")


def headers_without_role(user_id=COORDINATOR_USER_ID):
    """Headers carrying X-User-ID but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role="IntakeCoordinator"):
    """Headers carrying X-User-Role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
