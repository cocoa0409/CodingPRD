"""Pre-built role headers for every role in the PRD (§2.1).

All three roles have opaque identity: `X-User-ID` is not tied to any persisted
entity. Technician-scoped execution actions additionally compare `X-User-ID`
against the assigned technician recorded on the target resource, so fixtures
and tests must build technician headers whose user id equals that assignment.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "property_manager_headers": build_user_headers("pm-1", "PropertyManager"),
    "technician_headers": build_user_headers("tech-1", "Technician"),
    "auditor_headers": build_user_headers("aud-1", "ComplianceAuditor"),
}


def make_property_manager_headers(user_id: str = "pm-1") -> dict:
    """PropertyManager headers; identity is opaque (never compared to entity ids)."""
    return build_user_headers(user_id, "PropertyManager")


def make_technician_headers(user_id: str) -> dict:
    """Technician headers. For technician-scoped execution actions (visit
    start/complete/no-access, work-order submit-review/start/complete) the
    user_id MUST equal the visit's technician_id or the work order's
    assigned_technician_id."""
    return build_user_headers(user_id, "Technician")


def make_auditor_headers(user_id: str = "aud-1") -> dict:
    """ComplianceAuditor headers; recorded purely as an audit trail. For audit /
    verify calls the user_id must DIFFER from the performing technician's id
    (segregation of duties)."""
    return build_user_headers(user_id, "ComplianceAuditor")
