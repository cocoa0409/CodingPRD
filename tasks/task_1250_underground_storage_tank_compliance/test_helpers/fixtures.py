"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

All helpers use get_success_data() so a broken precondition surfaces as a clear
setup failure. Identity threading follows PRD §2.1: owner-gated calls use the
owning account id; technician-gated calls use make_technician_headers(tech id);
certify uses make_reviewer_headers(reviewer tech id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_facility_payload, create_tank_payload, create_component_payload,
    create_technician_payload, create_service_order_payload, create_record_payload,
    create_submission_payload, create_operator_payload, create_training_record_payload,
    create_release_event_payload, create_fund_claim_payload,
    tightness_readings, cp_readings, cp_divergence_readings,
)
from .test_users import TEST_USERS, make_owner_headers, make_technician_headers, make_reviewer_headers

ADMIN = TEST_USERS["contractor_admin_headers"]
REGULATOR = TEST_USERS["state_regulator_headers"]
READER = TEST_USERS["any_headers"]
DEFAULT_OWNER = "owner-1"


# ---------------------------------------------------------------------------
# Tier 0: clock + single-resource creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Drive the server logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_facility(owner_id: str = DEFAULT_OWNER, **overrides) -> dict:
    res = api_client.create_facility(create_facility_payload(**overrides),
                                     make_owner_headers(owner_id))
    return get_success_data(res)


def create_tank(facility_id: str, owner_id: str = DEFAULT_OWNER, **overrides) -> dict:
    res = api_client.create_tank_system(create_tank_payload(facility_id, **overrides),
                                        make_owner_headers(owner_id))
    return get_success_data(res)


def add_component(tank_id: str, component_type: str = "CATHODIC_PROTECTION",
                  owner_id: str = DEFAULT_OWNER, **overrides) -> dict:
    res = api_client.create_component(
        create_component_payload(tank_id, component_type=component_type, **overrides),
        make_owner_headers(owner_id))
    return get_success_data(res)


def create_technician(endorsements=(), trainer: bool = False,
                      full_name: str = "Field Tech") -> dict:
    res = api_client.create_technician(
        create_technician_payload(full_name=full_name,
                                  endorsements=list(endorsements), trainer=trainer),
        ADMIN)
    return get_success_data(res)


def create_order(facility_id: str, tank_id: str, service_type: str,
                 component_id=None, linked_deficiency_id=None,
                 line_items=None) -> dict:
    overrides = {}
    if component_id is not None:
        overrides["component_id"] = component_id
    if linked_deficiency_id is not None:
        overrides["linked_deficiency_id"] = linked_deficiency_id
    if line_items is not None:
        overrides["line_items"] = line_items
    res = api_client.create_service_order(
        create_service_order_payload(facility_id, tank_id, service_type, **overrides),
        ADMIN)
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def activate_facility(facility_id: str, owner_id: str = DEFAULT_OWNER) -> dict:
    return get_success_data(
        api_client.activate_facility(facility_id, make_owner_headers(owner_id)))


def place_tank_in_service(tank_id: str, owner_id: str = DEFAULT_OWNER) -> dict:
    return get_success_data(
        api_client.place_in_service(tank_id, make_owner_headers(owner_id)))


def setup_active_facility_with_tank(owner_id: str = DEFAULT_OWNER,
                                    facility_overrides=None, tank_overrides=None):
    """Facility REGISTERED -> ACTIVE + one tank REGISTERED -> IN_SERVICE.
    Returns (facility, tank) re-read after activation."""
    facility = create_facility(owner_id, **(facility_overrides or {}))
    tank = create_tank(facility["id"], owner_id, **(tank_overrides or {}))
    facility = activate_facility(facility["id"], owner_id)
    tank = place_tank_in_service(tank["id"], owner_id)
    return facility, tank


def schedule_order(order_id: str, technician_id: str,
                   window_start: str, window_end: str) -> dict:
    """REQUESTED -> SCHEDULED with an explicit half-open window (PRD §3.3)."""
    res = api_client.schedule_service_order(
        order_id,
        {"technician_id": technician_id,
         "window_start": window_start, "window_end": window_end},
        ADMIN)
    return get_success_data(res)


def start_order(order_id: str, technician_id: str, at_iso: str) -> dict:
    """Move the clock inside the window, then start as the assigned technician."""
    set_clock(at_iso)
    res = api_client.start_service_order(order_id, make_technician_headers(technician_id))
    return get_success_data(res)


def schedule_and_start(order_id: str, technician_id: str, window_start: str,
                       window_end: str, at_iso: str) -> dict:
    schedule_order(order_id, technician_id, window_start, window_end)
    return start_order(order_id, technician_id, at_iso)


def record_results(order_id: str, technician_id: str, readings: dict) -> dict:
    """IN_PROGRESS -> UNDER_REVIEW as the performing technician (PRD §3.4)."""
    res = api_client.record_results(order_id, {"readings": readings},
                                    make_technician_headers(technician_id))
    return get_success_data(res)


def certify_order(order_id: str, reviewer_technician_id: str) -> dict:
    """UNDER_REVIEW -> CERTIFIED as a reviewer != performer (PRD §3.5)."""
    res = api_client.certify_service_order(
        order_id, make_reviewer_headers(reviewer_technician_id))
    return get_success_data(res)


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_service_order(order_id, READER))


def get_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, READER))


def get_tank(tank_id: str) -> dict:
    return get_success_data(api_client.get_tank_system(tank_id, READER))


def get_component(component_id: str) -> dict:
    return get_success_data(api_client.get_component(component_id, READER))


def get_deficiency(deficiency_id: str) -> dict:
    return get_success_data(api_client.get_deficiency(deficiency_id, READER))


def get_release(release_id: str) -> dict:
    return get_success_data(api_client.get_release_event(release_id, READER))


def latest_result_record(order_id: str) -> dict:
    """The order's result ledger lists oldest first (PRD §3.5); take the last."""
    res = api_client.list_result_records(READER, params={"service_order_id": order_id})
    body = res.json()
    items = body["data"]
    assert items, f"expected at least one ResultRecord for order {order_id}"
    return items[-1]


def deficiency_for_order(order_id: str) -> dict:
    """The deficiency whose source_service_order_id is the given order."""
    res = api_client.list_deficiencies(READER, params={"source_service_order_id": order_id})
    items = res.json()["data"]
    assert len(items) == 1, f"expected exactly one deficiency for order {order_id}"
    return items[0]


# ---------------------------------------------------------------------------
# Tier 2/3: field-work composites
# ---------------------------------------------------------------------------

def setup_cp_site(owner_id: str = DEFAULT_OWNER, facility_overrides=None,
                  tank_overrides=None) -> dict:
    """ACTIVE facility + IN_SERVICE tank carrying a CATHODIC_PROTECTION component,
    plus a CP-endorsed tester and a reviewer technician. Returns a context dict."""
    facility, tank = setup_active_facility_with_tank(owner_id, facility_overrides, tank_overrides)
    comp = add_component(tank["id"], "CATHODIC_PROTECTION", owner_id, serial_no="CP-1")
    t_cp = create_technician(["CP_TESTER"], full_name="CP Tester")
    t_rev = create_technician([], full_name="Reviewer")
    return {"facility": facility, "tank": tank, "component": comp,
            "tester": t_cp, "reviewer": t_rev, "owner_id": owner_id}


def create_started_order(ctx: dict, service_type: str, window_start: str,
                         window_end: str, at_iso: str, component_id=None,
                         linked_deficiency_id=None, line_items=None,
                         tester_id=None) -> dict:
    """Create -> schedule -> start an order inside its window. Returns the
    IN_PROGRESS order."""
    tech_id = tester_id or ctx["tester"]["id"]
    order = create_order(ctx["facility"]["id"], ctx["tank"]["id"], service_type,
                         component_id=component_id,
                         linked_deficiency_id=linked_deficiency_id,
                         line_items=line_items)
    schedule_and_start(order["id"], tech_id, window_start, window_end, at_iso)
    return get_order(order["id"])


def setup_started_cp_order(owner_id: str = DEFAULT_OWNER,
                           window_start="2026-05-02T10:00:00Z",
                           window_end="2026-05-02T11:00:00Z",
                           at_iso="2026-05-02T10:30:00Z") -> dict:
    """CP site with one CP_SURVEY order started inside its window."""
    ctx = setup_cp_site(owner_id)
    ctx["order"] = create_started_order(
        ctx, "CP_SURVEY", window_start, window_end, at_iso,
        component_id=ctx["component"]["id"],
        line_items=[{"description": "cp", "qty": 1, "unit_price_cents": 40000}])
    return ctx


def setup_failed_cp_order(owner_id: str = DEFAULT_OWNER) -> dict:
    """CP site whose CP_SURVEY order FAILed (-800 > -850 under INSTANT_OFF):
    opens a MAJOR TEST_FAILURE deficiency and moves the component DEFICIENT.
    Context gains: order, deficiency."""
    ctx = setup_started_cp_order(owner_id)
    record_results(ctx["order"]["id"], ctx["tester"]["id"],
                   cp_divergence_readings("INSTANT_OFF"))
    ctx["order"] = get_order(ctx["order"]["id"])
    ctx["deficiency"] = deficiency_for_order(ctx["order"]["id"])
    return ctx


def setup_corrected_deficiency(owner_id: str = DEFAULT_OWNER) -> dict:
    """Failed CP order, deficiency driven OPEN -> CORRECTION_ORDERED -> CORRECTED."""
    ctx = setup_failed_cp_order(owner_id)
    owner = make_owner_headers(ctx["owner_id"])
    get_success_data(api_client.order_correction(ctx["deficiency"]["id"], owner))
    corrected = get_success_data(api_client.mark_corrected(ctx["deficiency"]["id"], owner))
    ctx["deficiency"] = corrected
    return ctx


def setup_tightness_site(owner_id: str = DEFAULT_OWNER) -> dict:
    """ACTIVE facility + IN_SERVICE tank (no components) + TIGHTNESS_TESTER."""
    facility, tank = setup_active_facility_with_tank(owner_id)
    t_tt = create_technician(["TIGHTNESS_TESTER"], full_name="Tightness Tester")
    return {"facility": facility, "tank": tank, "tester": t_tt, "owner_id": owner_id}


def setup_started_tightness_order(owner_id: str = DEFAULT_OWNER,
                                  service_type="TANK_TIGHTNESS",
                                  window_start="2026-05-02T10:00:00Z",
                                  window_end="2026-05-02T11:00:00Z",
                                  at_iso="2026-05-02T10:30:00Z") -> dict:
    """Tightness site with one order started inside its window."""
    ctx = setup_tightness_site(owner_id)
    ctx["order"] = create_started_order(
        ctx, service_type, window_start, window_end, at_iso,
        line_items=[{"description": "tightness", "qty": 1, "unit_price_cents": 60000}])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2/3: releases and fund claims
# ---------------------------------------------------------------------------

def setup_confirmed_release_site(owner_id: str = DEFAULT_OWNER,
                                 election: str = "PER_OCCURRENCE",
                                 fees_through: str = "2027-01-01T00:00:00Z") -> dict:
    """ACTIVE facility (given fund election, fees current) with a tank in service
    and a tank-less release already CONFIRMED by the regulator (PRD §3.8)."""
    facility, tank = setup_active_facility_with_tank(
        owner_id,
        facility_overrides={"annual_fee_paid_through": fees_through,
                            "fund_program_election": election},
        tank_overrides={"substance": "GASOLINE", "capacity_gallons": 8000,
                        "tank_construction": "FRP", "piping_type": "SUCTION"})
    owner = make_owner_headers(owner_id)
    release = get_success_data(api_client.create_release_event(
        create_release_event_payload(facility["id"]), owner))
    release = get_success_data(api_client.confirm_release(release["id"], REGULATOR))
    return {"facility": facility, "tank": tank, "release": release, "owner_id": owner_id}


def create_draft_claim(facility_id: str, release_id: str, amount_cents: int,
                       owner_id: str = DEFAULT_OWNER) -> dict:
    res = api_client.create_fund_claim(
        create_fund_claim_payload(
            facility_id, release_id,
            expense_lines=[{"description": "cleanup", "amount_cents": amount_cents}]),
        make_owner_headers(owner_id))
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2/3: records, submissions, operators
# ---------------------------------------------------------------------------

def create_record(tank_id: str, period_month: str, owner_id: str = DEFAULT_OWNER,
                  **overrides) -> dict:
    res = api_client.create_release_detection_record(
        create_record_payload(tank_id, period_month, **overrides),
        make_owner_headers(owner_id))
    return get_success_data(res)


def create_monthly_submission(facility_id: str, period_month: str, record_ids,
                              reviewer_id: str) -> dict:
    res = api_client.create_submission(
        create_submission_payload(
            facility_id, "MONTHLY_RELEASE_DETECTION",
            period_month=period_month,
            release_detection_record_ids=list(record_ids)),
        make_reviewer_headers(reviewer_id))
    return get_success_data(res)


def create_operator(facility_id: str, operator_class: str = "A",
                    owner_id: str = DEFAULT_OWNER, **overrides) -> dict:
    res = api_client.create_operator(
        create_operator_payload(facility_id, operator_class=operator_class, **overrides),
        make_owner_headers(owner_id))
    return get_success_data(res)


def issue_training(operator_id: str, course_class: str, completed_at: str,
                   trainer_technician_id: str) -> dict:
    res = api_client.create_training_record(
        create_training_record_payload(operator_id, course_class,
                                       completed_at=completed_at),
        make_technician_headers(trainer_technician_id))
    return get_success_data(res)
