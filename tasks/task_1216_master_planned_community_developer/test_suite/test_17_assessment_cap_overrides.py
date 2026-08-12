"""Corner coverage: statutory assessment cap override flows at
DECLARANT_CONTROL (approval alone suffices) and at PARITY (owner ratification
additionally required)."""
from test_helpers import (
    api_client,
    close_lots_with_owners,
    create_active_agreement,
    create_active_community,
    create_adopted_budget,
    create_and_schedule_notice,
    create_effective_rate,
    create_offered_lot,
    create_open_phase,
    create_builder,
    create_proposed_budget,
    create_residents,
    list_community_seats,
    fill_seat_by_election,
    set_clock,
    get_success_data,
    validate_error,
    make_owner_director_headers,
    ApiErrorId,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]
LIFESTYLE = TEST_USERS["lifestyle_coordinator_headers"]

FY27_LINES = [
    ("LANDSCAPE_MAINTENANCE", 12000000),
    ("AMENITY_OPERATIONS", 6000000),
    ("MANAGEMENT", 2000000),
    ("RESERVE_CONTRIBUTION", 2000000, True),
]


class TestAssessmentCapOverrideDeclarantControl:
    """FY2027 rate EFFECTIVE at 200,000c; FY2028 budget gap 24,100,000c over
    100 units -> 241,000c per unit, increase 20.50% > 20.00 cap."""

    FY28_LINES = [
        ("LANDSCAPE_MAINTENANCE", 12000000),
        ("AMENITY_OPERATIONS", 6000000),
        ("MANAGEMENT", 3000000),
        ("RESERVE_CONTRIBUTION", 4000000, True),
        ("EVENTS_PROGRAMMING", 1100000),
    ]

    def _setup(self):
        community = create_active_community("Cap Canyon", 100)
        rate27, _ = create_effective_rate(
            community["id"], 2027, FY27_LINES, non_assessment_income_cents=2000000
        )
        assert rate27["per_unit_annual_cents"] == 200000
        budget28 = create_adopted_budget(
            community["id"], 2028, self.FY28_LINES,
            non_assessment_income_cents=2000000,
            notice_send_at="2027-01-05T00:00:00Z", adopt_at="2027-01-20T00:00:00Z",
        )
        rate28 = get_success_data(
            api_client.create_assessment_rate(
                {"community_id": community["id"], "budget_id": budget28["id"],
                 "fiscal_year": 2028},
                CTRL,
            )
        )
        # Notice SENT 2027-11-01, comfortably ahead of the 2027-12-02 deadline.
        create_and_schedule_notice(
            community["id"], "ASSESSMENT_CHANGE", "2027-11-01T00:00:00Z",
            assessment_rate_id=rate28["id"], subject="r28", body="rate",
            effective_date="2028-01-01T00:00:00Z",
        )
        set_clock("2027-11-02T00:00:00Z")
        return community, rate28

    def test_cap_breach_requires_override_at_declarant_control(self):
        """PRD §3.5: "The cap applies only when `increase_pct` is non-null: an increase of 20.00 percent or less passes without ceremony — the boundary is inclusive — while anything above requires `cap_override_approved_by` to be set, and when `transition_stage` is `PARITY` or `OWNER_MAJORITY` it additionally requires `cap_override_ratified_by`; arming without the required override fails with `ERR_ASSESSMENT_CAP_EXCEEDED`."
        PRD §3.5: "The override is approved through the approve-cap-override action — by an `AssociationDirector` before turnover or an `OwnerDirector` after — which stamps `cap_override_approved_by`, and ratified through the ratify-cap-override action by an `OwnerDirector`, which stamps `cap_override_ratified_by` and must be a different user than the approver.".

        Design: Corner/calculations/assessment_cap_override_declarant_control
        """
        _, rate28 = self._setup()
        assert rate28["per_unit_annual_cents"] == 241000
        assert float(rate28["increase_pct"]) == 20.50

        resp = api_client.arm_rate(rate28["id"], CTRL)
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_CAP_EXCEEDED)

        approved = get_success_data(api_client.approve_cap_override(rate28["id"], DIRECTOR))
        assert approved["cap_override_approved_by"] is not None

        # DECLARANT_CONTROL: no owner ratification is required.
        armed = get_success_data(api_client.arm_rate(rate28["id"], CTRL))
        assert armed["status"] == "ARMED"

        set_clock("2028-01-01T00:00:00Z")
        effective = get_success_data(api_client.get_assessment_rate(rate28["id"], CTRL))
        assert effective["status"] == "EFFECTIVE", (
            "the sweep flips ARMED to EFFECTIVE at fiscal-year start"
        )


class TestAssessmentCapOverrideRequiresRatifyAtParity:
    """4-unit community at PARITY (2 closings); FY2027 rate EFFECTIVE at
    200,000c; FY2028 budget gap 1,000,000c over 4 units -> 250,000c per unit,
    increase 25.00%."""

    def _setup(self):
        community = create_active_community("Parity Pines", 4)
        rate27, _ = create_effective_rate(
            community["id"], 2027, [("MANAGEMENT", 800000)],
        )
        assert rate27["per_unit_annual_cents"] == 200000

        # Sales side: 2 closings -> 50.00 pct -> PARITY.
        phase = create_open_phase(community["id"], "P1", 1, 4)
        builder = create_builder(community["id"], "Parity Builders", "A")
        agreement, _ = create_active_agreement(
            community["id"], builder["id"], phase["id"], 2,
            [("2027-06-30T00:00:00Z", 2)], earnest_money_cents=1000000,
        )
        lot1 = create_offered_lot(phase["id"], "P1")
        lot2 = create_offered_lot(phase["id"], "P2")
        r1, r2 = create_residents(
            community["id"], [("P One", "p1@x.com"), ("P Two", "p2@x.com")]
        )
        set_clock("2027-06-01T00:00:00Z")
        close_lots_with_owners(
            agreement["id"], [lot1["id"], lot2["id"]], [r1["id"], r2["id"]]
        )
        # Elect r1 to the vacant seat 5 (quorum 1 of 2 eligible voters).
        seats = list_community_seats(community["id"])
        seat5 = seats[4]
        assert seat5["status"] == "VACANT"
        fill_seat_by_election(seat5["id"], r1["id"], votes_cast=1, votes_for=1)

        # FY2028 budget: at PARITY the adopt lands PENDING_RATIFICATION, and
        # the OwnerDirector (not the adopter) ratifies.
        budget28 = create_proposed_budget(community["id"], 2028, [("MANAGEMENT", 1000000)])
        create_and_schedule_notice(
            community["id"], "BUDGET_ADOPTION", "2027-06-02T00:00:00Z",
            budget_id=budget28["id"], subject="b28", body="adopt",
        )
        set_clock("2027-06-02T00:00:00Z")
        set_clock("2027-06-17T00:00:00Z")
        adopted = get_success_data(api_client.adopt_budget(budget28["id"], DIRECTOR))
        assert adopted["status"] == "PENDING_RATIFICATION", (
            f"at PARITY the adopt lands PENDING_RATIFICATION, got {adopted['status']}"
        )
        ratified = get_success_data(
            api_client.ratify_budget(budget28["id"], make_owner_director_headers(r1["id"]))
        )
        assert ratified["status"] == "ADOPTED"

        rate28 = get_success_data(
            api_client.create_assessment_rate(
                {"community_id": community["id"], "budget_id": budget28["id"],
                 "fiscal_year": 2028},
                CTRL,
            )
        )
        create_and_schedule_notice(
            community["id"], "ASSESSMENT_CHANGE", "2027-11-01T00:00:00Z",
            assessment_rate_id=rate28["id"], subject="r28", body="rate",
            effective_date="2028-01-01T00:00:00Z",
        )
        set_clock("2027-11-02T00:00:00Z")
        return community, rate28, r1

    def test_director_override_not_sufficient_at_parity(self):
        """PRD §3.5: "The cap applies only when `increase_pct` is non-null: an increase of 20.00 percent or less passes without ceremony — the boundary is inclusive — while anything above requires `cap_override_approved_by` to be set, and when `transition_stage` is `PARITY` or `OWNER_MAJORITY` it additionally requires `cap_override_ratified_by`; arming without the required override fails with `ERR_ASSESSMENT_CAP_EXCEEDED`."
        PRD §3.5: "The override is approved through the approve-cap-override action — by an `AssociationDirector` before turnover or an `OwnerDirector` after — which stamps `cap_override_approved_by`, and ratified through the ratify-cap-override action by an `OwnerDirector`, which stamps `cap_override_ratified_by` and must be a different user than the approver."

        Design: Corner/calculations/assessment_cap_override_requires_ratify_at_parity
        """
        _, rate28, r1 = self._setup()
        assert rate28["per_unit_annual_cents"] == 250000, (
            f"gap 1,000,000 / 4 units = 250000, got {rate28['per_unit_annual_cents']}"
        )
        assert float(rate28["increase_pct"]) == 25.00

        resp1 = api_client.arm_rate(rate28["id"], CTRL)
        validate_error(resp1, ApiErrorId.ERR_ASSESSMENT_CAP_EXCEEDED)

        get_success_data(api_client.approve_cap_override(rate28["id"], DIRECTOR))
        resp2 = api_client.arm_rate(rate28["id"], CTRL)
        validate_error(resp2, ApiErrorId.ERR_ASSESSMENT_CAP_EXCEEDED)

        get_success_data(
            api_client.ratify_cap_override(rate28["id"], make_owner_director_headers(r1["id"]))
        )
        armed = get_success_data(api_client.arm_rate(rate28["id"], CTRL))
        assert armed["status"] == "ARMED"
