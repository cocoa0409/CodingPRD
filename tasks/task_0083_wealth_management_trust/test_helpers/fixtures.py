"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: entity-backed Trustee/Grantor calls use make_*_headers(entity_id) so the
X-User-ID equals the acting entity's real id. Trustee distribution operations require the
acting trustee to hold an ACTIVE appointment over the owning trust (PRD §2.1); grantor
amend/revoke require X-User-ID == Trust.grantor_id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_grantor_payload, create_trustee_payload, create_beneficiary_payload,
    create_trust_payload, create_trustee_appointment_payload, create_account_payload,
    create_receipt_payload, create_distribution_payload,
    create_gst_exemption_allocation_payload,
)
from .test_users import TEST_USERS, make_grantor_headers, make_trustee_headers

ADMIN = TEST_USERS["trust_admin_headers"]


# ─── Primitive creators ───────────────────────────────────────

def create_grantor(full_name="Test Grantor", generation_level=0, gst_exemption_total_cents=None):
    payload = create_grantor_payload(full_name=full_name, generation_level=generation_level)
    if gst_exemption_total_cents is not None:
        payload["gst_exemption_total_cents"] = gst_exemption_total_cents
    return get_success_data(api_client.create_grantor(payload, ADMIN))


def create_trustee(full_name="Test Trustee", is_corporate=None):
    payload = create_trustee_payload(full_name=full_name)
    if is_corporate is not None:
        payload["is_corporate"] = is_corporate
    return get_success_data(api_client.create_trustee(payload, ADMIN))


def create_beneficiary(grantor_id, generation_level=1, full_name="Test Beneficiary"):
    return get_success_data(api_client.create_beneficiary(
        create_beneficiary_payload(grantor_id, generation_level, full_name=full_name), ADMIN))


def create_trust(grantor_id, trust_type="IRREVOCABLE", name="Test Trust", **flags):
    return get_success_data(api_client.create_trust(
        create_trust_payload(grantor_id, trust_type, name=name, **flags), ADMIN))


def appoint_trustee(trust_id, trustee_id, **overrides):
    return get_success_data(api_client.create_trustee_appointment(
        trust_id, create_trustee_appointment_payload(trustee_id, **overrides), ADMIN))


def open_account(trust_id, tax_year=2025, **overrides):
    return get_success_data(api_client.create_account(
        trust_id, create_account_payload(tax_year, **overrides), ADMIN))


def post_receipt(account_id, amount_cents, receipt_kind):
    return get_success_data(api_client.create_receipt(
        account_id, create_receipt_payload(amount_cents, receipt_kind), ADMIN))


# ─── Tier 1 / Tier 2: stand up an ACTIVE trust with an OPEN account ───

def setup_active_trust(trust_type="IRREVOCABLE", contribution_cents=5_000_000,
                       income_receipts=None, grantor_gen=0,
                       grantor_total_cents=None, num_trustees=1, **trust_flags):
    """Create grantor + N trustees + trust + appointments + account, post a CONTRIBUTION
    (and any income receipts), then fund + activate.

    income_receipts: optional list of (amount_cents, receipt_kind) posted before funding.
    Returns dict with: grantor, trustees (list), trust, account, plus the trust re-fetched
    so balances/version reflect all posted receipts.
    """
    grantor = create_grantor(generation_level=grantor_gen,
                             gst_exemption_total_cents=grantor_total_cents)
    trustees = [create_trustee(full_name=f"Trustee {i+1}") for i in range(num_trustees)]
    trust = create_trust(grantor["id"], trust_type, **trust_flags)
    for t in trustees:
        appoint_trustee(trust["id"], t["id"])
    account = open_account(trust["id"])
    if contribution_cents and contribution_cents > 0:
        post_receipt(account["id"], contribution_cents, "CONTRIBUTION")
    for amount, kind in (income_receipts or []):
        post_receipt(account["id"], amount, kind)
    get_success_data(api_client.fund_trust(trust["id"], ADMIN))
    get_success_data(api_client.activate_trust(trust["id"], ADMIN))
    trust = get_success_data(api_client.get_trust(trust["id"], ADMIN))
    return {
        "grantor": grantor,
        "trustees": trustees,
        "trust": trust,
        "account": account,
    }


# ─── Tier 3: distribution lifecycle shortcuts ─────────────────

def propose_distribution(account_id, beneficiary_id, amount_cents, proposer_trustee_id,
                         distribution_kind="MANDATORY"):
    """Propose a distribution as the proposing trustee (entity-backed identity)."""
    return get_success_data(api_client.create_distribution(
        account_id,
        create_distribution_payload(beneficiary_id, amount_cents, proposer_trustee_id,
                                    distribution_kind),
        make_trustee_headers(proposer_trustee_id)))


def approve_distribution(distribution_id, approver_trustee_id):
    return get_success_data(api_client.approve_distribution(
        distribution_id, make_trustee_headers(approver_trustee_id)))


def pay_distribution(distribution_id, payer_trustee_id):
    return get_success_data(api_client.pay_distribution(
        distribution_id, make_trustee_headers(payer_trustee_id)))


def create_approved_distribution(account_id, beneficiary_id, amount_cents,
                                 proposer_trustee_id, approver_trustee_id,
                                 distribution_kind="MANDATORY"):
    """Propose then approve. Returns the APPROVED distribution."""
    dist = propose_distribution(account_id, beneficiary_id, amount_cents,
                                proposer_trustee_id, distribution_kind)
    return approve_distribution(dist["id"], approver_trustee_id)


def create_paid_distribution(account_id, beneficiary_id, amount_cents,
                             proposer_trustee_id, approver_trustee_id,
                             distribution_kind="MANDATORY"):
    """Propose → approve → pay. Returns the PAID distribution."""
    dist = create_approved_distribution(account_id, beneficiary_id, amount_cents,
                                        proposer_trustee_id, approver_trustee_id,
                                        distribution_kind)
    return pay_distribution(dist["id"], proposer_trustee_id)


# ─── Tier 4: GST exemption allocation ─────────────────────────

def allocate_gst_exemption(trust_id, grantor_id, amount_cents, expected_trust_version=None):
    """Allocate GST exemption; reads the current trust version if not supplied."""
    if expected_trust_version is None:
        trust = get_success_data(api_client.get_trust(trust_id, ADMIN))
        expected_trust_version = trust["version"]
    return get_success_data(api_client.create_gst_exemption_allocation(
        trust_id,
        create_gst_exemption_allocation_payload(grantor_id, amount_cents, expected_trust_version),
        ADMIN))


def setup_active_trust_with_allocation(amount_cents, contribution_cents=5_000_000,
                                       income_receipts=None, **kwargs):
    """Active trust with a single ALLOCATED GST exemption. Returns the setup dict plus
    'allocation'. The trust is re-fetched after allocation so version/inclusion_ratio
    reflect it."""
    ctx = setup_active_trust(contribution_cents=contribution_cents,
                             income_receipts=income_receipts, **kwargs)
    alloc = allocate_gst_exemption(ctx["trust"]["id"], ctx["grantor"]["id"], amount_cents,
                                   ctx["trust"]["version"])
    ctx["allocation"] = alloc
    ctx["trust"] = get_success_data(api_client.get_trust(ctx["trust"]["id"], ADMIN))
    return ctx


# ─── Tier 5: close / file lifecycle ───────────────────────────

def close_account(account_id):
    return get_success_data(api_client.close_account(account_id, ADMIN))


def create_draft_filing(account_id, supersedes_filing_id=None):
    payload = {}
    if supersedes_filing_id is not None:
        payload["supersedes_filing_id"] = supersedes_filing_id
    return get_success_data(api_client.create_filing(account_id, payload, ADMIN))


def setup_closed_account_with_draft_filing(taxable_interest_cents=2_000_000,
                                           contribution_cents=1, **kwargs):
    """Active trust → OPEN account with a CONTRIBUTION + an INTEREST receipt (so taxable
    income == the interest amount) → close account → create a DRAFT filing.
    Returns the setup dict plus 'filing'."""
    ctx = setup_active_trust(
        contribution_cents=contribution_cents,
        income_receipts=[(taxable_interest_cents, "INTEREST")],
        **kwargs)
    close_account(ctx["account"]["id"])
    ctx["filing"] = create_draft_filing(ctx["account"]["id"])
    return ctx


def setup_filed_account(taxable_interest_cents=2_000_000, contribution_cents=5_000_000, **kwargs):
    """Drive a non-grantor trust account all the way to FILED. Returns the setup dict plus
    'filing' (now FILED). Useful for termination-finalize and supersede flows."""
    ctx = setup_closed_account_with_draft_filing(
        taxable_interest_cents=taxable_interest_cents,
        contribution_cents=contribution_cents, **kwargs)
    ctx["filing"] = get_success_data(api_client.file_filing(ctx["filing"]["id"], ADMIN))
    return ctx
