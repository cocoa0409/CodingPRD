"""Authentication headers for every role.

Two shapes are provided, and choosing the wrong one is the classic source of
false failures.

``TEST_USERS`` holds one ready-made header set per role and is only safe where
the acting identity is genuinely irrelevant: the opaque ``ComplianceAdmin``
credential, and negative probes that never get past the authorisation band.

Every seat-backed role resolves ``X-User-ID`` to the acting ``CommitteeMember``
row, and ownership, function and segregation-of-duties checks compare that
identifier against the resource. Those calls must use the per-member builders
below so that the acting seat is the seat the scenario intends.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BUSINESS_LEADER,
    ROLE_CERTIFYING_OFFICER,
    ROLE_CHAIR,
    ROLE_COMPLIANCE_ADMIN,
    ROLE_CONTROLLER,
    ROLE_INVESTOR_RELATIONS,
    ROLE_LEGAL_COUNSEL,
)

# The opaque compliance-operations credential. X-User-ID is never resolved to a
# committee seat, so one shared value serves every call.
COMPLIANCE_ADMIN_USER_ID = "ops-console-7"

TEST_USERS = {
    ROLE_COMPLIANCE_ADMIN: build_user_headers(COMPLIANCE_ADMIN_USER_ID, ROLE_COMPLIANCE_ADMIN),
    ROLE_CHAIR: build_user_headers("chair-placeholder", ROLE_CHAIR),
    ROLE_CONTROLLER: build_user_headers("controller-placeholder", ROLE_CONTROLLER),
    ROLE_LEGAL_COUNSEL: build_user_headers("legal-placeholder", ROLE_LEGAL_COUNSEL),
    ROLE_INVESTOR_RELATIONS: build_user_headers("ir-placeholder", ROLE_INVESTOR_RELATIONS),
    ROLE_CERTIFYING_OFFICER: build_user_headers("officer-placeholder", ROLE_CERTIFYING_OFFICER),
    ROLE_BUSINESS_LEADER: build_user_headers("leader-placeholder", ROLE_BUSINESS_LEADER),
}

ADMIN = TEST_USERS[ROLE_COMPLIANCE_ADMIN]


def admin_headers():
    """Headers for the opaque compliance-operations credential."""
    return build_user_headers(COMPLIANCE_ADMIN_USER_ID, ROLE_COMPLIANCE_ADMIN)


def make_chair_headers(user_id):
    """Act as DisclosureCommitteeChair from the seat ``user_id``; the seat's
    ``voting`` flag must be true."""
    return build_user_headers(user_id, ROLE_CHAIR)


def make_controller_headers(user_id):
    """Act as Controller from the seat ``user_id``; the seat's ``function``
    must be FINANCE."""
    return build_user_headers(user_id, ROLE_CONTROLLER)


def make_legal_counsel_headers(user_id):
    """Act as LegalCounsel from the seat ``user_id``; the seat's ``function``
    must be LEGAL."""
    return build_user_headers(user_id, ROLE_LEGAL_COUNSEL)


def make_investor_relations_headers(user_id):
    """Act as InvestorRelations from the seat ``user_id``; the seat's
    ``function`` must be INVESTOR_RELATIONS."""
    return build_user_headers(user_id, ROLE_INVESTOR_RELATIONS)


def make_certifying_officer_headers(user_id):
    """Act as CertifyingOfficer from the seat ``user_id``; the seat's
    ``is_officer`` flag must be true."""
    return build_user_headers(user_id, ROLE_CERTIFYING_OFFICER)


def make_business_leader_headers(user_id):
    """Act as BusinessLeader from the seat ``user_id``; any function is
    accepted."""
    return build_user_headers(user_id, ROLE_BUSINESS_LEADER)


def make_headers(user_id, role):
    """Act as an arbitrary role from an arbitrary identifier, including role
    names that are not among the seven declared ones."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id):
    """Headers carrying only ``X-User-ID``."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role):
    """Headers carrying only ``X-User-Role``."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_user_id(role):
    """Headers whose ``X-User-ID`` is the empty string."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}
