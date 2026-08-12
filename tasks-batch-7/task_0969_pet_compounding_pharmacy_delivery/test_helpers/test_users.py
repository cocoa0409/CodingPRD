"""Pre-built role headers for every role in the PRD (§2.1).

Owner and Veterinarian are entity-backed: X-User-ID must be the id of the
acting Owner/Veterinarian record on ownership-guarded calls — use the
make_*_headers builders with the real entity id. The other five roles carry
opaque operator identifiers, so shared constants are canonical for them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles (PRD §2.1) — shared constants are canonical.
    "pharmacist_a_headers": build_user_headers("pharm-a", "Pharmacist"),
    "pharmacist_b_headers": build_user_headers("pharm-b", "Pharmacist"),
    "pharmacy_tech_headers": build_user_headers("tech-1", "PharmacyTech"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    "insurance_adjuster_headers": build_user_headers("adjuster-1", "InsuranceAdjuster"),
    "pharmacy_admin_headers": build_user_headers("admin-1", "PharmacyAdmin"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
    "veterinarian_headers": build_user_headers("test-vet-1", "Veterinarian"),
}


def make_owner_headers(user_id: str) -> dict:
    """For Owner (entity-backed). Pass the actual Owner.id as user_id whenever
    the call is ownership-guarded (pay, appeal, enrollment/auto-ship management,
    recall-task acknowledge)."""
    return build_user_headers(user_id, "Owner")


def make_veterinarian_headers(user_id: str) -> dict:
    """For Veterinarian (entity-backed). Pass the actual Veterinarian.id as
    user_id whenever the call is ownership-guarded (vet-confirm, vet-reject,
    request-clarification)."""
    return build_user_headers(user_id, "Veterinarian")
