"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rule:

    "When X-User-Role is `Requester`, the value of `X-User-ID` is
    interpreted as the `id` of the acting `Requester` entity; any
    ownership check on a resource that references a requester (most
    notably `Request.requester_id`, and any cascading check via
    `Request`) compares the resource's foreign-key field to
    `X-User-ID`. When `X-User-Role` is `Officer`, `AppealAuthority`,
    `ThirdParty`, or `ClockOperator`, `X-User-ID` is an opaque operator
    identifier not tied to any persisted entity."

The only entity_backed role is `Requester` (PRD §2.1). All
requester-initiated calls that are ownership-gated — POST /foia/requests
(carrying the requester's own id), POST /foia/requests/{id}/withdraw,
POST /foia/fee-assessments/{id}/accept, POST /foia/appeals (when
appellant_role=REQUESTER) — MUST mint headers with the actual
Requester.id via `make_requester_headers(requester_id)`. Falling back
to a shared placeholder id would fail every ownership check
deterministically, hiding implementation bugs behind universal 403s.

The other four roles (Officer, AppealAuthority, ThirdParty,
ClockOperator) are opaque per PRD §2.1: shared deterministic ids are
the canonical form. AppealAuthority and ThirdParty additionally have
distinct-operator builders so segregation-of-duties (§2.8) and
third-party identity (§3.7) can be exercised explicitly.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared deterministic ids for opaque roles.
# ---------------------------------------------------------------------------
OFFICER_SHARED_ID: str = "officer-op-0001"
OFFICER_SECONDARY_ID: str = "officer-op-0002"

APPEAL_AUTHORITY_SHARED_ID: str = "appeal-auth-op-0001"
APPEAL_AUTHORITY_SECONDARY_ID: str = "appeal-auth-op-0002"

THIRD_PARTY_SHARED_ID: str = "third-party-op-0001"
THIRD_PARTY_SECONDARY_ID: str = "third-party-op-0002"

CLOCK_OPERATOR_SHARED_ID: str = "clock-op-0001"

# Requester is entity_backed — this placeholder resolves to no real
# Requester. Appropriate for auth/role-forbidden/404 probes only; any
# test whose success depends on the requester owning the resource MUST
# use make_requester_headers(requester_id) with a real Requester.id.
REQUESTER_PLACEHOLDER_ID: str = "requester-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed Requester — shared constant is a placeholder for
    # auth/role/404 probes only.
    "requester_headers": build_user_headers(
        REQUESTER_PLACEHOLDER_ID, "Requester",
    ),
    # opaque roles — shared constants are the canonical form.
    "officer_headers": build_user_headers(
        OFFICER_SHARED_ID, "Officer",
    ),
    "officer_secondary_headers": build_user_headers(
        OFFICER_SECONDARY_ID, "Officer",
    ),
    "appeal_authority_headers": build_user_headers(
        APPEAL_AUTHORITY_SHARED_ID, "AppealAuthority",
    ),
    "appeal_authority_secondary_headers": build_user_headers(
        APPEAL_AUTHORITY_SECONDARY_ID, "AppealAuthority",
    ),
    "third_party_headers": build_user_headers(
        THIRD_PARTY_SHARED_ID, "ThirdParty",
    ),
    "third_party_secondary_headers": build_user_headers(
        THIRD_PARTY_SECONDARY_ID, "ThirdParty",
    ),
    "clock_operator_headers": build_user_headers(
        CLOCK_OPERATOR_SHARED_ID, "ClockOperator",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for the entity_backed Requester role.
# PRD §2.1: "any ownership check on a resource that references a
# requester ... compares the resource's foreign-key field to X-User-ID."
# ---------------------------------------------------------------------------
def make_requester_headers(requester_id: str) -> Dict[str, str]:
    """Headers for a Requester acting on behalf of `requester_id`.

    Required whenever the call resolves an ownership check against the
    Requester.id — POST /foia/requests with this id in the body,
    POST /foia/requests/{id}/withdraw on a request whose
    requester_id == this id, POST /foia/fee-assessments/{id}/accept,
    POST /foia/appeals with appellant_role=REQUESTER.
    """
    return build_user_headers(requester_id, "Requester")


# ---------------------------------------------------------------------------
# Per-operator builders for opaque roles. Useful when a test needs two
# distinct operators (segregation-of-duties; third-party identity).
# ---------------------------------------------------------------------------
def make_officer_headers(operator_id: str) -> Dict[str, str]:
    """Headers for an Officer with a specific operator id. Used when a
    test needs to capture a specific actor_id on a DETERMINATION_ISSUED
    audit entry so it can later assert the segregation-of-duties check
    rejects the same operator when they try to accept the appeal."""
    return build_user_headers(operator_id, "Officer")


def make_appeal_authority_headers(operator_id: str) -> Dict[str, str]:
    """Headers for an AppealAuthority with a specific operator id."""
    return build_user_headers(operator_id, "AppealAuthority")


def make_third_party_headers(operator_id: str) -> Dict[str, str]:
    """Headers for a ThirdParty acting under a specific opaque id.

    PRD §3.7 requires the calling X-User-ID equal
    ThirdPartyNotice.third_party_id for /consent and /object; tests
    that exercise consent/object/object-then-override use this builder
    with the same third_party_id that was written onto the
    ResponsiveRecord and propagated to the notice.
    """
    return build_user_headers(operator_id, "ThirdParty")


def make_clock_operator_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "ClockOperator")


__all__ = [
    "OFFICER_SHARED_ID", "OFFICER_SECONDARY_ID",
    "APPEAL_AUTHORITY_SHARED_ID", "APPEAL_AUTHORITY_SECONDARY_ID",
    "THIRD_PARTY_SHARED_ID", "THIRD_PARTY_SECONDARY_ID",
    "CLOCK_OPERATOR_SHARED_ID",
    "REQUESTER_PLACEHOLDER_ID",
    "TEST_USERS",
    "make_requester_headers",
    "make_officer_headers",
    "make_appeal_authority_headers",
    "make_third_party_headers",
    "make_clock_operator_headers",
]
