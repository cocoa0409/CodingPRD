"""Eligibility/standing gates on a hold, validation precedence, and the no-show
suspension cascade.

A hold for a member runs a chain of business gates (PRD §3.5): active card, then
the card/fare eligibility gate, then the GOOD-standing gate. Crossing three
no-show strikes flips standing to SUSPENDED and auto-cancels the member's other
HELD visits (PRD §3.8). Covers queue-A priority_pair_validation_conflict /
cross_entity_state_dependency / transitive_cascade and queue-B validation corners.
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
    fixtures,
)

ADMIN = TEST_USERS["network_admin_headers"]


# ─── Queue A: priority_pair_validation_conflict ──────────────────────────────
def test_not_eligible_reported_before_member_suspended(api):
    """PRD §3.5: "Second, the eligibility gate proper: the member is permitted to
    enter on allotment or overage only when their active card's `card_status` meets
    or exceeds the plan's `min_card_status`, or their card's `fare_class` is
    `BUSINESS` or `FIRST`. A member who satisfies neither condition is not eligible
    and the hold is rejected with `ERR_NOT_ELIGIBLE` (HTTP 422); a day-pass entry
    bypasses this eligibility gate entirely. Third, the member's standing must be
    `GOOD`: a `SUSPENDED` member who attempts to open a hold is rejected with
    `ERR_MEMBER_SUSPENDED` (HTTP 409), while a day-pass-only entry is exempt."

    A member who is BOTH suspended and ineligible (SILVER card, ECONOMY fare, plan
    min GOLD) gets ERR_NOT_ELIGIBLE: the eligibility gate (Second) is evaluated
    before the standing gate (Third).

    Design: Difficulty/priority_pair_validation_conflict/ppvc_not_eligible_beats_member_suspended
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(
        tier="PRESTIGE_PLUS", included_visits_per_year=50, min_card_status="GOLD"
    )
    lounge = fixtures.create_lounge(airport_code="DFW", capacity=50)
    member = fixtures.create_member(plan["id"], full_name="Conflict Member")
    # First a GOLD/FIRST card so the member can accrue strikes to SUSPENDED.
    fixtures.create_card(member["id"], card_status="GOLD", fare_class="FIRST")
    for _ in range(3):
        fixtures.open_hold(lounge["id"], member_id=member["id"])
    fixtures.set_clock("2026-06-01T01:00:00Z")
    get_success_data(api_client.sweep_lounge(lounge["id"], ADMIN))
    assert fixtures.get_member(member["id"])["standing"] == "SUSPENDED"
    # Now a below-minimum SILVER/ECONOMY card replaces GOLD as active.
    fixtures.create_card(member["id"], card_status="SILVER", fare_class="ECONOMY")

    fresh_v = fixtures.get_lounge(lounge["id"])["version"]
    resp = api_client.create_visit(
        {"member_id": member["id"], "lounge_id": lounge["id"], "guest_count": 0,
         "expected_lounge_version": fresh_v},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_ELIGIBLE.value)


def test_suspended_eligible_member_reported_member_suspended(api):
    """PRD §3.5: "Third, the member's standing must be `GOOD`: a `SUSPENDED` member
    who attempts to open a hold is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 409),
    while a day-pass-only entry is exempt."

    A SUSPENDED member who IS eligible (BASIC card meets the BASIC plan minimum)
    fails only the standing gate, isolating ERR_MEMBER_SUSPENDED.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_not_eligible_beats_member_suspended
    """
    plan, lounge, member, card = fixtures.setup_suspended_member(
        plan_overrides={
            "tier": "PRESTIGE", "included_visits_per_year": 50, "min_card_status": "BASIC",
        },
        lounge_overrides={"airport_code": "SAN", "capacity": 50},
    )
    assert member["standing"] == "SUSPENDED", member
    fresh_v = fixtures.get_lounge(lounge["id"])["version"]
    resp = api_client.create_visit(
        {"member_id": member["id"], "lounge_id": lounge["id"], "guest_count": 0,
         "expected_lounge_version": fresh_v},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED.value)


# ─── Queue A: cross_entity_state_dependency — hold depends on standing ───────
def test_hold_rejected_for_suspended_member(api):
    """PRD §3.5: "Third, the member's standing must be `GOOD`: a `SUSPENDED` member
    who attempts to open a hold is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 409),
    while a day-pass-only entry is exempt."
    PRD §3.8: "When a member's recomputed `no_show_strikes` reaches three, the
    member's `standing` flips from `GOOD` to `SUSPENDED`, which by itself blocks any
    future hold."

    Visit creation depends on the Member entity's standing.

    Design: Difficulty/cross_entity_state_dependency/cesd_visit_hold_depends_on_member_standing
    """
    plan, lounge, member, card = fixtures.setup_suspended_member(
        plan_overrides={
            "tier": "PRESTIGE", "included_visits_per_year": 50, "min_card_status": "BASIC",
        },
        lounge_overrides={"airport_code": "SAN", "capacity": 50},
    )
    assert member["standing"] == "SUSPENDED", member
    fresh_v = fixtures.get_lounge(lounge["id"])["version"]
    resp = api_client.create_visit(
        {"member_id": member["id"], "lounge_id": lounge["id"], "guest_count": 0,
         "expected_lounge_version": fresh_v},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED.value)


def test_good_member_reinstated_can_hold_again(api):
    """PRD §3.2: "When the operator reinstates a suspended member, `no_show_strikes`
    is reset to 0 and `standing` returns to `GOOD`."
    PRD §3.5: "Third, the member's standing must be `GOOD`: a `SUSPENDED` member who
    attempts to open a hold is rejected with `ERR_MEMBER_SUSPENDED` (HTTP 409),
    while a day-pass-only entry is exempt."

    After reinstatement standing is GOOD, so a new hold succeeds — confirming the
    hold gate keys on the Member entity's standing.

    Design: Difficulty/cross_entity_state_dependency/cesd_visit_hold_depends_on_member_standing
    """
    plan, lounge, member, card = fixtures.setup_suspended_member(
        plan_overrides={
            "tier": "PRESTIGE", "included_visits_per_year": 50, "min_card_status": "BASIC",
        },
        lounge_overrides={"airport_code": "SAN", "capacity": 50},
    )
    reinstated = get_success_data(api_client.reinstate_member(member["id"], ADMIN))
    assert reinstated["standing"] == "GOOD", reinstated
    assert reinstated["no_show_strikes"] == 0, reinstated
    fresh_v = fixtures.get_lounge(lounge["id"])["version"]
    resp = api_client.create_visit(
        {"member_id": member["id"], "lounge_id": lounge["id"], "guest_count": 0,
         "expected_lounge_version": fresh_v},
        ADMIN,
    )
    visit = validate_success(resp, expected_status=201)
    assert visit["status"] == "HELD", visit


# ─── Queue A: transitive_cascade — strike -> suspend -> auto-cancel ──────────
def test_no_show_strike_suspends_and_autocancels_other_held_visit(api):
    """PRD §3.8: "When a member's recomputed `no_show_strikes` reaches three, the
    member's `standing` flips from `GOOD` to `SUSPENDED`, which by itself blocks any
    future hold. The suspension in turn auto-cancels every other visit of that
    member still in `HELD` status: each such hold transitions `HELD → CANCELLED`,
    and each cancellation releases that hold's `held_occupancy` at its own lounge —
    a third cascade hop that can flip several lounges back from `OVERFLOW` to
    `OPEN`."

    Member at 2 strikes holds VisitA on L1 and VisitB on L2; sweeping VisitA to
    NO_SHOW reaches strike 3 -> SUSPENDED -> auto-cancels VisitB -> releases L2's
    held seat.

    Design: Difficulty/transitive_cascade/tc_noshow_strike_suspend_autocancel_depth4
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=50, included_guest_visits_per_year=5)
    l1 = fixtures.create_lounge(airport_code="PHX", capacity=50)
    l2 = fixtures.create_lounge(airport_code="MIA", capacity=50)
    member = fixtures.create_member(plan["id"], full_name="Strike Member")
    fixtures.create_card(member["id"])

    # Accrue 2 strikes on L1 (held at 00:00, swept after 01:00).
    fixtures.open_hold(l1["id"], member_id=member["id"])
    fixtures.open_hold(l1["id"], member_id=member["id"])
    fixtures.set_clock("2026-06-01T01:00:00Z")
    get_success_data(api_client.sweep_lounge(l1["id"], ADMIN))
    assert fixtures.get_member(member["id"])["no_show_strikes"] == 2

    # VisitA on L1 at 02:00 (expires 02:30), VisitB on L2 at 02:20 (expires 02:50).
    fixtures.set_clock("2026-06-01T02:00:00Z")
    va = fixtures.open_hold(l1["id"], member_id=member["id"])
    fixtures.set_clock("2026-06-01T02:20:00Z")
    vb = fixtures.open_hold(l2["id"], member_id=member["id"])

    # Advance to 02:40 (past VisitA's expiry, before VisitB's) and sweep L1.
    fixtures.set_clock("2026-06-01T02:40:00Z")
    get_success_data(api_client.sweep_lounge(l1["id"], ADMIN))

    member_now = fixtures.get_member(member["id"])
    assert member_now["no_show_strikes"] == 3, member_now
    assert member_now["standing"] == "SUSPENDED", member_now
    assert get_success_data(api_client.get_visit(va["id"], ADMIN))["status"] == "NO_SHOW"
    assert get_success_data(api_client.get_visit(vb["id"], ADMIN))["status"] == "CANCELLED"
    assert fixtures.get_lounge(l2["id"])["held_occupancy"] == 0


# ─── Queue B: validation corners ─────────────────────────────────────────────
def test_below_minimum_card_with_business_fare_is_eligible(api):
    """PRD §3.5: "Second, the eligibility gate proper: the member is permitted to
    enter on allotment or overage only when their active card's `card_status` meets
    or exceeds the plan's `min_card_status`, or their card's `fare_class` is
    `BUSINESS` or `FIRST`. A member who satisfies neither condition is not eligible
    and the hold is rejected with `ERR_NOT_ELIGIBLE` (HTTP 422); a day-pass entry
    bypasses this eligibility gate entirely."

    A SILVER card (below GOLD min) with BUSINESS fare satisfies the override, so the
    hold succeeds.

    Design: Corner/validations/val_satisfaction_eligible_business_fare_passes
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(
        tier="PRESTIGE_PLUS", included_visits_per_year=10, min_card_status="GOLD"
    )
    lounge = fixtures.create_lounge(airport_code="SAN", capacity=10)
    member = fixtures.create_member(plan["id"], full_name="Biz Member")
    fixtures.create_card(member["id"], card_status="SILVER", fare_class="BUSINESS")
    fresh_v = fixtures.get_lounge(lounge["id"])["version"]
    resp = api_client.create_visit(
        {"member_id": member["id"], "lounge_id": lounge["id"], "guest_count": 0,
         "expected_lounge_version": fresh_v},
        ADMIN,
    )
    visit = validate_success(resp, expected_status=201)
    assert visit["status"] == "HELD", visit


def test_reinstate_good_member_rejected(api):
    """PRD §3.2: "A member's **standing** governs whether they may open new holds
    and is one of `GOOD` or `SUSPENDED`. Standing is driven solely by no-show
    strikes accumulating and by an operator reinstatement... When the operator
    reinstates a suspended member, `no_show_strikes` is reset to 0 and `standing`
    returns to `GOOD`."

    Reinstate is defined only from SUSPENDED; reinstating a GOOD member is rejected.

    Design: Corner/state_machines/sm_member_reinstate_from_good_invalid_state
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10)
    member = fixtures.create_member(plan["id"], full_name="Good Member")
    resp = api_client.reinstate_member(member["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Queue A second-coverage: transitive_cascade ─────────────────────────────
def test_standing_flips_to_suspended_exactly_at_third_strike(api):
    """PRD §3.8: "When a member's recomputed `no_show_strikes` reaches three, the
    member's `standing` flips from `GOOD` to `SUSPENDED`, which by itself blocks any
    future hold."

    The first link of the cascade at its boundary: after two swept no-shows the
    member is still GOOD (2 strikes); the third swept no-show is what flips standing
    to SUSPENDED.

    Design: Difficulty/transitive_cascade/tc_noshow_strike_suspend_autocancel_depth4
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=50)
    lounge = fixtures.create_lounge(airport_code="PHX", capacity=50)
    member = fixtures.create_member(plan["id"], full_name="Boundary Strike")
    fixtures.create_card(member["id"])

    # Two strikes: still GOOD.
    fixtures.open_hold(lounge["id"], member_id=member["id"])
    fixtures.open_hold(lounge["id"], member_id=member["id"])
    fixtures.set_clock("2026-06-01T01:00:00Z")
    get_success_data(api_client.sweep_lounge(lounge["id"], ADMIN))
    two = fixtures.get_member(member["id"])
    assert two["no_show_strikes"] == 2, two
    assert two["standing"] == "GOOD", two

    # Third strike: flips to SUSPENDED.
    fixtures.set_clock("2026-06-01T02:00:00Z")
    fixtures.open_hold(lounge["id"], member_id=member["id"])
    fixtures.set_clock("2026-06-01T03:00:00Z")
    get_success_data(api_client.sweep_lounge(lounge["id"], ADMIN))
    three = fixtures.get_member(member["id"])
    assert three["no_show_strikes"] == 3, three
    assert three["standing"] == "SUSPENDED", three
