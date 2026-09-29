"""
The cross-cutting layers where nothing else can explain the refusal: three
stale-version guards standing on parents whose own state machines are perfectly
willing, and the station selector settling a genuine score tie.
"""

from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U


def test_a_second_cut_echoing_the_first_cuts_stale_version_is_refused_inertly(api, lot_released):
    """
    The lot is still released and still has sixty-nine board feet standing, so
    nothing in its lifecycle objects to another cut — the only thing that refuses
    the second request is the version it echoes, and the refusal moves no wood, adds
    no billet and does not itself bump the version.

    PRD: "Sawing a billet requires `expected_tonewood_lot_version` to equal the
    current `version` of the lot named by `lot_id`."

    Design: Corner/cross_cutting_complexity_layers/a_second_cut_from_one_lot_must_echo_the_version_the_first_cut_produced
    """
    lot_id = lot_released["lot1"]
    stale = lot_released["lot_v1"]

    first = F.create_billet(api, lot_id, stale, billet_code="BLT-001",
                            board_feet=30.00, grade="AAA")
    assert first["kerf_loss_board_feet"] == 0.90

    after_first = validate_success(api.get_tonewood_lot(lot_id, U.MACHINIST_HEADERS))
    assert after_first["board_feet_unassigned"] == 30.00
    assert after_first["board_feet_available"] == 69.10
    assert after_first["version"] != stale

    validate_error(api.create_billet({
        "billet_code": "BLT-002", "lot_id": lot_id, "board_feet": 20.00,
        "grade": "AAA", "expected_tonewood_lot_version": stale,
    }, U.MACHINIST_HEADERS), E.ERR_STALE_VERSION, 412)

    _, meta = validate_paginated(api.list_billets(U.MACHINIST_HEADERS))
    assert meta["total_count"] == 1

    after_stale = validate_success(api.get_tonewood_lot(lot_id, U.MACHINIST_HEADERS))
    assert after_stale["board_feet_available"] == 69.10
    assert after_stale["board_feet_kerf_loss"] == 0.90
    assert after_stale["status"] == "RELEASED"
    assert after_stale["version"] == after_first["version"]


def test_the_refused_cut_succeeds_unchanged_once_the_client_re_reads_the_lot(api, lot_released):
    """
    The identical body is accepted the moment it carries the version the first cut
    produced, and both cuts then show up in one ledger where the two kerf charges,
    the sawn stock and the standing lumber still add up to everything received.

    PRD: "When the cut is booked, the lot's `board_feet_available` falls by the
    billet's `board_feet` and again by the kerf figure, `board_feet_unassigned`
    rises by the `board_feet`, `board_feet_kerf_loss` rises by the kerf figure, and
    `board_feet_cut` moves with the mirror definition of §2.10."

    Design: Corner/cross_cutting_complexity_layers/a_second_cut_from_one_lot_must_echo_the_version_the_first_cut_produced
    """
    lot_id = lot_released["lot1"]
    F.create_billet(api, lot_id, lot_released["lot_v1"], billet_code="BLT-001",
                    board_feet=30.00, grade="AAA")
    validate_error(api.create_billet({
        "billet_code": "BLT-002", "lot_id": lot_id, "board_feet": 20.00,
        "grade": "AAA", "expected_tonewood_lot_version": lot_released["lot_v1"],
    }, U.MACHINIST_HEADERS), E.ERR_STALE_VERSION, 412)

    fresh = validate_success(
        api.get_tonewood_lot(lot_id, U.MACHINIST_HEADERS))["version"]
    retry = F.create_billet(api, lot_id, fresh, billet_code="BLT-002",
                            board_feet=20.00, grade="AAA")
    assert retry["kerf_loss_board_feet"] == 0.60

    _, meta = validate_paginated(api.list_billets(U.MACHINIST_HEADERS))
    assert meta["total_count"] == 2

    lot = validate_success(api.get_tonewood_lot(lot_id, U.MACHINIST_HEADERS))
    A.assert_lot_ledger(lot, available=48.50, unassigned=50.00, reserved=0.00,
                        consumed=0.00, scrapped=0.00, kerf_loss=1.50)
    A.assert_wood_conserved(lot)


def test_an_option_stacked_on_a_quote_the_client_never_saw_is_refused(api, order_two_options):
    """
    Two selections already sit on this order, so a third is plainly legal and no
    state precondition can explain the refusal; the version echoed is the one the
    order carried before either existing line was added, and the running quote total
    proves the rejected request changed nothing.

    PRD: "Configuring an option on an order requires `expected_build_order_version`
    to equal that order's current `version`."

    Design: Corner/cross_cutting_complexity_layers/stacking_an_option_onto_a_quote_the_client_never_saw_is_refused
    """
    env = order_two_options
    option = F.create_option(api, dict(C.OPTION_PREMIUM_ELECTRONICS))["id"]

    validate_error(api.create_option_selection(env["bo1"], {
        "option_id": option, "quantity": 1,
        "expected_build_order_version": env["bo_v1"],
    }, U.COORDINATOR_3_HEADERS), E.ERR_STALE_VERSION, 412)

    _, meta = validate_paginated(api.list_option_selections(U.COORDINATOR_HEADERS))
    assert meta["total_count"] == 2

    order = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert order["provisional_quote_total_cents"] == 345910


def test_the_third_line_prices_itself_once_the_selection_carries_the_current_version(api, order_two_options):
    """
    With the fresh version the third artisan line is accepted and priced on its own
    before the summation, so the order lands one cent below what summing the raw
    upcharges first would have produced, and the binding total is still unset.

    PRD: "Rounding each line gives 16205, 29705 and 43205, an options subtotal of
    89115 and a total of 389115."

    Design: Corner/cross_cutting_complexity_layers/stacking_an_option_onto_a_quote_the_client_never_saw_is_refused
    """
    env = order_two_options
    option = F.create_option(api, dict(C.OPTION_PREMIUM_ELECTRONICS))["id"]
    validate_error(api.create_option_selection(env["bo1"], {
        "option_id": option, "quantity": 1,
        "expected_build_order_version": env["bo_v1"],
    }, U.COORDINATOR_3_HEADERS), E.ERR_STALE_VERSION, 412)

    fresh = validate_success(
        api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))["version"]
    retry = validate_success(api.create_option_selection(env["bo1"], {
        "option_id": option, "quantity": 1,
        "expected_build_order_version": fresh,
    }, U.COORDINATOR_3_HEADERS), 201)
    assert retry["status"] == "PENDING_APPROVAL"
    assert retry["line_total_cents"] == 43205

    _, meta = validate_paginated(api.list_option_selections(U.COORDINATOR_HEADERS))
    assert meta["total_count"] == 3

    order = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert order["provisional_quote_total_cents"] == 389115
    assert order["binding_quote_total_cents"] is None
    assert order["commercial_status"] == "QUOTED"


NEW_RUN = {"finish_system": "NITRO", "coat_count": 8}


def test_the_replacement_booking_cannot_reuse_the_version_the_first_run_moved(api, order_in_assembly):
    """
    The order has been round the refinish loop and stands back in assembly, so a
    second booking is a correct product operation rather than a state error — and
    the only ground for refusing it is that the version captured before the first
    run is now two writes out of date.

    PRD: "Booking a finish run requires `expected_build_order_version` to equal the
    current `version` of the build order named by `build_order_id`."

    Design: Corner/cross_cutting_complexity_layers/the_replacement_finish_run_in_the_refinish_loop_must_prove_a_fresh_version
    """
    env = order_in_assembly
    stale = env["bo_v3"]
    run = F.create_finish_run(api, env["bo1"], env["fb1"], stale,
                              finish_system="NITRO", coat_count=8)
    assert run["status"] == "SPRAYING"
    assert validate_success(api.get_build_order(
        env["bo1"], U.FINISH_TECH_HEADERS))["build_stage"] == "IN_FINISH"
    assert validate_success(api.get_storage_room(
        env["fb1"], U.FINISH_TECH_HEADERS))["occupied_slots"] == 1

    curing = F.complete_spray(api, run["id"])
    assert curing["status"] == "CURING"
    assert curing["cure_hours"] == 348
    assert curing["cure_ready_at"] == "2026-08-15T12:00:00Z"

    condemned = F.reject_run(api, run["id"], "orange peel across the lower bout")
    assert condemned["status"] == "REJECTED"

    payload = dict(NEW_RUN, build_order_id=env["bo1"], booth_id=env["fb1"],
                   expected_build_order_version=stale)
    validate_error(api.create_finish_run(payload, U.FINISH_TECH_HEADERS),
                   E.ERR_STALE_VERSION, 412)

    _, meta = validate_paginated(api.list_finish_runs(U.FINISH_TECH_HEADERS))
    assert meta["total_count"] == 1
    order = validate_success(api.get_build_order(env["bo1"], U.FINISH_TECH_HEADERS))
    assert order["build_stage"] == "IN_ASSEMBLY"
    assert order["refinish_count"] == 1
    assert validate_success(api.get_storage_room(
        env["fb1"], U.FINISH_TECH_HEADERS))["occupied_slots"] == 0


def test_the_replacement_run_is_booked_on_the_version_the_condemnation_produced(api, order_in_assembly):
    """
    Once the technician re-reads the order the same booking is accepted, which is
    what makes this the one stale-version rule whose endpoint is legitimately called
    twice on a single parent: the instrument goes back into the booth and the slot is
    taken again.

    PRD: "A replacement finish run legitimately supersedes a condemned one under the
    refinish loop of §3.7, so a second booking against the same order is a normal
    product operation rather than a state violation; the stale-version guard is what
    stops a technician from committing a booth window on the strength of an obsolete
    view of the order's finish system, stage and priority."

    Design: Corner/cross_cutting_complexity_layers/the_replacement_finish_run_in_the_refinish_loop_must_prove_a_fresh_version
    """
    env = order_in_assembly
    run = F.create_finish_run(api, env["bo1"], env["fb1"], env["bo_v3"],
                              finish_system="NITRO", coat_count=8)
    F.complete_spray(api, run["id"])
    F.reject_run(api, run["id"], "orange peel across the lower bout")

    fresh = validate_success(
        api.get_build_order(env["bo1"], U.FINISH_TECH_HEADERS))["version"]
    replacement = validate_success(api.create_finish_run(
        dict(NEW_RUN, build_order_id=env["bo1"], booth_id=env["fb1"],
             expected_build_order_version=fresh), U.FINISH_TECH_HEADERS), 201)
    assert replacement["status"] == "SPRAYING"

    _, meta = validate_paginated(api.list_finish_runs(U.FINISH_TECH_HEADERS))
    assert meta["total_count"] == 2
    assert validate_success(api.get_build_order(
        env["bo1"], U.FINISH_TECH_HEADERS))["build_stage"] == "IN_FINISH"
    assert validate_success(api.get_storage_room(
        env["fb1"], U.FINISH_TECH_HEADERS))["occupied_slots"] == 1


def a_third_order_tied_with_the_second(api, env):
    """
    A third plain build identical to BO-2 in every scoring input, holding the
    earliest window of the three on the router.
    """
    order = F.create_order(api, F.order_payload(
        order_code="BO-3", model_code="D28", base_price_cents=300000,
        promised_date="2026-08-20T00:00:00Z", is_custom_shop=False,
        artist_tier="NONE", finish_system="NITRO"), U.COORDINATOR_HEADERS)
    F.confirm_order(api, order["id"], 30000, U.COORDINATOR_HEADERS)
    reservation = F.create_reservation(api, env["cnc1"], "2026-08-02T08:00:00Z",
                                      "2026-08-02T09:00:00Z",
                                      build_order_id=order["id"])["id"]
    return order["id"], reservation


def test_the_highest_score_wins_outright_before_any_tie_arises(api, two_confirmed_orders_on_cnc1):
    """
    Two of the three eligible builds are deliberately identical in every scoring
    input and stand level at thirty-five and a half points, but the signature custom
    build outranks both, so the selector answers on score alone and reports the pool
    it drew from.

    PRD: "Eligible orders are ranked by `priority_score` descending."

    Design: Corner/cross_cutting_complexity_layers/the_selector_breaks_a_score_tie_by_the_earliest_window_not_by_the_older_order
    """
    env = two_confirmed_orders_on_cnc1
    bo3, _ = a_third_order_tied_with_the_second(api, env)

    assert validate_success(api.get_build_order(
        env["bo1"], U.COORDINATOR_HEADERS))["priority_score"] == 69.50
    assert validate_success(api.get_build_order(
        env["bo2"], U.COORDINATOR_HEADERS))["priority_score"] == 35.50
    assert validate_success(api.get_build_order(
        bo3, U.COORDINATOR_HEADERS))["priority_score"] == 35.50

    pick = validate_success(
        api.get_next_build_order(env["cnc1"], U.MACHINIST_HEADERS))
    assert pick["order_code"] == "BO-1"
    assert pick["priority_score"] == 69.50
    assert pick["starts_at"] == "2026-08-03T08:00:00Z"
    assert pick["eligible_count"] == 3


def test_the_tie_goes_to_the_earliest_window_and_not_to_the_older_order(api, two_confirmed_orders_on_cnc1):
    """
    With the leader's window handed back the two level builds must be separated by
    something, and it is the window: the build created last wins because its hold
    opens a day earlier, and only when that hold is released too does the older build
    take the bench.

    PRD: "Ties are broken first by the earliest `starts_at` among that order's `HELD`
    reservations on this station, ascending, and then by the order's own `created_at`,
    ascending."

    Design: Corner/cross_cutting_complexity_layers/the_selector_breaks_a_score_tie_by_the_earliest_window_not_by_the_older_order
    """
    env = two_confirmed_orders_on_cnc1
    _, res3 = a_third_order_tied_with_the_second(api, env)
    F.release_reservation(api, env["resA"])

    second = validate_success(
        api.get_next_build_order(env["cnc1"], U.MACHINIST_HEADERS))
    assert second["order_code"] == "BO-3"
    assert second["priority_score"] == 35.50
    assert second["starts_at"] == "2026-08-02T08:00:00Z"
    assert second["eligible_count"] == 2

    F.release_reservation(api, res3)

    third = validate_success(
        api.get_next_build_order(env["cnc1"], U.MACHINIST_HEADERS))
    assert third["order_code"] == "BO-2"
    assert third["priority_score"] == 35.50
    assert third["starts_at"] == "2026-08-04T08:00:00Z"
    assert third["eligible_count"] == 1
