"""Composite setup helpers.

These encapsulate the multi-step API sequences needed to drive the system into
the states that interesting tests assert against. Every setup call uses the
lenient get_success_data() validator so setup failures surface as clear
"Setup failed" errors rather than confusing downstream assertion mismatches.

The test harness kills and relaunches the server (empty DB) before every test,
so each helper builds all of its preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import make_coordinator_headers, make_sitter_headers
from . import factories as f

COORD = make_coordinator_headers()


# ---------------------------------------------------------------------------
# Low-level building blocks
# ---------------------------------------------------------------------------

def set_clock(api, iso, headers=COORD):
    return get_success_data(api.set_clock(iso, headers))


def create_client(api, **overrides):
    return get_success_data(api.create_client(f.create_client_payload(**overrides), COORD))


def create_property(api, client_id, **overrides):
    return get_success_data(
        api.create_property(f.create_property_payload(client_id, **overrides), COORD))


def create_sitter(api, **overrides):
    return get_success_data(api.create_sitter(f.create_sitter_payload(**overrides), COORD))


def get_sitter(api, sitter_id):
    return get_success_data(api.get_sitter(sitter_id, COORD))


def get_property(api, property_id):
    return get_success_data(api.get_property(property_id, COORD))


def get_booking(api, booking_id):
    return get_success_data(api.get_booking(booking_id, COORD))


def get_visit(api, visit_id):
    return get_success_data(api.get_visit(visit_id, COORD))


def get_incident(api, incident_id):
    return get_success_data(api.get_incident(incident_id, COORD))


def get_key_assignment(api, key_id):
    return get_success_data(api.get_key_assignment(key_id, COORD))


def get_coverage_policy(api, policy_id):
    return get_success_data(api.get_coverage_policy(policy_id, COORD))


def submit_background_check(api, sitter_id, **overrides):
    return get_success_data(
        api.create_background_check(f.create_background_check_payload(sitter_id, **overrides), COORD))


def clear_background_check(api, bgcheck_id, decision="CLEARED"):
    return get_success_data(
        api.decide_background_check(bgcheck_id, f.decide_payload(decision), COORD))


def issue_policy(api, sitter_id, policy_type="BOND", **overrides):
    """Fetch the sitter's live version and issue a coverage policy against it."""
    version = get_sitter(api, sitter_id)["version"]
    payload = f.create_coverage_policy_payload(sitter_id, version, policy_type=policy_type, **overrides)
    return get_success_data(api.create_coverage_policy(payload, COORD))


def onboard_cleared_bonded_sitter(api, bond_coverage=1000000, **sitter_overrides):
    """Create a sitter, submit + clear a background check, and issue an ACTIVE BOND.
    Returns the sitter as re-fetched after all mutations (status ACTIVE)."""
    sitter = create_sitter(api, **sitter_overrides)
    bg = submit_background_check(api, sitter["id"])
    clear_background_check(api, bg["id"])
    issue_policy(api, sitter["id"], policy_type="BOND", coverage_amount_cents=bond_coverage)
    return get_sitter(api, sitter["id"])


def add_liability_policy(api, sitter_id, coverage_amount_cents):
    return issue_policy(api, sitter_id, policy_type="LIABILITY",
                        coverage_amount_cents=coverage_amount_cents)


def create_booking(api, property_id, **overrides):
    return get_success_data(
        api.create_booking(f.create_booking_payload(property_id, **overrides), COORD))


def submit_booking(api, booking_id):
    return get_success_data(api.submit_booking(booking_id, COORD))


def assign_booking(api, booking_id, sitter_id):
    return get_success_data(
        api.assign_booking(booking_id, {"sitter_id": sitter_id}, COORD))


def create_and_checkout_key(api, property_id, sitter_id, booking_id):
    key = get_success_data(
        api.create_key_assignment(
            f.create_key_assignment_payload(property_id, sitter_id, booking_id), COORD))
    get_success_data(api.check_out_key(key["id"], COORD))
    return get_key_assignment(api, key["id"])


def activate_booking(api, booking_id):
    return get_success_data(api.activate_booking(booking_id, COORD))


def list_visits(api, booking_id):
    resp = api.list_visits(COORD, params={"booking_id": booking_id})
    body = resp.json()
    return body["data"]


def invoice_for_booking(api, booking_id):
    resp = api.list_invoices(COORD, params={"booking_id": booking_id})
    body = resp.json()
    data = body["data"]
    return data[0] if data else None


def add_photo_log(api, visit_id, sitter_id, captured_at="2026-06-01T09:06:00Z"):
    return get_success_data(
        api.create_visit_log(
            f.create_visit_log_payload(visit_id, entry_type="PHOTO", captured_at=captured_at),
            make_sitter_headers(sitter_id)))


def perform_checkin(api, visit_id, sitter_id, clock=None, gps_lat=40.0, gps_lng=-70.0):
    if clock is not None:
        set_clock(api, clock)
    return get_success_data(
        api.check_in_visit(visit_id, f.check_in_payload(gps_lat, gps_lng),
                           make_sitter_headers(sitter_id)))


def perform_checkout(api, visit_id, sitter_id, completed_tasks=None, clock=None):
    if clock is not None:
        set_clock(api, clock)
    return get_success_data(
        api.check_out_visit(visit_id, f.check_out_payload(completed_tasks),
                            make_sitter_headers(sitter_id)))


# ---------------------------------------------------------------------------
# Tier 2/3: hierarchies and lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_active_booking(api, *, property_overrides=None, booking_overrides=None,
                         bond_coverage=1000000, initial_clock="2026-05-01T00:00:00Z",
                         with_liability=None):
    """Active booking ready to run visits.

    Chain: set clock -> client -> property -> cleared+bonded sitter ->
    (optional LIABILITY policy) -> booking -> submit -> assign -> key checkout ->
    activate. Returns dict with client, property, sitter, booking, key, invoice, visits.

    `with_liability` (int coverage) adds an ACTIVE LIABILITY policy before booking.
    """
    set_clock(api, initial_clock)
    client = create_client(api)
    prop = create_property(api, client["id"], **(property_overrides or {}))
    sitter = onboard_cleared_bonded_sitter(api, bond_coverage=bond_coverage)
    if with_liability is not None:
        add_liability_policy(api, sitter["id"], with_liability)
        sitter = get_sitter(api, sitter["id"])
    booking = create_booking(api, prop["id"], **(booking_overrides or {}))
    submit_booking(api, booking["id"])
    assign_booking(api, booking["id"], sitter["id"])
    key = create_and_checkout_key(api, prop["id"], sitter["id"], booking["id"])
    activate_booking(api, booking["id"])
    visits = list_visits(api, booking["id"])
    invoice = invoice_for_booking(api, booking["id"])
    return {
        "client": client, "property": prop, "sitter": sitter,
        "booking": booking, "key": key, "invoice": invoice, "visits": visits,
    }


def setup_scheduled_booking(api, *, property_overrides=None, booking_overrides=None,
                            bond_coverage=1000000, initial_clock="2026-05-01T00:00:00Z"):
    """Booking assigned (SCHEDULED) with visits generated and a DRAFT invoice, but
    NOT activated (no key checked out, no active state). Returns client/property/
    sitter/booking/invoice/visits."""
    set_clock(api, initial_clock)
    client = create_client(api)
    prop = create_property(api, client["id"], **(property_overrides or {}))
    sitter = onboard_cleared_bonded_sitter(api, bond_coverage=bond_coverage)
    booking = create_booking(api, prop["id"], **(booking_overrides or {}))
    submit_booking(api, booking["id"])
    assign_booking(api, booking["id"], sitter["id"])
    visits = list_visits(api, booking["id"])
    invoice = invoice_for_booking(api, booking["id"])
    return {
        "client": client, "property": prop, "sitter": sitter,
        "booking": booking, "invoice": invoice, "visits": visits,
    }


def setup_pending_booking(api, *, property_overrides=None, booking_overrides=None,
                          initial_clock="2026-05-01T00:00:00Z", onboard_sitter=True,
                          bond_coverage=1000000, cleared=True, bonded=True):
    """Booking submitted (PENDING_ASSIGNMENT). A sitter may optionally be onboarded
    with configurable clearance/bond so assign-time guard tests can be built."""
    set_clock(api, initial_clock)
    client = create_client(api)
    prop = create_property(api, client["id"], **(property_overrides or {}))
    sitter = None
    if onboard_sitter:
        sitter = create_sitter(api)
        bg = submit_background_check(api, sitter["id"])
        if cleared:
            clear_background_check(api, bg["id"])
        if bonded:
            issue_policy(api, sitter["id"], policy_type="BOND", coverage_amount_cents=bond_coverage)
        sitter = get_sitter(api, sitter["id"])
    booking = create_booking(api, prop["id"], **(booking_overrides or {}))
    submit_booking(api, booking["id"])
    return {"client": client, "property": prop, "sitter": sitter, "booking": booking}


def setup_in_progress_visit(api, *, property_overrides=None, booking_overrides=None,
                            checkin_clock="2026-06-01T09:00:00Z", gps_lat=40.0, gps_lng=-70.0,
                            add_log=True, with_liability=None, bond_coverage=1000000):
    """Active booking whose first visit is IN_PROGRESS (checked in). Optionally
    appends one PHOTO log entry. Returns the setup dict plus 'visit'."""
    ctx = setup_active_booking(api, property_overrides=property_overrides,
                               booking_overrides=booking_overrides,
                               bond_coverage=bond_coverage, with_liability=with_liability)
    visit = ctx["visits"][0]
    perform_checkin(api, visit["id"], ctx["sitter"]["id"], clock=checkin_clock,
                    gps_lat=gps_lat, gps_lng=gps_lng)
    if add_log:
        add_photo_log(api, visit["id"], ctx["sitter"]["id"])
    ctx["visit"] = get_visit(api, visit["id"])
    return ctx


def setup_done_visit(api, *, property_overrides=None, booking_overrides=None,
                     checkin_clock="2026-06-01T09:00:00Z", checkout_clock="2026-06-01T09:30:00Z",
                     completed_tasks=None, bond_coverage=1000000):
    """Active booking whose first visit is DONE (checked in, one photo logged,
    checked out at checkout_clock). Returns the setup dict plus 'visit'."""
    ctx = setup_in_progress_visit(api, property_overrides=property_overrides,
                                  booking_overrides=booking_overrides,
                                  checkin_clock=checkin_clock, add_log=True,
                                  bond_coverage=bond_coverage)
    visit = ctx["visit"]
    perform_checkout(api, visit["id"], ctx["sitter"]["id"],
                     completed_tasks=completed_tasks, clock=checkout_clock)
    ctx["visit"] = get_visit(api, visit["id"])
    ctx["invoice"] = invoice_for_booking(api, ctx["booking"]["id"])
    return ctx


def setup_escalated_incident(api, *, severity="MAJOR", liability_coverage=150000,
                             property_overrides=None, booking_overrides=None,
                             checkin_clock="2026-06-01T09:00:00Z"):
    """Active booking with an IN_PROGRESS visit on which a sitter has filed and a
    coordinator has escalated an incident of the given severity. The sitter holds
    an ACTIVE LIABILITY policy of the given coverage. Returns dict with 'visit',
    'incident', and 'liability_policy'."""
    ctx = setup_active_booking(api, property_overrides=property_overrides,
                               booking_overrides=booking_overrides,
                               with_liability=liability_coverage)
    # capture the liability policy id
    resp = api.list_coverage_policies(COORD, params={"sitter_id": ctx["sitter"]["id"]})
    policies = resp.json()["data"]
    liability = next(p for p in policies if p["policy_type"] == "LIABILITY")
    visit = ctx["visits"][0]
    perform_checkin(api, visit["id"], ctx["sitter"]["id"], clock=checkin_clock)
    incident = get_success_data(
        api.create_incident(
            f.create_incident_payload(visit["id"], category="WATER_LEAK", severity=severity),
            make_sitter_headers(ctx["sitter"]["id"])))
    get_success_data(api.escalate_incident(incident["id"], COORD))
    ctx["visit"] = get_visit(api, visit["id"])
    ctx["incident"] = get_incident(api, incident["id"])
    ctx["liability_policy"] = get_coverage_policy(api, liability["id"])
    return ctx
