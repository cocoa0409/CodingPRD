"""CRUD, required-field, computed-field, and listing claims for core resources.

Covers venue/show/reservation creation defaults, not-found and required-field
rejections, server-computed charges, listing envelopes, and immediate visibility
of issued tickets — all per the PRD.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_venue_payload, create_show_payload, create_section_payload,
    assert_venue, assert_show,
    setup_ga_show_on_sale, create_performer, create_draft_show, create_venue,
    setup_listed_guest_entry,
    TEST_USERS, make_performer_headers,
)

BOOKER = TEST_USERS["booker_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
FLOOR = TEST_USERS["floor_manager_headers"]
NONEXISTENT_SHOW = "00000000-0000-4000-8000-0000000000aa"


def test_create_venue_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly created venue takes `posture` `OPEN` and `version` 1."
    PRD §3.1: "optionally its `house_fee_pct` ... a fraction between 0 and 1
    inclusive that defaults to 0.20 and is applied once at settlement."

    Design: Corner/entities/create_venue_returns_201_with_defaults
    """
    resp = api.create_venue(create_venue_payload(name="Solo Venue", settlement_currency="USD"), BOOKER)
    data = validate_success(resp, expected_status=201)
    assert_venue(data)
    assert data["posture"] == "OPEN", f"expected OPEN posture, got {data['posture']}"
    assert data["house_fee_pct"] == 0.20, f"expected default house_fee_pct 0.20, got {data['house_fee_pct']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def test_get_show_not_found_returns_404(api):
    """PRD §2.6: "The system validates path identifiers strictly left to right
    and rejects the request at the first identifier that does not resolve to an
    existing resource, returning `ERR_NOT_FOUND`."

    Design: Corner/entities/get_show_not_found_returns_404
    """
    resp = api.get_show(NONEXISTENT_SHOW, BOOKER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_reservation_missing_required_field_returns_422(api):
    """PRD §3.5: "A `BoxOffice` operator or a `Patron` creates a **Reservation**
    against a sellable show by supplying its `show_id`, the `section_id` booked
    into, the `tier_id` (the priced tier used), the `patron_id`, the `party_size`
    (at least 1), and an optional `is_comp` flag (default false)."
    PRD §2.6: "then, request-shape validity — required fields present and
    well-typed, enum values legal, and the numeric domain rules below
    (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_reservation_missing_required_field_returns_422
    """
    sc = setup_ga_show_on_sale()
    # Omit party_size (a required input field).
    payload = {
        "show_id": sc["show"]["id"],
        "section_id": sc["section"]["id"],
        "tier_id": sc["tier"]["id"],
        "patron_id": "patron-rq",
    }
    resp = api.create_reservation(payload, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_section_kind_requires_ga_capacity_when_ga(api):
    """PRD §3.2: "A capacity-tracked section — one whose `kind` is `GA` or
    `RESERVED` — requires a `ga_capacity` head count; a `TABLE` section must omit
    `ga_capacity` entirely, leaving it null. Supplying `ga_capacity` for a `TABLE`
    section, or omitting it for a `GA` or `RESERVED` section, is a request-shape
    violation rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/section_kind_requires_ga_capacity_when_ga
    """
    venue = create_venue(name="Kind Venue")
    show = create_draft_show(venue["id"], title="Kind Night",
                             starts_at="2026-05-02T03:00:00Z", ends_at="2026-05-02T05:00:00Z")
    # GA section with no ga_capacity.
    resp = api.create_section(venue["id"], show["id"], {"kind": "GA", "label": "No Cap"}, BOOKER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_ticket_charge_computed_from_tier_and_party(api):
    """PRD §3.5: "At creation the system computes the reservation's
    `ticket_charge_cents`: for a comp reservation it is zero, and otherwise it is
    the tier's `price_cents` multiplied by `party_size` — an exact integer product
    needing no rounding."

    Design: Corner/entities/ticket_charge_computed_input_ignored
    """
    sc = setup_ga_show_on_sale(price_cents=4500)
    payload = {
        "show_id": sc["show"]["id"], "section_id": sc["section"]["id"],
        "tier_id": sc["tier"]["id"], "patron_id": "patron-cc", "party_size": 2,
    }
    data = validate_success(api.create_reservation(payload, BOX_OFFICE), expected_status=201)
    assert data["ticket_charge_cents"] == 9000, \
        f"expected 4500*2 == 9000, got {data['ticket_charge_cents']}"


def test_comp_reservation_zero_ticket_charge(api):
    """PRD §3.5: "At creation the system computes the reservation's
    `ticket_charge_cents`: for a comp reservation it is zero, and otherwise it is
    the tier's `price_cents` multiplied by `party_size`".

    Design: Corner/entities/comp_reservation_zero_ticket_charge
    """
    sc = setup_ga_show_on_sale(price_cents=4500)
    payload = {
        "show_id": sc["show"]["id"], "section_id": sc["section"]["id"],
        "tier_id": sc["tier"]["id"], "patron_id": "patron-cz", "party_size": 2,
        "is_comp": True,
    }
    data = validate_success(api.create_reservation(payload, BOX_OFFICE), expected_status=201)
    assert data["ticket_charge_cents"] == 0, \
        f"comp reservation must have ticket_charge_cents 0, got {data['ticket_charge_cents']}"


def test_list_shows_pagination_envelope(api):
    """PRD §2.3: "Each list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the
    envelope, where `total_count` is the size of the full filtered result set and
    `has_more` indicates whether items remain beyond the current page."

    Design: Corner/entities/list_shows_pagination_envelope
    """
    venue = create_venue(name="List Venue")
    create_draft_show(venue["id"], title="List Night",
                      starts_at="2026-05-05T03:00:00Z", ends_at="2026-05-05T05:00:00Z")
    resp = api.list_shows(BOOKER, params={"venue_id": venue["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"expected has_more False, got {meta['has_more']}"


def test_fk_reverse_lineup_slots_by_performer(api):
    """PRD §3.9: "Lineup slots may be read individually and listed filtered by
    `show_id` or `performer_id`."

    Design: Corner/endpoints/fk_reverse_lineup_slots_by_performer
    """
    venue = create_venue(name="FK Venue")
    show = create_draft_show(venue["id"], title="FK Night",
                             starts_at="2026-06-03T03:00:00Z", ends_at="2026-06-03T05:00:00Z")
    performer = create_performer(stage_name="Find Me", standard_fee_cents=15000)
    slot_payload = {
        "show_id": show["id"], "performer_id": performer["id"],
        "slot_order": 1, "role": "OPENER", "offered_fee_cents": 15000,
    }
    validate_success(api.create_lineup_slot(slot_payload, BOOKER), expected_status=201)
    resp = api.list_lineup_slots(BOOKER, params={"performer_id": performer["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"


def test_guest_list_convert_creates_comp_reservation(api):
    """PRD §3.10: "Conversion moves `status` to `CONVERTED`, creates a comp
    `Reservation` (with `is_comp` true) carrying over the entry's `party_size`,
    links the new reservation back through `reservation_id`, and waives the
    minimum when `minimum_waived` is set."

    Design: Corner/endpoints/guest_list_convert_creates_comp_reservation
    """
    ctx = setup_listed_guest_entry(party_size=2, minimum_waived=True, as_performer=True)
    sc = ctx["scenario"]
    gle_id = ctx["guest_entry"]["id"]
    data = validate_success(
        api.convert_guest_list_entry(
            gle_id, {"section_id": sc["section"]["id"], "tier_id": sc["tier"]["id"]},
            BOX_OFFICE,
        )
    )
    assert data["status"] == "CONVERTED", f"expected CONVERTED, got {data['status']}"
    res_id = data["reservation_id"]
    assert res_id is not None, "convert must link a reservation_id"
    res = validate_success(api.get_reservation(res_id, BOX_OFFICE))
    assert res["is_comp"] is True, "linked reservation must be a comp (is_comp true)"


def test_record_consumption_meets_minimum(api):
    """PRD §3.6: "When the running `items_consumed_cents`, after applying the
    delta, reaches or exceeds the reservation's `minimum_due_cents`, the
    `settlement_status` advances from `TICKET_PAID` to `MINIMUM_MET`".

    Design: Corner/endpoints/record_consumption_meets_minimum
    """
    sc = setup_ga_show_on_sale()
    payload = {
        "show_id": sc["show"]["id"], "section_id": sc["section"]["id"],
        "tier_id": sc["tier"]["id"], "patron_id": "patron-co", "party_size": 2,
    }
    res = validate_success(api.create_reservation(payload, BOX_OFFICE), expected_status=201)
    validate_success(api.collect_ticket(res["id"], BOX_OFFICE))
    # party 2 * 2 items * 1000 == 4000 minimum due.
    data = validate_success(
        api.record_consumption(res["id"], {"delta_cents": 4000}, FLOOR)
    )
    assert data["items_consumed_cents"] == 4000, \
        f"expected items_consumed 4000, got {data['items_consumed_cents']}"
    assert data["settlement_status"] == "MINIMUM_MET", \
        f"expected MINIMUM_MET, got {data['settlement_status']}"


def test_collect_ticket_immediate_visibility(api):
    """PRD §3.6: "A `BoxOffice` operator collects ticket payment, advancing
    `settlement_status` from `UNCOLLECTED` to `TICKET_PAID`; this requires the
    reservation's `booking_status` to be `BOOKED`, `SEATED`, or `CHECKED_IN`, and
    it issues one **Ticket** per seat in the `ISSUED` scan state."

    Design: Corner/consistency_model/collect_ticket_immediate_visibility
    """
    sc = setup_ga_show_on_sale()
    payload = {
        "show_id": sc["show"]["id"], "section_id": sc["section"]["id"],
        "tier_id": sc["tier"]["id"], "patron_id": "patron-im", "party_size": 2,
    }
    res = validate_success(api.create_reservation(payload, BOX_OFFICE), expected_status=201)
    collected = validate_success(api.collect_ticket(res["id"], BOX_OFFICE))
    assert collected["settlement_status"] == "TICKET_PAID", \
        f"expected TICKET_PAID in collect response, got {collected['settlement_status']}"
    _, meta = validate_paginated(api.list_tickets(BOX_OFFICE, params={"reservation_id": res["id"]}))
    assert meta["total_count"] == 2, f"party 2 -> expected 2 tickets, got {meta['total_count']}"
