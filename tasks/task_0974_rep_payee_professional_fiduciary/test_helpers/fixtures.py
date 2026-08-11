"""Composite setup helpers.

Every fixture builds its preconditions from scratch against the PRD endpoints;
the harness restarts the server before every test, so nothing carries over.
All fixtures use get_success_data() internally so setup failures surface as
clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client as api
from .factories import (
    create_client_payload, create_entitlement_payload, create_trust_account_payload,
    create_budget_plan_payload, create_disbursement_payload, create_deposit_payload,
    create_court_order_payload, create_surety_bond_payload,
    create_accounting_report_payload, create_spend_down_plan_payload,
    create_audit_case_payload, create_conservator_payload,
)
from .test_users import (
    make_admin_headers, make_case_manager_headers, make_financial_officer_headers,
    make_auditor_headers, make_conservator_headers,
)

ADMIN = make_admin_headers()
CM = make_case_manager_headers("cm-1")
FO = make_financial_officer_headers("fo-1")
AUD = make_auditor_headers()


def set_clock(to_iso8601: str):
    """Advance the logical clock."""
    resp = api.set_clock(to_iso8601, ADMIN)
    get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: State Progression
# ---------------------------------------------------------------------------

def create_client(medicaid_enrolled=False, **overrides):
    """Create a client (INTAKE_REVIEW). Returns the client dict."""
    resp = api.create_client(
        create_client_payload(medicaid_enrolled=medicaid_enrolled, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_client_with_verified_entitlement(medicaid_enrolled=False,
                                            monthly_benefit_cents=80000,
                                            effective_start_date="2026-01-01",
                                            effective_end_date=None,
                                            claim_type="SSI",
                                            **client_overrides):
    """Client + one entitlement verified to VERIFIED. Returns (client, entitlement)."""
    client = create_client(medicaid_enrolled=medicaid_enrolled, **client_overrides)
    ent_payload = create_entitlement_payload(
        client_id=client["id"],
        claim_type=claim_type,
        monthly_benefit_cents=monthly_benefit_cents,
        effective_start_date=effective_start_date,
    )
    if effective_end_date is not None:
        ent_payload["effective_end_date"] = effective_end_date
    ent = get_success_data(api.create_entitlement(ent_payload, ADMIN))
    ent = get_success_data(api.verify_entitlement(ent["id"], ADMIN))
    return client, ent


def create_active_client(medicaid_enrolled=False, **kwargs):
    """Client + VERIFIED entitlement + activated. Returns (client, entitlement).

    Extra kwargs are forwarded to create_client_with_verified_entitlement.
    """
    client, ent = create_client_with_verified_entitlement(
        medicaid_enrolled=medicaid_enrolled, **kwargs
    )
    client = get_success_data(api.activate_client(client["id"], ADMIN))
    return client, ent


def create_account(client_id, account_type="OPERATING", **overrides):
    """Open a trust account. Returns the account dict."""
    resp = api.create_trust_account(
        create_trust_account_payload(client_id=client_id, account_type=account_type, **overrides),
        FO,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: Entity Hierarchy (client + account + bond)
# ---------------------------------------------------------------------------

def create_active_bond(coverage_amount_cents=5000000,
                       coverage_start_date="2026-01-01",
                       coverage_end_date="2027-01-01",
                       premium_paid_through_date="2026-12-31"):
    """Register + activate a surety bond. Returns the ACTIVE bond."""
    bond = get_success_data(api.create_surety_bond(
        create_surety_bond_payload(
            coverage_amount_cents=coverage_amount_cents,
            coverage_start_date=coverage_start_date,
            coverage_end_date=coverage_end_date,
            premium_paid_through_date=premium_paid_through_date,
        ), ADMIN))
    return get_success_data(api.activate_surety_bond(bond["id"], ADMIN))


def create_and_post_deposit(account_id, amount_cents, source="OTHER",
                            received_date="2026-06-02", entitlement_id=None):
    """Record + post a deposit. Returns the POSTED deposit."""
    payload = create_deposit_payload(
        account_id=account_id, source=source, amount_cents=amount_cents,
        received_date=received_date,
    )
    if entitlement_id is not None:
        payload["entitlement_id"] = entitlement_id
    dep = get_success_data(api.create_deposit(payload, FO))
    return get_success_data(api.post_deposit(dep["id"], FO))


def setup_client_account_bond(medicaid_enrolled=False, deposit_amount=None,
                              account_type="OPERATING", bond_coverage=5000000,
                              **client_kwargs):
    """ACTIVE client + one account + ACTIVE bond (+ optional posted deposit).

    Returns (client, entitlement, account, bond, deposit_or_None).
    """
    client, ent = create_active_client(medicaid_enrolled=medicaid_enrolled, **client_kwargs)
    account = create_account(client["id"], account_type=account_type)
    bond = create_active_bond(coverage_amount_cents=bond_coverage)
    deposit = None
    if deposit_amount is not None:
        deposit = create_and_post_deposit(account["id"], deposit_amount)
    return client, ent, account, bond, deposit


# ---------------------------------------------------------------------------
# Tier 3: Budget plan lifecycle
# ---------------------------------------------------------------------------

def create_budget_plan_for_client(client_id, period_month="2026-06",
                                  source_benefit_cents=100000,
                                  lines=None, as_user_id="cm-1"):
    """Create a DRAFT budget plan (reads fresh client version for OCC)."""
    if lines is None:
        lines = [{"category": "HOUSING", "percent": 100}]
    client = get_success_data(api.get_client(client_id, ADMIN))
    payload = create_budget_plan_payload(
        client_id=client_id, period_month=period_month,
        source_benefit_cents=source_benefit_cents, lines=lines,
        expected_client_version=client["version"],
    )
    return get_success_data(
        api.create_budget_plan(payload, make_case_manager_headers(as_user_id))
    )


def create_approved_budget_plan(client_id, period_month="2026-06",
                                source_benefit_cents=100000, lines=None,
                                cm_user_id="cm-1", fo_user_id="fo-1"):
    """DRAFT -> PROPOSED -> APPROVED plan. Returns the APPROVED plan."""
    plan = create_budget_plan_for_client(
        client_id, period_month=period_month,
        source_benefit_cents=source_benefit_cents, lines=lines,
        as_user_id=cm_user_id,
    )
    plan = get_success_data(
        api.propose_budget_plan(plan["id"], make_case_manager_headers(cm_user_id))
    )
    plan = get_success_data(
        api.approve_budget_plan(plan["id"], make_financial_officer_headers(fo_user_id))
    )
    return plan


# ---------------------------------------------------------------------------
# Tier 4: Disbursement lifecycle
# ---------------------------------------------------------------------------

def create_disbursement(client_id, account_id, budget_plan_id, amount_cents=10000,
                        category="HOUSING", scheduled_release_date="2026-06-10",
                        court_order_id=None, spend_down_plan_id=None,
                        payee_name="Test Payee", as_user_id="cm-1"):
    """Create a REQUESTED disbursement."""
    payload = create_disbursement_payload(
        client_id=client_id, account_id=account_id, budget_plan_id=budget_plan_id,
        payee_name=payee_name, category=category, amount_cents=amount_cents,
        scheduled_release_date=scheduled_release_date,
    )
    if court_order_id is not None:
        payload["court_order_id"] = court_order_id
    if spend_down_plan_id is not None:
        payload["spend_down_plan_id"] = spend_down_plan_id
    return get_success_data(
        api.create_disbursement(payload, make_case_manager_headers(as_user_id))
    )


def create_approved_disbursement(client_id, account_id, budget_plan_id,
                                 amount_cents=10000, category="HOUSING",
                                 scheduled_release_date="2026-06-10",
                                 court_order_id=None, spend_down_plan_id=None,
                                 payee_name="Test Payee",
                                 cm_user_id="cm-1", fo_user_id="fo-1"):
    """Create + approve a disbursement (lands APPROVED or PENDING_CONSERVATOR)."""
    d = create_disbursement(
        client_id, account_id, budget_plan_id, amount_cents=amount_cents,
        category=category, scheduled_release_date=scheduled_release_date,
        court_order_id=court_order_id, spend_down_plan_id=spend_down_plan_id,
        payee_name=payee_name, as_user_id=cm_user_id,
    )
    return get_success_data(
        api.approve_disbursement(d["id"], make_financial_officer_headers(fo_user_id))
    )


def create_released_disbursement(client_id, account_id, budget_plan_id,
                                 amount_cents=10000, category="HOUSING",
                                 scheduled_release_date="2026-06-10",
                                 payee_name="Test Payee",
                                 cm_user_id="cm-1", fo_user_id="fo-1"):
    """Create -> approve -> release. Returns the RELEASED disbursement."""
    d = create_approved_disbursement(
        client_id, account_id, budget_plan_id, amount_cents=amount_cents,
        category=category, scheduled_release_date=scheduled_release_date,
        payee_name=payee_name, cm_user_id=cm_user_id, fo_user_id=fo_user_id,
    )
    return get_success_data(
        api.release_disbursement(d["id"], make_financial_officer_headers(fo_user_id))
    )


def setup_funded_release_ready(deposit_amount=50000, budget_basis=100000,
                               disbursement_amount=10000, period_month="2026-06",
                               account_type="OPERATING",
                               medicaid_enrolled=False, **client_kwargs):
    """Full stack to an APPROVED disbursement ready to release.

    ACTIVE client + funded account + ACTIVE bond + APPROVED plan + APPROVED
    disbursement. Returns dict of all entities.
    """
    client, ent = create_active_client(medicaid_enrolled=medicaid_enrolled, **client_kwargs)
    account = create_account(client["id"], account_type=account_type)
    bond = create_active_bond()
    if deposit_amount is not None:
        create_and_post_deposit(account["id"], deposit_amount)
    plan = create_approved_budget_plan(client["id"], period_month=period_month,
                                       source_benefit_cents=budget_basis)
    disb = create_approved_disbursement(
        client["id"], account["id"], plan["id"], amount_cents=disbursement_amount,
    )
    return {
        "client": client, "entitlement": ent, "account": account,
        "bond": bond, "plan": plan, "disbursement": disb,
    }


# ---------------------------------------------------------------------------
# Tier 5: Court orders, conservators, spend-down, reports, audits
# ---------------------------------------------------------------------------

def create_granted_court_order(client_id, amount_limit_cents=50000,
                               expiry_date="2026-12-31",
                               petitioned_date="2026-06-01",
                               order_type="RESTRICTED_WITHDRAWAL"):
    """Petition + grant a court order. Returns the GRANTED order."""
    payload = create_court_order_payload(
        client_id=client_id, order_type=order_type,
        amount_limit_cents=amount_limit_cents,
        petitioned_date=petitioned_date, expiry_date=expiry_date,
    )
    if order_type != "RESTRICTED_WITHDRAWAL":
        payload.pop("amount_limit_cents", None)
    order = get_success_data(api.create_court_order(payload, ADMIN))
    return get_success_data(api.grant_court_order(order["id"], ADMIN))


def create_conservator(client_id, authority_scope="EXCLUSIVE", **overrides):
    """Register a conservator (starts ACTIVE). Returns the conservator."""
    return get_success_data(api.create_conservator(
        create_conservator_payload(client_id=client_id, authority_scope=authority_scope, **overrides),
        ADMIN,
    ))


def create_spend_down_plan(client_id, target_month="2026-06",
                           entries=None, as_user_id="cm-1"):
    """Create a DRAFT spend-down plan."""
    if entries is None:
        entries = [{"category": "MEDICAL", "planned_amount_cents": 1000}]
    return get_success_data(api.create_spend_down_plan(
        create_spend_down_plan_payload(client_id=client_id, target_month=target_month,
                                       entries=entries),
        make_case_manager_headers(as_user_id),
    ))


def create_active_spend_down_plan(client_id, target_month="2026-06",
                                  entries=None, as_user_id="cm-1"):
    """Create + activate a spend-down plan (requires positive provisional excess)."""
    sp = create_spend_down_plan(client_id, target_month=target_month,
                                entries=entries, as_user_id=as_user_id)
    return get_success_data(
        api.activate_spend_down_plan(sp["id"], make_case_manager_headers(as_user_id))
    )


def create_audit_with_findings(client_id, misuse_amount_cents, findings_count=1,
                               **overrides):
    """Open an audit case and issue findings. Returns FINDINGS_ISSUED case."""
    case = get_success_data(api.create_audit_case(
        create_audit_case_payload(client_id=client_id, **overrides), AUD
    ))
    return get_success_data(api.issue_findings(
        case["id"],
        {"misuse_amount_cents": misuse_amount_cents, "findings_count": findings_count},
        AUD,
    ))


def create_submitted_report(client_id, report_type="SSA_6233",
                            period_start_date="2026-05-01",
                            period_end_date="2026-05-31", basis="CASH",
                            cm_user_id="cm-1", fo_user_id="fo-1"):
    """Create + submit a report. Returns the SUBMITTED report."""
    report = get_success_data(api.create_accounting_report(
        create_accounting_report_payload(
            client_id=client_id, report_type=report_type,
            period_start_date=period_start_date, period_end_date=period_end_date,
            basis=basis,
        ),
        make_case_manager_headers(cm_user_id),
    ))
    return get_success_data(
        api.submit_accounting_report(report["id"], make_financial_officer_headers(fo_user_id))
    )
