"""Validation and priority-ordering tests: the pinned validation order from PRD
§2.9, plus individual create-time validation errors in isolation.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_visitor_headers,
    set_clock,
    create_garden,
    create_plan,
    create_time_slot,
    create_nonmember_reservation,
    setup_household_member_with_slot,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]


# =============================================================================
# priority_pair_validation_conflict — invalid state beats slot capacity
# =============================================================================
def test_checkin_cancelled_reservation_on_full_slot_returns_invalid_state(api):
    """PRD §2.9: "then the target's state validity for the requested transition
    (`ERR_INVALID_STATE`)... then slot capacity (`ERR_SLOT_CAPACITY_EXCEEDED`)...
    An earlier check that fires masks every later one".

    A check-in on an already-CANCELLED reservation, on a slot also at capacity,
    returns ERR_INVALID_STATE (priority 6) not ERR_SLOT_CAPACITY_EXCEEDED
    (priority 14).

    Design: Difficulty/priority_pair_validation_conflict/ppvc_invalid_state_beats_slot_capacity
    """
    garden = create_garden(name="Iris Bend")
    slot = create_time_slot(garden["id"], "2026-04-04T10:00:00Z", "2026-04-04T12:00:00Z",
                           capacity=1, ga_price_cents=2000)
    # Fill then cancel to vacate; then fill with x and y; cancel x so x is the
    # CANCELLED reservation while the slot is held to capacity by y.
    res_x = create_nonmember_reservation(garden["id"], slot["id"], paid_heads=1)
    validate_success(api.cancel_reservation(res_x["id"], make_visitor_headers("anon-x")))
    res_y = create_nonmember_reservation(garden["id"], slot["id"], paid_heads=1)
    assert res_y["status"] == "HELD"
    set_clock("2026-04-04T10:30:00Z")
    resp = api.check_in_reservation(res_x["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_checkin_cancelled_reservation_returns_invalid_state_isolated(api):
    """PRD §3.3: "Only a `HELD` reservation may be cancelled or checked in;
    acting on a terminal reservation yields `ERR_INVALID_STATE`."

    Isolating the state check: a check-in on a CANCELLED reservation (clock inside
    the window, slot below capacity) returns ERR_INVALID_STATE — the same outcome
    the priority pair asserts wins.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_invalid_state_beats_slot_capacity
    """
    garden = create_garden(name="Iris Bend Iso")
    slot = create_time_slot(garden["id"], "2026-04-04T10:00:00Z", "2026-04-04T12:00:00Z",
                           capacity=5, ga_price_cents=2000)
    res = create_nonmember_reservation(garden["id"], slot["id"], paid_heads=1)
    validate_success(api.cancel_reservation(res["id"], make_visitor_headers("anon-iso")))
    set_clock("2026-04-04T10:30:00Z")
    resp = api.check_in_reservation(res["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# =============================================================================
# priority_pair_validation_conflict — cross-garden ref beats household cap
# =============================================================================
def test_cross_garden_plan_with_oversized_household_returns_cross_garden(api):
    """PRD §2.9: "then same-garden referential integrity
    (`ERR_CROSS_GARDEN_REFERENCE`)... then the household-cap check
    (`ERR_HOUSEHOLD_CAP_EXCEEDED`)". PRD §2.7: "A reference whose target lives in
    a different garden is rejected with `ERR_CROSS_GARDEN_REFERENCE` (HTTP 422)."

    Creating a membership in Garden A referencing Garden B's plan AND passing 4
    household names (over cap 2) returns ERR_CROSS_GARDEN_REFERENCE (priority 5),
    not ERR_HOUSEHOLD_CAP_EXCEEDED (priority 10).

    Design: Difficulty/priority_pair_validation_conflict/ppvc_cross_garden_ref_beats_household_cap
    """
    garden_a = create_garden(name="Jasmine A", household_member_cap=2)
    garden_b = create_garden(name="Jasmine B", household_member_cap=2)
    plan_b = create_plan(garden_b["id"], tier="HOUSEHOLD", annual_fee_cents=9000)
    resp = api.create_membership(
        {"garden_id": garden_a["id"], "plan_id": plan_b["id"], "primary_member_name": "Kit",
         "household_member_names": ["a", "b", "c", "d"], "auto_renew": False},
        make_visitor_headers("anon-kit"),
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_GARDEN_REFERENCE.value, expected_status=422)


def test_household_cap_exceeded_in_isolation_returns_household_cap(api):
    """PRD §3.2: "for a `HOUSEHOLD` plan the number of entries in
    `household_member_names` must not exceed the garden's `household_member_cap`...
    A roster that violates either rule is rejected with
    `ERR_HOUSEHOLD_CAP_EXCEEDED`".

    Isolating the household-cap check (no cross-garden confound): a same-garden
    HOUSEHOLD membership with 3 names over cap 2 returns ERR_HOUSEHOLD_CAP_EXCEEDED
    — the later-priority error that the cross-garden pair masks.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_cross_garden_ref_beats_household_cap
    """
    garden = create_garden(name="Jasmine Solo", household_member_cap=2)
    plan = create_plan(garden["id"], tier="HOUSEHOLD", annual_fee_cents=9000)
    resp = api.create_membership(
        {"garden_id": garden["id"], "plan_id": plan["id"], "primary_member_name": "Solo",
         "household_member_names": ["a", "b", "c"], "auto_renew": False},
        make_visitor_headers("anon-solo"),
    )
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_CAP_EXCEEDED.value, expected_status=422)


# =============================================================================
# Corner: validations section
# =============================================================================
def test_time_slot_invalid_window_rejected(api):
    """PRD §3.1: "an exclusive window end `ends_at` that must be strictly later
    than `starts_at`". PRD §2.9 names `ERR_INVALID_WINDOW` for window
    well-formedness, and §5 maps it to 422.

    A time slot with ends_at <= starts_at is rejected with ERR_INVALID_WINDOW.

    Design: Corner/validations/reservation_invalid_window_already_implied_use_rental
    """
    garden = create_garden(name="Lobelia Lane")
    resp = api.create_time_slot(
        {"garden_id": garden["id"], "starts_at": "2026-04-02T12:00:00Z",
         "ends_at": "2026-04-02T10:00:00Z", "capacity": 5, "ga_price_cents": 2000}, STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value, expected_status=422)


def test_reservation_insufficient_guest_passes_rejected(api):
    """PRD §3.3: "Guest heads additionally require sufficient allotment —
    `guest_heads` must not exceed the membership's `guest_passes_remaining` — or
    the create fails with `ERR_INSUFFICIENT_GUEST_PASSES`."

    HOUSEHOLD membership with grant 4; a reservation claiming 5 guest_heads is
    rejected.

    Design: Corner/validations/reservation_insufficient_guest_passes_returns_409
    """
    garden, plan, membership, slot = setup_household_member_with_slot(
        guest_pass_grant_household=4, slot_capacity=10,
        slot_starts="2026-04-09T10:00:00Z", slot_ends="2026-04-09T12:00:00Z",
    )
    m_id = membership["id"]
    resp = api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "membership_id": m_id,
         "guest_heads": 5, "expected_membership_version": membership["version"]},
        make_visitor_headers(m_id),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_GUEST_PASSES.value, expected_status=409)


def test_reciprocal_flag_without_network_rejected(api):
    """PRD §3.3: "When `reciprocal` is set, the garden must actually belong to a
    network (its `reciprocal_network_code` must be non-empty)... otherwise the
    request is rejected with `ERR_RECIPROCAL_NOT_ELIGIBLE`."

    A reciprocal reservation at a garden with an empty network code is rejected.

    Design: Corner/validations/reciprocal_flag_without_network_returns_not_eligible
    """
    garden = create_garden(name="Narcissus Niche")
    slot = create_time_slot(garden["id"], "2026-04-10T10:00:00Z", "2026-04-10T12:00:00Z",
                           capacity=10, ga_price_cents=2000)
    resp = api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "paid_heads": 1, "reciprocal": True},
        make_visitor_headers("anon-rec"),
    )
    validate_error(resp, ApiErrorId.ERR_RECIPROCAL_NOT_ELIGIBLE.value, expected_status=422)


def test_reservation_member_heads_without_membership_rejected(api):
    """PRD §3.3: "`member_heads` or `guest_heads` may not be claimed without an
    attached membership; any of these defects yields `ERR_INVALID_HEAD_SPLIT`."

    A reservation claiming member_heads 2 with no membership_id is rejected.

    Design: Corner/validations/reservation_member_heads_without_membership_returns_invalid_head_split
    """
    garden = create_garden(name="Orchid Outlook")
    slot = create_time_slot(garden["id"], "2026-04-11T10:00:00Z", "2026-04-11T12:00:00Z",
                           capacity=10, ga_price_cents=2000)
    resp = api.create_reservation(
        {"garden_id": garden["id"], "time_slot_id": slot["id"], "member_heads": 2},
        make_visitor_headers("anon-bad"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_HEAD_SPLIT.value, expected_status=422)


def test_household_three_names_over_cap_two_rejected(api):
    """PRD §3.2: "for a `HOUSEHOLD` plan the number of entries in
    `household_member_names` must not exceed the garden's `household_member_cap`".

    Same-garden HOUSEHOLD membership with 3 names where cap is 2 -> rejected
    (no cross-garden confound).

    Design: Corner/validations/household_cap_exceeded_already_isolated
    """
    garden = create_garden(name="Primrose Park", household_member_cap=2)
    plan = create_plan(garden["id"], tier="HOUSEHOLD", annual_fee_cents=9000)
    resp = api.create_membership(
        {"garden_id": garden["id"], "plan_id": plan["id"], "primary_member_name": "Pat",
         "household_member_names": ["a", "b", "c"], "auto_renew": False},
        make_visitor_headers("anon-pat"),
    )
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_CAP_EXCEEDED.value, expected_status=422)


def test_household_exactly_at_cap_succeeds(api):
    """PRD §3.2: "the number of entries in `household_member_names` must not
    exceed the garden's `household_member_cap`". PRD §3.2: "A freshly created
    membership lands in `PENDING` status".

    A HOUSEHOLD membership with exactly cap (2) names is accepted (boundary
    == cap allowed) and lands PENDING.

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_household_cap_boundary
    """
    garden = create_garden(name="Dianthus Down", household_member_cap=2)
    plan = create_plan(garden["id"], tier="HOUSEHOLD", annual_fee_cents=9000)
    membership = validate_success(api.create_membership(
        {"garden_id": garden["id"], "plan_id": plan["id"], "primary_member_name": "Dot",
         "household_member_names": ["a", "b"], "auto_renew": False},
        make_visitor_headers("anon-dot"),
    ), expected_status=201)
    assert membership["status"] == "PENDING"
