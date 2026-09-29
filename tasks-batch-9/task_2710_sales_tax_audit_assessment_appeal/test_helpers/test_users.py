"""Pre-built role headers for the seven roles the API recognises.

Six roles are operator roles whose X-User-ID is an opaque identifier the server
never compares to an entity id. `Taxpayer` is the one entity-backed role: its
X-User-ID must be the id of the acting Taxpayer record, so ownership-gated calls
MUST build headers with make_taxpayer_headers(taxpayer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    APPEALS_OFFICER_USER_ID,
    COLLECTIONS_AGENT_USER_ID,
    LEAD_AUDITOR_USER_ID,
    OTHER_APPEALS_OFFICER_USER_ID,
    OTHER_AUDITOR_USER_ID,
    SELECTION_ANALYST_USER_ID,
    SUPERVISOR_USER_ID,
    TRIBUNAL_JUDGE_USER_ID,
)

TEST_USERS = {
    "selection_analyst_headers": build_user_headers(
        SELECTION_ANALYST_USER_ID, "SelectionAnalyst"
    ),
    "field_auditor_headers": build_user_headers(LEAD_AUDITOR_USER_ID, "FieldAuditor"),
    "other_field_auditor_headers": build_user_headers(
        OTHER_AUDITOR_USER_ID, "FieldAuditor"
    ),
    "audit_supervisor_headers": build_user_headers(SUPERVISOR_USER_ID, "AuditSupervisor"),
    "appeals_officer_headers": build_user_headers(
        APPEALS_OFFICER_USER_ID, "AppealsOfficer"
    ),
    "other_appeals_officer_headers": build_user_headers(
        OTHER_APPEALS_OFFICER_USER_ID, "AppealsOfficer"
    ),
    "tax_tribunal_judge_headers": build_user_headers(
        TRIBUNAL_JUDGE_USER_ID, "TaxTribunalJudge"
    ),
    "collections_agent_headers": build_user_headers(
        COLLECTIONS_AGENT_USER_ID, "CollectionsAgent"
    ),
    # Fallback only: safe for tests that never touch an ownership-gated path.
    "taxpayer_headers": build_user_headers("test-taxpayer-unowned", "Taxpayer"),
}

ROLE_HEADER_KEYS = {
    "SelectionAnalyst": "selection_analyst_headers",
    "FieldAuditor": "field_auditor_headers",
    "AuditSupervisor": "audit_supervisor_headers",
    "AppealsOfficer": "appeals_officer_headers",
    "TaxTribunalJudge": "tax_tribunal_judge_headers",
    "CollectionsAgent": "collections_agent_headers",
}


def make_taxpayer_headers(taxpayer_id: str) -> dict:
    """Headers for the entity-backed `Taxpayer` role.

    Pass the actual Taxpayer record's id: every ownership check compares the
    taxpayer reachable from the addressed resource against X-User-ID.
    """
    return build_user_headers(taxpayer_id, "Taxpayer")


def make_supervisor_headers(user_id: str) -> dict:
    """Headers for an `AuditSupervisor` acting under a chosen operator id."""
    return build_user_headers(user_id, "AuditSupervisor")


def make_field_auditor_headers(user_id: str) -> dict:
    """Headers for a `FieldAuditor` acting under a chosen operator id."""
    return build_user_headers(user_id, "FieldAuditor")


def make_appeals_officer_headers(user_id: str) -> dict:
    """Headers for an `AppealsOfficer` acting under a chosen operator id."""
    return build_user_headers(user_id, "AppealsOfficer")


def make_tribunal_judge_headers(user_id: str) -> dict:
    """Headers for a `TaxTribunalJudge` acting under a chosen operator id."""
    return build_user_headers(user_id, "TaxTribunalJudge")


def make_collections_agent_headers(user_id: str) -> dict:
    """Headers for a `CollectionsAgent` acting under a chosen operator id."""
    return build_user_headers(user_id, "CollectionsAgent")


def make_selection_analyst_headers(user_id: str) -> dict:
    """Headers for a `SelectionAnalyst` acting under a chosen operator id."""
    return build_user_headers(user_id, "SelectionAnalyst")
