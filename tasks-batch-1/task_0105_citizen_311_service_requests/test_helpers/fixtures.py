"""Composite setup helpers.

The harness restarts the server (empty DB) before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. Setup
calls use get_success_data() so failures surface as clear "Setup step failed"
errors rather than confusing assertion failures.

Identity threading: after a fixture creates an Agent or Citizen (entity-backed
roles), every ownership/department-gated call uses make_agent_headers(agent_id) /
make_citizen_headers(citizen_id) with the real entity id, never the shared
constant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_citizen_headers,
    make_agent_headers,
)
from . import factories as f
from .constants import DEFAULT_CLOCK_ISO

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ANON = TEST_USERS["anonymous_headers"]

# Monotonic counter so repeated factory calls within one test get unique
# unique-constrained values (email / category code / name).
_seq = itertools.count(1)


def _n() -> int:
    return next(_seq)


def _code_suffix(n: int) -> str:
    """Encode a positive integer as an uppercase A-Z letter sequence (base-26,
    A=1..Z=26), so generated category codes stay within the PRD's "uppercase
    letters A-Z and underscores" rule (no digits)."""
    letters = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


# ----------------------------------------------------------------------------
# Tier 0: clock + reference configuration
# ----------------------------------------------------------------------------
def set_clock(iso=DEFAULT_CLOCK_ISO):
    """Set the logical clock to an absolute UTC instant. Returns clock_now data."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def advance_clock(hours):
    """Advance the clock by N hours and run the SLA sweep. Returns advance data
    ({ clock_now, breached_request_ids, escalations_created })."""
    return get_success_data(api_client.advance_clock({"hours": hours}, ADMIN))


def create_department(backlog_threshold=5, name=None):
    name = name or f"Dept-{_n()}"
    return get_success_data(
        api_client.create_department(
            f.create_department_payload(name=name, backlog_threshold=backlog_threshold),
            ADMIN,
        )
    )


def create_category(default_department_id, requires_geolocation=False, **overrides):
    n = _n()
    payload = f.create_category_payload(
        default_department_id,
        name=overrides.pop("name", f"Category-{n}"),
        code=overrides.pop("code", f"CAT_{_code_suffix(n)}"),
        requires_geolocation=requires_geolocation,
        **overrides,
    )
    return get_success_data(api_client.create_category(payload, ADMIN))


def create_jurisdiction(min_lat, max_lat, min_lng, max_lng, **overrides):
    payload = f.create_jurisdiction_payload(
        min_lat, max_lat, min_lng, max_lng,
        name=overrides.pop("name", f"Jur-{_n()}"),
        **overrides,
    )
    return get_success_data(api_client.create_jurisdiction(payload, ADMIN))


def create_sla_policy(category_id, priority="STANDARD", resolution_sla_hours=24,
                      escalation_tier1_hours=2, escalation_tier2_hours=6):
    return get_success_data(
        api_client.create_sla_policy(
            f.create_sla_policy_payload(
                category_id, priority,
                resolution_sla_hours=resolution_sla_hours,
                escalation_tier1_hours=escalation_tier1_hours,
                escalation_tier2_hours=escalation_tier2_hours,
            ),
            ADMIN,
        )
    )


def create_citizen(email=None, **overrides):
    email = email or f"citizen{_n()}@example.com"
    return get_success_data(
        api_client.create_citizen(f.create_citizen_payload(email, **overrides), ANON)
    )


def create_agent(department_id, is_supervisor=False, **overrides):
    payload = f.create_agent_payload(
        department_id,
        full_name=overrides.pop("full_name", f"Agent-{_n()}"),
        is_supervisor=is_supervisor,
        **overrides,
    )
    return get_success_data(api_client.create_agent(payload, ADMIN))


# ----------------------------------------------------------------------------
# Tier 1: request creation
# ----------------------------------------------------------------------------
def create_request(citizen_id, category_id, **overrides):
    """File a SUBMITTED request as the owning citizen (entity-backed identity)."""
    payload = f.create_service_request_payload(citizen_id, category_id, **overrides)
    return get_success_data(
        api_client.create_service_request(payload, make_citizen_headers(citizen_id))
    )


def triage_request(request_id, requested_priority=None):
    payload = {}
    if requested_priority is not None:
        payload["requested_priority"] = requested_priority
    return get_success_data(
        api_client.triage_service_request(request_id, payload, DISPATCHER)
    )


def route_request(request_id):
    return get_success_data(api_client.route_service_request(request_id, DISPATCHER))


def get_work_order_for_request(request_id):
    """Fetch the single WorkOrder belonging to a request. Returns the WorkOrder dict."""
    data = get_success_data(
        api_client.list_work_orders(DISPATCHER, params={"request_id": request_id})
    )
    assert data, f"expected a WorkOrder for request {request_id}"
    return data[0]


# ----------------------------------------------------------------------------
# Tier 2: configured environment (dept + category [+ SLA] + citizen)
# ----------------------------------------------------------------------------
def setup_basic_environment(requires_geolocation=False, with_sla=True,
                            backlog_threshold=5, priority="STANDARD",
                            resolution_sla_hours=24, escalation_tier1_hours=2,
                            escalation_tier2_hours=6, set_clock_iso=DEFAULT_CLOCK_ISO):
    """Clock + department + category (+ STANDARD SLA) + citizen.

    Returns dict { dept, category, citizen } (and 'sla' if with_sla).
    """
    if set_clock_iso is not None:
        set_clock(set_clock_iso)
    dept = create_department(backlog_threshold=backlog_threshold)
    category = create_category(dept["id"], requires_geolocation=requires_geolocation)
    out = {"dept": dept, "category": category}
    if with_sla:
        out["sla"] = create_sla_policy(
            category["id"], priority=priority,
            resolution_sla_hours=resolution_sla_hours,
            escalation_tier1_hours=escalation_tier1_hours,
            escalation_tier2_hours=escalation_tier2_hours,
        )
    out["citizen"] = create_citizen()
    return out


# ----------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ----------------------------------------------------------------------------
def setup_routed_request(backlog_threshold=5, resolution_sla_hours=24,
                         escalation_tier1_hours=2, escalation_tier2_hours=6,
                         set_clock_iso=DEFAULT_CLOCK_ISO):
    """A request taken through triage + route (status ROUTED, one OPEN WorkOrder).

    Returns dict { dept, category, sla, citizen, request, work_order }.
    """
    env = setup_basic_environment(
        backlog_threshold=backlog_threshold,
        resolution_sla_hours=resolution_sla_hours,
        escalation_tier1_hours=escalation_tier1_hours,
        escalation_tier2_hours=escalation_tier2_hours,
        set_clock_iso=set_clock_iso,
    )
    request = create_request(env["citizen"]["id"], env["category"]["id"])
    triage_request(request["id"])
    request = route_request(request["id"])
    work_order = get_work_order_for_request(request["id"])
    env["request"] = request
    env["work_order"] = work_order
    return env


def assign_and_start(work_order_id, agent_id):
    """Assign an agent (OCC) then start the work order. Returns started WorkOrder."""
    wo = api_client.get_work_order(work_order_id, DISPATCHER).json()["data"]
    get_success_data(
        api_client.assign_work_order(
            work_order_id,
            f.assign_work_order_payload(agent_id, wo["version"]),
            DISPATCHER,
        )
    )
    return get_success_data(
        api_client.start_work_order(work_order_id, make_agent_headers(agent_id))
    )


def setup_started_request(set_clock_iso=DEFAULT_CLOCK_ISO, backlog_threshold=5,
                          resolution_sla_hours=24, escalation_tier1_hours=2,
                          escalation_tier2_hours=6):
    """A routed request with an agent assigned and the work order started
    (request IN_PROGRESS, WorkOrder IN_PROGRESS).

    Returns dict { dept, category, sla, citizen, request, work_order, agent }.
    """
    env = setup_routed_request(
        backlog_threshold=backlog_threshold,
        resolution_sla_hours=resolution_sla_hours,
        escalation_tier1_hours=escalation_tier1_hours,
        escalation_tier2_hours=escalation_tier2_hours,
        set_clock_iso=set_clock_iso,
    )
    agent = create_agent(env["dept"]["id"])
    env["agent"] = agent
    env["work_order"] = assign_and_start(env["work_order"]["id"], agent["id"])
    return env


def setup_resolved_request(set_clock_iso=DEFAULT_CLOCK_ISO, backlog_threshold=5,
                           resolution_sla_hours=24, completion_note="fixed",
                           escalation_tier1_hours=2, escalation_tier2_hours=6):
    """A request driven all the way to RESOLVED via work-order completion
    (request RESOLVED, WorkOrder COMPLETED, survey SENT).

    Returns dict { dept, category, sla, citizen, request, work_order, agent }.
    The work_order entry is refreshed to the COMPLETED state.
    """
    env = setup_started_request(
        set_clock_iso=set_clock_iso,
        backlog_threshold=backlog_threshold,
        resolution_sla_hours=resolution_sla_hours,
        escalation_tier1_hours=escalation_tier1_hours,
        escalation_tier2_hours=escalation_tier2_hours,
    )
    env["work_order"] = get_success_data(
        api_client.complete_work_order(
            env["work_order"]["id"],
            f.complete_work_order_payload(completion_note),
            make_agent_headers(env["agent"]["id"]),
        )
    )
    return env


def get_survey_for_request(request_id):
    """Fetch the SatisfactionSurvey for a request. Returns the survey dict."""
    data = get_success_data(
        api_client.list_surveys(DISPATCHER, params={"request_id": request_id})
    )
    assert data, f"expected a survey for request {request_id}"
    return data[0]


# ----------------------------------------------------------------------------
# Tier 4: duplicate cluster setup
# ----------------------------------------------------------------------------
def setup_cluster_on_canonical(requires_geolocation=True, lat=41.8800, lng=-87.6300,
                               set_clock_iso=DEFAULT_CLOCK_ISO):
    """A geo canonical request (still SUBMITTED) with an OPEN cluster anchored to it.

    Returns dict { dept, category, citizen, canonical, cluster }.
    """
    if set_clock_iso is not None:
        set_clock(set_clock_iso)
    dept = create_department(backlog_threshold=5)
    category = create_category(dept["id"], requires_geolocation=requires_geolocation)
    citizen = create_citizen()
    canonical = create_request(
        citizen["id"], category["id"], description="canonical", lat=lat, lng=lng
    )
    cluster = get_success_data(
        api_client.create_duplicate_cluster(
            f.create_duplicate_cluster_payload(
                category["id"], canonical["id"], canonical["version"]
            ),
            DISPATCHER,
        )
    )
    return {
        "dept": dept,
        "category": category,
        "citizen": citizen,
        "canonical": canonical,
        "cluster": cluster,
    }


# ----------------------------------------------------------------------------
# Tier 5: SLA breach
# ----------------------------------------------------------------------------
def setup_breached_request(advance_hours=27, set_clock_iso=DEFAULT_CLOCK_ISO,
                           resolution_sla_hours=24, escalation_tier1_hours=2,
                           escalation_tier2_hours=6, start=True):
    """A routed (optionally started) request whose SLA has been breached by
    advancing the clock, firing auto-escalations.

    advance_hours is measured from routed_at (the clock is set, request routed at
    that instant, then advanced by advance_hours). With routed_at at set_clock_iso
    and a 24h SLA, advance_hours=27 => overdue 3h (TIER1); advance_hours=30 =>
    overdue 6h (TIER2).

    Returns dict { dept, category, sla, citizen, request, work_order, agent?,
    advance } where advance is the /_clock/advance response data.
    """
    if start:
        env = setup_started_request(
            set_clock_iso=set_clock_iso,
            resolution_sla_hours=resolution_sla_hours,
            escalation_tier1_hours=escalation_tier1_hours,
            escalation_tier2_hours=escalation_tier2_hours,
        )
    else:
        env = setup_routed_request(
            set_clock_iso=set_clock_iso,
            resolution_sla_hours=resolution_sla_hours,
            escalation_tier1_hours=escalation_tier1_hours,
            escalation_tier2_hours=escalation_tier2_hours,
        )
    env["advance"] = advance_clock(advance_hours)
    return env


def get_request(request_id):
    return get_success_data(api_client.get_service_request(request_id, DISPATCHER))


def get_department(department_id):
    return get_success_data(api_client.get_department(department_id, DISPATCHER))


def get_escalations_for_request(request_id):
    return get_success_data(api_client.list_request_escalations(request_id, DISPATCHER))
