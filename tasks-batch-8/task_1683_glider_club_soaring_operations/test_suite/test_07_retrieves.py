"""Cross-country retrieves: banded cost split rounding order, the flight
back-reference, and terminal-state lockdown."""
from test_helpers import (
    ApiErrorId,
    assert_retrieve,
    get_flight,
    get_retrieve,
    make_duty_officer_headers,
    make_member_headers,
    setup_reconciled_flight,
    validate_error,
    validate_success,
)


def _setup_landed_out_flight(tier_code="PLAIN"):
    """A reconciled cross-country flight for the pilot (the landed-out launch
    a retrieve can be filed against)."""
    return setup_reconciled_flight(
        tier_overrides={
            "tier_code": tier_code,
            "monthly_dues_cents": 0,
            "tow_fee_discount_pct": 0.0,
            "included_tows_per_month": 0,
        },
        slot_start="2026-08-15T12:00:00Z", slot_end="2026-08-15T18:00:00Z",
        capacity=3,
        res_start="2026-08-15T12:30:00Z", res_end="2026-08-15T17:00:00Z",
        clock="2026-08-15T12:35:00Z",
        release_altitude_ft=2000,
        takeoff_at="2026-08-15T12:40:00Z",
        landed_at="2026-08-15T15:40:00Z",
    )


class TestRetrieveCostSplit:
    def test_retrieve_split_band_rounding_order(self, api):
        """PRD §3.6: "The total cost is a 5,000-cent base plus 120 cents per
        commenced kilometre — the distance rounded up to a whole kilometre
        before the per-kilometre rate applies."
        PRD §3.6: "The total is allocated across the bands in proportion to
        their kilometre widths, each band's allocation rounded half up to
        whole cents. The pilot pays the entire first band plus half of the
        second band — that half rounded half up — and nothing beyond the
        second band; the result is `pilot_share_cents`. The club absorbs the
        rest: `club_share_cents` is the total minus the pilot share, taken as
        the residual so the split always sums back to the total."

        Design: Difficulty/combinatorial_formula/retrieve_cost_split_rounding_order
        """
        ctx = _setup_landed_out_flight()
        resp = api.create_retrieve(
            {"flight_id": ctx["flight"]["id"], "distance_km": 75},
            make_member_headers(ctx["pilot"]["id"]),
        )
        retrieve = validate_success(resp, 201)
        assert_retrieve(retrieve)
        # Total 5000 + 75*120 = 14000; band1 round_half_up(14000*50/75) = 9333;
        # band2 round_half_up(14000*25/75) = 4667; pilot 9333 +
        # round_half_up(4667*0.5) = 9333 + 2334 = 11667; club residual 2333.
        assert retrieve["pilot_share_cents"] == 11667
        assert retrieve["club_share_cents"] == 2333
        assert retrieve["pilot_share_cents"] + retrieve["club_share_cents"] == 14000

    def test_retrieve_creation_sets_flight_back_reference(self, api):
        """PRD §3.6: "Creation computes the cost split and sets the flight's
        `retrieve_id` back-reference."

        Design: Difficulty/combinatorial_formula/retrieve_cost_split_rounding_order
        """
        ctx = _setup_landed_out_flight()
        resp = api.create_retrieve(
            {"flight_id": ctx["flight"]["id"], "distance_km": 75},
            make_member_headers(ctx["pilot"]["id"]),
        )
        retrieve = validate_success(resp, 201)
        flight = get_flight(ctx["flight"]["id"])
        assert flight["retrieve_id"] == retrieve["id"]


class TestRetrieveTerminalLockdown:
    def test_assign_crew_on_cancelled_retrieve_rejected(self, api):
        """PRD §3.6: "From `REQUESTED`, a `DutyOfficer` or `ClubAdmin` assigns
        a crew by naming a `crew_member_id`; the retrieve must still be
        `REQUESTED` (`ERR_RETRIEVE_NOT_REQUESTED`) and the crew member must be
        `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`)."
        PRD §3.6: "A retrieve that never launches may be cancelled from
        `REQUESTED`, ending `CANCELLED`."

        Design: Corner/state_machines/retrieve_terminal_cancel_lockdown
        """
        ctx = _setup_landed_out_flight("RT")
        officer = make_duty_officer_headers(ctx["tow_pilot"]["id"])
        resp = api.create_retrieve(
            {"flight_id": ctx["flight"]["id"], "distance_km": 40},
            make_member_headers(ctx["pilot"]["id"]),
        )
        retrieve = validate_success(resp, 201)
        resp = api.cancel_retrieve(retrieve["id"], officer)
        cancelled = validate_success(resp, 200)
        assert cancelled["status"] == "CANCELLED"

        resp = api.assign_crew(
            retrieve["id"], {"crew_member_id": ctx["tow_pilot"]["id"]}, officer
        )
        validate_error(resp, ApiErrorId.ERR_RETRIEVE_NOT_REQUESTED)
        after = get_retrieve(retrieve["id"])
        assert after["status"] == "CANCELLED"
        assert after["crew_member_id"] is None
