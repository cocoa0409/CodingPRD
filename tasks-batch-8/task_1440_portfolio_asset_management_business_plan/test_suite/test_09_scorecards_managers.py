"""Scorecard composite scoring and rating boundaries, duplicate-period
uniqueness, manager termination guards, and the probation-streak suspension
cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_scorecard_payload,
    get_manager,
    get_plan,
    get_success_data,
    lines_plan10,
    make_property_manager_headers,
    setup_base_asset,
    setup_plan_scenario,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director"]
AM = TEST_USERS["asset_manager"]
ANALYST = TEST_USERS["analyst"]


def _submit_scorecard(api, asset_id, pm_id, period, occ, coll, renew, exp_bps):
    return get_success_data(api.create_performance_scorecard(
        create_scorecard_payload(asset_id, period, occ, coll, renew, exp_bps),
        make_property_manager_headers(pm_id)))


def test_scorecard_composite_boundary_85_excellent(api):
    """PRD §3.7: "The `composite_score` is then thirty times occupancy plus
    thirty times collections plus twenty-five times the expense score plus
    fifteen times renewal, divided by one hundred, rounded half-up to a whole
    number between 0 and 100."
    PRD §3.7: "The `rating` follows fixed thresholds: a composite of 85 or
    more earns `EXCELLENT`; 70 through 84 earns `SATISFACTORY`; 55 through 69
    earns `WATCH`; below 55 lands on `PROBATION`."

    Design: Corner/calculations/scorecard_composite_boundary_85_excellent
    """
    ctx = setup_base_asset()
    sc85 = _submit_scorecard(api, ctx["asset"]["id"], ctx["manager"]["id"],
                             "2026-Q1", 80, 80, 80, 0)
    assert sc85["composite_score"] == 85, \
        "round_half_up((2400+2400+2500+1200)/100)"
    assert sc85["rating"] == "EXCELLENT", "85 is inclusive at the top tier"

    sc84 = _submit_scorecard(api, ctx["asset"]["id"], ctx["manager"]["id"],
                             "2026-Q2", 80, 80, 76, 0)
    assert sc84["composite_score"] == 84, \
        "round_half_up((2400+2400+2500+1140)/100) = round_half_up(84.4)"
    assert sc84["rating"] == "SATISFACTORY"


def test_scorecard_duplicate_period_rejected(api):
    """PRD §3.7: "Only one scorecard may exist per asset and period in any
    status (`ERR_DUPLICATE_SCORECARD`)."

    Design: Corner/validations/scorecard_duplicate_period_rejected
    """
    ctx = setup_base_asset()
    _submit_scorecard(api, ctx["asset"]["id"], ctx["manager"]["id"],
                      "2026-Q1", 80, 90, 70, 0)
    res = api.create_performance_scorecard(
        create_scorecard_payload(ctx["asset"]["id"], "2026-Q1", 85, 95, 75,
                                 100),
        make_property_manager_headers(ctx["manager"]["id"]))
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SCORECARD)


def test_manager_terminate_in_use_rejected(api):
    """PRD §3.1: "Termination is refused with `ERR_MANAGER_IN_USE` while any
    asset in `OWNED`, `LISTED_FOR_SALE`, or `UNDER_CONTRACT` still references
    the manager."
    PRD §3.1: "The director may suspend a manager, moving `ACTIVE` to
    `SUSPENDED`".

    Design: Corner/validations/manager_terminate_in_use_rejected
    """
    ctx = setup_base_asset()
    res = api.suspend_property_manager(ctx["manager"]["id"],
                                       {"terminate": True}, DIRECTOR)
    validate_error(res, ApiErrorId.ERR_MANAGER_IN_USE)

    suspended = validate_success(api.suspend_property_manager(
        ctx["manager"]["id"], {}, DIRECTOR), 200)
    assert suspended["status"] == "SUSPENDED"


class TestProbationStreakSuspension:
    """Difficulty instance: transitive_cascade / probation_streak_suspends_manager.

    Scorecard (40, 50, 30, 1500): expense score = 100 - floor(1500/50) = 70,
    composite = round_half_up((1200+1500+1750+450)/100) = 49 -> PROBATION.
    """

    def _finalize_probation(self, api, asset_id, pm_id, period):
        sc = _submit_scorecard(api, asset_id, pm_id, period, 40, 50, 30, 1500)
        get_success_data(api.review_performance_scorecard(sc["id"], AM))
        return get_success_data(api.finalize_performance_scorecard(sc["id"], AM))

    def test_second_probation_finalization_suspends_manager(self, api):
        """PRD §3.7: "A finalized `PROBATION` rating increments the manager's
        `probation_streak` by one; any other rating resets the streak to zero.
        When the increment drives the streak to two — a second consecutive
        probation quarter — the manager cascades from `ACTIVE` to
        `SUSPENDED`".

        Design: Difficulty/transitive_cascade/probation_streak_suspends_manager
        """
        ctx = setup_base_asset()
        first = self._finalize_probation(api, ctx["asset"]["id"],
                                         ctx["manager"]["id"], "2026-Q1")
        assert first["rating"] == "PROBATION"
        assert first["composite_score"] == 49
        manager = get_manager(ctx["manager"]["id"])
        assert manager["probation_streak"] == 1
        assert manager["status"] == "ACTIVE"

        self._finalize_probation(api, ctx["asset"]["id"],
                                 ctx["manager"]["id"], "2026-Q2")
        manager = get_manager(ctx["manager"]["id"])
        assert manager["probation_streak"] == 2
        assert manager["status"] == "SUSPENDED", \
            "second consecutive PROBATION quarter cascades to SUSPENDED"

    def test_suspension_then_gates_plan_approval(self, api):
        """PRD §3.7: "the manager cascades from `ACTIVE` to `SUSPENDED`, with
        the plan-approval consequences of §3.2".
        PRD §3.2: "the asset's property manager must be `ACTIVE` — a
        `SUSPENDED` or `TERMINATED` manager blocks approval with
        `ERR_MANAGER_SUSPENDED`".

        Design: Difficulty/transitive_cascade/probation_streak_suspends_manager
        """
        ctx = setup_plan_scenario(fiscal_year=2027, lines=lines_plan10(),
                                  approve=False)  # plan SUBMITTED (gate probe)
        self._finalize_probation(api, ctx["asset"]["id"],
                                 ctx["manager"]["id"], "2026-Q1")
        self._finalize_probation(api, ctx["asset"]["id"],
                                 ctx["manager"]["id"], "2026-Q2")
        res = api.approve_business_plan(ctx["plan"]["id"], DIRECTOR)
        validate_error(res, ApiErrorId.ERR_MANAGER_SUSPENDED)
        assert get_plan(ctx["plan"]["id"])["status"] == "SUBMITTED"
