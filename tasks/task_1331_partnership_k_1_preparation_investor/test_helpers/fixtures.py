"""Composite setup helpers.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints: the harness restarts the server before each test, so each test
starts against an empty database. Setup calls use the lenient
``get_success_data`` validator so failures surface as clear setup errors.

Segregation of duties (PRD §2.1, §3.4, §3.8): proposer/submitter user ids
must differ from approver/issuer ids; the helpers thread
``PREPARER_USER_ID`` / ``REVIEWER_USER_ID`` accordingly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CANONICAL_FUND, CANONICAL_PARTNERS, CANONICAL_TOTALS,
    PREPARER_USER_ID, REVIEWER_USER_ID,
)
from .factories import (
    create_fund_payload, create_tax_year_payload, create_partner_payload,
    create_capital_event_payload, create_transfer_payload,
    create_allocation_run_payload, create_special_allocation_payload,
    create_composite_filing_payload, create_withholding_accrual_payload,
    create_k1_amendment_payload, create_ticket_payload,
)
from .test_users import (
    TEST_USERS, make_fund_tax_admin_headers, make_tax_preparer_headers,
    make_tax_reviewer_headers, make_investor_services_rep_headers,
)

ADMIN = TEST_USERS["fund_tax_admin_headers"]
PREPARER = TEST_USERS["tax_preparer_headers"]
REVIEWER = TEST_USERS["tax_reviewer_headers"]
REP = TEST_USERS["investor_services_rep_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_fund(fund_overrides=None) -> dict:
    """POST /funds (FundTaxAdmin). Returns the created fund."""
    resp = api_client.create_fund(create_fund_payload(**(fund_overrides or {})), ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed (create fund): {resp.text}"
    return data


def create_partner(fund_id, **overrides) -> dict:
    """POST /funds/partners (FundTaxAdmin). Returns the created partner."""
    resp = api_client.create_partner(create_partner_payload(fund_id, **overrides), ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed (create partner): {resp.text}"
    return data


def create_tax_year(fund_id, **overrides) -> dict:
    """POST /funds/tax-years (FundTaxAdmin). Returns the created tax year (OPEN)."""
    resp = api_client.create_tax_year(create_tax_year_payload(fund_id, **overrides), ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed (create tax year): {resp.text}"
    return data


def post_capital_event(partner_id, tax_year_id, event_type, amount_cents, effective_date) -> dict:
    """POST /funds/capital-events (TaxPreparer). Returns the created event."""
    resp = api_client.create_capital_event(
        create_capital_event_payload(
            partner_id, tax_year_id,
            event_type=event_type, amount_cents=amount_cents, effective_date=effective_date,
        ),
        PREPARER,
    )
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed (capital event): {resp.text}"
    return data


def get_partner(partner_id) -> dict:
    resp = api_client.get_partner(partner_id, ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed (get partner): {resp.text}"
    return data


def get_tax_year(tax_year_id) -> dict:
    resp = api_client.get_tax_year(tax_year_id, ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed (get tax year): {resp.text}"
    return data


def get_k1_package(k1_id) -> dict:
    resp = api_client.get_k1_package(k1_id, ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed (get k1): {resp.text}"
    return data


def get_allocation_run(run_id) -> dict:
    resp = api_client.get_allocation_run(run_id, ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed (get run): {resp.text}"
    return data


def set_clock(to_iso8601: str):
    """POST /_clock/set_current_utc (FundTaxAdmin) — PRD §2.5."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed (set clock): {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 1b: tax-year state progression
# ---------------------------------------------------------------------------

def close_books(tax_year_id) -> dict:
    """OPEN -> BOOKS_CLOSED (FundTaxAdmin). Returns updated tax year."""
    resp = api_client.close_books(tax_year_id, ADMIN)
    data = get_success_data(resp)
    assert data.get("status") == "BOOKS_CLOSED", f"Setup failed (close books): {resp.text}"
    return data


def create_allocation_run(tax_year_id, run_kind="FINAL", expected_tax_year_version=None) -> dict:
    """POST /funds/allocation-runs (TaxPreparer) with the OCC version field
    (PRD §2.7). When expected_tax_year_version is None the current version is
    read first. Returns the created run (COMPUTED)."""
    if expected_tax_year_version is None:
        expected_tax_year_version = get_tax_year(tax_year_id)["version"]
    resp = api_client.create_allocation_run(
        create_allocation_run_payload(
            tax_year_id, expected_tax_year_version, run_kind=run_kind,
        ),
        PREPARER,
    )
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed (create run): {resp.text}"
    return data


def lock_run(run_id) -> dict:
    """COMPUTED FINAL -> LOCKED (TaxReviewer). Returns the locked run."""
    resp = api_client.lock_allocation_run(run_id, REVIEWER)
    data = get_success_data(resp)
    assert data.get("status") == "LOCKED", f"Setup failed (lock run): {resp.text}"
    return data


def create_and_lock_final_run(tax_year_id) -> dict:
    """Create a FINAL run (fresh OCC version) and lock it. Returns the run."""
    run = create_allocation_run(tax_year_id, run_kind="FINAL")
    return lock_run(run["id"])


def submit_tax_year_review(tax_year_id) -> dict:
    """ALLOCATED -> UNDER_REVIEW (TaxPreparer)."""
    resp = api_client.submit_tax_year_review(tax_year_id, PREPARER)
    data = get_success_data(resp)
    assert data.get("status") == "UNDER_REVIEW", f"Setup failed (ty submit-review): {resp.text}"
    return data


def approve_tax_year(tax_year_id) -> dict:
    """UNDER_REVIEW -> APPROVED (TaxReviewer)."""
    resp = api_client.approve_tax_year(tax_year_id, REVIEWER)
    data = get_success_data(resp)
    assert data.get("status") == "APPROVED", f"Setup failed (ty approve): {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 2/3: full tax-year pipelines
# ---------------------------------------------------------------------------

def setup_fund_with_partners(partner_specs=None, fund_overrides=None):
    """Fund + partners. ``partner_specs`` is a list of payload override dicts
    that may carry a ``key`` label. Returns (fund, partners_by_key_or_list)."""
    fund = create_fund(fund_overrides)
    partners = {}
    specs = partner_specs if partner_specs is not None else CANONICAL_PARTNERS
    for spec in specs:
        spec = dict(spec)
        key = spec.pop("key", None)
        partner = create_partner(fund["id"], **spec)
        partners[key or partner["legal_name"]] = partner
    return fund, partners


def setup_tax_year_with_locked_run(
    partner_specs=None,
    fund_overrides=None,
    tax_year_overrides=None,
    contributions=None,
    year=2025,
):
    """Fund + partners + tax year walked to a LOCKED FINAL run.

    ``contributions``: list of (partner_key, amount_cents, effective_date)
    posted before close-books. Returns a scenario dict with fund, partners,
    tax_year, run.
    """
    fund, partners = setup_fund_with_partners(partner_specs, fund_overrides)
    ty = create_tax_year(fund["id"], year=year, **(tax_year_overrides or {}))
    for key, amount, eff_date in (contributions or []):
        post_capital_event(partners[key]["id"], ty["id"], "CONTRIBUTION", amount, eff_date)
    close_books(ty["id"])
    run = create_and_lock_final_run(ty["id"])
    return {
        "fund": fund,
        "partners": partners,
        "tax_year": get_tax_year(ty["id"]),
        "run": get_allocation_run(run["id"]),
    }


def setup_approved_tax_year(**kwargs) -> dict:
    """LOCKED FINAL run + submit-review + approve. TaxYear ends APPROVED."""
    scenario = setup_tax_year_with_locked_run(**kwargs)
    submit_tax_year_review(scenario["tax_year"]["id"])
    approve_tax_year(scenario["tax_year"]["id"])
    scenario["tax_year"] = get_tax_year(scenario["tax_year"]["id"])
    return scenario


def generate_k1_packages(tax_year_id) -> list:
    """POST /funds/k1-generation (TaxPreparer). Returns packages in partner
    created_at ascending order (PRD §3.8)."""
    resp = api_client.generate_k1({"tax_year_id": tax_year_id}, PREPARER)
    data = get_success_data(resp)
    assert isinstance(data, list) and data and data[0].get("id"), (
        f"Setup failed (k1 generation): {resp.text}"
    )
    return data


def walk_k1_to_delivered(k1_id, delivery_method="PORTAL") -> dict:
    """prep GENERATED -> REVIEWED -> APPROVED -> DELIVERED (delivery SENT).

    Submitter and approver differ per segregation of duties (PRD §3.8).
    """
    resp = api_client.submit_k1_review(k1_id, make_tax_preparer_headers(PREPARER_USER_ID))
    data = get_success_data(resp)
    assert data.get("prep_status") == "REVIEWED", f"Setup failed (k1 submit-review): {resp.text}"
    resp = api_client.approve_k1(k1_id, make_tax_reviewer_headers(REVIEWER_USER_ID))
    data = get_success_data(resp)
    assert data.get("prep_status") == "APPROVED", f"Setup failed (k1 approve): {resp.text}"
    resp = api_client.deliver_k1(k1_id, {"delivery_method": delivery_method}, REP)
    data = get_success_data(resp)
    assert data.get("prep_status") == "DELIVERED", f"Setup failed (k1 deliver): {resp.text}"
    return data


def setup_k1_generated(**kwargs) -> dict:
    """APPROVED tax year + generated K-1 packages. Adds ``k1_packages``."""
    scenario = setup_approved_tax_year(**kwargs)
    scenario["k1_packages"] = generate_k1_packages(scenario["tax_year"]["id"])
    return scenario


def setup_k1_delivered(k1_index=0, delivery_method="PORTAL", **kwargs) -> dict:
    """K-1 pipeline through delivery of package ``k1_index``.

    Adds ``k1_packages`` (generation set) and ``k1`` (the delivered package).
    When every package of the year is delivered the tax year auto-completes
    (PRD §3.5); single-partner scenarios therefore end COMPLETED.
    """
    scenario = setup_k1_generated(**kwargs)
    k1 = walk_k1_to_delivered(scenario["k1_packages"][k1_index]["id"], delivery_method)
    scenario["k1"] = k1
    return scenario


# ---------------------------------------------------------------------------
# Tier 3b: transfers
# ---------------------------------------------------------------------------

def create_transfer(fund_id, transferor_id, transferee_id, **overrides) -> dict:
    """POST /funds/transfers (FundTaxAdmin). Returns the PROPOSED transfer."""
    resp = api_client.create_transfer(
        create_transfer_payload(fund_id, transferor_id, transferee_id, **overrides), ADMIN,
    )
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed (create transfer): {resp.text}"
    return data


def confirm_transfer(transfer_id) -> dict:
    resp = api_client.confirm_transfer(transfer_id, ADMIN)
    data = get_success_data(resp)
    assert data.get("status") == "CONFIRMED", f"Setup failed (confirm transfer): {resp.text}"
    return data


def settle_transfer(transfer_id) -> dict:
    resp = api_client.settle_transfer(transfer_id, ADMIN)
    data = get_success_data(resp)
    assert data.get("status") == "SETTLED", f"Setup failed (settle transfer): {resp.text}"
    return data


def create_and_confirm_transfer(fund_id, transferor_id, transferee_id, **overrides) -> dict:
    transfer = create_transfer(fund_id, transferor_id, transferee_id, **overrides)
    return confirm_transfer(transfer["id"])


def create_confirm_settle_transfer(fund_id, transferor_id, transferee_id, **overrides) -> dict:
    transfer = create_and_confirm_transfer(fund_id, transferor_id, transferee_id, **overrides)
    return settle_transfer(transfer["id"])


# ---------------------------------------------------------------------------
# Tier 3c: special allocations
# ---------------------------------------------------------------------------

def create_and_approve_special_allocation(tax_year_id, partner_id, **overrides) -> dict:
    """Propose (TaxPreparer prep_1) then approve (TaxReviewer rev_1) — the two
    user ids must differ per segregation of duties (PRD §3.4)."""
    resp = api_client.create_special_allocation(
        create_special_allocation_payload(tax_year_id, partner_id, **overrides),
        make_tax_preparer_headers(PREPARER_USER_ID),
    )
    data = get_success_data(resp)
    assert data.get("status") == "PROPOSED", f"Setup failed (create SA): {resp.text}"
    resp = api_client.approve_special_allocation(data["id"], make_tax_reviewer_headers(REVIEWER_USER_ID))
    approved = get_success_data(resp)
    assert approved.get("status") == "APPROVED", f"Setup failed (approve SA): {resp.text}"
    return approved


# ---------------------------------------------------------------------------
# Tier 3d: withholding
# ---------------------------------------------------------------------------

def accrue_withholding(tax_year_id, quarter, method) -> list:
    """POST /funds/withholding-accruals (TaxPreparer). Returns the records."""
    resp = api_client.create_withholding_accruals(
        create_withholding_accrual_payload(tax_year_id, quarter=quarter, method=method),
        PREPARER,
    )
    data = get_success_data(resp)
    assert isinstance(data, list) and data and data[0].get("id"), (
        f"Setup failed (withholding accrual): {resp.text}"
    )
    return data


# ---------------------------------------------------------------------------
# Tier 5: amendment / completion terminal states
# ---------------------------------------------------------------------------

def create_and_walk_amendment(k1_id, reason="ALLOCATION_CHANGE", stop_at="IN_REVIEW") -> dict:
    """Open an amendment on a DELIVERED package and walk it forward.

    stop_at: OPENED | IN_PREP | IN_REVIEW. prepared_by is prep_1.
    """
    resp = api_client.create_k1_amendment(create_k1_amendment_payload(k1_id, reason=reason), PREPARER)
    data = get_success_data(resp)
    assert data.get("status") == "OPENED", f"Setup failed (create amendment): {resp.text}"
    if stop_at == "OPENED":
        return data
    resp = api_client.start_amendment_prep(data["id"], PREPARER)
    data = get_success_data(resp)
    assert data.get("status") == "IN_PREP", f"Setup failed (start-prep): {resp.text}"
    if stop_at == "IN_PREP":
        return data
    resp = api_client.submit_amendment_review(data["id"], make_tax_preparer_headers(PREPARER_USER_ID))
    data = get_success_data(resp)
    assert data.get("status") == "IN_REVIEW", f"Setup failed (amendment submit-review): {resp.text}"
    return data


def create_ticket(partner_id, **overrides) -> dict:
    resp = api_client.create_ticket(create_ticket_payload(partner_id, **overrides), REP)
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), f"Setup failed (create ticket): {resp.text}"
    return data
