"""Customers and the foam material catalogue: creation defaults, round-trip
retrieval, server-minted system fields, and body well-formedness."""
from test_helpers import (
    PLANT,
    SALES,
    ApiErrorId,
    assert_customer,
    assert_material,
    create_material_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
)


def test_customer_creation_applies_defaults(api):
    """PRD §3.1: "A `SalesEngineer` onboards a customer by supplying a `name`,
    an `account_tier` of either `STANDARD` or `CONTRACT`, and optionally
    `branding_required`, which records whether kits ship with customer
    branding applied and defaults to false when omitted." PRD §3.1: "A new
    customer's `credit_balance_cents` starts at 0 and grows only through the
    scrap-recycling credits of §3.7." PRD §2.4: "`id` (string): a unique,
    server-minted identifier formatted as a UUID, with no type prefix."

    Design: Corner/entities/customer_creation_applies_defaults
    """
    resp = api.create_customer(
        {"name": "Acme Widgets", "account_tier": "STANDARD"}, SALES,
    )
    customer = validate_success(resp, 201)
    assert_customer(customer)
    assert customer["branding_required"] is False, (
        "omitted branding_required must default to false"
    )
    assert customer["credit_balance_cents"] == 0, (
        "a new customer's scrap-credit balance starts at 0"
    )
    assert is_valid_uuid(customer["id"]), "id must be a server-minted UUID"
    assert isinstance(customer["version"], int), "version must be an integer"


def test_material_creation_and_retrieval_round_trip(api):
    """PRD §3.1: "A `PlantManager` registers each foam material with its
    `foam_family` — one of `PE`, `EPE`, `PU`, or `XLPE` — its `density_pcf`
    in pounds per cubic foot, and its `ild_lb_25`, the Indentation Load
    Deflection at 25% compression in pounds." PRD §2.2: "Unless otherwise
    noted, operations that create or modify a resource will return the
    created or updated resource object in the data field."

    Design: Corner/entities/material_creation_and_retrieval_round_trip
    """
    payload = create_material_payload(
        foam_family="XLPE", density_pcf=2.2, ild_lb_25=90, sheet_thickness_in=3,
        cost_per_board_ft_cents=310, scrap_credit_per_lb_cents=14,
    )
    created = validate_success(api.create_material(payload, PLANT), 201)
    assert_material(created)
    assert created["foam_family"] == "XLPE"
    assert created["ild_lb_25"] == 90
    assert created["cost_per_board_ft_cents"] == 310

    fetched = validate_success(api.get_material(created["id"], SALES))
    assert_material(fetched)
    assert fetched["foam_family"] == "XLPE"
    assert fetched["ild_lb_25"] == 90
    assert fetched["cost_per_board_ft_cents"] == 310
    assert fetched["density_pcf"] == 2.2
    assert fetched["scrap_credit_per_lb_cents"] == 14


def test_material_system_fields_input_ignored(api):
    """PRD §2.4: "`id` (string): a unique, server-minted identifier formatted
    as a UUID, with no type prefix." PRD §2.4: "`version` (integer): a
    system-managed integer that increments with every modification to the
    resource."

    Design: Corner/entities/material_system_fields_input_ignored
    """
    supplied_id = "11111111-1111-4111-8111-111111111111"
    payload = create_material_payload(id=supplied_id, version=99)
    created = validate_success(api.create_material(payload, PLANT), 201)
    assert_material(created)
    assert created["id"] != supplied_id, (
        "the server must mint its own id, not honor the client-supplied one"
    )
    assert is_valid_uuid(created["id"])
    assert created["version"] != 99, (
        "version is system-managed; the client-supplied 99 must be ignored"
    )


def test_customer_create_invalid_enum_returns_400(api):
    """PRD §2.5: "Required fields must be present, enum values must be valid,
    and numeric ranges must be sane — quantities positive, `contamination_pct`
    between 0 and 100 inclusive — otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "an `account_tier` of either `STANDARD` or `CONTRACT`".

    Design: Corner/validations/customer_create_invalid_enum_returns_400
    """
    resp = api.create_customer({"name": "Gold Corp", "account_tier": "GOLD"}, SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
