"""Composite setup helpers for multi-step test prerequisites.

The server is restarted before every test, so every helper builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient) so a setup failure surfaces as a clear error.

Identity threading: after a FixerProfile is created, every Fixer-role call in
these helpers uses make_fixer_headers(fixer["id"]) — never the shared constant —
because ownership checks compare X-User-ID to the profile id (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK, EVENT_START, EVENT_END, SHIFT_START, SHIFT_END,
    DEFAULT_INDUCTION,
)
from .factories import (
    create_repair_event_payload, create_station_payload,
    create_fixer_profile_payload, create_fixer_skill_payload,
    create_fixer_shift_payload, create_visitor_payload, create_waiver_payload,
    create_repair_item_payload, create_triage_record_payload,
    create_part_stock_payload, create_part_reservation_payload,
    create_safety_incident_payload, record_outcome_payload,
)
from .test_users import TEST_USERS, make_fixer_headers

COORD = TEST_USERS["coordinator_headers"]
INTAKE = TEST_USERS["intake_volunteer_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


# ─── Atomic steps ───────────────────────────────────────────────────────────

def set_logical_clock(to_iso8601=DEFAULT_CLOCK):
    """Advance the logical clock (Coordinator-only, PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, COORD))


def create_event(name="Repair Cafe", starts_at=EVENT_START, ends_at=EVENT_END,
                 intake_item_cap=5):
    return get_success_data(api_client.create_repair_event(
        create_repair_event_payload(name=name, starts_at=starts_at,
                                    ends_at=ends_at, intake_item_cap=intake_item_cap),
        COORD))


def create_station(event_id, category="ELECTRONICS", label="E1", capacity=1):
    return get_success_data(api_client.create_station(
        create_station_payload(event_id, category=category, label=label,
                               capacity=capacity), COORD))


def register_fixer(display_name="Fixer A", email=None,
                   induction=DEFAULT_INDUCTION):
    overrides = {"display_name": display_name,
                 "safety_induction_completed_at": induction}
    if email is not None:
        overrides["email"] = email
    return get_success_data(api_client.create_fixer_profile(
        create_fixer_profile_payload(**overrides), COORD))


def add_skill(fixer_id, category="ELECTRONICS", level=4):
    return get_success_data(api_client.create_fixer_skill(
        create_fixer_skill_payload(fixer_id, category=category, level=level), COORD))


def sign_up_shift(fixer_id, station_id, event_id,
                  start_time=SHIFT_START, end_time=SHIFT_END):
    return get_success_data(api_client.create_fixer_shift(
        create_fixer_shift_payload(fixer_id, station_id, event_id,
                                   start_time=start_time, end_time=end_time),
        COORD))


def confirm_shift(shift_id):
    return get_success_data(api_client.confirm_shift(shift_id, COORD))


def check_in_shift(shift_id, fixer_id):
    """Check in as the owning fixer (entity-backed identity)."""
    return get_success_data(api_client.check_in_shift(
        shift_id, make_fixer_headers(fixer_id)))


def check_out_shift(shift_id, fixer_id, completion=True):
    return get_success_data(api_client.check_out_shift(
        shift_id, completion, make_fixer_headers(fixer_id)))


def publish_event(event_id):
    return get_success_data(api_client.publish_event(event_id, COORD))


def open_station(station_id):
    return get_success_data(api_client.open_station(station_id, COORD))


def pause_station(station_id):
    return get_success_data(api_client.pause_station(station_id, COORD))


def resume_station(station_id):
    return get_success_data(api_client.resume_station(station_id, COORD))


def open_intake(event_id):
    return get_success_data(api_client.open_intake(event_id, COORD))


def begin_repairs(event_id):
    return get_success_data(api_client.begin_repairs(event_id, COORD))


def close_event(event_id):
    return get_success_data(api_client.close_event(event_id, COORD))


def cancel_event(event_id):
    return get_success_data(api_client.cancel_event(event_id, COORD))


def register_visitor(full_name="Visitor One", email=None):
    overrides = {"full_name": full_name}
    if email is not None:
        overrides["email"] = email
    return get_success_data(api_client.create_visitor(
        create_visitor_payload(**overrides), INTAKE))


def sign_waiver(visitor_id, safety_clause=True):
    return get_success_data(api_client.create_waiver(
        create_waiver_payload(visitor_id, safety_clause_accepted=safety_clause),
        INTAKE))


def intake_item(event_id, visitor_id, category="ELECTRONICS",
                description="Broken device", weight_kg_estimated=3.0,
                hazard_flag=None):
    overrides = {"category": category, "description": description,
                 "weight_kg_estimated": weight_kg_estimated}
    if hazard_flag is not None:
        overrides["hazard_flag"] = hazard_flag
    return get_success_data(api_client.create_repair_item(
        create_repair_item_payload(event_id, visitor_id, **overrides), INTAKE))


def triage_item(item_id, fixer_id, severity=3, estimated_difficulty=2,
                diagnosis="diagnosis"):
    """Create a triage record with the item's CURRENT version (fresh OCC read)."""
    item = get_success_data(api_client.get_repair_item(item_id, COORD))
    return get_success_data(api_client.create_triage_record(
        item_id,
        create_triage_record_payload(item["version"], severity=severity,
                                     estimated_difficulty=estimated_difficulty,
                                     diagnosis=diagnosis),
        make_fixer_headers(fixer_id)))


def enqueue_item(item_id):
    return get_success_data(api_client.enqueue_item(item_id, COORD))


def assign_item(item_id, fixer_id=None, station_id=None):
    """Assign; omitting both ids invokes the auto-selection policy (PRD §3.4)."""
    payload = None
    if fixer_id is not None or station_id is not None:
        payload = {"fixer_id": fixer_id, "station_id": station_id}
    return get_success_data(api_client.assign_item(item_id, payload, COORD))


def start_item_repair(item_id, fixer_id):
    return get_success_data(api_client.start_repair(
        item_id, make_fixer_headers(fixer_id)))


def record_item_outcome(item_id, fixer_id, outcome="FIXED", weight_kg_actual=None):
    return get_success_data(api_client.record_outcome(
        item_id, record_outcome_payload(outcome, weight_kg_actual),
        make_fixer_headers(fixer_id)))


def verify_outcome_as_coordinator(outcome_id):
    return get_success_data(api_client.verify_outcome(outcome_id, COORD))


def make_part_stock(sku=None, name="Spare part", category="ELECTRONICS",
                    unit_cost_cents=400, quantity_on_hand=10):
    overrides = {"name": name, "category": category,
                 "unit_cost_cents": unit_cost_cents,
                 "quantity_on_hand": quantity_on_hand}
    if sku is not None:
        overrides["sku"] = sku
    return get_success_data(api_client.create_part_stock(
        create_part_stock_payload(**overrides), COORD))


def reserve_part(part_stock_id, repair_item_id, quantity, fixer_id):
    return get_success_data(api_client.create_part_reservation(
        create_part_reservation_payload(part_stock_id, repair_item_id,
                                        quantity=quantity),
        make_fixer_headers(fixer_id)))


def commit_reservation(reservation_id, fixer_id):
    return get_success_data(api_client.commit_reservation(
        reservation_id, make_fixer_headers(fixer_id)))


def release_reservation(reservation_id, fixer_id):
    return get_success_data(api_client.release_reservation(
        reservation_id, make_fixer_headers(fixer_id)))


def report_incident(event_id, severity="LOW", description="incident",
                    item_id=None, fixer_id=None, headers=None):
    overrides = {"severity": severity, "description": description}
    if item_id is not None:
        overrides["item_id"] = item_id
    if fixer_id is not None:
        overrides["fixer_id"] = fixer_id
    return get_success_data(api_client.create_safety_incident(
        create_safety_incident_payload(event_id, **overrides),
        headers or COORD))


# ─── Tier 1/2 composite: event with open station and checked-in fixer ───────

def setup_published_event_with_checked_in_fixer(
        category="ELECTRONICS", capacity=1, skill_level=4,
        clock=DEFAULT_CLOCK, event_name="Repair Cafe",
        starts_at=EVENT_START, ends_at=EVENT_END,
        shift_start=SHIFT_START, shift_end=SHIFT_END,
        induction=DEFAULT_INDUCTION, intake_item_cap=5):
    """Clock set; event + station + fixer + skill + shift created; event
    PUBLISHED; shift CONFIRMED then CHECKED_IN as the fixer.
    Returns dict(event, station, fixer, shift)."""
    set_logical_clock(clock)
    event = create_event(name=event_name, starts_at=starts_at, ends_at=ends_at,
                         intake_item_cap=intake_item_cap)
    station = create_station(event["id"], category=category, capacity=capacity)
    fixer = register_fixer(induction=induction)
    add_skill(fixer["id"], category=category, level=skill_level)
    shift = sign_up_shift(fixer["id"], station["id"], event["id"],
                          start_time=shift_start, end_time=shift_end)
    publish_event(event["id"])
    confirm_shift(shift["id"])
    shift = check_in_shift(shift["id"], fixer["id"])
    return {"event": event, "station": station, "fixer": fixer, "shift": shift}


def setup_intake_open_event(category="ELECTRONICS", capacity=1, skill_level=4,
                            clock=DEFAULT_CLOCK, event_name="Repair Cafe",
                            intake_item_cap=5, **kwargs):
    """Published event whose station is OPEN and whose intake is open — the
    event is posture-ACCEPTING (PRD §2.9). Adds visitor + safety waiver.
    Returns dict(event, station, fixer, shift, visitor, waiver)."""
    ctx = setup_published_event_with_checked_in_fixer(
        category=category, capacity=capacity, skill_level=skill_level,
        clock=clock, event_name=event_name, intake_item_cap=intake_item_cap,
        **kwargs)
    open_station(ctx["station"]["id"])
    open_intake(ctx["event"]["id"])
    visitor = register_visitor()
    waiver = sign_waiver(visitor["id"], safety_clause=True)
    ctx["visitor"] = visitor
    ctx["waiver"] = waiver
    return ctx


# ─── Tier 3: item lifecycle shortcuts ───────────────────────────────────────

def progress_item_to_queued(ctx, category=None, description="Broken device",
                            weight_kg_estimated=3.0, severity=3,
                            estimated_difficulty=2, hazard_flag=None,
                            diagnosis="diagnosis"):
    """Intake → triage → enqueue. Returns the QUEUED item (freshly read)."""
    category = category or ctx["station"]["category"]
    item = intake_item(ctx["event"]["id"], ctx["visitor"]["id"],
                       category=category, description=description,
                       weight_kg_estimated=weight_kg_estimated,
                       hazard_flag=hazard_flag)
    triage_item(item["id"], ctx["fixer"]["id"], severity=severity,
                estimated_difficulty=estimated_difficulty, diagnosis=diagnosis)
    enqueue_item(item["id"])
    return get_success_data(api_client.get_repair_item(item["id"], COORD))


def progress_item_to_assigned(ctx, **kwargs):
    """… → QUEUED → ASSIGNED (auto-select). Returns the ASSIGNED item."""
    item = progress_item_to_queued(ctx, **kwargs)
    assign_item(item["id"])
    return get_success_data(api_client.get_repair_item(item["id"], COORD))


def progress_item_to_in_repair(ctx, **kwargs):
    """… → ASSIGNED → IN_REPAIR. Returns the IN_REPAIR item."""
    item = progress_item_to_assigned(ctx, **kwargs)
    start_item_repair(item["id"], ctx["fixer"]["id"])
    return get_success_data(api_client.get_repair_item(item["id"], COORD))


def progress_item_to_outcome_recorded(ctx, outcome="FIXED", weight_kg_actual=3.2,
                                      **kwargs):
    """… → IN_REPAIR → OUTCOME_RECORDED. Returns (item, outcome)."""
    item = progress_item_to_in_repair(ctx, **kwargs)
    outcome_rec = record_item_outcome(item["id"], ctx["fixer"]["id"],
                                      outcome=outcome,
                                      weight_kg_actual=weight_kg_actual)
    item = get_success_data(api_client.get_repair_item(item["id"], COORD))
    return item, outcome_rec


def progress_item_to_verified(ctx, outcome="FIXED", weight_kg_actual=3.2,
                              **kwargs):
    """Full flow through a coordinator-verified outcome. Returns (item, outcome)."""
    item, outcome_rec = progress_item_to_outcome_recorded(
        ctx, outcome=outcome, weight_kg_actual=weight_kg_actual, **kwargs)
    verify_outcome_as_coordinator(outcome_rec["id"])
    item = get_success_data(api_client.get_repair_item(item["id"], COORD))
    outcome_rec = get_success_data(api_client.get_outcome(outcome_rec["id"], COORD))
    return item, outcome_rec
