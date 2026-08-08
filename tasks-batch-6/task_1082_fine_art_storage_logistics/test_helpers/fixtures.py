"""Composite setup helpers.

Each helper builds a multi-step precondition state from scratch using only
PRD-declared endpoints, so tests can focus on assertions. The harness restarts
the server (empty DB, clock at 2026-05-01T00:00:00Z) before every test.

All setup calls use get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion error deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers
from .api_client import api_client as api
from . import factories as F

# Opaque operator role headers used throughout setup.
REG = build_user_headers("op-reg-1", "Registrar")
COORD = build_user_headers("op-coord-1", "Coordinator")
APPR = build_user_headers("op-appr-1", "Approver")
BILL = build_user_headers("op-bill-1", "BillingAdmin")


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------
def set_clock(iso="2026-05-01T00:00:00Z"):
    return get_success_data(api.set_clock(iso, REG))


def make_client(**overrides):
    return get_success_data(api.create_client(F.client_payload(**overrides), REG))


def make_vault(**overrides):
    return get_success_data(api.create_vault(F.vault_payload(**overrides), REG))


def make_artwork(client_id, **overrides):
    return get_success_data(api.create_artwork(F.artwork_payload(client_id, **overrides), REG))


def artwork_version(artwork_id):
    return get_success_data(api.get_artwork(artwork_id, REG))["version"]


def make_appraisal(artwork_id, **overrides):
    v = artwork_version(artwork_id)
    return get_success_data(api.create_appraisal(F.appraisal_payload(artwork_id, v, **overrides), REG))


def make_policy(artwork_id, **overrides):
    v = artwork_version(artwork_id)
    return get_success_data(api.create_policy(F.policy_payload(artwork_id, v, **overrides), REG))


def make_placement(artwork_id, vault_id, **overrides):
    return get_success_data(api.create_placement(F.placement_payload(artwork_id, vault_id, **overrides), REG))


def make_crate(artwork_id, ready=False, **overrides):
    c = get_success_data(api.create_crate(F.crate_payload(artwork_id, **overrides), COORD))
    if ready:
        c = get_success_data(api.transition_crate(c["id"], {"to_status": "READY"}, COORD))
    return c


def make_crew(**overrides):
    return get_success_data(api.create_crew(F.crew_payload(**overrides), COORD))


def make_viewing_room(**overrides):
    return get_success_data(api.create_viewing_room(F.viewing_room_payload(**overrides), COORD))


def make_loan(artwork_id, client_id, **overrides):
    return get_success_data(api.create_loan(F.loan_payload(artwork_id, client_id, **overrides), REG))


# --------------------------------------------------------------------------
# Tier 2/3: entity hierarchies and lifecycle shortcuts
# --------------------------------------------------------------------------
def setup_placed_artwork(vault_capacity=5, climate="AMBIENT", size="MEDIUM",
                         fragility="MEDIUM", start="2026-05-01T00:00:00Z",
                         scheduled_end="2026-06-01T00:00:00Z"):
    """Active parent + vault + artwork placed ACTIVE (custody IN_STORAGE).

    Returns dict with client, vault, artwork, placement.
    """
    c = make_client()
    v = make_vault(climate_class=climate, capacity_slots=vault_capacity)
    a = make_artwork(c["id"], size_class=size, fragility_class=fragility, climate_class=climate)
    p = make_placement(a["id"], v["id"], start_at=start, scheduled_end_at=scheduled_end)
    return {"client": c, "vault": v, "artwork": a, "placement": p}


def setup_ready_transport(requires_rigging=False, estimated_hours=2,
                          scheduled_start="2026-06-01T09:00:00Z",
                          scheduled_end="2026-06-01T11:00:00Z", place_artwork=True):
    """Artwork (optionally placed IN_STORAGE), READY crate, crew, SCHEDULED job.

    When place_artwork is False the artwork stays IN_INTAKE (never placed).
    Returns dict with client, vault, artwork, crate, crew, job.
    """
    c = make_client()
    v = make_vault(capacity_slots=3)
    a = make_artwork(c["id"])
    placement = None
    if place_artwork:
        placement = make_placement(a["id"], v["id"])
    crate = make_crate(a["id"], ready=True)
    crew = make_crew()
    job = get_success_data(api.create_transport_job(
        F.transport_job_payload(
            a["id"], crate["id"], crew["id"],
            requires_rigging=requires_rigging, estimated_hours=estimated_hours,
            scheduled_start=scheduled_start, scheduled_end=scheduled_end),
        COORD))
    return {"client": c, "vault": v, "artwork": a, "placement": placement,
            "crate": crate, "crew": crew, "job": job}


def setup_submitted_loan(placed=True, with_appraisal=True, with_policy=True,
                         insured=1000000, required=1000000, coverage="ALL_RISK",
                         is_international=False, submitter_id="op-reg-1"):
    """Draft -> SUBMITTED loan with configurable preconditions.

    Returns dict with client, vault, artwork, placement, appraisal, policy, loan.
    submitter records submitted_by_user_id = submitter_id (a Registrar).
    """
    set_clock()
    c = make_client()
    v = make_vault(capacity_slots=3)
    a = make_artwork(c["id"])
    placement = make_placement(a["id"], v["id"]) if placed else None
    appraisal = make_appraisal(a["id"]) if with_appraisal else None
    policy = make_policy(a["id"], coverage_type=coverage, insured_value_cents=insured) if with_policy else None
    loan = make_loan(a["id"], c["id"], is_international=is_international,
                     required_value_cents=required,
                     loan_start="2026-05-10T00:00:00Z", loan_end="2026-06-10T00:00:00Z")
    get_success_data(api.transition_loan(
        loan["id"], {"to_status": "SUBMITTED"}, build_user_headers(submitter_id, "Registrar")))
    return {"client": c, "vault": v, "artwork": a, "placement": placement,
            "appraisal": appraisal, "policy": policy, "loan": loan}


def setup_approved_loan(is_international=False, with_carnet=False, insured=1000000,
                        required=1000000, coverage="ALL_RISK",
                        submitter_id="op-reg-1", approver_id="op-appr-1"):
    """Loan taken to APPROVED. Optionally issues an ISSUED carnet before approval.

    Returns dict incl. loan (APPROVED) and carnet (if requested).
    """
    s = setup_submitted_loan(placed=True, with_appraisal=True, with_policy=True,
                             insured=insured, required=required, coverage=coverage,
                             is_international=is_international, submitter_id=submitter_id)
    carnet = None
    if with_carnet:
        carnet = get_success_data(api.create_carnet(F.carnet_payload(s["loan"]["id"]), COORD))
    get_success_data(api.transition_loan(
        s["loan"]["id"], {"to_status": "APPROVED"}, build_user_headers(approver_id, "Approver")))
    s["carnet"] = carnet
    return s


def setup_active_international_loan():
    """International loan driven all the way to ACTIVE: artwork ON_LOAN, its
    placement SUSPENDED, vault.occupied_slots 0, carnet ACTIVATED.

    Returns dict with client, vault, artwork, placement, loan, carnet.
    """
    s = setup_approved_loan(is_international=True, with_carnet=True)
    get_success_data(api.transition_loan(s["loan"]["id"], {"to_status": "ACTIVE"}, COORD))
    return s


# --------------------------------------------------------------------------
# Viewing-room scenarios
# --------------------------------------------------------------------------
def setup_confirmed_booking(room_id, client_id, artwork_id,
                            start="2026-05-02T14:00:00Z", end="2026-05-02T15:00:00Z"):
    """Create a REQUESTED booking on room and confirm it. Returns the booking."""
    b = get_success_data(api.create_viewing_booking(
        F.viewing_booking_payload(artwork_id, room_id, client_id,
                                  scheduled_start=start, scheduled_end=end), COORD))
    return get_success_data(api.transition_viewing_booking(b["id"], {"to_status": "CONFIRMED"}, COORD))


def setup_two_bookings(second_start, second_end, damage_second=False):
    """Room OPERATIONAL; artwork A1 booked+CONFIRMED 14:00-15:00; artwork A2
    booked REQUESTED over [second_start, second_end). If damage_second, drive A2
    to MAJOR_DAMAGE first.

    Returns dict with client, room, a1, a2, b1 (CONFIRMED), b2 (REQUESTED).
    """
    c = make_client()
    room = make_viewing_room()
    a1 = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW")
    a2 = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW")
    if damage_second:
        get_success_data(api.create_condition_report(
            F.condition_report_payload(a2["id"], report_type="PERIODIC",
                                       condition_grade="F", damage_noted=True,
                                       notes="torn canvas"), REG))
    b1 = setup_confirmed_booking(room["id"], c["id"], a1["id"])
    b2 = get_success_data(api.create_viewing_booking(
        F.viewing_booking_payload(a2["id"], room["id"], c["id"],
                                  scheduled_start=second_start, scheduled_end=second_end), COORD))
    return {"client": c, "room": room, "a1": a1, "a2": a2, "b1": b1, "b2": b2}


# --------------------------------------------------------------------------
# Crew temporal-overlap scenario
# --------------------------------------------------------------------------
def setup_crew_with_scheduled_job(job1_start="2026-06-01T09:00:00Z",
                                  job1_end="2026-06-01T11:00:00Z"):
    """One crew; two artworks and READY crates; job1 scheduled on the crew.

    Returns dict with crew, a2, crate2, job1 for a second scheduling attempt.
    """
    c = make_client()
    a1 = make_artwork(c["id"], size_class="LARGE", fragility_class="HIGH")
    a2 = make_artwork(c["id"], size_class="LARGE", fragility_class="HIGH")
    crate1 = make_crate(a1["id"], crate_type="CLIMATE")
    crate2 = make_crate(a2["id"], crate_type="CLIMATE")
    crew = make_crew(certification_level="MONUMENTAL", crew_size=4)
    job1 = get_success_data(api.create_transport_job(
        F.transport_job_payload(a1["id"], crate1["id"], crew["id"],
                                requires_rigging=True, estimated_hours=2,
                                scheduled_start=job1_start, scheduled_end=job1_end), COORD))
    return {"client": c, "a2": a2, "crate2": crate2, "crew": crew, "job1": job1}


# --------------------------------------------------------------------------
# Billing scenario
# --------------------------------------------------------------------------
def setup_issued_invoice(line_amount=10000):
    """Client with a single-manual-line invoice issued (moves to ISSUED).

    Returns dict with client and invoice.
    """
    c = make_client()
    inv = get_success_data(api.create_invoice(
        F.invoice_payload(c["id"],
                          manual_line_items=[{"description": "Storage", "amount_cents": line_amount}]),
        BILL))
    inv = get_success_data(api.transition_invoice(inv["id"], {"to_status": "ISSUED"}, BILL))
    return {"client": c, "invoice": inv}
