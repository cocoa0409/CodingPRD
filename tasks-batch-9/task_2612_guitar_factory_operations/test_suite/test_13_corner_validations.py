"""
The validation ladder at its ordinary rungs: uniqueness per natural key, window
ordering ahead of overlap, aggregate wood availability, the conditional option
requirement, cross-entity option compatibility, identity before permission, and
the two deliberately different climate predicates.
"""

from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U

MISSING_ID = "00000000-0000-4000-8000-000000000000"

NITRO_ONLY_OPTION = {
    "option_code": "SB-NITRO",
    "option_group": "NECK_PROFILE",
    "upcharge_cents": 60000,
    "complexity_class": "MASTER",
    "lead_time_days": 20,
    "requires_finish_system": "NITRO",
}


def test_a_lot_code_already_on_the_books_cannot_be_reused_for_another_species(api, lot_received):
    """
    The delivery code is unique across the whole rack, so a maple delivery cannot
    borrow the spruce delivery's code, and the refused request leaves the rack
    holding exactly the one lot it held before.

    PRD: "**Natural-key uniqueness.** `room_code`, `lot_code`, `billet_code`,
    `spec_code`, `station_code`, `option_code`, `order_code` and `shop_code` are
    each globally unique across their own resource; a duplicate is
    `ERR_DUPLICATE_CODE` (409)."

    Design: Corner/validations/a_duplicate_lot_code_is_refused_even_for_a_different_species
    """
    validate_error(api.create_tonewood_lot(F.lot_payload(
        lot_code="LOT-001", species_code="HARD_MAPLE", cites_appendix="NONE",
        board_feet_received=55.00, moisture_content_pct=10.0,
        storage_room_id=lot_received["dry1"]), U.WOOD_BUYER_HEADERS),
        E.ERR_DUPLICATE_CODE, 409)

    rows, meta = validate_paginated(api.list_tonewood_lots(U.WOOD_BUYER_HEADERS))
    assert meta["total_count"] == 1
    assert rows[0]["species_code"] == "SITKA_SPRUCE"
    assert rows[0]["lot_code"] == "LOT-001"


def test_a_booking_whose_window_does_not_advance_is_refused_before_any_overlap_test(api, one_cnc_station):
    """
    A window of no duration and a window that runs backwards are both refused on
    the ordering rule rather than being reported as a clash with anything, and the
    router's booked minutes never move.

    PRD: "**Window ordering.** On a station-reservation booking, `starts_at` must
    be strictly earlier than `ends_at`, and any explicit booth window must have
    `booth_hold_from` strictly earlier than `booth_hold_until`. Violation:
    `ERR_INVALID_WINDOW` (422)."

    Design: Corner/validations/a_reservation_window_that_does_not_advance_is_refused
    """
    zero_length = {"station_id": one_cnc_station["cnc1"],
                   "starts_at": "2026-08-02T08:00:00Z",
                   "ends_at": "2026-08-02T08:00:00Z"}
    validate_error(api.create_station_reservation(zero_length, U.MACHINIST_HEADERS),
                   E.ERR_INVALID_WINDOW, 422)

    inverted = {"station_id": one_cnc_station["cnc1"],
                "starts_at": "2026-08-02T09:00:00Z",
                "ends_at": "2026-08-02T08:00:00Z"}
    validate_error(api.create_station_reservation(inverted, U.MACHINIST_HEADERS),
                   E.ERR_INVALID_WINDOW, 422)

    _, meta = validate_paginated(
        api.list_station_reservations(U.MACHINIST_HEADERS))
    assert meta["total_count"] == 0

    station = validate_success(
        api.get_station(one_cnc_station["cnc1"], U.MACHINIST_HEADERS))
    A.assert_station_minutes(station, total=0, held=0, consumed=0, released=0)


def test_the_second_cut_is_refused_on_the_wood_it_needs_including_its_own_kerf(api, lot_after_big_cut):
    """
    Thirty board feet is less than the twenty-nine and ninety-six hundredths still
    standing only if the sawdust is ignored; charged with its own kerf the cut
    needs thirty and nine tenths, so it overdraws the lot and is refused.

    PRD: "The billet's `board_feet` plus its computed `kerf_loss_board_feet` must
    be less than or equal to the lot's current `board_feet_available`, and a cut
    that would overdraw the lot is refused with `ERR_INSUFFICIENT_BOARD_FEET`."

    Design: Corner/validations/two_individually_legal_cuts_that_collectively_exceed_the_lot_are_refused
    """
    before = validate_success(
        api.get_tonewood_lot(lot_after_big_cut["lot1"], U.MACHINIST_HEADERS))
    assert before["board_feet_available"] == 29.96

    validate_error(api.create_billet({
        "billet_code": "BLT-002", "lot_id": lot_after_big_cut["lot1"],
        "board_feet": 30.00, "grade": "AAA",
        "expected_tonewood_lot_version": lot_after_big_cut["lot_v2"],
    }, U.MACHINIST_HEADERS), E.ERR_INSUFFICIENT_BOARD_FEET, 409)

    _, meta = validate_paginated(api.list_billets(U.MACHINIST_HEADERS))
    assert meta["total_count"] == 1

    after = validate_success(
        api.get_tonewood_lot(lot_after_big_cut["lot1"], U.MACHINIST_HEADERS))
    assert after["board_feet_available"] == 29.96


def test_a_slightly_smaller_cut_fits_and_leaves_the_lot_too_thin_to_saw_again(api, lot_after_big_cut):
    """
    Twenty-nine board feet plus its own eighty-seven hundredths of sawdust fits
    inside what is left, and the nine hundredths that remain are below the usable
    minimum, so the lot closes itself out in the same request.

    PRD: "If the cut leaves the lot with less than two board feet still standing
    in `board_feet_available`, the lot moves `RELEASED → DEPLETED` in the same
    request and no further billets may be sawn from it."

    Design: Corner/validations/two_individually_legal_cuts_that_collectively_exceed_the_lot_are_refused
    """
    billet = F.create_billet(api, lot_after_big_cut["lot1"],
                             lot_after_big_cut["lot_v2"],
                             billet_code="BLT-003", board_feet=29.00, grade="AA")
    assert billet["kerf_loss_board_feet"] == 0.87

    lot = validate_success(
        api.get_tonewood_lot(lot_after_big_cut["lot1"], U.MACHINIST_HEADERS))
    assert lot["board_feet_available"] == 0.09
    assert lot["status"] == "DEPLETED"
    assert lot["board_feet_kerf_loss"] == 2.91
    A.assert_wood_conserved(lot)


def test_a_custom_shop_order_needs_an_approved_option_before_it_can_take_a_deposit(api, two_orders_custom_and_standard):
    """
    The requirement is conditional on the build being a custom shop one: the
    custom order is refused at a deposit that exactly meets its threshold, while
    the otherwise identical standard order at the same list price confirms.

    PRD: "On an order whose `is_custom_shop` is true, at least one selection must
    already be in status `SELECTED`, otherwise the request is refused with
    `ERR_OPTIONS_NOT_SELECTED` — and because that check sits above the fiscal rung
    of the ladder, an under-funded custom order with no approved option reports
    the missing option rather than the thin deposit."

    Design: Corner/validations/a_custom_shop_order_cannot_confirm_without_a_selected_option
    """
    env = two_orders_custom_and_standard
    custom = validate_success(api.get_build_order(env["boCS"], U.COORDINATOR_HEADERS))
    assert custom["provisional_quote_total_cents"] == 537600

    validate_error(api.confirm_build_order(env["boCS"], {"deposit_cents": 53760},
                                           U.COORDINATOR_HEADERS),
                   E.ERR_OPTIONS_NOT_SELECTED, 409)
    refused = validate_success(api.get_build_order(env["boCS"], U.COORDINATOR_HEADERS))
    assert refused["commercial_status"] == "QUOTED"
    assert refused["deposit_paid_cents"] == 0

    standard = validate_success(api.get_build_order(env["boSTD"], U.COORDINATOR_HEADERS))
    assert standard["provisional_quote_total_cents"] == 480000
    confirmed = validate_success(api.confirm_build_order(
        env["boSTD"], {"deposit_cents": 48000}, U.COORDINATOR_HEADERS))
    assert confirmed["commercial_status"] == "CONFIRMED"
    assert confirmed["deposit_held_cents"] == 48000


def test_the_missing_option_is_reported_ahead_of_the_missing_money(api, two_orders_custom_and_standard):
    """
    One call breaks both rules at once — no approved option and a single cent
    against a threshold of tens of thousands — and the answer is the option rule,
    which the status code alone distinguishes from the fiscal one.

    PRD: "Requests are validated in a fixed order, and the **first** rule whose
    condition is violated short-circuits the request: its error is returned, no
    later rule is evaluated, and no state whatsoever is mutated."

    Design: Corner/validations/the_option_requirement_outranks_the_deposit_threshold_on_confirm
    """
    env = two_orders_custom_and_standard

    validate_error(api.confirm_build_order(env["boCS"], {"deposit_cents": 1},
                                           U.COORDINATOR_HEADERS),
                   E.ERR_OPTIONS_NOT_SELECTED, 409)

    order = validate_success(api.get_build_order(env["boCS"], U.COORDINATOR_HEADERS))
    assert order["commercial_status"] == "QUOTED"
    assert order["deposit_paid_cents"] == 0
    assert order["deposit_held_cents"] == 0


def test_an_option_the_existing_selection_excludes_is_refused_until_that_row_is_dropped(api, order_with_vine):
    """
    The dot inlay is legal in itself and illegal only because a live vine
    selection names it; withdrawing the vine makes the identical request succeed,
    which proves the check reads the order's current selection set.

    PRD: "And if the requested option's `option_code` appears in the
    `incompatible_option_codes` of an option already on the order in status
    `PENDING_APPROVAL`, `SELECTED` or `LOCKED` — or if one of those options' codes
    appears in the requested option's own `incompatible_option_codes`, since the
    check runs in both directions — the request is refused with
    `ERR_OPTION_INCOMPATIBLE`."

    Design: Corner/validations/an_option_excluded_by_an_already_selected_option_is_refused
    """
    env = order_with_vine
    validate_error(api.create_option_selection(env["boCS"], {
        "option_id": env["optD"], "quantity": 1,
        "expected_build_order_version": env["boCS_v2"],
    }, U.COORDINATOR_HEADERS), E.ERR_OPTION_INCOMPATIBLE, 409)

    _, meta = validate_paginated(api.list_option_selections(U.COORDINATOR_HEADERS))
    assert meta["total_count"] == 1

    F.reject_selection(api, env["selV"], "customer changed mind")

    current = validate_success(api.get_build_order(env["boCS"], U.COORDINATOR_HEADERS))
    accepted = validate_success(api.create_option_selection(env["boCS"], {
        "option_id": env["optD"], "quantity": 1,
        "expected_build_order_version": current["version"],
    }, U.COORDINATOR_HEADERS), 201)
    assert accepted["status"] == "PENDING_APPROVAL"
    assert accepted["line_total_cents"] == 16205


def a_polyurethane_order_and_two_options(api):
    """
    A custom polyurethane order alongside one option that insists on lacquer and
    one that accepts any chemistry at all.
    """
    env = X.build_clock(api)
    env["optN"] = F.create_option(api, dict(NITRO_ONLY_OPTION))["id"]
    env["optG"] = F.create_option(api, dict(C.OPTION_GOLD_HARDWARE))["id"]
    order = F.create_order(api, F.order_payload(
        order_code="ORD-POLY", model_code="D28", base_price_cents=300000,
        promised_date="2026-11-01T00:00:00Z", is_custom_shop=True,
        artist_tier="NONE", finish_system="POLY"), U.COORDINATOR_HEADERS)
    env["boP"] = order["id"]
    env["boP_v1"] = order["version"]
    return env


def test_an_option_that_insists_on_lacquer_is_refused_while_a_wildcard_attaches(api):
    """
    The option that names a chemistry different from the order's is refused, and
    the option left at the wildcard is not treated as a third chemistry but
    attaches to the same order.

    PRD: "If the catalog row's `requires_finish_system` is `NITRO` or `POLY` and
    differs from the order's `finish_system`, the request is refused with
    `ERR_OPTION_FINISH_MISMATCH`; a `requires_finish_system` of `ANY` never
    conflicts."

    Design: Corner/validations/an_option_requiring_nitro_is_refused_on_a_polyurethane_order
    """
    env = a_polyurethane_order_and_two_options(api)

    validate_error(api.create_option_selection(env["boP"], {
        "option_id": env["optN"], "quantity": 1,
        "expected_build_order_version": env["boP_v1"],
    }, U.COORDINATOR_HEADERS), E.ERR_OPTION_FINISH_MISMATCH, 422)

    _, meta = validate_paginated(api.list_option_selections(U.COORDINATOR_HEADERS))
    assert meta["total_count"] == 0

    accepted = validate_success(api.create_option_selection(env["boP"], {
        "option_id": env["optG"], "quantity": 1,
        "expected_build_order_version": env["boP_v1"],
    }, U.COORDINATOR_HEADERS), 201)
    assert accepted["status"] == "PENDING_APPROVAL"
    assert accepted["line_total_cents"] == 29705

    order = validate_success(api.get_build_order(env["boP"], U.COORDINATOR_HEADERS))
    assert order["provisional_quote_total_cents"] == 369270


def test_an_incomplete_or_unrecognised_identity_is_turned_away_before_permissions(api, clock):
    """
    A caller who names a role but no user, and a caller who names a user under a
    role this factory does not employ, are both unauthenticated rather than
    merely unpermitted, and neither leaves a room behind.

    PRD: "If either header is absent, if `X-User-ID` is empty, or if
    `X-User-Role` is not one of the ten role names enumerated below, the request
    is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/validations/a_request_without_a_user_id_header_is_unauthenticated
    """
    payload = dict(C.DRY_STORE_1)

    validate_error(api.create_storage_room(payload, U.NO_USER_HEADERS),
                   E.ERR_UNAUTHENTICATED, 401)
    validate_error(api.create_storage_room(payload, U.UNKNOWN_ROLE_HEADERS),
                   E.ERR_UNAUTHENTICATED, 401)

    _, meta = validate_paginated(api.list_storage_rooms(U.PLANT_ADMIN_HEADERS))
    assert meta["total_count"] == 0


def test_a_drifting_room_still_takes_deliveries_but_a_condemned_one_does_not(api, clock):
    """
    The receiving guard names the stricter posture specifically, so wood may be
    booked into a room that has merely drifted out of band and may not be booked
    into one that has been condemned.

    PRD: "`QUARANTINED` is the stricter posture: it produces
    `ERR_ROOM_QUARANTINED` instead, and it additionally blocks commissioning a new
    station in that room and booking any reservation on a station that sits in it.
    Receiving a tonewood lot into a `QUARANTINED` room is likewise refused."

    Design: Corner/validations/a_lot_may_be_received_into_an_out_of_spec_room_but_not_a_quarantined_one
    """
    env = X.build_dry_store(api, clock)
    drifted = F.log_climate_reading(api, env["dry1"], 60.0, 21.0)
    assert drifted["climate_status"] == "OUT_OF_SPEC"

    lot = F.create_lot(api, F.lot_payload(
        lot_code="LOT-001", species_code="SITKA_SPRUCE", cites_appendix="NONE",
        board_feet_received=100.00, moisture_content_pct=7.0,
        storage_room_id=env["dry1"]))
    assert lot["status"] == "RECEIVED"

    F.set_clock(api, "2026-08-02T00:00:00Z")
    condemned = F.log_climate_reading(api, env["dry1"], 60.0, 21.0)
    assert condemned["climate_status"] == "QUARANTINED"

    validate_error(api.create_tonewood_lot(F.lot_payload(
        lot_code="LOT-002", species_code="SITKA_SPRUCE", cites_appendix="NONE",
        board_feet_received=100.00, moisture_content_pct=7.0,
        storage_room_id=env["dry1"]), U.WOOD_BUYER_HEADERS),
        E.ERR_ROOM_QUARANTINED, 409)

    _, meta = validate_paginated(api.list_tonewood_lots(U.WOOD_BUYER_HEADERS))
    assert meta["total_count"] == 1


def test_a_shop_registering_in_another_shops_name_is_turned_away_on_identity(api, two_authorized_shops):
    """
    The external caller's own identifier is the shop it may act for, so naming a
    different shop is refused on identity before the request's other defects are
    ever reached — the order it names does not exist and is never looked up.

    PRD: "When it names some other shop — supplying a `registering_shop_id` that
    is not its own `X-User-ID`, or reading a shop row whose path identifier is not
    its own `X-User-ID`, or listing registrations without filtering to its own
    `registering_shop_id` — the request is refused with
    `ERR_SHOP_IDENTITY_MISMATCH` and HTTP 403."

    Design: Corner/validations/an_authorized_shop_cannot_register_a_warranty_for_a_different_shop
    """
    env = two_authorized_shops
    impostor = U.make_authorized_shop_headers(env["shopB"])

    validate_error(api.create_warranty_registration({
        "build_order_id": MISSING_ID,
        "registering_shop_id": env["shopA"],
        "serial_number": "OM45-2026-00001",
        "owner_email": "owner@example.com",
        "purchase_date": "2026-08-16T00:00:00Z",
    }, impostor), E.ERR_SHOP_IDENTITY_MISMATCH, 403)

    _, meta = validate_paginated(
        api.list_warranty_registrations(U.SERVICE_MANAGER_HEADERS))
    assert meta["total_count"] == 0
