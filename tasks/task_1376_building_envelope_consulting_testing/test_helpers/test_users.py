"""Pre-built role headers for every role in the PRD.

All five roles are opaque: PRD section 2.1 states X-User-ID "is an opaque
operator identifier that is not tied to any persisted entity" and is never
compared against any entity's id. Shared constants are therefore the
canonical form. Per-instance builders exist so segregation-of-duties tests
can pin a specific X-User-ID against recorded reviewer/performer fields.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "principal_headers": build_user_headers("principal-shared-1", "Principal"),
    "consultant_headers": build_user_headers("consultant-shared-1", "Consultant"),
    "reviewer_headers": build_user_headers("reviewer-shared-1", "Reviewer"),
    "field_technician_headers": build_user_headers("tech-shared-1", "FieldTechnician"),
    "manufacturer_rep_headers": build_user_headers("mfr-shared-1", "ManufacturerRep"),
}


def make_principal_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Principal")


def make_consultant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Consultant")


def make_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Reviewer")


def make_field_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldTechnician")


def make_manufacturer_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ManufacturerRep")
