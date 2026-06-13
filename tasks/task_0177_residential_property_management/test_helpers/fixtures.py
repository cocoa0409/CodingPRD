"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked through a 5-12 call
preamble (owner -> property -> unit -> applicant -> screen -> decide ->
lease -> deposit -> sign) to reach an ACTIVE lease before the behavior under
test can even be exercised. These helpers encapsulate those preambles.

All setup calls use get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion failure inside a test. The harness wipes the database before every
test, so every helper builds its world from scratch.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_owner_payload,
    create_property_payload,
    create_unit_payload,
    create_applicant_payload,
    create_lease_payload,
    create_rent_charge_payload,
    create_payment_payload,
    create_security_deposit_payload,
    create_work_order_payload,
    create_eviction_payload,
    create_owner_statement_payload,
    create_turnover_payload,
)
from .test_users import TEST_USERS

PM = TEST_USERS["property_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# --- Tier 1: base entities ---------------------------------------------------

def create_owner(management_fee_pct=0.08, **overrides):
    res = api_client.create_owner(
        create_owner_payload(management_fee_pct=management_fee_pct, **overrides), PM
    )
    return get_success_data(res)


def create_property(owner_id=None, state_code="TX", reserve_floor_cents=0, **overrides):
    if owner_id is None:
        owner_id = create_owner()["id"]
    res = api_client.create_property(
        create_property_payload(
            owner_id,
            state_code=state_code,
            reserve_floor_cents=reserve_floor_cents,
            **overrides,
        ),
        PM,
    )
    return get_success_data(res)


def create_unit(property_id=None, market_rent_cents=200000, **overrides):
    if property_id is None:
        property_id = create_property()["id"]
    res = api_client.create_unit(
        create_unit_payload(property_id, market_rent_cents=market_rent_cents, **overrides),
        PM,
    )
    return get_success_data(res)


def fund_trust(property_id, amount_cents):
    res = api_client.fund_trust(property_id, {"amount_cents": amount_cents}, PM)
    return get_success_data(res)


# --- Tier 2: applicant lifecycle --------------------------------------------

def create_submitted_applicant(unit_id, **overrides):
    res = api_client.create_applicant(create_applicant_payload(unit_id, **overrides), PM)
    return get_success_data(res)


def create_screened_applicant(unit_id, **overrides):
    """Submit then screen an applicant. Returns the SCREENED applicant."""
    app = create_submitted_applicant(unit_id, **overrides)
    res = api_client.screen_applicant(app["id"], PM)
    return get_success_data(res)


def create_approved_applicant(unit_id, **overrides):
    """Submit -> screen -> decide(APPROVE). Returns the APPROVED applicant.

    Defaults produce a passing applicant (income 12_000_000, rent 200_000,
    credit 700 -> rti 0.20, dti 0.20).
    """
    app = create_screened_applicant(unit_id, **overrides)
    res = api_client.decide_applicant(app["id"], {"decision": "APPROVE"}, PM)
    return get_success_data(res)


# --- Tier 3: lease lifecycle -------------------------------------------------

def create_draft_lease(unit_id, applicant_id, **lease_overrides):
    res = api_client.create_lease(
        create_lease_payload(unit_id, applicant_id=applicant_id, **lease_overrides), PM
    )
    return get_success_data(res)


def collect_deposit(lease_id, collected_cents=200000, collected_date="2026-06-01"):
    res = api_client.create_security_deposit(
        create_security_deposit_payload(
            lease_id, collected_cents=collected_cents, collected_date=collected_date
        ),
        PM,
    )
    return get_success_data(res)


def setup_active_lease(
    state_code="TX",
    reserve_floor_cents=0,
    market_rent_cents=200000,
    deposit_cents=200000,
    deposit_date="2026-06-01",
    applicant_overrides=None,
    lease_overrides=None,
):
    """Walk an empty database to a signed ACTIVE lease.

    Sequence: owner -> property -> unit -> applicant(screen,approve) ->
    draft lease -> collect deposit -> sign.

    Returns a dict with keys: owner, property, unit, applicant, lease (signed),
    deposit, and tenant_id (from the signed lease).
    """
    owner = create_owner()
    prop = create_property(
        owner_id=owner["id"],
        state_code=state_code,
        reserve_floor_cents=reserve_floor_cents,
    )
    unit = create_unit(property_id=prop["id"], market_rent_cents=market_rent_cents)
    app = create_approved_applicant(unit["id"], **(applicant_overrides or {}))
    lease = create_draft_lease(unit["id"], app["id"], **(lease_overrides or {}))
    deposit = collect_deposit(
        lease["id"], collected_cents=deposit_cents, collected_date=deposit_date
    )
    signed = get_success_data(api_client.sign_lease(lease["id"], PM))
    return {
        "owner": owner,
        "property": prop,
        "unit": unit,
        "applicant": app,
        "lease": signed,
        "deposit": deposit,
        "tenant_id": signed.get("tenant_id"),
    }


def setup_draft_lease_ready_to_sign(
    state_code="TX",
    market_rent_cents=200000,
    with_deposit=True,
    approve=True,
    lease_overrides=None,
):
    """Build up to a DRAFT lease (not signed). Useful for sign-precondition tests.

    approve=False leaves the applicant at SCREENED.
    with_deposit=False skips deposit collection.
    Returns dict: owner, property, unit, applicant, lease (DRAFT), deposit (or None).
    """
    owner = create_owner()
    prop = create_property(owner_id=owner["id"], state_code=state_code)
    unit = create_unit(property_id=prop["id"], market_rent_cents=market_rent_cents)
    if approve:
        app = create_approved_applicant(unit["id"])
    else:
        app = create_screened_applicant(unit["id"])
    lease = create_draft_lease(unit["id"], app["id"], **(lease_overrides or {}))
    deposit = collect_deposit(lease["id"]) if with_deposit else None
    return {
        "owner": owner,
        "property": prop,
        "unit": unit,
        "applicant": app,
        "lease": lease,
        "deposit": deposit,
    }


# --- Tier 4: rent roll / charges / payments ---------------------------------

def post_rent_charge(lease_id, amount_cents=200000, period_label="2026-06",
                     due_date="2026-06-01", charge_type="RENT"):
    res = api_client.create_rent_charge(
        create_rent_charge_payload(
            lease_id,
            amount_cents=amount_cents,
            period_label=period_label,
            due_date=due_date,
            charge_type=charge_type,
        ),
        PM,
    )
    return get_success_data(res)


def post_payment(lease_id, amount_cents, received_date="2026-06-10"):
    res = api_client.create_payment(
        create_payment_payload(lease_id, amount_cents, received_date=received_date), PM
    )
    return get_success_data(res)


def assess_late_fees(lease_id, as_of_date):
    res = api_client.assess_late_fees(lease_id, {"as_of_date": as_of_date}, PM)
    return get_success_data(res)


def list_late_fee_charges(lease_id):
    """Return the list of LATE_FEE charges on a lease (sorted by created_at)."""
    res = api_client.list_rent_charges(
        PM, params={"lease_id": lease_id, "charge_type": "LATE_FEE"}
    )
    data, _ = _paginated(res)
    return data


def _paginated(res):
    """Lenient extraction of (data_list, meta) from a list response."""
    body = res.json()
    return body.get("data", []), body.get("meta", {})


# --- Tier 5: eviction lifecycle ---------------------------------------------

def serve_eviction(lease_id, reason="NONPAYMENT", notice_date="2026-06-10"):
    res = api_client.create_eviction(
        create_eviction_payload(lease_id, reason=reason, notice_date=notice_date), PM
    )
    return get_success_data(res)


def setup_filed_eviction(
    state_code="FL",
    reason="NONPAYMENT",
    notice_date="2026-06-10",
    file_as_of_date="2026-06-20",
    with_rent_charge=True,
    rent_amount=200000,
):
    """Active lease -> serve notice -> (file after cure window). Returns dict.

    Keys: world (the setup_active_lease dict), eviction (FILED case).
    """
    world = setup_active_lease(state_code=state_code, market_rent_cents=rent_amount,
                               deposit_cents=rent_amount)
    lease_id = world["lease"]["id"]
    if with_rent_charge:
        post_rent_charge(lease_id, amount_cents=rent_amount)
    eviction = serve_eviction(lease_id, reason=reason, notice_date=notice_date)
    filed = get_success_data(
        api_client.file_eviction(eviction["id"], {"as_of_date": file_as_of_date}, CO)
    )
    world["eviction"] = filed
    return world


# --- Tier 6: deposit settlement / lease wind-down ---------------------------

def setup_expired_lease(
    state_code="TX",
    start_date="2026-06-01",
    end_date="2027-06-01",
    expire_as_of="2027-06-01",
    deposit_cents=200000,
    deposit_date="2026-06-01",
    market_rent_cents=200000,
    rent_charge=None,
):
    """Active lease -> (optional rent charge) -> expire. Returns the setup dict
    plus an 'eviction'-free wound-down world. Key 'deposit' is the HELD deposit.

    rent_charge: dict of {amount_cents, period_label, due_date} to post before expiry.
    """
    world = setup_active_lease(
        state_code=state_code,
        market_rent_cents=market_rent_cents,
        deposit_cents=deposit_cents,
        deposit_date=deposit_date,
        lease_overrides={"start_date": start_date, "end_date": end_date},
    )
    lease_id = world["lease"]["id"]
    if rent_charge:
        post_rent_charge(lease_id, **rent_charge)
    expired = get_success_data(
        api_client.expire_lease(lease_id, {"as_of_date": expire_as_of}, PM)
    )
    world["lease"] = expired
    return world


# --- Tier 7: work orders -----------------------------------------------------

def create_work_order(unit_id, charge_to_owner=False, **overrides):
    res = api_client.create_work_order(
        create_work_order_payload(unit_id, charge_to_owner=charge_to_owner, **overrides),
        PM,
    )
    return get_success_data(res)


def create_assigned_work_order(unit_id, charge_to_owner=False, **overrides):
    wo = create_work_order(unit_id, charge_to_owner=charge_to_owner, **overrides)
    assigned = get_success_data(api_client.assign_work_order(wo["id"], PM))
    return assigned


def create_completed_work_order(unit_id, actual_cost_cents=5000,
                                completed_date="2026-06-15", charge_to_owner=False,
                                **overrides):
    wo = create_assigned_work_order(unit_id, charge_to_owner=charge_to_owner, **overrides)
    completed = get_success_data(
        api_client.complete_work_order(
            wo["id"],
            {"actual_cost_cents": actual_cost_cents, "completed_date": completed_date},
            PM,
        )
    )
    return completed


# --- Tier 8: owner statements -----------------------------------------------

def create_draft_statement(property_id, period_label="2026-06", basis="CASH"):
    res = api_client.create_owner_statement(
        create_owner_statement_payload(property_id, period_label=period_label, basis=basis),
        PM,
    )
    return get_success_data(res)


def create_finalized_statement(property_id, period_label="2026-06", basis="CASH"):
    stmt = create_draft_statement(property_id, period_label=period_label, basis=basis)
    finalized = get_success_data(api_client.finalize_owner_statement(stmt["id"], PM))
    return finalized


def property_version(property_id):
    res = api_client.get_property(property_id, PM)
    return get_success_data(res)["version"]


# --- Tier 9: turnover --------------------------------------------------------

def create_open_turnover(unit_id, opened_date="2026-07-02",
                         target_ready_date="2026-07-20", make_ready_cost_cents=None):
    overrides = {}
    if make_ready_cost_cents is not None:
        overrides["make_ready_cost_cents"] = make_ready_cost_cents
    res = api_client.create_turnover(
        create_turnover_payload(
            unit_id, opened_date=opened_date, target_ready_date=target_ready_date,
            **overrides,
        ),
        PM,
    )
    return get_success_data(res)
