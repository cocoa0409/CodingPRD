"""CRUD basics, system-field minting, defaults, immutability, listings, and
FK-reverse computed reads.

Covers the corner entities and endpoints instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_yard, setup_returned_pending_inspection, inspect,
    create_rate_card_payload, create_catalog_item_payload,
    create_equipment_unit_payload, TEST_USERS,
)

YM = TEST_USERS["yard_manager_headers"]
AGENT = TEST_USERS["rental_agent_headers"]


# ─── corner: entities ─────────────────────────────────────────────

def test_create_rate_card_returns_201_with_fields(api):
    """PRD §3.1: "A newly created card is born active — its active flag is true".
    PRD §2.4: "The version field is an integer that starts at 1 on creation and
    increments by exactly one on every mutation."

    Design: Corner/entities/create_rate_card_returns_201_with_all_fields
    """
    rc = validate_success(
        api.create_rate_card(create_rate_card_payload(), YM), 201)
    assert rc["daily_rate_cents"] == 4000
    assert rc["version"] == 1
    assert rc["active"] is True


def test_get_equipment_unit_not_found(api):
    """PRD §2.5: "the server validates existence ... and rejects the first missing
    reference with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_equipment_unit_not_found_returns_404
    """
    res = api.get_equipment_unit("00000000-0000-4000-8000-000000000000", YM)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_catalog_item_missing_category_returns_400(api):
    """PRD §3.1: "If a creation request omits a required field, supplies a bad
    type, or names an invalid category, it is rejected with ERR_INVALID_REQUEST
    (HTTP 400)".

    Design: Corner/entities/create_catalog_item_missing_required_field_returns_400
    """
    rc = validate_success(
        api.create_rate_card(create_rate_card_payload(), YM), 201)
    res = api.create_catalog_item({
        "rate_card_id": rc["id"], "sku": "MX15",
        "name": "Mini Excavator", "fuel_capacity_liters": 40,
    }, YM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_catalog_item_invalid_category_returns_400(api):
    """PRD §3.1: "If a creation request omits a required field, supplies a bad
    type, or names an invalid category, it is rejected with ERR_INVALID_REQUEST
    (HTTP 400)".

    Design: Corner/entities/create_catalog_item_invalid_enum_category_returns_400
    """
    rc = validate_success(
        api.create_rate_card(create_rate_card_payload(), YM), 201)
    res = api.create_catalog_item(
        create_catalog_item_payload(rc["id"], category="SPACESHIP"), YM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_duplicate_asset_tag_returns_409(api):
    """PRD §3.2: "A duplicate asset_tag is rejected with ERR_DUPLICATE_KEY
    (HTTP 409)."

    Design: Corner/entities/create_equipment_unit_duplicate_asset_tag_returns_409
    """
    ctx = setup_yard()  # already registers one unit with asset_tag EU-1
    res = api.create_equipment_unit(
        create_equipment_unit_payload(ctx["item"]["id"], asset_tag="EU-1"), YM)
    validate_error(res, "ERR_DUPLICATE_KEY")


def test_catalog_item_requires_delivery_default_false(api):
    """PRD §3.1: "The optional requires_delivery flag (default false) marks
    equipment that cannot leave by counter pickup."

    Design: Corner/entities/catalog_item_requires_delivery_default_false
    """
    rc = validate_success(
        api.create_rate_card(create_rate_card_payload(), YM), 201)
    item = validate_success(api.create_catalog_item({
        "rate_card_id": rc["id"], "sku": "MX15", "name": "Mini Excavator",
        "category": "POWER_TOOL", "fuel_capacity_liters": 0,
    }, YM), 201)
    assert item["requires_delivery"] is False


def test_equipment_unit_system_fields_minted(api):
    """PRD §3.2: "A freshly registered unit is AVAILABLE, with fuel_level_liters at
    0 and lifetime_rental_days at 0."
    PRD §2.4: "The version field is an integer that starts at 1 on creation".

    Design: Corner/entities/equipment_unit_id_system_minted_input_ignored
    """
    ctx = setup_yard()
    unit = validate_success(api.create_equipment_unit(
        create_equipment_unit_payload(ctx["item"]["id"], asset_tag="EU-NEW"), YM), 201)
    assert unit["availability_state"] == "AVAILABLE"
    assert unit["lifetime_rental_days"] == 0
    assert unit["version"] == 1


def test_damage_charge_has_no_version_field(api):
    """PRD §2.4: "Three entities are append-only or singleton records and therefore
    carry only id and created_at ... These are the DamageCharge (an immutable record
    of an assessed damage), the AccountLedgerEntry (an append-only ledger line), and
    the YardClock (the singleton simulated clock). For these three, neither
    updated_at nor version is present on the persisted row or in the response."

    Design: Corner/entities/damage_charge_immutable_no_version_field
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    inspect(ctx["agreement"]["id"], return_fuel_level_liters=40,
            cleanliness="CLEAN", damage_assessed_cents=9000)
    data, _ = validate_paginated(api.list_damage_charges(YM))
    assert len(data) == 1
    charge = data[0]
    assert "version" not in charge
    assert "updated_at" not in charge


def test_list_rate_cards_paginated_envelope(api):
    """PRD §2.3: "Every list response includes limit, offset, total_count, and
    has_more in the meta object of the envelope."

    Design: Corner/entities/list_rate_cards_paginated_envelope
    """
    validate_success(api.create_rate_card(
        create_rate_card_payload(name="A"), YM), 201)
    validate_success(api.create_rate_card(
        create_rate_card_payload(name="B", daily_rate_cents=5000), YM), 201)
    data, meta = validate_paginated(
        api.list_rate_cards(YM, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ─── corner: endpoints (computed reads / reverse reachability) ────

def test_list_units_by_catalog_item(api):
    """PRD §3.7: "equipment units by catalog_item_id or availability_state".

    Design: Corner/endpoints/fk_reverse_list_units_by_catalog_item
    """
    ctx = setup_yard()  # one unit EU-1 already
    validate_success(api.create_equipment_unit(
        create_equipment_unit_payload(ctx["item"]["id"], asset_tag="EU-2"), YM), 201)
    data, meta = validate_paginated(
        api.list_equipment_units(YM, params={"catalog_item_id": ctx["item"]["id"]}))
    assert meta["total_count"] == 2


def test_catalog_item_computed_available_unit_count(api):
    """PRD §2.8: "unit_count is the number of EquipmentUnit rows whose
    catalog_item_id points at the catalog item, in any availability state;
    available_unit_count is the number of those units whose availability_state is
    AVAILABLE."

    Design: Corner/endpoints/catalog_item_computed_available_unit_count_after_register
    """
    ctx = setup_yard()  # one unit EU-1
    validate_success(api.create_equipment_unit(
        create_equipment_unit_payload(ctx["item"]["id"], asset_tag="EU-2"), YM), 201)
    item = validate_success(api.get_catalog_item(ctx["item"]["id"], YM), 200)
    assert item["unit_count"] == 2
    assert item["available_unit_count"] == 2


def test_agreement_ledger_entries_reverse_reachability(api):
    """PRD §3.7: "An agreement's ledger entries can be listed by walking
    AccountLedgerEntry.rental_agreement_id, since every settlement line records the
    rental_agreement_id that generated it".
    PRD §3.6: "a RENTAL_CHARGE ... and a DEPOSIT_REFUND for the full
    deposit_held_cents".

    Design: Corner/endpoints/ledger_reverse_reachability_by_agreement
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    inspect(ctx["agreement"]["id"], return_fuel_level_liters=40,
            cleanliness="CLEAN", damage_assessed_cents=0)
    data, meta = validate_paginated(
        api.list_agreement_ledger_entries(ctx["agreement"]["id"], YM))
    # Clean on-time full-fuel close: RENTAL_CHARGE + DEPOSIT_REFUND only.
    assert meta["total_count"] == 2


def test_damage_charge_reverse_reachability_by_inspection(api):
    """PRD §3.7: "Damage charges can be retraced by their rental_agreement_id or
    return_inspection_id".

    Design: Corner/endpoints/damage_charge_reverse_reachability_by_inspection
    """
    ctx = setup_returned_pending_inspection(reservation_overrides={
        "rental_start_date": "2026-06-01", "rental_end_date": "2026-06-10"})
    ins = inspect(ctx["agreement"]["id"], return_fuel_level_liters=40,
                  cleanliness="CLEAN", damage_assessed_cents=9000)
    data, meta = validate_paginated(api.list_damage_charges(
        YM, params={"return_inspection_id": ins["id"]}))
    assert meta["total_count"] == 1
