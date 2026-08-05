"""Pre-built role headers for every role in the PRD.

MunicipalAdmin and CountyClerk are opaque operator identities (the server records
X-User-ID for audit but never matches it against an entity id). Developer and
TaxingBodyRep are entity-backed: their X-User-ID must equal the acting entity's id,
so ownership-gated calls MUST use the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Two distinct MunicipalAdmin identities to exercise four-eyes segregation of
# duties: admin-1 registers, admin-2 disburses.
ADMIN_1_ID = "admin-1"
ADMIN_2_ID = "admin-2"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "municipal_admin_headers": build_user_headers(ADMIN_1_ID, "MunicipalAdmin"),
    "municipal_admin_2_headers": build_user_headers(ADMIN_2_ID, "MunicipalAdmin"),
    "county_clerk_headers": build_user_headers("clerk-1", "CountyClerk"),
    # Entity-backed fallback used only for non-ownership tests (e.g. 404/validation).
    "taxing_body_rep_headers": build_user_headers("tbrep-unbound", "TaxingBodyRep"),
    "developer_headers": build_user_headers("dev-unbound", "Developer"),
}


def make_admin_headers(user_id: str) -> dict:
    """MunicipalAdmin headers for a specific operator id (four-eyes SoD)."""
    return build_user_headers(user_id, "MunicipalAdmin")


def make_developer_headers(user_id: str) -> dict:
    """For Developer (entity_backed:Developer). Pass the actual Developer.id so
    ownership checks (X-User-ID == obligation.developer_id) pass."""
    return build_user_headers(user_id, "Developer")


def make_county_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CountyClerk")


def make_taxing_body_rep_headers(user_id: str) -> dict:
    """For TaxingBodyRep (entity_backed:TaxingBody). Pass the actual TaxingBody.id."""
    return build_user_headers(user_id, "TaxingBodyRep")
