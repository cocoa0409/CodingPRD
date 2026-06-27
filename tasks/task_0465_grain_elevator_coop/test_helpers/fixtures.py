"""Composite setup helpers.

Each fixture builds preconditions from scratch using only PRD-declared endpoints,
because the harness restarts the server (empty DB) before every test. Fixtures use
get_success_data() (lenient) internally so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as f

MERCH = TEST_USERS["merchandiser_headers"]
CLERK = TEST_USERS["grade_clerk_headers"]
OFFICER = TEST_USERS["settlement_officer_headers"]
SHIPPER = TEST_USERS["shipping_clerk_headers"]
RISK = TEST_USERS["risk_manager_headers"]


# --- Logical clock ---------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the server logical clock (Merchandiser-only, PRD §2.9)."""
    return get_success_data(api_client.set_clock(to_iso8601, MERCH))


def reset_clock_default():
    return set_clock("2026-01-01T00:00:00Z")


# --- Reference data --------------------------------------------------------

def create_commodity(**overrides):
    """Create a commodity (defaults to CORN reference standards)."""
    return get_success_data(api_client.create_commodity(f.create_commodity_payload(**overrides), MERCH))


def create_wheat_commodity(**overrides):
    payload = {
        "symbol": "WHEAT",
        "test_weight_lbs_per_bushel": 60,
        "base_moisture_pct": 13.5,
        "shrink_pct_per_point": 1.2,
        "drying_cents_per_point_per_bushel": 3,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_commodity(payload, MERCH))


def create_member(name="Test Farm", **overrides):
    return get_success_data(api_client.create_member(f.create_member_payload(name=name, **overrides), MERCH))


def create_price_board(commodity_id, futures_price=4.80, cash_basis=-0.10):
    return get_success_data(
        api_client.create_price_board(
            f.create_price_board_payload(commodity_id, futures_price=futures_price, cash_basis=cash_basis),
            MERCH,
        )
    )


def create_loadout_bay(name="BAY-1"):
    return get_success_data(api_client.create_loadout_bay(f.create_loadout_bay_payload(name=name), MERCH))


def create_dryer_line(name="DRYER-A", cleanout_buffer_minutes=30):
    return get_success_data(
        api_client.create_dryer_line(
            f.create_dryer_line_payload(name=name, cleanout_buffer_minutes=cleanout_buffer_minutes), MERCH
        )
    )


# --- Scale tickets & storage positions ------------------------------------

def create_weighed_ticket(member_id, commodity_id, **overrides):
    """Create a WEIGHED scale ticket."""
    return get_success_data(
        api_client.create_scale_ticket(
            f.create_scale_ticket_payload(member_id, commodity_id, **overrides), CLERK
        )
    )


def grade_ticket(ticket_id):
    """Grade a WEIGHED ticket -> GRADED, creating its StoragePosition."""
    return get_success_data(api_client.grade_scale_ticket(ticket_id, CLERK))


def create_graded_position(commodity_id=None, member_id=None,
                           deposit_account_type="DELAYED_PRICE",
                           gross_weight_lbs=72000, tare_weight_lbs=16000,
                           moisture_pct=15.0, dockage_pct=0, member_name="Pos Farm"):
    """Create commodity (if needed) + member (if needed) + a graded clean position.

    Returns (commodity, member, ticket, position). With the default 72000/16000
    clean corn load this yields exactly 1000.0000 net_dry_bushels.
    """
    commodity = create_commodity() if commodity_id is None else {"id": commodity_id}
    cid = commodity["id"]
    member = create_member(name=member_name) if member_id is None else {"id": member_id}
    mid = member["id"]
    ticket = create_weighed_ticket(
        mid, cid,
        deposit_account_type=deposit_account_type,
        gross_weight_lbs=gross_weight_lbs, tare_weight_lbs=tare_weight_lbs,
        moisture_pct=moisture_pct, dockage_pct=dockage_pct,
    )
    graded = grade_ticket(ticket["id"])
    position = get_success_data(
        api_client.get_storage_position(graded["storage_position_id"], OFFICER)
    )
    return commodity, member, graded, position


def issue_warehouse_receipt(storage_position_id):
    return get_success_data(
        api_client.create_warehouse_receipt(
            f.create_warehouse_receipt_payload(storage_position_id), MERCH
        )
    )


# --- Contracts -------------------------------------------------------------

def create_open_cash_contract(member_id, commodity_id, contracted_bushels=1000):
    """Create an OPEN CASH contract (no legs at create)."""
    return get_success_data(
        api_client.create_contract(
            f.create_contract_payload(
                member_id, commodity_id, contract_type="CASH", contracted_bushels=contracted_bushels
            ),
            MERCH,
        )
    )


def create_priced_cash_contract(member_id, commodity_id, contracted_bushels=1000):
    """Create + fix a CASH contract from the current board -> PRICED.

    Requires a current PriceBoard to already exist for the commodity.
    """
    contract = create_open_cash_contract(member_id, commodity_id, contracted_bushels)
    return get_success_data(api_client.fix_price(contract["id"], MERCH))


def create_contract(member_id, commodity_id, contract_type, contracted_bushels=1000, **legs):
    """Create a contract of an arbitrary type with explicit legs."""
    return get_success_data(
        api_client.create_contract(
            f.create_contract_payload(
                member_id, commodity_id,
                contract_type=contract_type, contracted_bushels=contracted_bushels, **legs
            ),
            MERCH,
        )
    )


# --- Settlements -----------------------------------------------------------

def create_draft_settlement(contract_id, storage_position_id, priced_bushels=1000, storage_basis="ACTUAL"):
    return get_success_data(
        api_client.create_settlement(
            f.create_settlement_payload(
                contract_id, storage_position_id,
                priced_bushels=priced_bushels, storage_basis=storage_basis,
            ),
            OFFICER,
        )
    )


def post_settlement(settlement_id, storage_position_id):
    """Post a DRAFT settlement, reading the position's current version for the OCC guard."""
    pos = get_success_data(api_client.get_storage_position(storage_position_id, OFFICER))
    return get_success_data(
        api_client.post_settlement(
            settlement_id, {"expected_storage_position_version": pos["version"]}, OFFICER
        )
    )


def settle_member_bushels(commodity_id, member_id, priced_bushels=1000, member_name="Settle Farm"):
    """Grade a clean position for member, draft + post a full CASH settlement so the
    member accrues net_priced_bushels == priced_bushels. Requires a current board.

    Returns (position, contract, settlement).
    """
    _, _, _graded, position = create_graded_position(
        commodity_id=commodity_id, member_id=member_id, member_name=member_name
    )
    contract = create_priced_cash_contract(member_id, commodity_id, contracted_bushels=priced_bushels)
    settlement = create_draft_settlement(
        contract["id"], position["id"], priced_bushels=priced_bushels
    )
    settled = post_settlement(settlement["id"], position["id"])
    return position, contract, settled


def make_member_with_priced_bushels(commodity_id, name, bushels=1000):
    """Create a member and drive net_priced_bushels to `bushels` via a full settlement.
    Returns the member dict (re-read after settlement so ledger fields are fresh)."""
    member = create_member(name=name)
    settle_member_bushels(commodity_id, member["id"], priced_bushels=bushels, member_name=name)
    return get_success_data(api_client.get_member(member["id"], MERCH))


# --- Hedge positions -------------------------------------------------------

def open_hedge(commodity_id, side="SHORT", contracts=3, entry_futures_price=4.50):
    return get_success_data(
        api_client.create_hedge_position(
            f.create_hedge_position_payload(
                commodity_id, side=side, contracts=contracts, entry_futures_price=entry_futures_price
            ),
            RISK,
        )
    )


def open_hedge_in_margin_call(commodity_id=None, contracts=3, entry_futures_price=4.50,
                              mark_futures_price=4.80):
    """Open a SHORT hedge and mark it into MARGIN_CALL.

    Returns (hedge, marked) where marked is the post-mark MARGIN_CALL state.
    """
    cid = create_commodity()["id"] if commodity_id is None else commodity_id
    hedge = open_hedge(cid, side="SHORT", contracts=contracts, entry_futures_price=entry_futures_price)
    marked = get_success_data(
        api_client.mark_hedge_position(hedge["id"], {"mark_futures_price": mark_futures_price}, RISK)
    )
    return hedge, marked


def meet_call(position_id, deposit_dollars):
    """Meet a margin call, reading the hedge's current version for the OCC guard."""
    hp = get_success_data(api_client.get_hedge_position(position_id, RISK))
    return get_success_data(
        api_client.meet_call(
            position_id,
            {"deposit_dollars": deposit_dollars, "expected_hedge_position_version": hp["version"]},
            RISK,
        )
    )


# --- Shipments -------------------------------------------------------------

def schedule_shipment(commodity_id, storage_position_id, loadout_bay_id, bushels=100,
                      bay_window_start="2026-02-01T08:00:00Z", bay_window_end="2026-02-01T10:00:00Z"):
    return get_success_data(
        api_client.create_shipment(
            f.create_shipment_payload(
                commodity_id, storage_position_id, loadout_bay_id,
                bushels=bushels, bay_window_start=bay_window_start, bay_window_end=bay_window_end,
            ),
            SHIPPER,
        )
    )


def load_shipment(shipment_id):
    return get_success_data(api_client.load_shipment(shipment_id, SHIPPER))


# --- Patronage -------------------------------------------------------------

def open_patronage_period(label="FY2026", pool_dollars=100000, qualified_cash_pct=0.20):
    return get_success_data(
        api_client.create_patronage_period(
            f.create_patronage_period_payload(
                label=label, pool_dollars=pool_dollars, qualified_cash_pct=qualified_cash_pct
            ),
            MERCH,
        )
    )
