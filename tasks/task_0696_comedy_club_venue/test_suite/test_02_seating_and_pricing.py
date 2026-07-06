"""Seating layout, the item/drink minimum, and table/server assignment rules.

Translates the dual-variant minimum_due difficulty instance (queue A) plus the
pricing and table-assignment corner instances (queue B).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_ga_show_on_sale, setup_table_show_on_sale,
    create_venue, create_draft_show, create_server,
    create_table_reservation, create_table_reservation_assigned,
    assign_table_to_reservation,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
FLOOR = TEST_USERS["floor_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty queue A — dual_variant_calc / minimum_due_pre_vs_post_seating
# ---------------------------------------------------------------------------
def test_minimum_due_pre_seating_uses_venue_default(api):
    """PRD §3.4: "At reservation creation, before any table is known, the minimum
    is estimated from the tier override if present and otherwise from the venue
    default of 2 — the table's own per-seat figure is not yet visible."
    PRD §3.4: "The minimum a party owes, recorded as `minimum_due_cents`, is
    therefore the chosen per-seat item count multiplied by 1000 cents and then
    multiplied by the reservation's `party_size`."

    Design: Difficulty/dual_variant_calc/minimum_due_pre_vs_post_seating
    """
    sc = setup_table_show_on_sale(seats=4, min_items_per_seat=3, price_cents=4500)
    res = create_table_reservation(sc, patron_id="patron-aa", party_size=2)
    # pre-seating: venue default 2 items * 1000 * party 2 == 4000.
    assert res["minimum_due_cents"] == 4000, \
        f"pre-seating minimum_due expected 4000, got {res['minimum_due_cents']}"


def test_minimum_due_post_seating_uses_table_min(api):
    """PRD §3.4: "After a table is assigned to a `TABLE`-section reservation, the
    minimum is recomputed with that table's `min_items_per_seat` taking its place
    in the precedence chain; a table whose per-seat minimum is higher than the
    estimate therefore raises `minimum_due_cents` at assignment time."
    PRD §3.6: "A successful assignment moves the table from `AVAILABLE` to `HELD`,
    sets the reservation's `table_id`, recomputes `minimum_due_cents` in its
    post-seating form, and advances the table's `version`."

    Design: Difficulty/dual_variant_calc/minimum_due_pre_vs_post_seating
    """
    sc = setup_table_show_on_sale(seats=4, min_items_per_seat=3, price_cents=4500)
    res = create_table_reservation(sc, patron_id="patron-aa", party_size=2)
    assert res["minimum_due_cents"] == 4000, "precondition: pre-seating estimate is 4000"
    after = assign_table_to_reservation(sc, res["id"])
    # post-seating: table min 3 * 1000 * party 2 == 6000.
    assert after["minimum_due_cents"] == 6000, \
        f"post-seating minimum_due expected 6000, got {after['minimum_due_cents']}"


# ---------------------------------------------------------------------------
# Corner queue B — calculations / minimum_due_tier_override_precedence
# ---------------------------------------------------------------------------
def test_minimum_due_tier_override_precedence(api):
    """PRD §3.4: "The per-seat item minimum follows a strict precedence, taking
    the first value that is set: the tier's `min_items_override` if present;
    otherwise, once a table has been assigned to a `TABLE`-section party, that
    table's `min_items_per_seat`; otherwise the venue default of 2 items per seat."

    Design: Corner/calculations/minimum_due_tier_override_precedence
    """
    sc = setup_ga_show_on_sale(price_cents=6000, ga_capacity=50,
                               tier_overrides={"min_items_override": 5})
    payload = {
        "show_id": sc["show"]["id"], "section_id": sc["section"]["id"],
        "tier_id": sc["tier"]["id"], "patron_id": "patron-ov", "party_size": 2,
    }
    data = validate_success(api.create_reservation(payload, BOX_OFFICE), expected_status=201)
    # override 5 items * 1000 * party 2 == 10000.
    assert data["minimum_due_cents"] == 10000, \
        f"tier override minimum_due expected 10000, got {data['minimum_due_cents']}"


# ---------------------------------------------------------------------------
# Corner queue B — validations: table assignment & server load
# ---------------------------------------------------------------------------
def test_assign_table_too_small_rejected(api):
    """PRD §3.6: "a table whose `seats` fall short of `party_size` is rejected
    with `ERR_TABLE_TOO_SMALL`".

    Design: Corner/validations/assign_table_too_small_rejected
    """
    sc = setup_table_show_on_sale(seats=2, price_cents=4500)
    res = create_table_reservation(sc, patron_id="patron-ts", party_size=4)
    resp = api.assign_table(
        res["id"],
        {"table_id": sc["table"]["id"], "expected_table_version": sc["table_version"]},
        FLOOR,
    )
    validate_error(resp, ApiErrorId.ERR_TABLE_TOO_SMALL)


def test_assign_table_no_server_rejected(api):
    """PRD §3.6: "a table with no `assigned_server_id` is rejected with
    `ERR_NO_SERVER_ASSIGNED`".

    Design: Corner/validations/assign_table_no_server_rejected
    """
    sc = setup_table_show_on_sale(seats=4, price_cents=4500, assign_server=False)
    res = create_table_reservation(sc, patron_id="patron-nsv", party_size=2)
    resp = api.assign_table(
        res["id"],
        {"table_id": sc["table"]["id"], "expected_table_version": sc["table_version"]},
        FLOOR,
    )
    validate_error(resp, ApiErrorId.ERR_NO_SERVER_ASSIGNED)


def test_server_overloaded_rejected(api):
    """PRD §3.3: "The assignment is refused if it would push the server's
    `assigned_table_count` above its `max_tables`, in which case the request is
    rejected with `ERR_SERVER_OVERLOADED`."

    Design: Corner/validations/server_overloaded_rejected
    """
    venue = create_venue(name="Overload Venue")
    show = create_draft_show(venue["id"], title="Overload Night",
                             starts_at="2026-05-23T03:00:00Z", ends_at="2026-05-23T05:00:00Z")
    section = validate_success(
        api.create_section(venue["id"], show["id"], {"kind": "TABLE", "label": "Floor"}, BOOKER),
        expected_status=201,
    )
    t1 = validate_success(
        api.create_table(venue["id"], show["id"], section["id"],
                         {"table_number": "T1", "seats": 4}, FLOOR),
        expected_status=201,
    )
    t2 = validate_success(
        api.create_table(venue["id"], show["id"], section["id"],
                         {"table_number": "T2", "seats": 4}, FLOOR),
        expected_status=201,
    )
    server = create_server(name="Lee", max_tables=1)
    validate_success(api.assign_server(t1["id"], {"server_id": server["id"]}, FLOOR))
    resp = api.assign_server(t2["id"], {"server_id": server["id"]}, FLOOR)
    validate_error(resp, ApiErrorId.ERR_SERVER_OVERLOADED)


def test_table_create_on_non_table_section_rejected(api):
    """PRD §3.2: "creating a table beneath a section whose `kind` is not `TABLE`
    is rejected with `ERR_WRONG_SECTION_KIND`."

    Design: Corner/validations/table_create_on_non_table_section_rejected
    """
    sc = setup_ga_show_on_sale(ga_capacity=50)
    resp = api.create_table(
        sc["venue"]["id"], sc["show"]["id"], sc["section"]["id"],
        {"table_number": "T1", "seats": 4}, FLOOR,
    )
    validate_error(resp, ApiErrorId.ERR_WRONG_SECTION_KIND)
