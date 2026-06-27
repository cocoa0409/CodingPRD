"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_serial_counter = itertools.count(1)


def unique_serial(prefix: str = "SN") -> str:
    """Generate a process-unique ATM serial so duplicate-serial isn't accidentally triggered."""
    return f"{prefix}-{next(_serial_counter)}"


def create_site_merchant_payload(**overrides) -> dict:
    """SiteMerchant: legal_name, commission_pct_bps, commission_flat_per_wd_cents,
    commission_monthly_ceiling_cents, commission_basis? (defaults GREATER_OF)."""
    defaults = {
        "legal_name": "Downtown Deli",
        "commission_pct_bps": 1500,
        "commission_flat_per_wd_cents": 30,
        "commission_monthly_ceiling_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


def create_vault_payload(**overrides) -> dict:
    """Vault: name, provisioned_cents."""
    defaults = {
        "name": "Main Vault",
        "provisioned_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(vault_id, **overrides) -> dict:
    """ArmoredRoute: carrier_name, vault_id."""
    defaults = {
        "carrier_name": "Acme Armored",
        "vault_id": vault_id,
    }
    defaults.update(overrides)
    return defaults


def create_location_payload(site_merchant_id, route_id, **overrides) -> dict:
    """Location: name, jurisdiction_code, site_merchant_id, route_id, address."""
    defaults = {
        "name": "Site 1",
        "jurisdiction_code": "CA",
        "site_merchant_id": site_merchant_id,
        "route_id": route_id,
        "address": "1 Main St",
    }
    defaults.update(overrides)
    return defaults


def create_atm_payload(location_id, **overrides) -> dict:
    """ATM: serial_no, location_id, surcharge_cents, note_denomination_cents? (defaults 2000)."""
    defaults = {
        "serial_no": unique_serial(),
        "location_id": location_id,
        "surcharge_cents": 250,
    }
    defaults.update(overrides)
    return defaults


def create_cassette_payload(**overrides) -> dict:
    """Cassette: position (C1|C2|C3|C4)."""
    defaults = {"position": "C1"}
    defaults.update(overrides)
    return defaults


def create_transaction_payload(kind="WITHDRAWAL", **overrides) -> dict:
    """Transaction: kind, amount_cents? (for WITHDRAWAL)."""
    defaults = {"kind": kind}
    if kind == "WITHDRAWAL" and "amount_cents" not in overrides:
        defaults["amount_cents"] = 2000
    defaults.update(overrides)
    return defaults


def create_replenishment_order_payload(atm_id, route_id, **overrides) -> dict:
    """ReplenishmentOrder: atm_id, route_id, order_amount_cents,
    service_window_start, service_window_end, forecast_basis? (defaults FORWARD)."""
    defaults = {
        "atm_id": atm_id,
        "route_id": route_id,
        "order_amount_cents": 200_000,
        "service_window_start": "2026-01-05T08:00:00Z",
        "service_window_end": "2026-01-05T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_cash_count_payload(counted_cents, **overrides) -> dict:
    """CashCount: counted_cents, tolerance_cents? (defaults 500)."""
    defaults = {"counted_cents": counted_cents}
    defaults.update(overrides)
    return defaults


def create_service_ticket_payload(atm_id, fault_kind="CASH_JAM", **overrides) -> dict:
    """ServiceTicket: atm_id, fault_kind, severity? (defaults MINOR)."""
    defaults = {
        "atm_id": atm_id,
        "fault_kind": fault_kind,
    }
    defaults.update(overrides)
    return defaults


def create_fee_disclosure_payload(disclosed_surcharge_cents, **overrides) -> dict:
    """FeeDisclosure: disclosed_surcharge_cents, ack_text_present? (defaults false)."""
    defaults = {"disclosed_surcharge_cents": disclosed_surcharge_cents}
    defaults.update(overrides)
    return defaults


def create_settlement_run_payload(atm_id, **overrides) -> dict:
    """SettlementRun: atm_id, window_start, window_end."""
    defaults = {
        "atm_id": atm_id,
        "window_start": "2026-01-01T00:00:00Z",
        "window_end": "2026-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
