"""Room housekeeping cycle, folio dispute/resolve loop, checkout and no-show cascades.

Difficulty queue: non_linear_state_machine, transitive_cascade.
Corner queue (state_machines): idempotency, terminal lockdown, preconditions, valid
transitions; plus the night-audit no-show / room-charge cascades.
"""
from test_helpers import (
    api_client as _api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_basic,
    setup_corporate,
    create_hotel,
    create_room_type,
    create_rate_plan,
    create_corporate_account,
    create_guest,
    create_room,
    create_inspected_room,
    create_group_block,
    create_confirmed_reservation,
    create_assigned_reservation,
    create_checked_in_reservation,
    create_checked_out_reservation,
    get_folio_for_reservation,
    open_audit,
    complete_audit,
    run_one_audit,
)
api = _api_client
RM = TEST_USERS["revenue_manager_headers"]
FDA = TEST_USERS["front_desk_headers"]
NA = TEST_USERS["night_auditor_headers"]


def _folio(hotel_id, res_id):
    return get_folio_for_reservation(hotel_id, res_id)


# ===========================================================================
# Difficulty/non_linear_state_machine/room_housekeeping_cycle_dirty_clean_inspected_occupied_dirty
# ===========================================================================
def test_room_occupied_at_checkin_then_dirty_at_checkout():
    """PRD §3.6: "On check-in the assigned room cascades `INSPECTED → OCCUPIED`".
    PRD §3.6: "the assigned room cascades `OCCUPIED → DIRTY`, its `assigned_reservation_id`
    is cleared to null, and its `version` is incremented".

    Design: Difficulty/non_linear_state_machine/room_housekeeping_cycle_dirty_clean_inspected_occupied_dirty
    """
    b = setup_basic()
    res, room = create_checked_in_reservation(b, room_number="301")
    after_checkin = validate_success(api.get_room(room["id"], FDA))
    assert after_checkin["housekeeping_status"] == "OCCUPIED", after_checkin

    validate_success(api.check_out(res["id"], FDA))
    after_checkout = validate_success(api.get_room(room["id"], FDA))
    assert after_checkout["housekeeping_status"] == "DIRTY", after_checkout


def test_room_cycle_closes_dirty_back_to_clean():
    """PRD §3.5: "After a stay, the room returns `DIRTY` and is cleaned `DIRTY → CLEAN`
    and then inspected again, forming the cycle
    `DIRTY → CLEAN → INSPECTED → OCCUPIED → DIRTY`."

    After checkout the room is DIRTY; a DIRTY->CLEAN housekeeping transition closes the cycle.

    Design: Difficulty/non_linear_state_machine/room_housekeeping_cycle_dirty_clean_inspected_occupied_dirty
    """
    b = setup_basic()
    res, room = create_checked_in_reservation(b, room_number="301")
    validate_success(api.check_out(res["id"], FDA))
    dirty = validate_success(api.get_room(room["id"], FDA))
    assert dirty["housekeeping_status"] == "DIRTY", dirty

    cleaned = validate_success(api.room_housekeeping(
        room["id"], {"target": "CLEAN", "expected_room_version": dirty["version"]}, FDA))
    assert cleaned["housekeeping_status"] == "CLEAN", cleaned


# ===========================================================================
# Difficulty/non_linear_state_machine/folio_dispute_then_resolve_revert_loop
# ===========================================================================
def test_folio_dispute_moves_open_to_disputed():
    """PRD §3.6: "A `FrontDeskAgent` disputes an `OPEN` folio, moving its `status`
    `OPEN → DISPUTED`, after which no new incidental postings are accepted and check-out
    is blocked."

    Design: Difficulty/non_linear_state_machine/folio_dispute_then_resolve_revert_loop
    """
    b = setup_basic()
    res = get_success_data(api.create_reservation({
        "hotel_id": b["hotel"]["id"], "guest_id": b["guest"]["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-03"}, FDA))
    folio_id = _folio(b["hotel"]["id"], res["id"])["id"]

    disputed = validate_success(api.dispute_folio(folio_id, FDA))
    assert disputed["status"] == "DISPUTED", disputed


def test_folio_resolve_reverts_disputed_to_open():
    """PRD §3.6: "The agent later resolves the dispute, moving `DISPUTED → OPEN` and
    re-opening the folio for postings and check-out."

    Design: Difficulty/non_linear_state_machine/folio_dispute_then_resolve_revert_loop
    """
    b = setup_basic()
    res = get_success_data(api.create_reservation({
        "hotel_id": b["hotel"]["id"], "guest_id": b["guest"]["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-03"}, FDA))
    folio_id = _folio(b["hotel"]["id"], res["id"])["id"]
    get_success_data(api.dispute_folio(folio_id, FDA))

    resolved = validate_success(api.resolve_folio(folio_id, FDA))
    assert resolved["status"] == "OPEN", resolved


# ===========================================================================
# Difficulty/transitive_cascade/checkout_cascade_room_dirty_and_corporate_ledger_depth3
# ===========================================================================
def test_checkout_cascades_folio_close_room_dirty_and_corporate_ledger():
    """PRD §3.6: "On check-out the folio moves `OPEN → CLOSED` with its final balance
    frozen; the assigned room cascades `OCCUPIED → DIRTY`, its `assigned_reservation_id`
    is cleared to null, and its `version` is incremented; and when the folio's `bill_to`
    is `CORPORATE`, the folio's `balance_cents` is added to the corporate account's
    `outstanding_balance_cents` and that account's `version` is incremented."

    Corporate FLAT+0 base 20000 stay with a 1500 minibar; checkout closes folio (1500),
    sets room DIRTY/unbound, raises outstanding to 1500.

    Design: Difficulty/transitive_cascade/checkout_cascade_room_dirty_and_corporate_ledger_depth3
    """
    b = setup_corporate(credit_limit_cents=100000, base_rate_cents=20000,
                        physical_inventory=2, adjustment_value=0)
    hotel_id = b["hotel"]["id"]
    room = create_inspected_room(hotel_id, b["room_type"]["id"], room_number="401")
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel_id, "guest_id": b["guest"]["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-03"}, FDA))
    folio_id = _folio(hotel_id, res["id"])["id"]
    get_success_data(api.confirm_reservation(res["id"], FDA))
    get_success_data(api.assign_room(res["id"],
        {"room_id": room["id"], "expected_room_version": room["version"]}, FDA))
    get_success_data(api.check_in(res["id"], FDA))
    get_success_data(api.create_incidental({
        "hotel_id": hotel_id, "folio_id": folio_id, "kind": "CHARGE",
        "description": "Minibar", "amount_cents": 1500}, FDA))

    validate_success(api.check_out(res["id"], FDA))

    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["status"] == "CLOSED", folio
    assert folio["balance_cents"] == 1500, folio
    room_after = validate_success(api.get_room(room["id"], FDA))
    assert room_after["housekeeping_status"] == "DIRTY", room_after
    assert room_after["assigned_reservation_id"] is None, room_after
    acct = validate_success(api.get_corporate_account(b["account"]["id"], RM))
    assert acct["outstanding_balance_cents"] == 1500, acct


def test_guest_billed_checkout_cascades_room_dirty_and_folio_close():
    """PRD §3.6: "On check-out the folio moves `OPEN → CLOSED` with its final balance
    frozen; the assigned room cascades `OCCUPIED → DIRTY`, its `assigned_reservation_id`
    is cleared to null, and its `version` is incremented".
    PRD §3.6: "The folio's `bill_to` is `CORPORATE` when the reservation carries a
    `corporate_account_id` and `GUEST` otherwise."

    A GUEST-billed checkout drives the folio-close and room-DIRTY hops of the same cascade;
    bill_to is GUEST, so the corporate-ledger hop does not apply.

    Design: Difficulty/transitive_cascade/checkout_cascade_room_dirty_and_corporate_ledger_depth3
    """
    b = setup_basic(physical_inventory=2)
    res, room = create_checked_in_reservation(b, room_number="402")
    folio_id = _folio(b["hotel"]["id"], res["id"])["id"]
    folio_pre = validate_success(api.get_folio(folio_id, FDA))
    assert folio_pre["bill_to"] == "GUEST", folio_pre

    validate_success(api.check_out(res["id"], FDA))

    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["status"] == "CLOSED", folio
    room_after = validate_success(api.get_room(room["id"], FDA))
    assert room_after["housekeeping_status"] == "DIRTY", room_after
    assert room_after["assigned_reservation_id"] is None, room_after


# ===========================================================================
# Difficulty/transitive_cascade/night_audit_noshow_cascade_charge_and_block_pickup_depth2
# ===========================================================================
def test_night_audit_no_show_posts_charge_and_drops_block_pickup():
    """PRD §3.8: "every reservation that is `CONFIRMED`, arriving today (its
    `arrival_date` equals the `business_date`), and not `CHECKED_IN` is flipped
    `CONFIRMED → NO_SHOW`, a no-show charge is posted to its folio per the rate plan's
    policy, its covered availability is recomputed to release inventory, its group block's
    `picked_up_rooms` is recomputed if it is a pickup, and its folio moves `OPEN → CLOSED`".

    QUEEN base 15000, BAR PCT -10 -> nightly 13500; FULL_STAY 1 night = 13500;
    block pickup count drops to 0.

    Design: Difficulty/transitive_cascade/night_audit_noshow_cascade_charge_and_block_pickup_depth2
    """
    hotel = create_hotel(current_business_date="2026-07-10", overbooking_allowance_pct=0.0)
    queen = create_room_type(hotel["id"], code="QUEEN", tier_rank=1,
                             physical_inventory=5, base_rate_cents=15000)
    grp = create_rate_plan(hotel["id"], code="GRP", kind="BAR",
                           adjustment_mode="PCT", adjustment_value=-10,
                           no_show_policy="FULL_STAY")
    block = create_group_block(hotel["id"], queen["id"], grp["id"], block_name="Conf",
                               arrival_date="2026-07-10", departure_date="2026-07-11",
                               cutoff_date="2026-07-20", blocked_rooms=3)
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": queen["id"],
        "rate_plan_id": grp["id"], "arrival_date": "2026-07-10",
        "departure_date": "2026-07-11", "group_block_id": block["id"],
        "expected_group_block_version": block["version"]}, FDA))
    folio_id = _folio(hotel["id"], res["id"])["id"]
    get_success_data(api.confirm_reservation(res["id"], FDA))
    run_one_audit(hotel["id"])

    res_after = validate_success(api.get_reservation(res["id"], FDA))
    assert res_after["status"] == "NO_SHOW", res_after
    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["room_charges_cents"] == 13500, folio
    block_after = validate_success(api.get_group_block(block["id"], RM))
    assert block_after["picked_up_rooms"] == 0, block_after


def test_night_audit_no_show_closes_folio_and_counts_sweep():
    """PRD §3.8: "its folio moves `OPEN → CLOSED`; the run's `no_show_count` records how
    many were swept."

    The audit-complete -> no-show hop closes the no-showed reservation's folio and the run
    records no_show_count == 1 (the second-order effect of the same depth-2 cascade).

    Design: Difficulty/transitive_cascade/night_audit_noshow_cascade_charge_and_block_pickup_depth2
    """
    hotel = create_hotel(current_business_date="2026-07-10", overbooking_allowance_pct=0.0)
    queen = create_room_type(hotel["id"], code="QUEEN", tier_rank=1,
                             physical_inventory=5, base_rate_cents=15000)
    grp = create_rate_plan(hotel["id"], code="GRP", kind="BAR",
                           adjustment_mode="PCT", adjustment_value=-10,
                           no_show_policy="FULL_STAY")
    block = create_group_block(hotel["id"], queen["id"], grp["id"], block_name="Conf",
                               arrival_date="2026-07-10", departure_date="2026-07-11",
                               cutoff_date="2026-07-20", blocked_rooms=3)
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": queen["id"],
        "rate_plan_id": grp["id"], "arrival_date": "2026-07-10",
        "departure_date": "2026-07-11", "group_block_id": block["id"],
        "expected_group_block_version": block["version"]}, FDA))
    folio_id = _folio(hotel["id"], res["id"])["id"]
    get_success_data(api.confirm_reservation(res["id"], FDA))
    run = open_audit(hotel["id"])
    completed = complete_audit(hotel["id"], run["id"])

    assert completed["no_show_count"] == 1, completed
    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["status"] == "CLOSED", folio


# ===========================================================================
# Corner/state_machines/confirm_already_confirmed_returns_invalid_state
# ===========================================================================
def test_confirm_already_confirmed_returns_invalid_state():
    """PRD §3.6: "Confirming a reservation not in `HELD` is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/confirm_already_confirmed_returns_invalid_state
    """
    b = setup_basic()
    res = create_confirmed_reservation(b)
    resp = api.confirm_reservation(res["id"], FDA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    res_after = validate_success(api.get_reservation(res["id"], FDA))
    assert res_after["status"] == "CONFIRMED", res_after


# ===========================================================================
# Corner/state_machines/cancel_checked_out_terminal_returns_invalid_state
# ===========================================================================
def test_cancel_checked_out_terminal_returns_invalid_state():
    """PRD §3.3: "Re-triggering cancel on a reservation already in a terminal state is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/cancel_checked_out_terminal_returns_invalid_state
    """
    b = setup_basic()
    res, _room = create_checked_out_reservation(b, room_number="701")
    resp = api.cancel_reservation(res["id"], FDA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    res_after = validate_success(api.get_reservation(res["id"], FDA))
    assert res_after["status"] == "CHECKED_OUT", res_after


# ===========================================================================
# Corner/state_machines/checkin_before_arrival_date_returns_arrival_not_reached
# ===========================================================================
def test_checkin_before_arrival_date_returns_arrival_not_reached():
    """PRD §3.6: "the property's `current_business_date` on or after the reservation's
    `arrival_date` (otherwise `ERR_ARRIVAL_NOT_REACHED`, HTTP 409)."

    Hotel date 07-01, reservation arriving 07-05, room assigned + INSPECTED.

    Design: Corner/state_machines/checkin_before_arrival_date_returns_arrival_not_reached
    """
    b = setup_basic(current_business_date="2026-07-01")
    res, _room = create_assigned_reservation(b, room_number="801",
                                             arrival_date="2026-07-05",
                                             departure_date="2026-07-07")
    resp = api.check_in(res["id"], FDA)
    validate_error(resp, ApiErrorId.ERR_ARRIVAL_NOT_REACHED.value)


# ===========================================================================
# Corner/state_machines/checkin_no_room_assigned_returns_no_room_assigned
# ===========================================================================
def test_checkin_without_assigned_room_returns_no_room_assigned():
    """PRD §3.6: "It requires posture `OPEN`, a non-null `assigned_room_id` (otherwise
    `ERR_NO_ROOM_ASSIGNED`, HTTP 409)".

    Design: Corner/state_machines/checkin_no_room_assigned_returns_no_room_assigned
    """
    b = setup_basic(current_business_date="2026-07-01")
    res = create_confirmed_reservation(b, arrival_date="2026-07-01",
                                       departure_date="2026-07-02")
    resp = api.check_in(res["id"], FDA)
    validate_error(resp, ApiErrorId.ERR_NO_ROOM_ASSIGNED.value)


# ===========================================================================
# Corner/state_machines/open_second_audit_while_in_progress_returns_audit_already_running
# ===========================================================================
def test_open_second_audit_while_in_progress_returns_audit_already_running():
    """PRD §3.8: "Opening a second audit while one is already `IN_PROGRESS` for the
    property is rejected with `ERR_AUDIT_ALREADY_RUNNING` (HTTP 409)."

    Design: Corner/state_machines/open_second_audit_while_in_progress_returns_audit_already_running
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    open_audit(hotel["id"])
    hv = validate_success(api.get_hotel(hotel["id"], NA))["version"]
    resp = api.create_night_audit_run(
        {"hotel_id": hotel["id"], "expected_hotel_version": hv}, NA)
    validate_error(resp, ApiErrorId.ERR_AUDIT_ALREADY_RUNNING.value)
    hotel_after = validate_success(api.get_hotel(hotel["id"], NA))
    assert hotel_after["posture"] == "AUDIT_LOCK", hotel_after


# ===========================================================================
# Corner/state_machines/out_of_order_room_with_assignment_returns_room_not_assignable
# ===========================================================================
def test_out_of_order_on_assigned_room_returns_room_not_assignable():
    """PRD §3.5: "A `RevenueManager` moves a room to `OUT_OF_ORDER` from any of `DIRTY`,
    `CLEAN`, or `INSPECTED`, provided the room's `assigned_reservation_id` is null; a room
    currently bound to a reservation cannot be taken out of order and the attempt is
    rejected with `ERR_ROOM_NOT_ASSIGNABLE` (HTTP 409)."

    Design: Corner/state_machines/out_of_order_room_with_assignment_returns_room_not_assignable
    """
    b = setup_basic()
    res, room = create_assigned_reservation(b, room_number="901")
    room_now = validate_success(api.get_room(room["id"], FDA))
    resp = api.room_housekeeping(room["id"],
        {"target": "OUT_OF_ORDER", "expected_room_version": room_now["version"]}, RM)
    validate_error(resp, ApiErrorId.ERR_ROOM_NOT_ASSIGNABLE.value)


# ===========================================================================
# Corner/state_machines/corporate_reinstate_then_active_transition
# ===========================================================================
def test_corporate_reinstate_returns_account_to_active():
    """PRD §3.1: "A `RevenueManager` may suspend an account, moving its `status` from
    `ACTIVE` to `SUSPENDED`, and may reinstate a suspended account, moving its `status`
    back to `ACTIVE`; both transitions require `expected_corporate_account_version` and
    each increments the account's `version`."

    Design: Corner/state_machines/corporate_reinstate_then_active_transition
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    acct = create_corporate_account(hotel["id"], name="Stark", credit_limit_cents=50000)
    suspended = validate_success(api.suspend_corporate_account(
        acct["id"], {"expected_corporate_account_version": acct["version"]}, RM))
    assert suspended["status"] == "SUSPENDED", suspended
    reinstated = validate_success(api.reinstate_corporate_account(
        acct["id"], {"expected_corporate_account_version": suspended["version"]}, RM))
    assert reinstated["status"] == "ACTIVE", reinstated
