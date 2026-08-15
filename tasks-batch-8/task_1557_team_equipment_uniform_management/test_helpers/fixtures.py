"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All three roles are opaque identities, so the
shared header constants are used for every call.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_SEASON
from .factories import (
    create_damage_claim_payload,
    create_disposition_case_payload,
    create_game_event_payload,
    create_gear_item_payload,
    create_inventory_pool_payload,
    create_kit_assignment_payload,
    create_kit_order_payload,
    create_player_payload,
    create_reconditioning_job_payload,
    create_supplier_contract_payload,
)
from .test_users import TEST_USERS

EM = TEST_USERS["equipment_manager_headers"]
TA = TEST_USERS["team_admin_headers"]
LV = TEST_USERS["laundry_vendor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_player(full_name="Test Player", position_group="OFFENSE"):
    """Create a roster player (born ACTIVE). Returns the player."""
    return get_success_data(api_client.create_player(
        create_player_payload(full_name=full_name, position_group=position_group), EM))


def create_pool(season_label=DEFAULT_SEASON, garment_type="GAME_JERSEY", size_code="M",
                stock_on_hand=5, reorder_point=0, reorder_batch_size=1):
    """Create an inventory pool (born ACTIVE, counters zeroed). Returns the pool."""
    return get_success_data(api_client.create_inventory_pool(
        create_inventory_pool_payload(
            season_label=season_label, garment_type=garment_type, size_code=size_code,
            stock_on_hand=stock_on_hand, reorder_point=reorder_point,
            reorder_batch_size=reorder_batch_size), EM))


def create_jersey_and_pants_pools(season_label=DEFAULT_SEASON, jersey_stock=5,
                                  pants_stock=5, jersey_size="M", pants_size="34",
                                  jersey_reorder_point=0, jersey_reorder_batch_size=1):
    """Create the jersey/pants pool pair a kit reservation draws on.
    Returns (jersey_pool, pants_pool)."""
    jersey = create_pool(season_label=season_label, garment_type="GAME_JERSEY",
                         size_code=jersey_size, stock_on_hand=jersey_stock,
                         reorder_point=jersey_reorder_point,
                         reorder_batch_size=jersey_reorder_batch_size)
    pants = create_pool(season_label=season_label, garment_type="GAME_PANTS",
                        size_code=pants_size, stock_on_hand=pants_stock)
    return jersey, pants


def create_contract(vendor_name="Test Vendor", season_label=DEFAULT_SEASON,
                    allocation_caps=None, default_lead_time_days=30,
                    contract_rebate_pct=None):
    """Create a DRAFT supplier contract. Returns the contract."""
    payload = create_supplier_contract_payload(
        vendor_name=vendor_name, season_label=season_label,
        allocation_caps=allocation_caps
        or [{"garment_type": "GAME_JERSEY", "max_units": 50}],
        default_lead_time_days=default_lead_time_days,
    )
    if contract_rebate_pct is not None:
        payload["contract_rebate_pct"] = contract_rebate_pct
    return get_success_data(api_client.create_supplier_contract(payload, TA))


def create_active_contract(**kwargs):
    """Create a contract and activate it. Returns the ACTIVE contract."""
    contract = create_contract(**kwargs)
    return get_success_data(api_client.activate_supplier_contract(contract["id"], TA))


def create_gear(asset_tag="TAG-0001", item_type="HELMET", size_spec="HELMET-L",
                acquired_on="2025-01-01", certification_expires_on="2028-01-01T00:00:00Z",
                condition_grade=None):
    """Register a gear item (born IN_STOCK). Returns the gear item."""
    payload = create_gear_item_payload(
        asset_tag=asset_tag, item_type=item_type, size_spec=size_spec,
        acquired_on=acquired_on)
    if certification_expires_on is not None:
        payload["certification_expires_on"] = certification_expires_on
    if condition_grade is not None:
        payload["condition_grade"] = condition_grade
    return get_success_data(api_client.create_gear_item(payload, EM))


def issue_gear(gear_id, player_id):
    """Issue an IN_STOCK gear item to an ACTIVE player. Returns the item."""
    return get_success_data(
        api_client.issue_gear_item(gear_id, {"player_id": player_id}, EM))


def setup_player_with_issued_gear(asset_tag="HLM-1001", item_type="HELMET",
                                  size_spec="HELMET-L", acquired_on="2025-01-01",
                                  certification_expires_on="2028-01-01T00:00:00Z",
                                  condition_grade=None, player_name="Gear Player"):
    """ACTIVE player + gear item issued to them. Returns (player, gear)."""
    player = create_player(full_name=player_name)
    gear = create_gear(asset_tag=asset_tag, item_type=item_type, size_spec=size_spec,
                       acquired_on=acquired_on,
                       certification_expires_on=certification_expires_on,
                       condition_grade=condition_grade)
    gear = issue_gear(gear["id"], player["id"])
    return player, gear


# ---------------------------------------------------------------------------
# Tier 2: kit reservations
# ---------------------------------------------------------------------------

def create_reserved_kit(player_id, jersey_pool_id, pants_pool_id, jersey_number=1,
                        season_label=DEFAULT_SEASON):
    """Reserve a numbered kit (born RESERVED). Returns the kit assignment."""
    return get_success_data(api_client.create_kit_assignment(
        create_kit_assignment_payload(
            player_id, jersey_pool_id, pants_pool_id,
            jersey_number=jersey_number, season_label=season_label), EM))


def setup_reserved_kit(jersey_number=1, season_label=DEFAULT_SEASON, jersey_stock=5,
                       pants_stock=5, jersey_size="M", pants_size="34",
                       jersey_reorder_point=0, jersey_reorder_batch_size=1,
                       player_name="Kit Player"):
    """Player + jersey/pants pools + one RESERVED kit.

    Returns a dict: player, jersey_pool, pants_pool, kit."""
    jersey, pants = create_jersey_and_pants_pools(
        season_label=season_label, jersey_stock=jersey_stock, pants_stock=pants_stock,
        jersey_size=jersey_size, pants_size=pants_size,
        jersey_reorder_point=jersey_reorder_point,
        jersey_reorder_batch_size=jersey_reorder_batch_size)
    player = create_player(full_name=player_name)
    kit = create_reserved_kit(player["id"], jersey["id"], pants["id"],
                              jersey_number=jersey_number, season_label=season_label)
    return {"player": player, "jersey_pool": jersey, "pants_pool": pants, "kit": kit}


def setup_issued_kit(**kwargs):
    """setup_reserved_kit + issue. The workspace's kit is ISSUED."""
    ws = setup_reserved_kit(**kwargs)
    ws["kit"] = get_success_data(api_client.issue_kit_assignment(ws["kit"]["id"], EM))
    return ws


def create_reconditioning_job(item_id, provider_name="RCOA", sent_on="2026-08-01"):
    """Send an IN_STOCK gear item out for reconditioning (job born OUT;
    the item moves to OUT_FOR_RECONDITIONING). Returns the job."""
    return get_success_data(api_client.create_reconditioning_job(
        create_reconditioning_job_payload(
            item_id, provider_name=provider_name, sent_on=sent_on), EM))


# ---------------------------------------------------------------------------
# Tier 3: kit orders
# ---------------------------------------------------------------------------

def create_kit_order(contract_id, lines=None, quantity=1, garment_type="GAME_JERSEY",
                     size_code="M", unit_price_cents=5000):
    """Create and submit a MANUAL kit order. Returns the SUBMITTED order."""
    if lines is None:
        lines = [{"garment_type": garment_type, "size_code": size_code,
                  "quantity": quantity, "unit_price_cents": unit_price_cents}]
    return get_success_data(api_client.create_kit_order(
        create_kit_order_payload(contract_id, lines=lines), EM))


def setup_active_contract_with_pool(vendor_name="Test Vendor", cap=50, lead_days=30,
                                    season_label=DEFAULT_SEASON, pool_stock=10,
                                    garment_type="GAME_JERSEY", size_code="M",
                                    rebate=None, extra_caps=None):
    """Pool + ACTIVE contract covering the pool's garment type.

    Returns a dict: pool, contract."""
    pool = create_pool(season_label=season_label, garment_type=garment_type,
                       size_code=size_code, stock_on_hand=pool_stock)
    caps = [{"garment_type": garment_type, "max_units": cap}]
    if extra_caps:
        caps = caps + extra_caps
    contract = create_active_contract(
        vendor_name=vendor_name, season_label=season_label, allocation_caps=caps,
        default_lead_time_days=lead_days, contract_rebate_pct=rebate)
    return {"pool": pool, "contract": contract}


# ---------------------------------------------------------------------------
# Tier 4: game events and laundry
# ---------------------------------------------------------------------------

def create_event(season_label=DEFAULT_SEASON, opponent_name="Tigers",
                 kickoff_at="2026-09-05T15:00:00Z", designated_kit="HOME",
                 checklist=None):
    """Schedule a game event (born SCHEDULED, laundry NOT_STARTED)."""
    payload = create_game_event_payload(
        season_label=season_label, opponent_name=opponent_name,
        kickoff_at=kickoff_at, designated_kit=designated_kit)
    if checklist is not None:
        payload["checklist"] = checklist
    return get_success_data(api_client.create_game_event(payload, EM))


def setup_locked_event(kickoff_at="2026-09-05T15:00:00Z", designated_kit="HOME",
                       season_label=DEFAULT_SEASON, checklist=None,
 opponent_name="Tigers"):
    """Create an event, work off any checklist items, and lock the kit.
    Returns the KIT_LOCKED event."""
    event = create_event(season_label=season_label, opponent_name=opponent_name,
                         kickoff_at=kickoff_at, designated_kit=designated_kit,
                         checklist=checklist)
    for item in (checklist or []):
        get_success_data(api_client.complete_checklist_item(
            event["id"], item["item_ref"], {"outcome": "DONE"}, EM))
    return get_success_data(api_client.lock_game_event_kit(event["id"], EM))


def setup_completed_event_with_load(pool_id, quantity=1,
                                    kickoff_at="2026-09-05T15:00:00Z",
                                    season_label=DEFAULT_SEASON):
    """Event completed with a one-line laundry load; laundry sits COLLECTING.
    Returns the COMPLETED event."""
    event = setup_locked_event(kickoff_at=kickoff_at, season_label=season_label)
    return get_success_data(api_client.complete_game_event(
        event["id"], {"laundry_load": [{"pool_id": pool_id, "quantity": quantity}]}, EM))


# ---------------------------------------------------------------------------
# Tier 5: damage claims
# ---------------------------------------------------------------------------

def create_claim(player_id, claim_type="DAMAGED", base_value_cents=10000,
                 gear_item_id=None, kit_assignment_id=None, description=None):
    """Report a damage claim (born REPORTED with a provisional fee)."""
    payload = create_damage_claim_payload(
        player_id, claim_type=claim_type, base_value_cents=base_value_cents)
    if gear_item_id is not None:
        payload["gear_item_id"] = gear_item_id
    if kit_assignment_id is not None:
        payload["kit_assignment_id"] = kit_assignment_id
    if description is not None:
        payload["description"] = description
    return get_success_data(api_client.create_damage_claim(payload, EM))


def setup_assessed_gear_claim(claim_type="DAMAGED", base_value_cents=10000,
                              grade="B", asset_tag="HLM-2001",
                              acquired_on="2025-01-01",
                              certification_expires_on="2028-01-01T00:00:00Z"):
    """Player + issued helmet + claim + assessment. Returns (player, gear, claim)."""
    player, gear = setup_player_with_issued_gear(
        asset_tag=asset_tag, acquired_on=acquired_on,
        certification_expires_on=certification_expires_on)
    claim = create_claim(player["id"], claim_type=claim_type,
                         base_value_cents=base_value_cents, gear_item_id=gear["id"])
    claim = get_success_data(api_client.assess_damage_claim(
        claim["id"], {"condition_grade": grade}, EM))
    return player, gear, claim


# ---------------------------------------------------------------------------
# Tier 6: disposition cases
# ---------------------------------------------------------------------------

def create_disposition(season_label=DEFAULT_SEASON, garment_type="GAME_JERSEY",
                       method="DONATE", size_code=None, unit_price_cents=None):
    """Propose a disposition case (born PROPOSED). Returns the case."""
    payload = create_disposition_case_payload(
        season_label=season_label, garment_type=garment_type, method=method)
    if size_code is not None:
        payload["size_code"] = size_code
    if unit_price_cents is not None:
        payload["unit_price_cents"] = unit_price_cents
    return get_success_data(api_client.create_disposition_case(payload, EM))


def create_approved_disposition(**kwargs):
    """Propose + approve. Returns the APPROVED case."""
    case = create_disposition(**kwargs)
    return get_success_data(api_client.approve_disposition_case(case["id"], TA))


# ---------------------------------------------------------------------------
# Refresh helpers
# ---------------------------------------------------------------------------

def get_player(player_id):
    return get_success_data(api_client.get_player(player_id, EM))


def get_pool(pool_id):
    return get_success_data(api_client.get_inventory_pool(pool_id, EM))


def get_contract(contract_id):
    return get_success_data(api_client.get_supplier_contract(contract_id, EM))


def get_order(order_id):
    return get_success_data(api_client.get_kit_order(order_id, EM))


def get_kit(kit_id):
    return get_success_data(api_client.get_kit_assignment(kit_id, EM))


def get_gear(gear_id):
    return get_success_data(api_client.get_gear_item(gear_id, EM))


def get_job(job_id):
    return get_success_data(api_client.get_reconditioning_job(job_id, EM))


def get_event(event_id):
    return get_success_data(api_client.get_game_event(event_id, EM))


def get_claim(claim_id):
    return get_success_data(api_client.get_damage_claim(claim_id, EM))


def get_case(case_id):
    return get_success_data(api_client.get_disposition_case(case_id, EM))
