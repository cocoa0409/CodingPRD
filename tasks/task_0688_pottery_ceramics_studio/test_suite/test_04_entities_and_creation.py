"""Entity creation, defaults, computed fields, not-found, required fields, and the
append-only ledger entry shape.

Queue B (Corner): section entities.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    assert_member, assert_piece, assert_ledger_entry,
    create_member, create_open_visit, create_series,
    NON_EXISTENT_UUID, TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
MANAGER = TEST_USERS["manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_create_loyalty_member_defaults(api):
    """PRD §3.1: "A freshly registered member starts ACTIVE, in the BRONZE tier,
    with a point_balance of 0 and a lifetime_points_earned of 0." PRD §2.4: a
    version "begins at 1 and increments by one on every mutation."

    Design: Corner/entities/create_loyalty_member_minimal
    """
    res = api.create_member(
        {"email": "new@x.com", "full_name": "New Member", "phone": "555-1000"}, ANON)
    member = validate_success(res, 201)
    assert_member(member)
    assert member["tier"] == "BRONZE", member["tier"]
    assert member["point_balance"] == 0, member["point_balance"]
    assert member["lifetime_points_earned"] == 0, member["lifetime_points_earned"]
    assert member["status"] == "ACTIVE", member["status"]
    assert member["version"] == 1, member["version"]


def test_get_member_not_found(api):
    """PRD §2.8: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected with ERR_NOT_FOUND."

    Design: Corner/entities/get_member_not_found
    """
    res = api.get_member(NON_EXISTENT_UUID, STAFF)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_paint_bar_item_missing_unit_price(api):
    """PRD §2.10: "Field-shape validation (required fields present, enums within
    their allowed values, integers non-negative where required...) is the catch-all
    and surfaces as ERR_INVALID_REQUEST." PRD §3.7: a manager adds an item with "a
    unit_price_cents (the retail price per unit, which must be at least 0)."

    Design: Corner/entities/create_paint_bar_item_missing_required_field
    """
    res = api.create_paint_bar_item(
        {"sku": "GLZ-X", "name": "Glaze X", "category": "GLAZE", "reorder_threshold": 5}, MANAGER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_piece_firing_temp_defaults_cone_06(api):
    """PRD §3.3: "The firing temperature is CONE_06 by default or CONE_6." PRD §3.3:
    "On creation the piece enters PAINTED status with no kiln assignment."

    Design: Corner/entities/bisque_piece_firing_temp_default_applied
    """
    visit = create_open_visit()
    res = api.add_piece(visit["id"],
                        {"sku": "MUG-12OZ", "name": "Mug", "bisque_price_cents": 3000}, STAFF)
    piece = validate_success(res, 201)
    assert piece["firing_temp"] == "CONE_06", piece["firing_temp"]
    assert piece["status"] == "PAINTED", piece["status"]


def test_studio_fee_computed_not_input(api):
    """PRD §3.2: "the studio_fee_cents is set to the number of painters multiplied by
    the per-painter studio fee of 1000 cents (that is, ten dollars each) for a
    WALK_IN... The visit opens in OPEN status with its provisional_total_cents
    initialized to that studio fee."

    Design: Corner/entities/studio_fee_computed_input_ignored
    """
    res = api.create_visit(
        {"party_size": 3, "visit_type": "WALK_IN", "studio_fee_cents": 999999}, STAFF)
    visit = validate_success(res, 201)
    assert visit["studio_fee_cents"] == 3000, visit["studio_fee_cents"]
    assert visit["provisional_total_cents"] == 3000, visit["provisional_total_cents"]


def test_ledger_entry_is_append_only(api):
    """PRD §2.4: "A LoyaltyLedgerEntry is an append-only event record: it carries
    only an id and a created_at, and it has neither an updated_at nor a version."
    PRD §3.10: "an EARN ledger entry is appended with source_ref_type ENROLLMENT."

    Design: Corner/entities/ledger_entry_immutable_no_version
    """
    member = create_member()
    series = create_series(session_count=4, seat_capacity=5, price_cents=12000,
                           starts_at="2026-07-01T18:00:00Z")
    api.enroll(series["id"], {"member_id": member["id"]}, STAFF)

    data, meta = validate_paginated(api.get_member_ledger(member["id"], MANAGER))
    earns = [e for e in data if e["entry_type"] == "EARN"]
    assert len(earns) == 1, f"expected exactly one EARN entry, got {data}"
    entry = earns[0]
    assert_ledger_entry(entry)
    assert entry["points_delta"] == 120, entry["points_delta"]  # floor(12000/100)
    assert entry["source_ref_type"] == "ENROLLMENT", entry["source_ref_type"]
    assert "version" not in entry, "ledger entry must not carry version"
