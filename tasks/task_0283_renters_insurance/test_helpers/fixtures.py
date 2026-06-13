"""Composite setup helpers for the Renters Insurance API.

Each helper builds preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before every
test. Setup calls use get_success_data() so failures surface as clear
"Setup step failed" errors.

Identity threading: a Policyholder is entity_backed, so every ownership-gated
call (file claim, add item, pay invoice, name additional insured) uses
make_policyholder_headers(policyholder_id) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import FULL_COVERAGE
from .test_users import (
    TEST_USERS,
    make_adjuster_headers,
    make_policyholder_headers,
    make_underwriter_headers,
)

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["adjuster_headers"]


# --------------------------------------------------------------------------
# Low-level building blocks
# --------------------------------------------------------------------------
def set_clock(iso8601: str, headers=UW):
    """Set the server clock; returns the data payload."""
    return get_success_data(api_client.set_clock(iso8601, headers))


def create_policyholder(email="ph@example.com", full_name="PH", mailing_address="1 St"):
    """Create a policyholder. Returns the entity dict."""
    return get_success_data(
        api_client.create_policyholder(
            {"email": email, "full_name": full_name, "mailing_address": mailing_address},
            UW,
        )
    )


def create_bundle(policyholder_id, name="Home+Auto"):
    return get_success_data(
        api_client.create_bundle({"policyholder_id": policyholder_id, "name": name}, UW)
    )


def create_quoted_policy(policyholder_id, **policy_overrides):
    """Create a QUOTED policy. Returns the policy dict.

    policy_overrides may set territory_code, effective_date, expiry_date,
    deductible_cents, pp_valuation_method, billing_mode, bundle_id, etc.
    """
    payload = {
        "policyholder_id": policyholder_id,
        "insured_address": policy_overrides.pop("insured_address", "100 Rental Ave"),
        "territory_code": policy_overrides.pop("territory_code", "STANDARD"),
        "effective_date": policy_overrides.pop("effective_date", "2026-01-01T00:00:00Z"),
        "expiry_date": policy_overrides.pop("expiry_date", "2027-01-01T00:00:00Z"),
        "deductible_cents": policy_overrides.pop("deductible_cents", 25000),
    }
    payload.update(policy_overrides)
    return get_success_data(api_client.create_policy(payload, UW))


def add_coverage_line(policy_id, coverage_type, limit_cents, expected_version):
    """Add one coverage line; returns the line dict (carries the bumped policy
    version is NOT here — read the policy or capture from response). The
    response is the CoverageLine; callers thread version from the policy GET
    or from the returned line's owning policy via get_policy."""
    return get_success_data(
        api_client.add_coverage_line(
            policy_id,
            {
                "coverage_type": coverage_type,
                "limit_cents": limit_cents,
                "expected_policy_version": expected_version,
            },
            UW,
        )
    )


def _current_policy_version(policy_id):
    return get_success_data(api_client.get_policy(policy_id, UW))["version"]


def add_full_coverage(policy_id, limits=None):
    """Add all three coverage lines to a QUOTED policy, threading
    expected_policy_version correctly across the OCC-guarded adds.

    `limits` optionally overrides the (PP, LIABILITY, LOSS_OF_USE) limits as a
    dict keyed by coverage_type. Returns a dict {coverage_type: line_dict}.
    """
    if limits is None:
        limits = {ct: lim for ct, lim in FULL_COVERAGE}
    lines = {}
    version = _current_policy_version(policy_id)
    for coverage_type, default_limit in FULL_COVERAGE:
        limit = limits.get(coverage_type, default_limit)
        line = add_coverage_line(policy_id, coverage_type, limit, version)
        lines[coverage_type] = line
        version = _current_policy_version(policy_id)
    return lines


def add_scheduled_item(policy_id, appraised_value_cents, description="ring",
                       deductible_waived=None):
    """Add a scheduled item, threading the current policy version. Returns the
    scheduled-item dict."""
    version = _current_policy_version(policy_id)
    payload = {
        "description": description,
        "appraised_value_cents": appraised_value_cents,
        "expected_policy_version": version,
    }
    if deductible_waived is not None:
        payload["deductible_waived"] = deductible_waived
    return get_success_data(api_client.add_scheduled_item(policy_id, payload, UW))


def issue_policy(policy_id):
    """Issue a QUOTED policy -> ACTIVE. Returns the policy dict."""
    return get_success_data(api_client.issue_policy(policy_id, UW))


def get_first_invoice(policy_id):
    """Return the (single) PremiumInvoice for a policy."""
    data = get_success_data(
        api_client.list_invoices(UW, params={"policy_id": policy_id})
    )
    assert data, f"No invoice found for policy {policy_id}"
    return data[0]


# --------------------------------------------------------------------------
# Tier 1/2: an issued (ACTIVE) policy with full coverage
# --------------------------------------------------------------------------
def setup_active_policy(
    territory_code="STANDARD",
    deductible_cents=25000,
    pp_valuation_method="RCV",
    billing_mode="ANNUAL",
    effective_date="2026-01-01T00:00:00Z",
    expiry_date="2027-01-01T00:00:00Z",
    pp_limit=None,
    bundle_id=None,
    email="active@example.com",
    clock=None,
):
    """Create policyholder + QUOTED policy + all three coverage lines + issue.

    Returns (policyholder, policy, coverage_lines, invoice) where
    coverage_lines is {coverage_type: line_dict}. pp_limit overrides only the
    PERSONAL_PROPERTY limit; the others stay at the standard defaults.
    """
    if clock is not None:
        set_clock(clock)
    ph = create_policyholder(email=email)
    extra = {
        "territory_code": territory_code,
        "deductible_cents": deductible_cents,
        "pp_valuation_method": pp_valuation_method,
        "billing_mode": billing_mode,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
    }
    if bundle_id is not None:
        extra["bundle_id"] = bundle_id
    policy = create_quoted_policy(ph["id"], **extra)
    limits = None
    if pp_limit is not None:
        limits = {ct: lim for ct, lim in FULL_COVERAGE}
        limits["PERSONAL_PROPERTY"] = pp_limit
    lines = add_full_coverage(policy["id"], limits=limits)
    policy = issue_policy(policy["id"])
    invoice = get_first_invoice(policy["id"])
    return ph, policy, lines, invoice


# --------------------------------------------------------------------------
# Tier 3: claims lifecycle shortcuts
# --------------------------------------------------------------------------
def file_pp_claim(policy_id, policyholder_id, loss_date="2026-03-01T00:00:00Z"):
    """File a PERSONAL_PROPERTY claim as the owning policyholder."""
    headers = make_policyholder_headers(policyholder_id)
    return get_success_data(
        api_client.file_claim(
            policy_id, {"loss_type": "PERSONAL_PROPERTY", "loss_date": loss_date}, headers
        )
    )


def file_lou_claim(policy_id, policyholder_id, loss_date, disp_start, disp_end):
    """File a LOSS_OF_USE claim with a closed displacement interval."""
    headers = make_policyholder_headers(policyholder_id)
    return get_success_data(
        api_client.file_claim(
            policy_id,
            {
                "loss_type": "LOSS_OF_USE",
                "loss_date": loss_date,
                "displacement_start": disp_start,
                "displacement_end": disp_end,
            },
            headers,
        )
    )


def add_claim_item(claim_id, policyholder_id, coverage_line_id, replacement_cost_cents,
                   age_months=None, useful_life_months=None, scheduled_item_id=None):
    """Add a claim item to a FILED claim as the owning policyholder."""
    headers = make_policyholder_headers(policyholder_id)
    payload = {
        "coverage_line_id": coverage_line_id,
        "replacement_cost_cents": replacement_cost_cents,
    }
    if age_months is not None:
        payload["age_months"] = age_months
    if useful_life_months is not None:
        payload["useful_life_months"] = useful_life_months
    if scheduled_item_id is not None:
        payload["scheduled_item_id"] = scheduled_item_id
    return get_success_data(api_client.add_claim_item(claim_id, payload, headers))


def setup_claim_under_review(
    pp_limit=None,
    deductible_cents=25000,
    pp_valuation_method="RCV",
    items=None,
    loss_date="2026-03-01T00:00:00Z",
    clock=None,
    email="review@example.com",
):
    """Active policy + a PERSONAL_PROPERTY claim taken to UNDER_REVIEW.

    `items` is a list of dicts each with keys replacement_cost_cents and
    optionally age_months, useful_life_months, scheduled_item_id. If omitted, a
    single 120000/age0/life60 item is added.

    Returns (policyholder, policy, lines, claim, claim_items).
    """
    ph, policy, lines, _inv = setup_active_policy(
        deductible_cents=deductible_cents,
        pp_valuation_method=pp_valuation_method,
        pp_limit=pp_limit,
        clock=clock,
        email=email,
    )
    claim = file_pp_claim(policy["id"], ph["id"], loss_date=loss_date)
    if items is None:
        items = [{"replacement_cost_cents": 120000, "age_months": 0, "useful_life_months": 60}]
    cl_pp = lines["PERSONAL_PROPERTY"]["id"]
    claim_items = []
    for it in items:
        claim_items.append(
            add_claim_item(
                claim["id"],
                ph["id"],
                it.get("coverage_line_id", cl_pp),
                it["replacement_cost_cents"],
                age_months=it.get("age_months"),
                useful_life_months=it.get("useful_life_months"),
                scheduled_item_id=it.get("scheduled_item_id"),
            )
        )
    claim = get_success_data(api_client.start_review(claim["id"], ADJ))
    return ph, policy, lines, claim, claim_items


def setup_approved_claim(
    pp_limit=None,
    deductible_cents=25000,
    items=None,
    email="approved@example.com",
):
    """Active RCV policy with a PERSONAL_PROPERTY claim taken to APPROVED.

    Returns (policyholder, policy, lines, claim, claim_items).
    """
    ph, policy, lines, claim, claim_items = setup_claim_under_review(
        pp_limit=pp_limit,
        deductible_cents=deductible_cents,
        pp_valuation_method="RCV",
        items=items,
        email=email,
    )
    claim = get_success_data(api_client.approve_claim(claim["id"], ADJ))
    return ph, policy, lines, claim, claim_items


# --------------------------------------------------------------------------
# Tier 4/5: lapse / reinstatement / billing state
# --------------------------------------------------------------------------
def setup_lapsed_policy(
    effective_date="2026-01-01T00:00:00Z",
    due_date_clock="2026-01-01T00:00:00Z",
    lapse_clock="2026-01-20T00:00:00Z",
    email="lapsed@example.com",
    add_scheduled=False,
    add_filed_claim=False,
):
    """Active policy with an unpaid invoice, lapsed via process-billing.

    Returns dict with keys: policyholder, policy (post-lapse), lines, invoice,
    scheduled_item (or None), claim (or None).
    """
    set_clock(due_date_clock)
    ph = create_policyholder(email=email)
    policy = create_quoted_policy(
        ph["id"], effective_date=effective_date, expiry_date="2027-01-01T00:00:00Z"
    )
    lines = add_full_coverage(policy["id"])
    scheduled_item = None
    if add_scheduled:
        scheduled_item = add_scheduled_item(policy["id"], 200000, description="watch")
    policy = issue_policy(policy["id"])
    invoice = get_first_invoice(policy["id"])
    claim = None
    if add_filed_claim:
        claim = file_pp_claim(policy["id"], ph["id"])
        add_claim_item(claim["id"], ph["id"], lines["PERSONAL_PROPERTY"]["id"], 120000,
                       age_months=0, useful_life_months=60)
    set_clock(lapse_clock)
    policy = get_success_data(api_client.process_billing(policy["id"], UW))
    return {
        "policyholder": ph,
        "policy": policy,
        "lines": lines,
        "invoice": invoice,
        "scheduled_item": scheduled_item,
        "claim": claim,
    }


def setup_paid_invoice_policy(amount_cents=33350, email="paid@example.com",
                              clock="2026-01-01T00:00:00Z"):
    """Active standard policy whose invoice is fully paid (status PAID).

    Returns (policyholder, policy, invoice, payment).
    """
    set_clock(clock)
    ph = create_policyholder(email=email)
    policy = create_quoted_policy(ph["id"])
    add_full_coverage(policy["id"])
    policy = issue_policy(policy["id"])
    invoice = get_first_invoice(policy["id"])
    payment = get_success_data(
        api_client.record_payment(
            invoice["id"], {"amount_cents": amount_cents, "method": "CARD"},
            make_policyholder_headers(ph["id"]),
        )
    )
    invoice = get_success_data(api_client.get_invoice(invoice["id"], UW))
    return ph, policy, invoice, payment


# Re-export header builders for tests that need ad-hoc identities.
__all__ = [
    "UW",
    "ADJ",
    "set_clock",
    "create_policyholder",
    "create_bundle",
    "create_quoted_policy",
    "add_coverage_line",
    "add_full_coverage",
    "add_scheduled_item",
    "issue_policy",
    "get_first_invoice",
    "setup_active_policy",
    "file_pp_claim",
    "file_lou_claim",
    "add_claim_item",
    "setup_claim_under_review",
    "setup_approved_claim",
    "setup_lapsed_policy",
    "setup_paid_invoice_policy",
    "make_underwriter_headers",
    "make_adjuster_headers",
    "make_policyholder_headers",
]
