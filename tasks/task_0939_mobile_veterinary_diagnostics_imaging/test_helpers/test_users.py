"""Pre-built role headers for the six roles the PRD declares.

`PlatformAdmin`, `Scheduler` and `BillingAdmin` carry an opaque operator
identifier that is never compared to any entity's id, so a shared constant is
the canonical form for them.  `ClinicUser`, `FieldTech` and `Specialist` are
entity-backed: their `X-User-ID` must be the id of the acting Clinic,
Technician or Specialist, so every ownership-gated call MUST use the matching
per-instance builder.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("op-admin-1", "PlatformAdmin"),
    "scheduler_headers": build_user_headers("op-scheduler-1", "Scheduler"),
    "billing_admin_headers": build_user_headers("op-billing-1", "BillingAdmin"),
    # Entity-backed roles — these shared constants are safe ONLY for tests that
    # never reach an ownership check (401/403-on-role, 404-on-missing-resource,
    # request-shape failures).  Ownership-gated calls must use the builders.
    "clinic_user_headers": build_user_headers("unbound-clinic-user", "ClinicUser"),
    "field_tech_headers": build_user_headers("unbound-field-tech", "FieldTech"),
    "specialist_headers": build_user_headers("unbound-specialist", "Specialist"),
}


def make_clinic_user_headers(clinic_id: str) -> dict:
    """For ClinicUser: X-User-ID is the id of the acting Clinic."""
    return build_user_headers(clinic_id, "ClinicUser")


def make_field_tech_headers(technician_id: str) -> dict:
    """For FieldTech: X-User-ID is the id of the acting Technician."""
    return build_user_headers(technician_id, "FieldTech")


def make_specialist_headers(specialist_id: str) -> dict:
    """For Specialist: X-User-ID is the id of the acting Specialist."""
    return build_user_headers(specialist_id, "Specialist")


def make_platform_admin_headers(user_id: str = "op-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_scheduler_headers(user_id: str = "op-scheduler-1") -> dict:
    return build_user_headers(user_id, "Scheduler")


def make_billing_admin_headers(user_id: str = "op-billing-1") -> dict:
    return build_user_headers(user_id, "BillingAdmin")


def make_headers(user_id: str, role: str) -> dict:
    """Escape hatch for role names outside the declared six."""
    return build_user_headers(user_id, role)
