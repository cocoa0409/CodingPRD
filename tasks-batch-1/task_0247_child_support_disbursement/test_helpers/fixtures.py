"""Composite setup helpers.

These encapsulate the multi-step API sequences that test claims require, so
test bodies focus on assertions. All setup calls use get_success_data()
(lenient 2xx) so a broken precondition surfaces as a clear "Setup failed".

The test harness restarts the server (empty DB) before every test, so every
fixture builds its preconditions from scratch using only PRD-declared
endpoints.

Identity threading: after creating an entity_backed CustodialParty/Employer,
any ownership-gated call uses make_<role>_headers(entity_id). Operator roles
(CaseWorker/FinanceOfficer/Supervisor) use the shared headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_custodial_party_payload,
    create_noncustodial_party_payload,
    create_employer_payload,
    create_support_order_payload,
    create_remittance_payload,
    create_disbursement_payload,
    create_modification_payload,
    create_enforcement_action_payload,
    make_unique_fein,
)

CW = TEST_USERS["case_worker_headers"]
FO = TEST_USERS["finance_officer_headers"]
SUP = TEST_USERS["supervisor_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(iso8601: str):
    """Set the server's logical UTC clock (CaseWorker/FinanceOfficer)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, FO))


# ---------------------------------------------------------------------------
# Tier 1 — base parties
# ---------------------------------------------------------------------------
def create_custodial_party(assistance_status=None, **overrides) -> dict:
    payload = create_custodial_party_payload(**overrides)
    if assistance_status is not None:
        payload["assistance_status"] = assistance_status
    return get_success_data(api_client.create_custodial_party(payload, CW))


def create_noncustodial_party(supports_second_family=None, **overrides) -> dict:
    payload = create_noncustodial_party_payload(**overrides)
    if supports_second_family is not None:
        payload["supports_second_family"] = supports_second_family
    return get_success_data(api_client.create_noncustodial_party(payload, CW))


def create_employer(**overrides) -> dict:
    payload = create_employer_payload(**overrides)
    return get_success_data(api_client.create_employer(payload, CW))


def create_order(custodial_party_id, noncustodial_party_id, current_support_cents=30000, **overrides) -> dict:
    payload = create_support_order_payload(
        custodial_party_id, noncustodial_party_id,
        current_support_cents=current_support_cents, **overrides)
    return get_success_data(api_client.create_support_order(payload, CW))


def get_order(order_id) -> dict:
    return get_success_data(api_client.get_support_order(order_id, CW))


def order_version(order_id) -> int:
    return get_order(order_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2 — parties + order convenience bundles
# ---------------------------------------------------------------------------
def setup_parties(assistance_status=None, supports_second_family=None):
    """Returns (custodial_party, noncustodial_party, employer)."""
    cp = create_custodial_party(assistance_status=assistance_status)
    ncp = create_noncustodial_party(supports_second_family=supports_second_family)
    emp = create_employer()
    return cp, ncp, emp


def create_active_order(custodial_party_id, noncustodial_party_id,
                        current_support_cents=30000, **overrides) -> dict:
    """Create an ESTABLISHED order and activate it (posts first CHARGE).
    Returns the activated order resource."""
    order = create_order(custodial_party_id, noncustodial_party_id,
                         current_support_cents=current_support_cents, **overrides)
    get_success_data(api_client.activate_support_order(order["id"], CW))
    return get_order(order["id"])


def setup_active_order(current_support_cents=30000, assistance_status=None,
                       supports_second_family=None, **order_overrides):
    """payee + obligor + employer + one ACTIVE order.
    Returns (cp, ncp, emp, order)."""
    cp, ncp, emp = setup_parties(assistance_status=assistance_status,
                                 supports_second_family=supports_second_family)
    order = create_active_order(cp["id"], ncp["id"],
                                current_support_cents=current_support_cents,
                                **order_overrides)
    return cp, ncp, emp, order


# ---------------------------------------------------------------------------
# Tier 4 — arrears accumulation via rollover
# ---------------------------------------------------------------------------
def setup_order_with_principal(current_support_cents=50000, assistance_status=None,
                               supports_second_family=None, **order_overrides):
    """ACTIVE order where one post-charge has rolled the activation CHARGE into
    arrears PRINCIPAL. After this:
      arrears_principal_cents == current_support_cents (from rollover of the
      activation charge), current_support_due_cents == current_support_cents
      (the fresh period charge), interest_balance_cents == 0.
    Returns (cp, ncp, emp, order_resource_after_charge)."""
    cp, ncp, emp = setup_parties(assistance_status=assistance_status,
                                 supports_second_family=supports_second_family)
    order = create_active_order(cp["id"], ncp["id"],
                                current_support_cents=current_support_cents,
                                **order_overrides)
    get_success_data(api_client.post_charge(order["id"], CW))
    return cp, ncp, emp, get_order(order["id"])


# ---------------------------------------------------------------------------
# Remittance + allocation
# ---------------------------------------------------------------------------
def create_remittance(employer_id, noncustodial_party_id,
                      disposable_earnings_cents=100000, gross_remitted_cents=30000) -> dict:
    payload = create_remittance_payload(
        employer_id, noncustodial_party_id,
        disposable_earnings_cents=disposable_earnings_cents,
        gross_remitted_cents=gross_remitted_cents)
    return get_success_data(api_client.create_remittance(payload, FO))


def allocate_remittance(remittance_id) -> dict:
    return get_success_data(api_client.allocate_remittance(remittance_id, FO))


def list_allocations(remittance_id=None, support_order_id=None) -> list:
    params = {}
    if remittance_id is not None:
        params["remittance_id"] = remittance_id
    if support_order_id is not None:
        params["support_order_id"] = support_order_id
    return get_success_data(api_client.list_allocations(FO, params=params))


def create_and_allocate_remittance(employer_id, noncustodial_party_id,
                                   disposable_earnings_cents=100000,
                                   gross_remitted_cents=30000) -> dict:
    """Create a RECEIVED remittance and allocate it. Returns the allocated
    remittance resource."""
    rem = create_remittance(employer_id, noncustodial_party_id,
                            disposable_earnings_cents=disposable_earnings_cents,
                            gross_remitted_cents=gross_remitted_cents)
    return allocate_remittance(rem["id"])


def setup_allocation_for_order(current_support_cents=20000, gross_remitted_cents=None,
                               assistance_status=None, with_principal=False,
                               assigned_arrears_cents=None):
    """ACTIVE single order, then a remittance allocated against it producing one
    Allocation slice. If with_principal, a post-charge first rolls the
    activation charge into principal (so the order has both current-support due
    and arrears principal).

    Returns (cp, ncp, emp, order, allocation).
    """
    overrides = {}
    if assigned_arrears_cents is not None:
        overrides["assigned_arrears_cents"] = assigned_arrears_cents
    if with_principal:
        cp, ncp, emp, order = setup_order_with_principal(
            current_support_cents=current_support_cents,
            assistance_status=assistance_status, **overrides)
    else:
        cp, ncp, emp, order = setup_active_order(
            current_support_cents=current_support_cents,
            assistance_status=assistance_status, **overrides)
    if gross_remitted_cents is None:
        gross_remitted_cents = current_support_cents
    create_and_allocate_remittance(
        emp["id"], ncp["id"], disposable_earnings_cents=max(gross_remitted_cents * 5, 100000),
        gross_remitted_cents=gross_remitted_cents)
    allocs = list_allocations(support_order_id=order["id"])
    allocation = allocs[0]
    return cp, ncp, emp, get_order(order["id"]), allocation


# ---------------------------------------------------------------------------
# Multi-order obligor (allocation proration / surplus)
# ---------------------------------------------------------------------------
def setup_three_order_obligor(cs_amounts=(50000, 30000, 10000), assistance_status=None):
    """One obligor with three ACTIVE orders, created in the order of cs_amounts
    (so created_at A < B < C). Returns (cp, ncp, emp, [order_a, order_b, order_c])."""
    cp, ncp, emp = setup_parties(assistance_status=assistance_status)
    orders = []
    for cs in cs_amounts:
        o = create_active_order(cp["id"], ncp["id"], current_support_cents=cs)
        orders.append(o)
    return cp, ncp, emp, orders


# ---------------------------------------------------------------------------
# Disbursement
# ---------------------------------------------------------------------------
def create_disbursement(support_order_id, custodial_party_id, allocation_id, **overrides) -> dict:
    payload = create_disbursement_payload(
        support_order_id, custodial_party_id, allocation_id, **overrides)
    return get_success_data(api_client.create_disbursement(payload, FO))


def setup_pending_disbursement(current_support_cents=20000, assistance_status=None,
                               with_principal=False, assigned_arrears_cents=None,
                               gross_remitted_cents=None):
    """Full chain through a PENDING disbursement from an allocation slice.
    Returns (cp, ncp, emp, order, allocation, disbursement)."""
    cp, ncp, emp, order, allocation = setup_allocation_for_order(
        current_support_cents=current_support_cents,
        gross_remitted_cents=gross_remitted_cents,
        assistance_status=assistance_status, with_principal=with_principal,
        assigned_arrears_cents=assigned_arrears_cents)
    disb = create_disbursement(order["id"], cp["id"], allocation["id"])
    return cp, ncp, emp, get_order(order["id"]), allocation, disb


def setup_sent_disbursement(current_support_cents=20000, assistance_status=None,
                            with_principal=False, assigned_arrears_cents=None,
                            gross_remitted_cents=None):
    """Pending disbursement then SENT. Returns
    (cp, ncp, emp, order, allocation, disbursement)."""
    cp, ncp, emp, order, allocation, disb = setup_pending_disbursement(
        current_support_cents=current_support_cents,
        assistance_status=assistance_status, with_principal=with_principal,
        assigned_arrears_cents=assigned_arrears_cents,
        gross_remitted_cents=gross_remitted_cents)
    disb = get_success_data(api_client.send_disbursement(disb["id"], FO))
    return cp, ncp, emp, get_order(order["id"]), allocation, disb


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------
def propose_enforcement(order_id, action_type="TAX_INTERCEPT", expected_version=None) -> dict:
    if expected_version is None:
        expected_version = order_version(order_id)
    payload = create_enforcement_action_payload(order_id, expected_version,
                                                action_type=action_type)
    return get_success_data(api_client.create_enforcement_action(payload, CW))


def setup_order_with_proposed_enforcement(current_support_cents=50000,
                                          action_type="TAX_INTERCEPT"):
    """ACTIVE order rolled to arrears principal == current_support_cents
    (>= threshold when cs >= 50000), enforcement PROPOSED (INTERCEPT_PENDING).
    Returns (cp, ncp, emp, order, enforcement_action)."""
    cp, ncp, emp, order = setup_order_with_principal(current_support_cents=current_support_cents)
    enf = propose_enforcement(order["id"], action_type=action_type)
    return cp, ncp, emp, get_order(order["id"]), enf


def setup_order_with_certified_enforcement(current_support_cents=50000,
                                           action_type="LICENSE_SUSPENSION"):
    """ACTIVE order, arrears principal == current_support_cents, enforcement
    PROPOSED then CERTIFIED (INTERCEPT_ACTIVE).
    Returns (cp, ncp, emp, order, enforcement_action)."""
    cp, ncp, emp, order, enf = setup_order_with_proposed_enforcement(
        current_support_cents=current_support_cents, action_type=action_type)
    enf = get_success_data(api_client.certify_enforcement_action(enf["id"], CW))
    return cp, ncp, emp, get_order(order["id"]), enf


# ---------------------------------------------------------------------------
# Modification
# ---------------------------------------------------------------------------
def create_modification(support_order_id, **overrides) -> dict:
    payload = create_modification_payload(support_order_id, **overrides)
    return get_success_data(api_client.create_modification(payload, CW))


def setup_submitted_modification(current_support_cents=40000, proposed=45000,
                                 coverage_start_at="2026-07-01T00:00:00Z",
                                 coverage_end_at="2026-12-31T00:00:00Z"):
    """ACTIVE order + a SUBMITTED modification.
    Returns (cp, ncp, emp, order, modification)."""
    cp, ncp, emp, order = setup_active_order(current_support_cents=current_support_cents)
    mod = create_modification(order["id"], proposed_current_support_cents=proposed,
                              coverage_start_at=coverage_start_at,
                              coverage_end_at=coverage_end_at)
    get_success_data(api_client.submit_modification(mod["id"], CW))
    return cp, ncp, emp, get_order(order["id"]), get_success_data(
        api_client.get_modification(mod["id"], CW))


def setup_approved_modification(current_support_cents=40000, proposed=60000,
                                coverage_start_at="2026-07-01T00:00:00Z",
                                coverage_end_at="2026-12-31T00:00:00Z"):
    """ACTIVE order + a Modification advanced to APPROVED (submit then
    Supervisor approve). Returns (cp, ncp, emp, order, modification)."""
    cp, ncp, emp, order, mod = setup_submitted_modification(
        current_support_cents=current_support_cents, proposed=proposed,
        coverage_start_at=coverage_start_at, coverage_end_at=coverage_end_at)
    get_success_data(api_client.decide_modification(mod["id"], {"decision": "APPROVE"}, SUP))
    return cp, ncp, emp, get_order(order["id"]), get_success_data(
        api_client.get_modification(mod["id"], CW))


def setup_rejected_modification(current_support_cents=40000, proposed=45000):
    """ACTIVE order + a Modification advanced to REJECTED (submit then
    Supervisor reject). Returns (cp, ncp, emp, order, modification)."""
    cp, ncp, emp, order, mod = setup_submitted_modification(
        current_support_cents=current_support_cents, proposed=proposed)
    get_success_data(api_client.decide_modification(mod["id"], {"decision": "REJECT"}, SUP))
    return cp, ncp, emp, get_order(order["id"]), get_success_data(
        api_client.get_modification(mod["id"], CW))
