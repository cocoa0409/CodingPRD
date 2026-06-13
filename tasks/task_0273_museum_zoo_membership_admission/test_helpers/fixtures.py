"""Composite setup helpers for the membership/admission API.

Every test starts against a fresh, empty database (the harness restarts the
server before each test). These helpers build all preconditions from scratch
using only PRD-declared endpoints, and use get_success_data() internally so a
broken setup surfaces a clear "Setup step failed" error.

Identity threading: a Patron is entity-backed, so every ownership-gated Patron
call uses make_patron_headers(patron["id"]) with the real Patron.id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_patron_headers,
)
from . import factories as f

ADMIN = TEST_USERS["membership_admin_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
GATE = TEST_USERS["gate_scanner_headers"]


# ─── Tier 0: primitives ───────────────────────────────────────────────

def set_clock(iso8601: str):
    """Advance the server's logical UTC clock to an arbitrary instant."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, ADMIN))


def create_patron(**overrides) -> dict:
    return get_success_data(api_client.create_patron(f.patron_payload(**overrides), ADMIN))


def create_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_membership_plan(f.membership_plan_payload(**overrides), ADMIN)
    )


def create_slot(**overrides) -> dict:
    return get_success_data(api_client.create_slot(f.slot_payload(**overrides), ADMIN))


def create_exhibit(**overrides) -> dict:
    return get_success_data(
        api_client.create_special_exhibit(f.special_exhibit_payload(**overrides), ADMIN)
    )


def create_session(exhibit_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_exhibit_session(exhibit_id, f.exhibit_session_payload(**overrides), ADMIN)
    )


def create_partner(**overrides) -> dict:
    return get_success_data(
        api_client.create_reciprocal_partner(f.reciprocal_partner_payload(**overrides), ADMIN)
    )


# ─── Tier 1: membership state progression ─────────────────────────────

def create_pending_membership(plan_id: str, patron_id: str, **overrides) -> dict:
    """Create a membership in PENDING_PAYMENT for a patron on a plan."""
    return get_success_data(
        api_client.create_membership(
            f.membership_payload(plan_id, patron_id, **overrides),
            make_patron_headers(patron_id),
        )
    )


def settle_membership(membership_id: str) -> dict:
    """Drive a PENDING_PAYMENT membership to ACTIVE via the payment hook."""
    return get_success_data(
        api_client.settle_payment(
            {"target": "MEMBERSHIP", "membership_id": membership_id, "outcome": "SUCCEEDED"},
            ADMIN,
        )
    )


def setup_active_membership(plan_overrides=None, patron_overrides=None,
                            membership_overrides=None):
    """Create plan + patron + membership and activate it. Returns
    (plan, patron, membership) where membership is freshly re-read as ACTIVE."""
    plan = create_plan(**(plan_overrides or {}))
    patron = create_patron(**(patron_overrides or {}))
    create_pending_membership(plan["id"], patron["id"], **(membership_overrides or {}))
    # re-read id from creation
    membership = get_success_data(
        api_client.list_memberships(ADMIN, {"primary_patron_id": patron["id"]})
    )
    m_id = membership[0]["id"] if isinstance(membership, list) else membership["id"]
    settle_membership(m_id)
    active = get_success_data(api_client.get_membership(m_id, make_patron_headers(patron["id"])))
    return plan, patron, active


def setup_active_membership_simple(plan_overrides=None, patron_overrides=None,
                                   membership_overrides=None):
    """Like setup_active_membership but captures the membership id directly from
    the create call (avoids a list round-trip). Returns (plan, patron, membership)."""
    plan = create_plan(**(plan_overrides or {}))
    patron = create_patron(**(patron_overrides or {}))
    membership = create_pending_membership(
        plan["id"], patron["id"], **(membership_overrides or {})
    )
    settle_membership(membership["id"])
    active = get_success_data(
        api_client.get_membership(membership["id"], make_patron_headers(patron["id"]))
    )
    return plan, patron, active


def drive_membership_to_grace(membership_id: str, patron_id: str,
                              grace_clock="2027-06-15T00:00:00Z"):
    """Advance clock past a 2026-06-01-activated term's expiry and run the
    expiration job so the membership lands in GRACE. Returns the GRACE membership."""
    set_clock(grace_clock)
    get_success_data(api_client.run_expirations(ADMIN))
    return get_success_data(api_client.get_membership(membership_id, make_patron_headers(patron_id)))


# ─── Tier 2: orders ───────────────────────────────────────────────────

def create_draft_order(patron_id: str, slot_id: str, **overrides) -> dict:
    """Create a DRAFT order owned by patron_id."""
    return get_success_data(
        api_client.create_order(
            f.order_payload(patron_id, slot_id, **overrides),
            make_patron_headers(patron_id),
        )
    )


def add_ticket(order_id: str, patron_id: str, ticket_type: str,
               person_name: str = "Person", **overrides) -> dict:
    """Add one ticket to a DRAFT order as its owning patron."""
    return get_success_data(
        api_client.add_ticket(
            order_id,
            f.ticket_payload(ticket_type, person_name, **overrides),
            make_patron_headers(patron_id),
        )
    )


def confirm_order(order_id: str, patron_id: str) -> dict:
    """Confirm a DRAFT order as its owning patron. Returns the CONFIRMED order."""
    return get_success_data(
        api_client.confirm_order(order_id, make_patron_headers(patron_id))
    )


def build_draft_order_with_tickets(patron_id: str, slot_id: str, tickets,
                                   order_overrides=None) -> dict:
    """Create a DRAFT order and add the given tickets.

    `tickets` is a list of dicts, each with at least ticket_type, optionally
    person_name and reciprocal_partner_id. Returns the DRAFT order dict (re-read)."""
    order = create_draft_order(patron_id, slot_id, **(order_overrides or {}))
    for i, t in enumerate(tickets):
        add_ticket(
            order["id"], patron_id, t["ticket_type"],
            t.get("person_name", f"Person {i + 1}"),
            **({"reciprocal_partner_id": t["reciprocal_partner_id"]}
               if t.get("reciprocal_partner_id") else {}),
        )
    return get_success_data(api_client.get_order(order["id"], make_patron_headers(patron_id)))


def build_confirmed_order(patron_id: str, slot_id: str, tickets,
                          order_overrides=None) -> dict:
    """Create a DRAFT order, add tickets, and confirm it. Returns the CONFIRMED order."""
    order = build_draft_order_with_tickets(patron_id, slot_id, tickets, order_overrides)
    return confirm_order(order["id"], patron_id)


# ─── Tier 3: fill a slot to capacity via a filler patron ──────────────

def fill_slot_to_capacity(slot_id: str, seats: int, person_prefix="Filler"):
    """Confirm a single order of `seats` NON_MEMBER tickets by a fresh filler
    patron on `slot_id`, so the slot's reserved_count == seats. Returns the
    (filler_patron, confirmed_order)."""
    filler = create_patron()
    tickets = [{"ticket_type": "NON_MEMBER", "person_name": f"{person_prefix} {i}"}
               for i in range(seats)]
    order = build_confirmed_order(filler["id"], slot_id, tickets)
    return filler, order


# ─── Read helpers for assertions ──────────────────────────────────────

def get_order(order_id: str, patron_id: str = None) -> dict:
    headers = make_patron_headers(patron_id) if patron_id else ADMIN
    return get_success_data(api_client.get_order(order_id, headers))


def get_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_slot(slot_id, ADMIN))


def get_membership(membership_id: str, patron_id: str = None) -> dict:
    headers = make_patron_headers(patron_id) if patron_id else ADMIN
    return get_success_data(api_client.get_membership(membership_id, headers))


def list_guest_passes(membership_id: str, status: str = None) -> list:
    params = {"membership_id": membership_id}
    if status:
        params["status"] = status
    return get_success_data(api_client.list_guest_passes(ADMIN, params))


def count_guest_passes(membership_id: str, status: str) -> int:
    """Count guest passes of a membership in a given status, using the list
    endpoint's total_count (covers all pages for these small fixtures)."""
    resp = api_client.list_guest_passes(
        ADMIN, {"membership_id": membership_id, "status": status, "limit": 100}
    )
    body = resp.json()
    return body["meta"]["total_count"]
