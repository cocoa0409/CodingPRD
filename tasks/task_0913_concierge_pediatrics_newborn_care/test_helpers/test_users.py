"""Pre-built role headers for every role in the PRD (§2.1).

Three of the five roles carry an opaque `X-User-ID` that is never compared to a
persisted row: `PracticeAdmin`, `CareCoordinator` and `BillingSpecialist`.  The
shared constants below are the canonical form for those.

The remaining two are entity-backed and MUST be built per instance:

- `Physician` — `X-User-ID` is the id of the acting Physician row.
- `Parent`    — `X-User-ID` is the id of the acting Family row.

Any ownership-gated call for those two roles must use the matching builder with
the real entity id; the shared constants are only safe for calls that never
reach an ownership check.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — the shared constant is canonical.
    "admin_headers": build_user_headers("admin-001", "PracticeAdmin"),
    "coordinator_headers": build_user_headers("coord-001", "CareCoordinator"),
    "billing_headers": build_user_headers("billing-001", "BillingSpecialist"),
    # Entity-backed roles — fallback only for calls that never reach ownership.
    "physician_headers": build_user_headers("physician-unbound", "Physician"),
    "parent_headers": build_user_headers("parent-unbound", "Parent"),
}


def make_admin_headers(user_id: str) -> Dict[str, str]:
    """PracticeAdmin acting under a specific operator id."""
    return build_user_headers(user_id, "PracticeAdmin")


def make_coordinator_headers(user_id: str) -> Dict[str, str]:
    """CareCoordinator acting under a specific operator id."""
    return build_user_headers(user_id, "CareCoordinator")


def make_billing_headers(user_id: str) -> Dict[str, str]:
    """BillingSpecialist acting under a specific operator id.

    The segregation-of-duties rule compares this id against a line's
    `submitted_by_user_id`, so charge submission and adjudication must use
    different ids.
    """
    return build_user_headers(user_id, "BillingSpecialist")


def make_physician_headers(physician_id: str) -> Dict[str, str]:
    """Physician acting as the row named by `physician_id`.

    Pass the real Physician id whenever the call is ownership-gated: completing
    a well visit, completing an encounter's clinical axis, cancelling an
    encounter, or issuing a form request.
    """
    return build_user_headers(physician_id, "Physician")


def make_parent_headers(family_id: str) -> Dict[str, str]:
    """Parent acting as the household named by `family_id`."""
    return build_user_headers(family_id, "Parent")
