"""Pre-built role headers for every role in the PRD.

Three roles carry an identity tied to a persisted row: a `Physician` and a
`NurseInjector` supply the `id` of the acting `Provider`, and a `Patient`
supplies the `id` of the acting `Patient` record.  Any call whose outcome
depends on that identity MUST use the per-instance builders below and pass the
real row id; the shared constants are only safe where the identity is never
compared to a row.

The other four roles are opaque operator identifiers the server never compares
to any row's `id`, so their shared constants are the canonical form.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque identities — the canonical form for these four roles.
    "clinic_admin_headers": build_user_headers("ops-admin-1", "ClinicAdmin"),
    "inventory_manager_headers": build_user_headers("ops-inventory-1", "InventoryManager"),
    "front_desk_headers": build_user_headers("ops-frontdesk-1", "FrontDesk"),
    "compliance_officer_headers": build_user_headers("ops-compliance-1", "ComplianceOfficer"),
    # Entity-backed identities — fallback only for calls that never compare the id.
    "physician_headers": build_user_headers("not-a-provider-id", "Physician"),
    "nurse_injector_headers": build_user_headers("not-a-provider-id", "NurseInjector"),
    "patient_headers": build_user_headers("not-a-patient-id", "Patient"),
}


def make_physician_headers(provider_id: str) -> dict:
    """For a `Physician`; pass the acting Provider's `id`."""
    return build_user_headers(provider_id, "Physician")


def make_nurse_headers(provider_id: str) -> dict:
    """For a `NurseInjector`; pass the acting Provider's `id`."""
    return build_user_headers(provider_id, "NurseInjector")


def make_patient_headers(patient_id: str) -> dict:
    """For a `Patient`; pass the acting Patient row's `id`."""
    return build_user_headers(patient_id, "Patient")


def make_clinic_admin_headers(user_id: str = "ops-admin-1") -> dict:
    return build_user_headers(user_id, "ClinicAdmin")


def make_inventory_manager_headers(user_id: str = "ops-inventory-1") -> dict:
    return build_user_headers(user_id, "InventoryManager")


def make_front_desk_headers(user_id: str = "ops-frontdesk-1") -> dict:
    return build_user_headers(user_id, "FrontDesk")


def make_compliance_officer_headers(user_id: str = "ops-compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_headers_with_role(user_id: str, role: str) -> dict:
    """Escape hatch for role strings outside the seven declared roles."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
