"""Pre-built role headers for every role in the PRD (section 2.1).

ProjectManager, PayrollAdmin and BillingClerk carry an opaque X-User-ID that
the server never compares against any entity id, so shared constants are the
canonical form for them.

FieldRep and Client are entity-backed: X-User-ID must equal the acting
FieldRep/Client entity's id for ownership-gated calls (a rep acting on another
rep's assignment, or a client acting on another client's project, is rejected
with ERR_UNAUTHORIZED). Use make_field_rep_headers(entity_id) /
make_client_headers(entity_id) whenever the call is ownership-gated; the
shared constants are fallbacks for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "pm_headers": build_user_headers("pm-operator-1", "ProjectManager"),
    "payroll_admin_headers": build_user_headers("payroll-operator-1", "PayrollAdmin"),
    "billing_clerk_headers": build_user_headers("billing-operator-1", "BillingClerk"),
    # entity_backed fallbacks — non-ownership tests only
    "field_rep_headers": build_user_headers("rep-placeholder-1", "FieldRep"),
    "client_headers": build_user_headers("client-placeholder-1", "Client"),
    # Anonymous placeholder: negative auth tests omit both auth headers
    "anonymous_headers": {},
}


def make_field_rep_headers(rep_id: str) -> dict:
    """FieldRep is entity_backed: pass the actual FieldRep.id as rep_id
    whenever the call is ownership-gated (depart/check-in/check-out on the
    rep's own assignments, photo upload, own mileage-log submission)."""
    return build_user_headers(rep_id, "FieldRep")


def make_client_headers(client_id: str) -> dict:
    """Client is entity_backed: pass the actual Client.id as client_id
    whenever the call is ownership-gated (rework approve/deny)."""
    return build_user_headers(client_id, "Client")
