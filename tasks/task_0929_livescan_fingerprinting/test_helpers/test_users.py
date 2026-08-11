"""Pre-built role headers for every role in the PRD.

Five of the six roles carry an opaque operator identifier in X-User-ID: the
server records it wherever a transition writes an actor field but never
compares it against any row's id.  The Applicant role is different — its
X-User-ID is the id of the acting Applicant row — so ownership-gated calls
must use make_applicant_headers(applicant["id"]).
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities: the shared constant is the canonical form.
    "vendor_admin_headers": build_user_headers("vend-01", "VendorAdmin"),
    "technician_headers": build_user_headers("tech-01", "LivescanTechnician"),
    "second_technician_headers": build_user_headers("tech-02", "LivescanTechnician"),
    "supervisor_headers": build_user_headers("sup-77", "SiteSupervisor"),
    "second_supervisor_headers": build_user_headers("sup-88", "SiteSupervisor"),
    "adjudicator_headers": build_user_headers("adj-01", "AgencyAdjudicator"),
    "second_adjudicator_headers": build_user_headers("adj-02", "AgencyAdjudicator"),
    "destination_headers": build_user_headers("dest-01", "StateRepository"),
    # Applicant is entity-backed: this constant is a fallback for calls that do
    # not turn on ownership (role-denial probes, for example).
    "applicant_headers": build_user_headers("applicant-unbound", "Applicant"),
}

TECHNICIAN_USER_ID = "tech-01"
SECOND_TECHNICIAN_USER_ID = "tech-02"
SUPERVISOR_USER_ID = "sup-77"
SECOND_SUPERVISOR_USER_ID = "sup-88"
ADJUDICATOR_USER_ID = "adj-01"
SECOND_ADJUDICATOR_USER_ID = "adj-02"
VENDOR_ADMIN_USER_ID = "vend-01"
SECOND_VENDOR_ADMIN_USER_ID = "vend-02"
DESTINATION_USER_ID = "dest-01"


def make_applicant_headers(applicant_id: str) -> dict:
    """For the Applicant role, whose X-User-ID is the acting Applicant row's id."""
    return build_user_headers(applicant_id, "Applicant")


def make_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LivescanTechnician")


def make_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SiteSupervisor")


def make_adjudicator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AgencyAdjudicator")


def make_vendor_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VendorAdmin")


def headers_without_auth() -> dict:
    """A request carrying neither X-User-ID nor X-User-Role."""
    return {"Content-Type": "application/json"}
