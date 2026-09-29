"""Pre-built request headers for every role (PRD 2.1).

The first four roles are opaque: their ``X-User-ID`` is an operator identifier
that is recorded on the rows they touch but never compared against an entity id.
The ``Investor`` role is entity-backed by a Contact, so its ``X-User-ID`` must be
the acting contact's own id — always build those headers with
``make_investor_headers(contact["id"])``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_DISCLOSURE_OFFICER,
    ROLE_INVESTOR,
    ROLE_IR_ADMIN,
    ROLE_IR_ANALYST,
    ROLE_TRANSFER_AGENT_LIAISON,
)

# Stable operator identifiers for the four opaque roles.
IR_ADMIN_USER_ID = "u_ir_admin_1"
IR_ADMIN_2_USER_ID = "u_ir_admin_2"
IR_ANALYST_USER_ID = "u_ira_1"
IR_ANALYST_2_USER_ID = "u_ira_2"
DISCLOSURE_OFFICER_USER_ID = "u_do_1"
DISCLOSURE_OFFICER_2_USER_ID = "u_do_2"
TRANSFER_AGENT_USER_ID = "u_ta_1"
TRANSFER_AGENT_2_USER_ID = "u_ta_2"

# One operator identity that is used under two different roles, so that the
# authorship and segregation-of-duties walls can be probed with a single user.
DUAL_HAT_USER_ID = "u_dual_1"


def make_ir_admin_headers(user_id: str = IR_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_IR_ADMIN)


def make_ir_analyst_headers(user_id: str = IR_ANALYST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_IR_ANALYST)


def make_disclosure_officer_headers(
    user_id: str = DISCLOSURE_OFFICER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_DISCLOSURE_OFFICER)


def make_transfer_agent_headers(
    user_id: str = TRANSFER_AGENT_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_TRANSFER_AGENT_LIAISON)


def make_investor_headers(contact_id: str) -> Dict[str, str]:
    """Investor headers for the acting contact (its ``X-User-ID`` is the row id)."""
    return build_user_headers(contact_id, ROLE_INVESTOR)


# Shared, ready-made header sets for the four opaque roles.
IR_ADMIN = make_ir_admin_headers()
IR_ADMIN_2 = make_ir_admin_headers(IR_ADMIN_2_USER_ID)
IR_ANALYST = make_ir_analyst_headers()
IR_ANALYST_2 = make_ir_analyst_headers(IR_ANALYST_2_USER_ID)
DISCLOSURE_OFFICER = make_disclosure_officer_headers()
DISCLOSURE_OFFICER_2 = make_disclosure_officer_headers(DISCLOSURE_OFFICER_2_USER_ID)
TRANSFER_AGENT = make_transfer_agent_headers()
TRANSFER_AGENT_2 = make_transfer_agent_headers(TRANSFER_AGENT_2_USER_ID)

# The same operator identity wearing an analyst hat and an officer hat.
DUAL_HAT_ANALYST = make_ir_analyst_headers(DUAL_HAT_USER_ID)
DUAL_HAT_OFFICER = make_disclosure_officer_headers(DUAL_HAT_USER_ID)

TEST_USERS = {
    ROLE_IR_ADMIN: IR_ADMIN,
    ROLE_IR_ANALYST: IR_ANALYST,
    ROLE_DISCLOSURE_OFFICER: DISCLOSURE_OFFICER,
    ROLE_TRANSFER_AGENT_LIAISON: TRANSFER_AGENT,
    # Placeholder only: an Investor request is valid solely when its X-User-ID
    # is the acting contact's id, so tests must call make_investor_headers().
    ROLE_INVESTOR: None,
}

HEADER_BUILDERS = {
    ROLE_IR_ADMIN: make_ir_admin_headers,
    ROLE_IR_ANALYST: make_ir_analyst_headers,
    ROLE_DISCLOSURE_OFFICER: make_disclosure_officer_headers,
    ROLE_TRANSFER_AGENT_LIAISON: make_transfer_agent_headers,
    ROLE_INVESTOR: make_investor_headers,
}

# Header sets used to probe the authentication check (PRD 2.1).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS = {
    "X-User-ID": IR_ADMIN_USER_ID,
    "Content-Type": "application/json",
}
MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_IR_ADMIN,
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS = build_user_headers("u_intern_1", "IRIntern")
