"""Difficulty queue A — combinatorial_formula instances."""
import pytest

from test_helpers import (
    get_success_data, validate_success,
    create_airport, create_terminal, create_segment, create_passenger,
    create_assist_request, create_leg, submit_request, set_clock,
    api_client, TEST_USERS,
)


ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
REQ = TEST_USERS["requester_headers"]
DISP = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Design: Difficulty/combinatorial_formula/tiered_provisional_charge_with_companion_equipment_ummr_senior_tsa
# ---------------------------------------------------------------------------

class TestTieredProvisionalChargeCombinatorial:
    def _setup(self):
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="SJC", meet_buffer_minutes=25)
        terminal = create_terminal(airport["id"], code="INTL", requires_secure_escort=True)
        segment = create_segment(
            airport["id"], terminal["id"], flight_no="BA287",
            direction="DEPARTURE", scheduled_utc="2026-07-01T14:00:00Z",
        )
        passenger = create_passenger(
            full_name="Kid U", dob="2018-01-01", mobility_code="WCHC",
            airline_pnr="KID001",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="CONCIERGE",
            companion_count=2, umnr_handoff_required=True,
        )
        leg = create_leg(request["id"], segment["id"],
                         leg_kind="DEPARTURE_ESCORT", pickup_zone="CURB-INTL")
        return airport, terminal, segment, passenger, request, leg

    def test_concierge_tier_with_companion_wchc_ummr_tsa_computes_24000(self, api):
        """PRD §3.3: "Begin with the per-leg base in cents, which is fixed by
        `leg_kind`: 6000 cents for `MEET_ARRIVAL`, 7500 cents for `DEPARTURE_ESCORT`,
        and 9500 cents for `CONNECTION_TRANSFER`. Add the applicable flat fees, each
        in cents: the companion fee is 1500 cents multiplied by the request's
        `companion_count`; the equipment fee is 1800 cents when the leg requires a
        WCHC-rated chair, otherwise 800 cents when the leg merely requires a
        wheelchair, otherwise zero; the UMNR fee is 2500 cents when
        `requires_ummr_agent` holds; the senior fee is 900 cents when
        `requires_senior_agent` holds; and the TSA escort fee is 1200 cents when
        `requires_tsa_escort` holds. Multiply the resulting sum by the tier
        multiplier — 10000 basis points for `STANDARD`, 12500 for `PRIORITY`, 15000
        for `CONCIERGE` — and divide by 10000. Multiply again by the posture
        multiplier snapshotted from the airport's current posture at compute time —
        10000 basis points for `NORMAL`, 12500 for `DEGRADED` — and divide by 10000."

        Design: Difficulty/combinatorial_formula/tiered_provisional_charge_with_companion_equipment_ummr_senior_tsa
        """
        airport, terminal, segment, passenger, request, leg = self._setup()
        submitted = submit_request(request["id"])
        leg_after = get_success_data(api_client.get_leg(leg["id"], REQ))
        # base 7500 + 2*1500 companion + 1800 WCHC + 2500 UMMR + 0 senior + 1200 TSA
        #   = 16000; tier 1.5 → 24000; posture 1.0 → 24000
        assert leg_after["provisional_leg_cents"] == 24000
        assert submitted["provisional_charge_cents"] == 24000

    def test_submit_sets_billing_status_provisional(self, api):
        """PRD §3.3: "Submission then sets `billing_status` to `PROVISIONAL` and
        creates a `PROVISIONAL` invoice whose `amount_cents` equals the request's
        `provisional_charge_cents`."

        Design: Difficulty/combinatorial_formula/tiered_provisional_charge_with_companion_equipment_ummr_senior_tsa
        """
        airport, terminal, segment, passenger, request, leg = self._setup()
        submitted = submit_request(request["id"])
        assert submitted["billing_status"] == "PROVISIONAL"
        # A PROVISIONAL invoice exists for the request
        invoices = get_success_data(api_client.list_request_invoices(
            request["id"], TEST_USERS["billing_clerk_headers"],
        ))
        prov = [i for i in invoices if i["invoice_kind"] == "PROVISIONAL"]
        assert len(prov) == 1
        assert prov[0]["amount_cents"] == 24000
        assert prov[0]["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Design: Difficulty/combinatorial_formula/per_leg_rounding_then_sum_vs_sum_then_round_divergence
# ---------------------------------------------------------------------------

class TestPerLegRoundingThenSum:
    def _setup_two_legs_degraded(self):
        set_clock("2026-06-15T10:00:00Z")
        airport = create_airport(iata_code="LAX", meet_buffer_minutes=15)
        terminal = create_terminal(airport["id"], code="T3", requires_secure_escort=False)
        seg1 = create_segment(
            airport["id"], terminal["id"], flight_no="AA1",
            direction="DEPARTURE", scheduled_utc="2026-07-02T10:00:00Z",
        )
        seg2 = create_segment(
            airport["id"], terminal["id"], flight_no="AA2",
            direction="DEPARTURE", scheduled_utc="2026-07-03T10:00:00Z",
        )
        passenger = create_passenger(
            full_name="Ad X", dob="1990-06-01", mobility_code="WCHR",
            airline_pnr="P1",
        )
        request = create_assist_request(
            passenger["id"], bill_to="AIRLINE", service_tier="PRIORITY",
            companion_count=1,
        )
        leg1 = create_leg(request["id"], seg1["id"],
                          leg_kind="DEPARTURE_ESCORT", pickup_zone="Z1")
        leg2 = create_leg(request["id"], seg2["id"],
                          leg_kind="DEPARTURE_ESCORT", pickup_zone="Z2")
        # Set posture DEGRADED before submit so both legs pick up 1.25 multiplier
        get_success_data(api_client.set_airport_posture(
            airport["id"], {"posture": "DEGRADED"}, OPS,
        ))
        return airport, request, leg1, leg2

    def test_per_leg_rounding_then_sum_produces_28126(self, api):
        """PRD §2.8: "The rounding happens **per leg**; the request-level total
        is then the plain sum of the already-rounded per-leg amounts and is never
        re-rounded at the sum level."

        Design: Difficulty/combinatorial_formula/per_leg_rounding_then_sum_vs_sum_then_round_divergence
        """
        airport, request, leg1, leg2 = self._setup_two_legs_degraded()
        submitted = submit_request(request["id"])
        leg1_after = get_success_data(api_client.get_leg(leg1["id"], REQ))
        leg2_after = get_success_data(api_client.get_leg(leg2["id"], REQ))
        # Per-leg: (7500 + 1500 companion) = 9000 — the WCHR passenger sets no
        # requires_wheelchair flag (PRD §3.2), so no equipment fee;
        # * 1.25 (PRIORITY) = 11250; * 1.25 (DEGRADED) = 14062.5 → 14063
        assert leg1_after["provisional_leg_cents"] == 14063
        assert leg2_after["provisional_leg_cents"] == 14063
        # Sum of rounded legs: 14063 + 14063 = 28126 (not 28125)
        assert submitted["provisional_charge_cents"] == 28126
        assert submitted["provisional_charge_cents"] != 28125

    def test_sum_is_not_re_rounded_at_request_level(self, api):
        """PRD §2.8: "never re-rounded at the sum level."

        Design: Difficulty/combinatorial_formula/per_leg_rounding_then_sum_vs_sum_then_round_divergence
        """
        airport, request, leg1, leg2 = self._setup_two_legs_degraded()
        submitted = submit_request(request["id"])
        # If the implementation rounded at the sum level (sum = 28125.0), it would
        # return 28125. Per-leg rounding yields 28126; assert exact equality.
        assert submitted["provisional_charge_cents"] == 28126, (
            "Expected per-leg rounding (28126); got sum-then-round value "
            f"{submitted['provisional_charge_cents']}"
        )
