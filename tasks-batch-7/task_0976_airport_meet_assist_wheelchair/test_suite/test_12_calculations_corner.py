"""Corner queue B — calculations section instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, create_agent, create_wheelchair,
    submit_request, dispatch_leg, set_clock, setup_completed_request,
    api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]


class TestProvisionalBaseline:
    def test_provisional_charge_with_zero_companion_and_no_equipment(self, api):
        """PRD §3.3: "Begin with the per-leg base in cents, which is fixed by
        `leg_kind`: 6000 cents for `MEET_ARRIVAL`... Add the applicable flat fees,
        each in cents: the companion fee is 1500 cents multiplied by the request's
        `companion_count`; the equipment fee is 1800 cents when the leg requires a
        WCHC-rated chair, otherwise 800 cents when the leg merely requires a
        wheelchair, otherwise zero..."

        Design: Corner/calculations/provisional_charge_with_zero_companion_and_no_equipment
        """
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="PIT", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="M", requires_secure_escort=False)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="PIT1",
            direction="ARRIVAL", scheduled_utc="2026-06-16T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="P PIT", dob="1990-01-01", mobility_code="WCHR",
            airline_pnr="PIT1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="STANDARD",
            companion_count=0,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="MEET_ARRIVAL", pickup_zone="Z")
        submitted = submit_request(request["id"])
        leg_after = get_success_data(api_client.get_leg(leg["id"], REQ))
        # 6000 base; WCHR does not set requires_wheelchair (PRD §3.2), so the
        # equipment fee is zero; companion_count 0 → 6000; tier 1.0, posture 1.0
        assert leg_after["provisional_leg_cents"] == 6000
        assert submitted["provisional_charge_cents"] == 6000


class TestOnTimeArrivalZeroDelaySurcharge:
    def test_on_time_arrival_zero_delay_surcharge(self, api):
        """PRD §3.6: "the delay in minutes is the non-negative difference between
        `actual_utc` and `scheduled_utc`, converted to minutes; a grace of 20
        minutes is subtracted; any positive remainder is charged at 75 cents per
        minute."

        Design: Corner/calculations/on_time_arrival_zero_delay_surcharge
        """
        # 15 min delay <= 20 min grace → no surcharge
        out = setup_completed_request(
            iata_code="BNA",
            meet_buffer_minutes=15,
            requires_secure_escort=False,
            scheduled_utc="2026-06-16T10:00:00Z",
            actual_utc="2026-06-16T10:15:00Z",
            leg_kind="MEET_ARRIVAL",
            passenger_overrides={
                "full_name": "P BNA", "dob": "1990-01-01",
                "mobility_code": "WCHR", "airline_pnr": "BNA1",
            },
            request_overrides={"bill_to": "AIRLINE", "service_tier": "STANDARD",
                               "companion_count": 0},
            clock_at_submit="2026-06-16T09:00:00Z",
            dispatcher_user_id="disp_bna",
            confirmer_user_id="conf_bna",
        )
        # Within grace → final == provisional; WCHR carries no equipment fee
        # (PRD §3.2/§3.3) so both are the 6000 base at tier/posture 1.0
        assert out["leg"]["final_leg_cents"] == 6000
        assert out["leg"]["final_leg_cents"] == out["leg"]["provisional_leg_cents"]
