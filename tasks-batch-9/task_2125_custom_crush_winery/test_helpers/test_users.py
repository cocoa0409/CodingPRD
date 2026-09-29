"""Pre-built role headers for every role the facility recognises (PRD 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Standing operator identities.  FacilityAdmin, CellarSupervisor and
# ComplianceOfficer carry opaque X-User-ID values that are never compared to any
# entity id, so a shared constant is the canonical form for those three roles.
FACILITY_ADMIN_ID = "fa-carol"
CELLAR_SUPERVISOR_ID = "cs-bob"
COMPLIANCE_OFFICER_ID = "co-alice"
SECOND_COMPLIANCE_OFFICER_ID = "co-dave"

TEST_USERS = {
    "facility_admin_headers": build_user_headers(FACILITY_ADMIN_ID, "FacilityAdmin"),
    "cellar_supervisor_headers": build_user_headers(
        CELLAR_SUPERVISOR_ID, "CellarSupervisor"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_ID, "ComplianceOfficer"
    ),
    "second_compliance_officer_headers": build_user_headers(
        SECOND_COMPLIANCE_OFFICER_ID, "ComplianceOfficer"
    ),
    # ClientRep is identified by the Client id it acts for; this shared constant
    # is only safe on calls that never reach an ownership check (400-on-bad-body
    # or 403-on-role rejections).  Use make_client_rep_headers() everywhere else.
    "client_rep_headers": build_user_headers("test-client-rep-1", "ClientRep"),
}


def make_facility_admin_headers(user_id: str) -> dict:
    """FacilityAdmin acting under a specific operator identity."""
    return build_user_headers(user_id, "FacilityAdmin")


def make_cellar_supervisor_headers(user_id: str) -> dict:
    """CellarSupervisor acting under a specific operator identity."""
    return build_user_headers(user_id, "CellarSupervisor")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer acting under a specific operator identity."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_client_rep_headers(client_id: str) -> dict:
    """ClientRep for one Client.  X-User-ID must be that Client's own id."""
    return build_user_headers(client_id, "ClientRep")


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
