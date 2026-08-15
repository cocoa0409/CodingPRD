"""Pre-built role headers for the five PRD roles (PRD §2.1).

DepartmentAdmin, Radiopharmacist, NuclearMedicineTechnologist and
RadiationSafetyOfficer carry an opaque operator identifier: the server may
record it (e.g. as calibrated_by_user_id) but never matches it against an
entity id, so shared constants are safe for them.

AuthorizedUser is entity-backed: X-User-ID must be the id of an existing
AuthorizedUser record and ownership checks compare it to the order's
authorized_user_id. For any ownership-gated call, build headers with
make_authorized_user_headers(authorized_user["id"]) — never with the shared
fallback constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque-role shared constants (canonical form).
    "admin_headers": build_user_headers("admin-1", "DepartmentAdmin"),
    "radiopharmacist_headers": build_user_headers("rp-1", "Radiopharmacist"),
    "technologist_headers": build_user_headers("tech-1", "NuclearMedicineTechnologist"),
    "rso_headers": build_user_headers("rso-1", "RadiationSafetyOfficer"),
    # Entity-backed role: fallback for calls whose success does NOT depend on
    # the caller owning the subject resource (e.g. expecting ERR_NOT_FOUND).
    "authorized_user_headers": build_user_headers("test-au-1", "AuthorizedUser"),
}


def make_admin_headers(user_id: str) -> dict:
    """DepartmentAdmin with an explicit opaque operator id."""
    return build_user_headers(user_id, "DepartmentAdmin")


def make_radiopharmacist_headers(user_id: str) -> dict:
    """Radiopharmacist with an explicit opaque operator id (calibration SoD anchor)."""
    return build_user_headers(user_id, "Radiopharmacist")


def make_technologist_headers(user_id: str) -> dict:
    """NuclearMedicineTechnologist with an explicit opaque operator id (administration SoD anchor)."""
    return build_user_headers(user_id, "NuclearMedicineTechnologist")


def make_rso_headers(user_id: str) -> dict:
    """RadiationSafetyOfficer with an explicit opaque operator id (seal/certify and report/clear SoD anchors)."""
    return build_user_headers(user_id, "RadiationSafetyOfficer")


def make_authorized_user_headers(user_id: str) -> dict:
    """AuthorizedUser headers. Pass the actual AuthorizedUser.id whenever the
    call is ownership-gated (order creation, cancel, substitute, release
    instruction issuance)."""
    return build_user_headers(user_id, "AuthorizedUser")
