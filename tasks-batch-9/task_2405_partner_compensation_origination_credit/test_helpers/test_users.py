"""Pre-built role headers for every role the service recognises.

`CycleAdmin` and `AuditObserver` are opaque: their `X-User-ID` is an operator
identifier that is never compared to any entity's `id`, so the shared constants
below are the canonical form for them.

`Partner`, `CommitteeMember` and `CreditArbiter` are entity-backed: the header
value must be the `id` of a persisted partner row. Any ownership-gated or
actor-resolved call MUST use the matching `make_*_headers(partner_id)` builder
with the real partner id — the shared constants are only usable on tests that
never get past the actor-resolution gate.
"""

from prd_bench_local_runner.testing import build_user_headers

CYCLE_ADMIN_ID = "ops-cycle-admin-1"
AUDIT_OBSERVER_ID = "ops-audit-observer-1"

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "cycle_admin_headers": build_user_headers(CYCLE_ADMIN_ID, "CycleAdmin"),
    "audit_observer_headers": build_user_headers(AUDIT_OBSERVER_ID, "AuditObserver"),
    # Entity-backed roles — fallbacks for tests that never reach a partner lookup.
    "partner_headers": build_user_headers("unresolvable-partner-1", "Partner"),
    "committee_member_headers": build_user_headers(
        "unresolvable-committee-member-1", "CommitteeMember"
    ),
    "credit_arbiter_headers": build_user_headers(
        "unresolvable-credit-arbiter-1", "CreditArbiter"
    ),
}


def make_cycle_admin_headers(user_id: str = CYCLE_ADMIN_ID) -> dict:
    """Headers for the opaque CycleAdmin operator role."""
    return build_user_headers(user_id, "CycleAdmin")


def make_audit_observer_headers(user_id: str = AUDIT_OBSERVER_ID) -> dict:
    """Headers for the opaque, read-only AuditObserver role."""
    return build_user_headers(user_id, "AuditObserver")


def make_partner_headers(user_id: str) -> dict:
    """Headers for the Partner role. Pass the acting partner's own id."""
    return build_user_headers(user_id, "Partner")


def make_committee_member_headers(user_id: str) -> dict:
    """Headers for the CommitteeMember role. Pass the id of a partner row whose
    is_committee_member is true."""
    return build_user_headers(user_id, "CommitteeMember")


def make_credit_arbiter_headers(user_id: str) -> dict:
    """Headers for the CreditArbiter role. Pass the id of a partner row whose
    is_credit_arbiter is true."""
    return build_user_headers(user_id, "CreditArbiter")


# ─── Header shapes used by the authentication-gate tests ───

NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_headers_without_user_id(role: str) -> dict:
    """Both headers required; this one omits X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_without_role(user_id: str) -> dict:
    """Both headers required; this one omits X-User-Role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def make_headers_with_empty_role(user_id: str) -> dict:
    """X-User-Role present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def make_unrecognised_role_headers(user_id: str, role: str = "ManagingPartner") -> dict:
    """Headers naming a role string the service does not recognise."""
    return build_user_headers(user_id, role)
