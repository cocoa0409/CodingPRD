"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup steps use the lenient validator so a broken
precondition surfaces as a clear "Setup step failed" error.

Identity threading (PRD §2.1): SiteLead / IntakeStaff / OutreachWorker /
MedicalResponder calls that are compared against a staff foreign key always use
per-instance headers built from the real StaffMember.id via the make_*
builders; the shared constants are used only where no identity comparison
applies.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    BREACH_RUN_TIMES,
    DEFAULT_SCHEDULED_END,
    OVERNIGHT_SHIFT_END,
    OVERNIGHT_SHIFT_START,
    SETUP_CLOCK,
)
from .factories import (
    create_donation_payload,
    create_dispatch_payload,
    create_episode_payload,
    create_guest_payload,
    create_incident_payload,
    create_meal_service_payload,
    create_shift_payload,
    create_site_activation_payload,
    create_site_payload,
    create_staff_member_payload,
    create_stay_payload,
    create_vehicle_payload,
    serve_meal_payload,
    weather_reading_payload,
)
from .test_users import (
    TEST_USERS,
    make_eoc_manager_headers,
    make_medical_responder_headers,
    make_outreach_worker_headers,
    make_site_lead_headers,
)

EOC_HEADERS = TEST_USERS["eoc_manager_headers"]
TC_HEADERS = TEST_USERS["transport_coordinator_headers"]
INTAKE_HEADERS = TEST_USERS["intake_staff_headers"]
OUTREACH_HEADERS = TEST_USERS["outreach_worker_headers"]
SITE_LEAD_HEADERS = TEST_USERS["site_lead_headers"]

DISPATCH_WINDOW_START = "2026-08-10T14:00:00Z"
DISPATCH_WINDOW_END = "2026-08-10T15:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: clock and episode primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, EOC_HEADERS))


def create_episode(mode="COOLING", threshold_f=100.0, sustained_hours_required=1,
                   scheduled_end_at=DEFAULT_SCHEDULED_END):
    payload = create_episode_payload(
        mode=mode, threshold_f=threshold_f,
        sustained_hours_required=sustained_hours_required,
        scheduled_end_at=scheduled_end_at)
    return get_success_data(api_client.create_episode(payload, EOC_HEADERS))


def post_weather_reading(episode_id, observed_at, temp_f=95.0, heat_index_f=101.0,
                         source=None):
    payload = weather_reading_payload(observed_at, temp_f=temp_f,
                                      heat_index_f=heat_index_f, source=source)
    return get_success_data(
        api_client.post_weather_reading(episode_id, payload, EOC_HEADERS))


def post_breach_run(episode_id, times=None, temp_f=95.0, heat_index_f=101.0):
    """Post a qualifying breach run: five readings at 15-minute gaps spanning
    exactly 60 minutes (PRD §3.1) at a breaching heat index by default."""
    for t in (times or BREACH_RUN_TIMES):
        post_weather_reading(episode_id, t, temp_f=temp_f, heat_index_f=heat_index_f)


def get_episode(episode_id):
    return get_success_data(api_client.get_episode(episode_id, EOC_HEADERS))


def evaluate_episode(episode_id):
    return get_success_data(api_client.evaluate_episode(episode_id, EOC_HEADERS))


def activate_episode(episode_id, user_id=None):
    headers = make_eoc_manager_headers(user_id) if user_id else EOC_HEADERS
    return get_success_data(api_client.activate_episode(episode_id, headers))


def deactivate_episode(episode_id):
    return get_success_data(api_client.deactivate_episode(episode_id, EOC_HEADERS))


def run_ops(episode_id):
    return get_success_data(api_client.run_ops(episode_id, EOC_HEADERS))


# ---------------------------------------------------------------------------
# Tier 1: sites, activations, staff, shifts
# ---------------------------------------------------------------------------

def create_site(name="Rec Center", address="1 Main St", bed_capacity=4,
                pet_capacity=0, locker_capacity=0):
    payload = create_site_payload(name=name, address=address,
                                  bed_capacity=bed_capacity,
                                  pet_capacity=pet_capacity,
                                  locker_capacity=locker_capacity)
    return get_success_data(api_client.create_site(payload, EOC_HEADERS))


def designate_site(episode_id, site_id, capacity_override=None):
    payload = create_site_activation_payload(site_id, capacity_override)
    return get_success_data(
        api_client.create_site_activation(episode_id, payload, EOC_HEADERS))


def get_site_activation(site_activation_id):
    return get_success_data(
        api_client.get_site_activation(site_activation_id, EOC_HEADERS))


def add_staff_member(full_name, skills, active=None):
    payload = create_staff_member_payload(full_name, skills, active=active)
    return get_success_data(api_client.create_staff_member(payload, EOC_HEADERS))


def plan_shift(site_activation_id, staff_member_id, role_on_shift, start_at, end_at,
               planner_headers=None):
    payload = create_shift_payload(staff_member_id, role_on_shift, start_at, end_at)
    return get_success_data(api_client.create_shift(
        site_activation_id, payload, planner_headers or SITE_LEAD_HEADERS))


def confirm_shift(shift_id, confirmer_headers):
    return get_success_data(api_client.confirm_shift(shift_id, confirmer_headers))


def cancel_shift(shift_id, headers=None):
    return get_success_data(
        api_client.cancel_shift(shift_id, headers or SITE_LEAD_HEADERS))


def add_overnight_lead_coverage(site_activation_id, lead_staff_id, confirmer_staff_id,
                                start_at=OVERNIGHT_SHIFT_START,
                                end_at=OVERNIGHT_SHIFT_END):
    """Plan + confirm a SITE_LEAD shift fully containing tonight's overnight
    window (PRD §3.3). Confirmer differs from the shift's staff member."""
    shift = plan_shift(site_activation_id, lead_staff_id, "SITE_LEAD",
                       start_at, end_at,
                       planner_headers=make_site_lead_headers(confirmer_staff_id))
    confirm_shift(shift["id"], make_site_lead_headers(confirmer_staff_id))
    return shift


def open_activation(site_activation_id, opener_staff_id):
    return get_success_data(api_client.open_site_activation(
        site_activation_id, make_site_lead_headers(opener_staff_id)))


def close_activation(site_activation_id, closer_staff_id):
    return get_success_data(api_client.close_site_activation(
        site_activation_id, make_site_lead_headers(closer_staff_id)))


# ---------------------------------------------------------------------------
# Tier 1: guests and stays
# ---------------------------------------------------------------------------

def register_guest(alias, intake_headers=None, **kwargs):
    payload = create_guest_payload(alias, **kwargs)
    return get_success_data(
        api_client.create_guest(payload, intake_headers or INTAKE_HEADERS))


def walk_in_stay(site_activation_id, guest_id, intake_headers=None):
    payload = create_stay_payload(guest_id)
    return get_success_data(api_client.create_stay(
        site_activation_id, payload, intake_headers or INTAKE_HEADERS))


def get_stay(stay_id):
    return get_success_data(api_client.get_stay(stay_id, EOC_HEADERS))


# ---------------------------------------------------------------------------
# Tier 1: vehicles and dispatches
# ---------------------------------------------------------------------------

def create_vehicle(label="van-1", seats=4, turnaround_minutes=30):
    payload = create_vehicle_payload(label=label, seats=seats,
                                     turnaround_minutes=turnaround_minutes)
    return get_success_data(api_client.create_vehicle(payload, TC_HEADERS))


def create_dispatch(site_activation_id, guest_ids,
                    pickup_window_start=DISPATCH_WINDOW_START,
                    pickup_window_end=DISPATCH_WINDOW_END, has_pets=None,
                    outreach_headers=None):
    payload = create_dispatch_payload(site_activation_id, guest_ids,
                                      pickup_window_start, pickup_window_end,
                                      has_pets=has_pets)
    return get_success_data(api_client.create_transport_dispatch(
        payload, outreach_headers or OUTREACH_HEADERS))


def assign_dispatch(dispatch_id, vehicle_id):
    return get_success_data(api_client.assign_transport_dispatch(
        dispatch_id, {"vehicle_id": vehicle_id}, TC_HEADERS))


def arrive_dispatch(dispatch_id):
    return get_success_data(
        api_client.arrive_transport_dispatch(dispatch_id, TC_HEADERS))


def get_dispatch(dispatch_id):
    return get_success_data(api_client.get_transport_dispatch(dispatch_id, EOC_HEADERS))


def list_stays(params):
    data, _meta = validate_paginated(api_client.list_stays(EOC_HEADERS, params=params))
    return data


# ---------------------------------------------------------------------------
# Tier 1: donations, meal services, incidents, after-action reports
# ---------------------------------------------------------------------------

def pledge_donation(site_activation_id, partner_name, category, quantity,
                    lead_headers=None):
    payload = create_donation_payload(partner_name=partner_name, category=category,
                                      quantity=quantity)
    return get_success_data(api_client.create_donation(
        site_activation_id, payload, lead_headers or SITE_LEAD_HEADERS))


def receive_donation(donation_id, lead_headers=None):
    return get_success_data(api_client.receive_donation(
        donation_id, lead_headers or SITE_LEAD_HEADERS))


def plan_meal_service(site_activation_id, service_date, meal_period,
                      lead_headers=None):
    payload = create_meal_service_payload(service_date, meal_period)
    return get_success_data(api_client.create_meal_service(
        site_activation_id, payload, lead_headers or SITE_LEAD_HEADERS))


def serve_meal(meal_service_id, served_count, lead_headers=None):
    return get_success_data(api_client.serve_meal_service(
        meal_service_id, serve_meal_payload(served_count),
        lead_headers or SITE_LEAD_HEADERS))


def report_incident(site_activation_id, kind, severity, reporter_headers=None,
                    guest_id=None):
    payload = create_incident_payload(site_activation_id, kind, severity,
                                      guest_id=guest_id)
    return get_success_data(api_client.create_incident(
        payload, reporter_headers or INTAKE_HEADERS))


def escalate_incident(incident_id, headers):
    return get_success_data(api_client.escalate_incident(incident_id, headers))


def resolve_incident(incident_id, resolution_note, headers):
    return get_success_data(api_client.resolve_incident(
        incident_id, {"resolution_note": resolution_note}, headers))


def create_aar(episode_id):
    return get_success_data(api_client.create_after_action_report(episode_id,
                                                                  EOC_HEADERS))


def submit_aar(aar_id, headers=None):
    return get_success_data(
        api_client.submit_after_action_report(aar_id, headers or EOC_HEADERS))


def approve_aar(aar_id, headers):
    return get_success_data(api_client.approve_after_action_report(aar_id, headers))


# ---------------------------------------------------------------------------
# Tier 2: episode + site composites
# ---------------------------------------------------------------------------

def _register_leads():
    lead1 = add_staff_member("Lead One", ["SITE_LEAD"])
    lead2 = add_staff_member("Lead Two", ["SITE_LEAD"])
    return lead1, lead2


def setup_standby_episode_with_opening_site(bed_capacity=10, pet_capacity=0,
                                            locker_capacity=0,
                                            site_name="Armory",
                                            site_address="9 Oak Ave",
                                            mode="WARMING", threshold_f=32.0):
    """Episode in STANDBY (no weather posted) + one SiteActivation in OPENING.
    Donation, meal-service, shift-planning and incident flows need no OPEN."""
    episode = create_episode(mode=mode, threshold_f=threshold_f)
    site = create_site(name=site_name, address=site_address,
                       bed_capacity=bed_capacity, pet_capacity=pet_capacity,
                       locker_capacity=locker_capacity)
    sa = designate_site(episode["id"], site["id"])
    lead1 = add_staff_member("Lead One", ["SITE_LEAD"])
    return {
        "episode": episode, "site": site, "site_activation": sa,
        "lead1": lead1, "lead1_headers": make_site_lead_headers(lead1["id"]),
        "eoc_headers": EOC_HEADERS,
    }


def setup_activating_episode_with_site(bed_capacity=4, pet_capacity=0,
                                       locker_capacity=0, with_coverage=True,
                                       site_name="Rec Center"):
    """Episode driven to ACTIVATING (qualifying breach run + evaluate) with one
    SiteActivation in OPENING; optionally with confirmed overnight lead
    coverage already in place. Not yet activated."""
    set_clock(SETUP_CLOCK)
    episode = create_episode()
    post_breach_run(episode["id"])
    site = create_site(name=site_name, bed_capacity=bed_capacity,
                       pet_capacity=pet_capacity, locker_capacity=locker_capacity)
    sa = designate_site(episode["id"], site["id"])
    lead1, lead2 = _register_leads()
    shift = None
    if with_coverage:
        shift = add_overnight_lead_coverage(sa["id"], lead1["id"], lead2["id"])
    evaluate_episode(episode["id"])
    return {
        "episode": episode, "site": site, "site_activation": sa,
        "lead1": lead1, "lead2": lead2,
        "lead1_headers": make_site_lead_headers(lead1["id"]),
        "lead2_headers": make_site_lead_headers(lead2["id"]),
        "lead_shift": shift, "eoc_headers": EOC_HEADERS,
    }


def setup_active_episode_with_opening_site(bed_capacity=4, pet_capacity=0,
                                           locker_capacity=0,
                                           site_name="Rec Center",
                                           activator_user_id=None):
    """Episode ACTIVE with one SiteActivation still in OPENING (never opened),
    confirmed overnight lead coverage in place."""
    ws = setup_activating_episode_with_site(
        bed_capacity=bed_capacity, pet_capacity=pet_capacity,
        locker_capacity=locker_capacity, site_name=site_name)
    ws["episode"] = activate_episode(ws["episode"]["id"],
                                     user_id=activator_user_id)
    return ws


def setup_active_episode_with_open_site(bed_capacity=4, pet_capacity=0,
                                        locker_capacity=0,
                                        site_name="Rec Center",
                                        activator_user_id=None):
    """The workhorse: clock set, COOLING episode with a qualifying breach run,
    site designated, overnight SITE_LEAD shift confirmed, episode ACTIVATING ->
    ACTIVE, activation OPENING -> OPEN (beds_effective pinned)."""
    ws = setup_activating_episode_with_site(
        bed_capacity=bed_capacity, pet_capacity=pet_capacity,
        locker_capacity=locker_capacity, site_name=site_name)
    ws["episode"] = activate_episode(ws["episode"]["id"],
                                     user_id=activator_user_id)
    ws["site_activation"] = open_activation(ws["site_activation"]["id"],
                                            ws["lead1"]["id"])
    return ws


def setup_episode_trigger_met_without_sites():
    """Episode ACTIVATING (qualifying breach run evaluated) with zero site
    activations — the designated-site gate at activation (PRD §3.1)."""
    episode = create_episode()
    post_breach_run(episode["id"])
    evaluate_episode(episode["id"])
    return {"episode": episode, "eoc_headers": EOC_HEADERS}


# ---------------------------------------------------------------------------
# Tier 3: guest / dispatch scenes
# ---------------------------------------------------------------------------

def setup_open_site_with_guests(guest_specs, bed_capacity=4, pet_capacity=0,
                                locker_capacity=0):
    """OPEN activation plus registered guests. guest_specs is a list of kwargs
    dicts for register_guest; returns ws with 'guests' list."""
    ws = setup_active_episode_with_open_site(bed_capacity=bed_capacity,
                                             pet_capacity=pet_capacity,
                                             locker_capacity=locker_capacity)
    guests = [register_guest(**spec) for spec in guest_specs]
    ws["guests"] = guests
    return ws


def setup_assigned_dispatch_scene(rider_aliases=("rider-1", "rider-2"),
                                  bed_capacity=4, pet_capacity=0,
                                  locker_capacity=0, vehicle_seats=4,
                                  pickup_window_start=DISPATCH_WINDOW_START,
                                  pickup_window_end=DISPATCH_WINDOW_END,
                                  has_pets=None):
    """OPEN activation; a dispatch for the riders already ASSIGNED (one
    RESERVED stay per rider at the destination)."""
    ws = setup_open_site_with_guests(
        [{"alias": a} for a in rider_aliases],
        bed_capacity=bed_capacity, pet_capacity=pet_capacity,
        locker_capacity=locker_capacity)
    ws["outreach"] = add_staff_member("Outreach One", ["OUTREACH"])
    ws["outreach_headers"] = make_outreach_worker_headers(ws["outreach"]["id"])
    ws["vehicle"] = create_vehicle(seats=vehicle_seats)
    ws["dispatch"] = create_dispatch(
        ws["site_activation"]["id"], [g["id"] for g in ws["guests"]],
        pickup_window_start=pickup_window_start,
        pickup_window_end=pickup_window_end, has_pets=has_pets,
        outreach_headers=ws["outreach_headers"])
    ws["dispatch"] = assign_dispatch(ws["dispatch"]["id"], ws["vehicle"]["id"])
    return ws


def setup_arrived_dispatch_scene(**kwargs):
    """ASSIGNED dispatch that has ARRIVED (reserved stays now check-in
    eligible)."""
    ws = setup_assigned_dispatch_scene(**kwargs)
    ws["dispatch"] = arrive_dispatch(ws["dispatch"]["id"])
    return ws


def setup_requested_dispatch_scene():
    """OPEN activation; a dispatch still REQUESTED (never assigned)."""
    ws = setup_open_site_with_guests([{"alias": "rider"}])
    ws["outreach"] = add_staff_member("Outreach One", ["OUTREACH"])
    ws["outreach_headers"] = make_outreach_worker_headers(ws["outreach"]["id"])
    ws["dispatch"] = create_dispatch(
        ws["site_activation"]["id"], [ws["guests"][0]["id"]],
        outreach_headers=ws["outreach_headers"])
    return ws


def setup_dispatch_capacity_scene():
    """OPEN activation (beds 4, pet 2, locker 8); four guests (2+1 pets on the
    first two), a 6-seat vehicle, a 4-rider dispatch flagged has_pets and an
    identical-rider-count pair without pets."""
    ws = setup_active_episode_with_open_site(bed_capacity=4, pet_capacity=2,
                                             locker_capacity=8)
    g1 = register_guest("pet-two", has_pets=True, pet_count=2)
    g2 = register_guest("pet-one", has_pets=True, pet_count=1)
    g3 = register_guest("plain-three")
    g4 = register_guest("plain-four")
    outreach = add_staff_member("Outreach One", ["OUTREACH"])
    outreach_headers = make_outreach_worker_headers(outreach["id"])
    vehicle = create_vehicle(label="van-1", seats=6)
    disp_pets = create_dispatch(
        ws["site_activation"]["id"], [g1["id"], g2["id"], g3["id"], g4["id"]],
        has_pets=True, outreach_headers=outreach_headers)
    disp_plain = create_dispatch(
        ws["site_activation"]["id"], [g3["id"], g4["id"]],
        pickup_window_start="2026-08-10T16:00:00Z",
        pickup_window_end="2026-08-10T17:00:00Z",
        has_pets=False, outreach_headers=outreach_headers)
    ws.update({"guests": [g1, g2, g3, g4], "vehicle": vehicle,
               "dispatch_pets": disp_pets, "dispatch_plain": disp_plain,
               "outreach_headers": outreach_headers})
    return ws


def setup_vehicle_buffer_scene():
    """OPEN activation; vehicle V (seats 4, turnaround 30) with D1
    [14:00,15:00) already ASSIGNED; D2 [15:00,16:00) and D3 [15:30,16:30)
    REQUESTED."""
    ws = setup_open_site_with_guests(
        [{"alias": "rider-1"}, {"alias": "rider-2"}, {"alias": "rider-3"}])
    ws["outreach"] = add_staff_member("Outreach One", ["OUTREACH"])
    ws["outreach_headers"] = make_outreach_worker_headers(ws["outreach"]["id"])
    ws["vehicle"] = create_vehicle(label="van-1", seats=4, turnaround_minutes=30)
    g1, g2, g3 = [g["id"] for g in ws["guests"]]
    ws["d1"] = create_dispatch(ws["site_activation"]["id"], [g1],
                               "2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z",
                               outreach_headers=ws["outreach_headers"])
    assign_dispatch(ws["d1"]["id"], ws["vehicle"]["id"])
    ws["d2"] = create_dispatch(ws["site_activation"]["id"], [g2],
                               "2026-08-10T15:00:00Z", "2026-08-10T16:00:00Z",
                               outreach_headers=ws["outreach_headers"])
    ws["d3"] = create_dispatch(ws["site_activation"]["id"], [g3],
                               "2026-08-10T15:30:00Z", "2026-08-10T16:30:00Z",
                               outreach_headers=ws["outreach_headers"])
    return ws


def setup_dispatch_seats_beds_scene():
    """OPEN activation with a single bed; two riders; a 1-seat vehicle and a
    4-seat vehicle; one REQUESTED dispatch for both riders."""
    ws = setup_open_site_with_guests(
        [{"alias": "rider-1"}, {"alias": "rider-2"}], bed_capacity=1)
    ws["outreach"] = add_staff_member("Outreach One", ["OUTREACH"])
    ws["outreach_headers"] = make_outreach_worker_headers(ws["outreach"]["id"])
    ws["vehicle_small"] = create_vehicle(label="mini", seats=1)
    ws["vehicle_large"] = create_vehicle(label="van", seats=4)
    ws["dispatch"] = create_dispatch(
        ws["site_activation"]["id"], [g["id"] for g in ws["guests"]],
        outreach_headers=ws["outreach_headers"])
    return ws


def setup_two_open_sites_scene():
    """One ACTIVE episode with two OPEN activations: site A (beds 4) and site B
    (beds 2), each with its own confirmed overnight lead coverage. Guest g1
    arrives via an ASSIGNED dispatch at A (stay RESERVED); guest g2 is a
    walk-in CHECKED_IN at A."""
    set_clock(SETUP_CLOCK)
    episode = create_episode()
    post_breach_run(episode["id"])
    site_a = create_site(name="Site A", address="1 Main St", bed_capacity=4)
    site_b = create_site(name="Site B", address="2 Elm St", bed_capacity=2)
    sa_a = designate_site(episode["id"], site_a["id"])
    sa_b = designate_site(episode["id"], site_b["id"])
    lead1, lead2 = _register_leads()
    lead3 = add_staff_member("Lead Three", ["SITE_LEAD"])
    add_overnight_lead_coverage(sa_a["id"], lead1["id"], lead2["id"])
    add_overnight_lead_coverage(sa_b["id"], lead3["id"], lead2["id"])
    evaluate_episode(episode["id"])
    episode = activate_episode(episode["id"])
    sa_a = open_activation(sa_a["id"], lead1["id"])
    sa_b = open_activation(sa_b["id"], lead3["id"])
    g1 = register_guest("rider")
    g2 = register_guest("walker")
    outreach = add_staff_member("Outreach One", ["OUTREACH"])
    outreach_headers = make_outreach_worker_headers(outreach["id"])
    vehicle = create_vehicle(label="van-1", seats=4)
    dispatch = create_dispatch(sa_a["id"], [g1["id"]],
                               outreach_headers=outreach_headers)
    dispatch = assign_dispatch(dispatch["id"], vehicle["id"])
    stay2 = walk_in_stay(sa_a["id"], g2["id"])
    stay1 = list_stays({"transport_dispatch_id": dispatch["id"]})[0]
    return {
        "episode": episode, "site_a": site_a, "site_b": site_b,
        "sa_a": sa_a, "sa_b": sa_b,
        "lead1": lead1, "lead2": lead2, "lead3": lead3,
        "lead1_headers": make_site_lead_headers(lead1["id"]),
        "lead3_headers": make_site_lead_headers(lead3["id"]),
        "guest_rider": g1, "guest_walker": g2, "vehicle": vehicle,
        "dispatch": dispatch, "stay_reserved": stay1, "stay_walkin": stay2,
        "outreach_headers": outreach_headers, "eoc_headers": EOC_HEADERS,
    }


def setup_two_active_episodes_with_open_sites():
    """Two COOLING episodes, both ACTIVE, each with one OPEN activation;
    one guest CHECKED_IN at episode 1's site."""
    set_clock(SETUP_CLOCK)
    lead1, lead2 = _register_leads()
    lead3 = add_staff_member("Lead Three", ["SITE_LEAD"])

    def _build(name, address, beds, lead, confirmer):
        ep = create_episode()
        post_breach_run(ep["id"])
        site = create_site(name=name, address=address, bed_capacity=beds)
        sa = designate_site(ep["id"], site["id"])
        add_overnight_lead_coverage(sa["id"], lead["id"], confirmer["id"])
        evaluate_episode(ep["id"])
        ep = activate_episode(ep["id"])
        sa = open_activation(sa["id"], lead["id"])
        return ep, site, sa

    ep1, site_a, sa_a = _build("Site A", "1 Main St", 4, lead1, lead2)
    ep2, site_b, sa_b = _build("Site B", "2 Elm St", 2, lead3, lead2)
    guest = register_guest("walker")
    stay = walk_in_stay(sa_a["id"], guest["id"])
    return {
        "episode1": ep1, "episode2": ep2, "site_a": site_a, "site_b": site_b,
        "sa_a": sa_a, "sa_b": sa_b, "guest": guest, "stay": stay,
        "lead1": lead1, "lead1_headers": make_site_lead_headers(lead1["id"]),
        "eoc_headers": EOC_HEADERS,
    }


# ---------------------------------------------------------------------------
# Tier 3: staffing scenes
# ---------------------------------------------------------------------------

def setup_opening_site_with_staff(worker_skills=("INTAKE",)):
    """STANDBY episode + OPENING activation + a SITE_LEAD and a worker."""
    ws = setup_standby_episode_with_opening_site()
    ws["lead2"] = add_staff_member("Lead Two", ["SITE_LEAD"])
    ws["lead2_headers"] = make_site_lead_headers(ws["lead2"]["id"])
    ws["worker"] = add_staff_member("Worker W", list(worker_skills))
    return ws


def setup_shift_overlap_scene():
    """Worker W with a CONFIRMED shift S1 [20:00, 04:00+1d), plus PLANNED S2
    [04:00, 08:00) (merely touching S1) and PLANNED S3 [03:00, 05:00)
    (intersecting S1)."""
    ws = setup_opening_site_with_staff()
    s1 = plan_shift(ws["site_activation"]["id"], ws["worker"]["id"], "INTAKE",
                    "2026-08-10T20:00:00Z", "2026-08-11T04:00:00Z",
                    planner_headers=ws["lead1_headers"])
    confirm_shift(s1["id"], ws["lead1_headers"])
    s2 = plan_shift(ws["site_activation"]["id"], ws["worker"]["id"], "INTAKE",
                    "2026-08-11T04:00:00Z", "2026-08-11T08:00:00Z",
                    planner_headers=ws["lead1_headers"])
    s3 = plan_shift(ws["site_activation"]["id"], ws["worker"]["id"], "INTAKE",
                    "2026-08-11T03:00:00Z", "2026-08-11T05:00:00Z",
                    planner_headers=ws["lead1_headers"])
    ws.update({"s1": s1, "s2": s2, "s3": s3})
    return ws


def setup_cancelled_shift_scene():
    """Worker W with a CONFIRMED shift S1 [20:00, 04:00+1d) and a second shift
    S2 [03:00, 08:00) that overlaps S1 but is already CANCELLED."""
    ws = setup_opening_site_with_staff()
    s1 = plan_shift(ws["site_activation"]["id"], ws["worker"]["id"], "INTAKE",
                    "2026-08-10T20:00:00Z", "2026-08-11T04:00:00Z",
                    planner_headers=ws["lead1_headers"])
    confirm_shift(s1["id"], ws["lead1_headers"])
    s2 = plan_shift(ws["site_activation"]["id"], ws["worker"]["id"], "INTAKE",
                    "2026-08-11T03:00:00Z", "2026-08-11T08:00:00Z",
                    planner_headers=ws["lead1_headers"])
    cancel_shift(s2["id"], ws["lead1_headers"])
    ws.update({"s1": s1, "s2": s2})
    return ws


# ---------------------------------------------------------------------------
# Tier 3: deactivation / ops-sweep / after-action scenes
# ---------------------------------------------------------------------------

def setup_deactivation_cascade_scene():
    """ACTIVE episode; OPEN activation (beds 4); an ASSIGNED dispatch holding
    two RESERVED stays; one walk-in guest CHECKED_IN."""
    ws = setup_assigned_dispatch_scene(
        rider_aliases=("rider-1", "rider-2"))
    walker = register_guest("walker")
    ws["guest_walker"] = walker
    ws["stay_walkin"] = walk_in_stay(ws["site_activation"]["id"], walker["id"])
    return ws


def setup_active_episode_open_plus_opening_site():
    """ACTIVE episode with SA1 OPEN (lead coverage) and SA2 still OPENING with
    a CONFIRMED INTAKE shift of its own."""
    set_clock(SETUP_CLOCK)
    episode = create_episode()
    post_breach_run(episode["id"])
    site_a = create_site(name="Site A", address="1 Main St", bed_capacity=4)
    site_b = create_site(name="Site B", address="2 Elm St", bed_capacity=2)
    sa_a = designate_site(episode["id"], site_a["id"])
    sa_b = designate_site(episode["id"], site_b["id"])
    lead1, lead2 = _register_leads()
    worker = add_staff_member("Worker W", ["INTAKE"])
    shift_a = add_overnight_lead_coverage(sa_a["id"], lead1["id"], lead2["id"])
    shift_b = plan_shift(sa_b["id"], worker["id"], "INTAKE",
                         "2026-08-10T20:00:00Z", "2026-08-11T04:00:00Z",
                         planner_headers=make_site_lead_headers(lead1["id"]))
    confirm_shift(shift_b["id"], make_site_lead_headers(lead1["id"]))
    evaluate_episode(episode["id"])
    episode = activate_episode(episode["id"])
    sa_a = open_activation(sa_a["id"], lead1["id"])
    return {
        "episode": episode, "site_a": site_a, "site_b": site_b,
        "sa_a": sa_a, "sa_b": sa_b, "shift_a": shift_a, "shift_b": shift_b,
        "lead1": lead1, "lead2": lead2, "worker": worker,
        "lead1_headers": make_site_lead_headers(lead1["id"]),
        "eoc_headers": EOC_HEADERS,
    }


def setup_run_ops_scene():
    """ACTIVE episode; OPEN activation (beds 4); a CONFIRMED short shift
    09:00-10:00 for a worker; the CONFIRMED overnight lead shift
    22:00-06:00+1d; a dispatch ARRIVED at 13:00 leaving one RESERVED stay
    unchecked; logical clock advanced to 14:30 (90 minutes past arrival)."""
    ws = setup_active_episode_with_open_site()
    worker = add_staff_member("Worker W", ["INTAKE"])
    shift_w = plan_shift(ws["site_activation"]["id"], worker["id"], "INTAKE",
                         "2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z",
                         planner_headers=ws["lead1_headers"])
    confirm_shift(shift_w["id"], ws["lead1_headers"])
    guest = register_guest("rider")
    outreach = add_staff_member("Outreach One", ["OUTREACH"])
    outreach_headers = make_outreach_worker_headers(outreach["id"])
    vehicle = create_vehicle(label="van-1", seats=4)
    dispatch = create_dispatch(ws["site_activation"]["id"], [guest["id"]],
                               pickup_window_start="2026-08-10T12:00:00Z",
                               pickup_window_end="2026-08-10T13:00:00Z",
                               outreach_headers=outreach_headers)
    assign_dispatch(dispatch["id"], vehicle["id"])
    stay = list_stays({"transport_dispatch_id": dispatch["id"]})[0]
    set_clock("2026-08-10T13:00:00Z")
    dispatch = arrive_dispatch(dispatch["id"])
    set_clock("2026-08-10T14:30:00Z")
    ws.update({"worker": worker, "shift_worker": shift_w, "guest": guest,
               "vehicle": vehicle, "dispatch": dispatch, "stay": stay,
               "outreach_headers": outreach_headers})
    return ws


def setup_draining_site_with_checked_in_guest():
    """Episode deactivated (DEACTIVATING); its OPEN activation now DRAINING
    with one guest still CHECKED_IN."""
    ws = setup_active_episode_with_open_site()
    guest = register_guest("walker")
    stay = walk_in_stay(ws["site_activation"]["id"], guest["id"])
    ws["episode"] = deactivate_episode(ws["episode"]["id"])
    ws["guest"] = guest
    ws["stay"] = stay
    ws["site_activation"] = get_site_activation(ws["site_activation"]["id"])
    return ws


def _settle_episode_to_deactivated(ws):
    """Deactivate and close every activation so the episode settles."""
    deactivate_episode(ws["episode"]["id"])
    close_activation(ws["site_activation"]["id"], ws["lead1"]["id"])


def setup_deactivated_episode_with_open_incident():
    """Full lifecycle: a guest checked in 20:00-23:00 (zero midnight
    crossings), checked out; one BEHAVIORAL severity-1 incident still
    REPORTED; episode deactivated, site closed (episode DEACTIVATED); an
    after-action report created in DRAFT."""
    ws = setup_active_episode_with_open_site(activator_user_id="eoc-activator-1")
    guest = register_guest("walker")
    set_clock("2026-08-10T20:00:00Z")
    stay = walk_in_stay(ws["site_activation"]["id"], guest["id"])
    set_clock("2026-08-10T23:00:00Z")
    get_success_data(api_client.check_out_stay(stay["id"], INTAKE_HEADERS))
    incident = report_incident(ws["site_activation"]["id"], "BEHAVIORAL", 1,
                               reporter_headers=INTAKE_HEADERS,
                               guest_id=guest["id"])
    _settle_episode_to_deactivated(ws)
    aar = create_aar(ws["episode"]["id"])
    ws.update({"guest": guest, "stay": stay, "incident": incident, "aar": aar})
    return ws


def setup_deactivated_episode_with_aar():
    """Zero-guest lifecycle: ACTIVE (activated by eoc-activator-1) ->
    deactivated -> site closed -> DEACTIVATED; report created in DRAFT."""
    ws = setup_active_episode_with_open_site(activator_user_id="eoc-activator-1")
    _settle_episode_to_deactivated(ws)
    aar = create_aar(ws["episode"]["id"])
    ws["aar"] = aar
    return ws


def setup_deactivating_episode_with_aar():
    """Episode DEACTIVATING (site still DRAINING, no guests); a report drafted
    during the drain (DRAFT)."""
    ws = setup_active_episode_with_open_site()
    deactivate_episode(ws["episode"]["id"])
    aar = create_aar(ws["episode"]["id"])
    ws["aar"] = aar
    return ws


# ---------------------------------------------------------------------------
# Tier 3: incident scenes
# ---------------------------------------------------------------------------

def setup_full_one_bed_site_with_occupant():
    """OPEN activation with a single bed already occupied by a checked-in
    guest; a second guest registered and waiting."""
    ws = setup_open_site_with_guests(
        [{"alias": "occupant"}, {"alias": "second"}], bed_capacity=1)
    ws["stay_occupant"] = walk_in_stay(ws["site_activation"]["id"],
                                       ws["guests"][0]["id"])
    return ws


def setup_ejection_scene():
    """One-bed site full; a BEHAVIORAL severity-3 incident on the occupant
    reported (still REPORTED)."""
    ws = setup_full_one_bed_site_with_occupant()
    incident = report_incident(ws["site_activation"]["id"], "BEHAVIORAL", 3,
                               reporter_headers=INTAKE_HEADERS,
                               guest_id=ws["guests"][0]["id"])
    ws["incident"] = incident
    return ws


def setup_medical_hold_at_full_site():
    """One-bed site full; the waiting guest carries an active medical hold (an
    escalated, unresolved MEDICAL incident)."""
    ws = setup_full_one_bed_site_with_occupant()
    medic = add_staff_member("Medic One", ["MEDICAL"])
    incident = report_incident(ws["site_activation"]["id"], "MEDICAL", 2,
                               reporter_headers=INTAKE_HEADERS,
                               guest_id=ws["guests"][1]["id"])
    escalate_incident(incident["id"],
                      make_medical_responder_headers(medic["id"]))
    ws.update({"incident": incident, "medic": medic})
    return ws


def setup_opening_site_with_incidents():
    """STANDBY episode, OPENING activation, one REPORTED BEHAVIORAL and one
    REPORTED MEDICAL incident (no guests involved)."""
    ws = setup_opening_site_with_staff()
    medic = add_staff_member("Medic One", ["MEDICAL"])
    inc_b = report_incident(ws["site_activation"]["id"], "BEHAVIORAL", 1,
                            reporter_headers=INTAKE_HEADERS)
    inc_m = report_incident(ws["site_activation"]["id"], "MEDICAL", 2,
                            reporter_headers=INTAKE_HEADERS)
    ws.update({"medic": medic,
               "medic_headers": make_medical_responder_headers(medic["id"]),
               "incident_behavioral": inc_b, "incident_medical": inc_m})
    return ws


# ---------------------------------------------------------------------------
# Tier 4: supply / meal scenes
# ---------------------------------------------------------------------------

def setup_stock_scene():
    """OPENING activation with a 50-unit MEAL pledge outstanding and a 100-unit
    MEAL donation already RECEIVED."""
    ws = setup_standby_episode_with_opening_site()
    pledge_donation(ws["site_activation"]["id"], "FoodBank", "MEAL", 50,
                    lead_headers=ws["lead1_headers"])
    don_b = pledge_donation(ws["site_activation"]["id"], "Church", "MEAL", 100,
                            lead_headers=ws["lead1_headers"])
    receive_donation(don_b["id"], lead_headers=ws["lead1_headers"])
    return ws


def setup_meal_conservation_scene():
    """OPENING activation with 100 MEAL units RECEIVED and three planned meal
    services (LUNCH, DINNER, next-day BREAKFAST)."""
    ws = setup_standby_episode_with_opening_site()
    don = pledge_donation(ws["site_activation"]["id"], "FoodBank", "MEAL", 100,
                          lead_headers=ws["lead1_headers"])
    receive_donation(don["id"], lead_headers=ws["lead1_headers"])
    ms1 = plan_meal_service(ws["site_activation"]["id"], "2026-08-10T00:00:00Z",
                            "LUNCH", lead_headers=ws["lead1_headers"])
    ms2 = plan_meal_service(ws["site_activation"]["id"], "2026-08-10T00:00:00Z",
                            "DINNER", lead_headers=ws["lead1_headers"])
    ms3 = plan_meal_service(ws["site_activation"]["id"], "2026-08-11T00:00:00Z",
                            "BREAKFAST", lead_headers=ws["lead1_headers"])
    ws.update({"donation": don, "ms1": ms1, "ms2": ms2, "ms3": ms3})
    return ws


def setup_rounding_scene():
    """OPEN activation (beds 4) with three guests CHECKED_IN, so the meal-plan
    attendance snapshot is exactly 3."""
    ws = setup_open_site_with_guests(
        [{"alias": "a"}, {"alias": "b"}, {"alias": "c"}], bed_capacity=4)
    for g in ws["guests"]:
        walk_in_stay(ws["site_activation"]["id"], g["id"])
    return ws


# ---------------------------------------------------------------------------
# Tier 4: misc bespoke scenes
# ---------------------------------------------------------------------------

def setup_guest_checked_in_window(checkin_clock="2026-08-10T20:00:00Z",
                                  now_clock="2026-08-11T21:00:00Z",
                                  bed_capacity=4, pet_capacity=2,
                                  locker_capacity=4):
    """A guest checked in at `checkin_clock`, logical clock then advanced to
    `now_clock` — the bed-night dual-variant observation point (PRD §3.4)."""
    ws = setup_active_episode_with_open_site(bed_capacity=bed_capacity,
                                             pet_capacity=pet_capacity,
                                             locker_capacity=locker_capacity)
    guest = register_guest("guest-one")
    set_clock(checkin_clock)
    stay = walk_in_stay(ws["site_activation"]["id"], guest["id"])
    set_clock(now_clock)
    ws.update({"guest": guest, "stay": stay})
    return ws


def setup_capacity_override_open_scene():
    """OPEN activation designated with capacity_override 2 on a site whose
    registry bed_capacity is 10 — beds_effective pinned 2 at open."""
    set_clock(SETUP_CLOCK)
    episode = create_episode()
    post_breach_run(episode["id"])
    site = create_site(name="Big Hall", address="7 Grand Ave", bed_capacity=10)
    sa = designate_site(episode["id"], site["id"], capacity_override=2)
    lead1, lead2 = _register_leads()
    add_overnight_lead_coverage(sa["id"], lead1["id"], lead2["id"])
    evaluate_episode(episode["id"])
    episode = activate_episode(episode["id"])
    sa = open_activation(sa["id"], lead1["id"])
    return {"episode": episode, "site": site, "site_activation": sa,
            "lead1": lead1, "lead2": lead2,
            "lead1_headers": make_site_lead_headers(lead1["id"]),
            "eoc_headers": EOC_HEADERS}


def setup_active_episode_for_extensions():
    """Episode ACTIVE with a designated (OPENING) site — the state in which
    extensions are legal (PRD §3.8)."""
    set_clock(SETUP_CLOCK)
    episode = create_episode()
    post_breach_run(episode["id"])
    site = create_site()
    designate_site(episode["id"], site["id"])
    evaluate_episode(episode["id"])
    episode = activate_episode(episode["id"])
    return {"episode": episode, "site": site, "eoc_headers": EOC_HEADERS}


def setup_overnight_gap_contrast_scene():
    """ACTIVE episode with two activations: A with a CONFIRMED SITE_LEAD shift
    [22:00, 06:00+1d) (covers the half-open overnight window exactly) and B
    with one ending one minute earlier at 05:59+1d."""
    set_clock(SETUP_CLOCK)
    episode = create_episode()
    post_breach_run(episode["id"])
    site_a = create_site(name="Site A", address="1 Main St", bed_capacity=4)
    site_b = create_site(name="Site B", address="2 Elm St", bed_capacity=4)
    sa_a = designate_site(episode["id"], site_a["id"])
    sa_b = designate_site(episode["id"], site_b["id"])
    lead1, lead2 = _register_leads()
    lead3 = add_staff_member("Lead Three", ["SITE_LEAD"])
    add_overnight_lead_coverage(sa_a["id"], lead1["id"], lead2["id"],
                                end_at="2026-08-11T06:00:00Z")
    add_overnight_lead_coverage(sa_b["id"], lead3["id"], lead2["id"],
                                end_at="2026-08-11T05:59:00Z")
    evaluate_episode(episode["id"])
    episode = activate_episode(episode["id"])
    return {"episode": episode, "site_a": site_a, "site_b": site_b,
            "sa_a": sa_a, "sa_b": sa_b,
            "lead1": lead1, "lead2": lead2, "lead3": lead3,
            "eoc_headers": EOC_HEADERS}


def setup_lead_coverage_missing_scene():
    """ACTIVE episode; activation whose overnight window is fully tiled by two
    merged CONFIRMED INTAKE shifts [22:00, 02:00) + [02:00, 06:00) but with no
    SITE_LEAD shift containing it."""
    set_clock(SETUP_CLOCK)
    episode = create_episode()
    post_breach_run(episode["id"])
    site = create_site()
    sa = designate_site(episode["id"], site["id"])
    lead1 = add_staff_member("Lead One", ["SITE_LEAD"])
    w1 = add_staff_member("Worker One", ["INTAKE"])
    w2 = add_staff_member("Worker Two", ["INTAKE"])
    lead_headers = make_site_lead_headers(lead1["id"])
    sh1 = plan_shift(sa["id"], w1["id"], "INTAKE",
                     "2026-08-10T22:00:00Z", "2026-08-11T02:00:00Z",
                     planner_headers=lead_headers)
    confirm_shift(sh1["id"], lead_headers)
    sh2 = plan_shift(sa["id"], w2["id"], "INTAKE",
                     "2026-08-11T02:00:00Z", "2026-08-11T06:00:00Z",
                     planner_headers=lead_headers)
    confirm_shift(sh2["id"], lead_headers)
    evaluate_episode(episode["id"])
    episode = activate_episode(episode["id"])
    return {"episode": episode, "site": site, "site_activation": sa,
            "lead1": lead1, "lead1_headers": lead_headers,
            "eoc_headers": EOC_HEADERS}


def run_episode_double_cycle():
    """Drive an episode through both surveillance cycles (PRD §3.1):
    STANDBY -> ACTIVATING -> STANDBY (breach run reset), re-arm to ACTIVATING,
    activate with one covered site, deactivate to DEACTIVATING, then a fresh
    breach run during the drain re-surges the episode to ACTIVE and the
    DRAINING activation back to OPEN. Returns every captured status."""
    set_clock("2026-08-10T05:00:00Z")
    episode = create_episode()
    post_breach_run(episode["id"])
    st1 = evaluate_episode(episode["id"])["status"]
    # A non-breach reading resets the run (PRD §3.1).
    post_weather_reading(episode["id"], "2026-08-10T07:15:00Z",
                         temp_f=90.0, heat_index_f=90.0)
    st2 = evaluate_episode(episode["id"])["status"]
    post_breach_run(episode["id"], times=[
        "2026-08-10T08:00:00Z", "2026-08-10T08:15:00Z", "2026-08-10T08:30:00Z",
        "2026-08-10T08:45:00Z", "2026-08-10T09:00:00Z",
    ], heat_index_f=102.0)
    st3 = evaluate_episode(episode["id"])["status"]
    site = create_site()
    sa = designate_site(episode["id"], site["id"])
    lead1, lead2 = _register_leads()
    add_overnight_lead_coverage(sa["id"], lead1["id"], lead2["id"])
    st4 = activate_episode(episode["id"])["status"]
    open_activation(sa["id"], lead1["id"])
    st5 = deactivate_episode(episode["id"])["status"]
    post_breach_run(episode["id"], times=[
        "2026-08-10T14:00:00Z", "2026-08-10T14:15:00Z", "2026-08-10T14:30:00Z",
        "2026-08-10T14:45:00Z", "2026-08-10T15:00:00Z",
    ], heat_index_f=103.0)
    st6 = evaluate_episode(episode["id"])["status"]
    sa_after = get_site_activation(sa["id"])
    return {"episode_id": episode["id"], "site_activation_id": sa["id"],
            "st1": st1, "st2": st2, "st3": st3, "st4": st4, "st5": st5,
            "st6": st6, "sa_status": sa_after["status"]}
