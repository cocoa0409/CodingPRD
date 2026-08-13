"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at its 2026-08-01T00:00:00Z default). Setup
calls use get_success_data so failures surface as clear "Setup failed"
errors instead of confusing assertion failures.

Segregation-of-duties identities (PRD 2.10): resources are created by
"ana-1" (TaxAnalyst) and approved/activated by "mgr-1" (TaxManager) or
"tpl-1" (TransferPricingLead), so the approver always differs from the
stored creator/submitter id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_EFFECTIVE_FROM,
    DEFAULT_EFFECTIVE_TO,
    DEFAULT_GROUP_REVENUE_EUR,
    DEFAULT_MARKUP_BP,
    DEFAULT_YEAR_INDEX,
    STUDY_COMPARABLES_BP,
)
from .factories import (
    create_agreement_payload,
    create_audit_case_payload,
    create_benchmarking_study_payload,
    create_cash_pool_payload,
    create_clock_payload,
    create_doc_package_payload,
    create_fiscal_year_payload,
    create_legal_entity_payload,
    create_refresh_payload,
    create_sweep_payload,
    create_transaction_payload,
    create_true_up_run_payload,
)
from .test_users import (
    ADMIN,
    ANALYST,
    MANAGER,
    TP_LEAD,
    TREASURY,
    make_transfer_pricing_lead_headers,
)


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}")


def _ok(step, resp, expected_status=None):
    data = get_success_data(resp)
    if expected_status is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected_status, (
            f"Setup failed at {step}: expected status {expected_status}, "
            f"got {status}")
    return data


# ---------------------------------------------------------------------------
# Tier 1 — single-resource creation and state progression
# ---------------------------------------------------------------------------

def create_fiscal_year(year_index=DEFAULT_YEAR_INDEX,
                       group_revenue_eur=DEFAULT_GROUP_REVENUE_EUR):
    resp = api_client.create_fiscal_year(
        create_fiscal_year_payload(year_index=year_index,
                                   group_revenue_eur=group_revenue_eur),
        ADMIN)
    return _ok("create_fiscal_year", resp, expected_status="OPEN")


def begin_closing(fiscal_year_id):
    resp = api_client.begin_closing(fiscal_year_id, ADMIN)
    return _ok("begin_closing", resp, expected_status="CLOSING")


def close_year(fiscal_year_id):
    resp = api_client.close_fiscal_year(fiscal_year_id, ADMIN)
    return _ok("close_fiscal_year", resp, expected_status="CLOSED")


def set_clock(to_iso8601):
    resp = api_client.set_clock(create_clock_payload(to_iso8601), ADMIN)
    return _ok("set_clock", resp)


def create_legal_entity(name="USCo", country_code="US",
                        functional_currency="USD"):
    resp = api_client.create_legal_entity(
        create_legal_entity_payload(name=name, country_code=country_code,
                                    functional_currency=functional_currency),
        ADMIN)
    return _ok("create_legal_entity", resp, expected_status="ACTIVE")


def create_study(transaction_type="SERVICES", region="EU",
                 vintage_year=DEFAULT_YEAR_INDEX,
                 comparables_bp=STUDY_COMPARABLES_BP):
    """Create a DRAFT benchmarking study (creator X-User-ID ana-1)."""
    resp = api_client.create_benchmarking_study(
        create_benchmarking_study_payload(
            transaction_type=transaction_type, region=region,
            vintage_year=vintage_year, comparables_bp=list(comparables_bp)),
        ANALYST)
    return _ok("create_benchmarking_study", resp, expected_status="DRAFT")


def approve_study(study_id, headers=None):
    """Approve DRAFT -> CURRENT; approver defaults to tpl-1 (not creator)."""
    resp = api_client.approve_benchmarking_study(study_id, headers or TP_LEAD)
    return _ok("approve_benchmarking_study", resp, expected_status="CURRENT")


def create_current_study(**kwargs):
    """DRAFT study approved to CURRENT. Returns the approved study."""
    study = create_study(**kwargs)
    return approve_study(study["id"])


def create_agreement(provider_entity_id, recipient_entity_id, study_id,
                     transaction_type="SERVICES", markup_bp=DEFAULT_MARKUP_BP,
                     true_up_method="TO_MEDIAN",
                     effective_from=DEFAULT_EFFECTIVE_FROM,
                     effective_to=DEFAULT_EFFECTIVE_TO):
    """Create a DRAFT agreement (creator X-User-ID ana-1)."""
    resp = api_client.create_agreement(
        create_agreement_payload(
            provider_entity_id, recipient_entity_id, study_id,
            transaction_type=transaction_type, markup_bp=markup_bp,
            true_up_method=true_up_method, effective_from=effective_from,
            effective_to=effective_to),
        ANALYST)
    return _ok("create_agreement", resp, expected_status="DRAFT")


def activate_agreement(agreement_id, headers=None):
    """Activate DRAFT -> ACTIVE; activator defaults to mgr-1 (not creator)."""
    resp = api_client.activate_agreement(agreement_id, headers or MANAGER)
    return _ok("activate_agreement", resp, expected_status="ACTIVE")


def create_active_agreement(provider_entity_id, recipient_entity_id, study_id,
                            **kwargs):
    agreement = create_agreement(provider_entity_id, recipient_entity_id,
                                 study_id, **kwargs)
    return activate_agreement(agreement["id"])


def book_transaction(agreement_id, fiscal_year_id, cost_base_cents=1_000_000,
                     provider_revenue_cents=1_020_000,
                     recipient_cost_cents=None):
    if recipient_cost_cents is None:
        recipient_cost_cents = provider_revenue_cents
    resp = api_client.create_transaction(
        create_transaction_payload(
            agreement_id, fiscal_year_id, cost_base_cents=cost_base_cents,
            provider_revenue_cents=provider_revenue_cents,
            recipient_cost_cents=recipient_cost_cents),
        ANALYST)
    return _ok("book_transaction", resp, expected_status=None)


def match_transaction(transaction_id):
    resp = api_client.match_transaction(transaction_id, ANALYST)
    return _ok("match_transaction", resp)


def book_and_match(agreement_id, fiscal_year_id, cost_base_cents=1_000_000,
                   provider_revenue_cents=1_020_000,
                   recipient_cost_cents=None):
    tx = book_transaction(agreement_id, fiscal_year_id, cost_base_cents,
                          provider_revenue_cents, recipient_cost_cents)
    matched = match_transaction(tx["id"])
    return matched


def create_run(agreement_id, fiscal_year_id):
    """Create a DRAFT true-up run (creator X-User-ID ana-1)."""
    resp = api_client.create_true_up_run(
        create_true_up_run_payload(agreement_id, fiscal_year_id), ANALYST)
    return _ok("create_true_up_run", resp, expected_status="DRAFT")


def compute_run(run_id):
    resp = api_client.compute_true_up_run(run_id, ANALYST)
    return _ok("compute_true_up_run", resp, expected_status="COMPUTED")


def approve_run(run_id, headers=None):
    """Approve COMPUTED -> APPROVED; approver defaults to mgr-1."""
    resp = api_client.approve_true_up_run(run_id, headers or MANAGER)
    return _ok("approve_true_up_run", resp, expected_status="APPROVED")


def post_run(run_id, headers=None):
    resp = api_client.post_true_up_run(run_id, headers or MANAGER)
    return _ok("post_true_up_run", resp, expected_status="POSTED")


def create_pool(fiscal_year_id, interest_method="AVERAGE_BALANCE",
                admin_fee_cents=0):
    resp = api_client.create_cash_pool(
        create_cash_pool_payload(fiscal_year_id,
                                 interest_method=interest_method,
                                 admin_fee_cents=admin_fee_cents),
        TREASURY)
    return _ok("create_cash_pool", resp, expected_status="OPEN")


def post_sweep(pool_id, movements, expected_cash_pool_version):
    resp = api_client.post_sweeps(
        pool_id, create_sweep_payload(movements, expected_cash_pool_version),
        TREASURY)
    return _ok("post_sweeps", resp)


def begin_netting(pool_id):
    resp = api_client.begin_netting(pool_id, TREASURY)
    return _ok("begin_netting", resp, expected_status="NETTING")


def settle_pool(pool_id):
    resp = api_client.settle_cash_pool(pool_id, TREASURY)
    return _ok("settle_cash_pool", resp, expected_status="SETTLED")


def create_doc(fiscal_year_id, doc_type, entity_id=None):
    resp = api_client.create_doc_package(
        create_doc_package_payload(fiscal_year_id, doc_type,
                                   entity_id=entity_id),
        ANALYST)
    return _ok("create_doc_package", resp, expected_status="DRAFT")


def submit_doc(doc_id):
    """Submit DRAFT -> SUBMITTED (submitter X-User-ID ana-1)."""
    resp = api_client.submit_doc_package(doc_id, ANALYST)
    return _ok("submit_doc_package", resp, expected_status="SUBMITTED")


def approve_doc(doc_id, headers=None):
    """Approve SUBMITTED -> APPROVED; approver defaults to mgr-1."""
    resp = api_client.approve_doc_package(doc_id, headers or MANAGER)
    return _ok("approve_doc_package", resp, expected_status="APPROVED")


def file_doc(doc_id, headers=None):
    resp = api_client.file_doc_package(doc_id, headers or MANAGER)
    return _ok("file_doc_package", resp, expected_status="FILED")


def create_approved_doc(fiscal_year_id, doc_type, entity_id=None):
    doc = create_doc(fiscal_year_id, doc_type, entity_id=entity_id)
    submit_doc(doc["id"])
    return approve_doc(doc["id"])


def create_audit_case(entity_id, case_type="AUDIT", authority_country="US",
                      covered_year_indexes=None):
    resp = api_client.create_audit_case(
        create_audit_case_payload(
            entity_id, case_type, authority_country=authority_country,
            covered_year_indexes=covered_year_indexes),
        TP_LEAD)
    return _ok("create_audit_case", resp, expected_status="OPENED")


def attach_doc(case_id, doc_id):
    resp = api_client.attach_doc(case_id, {"doc_package_id": doc_id}, TP_LEAD)
    return _ok("attach_doc", resp)


def submit_response(case_id):
    resp = api_client.submit_response(case_id, TP_LEAD)
    return _ok("submit_response", resp,
               expected_status="SUBMITTED_TO_AUTHORITY")


def resolve_case(case_id):
    resp = api_client.resolve_audit_case(case_id, TP_LEAD)
    return _ok("resolve_audit_case", resp)


# ---------------------------------------------------------------------------
# Tier 2 — composite scenario: year + entities + CURRENT study + agreement
# ---------------------------------------------------------------------------

def setup_year_entities_study(year_index=DEFAULT_YEAR_INDEX,
                              group_revenue_eur=DEFAULT_GROUP_REVENUE_EUR,
                              vintage_year=DEFAULT_YEAR_INDEX,
                              comparables_bp=STUDY_COMPARABLES_BP):
    """Fiscal year + provider/recipient entities + CURRENT study.

    Returns dict(fiscal_year, provider, recipient, study).
    """
    fy = create_fiscal_year(year_index=year_index,
                            group_revenue_eur=group_revenue_eur)
    provider = create_legal_entity(name="USCo", country_code="US",
                                   functional_currency="USD")
    recipient = create_legal_entity(name="DECo", country_code="DE",
                                    functional_currency="EUR")
    study = create_current_study(vintage_year=vintage_year,
                                 comparables_bp=comparables_bp)
    return {"fiscal_year": fy, "provider": provider, "recipient": recipient,
            "study": study}


def setup_active_agreement(year_index=DEFAULT_YEAR_INDEX,
                           group_revenue_eur=DEFAULT_GROUP_REVENUE_EUR,
                           vintage_year=DEFAULT_YEAR_INDEX,
                           comparables_bp=STUDY_COMPARABLES_BP,
                           **agreement_kwargs):
    """Year + entities + CURRENT study + ACTIVE agreement.

    Returns dict(fiscal_year, provider, recipient, study, agreement).
    """
    ctx = setup_year_entities_study(
        year_index=year_index, group_revenue_eur=group_revenue_eur,
        vintage_year=vintage_year, comparables_bp=comparables_bp)
    agreement = create_active_agreement(
        ctx["provider"]["id"], ctx["recipient"]["id"], ctx["study"]["id"],
        **agreement_kwargs)
    ctx["agreement"] = agreement
    return ctx


def setup_agreement_with_matched_transactions(
        tx_specs=((1_000_000, 1_020_000), (2_000_000, 2_040_000)),
        **agreement_kwargs):
    """ACTIVE agreement plus booked-and-matched transactions.

    tx_specs is an iterable of (cost_base_cents, provider_revenue_cents)
    or (cost_base_cents, provider_revenue_cents, recipient_cost_cents).
    Returns the setup_active_agreement context plus "transactions".
    """
    ctx = setup_active_agreement(**agreement_kwargs)
    transactions = []
    for spec in tx_specs:
        cost, revenue = spec[0], spec[1]
        recipient_cost = spec[2] if len(spec) > 2 else revenue
        transactions.append(book_and_match(
            ctx["agreement"]["id"], ctx["fiscal_year"]["id"], cost, revenue,
            recipient_cost))
    ctx["transactions"] = transactions
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — true-up lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_computed_run(agreement_id, fiscal_year_id):
    run = create_run(agreement_id, fiscal_year_id)
    return compute_run(run["id"])


def create_approved_run(agreement_id, fiscal_year_id):
    """COMPUTED -> APPROVED. Caller must have begun closing the year first
    (approval requires the fiscal year to be CLOSING, PRD 3.5)."""
    run = create_computed_run(agreement_id, fiscal_year_id)
    return approve_run(run["id"])


def create_posted_run(agreement_id, fiscal_year_id):
    run = create_approved_run(agreement_id, fiscal_year_id)
    return post_run(run["id"])


# ---------------------------------------------------------------------------
# Tier 4 — targeted composite scenarios
# ---------------------------------------------------------------------------

def setup_approved_true_up_with_pool(
        tx_specs=((1_000_000, 1_020_000), (2_000_000, 2_040_000)),
        **agreement_kwargs):
    """Full cascade stand-up: matched transactions, OPEN pool, year CLOSING,
    run computed and approved. Returns ctx with pool and run (not yet posted).
    """
    ctx = setup_agreement_with_matched_transactions(
        tx_specs=tx_specs, **agreement_kwargs)
    ctx["pool"] = create_pool(ctx["fiscal_year"]["id"])
    begin_closing(ctx["fiscal_year"]["id"])
    ctx["run"] = create_approved_run(ctx["agreement"]["id"],
                                     ctx["fiscal_year"]["id"])
    return ctx


def setup_apa_locked_agreement(covered_year_indexes=(DEFAULT_YEAR_INDEX,)):
    """ACTIVE agreement locked by an APA case resolved to CLOSED_AGREED.

    Builds: year + entities + study + ACTIVE agreement + APPROVED master file
    + APA case for the provider covering the given years, with the doc
    attached and the response submitted and resolved.
    Returns the setup context plus "apa_case".
    """
    ctx = setup_active_agreement()
    doc = create_approved_doc(ctx["fiscal_year"]["id"], "MASTER_FILE")
    apa = create_audit_case(ctx["provider"]["id"], case_type="APA",
                            authority_country="US",
                            covered_year_indexes=list(covered_year_indexes))
    attach_doc(apa["id"], doc["id"])
    submit_response(apa["id"])
    ctx["apa_case"] = resolve_case(apa["id"])
    return ctx


def refresh_study(study_id, comparables_bp, expected_study_version,
                  headers=None):
    resp = api_client.refresh_benchmarking_study(
        study_id, create_refresh_payload(comparables_bp,
                                         expected_study_version),
        headers or TP_LEAD)
    return _ok("refresh_benchmarking_study", resp, expected_status="DRAFT")


def approve_refreshed_study(child_study_id):
    """Approve a refresh child; the child was created by tpl-1 via refresh,
    so approval runs under a different TransferPricingLead user id."""
    return approve_study(child_study_id,
                         headers=make_transfer_pricing_lead_headers("tpl-2"))
