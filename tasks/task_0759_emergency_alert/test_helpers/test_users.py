"""Pre-built role headers for every role in the PRD.

Opaque roles (Dispatcher, Approver, ContactAdmin, Integrator) carry an operator
identifier that is never compared to an entity id (except author_user_id for the
segregation-of-duties check). The Contact role is entity-backed: its X-User-ID must
equal the acting Contact's id, so ownership-gated calls MUST use make_contact_headers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable operator identifiers used consistently across setups. The Dispatcher id is
# recorded as author_user_id, so the Approver id must differ from it.
DISPATCHER_ID = "disp1"
APPROVER_ID = "appr1"
CONTACT_ADMIN_ID = "admin1"
INTEGRATOR_ID = "intg1"

TEST_USERS = {
    "dispatcher_headers": build_user_headers(DISPATCHER_ID, "Dispatcher"),
    "approver_headers": build_user_headers(APPROVER_ID, "Approver"),
    "contact_admin_headers": build_user_headers(CONTACT_ADMIN_ID, "ContactAdmin"),
    "integrator_headers": build_user_headers(INTEGRATOR_ID, "Integrator"),
    # Shared Contact constant — a fallback for non-ownership scenarios only. Ownership
    # -gated calls must instead use make_contact_headers(contact_id).
    "contact_headers": build_user_headers("contact-generic", "Contact"),
}


def make_contact_headers(user_id: str) -> dict:
    """For the Contact role (entity_backed:Contact). Pass the actual Contact.id as
    user_id whenever the call is ownership-gated (confirm/opt-out own channel,
    acknowledge own notification, subscribe/cancel own subscription)."""
    return build_user_headers(user_id, "Contact")


def make_dispatcher_headers(user_id: str) -> dict:
    """Dispatcher headers with an explicit operator id (recorded as author_user_id)."""
    return build_user_headers(user_id, "Dispatcher")


def make_approver_headers(user_id: str) -> dict:
    """Approver headers with an explicit operator id (compared to author_user_id for
    the segregation-of-duties check)."""
    return build_user_headers(user_id, "Approver")
