"""Drilling execution: tiered cost computation, per-boring floor, immediate
consistency, refusal, the offset mechanism, and terminal lockdown."""
import pytest

from test_helpers import (
    PM,
    SE,
    ApiErrorId,
    api_client,
    approve_authorization,
    assert_boring,
    create_authorization,
    drill_boring,
    get_success_data,
    make_drilling_sub_headers,
    setup_boring_cleared,
    setup_drilled_boring,
    setup_refused_boring,
    transition_boring,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Tiered drilling cost (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestDrillingCostTieredRockSurchargeMin:
    """A 40-ft boring with 10 ft of rock and difficult access as the plan's
    first drill: 25*4200 + 15*6800 footage, plus 10*6800*0.8 rock premium on
    the deepest 10 feet (which lie in the 25-75 ft band), plus the 15,000
    surcharge, above the 25,000 floor, plus 45,000 first-boring mobilization.
    """

    def _drill(self, api):
        ctx = setup_boring_cleared(planned_depth_ft=40, access_difficult=True)
        resp = api.transition_boring(
            ctx["boring"]["id"],
            {"to": "DRILLED", "actual_depth_ft": 40, "rock_depth_ft": 10,
             "groundwater_depth_ft": 12, "avg_n60": 20},
            make_drilling_sub_headers(ctx["subcontractor"]["id"]))
        return ctx, resp

    def test_tiered_cost_with_rock_surcharge_and_mobilization(self, api):
        """PRD section 3.3: "Each of the first 25 feet bills at 4,200 cents
        per foot; each foot beyond 25, up to and including 75 feet, bills at
        6,800 cents per foot; each foot beyond 75 bills at 9,500 cents per
        foot. Rock carries a multiplier: the deepest `rock_depth_ft` feet of
        the drilled interval are rock, and each rock foot bills at its own
        depth band's rate multiplied by 1.8 instead of the plain band rate —
        equivalently, the rock premium adds eight-tenths of the applicable
        band rate per rock foot. When `access_difficult` is true, a flat
        15,000-cent surcharge applies. A per-boring floor then raises the
        boring's cost to 25,000 cents when footage plus rock premium plus
        surcharge would otherwise total less. Finally, mobilization: 45,000
        cents is added only for the first boring of the plan to reach
        `DRILLED`, the event that flips `mobilization_charged`."

        Design: Difficulty/combinatorial_formula/drilling_cost_tiered_rock_surcharge_min
        """
        _ctx, resp = self._drill(api)
        bored = validate_success(resp)
        assert_boring(bored)
        # 105000 + 102000 footage, + 54400 rock premium, + 15000 surcharge,
        # = 276400 (above the 25000 floor), + 45000 mobilization.
        assert bored["drilling_cost_cents"] == 321400

    def test_cost_persisted_and_plan_locked_with_mobilization_charged(self, api):
        """PRD section 3.3: "At that moment the server also computes
        `drilling_cost_cents`; locks the plan — the owning plan transitions
        `APPROVED` → `LOCKED` on this first drill; flips the plan's
        `mobilization_charged` flag from false to true when this is the first
        boring of the plan to reach `DRILLED`" and "The result is stored on
        the boring as `drilling_cost_cents` in integer cents, the tier
        arithmetic itself exact."

        Design: Difficulty/combinatorial_formula/drilling_cost_tiered_rock_surcharge_min
        """
        ctx, resp = self._drill(api)
        validate_success(resp)

        reread = get_success_data(api.get_boring(ctx["boring"]["id"], PM))
        assert reread["drilling_cost_cents"] == 321400

        plan = get_success_data(api.get_boring_plan(ctx["plan"]["id"], SE))
        assert plan["status"] == "LOCKED"
        assert plan["mobilization_charged"] is True


def test_drilling_minimum_charge_floor(api):
    """PRD section 3.3: "A per-boring floor then raises the boring's cost to
    25,000 cents when footage plus rock premium plus surcharge would
    otherwise total less. Finally, mobilization: 45,000 cents is added only
    for the first boring of the plan to reach `DRILLED`, the event that flips
    `mobilization_charged`."

    Design: Corner/calculations/drilling_minimum_charge_floor
    """
    ctx = setup_boring_cleared(planned_depth_ft=3)
    bored = drill_boring(ctx["boring"]["id"], ctx["subcontractor"]["id"],
                         actual_depth_ft=3, rock_depth_ft=0,
                         groundwater_depth_ft=12, avg_n60=8)
    # Raw footage 3 * 4200 = 12600 < 25000 floor; floor binds, then +45000
    # first-boring mobilization.
    assert bored["drilling_cost_cents"] == 70000, (
        f"Floor 25000 + mobilization 45000 = 70000, got "
        f"{bored['drilling_cost_cents']}"
    )


def test_drill_response_carries_computed_cost_immediately(api):
    """PRD section 3.3: "At that moment the server also computes
    `drilling_cost_cents`".
    PRD section 2.2: "Unless otherwise noted, operations that create or
    modify a resource will return the created or updated resource object in
    the data field."

    Design: Corner/consistency_model/immediate_consistency_drill_response_contains_cost
    """
    ctx = setup_boring_cleared()
    pre = get_success_data(api.get_boring(ctx["boring"]["id"], PM))
    resp = api.transition_boring(
        ctx["boring"]["id"],
        {"to": "DRILLED", "actual_depth_ft": 30, "rock_depth_ft": 0,
         "groundwater_depth_ft": 12, "avg_n60": 12},
        make_drilling_sub_headers(ctx["subcontractor"]["id"]))
    bored = validate_success(resp)
    assert bored["status"] == "DRILLED"
    # 25*4200 + 5*6800 = 139000 footage, + 45000 first-boring mobilization.
    assert bored["drilling_cost_cents"] == 184000
    assert bored["version"] > pre["version"], (
        "The transition increments the boring's version"
    )


# ---------------------------------------------------------------------------
# Refusal and the offset mechanism
# ---------------------------------------------------------------------------

def test_offset_create_from_non_refused_rejected(api):
    """PRD section 3.3: "A `StaffEngineer` may create an offset boring from a
    parent boring that stands in `REFUSED`; a parent in any other state draws
    `ERR_OFFSET_PARENT_NOT_REFUSED` (HTTP 422)."

    Design: Corner/state_machines/offset_create_from_non_refused_rejected
    """
    ctx = setup_drilled_boring()  # parent stands in DRILLED, not REFUSED
    resp = api.create_offset_boring(
        ctx["boring"]["id"], {"boring_no": "B-1A", "planned_depth_ft": 30}, SE)
    validate_error(resp, ApiErrorId.ERR_OFFSET_PARENT_NOT_REFUSED)
    assert resp.status_code == 422


def test_offset_consumes_authorization_then_exhausts(api):
    """PRD section 3.3: "When the offset would push the plan's boring tally
    beyond `planned_boring_count`, the project must hold an `APPROVED`
    ExplorationAuthorization whose `consumed_boring_count` is still below its
    `extra_boring_count` (`ERR_EXTRA_BORINGS_EXHAUSTED`, HTTP 422,
    otherwise); creating such an over-plan offset increments the
    authorization's `consumed_boring_count` by 1, and when the count reaches
    `extra_boring_count` the authorization transitions automatically from
    `APPROVED` to `EXHAUSTED`, its amount remaining committed on the
    project."

    Design: Corner/state_machines/offset_consumes_authorization_then_exhausts
    """
    ctx = setup_refused_boring()  # plan count 1, B-1 REFUSED at 18 ft
    project_id = ctx["project"]["id"]
    auth = create_authorization(project_id, authorized_amount_cents=100000,
                                extra_boring_count=1)
    approve_authorization(auth["id"], ctx["client"]["id"], project_id)

    offset = get_success_data(api.create_offset_boring(
        ctx["boring"]["id"], {"boring_no": "B-1A", "planned_depth_ft": 30}, SE))
    assert offset["offset_of_boring_id"] == ctx["boring"]["id"], (
        "The offset's self-referential link points back at the refused parent"
    )

    auth_after = get_success_data(
        api.get_exploration_authorization(auth["id"], PM))
    assert auth_after["consumed_boring_count"] == 1
    assert auth_after["status"] == "EXHAUSTED", (
        "Reaching extra_boring_count transitions the authorization to EXHAUSTED"
    )

    resp = api.create_offset_boring(
        ctx["boring"]["id"], {"boring_no": "B-1B", "planned_depth_ft": 30}, SE)
    validate_error(resp, ApiErrorId.ERR_EXTRA_BORINGS_EXHAUSTED)
    assert resp.status_code == 422


def test_terminal_lockdown_closed_boring_rejects_transition(api):
    """PRD section 3: "where a transition has no guard listed, only the
    from-state itself constrains it, and requesting any transition from a
    state that does not offer it is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."
    PRD section 3.3: "a `StaffEngineer` later closes the log (`LOGGED` →
    `CLOSED`), at which point the boring is backfilled and sealed."

    Design: Corner/state_machines/terminal_lockdown_closed_boring_rejects_transition
    """
    from test_helpers import FG, create_sample
    ctx = setup_drilled_boring()
    create_sample(ctx["boring"]["id"])
    transition_boring(ctx["boring"]["id"], "LOGGED", FG)
    closed = transition_boring(ctx["boring"]["id"], "CLOSED", SE)
    assert closed["status"] == "CLOSED"

    resp = api.transition_boring(ctx["boring"]["id"], {"to": "CLEARED"}, SE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    reread = get_success_data(api.get_boring(ctx["boring"]["id"], PM))
    assert reread["status"] == "CLOSED"
