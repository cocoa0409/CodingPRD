"""Standby claims: the deductible/reason-branch payable computation, the
aggregate shutdown-hours bound, the permit-window overlap gate, and the
equipment-breakdown fiscal rule (PRD §3.8).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    assert_standby_claim,
    file_claim,
    setup_dredging_reach, setup_species_shutdown,
    setup_equipment_shutdown, open_event, set_clock,
)


def _ctx_with_ten_shutdown_hours():
    """Active project, reach DREDGING, one event that accrued exactly 10.0h of
    SPECIES shutdown (06:00 -> 16:00) and was resumed."""
    ctx = setup_dredging_reach()
    event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                       "2026-05-10T00:00:00Z")
    ctx["event"] = event
    setup_species_shutdown(ctx, observed_utc="2026-05-10T06:00:00Z",
                           resume_at="2026-05-10T16:00:00Z")
    return ctx


class TestPayableComputation:
    def test_standby_pay_weather_and_species_branches(self, api):
        """PRD §3.8: "`payable_hours` is `claimed_hours` minus the standing
        deductible of 4 hours, floored at zero"; "The multiplier is 1.0 for
        `WEATHER`, 1.0 for `OWNER_DIRECTED`, 0.5 for `SPECIES_SHUTDOWN`, and 0
        for `EQUIPMENT_BREAKDOWN`."; "`payable_amount_cents` is `payable_hours`
        multiplied by the project's `standby_rate_cents_per_hour` and by the
        reason multiplier, rounded half up to whole cents".

        Design: Difficulty/combinatorial_formula/standby_pay_reason_branching_and_deductible
        """
        ctx = _ctx_with_ten_shutdown_hours()
        weather = file_claim(ctx["project"]["id"], ctx["plant"]["id"],
                             "2026-05-10T06:00:00Z", "2026-05-10T16:00:00Z",
                             10.0, "WEATHER")
        assert_standby_claim(weather)
        # (10.0 - 4.0) x 5000 x 1.0 = 30000
        assert weather["payable_hours"] == pytest.approx(6.0, abs=1e-4)
        assert weather["payable_amount_cents"] == 30000
        species = file_claim(ctx["project"]["id"], ctx["plant"]["id"],
                             "2026-05-10T06:00:00Z", "2026-05-10T16:00:00Z",
                             10.0, "SPECIES_SHUTDOWN")
        # (10.0 - 4.0) x 5000 x 0.5 = 15000
        assert species["payable_hours"] == pytest.approx(6.0, abs=1e-4)
        assert species["payable_amount_cents"] == 15000

    def test_standby_pay_equipment_zero_branch(self, api):
        """PRD §3.8: "except for `EQUIPMENT_BREAKDOWN`, whose multiplier is zero
        and whose `payable_hours` is therefore zero regardless of what was
        claimed."

        Design: Difficulty/combinatorial_formula/standby_pay_reason_branching_and_deductible
        """
        ctx = _ctx_with_ten_shutdown_hours()
        equipment = file_claim(ctx["project"]["id"], ctx["plant"]["id"],
                               "2026-05-10T06:00:00Z", "2026-05-10T16:00:00Z",
                               10.0, "EQUIPMENT_BREAKDOWN")
        assert_standby_claim(equipment)
        assert equipment["payable_hours"] == pytest.approx(0, abs=1e-4)
        assert equipment["payable_amount_cents"] == 0
        # Same hours and rate, three different outcomes: the reason branch
        # alone flips the payable amount.
        weather = file_claim(ctx["project"]["id"], ctx["plant"]["id"],
                             "2026-05-10T06:00:00Z", "2026-05-10T16:00:00Z",
                             10.0, "WEATHER")
        species = file_claim(ctx["project"]["id"], ctx["plant"]["id"],
                             "2026-05-10T06:00:00Z", "2026-05-10T16:00:00Z",
                             10.0, "SPECIES_SHUTDOWN")
        amounts = {weather["payable_amount_cents"],
                   species["payable_amount_cents"],
                   equipment["payable_amount_cents"]}
        assert amounts == {30000, 15000, 0}


class TestAggregateHonestyBound:
    def test_standby_hours_exceed_shutdown_rejected(self, api,
                                                    contractor_headers):
        """PRD §3.8: "One aggregate honesty check applies at creation:
        `claimed_hours` may not exceed the total `shutdown_accumulated_hours`
        that plant has accumulated across all of its dredge events on the
        claiming project, else the claim is rejected with
        `ERR_STANDBY_HOURS_EXCEED_SHUTDOWN` (HTTP 422)."

        Design: Corner/validations/standby_hours_exceed_shutdown_rejected
        """
        ctx = _ctx_with_ten_shutdown_hours()
        # 12.0 claimed against 10.0 accumulated.
        payload = {
            "project_id": ctx["project"]["id"],
            "plant_id": ctx["plant"]["id"],
            "period_start_utc": "2026-05-10T06:00:00Z",
            "period_end_utc": "2026-05-10T16:00:00Z",
            "claimed_hours": 12.0,
            "reason": "WEATHER",
        }
        res = api.create_standby_claim(payload, contractor_headers)
        validate_error(res, ApiErrorId.ERR_STANDBY_HOURS_EXCEED_SHUTDOWN,
                       expected_status=422)


class TestApprovalGates:
    def test_claim_period_outside_window_rejected(self, api, owner_headers):
        """PRD §3.8: "the claim period must overlap at least one `ISSUED`
        permit's closed window of the project — the two intervals sharing at
        least one instant, meaning the period begins at or before the window's
        end and the window begins at or before the period's end — else
        `ERR_CLAIM_PERIOD_OUTSIDE_WINDOW` (HTTP 409)".

        Design: Corner/validations/claim_period_outside_window_rejected
        """
        ctx = setup_dredging_reach()
        event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                           "2026-05-10T00:00:00Z")
        ctx["event"] = event
        setup_species_shutdown(ctx, observed_utc="2026-05-10T06:00:00Z",
                               resume_at="2026-05-10T14:00:00Z")
        # 8.0h accumulated; claim inside the bound but outside every permit
        # window (permit ends 2026-08-31).
        claim = file_claim(ctx["project"]["id"], ctx["plant"]["id"],
                           "2027-01-01T00:00:00Z", "2027-01-02T00:00:00Z",
                           8.0, "WEATHER")
        set_clock("2026-05-20T00:00:00Z")
        res = api.approve_standby_claim(claim["id"], owner_headers)
        validate_error(res, ApiErrorId.ERR_CLAIM_PERIOD_OUTSIDE_WINDOW,
                       expected_status=409)
        claim_after = validate_success(api.get_standby_claim(claim["id"],
                                                             owner_headers))
        assert claim_after["status"] == "SUBMITTED"

    def test_equipment_claim_approve_not_payable(self, api, owner_headers):
        """PRD §3.8: "an `EQUIPMENT_BREAKDOWN` claim is not payable at all, so
        approving one is rejected with `ERR_CLAIM_NOT_PAYABLE` (HTTP 422)."
        PRD §3.8: "except for `EQUIPMENT_BREAKDOWN`, whose multiplier is zero
        and whose `payable_hours` is therefore zero regardless of what was
        claimed."

        Design: Corner/validations/equipment_claim_approve_not_payable
        """
        ctx = setup_dredging_reach()
        event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                           "2026-05-10T00:00:00Z")
        ctx["event"] = event
        # 10.0h of EQUIPMENT shutdown (plant down 06:00 -> 16:00), then resumed.
        setup_equipment_shutdown(ctx, down_at="2026-05-10T06:00:00Z",
                                 up_at="2026-05-10T16:00:00Z")
        claim = file_claim(ctx["project"]["id"], ctx["plant"]["id"],
                           "2026-05-10T06:00:00Z", "2026-05-10T16:00:00Z",
                           10.0, "EQUIPMENT_BREAKDOWN")
        # Multiplier 0: payable fields are zero already at creation.
        assert claim["payable_amount_cents"] == 0
        assert claim["payable_hours"] == pytest.approx(0, abs=1e-4)
        res = api.approve_standby_claim(claim["id"], owner_headers)
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_PAYABLE,
                       expected_status=422)
        claim_after = validate_success(api.get_standby_claim(claim["id"],
                                                             owner_headers))
        assert claim_after["status"] == "SUBMITTED"
