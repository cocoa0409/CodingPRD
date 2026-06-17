"""Composite setup helpers.

The platform carries a translation project from estimate through to settled invoice,
and most interesting assertions require the system to be in a late lifecycle state that
takes 10-25 API calls to reach. These helpers encapsulate those chains so test files can
focus on the trigger + assertion.

Every helper builds its preconditions from scratch using only PRD-declared endpoints
(the database is empty at the start of each test). Helpers use get_success_data() so a
broken setup step surfaces as a clear "Setup step failed" error.

Identity threading: after an entity-backed Client/Linguist is created, every
ownership-gated call uses make_client_headers(client["id"]) /
make_translator_headers(linguist["id"]) / make_reviewer_headers(linguist["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import (
    TEST_USERS, make_client_headers, make_translator_headers, make_reviewer_headers,
)
from .factories import (
    create_client_payload, create_linguist_payload, create_rate_card_payload,
    create_project_payload, create_job_payload, create_assignment_payload,
    create_qa_report_payload, deliver_payload, issue_invoice_payload,
)

PM = TEST_USERS["pm_headers"]
AR = TEST_USERS["ar_headers"]

# Default analyzed bands used throughout the design indices: NO_MATCH 1200, FUZZY 600,
# REPS 400, CONTEXT 300 -> weighted 1200 + 390 + 140 + 45 = 1775 words.
DEFAULT_BANDS = {
    "quoted_no_match_words": 1200,
    "quoted_fuzzy_words": 600,
    "quoted_reps_words": 400,
    "quoted_context_words": 300,
}
DEFAULT_ACTUAL_BANDS = {
    "actual_no_match_words": 1300,
    "actual_fuzzy_words": 600,
    "actual_reps_words": 400,
    "actual_context_words": 300,
}


# ─── Tier 1: Foundational records ─────────────────────
def create_client(name="Acme", billing_email="ar@acme.test", as_role=PM):
    resp = api.create_client(create_client_payload(name=name, billing_email=billing_email),
                             as_role)
    return get_success_data(resp)


def create_rate_card(**overrides):
    resp = api.create_rate_card(create_rate_card_payload(**overrides), PM)
    return get_success_data(resp)


def create_linguist(full_name="Trans One", can_review=False,
                    daily_throughput_words=None, qualified_pairs=None):
    extras = {}
    if can_review:
        extras["can_review"] = True
    if daily_throughput_words is not None:
        extras["daily_throughput_words"] = daily_throughput_words
    if qualified_pairs is not None:
        extras["qualified_pairs"] = qualified_pairs
    resp = api.create_linguist(create_linguist_payload(full_name=full_name, **extras), PM)
    return get_success_data(resp)


def create_project(client_id, rate_card_id, name="P1",
                   rush_tier=None, certification_mode=None):
    extras = {}
    if rush_tier is not None:
        extras["rush_tier"] = rush_tier
    if certification_mode is not None:
        extras["certification_mode"] = certification_mode
    resp = api.create_project(
        create_project_payload(client_id, rate_card_id, name=name, **extras), PM)
    return get_success_data(resp)


def add_job(project_id, filename="a.docx", bands=None):
    # Tests that omit `bands` expect the canonical analyzed bands (weighted 1775
    # words -> provisional payout 15975); only an explicit {} would mean "no words".
    payload = create_job_payload(
        filename=filename,
        **(dict(DEFAULT_BANDS) if bands is None else bands))
    resp = api.create_job(project_id, payload, PM)
    return get_success_data(resp)


# ─── Tier 2: Project base scenarios ───────────────────
def setup_foundations(rush_tier=None, certification_mode=None, bands=None,
                      need_reviewer=True, throughput=None):
    """Create client + rate card + project (DRAFT) + one job + translator linguist
    (+ reviewer linguist if need_reviewer). Returns a dict with all created entities."""
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist(full_name="Trans One", daily_throughput_words=throughput)
    reviewer = (create_linguist(full_name="Rev One", can_review=True)
                if need_reviewer else None)
    project = create_project(client["id"], rate_card["id"],
                             rush_tier=rush_tier, certification_mode=certification_mode)
    job = add_job(project["id"], bands=bands if bands is not None else dict(DEFAULT_BANDS))
    return {
        "client": client, "rate_card": rate_card, "translator": translator,
        "reviewer": reviewer, "project": project, "job": job,
    }


def quote_and_approve(ctx):
    """Quote the project (DRAFT->QUOTED) then have the owning client approve
    (QUOTED->APPROVED). Mutates nothing in ctx; returns the approved project data."""
    get_success_data(api.quote_project(ctx["project"]["id"], PM))
    approved = get_success_data(
        api.approve_project(ctx["project"]["id"],
                            make_client_headers(ctx["client"]["id"])))
    return approved


def current_job_version(job_id):
    return get_success_data(api.get_job(job_id, PM))["version"]


def current_project_version(project_id):
    return get_success_data(api.get_project(project_id, PM))["version"]


def assign(job_id, linguist_id, role, expected_job_version=None,
           window_start="2026-06-01T00:00:00.000Z",
           window_end="2026-06-02T00:00:00.000Z"):
    if expected_job_version is None:
        expected_job_version = current_job_version(job_id)
    resp = api.create_assignment(
        create_assignment_payload(job_id, linguist_id, role, expected_job_version,
                                  window_start=window_start, window_end=window_end), PM)
    return get_success_data(resp)


def accept_as_translator(assignment_id, linguist_id):
    return get_success_data(
        api.accept_assignment(assignment_id, make_translator_headers(linguist_id)))


def accept_as_reviewer(assignment_id, linguist_id):
    return get_success_data(
        api.accept_assignment(assignment_id, make_reviewer_headers(linguist_id)))


# ─── Tier 3: Full lifecycle progression shortcuts ─────
def setup_job_in_progress(rush_tier=None, certification_mode=None, bands=None,
                          rev_window_start="2026-06-02T00:00:00.000Z",
                          rev_window_end="2026-06-03T00:00:00.000Z",
                          throughput=None):
    """Through to: translator ACCEPTED (job TRANSLATING, project IN_PRODUCTION) AND
    reviewer ACCEPTED (IN_PROGRESS). Returns ctx augmented with translator_assignment
    and reviewer_assignment data."""
    ctx = setup_foundations(rush_tier=rush_tier, certification_mode=certification_mode,
                            bands=bands, need_reviewer=True, throughput=throughput)
    quote_and_approve(ctx)
    ta = assign(ctx["job"]["id"], ctx["translator"]["id"], "TRANSLATOR")
    accept_as_translator(ta["id"], ctx["translator"]["id"])
    ra = assign(ctx["job"]["id"], ctx["reviewer"]["id"], "REVIEWER",
                window_start=rev_window_start, window_end=rev_window_end)
    accept_as_reviewer(ra["id"], ctx["reviewer"]["id"])
    ctx["translator_assignment"] = ta
    ctx["reviewer_assignment"] = ra
    return ctx


def submit_translation(ctx):
    return get_success_data(
        api.submit_translation(ctx["job"]["id"],
                              make_translator_headers(ctx["translator"]["id"])))


def file_qa_report(ctx, critical_count=0, major_count=0, minor_count=0,
                   scored_word_count=2600):
    payload = create_qa_report_payload(
        ctx["reviewer_assignment"]["id"], scored_word_count,
        critical_count=critical_count, major_count=major_count, minor_count=minor_count)
    return get_success_data(
        api.create_qa_report(ctx["job"]["id"], payload,
                            make_reviewer_headers(ctx["reviewer"]["id"])))


def setup_job_in_qa(rush_tier=None, certification_mode=None, bands=None, throughput=None):
    """Through to: job IN_QA (translator submitted, reviewer in progress).
    Returns the same ctx as setup_job_in_progress."""
    ctx = setup_job_in_progress(rush_tier=rush_tier, certification_mode=certification_mode,
                                bands=bands, throughput=throughput)
    submit_translation(ctx)
    return ctx


def setup_job_qa_passed(rush_tier=None, certification_mode=None, bands=None,
                        critical_count=0, major_count=0, minor_count=1,
                        scored_word_count=2600):
    """Through to: job QA_PASSED (one passing QA report). Returns ctx with last_qa_report."""
    ctx = setup_job_in_qa(rush_tier=rush_tier, certification_mode=certification_mode,
                          bands=bands)
    report = file_qa_report(ctx, critical_count=critical_count, major_count=major_count,
                            minor_count=minor_count, scored_word_count=scored_word_count)
    ctx["last_qa_report"] = report
    return ctx


def deliver(ctx, actual_bands=None):
    payload = deliver_payload(**(actual_bands if actual_bands is not None
                                 else dict(DEFAULT_ACTUAL_BANDS)))
    return get_success_data(
        api.deliver_job(ctx["job"]["id"], payload, PM))


def setup_delivered_project(rush_tier=None, certification_mode=None, bands=None,
                            actual_bands=None, critical_count=0, major_count=0,
                            minor_count=1, scored_word_count=2600):
    """Through to: job DELIVERED and project DELIVERED (single-job bubble-up).
    Returns ctx with delivered_job."""
    ctx = setup_job_qa_passed(rush_tier=rush_tier, certification_mode=certification_mode,
                              bands=bands, critical_count=critical_count,
                              major_count=major_count, minor_count=minor_count,
                              scored_word_count=scored_word_count)
    ctx["delivered_job"] = deliver(ctx, actual_bands=actual_bands)
    return ctx


# ─── Tier 4: Invoice lifecycle ────────────────────────
def create_draft_invoice(ctx):
    inv = get_success_data(api.create_invoice(ctx["project"]["id"], AR))
    ctx["invoice"] = inv
    return inv


def issue_invoice(ctx, expected_project_version=None):
    if expected_project_version is None:
        expected_project_version = current_project_version(ctx["project"]["id"])
    issued = get_success_data(
        api.issue_invoice(ctx["invoice"]["id"],
                         issue_invoice_payload(expected_project_version), AR))
    ctx["invoice"] = issued
    return issued


def setup_issued_invoice(rush_tier="EXPRESS", certification_mode="CERTIFIED", bands=None,
                         actual_bands=None, critical_count=0, major_count=0,
                         minor_count=1, scored_word_count=2600):
    """Through to: invoice ISSUED for a single-pass delivered project.
    Returns ctx with project DELIVERED->INVOICED and invoice ISSUED."""
    ctx = setup_delivered_project(rush_tier=rush_tier, certification_mode=certification_mode,
                                  bands=bands, actual_bands=actual_bands,
                                  critical_count=critical_count, major_count=major_count,
                                  minor_count=minor_count, scored_word_count=scored_word_count)
    create_draft_invoice(ctx)
    issue_invoice(ctx)
    return ctx


# ─── Tier 5: Pricing-only quote setups (no staffing) ──
def setup_quotable_project(rush_tier=None, certification_mode=None, bands=None,
                           name="P-quote"):
    """Client + rate card + project (DRAFT) + one job with the given bands, ready to quote.
    No linguists. Returns ctx (client, rate_card, project, job)."""
    client = create_client()
    rate_card = create_rate_card()
    project = create_project(client["id"], rate_card["id"], name=name,
                             rush_tier=rush_tier, certification_mode=certification_mode)
    job = add_job(project["id"], bands=bands if bands is not None else dict(DEFAULT_BANDS))
    return {"client": client, "rate_card": rate_card, "project": project, "job": job}
