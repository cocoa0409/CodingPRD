"""Pre-built role headers for every role in the PRD (§2.1).

`Customer` is an entity-backed identity: X-User-ID *is* the acting Customer's `id`,
and every ownership check compares the resource's owning-customer field to it. Any
ownership-gated call MUST therefore use `make_customer_headers(<the real customer id>)`.

`LabTechnician`, `PrivacyOfficer` and `PlatformAdmin` carry opaque identities that the
server never compares against any entity id, so the shared constants below are canonical
for those three roles.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed role — the shared constant is only safe for calls that never
    # reach an ownership check (e.g. 401/403-role probes, unknown-resource 404 probes).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles — shared constants are the canonical form.
    "lab_technician_headers": build_user_headers("lab-1", "LabTechnician"),
    "privacy_officer_headers": build_user_headers("po-1", "PrivacyOfficer"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}

# Headers carrying neither X-User-ID nor X-User-Role (PRD §2.1 → ERR_UNAUTHENTICATED).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_customer_headers(customer_id: str) -> dict:
    """For the `Customer` role. Pass the actual Customer.id — ownership checks compare
    the resource's owning-customer field against X-User-ID."""
    return build_user_headers(customer_id, "Customer")


def make_lab_technician_headers(user_id: str = "lab-1") -> dict:
    """For the `LabTechnician` role (opaque identity)."""
    return build_user_headers(user_id, "LabTechnician")


def make_privacy_officer_headers(user_id: str = "po-1") -> dict:
    """For the `PrivacyOfficer` role (opaque identity, recorded verbatim in reviewed_by)."""
    return build_user_headers(user_id, "PrivacyOfficer")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    """For the `PlatformAdmin` role (opaque identity)."""
    return build_user_headers(user_id, "PlatformAdmin")
