"""Visit branching lifecycle, day-pass cyclic redemption, allotment/capacity
boundaries, and invalid transitions.

The visit forks from HELD into CHECKED_IN / CANCELLED / NO_SHOW with divergent
side effects (PRD §3.3, §3.4, §3.8). entry_mode resolution is a strict-less-than
threshold (PRD §3.3). Capacity is enforced at check-in on aggregate occupancy
(PRD §3.4). Covers queue-A non_linear_state_machine / boundary_precision_check /
resource_temporal_overlap (aggregate capacity) and queue-B state-machine corners.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    make_lounge_agent_headers,
    make_member_headers,
    fixtures,
)

ADMIN = TEST_USERS["network_admin_headers"]


# ─── Queue A: non_linear_state_machine — branching side effects ──────────────
def test_visit_branching_cancel_vs_no_show_side_effects(api):
    """PRD §3.3: "Because a cancelled visit leaves the set of statuses that count
    toward usage, no allotment is consumed by it."
    PRD §3.8: "for any entry that was not a day-pass entry the member's
    `no_show_strikes` is recomputed upward by one. A no-show still burns allotment,
    because `NO_SHOW` is one of the statuses that count toward usage — so a hold
    that expires unredeemed nonetheless consumes its `allotment_consumed` and
    `guest_allotment_consumed`."

    Member A's hold is cancelled (no strike, no allotment); Member B's hold is
    swept to NO_SHOW (+1 strike, allotment burned).

    Design: Difficulty/non_linear_state_machine/nlsm_visit_branching_divergent_side_effects
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10, included_guest_visits_per_year=5)
    lounge = fixtures.create_lounge(airport_code="SEA", capacity=50)
    ma = fixtures.create_member(plan["id"], full_name="Member A")
    fixtures.create_card(ma["id"])
    mb = fixtures.create_member(plan["id"], full_name="Member B")
    fixtures.create_card(mb["id"])

    va = fixtures.open_hold(lounge["id"], member_id=ma["id"])
    vb = fixtures.open_hold(lounge["id"], member_id=mb["id"])

    cancelled = fixtures.cancel_visit_as_member(va["id"], ma["id"])
    assert cancelled["status"] == "CANCELLED", cancelled

    fixtures.set_clock("2026-06-01T01:00:00Z")
    get_success_data(api_client.sweep_lounge(lounge["id"], ADMIN))

    vb_now = get_success_data(api_client.get_visit(vb["id"], ADMIN))
    assert vb_now["status"] == "NO_SHOW", vb_now
    ma_now = fixtures.get_member(ma["id"])
    mb_now = fixtures.get_member(mb["id"])
    assert ma_now["no_show_strikes"] == 0, ma_now
    assert mb_now["no_show_strikes"] == 1, mb_now
    assert mb_now["visits_used"] == 1, "no-show still burns allotment"
    assert ma_now["visits_used"] == 0, "cancel leaves the consuming set"


def test_day_pass_cyclic_redeem_then_revert_on_cancel(api):
    """PRD §3.6: "Redemption happens through a visit: a hold opened with a
    `day_pass_id` and then checked in finalises the pass to `REDEEMED` with its
    `redeemed_visit_id` set to that visit, provided the pass was `ISSUED`, not past
    its `valid_until`, and belongs to the visit's lounge. If instead the redeeming
    hold is cancelled before check-in, a `REDEEMED`-held pass reverts to `ISSUED`
    and its `redeemed_visit_id` is cleared back to empty."

    Design: Difficulty/non_linear_state_machine/nlsm_daypass_cyclic_redeem_revert
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="STANDARD", included_visits_per_year=0, included_guest_visits_per_year=0)
    lounge = fixtures.create_lounge(airport_code="BOS", capacity=50, day_pass_price_cents=4000)
    member = fixtures.create_member(plan["id"])
    day_pass = fixtures.purchase_day_pass_for_member(lounge["id"], member["id"])
    visit = fixtures.open_hold(lounge["id"], member_id=member["id"], day_pass_id=day_pass["id"])

    redeemed = get_success_data(api_client.get_day_pass(day_pass["id"], ADMIN))
    assert redeemed["status"] == "REDEEMED", redeemed
    assert redeemed["redeemed_visit_id"] == visit["id"], redeemed

    fixtures.cancel_visit_as_member(visit["id"], member["id"])
    reverted = get_success_data(api_client.get_day_pass(day_pass["id"], ADMIN))
    assert reverted["status"] == "ISSUED", reverted
    assert reverted["redeemed_visit_id"] in (None, ""), reverted


# ─── Queue A: boundary_precision_check ───────────────────────────────────────
def test_allotment_exhaustion_strict_less_than_boundary(api):
    """PRD §3.3: "Otherwise, if the member's `visits_used` for the current year is
    strictly less than the plan's `included_visits_per_year`, the entry mode is
    `ALLOTMENT` and allotment is consumed. In every other case the entry mode is
    `OVERAGE` and no allotment is consumed."
    PRD §3.3: "The boundary follows directly from the strict comparison: with six
    included visits, the seventh primary visit is the first to be charged as overage
    — the visit that observes `visits_used` equal to the included count is the first
    `OVERAGE`, while the visit that observes it one below is still free."

    included_visits 2: after two ALLOTMENT visits, the third observes visits_used
    == 2 (not < 2) and is the first OVERAGE.

    Design: Difficulty/boundary_precision_check/bpc_allotment_exhaustion_strict_less_than
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={
            "tier": "STANDARD", "included_visits_per_year": 2,
            "included_guest_visits_per_year": 0, "min_card_status": "BASIC",
        },
        lounge_overrides={"airport_code": "MSP", "capacity": 50},
    )
    for _ in range(2):
        v = fixtures.open_hold(lounge["id"], member_id=member["id"])
        assert v["entry_mode"] == "ALLOTMENT", v
        fixtures.check_in(v["id"], lounge["id"])
        fixtures.complete_visit(v["id"], lounge["id"])

    v3 = fixtures.open_hold(lounge["id"], member_id=member["id"])
    assert v3["entry_mode"] == "OVERAGE", v3
    assert v3["allotment_consumed"] is False, v3


def test_check_in_over_capacity_rejected_at_boundary(api):
    """PRD §3.4: "The lounge must have room: the lounge's `current_occupancy` plus
    the visit's `occupant_count` must not exceed the lounge's `capacity`, and a
    check-in that would breach that ceiling is rejected with `ERR_OVER_CAPACITY`
    (HTTP 409)."

    Capacity 2, one occupant CHECKED_IN; a check-in of occupant_count 2 (1 guest)
    would make 1+2=3 > 2 and is rejected.

    Design: Difficulty/boundary_precision_check/bpc_capacity_exact_boundary_checkin
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10, included_guest_visits_per_year=5)
    lounge = fixtures.create_lounge(airport_code="SLC", capacity=2)
    m1 = fixtures.create_member(plan["id"], full_name="Cap 1")
    fixtures.create_card(m1["id"])
    m2 = fixtures.create_member(plan["id"], full_name="Cap 2")
    fixtures.create_card(m2["id"])

    v1 = fixtures.open_hold(lounge["id"], member_id=m1["id"])
    fixtures.check_in(v1["id"], lounge["id"])
    v2 = fixtures.open_hold(lounge["id"], member_id=m2["id"], guest_count=1, guest_names=["Plus"])

    resp = api_client.check_in(v2["id"], make_lounge_agent_headers(lounge["id"]))
    validate_error(resp, ApiErrorId.ERR_OVER_CAPACITY.value)
    assert fixtures.get_lounge(lounge["id"])["current_occupancy"] == 1, "failed check-in occupies no seats"


# ─── Queue A: resource_temporal_overlap — aggregate capacity pool ────────────
def test_aggregate_occupancy_pool_rejects_over_capacity_check_in(api):
    """PRD §3.4: "The lounge must have room: the lounge's `current_occupancy` plus
    the visit's `occupant_count` must not exceed the lounge's `capacity`, and a
    check-in that would breach that ceiling is rejected with `ERR_OVER_CAPACITY`
    (HTTP 409)."

    Capacity 3 with aggregate occupancy 3 (one solo + one with a guest); a third
    single-occupant check-in is rejected because 3 + 1 > 3.

    Design: Difficulty/resource_temporal_overlap/rto_lounge_aggregate_capacity_overlap
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10, included_guest_visits_per_year=5)
    lounge = fixtures.create_lounge(airport_code="AUS", capacity=3)
    m1 = fixtures.create_member(plan["id"], full_name="Agg 1")
    fixtures.create_card(m1["id"])
    m2 = fixtures.create_member(plan["id"], full_name="Agg 2")
    fixtures.create_card(m2["id"])
    m3 = fixtures.create_member(plan["id"], full_name="Agg 3")
    fixtures.create_card(m3["id"])

    # All three holds must be opened while the lounge is still OPEN: per PRD §3.3
    # a hold is honoured only when status is OPEN, and the overflow line is the
    # sum of current_occupancy AND held_occupancy reaching capacity. So v3's hold
    # is opened first (lounge empty, OPEN), then v1 is opened and checked in, then
    # v2 (one guest) is opened and checked in — driving current_occupancy to 3
    # while v3 remains HELD. Only then is v3's check-in attempted (3 + 1 > 3).
    v3 = fixtures.open_hold(lounge["id"], member_id=m3["id"])
    v1 = fixtures.open_hold(lounge["id"], member_id=m1["id"])
    fixtures.check_in(v1["id"], lounge["id"])
    v2 = fixtures.open_hold(lounge["id"], member_id=m2["id"], guest_count=1, guest_names=["G"])
    fixtures.check_in(v2["id"], lounge["id"])
    assert fixtures.get_lounge(lounge["id"])["current_occupancy"] == 3

    resp = api_client.check_in(v3["id"], make_lounge_agent_headers(lounge["id"]))
    validate_error(resp, ApiErrorId.ERR_OVER_CAPACITY.value)


# ─── Queue B: state-machine corners ──────────────────────────────────────────
def test_visit_initial_state_held_with_30_minute_expiry(api):
    """PRD §3.3: "At hold time the system snapshots the member's active card onto
    the visit as `eligibility_card_id` (null for a day-pass-only entry), records
    `held_at` at the current logical clock, and sets `hold_expires_at` to thirty
    minutes after `held_at`. The hold's `status` begins at `HELD`."

    Design: Corner/state_machines/sm_initial_state_visit_held
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "BOS", "capacity": 10},
        clock="2026-06-01T00:00:00Z",
    )
    visit = fixtures.open_hold(lounge["id"], member_id=member["id"])
    assert visit["status"] == "HELD", visit
    assert visit["hold_expires_at"] == "2026-06-01T00:30:00.000Z", visit


def test_check_in_already_checked_in_rejected(api):
    """PRD §3.4: "A lounge agent admits a held visit by checking it in, which is
    defined only from `HELD` and only for the agent who staffs the visit's lounge."

    Design: Corner/state_machines/sm_checkin_already_checked_in_invalid_state
    """
    plan, lounge, member, card, visit = fixtures.setup_checked_in_visit(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "DEN", "capacity": 10},
    )
    resp = api_client.check_in(visit["id"], make_lounge_agent_headers(lounge["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_success_data(api_client.get_visit(visit["id"], ADMIN))["status"] == "CHECKED_IN"


def test_complete_already_completed_rejected(api):
    """PRD §3.4: "A checked-in visit is brought to a close by the lounge agent
    **completing** it, which is defined only from `CHECKED_IN`."

    Design: Corner/state_machines/sm_complete_terminal_completed_locked
    """
    plan, lounge, member, card, visit = fixtures.setup_completed_visit(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "PHX", "capacity": 10},
    )
    resp = api_client.complete_visit(visit["id"], make_lounge_agent_headers(lounge["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_checked_in_visit_rejected(api):
    """PRD §3.3: "A member may **cancel** a hold they own while it is still `HELD`,
    which is the only state from which cancellation is defined."

    Design: Corner/state_machines/sm_cancel_checked_in_visit_invalid_state
    """
    plan, lounge, member, card, visit = fixtures.setup_checked_in_visit(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "MIA", "capacity": 10},
    )
    resp = api_client.cancel_visit(visit["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_check_in_response_carries_pinned_charge_immediately(api):
    """PRD §3.4: "On a successful check-in the visit moves to `CHECKED_IN`, and the
    system computes and pins the member's charge for the visit as
    `member_charge_cents`."

    An OVERAGE primary (overage 5000, non-GOLD, no guests) check-in response itself
    carries CHECKED_IN status and the pinned charge 5000.

    Design: Corner/consistency_model/cm_immediate_checkin_visible_in_response
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={
            "tier": "STANDARD", "included_visits_per_year": 0,
            "included_guest_visits_per_year": 0, "overage_charge_cents": 5000,
        },
        lounge_overrides={"airport_code": "SAT", "capacity": 10},
    )
    visit = fixtures.open_hold(lounge["id"], member_id=member["id"])
    assert visit["entry_mode"] == "OVERAGE", visit
    resp = api_client.check_in(visit["id"], make_lounge_agent_headers(lounge["id"]))
    checked_in = validate_success(resp, expected_status=200)
    assert checked_in["status"] == "CHECKED_IN", checked_in
    assert checked_in["member_charge_cents"] == 5000, checked_in


# ─── Queue A second-coverage: non_linear_state_machine ───────────────────────
def test_visit_checked_in_branch_occupies_and_charges(api):
    """PRD §3.4: "Also at check-in the lounge's seats are moved: `current_occupancy`
    is recomputed upward by `occupant_count` and `held_occupancy` downward by the
    same."
    PRD §3.4: "On a successful check-in the visit moves to `CHECKED_IN`, and the
    system computes and pins the member's charge for the visit as
    `member_charge_cents`."

    The CHECKED_IN fork (distinct from the CANCELLED / NO_SHOW arms) occupies a
    live seat and pins a non-zero overage charge.

    Design: Difficulty/non_linear_state_machine/nlsm_visit_branching_divergent_side_effects
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={
            "tier": "STANDARD", "included_visits_per_year": 0,
            "included_guest_visits_per_year": 0, "overage_charge_cents": 5000,
        },
        lounge_overrides={"airport_code": "SEA", "capacity": 50},
    )
    visit = fixtures.open_hold(lounge["id"], member_id=member["id"])
    checked_in = fixtures.check_in(visit["id"], lounge["id"])
    assert checked_in["status"] == "CHECKED_IN", checked_in
    assert checked_in["member_charge_cents"] == 5000, checked_in
    lounge_now = fixtures.get_lounge(lounge["id"])
    assert lounge_now["current_occupancy"] == 1, lounge_now
    assert lounge_now["held_occupancy"] == 0, lounge_now


def test_day_pass_stays_redeemed_through_check_in(api):
    """PRD §3.4: "If the visit redeemed a day pass, that pass is finalised as
    redeemed at this point (see §3.6)."
    PRD §3.6: "a hold opened with a `day_pass_id` and then checked in finalises the
    pass to `REDEEMED` with its `redeemed_visit_id` set to that visit, provided the
    pass was `ISSUED`, not past its `valid_until`, and belongs to the visit's lounge."

    The forward edge of the cyclic machine: after check-in (not cancel) the pass
    stays REDEEMED rather than reverting.

    Design: Difficulty/non_linear_state_machine/nlsm_daypass_cyclic_redeem_revert
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="STANDARD", included_visits_per_year=0, included_guest_visits_per_year=0)
    lounge = fixtures.create_lounge(airport_code="BOS", capacity=50, day_pass_price_cents=4000)
    member = fixtures.create_member(plan["id"])
    day_pass = fixtures.purchase_day_pass_for_member(lounge["id"], member["id"])
    visit = fixtures.open_hold(lounge["id"], member_id=member["id"], day_pass_id=day_pass["id"])
    fixtures.check_in(visit["id"], lounge["id"])
    after = get_success_data(api_client.get_day_pass(day_pass["id"], ADMIN))
    assert after["status"] == "REDEEMED", after
    assert after["redeemed_visit_id"] == visit["id"], after


# ─── Queue A second-coverage: boundary_precision_check ───────────────────────
def test_allotment_first_free_second_overage_tight_boundary(api):
    """PRD §3.3: "Otherwise, if the member's `visits_used` for the current year is
    strictly less than the plan's `included_visits_per_year`, the entry mode is
    `ALLOTMENT` and allotment is consumed. In every other case the entry mode is
    `OVERAGE` and no allotment is consumed."

    included_visits 1: the first primary (visits_used 0 < 1) is ALLOTMENT, the
    second (visits_used 1, not < 1) is the first OVERAGE.

    Design: Difficulty/boundary_precision_check/bpc_allotment_exhaustion_strict_less_than
    """
    plan, lounge, member, card = fixtures.setup_plan_lounge_member(
        plan_overrides={
            "tier": "STANDARD", "included_visits_per_year": 1,
            "included_guest_visits_per_year": 0, "min_card_status": "BASIC",
        },
        lounge_overrides={"airport_code": "MSP", "capacity": 50},
    )
    v1 = fixtures.open_hold(lounge["id"], member_id=member["id"])
    assert v1["entry_mode"] == "ALLOTMENT", v1
    fixtures.check_in(v1["id"], lounge["id"])
    fixtures.complete_visit(v1["id"], lounge["id"])
    v2 = fixtures.open_hold(lounge["id"], member_id=member["id"])
    assert v2["entry_mode"] == "OVERAGE", v2


def test_check_in_at_exact_capacity_succeeds(api):
    """PRD §3.4: "The lounge must have room: the lounge's `current_occupancy` plus
    the visit's `occupant_count` must not exceed the lounge's `capacity`, and a
    check-in that would breach that ceiling is rejected with `ERR_OVER_CAPACITY`
    (HTTP 409)."

    Capacity 2, one occupant already in; a single-occupant check-in fills the last
    seat exactly (1 + 1 <= 2) and succeeds.

    Design: Difficulty/boundary_precision_check/bpc_capacity_exact_boundary_checkin
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10)
    lounge = fixtures.create_lounge(airport_code="SLC", capacity=2)
    m1 = fixtures.create_member(plan["id"], full_name="Cap 1")
    fixtures.create_card(m1["id"])
    m2 = fixtures.create_member(plan["id"], full_name="Cap 2")
    fixtures.create_card(m2["id"])
    v1 = fixtures.open_hold(lounge["id"], member_id=m1["id"])
    fixtures.check_in(v1["id"], lounge["id"])
    v2 = fixtures.open_hold(lounge["id"], member_id=m2["id"])
    resp = api_client.check_in(v2["id"], make_lounge_agent_headers(lounge["id"]))
    checked_in = validate_success(resp, expected_status=200)
    assert checked_in["status"] == "CHECKED_IN", checked_in
    assert fixtures.get_lounge(lounge["id"])["current_occupancy"] == 2


# ─── Queue A second-coverage: resource_temporal_overlap (aggregate) ──────────
def test_aggregate_occupancy_admits_check_in_below_capacity(api):
    """PRD §3.4: "The lounge must have room: the lounge's `current_occupancy` plus
    the visit's `occupant_count` must not exceed the lounge's `capacity`..."

    Capacity 3, aggregate occupancy 2; a single-occupant check-in succeeds because
    2 + 1 <= 3 — the complementary admit case of the aggregate-pool geometry.

    Design: Difficulty/resource_temporal_overlap/rto_lounge_aggregate_capacity_overlap
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10, included_guest_visits_per_year=5)
    lounge = fixtures.create_lounge(airport_code="AUS", capacity=3)
    m1 = fixtures.create_member(plan["id"], full_name="Agg 1")
    fixtures.create_card(m1["id"])
    m2 = fixtures.create_member(plan["id"], full_name="Agg 2")
    fixtures.create_card(m2["id"])
    v1 = fixtures.open_hold(lounge["id"], member_id=m1["id"], guest_count=1, guest_names=["G"])
    fixtures.check_in(v1["id"], lounge["id"])
    assert fixtures.get_lounge(lounge["id"])["current_occupancy"] == 2
    v2 = fixtures.open_hold(lounge["id"], member_id=m2["id"])
    resp = api_client.check_in(v2["id"], make_lounge_agent_headers(lounge["id"]))
    checked_in = validate_success(resp, expected_status=200)
    assert checked_in["status"] == "CHECKED_IN", checked_in
    assert fixtures.get_lounge(lounge["id"])["current_occupancy"] == 3
