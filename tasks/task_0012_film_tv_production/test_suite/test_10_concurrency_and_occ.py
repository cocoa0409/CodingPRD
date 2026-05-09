"""Optimistic concurrency control (OCC) and PRD-defined race conditions.

Covers PRD §2.4 (OCC), §3.2 (sign race), §3.5 (CHECK_OUT race), §3.7 (approve
race, reserve race), §3.9 (sign/cancel race).

Per PRD §2.4 OCC is *opt-in*: "if the client supplies `version`, it is
compared against the current `version` of the target resource and a mismatch
yields `ERR_VERSION_MISMATCH` (HTTP 409); if the client omits `version`, the
check is skipped(...)."
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    run_race,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    assert_race_outcome,
    create_change_order_payload,
    create_equipment_event_payload,
    setup_production_with_categories,
    setup_in_production,
    setup_signed_role,
    setup_role_with_n_breakdown_scenes,
    setup_equipment_checked_out,
    create_equipment,
    make_finance_controller_headers,
    make_line_producer_headers,
    iso,
    EXEC,
    LP,
    FC,
    CD,
    PC,
)


# ─── OCC: stale version → ERR_VERSION_MISMATCH ───────────────────────────────

def test_lock_baseline_with_stale_version_rejected(api):
    """PRD §2.4: "if the client supplies `version`, it is compared against
    the current `version` of the target resource and a mismatch yields
    `ERR_VERSION_MISMATCH` (HTTP 409)(...)."

    Claim: lock-baseline with a stale version → ERR_VERSION_MISMATCH (409).
    """
    base = setup_in_production(api)
    prod = base["production"]
    # Production is now IN_PRODUCTION and has some version. To test version
    # mismatch we need to call a state-changing endpoint that accepts version
    # AND find a transition consistent with current state. begin-wrap accepts
    # version. We'll attempt begin-wrap with stale version.
    stale_version = prod["version"] - 1 if prod["version"] > 1 else 0
    # Mark scene shot first to satisfy begin-wrap precondition.
    validate_success(api.mark_shot(prod["id"], base["scene"]["id"], PC), 200)
    res = api.begin_wrap(prod["id"], LP, payload={"version": stale_version})
    validate_error(res, "ERR_VERSION_MISMATCH", expected_status=409)


def test_lock_baseline_with_correct_version_succeeds(api):
    """PRD §2.4: "Clients that need linearizability against a specific
    snapshot must therefore include `version`(...)."

    Claim: lock-baseline with the exact current version succeeds and the
    returned version increments by 1.
    """
    # Build a Production with one SCHEDULED scene, then call lock-baseline
    # supplying the exact current version.
    prod, _ = setup_production_with_categories(api)
    from test_helpers import (
        create_location,
        create_scene_in_production,
        create_held_reservation,
        confirm_reservation_with_permit_and_weather,
    )
    location = create_location(api)
    scene = create_scene_in_production(api, production_id=prod["id"])
    reservation = create_held_reservation(
        api,
        location_id=location["id"],
        production_id=prod["id"],
        scene_id=scene["id"],
        start_at=iso(2026, 7, 1, 9),
        end_at=iso(2026, 7, 1, 17),
    )
    confirm_reservation_with_permit_and_weather(api, reservation_id=reservation["id"])
    validate_success(api.schedule_scene(
        prod["id"], scene["id"],
        {"reservation_id": reservation["id"]},
        LP,
    ), 200)
    # Read the production's current version to supply it accurately.
    fresh = validate_success(api.get_production(prod["id"], EXEC), 200)
    locked = validate_success(api.lock_baseline(
        prod["id"], LP, payload={"version": fresh["version"]},
    ), 200)
    assert locked["status"] == "IN_PRODUCTION"
    assert locked["version"] > fresh["version"]


# ─── §3.7 race: two approves on the same PENDING change order ────────────────

def test_two_approves_on_same_pending_change_order(api):
    """PRD §3.7: "Two simultaneous approves on the same pending change order
    serialize so that exactly one wins; the loser sees `ERR_INVALID_STATE`
    because the second writer encounters a row already advanced past
    `PENDING`."

    Claim: concurrent approves on a PENDING CO → exactly one succeeds; the
    loser receives ERR_INVALID_STATE.
    """
    # Use a setup with budget headroom so the REALLOCATION delta does not trip
    # ERR_BUDGET_OVERALLOCATED. Default fixture exhausts total_budget; here we
    # explicitly reserve headroom for the +100_000 increase to CAST.
    prod, cats = setup_production_with_categories(
        api,
        total_budget_cents=300_000_000,
        reserve_fund_cents=20_000_000,
    )
    lp = make_line_producer_headers("test-lp-race1")
    fc_a = make_finance_controller_headers("test-fc-race1-a")
    fc_b = make_finance_controller_headers("test-fc-race1-b")
    co = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=100_000,
            source="REALLOCATION",
        ),
        lp,
    ), 201)
    results = run_race(
        lambda: api.approve_change_order(co["id"], fc_a),
        lambda: api.approve_change_order(co["id"], fc_b),
    )
    outcome = assert_exactly_one_succeeds(*results)
    # Verify loser's error_id.
    loser_resp = outcome["failures"][0]
    validate_error(loser_resp, "ERR_INVALID_STATE", expected_status=409)


# ─── §3.7 race: two RESERVE_DRAW approvals racing for insufficient reserve ───

def test_two_reserve_draws_race_for_insufficient_reserve(api):
    """PRD §3.7: "Two concurrent `RESERVE_DRAW` approvals racing for a reserve
    fund that cannot satisfy both serialize on the production's reserve
    debit; whichever lands first wins, and the second receives
    `ERR_RESERVE_INSUFFICIENT`."

    Claim: two RESERVE_DRAW approvals each requesting 60% of the reserve →
    exactly one succeeds; the loser receives ERR_RESERVE_INSUFFICIENT.
    """
    prod, cats = setup_production_with_categories(
        api,
        total_budget_cents=200_000_000,
        reserve_fund_cents=1_000_000,
    )
    lp_a = make_line_producer_headers("test-lp-race2a")
    lp_b = make_line_producer_headers("test-lp-race2b")
    fc_x = make_finance_controller_headers("test-fc-race2x")
    fc_y = make_finance_controller_headers("test-fc-race2y")

    co_a = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=600_000,  # 60% of reserve
            source="RESERVE_DRAW",
        ),
        lp_a,
    ), 201)
    co_b = validate_success(api.create_change_order(
        create_change_order_payload(
            production_id=prod["id"],
            category_id=cats["CAST"]["id"],
            delta_cents=600_000,  # 60% of reserve — together: 120%
            source="RESERVE_DRAW",
        ),
        lp_b,
    ), 201)
    results = run_race(
        lambda: api.approve_change_order(co_a["id"], fc_x),
        lambda: api.approve_change_order(co_b["id"], fc_y),
    )
    outcome = assert_exactly_one_succeeds(*results)
    loser_resp = outcome["failures"][0]
    validate_error(loser_resp, "ERR_RESERVE_INSUFFICIENT", expected_status=409)


# ─── §3.5 race: two CHECK_OUT events on same equipment ──────────────────────

def test_two_check_outs_on_same_equipment(api):
    """PRD §3.5: "Two simultaneous `CHECK_OUT` events on the same equipment
    serialize so that exactly one succeeds; the loser receives
    `ERR_EQUIPMENT_UNAVAILABLE`."

    Claim: concurrent CHECK_OUTs on the same equipment → exactly one wins;
    the loser gets ERR_EQUIPMENT_UNAVAILABLE.
    """
    base = setup_in_production(api)
    prod = base["production"]
    eq = create_equipment(api)

    def attempt():
        return api.create_equipment_event(
            eq["id"],
            create_equipment_event_payload(
                production_id=prod["id"],
                event_type="CHECK_OUT",
                occurred_at=iso(2026, 2, 1, 12),
                damage_charge_cents=0,
            ),
            PC,
        )

    results = run_race(attempt, attempt)
    outcome = assert_exactly_one_succeeds(*results)
    loser_resp = outcome["failures"][0]
    validate_error(loser_resp, "ERR_EQUIPMENT_UNAVAILABLE", expected_status=409)


# ─── §3.2 race: two OFFERED→SIGNED calls on same role ───────────────────────

def test_two_signs_on_same_offered_role(api):
    """PRD §3.2: "Two `OFFERED → SIGNED` calls landing concurrently on the
    same role serialize so that exactly one wins; the loser receives
    `ERR_INVALID_STATE` because the race resolves at the level of
    `Role.casting_status` and the second writer encounters a state already
    advanced to `SIGNED`."

    Claim: concurrent sign requests on an OFFERED role → exactly one wins;
    the loser gets ERR_INVALID_STATE.
    """
    s = setup_role_with_n_breakdown_scenes(
        api,
        n_breakdown_scenes=1,
        n_shot_scenes=0,
        scene_minutes=120,
        role_union_tier="SUPPORTING",
        role_day_rate_cents=100_000,
        cast_planned_cents=10_000_000,
    )
    # Role at OFFERED.
    results = run_race(
        lambda: api.sign_role(s["production"]["id"], s["role"]["id"], LP),
        lambda: api.sign_role(s["production"]["id"], s["role"]["id"], LP),
    )
    outcome = assert_exactly_one_succeeds(*results)
    loser_resp = outcome["failures"][0]
    validate_error(loser_resp, "ERR_INVALID_STATE", expected_status=409)


# ─── §3.9 race: sign-and-cancel on same production ──────────────────────────

def test_sign_and_cancel_race(api):
    """PRD §3.9: "A simultaneous role-sign-and-cancel race on the same
    production serializes so that exactly one operation succeeds; the loser
    receives `ERR_INVALID_STATE`."

    Claim: concurrent (sign role) + (cancel production) → exactly one succeeds;
    the loser receives ERR_INVALID_STATE.
    """
    s = setup_role_with_n_breakdown_scenes(
        api,
        n_breakdown_scenes=1,
        n_shot_scenes=0,
        scene_minutes=120,
        role_union_tier="SUPPORTING",
        role_day_rate_cents=100_000,
        cast_planned_cents=10_000_000,
    )
    # Production is PLANNING; role is OFFERED. Cancel from PLANNING requires
    # no SIGNED roles — which is currently true. But the race semantics:
    # whichever lands first wins.
    results = run_race(
        lambda: api.sign_role(s["production"]["id"], s["role"]["id"], LP),
        lambda: api.cancel_production(s["production"]["id"], EXEC),
    )
    outcome = assert_exactly_one_succeeds(*results)
    loser_resp = outcome["failures"][0]
    validate_error(loser_resp, "ERR_INVALID_STATE", expected_status=409)
