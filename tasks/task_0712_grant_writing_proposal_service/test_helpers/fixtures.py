"""Composite setup helpers.

The system is killed and relaunched (empty DB) before every pytest test, so each
fixture builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() (lenient) so a setup failure raises a clear
"Setup failed" assertion rather than a confusing downstream error.

Identity threading: ClientContact is entity-backed by Client. Whenever a fixture
performs a ClientContact ownership-gated call (proposal request-changes/approve,
deliverable approve, revision-request create) it builds headers with
make_client_contact_headers(client["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_client_contact_headers
from .factories import (
    create_client_payload, create_opportunity_payload, create_engagement_payload,
    create_match_payload, create_proposal_payload, create_budget_line_payload,
    create_deliverable_payload, create_time_entry_payload, unique_ein,
)

AM = TEST_USERS["account_manager_headers"]
GW = TEST_USERS["grant_writer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["ops_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(iso: str):
    return get_success_data(api_client.set_clock(iso, OPS))


def reset_clock_default():
    """Pin the logical clock to the server-startup default 2026-03-01T00:00:00Z."""
    return set_clock("2026-03-01T00:00:00Z")


# --------------------------------------------------------------------------
# Tier 0: single-entity primitives
# --------------------------------------------------------------------------
def create_client(**overrides):
    return get_success_data(api_client.create_client(create_client_payload(**overrides), AM))


def create_opportunity(**overrides):
    return get_success_data(api_client.create_opportunity(create_opportunity_payload(**overrides), AM))


def create_engagement(client_id, **overrides):
    payload = create_engagement_payload(client_id=client_id, **overrides)
    return get_success_data(api_client.create_engagement(payload, AM))


def create_active_engagement(client_id, **overrides):
    """Create an engagement and activate it (DRAFT -> ACTIVE). Client must be ACTIVE."""
    eng = create_engagement(client_id, **overrides)
    get_success_data(api_client.activate_engagement(eng["id"], AM))
    return get_success_data(api_client.get_engagement(eng["id"], AM))


def create_pursuing_match(client_id, opportunity_id, actor=AM):
    """Create a match and move PROPOSED -> PURSUING."""
    m = get_success_data(api_client.create_match(
        create_match_payload(client_id=client_id, opportunity_id=opportunity_id), actor))
    get_success_data(api_client.pursue_match(m["id"], actor))
    return get_success_data(api_client.get_match(m["id"], actor))


# --------------------------------------------------------------------------
# Tier 1/2: a DRAFTING proposal sitting on an ACTIVE engagement + PURSUING match
# --------------------------------------------------------------------------
def setup_drafting_proposal(client_overrides=None, opp_overrides=None,
                            eng_overrides=None, requested_amount_cents=100_000):
    """Active client + opportunity + PURSUING match + active engagement + a DRAFTING
    proposal. Returns dict with client, opportunity, match, engagement, proposal."""
    client = create_client(**(client_overrides or {}))
    opp = create_opportunity(**(opp_overrides or {}))
    match = create_pursuing_match(client["id"], opp["id"])
    eng = create_active_engagement(client["id"], **(eng_overrides or {}))
    prop = get_success_data(api_client.create_proposal(
        create_proposal_payload(engagement_id=eng["id"], match_id=match["id"],
                                requested_amount_cents=requested_amount_cents), GW))
    return {"client": client, "opportunity": opp, "match": match,
            "engagement": eng, "proposal": prop}


def add_budget_line(proposal_id, **overrides):
    return get_success_data(api_client.create_budget_line(
        create_budget_line_payload(proposal_id=proposal_id, **overrides), GW))


def add_deliverable(proposal_id, **overrides):
    return get_success_data(api_client.create_deliverable(
        create_deliverable_payload(proposal_id=proposal_id, **overrides), GW))


def setup_review_ready_proposal(client_overrides=None, opp_overrides=None,
                                requested_amount_cents=100_000, budget_amount_cents=100_000):
    """A DRAFTING proposal that already has a NARRATIVE deliverable and a non-zero
    budget, so submit-for-review will pass its content gates. Returns the
    setup_drafting_proposal dict plus 'deliverable' and 'budget_line'."""
    ctx = setup_drafting_proposal(client_overrides=client_overrides,
                                  opp_overrides=opp_overrides,
                                  requested_amount_cents=requested_amount_cents)
    bl = add_budget_line(ctx["proposal"]["id"], category="PERSONNEL",
                         label="Staff", amount_cents=budget_amount_cents)
    deliv = add_deliverable(ctx["proposal"]["id"], kind="NARRATIVE",
                            title="Narrative", body="b")
    ctx["budget_line"] = bl
    ctx["deliverable"] = deliv
    return ctx


def setup_approved_proposal(client_overrides=None, opp_overrides=None,
                            requested_amount_cents=100_000, budget_amount_cents=100_000):
    """A proposal driven all the way to APPROVED: its NARRATIVE deliverable is
    approved by the owning ClientContact, then submit-for-review and approve.
    Returns the setup_review_ready_proposal dict; proposal reflects APPROVED."""
    ctx = setup_review_ready_proposal(client_overrides=client_overrides,
                                      opp_overrides=opp_overrides,
                                      requested_amount_cents=requested_amount_cents,
                                      budget_amount_cents=budget_amount_cents)
    cc = make_client_contact_headers(ctx["client"]["id"])
    get_success_data(api_client.advance_deliverable_content(ctx["deliverable"]["id"], GW))
    get_success_data(api_client.approve_deliverable(ctx["deliverable"]["id"], cc))
    get_success_data(api_client.submit_proposal_for_review(ctx["proposal"]["id"], GW))
    get_success_data(api_client.approve_proposal(ctx["proposal"]["id"], cc))
    ctx["proposal"] = get_success_data(api_client.get_proposal(ctx["proposal"]["id"], GW))
    return ctx


# --------------------------------------------------------------------------
# Tier 3: full lifecycle through a FILED submission, ACCEPTED submission, Award
# --------------------------------------------------------------------------
def setup_filed_submission(client_overrides=None, opp_overrides=None,
                           requested_amount_cents=100_000, decision_due_utc=None):
    """Build an APPROVED proposal, read its current version, and file a Submission.
    Returns the setup_approved_proposal dict plus 'submission'."""
    ctx = setup_approved_proposal(client_overrides=client_overrides,
                                  opp_overrides=opp_overrides,
                                  requested_amount_cents=requested_amount_cents)
    prop_v = ctx["proposal"]["version"]
    payload = {"proposal_id": ctx["proposal"]["id"], "expected_proposal_version": prop_v}
    if decision_due_utc is not None:
        payload["decision_due_utc"] = decision_due_utc
    sub = get_success_data(api_client.create_submission(payload, GW))
    ctx["submission"] = sub
    return ctx


def setup_accepted_submission(client_overrides=None, opp_overrides=None,
                              requested_amount_cents=100_000):
    """A submission filed and then recorded ACCEPTED. Returns the
    setup_filed_submission dict; submission reflects ACCEPTED."""
    ctx = setup_filed_submission(client_overrides=client_overrides,
                                 opp_overrides=opp_overrides,
                                 requested_amount_cents=requested_amount_cents)
    get_success_data(api_client.record_decision(ctx["submission"]["id"], "ACCEPTED", AM))
    ctx["submission"] = get_success_data(api_client.get_submission(ctx["submission"]["id"], AM))
    return ctx


def setup_active_award(client_overrides=None, opp_overrides=None,
                       awarded_amount_cents=1_000_000,
                       period_of_performance_months=12, report_cadence_months=3):
    """An ACTIVE award created from an ACCEPTED submission (current submission
    version threaded into expected_submission_version). Returns the
    setup_accepted_submission dict plus 'award'."""
    ctx = setup_accepted_submission(client_overrides=client_overrides,
                                    opp_overrides=opp_overrides)
    sub_v = ctx["submission"]["version"]
    award = get_success_data(api_client.create_award({
        "submission_id": ctx["submission"]["id"],
        "expected_submission_version": sub_v,
        "awarded_amount_cents": awarded_amount_cents,
        "period_of_performance_months": period_of_performance_months,
        "report_cadence_months": report_cadence_months,
    }, CO))
    ctx["award"] = award
    return ctx


# --------------------------------------------------------------------------
# Tier 4: time-entry / billing setups
# --------------------------------------------------------------------------
def setup_engagement_with_time(fee_model="HOURLY", time_entries=None, **eng_overrides):
    """An ACTIVE engagement of the given fee_model with the supplied LOGGED time
    entries. time_entries is a list of dicts each with at least minutes+period_yyyymm.
    Returns dict with client, engagement, time_entries (created entities)."""
    client = create_client()
    eng = create_active_engagement(client["id"], fee_model=fee_model, **eng_overrides)
    created = []
    for te in (time_entries or []):
        payload = create_time_entry_payload(engagement_id=eng["id"], **te)
        created.append(get_success_data(api_client.create_time_entry(payload, GW)))
    return {"client": client, "engagement": eng, "time_entries": created}


def get_engagement(eng_id):
    return get_success_data(api_client.get_engagement(eng_id, AM))


def get_client(client_id):
    return get_success_data(api_client.get_client(client_id, AM))


def get_proposal(prop_id):
    return get_success_data(api_client.get_proposal(prop_id, GW))


def get_submission(sub_id):
    return get_success_data(api_client.get_submission(sub_id, AM))


def get_deliverable(deliv_id):
    return get_success_data(api_client.get_deliverable(deliv_id, GW))


def get_award(award_id):
    return get_success_data(api_client.get_award(award_id, CO))


def get_revision_request(rev_id):
    return get_success_data(api_client.get_revision_request(rev_id, GW))


def get_invoice(inv_id):
    return get_success_data(api_client.get_invoice(inv_id, AM))


def get_time_entry(te_id):
    return get_success_data(api_client.get_time_entry(te_id, GW))


def get_boilerplate(snip_id):
    return get_success_data(api_client.get_boilerplate(snip_id, GW))


# --------------------------------------------------------------------------
# Tier: a DRAFTED deliverable with an OPEN revision request (open_revision_count=1)
# --------------------------------------------------------------------------
def setup_drafted_deliverable_with_open_revision():
    """A NARRATIVE deliverable advanced to content_status=DRAFTED carrying one OPEN
    RevisionRequest (open_revision_count=1, approval_status=CHANGES_REQUESTED).
    Returns dict with client, proposal, deliverable, revision."""
    ctx = setup_drafting_proposal()
    cc = make_client_contact_headers(ctx["client"]["id"])
    deliv = add_deliverable(ctx["proposal"]["id"], kind="NARRATIVE",
                            title="Narrative", body="drafted body")
    get_success_data(api_client.advance_deliverable_content(deliv["id"], GW))
    rev = get_success_data(api_client.create_revision_request(
        {"deliverable_id": deliv["id"], "note": "Please revise"}, cc))
    ctx["deliverable"] = deliv
    ctx["revision"] = rev
    return ctx
