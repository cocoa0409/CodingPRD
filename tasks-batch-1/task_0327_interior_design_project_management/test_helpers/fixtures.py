"""Composite setup helpers for multi-step test prerequisites (Interior Design PM API).

Every test runs against a freshly restarted, empty server, so each fixture builds
all of its preconditions from scratch using only PRD-declared endpoints.

Setup calls use get_success_data() (lenient) so a setup break surfaces as a clear
"Setup failed" rather than a confusing assertion failure deep in a test.

Identity threading: the Client role is entity_backed. After a fixture creates a
Client, every ownership-gated Client call (room approve, revision submit, punch
waive, ...) uses make_client_headers(client["id"]) — never the shared constant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_client_payload,
    create_project_payload,
    create_room_payload,
    create_moodboard_payload,
    create_ffe_item_payload,
    create_selection_payload,
    create_vendor_payload,
    create_order_payload,
    add_order_line_payload,
    create_payment_payload,
)
from .test_users import TEST_USERS, make_client_headers

ADMIN = TEST_USERS["studio_admin_headers"]
DESIGNER = TEST_USERS["designer_headers"]
PC = TEST_USERS["procurement_coordinator_headers"]

# Monotonic counters so repeated fixture calls within a single test produce
# unique email / sku values (uniqueness is enforced by the API).
_email_seq = itertools.count(1)
_sku_seq = itertools.count(1)


def unique_email(prefix="client") -> str:
    return f"{prefix}-{next(_email_seq)}@example.com"


def unique_sku(prefix="FFE") -> str:
    return f"{prefix}-{next(_sku_seq):05d}"


# ─── Tier 0: primitive creators ──────────────────────────────────────────────
def create_client(display_name="Acme Residence", email=None):
    """Register a Client. Returns the Client record."""
    payload = create_client_payload(
        display_name=display_name, email=email or unique_email()
    )
    return get_success_data(api_client.create_client(payload, ADMIN))


def create_project(client_id, **overrides):
    """Create a Project owned by client_id. Returns the Project record (status BRIEFING)."""
    payload = create_project_payload(client_id, **overrides)
    return get_success_data(api_client.create_project(payload, ADMIN))


def create_vendor(name="Heritage Supply Co.", **overrides):
    """Register a vendor. Returns the Vendor record."""
    payload = create_vendor_payload(name=name, **overrides)
    return get_success_data(api_client.create_vendor(payload, PC))


def create_ffe_item(**overrides):
    """Add a catalog FF&E item with a unique sku unless one is supplied."""
    if "sku" not in overrides:
        overrides["sku"] = unique_sku()
    payload = create_ffe_item_payload(**overrides)
    return get_success_data(api_client.create_ffe_item(payload, ADMIN))


def create_room(project_id, **overrides):
    """Add a room to a project (status SCOPING)."""
    payload = create_room_payload(**overrides)
    return get_success_data(api_client.create_room(project_id, payload, DESIGNER))


def project_version(project_id) -> int:
    """Read the project's current version (for OCC writes)."""
    proj = get_success_data(api_client.get_project(project_id, ADMIN))
    return proj["version"]


# ─── Tier 1: rooms & mood boards ─────────────────────────────────────────────
def create_room_with_presented_moodboard(project_id, room_name="Primary Bedroom"):
    """Room with one PRESENTED mood board, advanced to MOODBOARD_READY.
    Returns (room, moodboard)."""
    room = create_room(project_id, name=room_name)
    mb = get_success_data(
        api_client.create_moodboard(room["id"], create_moodboard_payload(), DESIGNER)
    )
    get_success_data(api_client.present_moodboard(mb["id"], DESIGNER))
    get_success_data(api_client.present_moodboard_room(room["id"], DESIGNER))
    return room, mb


def create_approved_room(project_id, client_id, room_name="Primary Bedroom"):
    """Room driven to APPROVED with one ACCEPTED mood board.
    Returns (room, moodboard). Approval is an ownership-gated Client action."""
    room, mb = create_room_with_presented_moodboard(project_id, room_name=room_name)
    get_success_data(api_client.approve_room(room["id"], make_client_headers(client_id)))
    room = get_success_data(api_client.get_room(room["id"], ADMIN))
    mb = get_success_data(api_client.get_moodboard(mb["id"], ADMIN))
    return room, mb


# ─── Tier 2: project with an approved room (the common base scenario) ─────────
def setup_project_with_approved_room(fee_overrides=None, room_name="Primary Bedroom"):
    """Client + Project (FLAT by default) + one APPROVED room + ACTIVE vendor.

    Returns dict: client, project, room, moodboard, vendor.
    Pass fee_overrides to choose a fee model, e.g. {"fee_model": "HOURLY", "hourly_rate_cents": 15000}.
    """
    fee_overrides = fee_overrides or {}
    client = create_client()
    project = create_project(client["id"], **fee_overrides)
    vendor = create_vendor()
    room, mb = create_approved_room(project["id"], client["id"], room_name=room_name)
    return {
        "client": client,
        "project": project,
        "room": room,
        "moodboard": mb,
        "vendor": vendor,
    }


# ─── Tier 3: selections ──────────────────────────────────────────────────────
def create_specified_selection(project_id, room_id, ffe_item_id, **sel_overrides):
    """Create a selection and move it to SPECIFIED (room must already be APPROVED).
    Returns the SPECIFIED selection record."""
    sel = get_success_data(
        api_client.create_selection(
            project_id, create_selection_payload(room_id, ffe_item_id, **sel_overrides), DESIGNER
        )
    )
    get_success_data(api_client.specify_selection(sel["id"], DESIGNER))
    return get_success_data(api_client.get_selection(sel["id"], ADMIN))


# ─── Tier 4: orders (DRAFT, with lines, and placed) ──────────────────────────
def create_draft_order_with_lines(project_id, vendor_id, selection_ids,
                                  window_start="2026-07-01T00:00:00Z",
                                  window_end="2026-07-02T00:00:00Z"):
    """Open a DRAFT order on vendor_id and attach each selection as a line.
    Returns the order record (still DRAFT)."""
    order = get_success_data(
        api_client.create_order(
            project_id,
            create_order_payload(vendor_id, window_start=window_start, window_end=window_end),
            PC,
        )
    )
    for sid in selection_ids:
        get_success_data(api_client.add_order_line(order["id"], add_order_line_payload(sid), PC))
    return get_success_data(api_client.get_order(order["id"], ADMIN))


def place_order(project_id, order_id):
    """Place a DRAFT order against the project's current version. Returns the ORDERED order."""
    pv = project_version(project_id)
    get_success_data(
        api_client.place_order(order_id, {"expected_project_version": pv}, PC)
    )
    return get_success_data(api_client.get_order(order_id, ADMIN))


def create_placed_order(project_id, vendor_id, selection_ids,
                        window_start="2026-07-01T00:00:00Z",
                        window_end="2026-07-02T00:00:00Z"):
    """Open + line + place an order in one shot. Returns the ORDERED order record."""
    order = create_draft_order_with_lines(
        project_id, vendor_id, selection_ids, window_start, window_end
    )
    return place_order(project_id, order["id"])


def create_delivered_order(project_id, vendor_id, selection_ids,
                           window_start="2026-07-01T00:00:00Z",
                           window_end="2026-07-02T00:00:00Z"):
    """Place → ship → deliver an order. Returns the DELIVERED order record."""
    order = create_placed_order(project_id, vendor_id, selection_ids, window_start, window_end)
    get_success_data(api_client.ship_order(order["id"], PC))
    get_success_data(api_client.deliver_order(order["id"], PC))
    return get_success_data(api_client.get_order(order["id"], ADMIN))


# ─── Tier 5: end-to-end scenario shortcuts used by difficulty instances ───────
def setup_single_selection_order(fee_overrides=None,
                                 ffe_overrides=None,
                                 sel_overrides=None):
    """Project (FLAT default) + approved room + one DELIVERED order carrying one
    selection. Returns dict with client, project, room, vendor, ffe, selection, order.

    Mirrors the dominant difficulty/corner preamble (transitive_cascade order-return,
    compensating_invariant, etc.)."""
    ffe_overrides = ffe_overrides or {}
    sel_overrides = sel_overrides or {}
    base = setup_project_with_approved_room(fee_overrides=fee_overrides)
    ffe = create_ffe_item(**ffe_overrides)
    sel = create_specified_selection(
        base["project"]["id"], base["room"]["id"], ffe["id"], **sel_overrides
    )
    return {**base, "ffe": ffe, "selection": sel}


def add_deposit(project_id, amount_cents, received_at="2026-07-05T00:00:00Z"):
    """Record a client deposit against the project's current version.
    Returns the PaymentReceipt record."""
    pv = project_version(project_id)
    return get_success_data(
        api_client.create_payment(
            project_id, create_payment_payload(amount_cents, pv, received_at=received_at), ADMIN
        )
    )


# ─── Convenience: advance a project through its lifecycle ─────────────────────
def advance_project_to(project_id, target_status, actor=None):
    """Advance the project one hop to target_status. Returns the updated project."""
    actor = actor or DESIGNER
    return get_success_data(
        api_client.advance_project(project_id, {"to": target_status}, actor)
    )
