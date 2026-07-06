"""Pre-built role headers for every role in the Charitable Gaming PRD (§2.1).

- Regulator is an OPAQUE role: X-User-ID is not tied to any entity, so the shared
  constant is the canonical form.
- OrgOfficer and Supplier are ENTITY-BACKED: X-User-ID must equal the acting
  Organization.id / Supplier.id respectively. Ownership-gated calls MUST use the
  per-instance builders make_orgofficer_headers(org_id) / make_supplier_headers(sup_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — Regulator is opaque (safe everywhere); the entity-backed
# shared entries are fallbacks only for tests that do not exercise ownership
# (e.g. unauthenticated/404/validation probes).
TEST_USERS = {
    "regulator_headers": build_user_headers("regulator-op-1", "Regulator"),
    "org_officer_headers": build_user_headers("test-org-officer-1", "OrgOfficer"),
    "supplier_headers": build_user_headers("test-supplier-1", "Supplier"),
}


def make_regulator_headers(user_id: str = "regulator-op-1") -> dict:
    """Regulator (opaque). Any authenticated Regulator may act on any resource."""
    return build_user_headers(user_id, "Regulator")


def make_orgofficer_headers(org_id: str) -> dict:
    """For OrgOfficer (entity_backed:Organization). Pass the acting Organization.id
    as user_id so ownership checks resolve to the owning organization."""
    return build_user_headers(org_id, "OrgOfficer")


def make_supplier_headers(supplier_id: str) -> dict:
    """For Supplier (entity_backed:Supplier). Pass the acting Supplier.id as user_id
    so ownership checks on equipment resolve correctly."""
    return build_user_headers(supplier_id, "Supplier")
