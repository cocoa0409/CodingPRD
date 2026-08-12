"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so no state is
ever carried over). Setup calls use the lenient get_success_data() validator
so failures surface as clear setup errors.

Common idioms:
- The logical clock starts at exactly 2026-05-01T00:00:00Z and never falls
  back to wall-clock (PRD section 2.5).
- Ownership-gated calls always use make_district_admin_headers(district_id) /
  make_driver_headers(driver_id), never the shared constants.
- List endpoints sort by created_at ascending, so the assignments of a service
  day come back in route-creation order.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_bus_payload,
    create_charter_trip_payload,
    create_contract_payload,
    create_credential_payload,
    create_district_payload,
    create_driver_payload,
    create_fuel_price_entry_payload,
    create_incident_payload,
    create_inspection_payload,
    create_ridership_report_payload,
    create_route_payload,
    create_service_day_payload,
    create_training_event_payload,
    create_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_district_admin_headers,
    make_driver_headers,
)

SYSADMIN = TEST_USERS["system_admin_headers"]
OPS = TEST_USERS["contractor_ops_headers"]
HR = TEST_USERS["hr_recruiter_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]

DEFAULT_SERVICE_DATE = "2026-06-01"


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation / state progression
# ---------------------------------------------------------------------------

def create_district(**overrides):
    """Create a district as SystemAdmin. Returns the district dict."""
    return get_success_data(api_client.create_district(create_district_payload(**overrides), SYSADMIN))


def set_clock(to_iso8601):
    """Advance the logical clock. Returns {current_utc}."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, SYSADMIN))


def create_contract(district_id, **overrides):
    """Create a contract in DRAFT_BID. Returns the contract dict."""
    return get_success_data(api_client.create_contract(create_contract_payload(district_id, **overrides), OPS))


def create_active_contract(district_id, **overrides):
    """Create a contract and walk DRAFT_BID -> SUBMITTED -> AWARDED -> ACTIVE.
    The award is posted by the owning district admin (entity-backed identity).
    Returns the ACTIVE contract dict."""
    contract = create_contract(district_id, **overrides)
    get_success_data(api_client.submit_contract(contract["id"], OPS))
    get_success_data(api_client.award_contract(contract["id"], make_district_admin_headers(district_id)))
    return get_success_data(api_client.activate_contract(contract["id"], OPS))


def create_route(contract_id, **overrides):
    """Create a route (born ACTIVE). Returns the route dict."""
    return get_success_data(api_client.create_route(create_route_payload(contract_id, **overrides), OPS))


def create_driver_applicant(district_id, **overrides):
    """Create a driver record (born APPLICANT). Returns the driver dict."""
    return get_success_data(api_client.create_driver(create_driver_payload(district_id, **overrides), HR))


def post_driver_event(driver_id, event_type, **extra):
    payload = {"event_type": event_type}
    payload.update(extra)
    return get_success_data(api_client.post_driver_event(driver_id, payload, HR))


def log_training(driver_id, category, minutes, occurred_on="2026-04-01"):
    return get_success_data(api_client.create_training_event(
        create_training_event_payload(driver_id, category=category, minutes=minutes,
                                      occurred_on=occurred_on), HR))


def advance_driver_to_testing(driver_id, behind_wheel_minutes=2400, classroom_minutes=1200):
    """APPLICANT -> SCREENING -> TRAINING, log training hours, SCHEDULE_TEST ->
    TESTING. Returns the TESTING driver dict."""
    post_driver_event(driver_id, "SCREEN")
    post_driver_event(driver_id, "ENROLL")
    if behind_wheel_minutes:
        log_training(driver_id, "BEHIND_WHEEL", behind_wheel_minutes)
    if classroom_minutes:
        log_training(driver_id, "CLASSROOM", classroom_minutes, occurred_on="2026-04-02")
    return post_driver_event(driver_id, "SCHEDULE_TEST")


def create_credential(driver_id, kind, issued_on="2026-04-10", expires_on="2027-01-01"):
    return get_success_data(api_client.create_credential(
        create_credential_payload(driver_id, kind=kind, issued_on=issued_on,
                                  expires_on=expires_on), HR))


def certify_driver(driver_id, cdl_expires_on="2027-01-01"):
    """Record CDL_B and TEST_PASS: TESTING -> CERTIFIED. Returns driver dict."""
    create_credential(driver_id, "CDL_B", expires_on=cdl_expires_on)
    return post_driver_event(driver_id, "TEST_PASS")


def activate_driver(driver_id, s_endorsement_expires_on="2027-01-01"):
    """Record S_ENDORSEMENT and ACTIVATE: CERTIFIED -> ACTIVE. Returns driver dict."""
    create_credential(driver_id, "S_ENDORSEMENT", issued_on="2026-04-15",
                      expires_on=s_endorsement_expires_on)
    return post_driver_event(driver_id, "ACTIVATE")


def create_active_driver(district_id, behind_wheel_minutes=2400, classroom_minutes=1200,
                         cdl_expires_on="2027-01-01", s_endorsement_expires_on="2027-01-01",
                         **overrides):
    """Full pipeline to ACTIVE with both credentials. Returns the ACTIVE driver."""
    driver = create_driver_applicant(district_id, **overrides)
    advance_driver_to_testing(driver["id"], behind_wheel_minutes, classroom_minutes)
    certify_driver(driver["id"], cdl_expires_on=cdl_expires_on)
    return activate_driver(driver["id"], s_endorsement_expires_on=s_endorsement_expires_on)


def suspend_driver(driver_id, reason="Discipline"):
    return get_success_data(api_client.post_driver_discipline(
        driver_id, {"action": "SUSPEND", "reason": reason}, OPS))


def reinstate_driver(driver_id):
    return api_client.post_driver_discipline(driver_id, {"action": "REINSTATE"}, OPS)


def create_bus(district_id, **overrides):
    """Register a bus (born IN_SERVICE). Returns the bus dict."""
    return get_success_data(api_client.create_bus(create_bus_payload(district_id, **overrides), FLEET))


def create_work_order(bus_id, **overrides):
    """Open a work order (bus -> IN_SHOP). Returns the work order dict."""
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(bus_id, **overrides), FLEET))


def post_work_order_event(work_order_id, event_type, **extra):
    payload = {"event_type": event_type}
    payload.update(extra)
    return get_success_data(api_client.post_work_order_event(work_order_id, payload, FLEET))


def create_inspection(bus_id, **overrides):
    """Schedule an inspection (born SCHEDULED). Returns the inspection dict."""
    return get_success_data(api_client.create_inspection(
        create_inspection_payload(bus_id, **overrides), FLEET))


# ---------------------------------------------------------------------------
# Tier 2: service-day construction and dispatch plumbing
# ---------------------------------------------------------------------------

def create_service_day(contract_id, service_date):
    """Create a service day (born SCHEDULED; auto-creates one PLANNED assignment
    per ACTIVE route). Returns the day dict."""
    return get_success_data(api_client.create_service_day(
        create_service_day_payload(contract_id, service_date), OPS))


def open_service_day(service_day_id):
    """SCHEDULED -> DISPATCH_OPEN. Returns the day dict."""
    return get_success_data(api_client.open_dispatch(service_day_id, OPS))


def get_day_assignments(service_day_id):
    """Assignments of the day, created_at ascending (route creation order)."""
    rows, _meta = validate_paginated(
        api_client.list_assignments(OPS, params={"service_day_id": service_day_id}))
    return rows


def confirm_assignment(assignment_id, driver_id, bus_id):
    """PLANNED -> CONFIRMED with driver+bus. Returns the assignment dict."""
    return get_success_data(api_client.confirm_assignment(
        assignment_id, {"driver_id": driver_id, "bus_id": bus_id}, OPS))


def run_assignment(assignment_id, driver_id, actual_start_minute, actual_end_minute,
                   actual_miles):
    """Driver self-service CONFIRMED -> EN_ROUTE -> COMPLETED with actuals.
    Returns the COMPLETED assignment dict."""
    driver_headers = make_driver_headers(driver_id)
    get_success_data(api_client.start_assignment(assignment_id, driver_headers))
    return get_success_data(api_client.complete_assignment(
        assignment_id, {"actual_start_minute": actual_start_minute,
                        "actual_end_minute": actual_end_minute,
                        "actual_miles": actual_miles}, driver_headers))


def lock_service_day(service_day_id):
    """DISPATCH_OPEN -> LOCKED with a fresh OCC read of the day version."""
    day = get_success_data(api_client.get_service_day(service_day_id, OPS))
    return get_success_data(api_client.lock_service_day(
        service_day_id, {"expected_service_day_version": day["version"]}, OPS))


def reconcile_service_day(service_day_id):
    """LOCKED -> RECONCILED. Returns the day dict."""
    return get_success_data(api_client.reconcile_service_day(service_day_id, OPS))


def build_service_day(contract_id, service_date, driver_id=None, bus_id=None,
                      run_miles=None, lock=False, reconcile=False):
    """Create + open a service day; optionally confirm every assignment to
    driver/bus; optionally run each to COMPLETED with run_miles (actual window
    = planned window); optionally lock; optionally reconcile.
    Returns (day_dict_refreshed, assignments_as_listed_after_open)."""
    day = create_service_day(contract_id, service_date)
    open_service_day(day["id"])
    assignments = get_day_assignments(day["id"])
    if driver_id is not None:
        for a in assignments:
            confirm_assignment(a["id"], driver_id, bus_id)
            if run_miles is not None:
                run_assignment(a["id"], driver_id, a["planned_start_minute"],
                               a["planned_end_minute"], run_miles)
    if lock:
        lock_service_day(day["id"])
    if reconcile:
        reconcile_service_day(day["id"])
    day = get_success_data(api_client.get_service_day(day["id"], OPS))
    return day, assignments


# ---------------------------------------------------------------------------
# Tier 3: full operations context (district + contract + routes + driver + bus)
# ---------------------------------------------------------------------------

def setup_ops_scenario(district_name="D-OPS", district_overrides=None,
                       contract_overrides=None, routes=((420, 480, 40),),
                       with_driver=True, with_bus=True, driver_overrides=None,
                       bus_overrides=None):
    """District + ACTIVE contract + routes (list of (am_start, am_end,
    student_count) tuples created in order) + optionally one ACTIVE driver and
    one bus. Returns a ctx dict."""
    district = create_district(name=district_name, **(district_overrides or {}))
    contract = create_active_contract(district["id"], **(contract_overrides or {}))
    route_objs = []
    for i, (start, end, students) in enumerate(routes, start=1):
        route_objs.append(create_route(
            contract["id"], route_code=f"R{i}", am_start_minute=start,
            am_end_minute=end, student_count=students))
    driver = create_active_driver(district["id"], **(driver_overrides or {})) if with_driver else None
    bus = create_bus(district["id"], **(bus_overrides or {})) if with_bus else None
    return {"district": district, "contract": contract, "routes": route_objs,
            "driver": driver, "bus": bus}


# ---------------------------------------------------------------------------
# Tier 4: billing fixtures (fuel entry, invoice lifecycle)
# ---------------------------------------------------------------------------

def create_fuel_entry(district_id, effective_month="2026-06", avg_price_cents_per_gallon=400,
                      source="EIA"):
    return get_success_data(api_client.create_fuel_price_entry(
        create_fuel_price_entry_payload(
            district_id, effective_month=effective_month,
            avg_price_cents_per_gallon=avg_price_cents_per_gallon, source=source), FINANCE))


def generate_invoice(contract_id, period_month="2026-06"):
    return get_success_data(api_client.generate_invoice(
        {"contract_id": contract_id, "period_month": period_month}, FINANCE))


def issue_invoice(invoice_id):
    return get_success_data(api_client.issue_invoice(invoice_id, FINANCE))


def setup_billing_scenario(district_name="D-BILL", district_overrides=None,
                           contract_overrides=None, routes=((420, 480, 40),),
                           mpg_x10=80, fuel_price=400, period_month="2026-06",
                           completed_days=(("2026-06-01", 60),),
                           locked_days=(), with_fuel_entry=True,
                           issue=False, issue_clock=None, num_invoices=1):
    """Billing-ready fixture: ops context; each (date, miles) in completed_days
    becomes a fully-run, locked, reconciled day; each date in locked_days
    becomes a confirmed, LOCKED, unreconciled day; fuel entry recorded (unless
    disabled); DRAFT invoice(s) generated for period_month; optionally the
    clock is moved and the invoice(s) issued.
    Returns a ctx dict with keys: district, contract, routes, driver, bus,
    reconciled_days, locked_days, invoices, issued."""
    ctx = setup_ops_scenario(
        district_name=district_name, district_overrides=district_overrides,
        contract_overrides=contract_overrides, routes=routes,
        bus_overrides={"mpg_x10": mpg_x10})
    driver_id = ctx["driver"]["id"]
    bus_id = ctx["bus"]["id"]
    reconciled = []
    for date, miles in completed_days:
        day, _asgs = build_service_day(ctx["contract"]["id"], date, driver_id, bus_id,
                                       run_miles=miles, lock=True, reconcile=True)
        reconciled.append(day)
    locked = []
    for date in locked_days:
        day, _asgs = build_service_day(ctx["contract"]["id"], date, driver_id, bus_id,
                                       lock=True)
        locked.append(day)
    if with_fuel_entry:
        create_fuel_entry(ctx["district"]["id"], period_month, fuel_price)
    invoices = [generate_invoice(ctx["contract"]["id"], period_month)
                for _ in range(num_invoices)]
    if issue:
        if issue_clock is not None:
            set_clock(issue_clock)
        invoices = [issue_invoice(inv["id"]) for inv in invoices]
    ctx.update({"reconciled_days": reconciled, "locked_days": locked,
                "invoices": invoices, "issued": issue})
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: charter lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_charter(contract_id, district_id, **overrides):
    """District requests a charter (born REQUESTED) as the owning district."""
    return get_success_data(api_client.create_charter_trip(
        create_charter_trip_payload(contract_id, **overrides),
        make_district_admin_headers(district_id)))


def quote_charter(charter_id):
    """REQUESTED -> QUOTED; sets quote_price_cents and quote_valid_until."""
    return get_success_data(api_client.quote_charter(charter_id, OPS))


def approve_charter(charter_id, district_id, deposit_cents=0):
    """QUOTED -> APPROVED with a fresh OCC read of the trip version."""
    charter = get_success_data(api_client.get_charter_trip(charter_id, OPS))
    return get_success_data(api_client.approve_charter(
        charter_id, {"expected_charter_trip_version": charter["version"],
                     "deposit_cents": deposit_cents},
        make_district_admin_headers(district_id)))


def create_quoted_charter(contract_id, district_id, **overrides):
    charter = create_charter(contract_id, district_id, **overrides)
    return quote_charter(charter["id"])


def create_approved_charter(contract_id, district_id, deposit_cents=0, **overrides):
    charter = create_quoted_charter(contract_id, district_id, **overrides)
    return approve_charter(charter["id"], district_id, deposit_cents=deposit_cents)


def schedule_charter(charter_id, bus_id, driver_id=None):
    payload = {"assigned_bus_id": bus_id}
    if driver_id is not None:
        payload["assigned_driver_id"] = driver_id
    return get_success_data(api_client.schedule_charter(charter_id, payload, OPS))


def create_scheduled_charter(contract_id, district_id, bus_id, deposit_cents=0,
                             driver_id=None, **overrides):
    charter = create_approved_charter(contract_id, district_id,
                                      deposit_cents=deposit_cents, **overrides)
    return schedule_charter(charter["id"], bus_id, driver_id=driver_id)


def create_completed_charter(contract_id, district_id, bus_id, actual_hours_x10,
                             actual_miles, deposit_cents=0, **overrides):
    """Drive a charter REQUESTED -> ... -> COMPLETED with actuals."""
    charter = create_scheduled_charter(contract_id, district_id, bus_id,
                                       deposit_cents=deposit_cents, **overrides)
    get_success_data(api_client.start_charter(charter["id"], OPS))
    return get_success_data(api_client.complete_charter(
        charter["id"], {"actual_hours_x10": actual_hours_x10,
                        "actual_miles": actual_miles}, OPS))


# ---------------------------------------------------------------------------
# Tier 6: incidents and ridership
# ---------------------------------------------------------------------------

def create_incident(district_id, **overrides):
    """Create an incident (born DRAFT) as ContractorOps."""
    return get_success_data(api_client.create_incident(
        create_incident_payload(district_id, **overrides), OPS))


def create_submitted_incident(district_id, **overrides):
    """DRAFT -> SUBMITTED; stamps submitted_at and district_due_by."""
    incident = create_incident(district_id, **overrides)
    return get_success_data(api_client.submit_incident(incident["id"], OPS))


def create_ridership_report(assignment_id, service_day_id, **overrides):
    return get_success_data(api_client.create_ridership_report(
        create_ridership_report_payload(assignment_id, service_day_id, **overrides), OPS))
