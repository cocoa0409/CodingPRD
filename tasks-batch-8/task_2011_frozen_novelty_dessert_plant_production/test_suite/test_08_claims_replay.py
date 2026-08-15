"""Temperature-abuse claims: replay engine, dual payout variants, appeal
window, ownership (PRD §3.9)."""
import pytest

from test_helpers import (
    allocate,
    create_customer,
    create_shipment,
    file_claim,
    get_success_data,
    set_clock,
    setup_completed_run,
    setup_delivered_shipment,
    validate_success,
)
from test_helpers.fixtures import ADJUSTER, WH

STANDARD_LOG = [
    {"recorded_at": "2026-08-12T08:00:00Z", "temp_c": -19.0},
    {"recorded_at": "2026-08-12T09:00:00Z", "temp_c": -16.0},
    {"recorded_at": "2026-08-12T10:00:00Z", "temp_c": -16.0},
    {"recorded_at": "2026-08-12T11:00:00Z", "temp_c": -20.0},
    {"recorded_at": "2026-08-12T12:00:00Z", "temp_c": -15.0},
]


def _shifted_log(day):
    return [{"recorded_at": r["recorded_at"].replace("2026-08-12", day),
             "temp_c": r["temp_c"]} for r in STANDARD_LOG]


class TestDualVariantPayout:
    def test_standard_vs_carrier_payout_on_identical_logs(self, api):
        """PRD §3.9: standard variant "tiers marginally on abuse_minutes:
        the first 30 minutes are free; minutes beyond 30 up to and including
        120 pay 200 cents per minute; minutes beyond 120 pay 350 cents per
        minute" and carrier variant: "the payout is abuse_minutes multiplied
        by 150 cents, minus a fixed 5000-cent deductible, floored at zero,
        then capped at 80% of declared_value_cents". Identical logs replay
        to abuse_minutes 180: standard pays 90*200 + 60*350 = 39000; carrier
        pays max(0, 180*150 - 5000) = 22000.

        Design: Difficulty/dual_variant_calc/claim_payout_standard_vs_carrier_policy
        """
        ctx = setup_completed_run(actual_units=2000, mix_metered_litres=100.0)
        customer = create_customer()
        # Standard shipment (carrier_liability omitted -> false).
        sh_std = create_shipment(customer["id"], shipment_code="SH-STD")
        allocate(sh_std["id"], ctx["lot"]["id"], 1000)
        get_success_data(api.load_shipment(sh_std["id"], WH))
        set_clock("2026-08-12T08:00:00Z")
        get_success_data(api.dispatch_shipment(sh_std["id"], WH))
        get_success_data(api.append_temperature_readings(
            sh_std["id"], {"readings": STANDARD_LOG}, WH), 201)
        set_clock("2026-08-12T13:00:00Z")
        get_success_data(api.deliver_shipment(sh_std["id"], WH))
        # Carrier shipment with a byte-identical log one day later.
        sh_car = create_shipment(customer["id"], shipment_code="SH-CAR",
                                 carrier_liability=True)
        allocate(sh_car["id"], ctx["lot"]["id"], 1000)
        get_success_data(api.load_shipment(sh_car["id"], WH))
        set_clock("2026-08-13T08:00:00Z")
        get_success_data(api.dispatch_shipment(sh_car["id"], WH))
        get_success_data(api.append_temperature_readings(
            sh_car["id"], {"readings": _shifted_log("2026-08-13")}, WH), 201)
        set_clock("2026-08-13T13:00:00Z")
        get_success_data(api.deliver_shipment(sh_car["id"], WH))
        cl_std = file_claim(sh_std["id"], customer["id"], claim_code="CL-STD",
                            declared_value_cents=100000)
        cl_car = file_claim(sh_car["id"], customer["id"], claim_code="CL-CAR",
                            declared_value_cents=100000)
        std = validate_success(api.open_claim_review(cl_std["id"], ADJUSTER))
        car = validate_success(api.open_claim_review(cl_car["id"], ADJUSTER))
        assert std["abuse_minutes"] == 180
        assert car["abuse_minutes"] == 180
        assert std["peak_temp_c"] == pytest.approx(-15.0, abs=0.001)
        assert car["peak_temp_c"] == pytest.approx(-15.0, abs=0.001)
        assert std["payout_standard_cents"] == 39000
        assert car["payout_carrier_cents"] == 22000
        assert std["payout_standard_cents"] != car["payout_carrier_cents"]

    def test_approve_selects_variant_from_carrier_liability(self, api):
        """PRD §3.9: "When the shipment's carrier_liability is true,
        payout_variant becomes CARRIER and payout_cents becomes
        payout_carrier_cents; otherwise payout_variant becomes STANDARD and
        payout_cents becomes payout_standard_cents."

        Design: Difficulty/dual_variant_calc/claim_payout_standard_vs_carrier_policy
        """
        ctx = setup_completed_run(actual_units=2000, mix_metered_litres=100.0)
        customer = create_customer()
        sh_std = create_shipment(customer["id"], shipment_code="SH-STD")
        allocate(sh_std["id"], ctx["lot"]["id"], 1000)
        get_success_data(api.load_shipment(sh_std["id"], WH))
        set_clock("2026-08-12T08:00:00Z")
        get_success_data(api.dispatch_shipment(sh_std["id"], WH))
        get_success_data(api.append_temperature_readings(
            sh_std["id"], {"readings": STANDARD_LOG}, WH), 201)
        set_clock("2026-08-12T13:00:00Z")
        get_success_data(api.deliver_shipment(sh_std["id"], WH))
        sh_car = create_shipment(customer["id"], shipment_code="SH-CAR",
                                 carrier_liability=True)
        allocate(sh_car["id"], ctx["lot"]["id"], 1000)
        get_success_data(api.load_shipment(sh_car["id"], WH))
        set_clock("2026-08-13T08:00:00Z")
        get_success_data(api.dispatch_shipment(sh_car["id"], WH))
        get_success_data(api.append_temperature_readings(
            sh_car["id"], {"readings": _shifted_log("2026-08-13")}, WH), 201)
        set_clock("2026-08-13T13:00:00Z")
        get_success_data(api.deliver_shipment(sh_car["id"], WH))
        cl_std = file_claim(sh_std["id"], customer["id"], claim_code="CL-STD",
                            declared_value_cents=100000)
        cl_car = file_claim(sh_car["id"], customer["id"], claim_code="CL-CAR",
                            declared_value_cents=100000)
        validate_success(api.open_claim_review(cl_std["id"], ADJUSTER))
        validate_success(api.open_claim_review(cl_car["id"], ADJUSTER))
        std = validate_success(api.approve_claim(cl_std["id"], ADJUSTER))
        car = validate_success(api.approve_claim(cl_car["id"], ADJUSTER))
        assert std["payout_variant"] == "STANDARD"
        assert std["payout_cents"] == 39000
        assert car["payout_variant"] == "CARRIER"
        assert car["payout_cents"] == 22000


class TestAbuseThresholdBoundary:
    def test_abuse_threshold_one_tenth_above_counts(self, api):
        """PRD §3.9: "abuse_minutes accumulates, for each consecutive pair,
        the minutes between the two timestamps whenever the earlier
        reading's temp_c is strictly above -18.0; a reading at exactly
        -18.0 contributes zero abuse." A reading at -17.9 IS strictly above
        -18.0, so the 08:00-09:00 interval it opens contributes 60 abuse
        minutes — the strictly-greater boundary is observable from either
        side.

        Design: Difficulty/boundary_precision_check/abuse_threshold_strictly_greater_boundary
        """
        ctx = setup_delivered_shipment(
            readings=[
                {"recorded_at": "2026-08-12T08:00:00Z", "temp_c": -17.9},
                {"recorded_at": "2026-08-12T09:00:00Z", "temp_c": -19.0},
            ],
            deliver_time="2026-08-12T10:00:00Z")
        claim = file_claim(ctx["shipment"]["id"], ctx["customer"]["id"],
                           claim_code="CL-E2")
        reviewed = validate_success(api.open_claim_review(claim["id"], ADJUSTER))
        assert reviewed["abuse_minutes"] == 60
        # 60 minutes is inside the 30..120 low tier: (60-30)*200 = 6000.
        assert reviewed["payout_standard_cents"] == 6000


class TestReplayBoundaries:
    def test_abuse_threshold_strictly_greater_boundary(self, api):
        """PRD §3.9: "abuse_minutes accumulates, for each consecutive pair,
        the minutes between the two timestamps whenever the earlier
        reading's temp_c is strictly above -18.0; a reading at exactly
        -18.0 contributes zero abuse." Both intervals here sit exactly on
        -18.0, so abuse stays 0 and the standard payout is 0 ("the first 30
        minutes are free").

        Design: Difficulty/boundary_precision_check/abuse_threshold_strictly_greater_boundary
        """
        ctx = setup_delivered_shipment(
            readings=[
                {"recorded_at": "2026-08-12T08:00:00Z", "temp_c": -18.0},
                {"recorded_at": "2026-08-12T09:00:00Z", "temp_c": -18.0},
            ],
            deliver_time="2026-08-12T10:00:00Z")
        claim = file_claim(ctx["shipment"]["id"], ctx["customer"]["id"],
                           claim_code="CL-E")
        reviewed = validate_success(api.open_claim_review(claim["id"], ADJUSTER))
        assert reviewed["abuse_minutes"] == 0
        assert reviewed["peak_temp_c"] == pytest.approx(-18.0, abs=0.001)
        assert reviewed["payout_standard_cents"] == 0

    def test_replay_excludes_predispatch_readings(self, api):
        """PRD §3.9: the replay walks "the shipment's in-window readings —
        those with recorded_at between dispatched_at and closed_at,
        inclusive on both ends"; "Readings before dispatch (logger warm-up)
        and after closure (late uploads) are excluded." The -10.0 warm-up
        reading at 07:30 precedes dispatch (08:00) so abuse stays 0 and
        peak stays -19.0.

        Design: Corner/calculations/replay_excludes_predispatch_readings
        """
        ctx = setup_delivered_shipment(
            readings=[
                {"recorded_at": "2026-08-12T07:30:00Z", "temp_c": -10.0},
                {"recorded_at": "2026-08-12T08:30:00Z", "temp_c": -19.0},
                {"recorded_at": "2026-08-12T09:30:00Z", "temp_c": -19.0},
            ],
            deliver_time="2026-08-12T10:30:00Z")
        claim = file_claim(ctx["shipment"]["id"], ctx["customer"]["id"],
                           claim_code="CL-PD")
        reviewed = validate_success(api.open_claim_review(claim["id"], ADJUSTER))
        assert reviewed["abuse_minutes"] == 0
        assert reviewed["peak_temp_c"] == pytest.approx(-19.0, abs=0.001)

    def test_replay_tie_break_created_at_ordering(self, api):
        """PRD §3.9: readings are "sorted by recorded_at ascending, with
        ties broken by created_at ascending". Two readings share recorded_at
        08:00; the later-created one (-16.0) is ordered after the -20.0
        reading, so the -16.0 reading governs interval 08:00-09:00 and the
        interval contributes 60 abuse minutes; the 09:00 -19.0 reading is
        at/below -18.0 so the closing interval contributes nothing.

        Design: Corner/calculations/replay_tie_break_created_at_ordering
        """
        ctx = setup_completed_run(actual_units=2000, mix_metered_litres=100.0)
        customer = create_customer()
        shipment = create_shipment(customer["id"], shipment_code="SH-TB")
        allocate(shipment["id"], ctx["lot"]["id"], 500)
        get_success_data(api.load_shipment(shipment["id"], WH))
        set_clock("2026-08-12T08:00:00Z")
        get_success_data(api.dispatch_shipment(shipment["id"], WH))
        # First batch creates the 08:00 -20.0 reading; the second batch
        # creates the 08:00 -16.0 reading later (created_at tie-break).
        get_success_data(api.append_temperature_readings(
            shipment["id"],
            {"readings": [{"recorded_at": "2026-08-12T08:00:00Z",
                           "temp_c": -20.0}]}, WH), 201)
        get_success_data(api.append_temperature_readings(
            shipment["id"],
            {"readings": [{"recorded_at": "2026-08-12T08:00:00Z",
                           "temp_c": -16.0},
                          {"recorded_at": "2026-08-12T09:00:00Z",
                           "temp_c": -19.0}]}, WH), 201)
        set_clock("2026-08-12T10:00:00Z")
        get_success_data(api.deliver_shipment(shipment["id"], WH))
        claim = file_claim(shipment["id"], customer["id"], claim_code="CL-TB")
        reviewed = validate_success(api.open_claim_review(claim["id"], ADJUSTER))
        assert reviewed["abuse_minutes"] == 60
