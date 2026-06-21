"""Payload factories — one per entity, input fields only."""


def create_account_payload(**overrides) -> dict:
    """Account creation. Only holder_name and home_state_code are required."""
    defaults = {
        "holder_name": "Test Holder",
        "home_state_code": "NY",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "plate_number": "TEST123",
        "plate_state_code": "NY",
    }
    defaults.update(overrides)
    return defaults


def create_transponder_payload(account_id: str, serial: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "serial": serial,
    }
    defaults.update(overrides)
    return defaults


def create_transponder_binding_payload(transponder_id: str, vehicle_id: str,
                                       effective_from: str, expected_vehicle_version: int,
                                       **overrides) -> dict:
    defaults = {
        "transponder_id": transponder_id,
        "vehicle_id": vehicle_id,
        "effective_from": effective_from,
        "expected_vehicle_version": expected_vehicle_version,
    }
    defaults.update(overrides)
    return defaults


def create_hov_window_payload(vehicle_id: str, window_from: str, window_to: str,
                              declared_occupants: int, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "window_from": window_from,
        "window_to": window_to,
        "declared_occupants": declared_occupants,
    }
    defaults.update(overrides)
    return defaults


def create_plaza_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Plaza",
        "state_code": "NY",
        "base_rate_cents": 400,
    }
    defaults.update(overrides)
    return defaults


def create_toll_transaction_payload(plaza_id: str, read_method: str, read_at: str,
                                    is_peak: bool, **overrides) -> dict:
    defaults = {
        "plaza_id": plaza_id,
        "read_method": read_method,
        "read_at": read_at,
        "is_peak": is_peak,
    }
    defaults.update(overrides)
    return defaults


def create_reprice_payload(declared_axles: int, is_peak: bool,
                           expected_transaction_version: int, **overrides) -> dict:
    defaults = {
        "declared_axles": declared_axles,
        "is_peak": is_peak,
        "expected_transaction_version": expected_transaction_version,
    }
    defaults.update(overrides)
    return defaults


def create_interop_agency_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Agency",
        "state_code": "NJ",
    }
    defaults.update(overrides)
    return defaults
