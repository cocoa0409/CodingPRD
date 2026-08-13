"""Composite setup helpers.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before each test, so each test starts against
an empty database and a logical clock reading 2026-08-01T00:00:00Z).

Clock discipline: the startup clock already reads 2026-08-01T00:00:00Z, so no
helper sets the clock to that value (the clock must advance strictly
monotonically). Clock advances always move forward.

Identity discipline: Client and Talent are entity-backed roles — every
ownership-gated call uses make_client_headers(client["id"]) /
make_talent_headers(talent["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import parse_utc
from .factories import (
    create_client_payload,
    create_delivery_payload,
    create_project_payload,
    create_self_audition_payload,
    create_session_payload,
    create_studio_payload,
    create_talent_payload,
)
from .test_users import TEST_USERS, make_client_headers, make_talent_headers

CD = TEST_USERS["casting_director_headers"]
ENGINEER = TEST_USERS["studio_engineer_headers"]
AGENT = TEST_USERS["agent_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (PlatformAdmin-only)."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def create_client(**overrides):
    resp = api_client.create_client(create_client_payload(**overrides), CD)
    return get_success_data(resp)


def create_talent(**overrides):
    resp = api_client.create_talent(create_talent_payload(**overrides), CD)
    return get_success_data(resp)


def create_studio(**overrides):
    resp = api_client.create_studio(create_studio_payload(**overrides), CD)
    return get_success_data(resp)


def create_project(client, **overrides):
    """Create a DRAFT project owned by `client` (ownership-gated call)."""
    payload = create_project_payload(client["id"], **overrides)
    resp = api_client.create_project(payload, make_client_headers(client["id"]))
    return get_success_data(resp)


def open_casting(project_id):
    resp = api_client.open_casting(project_id, CD)
    return get_success_data(resp)


def submit_audition(project_id, talent, **overrides):
    """Talent submits a self-audition (ownership-gated call)."""
    payload = create_self_audition_payload(talent["id"], **overrides)
    resp = api_client.submit_self_audition(project_id, payload,
                                           make_talent_headers(talent["id"]))
    return get_success_data(resp)


def select_talent(project, audition):
    resp = api_client.select_talent(project["id"], audition["id"],
                                    make_client_headers(project["client_id"]))
    return get_success_data(resp)


def get_project(project_id):
    resp = api_client.get_project(project_id, CD)
    return get_success_data(resp)


def get_talent(talent_id):
    resp = api_client.get_talent(talent_id, CD)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1–2: casting pipeline
# ---------------------------------------------------------------------------

def create_casting_project(client=None, talent=None, **project_overrides):
    """Client + talent + project opened to CASTING + one audition submitted.

    Returns dict(client, talent, project, audition).
    """
    client = client or create_client()
    talent = talent or create_talent()
    project = create_project(client, **project_overrides)
    open_casting(project["id"])
    audition = submit_audition(project["id"], talent)
    return {"client": client, "talent": talent, "project": project,
            "audition": audition}


def create_cast_project(client=None, talent=None, **project_overrides):
    """Full chain through CAST: project -> open_casting -> audition -> select.

    Returns dict(client, talent, project, audition); `project` is re-fetched
    after selection so it carries status CAST and buyout_final_cents.
    """
    ctx = create_casting_project(client=client, talent=talent, **project_overrides)
    select_talent(ctx["project"], ctx["audition"])
    ctx["project"] = get_project(ctx["project"]["id"])
    return ctx


def list_project_invoices(project_id):
    resp = api_client.list_project_invoices(project_id, AGENT)
    return get_success_data(resp)


def get_usage_terms(project_id):
    """Return the single UsageTerms row for a cast project."""
    resp = api_client.get_usage_terms(project_id, make_client_headers(
        get_project(project_id)["client_id"]))
    rows = get_success_data(resp)
    assert isinstance(rows, list) and len(rows) == 1, (
        f"expected exactly one usage-terms row, got {rows!r}"
    )
    return rows[0]


def get_talent_conflict_exclusions(talent_id):
    resp = api_client.list_talent_conflict_exclusions(talent_id, CD)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: sessions and full lifecycle
# ---------------------------------------------------------------------------

def create_session(project_id, studio, **overrides):
    """Create a TENTATIVE session on a CAST project."""
    resp = api_client.create_session(
        project_id, create_session_payload(studio["id"], **overrides), CD)
    return get_success_data(resp)


def confirm_session(session_id):
    resp = api_client.confirm_session(session_id, CD)
    return get_success_data(resp)


def setup_completed_primary_session(**kwargs):
    """CAST project + PRIMARY session confirmed then completed.

    The session starts 2026-08-02T10:00:00Z; the clock is advanced to its
    end_at before completion. Returns dict with client, talent, studio,
    project, session (all post-completion re-fetches applied to session).
    """
    ctx = create_cast_project(**kwargs)
    studio = create_studio()
    session = create_session(ctx["project"]["id"], studio)
    confirm_session(session["id"])
    set_clock("2026-08-02T11:00:00Z")  # == end_at of the default 60-min session
    resp = api_client.complete_session(session["id"], ENGINEER)
    ctx["studio"] = studio
    ctx["session"] = get_success_data(resp)
    ctx["project"] = get_project(ctx["project"]["id"])
    return ctx


def setup_delivered_project(**kwargs):
    """Full pipeline through delivery: project DELIVERED with a Delivery row
    and its generated invoices. Delivery happens at clock 2026-08-02T11:00:00Z,
    so revision_window_closes_at == 2026-08-05T11:00:00Z.

    Returns dict(client, talent, studio, project, session, delivery, invoices).
    """
    ctx = setup_completed_primary_session(**kwargs)
    resp = api_client.create_delivery(
        ctx["project"]["id"], create_delivery_payload(ctx["session"]["id"]), ENGINEER)
    ctx["delivery"] = get_success_data(resp)
    ctx["project"] = get_project(ctx["project"]["id"])
    ctx["invoices"] = list_project_invoices(ctx["project"]["id"])
    return ctx


def setup_cast_with_exclusivity(talent=None, product_category="AUTOMOTIVE",
                                term_months=12, **overrides):
    """CAST project with exclusivity_required=true; creates an ACTIVE
    ConflictExclusion on the talent. Returns dict plus `exclusions` list."""
    ctx = create_cast_project(
        talent=talent,
        product_category=product_category,
        usage_type="TERM",
        term_months=term_months,
        exclusivity_required=True,
        **overrides,
    )
    ctx["exclusions"] = get_talent_conflict_exclusions(ctx["talent"]["id"])
    return ctx


def cancel_project(project):
    """Cancel a project, reading its current version first (OCC)."""
    current = get_project(project["id"])
    resp = api_client.cancel_project(
        project["id"], current["version"],
        make_client_headers(current["client_id"]))
    return get_success_data(resp)


def get_audition(audition_id):
    resp = api_client.get_self_audition(audition_id, CD)
    return get_success_data(resp)


def get_session(session_id):
    resp = api_client.get_session(session_id, CD)
    return get_success_data(resp)
