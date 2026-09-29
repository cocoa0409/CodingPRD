"""Pre-built role headers for the nine roles of PRD §2.1.

Six roles carry an opaque identity: the shared constant in ``TEST_USERS`` is
their canonical form.  Three roles are entity-backed — `PdrTechnician` and
`QualityInspector` to a `Technician`, `InsurerAdjuster` to an `Insurer` — and
for those the header value is an ownership assertion the server checks.  Any
ownership-gated call MUST therefore use the matching per-instance builder with
the real entity's `id`; the shared constants exist only for calls whose
outcome does not depend on ownership (bad payloads, unknown paths, role
rejections).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # opaque identities
    "director_headers": build_user_headers("op-director-1", "CatastropheDirector"),
    "permit_officer_headers": build_user_headers("op-permit-officer-1", "PermitOfficer"),
    "crew_coordinator_headers": build_user_headers("op-crew-coordinator-1", "CrewCoordinator"),
    "intake_advisor_headers": build_user_headers("op-intake-advisor-1", "IntakeAdvisor"),
    "shop_estimator_headers": build_user_headers("op-shop-estimator-1", "ShopEstimator"),
    "billing_coordinator_headers": build_user_headers(
        "op-billing-coordinator-1", "BillingCoordinator"
    ),
    # entity-backed identities — fallbacks for non-ownership tests only
    "pdr_technician_headers": build_user_headers("00000000-0000-4000-8000-000000000000", "PdrTechnician"),
    "quality_inspector_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000000", "QualityInspector"
    ),
    "insurer_adjuster_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000000", "InsurerAdjuster"
    ),
}


# ─── Per-instance builders for the three entity-backed roles ───────────────────

def make_pdr_technician_headers(technician_id: str) -> Dict[str, str]:
    """`PdrTechnician` acts as a `Technician`: pass that technician's `id`."""
    return build_user_headers(technician_id, "PdrTechnician")


def make_quality_inspector_headers(technician_id: str) -> Dict[str, str]:
    """`QualityInspector` acts as a `Technician`: pass that technician's `id`."""
    return build_user_headers(technician_id, "QualityInspector")


def make_insurer_adjuster_headers(insurer_id: str) -> Dict[str, str]:
    """`InsurerAdjuster` acts as an `Insurer`: pass that carrier's `id`."""
    return build_user_headers(insurer_id, "InsurerAdjuster")


# ─── Builders for the opaque roles (identity is not compared to any row) ───────

def make_director_headers(user_id: str = "op-director-1") -> Dict[str, str]:
    return build_user_headers(user_id, "CatastropheDirector")


def make_permit_officer_headers(user_id: str = "op-permit-officer-1") -> Dict[str, str]:
    return build_user_headers(user_id, "PermitOfficer")


def make_crew_coordinator_headers(user_id: str = "op-crew-coordinator-1") -> Dict[str, str]:
    return build_user_headers(user_id, "CrewCoordinator")


def make_intake_advisor_headers(user_id: str = "op-intake-advisor-1") -> Dict[str, str]:
    return build_user_headers(user_id, "IntakeAdvisor")


def make_shop_estimator_headers(user_id: str = "op-shop-estimator-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ShopEstimator")


def make_billing_coordinator_headers(
    user_id: str = "op-billing-coordinator-1",
) -> Dict[str, str]:
    return build_user_headers(user_id, "BillingCoordinator")


def make_undeclared_role_headers(
    role: str = "HailCzar", user_id: str = "op-unknown-1"
) -> Dict[str, str]:
    """Headers naming a role string that is not one of the nine declared roles."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str = "CatastropheDirector") -> Dict[str, str]:
    """Well-formed `X-User-Role` with `X-User-ID` omitted entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
"""Neither `X-User-Role` nor `X-User-ID` is sent."""
