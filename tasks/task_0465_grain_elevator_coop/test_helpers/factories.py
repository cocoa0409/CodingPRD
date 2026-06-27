"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def create_commodity_payload(**overrides) -> dict:
    """Commodity input (PRD §3.1). futures_contract_bushels optional (default 5000)."""
    defaults = {
        "symbol": "CORN",
        "test_weight_lbs_per_bushel": 56,
        "base_moisture_pct": 15.0,
        "shrink_pct_per_point": 1.4,
        "drying_cents_per_point_per_bushel": 4,
    }
    defaults.update(overrides)
    return defaults


def create_price_board_payload(commodity_id, **overrides) -> dict:
    """PriceBoard input (PRD §3.1)."""
    defaults = {
        "commodity_id": commodity_id,
        "futures_price": 4.80,
        "cash_basis": -0.10,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    """Member input (PRD §3.1) — only name."""
    defaults = {"name": "Test Farm"}
    defaults.update(overrides)
    return defaults


def create_scale_ticket_payload(member_id, commodity_id, **overrides) -> dict:
    """ScaleTicket input (PRD §3.2). dockage_pct optional (default 0)."""
    defaults = {
        "member_id": member_id,
        "commodity_id": commodity_id,
        "gross_weight_lbs": 72000,
        "tare_weight_lbs": 16000,
        "moisture_pct": 15.0,
        "deposit_account_type": "DELAYED_PRICE",
        "dockage_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_warehouse_receipt_payload(storage_position_id, **overrides) -> dict:
    """WarehouseReceipt input (PRD §3.3)."""
    defaults = {"storage_position_id": storage_position_id}
    defaults.update(overrides)
    return defaults


def create_contract_payload(member_id, commodity_id, **overrides) -> dict:
    """Contract input (PRD §3.4). Legs supplied per contract_type."""
    defaults = {
        "member_id": member_id,
        "commodity_id": commodity_id,
        "contract_type": "CASH",
        "contracted_bushels": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(contract_id, storage_position_id, **overrides) -> dict:
    """Settlement input (PRD §3.5). storage_basis optional (default ACTUAL)."""
    defaults = {
        "contract_id": contract_id,
        "storage_position_id": storage_position_id,
        "priced_bushels": 1000,
        "storage_basis": "ACTUAL",
    }
    defaults.update(overrides)
    return defaults


def create_loadout_bay_payload(**overrides) -> dict:
    """LoadoutBay input (PRD §3.7)."""
    defaults = {"name": "BAY-1"}
    defaults.update(overrides)
    return defaults


def create_dryer_line_payload(**overrides) -> dict:
    """DryerLine input (PRD §3.2). cleanout_buffer_minutes optional (default 30)."""
    defaults = {"name": "DRYER-A", "cleanout_buffer_minutes": 30}
    defaults.update(overrides)
    return defaults


def create_drying_reservation_payload(dryer_line_id, scale_ticket_id, **overrides) -> dict:
    """DryingReservation input (PRD §3.2)."""
    defaults = {
        "dryer_line_id": dryer_line_id,
        "scale_ticket_id": scale_ticket_id,
        "window_start": "2026-02-01T10:00:00Z",
        "window_end": "2026-02-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(commodity_id, storage_position_id, loadout_bay_id, **overrides) -> dict:
    """Shipment input (PRD §3.7)."""
    defaults = {
        "commodity_id": commodity_id,
        "storage_position_id": storage_position_id,
        "loadout_bay_id": loadout_bay_id,
        "bushels": 100,
        "bay_window_start": "2026-02-01T08:00:00Z",
        "bay_window_end": "2026-02-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_hedge_position_payload(commodity_id, **overrides) -> dict:
    """HedgePosition input (PRD §3.8)."""
    defaults = {
        "commodity_id": commodity_id,
        "side": "SHORT",
        "contracts": 3,
        "entry_futures_price": 4.50,
    }
    defaults.update(overrides)
    return defaults


def create_patronage_period_payload(**overrides) -> dict:
    """PatronagePeriod input (PRD §3.9)."""
    defaults = {
        "label": "FY2026",
        "pool_dollars": 100000,
        "qualified_cash_pct": 0.20,
    }
    defaults.update(overrides)
    return defaults
