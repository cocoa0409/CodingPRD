"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use get_success_data() so a setup
failure surfaces as a clear error naming the step.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS as TD
from .factories import (
    create_acquisition_payload,
    create_deposit_payload,
    create_employee_decision_payload,
    create_inspection_payload,
    create_finding_payload,
    create_insurance_policy_payload,
    create_lease_file_payload,
    create_rent_roll_entry_payload,
    create_service_contract_payload,
    create_tax_projection_payload,
    create_unit_payload,
    generate_statement_payload,
)
from .test_users import (
    TEST_USERS,
    make_property_ops_headers,
    make_underwriting_manager_headers,
)

ANALYST = TEST_USERS["analyst_headers"]
UM1 = TEST_USERS["underwriting_manager_headers"]
UM2 = make_underwriting_manager_headers("um-2")
UM3 = make_underwriting_manager_headers("um-3")
POL1 = TEST_USERS["property_ops_headers"]
POL2 = make_property_ops_headers("pol-2")
HR1 = TEST_USERS["hr_partner_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]
EO1 = TEST_USERS["escrow_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

CLOSING = TD["CLOSING_DATE"]            # 2026-09-12
CLOCK_AT_CLOSING = "2026-09-12T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: acquisition creation and phase progression
# ---------------------------------------------------------------------------

def create_acquisition(**overrides):
    """Create an acquisition in DRAFT. Returns the acquisition."""
    return get_success_data(api_client.create_acquisition(
        create_acquisition_payload(**overrides), ANALYST), 201)


def create_kicked_off_acquisition(**overrides):
    """Create + kickoff. Returns the IN_DILIGENCE acquisition."""
    acq = create_acquisition(**overrides)
    return get_success_data(api_client.kickoff_acquisition(acq["id"], UM1))


def get_acquisition(acquisition_id):
    return get_success_data(api_client.get_acquisition(acquisition_id, UM1))


def get_acquisition_version(acquisition_id):
    return get_acquisition(acquisition_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2: single-workstream builders (unit, lease, rent roll, walk, deposit)
# ---------------------------------------------------------------------------

def add_unit(acquisition_id, **overrides):
    """Register a unit (born REGISTERED). Returns the unit."""
    return get_success_data(api_client.create_unit(
        create_unit_payload(acquisition_id, **overrides), ANALYST), 201)


def add_lease(unit_id, **overrides):
    """Upload a lease (born UPLOADED). Returns the lease file."""
    return get_success_data(api_client.create_lease_file(
        create_lease_file_payload(unit_id, **overrides), ANALYST), 201)


def add_rent_roll_entry(unit_id, **overrides):
    """Record the unit's rent roll line (born UNVERIFIED)."""
    return get_success_data(api_client.create_rent_roll_entry(
        create_rent_roll_entry_payload(unit_id, **overrides), ANALYST), 201)


def add_audited_lease(unit_id, *, contract_rent_cents=None, reported_rent_cents=None,
                      reported_deposit_cents=None, lease_start_date=None,
                      lease_end_date=None, deposit_amount_cents=None):
    """Lease + matching rent roll + audit. Variance 0 lands AUDITED/MATCH.

    Returns the lease.
    """
    rent = TD["CONTRACT_RENT_CENTS"] if contract_rent_cents is None else contract_rent_cents
    lease_kwargs = {"contract_rent_cents": rent}
    if lease_start_date is not None:
        lease_kwargs["lease_start_date"] = lease_start_date
    if lease_end_date is not None:
        lease_kwargs["lease_end_date"] = lease_end_date
    if deposit_amount_cents is not None:
        lease_kwargs["deposit_amount_cents"] = deposit_amount_cents
    lease = add_lease(unit_id, **lease_kwargs)
    rr_kwargs = {"reported_rent_cents": rent if reported_rent_cents is None else reported_rent_cents}
    if reported_deposit_cents is not None:
        rr_kwargs["reported_deposit_cents"] = reported_deposit_cents
    if lease_start_date is not None:
        rr_kwargs["move_in_date"] = lease_start_date
    add_rent_roll_entry(unit_id, **rr_kwargs)
    get_success_data(api_client.audit_lease_file(lease["id"], ANALYST))
    return get_success_data(api_client.get_lease_file(lease["id"], ANALYST))


def add_qa_accepted_walk(unit_id, *, inspector_ref=None, walk_start=None,
                         walk_end=None, condition_rating=4):
    """Schedule + complete + QA-accept a no-findings walk (SoD: pol-1 completes,
    pol-2 accepts). Returns the QA_ACCEPTED inspection."""
    kwargs = {}
    if inspector_ref is not None:
        kwargs["inspector_ref"] = inspector_ref
    if walk_start is not None:
        kwargs["walk_start"] = walk_start
    if walk_end is not None:
        kwargs["walk_end"] = walk_end
    insp = get_success_data(api_client.create_inspection(
        create_inspection_payload(unit_id, **kwargs), POL1), 201)
    get_success_data(api_client.complete_inspection(
        insp["id"], condition_rating, True, POL1))
    return get_success_data(api_client.qa_accept_inspection(insp["id"], POL2))


def add_reconciled_deposit(lease_id, *, seller_stated_amount_cents=None,
                           interest_required=True, annual_interest_rate=None,
                           do_reconcile=True):
    """Record a deposit entry and (optionally) reconcile it. With the defaults
    (stated 153090 = 150000 principal + 3090 DAILY_ACCRUAL interest over the
    376 days from 2025-09-01 to the 2026-09-12 closing) variance is zero and
    reconcile lands RECONCILED. Returns the entry."""
    kwargs = {"interest_required": interest_required}
    if seller_stated_amount_cents is not None:
        kwargs["seller_stated_amount_cents"] = seller_stated_amount_cents
    if annual_interest_rate is not None:
        kwargs["annual_interest_rate"] = annual_interest_rate
    dep = get_success_data(api_client.create_deposit(
        create_deposit_payload(lease_id, **kwargs), ANALYST), 201)
    if do_reconcile:
        return get_success_data(api_client.reconcile_deposit(dep["id"], ANALYST))
    return dep


def setup_verified_unit(*, contract_rent_cents=None, market_rent_cents=None,
                        deposit_amount_cents=None, stated_deposit_cents=None,
                        lease_start_date=None, lease_end_date=None,
                        interest_accrual_method=None, **acq_overrides):
    """IN_DILIGENCE acquisition + one fully VERIFIED unit (lease audited clean,
    walk QA_ACCEPTED with no findings, deposit reconciled with zero variance).

    Lease/rent-roll and deposit inputs are parameterizable; the deposit's
    seller-stated amount must equal principal plus the interest the
    acquisition's accrual method produces for the lease window, so that
    reconcile lands RECONCILED (variance 0).

    Returns dict(acq, unit, lease, inspection, deposit).
    """
    if interest_accrual_method is not None:
        acq_overrides["interest_accrual_method"] = interest_accrual_method
    acq = create_kicked_off_acquisition(**acq_overrides)
    unit_kwargs = {}
    if market_rent_cents is not None:
        unit_kwargs["market_rent_cents"] = market_rent_cents
    unit = add_unit(acq["id"], **unit_kwargs)
    lease = add_audited_lease(
        unit["id"],
        contract_rent_cents=contract_rent_cents,
        reported_deposit_cents=stated_deposit_cents,
        lease_start_date=lease_start_date,
        lease_end_date=lease_end_date,
        deposit_amount_cents=deposit_amount_cents,
    )
    inspection = add_qa_accepted_walk(unit["id"])
    deposit = add_reconciled_deposit(
        lease["id"], seller_stated_amount_cents=stated_deposit_cents)
    unit = get_success_data(api_client.get_unit(unit["id"], ANALYST))
    assert unit["status"] == "VERIFIED", (
        f"setup failed: unit should be VERIFIED, got {unit['status']}"
    )
    return {"acq": get_acquisition(acq["id"]), "unit": unit, "lease": lease,
            "inspection": inspection, "deposit": deposit}


def complete_diligence(acquisition_id):
    return get_success_data(api_client.complete_diligence(acquisition_id, UM1))


def setup_diligence_complete(**overrides):
    """Verified-unit scenario driven through complete-diligence.

    Returns the Tier-2 dict with the acquisition in DILIGENCE_COMPLETE.
    """
    ctx = setup_verified_unit(**overrides)
    complete_diligence(ctx["acq"]["id"])
    ctx["acq"] = get_acquisition(ctx["acq"]["id"])
    return ctx


def setup_diligence_complete_with_lease(**lease_kwargs):
    """setup_diligence_complete with explicit lease/deposit economics.

    Accepts contract_rent_cents, market_rent_cents, deposit_amount_cents,
    stated_deposit_cents, lease window dates, and acquisition overrides such as
    closing_date / diligence_deadline / interest_accrual_method.
    """
    return setup_diligence_complete(**lease_kwargs)


# ---------------------------------------------------------------------------
# Tier 3: tax projection lifecycle
# ---------------------------------------------------------------------------

def add_approved_price_anchored_projection(acquisition_id):
    """Create + compute + approve a PURCHASE_PRICE_ANCHORED projection.

    On the standard 200000000-price / 0.40-ratio / 25.0-millage acquisition
    the approved annual tax is 2000000 cents. Returns the projection.
    """
    version = get_acquisition_version(acquisition_id)
    proj = get_success_data(api_client.create_tax_projection(
        acquisition_id,
        create_tax_projection_payload(version, method="PURCHASE_PRICE_ANCHORED"),
        ANALYST), 201)
    get_success_data(api_client.compute_tax_projection(proj["id"], ANALYST))
    return get_success_data(api_client.approve_tax_projection(proj["id"], UM1))


def add_approved_income_projection(acquisition_id, *, cap_rate=0.055,
                                   noi_t12_cents=16_500_000):
    """Create + compute + approve an INCOME_APPROACH projection (defaults give
    value 300000000 and annual tax 3000000 on the standard acquisition)."""
    version = get_acquisition_version(acquisition_id)
    proj = get_success_data(api_client.create_tax_projection(
        acquisition_id,
        create_tax_projection_payload(version, method="INCOME_APPROACH",
                                      cap_rate=cap_rate, noi_t12_cents=noi_t12_cents),
        ANALYST), 201)
    get_success_data(api_client.compute_tax_projection(proj["id"], ANALYST))
    return get_success_data(api_client.approve_tax_projection(proj["id"], UM1))


# ---------------------------------------------------------------------------
# Tier 4: statement generation and the DRAFT -> REVIEWED -> APPROVED SoD chain
# ---------------------------------------------------------------------------

def generate_statement(acquisition_id, statement_type, day_count_method="ACTUAL_365"):
    """Generate a statement with a fresh OCC attestation. Returns it (DRAFT)."""
    version = get_acquisition_version(acquisition_id)
    return get_success_data(api_client.generate_proration_statement(
        acquisition_id,
        generate_statement_payload(statement_type, day_count_method, version),
        UM1), 201)


def run_statement_sod_chain(statement_id):
    """Drive a DRAFT statement to APPROVED: um-2 reviews, um-3 approves
    (creator um-1; PRD §3.8's three segregation-of-duties gates)."""
    get_success_data(api_client.submit_statement_review(statement_id, UM2))
    return get_success_data(api_client.approve_statement(statement_id, UM3))


def generate_approved_statement(acquisition_id, statement_type,
                                day_count_method="ACTUAL_365"):
    stmt = generate_statement(acquisition_id, statement_type, day_count_method)
    run_statement_sod_chain(stmt["id"])
    return get_success_data(api_client.get_proration_statement(stmt["id"], UM1))


# ---------------------------------------------------------------------------
# Tier 5: pre-closing and closing lifecycles
# ---------------------------------------------------------------------------

def setup_pre_closing(*, queue_deposit=True, with_draft_statement=True,
                      **overrides):
    """Diligence-complete acquisition + approved tax projection + APPROVED
    DRAFT_CLOSING statement + advance to PRE_CLOSING; optionally queues the
    deposit for escrow. Returns the context dict plus stmt_draft."""
    ctx = setup_diligence_complete(**overrides)
    acq_id = ctx["acq"]["id"]
    ctx["proj"] = add_approved_price_anchored_projection(acq_id)
    ctx["stmt_draft"] = generate_approved_statement(acq_id, "DRAFT_CLOSING")
    get_success_data(api_client.advance_to_pre_closing(acq_id, UM1))
    if queue_deposit:
        ctx["deposit"] = get_success_data(
            api_client.queue_deposit_escrow(ctx["deposit"]["id"], EO1))
    ctx["acq"] = get_acquisition(acq_id)
    assert ctx["acq"]["status"] == "PRE_CLOSING", "setup failed: not PRE_CLOSING"
    return ctx


def setup_closed_acquisition(**overrides):
    """Full lifecycle through CLOSED: PRE_CLOSING context + APPROVED
    FINAL_CLOSING statement + clock at the closing date + execute-closing.
    Returns the context dict plus stmt_final."""
    ctx = setup_pre_closing(**overrides)
    acq_id = ctx["acq"]["id"]
    ctx["stmt_final"] = generate_approved_statement(acq_id, "FINAL_CLOSING")
    get_success_data(api_client.set_clock(CLOCK_AT_CLOSING, ADMIN))
    get_success_data(api_client.execute_closing(acq_id, UM1))
    ctx["acq"] = get_acquisition(acq_id)
    assert ctx["acq"]["status"] == "CLOSED", "setup failed: not CLOSED"
    return ctx


# ---------------------------------------------------------------------------
# Ancillary workstreams used by closing scenarios
# ---------------------------------------------------------------------------

def add_assumed_service_contract(acquisition_id, **overrides):
    """Register + begin-review + assume a service contract."""
    sc = get_success_data(api_client.create_service_contract(
        create_service_contract_payload(acquisition_id, **overrides), VM1), 201)
    get_success_data(api_client.begin_review_service_contract(sc["id"], VM1))
    return get_success_data(api_client.assume_service_contract(sc["id"], VM1))


def add_assumed_low_risk_policy(acquisition_id, **overrides):
    """Register + review-loss-runs + assume a LOW-tier policy (default loss
    run 100000 on premium 1200000 gives ratio ~0.028)."""
    pol = get_success_data(api_client.create_insurance_policy(
        create_insurance_policy_payload(acquisition_id, **overrides), ANALYST), 201)
    get_success_data(api_client.review_loss_runs(pol["id"], UM1))
    return get_success_data(api_client.assume_insurance_policy(pol["id"], UM1))


def add_approved_employee_decision(acquisition_id, *, proposer_headers=None,
                                   approver_headers=None, **overrides):
    """Propose (HRPartner) + approve (UnderwritingManager) a decision.
    Defaults: TERMINATE, hire 2020-01-01, salary 5200000, PTO 40h,
    notice 2026-08-10, effective 2026-09-01 (22 days >= 14)."""
    proposer = proposer_headers or HR1
    approver = approver_headers or UM1
    dec = get_success_data(api_client.create_employee_decision(
        create_employee_decision_payload(acquisition_id, **overrides), proposer), 201)
    return get_success_data(api_client.approve_employee_decision(dec["id"], approver))


def add_completed_inspection(unit_id, *, completer_headers=None, no_findings=False,
                             condition_rating=2, **overrides):
    """Schedule + complete a walk (no QA step). Returns the COMPLETED inspection."""
    completer = completer_headers or POL1
    insp = get_success_data(api_client.create_inspection(
        create_inspection_payload(unit_id, **overrides), POL1), 201)
    get_success_data(api_client.complete_inspection(
        insp["id"], condition_rating, no_findings, completer))
    return get_success_data(api_client.get_inspection(insp["id"], POL1))


def add_finding(inspection_id, **overrides):
    """Record a deficiency finding (born OPEN) on a COMPLETED inspection."""
    return get_success_data(api_client.create_finding(
        create_finding_payload(inspection_id, **overrides), POL1), 201)
