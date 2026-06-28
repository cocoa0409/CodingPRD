"""Composite setup helpers.

Most interesting test claims require the project tree in a specific state that
takes 5-20 API calls to reach. These helpers encapsulate the multi-step
preambles so tests can focus on assertions. All setup uses get_success_data()
(lenient) so a setup misstep raises a clear "Setup failed"-style error rather
than a confusing assertion failure.

Every fixture builds preconditions from scratch (the server DB is empty at the
start of every test). Ownership-gated Homeowner calls thread the actual
Homeowner.id via make_homeowner_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_homeowner_headers,
)
from . import factories as F

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_consultant_headers"]
OPS = TEST_USERS["operations_coordinator_headers"]
TECH = TEST_USERS["service_tech_headers"]

# A CASEMENT 30x40 LOWE_DUAL opening: area = 1200/144 sqft; unit_price 47500.
# A single-opening quote sends to estimate_total 84000 (subtotal 47500, tier
# NONE, install 35000 + 1500 = 36500). This is the canonical small project used
# across many design instances.
DEFAULT_READY_DATE = "2026-05-06T00:00:00Z"   # past ready_at for a CASEMENT (lead 35d from 2026-04-01)
DEFAULT_WINDOW_DATE = "2026-05-10T09:00:00Z"   # after a 2026-05-10T08:00 window start


# ---------------------------------------------------------------------------
# Tier 0: atomic creators
# ---------------------------------------------------------------------------

def create_homeowner(api=api_client, **overrides):
    resp = api.create_homeowner(F.create_homeowner_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_project_for(api, homeowner_id, **overrides):
    resp = api.create_project(F.create_project_payload(homeowner_id, **overrides), SALES)
    return get_success_data(resp)


def create_crew(api=api_client, **overrides):
    resp = api.create_crew(F.create_crew_payload(**overrides), OPS)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1/2: state progression + hierarchy
# ---------------------------------------------------------------------------

def setup_measured_consultation(api, openings=None, homeowner_overrides=None):
    """Create homeowner -> project -> BOOKED consultation -> add openings ->
    complete-measure. Returns dict(homeowner, project, consultation, opening_ids).

    `openings` is a list of opening-payload override dicts; defaults to one
    CASEMENT 30x40 LOWE_DUAL. Pass [] to leave the consultation BOOKED with
    zero openings (no complete-measure performed).
    """
    homeowner_overrides = homeowner_overrides or {}
    homeowner = create_homeowner(api, **homeowner_overrides)
    project = create_project_for(api, homeowner["id"])
    cons = get_success_data(
        api.create_consultation(project["id"], F.create_consultation_payload(project["id"]), SALES)
    )
    opening_ids = []
    if openings is None:
        openings = [{}]
    for ov in openings:
        op = get_success_data(
            api.create_opening(project["id"], cons["id"], F.create_opening_payload(cons["id"], **ov), SALES)
        )
        opening_ids.append(op["id"])
    if openings:
        get_success_data(api.complete_measure(project["id"], cons["id"], SALES))
    return {
        "homeowner": homeowner,
        "project": project,
        "consultation": cons,
        "opening_ids": opening_ids,
    }


def setup_draft_quote(api, openings=None, homeowner_overrides=None):
    """Measured consultation + a DRAFT quote on it. Returns the measured-setup
    dict plus 'quote'."""
    base = setup_measured_consultation(api, openings=openings, homeowner_overrides=homeowner_overrides)
    quote = get_success_data(
        api.create_quote(
            base["project"]["id"],
            F.create_quote_payload(base["project"]["id"], base["consultation"]["id"]),
            SALES,
        )
    )
    base["quote"] = quote
    return base


def setup_sent_quote(api, openings=None, homeowner_overrides=None):
    """Measured consultation + DRAFT quote -> SENT. Returns the setup dict plus
    'quote' (the SENT quote dict, version captured) and 'quote_version'."""
    base = setup_draft_quote(api, openings=openings, homeowner_overrides=homeowner_overrides)
    sent = get_success_data(api.send_quote(base["project"]["id"], base["quote"]["id"], SALES))
    base["quote"] = sent
    base["quote_version"] = sent["version"]
    return base


def setup_accepted_quote(api, openings=None, homeowner_overrides=None):
    """SENT quote accepted by the owning homeowner -> Project CONTRACTED, a
    ManufactureOrder auto-created (QUEUED). Returns the setup dict plus
    'manufacture' and the accepted 'quote'."""
    base = setup_sent_quote(api, openings=openings, homeowner_overrides=homeowner_overrides)
    ho_id = base["homeowner"]["id"]
    accepted = get_success_data(
        api.accept_quote(
            base["project"]["id"], base["quote"]["id"],
            F.accept_quote_payload(base["quote_version"]),
            make_homeowner_headers(ho_id),
        )
    )
    base["quote"] = accepted
    # Discover the auto-created manufacture order.
    mo_list, _ = _list_data(api.list_manufacture(base["project"]["id"], OPS))
    base["manufacture"] = mo_list[0] if mo_list else None
    return base


def _list_data(resp):
    body = resp.json()
    return body.get("data", []), body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 3: production lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_manufacture_in_build(api, openings=None):
    """Accepted quote -> start-build (Project IN_PRODUCTION, order IN_BUILD).
    Clock left at default. Returns setup dict (manufacture now IN_BUILD)."""
    base = setup_accepted_quote(api, openings=openings)
    mo = base["manufacture"]
    base["manufacture"] = get_success_data(api.start_build(base["project"]["id"], mo["id"], OPS))
    return base


def setup_manufacture_ready(api, openings=None, ready_date=DEFAULT_READY_DATE):
    """IN_BUILD order -> advance clock past ready_at -> mark-ready (order READY).
    Returns setup dict (manufacture READY). The clock ends at ready_date."""
    base = setup_manufacture_in_build(api, openings=openings)
    get_success_data(api.set_clock(F.set_clock_payload(ready_date), ADMIN))
    base["manufacture"] = get_success_data(api.mark_ready(base["project"]["id"], base["manufacture"]["id"], OPS))
    return base


def setup_scheduled_install(api, openings=None, crew_overrides=None,
                            window_start="2026-05-10T08:00:00Z",
                            window_end="2026-05-10T17:00:00Z",
                            ready=True):
    """A SCHEDULED InstallJob on a crew (jurisdiction CENTRAL_LIGHT to match the
    default project) with goods READY (unless ready=False, which leaves the
    order IN_BUILD). Returns setup dict plus 'crew' and 'install_job'."""
    crew_overrides = crew_overrides or {}
    if ready:
        base = setup_manufacture_ready(api, openings=openings)
    else:
        base = setup_manufacture_in_build(api, openings=openings)
    crew = create_crew(api, **crew_overrides)
    base["crew"] = crew
    job = get_success_data(
        api.create_install_job(
            base["project"]["id"],
            F.create_install_job_payload(base["project"]["id"], crew["id"], window_start, window_end),
            OPS,
        )
    )
    base["install_job"] = job
    return base


def setup_en_route_install(api, openings=None, approve_permit=False,
                           depart_clock=DEFAULT_WINDOW_DATE):
    """SCHEDULED install with READY goods -> file a permit (optionally approve
    it) -> advance clock past window_start -> depart (job EN_ROUTE, Project
    INSTALLING). Returns setup dict plus 'crew', 'install_job', 'permit'."""
    base = setup_scheduled_install(api, openings=openings)
    permit = get_success_data(api.create_permit(base["project"]["id"], F.create_permit_payload(base["project"]["id"]), OPS))
    if approve_permit:
        permit = get_success_data(api.approve_permit(base["project"]["id"], permit["id"], OPS))
    base["permit"] = permit
    get_success_data(api.set_clock(F.set_clock_payload(depart_clock), ADMIN))
    base["install_job"] = get_success_data(api.depart_install_job(base["project"]["id"], base["install_job"]["id"], OPS))
    return base


def setup_install_completed_permit_approved(api, openings=None):
    """Drive to a COMPLETED InstallJob with an APPROVED permit, but do NOT yet
    record an inspection (project still INSPECTION). Returns setup dict plus
    'crew', 'install_job', 'permit'."""
    base = setup_en_route_install(api, openings=openings, approve_permit=True)
    pid = base["project"]["id"]
    base["install_job"] = get_success_data(api.complete_install_job(pid, base["install_job"]["id"], OPS))
    return base


def setup_completed_project_to_failed_permit(api, openings=None):
    """COMPLETED install job + APPROVED permit -> record-inspection FAIL, leaving
    the permit at INSPECTION_FAILED. Returns setup dict plus 'permit'."""
    base = setup_install_completed_permit_approved(api, openings=openings)
    base["permit"] = get_success_data(
        api.record_inspection(base["project"]["id"], base["permit"]["id"], F.record_inspection_payload("FAIL"), OPS)
    )
    return base


def setup_completed_project(api, openings=None):
    """Drive the full pipeline to a COMPLETED Project:
    accept -> start-build -> mark-ready -> crew -> install -> permit -> approve
    -> depart -> complete -> record-inspection PASS.
    Returns setup dict plus 'crew', 'install_job', 'permit'. Clock ends at
    2026-05-10T09:00:00Z.
    """
    base = setup_en_route_install(api, openings=openings, approve_permit=True)
    pid = base["project"]["id"]
    base["install_job"] = get_success_data(api.complete_install_job(pid, base["install_job"]["id"], OPS))
    base["permit"] = get_success_data(
        api.record_inspection(pid, base["permit"]["id"], F.record_inspection_payload("PASS"), OPS)
    )
    return base


# ---------------------------------------------------------------------------
# Tier 4: service tickets
# ---------------------------------------------------------------------------

def setup_dispatched_ticket(api, category="WARRANTY", openings=None):
    """COMPLETED project -> open a ServiceTicket on its opening -> dispatch.
    Returns setup dict plus 'ticket'."""
    if openings is None:
        openings = [{}]
    base = setup_completed_project(api, openings=openings)
    pid = base["project"]["id"]
    ho_id = base["homeowner"]["id"]
    opening_id = base["opening_ids"][0]
    ticket = get_success_data(
        api.create_service_ticket(
            pid, F.create_service_ticket_payload(pid, opening_id, category=category),
            make_homeowner_headers(ho_id),
        )
    )
    ticket = get_success_data(api.dispatch_service_ticket(pid, ticket["id"], TECH))
    base["ticket"] = ticket
    return base


def setup_resolved_ticket(api, category="WARRANTY", openings=None):
    """COMPLETED project with a RESOLVED ServiceTicket. Returns setup dict plus 'ticket'."""
    base = setup_dispatched_ticket(api, category=category, openings=openings)
    base["ticket"] = get_success_data(api.resolve_service_ticket(base["project"]["id"], base["ticket"]["id"], TECH))
    return base


# ---------------------------------------------------------------------------
# Tier 5: referral scenarios
# ---------------------------------------------------------------------------

def setup_completed_referrer(api, openings=None):
    """A COMPLETED referrer project (single default opening). Returns the
    setup dict for the referrer (keys: homeowner, project, consultation,
    opening_ids, quote, ...)."""
    return setup_completed_project(api, openings=openings)


def setup_pending_referral_to_sent_referred(api, referrer_base=None):
    """Given (or building) a COMPLETED referrer project, create a new referred
    project taken through to a SENT quote, then create a PENDING Referral from
    referrer to referred. Returns dict(referrer=..., referred=..., referral=...,
    referred_quote_version=...)."""
    if referrer_base is None:
        referrer_base = setup_completed_referrer(api)
    referred = setup_sent_quote(api)
    referral = get_success_data(
        api.create_referral(
            F.create_referral_payload(referrer_base["project"]["id"], referred["project"]["id"]),
            SALES,
        )
    )
    return {
        "referrer": referrer_base,
        "referred": referred,
        "referral": referral,
        "referred_quote_version": referred["quote_version"],
    }
