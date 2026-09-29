"""Two figures over one row: the capacity pair and the budget pair."""
import math

from test_helpers import (
    TEST_USERS,
    assert_ride_capacity_variants,
    assert_ride_system,
    open_project,
    open_review,
    open_ve_review,
    propose_ve_item,
    raise_finding,
    read_budget_position,
    read_ledger,
    register_ride_system,
    setup_program_with_approved_package,
    validate_success,
)

OWNER = TEST_USERS["owner_rep_headers"]
ENGINEER = TEST_USERS["ride_engineer_headers"]


class TestRideSystemCapacityVariants:
    """One ride system row carries a theoretical figure and a derated one."""

    def test_one_row_reports_theoretical_1440_and_operational_1179(self, api):
        """Third, the **theoretical design capacity** variant, `theoretical_hourly_capacity_guests`, is the number of dispatches that fit in an hour — 3,600 seconds divided by `dispatch_interval_seconds`, rounded down to a whole dispatch — multiplied by `riders_per_vehicle`; this variant stops here, with no derate of any kind, and it is the figure quoted in the vendor design submittal.

        Second, `dispatch_interval_seconds` is the `cycle_time_seconds` divided by
        that in-service vehicle count and rounded up to a whole second, but never
        below the control system's twenty-second minimum dispatch interval —
        whichever of the two is larger wins.

        Twelve vehicles against fourteen block zones leaves twelve in service, so
        the dispatch interval is the twenty-second minimum, the theoretical figure
        is 1440 guests per hour, and the derate of 0.819 carries the operational
        figure to 1179 — a gap of 261 guests per hour on one row.

        Design: Difficulty/dual_variant_calc/ride_capacity_theoretical_and_operational_diverge_on_one_row
        """
        project = open_project(name="Skyward Saga", design_day_attendance=8000,
                               peak_hour_share=0.10, budget_ceiling_cents=3600000000)
        ride = register_ride_system(project["id"])

        row = validate_success(api.get_ride_system(ride["id"], ENGINEER))

        assert_ride_system(row)
        assert_ride_capacity_variants(row, dispatch=20, theoretical=1440, operational=1179)
        assert row["theoretical_hourly_capacity_guests"] - row["operational_hourly_capacity_guests"] == 261
        assert row["status"] == "CANDIDATE"

    def test_capacity_yardstick_stands_beside_both_variants(self, api):
        """`required_hourly_capacity_guests` is the product of `design_day_attendance` and `peak_hour_share`, computed as an exact decimal and then rounded up to a whole number of guests.

        The derated variant is the only one any gate consults.

        The programme's own yardstick is 800 guests per hour, and the candidate is
        reported twice against it: the theoretical figure is exactly the whole
        dispatches of an hour multiplied by the riders each vehicle carries, with
        no derate of any kind, while the derated figure sits strictly below it.

        Design: Difficulty/dual_variant_calc/ride_capacity_theoretical_and_operational_diverge_on_one_row
        """
        project = open_project(design_day_attendance=8000, peak_hour_share=0.10)
        ride = register_ride_system(project["id"])

        row = validate_success(api.get_ride_system(ride["id"], ENGINEER))
        programme = validate_success(api.get_project(project["id"], OWNER))

        assert programme["required_hourly_capacity_guests"] == 800
        whole_dispatch_capacity = (
            math.floor(3600 / row["dispatch_interval_seconds"]) * row["riders_per_vehicle"]
        )
        assert row["theoretical_hourly_capacity_guests"] == whole_dispatch_capacity
        assert row["operational_hourly_capacity_guests"] < row["theoretical_hourly_capacity_guests"]
        assert row["operational_hourly_capacity_guests"] >= programme["required_hourly_capacity_guests"]


class TestBudgetCommittedAndForecastVariants:
    """One ledger, one instant, two deliberately different totals."""

    def _programme_with_in_flight_saving_and_open_finding(self):
        ctx = setup_program_with_approved_package()
        review = open_review(ctx["package"]["id"])
        ctx["finding"] = raise_finding(
            review["id"], severity="MAJOR",
            description="Evacuation walkway handrail height below standard on lift hill",
            remediation_cost_estimate_cents=12000000,
        )
        item = propose_ve_item(ctx["project"]["id"])
        ctx["ve_item"] = open_ve_review(item["id"])
        return ctx

    def test_forecast_subtracts_in_flight_saving_and_adds_open_remediation(self):
        """`forecast_cost_cents` is therefore `committed_cost_cents` less the in-flight savings plus the open remediation, so the same ledger yields two different numbers.

        In-flight value-engineering savings are the sum of `net_saving_cents` over
        the programme's value-engineering items whose `status` is `UNDER_REVIEW` —
        items still `PROPOSED`, or already `ADOPTED` or `REJECTED`, are excluded —
        and this sum is *subtracted*.

        Open safety remediation is the sum of `remediation_cost_estimate_cents`
        over every finding whose review belongs to a design package of this
        programme and whose `status` is `OPEN` or `RESOLVED` — `CLOSED` and
        `WAIVED` findings are excluded — and this sum is *added*.

        The single approved package committed 3080000000 cents. The under-review
        item retains 87500005 of its 350000021 gross saving and nets 83500005
        after its implementation cost, and the open major finding carries a
        12000000 remediation estimate, so the forecast reads 3008499995.

        Design: Difficulty/dual_variant_calc/budget_committed_and_forecast_diverge_with_in_flight_ve_and_open_finding
        """
        ctx = self._programme_with_in_flight_saving_and_open_finding()

        budget = read_budget_position(ctx["project"]["id"])

        assert ctx["ve_item"]["net_saving_cents"] == 83500005
        assert ctx["ve_item"]["status"] == "UNDER_REVIEW"
        assert budget["committed_cost_cents"] == 3080000000
        assert budget["forecast_cost_cents"] == 3008499995
        assert budget["committed_cost_cents"] - budget["forecast_cost_cents"] == 71500005

    def test_committed_basis_replays_the_ledger_while_adopted_savings_stay_zero(self):
        """The **committed basis** is a chronological replay: starting from zero, the server walks every ledger entry of the programme ordered by `created_at` ascending and then by `sequence_no` ascending, adding each entry's `amount_cents` to a running total, and the final total is `committed_cost_cents`.

        Across the programme, `ve_program_net_savings_cents` is the sum of
        `net_saving_cents` over items whose `status` is `ADOPTED`, and that sum is
        never re-rounded.

        Alongside them, `headroom_cents` is `budget_ceiling_cents` less
        `committed_cost_cents`, and `restricted_utilisation_cents` is
        `budget_ceiling_cents` multiplied by ninety percent, rounded down to whole
        cents — the threshold that separates `OPEN` from `RESTRICTED` per §2.7.

        Otherwise, if `open_major_finding_count` is greater than zero, or
        `committed_cost_cents` is strictly greater than
        `restricted_utilisation_cents`, the posture is `RESTRICTED`.

        The committed figure cannot see the in-flight saving at all: it is the
        replay of the one commitment entry, the adopted roll-up is still zero, and
        the posture is RESTRICTED on the open major finding alone even though
        3080000000 sits below the 3240000000 threshold.

        Design: Difficulty/dual_variant_calc/budget_committed_and_forecast_diverge_with_in_flight_ve_and_open_finding
        """
        ctx = self._programme_with_in_flight_saving_and_open_finding()

        budget = read_budget_position(ctx["project"]["id"])
        rows, _meta = read_ledger(ctx["project"]["id"])

        assert budget["committed_cost_cents"] == sum(row["amount_cents"] for row in rows)
        assert budget["budget_ceiling_cents"] == 3600000000
        assert budget["headroom_cents"] == 520000000
        assert budget["restricted_utilisation_cents"] == 3240000000
        assert budget["readiness_posture"] == "RESTRICTED"
        assert budget["ve_program_net_savings_cents"] == 0
