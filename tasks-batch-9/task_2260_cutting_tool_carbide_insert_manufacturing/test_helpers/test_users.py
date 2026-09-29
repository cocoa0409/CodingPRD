"""Pre-built caller identities for every role the PRD declares.

Every request carries ``X-User-ID`` and ``X-User-Role``. Six of the seven
roles are opaque operator identities whose ``X-User-ID`` is never compared to
any row's ``id``, so a shared constant is the canonical form for them. The
``Customer`` role is entity-backed: its ``X-User-ID`` is the ``id`` of the
acting ``Customer`` row, so ownership-gated calls MUST use
``make_customer_headers(customer["id"])``.
"""

from prd_bench_local_runner.testing import build_user_headers

# ── Shared constants for the six opaque operator roles ──────────────────────
TEST_USERS = {
    "metallurgy_engineer_headers": build_user_headers(
        "test-metallurgy-1", "MetallurgyEngineer"
    ),
    "geometry_engineer_headers": build_user_headers(
        "test-geometry-1", "GeometryEngineer"
    ),
    "coating_engineer_headers": build_user_headers(
        "test-coating-1", "CoatingEngineer"
    ),
    "application_engineer_headers": build_user_headers(
        "test-application-1", "ApplicationEngineer"
    ),
    "quality_approver_headers": build_user_headers(
        "test-quality-1", "QualityApprover"
    ),
    "production_planner_headers": build_user_headers(
        "test-planner-1", "ProductionPlanner"
    ),
    # Entity-backed role: this shared constant is a fallback for tests that do
    # not exercise ownership (it is not the id of any Customer row).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


# ── Per-instance builders ───────────────────────────────────────────────────

def make_customer_headers(customer_id: str) -> dict:
    """Headers for the ``Customer`` role.

    ``Customer`` is entity-backed, so pass the acting ``Customer`` row's own
    ``id`` whenever the call is ownership-gated.
    """
    return build_user_headers(customer_id, "Customer")


def make_metallurgy_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MetallurgyEngineer")


def make_geometry_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GeometryEngineer")


def make_coating_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CoatingEngineer")


def make_application_engineer_headers(user_id: str) -> dict:
    """Headers for an ``ApplicationEngineer`` acting under a named operator id.

    The recorded ``operator_user_id`` on a machining trial and
    ``submitted_by_user_id`` on a dossier come from this value, and both are
    later compared against the deciding user id.
    """
    return build_user_headers(user_id, "ApplicationEngineer")


def make_quality_approver_headers(user_id: str) -> dict:
    """Headers for a ``QualityApprover`` acting under a named user id.

    The deciding user id is recorded as ``decided_by_user_id`` and must differ
    from the submitter and from every trial operator.
    """
    return build_user_headers(user_id, "QualityApprover")


def make_production_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def headers_without_user_id(role: str = "MetallurgyEngineer") -> dict:
    """Headers that omit ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = "MetallurgyEngineer") -> dict:
    """Headers whose ``X-User-ID`` is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}
