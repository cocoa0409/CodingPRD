"""Confirmation gates and validation ordering: state-vs-safety and safety-vs-fiscal
precedence, the deposit boundary, and the cross-entity preconditions that gate
confirmation (host assignment, add-on staffing, waiver signability).
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_config, create_quote_draft_booking, hold_booking, add_addon, add_waiver,
    sign_waiver, create_held_booking, create_staff, assign_staff, take_payment,
    sign_n_waivers,
)

COORD = "coordinator_headers"


# ─── Difficulty: priority_pair_validation_conflict / ppvc_state_beats_waiver_safety

def test_confirm_quote_draft_returns_state_error_not_waiver(api, coordinator_headers):
    """PRD 2.8: "(6) the target entity being in a state that admits the requested
    transition;" precedes "(8) waiver completeness for confirmation;" and "Earlier
    checks mask later ones".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_waiver_safety
    """
    venue, room, package = setup_config(included_children=8)
    # QUOTE_DRAFT (never held), zero signed waivers: both the state check and the
    # waiver-completeness check would fail.
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    res = api.confirm_booking(bid, coordinator_headers)
    validate_error(res, "ERR_INVALID_STATE")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "QUOTE_DRAFT"


def test_confirm_cancelled_booking_returns_state_error(api, coordinator_headers):
    """PRD 2.8: "(6) the target entity being in a state that admits the requested
    transition;" precedes "(8) waiver completeness for confirmation;" and "Earlier
    checks mask later ones".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_waiver_safety
    """
    venue, room, package = setup_config(included_children=8)
    # CANCELLED (terminal, never held, zero signed waivers): the state check (6) fires
    # before any waiver-completeness check (8).
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    validate_success(api.cancel_booking(bid, coordinator_headers), 200)
    res = api.confirm_booking(bid, coordinator_headers)
    validate_error(res, "ERR_INVALID_STATE")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "CANCELLED"


# ─── Difficulty: priority_pair_validation_conflict / ppvc_staffing_safety_beats_deposit_fiscal

def test_confirm_missing_host_returns_staffing_error_not_deposit(api, coordinator_headers):
    """PRD 2.8: "(9) staffing completeness for confirmation;" precedes "(13) fiscal
    gates for deposit, balance, and refund magnitude;" and "Earlier checks mask later
    ones".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_staffing_safety_beats_deposit_fiscal
    """
    venue, room, package = setup_config(included_children=1)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=1)
    bid = booking["id"]
    hold_booking(bid)
    # Waivers complete, but no host assigned (priority 9) AND deposit unpaid (priority 13).
    waiver = add_waiver(bid, child_name="c1")
    sign_waiver(bid, waiver["id"])
    res = api.confirm_booking(bid, coordinator_headers)
    validate_error(res, "ERR_HOST_NOT_ASSIGNED")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "HELD"


def test_confirm_missing_addon_staff_returns_staffing_error_not_deposit(api, coordinator_headers):
    """PRD 2.8: "(9) staffing completeness for confirmation;" precedes "(13) fiscal
    gates for deposit, balance, and refund magnitude;" and "Earlier checks mask later
    ones".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_staffing_safety_beats_deposit_fiscal
    """
    venue, room, package = setup_config(base_price_cents=30000, included_children=1)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=1)
    bid = booking["id"]
    add_addon(bid, "CHARACTER", 12000)  # requires an ENTERTAINER
    hold_booking(bid)
    host = create_staff(venue["id"], "Host H", ["HOST"])
    assign_staff(bid, host["id"], "HOST")  # host present, entertainer missing (priority 9)
    waiver = add_waiver(bid, child_name="c1")
    sign_waiver(bid, waiver["id"])
    # No payment at all: the deposit gate (priority 13) would also fail, but staffing wins.
    res = api.confirm_booking(bid, coordinator_headers)
    validate_error(res, "ERR_ADDON_STAFF_MISSING")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "HELD"


# ─── Difficulty: boundary_precision_check / bpc_deposit_gate_exact_equal ───────

def test_confirm_with_exact_deposit_succeeds(api, coordinator_headers):
    """PRD 3.8: "The deposit gate must be met: `amount_paid_cents` must be at least
    `deposit_due_cents`, or confirmation is rejected with `ERR_DEPOSIT_NOT_MET`".

    Design: Difficulty/boundary_precision_check/bpc_deposit_gate_exact_equal
    """
    venue, room, package = setup_config(
        base_price_cents=30000, included_children=1, deposit_pct=0.25)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=1)
    bid = booking["id"]
    add_addon(bid, "CAKE", 4500)
    add_addon(bid, "CHARACTER", 12000)  # quote 46500, deposit ceil(11625.0)=11625
    hold_booking(bid)
    host = create_staff(venue["id"], "Host H", ["HOST"])
    assign_staff(bid, host["id"], "HOST")
    cook = create_staff(venue["id"], "Cook C", ["COOK"])
    assign_staff(bid, cook["id"], "COOK")
    ent = create_staff(venue["id"], "Ent E", ["ENTERTAINER"])
    assign_staff(bid, ent["id"], "ENTERTAINER")
    waiver = add_waiver(bid, child_name="c1")
    sign_waiver(bid, waiver["id"])
    take_payment(bid, 11625, direction="CHARGE", purpose="DEPOSIT")

    confirmed = validate_success(api.confirm_booking(bid, coordinator_headers), 200)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["amount_paid_cents"] == 11625
    assert confirmed["payment_status"] == "DEPOSIT_PAID"


def test_confirm_one_cent_below_deposit_rejected(api, coordinator_headers):
    """PRD 3.8: "The deposit gate must be met: `amount_paid_cents` must be at least
    `deposit_due_cents`, or confirmation is rejected with `ERR_DEPOSIT_NOT_MET`".

    Design: Difficulty/boundary_precision_check/bpc_deposit_gate_exact_equal
    """
    venue, room, package = setup_config(
        base_price_cents=30000, included_children=1, deposit_pct=0.25)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=1)
    bid = booking["id"]
    add_addon(bid, "CAKE", 4500)
    add_addon(bid, "CHARACTER", 12000)  # deposit_due 11625
    hold_booking(bid)
    host = create_staff(venue["id"], "Host H", ["HOST"])
    assign_staff(bid, host["id"], "HOST")
    cook = create_staff(venue["id"], "Cook C", ["COOK"])
    assign_staff(bid, cook["id"], "COOK")
    ent = create_staff(venue["id"], "Ent E", ["ENTERTAINER"])
    assign_staff(bid, ent["id"], "ENTERTAINER")
    waiver = add_waiver(bid, child_name="c1")
    sign_waiver(bid, waiver["id"])
    take_payment(bid, 11624, direction="CHARGE", purpose="DEPOSIT")  # one cent short

    res = api.confirm_booking(bid, coordinator_headers)
    validate_error(res, "ERR_DEPOSIT_NOT_MET")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "HELD"


# ─── Difficulty: boundary_precision_check / bpc_capacity_equal_max_ok ──────────

def test_hold_with_headcount_equal_max_capacity_ok(api, coordinator_headers):
    """PRD 3.7: "The committed head count — children plus adults — must not exceed the
    room's `max_capacity`, or the hold is rejected with `ERR_ROOM_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/bpc_capacity_equal_max_ok
    """
    venue, room, package = setup_config(max_capacity=10, included_children=8)
    booking = create_quote_draft_booking(room["id"], package["id"],
                                         children_count=8, adults_count=2)
    held = validate_success(api.hold_booking(booking["id"], coordinator_headers), 200)
    assert held["status"] == "HELD"
    assert held["headcount_committed"] == 10


def test_hold_with_headcount_above_max_capacity_rejected(api, coordinator_headers):
    """PRD 3.7: "The committed head count — children plus adults — must not exceed the
    room's `max_capacity`, or the hold is rejected with `ERR_ROOM_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/bpc_capacity_equal_max_ok
    """
    venue, room, package = setup_config(max_capacity=10, included_children=8)
    booking = create_quote_draft_booking(room["id"], package["id"],
                                         children_count=8, adults_count=3)  # total 11 > 10
    res = api.hold_booking(booking["id"], coordinator_headers)
    validate_error(res, "ERR_ROOM_CAPACITY_EXCEEDED")
    booking = validate_success(api.get_booking(booking["id"], coordinator_headers), 200)
    assert booking["status"] == "QUOTE_DRAFT"


# ─── Difficulty: cross_entity_state_dependency / cesd_confirm_requires_assigned_host

def test_confirm_fails_after_host_released(api, coordinator_headers):
    """PRD 3.8: "exactly one `ASSIGNED` staff assignment with `role_on_event` of
    `HOST` must exist, or confirmation is rejected with `ERR_HOST_NOT_ASSIGNED`".

    Design: Difficulty/cross_entity_state_dependency/cesd_confirm_requires_assigned_host
    """
    venue, room, package = setup_config(included_children=1)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=1)
    bid = booking["id"]
    hold_booking(bid)
    host = create_staff(venue["id"], "Host H", ["HOST"])
    assignment = assign_staff(bid, host["id"], "HOST")
    waiver = add_waiver(bid, child_name="c1")
    sign_waiver(bid, waiver["id"])
    take_payment(bid, 7500, direction="CHARGE", purpose="DEPOSIT")
    # Release the host (booking is HELD, not CONFIRMED, so release is allowed).
    validate_success(api.release_staff_assignment(bid, assignment["id"], coordinator_headers), 200)

    res = api.confirm_booking(bid, coordinator_headers)
    validate_error(res, "ERR_HOST_NOT_ASSIGNED")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "HELD"


def test_confirm_succeeds_with_assigned_host(api, coordinator_headers):
    """PRD 3.8: "exactly one `ASSIGNED` staff assignment with `role_on_event` of
    `HOST` must exist, or confirmation is rejected with `ERR_HOST_NOT_ASSIGNED`".

    Design: Difficulty/cross_entity_state_dependency/cesd_confirm_requires_assigned_host
    """
    venue, room, package = setup_config(base_price_cents=30000, included_children=1)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=1)
    bid = booking["id"]
    hold_booking(bid)
    host = create_staff(venue["id"], "Host H", ["HOST"])
    assign_staff(bid, host["id"], "HOST")  # ASSIGNED host present
    waiver = add_waiver(bid, child_name="c1")
    sign_waiver(bid, waiver["id"])
    take_payment(bid, 7500, direction="CHARGE", purpose="DEPOSIT")
    confirmed = validate_success(api.confirm_booking(bid, coordinator_headers), 200)
    assert confirmed["status"] == "CONFIRMED"


# ─── Difficulty: cross_entity_state_dependency / cesd_waiver_sign_requires_signable_booking

def test_sign_waiver_on_quote_draft_rejected(api, coordinator_headers):
    """PRD 3.5: "Signing is permitted only while the parent booking is in `HELD`,
    `CONFIRMED`, `WEATHER_HOLD`, or `RESCHEDULED`; attempting to sign against a booking
    in any other state is rejected with `ERR_BOOKING_NOT_SIGNABLE`".

    Design: Difficulty/cross_entity_state_dependency/cesd_waiver_sign_requires_signable_booking
    """
    venue, room, package = setup_config(included_children=8)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    waiver = add_waiver(bid, child_name="c1")  # booking still QUOTE_DRAFT
    res = api.sign_waiver(bid, waiver["id"], {"guardian_signature": "sig"}, coordinator_headers)
    validate_error(res, "ERR_BOOKING_NOT_SIGNABLE")
    waivers = validate_success(api.get_booking(bid, coordinator_headers), 200)
    # Confirm the waiver itself stayed DRAFT.
    from test_helpers import validate_paginated
    waiver_list, _ = validate_paginated(api.list_waivers(bid, coordinator_headers))
    assert [w for w in waiver_list if w["id"] == waiver["id"]][0]["status"] == "DRAFT"


def test_sign_waiver_on_held_booking_succeeds(api, coordinator_headers):
    """PRD 3.5: "Signing is permitted only while the parent booking is in `HELD`,
    `CONFIRMED`, `WEATHER_HOLD`, or `RESCHEDULED`".

    Design: Difficulty/cross_entity_state_dependency/cesd_waiver_sign_requires_signable_booking
    """
    venue, room, package = setup_config(included_children=8)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    hold_booking(bid)  # now HELD -> signable
    waiver = add_waiver(bid, child_name="c1")
    signed = validate_success(
        api.sign_waiver(bid, waiver["id"], {"guardian_signature": "sig"}, coordinator_headers), 200)
    assert signed["status"] == "SIGNED"


# ─── Corner: endpoints / addon_staff_missing_for_character_on_confirm ──────────

def test_confirm_with_character_addon_missing_entertainer_rejected(api, coordinator_headers):
    """PRD 3.8: "for every active add-on whose `requires_skill` is not `NONE`, an
    `ASSIGNED` assignment with the matching `role_on_event` must exist — a character
    add-on needs an entertainer and a cake add-on needs a cook — or confirmation is
    rejected with `ERR_ADDON_STAFF_MISSING`."

    Design: Corner/endpoints/addon_staff_missing_for_character_on_confirm
    """
    venue, room, package = setup_config(base_price_cents=30000, included_children=1)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=1)
    bid = booking["id"]
    add_addon(bid, "CHARACTER", 12000)
    hold_booking(bid)
    host = create_staff(venue["id"], "Host H", ["HOST"])
    assign_staff(bid, host["id"], "HOST")  # host present, but NO entertainer
    waiver = add_waiver(bid, child_name="c1")
    sign_waiver(bid, waiver["id"])
    take_payment(bid, 42000, direction="CHARGE", purpose="BALANCE")

    res = api.confirm_booking(bid, coordinator_headers)
    validate_error(res, "ERR_ADDON_STAFF_MISSING")
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["status"] == "HELD"
