"""Pre-built request headers for every role the PRD declares (PRD §2.1).

Two of the five roles are entity-backed and therefore need per-instance
builders: a `CHW`'s `X-User-ID` is the id of the acting `CommunityHealthWorker`,
and a `ResourcePartner`'s `X-User-ID` is the id of the acting `ResourceOrg`.
Ownership-gated calls MUST use the builders with the real entity id; the shared
constants below are only safe where ownership is not what is under test.

The remaining three roles carry opaque operator identifiers that are never
compared to any entity's id, so shared constants are the canonical form.
"""

from prd_bench_local_runner.testing import build_user_headers

# ─── Opaque operator identities ────────────────────────────────────────────

PROGRAM_ADMIN = build_user_headers("admin-1", "ProgramAdmin")
PROGRAM_ADMIN_TWO = build_user_headers("admin-2", "ProgramAdmin")
SUPERVISOR = build_user_headers("sup-1", "Supervisor")
SUPERVISOR_TWO = build_user_headers("sup-2", "Supervisor")
BILLING_SPECIALIST = build_user_headers("bill-1", "BillingSpecialist")

PROGRAM_ADMIN_ID = "admin-1"
PROGRAM_ADMIN_TWO_ID = "admin-2"
SUPERVISOR_ID = "sup-1"
SUPERVISOR_TWO_ID = "sup-2"
BILLING_SPECIALIST_ID = "bill-1"

# ─── Fallback constants for entity-backed roles ────────────────────────────
# Only for calls whose success does not depend on the caller owning the subject
# resource (bad payloads, unknown ids, pure role checks).

CHW_FALLBACK = build_user_headers("chw-unbound-1", "CHW")
RESOURCE_PARTNER_FALLBACK = build_user_headers("partner-unbound-1", "ResourcePartner")

# A request carrying neither header (PRD §2.1 rung 1).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


TEST_USERS = {
    "program_admin_headers": PROGRAM_ADMIN,
    "supervisor_headers": SUPERVISOR,
    "supervisor_two_headers": SUPERVISOR_TWO,
    "billing_specialist_headers": BILLING_SPECIALIST,
    "chw_headers": CHW_FALLBACK,
    "resource_partner_headers": RESOURCE_PARTNER_FALLBACK,
    "no_auth_headers": NO_AUTH_HEADERS,
}


# ─── Per-instance builders (mandatory for entity-backed roles) ─────────────

def make_chw_headers(worker_id: str) -> dict:
    """Headers for a `CHW` acting as the CommunityHealthWorker with this id."""
    return build_user_headers(worker_id, "CHW")


def make_partner_headers(resource_org_id: str) -> dict:
    """Headers for a `ResourcePartner` acting as the ResourceOrg with this id."""
    return build_user_headers(resource_org_id, "ResourcePartner")


def make_supervisor_headers(user_id: str) -> dict:
    """Headers for a `Supervisor` under an explicit opaque operator id."""
    return build_user_headers(user_id, "Supervisor")


def make_program_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_billing_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingSpecialist")
