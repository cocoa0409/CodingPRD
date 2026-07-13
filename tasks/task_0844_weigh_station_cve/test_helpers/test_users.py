"""Pre-built role headers for every role in the PRD.

Four roles are opaque operator identities (ComplianceAdmin, Screener, Inspector,
EnforcementOfficer): their X-User-ID is an arbitrary operator string never compared
to any entity id. The fifth role, CarrierRep, is entity-backed: its X-User-ID must be
the id of the acting Carrier, so ownership-gated calls MUST use make_carrier_rep_headers
with the actual Carrier.id.

EnforcementOfficer identity is recorded on citations (issued_by_user_id /
adjudicated_by_user_id) and drives the segregation-of-duties check, so distinct
officer identities are built with make_officer_headers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for non-ownership tests only.
TEST_USERS = {
    "compliance_admin_headers": build_user_headers("test-admin-1", "ComplianceAdmin"),
    "screener_headers": build_user_headers("test-screener-1", "Screener"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "enforcement_officer_headers": build_user_headers("officer-1", "EnforcementOfficer"),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "carrier_rep_headers": build_user_headers("test-carrier-rep-1", "CarrierRep"),
}


def make_carrier_rep_headers(carrier_id: str) -> dict:
    """For CarrierRep (entity_backed:Carrier). Pass the acting Carrier.id so ownership
    checks (X-User-ID == resource carrier reference) resolve."""
    return build_user_headers(carrier_id, "CarrierRep")


def make_officer_headers(user_id: str) -> dict:
    """For EnforcementOfficer. Pass a distinct operator id (e.g. 'officer-1',
    'officer-2') so segregation-of-duties (issuer != adjudicator) is exercisable."""
    return build_user_headers(user_id, "EnforcementOfficer")


def make_compliance_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ComplianceAdmin")


def make_screener_headers(user_id: str = "test-screener-1") -> dict:
    return build_user_headers(user_id, "Screener")


def make_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    return build_user_headers(user_id, "Inspector")
