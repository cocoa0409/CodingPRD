"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear "Setup failed"
errors, not confusing assertion failures.

Identity threading: after creating a Customer (entity_backed) or Technician (entity_backed:
FieldTech), every ownership-gated call uses make_customer_headers(customer_id) /
make_field_tech_headers(technician_id) with the owning entity's id — never the shared
TEST_USERS constant (PRD §2.1).

The canonical happy-path chain a visit walks to COMPLETED:
  clock -> customer -> route -> technician -> weather-window -> property -> quote ->
  line-items -> send -> accept -> visit -> schedule(OCC) -> crew-assignment -> confirm ->
  BEFORE photo -> start -> AFTER photo -> complete (auto-issues invoice)
Helpers stop at whatever stage a caller needs and accept overrides for the values tests pin.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_clock_payload, create_customer_payload, create_technician_payload,
    create_route_payload, create_property_payload, create_quote_payload,
    create_line_item_payload, create_plan_payload, generate_visit_payload,
    create_visit_payload, schedule_visit_payload, complete_visit_payload,
    create_assignment_payload, create_weather_window_payload, upload_photo_payload,
    create_claim_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_field_tech_headers
from .constants import (
    FIXTURE_CLOCK_UTC, HIGH_CREDIT_LIMIT_CENTS, DEFAULT_DURATION_MINUTES,
)

DISP = TEST_USERS["dispatcher_headers"]
BILL = TEST_USERS["billing_admin_headers"]

_EMAIL_SEQ = [0]


def _unique_email(prefix="cust"):
    _EMAIL_SEQ[0] += 1
    return f"{prefix}{_EMAIL_SEQ[0]}@example.com"


# ─── clock control ───────────────────────────────────────────────────────────

def set_clock(iso: str = FIXTURE_CLOCK_UTC):
    """Set the logical clock to a fixed instant for deterministic date-gated rules."""
    return get_success_data(api_client.set_clock(create_clock_payload(iso), DISP))


# ─── Tier 1: primitive creators ───────────────────────────────────────────────

def create_customer(**overrides):
    """Create an ACTIVE customer. Defaults to a high credit limit so the fiscal gate is
    never the reason a happy-path fixture fails; pass credit_limit_cents to control it."""
    overrides.setdefault("credit_limit_cents", HIGH_CREDIT_LIMIT_CENTS)
    overrides.setdefault("email", _unique_email())
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), DISP))


def create_technician(**overrides):
    """Create a technician. Defaults: ladder_cert_max_stories 3, insurance ACTIVE."""
    overrides.setdefault("ladder_cert_max_stories", 3)
    overrides.setdefault("insurance_status", "ACTIVE")
    return get_success_data(
        api_client.create_technician(create_technician_payload(**overrides), DISP))


def create_route(**overrides):
    """Create a route. Pass travel_buffer_minutes to control the overlap padding."""
    return get_success_data(api_client.create_route(create_route_payload(**overrides), DISP))


def create_property(customer_id, route_id, **overrides):
    """Create a property under a customer + route."""
    return get_success_data(
        api_client.create_property(create_property_payload(customer_id, route_id, **overrides), DISP))


def create_clear_weather_window(route_id, start="2026-05-01T00:00:00Z",
                                end="2026-05-01T23:59:59Z", wind_mph=5, **overrides):
    """Create a CLEAR weather window covering the given interval on the route."""
    return get_success_data(api_client.create_weather_window(
        create_weather_window_payload(route_id, start, end, wind_mph, **overrides), DISP))


# ─── Tier 2: quote building ────────────────────────────────────────────────────

def create_draft_quote(property_id, property_version, **overrides):
    """Create a DRAFT quote on a property (OCC carries the observed property version)."""
    return get_success_data(api_client.create_quote(
        create_quote_payload(property_id, property_version, **overrides), DISP))


def add_line_item(quote_id, surface_type, service_type, measured_sqft, **overrides):
    """Append a priced line item; server computes chemical_dose_oz + line_total_cents."""
    return get_success_data(api_client.add_line_item(
        quote_id, create_line_item_payload(surface_type, service_type, measured_sqft, **overrides), DISP))


def send_quote(quote_id):
    """Send a DRAFT quote (freezes subtotal/travel/total)."""
    return get_success_data(api_client.send_quote(quote_id, DISP))


def accept_quote(quote_id, customer_id):
    """Owner accepts a SENT quote (ownership-gated → make_customer_headers)."""
    return get_success_data(api_client.accept_quote(quote_id, make_customer_headers(customer_id)))


def setup_accepted_quote(property_overrides=None, soiling_level=None,
                         line_items=None, customer_overrides=None, route_overrides=None):
    """Build an ACCEPTED quote end-to-end and return a context dict.

    line_items: list of (surface_type, service_type, measured_sqft) tuples. Defaults to a
    single ROOF/ROOF_SOFT_WASH 2000-sqft line if omitted.
    Returns: {customer, route, property, quote (accepted), line_item_ids}.
    """
    customer = create_customer(**(customer_overrides or {}))
    route = create_route(**(route_overrides or {}))
    prop = create_property(customer["id"], route["id"], **(property_overrides or {}))
    quote_overrides = {}
    if soiling_level is not None:
        quote_overrides["soiling_level"] = soiling_level
    quote = create_draft_quote(prop["id"], prop["version"], **quote_overrides)
    if line_items is None:
        line_items = [("ROOF", "ROOF_SOFT_WASH", 2000)]
    li_ids = []
    for st, svc, sqft in line_items:
        li = add_line_item(quote["id"], st, svc, sqft)
        li_ids.append(li["id"])
    sent = send_quote(quote["id"])
    accepted = accept_quote(quote["id"], customer["id"])
    return {
        "customer": customer,
        "route": route,
        "property": prop,
        "quote": accepted,
        "sent_quote": sent,
        "line_item_ids": li_ids,
    }


# ─── Tier 3: visit lifecycle ────────────────────────────────────────────────────

def create_visit(property_id, quote_id, scheduled_date="2026-05-01", **overrides):
    """Create a REQUESTED one-off visit against an ACCEPTED quote."""
    overrides.setdefault("duration_minutes", DEFAULT_DURATION_MINUTES)
    return get_success_data(api_client.create_visit(
        create_visit_payload(property_id, quote_id, scheduled_date, **overrides), DISP))


def schedule_visit(visit_id, visit_version):
    """Schedule a REQUESTED visit (OCC, weather + credit gates)."""
    return get_success_data(api_client.schedule_visit(
        visit_id, schedule_visit_payload(visit_version), DISP))


def reserve_crew(visit_id, technician_id, window_start_utc="2026-05-01T14:00:00Z"):
    """Reserve a technician on a SCHEDULED visit (RESERVED assignment)."""
    return get_success_data(api_client.create_assignment(
        create_assignment_payload(visit_id, technician_id, window_start_utc), DISP))


def confirm_crew(assignment_id):
    """Confirm a RESERVED assignment."""
    return get_success_data(api_client.confirm_assignment(assignment_id, DISP))


def upload_photo(visit_id, phase, technician_id):
    """Upload a BEFORE/AFTER photo as the assigned FieldTech (ownership-gated)."""
    return get_success_data(api_client.upload_photo(
        visit_id, upload_photo_payload(phase), make_field_tech_headers(technician_id)))


def start_visit(visit_id, technician_id):
    """Start a SCHEDULED visit (FieldTech)."""
    return get_success_data(api_client.start_visit(visit_id, make_field_tech_headers(technician_id)))


def complete_visit(visit_id, technician_id, re_measured_roof_sqft=0,
                   re_measured_siding_sqft=0, re_measured_concrete_sqft=0):
    """Complete an IN_PROGRESS visit with on-site re-measured areas (auto-issues invoice)."""
    return get_success_data(api_client.complete_visit(
        visit_id,
        complete_visit_payload(re_measured_roof_sqft, re_measured_siding_sqft, re_measured_concrete_sqft),
        make_field_tech_headers(technician_id)))


def setup_scheduled_visit(property_overrides=None, soiling_level=None, line_items=None,
                          customer_overrides=None, route_overrides=None,
                          scheduled_date="2026-05-01", duration_minutes=DEFAULT_DURATION_MINUTES,
                          weather=True, clock=True):
    """Build an ACCEPTED quote + a SCHEDULED visit (no crew yet). Returns a context dict
    including 'technician' and the SCHEDULED visit. Sets the clock and a CLEAR weather window
    covering scheduled_date by default."""
    if clock:
        set_clock()
    ctx = setup_accepted_quote(property_overrides, soiling_level, line_items,
                               customer_overrides, route_overrides)
    if weather:
        ctx["weather_window"] = create_clear_weather_window(ctx["route"]["id"])
    ctx["technician"] = create_technician()
    visit = create_visit(ctx["property"]["id"], ctx["quote"]["id"],
                         scheduled_date=scheduled_date, duration_minutes=duration_minutes)
    scheduled = schedule_visit(visit["id"], visit["version"])
    ctx["visit"] = scheduled
    return ctx


def setup_crewed_scheduled_visit(window_start_utc="2026-05-01T14:00:00Z", confirm=True, **kwargs):
    """setup_scheduled_visit + a crew assignment (CONFIRMED by default). Adds 'assignment'."""
    ctx = setup_scheduled_visit(**kwargs)
    asg = reserve_crew(ctx["visit"]["id"], ctx["technician"]["id"], window_start_utc)
    if confirm:
        asg = confirm_crew(asg["id"])
    ctx["assignment"] = asg
    return ctx


def setup_in_progress_visit(**kwargs):
    """setup_crewed_scheduled_visit + BEFORE photo + start. Visit is IN_PROGRESS."""
    ctx = setup_crewed_scheduled_visit(**kwargs)
    upload_photo(ctx["visit"]["id"], "BEFORE", ctx["technician"]["id"])
    start_visit(ctx["visit"]["id"], ctx["technician"]["id"])
    ctx["before_photo_uploaded"] = True
    return ctx


def setup_completed_visit(re_measured_roof_sqft=None, re_measured_siding_sqft=0,
                          re_measured_concrete_sqft=0, **kwargs):
    """Full happy path to a COMPLETED visit (auto-issues an Invoice). Adds 'completed_visit'
    and 'invoice'. By default the roof re-measure mirrors the single 2000-sqft ROOF line so
    final == provisional unless the caller pins re_measured_* areas."""
    ctx = setup_in_progress_visit(**kwargs)
    if re_measured_roof_sqft is None:
        re_measured_roof_sqft = 2000
    upload_photo(ctx["visit"]["id"], "AFTER", ctx["technician"]["id"])
    completed = complete_visit(
        ctx["visit"]["id"], ctx["technician"]["id"],
        re_measured_roof_sqft, re_measured_siding_sqft, re_measured_concrete_sqft)
    ctx["completed_visit"] = completed
    ctx["invoice"] = get_invoice_for_visit(ctx["visit"]["id"])
    return ctx


# ─── Tier 4: invoice / claim helpers ────────────────────────────────────────────

def get_invoice_for_visit(visit_id):
    """Return the single auto-issued Invoice for a completed visit (or None)."""
    data, _meta = _list(api_client.list_invoices(BILL, params={"visit_id": visit_id}))
    return data[0] if data else None


def file_claim(visit_id, customer_id, reason="dissatisfied"):
    """Owner files an OPEN satisfaction claim against a COMPLETED visit (ownership-gated)."""
    return get_success_data(api_client.create_claim(
        create_claim_payload(visit_id, reason), make_customer_headers(customer_id)))


def setup_open_claim(**kwargs):
    """Full path to a COMPLETED visit, then file an OPEN claim. Adds 'claim'."""
    ctx = setup_completed_visit(**kwargs)
    ctx["claim"] = file_claim(ctx["visit"]["id"], ctx["customer"]["id"])
    return ctx


# ─── Tier 5: recurring plan helpers ───────────────────────────────────────────

def create_plan(property_id, source_quote_id, cadence_days=30,
                start_utc="2026-05-01T00:00:00Z", **overrides):
    """Create an ACTIVE recurring plan from an ACCEPTED quote."""
    return get_success_data(api_client.create_plan(
        create_plan_payload(property_id, source_quote_id, cadence_days, start_utc, **overrides), DISP))


def generate_plan_visit(plan_id, duration_minutes=DEFAULT_DURATION_MINUTES):
    """Generate the next REQUESTED visit under an ACTIVE plan (bumps visits_generated_count)."""
    return get_success_data(api_client.generate_visit(
        plan_id, generate_visit_payload(duration_minutes=duration_minutes), DISP))


def setup_plan_with_scheduled_visit(cadence_days=30, **quote_kwargs):
    """ACTIVE plan + one generated, SCHEDULED, CONFIRMED-crew visit (tech scheduled_minutes 120).
    Returns a context dict with 'plan', 'visit' (SCHEDULED), 'assignment' (CONFIRMED),
    'technician'."""
    set_clock()
    ctx = setup_accepted_quote(**quote_kwargs)
    ctx["weather_window"] = create_clear_weather_window(ctx["route"]["id"])
    ctx["technician"] = create_technician()
    plan = create_plan(ctx["property"]["id"], ctx["quote"]["id"], cadence_days=cadence_days)
    ctx["plan"] = plan
    visit = generate_plan_visit(plan["id"])
    scheduled = schedule_visit(visit["id"], visit["version"])
    ctx["visit"] = scheduled
    asg = confirm_crew(reserve_crew(visit["id"], ctx["technician"]["id"])["id"])
    ctx["assignment"] = asg
    return ctx


# ─── internal ──────────────────────────────────────────────────────────────────

def _list(response):
    """Parse a list response into (data, meta) using the raw JSON (setup-lenient)."""
    body = response.json()
    return body["data"], body.get("meta", {})
