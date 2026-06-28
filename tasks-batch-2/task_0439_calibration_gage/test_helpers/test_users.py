"""Pre-built role headers for every role in the PRD (§2.1).

All three roles use an opaque X-User-ID: the identifier is not tied to any
persisted entity and the server never compares it to an entity id for ownership.
The one place X-User-ID carries downstream meaning is segregation of duties — the
QualityEngineer who investigates or dispositions an out-of-tolerance impact must
have an X-User-ID that differs from the performed_by_user_id recorded on the
triggering calibration event. Tests that exercise that rule build per-id headers
with make_*_headers().
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — every role is opaque, so the shared form is canonical for
# tests whose success does not depend on a specific X-User-ID.
TEST_USERS = {
    "technician_headers": build_user_headers("technician-1", "Technician"),
    "quality_engineer_headers": build_user_headers("quality-engineer-1", "QualityEngineer"),
    "metrologist_headers": build_user_headers("metrologist-1", "Metrologist"),
}


def make_technician_headers(user_id: str) -> dict:
    """Technician headers carrying an explicit X-User-ID (segregation of duties)."""
    return build_user_headers(user_id, "Technician")


def make_quality_engineer_headers(user_id: str) -> dict:
    """QualityEngineer headers carrying an explicit X-User-ID (segregation of duties)."""
    return build_user_headers(user_id, "QualityEngineer")


def make_metrologist_headers(user_id: str) -> dict:
    """Metrologist headers carrying an explicit X-User-ID."""
    return build_user_headers(user_id, "Metrologist")
