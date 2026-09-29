"""Legality decided by the state of a parent or grandparent entity."""
import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error
from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    make_energy_analyst_headers,
    make_energy_manager_headers,
)

CE1_RATES = {
    "utility_name": "Midland Power",
    "rate_family": "TOU_DEMAND",
    "demand_charge_per_kw": 14.50,
    "rate_on_peak": 0.1450,
    "rate_off_peak": 0.0800,
}

CE1_BASELINE = [
    f.demand_interval("2026-08-04T14:00:00Z", 1290.5, True),
    f.demand_interval("2026-08-04T15:00:00Z", 1275.0, True),
    f.demand_interval("2026-08-04T16:00:00Z", 1245.0, True),
]


def _one_store_two_notified_events(api):
    """Two accounts of the same store each holding a NOTIFIED event, with the
    clock parked at the first event's curtailment start."""
    ctx = fx.setup_commissioned_store(api, code="STR-CE1", floor_area_sqft=122000)
    account_1 = fx.create_account(api, ctx["store_id"], rate_schedule_code="TOU-A", **CE1_RATES)
    account_2 = fx.create_account(api, ctx["store_id"], rate_schedule_code="TOU-B", **CE1_RATES)
    fx.ingest_intervals(api, account_1["id"], CE1_BASELINE)
    fx.ingest_intervals(api, account_2["id"], CE1_BASELINE)
    event_a = fx.create_event(
        api, account_1["id"], program_code="CPP-2026",
        curtailment_start_iso="2026-08-05T14:00:00Z",
        curtailment_end_iso="2026-08-05T15:00:00Z", target_reduction_kw=200.0,
    )
    event_b = fx.create_event(
        api, account_2["id"], program_code="CPP-2026",
        curtailment_start_iso="2026-08-05T14:30:00Z",
        curtailment_end_iso="2026-08-05T15:30:00Z", target_reduction_kw=150.0,
    )
    fx.notify_event(api, event_a["id"])
    ctx["event_b_notified"] = fx.notify_event(api, event_b["id"])
    fx.set_clock(api, "2026-08-05T14:00:00Z")
    ctx["account_1_id"] = account_1["id"]
    ctx["account_2_id"] = account_2["id"]
    ctx["event_a_id"] = event_a["id"]
    ctx["event_b_id"] = event_b["id"]
    return ctx


class TestDrActivationBlockedByCurtailedPosture:
    def test_activating_the_first_event_curtails_the_whole_store(self, api):
        """The posture rises even though only one account is participating.

        The PRD states: "A successful activation advances `NOTIFIED → ACTIVE`, and
        the owning store immediately recomputes its posture and rises to
        `CURTAILED`."

        Design: Difficulty/cross_entity_state_dependency/dr_activation_blocked_by_store_curtailed_posture
        """
        ctx = _one_store_two_notified_events(api)
        assert ctx["store"]["energy_posture"] == "NORMAL"
        assert ctx["event_b_notified"]["event_state"] == "NOTIFIED"

        activated = fx.activate_event(api, ctx["event_a_id"])
        store = fx.read_store(api, ctx["store_id"])

        assert activated["event_state"] == "ACTIVE"
        assert store["energy_posture"] == "CURTAILED"

    def test_the_grandparent_posture_blocks_the_second_account_event(self, api):
        """Nothing about account 2 changed, yet its activation is refused.

        The PRD states: "requires the owning account's store to be in `NORMAL` or
        `CONSTRAINED` — a store in `CURTAILED` or `LOCKED` is refused with
        `ERR_FOOD_SAFETY_HOLD`".

        Design: Difficulty/cross_entity_state_dependency/dr_activation_blocked_by_store_curtailed_posture
        """
        ctx = _one_store_two_notified_events(api)
        fx.activate_event(api, ctx["event_a_id"])
        fx.set_clock(api, "2026-08-05T14:30:00Z")

        response = api.activate_demand_response_event(ctx["event_b_id"], fx.MANAGER)

        validate_error(response, ApiErrorId.ERR_FOOD_SAFETY_HOLD.value, 409)
        events, _ = fx.list_events(api, ctx["account_2_id"])
        account_2 = fx.read_account(api, ctx["account_2_id"])
        assert fx.find_row(events, ctx["event_b_id"])["event_state"] == "NOTIFIED"
        assert account_2["dr_optout_count"] == 0

    def test_the_sweep_releases_the_posture_and_the_same_request_succeeds(self, api):
        """Completing the first event unblocks the second, unchanged request.

        The PRD states: "during the sweep, every event whose `event_state` is
        `ACTIVE` and whose `curtailment_end_iso` is at or before the new clock value
        advances `ACTIVE → COMPLETED`, its settlement dimension untouched, after
        which the store's posture is recomputed and falls out of `CURTAILED` if no
        other event of the account remains `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/dr_activation_blocked_by_store_curtailed_posture
        """
        ctx = _one_store_two_notified_events(api)
        fx.activate_event(api, ctx["event_a_id"])
        fx.set_clock(api, "2026-08-05T14:30:00Z")
        api.activate_demand_response_event(ctx["event_b_id"], fx.MANAGER)

        sweep = fx.set_clock(api, "2026-08-05T15:00:00Z")
        released = fx.read_store(api, ctx["store_id"])
        activated_b = fx.activate_event(api, ctx["event_b_id"])
        curtailed_again = fx.read_store(api, ctx["store_id"])

        assert sweep["dr_events_completed"] == 1
        assert sweep["stores_posture_recomputed"] == 1
        assert released["energy_posture"] == "NORMAL"
        events, _ = fx.list_events(api, ctx["account_1_id"])
        assert fx.find_row(events, ctx["event_a_id"])["event_state"] == "COMPLETED"
        assert activated_b["event_state"] == "ACTIVE"
        assert curtailed_again["energy_posture"] == "CURTAILED"


CE2_ACCOUNT = {
    "utility_name": "Midland Power",
    "rate_schedule_code": "TOU-GS3",
    "rate_family": "TOU_DEMAND",
    "demand_charge_per_kw": 14.50,
    "rate_on_peak": 0.1450,
    "rate_off_peak": 0.0800,
    "ratchet_peak_kw": 1500.0,
    "candidate_rate_schedule_code": "TOU-GS4",
    "candidate_rate_family": "TOU_DEMAND",
    "candidate_demand_charge_per_kw": 11.00,
    "candidate_rate_on_peak": 0.1100,
    "candidate_rate_off_peak": 0.0700,
}

CE2_CONSUMPTION = {
    "on_peak_kwh": 240000,
    "off_peak_kwh": 518000,
    "billed_kwh": 758000,
    "billed_peak_kw": 1310.5,
}


def _disputed_bill_on_a_switchable_account(api):
    """A VALIDATED June reference bill and a DISPUTED July bill on one account
    whose candidate schedule is comfortably cheaper."""
    ctx = fx.setup_commissioned_store(api, code="STR-CE2")
    account = fx.create_account(api, ctx["store_id"], **CE2_ACCOUNT)
    fx.ingest_intervals(
        api, account["id"],
        [
            f.demand_interval("2026-06-10T18:00:00Z", 1310.5, True),
            f.demand_interval("2026-07-10T18:00:00Z", 1310.5, True),
        ],
    )
    analyst = make_energy_analyst_headers("u_analyst_ce2")
    bill_1 = fx.create_bill(
        api, account["id"], period_start_iso="2026-06-01T00:00:00Z",
        period_end_iso="2026-07-01T00:00:00Z", billed_amount_usd=99996.04,
        **CE2_CONSUMPTION,
    )
    ctx["bill_1"] = fx.recompute_bill(api, bill_1["id"], analyst)
    bill_2 = fx.create_bill(
        api, account["id"], period_start_iso="2026-07-01T00:00:00Z",
        period_end_iso="2026-08-01T00:00:00Z", billed_amount_usd=102500.00,
        **CE2_CONSUMPTION,
    )
    ctx["bill_2_flagged"] = fx.recompute_bill(api, bill_2["id"], analyst)
    ctx["bill_2_disputed"] = get_success_data(
        api.dispute_utility_bill(
            bill_2["id"],
            f.dispute_payload("on-peak kWh double counted by the utility"),
            analyst,
        )
    )
    ctx["account"] = account
    ctx["account_id"] = account["id"]
    ctx["bill_1_id"] = bill_1["id"]
    ctx["bill_2_id"] = bill_2["id"]
    return ctx


class TestBillAdjustmentBlockedByPendingTariffSwitch:
    def test_the_projection_recommends_the_cheaper_candidate_schedule(self, api):
        """The comparison annualises both sides off the validated reference bill.

        The PRD states: "Finally, `switch_recommended` is true when
        `annual_delta_usd` is at or below negative two thousand five hundred
        dollars, meaning the switch must save at least 2500.00 dollars a year to be
        worth doing; a saving of exactly that amount qualifies."

        Design: Difficulty/cross_entity_state_dependency/bill_adjustment_blocked_by_pending_tariff_switch
        """
        ctx = _disputed_bill_on_a_switchable_account(api)
        assert ctx["account"]["tariff_state"] == "STABLE"
        assert ctx["bill_1"]["validation_state"] == "VALIDATED"
        assert ctx["bill_1"]["variance_pct"] == pytest.approx(0.00, abs=0.01)
        assert ctx["bill_2_flagged"]["validation_state"] == "VARIANCE_FLAGGED"
        assert ctx["bill_2_flagged"]["variance_pct"] == pytest.approx(2.50, abs=0.01)
        assert ctx["bill_2_disputed"]["validation_state"] == "DISPUTED"

        comparison = get_success_data(
            api.get_tariff_comparison(ctx["account_id"], make_energy_analyst_headers("u_analyst_ce2"))
        )

        assert comparison["reference_bill_id"] == ctx["bill_1_id"]
        assert comparison["current_annual_cost_usd"] == pytest.approx(1199952.48, abs=0.01)
        assert comparison["candidate_annual_cost_usd"] == pytest.approx(970383.84, abs=0.01)
        assert comparison["annual_delta_usd"] == pytest.approx(-229568.64, abs=0.01)
        assert comparison["switch_recommended"] is True
        assert comparison["candidate_peak_basis"] == "COINCIDENT_PEAK"

    def test_scheduling_the_switch_moves_the_account_to_pending_switch(self, api):
        """The parent account records the pending move.

        The PRD states: "An accepted switch sets `tariff_state` to
        `PENDING_SWITCH`, records `tariff_switch_effective_from_iso` from the
        supplied instant, and increments the account's `version`."

        Design: Difficulty/cross_entity_state_dependency/bill_adjustment_blocked_by_pending_tariff_switch
        """
        ctx = _disputed_bill_on_a_switchable_account(api)
        account = fx.read_account(api, ctx["account_id"])

        switched = get_success_data(
            api.tariff_switch(
                ctx["account_id"],
                f.tariff_switch_payload("2026-09-01T00:00:00Z", account["version"]),
                fx.MANAGER,
            )
        )

        assert switched["tariff_state"] == "PENDING_SWITCH"
        assert switched["tariff_switch_effective_from_iso"].startswith("2026-09-01T00:00:00")
        assert switched["version"] == account["version"] + 1

    def test_the_pending_switch_blocks_an_otherwise_legal_adjustment(self, api):
        """Every gate of the bill's own lifecycle passes, and it is still refused.

        The PRD states: "and the owning account's `tariff_state` must be `STABLE`,
        because negotiating a final amount while a tariff switch is pending would
        settle against a price list that is about to change — a pending switch
        yields `ERR_TARIFF_SWITCH_IN_PROGRESS` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/bill_adjustment_blocked_by_pending_tariff_switch
        """
        ctx = _disputed_bill_on_a_switchable_account(api)
        account = fx.read_account(api, ctx["account_id"])
        get_success_data(
            api.tariff_switch(
                ctx["account_id"],
                f.tariff_switch_payload("2026-09-01T00:00:00Z", account["version"]),
                fx.MANAGER,
            )
        )

        response = api.adjust_utility_bill(
            ctx["bill_2_id"], f.adjustment_payload(99996.04),
            make_energy_manager_headers("u_manager_ce2"),
        )

        validate_error(response, ApiErrorId.ERR_TARIFF_SWITCH_IN_PROGRESS.value, 409)
        bills, _ = fx.list_bills(api, ctx["account_id"])
        bill_2 = fx.find_row(bills, ctx["bill_2_id"])
        assert bill_2["validation_state"] == "DISPUTED"
        assert bill_2["adjusted_amount_usd"] is None
