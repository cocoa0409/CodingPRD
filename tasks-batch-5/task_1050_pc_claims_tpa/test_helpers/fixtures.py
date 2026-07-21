"""Composite setup helpers.

Every helper builds its preconditions from scratch (the server DB is empty before
each test) using only PRD-declared endpoints, and returns the created resources so
tests can focus on the trigger + assertions.

Identity threading: the acting Adjuster's own id is always used as X-User-ID
(make_adjuster_headers), and a Vendor submits invoices under its own id
(make_vendor_headers) — never the shared fallback constant on ownership-gated calls.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as _default_api
from .test_users import TEST_USERS, make_adjuster_headers, make_vendor_headers
from .factories import (
    create_client_account_payload, create_policy_payload, create_adjuster_payload,
    create_vendor_payload, create_claim_payload, create_assignment_payload,
    create_reserve_change_payload, create_payment_payload, create_vendor_invoice_payload,
    create_litigation_case_payload, create_subrogation_case_payload,
    create_siu_referral_payload, create_bordereau_report_payload,
)

CM = TEST_USERS["claims_manager_headers"]
FO = TEST_USERS["finance_officer_headers"]
SIU = TEST_USERS["siu_investigator_headers"]


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
def set_clock(api, to_iso8601, headers=CM):
    return get_success_data(api.set_clock(to_iso8601, headers))


# --------------------------------------------------------------------------- #
# Standing-data primitives
# --------------------------------------------------------------------------- #
def create_account(api, **overrides):
    return get_success_data(api.create_client_account(create_client_account_payload(**overrides), CM))


def create_policy(api, account_id, **overrides):
    return get_success_data(api.create_policy(create_policy_payload(account_id, **overrides), CM))


def create_adjuster(api, **overrides):
    return get_success_data(api.create_adjuster(create_adjuster_payload(**overrides), CM))


def create_vendor(api, **overrides):
    return get_success_data(api.create_vendor(create_vendor_payload(**overrides), CM))


def create_standing_data(api, account_overrides=None, policy_overrides=None, adjuster_overrides=None):
    """Account + ACTIVE policy + adjuster. Returns (account, policy, adjuster)."""
    account = create_account(api, **(account_overrides or {}))
    policy = create_policy(api, account["id"], **(policy_overrides or {}))
    adjuster = create_adjuster(api, **(adjuster_overrides or {}))
    return account, policy, adjuster


# --------------------------------------------------------------------------- #
# Claim helpers
# --------------------------------------------------------------------------- #
def claim_version(api, claim_id, headers):
    """Read the claim's current version (for OCC writes)."""
    return get_success_data(api.get_claim(claim_id, headers))["version"]


def get_claim(api, claim_id, headers=CM):
    return get_success_data(api.get_claim(claim_id, headers))


def create_claim(api, policy_id, headers, **overrides):
    return get_success_data(api.create_claim(create_claim_payload(policy_id, **overrides), headers))


def create_adjuster_assignment(api, claim_id, adjuster_id, headers,
                               inspection_start="2026-06-16T09:00:00Z",
                               inspection_end="2026-06-16T11:00:00Z", **overrides):
    payload = create_assignment_payload(
        claim_id, "ADJUSTER", adjuster_id=adjuster_id,
        inspection_start=inspection_start, inspection_end=inspection_end, **overrides)
    return get_success_data(api.create_assignment(payload, headers))


def create_vendor_assignment(api, claim_id, vendor_id, headers,
                             inspection_start="2026-06-17T09:00:00Z",
                             inspection_end="2026-06-17T11:00:00Z", scope="APPRAISAL", **overrides):
    payload = create_assignment_payload(
        claim_id, "VENDOR", vendor_id=vendor_id, scope=scope,
        inspection_start=inspection_start, inspection_end=inspection_end, **overrides)
    return get_success_data(api.create_assignment(payload, headers))


def setup_assigned_claim(api, *, account_overrides=None, policy_overrides=None,
                         adjuster_overrides=None, claim_overrides=None,
                         inspection_start="2026-06-16T09:00:00Z",
                         inspection_end="2026-06-16T11:00:00Z"):
    """Account + policy + adjuster + claim + first ADJUSTER assignment (claim now ASSIGNED).

    Returns a dict env: account, policy, adjuster, adj_headers, claim, assignment.
    """
    account, policy, adjuster = create_standing_data(
        api, account_overrides, policy_overrides, adjuster_overrides)
    adj_headers = make_adjuster_headers(adjuster["id"])
    claim = create_claim(api, policy["id"], adj_headers, **(claim_overrides or {}))
    assignment = create_adjuster_assignment(
        api, claim["id"], adjuster["id"], adj_headers,
        inspection_start=inspection_start, inspection_end=inspection_end)
    return {
        "account": account, "policy": policy, "adjuster": adjuster,
        "adj_headers": adj_headers, "claim": claim, "assignment": assignment,
    }


def advance_claim(api, claim_id, adj_headers, *statuses):
    """Drive the claim through a sequence of adjuster-driven transitions."""
    last = None
    for status in statuses:
        last = get_success_data(api.transition_claim(claim_id, status, adj_headers))
    return last


def setup_evaluated_claim(api, **kwargs):
    """Assigned claim advanced INVESTIGATING -> EVALUATED."""
    env = setup_assigned_claim(api, **kwargs)
    advance_claim(api, env["claim"]["id"], env["adj_headers"], "INVESTIGATING", "EVALUATED")
    env["claim"] = get_claim(api, env["claim"]["id"], env["adj_headers"])
    return env


def setup_closed_claim(api, **kwargs):
    """Assigned claim advanced INVESTIGATING -> EVALUATED -> CLOSED (no blockers)."""
    env = setup_assigned_claim(api, **kwargs)
    advance_claim(api, env["claim"]["id"], env["adj_headers"],
                  "INVESTIGATING", "EVALUATED", "CLOSED")
    env["claim"] = get_claim(api, env["claim"]["id"], env["adj_headers"])
    return env


# --------------------------------------------------------------------------- #
# Reserve changes
# --------------------------------------------------------------------------- #
def post_reserve_change(api, claim_id, headers, delta_cents,
                        reserve_type="INDEMNITY", reason="set", version=None):
    """Post a reserve change, reading the current claim version unless supplied."""
    if version is None:
        version = claim_version(api, claim_id, headers)
    payload = create_reserve_change_payload(
        claim_id, reserve_type, delta_cents, version, reason=reason)
    return get_success_data(api.create_reserve_change(payload, headers))


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #
def create_pending_payment(api, claim_id, headers, amount_cents, version=None, **overrides):
    """Create a PENDING_APPROVAL indemnity payment."""
    if version is None:
        version = claim_version(api, claim_id, headers)
    payload = create_payment_payload(claim_id, amount_cents, version, **overrides)
    return get_success_data(api.create_payment(payload, headers))


def create_approved_payment(api, claim_id, headers, amount_cents, version=None, **overrides):
    """Create then APPROVE a payment (ClaimsManager approval is always valid)."""
    payment = create_pending_payment(api, claim_id, headers, amount_cents, version=version, **overrides)
    get_success_data(api.transition_payment(payment["id"], "APPROVED", CM))
    return get_success_data(api.get_payment(payment["id"], headers))


def create_issued_payment(api, claim_id, headers, amount_cents, version=None, **overrides):
    """Create -> APPROVE -> ISSUE a payment (FinanceOfficer issues)."""
    payment = create_approved_payment(api, claim_id, headers, amount_cents, version=version, **overrides)
    get_success_data(api.transition_payment(payment["id"], "ISSUED", FO))
    return get_success_data(api.get_payment(payment["id"], headers))


def setup_claim_with_paid_indemnity(api, amount_cents=600000, reserve_cents=None, **kwargs):
    """Assigned claim with `amount_cents` indemnity paid via an ISSUED payment.

    Raises the indemnity reserve first (default to `amount_cents`) so the reserve is
    available to convert to paid on issuance. Returns env with `payment`.
    """
    env = setup_assigned_claim(api, **kwargs)
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    if reserve_cents is None:
        reserve_cents = amount_cents
    if reserve_cents:
        post_reserve_change(api, claim_id, adj, reserve_cents)
    env["payment"] = create_issued_payment(api, claim_id, adj, amount_cents)
    env["claim"] = get_claim(api, claim_id, adj)
    return env


# --------------------------------------------------------------------------- #
# Vendor invoices
# --------------------------------------------------------------------------- #
def submit_vendor_invoice(api, claim_id, assignment_id, vendor_id, hours=0, **overrides):
    payload = create_vendor_invoice_payload(claim_id, assignment_id, hours, **overrides)
    return get_success_data(api.create_vendor_invoice(payload, make_vendor_headers(vendor_id)))


def submit_and_approve_invoice(api, claim_id, assignment_id, vendor_id, hours=0, **overrides):
    invoice = submit_vendor_invoice(api, claim_id, assignment_id, vendor_id, hours=hours, **overrides)
    get_success_data(api.transition_vendor_invoice(invoice["id"], "APPROVED", CM))
    return get_success_data(api.get_vendor_invoice(invoice["id"], CM))


def submit_approve_pay_invoice(api, claim_id, assignment_id, vendor_id, hours=0, **overrides):
    invoice = submit_and_approve_invoice(api, claim_id, assignment_id, vendor_id, hours=hours, **overrides)
    get_success_data(api.transition_vendor_invoice(invoice["id"], "PAID", FO))
    return get_success_data(api.get_vendor_invoice(invoice["id"], CM))


def setup_claim_paid_indemnity_and_expense(api, paid_indemnity=600000, paid_expense=400000,
                                           vendor_type="INDEPENDENT_ADJUSTER", **kwargs):
    """Assigned claim with both a paid indemnity payment and a paid vendor invoice.

    Returns env with account, policy, adjuster, adj_headers, claim, vendor,
    adjuster assignment, vendor assignment (vendor_assignment), payment, invoice.
    """
    env = setup_assigned_claim(api, **kwargs)
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    vendor = create_vendor(api, vendor_type=vendor_type,
                           credentialed_coverages=["PROPERTY", "AUTO", "LIABILITY", "WORKERS_COMP"])
    vasg = create_vendor_assignment(api, claim_id, vendor["id"], adj)
    # paid indemnity
    post_reserve_change(api, claim_id, adj, paid_indemnity)
    env["payment"] = create_issued_payment(api, claim_id, adj, paid_indemnity)
    # paid expense (materials pass-through)
    env["invoice"] = submit_approve_pay_invoice(
        api, claim_id, vasg["id"], vendor["id"], hours=0, miles=0, materials_cents=paid_expense)
    env["vendor"] = vendor
    env["vendor_assignment"] = vasg
    env["claim"] = get_claim(api, claim_id, adj)
    return env


# --------------------------------------------------------------------------- #
# Subrogation
# --------------------------------------------------------------------------- #
def create_subrogation_case(api, claim_id, headers, demand_cents=800000, **overrides):
    payload = create_subrogation_case_payload(claim_id, demand_cents, **overrides)
    return get_success_data(api.create_subrogation_case(payload, headers))


def setup_subrogation_at_negotiating(api, claim_id, headers, demand_cents=800000):
    """Open a subrogation case and drive it OPEN -> DEMAND_SENT -> NEGOTIATING."""
    sub = create_subrogation_case(api, claim_id, headers, demand_cents=demand_cents)
    get_success_data(api.transition_subrogation_case(sub["id"], "DEMAND_SENT", headers))
    get_success_data(api.transition_subrogation_case(sub["id"], "NEGOTIATING", headers))
    return get_success_data(api.get_subrogation_case(sub["id"], headers))


def record_recovery(api, claim_id, sub_id, adj_headers, recovered_cents, allocation_method):
    """FinanceOfficer records NEGOTIATING -> RECOVERED with a current claim version."""
    version = claim_version(api, claim_id, adj_headers)
    return get_success_data(api.transition_subrogation_case(
        sub_id, "RECOVERED", FO,
        recovered_cents=recovered_cents, allocation_method=allocation_method,
        expected_claim_version=version))


# --------------------------------------------------------------------------- #
# Litigation / SIU
# --------------------------------------------------------------------------- #
def create_litigation_case(api, claim_id, **overrides):
    payload = create_litigation_case_payload(claim_id, **overrides)
    return get_success_data(api.create_litigation_case(payload, CM))


def create_siu_referral(api, claim_id, place_hold=True, actor=SIU, **overrides):
    payload = create_siu_referral_payload(claim_id, place_hold=place_hold, **overrides)
    return get_success_data(api.create_siu_referral(payload, actor))


# --------------------------------------------------------------------------- #
# Bordereau
# --------------------------------------------------------------------------- #
def create_bordereau(api, account_id, period_start, period_end, basis, headers=CM):
    payload = create_bordereau_report_payload(account_id, period_start, period_end, basis)
    return get_success_data(api.create_bordereau_report(payload, headers))
