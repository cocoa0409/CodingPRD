"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_DISTRICT_STATES = {"PROPOSED", "PROTEST_PERIOD", "FORMED", "ABANDONED"}
_PARCEL_STATES = {"ACTIVE", "SUBDIVIDED", "PAID_OFF", "IN_FORECLOSURE", "WITHDRAWN"}
_ROLL_STATES = {"DRAFT", "CONFIRMED", "SUPERSEDED"}
_BOND_STATES = {"AUTHORIZED", "ISSUED", "CALLED", "RETIRED", "DEFAULTED"}
_INSTALLMENT_STATES = {"SCHEDULED", "DUE", "PAID", "DELINQUENT", "DEFAULTED", "CANCELLED"}
_QUOTE_STATES = {"QUOTED", "HONORED", "EXPIRED", "VOIDED"}
_LIEN_STATES = {"RECORDED", "RELEASED", "FORECLOSED"}
_FORECLOSURE_STATES = {"INITIATED", "NOTICED", "JUDGMENT", "SALE", "REDEEMED", "CANCELLED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_district(data: dict):
    _assert_versioned(data)
    assert data["status"] in _DISTRICT_STATES, f"bad district status {data.get('status')!r}"
    assert data["formation_method"] in {"BENEFIT_UNITS", "FRONT_FOOTAGE", "LAND_AREA"}
    assert isinstance(data["total_project_cost_cents"], int)


def assert_parcel(data: dict):
    _assert_versioned(data)
    assert data["status"] in _PARCEL_STATES, f"bad parcel status {data.get('status')!r}"
    assert isinstance(data["assessed_principal_cents"], int)
    assert isinstance(data["remaining_principal_cents"], int)
    assert data["remaining_principal_cents"] >= 0, "remaining_principal_cents must be >= 0"


def assert_roll(data: dict):
    _assert_versioned(data)
    assert data["status"] in _ROLL_STATES, f"bad roll status {data.get('status')!r}"
    assert isinstance(data["total_apportioned_cents"], int)


def assert_bond(data: dict):
    _assert_versioned(data)
    assert data["status"] in _BOND_STATES, f"bad bond status {data.get('status')!r}"


def assert_installment(data: dict):
    _assert_versioned(data)
    assert data["status"] in _INSTALLMENT_STATES, f"bad installment status {data.get('status')!r}"
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["interest_cents"], int)
    assert isinstance(data["amount_due_cents"], int)


def assert_payoff_quote(data: dict):
    _assert_versioned(data)
    assert data["status"] in _QUOTE_STATES, f"bad quote status {data.get('status')!r}"
    assert isinstance(data["total_payoff_cents"], int)


def assert_lien(data: dict):
    _assert_versioned(data)
    assert data["status"] in _LIEN_STATES, f"bad lien status {data.get('status')!r}"
    assert data["lien_type"] in {"ASSESSMENT", "DELINQUENCY"}


def assert_foreclosure(data: dict):
    _assert_versioned(data)
    assert data["status"] in _FORECLOSURE_STATES, f"bad foreclosure status {data.get('status')!r}"


def assert_protest(data: dict):
    # Append-only: id + created_at only, no version / updated_at.
    _assert_common(data)
    assert "version" not in data, "ProtestFiling is append-only and must not carry version"
    assert "updated_at" not in data, "ProtestFiling is append-only and must not carry updated_at"


def assert_payment(data: dict):
    # Append-only: id + created_at only, no version / updated_at.
    _assert_common(data)
    assert "version" not in data, "Payment is append-only and must not carry version"
    assert "updated_at" not in data, "Payment is append-only and must not carry updated_at"
    assert isinstance(data["amount_cents"], int)
