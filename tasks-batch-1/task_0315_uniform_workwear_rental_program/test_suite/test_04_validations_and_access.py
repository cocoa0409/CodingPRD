"""Validation precedence, cross-entity gating, interval geometries, the empty-soil
boundary, body/field validation, role-based access control, and triggerable errors.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    build_user_headers,
    TEST_USERS,
    setup_account_on_hold,
    setup_assigned_garment,
    setup_provisional_finalized_visit,
    make_account,
    make_garment_type,
    make_wearer,
    make_garment,
    make_assignment,
    make_route,
    make_route_stop,
    setup_route_stop_for_account,
    make_service_visit,
    get_garment,
    get_wearer,
    create_route_stop_payload,
    create_wearer_payload,
    create_garment_payload,
    create_account_payload,
    pickup_payload,
    apply_emblem_payload,
    reconcile_payload,
)

ADMIN = TEST_USERS["program_admin_headers"]
MANAGER = TEST_USERS["account_manager_headers"]
DRIVER = TEST_USERS["route_driver_headers"]


# ─── Queue A: priority_pair_validation_conflict ───────────────────────────

def test_on_hold_beats_wearer_not_active_on_assignment(api):
    """PRD §2.9: "(6) the account-on-hold safety gate, else `ERR_ACCOUNT_ON_HOLD`;
    (7) wearer-active constraint on assignment, else `ERR_WEARER_NOT_ACTIVE`;
    (8) the wearer-has-garments removal constraint, else `ERR_WEARER_HAS_GARMENTS`;"

    Design: Difficulty/priority_pair_validation_conflict/on_hold_account_beats_wearer_not_active_on_assignment
    """
    # Ramp the spare wearer down BEFORE the hold (ramp-down is blocked on an
    # ON_HOLD account), so the assignment also violates the wearer-active rule.
    ctx = setup_account_on_hold(ramp_spare_wearer=True)
    # Account is ON_HOLD AND the wearer is RAMP_DOWN — both priority 6 and 7 are violated.
    res = api.create_assignment(
        {"garment_id": ctx["spare_garment"]["id"], "wearer_id": ctx["spare_wearer"]["id"]},
        MANAGER,
    )
    validate_error(res, "ERR_ACCOUNT_ON_HOLD", expected_status=409)


def test_on_hold_rejection_leaves_garment_unassigned(api):
    """PRD §2.9: "(6) the account-on-hold safety gate, else `ERR_ACCOUNT_ON_HOLD`;
    (7) wearer-active constraint on assignment, else `ERR_WEARER_NOT_ACTIVE`;
    (8) the wearer-has-garments removal constraint, else `ERR_WEARER_HAS_GARMENTS`;"
    PRD §3.4: "When all gates pass, the assignment is created in `ASSIGNED` status, the
    garment's `lifecycle_status` advances `IN_STOCK → ASSIGNED`..."

    Design: Difficulty/priority_pair_validation_conflict/on_hold_account_beats_wearer_not_active_on_assignment
    """
    # Ramp the spare wearer down BEFORE the hold (ramp-down is blocked on an
    # ON_HOLD account), so the assignment also violates the wearer-active rule.
    ctx = setup_account_on_hold(ramp_spare_wearer=True)
    res = api.create_assignment(
        {"garment_id": ctx["spare_garment"]["id"], "wearer_id": ctx["spare_wearer"]["id"]},
        MANAGER,
    )
    validate_error(res, "ERR_ACCOUNT_ON_HOLD", expected_status=409)
    # The higher-priority gate rejected before any footprint-growing transition fired.
    garment = get_garment(ctx["spare_garment"]["id"])
    assert garment["lifecycle_status"] == "IN_STOCK", (
        f"a gated assignment must not advance the garment, got {garment['lifecycle_status']}"
    )


def test_invalid_state_beats_stale_version_on_reconcile(api):
    """PRD §2.9: "(5) state legality of the requested transition, else `ERR_INVALID_STATE`;
    (6) the account-on-hold safety gate, else `ERR_ACCOUNT_ON_HOLD`;"
    PRD §2.9: "(13) reconciliation version match, else `ERR_STALE_VISIT_VERSION`; and
    (14) general body well-formedness, else `ERR_INVALID_REQUEST`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_stale_version_on_reconcile
    """
    acct = make_account(shortage_grace_units=0)
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)  # left SCHEDULED, version 1
    # Reconcile a SCHEDULED visit (state-illegal) while ALSO passing a stale version (0).
    res = api.reconcile_visit(visit["id"], reconcile_payload(0), ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_state_check_preempts_version_check_only_when_state_illegal(api):
    """PRD §3.10: "it is permitted only while the visit is `DELIVERED` (else
    `ERR_INVALID_STATE`) and only when the body's `expected_service_visit_version` matches
    the visit's current `version` — a mismatch yields `ERR_STALE_VISIT_VERSION` at HTTP
    412, as detailed in §2.7."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_stale_version_on_reconcile
    """
    # A DELIVERED visit (state-legal) with a stale version surfaces the version error,
    # confirming the SCHEDULED case's INVALID_STATE came from the higher-priority state
    # gate rather than the version gate.
    ctx = setup_provisional_finalized_visit(grace=5, weekly_rate_cents=1000,
                                            num_garments=1, num_washed=1, actual_soil_count=1)
    res = api.reconcile_visit(ctx["visit"]["id"], reconcile_payload(0), ADMIN)
    validate_error(res, "ERR_STALE_VISIT_VERSION", expected_status=412)


# ─── Queue A: cross_entity_state_dependency ───────────────────────────────

def test_assignment_blocked_when_account_on_hold(api):
    """PRD §3.4: "The account must not be `ON_HOLD`, else `ERR_ACCOUNT_ON_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/assignment_blocked_when_account_on_hold
    """
    ctx = setup_account_on_hold()
    # The spare wearer is still ACTIVE, so only the ON_HOLD gate can fail here.
    res = api.create_assignment(
        {"garment_id": ctx["spare_garment"]["id"], "wearer_id": ctx["spare_wearer"]["id"]},
        MANAGER,
    )
    validate_error(res, "ERR_ACCOUNT_ON_HOLD", expected_status=409)
    garment = get_garment(ctx["spare_garment"]["id"])
    assert garment["lifecycle_status"] == "IN_STOCK", (
        f"a rejected assignment must leave the garment IN_STOCK, got {garment['lifecycle_status']}"
    )


def test_assignment_succeeds_once_hold_released(api):
    """PRD §3.1: "Releasing a hold moves the posture from `ON_HOLD` back to `CURRENT`, and
    is permitted only while the account is `ON_HOLD` and its `outstanding_cents` stands at
    or below 50,000 cents."
    PRD §3.4: "The account must not be `ON_HOLD`, else `ERR_ACCOUNT_ON_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/assignment_blocked_when_account_on_hold
    """
    ctx = setup_account_on_hold()
    # Settle the outstanding LOSS so the account can be released below the threshold.
    from test_helpers import list_account_charges
    for charge in list_account_charges(ctx["account"]["id"]):
        if not charge["paid"]:
            validate_success(api.settle_charge(charge["id"], ADMIN), 200)
    validate_success(api.release_hold(ctx["account"]["id"], ADMIN), 200)
    # With the parent account back to CURRENT, the cross-entity gate no longer blocks.
    created = validate_success(
        api.create_assignment(
            {"garment_id": ctx["spare_garment"]["id"], "wearer_id": ctx["spare_wearer"]["id"]},
            MANAGER,
        ),
        201,
    )
    assert created["status"] == "ASSIGNED", (
        f"assignment should succeed once the hold is released, got {created['status']}"
    )


def test_wearer_remove_blocked_while_holding_garment(api):
    """PRD §3.2: "A removal attempt against a wearer still holding one or more assigned
    garments is rejected with `ERR_WEARER_HAS_GARMENTS`."

    Design: Difficulty/cross_entity_state_dependency/wearer_remove_blocked_while_garments_assigned
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(grace=0)
    validate_success(api.ramp_down_wearer(wearer["id"], MANAGER), 200)
    # The wearer is RAMP_DOWN but still holds one ASSIGNED garment.
    res = api.remove_wearer(wearer["id"], MANAGER)
    validate_error(res, "ERR_WEARER_HAS_GARMENTS", expected_status=409)
    after = get_wearer(wearer["id"])
    assert after["roster_status"] == "RAMP_DOWN", (
        f"a blocked removal must leave roster_status RAMP_DOWN, got {after['roster_status']}"
    )


def test_wearer_remove_succeeds_after_garment_returned(api):
    """PRD §3.2: "A wearer can be removed only once every garment has left its hands — that
    is, only while its `assigned_garment_count` is exactly zero."
    PRD §3.2: "Removing a wearer is the terminal step, moving `roster_status` from
    `RAMP_DOWN` to `REMOVED` and recomputing the account's `active_wearer_count`; it is
    permitted only from `RAMP_DOWN`."

    Design: Difficulty/cross_entity_state_dependency/wearer_remove_blocked_while_garments_assigned
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(grace=0)
    validate_success(api.ramp_down_wearer(wearer["id"], MANAGER), 200)
    # Returning the garment drops assigned_garment_count to 0, clearing the removal gate.
    validate_success(api.return_assignment(asg["id"], MANAGER), 200)
    removed = validate_success(api.remove_wearer(wearer["id"], MANAGER), 200)
    assert removed["roster_status"] == "REMOVED", (
        f"removal must now succeed and reach REMOVED, got {removed['roster_status']}"
    )


# ─── Queue A: resource_temporal_overlap ───────────────────────────────────

def test_route_stop_window_overlap_rejected(api):
    """PRD §3.7: "The **window-overlap** rule forbids any positive-length intersection
    between a new stop's `[window_start_min, window_end_min)` and the window of any
    existing stop on the same route; because the windows are half-open, two windows that
    merely touch at a single endpoint (one stop's end equal to the next stop's start) do
    **not** conflict, while any overlap of positive length does."

    Design: Difficulty/resource_temporal_overlap/route_stop_window_pairwise_halfopen_overlap
    """
    acct1 = make_account()
    acct2 = make_account()
    route = make_route()
    make_route_stop(route["id"], acct1["id"], stop_sequence=1,
                    window_start_min=480, window_end_min=540)
    # [500,560) overlaps [480,540) by positive length on the same route.
    res = api.create_route_stop(
        route["id"],
        create_route_stop_payload(acct2["id"], stop_sequence=2,
                                  window_start_min=500, window_end_min=560),
        ADMIN,
    )
    validate_error(res, "ERR_STOP_WINDOW_OVERLAP", expected_status=409)


def test_route_stop_window_containment_overlap_rejected(api):
    """PRD §3.7: "The **window-overlap** rule forbids any positive-length intersection
    between a new stop's `[window_start_min, window_end_min)` and the window of any
    existing stop on the same route..."

    Design: Difficulty/resource_temporal_overlap/route_stop_window_pairwise_halfopen_overlap
    """
    acct1 = make_account()
    acct2 = make_account()
    route = make_route()
    make_route_stop(route["id"], acct1["id"], stop_sequence=1,
                    window_start_min=480, window_end_min=540)
    # [470,550) fully contains [480,540) — a positive-length intersection of a different
    # geometry than partial overlap, still rejected by the window rule.
    res = api.create_route_stop(
        route["id"],
        create_route_stop_payload(acct2["id"], stop_sequence=2,
                                  window_start_min=470, window_end_min=550),
        ADMIN,
    )
    validate_error(res, "ERR_STOP_WINDOW_OVERLAP", expected_status=409)


def test_wash_station_capacity_overflow_rejected(api):
    """PRD §3.5: "A new garment's slot `[slot_start_min, slot_end_min)` may be admitted to
    a station only if, at no instant within that interval, more than the station's
    `capacity` garment slots overlap on that station — counting the new garment in the
    tally."

    Design: Difficulty/resource_temporal_overlap/wash_station_aggregate_capacity_overflow
    """
    from test_helpers import make_wash_station, start_wash_payload
    acct = make_account(shortage_grace_units=5)
    gt = make_garment_type(weekly_rate_cents=1000)
    ws = make_wash_station(capacity=1)
    wearer = make_wearer(acct["id"])
    g1 = make_garment(acct["id"], gt["id"])
    g2 = make_garment(acct["id"], gt["id"])
    make_assignment(g1["id"], wearer["id"])
    make_assignment(g2["id"], wearer["id"])
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)
    # Both garments soiled at pickup, then g1 reserves [600,660) at the capacity-1 station.
    get_success_data(api.pickup_visit(visit["id"], pickup_payload(2), DRIVER))
    TECH = TEST_USERS["cleanroom_tech_headers"]
    get_success_data(api.start_wash(g1["id"], start_wash_payload(ws["id"], 600, 660), TECH))
    # g2's [630,690) overlaps g1's slot, exceeding capacity 1.
    res = api.start_wash(g2["id"], start_wash_payload(ws["id"], 630, 690), TECH)
    validate_error(res, "ERR_WASH_STATION_FULL", expected_status=409)


def test_wash_station_touching_slots_allowed_at_capacity_one(api):
    """PRD §3.5: "A new garment's slot `[slot_start_min, slot_end_min)` may be admitted to
    a station only if, at no instant within that interval, more than the station's
    `capacity` garment slots overlap on that station — counting the new garment in the
    tally."

    Design: Difficulty/resource_temporal_overlap/wash_station_aggregate_capacity_overflow
    """
    from test_helpers import make_wash_station, start_wash_payload
    acct = make_account(shortage_grace_units=5)
    gt = make_garment_type(weekly_rate_cents=1000)
    ws = make_wash_station(capacity=1)
    wearer = make_wearer(acct["id"])
    g1 = make_garment(acct["id"], gt["id"])
    g2 = make_garment(acct["id"], gt["id"])
    make_assignment(g1["id"], wearer["id"])
    make_assignment(g2["id"], wearer["id"])
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)
    get_success_data(api.pickup_visit(visit["id"], pickup_payload(2), DRIVER))
    TECH = TEST_USERS["cleanroom_tech_headers"]
    get_success_data(api.start_wash(g1["id"], start_wash_payload(ws["id"], 600, 660), TECH))
    # g2's [660,720) touches g1's slot only at the half-open boundary 660 — at no instant
    # do two slots overlap, so capacity 1 is never exceeded and the slot is admitted.
    started = validate_success(api.start_wash(g2["id"], start_wash_payload(ws["id"], 660, 720), TECH), 200)
    assert started["wash_location"] == "IN_WASH", (
        f"a touching (non-overlapping) slot must be admitted at capacity 1, got "
        f"{started['wash_location']}"
    )


# ─── Queue A: boundary_precision_check (empty-set) ────────────────────────

def test_empty_soil_pickup_yields_zero_counts(api):
    """PRD §3.8: "On pickup the system snapshots `expected_soil_count` as the count of the
    account's garments that are currently `ASSIGNED` and `AT_CUSTOMER` — the garments that
    ought to be coming back."

    Design: Difficulty/boundary_precision_check/empty_soil_pickup_zero_count_no_strikes
    """
    acct = make_account(shortage_grace_units=0)
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)
    # No garments assigned to this account at all.
    picked = validate_success(api.pickup_visit(visit["id"], pickup_payload(0), DRIVER), 200)
    assert picked["expected_soil_count"] == 0, (
        f"no ASSIGNED garments must snapshot expected_soil_count 0, got "
        f"{picked['expected_soil_count']}"
    )
    assert picked["actual_soil_count"] == 0, (
        f"actual_soil_count should record the submitted 0, got {picked['actual_soil_count']}"
    )
    assert picked["status"] == "PICKED_UP", (
        f"pickup must still advance the visit to PICKED_UP, got {picked['status']}"
    )


def test_empty_account_visit_yields_zero_provisional_charge(api):
    """PRD §3.9: "Its rental portion is the sum, over every garment of the account whose
    `lifecycle_status` is `ASSIGNED` at delivery time ... of that garment's type's
    `weekly_rate_cents`..."
    PRD §3.9: "the shortfall is the larger of zero and the quantity obtained by taking
    `expected_soil_count`, subtracting `actual_soil_count`, and then subtracting the
    account's `shortage_grace_units`..."

    Design: Difficulty/boundary_precision_check/empty_soil_pickup_zero_count_no_strikes
    """
    acct = make_account(shortage_grace_units=0)
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)
    get_success_data(api.pickup_visit(visit["id"], pickup_payload(0), DRIVER))
    delivered = validate_success(api.deliver_visit(visit["id"], DRIVER), 200)
    # No ASSIGNED garments -> rental 0; expected-actual = 0 -> shortage 0.
    assert delivered["provisional_charge_cents"] == 0, (
        f"an empty account's visit must produce a zero provisional charge, got "
        f"{delivered['provisional_charge_cents']}"
    )


# ─── Queue B: validations section ─────────────────────────────────────────

def test_assign_to_rampdown_wearer_rejected(api):
    """PRD §3.4: "only an `ACTIVE` wearer may receive a garment: assigning to a wearer
    whose `roster_status` is `RAMP_DOWN` or `REMOVED` is rejected with
    `ERR_WEARER_NOT_ACTIVE`."

    Design: Corner/validations/assign_garment_to_rampdown_wearer_rejected
    """
    acct = make_account()
    gt = make_garment_type()
    wearer = make_wearer(acct["id"])
    g = make_garment(acct["id"], gt["id"])
    validate_success(api.ramp_down_wearer(wearer["id"], MANAGER), 200)
    # Account is CURRENT, so only the wearer-active rule applies.
    res = api.create_assignment({"garment_id": g["id"], "wearer_id": wearer["id"]}, MANAGER)
    validate_error(res, "ERR_WEARER_NOT_ACTIVE", expected_status=409)


def test_cross_account_assignment_fk_integrity(api):
    """PRD §3.4: "The garment and wearer named in the body must both exist and, critically,
    must belong to the same account, since a garment is assigned within the account that
    rents it; a body foreign key that does not resolve, or a garment and wearer drawn from
    different accounts, is rejected with `ERR_FK_INTEGRITY`."

    Design: Corner/validations/cross_account_assignment_fk_integrity
    """
    acct_a = make_account()
    acct_b = make_account()
    gt = make_garment_type()
    garment_a = make_garment(acct_a["id"], gt["id"])
    wearer_b = make_wearer(acct_b["id"])
    res = api.create_assignment(
        {"garment_id": garment_a["id"], "wearer_id": wearer_b["id"]}, MANAGER
    )
    validate_error(res, "ERR_FK_INTEGRITY", expected_status=422)


def test_sequence_buffer_violation_rejected(api):
    """PRD §3.7: "consecutive sequence-ordered stops must respect a fixed fifteen-minute
    travel buffer: a later stop's `window_start_min` must be at least the immediately-prior
    sequence's `window_end_min` plus fifteen minutes. A duplicated `stop_sequence`, or a
    buffer the new stop fails to honor, is rejected with `ERR_STOP_SEQUENCE_CONFLICT`."

    Design: Corner/validations/sequence_buffer_violation_on_route_stop
    """
    acct1 = make_account()
    acct2 = make_account()
    route = make_route()
    make_route_stop(route["id"], acct1["id"], stop_sequence=1,
                    window_start_min=480, window_end_min=540)
    # seq-1 ends at 540; seq-2 must start >= 555, but starts at 545.
    res = api.create_route_stop(
        route["id"],
        create_route_stop_payload(acct2["id"], stop_sequence=2,
                                  window_start_min=545, window_end_min=600),
        ADMIN,
    )
    validate_error(res, "ERR_STOP_SEQUENCE_CONFLICT", expected_status=409)


def test_duplicate_tag_code_per_account_rejected(api):
    """PRD §3.3: "The `tag_code` must be unique within that account, and a collision is
    rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/validations/duplicate_tag_code_per_account
    """
    acct = make_account()
    gt = make_garment_type()
    validate_success(
        api.create_garment(acct["id"], create_garment_payload(gt["id"], tag_code="T1"), ADMIN), 201
    )
    res = api.create_garment(acct["id"], create_garment_payload(gt["id"], tag_code="T1"), ADMIN)
    validate_error(res, "ERR_DUPLICATE_KEY", expected_status=409)


def test_pickup_actual_above_expected_rejected(api):
    """PRD §3.8: "A submitted `actual_soil_count` exceeding that snapshot
    `expected_soil_count` is rejected as `ERR_INVALID_REQUEST`, since the driver cannot
    scan back more garments than were out."

    Design: Corner/validations/soil_count_above_expected_rejected
    """
    acct, wearer, gt, g, asg = setup_assigned_garment(grace=0)  # exactly 1 ASSIGNED garment
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)
    res = api.pickup_visit(visit["id"], pickup_payload(5), DRIVER)  # expected 1, actual 5
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_wearer_missing_shirt_size_rejected(api):
    """PRD §3.2: "An account manager populates the roster by adding a `Wearer` to an
    account, providing the employee's `full_name`, a `shirt_size` from the set `XS`, `S`,
    `M`, `L`, `XL`, or `XXL`, a numeric `pant_size` that is an integer waist measurement
    between 28 and 48 inclusive, and a `locker_label` naming the physical locker slot..."

    Design: Corner/entities/missing_required_field_on_wearer_create
    """
    acct = make_account()
    payload = create_wearer_payload()
    del payload["shirt_size"]
    res = api.create_wearer(acct["id"], payload, MANAGER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_wearer_invalid_shirt_size_enum_rejected(api):
    """PRD §3.2: "providing the employee's `full_name`, a `shirt_size` from the set `XS`,
    `S`, `M`, `L`, `XL`, or `XXL`..."
    PRD §2.9: "(14) general body well-formedness, else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/invalid_enum_shirt_size_rejected
    """
    acct = make_account()
    res = api.create_wearer(acct["id"], create_wearer_payload(shirt_size="XXXL"), MANAGER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ─── Queue B: errors section ──────────────────────────────────────────────

def test_blank_emblem_text_rejected(api):
    """PRD §3.5: "The text must not be blank; an empty or whitespace-only `emblem_text` is
    rejected with `ERR_EMBLEM_TEXT_INVALID`."

    Design: Corner/errors/blank_emblem_text_rejected
    """
    acct = make_account()
    gt = make_garment_type(emblem_setup_cents=500)
    g = make_garment(acct["id"], gt["id"])
    res = api.apply_emblem(g["id"], apply_emblem_payload(""), MANAGER)
    validate_error(res, "ERR_EMBLEM_TEXT_INVALID", expected_status=400)


def test_pagination_limit_above_max_rejected(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to
    10 when omitted, with a minimum of 1 and a maximum of 100. ... A `limit` or `offset`
    outside these bounds is rejected with `ERR_PAGINATION_INVALID`."

    Design: Corner/errors/pagination_invalid_limit_rejected
    """
    res = api.list_accounts(ADMIN, params={"limit": 999})
    validate_error(res, "ERR_PAGINATION_INVALID", expected_status=400)


# ─── Queue B: rbac section ────────────────────────────────────────────────

def test_driver_cannot_create_account(api):
    """PRD §2.1: "If the header is valid but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/driver_cannot_create_account
    """
    res = api.create_account(create_account_payload(legal_name="Nope"), DRIVER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_account_manager_cannot_pickup(api):
    """PRD §2.1: "If the header is valid but the named role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/account_manager_cannot_pickup
    """
    acct = make_account()
    route, stop = setup_route_stop_for_account(acct["id"])
    visit = make_service_visit(stop["id"], week_index=0)
    res = api.pickup_visit(visit["id"], pickup_payload(0), MANAGER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or does not name one of the declared roles,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    bad_headers = build_user_headers("anon-1", "Nobody")
    res = api.create_account(create_account_payload(legal_name="Anon"), bad_headers)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
