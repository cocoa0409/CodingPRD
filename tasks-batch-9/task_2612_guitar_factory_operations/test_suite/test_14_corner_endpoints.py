"""
Endpoints at their ordinary settings: the work selector's ranking, pool size and
empty-pool refusal, the clock's effect on a live score versus a booking-time
snapshot, the document negotiation cycle, both foreign keys on a registration,
and a filtered listing paginating over its filtered total.
"""

from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                           validate_success)

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import test_users as U

MISSING_ID = "00000000-0000-4000-8000-000000000000"
MISSING_SHOP_ID = "11111111-1111-4111-8111-111111111111"


def test_the_work_selector_returns_the_highest_scoring_order_and_the_whole_pool_size(api, two_confirmed_orders_on_cnc1):
    """
    The signature custom build outranks the plainer instrument even though the
    plain one is promised sooner, because the artist and custom-shop terms
    outweigh ten weeks of urgency, and the reported count is the pool the winner
    was drawn from rather than the single row returned.

    PRD: "The reply names the winning `build_order_id`, its `order_code`, its
    `priority_score`, the `starts_at` that decided the tie-break, and an
    `eligible_count` giving the size of the pool the winner was drawn from."

    Design: Corner/endpoints/the_station_selector_ranks_by_priority_score_and_reports_the_pool_size
    """
    env = two_confirmed_orders_on_cnc1

    picked = validate_success(
        api.get_next_build_order(env["cnc1"], U.MACHINIST_HEADERS))
    assert picked["build_order_id"] == env["bo1"]
    assert picked["order_code"] == "BO-1"
    assert picked["priority_score"] == 69.50
    assert picked["starts_at"] == "2026-08-03T08:00:00Z"
    assert picked["eligible_count"] == 2


def test_handing_the_windows_back_shrinks_the_pool_and_then_refuses_the_read(api, two_confirmed_orders_on_cnc1):
    """
    Eligibility follows the booking's current status rather than its existence:
    releasing the leader's hold promotes the other instrument, and releasing the
    second hold leaves a pool that is refused outright instead of answered with an
    empty payload.

    PRD: "An order is eligible for a given station only if it satisfies all three
    of the following: it holds at least one reservation on that station whose
    status is `HELD`; its `build_stage` is not `SERIALIZED`, `SCRAPPED` or
    `COMPLIANCE_HOLD`; and its `commercial_status` is not `QUOTED`, `INVOICED`,
    `CLOSED` or `CANCELLED`."

    Design: Corner/endpoints/releasing_the_reservations_shrinks_the_pool_and_then_empties_it
    """
    env = two_confirmed_orders_on_cnc1
    F.release_reservation(api, env["resA"])

    promoted = validate_success(
        api.get_next_build_order(env["cnc1"], U.MACHINIST_HEADERS))
    assert promoted["build_order_id"] == env["bo2"]
    assert promoted["order_code"] == "BO-2"
    assert promoted["priority_score"] == 35.50
    assert promoted["eligible_count"] == 1

    F.release_reservation(api, env["resB"])
    validate_error(api.get_next_build_order(env["cnc1"], U.MACHINIST_HEADERS),
                   E.ERR_NO_ELIGIBLE_BUILD_ORDER, 409)

    for res in (env["resA"], env["resB"]):
        row = validate_success(api.get_station_reservation(res, U.MACHINIST_HEADERS))
        assert row["status"] == "RELEASED"


def test_moving_the_clock_rescores_the_selector_but_not_the_booking_snapshot(api, two_confirmed_orders_on_cnc1):
    """
    Ten days closer to the promise raises the live urgency term by five points as
    the selector reads it, while the score the booking copied down when it was
    made is deliberately left where it was.

    PRD: "It also snapshots `priority_score` from the owning build order at
    booking time, and that snapshot is never re-synced when the order's live score
    later moves."

    Design: Corner/endpoints/advancing_the_clock_rescores_the_selector_without_writing_the_order
    """
    env = two_confirmed_orders_on_cnc1

    moved = F.set_clock(api, "2026-08-11T00:00:00Z")
    assert moved["current_utc"] == "2026-08-11T00:00:00Z"

    picked = validate_success(
        api.get_next_build_order(env["cnc1"], U.MACHINIST_HEADERS))
    assert picked["build_order_id"] == env["bo1"]
    assert picked["priority_score"] == 74.50
    assert picked["eligible_count"] == 2

    snapshot = validate_success(
        api.get_station_reservation(env["resA"], U.MACHINIST_HEADERS))
    assert snapshot["priority_score"] == 69.50


def test_a_rejected_file_cannot_be_released_and_may_be_handed_in_again(api, shipment_docs_pending):
    """
    With no listed wood contributing, the file goes in with no permit number at
    all; once the issuing authority objects the shipment is not releasable from
    that posture, and a second attach overwrites the field rather than being
    refused as a repeat.

    PRD: "Attaching stores the number, overwriting any value from a previous
    attempt."

    Design: Corner/endpoints/the_docs_rejected_cycle_reopens_release_and_exposes_the_next_guard
    """
    env = shipment_docs_pending

    first = F.attach_docs(api, env["shp1"])
    assert first["status"] == "DOCS_ATTACHED"
    assert first["cites_permit_required"] is False
    assert first["cites_permit_number"] is None

    rejected = F.reject_docs(api, env["shp1"],
                             "origin query from the issuing authority")
    assert rejected["status"] == "DOCS_REJECTED"

    validate_error(api.release_export_shipment(env["shp1"], U.COMPLIANCE_2_HEADERS),
                   E.ERR_SHIPMENT_STATE_INVALID, 409)

    second = F.attach_docs(api, env["shp1"], "JP-RE-2026-0001")
    assert second["status"] == "DOCS_ATTACHED"
    assert second["cites_permit_number"] == "JP-RE-2026-0001"


def test_the_re_attached_file_then_meets_the_gate_the_state_check_was_hiding(api, shipment_docs_pending):
    """
    Once the shipment's own posture is acceptable the next precondition surfaces,
    and this instrument has never been built, so the refusal names the build stage
    rather than the paperwork or the money.

    PRD: "The order's `build_stage` must be `SERIALIZED`, otherwise
    `ERR_BUILD_STAGE_INVALID` — an unfinished instrument cannot be exported."

    Design: Corner/endpoints/the_docs_rejected_cycle_reopens_release_and_exposes_the_next_guard
    """
    env = shipment_docs_pending
    F.attach_docs(api, env["shp1"])
    F.reject_docs(api, env["shp1"], "origin query from the issuing authority")
    F.attach_docs(api, env["shp1"], "JP-RE-2026-0001")

    validate_error(api.release_export_shipment(env["shp1"], U.COMPLIANCE_2_HEADERS),
                   E.ERR_BUILD_STAGE_INVALID, 409)

    shipment = validate_success(
        api.get_export_shipment(env["shp1"], U.COMPLIANCE_HEADERS))
    assert shipment["status"] == "DOCS_ATTACHED"
    assert shipment["released_by_user_id"] is None


def test_both_foreign_keys_on_a_registration_are_resolved_and_named_separately(api, two_authorized_shops):
    """
    The unknown instrument and the unknown shop come back as two different
    not-found codes from the same endpoint, and neither refused request touches the
    real shop's live registration tally.

    PRD: "**Body referential integrity.** Every foreign key in the request body
    resolves to an existing row — `lot_id` and `parent_billet_id` when sawing a
    billet; `spec_id`, `billet_id` and `build_order_id` when opening a component;
    `room_id` when commissioning a station; `station_id`, `build_order_id` and
    `component_id` when booking a reservation; `option_id` when configuring an
    option; `build_order_id` and `booth_id` when booking a finish run;
    `build_order_id` and `registering_shop_id` when registering a warranty;
    `build_order_id` when opening an export shipment; `storage_room_id` when
    receiving a tonewood lot."

    Design: Corner/endpoints/a_warranty_registration_needs_both_the_order_and_the_shop_to_resolve
    """
    env = two_authorized_shops
    base = {
        "serial_number": "OM45-2026-00001",
        "owner_email": "owner@example.com",
        "purchase_date": "2026-08-16T00:00:00Z",
    }

    validate_error(api.create_warranty_registration(dict(
        base, build_order_id=MISSING_ID, registering_shop_id=env["shopA"]),
        U.SERVICE_MANAGER_HEADERS), E.ERR_BUILD_ORDER_NOT_FOUND, 404)

    validate_error(api.create_warranty_registration(dict(
        base, build_order_id=MISSING_ID, registering_shop_id=MISSING_SHOP_ID),
        U.SERVICE_MANAGER_HEADERS), E.ERR_BUILD_ORDER_NOT_FOUND, 404)

    _, meta = validate_paginated(
        api.list_warranty_registrations(U.SERVICE_MANAGER_HEADERS))
    assert meta["total_count"] == 0

    shop = validate_success(api.get_repair_shop(env["shopA"], U.SERVICE_MANAGER_HEADERS))
    assert shop["warranty_claim_count"] == 0


def three_shops_in_two_countries(api, clock):
    """Two Japanese shops with an American one booked between them."""
    env = dict(clock)
    env["jp1"] = F.create_shop(api, F.shop_payload(
        shop_code="SHP-JP1", shop_name="Kanto Fret Works", country_code="JP"))["id"]
    env["us1"] = F.create_shop(api, F.shop_payload(
        shop_code="SHP-US1", shop_name="Bay Guitar Service", country_code="US"))["id"]
    env["jp2"] = F.create_shop(api, F.shop_payload(
        shop_code="SHP-JP2", shop_name="Kansai Lutherie", country_code="JP"))["id"]
    return env


def test_the_shop_listing_counts_the_filtered_set_and_pages_within_it(api, clock):
    """
    The reported total is the size of the Japanese subset rather than of the whole
    network, so the first single-row page still has more behind it, the second does
    not, and a page beyond the end is an empty page rather than a not-found.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters
    before pagination is applied and `has_more` is true exactly when rows remain
    beyond the current page."

    Design: Corner/endpoints/repair_shop_listing_filters_then_paginates
    """
    env = three_shops_in_two_countries(api, clock)
    jp = {"country_code": "JP"}

    rows, meta = validate_paginated(
        api.list_repair_shops(U.SERVICE_MANAGER_HEADERS, jp))
    assert meta["limit"] == 10
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert {row["id"] for row in rows} == {env["jp1"], env["jp2"]}

    page1, meta1 = validate_paginated(api.list_repair_shops(
        U.SERVICE_MANAGER_HEADERS, dict(jp, limit=1, offset=0)))
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_repair_shops(
        U.SERVICE_MANAGER_HEADERS, dict(jp, limit=1, offset=1)))
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"]
    assert env["us1"] not in {page1[0]["id"], page2[0]["id"]}

    past_end, meta3 = validate_paginated(api.list_repair_shops(
        U.SERVICE_MANAGER_HEADERS, dict(jp, limit=1, offset=5)))
    assert past_end == []
    assert meta3["total_count"] == 2
    assert meta3["has_more"] is False
