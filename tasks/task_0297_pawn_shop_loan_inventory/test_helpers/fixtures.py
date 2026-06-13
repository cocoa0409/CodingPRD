"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so a setup failure
surfaces as a clear "Setup step failed" error rather than a confusing
assertion failure deep inside a test.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before every test.

Identity threading: the appraiser and originating loan officer must be distinct
opaque operator ids (PRD §3.2 separation of duties). Fixtures default to
appraiser id "appraiser-1" and officer id "officer-1".
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import FL_SCHEDULE, CA_SCHEDULE, EPOCH, GRACE_END
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_appraiser_headers,
    make_officer_headers,
)

MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
LAW = TEST_USERS["law_headers"]


# ─── Clock control ────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Set the simulated clock (PRD §3.11). ShopManager-only."""
    return get_success_data(api_client.set_clock(f.set_clock_payload(to_iso8601), MANAGER))


# ─── Tier 1/2: base configuration ─────────────────────────────────────

def setup_schedule_and_shop(schedule=None, police_reporting_enabled=False,
                            clock=EPOCH, shop_name="Test Branch"):
    """Set the clock, create a state schedule, a shop in that state, and a bin.

    Returns dict with shop, bin, state_code, schedule.
    """
    schedule = dict(schedule or FL_SCHEDULE)
    state_code = schedule["state_code"]
    if clock is not None:
        set_clock(clock)
    get_success_data(api_client.create_state_schedule(
        f.create_state_schedule_payload(**schedule), MANAGER))
    shop = get_success_data(api_client.create_shop(
        f.create_shop_payload(name=shop_name, state_code=state_code,
                              police_reporting_enabled=police_reporting_enabled), MANAGER))
    bin_ = get_success_data(api_client.create_storage_bin(
        f.create_storage_bin_payload(shop["id"], label="A-1", capacity=5), MANAGER))
    return {"shop": shop, "bin": bin_, "state_code": state_code, "schedule": schedule}


def create_customer(full_name="Test Borrower", gov_id_number=None):
    payload = f.create_customer_payload(full_name=full_name)
    if gov_id_number is not None:
        payload["gov_id_number"] = gov_id_number
    return get_success_data(api_client.create_customer(payload, OFFICER))


def create_appraised_item(shop_id, customer_id, appraised_value_cents=40000,
                          description="Test item", serial_number=None,
                          appraiser_id="appraiser-1"):
    """Intake an item and appraise it, returning the APPRAISED item dict.

    The appraiser id is recorded as appraised_by_user_id (PRD §3.2).
    """
    payload = f.create_item_payload(shop_id, customer_id, description=description)
    if serial_number is not None:
        payload["serial_number"] = serial_number
    item = get_success_data(api_client.create_item(payload, OFFICER))
    item = get_success_data(api_client.appraise_item(
        item["id"], f.appraise_item_payload(appraised_value_cents),
        make_appraiser_headers(appraiser_id)))
    return item


# ─── Tier 3: a fully originated loan ──────────────────────────────────

def originate_loan(shop_id, item_id, bin_id, officer_id="officer-1"):
    """Originate a loan against an APPRAISED item (PRD §3.3). LoanOfficer-only.

    officer_id must differ from the appraiser id to satisfy separation of duties.
    """
    return get_success_data(api_client.create_loan(
        f.create_loan_payload(shop_id, item_id, bin_id),
        make_officer_headers(officer_id)))


def setup_active_loan(schedule=None, police_reporting_enabled=False,
                      appraised_value_cents=40000, clock=EPOCH,
                      serial_number=None, customer_name="Test Borrower"):
    """Full chain to a freshly originated ACTIVE loan.

    Returns dict: shop, bin, customer, item, loan, schedule, state_code.
    Loan principal at the default FL params (appraised 40000, ltv 5000) is 20000.
    """
    base = setup_schedule_and_shop(schedule=schedule,
                                   police_reporting_enabled=police_reporting_enabled,
                                   clock=clock)
    customer = create_customer(full_name=customer_name)
    item = create_appraised_item(base["shop"]["id"], customer["id"],
                                 appraised_value_cents=appraised_value_cents,
                                 serial_number=serial_number)
    loan = originate_loan(base["shop"]["id"], item["id"], base["bin"]["id"])
    return {**base, "customer": customer, "item": item, "loan": loan}


# ─── Tier 4/5: forfeiture → priced inventory ──────────────────────────

def get_inventory_for_loan(loan_id):
    """Reverse-reachability lookup of the inventory item spawned by a forfeit."""
    data, _meta = _list(api_client.list_inventory(MANAGER, params={"source_loan_id": loan_id}))
    return data


def _list(response):
    body = response.json()
    return body["data"], body["meta"]


def setup_forfeited_inventory(appraised_value_cents=40000, schedule=None,
                              police_reporting_enabled=False,
                              forfeit_clock=GRACE_END):
    """Originate an FL loan, advance the clock to grace_end, forfeit it, and
    return the spawned AVAILABLE InventoryItem along with the full context.

    At the default FL params (appraised 40000 -> principal 20000), forfeiting
    exactly at grace_end (60 days, 2 live periods) yields cost_basis 25200,
    floor_price 25200, list_price 54000.

    Returns dict: shop, bin, customer, item, loan, inventory, schedule.
    """
    ctx = setup_active_loan(schedule=schedule,
                            police_reporting_enabled=police_reporting_enabled,
                            appraised_value_cents=appraised_value_cents)
    set_clock(forfeit_clock)
    get_success_data(api_client.forfeit_loan(ctx["loan"]["id"], MANAGER))
    inv_list = get_inventory_for_loan(ctx["loan"]["id"])
    assert len(inv_list) == 1, f"expected exactly one spawned inventory item, got {len(inv_list)}"
    return {**ctx, "inventory": inv_list[0]}


def setup_layaway_plan(installment_count=3, appraised_value_cents=40000,
                       reserved_until_at="2026-12-01T00:00:00.000Z"):
    """Forfeit a loan to spawn inventory, then put that item on layaway.

    Returns dict: ...forfeited context..., plan, plus installments list.
    """
    ctx = setup_forfeited_inventory(appraised_value_cents=appraised_value_cents)
    plan = get_success_data(api_client.create_layaway_plan(
        f.create_layaway_plan_payload(ctx["inventory"]["id"], ctx["customer"]["id"],
                                      installment_count=installment_count,
                                      reserved_until_at=reserved_until_at),
        MANAGER))
    inst_data, _ = _list(api_client.list_layaway_installments(plan["id"], MANAGER))
    return {**ctx, "plan": plan, "installments": inst_data}


# ─── Police hold helpers ──────────────────────────────────────────────

def place_pawn_item_hold(pawn_item_id, case_number="CASE-1"):
    """LawEnforcement places an ACTIVE hold on a pawn item (PRD §3.10)."""
    return get_success_data(api_client.create_police_hold(
        f.create_police_hold_payload("PAWN_ITEM", case_number=case_number,
                                     pawn_item_id=pawn_item_id),
        LAW))


def place_inventory_item_hold(inventory_item_id, case_number="CASE-1"):
    """LawEnforcement places an ACTIVE hold on an inventory item (PRD §3.10)."""
    return get_success_data(api_client.create_police_hold(
        f.create_police_hold_payload("INVENTORY_ITEM", case_number=case_number,
                                     inventory_item_id=inventory_item_id),
        LAW))
