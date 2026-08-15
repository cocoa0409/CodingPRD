"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server, so nothing carries over).
Lenient get_success_data is used internally so setup failures surface as
clear "Setup failed" errors instead of confusing assertion failures.

Identity threading (PRD §2.1): WaterUser calls that are ownership-gated
(order create/cancel, transfer create/cancel, invoice pay) always use
make_water_user_headers(account_id); DitchRider assignment-gated calls
(start, submit-measurement) always use make_ditch_rider_headers(rider_user_id).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_assessment_invoice_payload,
    create_canal_reach_payload,
    create_drought_declaration_payload,
    create_maintenance_window_payload,
    create_season_allocation_payload,
    create_season_payload,
    create_turnout_order_payload,
    create_transfer_request_payload,
    create_water_account_payload,
)
from .test_users import TEST_USERS, make_ditch_rider_headers, make_water_user_headers

ADMIN = TEST_USERS["district_admin_headers"]
DEFAULT_ORDER_START = TEST_DEFAULTS["ORDER_START"]
DEFAULT_ORDER_END = TEST_DEFAULTS["ORDER_END"]


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: master data and lifecycle transitions
# ---------------------------------------------------------------------------

def create_account(holder_name: str = "Test Holder", parcel_number: str = "APN-000",
                   irrigated_acres: float = TEST_DEFAULTS["IRRIGATED_ACRES"],
                   water_right_priority_date: str = TEST_DEFAULTS["SENIOR_PRIORITY_DATE"],
                   **overrides) -> dict:
    payload = create_water_account_payload(
        holder_name=holder_name,
        parcel_number=parcel_number,
        irrigated_acres=irrigated_acres,
        water_right_priority_date=water_right_priority_date,
        **overrides,
    )
    return get_success_data(api_client.create_water_account(payload, ADMIN))


def get_account(account_id: str) -> dict:
    return get_success_data(api_client.get_water_account(account_id, ADMIN))


def create_season(**overrides) -> dict:
    """Create a season (born DRAFT)."""
    return get_success_data(api_client.create_season(create_season_payload(**overrides), ADMIN))


def get_season(season_id: str) -> dict:
    return get_success_data(api_client.get_season(season_id, ADMIN))


def announce_season(season_id: str) -> dict:
    return get_success_data(api_client.announce_season(season_id, ADMIN))


def open_season(season_id: str) -> dict:
    return get_success_data(api_client.open_season(season_id, ADMIN))


def create_announced_season(**overrides) -> dict:
    season = create_season(**overrides)
    return announce_season(season["id"])


def create_open_season(**overrides) -> dict:
    season = create_announced_season(**overrides)
    return open_season(season["id"])


def create_reach(name: str = "Reach-1",
                 max_capacity_cfs: float = TEST_DEFAULTS["REACH_CAPACITY_CFS"],
                 **overrides) -> dict:
    payload = create_canal_reach_payload(
        name=name, max_capacity_cfs=max_capacity_cfs, **overrides,
    )
    return get_success_data(api_client.create_canal_reach(payload, ADMIN))


def get_reach(reach_id: str) -> dict:
    return get_success_data(api_client.get_canal_reach(reach_id, ADMIN))


def create_allocation(account_id: str, season_id: str) -> dict:
    payload = create_season_allocation_payload(account_id, season_id)
    return get_success_data(api_client.create_season_allocation(payload, ADMIN))


def get_allocation(allocation_id: str) -> dict:
    return get_success_data(api_client.get_season_allocation(allocation_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: ordering pipeline (account + allocation + reach + order)
# ---------------------------------------------------------------------------

def setup_open_season_with_allocation(
        irrigated_acres: float = TEST_DEFAULTS["IRRIGATED_ACRES"],
        priority_date: str = TEST_DEFAULTS["SENIOR_PRIORITY_DATE"],
        reach_capacity_cfs: float = TEST_DEFAULTS["REACH_CAPACITY_CFS"],
        holder_name: str = "Test Holder",
        parcel_number: str = "APN-000",
        **season_overrides) -> dict:
    """OPEN season + ACTIVE account + its allocation + a canal reach."""
    season = create_open_season(**season_overrides)
    account = create_account(
        holder_name=holder_name,
        parcel_number=parcel_number,
        irrigated_acres=irrigated_acres,
        water_right_priority_date=priority_date,
    )
    allocation = create_allocation(account["id"], season["id"])
    reach = create_reach(max_capacity_cfs=reach_capacity_cfs)
    return {"season": season, "account": account, "allocation": allocation,
            "reach": reach}


def place_order(account_id: str, allocation_id: str, reach_id: str,
                requested_cfs: float = 5.0,
                start: str = DEFAULT_ORDER_START,
                end: str = DEFAULT_ORDER_END,
                **overrides) -> dict:
    """Place a turnout order as the owning WaterUser.

    Reads the account fresh so expected_water_account_version matches the
    current version (PRD §2.6).
    """
    account = get_account(account_id)
    payload = create_turnout_order_payload(
        account_id, allocation_id, reach_id,
        expected_water_account_version=account["version"],
        requested_cfs=requested_cfs,
        requested_start_at=start,
        requested_end_at=end,
        **overrides,
    )
    return get_success_data(
        api_client.create_turnout_order(payload, make_water_user_headers(account_id))
    )


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_turnout_order(order_id, ADMIN))


def get_work_order_for_order(order_id: str) -> dict:
    """The single RiderWorkOrder created by scheduling (PRD §3.3)."""
    data, _meta = validate_paginated(
        api_client.list_rider_work_orders(ADMIN, params={"turnout_order_id": order_id})
    )
    assert len(data) == 1, (
        f"Expected exactly one work order for order {order_id}, got {len(data)}"
    )
    return data[0]


def get_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_rider_work_order(work_order_id, ADMIN))


def schedule_order(order_id: str, rider_user_id: str = "rider-1") -> tuple:
    """Schedule a REQUESTED order; returns (updated order, created work order)."""
    order = get_success_data(
        api_client.schedule_turnout_order(order_id, {"rider_user_id": rider_user_id}, ADMIN)
    )
    return order, get_work_order_for_order(order_id)


def start_order(order_id: str, rider_user_id: str) -> dict:
    """Assigned rider opens the turnout (clock must already be inside the window)."""
    return get_success_data(
        api_client.start_turnout_order(order_id, make_ditch_rider_headers(rider_user_id))
    )


def submit_measurement(work_order_id: str, rider_user_id: str,
                       measured_cfs: float, measured_hours: float) -> dict:
    return get_success_data(
        api_client.submit_measurement(
            work_order_id,
            {"measured_cfs": measured_cfs, "measured_hours": measured_hours},
            make_ditch_rider_headers(rider_user_id),
        )
    )


def verify_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.verify_work_order(work_order_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: full delivery lifecycle (order -> SCHEDULED -> FLOWING -> DELIVERED)
# ---------------------------------------------------------------------------

def setup_scheduled_order(requested_cfs: float = 5.0,
                          start: str = DEFAULT_ORDER_START,
                          end: str = DEFAULT_ORDER_END,
                          rider_user_id: str = "rider-1",
                          **scenario_overrides) -> dict:
    """OPEN season + account + allocation + reach + one SCHEDULED order with
    its ASSIGNED work order."""
    scenario = setup_open_season_with_allocation(**scenario_overrides)
    order = place_order(
        scenario["account"]["id"], scenario["allocation"]["id"],
        scenario["reach"]["id"],
        requested_cfs=requested_cfs, start=start, end=end,
    )
    order, work_order = schedule_order(order["id"], rider_user_id)
    scenario.update({"order": order, "work_order": work_order,
                     "rider_user_id": rider_user_id})
    return scenario


def setup_flowing_order(clock_at: str = "2026-06-01T09:00:00Z",
                        **kwargs) -> dict:
    """A scheduled order started by its rider (order FLOWING, work order
    IN_PROGRESS). The clock is set inside the requested window."""
    scenario = setup_scheduled_order(**kwargs)
    set_clock(clock_at)
    order = start_order(scenario["order"]["id"], scenario["rider_user_id"])
    scenario["order"] = order
    scenario["work_order"] = get_work_order(scenario["work_order"]["id"])
    return scenario


def setup_delivered_order(measured_cfs: float = 5.0, measured_hours: float = 10.0,
                          clock_at: str = "2026-06-01T09:00:00Z",
                          **kwargs) -> dict:
    """A fully delivered order: measurement submitted by the rider and
    verified by the district. Order DELIVERED, work order VERIFIED."""
    scenario = setup_flowing_order(clock_at=clock_at, **kwargs)
    work_order = submit_measurement(
        scenario["work_order"]["id"], scenario["rider_user_id"],
        measured_cfs, measured_hours,
    )
    work_order = verify_work_order(work_order["id"])
    scenario["work_order"] = work_order
    scenario["order"] = get_order(scenario["order"]["id"])
    scenario["allocation"] = get_allocation(scenario["allocation"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: billing / delinquency / lien helpers
# ---------------------------------------------------------------------------

def create_invoice(account_id: str, season_id: str) -> dict:
    payload = create_assessment_invoice_payload(account_id, season_id)
    return get_success_data(api_client.create_assessment_invoice(payload, ADMIN))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_assessment_invoice(invoice_id, ADMIN))


def create_issued_invoice(account_id: str, season_id: str,
                          due_date: str = TEST_DEFAULTS["INVOICE_DUE_DATE"]) -> dict:
    invoice = create_invoice(account_id, season_id)
    return get_success_data(
        api_client.issue_invoice(invoice["id"], {"due_date": due_date}, ADMIN)
    )


def run_sweep(season_id: str) -> dict:
    return get_success_data(api_client.run_delinquency_sweep(season_id, ADMIN))


def pay_invoice(invoice_id: str, account_id: str) -> dict:
    """Pay as the owning WaterUser (ownership: X-User-ID == water_account_id)."""
    return get_success_data(
        api_client.pay_invoice(invoice_id, make_water_user_headers(account_id))
    )


def suspend_account_via_lien(
        account_id: str, season_id: str,
        due_date: str = "2026-08-05T00:00:00Z",
        sweep_clock: str = "2026-08-16T00:00:00Z") -> dict:
    """Drive an account to SUSPENDED: issue an invoice, move the clock past
    due + grace, sweep to DELINQUENT, then file the lien (PRD §3.8)."""
    invoice = create_issued_invoice(account_id, season_id, due_date=due_date)
    set_clock(sweep_clock)
    run_sweep(season_id)
    invoice = get_success_data(api_client.file_lien(invoice["id"], ADMIN))
    return invoice


# ---------------------------------------------------------------------------
# Tier 4: transfer helpers
# ---------------------------------------------------------------------------

def create_transfer(source_allocation_id: str, from_account_id: str,
                    to_account_id: str, season_id: str, quantity_af: float) -> dict:
    """Create a transfer as the source-account owner; the source allocation's
    current version is read fresh for the OCC field (PRD §2.6)."""
    allocation = get_allocation(source_allocation_id)
    payload = create_transfer_request_payload(
        from_account_id, to_account_id, season_id, quantity_af,
        expected_source_allocation_version=allocation["version"],
    )
    return get_success_data(
        api_client.create_transfer_request(payload, make_water_user_headers(from_account_id))
    )


def get_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.get_transfer_request(transfer_id, ADMIN))


def post_transfer_full(source_allocation_id: str, from_account_id: str,
                       to_account_id: str, season_id: str,
                       quantity_af: float) -> dict:
    """Create -> approve -> post a transfer. Returns the POSTED transfer."""
    transfer = create_transfer(
        source_allocation_id, from_account_id, to_account_id, season_id, quantity_af,
    )
    transfer = get_success_data(api_client.approve_transfer(transfer["id"], ADMIN))
    return get_success_data(api_client.post_transfer(transfer["id"], ADMIN))


def setup_two_accounts_with_allocations(
        acres_a: float = 5.0, acres_b: float = 1.0,
        priority_a: str = TEST_DEFAULTS["SENIOR_PRIORITY_DATE"],
        priority_b: str = "1890-01-01T00:00:00Z",
        **season_overrides) -> dict:
    """OPEN season + two ACTIVE accounts with their allocations."""
    season = create_open_season(**season_overrides)
    account_a = create_account(holder_name="Alpha A", parcel_number="APN-A",
                               irrigated_acres=acres_a,
                               water_right_priority_date=priority_a)
    account_b = create_account(holder_name="Beta B", parcel_number="APN-B",
                               irrigated_acres=acres_b,
                               water_right_priority_date=priority_b)
    alloc_a = create_allocation(account_a["id"], season["id"])
    alloc_b = create_allocation(account_b["id"], season["id"])
    return {"season": season, "account_a": account_a, "account_b": account_b,
            "alloc_a": alloc_a, "alloc_b": alloc_b}


# ---------------------------------------------------------------------------
# Tier 4: maintenance windows and drought declarations
# ---------------------------------------------------------------------------

def create_window(reach_id: str, start_at: str = "2026-08-10T08:00:00Z",
                  end_at: str = "2026-08-10T14:00:00Z",
                  reason: str = "scheduled maintenance", **overrides) -> dict:
    payload = create_maintenance_window_payload(
        reach_id, start_at=start_at, end_at=end_at, reason=reason, **overrides,
    )
    return get_success_data(api_client.create_maintenance_window(payload, ADMIN))


def get_window(window_id: str) -> dict:
    return get_success_data(api_client.get_maintenance_window(window_id, ADMIN))


def create_drought(season_id: str, stage: str = "STAGE_1") -> dict:
    payload = create_drought_declaration_payload(season_id, stage)
    return get_success_data(api_client.create_drought_declaration(payload, ADMIN))


def get_drought(declaration_id: str) -> dict:
    return get_success_data(api_client.get_drought_declaration(declaration_id, ADMIN))


def effectuate_drought(declaration_id: str) -> dict:
    return get_success_data(api_client.effectuate_drought(declaration_id, ADMIN))
