"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors.

OCC note: the PRD (section 2.9) increments a resource's version whenever a
derived field on it is recomputed, so helpers always re-read the fresh
version of an OCC-guarded resource immediately before patching it.

Stockpile note: the PRD names the per-size-class cubic-yard intake factor
table but does not pin its per-class figures, so helpers that must satisfy
an exact stockpile draw read the live `stockpile_cy` back from the site
instead of hardcoding cubic-yard expectations.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLAIM_WINDOW_CLOCK,
    RUN_COMPLETE_CLOCK,
    RUN_END,
    RUN_START,
    WINDOW_START,
    YIELD_CY_PER_TON,
)
from .factories import (
    create_booking_payload,
    create_claim_payload,
    create_household_payload,
    create_intake_payload,
    create_mulch_event_payload,
    create_program_payload,
    create_run_payload,
    create_shift_payload,
    create_site_payload,
    create_ticket_payload,
    create_volunteer_payload,
    create_zone_payload,
)
from .test_users import (
    TEST_USERS,
    make_program_admin_headers,
    make_resident_headers,
    make_site_supervisor_headers,
    make_volunteer_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
SUPERVISOR = TEST_USERS["site_supervisor_headers"]
HAULER = TEST_USERS["hauler_partner_headers"]
ANON = TEST_USERS["anonymous_headers"]


def _ok(step, resp, expected=None):
    data = get_success_data(resp)
    if expected is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected, (
            f"Setup failed at {step}: expected status {expected}, got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    _ok("set_clock", resp)


# ---------------------------------------------------------------------------
# Tier 1 — program / site / zone stand-up and state progression
# ---------------------------------------------------------------------------

def create_program(**overrides):
    resp = api_client.create_program(create_program_payload(**overrides), ADMIN)
    return _ok("create_program", resp, expected="DRAFT")


def add_site(program_id, **overrides):
    resp = api_client.create_site(create_site_payload(program_id, **overrides),
                                  ADMIN)
    return _ok("create_site", resp, expected="PLANNED")


def add_zone(program_id, **overrides):
    resp = api_client.create_zone(create_zone_payload(program_id, **overrides),
                                  ADMIN)
    return _ok("create_zone", resp, expected="ACTIVE")


def get_program(program_id):
    return _ok("get_program", api_client.get_program(program_id, ADMIN))


def get_site(site_id):
    return _ok("get_site", api_client.get_site(site_id, ADMIN))


def get_zone(zone_id):
    return _ok("get_zone", api_client.get_zone(zone_id, ADMIN))


def patch_program(program_id, **fields):
    """PATCH a program with a fresh OCC version (re-read first)."""
    current = get_program(program_id)
    payload = dict(fields)
    payload["expected_program_version"] = current["version"]
    return _ok("patch_program",
               api_client.patch_program(program_id, payload, ADMIN))


def patch_site(site_id, as_headers=None, **fields):
    """PATCH a site with a fresh OCC version (re-read first)."""
    current = get_site(site_id)
    payload = dict(fields)
    payload["expected_site_version"] = current["version"]
    return _ok("patch_site",
               api_client.patch_site(site_id, payload, as_headers or ADMIN))


def patch_zone(zone_id, **fields):
    """PATCH a zone with a fresh OCC version (re-read first)."""
    current = get_zone(zone_id)
    payload = dict(fields)
    payload["expected_zone_version"] = current["version"]
    return _ok("patch_zone",
               api_client.patch_zone(zone_id, payload, ADMIN))


def publish_program(program):
    """DRAFT -> PUBLISHED (requires >=1 zone and >=1 site to exist)."""
    return patch_program(program["id"], status="PUBLISHED")


def activate_program(program_id, clock=WINDOW_START):
    """PUBLISHED -> ACTIVE: moves the logical clock to window_start first."""
    set_clock(clock)
    return patch_program(program_id, status="ACTIVE")


def create_active_program(site=True, zone=True, clock=WINDOW_START,
                          site_overrides=None, zone_overrides=None,
                          **program_overrides):
    """Program with one site and one zone, published and activated.

    Returns dict(program, site, zone). The site is still PLANNED; the logical
    clock sits at `clock` (default: the window start).
    """
    program = create_program(**program_overrides)
    site = add_site(program["id"], **(site_overrides or {})) if site else None
    zone = add_zone(program["id"], **(zone_overrides or {})) if zone else None
    publish_program(program)
    program = activate_program(program["id"], clock=clock)
    return {"program": program, "site": site, "zone": zone}


def open_site(site, as_headers=None):
    """PLANNED -> OPEN with a fresh OCC version."""
    return patch_site(site["id"], as_headers=as_headers, status="OPEN")


# ---------------------------------------------------------------------------
# Tier 2 — households, bookings, tickets
# ---------------------------------------------------------------------------

def register_household(program_id, zone_id, **overrides):
    resp = api_client.create_household(
        create_household_payload(program_id, zone_id, **overrides), ANON)
    return _ok("create_household", resp)


def create_confirmed_booking(household, zone_id, tree_count=1,
                             size_class="SMALL", as_admin=False):
    """Create a booking (initial CONFIRMED) for the given household dict."""
    headers = ADMIN if as_admin else make_resident_headers(household["id"])
    resp = api_client.create_booking(
        create_booking_payload(household["id"], zone_id,
                               tree_count=tree_count, size_class=size_class),
        headers)
    return _ok("create_booking", resp, expected="CONFIRMED")


def get_booking(booking_id):
    return _ok("get_booking", api_client.get_booking(booking_id, ADMIN))


def record_booking_outcome(booking_id, outcome, actual_tons=None):
    payload = {"outcome": outcome}
    if actual_tons is not None:
        payload["actual_tons"] = actual_tons
    resp = api_client.record_booking_outcome(booking_id, payload, SUPERVISOR)
    return _ok("record_booking_outcome", resp, expected=outcome)


def create_serviced_booking(household, zone_id, tree_count=1,
                            size_class="SMALL", actual_tons=None):
    """Create a booking and record it SERVICED (makes the household a
    PARTICIPANT for mulch tiers). Returns the SERVICED booking."""
    booking = create_confirmed_booking(household, zone_id,
                                       tree_count=tree_count,
                                       size_class=size_class)
    return record_booking_outcome(booking["id"], "SERVICED",
                                  actual_tons=actual_tons)


def report_ticket(program_id, booking_id=None, site_id=None,
                  category="OTHER", reporter_headers=None):
    payload = create_ticket_payload(program_id, category=category)
    if booking_id is not None:
        payload["booking_id"] = booking_id
    if site_id is not None:
        payload["site_id"] = site_id
    resp = api_client.create_contamination_ticket(
        payload, reporter_headers or make_site_supervisor_headers("sup-1"))
    return _ok("create_contamination_ticket", resp, expected="OPEN")


def adjudicate(ticket_id, verdict, adjudicator_headers=None):
    resp = api_client.adjudicate_ticket(
        ticket_id, {"verdict": verdict},
        adjudicator_headers or make_program_admin_headers("admin-1"))
    return _ok("adjudicate", resp, expected=verdict)


def get_ticket(ticket_id):
    return _ok("get_ticket",
               api_client.get_contamination_ticket(ticket_id, ADMIN))


def get_household(household_id):
    return _ok("get_household", api_client.get_household(household_id, ADMIN))


def list_notifications(program_id, params=None):
    return _ok("list_notifications",
               api_client.list_program_notifications(program_id, ADMIN,
                                                     params=params))


# ---------------------------------------------------------------------------
# Tier 3 — intake, stockpile, chipping runs
# ---------------------------------------------------------------------------

def record_intake(site_id, tree_count=10, size_class="MEDIUM",
                  source_type="CITY_CREW", contaminated_cy=None,
                  weighed_tons=None):
    payload = create_intake_payload(site_id, tree_count=tree_count,
                                    size_class=size_class,
                                    source_type=source_type)
    if contaminated_cy is not None:
        payload["contaminated_cy"] = contaminated_cy
    if weighed_tons is not None:
        payload["weighed_tons"] = weighed_tons
    resp = api_client.create_intake_event(payload, SUPERVISOR)
    return _ok("create_intake_event", resp, expected="RECORDED")


def site_stockpile(site_id):
    """Live read-back of the site's stockpile_cy."""
    return get_site(site_id)["stockpile_cy"]


def get_intake_event(intake_id):
    return _ok("get_intake_event",
               api_client.get_intake_event(intake_id, ADMIN))


def schedule_run(program_id, site_id, scheduled_start=RUN_START,
                 scheduled_end=RUN_END, material_class="MIXED_LOAD"):
    resp = api_client.create_chipping_run(
        create_run_payload(program_id, site_id,
                           scheduled_start=scheduled_start,
                           scheduled_end=scheduled_end,
                           material_class=material_class),
        ADMIN)
    return _ok("create_chipping_run", resp, expected="SCHEDULED")


def complete_run(run, input_cy=None, measured_input_tons=None,
                 contaminated_input_tons=0, measured_output_cy=None,
                 yield_review_confirmed=None, clock=RUN_COMPLETE_CLOCK):
    """Complete a SCHEDULED run. input_cy=None draws the site's whole current
    stockpile (exact-draw, which the PRD admits)."""
    set_clock(clock)
    if input_cy is None:
        input_cy = site_stockpile(run["site_id"])
    payload = {
        "input_cy": input_cy,
        "measured_input_tons": measured_input_tons,
        "contaminated_input_tons": contaminated_input_tons,
        "measured_output_cy": measured_output_cy,
    }
    if yield_review_confirmed is not None:
        payload["yield_review_confirmed"] = yield_review_confirmed
    resp = api_client.complete_chipping_run(run["id"], payload, HAULER)
    return _ok("complete_chipping_run", resp, expected="COMPLETED")


def produce_mulch(program_id, site_id, measured_output_cy,
                  material_class="MIXED_LOAD", scheduled_start=RUN_START,
                  scheduled_end=RUN_END, clock=RUN_COMPLETE_CLOCK):
    """Schedule + complete a run whose measured output is exactly
    `measured_output_cy` (zero contamination, zero variance), crediting the
    program's mulch pool. Draws the site's whole current stockpile.

    measured_input_tons is chosen so the theoretical yield equals the
    measured output exactly for the given material class.
    """
    yield_factor = YIELD_CY_PER_TON[material_class]
    measured_input_tons = measured_output_cy / yield_factor
    run = schedule_run(program_id, site_id,
                       scheduled_start=scheduled_start,
                       scheduled_end=scheduled_end,
                       material_class=material_class)
    return complete_run(run, measured_input_tons=measured_input_tons,
                        measured_output_cy=measured_output_cy, clock=clock)


# ---------------------------------------------------------------------------
# Tier 4 — mulch events and claims
# ---------------------------------------------------------------------------

def create_mulch_event(program_id, **overrides):
    resp = api_client.create_mulch_event(
        create_mulch_event_payload(program_id, **overrides), ADMIN)
    return _ok("create_mulch_event", resp, expected="SCHEDULED")


def open_mulch_event(event_id):
    resp = api_client.patch_mulch_event(event_id, {"status": "OPEN"}, ADMIN)
    return _ok("open_mulch_event", resp, expected="OPEN")


def create_open_event(program_id, **overrides):
    event = create_mulch_event(program_id, **overrides)
    return open_mulch_event(event["id"])


def create_claim(event_id, household, requested_cy=1.0, as_admin=False):
    """Create a mulch claim for the given household dict (resident-owned by
    default; ProgramAdmin on its behalf when as_admin=True)."""
    headers = ADMIN if as_admin else make_resident_headers(household["id"])
    resp = api_client.create_mulch_claim(
        create_claim_payload(event_id, household["id"],
                             requested_cy=requested_cy),
        headers)
    return _ok("create_mulch_claim", resp)


def get_claim(claim_id):
    return _ok("get_claim", api_client.get_mulch_claim(claim_id, ADMIN))


def setup_mulch_pool(produced_cy=10.0, num_general_households=3,
                     with_participant=True):
    """Full mulch-giveback scenario.

    ACTIVE program -> OPEN site -> (optional) PARTICIPANT household with a
    SERVICED booking -> intake recorded -> run completed crediting
    `produced_cy` of mulch -> event created and opened -> clock inside the
    claim window -> N GENERAL households registered.

    Returns dict(program, site, zone, event, participant, generals).
    """
    ctx = create_active_program()
    program, site, zone = ctx["program"], ctx["site"], ctx["zone"]
    open_site(site)

    participant = None
    if with_participant:
        participant = register_household(program["id"], zone["id"])
        create_serviced_booking(participant, zone["id"],
                                tree_count=1, size_class="SMALL")

    record_intake(site["id"], tree_count=20, size_class="MEDIUM")
    produce_mulch(program["id"], site["id"], produced_cy)

    event = create_open_event(program["id"])
    set_clock(CLAIM_WINDOW_CLOCK)

    generals = [register_household(program["id"], zone["id"])
                for _ in range(num_general_households)]

    return {"program": program, "site": site, "zone": zone, "event": event,
            "participant": participant, "generals": generals}


# ---------------------------------------------------------------------------
# Tier 5 — volunteers and shifts
# ---------------------------------------------------------------------------

def register_volunteer(program_id, **overrides):
    resp = api_client.create_volunteer(
        create_volunteer_payload(program_id, **overrides), ANON)
    return _ok("create_volunteer", resp, expected="APPLIED")


def approve_volunteer(volunteer_id):
    resp = api_client.patch_volunteer(volunteer_id, {"status": "APPROVED"},
                                      ADMIN)
    return _ok("approve_volunteer", resp, expected="APPROVED")


def register_approved_volunteer(program_id, **overrides):
    volunteer = register_volunteer(program_id, **overrides)
    return approve_volunteer(volunteer["id"])


def create_shift(volunteer, site_id, start_at="2027-01-09T09:00:00Z",
                 end_at="2027-01-09T12:00:00Z", shift_role="LOADER",
                 as_admin=False):
    headers = (ADMIN if as_admin
               else make_volunteer_headers(volunteer["id"]))
    resp = api_client.create_volunteer_shift(
        create_shift_payload(volunteer["id"], site_id, start_at=start_at,
                             end_at=end_at, shift_role=shift_role),
        headers)
    return _ok("create_volunteer_shift", resp, expected="SIGNED_UP")


def get_shift(shift_id):
    return _ok("get_shift", api_client.get_volunteer_shift(shift_id, ADMIN))


def get_volunteer(volunteer_id):
    return _ok("get_volunteer", api_client.get_volunteer(volunteer_id, ADMIN))


def setup_approved_volunteer_scenario(site_overrides=None):
    """ACTIVE program + OPEN site + one APPROVED volunteer."""
    ctx = create_active_program(site_overrides=site_overrides)
    open_site(ctx["site"])
    volunteer = register_approved_volunteer(ctx["program"]["id"])
    ctx["volunteer"] = volunteer
    return ctx


# ---------------------------------------------------------------------------
# Diversion reports
# ---------------------------------------------------------------------------

def create_report(program_id):
    """POST /diversion-reports with the program's fresh OCC version."""
    current = get_program(program_id)
    resp = api_client.create_diversion_report(
        {"program_id": program_id,
         "expected_program_version": current["version"]},
        ADMIN)
    return _ok("create_diversion_report", resp, expected="DRAFT")
