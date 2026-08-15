"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build complete precondition chains —
syndication activation, offering open, the subscription review pipeline,
capital-call escrow funding, quarterly reports, distributions, capital events,
K-1 packages, and transfer requests — out of PRD-declared endpoints only.

Identity threading: the Investor role is entity-backed (PRD §2.1), so every
ownership-gated call uses make_investor_headers(investor["id"]). Segregation
of duties (PRD §3.3) is honored by verifying accreditation with the first
compliance desk and approving suitability with the second.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_capital_call_payload,
    create_capital_event_payload,
    create_distribution_payload,
    create_document_payload,
    create_investor_payload,
    create_k1_package_payload,
    create_offering_payload,
    create_property_payload,
    create_quarterly_report_payload,
    create_subscription_payload,
    create_syndication_payload,
    create_transfer_request_payload,
    receive_escrow_payload,
)
from .test_users import TEST_USERS, make_investor_headers
from .types import DocType

SPONSOR = TEST_USERS["sponsor_operator_headers"]
OFFICER_1 = TEST_USERS["compliance_officer_headers"]
OFFICER_2 = TEST_USERS["compliance_officer_2_headers"]
AGENT = TEST_USERS["transfer_agent_headers"]

REQUIRED_DOC_TYPES = (
    DocType.SUBSCRIPTION_AGREEMENT.value,
    DocType.W9.value,
    DocType.SUITABILITY_QUESTIONNAIRE.value,
)
ALL_DOC_TYPES = REQUIRED_DOC_TYPES + (DocType.ACCREDITATION_LETTER.value,)


def _inv_headers(investor):
    return make_investor_headers(investor["id"])


# ---------------------------------------------------------------------------
# Tier 0/1: single-entity creators and readers
# ---------------------------------------------------------------------------

def make_syndication(**overrides):
    """Create a syndication (starts DRAFT)."""
    return get_success_data(api_client.create_syndication(
        create_syndication_payload(**overrides), SPONSOR))


def make_active_syndication(**overrides):
    """Create a syndication and activate it."""
    syn = make_syndication(**overrides)
    return get_success_data(api_client.activate_syndication(syn["id"], SPONSOR))


def make_property(**overrides):
    """Register a property (starts OWNED)."""
    return get_success_data(api_client.create_property(
        create_property_payload(**overrides), SPONSOR))


def make_investor(**overrides):
    """Register an investor (portal_access_status starts INVITED)."""
    return get_success_data(api_client.create_investor(
        create_investor_payload(**overrides), SPONSOR))


def make_offering(syndication_id, property_id=None, **overrides):
    """Create a DRAFT offering under the syndication (creates a property when
    property_id is not supplied)."""
    if property_id is None:
        property_id = make_property()["id"]
    return get_success_data(api_client.create_offering(
        syndication_id, create_offering_payload(property_id, **overrides), SPONSOR))


def make_open_offering(syndication_id, property_id=None, **overrides):
    """Create a DRAFT offering and open it. Returns the OPEN offering."""
    offering = make_offering(syndication_id, property_id, **overrides)
    return get_success_data(api_client.open_offering(
        syndication_id, offering["id"], SPONSOR))


def get_syndication(syndication_id):
    return get_success_data(api_client.get_syndication(syndication_id, SPONSOR))


def get_property(property_id):
    return get_success_data(api_client.get_property(property_id, SPONSOR))


def get_offering(syndication_id, offering_id):
    return get_success_data(api_client.get_offering(syndication_id, offering_id,
                                                    SPONSOR))


def get_subscription(syndication_id, offering_id, subscription_id):
    return get_success_data(api_client.get_subscription(
        syndication_id, offering_id, subscription_id, SPONSOR))


def get_capital_call(syndication_id, offering_id, capital_call_id):
    return get_success_data(api_client.get_capital_call(
        syndication_id, offering_id, capital_call_id, SPONSOR))


def get_contribution(syndication_id, offering_id, capital_call_id, contribution_id):
    return get_success_data(api_client.get_contribution(
        syndication_id, offering_id, capital_call_id, contribution_id, SPONSOR))


def get_quarterly_report(syndication_id, offering_id, quarterly_report_id):
    return get_success_data(api_client.get_quarterly_report(
        syndication_id, offering_id, quarterly_report_id, SPONSOR))


def get_document(syndication_id, offering_id, subscription_id, document_id):
    return get_success_data(api_client.get_document(
        syndication_id, offering_id, subscription_id, document_id, SPONSOR))


def get_k1_package(syndication_id, offering_id, k1_package_id):
    return get_success_data(api_client.get_k1_package(
        syndication_id, offering_id, k1_package_id, SPONSOR))


def get_distribution(syndication_id, offering_id, distribution_id):
    return get_success_data(api_client.get_distribution(
        syndication_id, offering_id, distribution_id, SPONSOR))


def get_capital_event(syndication_id, property_id, capital_event_id):
    return get_success_data(api_client.get_capital_event(
        syndication_id, property_id, capital_event_id, SPONSOR))


def get_transfer_request(syndication_id, offering_id, subscription_id,
                         transfer_request_id):
    return get_success_data(api_client.get_transfer_request(
        syndication_id, offering_id, subscription_id, transfer_request_id, SPONSOR))


def set_clock(to_iso8601):
    """Advance the server's logical clock (SponsorOperator-only, PRD §2.8)."""
    return get_success_data(api_client.set_clock(to_iso8601, SPONSOR))


# ---------------------------------------------------------------------------
# Tier 2: subscription review pipeline
# ---------------------------------------------------------------------------

def make_draft_subscription(offering, investor, committed_cents=5_000_000,
                            syndication_id=None):
    """Create a DRAFT subscription as the investor (ownership-threaded)."""
    syn_id = syndication_id or offering["syndication_id"]
    return get_success_data(api_client.create_subscription(
        syn_id, offering["id"],
        create_subscription_payload(investor["id"], committed_cents),
        _inv_headers(investor)))


def upload_and_review_documents(syndication_id, offering_id, subscription_id,
                                investor_id, upload_types=ALL_DOC_TYPES,
                                accept_types=None):
    """Upload each doc_type as the owning investor, then let a compliance
    officer accept every type in accept_types (default: all uploaded types).
    Returns {doc_type: document_dict}."""
    if accept_types is None:
        accept_types = upload_types
    docs = {}
    for doc_type in upload_types:
        docs[doc_type] = get_success_data(api_client.upload_document(
            syndication_id, offering_id, subscription_id,
            create_document_payload(doc_type=doc_type),
            make_investor_headers(investor_id)))
    for doc_type in accept_types:
        docs[doc_type] = get_success_data(api_client.accept_document(
            syndication_id, offering_id, subscription_id, docs[doc_type]["id"],
            OFFICER_1))
    return docs


def submit_subscription(syndication_id, offering_id, subscription_id, investor_id):
    return get_success_data(api_client.submit_subscription(
        syndication_id, offering_id, subscription_id,
        make_investor_headers(investor_id)))


def make_submitted_subscription(offering, investor, committed_cents=5_000_000,
                                syndication_id=None, doc_upload_types=ALL_DOC_TYPES,
                                doc_accept_types=None):
    """DRAFT subscription with documents uploaded/accepted, then SUBMITTED."""
    syn_id = syndication_id or offering["syndication_id"]
    sub = make_draft_subscription(offering, investor, committed_cents, syn_id)
    upload_and_review_documents(syn_id, offering["id"], sub["id"], investor["id"],
                                upload_types=doc_upload_types,
                                accept_types=doc_accept_types)
    return submit_subscription(syn_id, offering["id"], sub["id"], investor["id"])


def verify_accreditation(syndication_id, offering_id, subscription_id, officer=None):
    """Verify accreditation with the first compliance desk by default."""
    return get_success_data(api_client.verify_accreditation(
        syndication_id, offering_id, subscription_id, officer or OFFICER_1))


def approve_suitability(syndication_id, offering_id, subscription_id, officer=None):
    """Approve suitability with the SECOND compliance desk by default, so the
    approver differs from the verifier (segregation of duties, PRD §3.3)."""
    return get_success_data(api_client.approve_suitability(
        syndication_id, offering_id, subscription_id, officer or OFFICER_2))


def make_accreditation_verified_subscription(offering, investor,
                                             committed_cents=5_000_000,
                                             syndication_id=None):
    """Subscription driven DRAFT -> SUBMITTED -> ACCREDITATION_VERIFIED."""
    syn_id = syndication_id or offering["syndication_id"]
    sub = make_submitted_subscription(offering, investor, committed_cents, syn_id)
    return verify_accreditation(syn_id, offering["id"], sub["id"])


def make_awaiting_funding_subscription(offering, investor, committed_cents=5_000_000,
                                       syndication_id=None):
    """Subscription driven through approval, landing in AWAITING_FUNDING."""
    syn_id = syndication_id or offering["syndication_id"]
    sub = make_accreditation_verified_subscription(
        offering, investor, committed_cents, syn_id)
    return approve_suitability(syn_id, offering["id"], sub["id"])


# ---------------------------------------------------------------------------
# Tier 3: capital calls and escrow funding
# ---------------------------------------------------------------------------

def issue_capital_call(syndication_id, offering_id, total_call_cents,
                       due_date="2027-01-01T00:00:00Z"):
    """Create + issue a capital call. Returns (call, contributions list) with
    contributions matched to subscriptions via their subscription_id field."""
    call = get_success_data(api_client.create_capital_call(
        syndication_id, offering_id,
        create_capital_call_payload(total_call_cents, due_date), SPONSOR))
    call = get_success_data(api_client.issue_capital_call(
        syndication_id, offering_id, call["id"], SPONSOR))
    contribs = get_success_data(api_client.list_contributions(
        syndication_id, offering_id, call["id"], SPONSOR))
    assert isinstance(contribs, list), "Setup failed: contributions list not an array"
    return call, contribs


def contribution_for(contribs, subscription_id):
    """Find the synthesized contribution for a subscription."""
    for c in contribs:
        if c.get("subscription_id") == subscription_id:
            return c
    raise AssertionError(
        f"Setup failed: no contribution synthesized for subscription {subscription_id}")


def fund_contribution(syndication_id, offering_id, capital_call_id, contribution,
                      investor, amount_cents=None):
    """Investor wires escrow, sponsor releases it. Returns the RELEASED
    contribution."""
    amount = (amount_cents if amount_cents is not None
              else contribution["amount_due_cents"])
    get_success_data(api_client.receive_escrow(
        syndication_id, offering_id, capital_call_id, contribution["id"],
        receive_escrow_payload(amount), _inv_headers(investor)))
    return get_success_data(api_client.release_escrow(
        syndication_id, offering_id, capital_call_id, contribution["id"], SPONSOR))


def setup_offering_with_approved_subscriptions(commitments, pref=0.08, carry=0.20,
                                               min_subscription_cents=10_000,
                                               offering_overrides=None):
    """Active syndication + OWNED property + OPEN offering + one investor per
    commitment, each subscription driven to AWAITING_FUNDING with all four
    document types accepted. Returns a context dict."""
    syn = make_active_syndication(preferred_return_pct_annual=pref,
                                  carried_interest_pct=carry)
    prop = make_property()
    overrides = {"preferred_return_pct_annual": pref, "carried_interest_pct": carry,
                 "min_subscription_cents": min_subscription_cents}
    if offering_overrides:
        overrides.update(offering_overrides)
    off = make_open_offering(syn["id"], prop["id"], **overrides)
    investors, subs = [], []
    for committed in commitments:
        inv = make_investor()
        sub = make_awaiting_funding_subscription(off, inv, committed, syn["id"])
        investors.append(inv)
        subs.append(sub)
    return {"syn": syn, "prop": prop, "off": off, "investors": investors,
            "subs": subs}


def setup_funded_offering(commitments, pref=0.08, carry=0.20, fund_at=None,
                          min_subscription_cents=10_000, offering_overrides=None):
    """Full funding pipeline: one capital call for the exact committed total,
    every contribution received and released, every subscription FUNDED.
    Returns a context dict with call/contributions and fresh entity reads."""
    ctx = setup_offering_with_approved_subscriptions(
        commitments, pref=pref, carry=carry,
        min_subscription_cents=min_subscription_cents,
        offering_overrides=offering_overrides)
    if fund_at is not None:
        set_clock(fund_at)
    total = sum(commitments)
    call, contribs = issue_capital_call(ctx["syn"]["id"], ctx["off"]["id"], total)
    for sub, inv in zip(ctx["subs"], ctx["investors"]):
        fund_contribution(ctx["syn"]["id"], ctx["off"]["id"], call["id"],
                          contribution_for(contribs, sub["id"]), inv)
    ctx["call"] = get_capital_call(ctx["syn"]["id"], ctx["off"]["id"], call["id"])
    ctx["contributions"] = [
        get_contribution(ctx["syn"]["id"], ctx["off"]["id"], call["id"], c["id"])
        for c in contribs]
    ctx["subs"] = [get_subscription(ctx["syn"]["id"], ctx["off"]["id"], s["id"])
                   for s in ctx["subs"]]
    ctx["off"] = get_offering(ctx["syn"]["id"], ctx["off"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: quarterly reports and distributions
# ---------------------------------------------------------------------------

def make_published_report(syndication_id, offering_id, report_year=2026,
                          report_quarter=1, noi_cents=10_000_000,
                          occupancy_pct=0.95):
    """Create + publish a quarterly report."""
    report = get_success_data(api_client.create_quarterly_report(
        syndication_id, offering_id,
        create_quarterly_report_payload(report_year=report_year,
                                        report_quarter=report_quarter,
                                        noi_cents=noi_cents,
                                        occupancy_pct=occupancy_pct),
        SPONSOR))
    return get_success_data(api_client.publish_quarterly_report(
        syndication_id, offering_id, report["id"], SPONSOR))


def make_calculated_distribution(syndication_id, offering_id, distribution_kind,
                                 total_distributable_cents, quarterly_report_id=None,
                                 capital_event_id=None):
    """Create + calculate a distribution. Returns the CALCULATED distribution."""
    dist = get_success_data(api_client.create_distribution(
        syndication_id, offering_id,
        create_distribution_payload(
            distribution_kind, total_distributable_cents,
            quarterly_report_id=quarterly_report_id,
            capital_event_id=capital_event_id),
        SPONSOR))
    return get_success_data(api_client.calculate_distribution(
        syndication_id, offering_id, dist["id"], SPONSOR))


def approve_distribution(syndication_id, offering_id, distribution_id):
    """Approve a CALCULATED distribution with its current version (OCC)."""
    dist = get_distribution(syndication_id, offering_id, distribution_id)
    return get_success_data(api_client.approve_distribution(
        syndication_id, offering_id, distribution_id,
        {"expected_distribution_version": dist["version"]}, SPONSOR))


def make_approved_distribution(syndication_id, offering_id, distribution_kind,
                               total_distributable_cents, quarterly_report_id=None,
                               capital_event_id=None):
    dist = make_calculated_distribution(
        syndication_id, offering_id, distribution_kind, total_distributable_cents,
        quarterly_report_id=quarterly_report_id, capital_event_id=capital_event_id)
    return approve_distribution(syndication_id, offering_id, dist["id"])


def make_paid_distribution(syndication_id, offering_id, distribution_kind,
                           total_distributable_cents, quarterly_report_id=None,
                           capital_event_id=None):
    dist = make_approved_distribution(
        syndication_id, offering_id, distribution_kind, total_distributable_cents,
        quarterly_report_id=quarterly_report_id, capital_event_id=capital_event_id)
    return get_success_data(api_client.pay_distribution(
        syndication_id, offering_id, dist["id"], SPONSOR))


def list_distribution_lines(syndication_id, offering_id, distribution_id):
    lines = get_success_data(api_client.list_distribution_lines(
        syndication_id, offering_id, distribution_id, SPONSOR))
    assert isinstance(lines, list), "Setup failed: distribution lines not an array"
    return lines


# ---------------------------------------------------------------------------
# Tier 5: capital events and K-1 packages
# ---------------------------------------------------------------------------

def make_capital_event(syndication_id, property_id, event_kind="REFINANCE",
                       gross_proceeds_cents=6_000_000, debt_payoff_cents=1_000_000):
    """Announce a capital event (starts ANNOUNCED)."""
    return get_success_data(api_client.create_capital_event(
        syndication_id, property_id,
        create_capital_event_payload(
            event_kind=event_kind, gross_proceeds_cents=gross_proceeds_cents,
            debt_payoff_cents=debt_payoff_cents),
        SPONSOR))


def make_executed_capital_event(syndication_id, property_id, event_kind="REFINANCE",
                                gross_proceeds_cents=6_000_000,
                                debt_payoff_cents=1_000_000):
    """Announce + execute a capital event."""
    event = make_capital_event(syndication_id, property_id, event_kind,
                               gross_proceeds_cents, debt_payoff_cents)
    return get_success_data(api_client.execute_capital_event(
        syndication_id, property_id, event["id"], SPONSOR))


def make_k1_package(syndication_id, offering_id, tax_year=2026,
                    preparer_firm="Test CPA LLP"):
    return get_success_data(api_client.create_k1_package(
        syndication_id, offering_id,
        create_k1_package_payload(tax_year=tax_year, preparer_firm=preparer_firm),
        SPONSOR))


def make_k1_in_partner_review(syndication_id, offering_id, tax_year=2026):
    pkg = make_k1_package(syndication_id, offering_id, tax_year)
    return get_success_data(api_client.submit_k1_for_review(
        syndication_id, offering_id, pkg["id"], SPONSOR))


# ---------------------------------------------------------------------------
# Tier 6: transfer requests
# ---------------------------------------------------------------------------

def make_transfer_request(syndication_id, offering_id, from_subscription,
                          to_investor_id, transfer_cents):
    """Create a transfer request as the selling investor with a fresh OCC
    read of the subscription version."""
    fresh = get_subscription(syndication_id, offering_id, from_subscription["id"])
    return get_success_data(api_client.create_transfer_request(
        syndication_id, offering_id, from_subscription["id"],
        create_transfer_request_payload(to_investor_id, transfer_cents,
                                        fresh["version"]),
        make_investor_headers(fresh["investor_id"])))


def make_agent_approved_transfer(syndication_id, offering_id, from_subscription,
                                 to_investor_id, transfer_cents):
    """Transfer request walked through sponsor approval and agent approval."""
    tr = make_transfer_request(syndication_id, offering_id, from_subscription,
                               to_investor_id, transfer_cents)
    get_success_data(api_client.sponsor_approve_transfer(
        syndication_id, offering_id, from_subscription["id"], tr["id"], SPONSOR))
    return get_success_data(api_client.agent_approve_transfer(
        syndication_id, offering_id, from_subscription["id"], tr["id"], AGENT))
