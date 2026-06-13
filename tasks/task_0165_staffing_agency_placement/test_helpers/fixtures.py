"""Composite setup helpers for the Staffing Agency Placement API.

These encapsulate the multi-step preambles that most test claims require, so the
tests themselves focus on the trigger and assertions. All setup calls use
get_success_data() (lenient 2xx validator) so a broken precondition surfaces as
a clear "Setup failed" rather than a confusing assertion error.

Identity threading: the Client and Candidate roles are entity-backed, so every
ownership-gated call here uses make_client_headers(client["id"]) /
make_candidate_headers(candidate["id"]) with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    make_recruiter_headers, make_account_manager_headers,
    make_client_headers, make_candidate_headers,
)
from . import factories


# Default operator headers (opaque roles).
RECRUITER = make_recruiter_headers()
AM = make_account_manager_headers()


# -----------------------------------------------------------------------------
# Tier 0: atomic create primitives
# -----------------------------------------------------------------------------

def create_skill(code="JAVA", category="TECH"):
    """Create one skill catalog entry. Returns the skill dict."""
    return get_success_data(
        api_client.create_skill(factories.create_skill_payload(code=code, category=category), RECRUITER)
    )


def ensure_skills(codes):
    """Create each (code, category) pair. `codes` is a list of (code, category)."""
    out = []
    for code, category in codes:
        out.append(create_skill(code=code, category=category))
    return out


def create_client(name="Acme", credit_limit_cents=100_000_000, **overrides):
    """Create a client. Returns the client dict."""
    payload = factories.create_client_payload(
        name=name, credit_limit_cents=credit_limit_cents, **overrides
    )
    return get_success_data(api_client.create_client(payload, AM))


def create_candidate(skill_codes=("JAVA",), full_name="Cara Dev", base_pay_rate_cents=8000, **overrides):
    """Create a candidate. Returns the candidate dict."""
    payload = factories.create_candidate_payload(
        full_name=full_name, skill_codes=list(skill_codes),
        base_pay_rate_cents=base_pay_rate_cents, **overrides
    )
    return get_success_data(api_client.create_candidate(payload, RECRUITER))


def create_open_job_order(client_id, **overrides):
    """Create a job order and transition it DRAFT -> OPEN.

    Returns (job_order, version) where version is the post-OPEN version.
    """
    jo = get_success_data(
        api_client.create_job_order(factories.create_job_order_payload(client_id, **overrides), AM)
    )
    opened = get_success_data(
        api_client.patch_job_order(jo["id"], {"target_status": "OPEN"}, AM)
    )
    return opened, opened["version"]


# -----------------------------------------------------------------------------
# Tier 1/2/3: pipeline progression toward a placement
# -----------------------------------------------------------------------------

def drive_submission_to_offer_extended(job_order, candidate, client, submitted_pay_rate_cents=8000):
    """Create a submission and walk it to OFFER_EXTENDED.

    Pipeline: submit -> CLIENT_REVIEW (Recruiter) -> interview (Client) ->
    record PASSED (Client) -> OFFER_EXTENDED (Client). Returns (submission, interview).
    """
    client_headers = make_client_headers(client["id"])
    sub = get_success_data(api_client.create_submission(
        factories.create_submission_payload(
            job_order["id"], candidate["id"], submitted_pay_rate_cents=submitted_pay_rate_cents
        ), RECRUITER))
    get_success_data(api_client.patch_submission(sub["id"], {"target_status": "CLIENT_REVIEW"}, RECRUITER))
    iv = get_success_data(api_client.create_interview(
        sub["id"], factories.create_interview_payload(), client_headers))
    get_success_data(api_client.patch_interview(iv["id"], {"outcome": "PASSED"}, client_headers))
    get_success_data(api_client.patch_submission(sub["id"], {"target_status": "OFFER_EXTENDED"}, client_headers))
    return sub, iv


def setup_offer_extended_scenario(client_overrides=None, job_order_overrides=None,
                                  candidate_overrides=None, skill=("JAVA", "TECH"),
                                  submitted_pay_rate_cents=8000):
    """Full preamble through one submission at OFFER_EXTENDED.

    Builds skill + client + open job order + candidate + submission(OFFER_EXTENDED).
    Returns a dict with keys: client, job_order, jo_version, candidate, submission,
    interview, recruiter, am, client_headers, candidate_headers.
    """
    create_skill(code=skill[0], category=skill[1])
    client = create_client(**(client_overrides or {}))
    job_order, jo_version = create_open_job_order(client["id"], **(job_order_overrides or {}))
    candidate = create_candidate(**(candidate_overrides or {}))
    submission, interview = drive_submission_to_offer_extended(
        job_order, candidate, client, submitted_pay_rate_cents=submitted_pay_rate_cents)
    return {
        "client": client,
        "job_order": job_order,
        "jo_version": jo_version,
        "candidate": candidate,
        "submission": submission,
        "interview": interview,
        "recruiter": RECRUITER,
        "am": AM,
        "client_headers": make_client_headers(client["id"]),
        "candidate_headers": make_candidate_headers(candidate["id"]),
    }


def create_placement(submission_id, jo_version, **overrides):
    """Create a placement from an OFFER_EXTENDED submission. Returns placement dict."""
    payload = factories.create_placement_payload(submission_id, jo_version, **overrides)
    return get_success_data(api_client.create_placement(payload, RECRUITER))


def start_placement(placement_id):
    """PENDING_START -> ACTIVE. Returns the updated placement dict."""
    return get_success_data(
        api_client.patch_placement(placement_id, {"target_assignment_status": "ACTIVE"}, RECRUITER)
    )


def end_placement(placement_id):
    """ACTIVE -> ENDED. Returns the updated placement dict."""
    return get_success_data(
        api_client.patch_placement(placement_id, {"target_assignment_status": "ENDED"}, RECRUITER)
    )


def setup_active_placement(client_overrides=None, job_order_overrides=None,
                           candidate_overrides=None, skill=("JAVA", "TECH"),
                           submitted_pay_rate_cents=8000, placement_overrides=None):
    """Full preamble through one ACTIVE placement.

    Returns the OFFER_EXTENDED scenario dict extended with keys:
    placement (ACTIVE).
    """
    scen = setup_offer_extended_scenario(
        client_overrides=client_overrides, job_order_overrides=job_order_overrides,
        candidate_overrides=candidate_overrides, skill=skill,
        submitted_pay_rate_cents=submitted_pay_rate_cents)
    placement = create_placement(scen["submission"]["id"], scen["jo_version"],
                                 **(placement_overrides or {}))
    placement = start_placement(placement["id"])
    scen["placement"] = placement
    return scen


# -----------------------------------------------------------------------------
# Tier 4: timesheet / invoice accumulation
# -----------------------------------------------------------------------------

def create_timesheet(placement_id, candidate_id, week_start, week_end, hours):
    """Create one timesheet on an ACTIVE placement (Candidate). Returns timesheet dict."""
    headers = make_candidate_headers(candidate_id)
    return get_success_data(api_client.create_timesheet(
        factories.create_timesheet_payload(
            placement_id, week_start=week_start, week_end=week_end, hours=hours),
        headers))


def submit_timesheet(timesheet_id, candidate_id):
    headers = make_candidate_headers(candidate_id)
    return get_success_data(
        api_client.patch_timesheet(timesheet_id, {"target_status": "SUBMITTED"}, headers))


def approve_timesheet(timesheet_id, client_id):
    headers = make_client_headers(client_id)
    return get_success_data(
        api_client.patch_timesheet(timesheet_id, {"target_status": "APPROVED"}, headers))


def reject_timesheet(timesheet_id, client_id):
    headers = make_client_headers(client_id)
    return get_success_data(
        api_client.patch_timesheet(timesheet_id, {"target_status": "REJECTED"}, headers))


def create_and_approve_timesheet(placement_id, candidate_id, client_id,
                                 week_start, week_end, hours):
    """Create -> SUBMITTED -> APPROVED. Returns the APPROVED timesheet dict."""
    ts = create_timesheet(placement_id, candidate_id, week_start, week_end, hours)
    submit_timesheet(ts["id"], candidate_id)
    return approve_timesheet(ts["id"], client_id)


def create_draft_invoice(client_id):
    """Create a DRAFT invoice for a client. Returns invoice dict."""
    return get_success_data(
        api_client.create_invoice(factories.create_invoice_payload(client_id), AM))


def add_line_item(invoice_id, timesheet_id):
    """Add one line item billing an APPROVED timesheet. Returns line item dict."""
    return get_success_data(api_client.add_invoice_line_item(
        invoice_id, factories.create_line_item_payload(timesheet_id), AM))


def issue_invoice(invoice_id):
    return get_success_data(
        api_client.patch_invoice(invoice_id, {"target_status": "ISSUED"}, AM))


def void_invoice(invoice_id):
    return get_success_data(
        api_client.patch_invoice(invoice_id, {"target_status": "VOID"}, AM))


def setup_issued_invoice_one_timesheet(hours=40):
    """ACTIVE placement -> one APPROVED timesheet -> DRAFT invoice + line item -> ISSUED.

    Returns the active-placement scenario dict extended with keys:
    timesheet (INVOICED), invoice (ISSUED), line_item.
    """
    scen = setup_active_placement()
    ts = create_and_approve_timesheet(
        scen["placement"]["id"], scen["candidate"]["id"], scen["client"]["id"],
        "2026-06-15T00:00:00Z", "2026-06-22T00:00:00Z", hours)
    inv = create_draft_invoice(scen["client"]["id"])
    li = add_line_item(inv["id"], ts["id"])
    inv = issue_invoice(inv["id"])
    scen["timesheet"] = ts
    scen["invoice"] = inv
    scen["line_item"] = li
    return scen
