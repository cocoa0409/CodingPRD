"""Composite setup helpers for multi-step test prerequisites.

All helpers use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.
Every helper builds state from scratch against an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    make_pilot_payload, make_endorsement_payload, make_order_payload,
    make_boat_payload, make_tariff_schedule_payload, make_dispatch_payload,
    make_completion_payload, make_incident_payload, make_apprentice_payload,
    make_record_progress_payload, make_distribution_run_payload,
)
from .test_users import TEST_USERS, make_pilot_headers, make_agent_headers

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
FINANCE = TEST_USERS["finance_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]


# ─── Atomic builders ────────────────────────────────────────────────────────

def create_main_tariff(**overrides):
    """Publish the standard three-tier schedule (effective 2026-01-01)."""
    res = api_client.create_tariff_schedule(make_tariff_schedule_payload(**overrides), ADMIN)
    return get_success_data(res)


def set_clock(to_iso8601: str):
    res = api_client.set_logical_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(res)


def register_pilot(full_name="Pilot One", license_number="LIC-1", share_units=1):
    res = api_client.create_pilot(
        make_pilot_payload(full_name=full_name, license_number=license_number,
                           share_units=share_units), ADMIN)
    return get_success_data(res)


def issue_endorsement(pilot_id, endorsement_class="UNLIMITED", tonnage_cap_gt=100000,
                      expires_at="2027-01-01T00:00:00Z"):
    """Issue an endorsement with a fresh OCC version read (PRD §2.7)."""
    pilot = get_success_data(api_client.get_pilot(pilot_id, ADMIN))
    payload = make_endorsement_payload(
        endorsement_class=endorsement_class, tonnage_cap_gt=tonnage_cap_gt,
        expires_at=expires_at, expected_pilot_version=pilot["version"])
    res = api_client.create_endorsement(pilot_id, payload, ADMIN)
    return get_success_data(res)


def register_endorsed_pilot(full_name="Pilot One", license_number="LIC-1", share_units=1,
                            endorsement_class="UNLIMITED", tonnage_cap_gt=100000,
                            expires_at="2027-01-01T00:00:00Z"):
    """Pilot + one endorsement; returns the pilot dict."""
    pilot = register_pilot(full_name, license_number, share_units)
    issue_endorsement(pilot["id"], endorsement_class, tonnage_cap_gt, expires_at)
    return pilot


def register_boat(name="Boat A", capacity_persons=6):
    res = api_client.create_boat(
        make_boat_payload(name=name, capacity_persons=capacity_persons), ADMIN)
    return get_success_data(res)


def place_order(agent_id="agent-1", vessel_name="MV One", gt=8000, draft_dm=90,
                order_type="ARRIVAL", eta="2026-08-10T00:00:00Z"):
    res = api_client.create_order(
        make_order_payload(vessel_name=vessel_name, gt=gt, draft_dm=draft_dm,
                           order_type=order_type, eta=eta),
        make_agent_headers(agent_id))
    return get_success_data(res)


def dispatch(order_id, scheduled_start="2026-08-10T10:00:00Z",
             scheduled_end="2026-08-10T11:00:00Z", boat_id=None, apprentice_id=None):
    payload = make_dispatch_payload(scheduled_start, scheduled_end)
    if boat_id is not None:
        payload["boat_id"] = boat_id
    if apprentice_id is not None:
        payload["apprentice_id"] = apprentice_id
    res = api_client.dispatch_order(order_id, payload, DISPATCHER)
    return get_success_data(res)


def launch(assignment):
    """ASSIGNED -> EN_ROUTE as the assignment's own pilot."""
    res = api_client.start_assignment(
        assignment["id"], make_pilot_headers(assignment["pilot_id"]))
    return get_success_data(res)


def board(assignment):
    """EN_ROUTE -> ABOARD as the assignment's own pilot."""
    res = api_client.board_assignment(
        assignment["id"], make_pilot_headers(assignment["pilot_id"]))
    return get_success_data(res)


def complete(assignment, detention_minutes=0, delay_minutes=0):
    """ABOARD -> COMPLETED as the assignment's own pilot."""
    res = api_client.complete_assignment(
        assignment["id"], make_completion_payload(detention_minutes, delay_minutes),
        make_pilot_headers(assignment["pilot_id"]))
    return get_success_data(res)


def recall(assignment_id):
    return get_success_data(api_client.recall_assignment(assignment_id, DISPATCHER))


def cancel_assignment(assignment_id):
    return get_success_data(api_client.cancel_assignment(assignment_id, DISPATCHER))


def get_pilot_fresh(pilot_id):
    return get_success_data(api_client.get_pilot(pilot_id, DISPATCHER))


def get_order_fresh(order_id):
    return get_success_data(api_client.get_order(order_id, DISPATCHER))


def get_assignment_fresh(assignment_id):
    return get_success_data(api_client.get_assignment(assignment_id, DISPATCHER))


def rotation_entry_of(pilot_id):
    """The pilot's single rotation entry (array of 0-1 per PRD §3.1)."""
    data, _meta = _list(api_client.list_pilot_rotation_entries(pilot_id, DISPATCHER))
    assert len(data) == 1, f"expected exactly one rotation entry for pilot {pilot_id}"
    return data[0]


def invoice_of_assignment(assignment_id):
    data, _meta = _list(api_client.list_invoices(FINANCE, params={"assignment_id": assignment_id}))
    assert len(data) == 1, f"expected exactly one invoice for assignment {assignment_id}"
    return data[0]


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


# ─── Composite scenarios ────────────────────────────────────────────────────

def setup_assigned_scenario(gt=8000, draft_dm=90, eta="2026-08-10T00:00:00Z",
                            order_type="ARRIVAL", vessel_name="MV One",
                            scheduled_start="2026-08-10T10:00:00Z",
                            scheduled_end="2026-08-10T11:00:00Z",
                            pilot_cap=100000, boat_name="Boat A", agent_id="agent-1",
                            pilot_name="Pilot One", license_number="LIC-1",
                            share_units=1):
    """Tariff + endorsed pilot + boat + order + dispatch. Returns the pieces."""
    create_main_tariff()
    pilot = register_endorsed_pilot(pilot_name, license_number, share_units,
                                    tonnage_cap_gt=pilot_cap)
    boat = register_boat(boat_name)
    order = place_order(agent_id, vessel_name, gt, draft_dm, order_type, eta)
    assignment = dispatch(order["id"], scheduled_start, scheduled_end)
    return {"pilot": pilot, "boat": boat, "order": order, "assignment": assignment}


def setup_aboard_scenario(**kwargs):
    """Assigned scenario walked through start + board."""
    ctx = setup_assigned_scenario(**kwargs)
    ctx["assignment"] = launch(ctx["assignment"])
    ctx["assignment"] = board(ctx["assignment"])
    return ctx


def setup_completed_scenario(detention_minutes=0, delay_minutes=0, **kwargs):
    """Full lifecycle through completion; returns pieces incl. the minted invoice."""
    ctx = setup_aboard_scenario(**kwargs)
    ctx["assignment"] = complete(ctx["assignment"], detention_minutes, delay_minutes)
    ctx["invoice"] = invoice_of_assignment(ctx["assignment"]["id"])
    return ctx


def setup_two_pilots(cap1=100000, cap2=100000, class1="UNLIMITED", class2="UNLIMITED",
                     expiry1="2027-01-01T00:00:00Z", expiry2="2027-01-01T00:00:00Z",
                     share_units1=1, share_units2=1):
    """Two endorsed pilots: P1 boards at position 1, P2 at position 2."""
    p1 = register_endorsed_pilot("Pilot One", "LIC-1", share_units1, class1, cap1, expiry1)
    p2 = register_endorsed_pilot("Pilot Two", "LIC-2", share_units2, class2, cap2, expiry2)
    return p1, p2


def setup_recalled_assignment(second_pilot_cap=5000, second_pilot_class="HARBOR",
                              order_gt=8000, window=("2026-08-11T10:00:00Z",
                                                     "2026-08-11T11:00:00Z"),
                              first_window=("2026-08-10T10:00:00Z",
                                            "2026-08-10T12:00:00Z")):
    """A1 held by P1; A2 (on its own boat) dispatched to P2 and recalled.

    Returns dict with pilots, boats, orders, a1, a2 (a2 is RECALLED).
    """
    create_main_tariff()
    p1, p2 = setup_two_pilots(cap1=100000, cap2=second_pilot_cap,
                              class2=second_pilot_class)
    boat_a = register_boat("Boat A")
    boat_b = register_boat("Boat B")
    o1 = place_order(vessel_name="MV One", gt=8000, draft_dm=90,
                     order_type="ARRIVAL", eta="2026-08-10T00:00:00Z")
    a1 = dispatch(o1["id"], first_window[0], first_window[1])
    o2 = place_order(vessel_name="MV Two", gt=order_gt, draft_dm=90,
                     order_type="DEPARTURE", eta="2026-08-11T00:00:00Z")
    a2 = dispatch(o2["id"], window[0], window[1], boat_id=boat_b["id"])
    a2 = recall(a2["id"])
    return {"p1": p1, "p2": p2, "boat_a": boat_a, "boat_b": boat_b,
            "o1": o1, "o2": o2, "a1": a1, "a2": a2}


def setup_finalized_invoice(gt=8000, draft_dm=90, detention_minutes=0,
                            delay_minutes=0, share_units=1, **kwargs):
    """Completed assignment + its invoice FINALIZED at the current clock."""
    ctx = setup_completed_scenario(detention_minutes, delay_minutes,
                                   gt=gt, draft_dm=draft_dm, share_units=share_units,
                                   **kwargs)
    invoice = ctx["invoice"]
    res = api_client.finalize_invoice(invoice["id"], FINANCE)
    ctx["invoice"] = get_success_data(res)
    return ctx
