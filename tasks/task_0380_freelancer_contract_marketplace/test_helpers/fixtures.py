"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked through many API calls to reach
the state under test (post → bid → accept → activate → milestone → fund → submit → ...).
These helpers encapsulate those preambles. They use get_success_data() (lenient validator)
so a setup failure surfaces as a clear "Setup failed" error rather than a confusing
assertion deep inside a test.

Identity threading: Client and Freelancer are entity-backed. Every ownership-gated call
uses make_client_headers(client["id"]) / make_freelancer_headers(freelancer["id"]) with the
REAL entity id — never the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_client_payload, create_freelancer_payload, deposit_payload,
    create_job_posting_payload, create_proposal_payload, accept_payload,
    activate_contract_payload, create_milestone_payload, fund_payload, release_payload,
    create_timelog_payload, dispute_payload, resolve_payload, create_review_payload,
    create_tax_record_payload,
)
from .test_users import (
    make_client_headers, make_freelancer_headers, make_arbitrator_headers, make_admin_headers,
)


# ─── Tier 0: Principals ───────────────────────────────────────────────
def create_client(deposit_cents: int = 0, **overrides) -> dict:
    """Create a Client (admin op); optionally top up its wallet. Returns the Client dict
    (after deposit, so wallet_balance_cents reflects the deposit)."""
    client = get_success_data(api_client.create_client(
        create_client_payload(**overrides), make_admin_headers()))
    if deposit_cents > 0:
        client = get_success_data(api_client.deposit_wallet(
            client["id"], deposit_payload(deposit_cents), make_admin_headers()))
    return client


def create_freelancer(skills=None, tax_id_on_file=None, **overrides) -> dict:
    """Create a Freelancer (admin op). Returns the Freelancer dict."""
    payload = create_freelancer_payload(**overrides)
    if skills is not None:
        payload["skills"] = skills
    if tax_id_on_file is not None:
        payload["tax_id_on_file"] = tax_id_on_file
    return get_success_data(api_client.create_freelancer(payload, make_admin_headers()))


# ─── Tier 1: Awarded / activated contract ─────────────────────────────
def create_active_contract(billing_type="FIXED", skills=("python",),
                           bid_amount_cents=20000, budget_cents=30000,
                           deposit_cents=0, tax_id_on_file=True,
                           hourly_cap_hours=None, sow_text="Statement of work."):
    """Walk: client (+deposit) -> freelancer -> posting -> proposal -> accept -> activate.

    Returns a dict with keys: client, freelancer, posting, proposal, contract,
    client_headers, freelancer_headers. The contract is ACTIVE.
    """
    skills = list(skills)
    client = create_client(deposit_cents=deposit_cents)
    ch = make_client_headers(client["id"])
    freelancer = create_freelancer(skills=skills, tax_id_on_file=tax_id_on_file)
    fh = make_freelancer_headers(freelancer["id"])

    posting = get_success_data(api_client.create_job_posting(
        create_job_posting_payload(client["id"], billing_type=billing_type,
                                   budget_cents=budget_cents, required_skills=skills), ch))
    proposal = get_success_data(api_client.create_proposal(
        create_proposal_payload(posting["id"], freelancer["id"],
                                bid_amount_cents=bid_amount_cents), fh))
    accepted = get_success_data(api_client.accept_proposal(
        proposal["id"], accept_payload("CLIENT"), ch))

    # Accepting a proposal creates a DRAFT Contract (PRD §3.2/§3.3). Resolve it from the
    # client's contracts list, matching on the originating proposal where exposed.
    contracts = get_success_data(api_client.list_client_contracts(client["id"], ch))
    assert isinstance(contracts, list) and contracts, (
        "Setup failed: no contract created after proposal accept")
    contract = next(
        (c for c in contracts if c.get("proposal_id") == proposal["id"]),
        contracts[-1],
    )

    activate_body = activate_contract_payload(sow_text=sow_text)
    if hourly_cap_hours is not None:
        activate_body["hourly_cap_hours"] = hourly_cap_hours
    contract = get_success_data(api_client.activate_contract(contract["id"], activate_body, ch))

    return {
        "client": client, "freelancer": freelancer, "posting": posting,
        "proposal": accepted, "contract": contract,
        "client_headers": ch, "freelancer_headers": fh,
    }


def _contract_version(contract_id, client_headers) -> int:
    return get_success_data(api_client.get_contract(contract_id, client_headers))["version"]


# ─── Tier 2: Milestone lifecycle shortcuts (FIXED contracts) ──────────
def add_milestone(ctx, amount_cents, ordinal, title="M"):
    """Create a DRAFT milestone on an ACTIVE FIXED contract in ctx. Returns the milestone."""
    return get_success_data(api_client.create_milestone(
        ctx["contract"]["id"],
        create_milestone_payload(title=title, amount_cents=amount_cents, ordinal=ordinal),
        ctx["client_headers"]))


def fund_milestone(ctx, milestone_id):
    """Fund a DRAFT milestone reading the live contract version for the OCC field.
    Returns the milestone after funding."""
    cv = _contract_version(ctx["contract"]["id"], ctx["client_headers"])
    return get_success_data(api_client.fund_milestone(
        ctx["contract"]["id"], milestone_id, fund_payload(cv), ctx["client_headers"]))


def setup_funded_milestone(amount_cents=20000, budget_cents=30000, **kwargs):
    """Active FIXED contract with one FUNDED milestone. Returns (ctx, milestone)."""
    deposit = kwargs.pop("deposit_cents", amount_cents)
    ctx = create_active_contract(billing_type="FIXED", budget_cents=budget_cents,
                                 bid_amount_cents=amount_cents, deposit_cents=deposit, **kwargs)
    m = add_milestone(ctx, amount_cents, ordinal=1)
    m = fund_milestone(ctx, m["id"])
    return ctx, m


def setup_submitted_milestone(amount_cents=20000, **kwargs):
    """Active FIXED contract with one FUNDED->SUBMITTED milestone. Returns (ctx, milestone)."""
    ctx, m = setup_funded_milestone(amount_cents=amount_cents, **kwargs)
    get_success_data(api_client.submit_milestone(
        ctx["contract"]["id"], m["id"], ctx["freelancer_headers"]))
    m = get_success_data(api_client.get_milestone_in_contract(
        ctx["contract"]["id"], m["id"], ctx["client_headers"]))
    return ctx, m


def setup_approved_milestone(amount_cents=20000, **kwargs):
    """Active FIXED contract with one FUNDED->SUBMITTED->APPROVED milestone. Returns (ctx, milestone)."""
    ctx, m = setup_submitted_milestone(amount_cents=amount_cents, **kwargs)
    m = get_success_data(api_client.approve_milestone(
        ctx["contract"]["id"], m["id"], ctx["client_headers"]))
    return ctx, m


def release_milestone(ctx, milestone_id):
    """Release an APPROVED milestone reading the live contract version. Returns the milestone."""
    cv = _contract_version(ctx["contract"]["id"], ctx["client_headers"])
    return get_success_data(api_client.release_milestone(
        ctx["contract"]["id"], milestone_id, release_payload(cv), ctx["client_headers"]))


def setup_released_milestone(amount_cents=20000, **kwargs):
    """Active FIXED contract with one milestone walked through to RELEASED. Returns (ctx, milestone)."""
    ctx, m = setup_approved_milestone(amount_cents=amount_cents, **kwargs)
    m = release_milestone(ctx, m["id"])
    return ctx, m


def milestone_payout(milestone_id) -> dict:
    """Return the single Payout created for a released milestone (admin read)."""
    payouts = get_success_data(api_client.list_milestone_payouts(milestone_id, make_admin_headers()))
    assert isinstance(payouts, list) and payouts, "Setup failed: no payout for milestone"
    return get_success_data(api_client.get_payout(payouts[0]["id"], make_admin_headers()))


def setup_paid_payout(amount_cents=60000, tax_id_on_file=True, **kwargs):
    """Active FIXED contract -> release -> settle the payout (PAID if tax id on file).
    Returns (ctx, milestone, payout) with payout reflecting its settled state."""
    ctx, m = setup_released_milestone(amount_cents=amount_cents,
                                      tax_id_on_file=tax_id_on_file, **kwargs)
    payout = milestone_payout(m["id"])
    settled = get_success_data(api_client.settle_payout(payout["id"], make_admin_headers()))
    return ctx, m, settled


# ─── Tier 3: Dispute lifecycle shortcuts ──────────────────────────────
def setup_disputed_milestone(amount_cents=20000, raised_by="CLIENT", claimed=None, **kwargs):
    """Active FIXED contract with a SUBMITTED->DISPUTED milestone (dispute OPEN).
    Returns (ctx, milestone, dispute)."""
    ctx, m = setup_submitted_milestone(amount_cents=amount_cents, **kwargs)
    raiser = ctx["client_headers"] if raised_by == "CLIENT" else ctx["freelancer_headers"]
    claimed = amount_cents if claimed is None else claimed
    dispute = get_success_data(api_client.dispute_milestone(
        ctx["contract"]["id"], m["id"],
        dispute_payload(raised_by, claimed_release_cents=claimed), raiser))
    return ctx, m, dispute


def setup_dispute_under_arbitration(amount_cents=20000, raised_by="CLIENT", **kwargs):
    """Active FIXED contract with a DISPUTED milestone whose dispute is UNDER_ARBITRATION.
    Returns (ctx, milestone, dispute)."""
    ctx, m, dispute = setup_disputed_milestone(amount_cents=amount_cents,
                                               raised_by=raised_by, **kwargs)
    dispute = get_success_data(api_client.assign_arbitration(dispute["id"], make_arbitrator_headers()))
    return ctx, m, dispute


def resolve_dispute(dispute_id, award_cents):
    """Arbitrator resolves a dispute with the given award. Returns the dispute."""
    return get_success_data(api_client.resolve_dispute(
        dispute_id, resolve_payload(award_cents), make_arbitrator_headers()))


# ─── Tier 4: HOURLY contract + timelogs ───────────────────────────────
def create_active_hourly_contract(rate_cents=5000, skills=("python",),
                                  hourly_cap_hours=8, deposit_cents=100000):
    """Active HOURLY contract at the given agreed hourly rate. Returns the ctx dict."""
    return create_active_contract(
        billing_type="HOURLY", skills=skills, bid_amount_cents=rate_cents,
        budget_cents=10000, deposit_cents=deposit_cents, tax_id_on_file=True,
        hourly_cap_hours=hourly_cap_hours, sow_text="Hourly work.")


def add_hourly_milestone(ctx, ordinal=1, title="Week"):
    """Create a milestone on an HOURLY contract (amount recomputed from verified time)."""
    return get_success_data(api_client.create_milestone(
        ctx["contract"]["id"],
        create_milestone_payload(title=title, amount_cents=100, ordinal=ordinal),
        ctx["client_headers"]))


def add_timelog(ctx, milestone_id, work_date, start_minute, end_minute, memo="work"):
    """Create a LOGGED timelog on an HOURLY contract. Returns the timelog (or the raw
    response when the caller needs to assert an error — use api_client directly for that)."""
    return get_success_data(api_client.create_timelog(
        ctx["contract"]["id"],
        create_timelog_payload(milestone_id, work_date, start_minute, end_minute, memo),
        ctx["freelancer_headers"]))


def verify_timelog(ctx, timelog_id):
    """Verify a LOGGED timelog. Returns the timelog."""
    return get_success_data(api_client.verify_timelog(
        ctx["contract"]["id"], timelog_id, ctx["client_headers"]))


# ─── Tier 5: Completed contract + review ──────────────────────────────
def setup_completed_contract(amount_cents=20000, **kwargs):
    """Active FIXED contract -> single milestone RELEASED -> contract COMPLETED.
    Returns (ctx, milestone, contract)."""
    ctx, m = setup_released_milestone(amount_cents=amount_cents, **kwargs)
    contract = get_success_data(api_client.complete_contract(
        ctx["contract"]["id"], ctx["client_headers"]))
    ctx["contract"] = contract
    return ctx, m, contract
